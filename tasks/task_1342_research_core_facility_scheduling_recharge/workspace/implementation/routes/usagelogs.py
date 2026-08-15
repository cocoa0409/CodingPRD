"""Usage logs (PRD §3.8): draft, edit, submit, validate (final charge +
subsidy waterfall + USAGE entry), reject."""

from datetime import timedelta

from flask import Blueprint, request

from auth import authenticate, require_roles, is_entity_role, auth_id
from errors import fail
from helpers import (
    Body, validate_body, is_int, dt_ok, parse_dt,
    grant_ledger, ser_usage_log, open_batch, run_waterfall, commit_draws,
    create_entry, ceil_div,
)
from routes.bookings import get_booking_or_404
from store import store, now
from util import new_entity, ok_object, parse_pagination, paginate, sort_default, touch, fmt_ts
from util import round_half_up_cents, whole_minutes
from decimal import Decimal

bp = Blueprint("usagelogs", __name__)


def get_log_or_404(lid):
    u = store.usage_logs.get(lid)
    if u is None:
        fail("ERR_NOT_FOUND", "Usage log not found")
    return u


def _window_ok(log_start, log_end, booking):
    """Priority 19: actual_end > actual_start and <= booking.end_at + 24h."""
    if log_start is None or log_end is None:
        return
    if not (log_end > log_start):
        fail("ERR_USAGE_WINDOW_INVALID", "actual_end_at must be after actual_start_at")
    if log_end > booking["_end_at"] + timedelta(hours=24):
        fail("ERR_USAGE_WINDOW_INVALID", "actual_end_at beyond booking.end_at + 24h")


@bp.route("/usage-logs", methods=["POST"])
def create_usage_log():
    authenticate()
    require_roles("CoreStaff")
    body = Body(request.get_json(silent=True))
    booking_id = body.get("booking_id")
    # Priority 4 — booking FK existence
    if booking_id is not None and booking_id not in store.bookings:
        fail("ERR_NOT_FOUND", "booking_id does not reference an existing booking")
    booking = store.bookings.get(booking_id)
    a_start = parse_dt(body.get("actual_start_at"))
    a_end = parse_dt(body.get("actual_end_at"))
    # Priority 19 — usage window shape
    if booking is not None:
        _window_ok(a_start, a_end, booking)
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"booking_id", "actual_start_at", "actual_end_at", "consumable_fee_cents"},
        required={"booking_id", "actual_start_at", "actual_end_at"},
        checkers={
            "booking_id": lambda v: isinstance(v, str),
            "actual_start_at": dt_ok,
            "actual_end_at": dt_ok,
            "consumable_fee_cents": lambda v: is_int(v) and v >= 0,
        },
    )
    # Priority 25 — one usage log per booking
    for u in store.usage_logs.values():
        if u["booking_id"] == booking_id:
            fail("ERR_USAGE_LOG_EXISTS", "Booking already has a usage log")
    # Priority 39 — booking must be COMPLETED
    if booking["status"] != "COMPLETED":
        fail("ERR_BOOKING_NOT_COMPLETED", "Usage logs require a COMPLETED booking")
    log = new_entity({
        "booking_id": booking_id,
        "instrument_id": booking["instrument_id"],
        "user_id": booking["user_id"],
        "actual_start_at": fmt_ts(a_start),
        "actual_end_at": fmt_ts(a_end),
        "consumable_fee_cents": body.get("consumable_fee_cents", 0),
        "status": "DRAFT",
        "logged_by": auth_id(),
        "validated_by": None,
        "billable_minutes": None,
        "usage_charge_cents": None,
        "_actual_start_at": a_start,
        "_actual_end_at": a_end,
    })
    store.usage_logs[log["id"]] = log
    return ok_object(ser_usage_log(log), status=201)


@bp.route("/usage-logs", methods=["GET"])
def list_usage_logs():
    authenticate()
    require_roles("CoreStaff", "FacilityAdmin", "FinanceOfficer", "Researcher", "ExternalClient")
    limit, offset = parse_pagination(request.args)
    items = list(store.usage_logs.values())
    if is_entity_role():
        items = [u for u in items if u["user_id"] == auth_id()]
    else:
        user_id = request.args.get("user_id")
        if user_id is not None:
            items = [u for u in items if u["user_id"] == user_id]
    for param in ("booking_id", "instrument_id"):
        v = request.args.get(param)
        if v is not None:
            items = [u for u in items if u.get(param) == v]
    status = request.args.get("status")
    if status is not None:
        items = [u for u in items if u["status"] == status]
    return paginate(sort_default(items), limit, offset, ser_usage_log)


@bp.route("/usage-logs/<lid>", methods=["GET"])
def get_usage_log(lid):
    authenticate()
    require_roles("CoreStaff", "FacilityAdmin", "FinanceOfficer", "Researcher", "ExternalClient")
    log = get_log_or_404(lid)
    if is_entity_role() and log["user_id"] != auth_id():
        fail("ERR_FORBIDDEN", "Entity-backed callers may only access their own resources")
    return ok_object(ser_usage_log(log))


