"""Facility registration, lifecycle, and the monthly close checkpoint
(PRD 3.1, 3.2, 3.9)."""
from flask import Blueprint

from authz import (
    CONTRACTOR_ADMIN, FACILITY_OWNER, READ_ROLES, check_facility_ownership,
    require_roles,
)
from calc import (
    AGGREGATE_YEAR_DEDUCTIBLE_CENTS, FUND_YEAR_CAP_CENTS, latest_training_record,
    recompute_posture,
)
from cascades import cancel_order_cascade, create_deficiency
from db import store
from errors import (
    close_too_early, facility_not_active, facility_not_found, invalid_request,
    no_tank_registered, tanks_not_closed,
)
from respond import success
from serialize import ser_facility
from store_ops import (
    check_closed, get_or_404, json_body, new_common_fields, new_id, paginate,
    qparam, req_instant, req_period, req_str, sorted_by_creation, touch,
)
from timeutil import close_earliest_ts, parse_period

bp = Blueprint("facilities", __name__)

FUND_ELECTIONS = ["PER_OCCURRENCE", "AGGREGATE"]


def get_facility_or_404(fac_id):
    return get_or_404(store.facilities, fac_id, facility_not_found)


@bp.route("/facilities", methods=["POST"])
def create_facility():
    uid, _ = require_roles([FACILITY_OWNER])
    data = json_body()
    check_closed(data, {"facility_name", "state_code", "annual_fee_paid_through",
                        "fund_program_election"})
    name = req_str(data, "facility_name")
    state_code = req_str(data, "state_code")
    fee_through = req_instant(data, "annual_fee_paid_through")
    election = data.get("fund_program_election")
    if election is None:
        election = "PER_OCCURRENCE"
    elif election not in FUND_ELECTIONS:
        raise invalid_request("Field fund_program_election must be one of PER_OCCURRENCE, AGGREGATE")
    f = {
        "id": new_id(),
        "_seq": next(store.seq),
        "facility_name": name,
        "state_code": state_code,
        "owner_account_id": uid,
        "annual_fee_paid_through": fee_through,
        "fund_program_election": election,
        "posture_score": 100,
        "compliance_posture": "COMPLIANT",
        "fund_cap_remaining_cents": FUND_YEAR_CAP_CENTS,
        "fund_year_deductible_remaining_cents": AGGREGATE_YEAR_DEDUCTIBLE_CENTS,
        "status": "REGISTERED",
    }
    f.update(new_common_fields())
    store.facilities[f["id"]] = f
    return success(ser_facility(f), status=201)


@bp.route("/facilities", methods=["GET"])
def list_facilities():
    require_roles(READ_ROLES)
    state_code = qparam("state_code")
    owner = qparam("owner_account_id")
    status = qparam("status")
    items = store.facilities.values()
    if state_code is not None:
        items = [f for f in items if f["state_code"] == state_code]
    if owner is not None:
        items = [f for f in items if f["owner_account_id"] == owner]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_facility(f) for f in page], response_type="array",
                   pagination=pagination)


@bp.route("/facilities/<fac_id>", methods=["GET"])
def get_facility(fac_id):
    require_roles(READ_ROLES)
    return success(ser_facility(get_facility_or_404(fac_id)))


@bp.route("/facilities/<fac_id>/activate", methods=["POST"])
def activate_facility(fac_id):
    uid, _ = require_roles([FACILITY_OWNER])
    f = get_facility_or_404(fac_id)
    check_facility_ownership(uid, f)
    if f["status"] != "REGISTERED":
        raise facility_not_active("Facility activation requires status REGISTERED")
    has_tank = any(t["facility_id"] == fac_id for t in store.tank_systems.values())
    if not has_tank:
        raise no_tank_registered()
    f["status"] = "ACTIVE"
    touch(f)
    return success(ser_facility(f))


