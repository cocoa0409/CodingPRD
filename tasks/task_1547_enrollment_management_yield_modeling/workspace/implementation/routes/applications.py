"""Application endpoints + transition logic."""
from flask import Blueprint, request

from db import store, clock, new_id, now_iso, _parse_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_SCORE_OUT_OF_RANGE, ERR_PROGRAM_CYCLE_MISMATCH, ERR_CYCLE_PHASE_MISMATCH,
    ERR_INTAKE_PAUSED, ERR_REVIEW_QUORUM_NOT_MET, ERR_NOT_RESOURCE_OWNER,
    ERR_FORBIDDEN,
)
from middleware import require_roles, get_auth
from response import success_object, success_list
from services.derived import (
    recompute_cycle, recompute_program, recompute_application_aid_fields,
    recompute_melt_risk, recompute_submitted_read_count,
    compute_waitlist_rank_score, cancel_assigned_reviews, revoke_aid_offers,
    maybe_auto_activate, activate_waitlist_entry, select_top_waitlist_entry,
)
from services.serializers import serialize_application, touch

bp = Blueprint("applications", __name__, url_prefix="/enrollment/applications")

REVIEW_QUORUM = 2


def _get_app_or_404(aid):
    a = store.applications.get(aid)
    if not a:
        raise ApiError(ERR_NOT_FOUND, 404, "Application not found")
    return a


