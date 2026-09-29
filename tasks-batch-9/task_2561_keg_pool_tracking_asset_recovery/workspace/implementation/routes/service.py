"""The service line: centres, intake, cleaning, inspection, pressure test and
release."""
from datetime import timedelta

from flask import Blueprint

import clock
import db
import middleware
import response
import util
from errors import fail
from services import calc, recompute, view

bp = Blueprint("service", __name__)

REGION_PATTERN = r"^[A-Z]{2}$"
OPEN_STAGES = ("RECEIVED", "CLEANED", "INSPECTED", "PRESSURE_TESTED",
               "QUARANTINED")
STEPS = ("CLEAN", "INSPECT", "PRESSURE_TEST")
INSPECTION_RESULTS = ("PASS", "MINOR_DEFECT", "MAJOR_DEFECT")
PRESSURE_RESULTS = ("PASS", "FAIL")


def _open_cycle_count(center_id):
    return len([row for row in db.service_cycles.values()
                if row["service_center_id"] == center_id
                and row["stage"] in OPEN_STAGES])


def _center_out(center):
    row = dict(center)
    row["open_cycle_count"] = _open_cycle_count(center["id"])
    return row


# ------------------------------------------------------ service centres ------


@bp.post("/service-centers")
def create_center():
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    name = util.req_string(payload, "name", 1, 120)
    region_code = util.req_string(payload, "region_code", 2, 2,
                                  pattern=REGION_PATTERN)
    capacity = util.req_int(payload, "concurrent_cycle_capacity", minimum=1,
                            maximum=50)
    buffer_hours = util.opt_int(payload, "intake_buffer_hours", minimum=0,
                               maximum=48, default=4)
    center = util.common_fields()
    center.update({
        "name": name,
        "region_code": region_code,
        "concurrent_cycle_capacity": capacity,
        "intake_buffer_hours": buffer_hours,
        "open_cycle_count": 0,
    })
    db.service_centers[center["id"]] = center
    return response.created(center)


@bp.get("/service-centers/<center_id>")
def read_center(center_id):
    middleware.authenticate("PoolOperator", "ServiceTechnician",
                            "AssetRecoveryAnalyst")
    center = db.service_centers.get(center_id)
    if center is None:
        fail("ERR_SERVICE_CENTER_NOT_FOUND")
    return response.ok(_center_out(center))


# -------------------------------------------------------- service cycles -----


@bp.post("/service-cycles")
def book_cycle():
    middleware.authenticate("PoolOperator", "ServiceTechnician")
    payload = util.body()
    util.forbid_version_fields(payload)
    keg_id = util.req_string(payload, "keg_id")
    center_id = util.req_string(payload, "service_center_id")
    received_at = util.parse_instant(util.req_present(payload, "received_at"),
                                     "received_at")
    keg = db.kegs.get(keg_id)
    if keg is None:
        fail("ERR_KEG_NOT_FOUND")
    center = db.service_centers.get(center_id)
    if center is None:
        fail("ERR_SERVICE_CENTER_NOT_FOUND")
    # Every custody state other than the two legal intakes -- QUARANTINED and
    # the written-off states included -- is ERR_INVALID_STATE (PRD 3.8).
    if keg["custody_state"] not in ("IN_FLOAT", "IN_SERVICE"):
        fail("ERR_INVALID_STATE",
             "A keg in %s cannot be booked onto a line."
             % keg["custody_state"])
    util.not_future_instant(received_at, "received_at")
    # The intake window is closed at both ends and is evaluated against every
    # cycle the centre has ever received, RELEASED ones included.
    span = timedelta(hours=center["intake_buffer_hours"])
    for row in db.service_cycles.values():
        if row["service_center_id"] != center_id:
            continue
        if row["received_at"] <= received_at <= row["received_at"] + span:
            fail("ERR_INTAKE_WINDOW_CONFLICT",
                 "received_at falls inside an existing intake window.")
    if _open_cycle_count(center_id) >= center["concurrent_cycle_capacity"]:
        fail("ERR_SERVICE_CAPACITY_EXCEEDED",
             "The centre is at its concurrent cycle capacity.")
    cycle = util.common_fields()
    cycle.update({
        "keg_id": keg["id"],
        "service_center_id": center["id"],
        "stage": "RECEIVED",
        "received_at": received_at,
        "cleaned_at": None,
        "caustic_cycle_minutes": None,
        "inspected_at": None,
        "inspection_result": None,
        "pressure_tested_at": None,
        "pressure_test_psi": None,
        "pressure_test_result": None,
        "pressure_test_performed_by_user_id": None,
        "released_at": None,
        "released_by_user_id": None,
        "quarantine_reason": None,
    })
    db.service_cycles[cycle["id"]] = cycle
    util.apply_changes(center,
                       {"open_cycle_count": _open_cycle_count(center["id"])})
    # Booking a keg that is already IN_SERVICE touches neither the keg nor the
    # census and does not bump the keg's version.
    if keg["custody_state"] == "IN_FLOAT":
        keg["custody_state"] = "IN_SERVICE"
        util.bump(keg)
        recompute.cascade_pool_id(keg["pool_id"])
    return response.created(cycle)


