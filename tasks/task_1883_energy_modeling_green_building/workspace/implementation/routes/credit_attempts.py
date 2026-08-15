"""CreditAttempt endpoints (PRD 3.2 strategy, 3.5 review loop)."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth_headers, require_role
from response import ok, ok_list
from services import (
    attempts_of_project,
    bucket_points_for_improvement,
    bubble_up_phase,
    comments_of_attempt,
    get_attempt,
    get_entry,
    get_member,
    get_project,
    locked_model,
    ser_attempt,
    ser_comment,
    sorted_created,
    stamp,
    sync_project_derived,
    touch,
)
from util import (
    PHASES,
    as_enum,
    as_number,
    as_str,
    body,
    num_out,
    pagination_args,
    required,
    round_half_up_int,
)

bp = Blueprint("credit_attempts", __name__)


@bp.post("/credit-attempts")
def create_attempt():
    _user_id, role = auth_headers()
    data = body()
    project_id = as_str(required(data, "project_id"), "project_id")
    entry_id = as_str(required(data, "credit_library_entry_id"), "credit_library_entry_id")
    phase = as_enum(required(data, "phase"), PHASES, "phase")
    owner_id = as_str(required(data, "documentation_owner_id"), "documentation_owner_id")
    require_role(role, {"ProjectAdministrator"})
    project = get_project(project_id)
    entry = get_entry(entry_id)
    owner = get_member(owner_id)
    if project["status"] not in ("REGISTERED", "STRATEGY_LOCKED"):
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            409,
            "Credit attempts require the project to be REGISTERED or STRATEGY_LOCKED",
        )
    # Referential attribute checks (PRD 3.2 order: phase, then specialty).
    if entry["phase_eligibility"] != "BOTH" and entry["phase_eligibility"] != phase:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "phase is not compatible with the entry's phase_eligibility",
        )
    if owner["specialty"] != "DOCUMENTATION":
        raise ApiError(
            "ERR_INVALID_TEAM_MEMBER_SPECIALTY",
            422,
            "documentation owner must have specialty DOCUMENTATION",
        )
    for a in attempts_of_project(project["id"]):
        if a["status"] != "DROPPED" and a["credit_code"] == entry["credit_code"]:
            raise ApiError(
                "ERR_DUPLICATE_CREDIT_ATTEMPT",
                409,
                "A non-dropped attempt for this credit_code already exists",
            )
    rec = stamp(
        {
            "project_id": project["id"],
            "credit_library_entry_id": entry["id"],
            "credit_code": entry["credit_code"],
            "points_possible": entry["points_possible"],
            "is_prerequisite": entry["is_prerequisite"],
            "phase": phase,
            "documentation_owner_id": owner["id"],
            "pinned_proposed_model_id": None,
            "has_stale_model_pin": False,
            "raw_points_earned": None,
            "points_awarded": None,
            "submission_round": 0,
            "status": "SELECTED",
        }
    )
    DB["credit_attempts"][rec["id"]] = rec
    sync_project_derived(project, explicit_bump=True)
    return ok(ser_attempt(rec), status=201)


@bp.get("/credit-attempts")
def list_attempts():
    auth_headers()
    items = list(DB["credit_attempts"].values())
    for param, field in (
        ("project_id", "project_id"),
        ("credit_library_entry_id", "credit_library_entry_id"),
        ("documentation_owner_id", "documentation_owner_id"),
        ("pinned_proposed_model_id", "pinned_proposed_model_id"),
        ("status", "status"),
        ("phase", "phase"),
    ):
        value = request.args.get(param)
        if value is not None:
            items = [a for a in items if a[field] == value]
    items = sorted_created(items)
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_attempt(a) for a in page], total, limit, offset)


@bp.get("/credit-attempts/<attempt_id>")
def get_one_attempt(attempt_id):
    auth_headers()
    return ok(ser_attempt(get_attempt(attempt_id)))


@bp.post("/credit-attempts/<attempt_id>/assign-owner")
def assign_owner(attempt_id):
    _user_id, role = auth_headers()
    data = body()
    owner_id = as_str(required(data, "documentation_owner_id"), "documentation_owner_id")
    require_role(role, {"ProjectAdministrator"})
    attempt = get_attempt(attempt_id)
    owner = get_member(owner_id)
    if attempt["status"] not in ("SELECTED", "DOCUMENTATION_IN_PROGRESS"):
        raise ApiError(
            "ERR_INVALID_CREDIT_ATTEMPT_STATE",
            409,
            "Owner assignment requires SELECTED or DOCUMENTATION_IN_PROGRESS",
        )
    if owner["specialty"] != "DOCUMENTATION":
        raise ApiError(
            "ERR_INVALID_TEAM_MEMBER_SPECIALTY",
            422,
            "documentation owner must have specialty DOCUMENTATION",
        )
    attempt["documentation_owner_id"] = owner["id"]
    if attempt["status"] == "SELECTED":
        attempt["status"] = "DOCUMENTATION_IN_PROGRESS"
    touch(attempt)
    return ok(ser_attempt(attempt))


@bp.post("/credit-attempts/<attempt_id>/mark-ready")
def mark_ready(attempt_id):
    user_id, role = auth_headers()
    body()
    require_role(role, {"DocumentationSpecialist"})
    attempt = get_attempt(attempt_id)
    if user_id != attempt["documentation_owner_id"]:
        raise ApiError(
            "ERR_NOT_DOCUMENTATION_OWNER",
            403,
            "Only the documentation owner may mark the attempt ready",
        )
    if attempt["status"] != "DOCUMENTATION_IN_PROGRESS":
        raise ApiError(
            "ERR_INVALID_CREDIT_ATTEMPT_STATE",
            409,
            "mark-ready requires DOCUMENTATION_IN_PROGRESS",
        )
    entry = DB["credit_library_entries"][attempt["credit_library_entry_id"]]
    if entry["requires_energy_model"]:
        proposed = locked_model(attempt["project_id"], "PROPOSED")
        if proposed is None:
            raise ApiError(
                "ERR_PROPOSED_MODEL_NOT_LOCKED",
                409,
                "A LOCKED proposed model is required to mark this credit ready",
            )
        attempt["pinned_proposed_model_id"] = proposed["id"]
        attempt["has_stale_model_pin"] = False
    attempt["status"] = "READY_FOR_SUBMITTAL"
    touch(attempt)
    return ok(ser_attempt(attempt))


@bp.post("/credit-attempts/<attempt_id>/drop")
def drop_attempt(attempt_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"ProjectAdministrator"})
    attempt = get_attempt(attempt_id)
    if attempt["status"] not in ("SELECTED", "DOCUMENTATION_IN_PROGRESS", "READY_FOR_SUBMITTAL"):
        raise ApiError(
            "ERR_INVALID_CREDIT_ATTEMPT_STATE",
            409,
            "Only a not-yet-submitted attempt can be dropped",
        )
    attempt["status"] = "DROPPED"
    touch(attempt)
    project = DB["projects"][attempt["project_id"]]
    sync_project_derived(project, explicit_bump=True)
    return ok(ser_attempt(attempt))


@bp.post("/credit-attempts/<attempt_id>/begin-review")
def begin_review(attempt_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"CertificationReviewer"})
    attempt = get_attempt(attempt_id)
    if attempt["status"] not in ("SUBMITTED", "RESUBMITTED", "APPEALED"):
        raise ApiError(
            "ERR_INVALID_CREDIT_ATTEMPT_STATE",
            409,
            "begin-review requires SUBMITTED, RESUBMITTED, or APPEALED",
        )
    project = DB["projects"][attempt["project_id"]]
    if project["status"] not in ("DESIGN_SUBMITTED", "CONSTRUCTION_SUBMITTED"):
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            409,
            "Project must be in a submitted phase state",
        )
    if attempt["status"] == "RESUBMITTED":
        for c in comments_of_attempt(attempt["id"]):
            if c["status"] != "ACCEPTED":
                raise ApiError(
                    "ERR_UNRESOLVED_REVIEW_COMMENTS",
                    409,
                    "Every review comment must be ACCEPTED before resuming review",
                )
    attempt["status"] = "UNDER_REVIEW"
    touch(attempt)
    sync_project_derived(project)
    return ok(ser_attempt(attempt))


@bp.post("/credit-attempts/<attempt_id>/resubmit")
def resubmit_attempt(attempt_id):
    user_id, role = auth_headers()
    body()
    require_role(role, {"DocumentationSpecialist"})
    attempt = get_attempt(attempt_id)
    if user_id != attempt["documentation_owner_id"]:
        raise ApiError(
            "ERR_NOT_DOCUMENTATION_OWNER",
            403,
            "Only the documentation owner may resubmit the attempt",
        )
    if attempt["status"] != "CLARIFICATION_REQUESTED":
        raise ApiError(
            "ERR_INVALID_CREDIT_ATTEMPT_STATE",
            409,
            "resubmit requires CLARIFICATION_REQUESTED",
        )
    for c in comments_of_attempt(attempt["id"]):
        if c["status"] != "ADDRESSED":
            raise ApiError(
                "ERR_UNRESOLVED_REVIEW_COMMENTS",
                409,
                "Every review comment must be ADDRESSED before resubmission",
            )
    attempt["status"] = "RESUBMITTED"
    attempt["submission_round"] += 1
    touch(attempt)
    sync_project_derived(DB["projects"][attempt["project_id"]])
    return ok(ser_attempt(attempt))


@bp.post("/credit-attempts/<attempt_id>/award")
def award_attempt(attempt_id):
    _user_id, role = auth_headers()
    data = body()
    raw = as_number(data["raw_points_earned"], "raw_points_earned") if (
        "raw_points_earned" in data and data["raw_points_earned"] is not None
    ) else None
    require_role(role, {"CertificationReviewer"})
    attempt = get_attempt(attempt_id)
    if attempt["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_CREDIT_ATTEMPT_STATE", 409, "award requires UNDER_REVIEW"
        )
    if raw is not None:
        if raw < 0 or raw > attempt["points_possible"]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "raw_points_earned must lie within 0..points_possible",
            )
        raw_value = raw
    else:
        entry = DB["credit_library_entries"][attempt["credit_library_entry_id"]]
        if not entry["requires_energy_model"] or attempt["pinned_proposed_model_id"] is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "raw_points_earned is required for credits without an energy model pin",
            )
        pinned = DB["energy_models"][attempt["pinned_proposed_model_id"]]
        raw_value = Decimal(bucket_points_for_improvement(pinned["improvement_pct_final"]))
    # Per-attempt rounding BEFORE any project summation (PRD 3.5).
    attempt["raw_points_earned"] = num_out(raw_value)
    attempt["points_awarded"] = round_half_up_int(raw_value)
    attempt["status"] = "AWARDED"
    touch(attempt)
    project = DB["projects"][attempt["project_id"]]
    sync_project_derived(project)
    bubble_up_phase(project, attempt["phase"])
    return ok(ser_attempt(attempt))


@bp.post("/credit-attempts/<attempt_id>/deny")
def deny_attempt(attempt_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"CertificationReviewer"})
    attempt = get_attempt(attempt_id)
    if attempt["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_CREDIT_ATTEMPT_STATE", 409, "deny requires UNDER_REVIEW"
        )
    attempt["status"] = "DENIED"
    touch(attempt)
    project = DB["projects"][attempt["project_id"]]
    sync_project_derived(project)
    bubble_up_phase(project, attempt["phase"])
    return ok(ser_attempt(attempt))


@bp.post("/credit-attempts/<attempt_id>/appeal")
def appeal_attempt(attempt_id):
    _user_id, role = auth_headers()
    data = body()
    as_str(required(data, "appeal_justification"), "appeal_justification")
    require_role(role, {"ProjectAdministrator"})
    attempt = get_attempt(attempt_id)
    if attempt["status"] != "DENIED":
        raise ApiError("ERR_INVALID_CREDIT_ATTEMPT_STATE", 409, "appeal requires DENIED")
    attempt["status"] = "APPEALED"
    touch(attempt)
    project = DB["projects"][attempt["project_id"]]
    # The appeal reopens the phase review if the project already advanced.
    if attempt["phase"] == "DESIGN" and project["status"] == "DESIGN_REVIEWED":
        project["status"] = "DESIGN_SUBMITTED"
        touch(project)
    elif attempt["phase"] == "CONSTRUCTION" and project["status"] == "CONSTRUCTION_REVIEWED":
        project["status"] = "CONSTRUCTION_SUBMITTED"
        touch(project)
    return ok(ser_attempt(attempt))


@bp.get("/credit-attempts/<attempt_id>/review-comments")
def list_attempt_comments(attempt_id):
    auth_headers()
    attempt = get_attempt(attempt_id)
    items = comments_of_attempt(attempt["id"])
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_comment(c) for c in page], total, limit, offset)
