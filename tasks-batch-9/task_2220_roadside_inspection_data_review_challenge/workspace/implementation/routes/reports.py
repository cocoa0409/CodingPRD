"""Inspection reports, violations and state-agency amendments."""

from datetime import timedelta

from flask import Blueprint

from db import base_record, get_or_404, serialize, store, touch
from errors import err
from middleware import ALL_ROLES, actor, scope, scope_rows
from response import created, ok
from routes.helpers import filtered, listing, rows_of, view_violation
from services import cascade
from services.calc import (CATEGORIES, DUPLICATE_BUFFER_MINUTES,
                           ACTIVE_STATUSES, whole_days)
from validation import (body, get_bool, get_dt, get_enum, get_int, get_str,
                        pagination, q_bool, q_enum, q_str)

bp = Blueprint("reports", __name__)

REPORT_STATUSES = ("RECEIVED", "VALIDATED", "SCORED", "AMENDED", "RESCINDED")
SELECTION_SOURCES = ("ISS_SCREENING", "RANDOM", "POST_CRASH", "COMPLAINT",
                     "WEIGH_STATION")
VIOLATION_STATUSES = ("ACTIVE", "RECODED", "REMOVED")
UNIT_TYPES = ("VEHICLE", "DRIVER")
AMENDMENT_TYPES = ("VIOLATION_CODE_CORRECTION", "DRIVER_ATTRIBUTION_CORRECTION",
                   "CARRIER_REATTRIBUTION", "VIOLATION_REMOVAL")
AMENDABLE_REPORT_STATUSES = ("VALIDATED", "SCORED", "AMENDED")


# ---------------------------------------------------------------------------
# inspection reports
# ---------------------------------------------------------------------------

@bp.post("/inspection-reports")
def create_report():
    actor("StateInspectionOfficer")
    b = body()
    report_number = get_str(b, "report_number", max_len=40)
    inspection_state = get_str(b, "inspection_state", max_len=2)
    if len(inspection_state) != 2 or not inspection_state.isalpha() \
            or inspection_state != inspection_state.upper():
        raise err("ERR_INVALID_REQUEST",
                  "'inspection_state' must be two uppercase letters.")
    inspection_level = get_int(b, "inspection_level", minimum=1, maximum=6)
    inspection_start = get_dt(b, "inspection_start")
    inspection_end = get_dt(b, "inspection_end")
    if inspection_end.dt <= inspection_start.dt:
        raise err("ERR_INVALID_REQUEST",
                  "'inspection_end' must be after 'inspection_start'.")
    vehicle_vin = get_str(b, "vehicle_vin", max_len=40)
    attributed_carrier_id = get_str(b, "attributed_carrier_id")
    selection_source = get_enum(b, "selection_source", SELECTION_SOURCES)
    driver_id = get_str(b, "driver_id", required=False)

    carrier = get_or_404(store.carriers, attributed_carrier_id,
                         "ERR_CARRIER_NOT_FOUND")
    driver = None
    if driver_id is not None:
        driver = get_or_404(store.drivers, driver_id, "ERR_DRIVER_NOT_FOUND")
    if driver is not None and driver["carrier_id"] != carrier["id"]:
        raise err("ERR_DRIVER_CARRIER_MISMATCH",
                  "The driver is not employed by the attributed carrier.")

    buffer = timedelta(minutes=DUPLICATE_BUFFER_MINUTES)
    window_start = inspection_start.dt - buffer
    window_end = inspection_end.dt + buffer
    for existing in store.reports.values():
        if existing["vehicle_vin"] != vehicle_vin:
            continue
        if existing["status"] == "RESCINDED":
            continue
        if (existing["inspection_start"].dt <= window_end
                and existing["inspection_end"].dt >= window_start):
            raise err("ERR_DUPLICATE_INSPECTION_WINDOW",
                      "Another inspection of this vehicle overlaps the window.")
    for existing in store.reports.values():
        if existing["report_number"] == report_number:
            raise err("ERR_DUPLICATE_REPORT_NUMBER",
                      "This report_number already exists.")
    if (selection_source == "ISS_SCREENING"
            and carrier["selection_band"] not in ("OPTIONAL", "INSPECT")):
        raise err("ERR_SCREENING_SELECTION_INCONSISTENT",
                  "The carrier's screening band does not support an "
                  "ISS_SCREENING selection.")

    report = base_record()
    report.update({
        "report_number": report_number,
        "inspection_state": inspection_state,
        "inspection_level": inspection_level,
        "inspection_start": inspection_start,
        "inspection_end": inspection_end,
        "vehicle_vin": vehicle_vin,
        "attributed_carrier_id": carrier["id"],
        "original_carrier_id": None,
        "driver_id": driver["id"] if driver else None,
        "duplicate_master_report_id": None,
        "selection_source": selection_source,
        "iss_value_at_selection": carrier["iss_value"],
        "selection_band_at_selection": carrier["selection_band"],
        "status": "RECEIVED",
        "reattributed": False,
        "active_violation_count": 0,
        "total_time_weighted_severity": 0.0,
        "scored_at": None,
        "severity_basis_utc": None,
    })
    store.reports[report["id"]] = report
    return created(serialize(report))


