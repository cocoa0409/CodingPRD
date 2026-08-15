"""Assignment endpoints: routing (auto/override), screening, waiver, activation,
release (PRD 3.4)."""
from flask import Blueprint, request

from db import DB, new_id, next_seq, now_dt
from errors import ApiError
from middleware import STAFF_READ_ROLES, auth
from response import ok, ok_list
from services import (
    CONFLICT_TYPES,
    SCREEN_OUTCOMES,
    active_case_count,
    add_event,
    assignment_view,
    bump,
    case_posture,
    get_assignment,
    get_case,
    paginate,
    select_investigator,
)
from util import as_occ_version, as_str, body, opt_str, pagination_args, req_enum

bp = Blueprint("assignments", __name__)

SUPERSEDABLE = ("PROPOSED", "CONFLICT_PENDING", "CLEARED")


@bp.post("/hotline/cases/<cid>/assignments")
def propose_assignment(cid):
    user_id, role = auth(["IntakeSpecialist", "ComplianceOfficer"])
    case = get_case(cid)
    data = body()
    if "expected_case_version" not in data or data["expected_case_version"] is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Missing required field: expected_case_version"
        )
    expected = as_occ_version(data["expected_case_version"], "expected_case_version")
    investigator_id = opt_str(data, "investigator_id")
    opt_str(data, "override_reason")

    # Role-conditional rule: only a ComplianceOfficer may steer to a specific person.
    if investigator_id is not None and role != "ComplianceOfficer":
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            403,
            "Explicit investigator override requires ComplianceOfficer",
        )

    # OCC (priority 7)
    if expected != case["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_case_version does not match the case's current version",
        )

    # State (priority 8)
    supersede_targets = [
        a
        for a in DB["assignments"].values()
        if a["case_id"] == case["id"] and a["status"] in SUPERSEDABLE
    ]
    state_ok = case["status"] in ("TRIAGED", "REOPENED") or (
        case["status"] == "ASSIGNED" and len(supersede_targets) > 0
    )
    if not state_ok:
        raise ApiError(
            "ERR_CASE_NOT_TRIAGED_OR_REOPENED",
            409,
            "Assignment proposal requires case TRIAGED or REOPENED",
        )

    # Legal-hold freeze gate (priority 9)
    if case_posture(case) != "NORMAL":
        raise ApiError(
            "ERR_LEGAL_HOLD_FREEZE", 409, "Case is FROZEN by an ACTIVE legal hold"
        )

    if investigator_id is not None:
        # Override path (priority 10 then 11).
        target = DB["staff_members"].get(investigator_id)
        if target is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
        if investigator_id == case["triaged_by_id"]:
            raise ApiError(
                "ERR_SOD_TRIAGER_INELIGIBLE",
                409,
                "The triaging specialist may not become the case investigator",
            )
        if (
            target["email"] in case["subject_employee_ids"]
            or target["display_name"] in case["subject_employee_ids"]
        ):
            raise ApiError(
                "ERR_SUBJECT_NAMED_AS_INVESTIGATOR",
                409,
                "The override target is named in the case's subject_employee_ids",
            )
        # The override eligibility bar (ACTIVE employment, INVESTIGATION
        # capability); capacity is enforced at activate time, not at propose.
        if (
            target["employment_status"] != "ACTIVE"
            or "INVESTIGATION" not in target["capabilities"]
        ):
            raise ApiError(
                "ERR_NO_ELIGIBLE_INVESTIGATOR",
                409,
                "The override target does not satisfy the routing eligibility bar",
            )
        candidate = target
        selection_mode = "OVERRIDE"
    else:
        candidate = select_investigator(case)
        selection_mode = "AUTO"

    # Side effects: supersede the prior non-terminal assignment, then propose.
    for prior in supersede_targets:
        from_status = prior["status"]
        prior["status"] = "SUPERSEDED"
        bump(prior)
        add_event(
            case["id"], "ASSIGNMENT_SUPERSEDED", from_status, "SUPERSEDED", role, user_id
        )

    rec = {
        "id": new_id(),
        "case_id": case["id"],
        "investigator_id": candidate["id"],
        "routed_by_id": user_id,
        "selection_mode": selection_mode,
        "status": "PROPOSED",
        "screened_by_id": None,
        "conflict_type": None,
        "waived_by_id": None,
        "waiver_justification": None,
        "created_at": now_dt(),
        "updated_at": now_dt(),
        "version": 1,
        "_seq": next_seq(),
    }
    DB["assignments"][rec["id"]] = rec
    from_case_status = case["status"]
    case["assigned_investigator_id"] = candidate["id"]
    case["status"] = "ASSIGNED"
    bump(case)
    add_event(case["id"], "ASSIGNMENT_PROPOSED", from_case_status, "ASSIGNED", role, user_id)
    return ok(assignment_view(rec), status=201)


