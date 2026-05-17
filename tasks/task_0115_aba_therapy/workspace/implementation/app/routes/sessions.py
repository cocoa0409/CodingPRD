"""TherapySession endpoints — PRD §3.5."""
from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..clock import add_days, diff_minutes, parse_iso
from ..errors import APIError
from ..helpers import (
    get_json_body,
    get_pagination_params,
    optional_field,
    paginate,
    require_field,
)
from ..responses import list_response, success_response
from ..services.calculations import (
    ceil_units,
    provisional_balance,
    recompute_authorization_consumption,
    recompute_patient_progress_scores,
)
from ..services.ledger import append_ledger_entry
from ..services.lookups import (
    get_authorization,
    get_patient,
    get_session,
    get_therapist,
)
from ..services.serialize import serialize_session
from ..store import get_lock, get_store, stamp_create, stamp_update


bp = Blueprint("sessions", __name__)


SESSION_TYPES = {"DIRECT_RBT", "BCBA_SUPERVISION", "PARENT_TRAINING"}
CPT_FOR_TYPE = {
    "DIRECT_RBT": "97153",
    "BCBA_SUPERVISION": "97155",
    "PARENT_TRAINING": "97156",
}
MIN_SESSION_MINUTES = 15
MAX_SESSION_MINUTES = 480
THERAPIST_BLOCKING_STATUSES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "BILLED", "DISPUTED"}


def _intervals_half_open_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    """True iff [a_start, a_end) and [b_start, b_end) overlap (touching is allowed)."""
    a_s = parse_iso(a_start)
    a_e = parse_iso(a_end)
    b_s = parse_iso(b_start)
    b_e = parse_iso(b_end)
    return (a_s < b_e) and (b_s < a_e)


def _intervals_closed_buffer_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    """Closed-closed overlap with 15-minute buffer on EACH side of the parent-training session.

    The parent-training session is the candidate (a). We expand a by 15 minutes
    on each side and then ask whether [a_start-15min, a_end+15min] intersects
    [b_start, b_end] inclusively (touching is a conflict).
    """
    a_s = parse_iso(add_days_minutes(a_start, -15))
    a_e = parse_iso(add_days_minutes(a_end, 15))
    b_s = parse_iso(b_start)
    b_e = parse_iso(b_end)
    return (a_s <= b_e) and (b_s <= a_e)


def add_days_minutes(base_iso: str, minutes: int) -> str:
    """Internal helper: shift an ISO timestamp by signed minutes."""
    from datetime import timedelta
    from ..clock import format_iso
    return format_iso(parse_iso(base_iso) + timedelta(minutes=minutes))


