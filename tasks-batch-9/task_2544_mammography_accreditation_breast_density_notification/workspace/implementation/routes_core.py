"""Clock, StatePolicy and Facility endpoints."""

from flask import Blueprint, g

import services as svc
from common import (
    ALL_ROLES, DB, EPOCH_DEFAULT, ROLE_COORDINATOR, ROLE_INSPECTOR, ROLE_QA,
    ROLE_REVIEWER, body_dict, endpoint, fail, filter_rows, fmt_dt, new_entity,
    ok_entity, ok_list, ok_object, parse_dt, plus_days, sort_rows, touch, v_dt,
    v_enum, v_int, v_state_code, v_str, v_str_list,
)

bp = Blueprint("core", __name__)

DENSITY_NOTICE_RULES = ("FEDERAL_ONLY", "STATE_DENSE_ONLY", "STATE_ENHANCED_ALL")
COVERAGE_MANDATES = ("NONE", "COVERAGE_WITH_COST_SHARING", "COVERAGE_NO_COST_SHARING")
ACCREDITATION_BODIES = ("ACR", "STATE_CERTIFIED")
MODALITIES = ("DM_2D", "DBT_3D")
ROLE_TYPES = ("INTERPRETING_PHYSICIAN", "TECHNOLOGIST", "MEDICAL_PHYSICIST")
FINDING_LEVELS = ("NONE", "LEVEL_3", "LEVEL_2", "LEVEL_1")


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(ALL_ROLES)
def clock_set():
    body = body_dict()
    raw = v_str(body, "current_utc", required=True)
    requested = parse_dt(raw)
    if requested is None:
        fail("ERR_INVALID_REQUEST", "current_utc must be an ISO-8601 timestamp")
    if requested < DB.clock:
        fail("ERR_CLOCK_REWIND", "the logical clock may only move forward or be held")
    previous_display = DB.clock_display
    DB.clock = requested
    DB.clock_display = raw if raw.endswith("Z") else fmt_dt(requested)
    return ok_object({
        "current_utc": DB.clock_display,
        "previous_utc": previous_display,
    })


@bp.route("/_clock/current", methods=["GET"])
@endpoint(ALL_ROLES)
def clock_current():
    return ok_object({"current_utc": DB.clock_display or EPOCH_DEFAULT})


# ---------------------------------------------------------------------------
# StatePolicy
# ---------------------------------------------------------------------------
@bp.route("/state-policies", methods=["POST"])
@endpoint([ROLE_REVIEWER, ROLE_INSPECTOR])
def state_policy_create():
    body = body_dict()
    state_code = v_state_code(body, "state_code", required=True)
    rule = v_enum(body, "density_notice_rule", DENSITY_NOTICE_RULES, required=True)
    grade = v_int(body, "lay_summary_max_reading_grade", True, 4, 12)
    deadline_days = v_int(body, "lay_summary_deadline_days", True, 1, 90)
    mandate = v_enum(body, "supplemental_coverage_mandate", COVERAGE_MANDATES, True)
    notice_codes = v_str_list(body, "required_notice_codes", False, default=[])
    waiver = v_int(body, "supplemental_cost_share_waiver_threshold_cents", False, 0,
                   None, default=0)
    followup_grace_days = v_int(body, "followup_grace_days", False, 1, 365, default=60)
    report_days = v_int(body, "report_turnaround_days", False, 1, 90, default=30)
    urgent_days = v_int(body, "urgent_report_turnaround_days", False, 1, 30, default=7)
    ce_grace_days = v_int(body, "ce_grace_days", False, 1, 365, default=90)
    if urgent_days > report_days:
        fail("ERR_INVALID_REQUEST",
             "urgent_report_turnaround_days must not exceed report_turnaround_days")

    if svc.policy_by_state_code(state_code) is not None:
        fail("ERR_DUPLICATE_RESOURCE", "state_code %s is already registered" % state_code)

    policy = new_entity("state_policy", {
        "state_code": state_code,
        "density_notice_rule": rule,
        "lay_summary_max_reading_grade": grade,
        "lay_summary_deadline_days": deadline_days,
        "required_notice_codes": notice_codes,
        "supplemental_coverage_mandate": mandate,
        "supplemental_cost_share_waiver_threshold_cents": waiver,
        "followup_grace_days": followup_grace_days,
        "report_turnaround_days": report_days,
        "urgent_report_turnaround_days": urgent_days,
        "ce_grace_days": ce_grace_days,
    })
    return ok_entity(policy, 201)


def _policy_or_404(policy_id):
    policy = DB.get("state_policy", policy_id)
    if policy is None:
        fail("ERR_STATE_POLICY_NOT_FOUND", "state policy %s does not exist" % policy_id)
    return policy