@bp.get("/hotline/cases/<cid>/assignments")
def list_assignments(cid):
    auth(STAFF_READ_ROLES)
    get_case(cid)
    limit, offset = pagination_args()
    records = [a for a in DB["assignments"].values() if a["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        records = [a for a in records if a["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([assignment_view(a) for a in page], total, limit, offset)


@bp.post("/hotline/assignments/<aid>/screen")
def screen_assignment(aid):
    # Investigator is carried past the role gate so that the candidate's
    # self-screen attempt surfaces ERR_SOD_SELF_SCREEN (priority 10); an
    # Investigator who is not the candidate is rejected below.
    user_id, role = auth(["IntakeSpecialist", "ComplianceOfficer", "Investigator"])
    assignment = get_assignment(aid)
    data = body()
    outcome = req_enum(data, "outcome", SCREEN_OUTCOMES)
    conflict_type = None
    if "conflict_type" in data and data["conflict_type"] is not None:
        conflict_type = req_enum(data, "conflict_type", CONFLICT_TYPES)
    if outcome == "CONFLICT_FOUND" and conflict_type is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "conflict_type is required when the screening outcome is CONFLICT_FOUND",
        )
    opt_str(data, "notes")

    if role == "Investigator" and user_id != assignment["investigator_id"]:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS", 403, "Role not permitted for this endpoint"
        )

    if assignment["status"] != "PROPOSED":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_PROPOSED", 409, "Screening requires assignment PROPOSED"
        )
    if user_id == assignment["investigator_id"]:
        raise ApiError(
            "ERR_SOD_SELF_SCREEN",
            409,
            "The candidate investigator may not screen their own assignment",
        )

    from_status = assignment["status"]
    assignment["screened_by_id"] = user_id
    if outcome == "CLEAR":
        assignment["status"] = "CLEARED"
    else:
        assignment["status"] = "CONFLICT_PENDING"
        assignment["conflict_type"] = conflict_type
    bump(assignment)
    add_event(
        assignment["case_id"], "SCREENED", from_status, assignment["status"], role, user_id
    )
    return ok(assignment_view(assignment))


@bp.post("/hotline/assignments/<aid>/waive-conflict")
def waive_conflict(aid):
    user_id, role = auth(["ComplianceOfficer"])
    assignment = get_assignment(aid)
    data = body()
    justification = data.get("waiver_justification")
    if justification is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Missing required field: waiver_justification"
        )
    justification = as_str(justification, "waiver_justification", min_len=20)

    if assignment["status"] != "CONFLICT_PENDING":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_CONFLICT_PENDING",
            409,
            "Waiver requires assignment CONFLICT_PENDING",
        )
    if user_id == assignment["screened_by_id"] or user_id == assignment["investigator_id"]:
        raise ApiError(
            "ERR_SOD_SELF_WAIVER",
            409,
            "The waiving officer must differ from the screener and the candidate",
        )

    from_status = assignment["status"]
    assignment["status"] = "CLEARED"
    assignment["waived_by_id"] = user_id
    assignment["waiver_justification"] = justification
    bump(assignment)
    add_event(
        assignment["case_id"], "CONFLICT_WAIVED", from_status, "CLEARED", role, user_id
    )
    return ok(assignment_view(assignment))


@bp.post("/hotline/assignments/<aid>/activate")
def activate_assignment(aid):
    user_id, role = auth(["ComplianceOfficer"])
    assignment = get_assignment(aid)
    if assignment["status"] != "CLEARED":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_CLEARED", 409, "Activation requires assignment CLEARED"
        )
    case = DB["cases"].get(assignment["case_id"])
    if case is not None and case_posture(case) != "NORMAL":
        raise ApiError(
            "ERR_LEGAL_HOLD_FREEZE", 409, "Case is FROZEN by an ACTIVE legal hold"
        )
    investigator = DB["staff_members"].get(assignment["investigator_id"])
    if investigator is not None and (
        active_case_count(investigator["id"]) >= investigator["max_active_cases"]
    ):
        raise ApiError(
            "ERR_INVESTIGATOR_CAPACITY_EXCEEDED",
            409,
            "Activation would exceed the investigator's max_active_cases",
        )

    assignment["status"] = "ACTIVE"
    bump(assignment)
    if case is not None:
        from_status = case["status"]
        case["status"] = "UNDER_INVESTIGATION"
        bump(case)
        add_event(
            case["id"], "ASSIGNMENT_ACTIVATED", from_status, "UNDER_INVESTIGATION", role, user_id
        )
    return ok(assignment_view(assignment))


@bp.post("/hotline/assignments/<aid>/release")
def release_assignment(aid):
    user_id, role = auth(["ComplianceOfficer"])
    assignment = get_assignment(aid)
    if assignment["status"] not in ("PROPOSED", "CONFLICT_PENDING", "CLEARED", "ACTIVE"):
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_RELEASABLE",
            409,
            "Assignment in a terminal state cannot be released",
        )
    was_active = assignment["status"] == "ACTIVE"
    case = DB["cases"].get(assignment["case_id"])
    if was_active and case is not None:
        conducted = any(
            i["case_id"] == case["id"] and i["status"] == "CONDUCTED"
            for i in DB["interviews"].values()
        )
        if conducted:
            raise ApiError(
                "ERR_CASE_HAS_CONDUCTED_INTERVIEWS",
                409,
                "Release of an ACTIVE assignment requires zero CONDUCTED interviews",
            )

    assignment["status"] = "RELEASED"
    bump(assignment)
    if case is not None:
        from_status = case["status"]
        case["assigned_investigator_id"] = None
        case["status"] = "TRIAGED"
        bump(case)
        add_event(
            case["id"], "ASSIGNMENT_RELEASED", from_status, "TRIAGED", role, user_id
        )
    return ok(assignment_view(assignment))
