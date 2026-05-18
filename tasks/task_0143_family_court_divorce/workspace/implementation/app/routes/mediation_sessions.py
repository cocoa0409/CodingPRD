"""MediationSession routes (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint

from app import serializers, store
from app.auth import require_roles, role, user_id
from app.envelope import success, success_list
from app.errors import ApiError, forbidden, invalid_state, not_found
from app.services import case_service
from app.store import lock, new_id, now, parse_iso
from app.util import get_json_body, pagination_args, paginate


bp = Blueprint("mediation_sessions", __name__)


def _case_or_404(case_id):
    case = store.cases.get(case_id)
    if not case:
        raise not_found("Case not found")
    return case


def _session_or_404(case_id, sid):
    s = store.mediation_sessions.get(sid)
    if not s or s["case_id"] != case_id:
        raise not_found("Mediation session not found on this case")
    return s


def _intervals_overlap(a_start, a_end, b_start, b_end):
    # Half-open [start, end) intersection.
    return a_start < b_end and b_start < a_end


# ---------- schedule ------------------------------------------------------

@bp.post("/cases/<case_id>/mediation-sessions")
def schedule_session(case_id):
    require_roles("Mediator", "Judge")
    body = get_json_body()
    with lock():
        case = _case_or_404(case_id)
        mediator_user_id = body.get("mediator_user_id")
        if not mediator_user_id:
            raise invalid_state("mediator_user_id is required")
        start = parse_iso(body.get("scheduled_start_at"))
        end = parse_iso(body.get("scheduled_end_at"))
        if start is None or end is None:
            raise invalid_state("Invalid scheduled_start_at/scheduled_end_at")
        if end <= start:
            raise invalid_state("scheduled_end_at must be after scheduled_start_at")
        duration_minutes = int((end - start).total_seconds() // 60)
        if duration_minutes not in {60, 120, 180}:
            raise invalid_state("Session length must be 60, 120, or 180 minutes")

        # Mediation cap check (validation priority 15) for *this case*.
        if case["mediation_round"] >= 3:
            raise ApiError(
                "ERR_MEDIATION_CAP_REACHED",
                409,
                "Mediation round cap (3) already reached for this case",
            )

        # Double-booking across all cases for the same mediator.
        for other in store.mediation_sessions.values():
            if other["mediator_user_id"] != mediator_user_id:
                continue
            if other["status"] not in {"SCHEDULED", "IN_PROGRESS"}:
                continue
            if _intervals_overlap(start, end, other["scheduled_start_at"], other["scheduled_end_at"]):
                raise ApiError(
                    "ERR_MEDIATOR_DOUBLE_BOOKED",
                    409,
                    "Mediator is already booked for an overlapping interval",
                )

        ts = now()
        session = {
            "id": new_id(),
            "case_id": case_id,
            "mediator_user_id": mediator_user_id,
            "scheduled_start_at": start,
            "scheduled_end_at": end,
            "round_index": case["mediation_round"] + 1,
            "status": "SCHEDULED",
            "outcome": None,
            "parenting_plan_id": None,
            "created_at": ts,
        }
        store.mediation_sessions[session["id"]] = session
        return success(serializers.mediation_session(session), status=201)


# ---------- start ---------------------------------------------------------

@bp.post("/cases/<case_id>/mediation-sessions/<session_id>/start")
def start_session(case_id, session_id):
    require_roles("Mediator")
    with lock():
        _case_or_404(case_id)
        session = _session_or_404(case_id, session_id)
        if session["status"] != "SCHEDULED":
            raise invalid_state("Session is not SCHEDULED")
        ts = now()
        window_open = session["scheduled_start_at"] - timedelta(minutes=15)
        if ts < window_open or ts > session["scheduled_end_at"]:
            raise ApiError("ERR_SESSION_OUT_OF_WINDOW", 409, "Outside start window")
        session["status"] = "IN_PROGRESS"
        return success(serializers.mediation_session(session))


# ---------- complete ------------------------------------------------------

@bp.post("/cases/<case_id>/mediation-sessions/<session_id>/complete")
def complete_session(case_id, session_id):
    require_roles("Mediator")
    body = get_json_body()
    with lock():
        case = _case_or_404(case_id)
        session = _session_or_404(case_id, session_id)
        if session["status"] != "IN_PROGRESS":
            raise invalid_state("Session is not IN_PROGRESS")
        outcome = body.get("outcome")
        if outcome not in {"AGREEMENT", "PARTIAL", "IMPASSE"}:
            raise ApiError("ERR_OUTCOME_REQUIRED", 422, "Missing or invalid outcome")
        plan_id = body.get("parenting_plan_id")
        target_plan = None
        if outcome in {"AGREEMENT", "PARTIAL"}:
            if not plan_id:
                raise invalid_state("parenting_plan_id required for this outcome")
            target_plan = store.parenting_plans.get(plan_id)
            if not target_plan or target_plan["case_id"] != case_id:
                raise not_found("parenting_plan_id not found on this case")

        ts = now()
        session["status"] = "COMPLETED"
        session["outcome"] = outcome
        session["parenting_plan_id"] = plan_id
        case["mediation_round"] += 1
        case["updated_at"] = ts
        case["version"] += 1

        # AGREEMENT cascade: auto-AGREE the named plan when disclosures are ACCEPTED.
        if outcome == "AGREEMENT" and target_plan is not None:
            if case_service.both_disclosures_accepted(case_id) and target_plan["status"] in {"PROPOSED", "COUNTERED"}:
                p_disc = case_service.latest_accepted_disclosure(case_id, case["petitioner_party_id"])
                r_disc = case_service.latest_accepted_disclosure(case_id, case["respondent_party_id"])
                target_plan["pinned_petitioner_disclosure_version"] = int(p_disc["version"])
                target_plan["pinned_respondent_disclosure_version"] = int(r_disc["version"])
                target_plan["status"] = "AGREED"
                target_plan["updated_at"] = ts
                target_plan["version"] += 1

        # IMPASSE & cap reached: the latest active plan goes CONTESTED.
        if outcome == "IMPASSE" and case["mediation_round"] >= 3:
            latest = case_service.latest_active_plan(case_id)
            if latest is not None:
                latest["status"] = "CONTESTED"
                latest["updated_at"] = ts
                latest["version"] += 1

        # Possibly advance the case to AWAITING_JUDGMENT.
        case_service.maybe_advance_mediation_to_judgment(case, ts)
        return success(serializers.mediation_session(session))


# ---------- cancel --------------------------------------------------------

@bp.post("/cases/<case_id>/mediation-sessions/<session_id>/cancel")
def cancel_session(case_id, session_id):
    require_roles("Mediator", "Judge")
    with lock():
        _case_or_404(case_id)
        session = _session_or_404(case_id, session_id)
        if session["status"] != "SCHEDULED":
            raise invalid_state("Session is not SCHEDULED")
        ts = now()
        if ts >= session["scheduled_start_at"]:
            raise ApiError("ERR_SESSION_ALREADY_STARTED", 409, "Session has already started")
        session["status"] = "CANCELLED"
        return success(serializers.mediation_session(session))


# ---------- no-show -------------------------------------------------------

@bp.post("/cases/<case_id>/mediation-sessions/<session_id>/no-show")
def no_show_session(case_id, session_id):
    require_roles("Mediator", "Judge")
    with lock():
        case = _case_or_404(case_id)
        session = _session_or_404(case_id, session_id)
        if session["status"] != "SCHEDULED":
            raise invalid_state("Session is not SCHEDULED")
        ts = now()
        if ts <= session["scheduled_end_at"]:
            raise ApiError("ERR_SESSION_NOT_OVER", 409, "Session has not finished yet")
        session["status"] = "NO_SHOW"
        case["mediation_round"] += 1
        case["updated_at"] = ts
        case["version"] += 1
        return success(serializers.mediation_session(session))


# ---------- list ----------------------------------------------------------

@bp.get("/cases/<case_id>/mediation-sessions")
def list_sessions(case_id):
    require_roles("Petitioner", "Respondent", "Judge", "Mediator", "AttorneyOfRecord")
    case = _case_or_404(case_id)
    r = role()
    uid = user_id()
    if r == "Petitioner" and uid != case["petitioner_party_id"]:
        raise forbidden("Caller is not the petitioner on this case")
    if r == "Respondent" and uid != case["respondent_party_id"]:
        raise forbidden("Caller is not the respondent on this case")
    if r == "AttorneyOfRecord":
        pet = store.parties.get(case["petitioner_party_id"])
        res = store.parties.get(case["respondent_party_id"])
        if not ((pet and pet.get("counsel_user_id") == uid) or (res and res.get("counsel_user_id") == uid)):
            raise forbidden("Attorney is not counsel for any party on this case")

    limit, offset = pagination_args()
    items = [s for s in store.mediation_sessions.values() if s["case_id"] == case_id]
    page, total = paginate(items, limit, offset)
    return success_list([serializers.mediation_session(s) for s in page], limit, offset, total)
