"""Test labs, mockup tests, field tests and defect items."""

from flask import Blueprint

import calc
import domain
from common import created, get_or_404, listing, single
from errors import ApiError
from store import apply, base_row, collection, db, fmt_dt, now_iso, parse_dt
from validate import (
    DEFECT_ORIGINS,
    DEFECT_SEVERITIES,
    DEFECT_STATUSES,
    F,
    FIELD_TEST_KINDS,
    FIELD_TEST_STATES,
    MOCKUP_STATES,
    REINSPECT_OUTCOMES,
    auth,
    body,
    check_window,
    q_enum,
    q_str,
    read_fields,
    require_user,
    user_id,
)

bp = Blueprint("qc", __name__)


# ==========================================================================
# TestLab (immutable reference row: no version, no update path)
# ==========================================================================
LAB_SPECS = (
    F("name", "string"),
    F("chamber_capacity", "int", rng=lambda v: v >= 1),
    F("accreditation_ref", "string"),
)


@bp.post("/test-labs")
def create_lab():
    auth("CWProjectManager")
    values = read_fields(body(), LAB_SPECS)
    row = base_row(versioned=False)
    row.update(
        {
            "name": values["name"],
            "chamber_capacity": values["chamber_capacity"],
            "accreditation_ref": values["accreditation_ref"],
        }
    )
    db.labs[row["id"]] = row
    return created(row, domain.ser_lab)


@bp.get("/test-labs")
def list_labs():
    auth()
    rows = collection(db.labs, name=q_str("name"))
    return listing(rows, domain.ser_lab)


@bp.get("/test-labs/<lab_id>")
def read_lab(lab_id):
    auth()
    row = get_or_404(db.labs, lab_id, "ERR_RESOURCE_NOT_FOUND")
    return single(row, domain.ser_lab)


# ==========================================================================
# MockupTest
# ==========================================================================
MOCKUP_SPECS = (
    F("package_id", "string"),
    F("test_lab_id", "string"),
    F("retest_of_test_id", "string", required=False),
    F("attempt_no", "int", required=False, default=1, rng=lambda v: v >= 1),
    F("window_start", "datetime"),
    F("window_end", "datetime"),
    F("chambers_required", "int", rng=lambda v: v >= 1),
)


@bp.post("/mockup-tests")
def create_mockup():
    auth("CWProjectManager", "QCInspector")
    values = read_fields(body(), MOCKUP_SPECS)
    window_start = values["window_start"]
    window_end = values["window_end"]
    check_window(window_start, window_end)

    package = get_or_404(db.packages, values["package_id"], "ERR_PACKAGE_NOT_FOUND")
    retest_of = values["retest_of_test_id"]
    if retest_of is not None:
        get_or_404(db.mockups, retest_of, "ERR_TEST_NOT_FOUND")
    lab = get_or_404(db.labs, values["test_lab_id"], "ERR_RESOURCE_NOT_FOUND")

    occupied = 0
    for other in db.mockups.values():
        if other["test_lab_id"] != lab["id"] or other["state"] != "SCHEDULED":
            continue
        other_start = parse_dt(other["window_start"])
        other_end = parse_dt(other["window_end"])
        if other_start is None or other_end is None:
            continue
        if window_start < other_end and window_end > other_start:
            occupied += int(other["chambers_required"])
    if occupied + int(values["chambers_required"]) > int(lab["chamber_capacity"]):
        raise ApiError("ERR_LAB_CAPACITY_EXCEEDED")

    hours, subtotal, surcharge, total = calc.mockup_invoice_cents(
        window_start, window_end, values["chambers_required"], retest_of is not None
    )
    row = base_row()
    row.update(
        {
            "package_id": package["id"],
            "test_lab_id": lab["id"],
            "retest_of_test_id": retest_of,
            "attempt_no": values["attempt_no"],
            "window_start": fmt_dt(window_start),
            "window_end": fmt_dt(window_end),
            "chambers_required": values["chambers_required"],
            "state": "SCHEDULED",
            "chamber_hours": hours,
            "invoice_subtotal_cents": subtotal,
            "surcharge_cents": surcharge,
            "invoice_cents": total,
            "air_infiltration_cfm": None,
            "water_penetration_observed": None,
            "structural_deflection_mm": None,
            "result_recorded_at": None,
        }
    )
    db.mockups[row["id"]] = row
    return created(row, domain.ser_mockup)