@bp.route("/usage-logs/<lid>", methods=["PUT"])
def edit_usage_log(lid):
    authenticate()
    require_roles("CoreStaff")
    log = get_log_or_404(lid)
    body = Body(request.get_json(silent=True))
    # Priority 6 — only DRAFT or REJECTED logs are editable
    if log["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_INVALID_STATE", "Only DRAFT or REJECTED usage logs can be edited")
    booking = store.bookings.get(log["booking_id"])
    a_start = parse_dt(body.get("actual_start_at")) if body.has("actual_start_at") else log["_actual_start_at"]
    a_end = parse_dt(body.get("actual_end_at")) if body.has("actual_end_at") else log["_actual_end_at"]
    # Priority 19 — window shape on the merged values
    if booking is not None:
        _window_ok(a_start, a_end, booking)
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"actual_start_at", "actual_end_at", "consumable_fee_cents"},
        required=set(),
        checkers={
            "actual_start_at": dt_ok,
            "actual_end_at": dt_ok,
            "consumable_fee_cents": lambda v: is_int(v) and v >= 0,
        },
    )
    if body.has("actual_start_at"):
        log["actual_start_at"] = fmt_ts(a_start)
        log["_actual_start_at"] = a_start
    if body.has("actual_end_at"):
        log["actual_end_at"] = fmt_ts(a_end)
        log["_actual_end_at"] = a_end
    if body.has("consumable_fee_cents"):
        log["consumable_fee_cents"] = body.get("consumable_fee_cents")
    touch(log)
    return ok_object(ser_usage_log(log))


@bp.route("/usage-logs/<lid>/submit", methods=["POST"])
def submit_usage_log(lid):
    authenticate()
    require_roles("CoreStaff")
    log = get_log_or_404(lid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if log["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_INVALID_STATE", "Only DRAFT or REJECTED logs can be submitted")
    log["status"] = "SUBMITTED"
    touch(log)
    return ok_object(ser_usage_log(log))


@bp.route("/usage-logs/<lid>/validate", methods=["POST"])
def validate_usage_log(lid):
    authenticate()
    require_roles("CoreStaff")
    log = get_log_or_404(lid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    # Priority 3 — segregation of duties: validator != logger
    if auth_id() == log.get("logged_by"):
        fail("ERR_SEGREGATION_OF_DUTIES", "The logger cannot validate their own usage log")
    # Priority 6 — state legality
    if log["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED usage log can be validated")
    booking = store.bookings.get(log["booking_id"])
    if booking is None or booking["status"] != "COMPLETED":
        fail("ERR_BOOKING_NOT_COMPLETED", "Booking must be COMPLETED")
    # Priority 7 — OPEN batch required
    batch = open_batch()
    if batch is None:
        fail("ERR_BATCH_NOT_OPEN", "No OPEN recharge batch")
    # Final charge (calculation usage_charge, FINAL variant):
    # ceil to increment first, min-charge floor second, xrate round half-up
    # third, consumables last (never rounded).
    actual_minutes = whole_minutes(log["_actual_end_at"] - log["_actual_start_at"])
    inc = booking["applied_increment_minutes"]
    min_charge = booking["applied_min_charge_minutes"]
    billable = max(ceil_div(actual_minutes, inc) * inc, min_charge)
    rate = booking["applied_rate_cents_per_hour"]
    charge = round_half_up_cents(Decimal(billable) * Decimal(rate) / Decimal(60))
    charge += log["consumable_fee_cents"]
    user = store.users.get(booking["user_id"])
    is_external = bool(user and user["affiliation"] == "EXTERNAL")
    offset = 0
    draws = []
    grant = None
    if not is_external:
        # Subsidy waterfall (INTERNAL only), evaluated at entry-creation time
        offset, draws = run_waterfall(booking["user_id"], charge, now())
        net = charge - offset
        grant = store.grants.get(booking["grant_id"]) if booking.get("grant_id") else None
        if grant is not None:
            _, _, available = grant_ledger(grant)
            if available < net:
                fail("ERR_GRANT_BUDGET_EXCEEDED", "Grant budget_available_cents below the entry net")
    else:
        net = charge
    # ---- commit ----
    commit_draws(draws)
    create_entry(
        batch_id=batch["id"],
        kind="USAGE",
        amount=charge,
        offset=offset,
        status="PENDING",
        user_id=booking["user_id"],
        instrument_id=booking["instrument_id"],
        grant_id=None if is_external else booking.get("grant_id"),
        booking_id=booking["id"],
        usage_log_id=log["id"],
        is_external=is_external,
        draws=draws,
    )
    log["billable_minutes"] = billable
    log["usage_charge_cents"] = charge
    log["validated_by"] = auth_id()
    log["status"] = "VALIDATED"
    touch(log)
    return ok_object(ser_usage_log(log))


@bp.route("/usage-logs/<lid>/reject", methods=["POST"])
def reject_usage_log(lid):
    authenticate()
    require_roles("CoreStaff")
    log = get_log_or_404(lid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            if k not in ("reason",):
                fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    # Priority 3 — segregation of duties: rejecter != logger
    if auth_id() == log.get("logged_by"):
        fail("ERR_SEGREGATION_OF_DUTIES", "The logger cannot reject their own usage log")
    if log["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED usage log can be rejected")
    log["status"] = "REJECTED"
    touch(log)
    return ok_object(ser_usage_log(log))
