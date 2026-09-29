"""Lease inventory, tenure and the obligation calendar (PRD 3.1)."""
from flask import Blueprint

from calc import (MAX_SHUT_IN_PAYMENTS, continuous_dev_deadline, db,
                  get_lease, guard_terminal, lease_allocations,
                  recompute_lease_acres, shut_in_next_due)
from common import add_months, dec, ok, ok_list, q2, today, touch
from errors import fail
from store import by_created, insert, out_lease, rows
from validate import (READ_INTERNAL, ROLE_LAND, authenticate, authorize, body,
                      filt, pagination, require, v_cents, v_date, v_enum,
                      v_int, v_number, v_pct, v_str, window)

bp = Blueprint("leases", __name__)

TENURE_STATUSES = ("PRIMARY_TERM", "HELD_BY_PRODUCTION", "SHUT_IN_HELD",
                   "CONTINUOUS_DEV_HELD", "EXPIRED")
OBLIGATION_STATUSES = ("COMPLIANT", "OBLIGATION_DUE", "IN_BREACH", "CURED")
EVENT_TYPES = ("SHUT_IN_PAYMENT", "CONTINUOUS_OPERATION", "PRODUCTION_ESTABLISHED")


def lease_view(lease):
    """Serialize with the two obligation deadlines recomputed from their inputs."""
    lease["shut_in_next_due_date"] = shut_in_next_due(lease)
    lease["continuous_dev_deadline"] = continuous_dev_deadline(lease)
    return out_lease(lease)


@bp.route("/leases", methods=["POST"])
def create_lease():
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["lease_number", "lessor_name", "gross_acres", "royalty_rate",
                   "primary_term_end_date"])
    lease_number = v_str(data, "lease_number", 1, 32)
    lessor_name = v_str(data, "lessor_name", 1)
    gross_acres = v_number(data, "gross_acres", strictly_positive=True, places=2)
    royalty_rate = v_pct(data, "royalty_rate", min_exclusive=True, max_exclusive=True)
    primary_term_end_date = v_date(data, "primary_term_end_date")
    extension_option_months = v_int(data, "extension_option_months", 0, 60, 0)
    extension_bonus_per_acre_cents = v_cents(data, "extension_bonus_per_acre_cents", 0)
    shut_in_royalty_per_acre_cents = v_cents(data, "shut_in_royalty_per_acre_cents", 0)
    continuous_dev_window_days = v_int(data, "continuous_dev_window_days", 30, 365, 180)

    for existing in rows("leases"):
        if existing["lease_number"] == lease_number:
            fail("ERR_DUPLICATE_LEASE_NUMBER")

    lease = insert("leases", {
        "lease_number": lease_number,
        "lessor_name": lessor_name,
        "gross_acres": gross_acres,
        "royalty_rate": royalty_rate,
        "primary_term_end_date": primary_term_end_date,
        "extension_option_months": extension_option_months,
        "extension_bonus_per_acre_cents": extension_bonus_per_acre_cents,
        "extension_exercised": False,
        "extension_bonus_paid_cents": 0,
        "shut_in_royalty_per_acre_cents": shut_in_royalty_per_acre_cents,
        "shut_in_start_date": None,
        "shut_in_payments_made": 0,
        "shut_in_next_due_date": None,
        "continuous_dev_window_days": continuous_dev_window_days,
        "last_operation_end_date": None,
        "continuous_dev_deadline": None,
        "tenure_status": "PRIMARY_TERM",
        "obligation_status": "COMPLIANT",
        "committed_acres_total": q2(dec(0)),
        "held_acres": q2(dec(0)),
    })
    return ok(lease_view(lease), 201)


@bp.route("/leases", methods=["GET"])
def list_leases():
    authenticate()
    authorize(*READ_INTERNAL)
    limit, offset = pagination()
    found = rows("leases")
    tenure = filt("tenure_status")
    obligation = filt("obligation_status")
    number = filt("lease_number")
    if tenure is not None:
        found = [l for l in found if l["tenure_status"] == tenure]
    if obligation is not None:
        found = [l for l in found if l["obligation_status"] == obligation]
    if number is not None:
        found = [l for l in found if l["lease_number"] == number]
    found = by_created(found, descending=True)
    page, total = window(found, limit, offset)
    return ok_list([lease_view(l) for l in page], limit, offset, total)


