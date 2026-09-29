"""ShellTest endpoints (PRD 3.5, 3.6)."""
from flask import Blueprint

import calc
import cascades
import db
import helpers
import serialize
import validate
from auth import authorize
from db import touch
from errors import ApiError
from util import add_minutes, date_key

bp = Blueprint("shell_tests", __name__)

READ_ROLES = ("PlantManager", "Technician", "CertifyingInspector", "ComplianceOfficer")


@bp.post("/shell-tests")
def create_shell_test():
    authorize(("Technician",))
    data = validate.body()
    equipment_unit_id = validate.req_id(data, "equipment_unit_id")
    test_bench_id = validate.req_id(data, "test_bench_id")
    (start, start_raw), (end, end_raw) = validate.req_window(data)
    conditioning = validate.req_enum(data, "conditioning", calc.CONDITIONINGS)
    unit = helpers.unit(equipment_unit_id)
    bench = helpers.bench(test_bench_id)

    if unit["recon_status"] not in ("INSPECTED", "REPAIRED"):
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "Bench sessions are only defined for INSPECTED or REPAIRED units.")
    if unit["inspection_verdict_summary"] == "PENDING":
        raise ApiError("ERR_INSPECTION_INCOMPLETE",
                       "Every required component must be inspected before testing.")
    model = cascades.model_of(unit)
    if model is not None and unit["retest_count"] >= model["max_retest_count"]:
        raise ApiError("ERR_RETEST_LIMIT_EXCEEDED",
                       "The unit has reached its model's retest ceiling.")

    # PRD 3.5: the requested window is expanded by the cooldown on both sides and
    # both intervals are closed, so touching endpoints do collide.
    cooldown = bench["cooldown_minutes"] or 0
    guard_start = add_minutes(start, -cooldown)
    guard_end = add_minutes(end, cooldown)
    same_day = 0
    for row in db.db.shell_tests.values():
        if row["test_bench_id"] != bench["id"]:
            continue
        if guard_start <= row["window_end"] and row["window_start"] <= guard_end:
            raise ApiError("ERR_BENCH_WINDOW_CONFLICT",
                           "The rig is occupied within its cooldown envelope.")
        if date_key(row["window_start"]) == date_key(start):
            same_day += 1
    if same_day >= bench["daily_session_quota"]:
        raise ApiError("ERR_BENCH_DAILY_QUOTA_EXCEEDED",
                       "The rig has reached its daily session quota.")

    previous = [row for row in db.db.shell_tests.values()
                if row["equipment_unit_id"] == unit["id"]]
    attempt_index = 1 + max([row["attempt_index"] for row in previous] or [0])

    record = db.base_record()
    record.update({
        "equipment_unit_id": unit["id"],
        "test_bench_id": bench["id"],
        "window_start": start,
        "window_end": end,
        "conditioning": conditioning,
        "attempt_index": attempt_index,
        "peak_g_front": None,
        "peak_g_side": None,
        "peak_g_crown": None,
        "severity_index": None,
        "computed_result": None,
        "determination": None,
        "override_reason": None,
        "determined_by_user_id": None,
        "status": "SCHEDULED",
    })
    db.raw_set(record, "window_start", start_raw)
    db.raw_set(record, "window_end", end_raw)
    db.db.shell_tests[record["id"]] = record

    retest_count = attempt_index - 1
    if unit["retest_count"] != retest_count:
        unit["retest_count"] = retest_count
        touch(unit)
    return helpers.single(record, serialize.shell_test, 201)


@bp.get("/shell-tests/<row_id>")
def get_shell_test(row_id):
    authorize(READ_ROLES)
    return helpers.single(helpers.shell_test(row_id), serialize.shell_test)


@bp.get("/shell-tests")
def list_shell_tests():
    authorize(READ_ROLES)
    filters = {
        "equipment_unit_id": validate.query_str("equipment_unit_id"),
        "test_bench_id": validate.query_str("test_bench_id"),
        "status": validate.query_enum("status", calc.SHELL_TEST_STATUSES),
    }
    return helpers.listing("shell_tests", serialize.shell_test, filters)


