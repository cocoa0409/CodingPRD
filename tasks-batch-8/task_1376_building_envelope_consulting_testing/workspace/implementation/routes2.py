"""API routes — part 2: chamber slots, mock-ups, field tests, surveys, anomalies."""
from decimal import Decimal

from flask import request

from db import STORE, clock_now
from errors import (
    ERR_ANOMALY_NOT_OPEN,
    ERR_ASSEMBLY_NOT_APPROVED,
    ERR_DIAGNOSIS_INCOMPLETE,
    ERR_DUTY_SEGREGATION_VIOLATION,
    ERR_ENGAGEMENT_FROZEN,
    ERR_FIELD_TEST_NOT_ACTIONABLE,
    ERR_IMAGING_DELTA_T_INSUFFICIENT,
    ERR_INVALID_REQUEST,
    ERR_MOCKUP_NOT_ACTIONABLE,
    ERR_NOT_FOUND,
    ERR_OUTSIDE_SLOT_WINDOW,
    ERR_SLOT_IN_USE,
    ERR_SLOT_NOT_RESERVED,
    ERR_SURVEY_NOT_ACTIONABLE,
    ERR_WINDOW_OVERLAP,
    raise_err,
)
from middleware import ANY_ROLE, auth, require_role
from response import ok
from routes import (
    bp,
    get_child,
    get_engagement,
    list_response,
    require_in_progress,
    require_not_frozen,
)
from services import (
    FIELD_TEST_FAIL_DELTA,
    MOCKUP_FAIL_DELTA,
    VERIFY_DELTAS,
    apply_fee_delta,
    apply_risk_delta,
    field_test_result,
    fiscal_gate,
    mockup_testing_fee,
    new_common,
    ser_anomaly,
    ser_chamber_slot,
    ser_field_test,
    ser_mock_up,
    ser_survey,
    touch,
)
from validators import (
    get_body,
    opt_int,
    parse_date,
    req_enum,
    req_int,
    req_num,
    req_str,
)