@bp.route("/leases/<lease_id>", methods=["GET"])
def read_lease(lease_id):
    authenticate()
    authorize(*READ_INTERNAL)
    return ok(lease_view(get_lease(lease_id)))


@bp.route("/leases/<lease_id>/extension", methods=["POST"])
def exercise_extension(lease_id):
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["bonus_paid_cents"])
    bonus_paid_cents = v_cents(data, "bonus_paid_cents")
    lease = get_lease(lease_id)
    guard_terminal("lease", lease)

    if lease["tenure_status"] != "PRIMARY_TERM" \
            or lease["extension_exercised"] \
            or lease["extension_option_months"] <= 0 \
            or today() > lease["primary_term_end_date"]:
        fail("ERR_EXTENSION_NOT_AVAILABLE")

    from common import rhu
    expected = rhu(dec(lease["gross_acres"]) * dec(lease["extension_bonus_per_acre_cents"]))
    if bonus_paid_cents != expected:
        fail("ERR_EXTENSION_BONUS_MISMATCH")

    lease["primary_term_end_date"] = add_months(lease["primary_term_end_date"],
                                                lease["extension_option_months"])
    lease["extension_exercised"] = True
    lease["extension_bonus_paid_cents"] = bonus_paid_cents
    if lease["obligation_status"] == "OBLIGATION_DUE":
        lease["obligation_status"] = "CURED"
    touch(lease)
    return ok(lease_view(lease))


@bp.route("/leases/<lease_id>/obligation-events", methods=["POST"])
def record_obligation_event(lease_id):
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["event_type", "event_date"])
    event_type = v_enum(data, "event_type", EVENT_TYPES)
    event_date = v_date(data, "event_date")
    operation_end_date = v_date(data, "operation_end_date")
    supplied_shut_in_start = v_date(data, "shut_in_start_date")

    lease = get_lease(lease_id)
    guard_terminal("lease", lease)
    now_date = today()

    if event_type == "SHUT_IN_PAYMENT":
        if lease["tenure_status"] not in ("PRIMARY_TERM", "HELD_BY_PRODUCTION",
                                         "SHUT_IN_HELD"):
            fail("ERR_LEASE_NOT_HELD")
        feeds_shut_in = False
        for alloc in lease_allocations(lease["id"], committed_only=True):
            well = db.wells.get(alloc["well_id"])
            if well is not None and well["well_status"] == "SHUT_IN":
                feeds_shut_in = True
                break
        if not feeds_shut_in:
            fail("ERR_LEASE_NOT_HELD")
        if lease["shut_in_payments_made"] >= MAX_SHUT_IN_PAYMENTS:
            fail("ERR_SHUT_IN_LIMIT_EXCEEDED")
        if lease["shut_in_payments_made"] == 0 and supplied_shut_in_start is not None:
            lease["shut_in_start_date"] = supplied_shut_in_start
        lease["shut_in_payments_made"] = lease["shut_in_payments_made"] + 1
        lease["shut_in_next_due_date"] = shut_in_next_due(lease)
        lease["tenure_status"] = "SHUT_IN_HELD"
        if lease["obligation_status"] == "OBLIGATION_DUE":
            lease["obligation_status"] = "CURED"
    elif event_type == "CONTINUOUS_OPERATION":
        if lease["tenure_status"] not in ("PRIMARY_TERM", "HELD_BY_PRODUCTION",
                                         "CONTINUOUS_DEV_HELD"):
            fail("ERR_LEASE_NOT_HELD")
        if lease["tenure_status"] == "CONTINUOUS_DEV_HELD":
            deadline = lease.get("continuous_dev_deadline")
            if deadline is None or now_date > deadline:
                fail("ERR_LEASE_NOT_HELD")
        if event_date > now_date:
            fail("ERR_EFFECTIVE_DATE_OUT_OF_RANGE")
        lease["last_operation_end_date"] = operation_end_date or event_date
        lease["continuous_dev_deadline"] = continuous_dev_deadline(lease)
        lease["tenure_status"] = "CONTINUOUS_DEV_HELD"
        if lease["obligation_status"] in ("OBLIGATION_DUE", "IN_BREACH"):
            lease["obligation_status"] = "CURED"
    else:
        lease["tenure_status"] = "HELD_BY_PRODUCTION"
        if lease["obligation_status"] in ("OBLIGATION_DUE", "IN_BREACH"):
            lease["obligation_status"] = "CURED"

    touch(lease)
    recompute_lease_acres(lease)
    return ok(lease_view(lease))