@bp.post("/patients/<patient_id>/sessions")
@require_auth("ClinicAdmin", "BCBA")
def create_session(patient_id):
    body = get_json_body()
    with get_lock():
        patient = get_patient(patient_id)
        clinic = get_store().clinics[patient["clinic_id"]]
        store = get_store()

        authorization_id = require_field(body, "authorization_id")
        therapist_id = require_field(body, "therapist_id")
        session_type = require_field(body, "session_type")
        planned_start = require_field(body, "planned_start")
        planned_end = require_field(body, "planned_end")
        supervising_therapist_id = optional_field(body, "supervising_therapist_id")

        if session_type not in SESSION_TYPES:
            raise APIError("ERR_VALIDATION",
                           f"session_type must be one of {sorted(SESSION_TYPES)}")
        ps_dt = parse_iso(planned_start)
        pe_dt = parse_iso(planned_end)
        if pe_dt <= ps_dt:
            raise APIError("ERR_VALIDATION", "planned_end must be strictly after planned_start")
        minutes = diff_minutes(planned_start, planned_end)
        if minutes < MIN_SESSION_MINUTES or minutes > MAX_SESSION_MINUTES:
            raise APIError("ERR_VALIDATION",
                           f"session length must be in [{MIN_SESSION_MINUTES}, {MAX_SESSION_MINUTES}] minutes")
        planned_units = ceil_units(minutes)

        # Body FK resolution after path resolution.
        auth = get_authorization(authorization_id)
        if auth["patient_id"] != patient_id:
            raise APIError("ERR_VALIDATION",
                           "authorization must belong to the same patient")
        therapist = get_therapist(therapist_id)
        if therapist["clinic_id"] != patient["clinic_id"]:
            raise APIError("ERR_VALIDATION",
                           "therapist must belong to the same clinic as the patient")

        # State precondition: Authorization must be ACTIVE.
        if auth["status"] != "ACTIVE":
            raise APIError("ERR_INVALID_STATE",
                           f"Authorization must be ACTIVE (is {auth['status']})")

        # CPT/session-type alignment (priority 12).
        expected_cpt = CPT_FOR_TYPE[session_type]
        if auth["cpt_code"] != expected_cpt:
            raise APIError("ERR_CPT_CODE_MISMATCH",
                           f"session_type {session_type} requires CPT {expected_cpt}, "
                           f"authorization has {auth['cpt_code']}")

        # BCBA_SUPERVISION requires an eligible RBT (priority 13).
        if session_type == "BCBA_SUPERVISION":
            if supervising_therapist_id is None:
                raise APIError("ERR_NO_RBT_TO_SUPERVISE",
                               "supervising_therapist_id required for BCBA_SUPERVISION")
            rbt = store.therapists.get(supervising_therapist_id)
            if rbt is None:
                raise APIError("ERR_NO_RBT_TO_SUPERVISE",
                               "supervising_therapist_id not found")
            if rbt["credential"] != "RBT" or rbt["status"] != "ACTIVE":
                raise APIError("ERR_NO_RBT_TO_SUPERVISE",
                               "supervising therapist must be an ACTIVE RBT")
            if rbt["clinic_id"] != patient["clinic_id"]:
                raise APIError("ERR_NO_RBT_TO_SUPERVISE",
                               "supervising RBT must belong to the same clinic")
            # Must have at least one COMPLETED|BILLED session with this patient in trailing 30 days.
            now_ts = clinic["now_ts"]
            window_start = add_days(now_ts, -30)
            ws_dt = parse_iso(window_start)
            we_dt = parse_iso(now_ts)
            has_session = False
            for s in store.sessions.values():
                if s["patient_id"] != patient_id:
                    continue
                if s["therapist_id"] != supervising_therapist_id:
                    continue
                if s["status"] not in ("COMPLETED", "BILLED"):
                    continue
                if not s.get("actual_end"):
                    continue
                ae = parse_iso(s["actual_end"])
                if (ae > ws_dt) and (ae <= we_dt):
                    has_session = True
                    break
            if not has_session:
                raise APIError("ERR_NO_RBT_TO_SUPERVISE",
                               "RBT has no qualifying session with patient in trailing 30 days")
        else:
            supervising_therapist_id = None  # ignored for non-supervision types

        # Therapist overlap (priority 14): half-open intervals on [planned_start, planned_end).
        for s in store.sessions.values():
            if s["therapist_id"] != therapist_id:
                continue
            if s["status"] not in THERAPIST_BLOCKING_STATUSES:
                continue
            if _intervals_half_open_overlap(planned_start, planned_end,
                                            s["planned_start"], s["planned_end"]):
                raise APIError("ERR_SESSION_THERAPIST_OVERLAP",
                               "Overlapping session for this therapist")

        # Parent-training buffer (priority 15): closed-closed with 15-min buffer.
        if session_type == "PARENT_TRAINING":
            for s in store.sessions.values():
                if s["patient_id"] != patient_id:
                    continue
                if s["status"] not in THERAPIST_BLOCKING_STATUSES:
                    continue
                if _intervals_closed_buffer_overlap(planned_start, planned_end,
                                                    s["planned_start"], s["planned_end"]):
                    raise APIError("ERR_PARENT_TRAINING_BUFFER",
                                   "Parent-training buffer rule violated")

        # Temporal window (priority 16).
        es_dt = parse_iso(auth["effective_start"])
        ee_dt = parse_iso(auth["effective_end"])
        now_dt = parse_iso(clinic["now_ts"])
        if ps_dt < now_dt:
            raise APIError("ERR_SESSION_OUTSIDE_AUTH_WINDOW",
                           "planned_start cannot be in the past")
        if ps_dt < es_dt or pe_dt > ee_dt:
            raise APIError("ERR_SESSION_OUTSIDE_AUTH_WINDOW",
                           "session interval must fit within authorization window")

        # Fiscal: planned_units <= provisional_balance (priority 17).
        if planned_units > provisional_balance(auth):
            raise APIError("ERR_AUTH_UNITS_EXHAUSTED",
                           "planned_units exceed authorization's provisional balance")

        record = stamp_create(
            {
                "patient_id": patient_id,
                "authorization_id": authorization_id,
                "therapist_id": therapist_id,
                "supervising_therapist_id": supervising_therapist_id,
                "session_type": session_type,
                "planned_start": planned_start,
                "planned_end": planned_end,
                "actual_start": None,
                "actual_end": None,
                "planned_units": planned_units,
                "billed_units": None,
                "dispute_reason": None,
                "progress_rating": None,
                "status": "SCHEDULED",
            },
            now=clinic["now_ts"],
        )
        store.sessions[record["id"]] = record

    body_out, status = success_response(serialize_session(record), status=201)
    return jsonify(body_out), status


