"""Repurchase periods, tenders, the tiered waterfall and settlement — PRD §3.8."""

from datetime import timedelta

from flask import Blueprint

import calc
import domain
import validate as V
from auth import require_roles, require_transition_role, user_id
from errors import fail
from routes.helpers import listing, new, resolve, single
from store import DB, all_rows, logical_now, new_row, touch

bp = Blueprint("repurchase", __name__)

PERIOD_STATES = ("OPEN", "SUSPENDED", "PROCESSED", "CANCELLED")
REQUEST_STATES = ("QUEUED", "HELD", "WITHDRAWN", "FULFILLED",
                  "PARTIALLY_FULFILLED", "REJECTED")
HARDSHIP_TYPES = ("NONE", "DEATH", "DISABILITY")
TIER_ONE = ("DEATH", "DISABILITY")

REQUEST_STATUS_ROLES = {"WITHDRAWN": ("InvestorUser",)}

READ_ROLES = ("TransferAgent", "SponsorOperator", "ComplianceOfficer",
              "InvestorUser")


# --------------------------------------------------------------------------
# RepurchasePeriod
# --------------------------------------------------------------------------

@bp.post("/repurchase-periods")
def create_period():
    require_roles("TransferAgent", "SponsorOperator")
    body = V.json_body()
    offering_id = V.fk(body, "offering_id")
    month_literal, month_parts = V.month_field(body, "period_month")
    opens_literal, opens_at = V.instant_field(body, "opens_at")
    cutoff_literal, cutoff_at = V.instant_field(body, "request_cutoff_at")
    if cutoff_at <= opens_at:
        fail("ERR_INVALID_REQUEST",
             "request_cutoff_at must be strictly later than opens_at.")
    settlement_literal, settlement_date = V.date_field(body, "settlement_date")
    if settlement_date < cutoff_at.date():
        fail("ERR_INVALID_REQUEST",
             "settlement_date may not fall before the calendar date of request_cutoff_at.")

    offering = resolve("offerings", offering_id)

    # Level 8 — dependency states.
    if offering["registration_status"] != "EFFECTIVE":
        fail("ERR_OFFERING_NOT_EFFECTIVE")
    if offering["repurchase_plan_status"] != "ACTIVE":
        fail("ERR_REPURCHASE_PLAN_SUSPENDED")

    siblings = [p for p in domain.periods_of(offering["id"])
                if p["status"] != "CANCELLED"]

    # Level 9 — the half-open window may abut a sibling but never overlap it,
    # and it may not open inside the five-day settlement blackout.
    for sibling in siblings:
        if opens_at < sibling["_cutoff_at"] and sibling["_opens_at"] < cutoff_at:
            fail("ERR_REPURCHASE_PERIOD_WINDOW_CONFLICT")
        if opens_at >= sibling["_cutoff_at"]:
            buffer_start = sibling["_settlement_date"] + timedelta(
                days=calc.REPURCHASE_PERIOD_BLACKOUT_DAYS)
            if opens_at.date() < buffer_start:
                fail("ERR_REPURCHASE_PERIOD_WINDOW_CONFLICT")

    # Level 11 — one non-cancelled period per calendar month.
    for sibling in siblings:
        if sibling["period_month"] == month_literal:
            fail("ERR_DUPLICATE_REPURCHASE_PERIOD")

    year, month = month_parts
    row = new_row("repurchase_periods", {
        "offering_id": offering["id"],
        "period_month": month_literal,
        "quarter_key": calc.quarter_key(year, month),
        "opens_at": opens_literal,
        "_opens_at": opens_at,
        "request_cutoff_at": cutoff_literal,
        "_cutoff_at": cutoff_at,
        "settlement_date": settlement_literal,
        "_settlement_date": settlement_date,
        "monthly_cap_cents": 0,
        "quarterly_remaining_cents": 0,
        "capacity_cents": 0,
        "settled_amount_cents": 0,
        "prorated": False,
        "status": "OPEN",
    })
    return new(row)