@bp.post("/service-cycles/<cycle_id>/record-step")
def record_step(cycle_id):
    actor = middleware.authenticate("ServiceTechnician")
    payload = util.body()
    util.forbid_version_fields(payload)
    step = util.req_enum(payload, "step", STEPS)
    occurred_at = util.parse_instant(util.req_present(payload, "occurred_at"),
                                     "occurred_at")
    caustic_minutes = None
    inspection_result = None
    pressure_psi = None
    pressure_result = None
    if step == "CLEAN":
        caustic_minutes = util.req_int(payload, "caustic_cycle_minutes")
    elif step == "INSPECT":
        inspection_result = util.req_enum(payload, "inspection_result",
                                          INSPECTION_RESULTS)
    else:
        pressure_psi = util.req_number(payload, "pressure_test_psi")
        pressure_result = util.req_enum(payload, "pressure_test_result",
                                        PRESSURE_RESULTS)
    cycle = db.service_cycles.get(cycle_id)
    if cycle is None:
        fail("ERR_SERVICE_CYCLE_NOT_FOUND")
    stage = cycle["stage"]
    if step == "CLEAN" and stage != "RECEIVED":
        fail("ERR_INVALID_STATE", "A CLEAN step requires stage RECEIVED.")
    if step == "INSPECT" and stage != "CLEANED":
        fail("ERR_INVALID_STATE", "An INSPECT step requires stage CLEANED.")
    if step == "PRESSURE_TEST" and stage not in ("INSPECTED", "QUARANTINED"):
        fail("ERR_INVALID_STATE",
             "A PRESSURE_TEST step requires stage INSPECTED or QUARANTINED.")
    if step == "CLEAN" and caustic_minutes < calc.CAUSTIC_MIN_MINUTES:
        fail("ERR_CAUSTIC_CYCLE_TOO_SHORT",
             "caustic_cycle_minutes must be at least %d."
             % calc.CAUSTIC_MIN_MINUTES)
    if step == "PRESSURE_TEST":
        if pressure_psi < calc.PRESSURE_TEST_MIN_PSI:
            fail("ERR_PRESSURE_TEST_PSI_TOO_LOW",
                 "pressure_test_psi must be at least %d."
                 % calc.PRESSURE_TEST_MIN_PSI)
        # A structural defect can never be argued away by a pressure gauge.
        if stage == "QUARANTINED" \
                and cycle["quarantine_reason"] != "PRESSURE_TEST_FAIL":
            fail("ERR_QUARANTINE_RELEASE_BLOCKED",
                 "A cycle quarantined for a major defect may not be retested.")
    util.not_future_instant(occurred_at, "occurred_at")
    if step == "CLEAN" and occurred_at < cycle["received_at"]:
        util.bad("occurred_at", "must be at or after the cycle's received_at")
    if step == "INSPECT" and cycle["cleaned_at"] is not None \
            and occurred_at < cycle["cleaned_at"]:
        util.bad("occurred_at", "must be at or after the cycle's cleaned_at")
    keg = db.kegs.get(cycle["keg_id"])
    if step == "CLEAN":
        cycle["caustic_cycle_minutes"] = caustic_minutes
        cycle["cleaned_at"] = occurred_at
        cycle["stage"] = "CLEANED"
    elif step == "INSPECT":
        cycle["inspection_result"] = inspection_result
        cycle["inspected_at"] = occurred_at
        if inspection_result == "MAJOR_DEFECT":
            cycle["stage"] = "QUARANTINED"
            cycle["quarantine_reason"] = "INSPECTION_MAJOR_DEFECT"
            if keg is not None:
                keg["custody_state"] = "QUARANTINED"
                keg["service_state"] = "SERVICE_FAILED"
                util.bump(keg)
                recompute.cascade_pool_id(keg["pool_id"])
        else:
            cycle["stage"] = "INSPECTED"
    else:
        retest = stage == "QUARANTINED"
        cycle["pressure_test_psi"] = pressure_psi
        cycle["pressure_test_result"] = pressure_result
        if pressure_result == "PASS":
            cycle["stage"] = "PRESSURE_TESTED"
            cycle["pressure_tested_at"] = occurred_at
            cycle["pressure_test_performed_by_user_id"] = actor.user_id
            if retest and keg is not None:
                keg["custody_state"] = "IN_SERVICE"
                util.bump(keg)
                recompute.cascade_pool_id(keg["pool_id"])
        else:
            cycle["stage"] = "QUARANTINED"
            cycle["quarantine_reason"] = "PRESSURE_TEST_FAIL"
            cycle["pressure_tested_at"] = occurred_at
            if keg is not None:
                keg["custody_state"] = "QUARANTINED"
                keg["service_state"] = "SERVICE_FAILED"
                util.bump(keg)
                recompute.cascade_pool_id(keg["pool_id"])
    util.bump(cycle)
    return response.ok(cycle)


