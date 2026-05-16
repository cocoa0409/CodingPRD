"""Appeal routes (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint, g, request

from core.auth import require_roles
from core.clock import CLOCK
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, gen_id, lock
from core.timeutils import iso_format, days, parse_iso
from core.validation import require_body, require_field
from services.mutations import stamp_create, bump
from services.projections import project_appeal, project_fair_hearing


bp = Blueprint("appeals", __name__)


def _appeal_or_404(appeal_id):
    row = STORE.appeals.get(appeal_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "Appeal not found")
    return row


def _associated_fair_hearing(appeal_id):
    """Return the most-recent FairHearing for this appeal (or None)."""
    matches = [h for h in STORE.fair_hearings.values() if h["appeal_id"] == appeal_id]
    matches.sort(key=lambda h: h["created_at"])
    return matches[-1] if matches else None


@bp.route("/appeals", methods=["POST"])
@require_roles("IntakeWorker")
def file_appeal():
    body = require_body(request)
    determination_id = require_field(body, "determination_id", kind="string")
    det = STORE.determinations.get(determination_id)
    if det is None:
        raise_error("ERR_NOT_FOUND", "EligibilityDetermination not found")
    application = STORE.applications.get(det["application_id"])
    if application is None:
        raise_error("ERR_NOT_FOUND", "Application not found")
    # Application must currently be DENIED
    if application["status"] != "DENIED":
        raise_error("ERR_INVALID_STATE", "Application must be DENIED to appeal")
    # Within 90 days of determination
    try:
        decided_at = parse_iso(det["decided_at"], "decided_at")
    except Exception:
        raise_error("ERR_INVALID_REQUEST", "Invalid decided_at on determination")
    now = CLOCK.now()
    if now >= decided_at + days(90):
        raise_error("ERR_APPEAL_WINDOW_EXPIRED", "Appeal filed more than 90 days after determination")
    # Uniqueness: at most one appeal per determination_id
    for a in STORE.appeals.values():
        if a["determination_id"] == determination_id:
            raise_error("ERR_APPEAL_ALREADY_EXISTS", "An appeal already exists for this determination")

    with lock():
        aid = gen_id()
        filed_dt = now
        deadline_dt = filed_dt + days(90)
        row = {
            "id": aid,
            "determination_id": determination_id,
            "filed_at": iso_format(filed_dt),
            "deadline_at": iso_format(deadline_dt),
            "_filed_at_dt": filed_dt,
            "_deadline_at_dt": deadline_dt,
            "status": "FILED",
            "officer_id": None,
            "outcome_reason": None,
        }
        stamp_create(row)
        STORE.appeals[aid] = row
        # Linked side-effect: Application -> APPEALED
        application["status"] = "APPEALED"
        bump(application)
    return success_object(project_appeal(row), status=201)


@bp.route("/appeals/<appeal_id>", methods=["GET"])
@require_roles("IntakeWorker", "EligibilityCaseworker", "AppealsOfficer", "PolicyAdmin")
def get_appeal(appeal_id):
    row = _appeal_or_404(appeal_id)
    return success_object(project_appeal(row))


def _check_hearing_overlap(officer_id, new_start_dt, new_end_dt):
    """Closed-interval overlap with 30-min buffer on new side; existing un-buffered."""
    buffered_start = new_start_dt - timedelta(minutes=30)
    buffered_end = new_end_dt + timedelta(minutes=30)
    for h in STORE.fair_hearings.values():
        if h["status"] != "SCHEDULED":
            continue
        if h["officer_id"] != officer_id:
            continue
        try:
            ex_start = parse_iso(h["scheduled_start"], "scheduled_start")
            ex_end = parse_iso(h["scheduled_end"], "scheduled_end")
        except Exception:
            continue
        # Closed-closed intersection: buffered_start <= ex_end AND ex_start <= buffered_end
        if buffered_start <= ex_end and ex_start <= buffered_end:
            return True
    return False


@bp.route("/appeals/<appeal_id>/schedule-hearing", methods=["POST"])
@require_roles("AppealsOfficer")
def schedule_hearing(appeal_id):
    appeal = _appeal_or_404(appeal_id)
    body = require_body(request)
    officer_id = require_field(body, "officer_id", kind="string")
    scheduled_start = require_field(body, "scheduled_start", kind="string")
    scheduled_end = require_field(body, "scheduled_end", kind="string")
    start_dt = parse_iso(scheduled_start, "scheduled_start")
    end_dt = parse_iso(scheduled_end, "scheduled_end")

    # Priority order:
    # 3 (same-actor) → 5 (state) → 7 (appeal-window) → 8 (hearing-time) → 9 (overlap)
    # Segregation-of-duties (priority 3): officer must differ from determining caseworker
    det = STORE.determinations.get(appeal["determination_id"])
    if det is not None and det.get("_decider_user_id") == g.user_id:
        raise_error(
            "ERR_FORBIDDEN_SAME_ACTOR",
            "AppealsOfficer cannot be the caseworker who issued the appealed determination",
        )
    if appeal["status"] != "FILED":
        raise_error("ERR_INVALID_STATE", "Appeal must be FILED to schedule a hearing")
    # Priority 7: hearing scheduled_start must be before Appeal.deadline_at
    deadline_dt = appeal["_deadline_at_dt"]
    if start_dt >= deadline_dt:
        raise_error("ERR_APPEAL_WINDOW_EXPIRED", "Hearing scheduled at or after appeal deadline")
    # Priority 8: start<end and both in future
    now = CLOCK.now()
    if not (start_dt < end_dt):
        raise_error("ERR_HEARING_NOT_DUE", "scheduled_start must be strictly before scheduled_end")
    if start_dt <= now or end_dt <= now:
        raise_error("ERR_HEARING_NOT_DUE", "scheduled_start and scheduled_end must be in the future")
    # Priority 9: overlap
    if _check_hearing_overlap(officer_id, start_dt, end_dt):
        raise_error("ERR_HEARING_CONFLICT",
                    "Hearing collides with another SCHEDULED hearing for this officer")

    with lock():
        hid = gen_id()
        h_row = {
            "id": hid,
            "appeal_id": appeal_id,
            "officer_id": officer_id,
            "scheduled_start": iso_format(start_dt),
            "scheduled_end": iso_format(end_dt),
            "status": "SCHEDULED",
        }
        stamp_create(h_row)
        STORE.fair_hearings[hid] = h_row
        appeal["status"] = "HEARING_SCHEDULED"
        appeal["officer_id"] = officer_id
        bump(appeal)
    return success_object(project_fair_hearing(h_row))


@bp.route("/appeals/<appeal_id>/grant", methods=["POST"])
@require_roles("AppealsOfficer")
def grant_appeal(appeal_id):
    appeal = _appeal_or_404(appeal_id)
    body = require_body(request) if request.content_length else {}
    outcome_reason = body.get("outcome_reason")
    # Same-actor: officer cannot be the determining caseworker
    det = STORE.determinations.get(appeal["determination_id"])
    if det is not None and det.get("_decider_user_id") == g.user_id:
        raise_error(
            "ERR_FORBIDDEN_SAME_ACTOR",
            "AppealsOfficer cannot be the caseworker who issued the appealed determination",
        )
    if appeal["status"] != "UNDER_REVIEW":
        raise_error("ERR_INVALID_STATE", "Appeal must be UNDER_REVIEW to grant")
    hearing = _associated_fair_hearing(appeal_id)
    if hearing is None or hearing["status"] != "HELD":
        raise_error("ERR_INVALID_STATE", "Associated FairHearing must be HELD")
    with lock():
        appeal["status"] = "GRANTED"
        if outcome_reason is not None:
            appeal["outcome_reason"] = outcome_reason
        bump(appeal)
        # Cascade hop 1: Determination.outcome = OVERTURNED
        if det is not None:
            det["outcome"] = "OVERTURNED"
            bump(det)
        # Cascade hop 2: Application -> UNDER_REVIEW
        if det is not None:
            application = STORE.applications.get(det["application_id"])
            if application is not None and application["status"] == "APPEALED":
                application["status"] = "UNDER_REVIEW"
                bump(application)
    return success_object(project_appeal(appeal))


@bp.route("/appeals/<appeal_id>/uphold", methods=["POST"])
@require_roles("AppealsOfficer")
def uphold_appeal(appeal_id):
    appeal = _appeal_or_404(appeal_id)
    body = require_body(request) if request.content_length else {}
    outcome_reason = body.get("outcome_reason")
    # Same-actor
    det = STORE.determinations.get(appeal["determination_id"])
    if det is not None and det.get("_decider_user_id") == g.user_id:
        raise_error(
            "ERR_FORBIDDEN_SAME_ACTOR",
            "AppealsOfficer cannot be the caseworker who issued the appealed determination",
        )
    if appeal["status"] != "UNDER_REVIEW":
        raise_error("ERR_INVALID_STATE", "Appeal must be UNDER_REVIEW to uphold")
    hearing = _associated_fair_hearing(appeal_id)
    if hearing is None or hearing["status"] != "HELD":
        raise_error("ERR_INVALID_STATE", "Associated FairHearing must be HELD")
    with lock():
        appeal["status"] = "UPHELD"
        if outcome_reason is not None:
            appeal["outcome_reason"] = outcome_reason
        bump(appeal)
        # Application stays DENIED — per PRD §3.6 "Application stays DENIED".
        if det is not None:
            application = STORE.applications.get(det["application_id"])
            if application is not None and application["status"] == "APPEALED":
                application["status"] = "DENIED"
                bump(application)
    return success_object(project_appeal(appeal))


@bp.route("/appeals/<appeal_id>/withdraw", methods=["POST"])
@require_roles("IntakeWorker")
def withdraw_appeal(appeal_id):
    appeal = _appeal_or_404(appeal_id)
    if appeal["status"] not in ("FILED", "HEARING_SCHEDULED"):
        raise_error("ERR_INVALID_STATE", "Appeal must be FILED or HEARING_SCHEDULED to withdraw")
    with lock():
        appeal["status"] = "WITHDRAWN"
        bump(appeal)
        # Cancel any SCHEDULED hearing
        for h in STORE.fair_hearings.values():
            if h["appeal_id"] == appeal_id and h["status"] == "SCHEDULED":
                h["status"] = "CANCELLED"
                bump(h)
    return success_object(project_appeal(appeal))