@bp.post("/shell-tests/<row_id>/record-impacts")
def record_impacts(row_id):
    authorize(("Technician",))
    data = validate.body()
    peak_g_front = validate.req_num(data, "peak_g_front", minimum=0)
    peak_g_side = validate.req_num(data, "peak_g_side", minimum=0)
    peak_g_crown = validate.req_num(data, "peak_g_crown", minimum=0)
    record = helpers.shell_test(row_id)

    if record["status"] != "SCHEDULED":
        raise ApiError("ERR_SHELL_TEST_STATE_INVALID",
                       "Impacts may only be recorded against a SCHEDULED session.")
    unit = db.db.equipment_units.get(record["equipment_unit_id"])
    if unit is None or unit["recon_status"] not in ("INSPECTED", "REPAIRED"):
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "The unit is not in a status from which testing is defined.")
    bench = db.db.test_benches.get(record["test_bench_id"])
    valid_until = bench["calibration_valid_until"] if bench else None
    if valid_until is None or valid_until < db.now():
        raise ApiError("ERR_BENCH_CALIBRATION_EXPIRED",
                       "The rig's calibration is not current.")

    model = cascades.model_of(unit)
    record["peak_g_front"] = peak_g_front
    record["peak_g_side"] = peak_g_side
    record["peak_g_crown"] = peak_g_crown
    severity = calc.severity_index(peak_g_front, peak_g_side, peak_g_crown,
                                   record["conditioning"], model["shell_material"])
    record["severity_index"] = severity
    record["computed_result"] = calc.computed_result(severity, model["pass_si_max"],
                                                    model["repair_si_max"])
    record["status"] = "COMPLETED"
    touch(record)

    unit["recon_status"] = "TESTED"
    unit["current_si"] = severity
    touch(unit)
    return helpers.single(record, serialize.shell_test)


@bp.post("/shell-tests/<row_id>/determine")
def determine_shell_test(row_id):
    caller = authorize(("CertifyingInspector",))
    data = validate.body()
    determination = validate.req_enum(data, "determination", calc.DETERMINATIONS)
    override_reason = validate.opt_str(data, "override_reason", max_len=1000)
    record = helpers.shell_test(row_id)

    if record["status"] != "COMPLETED":
        raise ApiError("ERR_SHELL_TEST_STATE_INVALID",
                       "Determinations are only signed on a COMPLETED session.")
    unit = db.db.equipment_units.get(record["equipment_unit_id"])
    if unit is None or unit["recon_status"] != "TESTED":
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "The unit is not in TESTED, so no determination branch applies.")
    if unit["condemn_required"] and determination != "CONDEMN":
        raise ApiError("ERR_CONDEMN_REQUIRED",
                       "This unit must be condemned; no other determination is allowed.")
    computed = record["computed_result"]
    if determination != computed and override_reason is None:
        raise ApiError("ERR_DETERMINATION_MISMATCH",
                       "An override_reason is required to depart from the machine result.")
    if (override_reason is not None
            and calc.DETERMINATION_SEVERITY[determination]
            < calc.DETERMINATION_SEVERITY[computed]):
        raise ApiError("ERR_DETERMINATION_UPGRADE_FORBIDDEN",
                       "An inspector may be stricter than the rig, never more lenient.")

    record["determination"] = determination
    record["override_reason"] = override_reason
    record["determined_by_user_id"] = caller.user_id
    record["status"] = "DETERMINED"
    touch(record)

    if determination == "PASS":
        unit["recon_status"] = "TEST_PASSED"
        touch(unit)
    elif determination == "REPAIR":
        unit["recon_status"] = "REPAIR_PENDING"
        touch(unit)
    else:
        if unit["life_expired"]:
            reason = "LIFE_EXPIRED"
        elif unit["inspection_verdict_summary"] == "FAIL":
            reason = "COMPONENT_FAIL"
        else:
            reason = "SI_EXCEEDS_LIMIT"
        cascades.condemn_cascade(unit, reason)
    return helpers.single(record, serialize.shell_test)