@bp.get("/repurchase-periods")
def list_periods():
    require_roles(*READ_ROLES)
    limit, offset = V.pagination()
    offering_id = V.query_string("offering_id")
    status = V.query_enum("status", PERIOD_STATES)
    quarter_key = V.query_string("quarter_key")
    period_month = V.query_month("period_month")
    rows = [p for p in all_rows("repurchase_periods")
            if (offering_id is None or p["offering_id"] == offering_id)
            and (status is None or p["status"] == status)
            and (quarter_key is None or p["quarter_key"] == quarter_key)
            and (period_month is None or p["period_month"] == period_month)]
    return listing(rows, limit, offset)


@bp.get("/repurchase-periods/<repurchase_period_id>")
def get_period(repurchase_period_id):
    require_roles(*READ_ROLES)
    return single(resolve("repurchase_periods", repurchase_period_id))


@bp.post("/repurchase-periods/<repurchase_period_id>/processing")
def process_period(repurchase_period_id):
    require_roles("TransferAgent")
    period = resolve("repurchase_periods", repurchase_period_id)
    offering = DB["offerings"].get(period["offering_id"])

    # Level 7 — own state.
    if period["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION")

    # Level 8 — the plan, then a published valuation for every tendered class.
    if offering is None or offering["repurchase_plan_status"] != "ACTIVE":
        fail("ERR_REPURCHASE_PLAN_SUSPENDED")
    queued = [r for r in domain.requests_of_period(period["id"])
              if r["status"] == "QUEUED"]
    for request_row in queued:
        if domain.latest_published(request_row["share_class_id"]) is None:
            fail("ERR_NO_PUBLISHED_NAV")

    # Level 9 — the request window must have closed.
    if logical_now() < period["_cutoff_at"]:
        fail("ERR_PERIOD_NOT_READY_FOR_PROCESSING")

    # --- capacity, captured at this moment and not before ------------------
    aggregate = offering["aggregate_nav_cents"]
    quarter_used = sum(
        other["settled_amount_cents"] for other in domain.periods_of(offering["id"])
        if other["id"] != period["id"]
        and other["quarter_key"] == period["quarter_key"]
        and other["status"] == "PROCESSED")
    monthly_cap, quarterly_remaining, capacity = calc.repurchase_capacity(
        aggregate, quarter_used)

    prices = {r["id"]: domain.transaction_price_of_class_id(r["share_class_id"])
              for r in queued}
    requested = {r["id"]: calc.round_half_up(
        r["shares_requested_e4"] * prices[r["id"]], calc.SHARE_UNIT_SCALE)
        for r in queued}

    approved = _run_waterfall(queued, requested, capacity)
    approved_shares = {
        r["id"]: calc.floor_div(approved[r["id"]] * calc.SHARE_UNIT_SCALE,
                                prices[r["id"]])
        for r in queued}

    # --- settlement, planned in full before anything is mutated -----------
    plan = _plan_settlement(queued, prices, approved_shares, period)

    # --- apply -------------------------------------------------------------
    for lot, take in plan["lot_takes"]:
        lot["remaining_shares_e4"] -= take
        if lot["remaining_shares_e4"] == 0:
            lot["status"] = "CLOSED"
        touch(lot)

    settled_total = 0
    prorated = False
    investors = []
    for request_row in queued:
        grant = approved[request_row["id"]]
        want = requested[request_row["id"]]
        request_row["requested_value_cents"] = want
        request_row["approved_value_cents"] = grant
        request_row["approved_shares_e4"] = approved_shares[request_row["id"]]
        request_row["early_repurchase_deduction_cents"] = \
            plan["deductions"].get(request_row["id"], 0)
        request_row["net_proceeds_cents"] = plan["proceeds"].get(request_row["id"], 0)
        if grant == want:
            request_row["status"] = "FULFILLED"
        elif grant == 0:
            request_row["status"] = "REJECTED"
        else:
            request_row["status"] = "PARTIALLY_FULFILLED"
        touch(request_row)
        settled_total += grant
        if request_row["hardship_type"] == "NONE" and grant < want:
            prorated = True
        investor = DB["investors"].get(request_row["investor_id"])
        if investor is not None:
            deduction = plan["deductions"].get(request_row["id"], 0)
            if deduction:
                investor["cumulative_early_repurchase_deduction_cents"] += deduction
                touch(investor)
            if investor not in investors:
                investors.append(investor)

    period["monthly_cap_cents"] = monthly_cap
    period["quarterly_remaining_cents"] = quarterly_remaining
    period["capacity_cents"] = capacity
    period["settled_amount_cents"] = settled_total
    period["prorated"] = prorated
    period["status"] = "PROCESSED"
    touch(period)

    domain.sync_derived()
    for investor in investors:
        domain.note_position_possibly_closed(investor)
    return single(period)


