"""Monthly settlement: opening, calculating, posting and paying (PRD 3.8)."""

from flask import Blueprint

import calc
from envelope import created, ok
from errors import ApiError
from guards import PERIOD_MONTH_RE, authenticate, field_str, read_body, _bad
from listing import list_response
from lookup import get_run, get_statement
from store import month_window, new_row, ordered, serialize, store, touch

bp = Blueprint("settlement", __name__)

READ_ROLES = ("HostOperations", "HostController", "ComplianceOfficer", "Advisor")


@bp.post("/settlement-runs")
def open_run():
    authenticate(("HostOperations",))
    body = read_body(("period_month",))
    period_month = field_str(body, "period_month")
    if not PERIOD_MONTH_RE.match(period_month):
        _bad("period_month must be written as YYYY-MM with a month between 01 and 12.")

    for existing in store.runs.values():
        if existing["period_month"] == period_month:
            raise ApiError("ERR_SETTLEMENT_PERIOD_DUPLICATE")

    row = new_row({
        "period_month": period_month,
        "status": "OPEN",
        "calculated_by_user_id": None,
        "posted_by_user_id": None,
        "statement_count": 0,
        "gross_commission_cents": 0,
        "advisor_share_total_cents": 0,
        "chargeback_total_cents": 0,
        "platform_fee_total_cents": 0,
        "marketing_fund_total_cents": 0,
        "net_payout_total_cents": 0,
    })
    store.runs[row["id"]] = row
    return created(serialize(row))


@bp.get("/settlement-runs/<run_id>")
def read_run(run_id):
    authenticate(READ_ROLES)
    return ok(serialize(get_run(run_id)))


# --------------------------------------------------------------------------
# calculate
# --------------------------------------------------------------------------

def _final_basis(advisor):
    """The FINAL production total and the tier it selects, computed without
    writing anything, so an unresolvable ladder can be reported before the run
    mutates a single row."""
    from store import year_window
    year_start, year_end = year_window(store.clock)
    total = 0
    for booking in calc.advisor_bookings(advisor["id"]):
        if booking["booking_status"] not in ("CONFIRMED", "TRAVELED"):
            continue
        if booking["commission_status"] != "RECEIVED":
            continue
        received_on = booking["commission_received_on"]
        if received_on is None or not (year_start <= received_on < year_end):
            continue
        total += booking["received_commission_cents"]
    schedule = calc.tier_schedule_for(advisor)
    tier = None
    if schedule is not None:
        tier = calc.select_tier(schedule["tiers"], total)
        if tier is None:
            raise ApiError("ERR_SPLIT_TIER_UNRESOLVED")
    return total, tier


def _plan_statement(run, advisor, period_start, period_end):
    """Everything the statement will carry, computed without mutating a row."""
    inclusion = []
    chargebacks = []
    for booking in calc.advisor_bookings(advisor["id"]):
        if (booking["booking_status"] in ("CONFIRMED", "TRAVELED")
                and booking["commission_status"] == "RECEIVED"
                and booking["statement_id"] is None
                and booking["commission_received_on"] is not None
                and period_start <= booking["commission_received_on"] < period_end):
            inclusion.append(booking)
        if (booking["commission_status"] == "CHARGED_BACK"
                and booking["chargeback_recognized_at"] is None):
            chargebacks.append(booking)

    carryforward = advisor["carryforward_chargeback_cents"]
    if not inclusion and not chargebacks and carryforward == 0:
        return None

    final_total, final_tier = _final_basis(advisor)

    priced = []
    gross = 0
    share = 0
    for booking in inclusion:
        agreement = store.agreements.get(booking["agreement_id"])
        if advisor["status"] == "DEPARTED":
            pct = calc.D(agreement["post_departure_advisor_pct"]) if agreement else calc.D(0)
            tier_level = None
        else:
            schedule = calc.schedule_of(agreement)
            tier = calc.select_tier(schedule["tiers"], final_total) if schedule else None
            if tier is None:
                raise ApiError("ERR_SPLIT_TIER_UNRESOLVED")
            pct = calc.D(tier["advisor_pct"])
            tier_level = tier["tier_level"]
        # Round per booking, then sum the rounded integers (PRD 2.6).
        settled = calc.round_half_up(calc.D(booking["received_commission_cents"]) * pct)
        priced.append((booking, settled, tier_level))
        gross += booking["received_commission_cents"]
        share += settled

    chargeback_total = carryforward + sum(b["chargeback_amount_cents"]
                                          for b in chargebacks)

    platform_fee, marketing_fund, net_payout, carry_applied = calc.host_platform_fee(
        advisor, share, chargeback_total)

    return {
        "advisor": advisor,
        "priced": priced,
        "chargebacks": chargebacks,
        "final_total": final_total,
        "final_tier": final_tier,
        "booking_count": len(inclusion),
        "gross_commission_cents": gross,
        "advisor_share_cents": share,
        "chargeback_cents": chargeback_total,
        "platform_fee_cents": platform_fee,
        "marketing_fund_cents": marketing_fund,
        "net_payout_cents": net_payout,
        "carryforward_applied_cents": carry_applied,
    }


