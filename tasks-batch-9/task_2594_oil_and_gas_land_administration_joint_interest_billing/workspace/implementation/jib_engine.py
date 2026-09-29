"""Statement issuance: reallocation, per-owner shares and bucket rounding
(PRD 3.6)."""
from calc import (PAYMENT_TERMS_DAYS, add_billed, db, recompute_statement_totals,
                  statement_line_items, well_interests, well_statements)
from common import ZERO6, add_days, dec, now_ts, q6, rhu, touch
from store import insert, order_key


def owner_order(interests):
    """working_interest_pct DESC, ties by position created_at ASC."""
    return sorted(interests,
                  key=lambda i: (-i["working_interest_pct"], order_key(i)))


def create_draft_statement(well_id, statement_number, period_start, period_end,
                          cost_basis, activity_class, overhead_rate_class,
                          prepared_by_user_id, superseded_statement_id=None):
    statement = insert("statements", {
        "well_id": well_id,
        "superseded_statement_id": superseded_statement_id,
        "statement_number": statement_number,
        "billing_period_start": period_start,
        "billing_period_end": period_end,
        "cost_basis": cost_basis,
        "activity_class": activity_class,
        "overhead_rate_class": overhead_rate_class,
        "capital_direct_cents": 0,
        "operating_direct_cents": 0,
        "direct_cost_cents": 0,
        "billable_months": 0,
        "overhead_cents": 0,
        "total_billed_cents": 0,
        "prepared_by_user_id": prepared_by_user_id,
        "issued_at": None,
        "payment_due_date": None,
        "statement_status": "DRAFT",
    })
    recompute_statement_totals(statement)
    return statement


def revision_number(well_id, original_number):
    existing = [s for s in well_statements(well_id)
                if s.get("superseded_statement_id") is not None]
    return "%s-R%d" % (original_number, len(existing) + 1)


def issue_statement(statement):
    well = db.wells[statement["well_id"]]
    pool = recompute_statement_totals(statement)

    capital_direct = statement["capital_direct_cents"]
    operating_direct = statement["operating_direct_cents"]
    direct_cost = statement["direct_cost_cents"]
    overhead_total = statement["overhead_cents"]

    owners = owner_order(well_interests(well["id"], "ACTIVE"))

    # --- AFE capital under partially consented AFEs, ascending AFE created_at
    afe_ids = []
    for entry in pool:
        if entry["cost_class"] != "CAPITAL" or entry.get("afe_id") is None:
            continue
        afe = db.afes.get(entry["afe_id"])
        if afe is None or afe["afe_status"] != "PARTIALLY_CONSENTED":
            continue
        if afe["id"] not in afe_ids:
            afe_ids.append(afe["id"])
    afe_list = sorted([db.afes[i] for i in afe_ids], key=order_key)
    afe_capital = {}
    for afe in afe_list:
        afe_capital[afe["id"]] = sum(
            e["amount_cents"] for e in pool
            if e["cost_class"] == "CAPITAL" and e.get("afe_id") == afe["id"])
    afe_capital_total = sum(afe_capital.values())
    non_afe_capital = capital_direct - afe_capital_total

    # --- consent-normalized weights
    denominator = well["consent_working_interest_pct"]
    consenting = [o for o in owners if not o["non_consent_flag"]]
    normalized = {}
    for position in owners:
        if position["non_consent_flag"] or denominator == 0:
            normalized[position["id"]] = ZERO6
        else:
            normalized[position["id"]] = q6(dec(position["working_interest_pct"])
                                            / dec(denominator))
    if consenting:
        residual = dec("1.000000") - sum(normalized.values(), dec(0))
        if residual != 0:
            target = consenting[0]
            normalized[target["id"]] = q6(normalized[target["id"]] + residual)

    # --- unrounded raw shares
    raw_operating = {}
    raw_capital = {}
    raw_overhead = {}
    for position in owners:
        wi = dec(position["working_interest_pct"])
        raw_operating[position["id"]] = dec(operating_direct) * wi
        afe_share = dec(0)
        for afe in afe_list:
            afe_share += dec(afe_capital[afe["id"]]) * dec(normalized[position["id"]])
        raw_capital[position["id"]] = dec(non_afe_capital) * wi + afe_share
    for position in owners:
        if direct_cost == 0:
            raw_overhead[position["id"]] = dec(0)
        else:
            raw_overhead[position["id"]] = (
                dec(overhead_total)
                * (raw_capital[position["id"]] + raw_operating[position["id"]])
                / dec(direct_cost))

    # --- reporting figures, each rounded independently, per AFE
    withheld = dict((p["id"], 0) for p in owners)
    reallocated = dict((p["id"], 0) for p in owners)
    penalty = dict((p["id"], 0) for p in owners)
    residuals = dict((p["id"], 0) for p in owners)
    for afe in afe_list:
        amount = dec(afe_capital[afe["id"]])
        for position in owners:
            wi = dec(position["working_interest_pct"])
            if position["non_consent_flag"]:
                own = rhu(amount * wi)
                withheld[position["id"]] += own
                if afe["cost_class"] == "CAPITAL":
                    penalty[position["id"]] += rhu(
                        dec(afe["non_consent_penalty_multiple"]) * dec(own))
            else:
                reallocated[position["id"]] += rhu(
                    amount * dec(normalized[position["id"]]) - amount * wi)

    # --- bucket rounding in the fixed order b1, b2, b3
    def distribute(bucket_total, raws, capital_bucket=False):
        cents = dict((p["id"], rhu(raws[p["id"]])) for p in owners)
        if not owners:
            return cents
        residual = bucket_total - sum(cents.values())
        target = owners[0]
        if capital_bucket and normalized[target["id"]] == ZERO6 and consenting:
            target = consenting[0]
        cents[target["id"]] += residual
        residuals[target["id"]] += residual
        return cents

    bucket_capital = distribute(capital_direct, raw_capital, capital_bucket=True)
    bucket_operating = distribute(operating_direct, raw_operating)
    bucket_overhead = distribute(overhead_total, raw_overhead)

    for position in owners:
        key = position["id"]
        total = (bucket_capital[key] + bucket_operating[key] + bucket_overhead[key])
        insert("line_items", {
            "_versioned": False,
            "statement_id": statement["id"],
            "owner_id": position["owner_id"],
            "wi_pct_snapshot": position["working_interest_pct"],
            "consent_normalized_wi_pct": normalized[key],
            "direct_capital_cents": bucket_capital[key],
            "direct_operating_cents": bucket_operating[key],
            "overhead_cents": bucket_overhead[key],
            "non_consent_reallocated_cents": reallocated[key],
            "non_consent_withheld_cents": withheld[key],
            "penalty_accrued_cents": penalty[key],
            "rounding_residual_cents": residuals[key],
            "total_billed_cents": total,
        })

    issued_at = now_ts()
    statement["issued_at"] = issued_at
    statement["payment_due_date"] = add_days(issued_at.date(), PAYMENT_TERMS_DAYS)
    statement["statement_status"] = "ISSUED"
    touch(statement)

    add_billed(well, statement["total_billed_cents"])

    for position in owners:
        key = position["id"]
        if position["non_consent_flag"] and (withheld[key] or penalty[key]):
            position["non_consent_recoverable_balance_cents"] = (
                position["non_consent_recoverable_balance_cents"]
                + withheld[key] + penalty[key])
            touch(position)
    return statement