@bp.get("/mockup-tests")
def list_mockups():
    auth()
    rows = collection(
        db.mockups,
        package_id=q_str("package_id"),
        test_lab_id=q_str("test_lab_id"),
        retest_of_test_id=q_str("retest_of_test_id"),
        state=q_enum("state", MOCKUP_STATES),
    )
    return listing(rows, domain.ser_mockup)


@bp.get("/mockup-tests/<test_id>")
def read_mockup(test_id):
    auth()
    row = get_or_404(db.mockups, test_id, "ERR_TEST_NOT_FOUND")
    return single(row, domain.ser_mockup)


@bp.post("/mockup-tests/<test_id>/record-result")
def record_mockup_result(test_id):
    auth("QCInspector")
    acting = user_id()
    values = read_fields(
        body(),
        (
            F("water_penetration_observed", "bool"),
            F("air_infiltration_cfm", "num"),
            F("structural_deflection_mm", "num"),
        ),
    )
    test = get_or_404(db.mockups, test_id, "ERR_TEST_NOT_FOUND")
    if test["state"] in ("PASSED", "FAILED"):
        raise ApiError("ERR_TERMINAL_STATE")
    if test["state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    passed = (
        not bool(values["water_penetration_observed"])
        and calc.D(values["air_infiltration_cfm"]) < calc.AIR_LEAKAGE_LIMIT_CFM
        and calc.D(values["structural_deflection_mm"]) < calc.MOCKUP_DEFLECTION_LIMIT_MM
    )
    hours, subtotal, surcharge, total = calc.mockup_invoice_cents(
        parse_dt(test["window_start"]),
        parse_dt(test["window_end"]),
        test["chambers_required"],
        test["retest_of_test_id"] is not None,
    )
    apply(
        test,
        {
            "state": "PASSED" if passed else "FAILED",
            "water_penetration_observed": bool(values["water_penetration_observed"]),
            "air_infiltration_cfm": values["air_infiltration_cfm"],
            "structural_deflection_mm": values["structural_deflection_mm"],
            "result_recorded_at": now_iso(),
            "chamber_hours": hours,
            "invoice_subtotal_cents": subtotal,
            "surcharge_cents": surcharge,
            "invoice_cents": total,
        },
    )

    package = db.packages.get(test["package_id"])
    if package is not None:
        if passed:
            extra = None
            if package["state"] == "SYSTEM_SELECTED":
                extra = {"state": "MOCKUP_QUALIFIED"}
            domain.sync_package(package, extra)
        else:
            defect = base_row()
            defect.update(
                {
                    "package_id": package["id"],
                    "zone_id": None,
                    "field_test_id": None,
                    "mockup_test_id": test["id"],
                    "origin": "MOCKUP_TEST",
                    "severity": "CRITICAL",
                    "description": "Mockup test failed performance criteria",
                    "status": "OPEN",
                    "raised_by_user_id": acting,
                    "remediation_note": None,
                    "reinspected_by_user_id": None,
                    "reinspect_fail_count": 0,
                    "waiver_ref": None,
                    "closed_at": None,
                }
            )
            db.defects[defect["id"]] = defect
            domain.sync_package(package)
    return single(test, domain.ser_mockup)


# ==========================================================================
# FieldTest
# ==========================================================================
FIELD_TEST_SPECS = (
    F("test_kind", "enum", enum=FIELD_TEST_KINDS),
    F("scheduled_for", "datetime"),
    F("attempt_no", "int", required=False, default=1, rng=lambda v: v >= 1),
)


@bp.post("/installation-zones/<zone_id>/field-tests")
def create_field_test(zone_id):
    auth("QCInspector")
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    values = read_fields(body(), FIELD_TEST_SPECS)
    package = domain.zone_package(zone)
    if values["test_kind"] == "STRUCTURAL_DEFLECTION":
        if package is None or package["system_type"] == "UNDECIDED":
            raise ApiError("ERR_DEFLECTION_LIMIT_UNSET")

    row = base_row()
    row.update(
        {
            "zone_id": zone["id"],
            "test_kind": values["test_kind"],
            "scheduled_for": fmt_dt(values["scheduled_for"]),
            "attempt_no": values["attempt_no"],
            "state": "SCHEDULED",
            "water_penetration_observed": None,
            "measured_air_leakage_cfm": None,
            "measured_deflection_mm": None,
            "outcome_reason": None,
            "recorded_by_user_id": None,
            "result_recorded_at": None,
        }
    )
    db.field_tests[row["id"]] = row
    return created(row, domain.ser_field_test)