@bp.get("/inspection-reports")
def list_reports():
    act = actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.reports), [
        ("attributed_carrier_id", q_str("attributed_carrier_id")),
        ("original_carrier_id", q_str("original_carrier_id")),
        ("driver_id", q_str("driver_id")),
        ("duplicate_master_report_id", q_str("duplicate_master_report_id")),
        ("status", q_enum("status", REPORT_STATUSES)),
        ("vehicle_vin", q_str("vehicle_vin")),
    ])
    rows = scope_rows(act, rows, "attributed_carrier_id")
    return listing(rows, limit, offset)


@bp.get("/inspection-reports/<report_id>")
def get_report(report_id):
    act = actor(*ALL_ROLES)
    report = get_or_404(store.reports, report_id, "ERR_REPORT_NOT_FOUND")
    scope(act, report["attributed_carrier_id"])
    return ok(serialize(report))


@bp.post("/inspection-reports/<report_id>/violations")
def append_violation(report_id):
    actor("StateInspectionOfficer")
    b = body()
    violation_code_id = get_str(b, "violation_code_id")
    unit_type = get_enum(b, "unit_type", UNIT_TYPES)
    out_of_service = get_bool(b, "out_of_service", required=False, default=False)
    driver_id = get_str(b, "driver_id", required=False)

    report = get_or_404(store.reports, report_id, "ERR_REPORT_NOT_FOUND")
    code = get_or_404(store.violation_codes, violation_code_id,
                      "ERR_VIOLATION_CODE_NOT_FOUND")
    driver = None
    if driver_id is not None:
        driver = get_or_404(store.drivers, driver_id, "ERR_DRIVER_NOT_FOUND")
    if driver is not None and driver["carrier_id"] != report["attributed_carrier_id"]:
        raise err("ERR_DRIVER_CARRIER_MISMATCH",
                  "The driver is not employed by the report's carrier.")
    if report["status"] != "RECEIVED":
        raise err("ERR_INVALID_REPORT_STATE",
                  "Violations may only be appended while the report is RECEIVED.")

    violation = base_record()
    violation.update({
        "report_id": report["id"],
        "violation_code_id": code["id"],
        "effective_violation_code_id": code["id"],
        "basic_category": code["basic_category"],
        "driver_id": driver["id"] if driver else None,
        "attributed_carrier_id": report["attributed_carrier_id"],
        "out_of_service": out_of_service,
        "unit_type": unit_type,
        "status": "ACTIVE",
        "removal_reason": None,
        "under_challenge": False,
        "code_weight_snapshot": None,
        "oos_add_on_snapshot": None,
        "pinned_violation_code_version": None,
        "time_weight": 0,
        "time_weighted_severity": 0.0,
    })
    store.violations[violation["id"]] = violation
    cascade.rollup_report(report)
    touch(report)
    return created(view_violation(violation))


