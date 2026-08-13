"""Routes: patient cases, classification decisions, case assignments."""

from flask import Blueprint, g, request

import cascades
import db
import derived
import errors
import middleware
from clock import parse_iso
from helpers import (
    ASSIGNMENT_ROLES,
    CHANNELS,
    DECISIONS,
    GRIEVANCE_CATEGORIES,
    RATIONALE_CODES,
    SEVERITY_TIERS,
    _MISSING,
    check_bool,
    check_datetime,
    check_enum,
    check_string,
    get_body,
    new_id,
    paginate,
    parse_pagination,
    require_present,
    serialize_assignment,
    serialize_case,
    serialize_decision,
    sorted_by_creation,
    stamp_light,
    stamp_new,
    touch,
)
from response import success_list, success_object
from state import CLOCK

bp = Blueprint("cases", __name__)


def get_case_or_404(case_id):
    case = db.patient_cases.get(case_id)
    if case is None:
        raise errors.not_found(errors.ERR_CASE_NOT_FOUND, "PatientCase not found")
    return case


def check_expected_case_version(case, body):
    """OCC guard (PRD §2.7): expected_case_version compared before business rules."""
    expected = body.get("expected_case_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_case_version must be an integer")
    if expected != case["version"]:
        raise errors.stale_version()


# ---------------------------------------------------------------------------
# PatientCase
# ---------------------------------------------------------------------------


@bp.route("/api/patient-cases", methods=["POST"])
def create_case():
    middleware.authenticate()
    middleware.require_roles("IntakeCoordinator")
    body = get_body()
    require_present(
        body,
        "patient_ref",
        "unit_id",
        "received_at",
        "channel",
        "description",
        "grievance_category",
    )
    unit = db.hospital_units.get(body.get("unit_id"))
    if unit is None:
        raise errors.not_found(errors.ERR_UNIT_NOT_FOUND, "HospitalUnit not found")
    # Cross-aggregate integrity (rung 9): RESTRICTED posture blocks intake.
    if unit["posture"] == "RESTRICTED":
        raise errors.api_error(
            errors.ERR_UNIT_IN_RESTRICTED_POSTURE,
            409,
            "Unit posture RESTRICTED rejects new case intake",
        )
    # Temporal sanity (rung 11): received_at must not lie ahead of the clock.
    received_dt = check_datetime(body, "received_at", required=True)
    now = CLOCK.now()
    if received_dt > now:
        raise errors.api_error(
            errors.ERR_RECEIVED_AT_IN_FUTURE,
            422,
            "received_at is after the current logical clock",
        )
    # Schema value-domain checks (rung 13).
    patient_ref = check_string(body, "patient_ref", required=True)
    description = check_string(body, "description", required=True)
    channel = check_enum(body, "channel", CHANNELS, required=True)
    category = check_enum(body, "grievance_category", GRIEVANCE_CATEGORIES, required=True)
    severity = check_enum(body, "severity_tier", SEVERITY_TIERS, default="STANDARD")
    abuse_flag = check_bool(body, "alleged_abuse_flag", default=False)
    vulnerable_flag = check_bool(body, "vulnerable_patient_flag", default=False)
    from clock import iso_ms

    case = stamp_new()
    case.update(
        {
            "patient_ref": patient_ref,
            "unit_id": unit["id"],
            "received_at": iso_ms(received_dt),
            "channel": channel,
            "description": description,
            "grievance_category": category,
            "alleged_abuse_flag": abuse_flag,
            "vulnerable_patient_flag": vulnerable_flag,
            "severity_tier": severity,
            "classification": "UNCLASSIFIED",
            "lifecycle_status": "INTAKE",
            "acknowledged_at": None,
            "ack_due_at": None,
            "current_classification_decision_id": None,
            "resolution_timeliness": "NA",
            "closure_note": None,
            "closed_at": None,
            "reopen_count": 0,
            "_cal_anchor": None,
            "_cal_days": 0,
            "_cal_offset": 0,
            "_biz_anchor": None,
            "_biz_days": 0,
            "_biz_offset": 0,
            "_closure_due_calendar_at": None,
        }
    )
    db.patient_cases[case["id"]] = case
    return success_object(serialize_case(case), 201)