TEST_METHODS = {"ASTM_E1105", "ASTM_E783", "AAMA_502"}
SURVEY_TYPES = {"THERMAL_IMAGING", "MOISTURE", "COMBINED"}
ANOMALY_TYPES = {"WATER_INGRESS", "AIR_LEAKAGE", "THERMAL_BRIDGE", "MOISTURE_TRAP"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
LIVE_MOCKUP_STATES = {"PLANNED", "CONSTRUCTING", "READY_FOR_TEST", "REMEDIATED"}


# ---------------------------------------------------------------------------
# ChamberSlot
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/chamber-slots", methods=["POST"], strict_slashes=False)
def create_chamber_slot(engagement_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    body = get_body()
    chamber_code = req_str(body, "chamber_code")
    start_s = req_str(body, "start_date")
    end_s = req_str(body, "end_date")
    start_d = parse_date(start_s, "start_date")
    end_d = parse_date(end_s, "end_date")
    if not (end_d > start_d):
        raise_err(ERR_INVALID_REQUEST, "end_date must be strictly later than start_date")
    daily_rate = req_int(body, "daily_rate_cents", lo=1)
    require_in_progress(eng)
    # Half-open overlap: same chamber_code, same engagement, RESERVED/CONSUMED.
    # Windows touching at a boundary day do not conflict.
    for s in STORE["chamber_slots"].values():
        if (
            s["engagement_id"] == eng["id"]
            and s["chamber_code"] == chamber_code
            and s["status"] in ("RESERVED", "CONSUMED")
            and start_d < s["_end_date"]
            and s["_start_date"] < end_d
        ):
            raise_err(
                ERR_WINDOW_OVERLAP,
                "Chamber slot window overlaps an existing reservation",
            )
    slot = new_common()
    slot.update(
        {
            "engagement_id": eng["id"],
            "chamber_code": chamber_code,
            "start_date": start_s,
            "end_date": end_s,
            "_start_date": start_d,
            "_end_date": end_d,
            "daily_rate_cents": daily_rate,
            "status": "RESERVED",
        }
    )
    STORE["chamber_slots"][slot["id"]] = slot
    return ok(ser_chamber_slot(slot), status=201)


@bp.route("/engagements/<engagement_id>/chamber-slots", methods=["GET"], strict_slashes=False)
def list_chamber_slots(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return list_response(
        [s for s in STORE["chamber_slots"].values() if s["engagement_id"] == eng["id"]],
        ser_chamber_slot,
    )


@bp.route("/engagements/<engagement_id>/chamber-slots/<slot_id>", methods=["GET"], strict_slashes=False)
def get_chamber_slot_route(engagement_id, slot_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return ok(ser_chamber_slot(get_child("chamber_slots", slot_id, eng["id"], "ChamberSlot")))


@bp.route(
    "/engagements/<engagement_id>/chamber-slots/<slot_id>/release",
    methods=["POST"],
    strict_slashes=False,
)
def release_chamber_slot(engagement_id, slot_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    slot = get_child("chamber_slots", slot_id, eng["id"], "ChamberSlot")
    require_in_progress(eng)
    if slot["status"] != "RESERVED":
        raise_err(ERR_SLOT_NOT_RESERVED, "release requires slot status RESERVED")
    if any(
        m["chamber_slot_id"] == slot["id"] and m["status"] in LIVE_MOCKUP_STATES
        for m in STORE["mock_ups"].values()
        if m["engagement_id"] == eng["id"]
    ):
        raise_err(ERR_SLOT_IN_USE, "A live mock-up references this slot")
    slot["status"] = "RELEASED"
    touch(slot)
    return ok(ser_chamber_slot(slot))


# ---------------------------------------------------------------------------
# MockUp
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/mock-ups", methods=["POST"], strict_slashes=False)
def create_mock_up(engagement_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    body = get_body()
    assembly_id = req_str(body, "assembly_id")
    chamber_slot_id = req_str(body, "chamber_slot_id")
    specimen_count = req_int(body, "specimen_count", lo=1)
    require_in_progress(eng)
    get_child("assemblies", assembly_id, eng["id"], "Assembly")
    get_child("chamber_slots", chamber_slot_id, eng["id"], "ChamberSlot")
    m = new_common()
    m.update(
        {
            "engagement_id": eng["id"],
            "assembly_id": assembly_id,
            "chamber_slot_id": chamber_slot_id,
            "specimen_count": specimen_count,
            "air_leakage_lps_m2": None,
            "testing_fee_cents": None,
            "attempt_number": 1,
            "status": "PLANNED",
        }
    )
    STORE["mock_ups"][m["id"]] = m
    return ok(ser_mock_up(m), status=201)


@bp.route("/engagements/<engagement_id>/mock-ups", methods=["GET"], strict_slashes=False)
def list_mock_ups(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    items = [m for m in STORE["mock_ups"].values() if m["engagement_id"] == eng["id"]]
    assembly_id = request.args.get("assembly_id")
    if assembly_id is not None:
        items = [m for m in items if m["assembly_id"] == assembly_id]
    return list_response(items, ser_mock_up)


@bp.route("/engagements/<engagement_id>/mock-ups/<mockup_id>", methods=["GET"], strict_slashes=False)
def get_mock_up_route(engagement_id, mockup_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return ok(ser_mock_up(get_child("mock_ups", mockup_id, eng["id"], "MockUp")))


def _mockup_transition(engagement_id, mockup_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    m = get_child("mock_ups", mockup_id, eng["id"], "MockUp")
    require_in_progress(eng)
    return eng, m


@bp.route(
    "/engagements/<engagement_id>/mock-ups/<mockup_id>/begin-construction",
    methods=["POST"],
    strict_slashes=False,
)
def mockup_begin_construction(engagement_id, mockup_id):
    eng, m = _mockup_transition(engagement_id, mockup_id)
    require_not_frozen(eng)
    if m["status"] != "PLANNED":
        raise_err(ERR_MOCKUP_NOT_ACTIONABLE, "begin-construction requires PLANNED")
    m["status"] = "CONSTRUCTING"
    touch(m)
    return ok(ser_mock_up(m))


@bp.route(
    "/engagements/<engagement_id>/mock-ups/<mockup_id>/declare-ready",
    methods=["POST"],
    strict_slashes=False,
)
def mockup_declare_ready(engagement_id, mockup_id):
    eng, m = _mockup_transition(engagement_id, mockup_id)
    if m["status"] != "CONSTRUCTING":
        raise_err(ERR_MOCKUP_NOT_ACTIONABLE, "declare-ready requires CONSTRUCTING")
    m["status"] = "READY_FOR_TEST"
    touch(m)
    return ok(ser_mock_up(m))


@bp.route(
    "/engagements/<engagement_id>/mock-ups/<mockup_id>/begin-testing",
    methods=["POST"],
    strict_slashes=False,
)
def mockup_begin_testing(engagement_id, mockup_id):
    eng, m = _mockup_transition(engagement_id, mockup_id)
    if m["status"] == "READY_FOR_TEST":
        slot = get_child("chamber_slots", m["chamber_slot_id"], eng["id"], "ChamberSlot")
        if slot["status"] != "RESERVED":
            raise_err(ERR_SLOT_NOT_RESERVED, "Bound chamber slot is not RESERVED")
    elif m["status"] == "REMEDIATED":
        body = get_body()
        new_slot_id = body.get("new_chamber_slot_id")
        slot = None
        if isinstance(new_slot_id, str):
            candidate = STORE["chamber_slots"].get(new_slot_id)
            if candidate is not None and candidate["engagement_id"] == eng["id"]:
                slot = candidate
        if slot is None or slot["status"] != "RESERVED":
            raise_err(
                ERR_SLOT_NOT_RESERVED,
                "new_chamber_slot_id must reference a RESERVED slot of this engagement",
            )
    else:
        raise_err(
            ERR_MOCKUP_NOT_ACTIONABLE,
            "begin-testing requires READY_FOR_TEST or REMEDIATED",
        )
    today = clock_now().date()
    if not (slot["_start_date"] <= today < slot["_end_date"]):
        raise_err(
            ERR_OUTSIDE_SLOT_WINDOW,
            "Logical clock date is outside the slot's half-open window",
        )
    if m["status"] == "REMEDIATED":
        m["attempt_number"] += 1
        m["chamber_slot_id"] = slot["id"]
    m["status"] = "TESTING"
    touch(m)
    slot["status"] = "CONSUMED"
    touch(slot)
    return ok(ser_mock_up(m))


@bp.route(
    "/engagements/<engagement_id>/mock-ups/<mockup_id>/record-result",
    methods=["POST"],
    strict_slashes=False,
)
def mockup_record_result(engagement_id, mockup_id):
    eng, m = _mockup_transition(engagement_id, mockup_id)
    body = get_body()
    measured = req_num(body, "measured_leakage_lps_m2")
    if m["status"] != "TESTING":
        raise_err(ERR_MOCKUP_NOT_ACTIONABLE, "record-result requires TESTING")
    asm = get_child("assemblies", m["assembly_id"], eng["id"], "Assembly")
    slot = get_child("chamber_slots", m["chamber_slot_id"], eng["id"], "ChamberSlot")
    passed = measured <= asm["required_airtightness_lps_m2"]  # equality passes
    fee = mockup_testing_fee(m, slot)
    fiscal_gate(eng, fee)
    m["status"] = "PASSED" if passed else "FAILED"
    m["air_leakage_lps_m2"] = measured
    m["testing_fee_cents"] = fee
    touch(m)
    apply_fee_delta(eng, fee, "mockup_testing_fee")
    if not passed:
        apply_risk_delta(eng, MOCKUP_FAIL_DELTA)
    return ok(ser_mock_up(m))


@bp.route(
    "/engagements/<engagement_id>/mock-ups/<mockup_id>/mark-remediated",
    methods=["POST"],
    strict_slashes=False,
)
def mockup_mark_remediated(engagement_id, mockup_id):
    eng, m = _mockup_transition(engagement_id, mockup_id)
    if m["status"] != "FAILED":
        raise_err(ERR_MOCKUP_NOT_ACTIONABLE, "mark-remediated requires FAILED")
    m["status"] = "REMEDIATED"
    touch(m)
    return ok(ser_mock_up(m))


# ---------------------------------------------------------------------------
# FieldTest
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/field-tests", methods=["POST"], strict_slashes=False)
def create_field_test(engagement_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    body = get_body()
    assembly_id = req_str(body, "assembly_id")
    test_method = req_enum(body, "test_method", TEST_METHODS)
    test_date_s = req_str(body, "test_date")
    parse_date(test_date_s, "test_date")
    pressure = req_int(body, "test_pressure_pa", lo=50, hi=1000)
    require_in_progress(eng)
    get_child("assemblies", assembly_id, eng["id"], "Assembly")
    t = new_common()
    t.update(
        {
            "engagement_id": eng["id"],
            "assembly_id": assembly_id,
            "test_method": test_method,
            "test_date": test_date_s,
            "test_pressure_pa": pressure,
            "measured_leakage_lps_m2": None,
            "performed_by": None,
            "certified_by": None,
            "result": None,
            "execution_status": "SCHEDULED",
            "diagnosis_status": "NOT_REQUIRED",
        }
    )
    STORE["field_tests"][t["id"]] = t
    return ok(ser_field_test(t), status=201)


@bp.route("/engagements/<engagement_id>/field-tests", methods=["GET"], strict_slashes=False)
def list_field_tests(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    items = [t for t in STORE["field_tests"].values() if t["engagement_id"] == eng["id"]]
    assembly_id = request.args.get("assembly_id")
    if assembly_id is not None:
        items = [t for t in items if t["assembly_id"] == assembly_id]
    return list_response(items, ser_field_test)


@bp.route("/engagements/<engagement_id>/field-tests/<test_id>", methods=["GET"], strict_slashes=False)
def get_field_test_route(engagement_id, test_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return ok(ser_field_test(get_child("field_tests", test_id, eng["id"], "FieldTest")))


def _field_test_transition(engagement_id, test_id, allowed_roles):
    uid, role = auth()
    require_role(role, allowed_roles)
    eng = get_engagement(engagement_id)
    t = get_child("field_tests", test_id, eng["id"], "FieldTest")
    require_in_progress(eng)
    return uid, eng, t


@bp.route(
    "/engagements/<engagement_id>/field-tests/<test_id>/begin",
    methods=["POST"],
    strict_slashes=False,
)
def field_test_begin(engagement_id, test_id):
    _, eng, t = _field_test_transition(engagement_id, test_id, {"FieldTechnician"})
    require_not_frozen(eng)
    if t["execution_status"] != "SCHEDULED":
        raise_err(ERR_FIELD_TEST_NOT_ACTIONABLE, "begin requires SCHEDULED")
    asm = get_child("assemblies", t["assembly_id"], eng["id"], "Assembly")
    if asm["review_status"] != "APPROVED":
        raise_err(
            ERR_ASSEMBLY_NOT_APPROVED,
            "Field test begin requires the assembly review_status == APPROVED",
        )
    t["execution_status"] = "IN_PROGRESS"
    touch(t)
    return ok(ser_field_test(t))


@bp.route(
    "/engagements/<engagement_id>/field-tests/<test_id>/record-result",
    methods=["POST"],
    strict_slashes=False,
)
def field_test_record_result(engagement_id, test_id):
    uid, eng, t = _field_test_transition(engagement_id, test_id, {"FieldTechnician"})
    body = get_body()
    measured = req_num(body, "measured_leakage_lps_m2")
    if t["execution_status"] != "IN_PROGRESS":
        raise_err(ERR_FIELD_TEST_NOT_ACTIONABLE, "record-result requires IN_PROGRESS")
    asm = get_child("assemblies", t["assembly_id"], eng["id"], "Assembly")
    result = field_test_result(measured, asm, t["test_pressure_pa"])
    t["execution_status"] = "RESULT_RECORDED"
    t["performed_by"] = uid
    t["measured_leakage_lps_m2"] = measured
    t["result"] = result
    touch(t)
    if result == "FAIL":
        t["diagnosis_status"] = "UNDIAGNOSED"
        anomaly = new_common()
        anomaly.update(
            {
                "engagement_id": eng["id"],
                "field_test_id": t["id"],
                "survey_id": None,
                "anomaly_type": "AIR_LEAKAGE",
                "severity": "HIGH",
                "description": "Auto-raised from failing field test",
                "status": "OPEN",
            }
        )
        STORE["anomalies"][anomaly["id"]] = anomaly
        apply_risk_delta(eng, FIELD_TEST_FAIL_DELTA)
    return ok(ser_field_test(t))


@bp.route(
    "/engagements/<engagement_id>/field-tests/<test_id>/begin-diagnosis",
    methods=["POST"],
    strict_slashes=False,
)
def field_test_begin_diagnosis(engagement_id, test_id):
    _, eng, t = _field_test_transition(engagement_id, test_id, {"Consultant"})
    if t["diagnosis_status"] != "UNDIAGNOSED":
        raise_err(ERR_FIELD_TEST_NOT_ACTIONABLE, "begin-diagnosis requires UNDIAGNOSED")
    t["diagnosis_status"] = "DIAGNOSING"
    touch(t)
    return ok(ser_field_test(t))


@bp.route(
    "/engagements/<engagement_id>/field-tests/<test_id>/complete-diagnosis",
    methods=["POST"],
    strict_slashes=False,
)
def field_test_complete_diagnosis(engagement_id, test_id):
    _, eng, t = _field_test_transition(engagement_id, test_id, {"Consultant"})
    if t["diagnosis_status"] != "DIAGNOSING":
        raise_err(ERR_FIELD_TEST_NOT_ACTIONABLE, "complete-diagnosis requires DIAGNOSING")
    t["diagnosis_status"] = "DIAGNOSED"
    touch(t)
    return ok(ser_field_test(t))


@bp.route(
    "/engagements/<engagement_id>/field-tests/<test_id>/certify",
    methods=["POST"],
    strict_slashes=False,
)
def field_test_certify(engagement_id, test_id):
    uid, eng, t = _field_test_transition(engagement_id, test_id, {"Principal"})
    require_not_frozen(eng)
    if t["execution_status"] != "RESULT_RECORDED":
        raise_err(ERR_FIELD_TEST_NOT_ACTIONABLE, "certify requires RESULT_RECORDED")
    if uid == t["performed_by"]:
        raise_err(
            ERR_DUTY_SEGREGATION_VIOLATION,
            "Certifier must differ from the performer who recorded the result",
        )
    if t["result"] == "FAIL" and t["diagnosis_status"] != "DIAGNOSED":
        raise_err(
            ERR_DIAGNOSIS_INCOMPLETE,
            "Certification of a FAIL result requires diagnosis_status == DIAGNOSED",
        )
    t["execution_status"] = "CERTIFIED"
    t["certified_by"] = uid
    touch(t)
    return ok(ser_field_test(t))


# ---------------------------------------------------------------------------
# Survey
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/surveys", methods=["POST"], strict_slashes=False)
def create_survey(engagement_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    body = get_body()
    assembly_id = req_str(body, "assembly_id")
    survey_type = req_enum(body, "survey_type", SURVEY_TYPES)
    survey_date_s = req_str(body, "survey_date")
    parse_date(survey_date_s, "survey_date")
    delta_t = req_num(body, "ambient_delta_t_c")
    require_in_progress(eng)
    get_child("assemblies", assembly_id, eng["id"], "Assembly")
    s = new_common()
    s.update(
        {
            "engagement_id": eng["id"],
            "assembly_id": assembly_id,
            "survey_type": survey_type,
            "survey_date": survey_date_s,
            "ambient_delta_t_c": delta_t,
            "status": "PLANNED",
        }
    )
    STORE["surveys"][s["id"]] = s
    return ok(ser_survey(s), status=201)


@bp.route("/engagements/<engagement_id>/surveys", methods=["GET"], strict_slashes=False)
def list_surveys(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    items = [s for s in STORE["surveys"].values() if s["engagement_id"] == eng["id"]]
    assembly_id = request.args.get("assembly_id")
    if assembly_id is not None:
        items = [s for s in items if s["assembly_id"] == assembly_id]
    return list_response(items, ser_survey)


@bp.route("/engagements/<engagement_id>/surveys/<survey_id>", methods=["GET"], strict_slashes=False)
def get_survey_route(engagement_id, survey_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return ok(ser_survey(get_child("surveys", survey_id, eng["id"], "Survey")))


@bp.route(
    "/engagements/<engagement_id>/surveys/<survey_id>/complete",
    methods=["POST"],
    strict_slashes=False,
)
def survey_complete(engagement_id, survey_id):
    _, role = auth()
    require_role(role, {"FieldTechnician"})
    eng = get_engagement(engagement_id)
    s = get_child("surveys", survey_id, eng["id"], "Survey")
    require_in_progress(eng)
    require_not_frozen(eng)
    if s["status"] != "PLANNED":
        raise_err(ERR_SURVEY_NOT_ACTIONABLE, "complete requires PLANNED")
    if s["survey_type"] in ("THERMAL_IMAGING", "COMBINED") and s[
        "ambient_delta_t_c"
    ] < Decimal("3.0"):
        raise_err(
            ERR_IMAGING_DELTA_T_INSUFFICIENT,
            "Imaging survey completion requires ambient_delta_t_c >= 3.0",
        )
    s["status"] = "COMPLETED"
    touch(s)
    return ok(ser_survey(s))


@bp.route(
    "/engagements/<engagement_id>/surveys/<survey_id>/analyze",
    methods=["POST"],
    strict_slashes=False,
)
def survey_analyze(engagement_id, survey_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    s = get_child("surveys", survey_id, eng["id"], "Survey")
    require_in_progress(eng)
    if s["status"] != "COMPLETED":
        raise_err(ERR_SURVEY_NOT_ACTIONABLE, "analyze requires COMPLETED")
    s["status"] = "ANALYZED"
    touch(s)
    return ok(ser_survey(s))


@bp.route(
    "/engagements/<engagement_id>/surveys/<survey_id>/void",
    methods=["POST"],
    strict_slashes=False,
)
def survey_void(engagement_id, survey_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    s = get_child("surveys", survey_id, eng["id"], "Survey")
    require_in_progress(eng)
    if s["status"] != "PLANNED":
        raise_err(ERR_SURVEY_NOT_ACTIONABLE, "void requires PLANNED")
    s["status"] = "VOID"
    touch(s)
    return ok(ser_survey(s))


# ---------------------------------------------------------------------------
# Anomaly
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/anomalies", methods=["POST"], strict_slashes=False)
def create_anomaly(engagement_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    body = get_body()
    field_test_id = body.get("field_test_id")
    survey_id = body.get("survey_id")
    if field_test_id is not None and not isinstance(field_test_id, str):
        raise_err(ERR_INVALID_REQUEST, "field_test_id must be a string")
    if survey_id is not None and not isinstance(survey_id, str):
        raise_err(ERR_INVALID_REQUEST, "survey_id must be a string")
    # XOR: exactly one parent reference set
    if (field_test_id is None) == (survey_id is None):
        raise_err(
            ERR_INVALID_REQUEST,
            "Exactly one of field_test_id / survey_id must be set",
        )
    anomaly_type = req_enum(body, "anomaly_type", ANOMALY_TYPES)
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_str(body, "description")
    require_in_progress(eng)
    if field_test_id is not None:
        get_child("field_tests", field_test_id, eng["id"], "FieldTest")
    else:
        get_child("surveys", survey_id, eng["id"], "Survey")
    a = new_common()
    a.update(
        {
            "engagement_id": eng["id"],
            "field_test_id": field_test_id,
            "survey_id": survey_id,
            "anomaly_type": anomaly_type,
            "severity": severity,
            "description": description,
            "status": "OPEN",
        }
    )
    STORE["anomalies"][a["id"]] = a
    return ok(ser_anomaly(a), status=201)


@bp.route("/engagements/<engagement_id>/anomalies", methods=["GET"], strict_slashes=False)
def list_anomalies(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    items = [a for a in STORE["anomalies"].values() if a["engagement_id"] == eng["id"]]
    field_test_id = request.args.get("field_test_id")
    survey_id = request.args.get("survey_id")
    if field_test_id is not None:
        items = [a for a in items if a["field_test_id"] == field_test_id]
    if survey_id is not None:
        items = [a for a in items if a["survey_id"] == survey_id]
    return list_response(items, ser_anomaly)


@bp.route("/engagements/<engagement_id>/anomalies/<anomaly_id>", methods=["GET"], strict_slashes=False)
def get_anomaly_route(engagement_id, anomaly_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return ok(ser_anomaly(get_child("anomalies", anomaly_id, eng["id"], "Anomaly")))


@bp.route(
    "/engagements/<engagement_id>/anomalies/<anomaly_id>/verify",
    methods=["POST"],
    strict_slashes=False,
)
def anomaly_verify(engagement_id, anomaly_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    a = get_child("anomalies", anomaly_id, eng["id"], "Anomaly")
    require_in_progress(eng)
    if a["status"] != "OPEN":
        raise_err(ERR_ANOMALY_NOT_OPEN, "verify requires anomaly status OPEN")
    a["status"] = "VERIFIED"
    touch(a)
    apply_risk_delta(eng, VERIFY_DELTAS[a["severity"]])
    return ok(ser_anomaly(a))


@bp.route(
    "/engagements/<engagement_id>/anomalies/<anomaly_id>/dismiss",
    methods=["POST"],
    strict_slashes=False,
)
def anomaly_dismiss(engagement_id, anomaly_id):
    _, role = auth()
    require_role(role, {"Principal"})
    eng = get_engagement(engagement_id)
    a = get_child("anomalies", anomaly_id, eng["id"], "Anomaly")
    require_in_progress(eng)
    if a["status"] != "OPEN":
        raise_err(ERR_ANOMALY_NOT_OPEN, "dismiss requires anomaly status OPEN")
    a["status"] = "DISMISSED"
    touch(a)
    return ok(ser_anomaly(a))