@bp.post("/sessions/<session_id>/start")
@require_auth("BCBA", "RBT")
def start_session(session_id):
    with get_lock():
        s = get_session(session_id)
        if s["therapist_id"] != g.user_id:
            raise APIError("ERR_NOT_THERAPIST_OF_RECORD",
                           "Acting therapist is not this session's therapist_id")
        if s["status"] != "SCHEDULED":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot start session in status {s['status']}")
        store = get_store()
        auth = store.authorizations[s["authorization_id"]]
        if auth["status"] != "ACTIVE":
            raise APIError("ERR_INVALID_STATE",
                           f"Authorization must be ACTIVE (is {auth['status']})")
        # CPT alignment re-check.
        expected_cpt = CPT_FOR_TYPE[s["session_type"]]
        if auth["cpt_code"] != expected_cpt:
            raise APIError("ERR_CPT_CODE_MISMATCH",
                           "Authorization cpt_code no longer aligns with session_type")
        patient = get_patient(s["patient_id"])
        clinic = store.clinics[patient["clinic_id"]]
        now_dt = parse_iso(clinic["now_ts"])
        if not (parse_iso(auth["effective_start"]) <= now_dt <= parse_iso(auth["effective_end"])):
            raise APIError("ERR_SESSION_OUTSIDE_AUTH_WINDOW",
                           "clinic.now_ts is outside authorization effective window")

        s["actual_start"] = clinic["now_ts"]
        s["status"] = "IN_PROGRESS"
        stamp_update(s, now=clinic["now_ts"])

    body_out, status = success_response(serialize_session(s))
    return jsonify(body_out), status


@bp.post("/sessions/<session_id>/complete")
@require_auth("BCBA", "RBT")
def complete_session(session_id):
    body = get_json_body()
    with get_lock():
        s = get_session(session_id)
        if s["therapist_id"] != g.user_id:
            raise APIError("ERR_NOT_THERAPIST_OF_RECORD",
                           "Acting therapist is not this session's therapist_id")
        if s["status"] != "IN_PROGRESS":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot complete session in status {s['status']}")
        progress_rating = require_field(body, "progress_rating")
        if not isinstance(progress_rating, int) or isinstance(progress_rating, bool):
            raise APIError("ERR_VALIDATION", "progress_rating must be an integer")
        if not (1 <= progress_rating <= 5):
            raise APIError("ERR_VALIDATION", "progress_rating must be in [1, 5]")

        store = get_store()
        patient = get_patient(s["patient_id"])
        clinic = store.clinics[patient["clinic_id"]]
        if parse_iso(clinic["now_ts"]) <= parse_iso(s["actual_start"]):
            raise APIError("ERR_INVALID_STATE",
                           "clinic.now_ts must be strictly after actual_start")

        now_ts = clinic["now_ts"]
        s["actual_end"] = now_ts
        elapsed_minutes = diff_minutes(s["actual_start"], now_ts)
        s["billed_units"] = ceil_units(elapsed_minutes)
        s["progress_rating"] = progress_rating
        s["status"] = "COMPLETED"
        stamp_update(s, now=now_ts)

        # Append PROVISIONAL_DEBIT, recompute authorization consumption and patient progress.
        auth = store.authorizations[s["authorization_id"]]
        append_ledger_entry(
            authorization_id=auth["id"],
            entry_type="PROVISIONAL_DEBIT",
            units_delta=-s["billed_units"],
            reason_code="SESSION_COMPLETED",
            now=now_ts,
            session_id=s["id"],
        )
        recompute_authorization_consumption(auth)
        recompute_patient_progress_scores(patient, now_ts)

    body_out, status = success_response(serialize_session(s))
    return jsonify(body_out), status