@bp.route("/api/patient-cases", methods=["GET"])
def list_cases():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    unit_id = request.args.get("unit_id")
    lifecycle = request.args.get("lifecycle_status")
    classification = request.args.get("classification")
    category = request.args.get("grievance_category")
    decision_id = request.args.get("current_classification_decision_id")
    cases = list(db.patient_cases.values())
    if unit_id is not None:
        cases = [c for c in cases if c["unit_id"] == unit_id]
    if lifecycle is not None:
        cases = [c for c in cases if c["lifecycle_status"] == lifecycle]
    if classification is not None:
        cases = [c for c in cases if c["classification"] == classification]
    if category is not None:
        cases = [c for c in cases if c["grievance_category"] == category]
    if decision_id is not None:
        cases = [c for c in cases if c["current_classification_decision_id"] == decision_id]
    cases = sorted_by_creation(cases)
    page, total = paginate(cases, limit, offset)
    return success_list([serialize_case(c) for c in page], limit, offset, total)


@bp.route("/api/patient-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    case = get_case_or_404(case_id)
    return success_object(serialize_case(case))


@bp.route("/api/patient-cases/<case_id>/timeline", methods=["GET"])
def get_case_timeline(case_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    case = get_case_or_404(case_id)
    from clock import iso_ms

    now = CLOCK.now()
    cal_due, biz_due, tolling = derived.response_dues(case, now)
    data = {
        "ack_due_at": case["ack_due_at"],
        "response_due_calendar_at": iso_ms(cal_due) if cal_due else None,
        "response_due_business_at": iso_ms(biz_due) if biz_due else None,
        "tolling_credit_seconds": tolling,
        "regulatory_clock_status": derived.regulatory_clock_status(case, now),
        "priority_score": derived.priority_score(case, now),
        "days_remaining": derived.days_remaining(case, now),
    }
    return success_object(data)


@bp.route("/api/patient-cases/<case_id>/acknowledge", methods=["POST"])
def acknowledge_case(case_id):
    middleware.authenticate()
    middleware.require_roles("IntakeCoordinator")
    get_body()
    case = get_case_or_404(case_id)
    if case["lifecycle_status"] in ("CLOSED", "WITHDRAWN"):
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE, 409, "Case is CLOSED or WITHDRAWN"
        )
    if case["acknowledged_at"] is not None:
        raise errors.api_error(
            errors.ERR_ALREADY_ACKNOWLEDGED, 409, "Case acknowledgment already recorded"
        )
    case["acknowledged_at"] = CLOCK.now_iso()
    touch(case)
    return success_object(serialize_case(case))


@bp.route("/api/patient-cases/<case_id>/withdraw", methods=["POST"])
def withdraw_case(case_id):
    middleware.authenticate()
    middleware.require_roles("IntakeCoordinator")
    get_body()  # optional withdraw_reason is accepted and not persisted
    case = get_case_or_404(case_id)
    # Available from every non-terminal state except CLOSED (PRD §3.9).
    if case["lifecycle_status"] in ("CLOSED", "WITHDRAWN"):
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE,
            409,
            "Case cannot be withdrawn from its current state",
        )
    cascades.withdraw_case(case, CLOCK.now())
    return success_object(serialize_case(case))


@bp.route("/api/patient-cases/<case_id>/reopen", methods=["POST"])
def reopen_case(case_id):
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector")
    get_body()  # optional reopen_reason is accepted and not persisted
    case = get_case_or_404(case_id)
    if case["lifecycle_status"] != "CLOSED":
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE, 409, "Only a CLOSED case can be reopened"
        )
    cascades.reopen_case(case, CLOCK.now())
    return success_object(serialize_case(case))


@bp.route("/api/patient-cases/<case_id>/fast-track", methods=["POST"])
def fast_track_case(case_id):
    middleware.authenticate()
    middleware.require_roles("IntakeCoordinator")
    get_body()
    case = get_case_or_404(case_id)
    if case["lifecycle_status"] != "ASSIGNED":
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE, 409, "Fast-track requires the case ASSIGNED"
        )
    if case["classification"] != "COMPLAINT":
        raise errors.api_error(
            errors.ERR_FAST_TRACK_COMPLAINT_ONLY,
            409,
            "fast-track requires classification = COMPLAINT",
        )
    case["lifecycle_status"] = "RESPONSE_DRAFTING"
    touch(case)
    return success_object(serialize_case(case))


@bp.route("/api/patient-cases/<case_id>/close", methods=["POST"])
def close_case_endpoint(case_id):
    middleware.authenticate()
    middleware.require_roles("IntakeCoordinator")
    body = get_body()
    require_present(body, "closure_note")
    case = get_case_or_404(case_id)
    if case["lifecycle_status"] != "RESPONSE_DRAFTING":
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE,
            409,
            "Complaint fast-track closure requires RESPONSE_DRAFTING",
        )
    if case["classification"] != "COMPLAINT":
        raise errors.api_error(
            errors.ERR_GRIEVANCE_REQUIRES_WRITTEN_RESPONSE,
            409,
            "A grievance closes only through an issued ResponseLetter",
        )
    closure_note = check_string(body, "closure_note", required=True)
    if len(closure_note) < 20:
        raise errors.invalid_request("closure_note must be at least 20 characters")
    cascades.close_case(case, CLOCK.now(), closure_note)
    return success_object(serialize_case(case))