@bp.post("/settlement-runs/<run_id>/calculate")
def calculate_run(run_id):
    caller = authenticate(("HostController",))
    read_body((), required_body=False)
    run = get_run(run_id)

    if run["status"] != "OPEN":
        raise ApiError("ERR_INVALID_RUN_STATE")
    for other in store.runs.values():
        if (other["id"] != run["id"]
                and other["period_month"] == run["period_month"]
                and other["status"] in ("CALCULATED", "POSTED", "CLOSED")):
            raise ApiError("ERR_INVALID_RUN_STATE")

    period_start, period_end = month_window(run["period_month"])

    plans = []
    for advisor in ordered(store.advisors.values()):
        plan = _plan_statement(run, advisor, period_start, period_end)
        if plan is not None:
            plans.append(plan)

    # Deterministic creation order: advisor created_at ASC, then email ASC.
    plans.sort(key=lambda p: (p["advisor"]["created_at"], p["advisor"]["email"]))

    totals = {
        "gross_commission_cents": 0,
        "advisor_share_total_cents": 0,
        "chargeback_total_cents": 0,
        "platform_fee_total_cents": 0,
        "marketing_fund_total_cents": 0,
        "net_payout_total_cents": 0,
    }

    for plan in plans:
        advisor = plan["advisor"]
        advisor["production_ytd_final_cents"] = plan["final_total"]
        if plan["final_tier"] is not None:
            advisor["split_tier_final"] = plan["final_tier"]["tier_level"]
        tier_level_applied = advisor["split_tier_final"]
        pct_applied = (plan["final_tier"]["advisor_pct"]
                       if plan["final_tier"] is not None else 0)

        statement = new_row({
            "settlement_run_id": run["id"],
            "advisor_id": advisor["id"],
            "tier_level_applied": tier_level_applied,
            "advisor_pct_applied": pct_applied,
            "booking_count": plan["booking_count"],
            "gross_commission_cents": plan["gross_commission_cents"],
            "advisor_share_cents": plan["advisor_share_cents"],
            "chargeback_cents": plan["chargeback_cents"],
            "platform_fee_cents": plan["platform_fee_cents"],
            "marketing_fund_cents": plan["marketing_fund_cents"],
            "net_payout_cents": plan["net_payout_cents"],
            "carryforward_applied_cents": plan["carryforward_applied_cents"],
            "status": "DRAFT",
            "paid_at": None,
        })
        store.statements[statement["id"]] = statement

        for booking, settled, tier_level in plan["priced"]:
            booking["statement_id"] = statement["id"]
            booking["settled_share_cents"] = settled
            booking["settled_tier_level"] = tier_level
            touch(booking)
        for booking in plan["chargebacks"]:
            booking["chargeback_recognized_at"] = store.clock
            touch(booking)

        totals["gross_commission_cents"] += plan["gross_commission_cents"]
        totals["advisor_share_total_cents"] += plan["advisor_share_cents"]
        totals["chargeback_total_cents"] += plan["chargeback_cents"]
        totals["platform_fee_total_cents"] += plan["platform_fee_cents"]
        totals["marketing_fund_total_cents"] += plan["marketing_fund_cents"]
        totals["net_payout_total_cents"] += plan["net_payout_cents"]

    run["status"] = "CALCULATED"
    run["calculated_by_user_id"] = caller.user_id
    run["statement_count"] = len(plans)
    run.update(totals)
    touch(run)
    return ok(serialize(run))