@bp.post("/sessions/<session_id>/dispute")
@require_auth("BCBA")
def dispute_session(session_id):
    body = get_json_body()
    dispute_reason = require_field(body, "dispute_reason")
    if not isinstance(dispute_reason, str) or not dispute_reason.strip():
        raise APIError("ERR_VALIDATION", "dispute_reason must be a non-empty string")
    with get_lock():
        s = get_session(session_id)
        if s["status"] != "COMPLETED":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot dispute session in status {s['status']}")
        store = get_store()
        # Session must not appear in any non-DENIED non-DRAFT claim.
        for c in store.claims.values():
            if s["id"] in c["session_ids"] and c["status"] in (
                "SUBMITTED", "ADJUDICATED", "PAID", "APPEALED",
            ):
                raise APIError("ERR_INVALID_STATE",
                               "Session is part of an in-flight claim and cannot be disputed")

        patient = get_patient(s["patient_id"])
        clinic = store.clinics[patient["clinic_id"]]
        now_ts = clinic["now_ts"]

        s["dispute_reason"] = dispute_reason
        s["status"] = "DISPUTED"
        stamp_update(s, now=now_ts)

        auth = store.authorizations[s["authorization_id"]]
        append_ledger_entry(
            authorization_id=auth["id"],
            entry_type="PROVISIONAL_CREDIT",
            units_delta=+s["billed_units"],
            reason_code="SESSION_DISPUTED",
            now=now_ts,
            session_id=s["id"],
        )
        recompute_authorization_consumption(auth)
        recompute_patient_progress_scores(patient, now_ts)

    body_out, status = success_response(serialize_session(s))
    return jsonify(body_out), status


@bp.post("/sessions/<session_id>/resolve-dispute")
@require_auth("BCBA")
def resolve_dispute(session_id):
    with get_lock():
        s = get_session(session_id)
        if s["status"] != "DISPUTED":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot resolve dispute on session in status {s['status']}")
        store = get_store()
        patient = get_patient(s["patient_id"])
        clinic = store.clinics[patient["clinic_id"]]
        now_ts = clinic["now_ts"]
        s["status"] = "COMPLETED"
        stamp_update(s, now=now_ts)

        auth = store.authorizations[s["authorization_id"]]
        append_ledger_entry(
            authorization_id=auth["id"],
            entry_type="PROVISIONAL_DEBIT",
            units_delta=-s["billed_units"],
            reason_code="SESSION_COMPLETED",
            now=now_ts,
            session_id=s["id"],
        )
        recompute_authorization_consumption(auth)
        recompute_patient_progress_scores(patient, now_ts)

    body_out, status = success_response(serialize_session(s))
    return jsonify(body_out), status


@bp.post("/sessions/<session_id>/cancel")
@require_auth("ClinicAdmin", "BCBA")
def cancel_session(session_id):
    with get_lock():
        s = get_session(session_id)
        if s["status"] != "SCHEDULED":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot cancel session in status {s['status']}")
        patient = get_patient(s["patient_id"])
        clinic = get_store().clinics[patient["clinic_id"]]
        s["status"] = "CANCELLED"
        stamp_update(s, now=clinic["now_ts"])
    body_out, status = success_response(serialize_session(s))
    return jsonify(body_out), status


@bp.get("/patients/<patient_id>/sessions")
@require_auth("BCBA", "RBT", "ClinicAdmin", "PayerAdmin")
def list_sessions(patient_id):
    limit, offset = get_pagination_params()
    status_filter = request.args.get("status")
    session_type_filter = request.args.get("session_type")
    therapist_filter = request.args.get("therapist_id")
    with get_lock():
        get_patient(patient_id)
        items = []
        for s in get_store().sessions.values():
            if s["patient_id"] != patient_id:
                continue
            if status_filter is not None and s["status"] != status_filter:
                continue
            if session_type_filter is not None and s["session_type"] != session_type_filter:
                continue
            if therapist_filter is not None and s["therapist_id"] != therapist_filter:
                continue
            items.append(s)
        items.sort(key=lambda s: s["created_at"])
        page, total = paginate(items, limit, offset)
        body_out, status = list_response(
            [serialize_session(s) for s in page], total, limit, offset
        )
    return jsonify(body_out), status