@bp.post("/inspection-reports/<report_id>/validate")
def validate_report(report_id):
    actor("StateInspectionOfficer")
    report = get_or_404(store.reports, report_id, "ERR_REPORT_NOT_FOUND")
    if report["status"] != "RECEIVED":
        raise err("ERR_INVALID_REPORT_STATE",
                  "Only a RECEIVED report can be validated.")
    for violation in cascade.violations_of_report(report["id"]):
        if violation["status"] == "REMOVED":
            continue
        if violation["unit_type"] != "DRIVER":
            continue
        if not violation.get("driver_id") and not report.get("driver_id"):
            raise err("ERR_DRIVER_ATTRIBUTION_MISSING",
                      "A driver violation has no driver attribution.")
    report["status"] = "VALIDATED"
    touch(report)
    return ok(serialize(report))


@bp.post("/inspection-reports/<report_id>/score")
def score_report(report_id):
    actor("StateInspectionOfficer", "FmcsaProgramAuditor")
    report = get_or_404(store.reports, report_id, "ERR_REPORT_NOT_FOUND")
    if report["status"] not in ("VALIDATED", "AMENDED"):
        raise err("ERR_INVALID_REPORT_STATE",
                  "Only a VALIDATED or AMENDED report can be scored.")
    snapshot = store.now_ts()
    driver_ids = []
    for violation in cascade.violations_of_report(report["id"]):
        if violation["status"] in ACTIVE_STATUSES:
            if cascade.pin_violation(violation, report, snapshot.dt):
                touch(violation)
        if violation.get("driver_id"):
            driver_ids.append(violation["driver_id"])
    report["status"] = "SCORED"
    report["scored_at"] = snapshot
    report["severity_basis_utc"] = snapshot
    cascade.rollup_report(report)
    touch(report)
    cascade.cascade_carrier_id(report["attributed_carrier_id"],
                              snapshot_ts=snapshot, create=True, strict=True)
    cascade.recompute_drivers(driver_ids)
    return ok(serialize(report))


# ---------------------------------------------------------------------------
# amendments
# ---------------------------------------------------------------------------