@bp.route("", methods=["POST"])
def create_application():
    require_roles("AdmissionsOfficer")
    body = request.get_json(silent=True) or {}
    applicant_id = body.get("applicant_id")
    program_id = body.get("program_id")
    cycle_id = body.get("cycle_id")
    academic_score = body.get("academic_score")
    efc_cents = body.get("efc_cents")

    if applicant_id is None or applicant_id not in store.applicants:
        raise ApiError(ERR_NOT_FOUND, 404, "applicant_id not found")
    if program_id is None or program_id not in store.programs:
        raise ApiError(ERR_NOT_FOUND, 404, "program_id not found")
    if cycle_id is None or cycle_id not in store.cycles:
        raise ApiError(ERR_NOT_FOUND, 404, "cycle_id not found")

    applicant = store.applicants[applicant_id]
    program = store.programs[program_id]
    cycle = store.cycles[cycle_id]

    if academic_score is None or efc_cents is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "academic_score/efc_cents required")
    if not isinstance(academic_score, (int, float)) or academic_score < 0 or academic_score > 100:
        raise ApiError(ERR_SCORE_OUT_OF_RANGE, 422,
                       "academic_score must be 0..100")
    if not isinstance(efc_cents, int) or efc_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "efc_cents must be a non-negative integer")

    if applicant["cycle_id"] != cycle_id or program["cycle_id"] != cycle_id:
        raise ApiError(ERR_PROGRAM_CYCLE_MISMATCH, 422,
                       "cycle_id mismatch across applicant/program/cycle")
    if cycle["status"] != "OPEN":
        raise ApiError(ERR_CYCLE_PHASE_MISMATCH, 409,
                       f"Cycle status {cycle['status']} does not permit application filing")

    now = now_iso()
    app = {
        "id": new_id(),
        "applicant_id": applicant_id,
        "program_id": program_id,
        "cycle_id": cycle_id,
        "academic_score": academic_score,
        "efc_cents": efc_cents,
        "submitted_at": now,
        "review_round": 1,
        "submitted_read_count": 0,
        "aid_accepted_cents": 0,
        "aid_gap_cents": program["tuition_cents"],
        "melt_risk_score": 0.0,
        "status": "SUBMITTED",
        "_ever_admitted": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.applications[app["id"]] = app

    # Flip applicant INQUIRY -> APPLIED (absorbing)
    if applicant["funnel_stage"] == "INQUIRY":
        applicant["funnel_stage"] = "APPLIED"
        touch(applicant)

    recompute_cycle(cycle)
    return success_object(serialize_application(app), status=201)


@bp.route("/<applicationId>", methods=["GET"])
def get_application(applicationId):
    user_id, role = get_auth()
    if role not in ("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer",
                    "FinancialAidOfficer", "ApplicationReader", "Applicant"):
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted")
    app = _get_app_or_404(applicationId)
    if role == "Applicant" and user_id != app["applicant_id"]:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Not resource owner")
    return success_object(serialize_application(app))


@bp.route("", methods=["GET"])
def list_applications():
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer", "FinancialAidOfficer")
    cycle_id = request.args.get("cycle_id")
    program_id = request.args.get("program_id")
    applicant_id = request.args.get("applicant_id")
    status = request.args.get("status")
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = list(store.applications.values())
    if cycle_id:
        items = [a for a in items if a["cycle_id"] == cycle_id]
    if program_id:
        items = [a for a in items if a["program_id"] == program_id]
    if applicant_id:
        items = [a for a in items if a["applicant_id"] == applicant_id]
    if status:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_application(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def _melt_application(app):
    """DEPOSITED -> MELTED cascade. Returns list of activated waitlist entry ids."""
    program = store.programs.get(app["program_id"])
    cycle = store.cycles.get(app["cycle_id"])
    # Deposit -> FORFEITED
    for d in store.deposits.values():
        if d["application_id"] == app["id"] and d["status"] == "PAID":
            d["status"] = "FORFEITED"
            d["refund_amount_cents"] = 0
            touch(d)
    app["status"] = "MELTED"
    touch(app)
    # Aid offers revoked
    revoke_aid_offers(app["id"], ("OFFERED", "REVISION_REQUESTED", "ACCEPTED"))
    # Program counters recompute
    activated = []
    if program:
        recompute_program(program)
        # Conditional auto-activation
        entry = maybe_auto_activate(program)
        if entry:
            activated.append(entry["id"])
    if cycle:
        recompute_cycle(cycle)
    return activated


def _withdraw_from_deposited(app):
    """DEPOSITED -> WITHDRAWN cascade. Returns list of activated entry ids."""
    program = store.programs.get(app["program_id"])
    cycle = store.cycles.get(app["cycle_id"])
    deadline = _parse_iso(cycle["deposit_deadline_at"]) if cycle else None
    now = clock.now()
    for d in store.deposits.values():
        if d["application_id"] == app["id"] and d["status"] == "PAID":
            if deadline and now <= deadline:
                d["status"] = "REFUNDED"
                d["refund_amount_cents"] = d["amount_cents"]
            else:
                d["status"] = "FORFEITED"
                d["refund_amount_cents"] = 0
            touch(d)
    app["status"] = "WITHDRAWN"
    touch(app)
    revoke_aid_offers(app["id"], ("OFFERED", "REVISION_REQUESTED", "ACCEPTED"))
    activated = []
    if program:
        recompute_program(program)
        entry = maybe_auto_activate(program)
        if entry:
            activated.append(entry["id"])
    if cycle:
        recompute_cycle(cycle)
    return activated


ALLOWED_TRANSITIONS = {
    # current -> allowed targets with actors
    "SUBMITTED": {"IN_REVIEW", "WITHDRAWN"},
    "IN_REVIEW": {"COMMITTEE_REVIEW", "WITHDRAWN"},  # COMMITTEE_REVIEW normally auto; explicit allowed
    "COMMITTEE_REVIEW": {"IN_REVIEW", "DECISION_PENDING", "WITHDRAWN"},
    "DECISION_PENDING": {"ADMITTED", "DENIED", "WAITLISTED", "WITHDRAWN"},
    "ADMITTED": {"DEPOSITED", "WITHDRAWN"},  # DEPOSITED via deposit creation, not direct
    "DEPOSITED": {"ENROLLED", "MELTED", "WITHDRAWN"},
    "WAITLISTED": {"ADMITTED", "DENIED", "WITHDRAWN"},
    "DENIED": set(),
    "ENROLLED": set(),
    "MELTED": set(),
    "WITHDRAWN": set(),
}


@bp.route("/<applicationId>/transition", methods=["POST"])
def transition_application(applicationId):
    user_id, role = get_auth()
    if role not in ("AdmissionsOfficer", "EnrollmentManager", "Applicant"):
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted")
    app = _get_app_or_404(applicationId)
    body = request.get_json(silent=True) or {}
    to_status = body.get("to_status")
    if not to_status:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_status required")

    current = app["status"]
    program = store.programs.get(app["program_id"])
    cycle = store.cycles.get(app["cycle_id"])

    # DEPOSITED is not reachable via this endpoint (deposit flow does it)
    # MELTED is not reachable directly (melt-sweep does it)
    if to_status == "DEPOSITED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "DEPOSITED reached only via deposit creation")
    if to_status == "MELTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "MELTED reached only via melt sweep")
    # WAITLISTED -> ADMITTED goes through waitlist activation
    if current == "WAITLISTED" and to_status == "ADMITTED":
        # Allow if program has an ACTIVE waitlist entry for this app and posture/cycle allow
        entry = next(
            (e for e in store.waitlist_entries.values()
             if e["application_id"] == app["id"] and e["status"] == "ACTIVE"),
            None,
        )
        if not entry:
            raise ApiError(ERR_INVALID_STATE, 409, "No ACTIVE waitlist entry")
        recompute_program(program)
        if program["intake_posture"] != "OPEN":
            raise ApiError(ERR_INTAKE_PAUSED, 409, "intake_posture not OPEN")
        if cycle["status"] not in ("DECISIONS_RELEASED", "ENROLLMENT_TRACKING"):
            raise ApiError(ERR_CYCLE_PHASE_MISMATCH, 409, "cycle phase mismatch")
        activate_waitlist_entry(entry)
        if cycle:
            recompute_cycle(cycle)
        return success_object(serialize_application(app))

    if to_status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Cannot transition {current} -> {to_status}")

    # Role gating per transition
    actor_only_officer_targets = {"IN_REVIEW", "COMMITTEE_REVIEW", "DECISION_PENDING",
                                   "ADMITTED", "DENIED", "WAITLISTED"}
    if to_status in actor_only_officer_targets and role != "AdmissionsOfficer":
        raise ApiError(ERR_FORBIDDEN, 403,
                       f"Only AdmissionsOfficer may transition to {to_status}")
    if to_status == "ENROLLED" and role != "EnrollmentManager":
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Only EnrollmentManager may transition to ENROLLED")
    if to_status == "WITHDRAWN" and role not in ("AdmissionsOfficer", "Applicant"):
        raise ApiError(ERR_FORBIDDEN, 403, "Only AdmissionsOfficer or Applicant may withdraw")
    if role == "Applicant" and to_status == "WITHDRAWN":
        if user_id != app["applicant_id"]:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Not resource owner")

    # Specific preconditions
    if current == "COMMITTEE_REVIEW" and to_status == "DECISION_PENDING":
        recompute_submitted_read_count(app)
        if app["submitted_read_count"] < REVIEW_QUORUM:
            raise ApiError(ERR_REVIEW_QUORUM_NOT_MET, 409,
                           "submitted_read_count below quorum")

    if current == "DECISION_PENDING" and to_status == "ADMITTED":
        recompute_program(program)
        if program["intake_posture"] != "OPEN":
            raise ApiError(ERR_INTAKE_PAUSED, 409, "intake_posture not OPEN")
        if cycle["status"] not in ("OPEN", "REVIEW_CLOSED", "DECISIONS_RELEASED"):
            raise ApiError(ERR_CYCLE_PHASE_MISMATCH, 409, "cycle phase mismatch")

    if current == "DEPOSITED" and to_status == "ENROLLED":
        if cycle["status"] not in ("DECISIONS_RELEASED", "ENROLLMENT_TRACKING"):
            raise ApiError(ERR_CYCLE_PHASE_MISMATCH, 409, "cycle phase mismatch")

    # Execute transition
    if current == "COMMITTEE_REVIEW" and to_status == "IN_REVIEW":
        app["review_round"] += 1
        cancel_assigned_reviews(app["id"])
    elif current == "DECISION_PENDING" and to_status == "ADMITTED":
        app["status"] = "ADMITTED"
        app["_ever_admitted"] = True
        touch(app)
        if program:
            recompute_program(program)
            touch(program)
        if cycle:
            recompute_cycle(cycle)
        return success_object(serialize_application(app))
    elif current == "DECISION_PENDING" and to_status == "DENIED":
        cancel_assigned_reviews(app["id"])
    elif current == "DECISION_PENDING" and to_status == "WAITLISTED":
        cancel_assigned_reviews(app["id"])
        # Create waitlist entry
        rank = compute_waitlist_rank_score(app)
        now = now_iso()
        entry = {
            "id": new_id(),
            "application_id": app["id"],
            "program_id": app["program_id"],
            "rank_score": rank,
            "status": "ACTIVE",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.waitlist_entries[entry["id"]] = entry
    elif current == "WAITLISTED" and to_status == "DENIED":
        for e in store.waitlist_entries.values():
            if e["application_id"] == app["id"] and e["status"] == "ACTIVE":
                e["status"] = "REMOVED"
                touch(e)
    elif current == "WAITLISTED" and to_status == "WITHDRAWN":
        for e in store.waitlist_entries.values():
            if e["application_id"] == app["id"] and e["status"] == "ACTIVE":
                e["status"] = "REMOVED"
                touch(e)
    elif to_status == "WITHDRAWN" and current in ("COMMITTEE_REVIEW", "DECISION_PENDING"):
        cancel_assigned_reviews(app["id"])
    elif to_status == "WITHDRAWN" and current == "ADMITTED":
        revoke_aid_offers(app["id"], ("OFFERED", "REVISION_REQUESTED"))
        app["status"] = "WITHDRAWN"
        touch(app)
        if program:
            recompute_program(program)
            touch(program)
        if cycle:
            recompute_cycle(cycle)
        return success_object(serialize_application(app))
    elif to_status == "WITHDRAWN" and current == "DEPOSITED":
        _withdraw_from_deposited(app)
        return success_object(serialize_application(app))
    elif current == "DEPOSITED" and to_status == "ENROLLED":
        # cancel scheduled interventions
        for i in store.interventions.values():
            if i["application_id"] == app["id"] and i["status"] == "SCHEDULED":
                i["status"] = "CANCELLED"
                touch(i)
        app["status"] = "ENROLLED"
        touch(app)
        if program:
            recompute_program(program)
            touch(program)
        if cycle:
            recompute_cycle(cycle)
        return success_object(serialize_application(app))

    # Generic status set + recompute
    app["status"] = to_status
    touch(app)
    if program:
        recompute_program(program)
    if cycle:
        recompute_cycle(cycle)
    return success_object(serialize_application(app))