@bp.get("/field-tests")
def list_field_tests():
    auth()
    rows = collection(
        db.field_tests,
        zone_id=q_str("zone_id"),
        test_kind=q_enum("test_kind", FIELD_TEST_KINDS),
        state=q_enum("state", FIELD_TEST_STATES),
    )
    return listing(rows, domain.ser_field_test)


@bp.get("/field-tests/<test_id>")
def read_field_test(test_id):
    auth()
    row = get_or_404(db.field_tests, test_id, "ERR_TEST_NOT_FOUND")
    return single(row, domain.ser_field_test)


MEASUREMENT_BY_KIND = {
    "WATER_AAMA_501_2": ("water_penetration_observed", "bool"),
    "AIR_INFILTRATION": ("measured_air_leakage_cfm", "num"),
    "STRUCTURAL_DEFLECTION": ("measured_deflection_mm", "num"),
}


@bp.post("/field-tests/<test_id>/record-result")
def record_field_test_result(test_id):
    auth("QCInspector")
    acting = user_id()
    payload = body()
    test = get_or_404(db.field_tests, test_id, "ERR_TEST_NOT_FOUND")

    field_name, field_kind = MEASUREMENT_BY_KIND[test["test_kind"]]
    values = read_fields(payload, (F(field_name, field_kind),))

    if test["state"] in ("PASSED", "FAILED"):
        raise ApiError("ERR_TERMINAL_STATE")
    if test["state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    zone = db.zones.get(test["zone_id"])
    if zone is None or zone["install_status"] != "PANELS_HUNG":
        raise ApiError("ERR_INVALID_STATE")

    measurement = values[field_name]
    updates = {"recorded_by_user_id": acting, "result_recorded_at": now_iso()}
    if test["test_kind"] == "WATER_AAMA_501_2":
        passed = not bool(measurement)
        updates["water_penetration_observed"] = bool(measurement)
        reason = "WITHIN_TOLERANCE" if passed else "WATER_PENETRATION"
    elif test["test_kind"] == "AIR_INFILTRATION":
        passed = calc.D(measurement) < calc.AIR_LEAKAGE_LIMIT_CFM
        updates["measured_air_leakage_cfm"] = measurement
        reason = "WITHIN_TOLERANCE" if passed else "AIR_LEAKAGE_EXCEEDED"
    else:
        limit = zone["deflection_limit_mm"]
        passed = limit is not None and calc.D(measurement) < calc.D(limit)
        updates["measured_deflection_mm"] = measurement
        reason = "WITHIN_TOLERANCE" if passed else "DEFLECTION_EXCEEDED"
    updates["state"] = "PASSED" if passed else "FAILED"
    updates["outcome_reason"] = reason
    apply(test, updates)

    if not passed:
        severity = "MAJOR" if reason == "AIR_LEAKAGE_EXCEEDED" else "CRITICAL"
        defect = base_row()
        defect.update(
            {
                "package_id": zone["package_id"],
                "zone_id": zone["id"],
                "field_test_id": test["id"],
                "mockup_test_id": None,
                "origin": "FIELD_TEST",
                "severity": severity,
                "description": "Field test failed: %s" % reason,
                "status": "OPEN",
                "raised_by_user_id": acting,
                "remediation_note": None,
                "reinspected_by_user_id": None,
                "reinspect_fail_count": 0,
                "waiver_ref": None,
                "closed_at": None,
            }
        )
        db.defects[defect["id"]] = defect
        domain.revert_zone_weather(zone)
        package = domain.zone_package(zone)
        if package is not None:
            domain.sync_package(package)
    return single(test, domain.ser_field_test)


# ==========================================================================
# DefectItem
# ==========================================================================
DEFECT_SPECS = (
    F("package_id", "string"),
    F("zone_id", "string", required=False),
    F("field_test_id", "string", required=False),
    F("mockup_test_id", "string", required=False),
    F("origin", "enum", enum=DEFECT_ORIGINS),
    F("severity", "enum", enum=DEFECT_SEVERITIES),
    F("description", "string"),
)


@bp.post("/defect-items")
def create_defect():
    auth("QCInspector", "ArchitectOfRecord")
    acting = user_id()
    values = read_fields(body(), DEFECT_SPECS)
    package = get_or_404(db.packages, values["package_id"], "ERR_PACKAGE_NOT_FOUND")

    zone_id = values["zone_id"]
    if zone_id is not None:
        zone = db.zones.get(zone_id)
        if zone is None or zone["package_id"] != package["id"]:
            raise ApiError("ERR_ZONE_NOT_FOUND")
    if values["field_test_id"] is not None:
        get_or_404(db.field_tests, values["field_test_id"], "ERR_TEST_NOT_FOUND")
    if values["mockup_test_id"] is not None:
        get_or_404(db.mockups, values["mockup_test_id"], "ERR_TEST_NOT_FOUND")

    row = base_row()
    row.update(
        {
            "package_id": package["id"],
            "zone_id": zone_id,
            "field_test_id": values["field_test_id"],
            "mockup_test_id": values["mockup_test_id"],
            "origin": values["origin"],
            "severity": values["severity"],
            "description": values["description"],
            "status": "OPEN",
            "raised_by_user_id": acting,
            "remediation_note": None,
            "reinspected_by_user_id": None,
            "reinspect_fail_count": 0,
            "waiver_ref": None,
            "closed_at": None,
        }
    )
    db.defects[row["id"]] = row
    domain.sync_package(package)
    return created(row, domain.ser_defect)


@bp.get("/defect-items")
def list_defects():
    auth()
    rows = collection(
        db.defects,
        package_id=q_str("package_id"),
        zone_id=q_str("zone_id"),
        field_test_id=q_str("field_test_id"),
        mockup_test_id=q_str("mockup_test_id"),
        status=q_enum("status", DEFECT_STATUSES),
        severity=q_enum("severity", DEFECT_SEVERITIES),
        origin=q_enum("origin", DEFECT_ORIGINS),
    )
    return listing(rows, domain.ser_defect)


@bp.get("/defect-items/<item_id>")
def read_defect(item_id):
    auth()
    row = get_or_404(db.defects, item_id, "ERR_DEFECT_NOT_FOUND")
    return single(row, domain.ser_defect)


@bp.post("/defect-items/<item_id>/submit-remediation")
def submit_remediation(item_id):
    auth("CWDetailer")
    values = read_fields(body(), (F("remediation_note", "string"),))
    item = get_or_404(db.defects, item_id, "ERR_DEFECT_NOT_FOUND")
    if item["status"] in ("CLOSED", "WAIVED"):
        raise ApiError("ERR_TERMINAL_STATE")
    if item["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    apply(
        item,
        {
            "status": "REMEDIATION_SUBMITTED",
            "remediation_note": values["remediation_note"],
        },
    )
    package = db.packages.get(item["package_id"])
    if package is not None:
        domain.sync_package(package)
    return single(item, domain.ser_defect)


@bp.post("/defect-items/<item_id>/reinspect")
def reinspect_defect(item_id):
    auth("QCInspector")
    acting = require_user()
    values = read_fields(body(), (F("outcome", "enum", enum=REINSPECT_OUTCOMES),))
    item = get_or_404(db.defects, item_id, "ERR_DEFECT_NOT_FOUND")
    if item["status"] in ("CLOSED", "WAIVED"):
        raise ApiError("ERR_TERMINAL_STATE")
    if item["status"] != "REMEDIATION_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    if item["raised_by_user_id"] is not None and acting == item["raised_by_user_id"]:
        raise ApiError("ERR_INSPECTOR_CONFLICT")

    if values["outcome"] == "PASS":
        apply(
            item,
            {
                "status": "CLOSED",
                "reinspected_by_user_id": acting,
                "closed_at": now_iso(),
            },
        )
    else:
        apply(
            item,
            {
                "status": "OPEN",
                "reinspected_by_user_id": acting,
                "reinspect_fail_count": int(item["reinspect_fail_count"]) + 1,
                "remediation_note": None,
            },
        )
    package = db.packages.get(item["package_id"])
    if package is not None:
        domain.sync_package(package)
    return single(item, domain.ser_defect)


@bp.post("/defect-items/<item_id>/waive")
def waive_defect(item_id):
    auth("ArchitectOfRecord")
    values = read_fields(body(), (F("waiver_ref", "string"),))
    item = get_or_404(db.defects, item_id, "ERR_DEFECT_NOT_FOUND")
    if item["status"] in ("CLOSED", "WAIVED"):
        raise ApiError("ERR_TERMINAL_STATE")
    if item["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    if item["severity"] == "CRITICAL":
        raise ApiError("ERR_WAIVER_NOT_PERMITTED")
    apply(
        item,
        {
            "status": "WAIVED",
            "waiver_ref": values["waiver_ref"],
            "closed_at": now_iso(),
        },
    )
    package = db.packages.get(item["package_id"])
    if package is not None:
        domain.sync_package(package)
    return single(item, domain.ser_defect)