@bp.post("/inspection-reports/<report_id>/amendments")
def create_amendment(report_id):
    actor("StateInspectionOfficer")
    b = body()
    expected_report_version = get_int(b, "expected_report_version", minimum=0)
    amendment_type = get_enum(b, "amendment_type", AMENDMENT_TYPES)
    rationale = get_str(b, "rationale", max_len=2000)
    target_violation_id = get_str(b, "target_violation_id", required=False)
    corrected_violation_code_id = get_str(b, "corrected_violation_code_id",
                                          required=False)
    corrected_driver_id = get_str(b, "corrected_driver_id", required=False)
    corrected_carrier_id = get_str(b, "corrected_carrier_id", required=False)

    report = get_or_404(store.reports, report_id, "ERR_REPORT_NOT_FOUND")
    target = None
    if target_violation_id is not None:
        target = get_or_404(store.violations, target_violation_id,
                            "ERR_VIOLATION_NOT_FOUND")
    corrected_code = None
    if corrected_violation_code_id is not None:
        corrected_code = get_or_404(store.violation_codes,
                                    corrected_violation_code_id,
                                    "ERR_VIOLATION_CODE_NOT_FOUND")
    corrected_driver = None
    if corrected_driver_id is not None:
        corrected_driver = get_or_404(store.drivers, corrected_driver_id,
                                      "ERR_DRIVER_NOT_FOUND")
    corrected_carrier = None
    if corrected_carrier_id is not None:
        corrected_carrier = get_or_404(store.carriers, corrected_carrier_id,
                                       "ERR_CARRIER_NOT_FOUND")

    if expected_report_version != report["version"]:
        raise err("ERR_STALE_REPORT_VERSION",
                  "The report has advanced since it was read.")
    if report["status"] not in AMENDABLE_REPORT_STATUSES:
        raise err("ERR_INVALID_REPORT_STATE",
                  "This report cannot be amended in its current state.")

    if amendment_type == "CARRIER_REATTRIBUTION":
        if corrected_carrier is None:
            raise err("ERR_AMENDMENT_PAYLOAD_INCOMPLETE",
                      "CARRIER_REATTRIBUTION requires corrected_carrier_id.")
        if corrected_carrier["id"] == report["attributed_carrier_id"]:
            raise err("ERR_AMENDMENT_PAYLOAD_INCOMPLETE",
                      "corrected_carrier_id must differ from the current carrier.")
    else:
        if target is None:
            raise err("ERR_AMENDMENT_PAYLOAD_INCOMPLETE",
                      "This amendment type requires target_violation_id.")
        if amendment_type == "VIOLATION_CODE_CORRECTION" and corrected_code is None:
            raise err("ERR_AMENDMENT_PAYLOAD_INCOMPLETE",
                      "VIOLATION_CODE_CORRECTION requires "
                      "corrected_violation_code_id.")
        if (amendment_type == "DRIVER_ATTRIBUTION_CORRECTION"
                and corrected_driver is None):
            raise err("ERR_AMENDMENT_PAYLOAD_INCOMPLETE",
                      "DRIVER_ATTRIBUTION_CORRECTION requires corrected_driver_id.")
    if target is not None and target["report_id"] != report["id"]:
        raise err("ERR_AMENDMENT_TARGET_MISMATCH",
                  "target_violation_id does not belong to this report.")

    was_scored = report["status"] == "SCORED"
    old_carrier_id = report["attributed_carrier_id"]
    version_before = report["version"]
    driver_ids = []

    if amendment_type == "VIOLATION_CODE_CORRECTION":
        target["effective_violation_code_id"] = corrected_code["id"]
        target["status"] = "RECODED"
        target["basic_category"] = corrected_code["basic_category"]
        if target.get("pinned_violation_code_version") is not None:
            # A code-correction amendment re-pins the snapshot from the new code.
            basis = report.get("severity_basis_utc")
            cascade.pin_violation(target, report,
                                  basis.dt if basis else store.now())
        touch(target)
        if target.get("driver_id"):
            driver_ids.append(target["driver_id"])
    elif amendment_type == "DRIVER_ATTRIBUTION_CORRECTION":
        if target.get("driver_id"):
            driver_ids.append(target["driver_id"])
        target["driver_id"] = corrected_driver["id"]
        touch(target)
        driver_ids.append(corrected_driver["id"])
    elif amendment_type == "CARRIER_REATTRIBUTION":
        report["original_carrier_id"] = old_carrier_id
        report["attributed_carrier_id"] = corrected_carrier["id"]
        report["reattributed"] = True
        for violation in cascade.violations_of_report(report["id"]):
            violation["attributed_carrier_id"] = corrected_carrier["id"]
            touch(violation)
            if violation.get("driver_id"):
                driver_ids.append(violation["driver_id"])
    else:  # VIOLATION_REMOVAL
        target["status"] = "REMOVED"
        target["removal_reason"] = "AMENDMENT_REMOVAL"
        target["time_weighted_severity"] = 0.0
        touch(target)
        if target.get("driver_id"):
            driver_ids.append(target["driver_id"])

    report["status"] = "AMENDED"
    cascade.rollup_report(report)
    touch(report)
    version_after = report["version"]

    if target is not None:
        cascade.waive_stale_assignments(target)

    amendment = base_record(with_version=False)
    amendment.update({
        "report_id": report["id"],
        "amendment_type": amendment_type,
        "target_violation_id": target["id"] if target else None,
        "corrected_violation_code_id": (corrected_code["id"] if corrected_code
                                        else None),
        "corrected_driver_id": (corrected_driver["id"] if corrected_driver
                                else None),
        "corrected_carrier_id": (corrected_carrier["id"] if corrected_carrier
                                 else None),
        "source_challenge_id": None,
        "rationale": rationale,
        "applied_at": store.now_ts(),
        "report_version_before": version_before,
        "report_version_after": version_after,
    })
    store.amendments[amendment["id"]] = amendment

    if was_scored:
        snapshot = cascade.epoch_for(old_carrier_id)
        cascade.cascade_carrier_id(old_carrier_id, snapshot_ts=snapshot,
                                   create=True)
        if amendment_type == "CARRIER_REATTRIBUTION":
            # PRD 3.7: for a CARRIER_REATTRIBUTION all four rows of the new
            # attributed carrier are recomputed as well, so they are minted
            # here when this is that carrier's first scoring event.
            cascade.cascade_carrier_id(corrected_carrier["id"],
                                       snapshot_ts=snapshot, create=True)
        cascade.recompute_drivers(driver_ids)
    else:
        cascade.recount_carrier_id(old_carrier_id)
        if amendment_type == "CARRIER_REATTRIBUTION":
            cascade.recount_carrier_id(corrected_carrier["id"])

    return created(serialize(amendment))