@bp.route("/state-policies/<policy_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def state_policy_read(policy_id):
    return ok_entity(_policy_or_404(policy_id))


@bp.route("/state-policies/<policy_id>/facilities", methods=["GET"])
@endpoint(ALL_ROLES)
def state_policy_facilities(policy_id):
    _policy_or_404(policy_id)
    rows = [f for f in DB.all("facility") if f["state_policy_id"] == policy_id]
    return ok_list(sort_rows(rows))


# ---------------------------------------------------------------------------
# Facility
# ---------------------------------------------------------------------------
def _facility_or_404(facility_id):
    facility = DB.get("facility", facility_id)
    if facility is None:
        fail("ERR_FACILITY_NOT_FOUND", "facility %s does not exist" % facility_id)
    return facility


@bp.route("/facilities", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def facility_create():
    body = body_dict()
    name = v_str(body, "name", True, 1, 120)
    state_policy_id = v_str(body, "state_policy_id", True)
    accreditation_body = v_enum(body, "accreditation_body", ACCREDITATION_BODIES, True)
    capacity = v_int(body, "supplemental_concurrent_capacity", False, 1, 10, default=2)

    if DB.get("state_policy", state_policy_id) is None:
        fail("ERR_STATE_POLICY_NOT_FOUND",
             "state policy %s does not exist" % state_policy_id)

    facility = new_entity("facility", {
        "name": name,
        "state_policy_id": state_policy_id,
        "accreditation_body": accreditation_body,
        "supplemental_concurrent_capacity": capacity,
        "total_funded_cents": 0,
        "prepaid_credit_cents": 0,
        "fee_held_cents": 0,
        "fee_consumed_cents": 0,
        "compliance_posture": "COMPLIANT",
        "open_notice_obligations": 0,
        "last_compliance_run_at": None,
    })
    return ok_entity(facility, 201)


@bp.route("/facilities/<facility_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def facility_read(facility_id):
    return ok_entity(_facility_or_404(facility_id))


@bp.route("/facilities/<facility_id>/funding-deposits", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def facility_deposit(facility_id):
    facility = _facility_or_404(facility_id)
    body = body_dict()
    if "amount_cents" not in body or body["amount_cents"] is None:
        fail("ERR_INVALID_REQUEST", "amount_cents is required")
    amount = body["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        fail("ERR_INVALID_DEPOSIT_AMOUNT",
             "amount_cents must be a positive integer number of cents")
    svc.ledger_deposit(facility, amount)
    return ok_entity(facility)


@bp.route("/facilities/<facility_id>/units", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def facility_unit_create(facility_id):
    facility = _facility_or_404(facility_id)
    body = body_dict()
    manufacturer = v_str(body, "manufacturer", True, 1)
    model_serial = v_str(body, "model_serial", True, 1)
    modality = v_enum(body, "modality", MODALITIES, True)
    expires_on = v_dt(body, "accreditation_expires_on", True)

    for peer in svc.units_of_facility(facility_id):
        if peer["model_serial"] == model_serial:
            fail("ERR_DUPLICATE_RESOURCE",
                 "model_serial %s already exists at this facility" % model_serial)

    unit = new_entity("unit", {
        "facility_id": facility_id,
        "manufacturer": manufacturer,
        "model_serial": model_serial,
        "modality": modality,
        "accreditation_status": "PROVISIONAL",
        "operational_state": "IN_SERVICE",
        "accreditation_expires_on": expires_on,
        "reaccreditation_attempts_remaining": 3,
        "survey_compliance": "OVERDUE",
        "last_passed_survey_end": None,
        "total_images_acquired": 0,
        "repeat_images_acquired": 0,
        "image_based_repeat_rate_pct": None,
        "patient_based_repeat_rate_pct": None,
        "repeat_rate_flag": False,
        "_ever_accredited": False,
    })
    svc.recompute_posture(facility)
    return ok_entity(unit, 201)


@bp.route("/facilities/<facility_id>/units", methods=["GET"])
@endpoint(ALL_ROLES)
def facility_units_list(facility_id):
    _facility_or_404(facility_id)
    rows = svc.units_of_facility(facility_id)
    rows = filter_rows(rows, {"accreditation_status": "accreditation_status",
                              "operational_state": "operational_state"})
    return ok_list(sort_rows(rows))


@bp.route("/facilities/<facility_id>/personnel", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def facility_personnel_create(facility_id):
    _facility_or_404(facility_id)
    body = body_dict()
    full_name = v_str(body, "full_name", True, 1)
    role_type = v_enum(body, "role_type", ROLE_TYPES, True)
    qualified_on = v_dt(body, "initial_qualification_on", True)
    training_hours = v_int(body, "initial_training_hours", True, 0)
    read_volume = v_int(body, "initial_read_volume", True, 0)
    certifications = v_str_list(body, "modality_certifications", False,
                               allowed=MODALITIES, default=[])

    if qualified_on > DB.clock:
        fail("ERR_FUTURE_TIMESTAMP",
             "initial_qualification_on may not be in the future")

    thresholds = svc.CE_THRESHOLDS[role_type]
    initial_ok = (training_hours >= thresholds["initial_hours"]
                  and read_volume >= thresholds["initial_volume"])

    person = new_entity("personnel", {
        "facility_id": facility_id,
        "full_name": full_name,
        "role_type": role_type,
        "initial_qualification_on": qualified_on,
        "initial_training_hours": training_hours,
        "initial_read_volume": read_volume,
        "modality_certifications": certifications,
        "qualification_status": "QUALIFIED" if initial_ok else "PROVISIONAL",
        "ce_status": "COMPLIANT",
        "ce_hours_36mo": 0,
        "volume_credit_24mo": 0,
        "ce_deadline_at": None,
        "last_qualification_review_at": None,
    })
    return ok_entity(person, 201)


@bp.route("/facilities/<facility_id>/personnel", methods=["GET"])
@endpoint(ALL_ROLES)
def facility_personnel_list(facility_id):
    _facility_or_404(facility_id)
    rows = svc.personnel_of_facility(facility_id)
    rows = filter_rows(rows, {"role_type": "role_type",
                              "qualification_status": "qualification_status",
                              "ce_status": "ce_status"})
    return ok_list(sort_rows(rows))


@bp.route("/facilities/<facility_id>/inspections", methods=["POST"])
@endpoint([ROLE_INSPECTOR])
def facility_inspection_create(facility_id):
    facility = _facility_or_404(facility_id)
    body = body_dict()
    inspection_date = v_dt(body, "inspection_date", True)
    level = v_enum(body, "inspector_findings_level", FINDING_LEVELS, True)
    finding_codes = v_str_list(body, "finding_codes", False, default=[])

    if inspection_date > DB.clock:
        fail("ERR_FUTURE_TIMESTAMP", "inspection_date may not be in the future")

    if level in svc.CORRECTIVE_ACTION_DAYS:
        status = "CORRECTIVE_ACTION_REQUIRED"
        due_at = plus_days(inspection_date, svc.CORRECTIVE_ACTION_DAYS[level])
    else:
        status = "RECORDED"
        due_at = None

    inspection = new_entity("inspection", {
        "facility_id": facility_id,
        "inspection_date": inspection_date,
        "inspector_findings_level": level,
        "finding_codes": finding_codes,
        "status": status,
        "corrective_action_due_at": due_at,
        "closed_at": None,
    })
    svc.recompute_posture(facility)
    return ok_entity(inspection, 201)


@bp.route("/facilities/<facility_id>/inspections", methods=["GET"])
@endpoint(ALL_ROLES)
def facility_inspections_list(facility_id):
    _facility_or_404(facility_id)
    rows = svc.inspections_of_facility(facility_id)
    rows = filter_rows(rows, {"status": "status",
                              "inspector_findings_level": "inspector_findings_level"})
    return ok_list(sort_rows(rows))


@bp.route("/facilities/<facility_id>/compliance-runs", methods=["POST"])
@endpoint([ROLE_COORDINATOR, ROLE_QA])
def facility_compliance_run(facility_id):
    facility = _facility_or_404(facility_id)
    result = svc.run_compliance_checkpoint(facility)
    result["ran_at"] = fmt_dt(result["ran_at"])
    return ok_object(result)


# ---------------------------------------------------------------------------
# AnnualInspection (top level)
# ---------------------------------------------------------------------------
def _inspection_or_404(inspection_id):
    inspection = DB.get("inspection", inspection_id)
    if inspection is None:
        fail("ERR_INSPECTION_NOT_FOUND", "inspection %s does not exist" % inspection_id)
    return inspection


@bp.route("/inspections/<inspection_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def inspection_read(inspection_id):
    return ok_entity(_inspection_or_404(inspection_id))


@bp.route("/inspections/<inspection_id>/close", methods=["POST"])
@endpoint([ROLE_INSPECTOR])
def inspection_close(inspection_id):
    inspection = _inspection_or_404(inspection_id)
    body_dict()
    if inspection["status"] == "CLOSED":
        fail("ERR_INSPECTION_ALREADY_CLOSED", "inspection is already closed")
    inspection["status"] = "CLOSED"
    inspection["closed_at"] = DB.clock
    touch(inspection)
    svc.recompute_posture(DB.get("facility", inspection["facility_id"]))
    return ok_entity(inspection)