def _run_waterfall(queued, requested, capacity):
    """PRD §3.8 — hardship tenders in full first, then pro rata by requested
    value with the floored remainder handed out a cent at a time."""
    approved = {r["id"]: 0 for r in queued}
    remaining = capacity

    tier_one = [r for r in queued if r["hardship_type"] in TIER_ONE]
    for request_row in tier_one:
        grant = min(requested[request_row["id"]], remaining)
        approved[request_row["id"]] = grant
        remaining -= grant

    tier_two = [r for r in queued if r["hardship_type"] == "NONE"]
    tier_two_total = sum(requested[r["id"]] for r in tier_two)
    if tier_two_total <= remaining:
        for request_row in tier_two:
            approved[request_row["id"]] = requested[request_row["id"]]
    else:
        for request_row in tier_two:
            approved[request_row["id"]] = calc.floor_div(
                remaining * requested[request_row["id"]], tier_two_total)
        leftover = remaining - sum(approved[r["id"]] for r in tier_two)
        for request_row in tier_two:
            if leftover <= 0:
                break
            approved[request_row["id"]] += 1
            leftover -= 1
    return approved


def _plan_settlement(queued, prices, approved_shares, period):
    """Consume lots oldest-first without mutating anything: an exhausted
    position must fail the whole run (PRD §3.8)."""
    working = {}
    lot_takes = []
    deductions = {}
    proceeds = {}

    for request_row in queued:
        to_consume = approved_shares[request_row["id"]]
        deduction_total = 0
        proceeds_total = 0
        price = prices[request_row["id"]]
        lots = domain.lots_fifo(domain.open_lots_of(
            request_row["investor_id"], request_row["share_class_id"]))
        for lot in lots:
            if to_consume == 0:
                break
            available = working.get(lot["id"], lot["remaining_shares_e4"])
            if available == 0:
                continue
            take = min(available, to_consume)
            lot_gross = calc.round_half_up(price * take, calc.SHARE_UNIT_SCALE)
            holding_days = (period["_settlement_date"] - lot["_issued_at"].date()).days
            deduction = calc.early_repurchase_deduction_cents(lot_gross, holding_days)
            deduction_total += deduction
            proceeds_total += lot_gross - deduction
            working[lot["id"]] = available - take
            lot_takes.append((lot, take))
            to_consume -= take
        if to_consume > 0:
            fail("ERR_INSUFFICIENT_SHARES")
        deductions[request_row["id"]] = deduction_total
        proceeds[request_row["id"]] = proceeds_total

    return {"lot_takes": lot_takes, "deductions": deductions, "proceeds": proceeds}


# --------------------------------------------------------------------------
# RepurchaseRequest
# --------------------------------------------------------------------------