@bp.get("/report-amendments")
def list_amendments():
    actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.amendments), [
        ("report_id", q_str("report_id")),
        ("target_violation_id", q_str("target_violation_id")),
        ("corrected_violation_code_id", q_str("corrected_violation_code_id")),
        ("corrected_driver_id", q_str("corrected_driver_id")),
        ("corrected_carrier_id", q_str("corrected_carrier_id")),
        ("source_challenge_id", q_str("source_challenge_id")),
    ])
    return listing(rows, limit, offset)


@bp.get("/report-amendments/<amendment_id>")
def get_amendment(amendment_id):
    actor(*ALL_ROLES)
    amendment = get_or_404(store.amendments, amendment_id,
                           "ERR_AMENDMENT_NOT_FOUND")
    return ok(serialize(amendment))


# ---------------------------------------------------------------------------
# violations
# ---------------------------------------------------------------------------

@bp.get("/violations")
def list_violations():
    act = actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.violations), [
        ("report_id", q_str("report_id")),
        ("violation_code_id", q_str("violation_code_id")),
        ("effective_violation_code_id", q_str("effective_violation_code_id")),
        ("driver_id", q_str("driver_id")),
        ("attributed_carrier_id", q_str("attributed_carrier_id")),
        ("status", q_enum("status", VIOLATION_STATUSES)),
        ("basic_category", q_enum("basic_category", CATEGORIES)),
        ("under_challenge", q_bool("under_challenge")),
        ("out_of_service", q_bool("out_of_service")),
    ])
    rows = scope_rows(act, rows, "attributed_carrier_id")
    return listing(rows, limit, offset, view=view_violation)


@bp.get("/violations/<violation_id>")
def get_violation(violation_id):
    act = actor(*ALL_ROLES)
    violation = get_or_404(store.violations, violation_id,
                           "ERR_VIOLATION_NOT_FOUND")
    scope(act, violation["attributed_carrier_id"])
    return ok(view_violation(violation))


@bp.post("/violations/<violation_id>/driver-attribution")
def set_driver_attribution(violation_id):
    act = actor("CarrierSafetyManager")
    b = body()
    driver_id = get_str(b, "driver_id")
    violation = get_or_404(store.violations, violation_id,
                           "ERR_VIOLATION_NOT_FOUND")
    driver = get_or_404(store.drivers, driver_id, "ERR_DRIVER_NOT_FOUND")
    scope(act, violation["attributed_carrier_id"])
    if violation["status"] == "REMOVED":
        raise err("ERR_VIOLATION_NOT_ACTIVE",
                  "A removed violation cannot be attributed to a driver.")
    if driver["carrier_id"] != violation["attributed_carrier_id"]:
        raise err("ERR_DRIVER_CARRIER_MISMATCH",
                  "The driver is not employed by the violation's carrier.")
    previous_driver_id = violation.get("driver_id")
    violation["driver_id"] = driver["id"]
    touch(violation)
    cascade.waive_stale_assignments(violation)
    cascade.recompute_drivers([previous_driver_id, driver["id"]])
    cascade.recount_carrier_id(violation["attributed_carrier_id"])
    return ok(view_violation(violation))


@bp.delete("/violations/<violation_id>/driver-attribution")
def clear_driver_attribution(violation_id):
    act = actor("CarrierSafetyManager")
    violation = get_or_404(store.violations, violation_id,
                           "ERR_VIOLATION_NOT_FOUND")
    scope(act, violation["attributed_carrier_id"])
    previous_driver_id = violation.get("driver_id")
    violation["driver_id"] = None
    touch(violation)
    cascade.waive_for_attribution_change(violation["id"], previous_driver_id)
    cascade.recompute_drivers([previous_driver_id])
    cascade.recount_carrier_id(violation["attributed_carrier_id"])
    return ok(view_violation(violation))