# ---------------------------------------------------------------------------
# ClassificationDecision
# ---------------------------------------------------------------------------


@bp.route("/api/patient-cases/<case_id>/classification-decisions", methods=["POST"])
def create_classification_decision(case_id):
    middleware.authenticate()
    middleware.require_roles("IntakeCoordinator")
    body = get_body()
    require_present(body, "decision", "rationale_code", "expected_case_version")
    case = get_case_or_404(case_id)
    check_expected_case_version(case, body)
    # Case lifecycle (rung 6): no decisions on CLOSED/WITHDRAWN; a downgrade
    # GRIEVANCE -> COMPLAINT is accepted only while in INTAKE or CLASSIFIED.
    if case["lifecycle_status"] in ("CLOSED", "WITHDRAWN"):
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE,
            409,
            "Decisions may not be recorded on a CLOSED or WITHDRAWN case",
        )
    if (
        body.get("decision") == "COMPLAINT"
        and case["classification"] == "GRIEVANCE"
        and case["lifecycle_status"] not in ("INTAKE", "CLASSIFIED")
    ):
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE,
            409,
            "GRIEVANCE -> COMPLAINT downgrade allowed only in INTAKE or CLASSIFIED",
        )
    decision_value = check_enum(body, "decision", DECISIONS, required=True)
    rationale = check_enum(body, "rationale_code", RATIONALE_CODES, required=True)
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise errors.invalid_request("note must be a string")
    decision = stamp_light()
    decision.update(
        {
            "case_id": case["id"],
            "decision": decision_value,
            "rationale_code": rationale,
            "note": note,
            "decided_by_id": g.user_id,
            "supersedes_decision_id": case["current_classification_decision_id"],
        }
    )
    db.classification_decisions[decision["id"]] = decision
    case["classification"] = decision_value
    case["current_classification_decision_id"] = decision["id"]
    if case["lifecycle_status"] == "INTAKE":
        case["lifecycle_status"] = "CLASSIFIED"
    derived.recompute_dues_on_classification(case)
    touch(case)
    if decision_value == "GRIEVANCE":
        # Systemic-issue sweep runs after the dues are computed (PRD §3.2).
        cascades.systemic_issue_sweep(case, CLOCK.now())
    return success_object(serialize_decision(decision), 201)


@bp.route("/api/classification-decisions", methods=["GET"])
def list_classification_decisions():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    supersedes = request.args.get("supersedes_decision_id")
    decisions = list(db.classification_decisions.values())
    if case_id is not None:
        decisions = [d for d in decisions if d["case_id"] == case_id]
    if supersedes is not None:
        decisions = [d for d in decisions if d["supersedes_decision_id"] == supersedes]
    decisions = sorted_by_creation(decisions)
    page, total = paginate(decisions, limit, offset)
    return success_list([serialize_decision(d) for d in page], limit, offset, total)