@bp.post("/service-cycles/<cycle_id>/release")
def release_cycle(cycle_id):
    actor = middleware.authenticate("PoolOperator", "ServiceTechnician")
    payload = util.body()
    util.forbid_version_fields(payload)
    released_at = util.parse_instant(util.req_present(payload, "released_at"),
                                     "released_at")
    cycle = db.service_cycles.get(cycle_id)
    if cycle is None:
        fail("ERR_SERVICE_CYCLE_NOT_FOUND")
    if cycle["stage"] == "QUARANTINED":
        if cycle["quarantine_reason"] == "INSPECTION_MAJOR_DEFECT":
            fail("ERR_QUARANTINE_RELEASE_BLOCKED",
                 "A cycle quarantined for a major defect may never be "
                 "released.")
        fail("ERR_INVALID_STATE",
             "A quarantined cycle needs a passing retest before release.")
    if cycle["stage"] != "PRESSURE_TESTED" \
            or cycle["pressure_test_result"] != "PASS":
        fail("ERR_INVALID_STATE",
             "Only a passing PRESSURE_TESTED cycle may be released.")
    if actor.user_id == cycle["pressure_test_performed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The technician who certified the keg may not release it.")
    cycle["stage"] = "RELEASED"
    cycle["released_at"] = released_at
    cycle["released_by_user_id"] = actor.user_id
    util.bump(cycle)
    center = db.service_centers.get(cycle["service_center_id"])
    if center is not None:
        util.apply_changes(center, {
            "open_cycle_count": _open_cycle_count(center["id"])})
    keg = db.kegs.get(cycle["keg_id"])
    if keg is not None:
        keg["custody_state"] = "IN_FLOAT"
        keg["service_state"] = "SERVICE_OK"
        keg["fills_at_last_pressure_test"] = keg["fill_count"]
        keg["last_pressure_test_at"] = cycle["pressure_tested_at"]
        keg["current_brewer_id"] = None
        keg["current_distributor_id"] = None
        keg["issuance_order_id"] = None
        keg["distributor_custody_started_at"] = None
        keg["dwell_started_at"] = released_at
        keg["dwell_flag"] = "WITHIN_LIMIT"
        util.bump(keg)
        recompute.cascade_pool_id(keg["pool_id"])
    return response.ok(cycle)


@bp.get("/service-cycles/<cycle_id>")
def read_cycle(cycle_id):
    middleware.authenticate("PoolOperator", "ServiceTechnician",
                            "AssetRecoveryAnalyst")
    cycle = db.service_cycles.get(cycle_id)
    if cycle is None:
        fail("ERR_SERVICE_CYCLE_NOT_FOUND")
    return response.ok(cycle)


@bp.get("/service-cycles")
def list_cycles():
    middleware.authenticate("PoolOperator", "ServiceTechnician",
                            "AssetRecoveryAnalyst")
    limit, offset = middleware.pagination()
    filters = {field: middleware.qparam(field)
               for field in ("keg_id", "service_center_id", "stage",
                             "inspection_result", "pressure_test_result")}
    rows = [row for row in db.service_cycles.values()
            if all(view.match(row, field, value)
                   for field, value in filters.items())]
    page, total = view.paginate(view.ordered(rows), limit, offset)
    return response.listing(page, limit, offset, total)
