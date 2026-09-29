"""Commission statement earnings components and run roll-ups (PRD section 3.5)."""

from common import clock_str, new_row, rhu, touch
from db import db
from services import planlib
from services.genealogy import by_created, descendants_with_level, path_between
from services.qual import row_for, rows_of_period


def statements_of_run(run_id):
    return by_created([s for s in db.statements.values() if s["commission_run_id"] == run_id])


def active_statements(run_id):
    return [s for s in statements_of_run(run_id) if s["status"] == "ACTIVE"]


def orders_of(consultant_id):
    return by_created([o for o in db.orders.values() if o["consultant_id"] == consultant_id])


# --------------------------------------------------------------------------
# Retail profit
# --------------------------------------------------------------------------

def retail_profit_cents(consultant_id, period_code):
    total = 0
    for order in orders_of(consultant_id):
        if order["posted_period_code"] != period_code:
            continue
        if order["order_type"] != "RETAIL_CUSTOMER":
            continue
        if order["payment_status"] not in ("PAID", "REFUNDED_PARTIAL"):
            continue
        for line in order["lines"]:
            margin = int(line["unit_srp_cents"]) - int(line["unit_wholesale_price_cents"])
            units = int(line["quantity"]) - int(line["returned_quantity"])
            total += margin * units
    return total


# --------------------------------------------------------------------------
# Personal volume bonus
# --------------------------------------------------------------------------

def pv_bonus_cents(plan, consultant, row):
    volume = int(row["net_personal_volume_points"])
    if volume < int(plan["pv_bonus_min_points"]):
        return 0

    point_value = int(plan["point_value_cents"])

    # Step one: marginal bands, rounded half up per band.
    base = 0
    lower = 0
    for band in plan["pv_bonus_bands"]:
        upper = band["upper_points"]
        ceiling = volume if upper is None else int(upper)
        band_points = max(0, min(volume, ceiling) - lower)
        base += rhu(band_points * point_value * int(band["rate_bp"]), 10000)
        lower = ceiling
        if lower >= volume:
            break

    # Step two: senior rank bump on the whole volume.
    bump = 0
    paid_as = row.get("paid_as_rank_code")
    if paid_as is not None:
        rung = planlib.rung_by_code(plan, paid_as)
        if rung is not None and int(rung["rank_order"]) >= 2:
            bump = rhu(volume * point_value * int(plan["senior_rank_bump_bp"]), 10000)

    # Step three: cap after the bump.
    capped = min(int(plan["pv_bonus_cap_cents"]), base + bump)

    # Step four: probation haircut after the cap.
    if consultant is not None and consultant.get("status") == "PROBATION":
        return rhu(capped * int(plan["probation_keep_bp"]), 10000)
    return capped


# --------------------------------------------------------------------------
# Multi-level overrides
# --------------------------------------------------------------------------

def _payline_qualified(plan, period_id, consultant):
    if consultant is None or consultant.get("status") == "TERMINATED":
        return False
    row = row_for(period_id, consultant["id"])
    if row is None:
        return False
    return int(row["net_personal_volume_points"]) >= int(plan["payline_min_pv_points"])


def _node_amount(plan, period_id, consultant_id, level, rates):
    row = row_for(period_id, consultant_id)
    volume = int(row["net_personal_volume_points"]) if row is not None else 0
    rate_bp = int(rates[level - 1])
    return volume, rhu(volume * int(plan["point_value_cents"]) * rate_bp, 10000)


def overrides(plan, period, earner_consultant, earner_row, compression_mode):
    """Returns (override_total_cents, override_breakdown, forfeited_cents)."""
    paid_as = earner_row.get("paid_as_rank_code")
    if paid_as is None:
        return 0, [], 0
    rung = planlib.rung_by_code(plan, paid_as)
    if rung is None:
        return 0, [], 0
    levels = int(rung["override_levels"])
    rates = list(rung["override_bp_by_level"] or [])
    if levels == 0 or not rates:
        return 0, [], 0

    period_id = period["id"]
    entries = []
    forfeited = 0

    for node, gen_level in descendants_with_level(earner_consultant["id"]):
        qualified = _payline_qualified(plan, period_id, node)
        if compression_mode == "STATIC":
            if qualified:
                paid_level = gen_level
                if 1 <= paid_level <= levels:
                    volume, amount = _node_amount(plan, period_id, node["id"], paid_level, rates)
                    entries.append(
                        {
                            "source_consultant_id": node["id"],
                            "paid_level": paid_level,
                            "volume_points": volume,
                            "amount_cents": amount,
                            "_created_at": node["created_at"],
                            "_seq": node["_seq"],
                        }
                    )
            else:
                if 1 <= gen_level <= levels:
                    _volume, amount = _node_amount(plan, period_id, node["id"], gen_level, rates)
                    forfeited += amount
        else:  # DYNAMIC
            if not qualified:
                continue
            between = path_between(earner_consultant["id"], node)
            skipped = 0
            for mid_id in between:
                if not _payline_qualified(plan, period_id, db.consultants.get(mid_id)):
                    skipped += 1
            paid_level = gen_level - skipped
            if 1 <= paid_level <= levels:
                volume, amount = _node_amount(plan, period_id, node["id"], paid_level, rates)
                entries.append(
                    {
                        "source_consultant_id": node["id"],
                        "paid_level": paid_level,
                        "volume_points": volume,
                        "amount_cents": amount,
                        "_created_at": node["created_at"],
                        "_seq": node["_seq"],
                    }
                )

    entries.sort(key=lambda e: (e["paid_level"], e["_created_at"], e["_seq"]))
    breakdown = [
        {
            "source_consultant_id": e["source_consultant_id"],
            "paid_level": e["paid_level"],
            "volume_points": e["volume_points"],
            "amount_cents": e["amount_cents"],
        }
        for e in entries
    ]
    total = sum(e["amount_cents"] for e in breakdown)
    return total, breakdown, forfeited