@bp.route("/api/classification-decisions/<decision_id>", methods=["GET"])
def get_classification_decision(decision_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    decision = db.classification_decisions.get(decision_id)
    if decision is None:
        raise errors.not_found(
            errors.ERR_CLASSIFICATION_NOT_FOUND, "ClassificationDecision not found"
        )
    return success_object(serialize_decision(decision))


# ---------------------------------------------------------------------------
# CaseAssignment
# ---------------------------------------------------------------------------


@bp.route("/api/patient-cases/<case_id>/assignments", methods=["POST"])
def create_assignment(case_id):
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector")
    body = get_body()
    require_present(body, "expected_case_version")
    case = get_case_or_404(case_id)
    check_expected_case_version(case, body)
    if case["lifecycle_status"] not in ("CLASSIFIED", "ASSIGNED"):
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE,
            409,
            "Assignment requires the case CLASSIFIED or ASSIGNED",
        )
    assignment_role = check_enum(
        body, "assignment_role", ASSIGNMENT_ROLES, default="PRIMARY"
    )
    investigator_id = body.get("investigator_id")
    assigned_by = g.user_id
    if investigator_id is not None:
        if not isinstance(investigator_id, str):
            raise errors.invalid_request("investigator_id must be a string")
        staff = db.staff_members.get(investigator_id)
        if staff is None:
            raise errors.not_found(errors.ERR_STAFF_NOT_FOUND, "StaffMember not found")
        if "INVESTIGATOR" not in staff["capabilities"]:
            raise errors.invalid_request(
                "Named investigator must hold the INVESTIGATOR capability"
            )
        if staff["on_leave"]:
            raise errors.api_error(
                errors.ERR_ADVOCATE_ON_LEAVE,
                403,
                "Staff member on_leave may not be assigned",
            )
        if derived.staff_open_assignment_count(staff["id"]) >= staff[
            "max_concurrent_assignments"
        ]:
            raise errors.api_error(
                errors.ERR_INVESTIGATOR_AT_CAPACITY,
                409,
                "Investigator has reached max_concurrent_assignments",
            )
        for a in db.case_assignments.values():
            if (
                a["case_id"] == case["id"]
                and a["investigator_id"] == staff["id"]
                and a["status"] == "ACTIVE"
            ):
                raise errors.api_error(
                    errors.ERR_DUPLICATE_ACTIVE_ASSIGNMENT,
                    409,
                    "Same investigator already has an ACTIVE assignment on this case",
                )
        chosen = staff
    else:
        chosen = auto_select_investigator()
        if chosen is None:
            raise errors.api_error(
                errors.ERR_NO_ELIGIBLE_INVESTIGATOR,
                409,
                "Auto-assignment pool is empty",
            )
        assigned_by = "system"
    now = CLOCK.now()
    # Supersede: a new PRIMARY releases any existing ACTIVE PRIMARY on the case.
    if assignment_role == "PRIMARY":
        from clock import iso_ms

        for a in db.case_assignments.values():
            if (
                a["case_id"] == case["id"]
                and a["status"] == "ACTIVE"
                and a["assignment_role"] == "PRIMARY"
            ):
                a["status"] = "RELEASED"
                a["released_at"] = iso_ms(now)
                touch(a)
    assignment = stamp_new()
    assignment.update(
        {
            "case_id": case["id"],
            "investigator_id": chosen["id"],
            "assignment_role": assignment_role,
            "status": "ACTIVE",
            "assigned_by_id": assigned_by,
            "released_at": None,
        }
    )
    db.case_assignments[assignment["id"]] = assignment
    if case["lifecycle_status"] == "CLASSIFIED":
        case["lifecycle_status"] = "ASSIGNED"
    touch(case)
    return success_object(serialize_assignment(assignment), 201)


def auto_select_investigator():
    """Eligibility: INVESTIGATOR capability, not on leave, headroom.

    Ranking: open_assignment_count ASC, ties by created_at ASC (earliest
    registered first; id never used).
    """
    pool = []
    for staff in db.staff_members.values():
        if "INVESTIGATOR" not in staff["capabilities"]:
            continue
        if staff["on_leave"]:
            continue
        count = derived.staff_open_assignment_count(staff["id"])
        if count >= staff["max_concurrent_assignments"]:
            continue
        pool.append((count, staff["_seq"], staff))
    if not pool:
        return None
    pool.sort(key=lambda entry: (entry[0], entry[1]))
    return pool[0][2]


@bp.route("/api/case-assignments", methods=["GET"])
def list_assignments():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    investigator_id = request.args.get("investigator_id")
    status = request.args.get("status")
    assignments = list(db.case_assignments.values())
    if case_id is not None:
        assignments = [a for a in assignments if a["case_id"] == case_id]
    if investigator_id is not None:
        assignments = [a for a in assignments if a["investigator_id"] == investigator_id]
    if status is not None:
        assignments = [a for a in assignments if a["status"] == status]
    assignments = sorted_by_creation(assignments)
    page, total = paginate(assignments, limit, offset)
    return success_list([serialize_assignment(a) for a in page], limit, offset, total)


@bp.route("/api/case-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    assignment = db.case_assignments.get(assignment_id)
    if assignment is None:
        raise errors.not_found(errors.ERR_ASSIGNMENT_NOT_FOUND, "CaseAssignment not found")
    return success_object(serialize_assignment(assignment))


@bp.route("/api/case-assignments/<assignment_id>/release", methods=["POST"])
def release_assignment(assignment_id):
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector")
    get_body()  # optional release_reason is accepted and not persisted
    assignment = db.case_assignments.get(assignment_id)
    if assignment is None:
        raise errors.not_found(errors.ERR_ASSIGNMENT_NOT_FOUND, "CaseAssignment not found")
    if assignment["status"] != "ACTIVE":
        raise errors.api_error(
            errors.ERR_ASSIGNMENT_INVALID_STATE, 409, "Assignment is not ACTIVE"
        )
    from clock import iso_ms

    assignment["status"] = "RELEASED"
    assignment["released_at"] = iso_ms(CLOCK.now())
    touch(assignment)
    return success_object(serialize_assignment(assignment))