@bp.post("/repurchase-requests")
def create_request():
    require_roles("InvestorUser")
    body = V.json_body()
    period_id = V.fk(body, "repurchase_period_id")
    share_class_id = V.fk(body, "share_class_id")
    shares = V.integer(body, "shares_requested_e4", minimum=1)
    hardship = V.enum(body, "hardship_type", HARDSHIP_TYPES,
                      required=False, default="NONE")

    # PRD §2.6 — body foreign keys resolve share_class_id before
    # repurchase_period_id.
    cls = resolve("share_classes", share_class_id)
    period = resolve("repurchase_periods", period_id)

    # Level 5 — the acting stockholder is the holder of record.
    investor = DB["investors"].get(user_id())
    if investor is None:
        fail("ERR_NOT_RESOURCE_OWNER")

    offering = DB["offerings"].get(period["offering_id"])

    # Level 8 — the plan must be running.
    if offering is None or offering["repurchase_plan_status"] != "ACTIVE":
        fail("ERR_REPURCHASE_PLAN_SUSPENDED")

    # Level 9 — the half-open window [opens_at, request_cutoff_at).
    now = logical_now()
    if now < period["_opens_at"] or now >= period["_cutoff_at"]:
        fail("ERR_REPURCHASE_PERIOD_CLOSED")

    # Level 11 — the shares must actually be there.
    held = sum(l["remaining_shares_e4"]
               for l in domain.open_lots_of(investor["id"], cls["id"]))
    already = sum(r["shares_requested_e4"] for r in domain.requests_of_period(period["id"])
                  if r["investor_id"] == investor["id"]
                  and r["share_class_id"] == cls["id"]
                  and r["status"] in ("QUEUED", "HELD"))
    if shares > held - already:
        fail("ERR_INSUFFICIENT_SHARES")

    row = new_row("repurchase_requests", {
        "repurchase_period_id": period["id"],
        "investor_id": investor["id"],
        "share_class_id": cls["id"],
        "shares_requested_e4": shares,
        "hardship_type": hardship,
        "requested_value_cents": 0,
        "approved_value_cents": 0,
        "approved_shares_e4": 0,
        "early_repurchase_deduction_cents": 0,
        "net_proceeds_cents": 0,
        "status": "QUEUED",
    })
    return new(row)


@bp.get("/repurchase-requests")
def list_requests():
    require_roles(*READ_ROLES)
    limit, offset = V.pagination()
    period_id = V.query_string("repurchase_period_id")
    investor_id = V.query_string("investor_id")
    share_class_id = V.query_string("share_class_id")
    status = V.query_enum("status", REQUEST_STATES)
    hardship = V.query_enum("hardship_type", HARDSHIP_TYPES)
    rows = [r for r in all_rows("repurchase_requests")
            if (period_id is None or r["repurchase_period_id"] == period_id)
            and (investor_id is None or r["investor_id"] == investor_id)
            and (share_class_id is None or r["share_class_id"] == share_class_id)
            and (status is None or r["status"] == status)
            and (hardship is None or r["hardship_type"] == hardship)]
    return listing(rows, limit, offset)


@bp.get("/repurchase-requests/<repurchase_request_id>")
def get_request(repurchase_request_id):
    require_roles(*READ_ROLES)
    return single(resolve("repurchase_requests", repurchase_request_id))


@bp.post("/repurchase-requests/<repurchase_request_id>/status")
def drive_request(repurchase_request_id):
    require_roles("InvestorUser")
    peek = V.json_body(silent=True)
    require_transition_role(REQUEST_STATUS_ROLES, peek.get("to_status"))
    body = V.json_body()
    to_status = V.enum(body, "to_status", REQUEST_STATES)

    request_row = resolve("repurchase_requests", repurchase_request_id)

    # Level 5 — a stockholder withdraws only its own tender.
    if request_row["investor_id"] != user_id():
        fail("ERR_NOT_RESOURCE_OWNER")

    if to_status != "WITHDRAWN" or request_row["status"] != "QUEUED":
        fail("ERR_INVALID_STATE_TRANSITION")

    period = DB["repurchase_periods"].get(request_row["repurchase_period_id"])

    # Level 9 — strictly before the cutoff.
    if period is not None and logical_now() >= period["_cutoff_at"]:
        fail("ERR_REPURCHASE_PERIOD_CLOSED")

    request_row["status"] = "WITHDRAWN"
    touch(request_row)
    domain.sync_derived()
    return single(request_row)