# --------------------------------------------------------------------------
# Withholding
# --------------------------------------------------------------------------

def withholding(plan, consultant, gross):
    if gross > int(plan["withhold_tier_threshold_cents"]):
        rate_bp = int(plan["withhold_high_bp"])
    else:
        rate_bp = int(plan["withhold_low_bp"])
    tier = rhu(gross * rate_bp, 10000)
    balance = int(consultant["clawback_balance_cents"]) if consultant else 0
    withheld = min(tier, balance)
    if withheld < 0:
        withheld = 0
    return rate_bp, withheld


# --------------------------------------------------------------------------
# Run calculation
# --------------------------------------------------------------------------

def refresh_run_totals(run):
    actives = active_statements(run["id"])
    run["gross_total_cents"] = sum(int(s["gross_commission_cents"]) for s in actives)
    run["withheld_total_cents"] = sum(int(s["withholding_cents"]) for s in actives)
    run["net_payable_total_cents"] = sum(int(s["net_payable_cents"]) for s in actives)
    run["statement_count"] = len(actives)
    run["distributable_pool_cents"] = int(run["gross_total_cents"]) + int(
        run["forfeited_to_company_cents"]
    )


def calculate_run(run, period, plan, user_id):
    # Supersede the previous generation.
    for statement in active_statements(run["id"]):
        statement["status"] = "SUPERSEDED"
        statement["payout_status"] = "PENDING"
        touch(statement)

    compression_mode = plan["compression_mode"]
    sequence = int(run["calculation_sequence"])
    forfeited_total = 0

    for row in rows_of_period(period["id"]):
        consultant = db.consultants.get(row["consultant_id"])
        if consultant is None or consultant["status"] == "TERMINATED":
            continue

        retail = retail_profit_cents(consultant["id"], run["period_code"])
        bonus = pv_bonus_cents(plan, consultant, row)
        override_total, breakdown, forfeited = overrides(
            plan, period, consultant, row, compression_mode
        )
        forfeited_total += forfeited

        gross = retail + bonus + override_total
        rate_bp, withheld = withholding(plan, consultant, gross)

        statement = new_row()
        statement.update(
            {
                "commission_run_id": run["id"],
                "consultant_id": consultant["id"],
                "period_code": run["period_code"],
                "calculation_sequence": sequence,
                "paid_as_rank_code": row.get("paid_as_rank_code"),
                "net_personal_volume_points": int(row["net_personal_volume_points"]),
                "retail_profit_cents": retail,
                "pv_bonus_cents": bonus,
                "override_total_cents": override_total,
                "override_breakdown": breakdown,
                "gross_commission_cents": gross,
                "withhold_rate_bp": rate_bp,
                "withholding_cents": withheld,
                "net_payable_cents": gross - withheld,
                "paid_cents": 0,
                "carry_forward_cents": 0,
                "payout_status": "PENDING",
                "status": "ACTIVE",
            }
        )
        db.statements[statement["id"]] = statement

    run["compression_mode_snapshot"] = compression_mode
    run["calculation_sequence"] = sequence + 1
    run["calculated_by_user_id"] = user_id
    run["forfeited_to_company_cents"] = forfeited_total
    refresh_run_totals(run)
    run["status"] = "CALCULATED"
    touch(run)


def statement_for(run_id, consultant_id, statuses=("ACTIVE",)):
    matches = [
        s
        for s in statements_of_run(run_id)
        if s["consultant_id"] == consultant_id and s["status"] in statuses
    ]
    return matches[-1] if matches else None