# --------------------------------------------------------------------------
# post and pay
# --------------------------------------------------------------------------

def _run_statements(run_id):
    return ordered([s for s in store.statements.values()
                    if s["settlement_run_id"] == run_id])


@bp.post("/settlement-runs/<run_id>/post")
def post_run(run_id):
    caller = authenticate(("HostController",))
    read_body((), required_body=False)
    run = get_run(run_id)

    if run["status"] != "CALCULATED":
        raise ApiError("ERR_INVALID_RUN_STATE")
    if run["calculated_by_user_id"] == caller.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    statements = _run_statements(run["id"])
    for statement in statements:
        if statement["status"] != "DRAFT":
            continue
        statement["status"] = "POSTED"
        touch(statement)

        advisor = store.advisors.get(statement["advisor_id"])
        if advisor is None:
            continue
        calc.recompute_advisor_lifetime(advisor)
        # REPLACED, not incremented, so an unabsorbed chargeback carries once.
        advisor["carryforward_chargeback_cents"] = statement["carryforward_applied_cents"]
        touch(advisor)

        if advisor["consortium_id"] is not None:
            consortium = store.consortiums.get(advisor["consortium_id"])
            if consortium is not None:
                calc.recompute_consortium_fund(consortium)
                touch(consortium)

    run["status"] = "POSTED"
    run["posted_by_user_id"] = caller.user_id
    touch(run)

    if not statements:
        # An empty run is not an error: it closes within the same request.
        run["status"] = "CLOSED"
        touch(run)

    return ok(serialize(run))


@bp.get("/advisor-statements/<statement_id>")
def read_statement(statement_id):
    authenticate(READ_ROLES)
    return ok(serialize(get_statement(statement_id)))


@bp.get("/advisor-statements")
def list_statements():
    authenticate(READ_ROLES)
    return list_response(store.statements.values(),
                         (("settlement_run_id", "settlement_run_id"),
                          ("advisor_id", "advisor_id"),
                          ("status", "status")))


@bp.post("/advisor-statements/<statement_id>/pay")
def pay_statement(statement_id):
    authenticate(("HostController",))
    body = read_body(("payment_reference",))
    field_str(body, "payment_reference", max_len=200)

    statement = get_statement(statement_id)
    run = store.runs.get(statement["settlement_run_id"])

    if run is None or run["status"] not in ("POSTED", "CLOSED"):
        raise ApiError("ERR_RUN_NOT_POSTED")
    if statement["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")

    advisor = store.advisors.get(statement["advisor_id"])
    if advisor is None or advisor["status"] == "DRAFT":
        raise ApiError("ERR_ADVISOR_NOT_ACTIVE")

    statement["status"] = "PAID"
    statement["paid_at"] = store.clock
    touch(statement)

    calc.recompute_advisor_lifetime(advisor)
    if advisor["consortium_id"] is not None:
        consortium = store.consortiums.get(advisor["consortium_id"])
        if consortium is not None:
            calc.recompute_consortium_fund(consortium)

    siblings = _run_statements(run["id"])
    if run["status"] == "POSTED" and all(s["status"] == "PAID" for s in siblings):
        run["status"] = "CLOSED"
        touch(run)

    return ok(serialize(statement))