@bp.route("/facilities/<fac_id>/close", methods=["POST"])
def close_facility(fac_id):
    uid, _ = require_roles([FACILITY_OWNER])
    f = get_facility_or_404(fac_id)
    check_facility_ownership(uid, f)
    if f["status"] != "ACTIVE":
        raise facility_not_active("Facility closure requires status ACTIVE")
    tanks = [t for t in store.tank_systems.values() if t["facility_id"] == fac_id]
    if any(t["status"] != "PERMANENTLY_CLOSED" for t in tanks):
        raise tanks_not_closed()
    # Cascades: pending orders cancelled (linked re-test deficiencies fall back
    # to CORRECTED); operators revoked.
    for o in sorted(store.service_orders.values(), key=lambda o: o["_seq"]):
        if o["facility_id"] == fac_id and o["status"] in ("REQUESTED", "SCHEDULED"):
            cancel_order_cascade(o)
    for op in sorted(store.operators.values(), key=lambda o: o["_seq"]):
        if op["facility_id"] == fac_id and op["status"] in ("DESIGNATED", "ACTIVE", "LAPSED"):
            op["status"] = "REVOKED"
            touch(op)
    f["status"] = "CLOSED"
    touch(f)
    return success(ser_facility(f))


@bp.route("/facilities/<fac_id>/run-monthly-close", methods=["POST"])
def run_monthly_close(fac_id):
    require_roles([CONTRACTOR_ADMIN])
    data = json_body()
    check_closed(data, {"period_month"})
    f = get_facility_or_404(fac_id)
    if f["status"] != "ACTIVE":
        raise facility_not_active("Monthly close requires facility status ACTIVE")
    period = req_period(data, "period_month")
    y, m = parse_period(period)
    # Close is timely only once the clock reaches 00:00:00Z on day 11 of the
    # following month.
    if store.clock < close_earliest_ts(y, m):
        raise close_too_early()

    # Step 1: missing-record sweep (idempotent per tank+origin+period).
    created = 0
    tanks = sorted(
        [t for t in store.tank_systems.values()
         if t["facility_id"] == fac_id and t["status"] in ("IN_SERVICE", "TEMPORARILY_CLOSED")],
        key=lambda t: t["_seq"])
    for t in tanks:
        has_record = any(r["tank_system_id"] == t["id"] and r["period_month"] == period
                         for r in store.release_detection_records.values())
        if has_record:
            continue
        dup = any(d["tank_system_id"] == t["id"] and d["origin"] == "CLOSE_SWEEP"
                  and d["period_month"] == period
                  for d in store.deficiencies.values())
        if dup:
            continue
        create_deficiency(
            facility_id=fac_id, tank_system_id=t["id"], component_id=None,
            source_service_order_id=None, origin="CLOSE_SWEEP",
            period_month=period, severity="MINOR",
            description="Missing release-detection record for period %s" % period)
        created += 1

    # Step 2: operator lapse sweep.
    lapsed = 0
    for op in sorted(store.operators.values(), key=lambda o: o["_seq"]):
        if op["facility_id"] != fac_id or op["status"] != "ACTIVE":
            continue
        latest = latest_training_record(op["id"], op["operator_class"])
        if latest is not None and latest["expires_at"] <= store.clock:
            op["status"] = "LAPSED"
            touch(op)
            lapsed += 1

    # Step 3: escalation sweep.
    escalated = 0
    for d in sorted(store.deficiencies.values(), key=lambda d: d["_seq"]):
        if (d["facility_id"] == fac_id
                and d["status"] in ("OPEN", "CORRECTION_ORDERED", "CORRECTED", "RE_TEST_SCHEDULED")
                and store.clock > d["correction_deadline"]):
            d["status"] = "ESCALATED"
            d["escalated_at"] = store.clock
            touch(d)
            escalated += 1

    # Step 4: single posture recompute after steps 1-3.
    recompute_posture(f)
    return success({
        "deficiencies_created": created,
        "operators_lapsed": lapsed,
        "deficiencies_escalated": escalated,
        "posture_score": f["posture_score"],
        "compliance_posture": f["compliance_posture"],
    })
