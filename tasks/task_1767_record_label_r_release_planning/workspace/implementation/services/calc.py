"""Calculation rules: scouting score, effective rate, budget posture,
tiered royalty statement computation, recoupment waterfall, net payable."""

from decimal import Decimal, ROUND_HALF_UP

from db import db


def round_half_up_cents(value):
    """Round a Decimal to whole cents, half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_scouting_score(label, genre, monthly_streams, social_followers,
                           engagement_rate, live_draw_avg):
    """Weighted scouting score, 1 decimal, round half up, clamped [0,100]."""
    def norm(x, cap):
        return min(Decimal(x) / Decimal(cap), Decimal(1))

    raw = Decimal(100) * (
        Decimal("0.30") * norm(monthly_streams, 1000000)
        + Decimal("0.20") * norm(social_followers, 2000000)
        + Decimal("0.25") * Decimal(str(engagement_rate))
        + Decimal("0.25") * norm(live_draw_avg, 2000)
    )
    mult = Decimal(str(label["genre_multipliers"].get(genre, 1.0)))
    score = (raw * mult).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if score < 0:
        score = Decimal("0.0")
    if score > 100:
        score = Decimal("100.0")
    return float(score)


def effective_base_rate_bps(contract):
    return min(
        contract["base_royalty_rate_bps"]
        + contract["options_exercised"] * contract["option_escalation_bps"],
        3000,
    )


def recompute_budget_posture(project):
    total = project["spent_cents"] + project["committed_cents"]
    # AT_RISK when spent+committed >= 85% of budget (inclusive).
    if total * 100 >= 85 * project["budget_cents"]:
        project["budget_posture"] = "AT_RISK"
    else:
        project["budget_posture"] = "WITHIN_BUDGET"


def recompute_account_totals(account):
    account["total_unrecouped_cents"] = (
        account["recording_balance_cents"]
        + account["advance_balance_cents"]
        + account["tour_support_balance_cents"]
        + account["promo_balance_cents"]
    )


def waterfall_total(account, scope, royalty_earned_cents):
    """Projected/applied recoupment total (no mutation)."""
    if scope == "CROSS_COLLATERALIZED":
        buckets = [
            "recording_balance_cents", "advance_balance_cents",
            "tour_support_balance_cents", "promo_balance_cents",
        ]
    else:  # MASTER_ONLY
        buckets = ["recording_balance_cents", "advance_balance_cents"]
    available = sum(account[b] for b in buckets)
    distributable = min(royalty_earned_cents, available)
    remaining = distributable
    applied = 0
    for b in buckets:
        take = min(account[b], remaining)
        applied += take
        remaining -= take
    return applied


def waterfall_apply(account, scope, royalty_earned_cents):
    """Apply the waterfall, mutating bucket balances. Returns applied total."""
    if scope == "CROSS_COLLATERALIZED":
        buckets = [
            "recording_balance_cents", "advance_balance_cents",
            "tour_support_balance_cents", "promo_balance_cents",
        ]
    else:
        buckets = ["recording_balance_cents", "advance_balance_cents"]
    available = sum(account[b] for b in buckets)
    remaining = min(royalty_earned_cents, available)
    applied = 0
    for b in buckets:
        take = min(account[b], remaining)
        account[b] -= take
        applied += take
        remaining -= take
    recompute_account_totals(account)
    return applied


def compute_net_payable(statement, reserve_rate_bps):
    """Net payable under the statement's current status variant."""
    if statement["status"] == "PROVISIONAL":
        applied = statement["projected_recoupment_cents"]
        remainder = statement["royalty_earned_cents"] - applied
        reserve = round_half_up_cents(
            Decimal(remainder) * Decimal(reserve_rate_bps) / Decimal(10000)
        )
        statement["reserve_held_cents"] = reserve
    else:
        applied = statement["recoupment_applied_cents"]
        remainder = statement["royalty_earned_cents"] - applied
        statement["reserve_held_cents"] = 0
    statement["net_payable_cents"] = (
        remainder - statement["reserve_held_cents"] + statement["adjustment_cents"]
    )


def contract_label(contract):
    artist = db.artists.get(contract["artist_id"])
    return db.labels.get(artist["label_id"]) if artist else None


def compute_statement_lines(contract, run):
    """Compute the statement's line-level figures for a contract and run.

    Eligible reports: release belongs to the contract, report.period <=
    run.period, and the report has not been counted by an earlier run's
    statement. Current-period lines (period == run.period) are walked in
    (created_at ASC, gross_revenue_cents ASC) order; the running cumulative
    unit count starts at the sum of units over eligible reports with period
    strictly earlier than the run period.

    Returns dict(gross, net, earned, counted_report_ids) or None when the
    contract has no current-period eligible report.
    """
    label = contract_label(contract)
    release_ids = {
        r["id"] for r in db.releases.values() if r["contract_id"] == contract["id"]
    }
    eligible = [
        rep for rep in db.revenue_reports.values()
        if rep["release_id"] in release_ids
        and rep["period"] <= run["period"]
        and not rep.get("_counted")
    ]
    current = [rep for rep in eligible if rep["period"] == run["period"]]
    if not current:
        return None
    prior_cumulative = sum(
        rep["units"] for rep in eligible if rep["period"] < run["period"]
    )
    lines = sorted(current, key=lambda r: (r["created_at"], r["gross_revenue_cents"]))

    tiers = sorted(label["tier_thresholds"], key=lambda t: t["units"])
    deduction = label["channel_deduction_bps"]
    base_rate = contract["effective_base_rate_bps"]

    gross_total = 0
    net_total = 0
    earned_total = 0
    cumulative = prior_cumulative
    for rep in lines:
        cumulative += rep["units"]
        line_net = round_half_up_cents(
            Decimal(rep["gross_revenue_cents"])
            * Decimal(10000 - int(deduction.get(rep["channel"], 0)))
            / Decimal(10000)
        )
        if rep["channel"] == "SYNC":
            line_royalty = round_half_up_cents(Decimal(line_net) * Decimal("0.50"))
        else:
            delta = 0
            for tier in tiers:
                if cumulative > tier["units"]:
                    delta = tier["delta_bps"]
            line_rate = base_rate + delta
            line_royalty = round_half_up_cents(
                Decimal(line_net) * Decimal(line_rate) / Decimal(10000)
            )
        gross_total += rep["gross_revenue_cents"]
        net_total += line_net
        earned_total += line_royalty

    return {
        "gross": gross_total,
        "net": net_total,
        "earned": earned_total,
        "counted_report_ids": [rep["id"] for rep in eligible],
    }
