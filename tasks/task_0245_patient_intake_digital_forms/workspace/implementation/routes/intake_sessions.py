"""IntakeSession routes: open, read, list, and the workflow + financial
lifecycle transitions (PRD §3.3, §3.4, §3.10).
"""
from flask import Blueprint, request

import clock
import db
import serialize
from errors import (
    err,
    ERR_SESSION_NOT_READY,
    ERR_CONSENT_NOT_SIGNED,
    ERR_SESSION_NOT_CHECKED_IN,
    ERR_QUEUE_ENTRY_NOT_DONE,
    ERR_COPAY_UNSETTLED,
    ERR_SESSION_NOT_CANCELLABLE,
    ERR_COPAY_NOT_DUE,
    ERR_WAIVE_BLOCKED_HIGH_RISK,
)
from middleware import require_roles
from response import success, success_list
from services.common import touch, require_string
from services.lookups import get_appointment, get_session
from services.pagination import paginate
from services import sessions as S

bp = Blueprint("intake_sessions", __name__)


@bp.route("/intake-sessions", methods=["POST"])
@require_roles("ClinicAdmin", "FrontDeskStaff")
def open_session():
    body = request.get_json(silent=True) or {}
    appointment_id = require_string(body, "appointment_id")
    appt = get_appointment(appointment_id)

    clinic = db.clinics[appt["clinic_id"]]
    # PRD §2.6/§1.3: time does not come from the wall clock. A session's
    # created_at is the clinic's deterministic current_utc at creation, and
    # expires_at = created_at + clinic.form_expiration_hours, so that the
    # clock-driven expiration sweep is reproducible.
    now = clinic["current_utc"]
    created_dt = clock.parse_instant(now)
    expires_dt = clock.add_hours(created_dt, clinic["form_expiration_hours"])

    with db.LOCK:
        session = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": db.next_seq(),
            "appointment_id": appointment_id,
            "clinic_id": appt["clinic_id"],
            "provider_id": appt["provider_id"],
            "patient_id": appt["patient_id"],
            "expires_at": clock.format_instant(expires_dt),
            "workflow_status": "DRAFT",
            "financial_status": "PENDING_ELIGIBILITY",
            "forms_complete": False,
            "final_patient_responsibility_cents": None,
        }
        db.intake_sessions[session["id"]] = session
        # Parent appointment status -> INTAKE_OPENED (PRD §3.3).
        appt["status"] = "INTAKE_OPENED"
        touch(appt)
    return success(serialize.intake_session(session), status=201)


@bp.route("/intake-sessions/<sid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_session_route(sid):
    session = get_session(sid)
    return success(serialize.intake_session(session), status=200)


@bp.route("/intake-sessions", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_sessions():
    records = list(db.intake_sessions.values())
    for f in ("appointment_id", "clinic_id", "provider_id", "patient_id"):
        val = request.args.get(f)
        if val is not None:
            records = [r for r in records if r[f] == val]
    items, limit, offset, total = paginate(records, serialize.intake_session)
    return success_list(items, limit, offset, total)


@bp.route("/intake-sessions/<sid>/check-in", methods=["POST"])
@require_roles("FrontDeskStaff")
def check_in(sid):
    session = get_session(sid)
    with db.LOCK:
        if session["workflow_status"] != "READY_FOR_VISIT":
            raise err(ERR_SESSION_NOT_READY, "session not READY_FOR_VISIT")
        # Every required consent must currently be SIGNED (PRD §3.3).
        provider = db.providers[session["provider_id"]]
        required_codes = provider.get("required_consent_codes") or []
        signed_codes = {c["consent_code"] for c in S.session_consents(session["id"])
                        if c["status"] == "SIGNED"}
        if not all(code in signed_codes for code in required_codes):
            raise err(ERR_CONSENT_NOT_SIGNED, "a required consent is not signed")
        session["workflow_status"] = "CHECKED_IN"
        touch(session)
    return success(serialize.intake_session(session), status=200)


@bp.route("/intake-sessions/<sid>/complete", methods=["POST"])
@require_roles("FrontDeskStaff")
def complete(sid):
    session = get_session(sid)
    with db.LOCK:
        if session["workflow_status"] != "CHECKED_IN":
            raise err(ERR_SESSION_NOT_CHECKED_IN, "session not CHECKED_IN")
        # The session's queue entry must be DONE (PRD §3.3).
        done = any(q["intake_session_id"] == session["id"] and q["status"] == "DONE"
                   for q in db.queue_entries.values())
        if not done:
            raise err(ERR_QUEUE_ENTRY_NOT_DONE, "queue entry not DONE")
        # financial dimension must not still be COPAY_DUE (PRD §3.3).
        if session["financial_status"] == "COPAY_DUE":
            raise err(ERR_COPAY_UNSETTLED, "copay unsettled")
        session["workflow_status"] = "COMPLETED"
        touch(session)
    return success(serialize.intake_session(session), status=200)


@bp.route("/intake-sessions/<sid>/cancel", methods=["POST"])
@require_roles("FrontDeskStaff")
def cancel(sid):
    session = get_session(sid)
    with db.LOCK:
        if session["workflow_status"] not in {"DRAFT", "IN_PROGRESS", "READY_FOR_VISIT"}:
            raise err(ERR_SESSION_NOT_CANCELLABLE, "session not cancellable")
        session["workflow_status"] = "CANCELLED"
        touch(session)
        # Cascade: NO_SHOW any active queue entry (PRD §3.3).
        entry = S.session_active_queue_entry(session["id"])
        if entry is not None:
            S.eject_queue_entry(entry)
        # Cascade: every SCHEDULED reminder -> CANCELLED.
        for r in S.session_scheduled_reminders(session["id"]):
            r["status"] = "CANCELLED"
            touch(r)
    return success(serialize.intake_session(session), status=200)


@bp.route("/intake-sessions/<sid>/waive-copay", methods=["POST"])
@require_roles("BillingClerk")
def waive_copay(sid):
    session = get_session(sid)
    with db.LOCK:
        if session["financial_status"] != "COPAY_DUE":
            raise err(ERR_COPAY_NOT_DUE, "financial_status not COPAY_DUE")
        # Blocked when the session's questionnaire is high-risk (PRD §3.10).
        q = S.session_questionnaire(session["id"])
        if q is not None and q.get("high_risk_flag"):
            raise err(ERR_WAIVE_BLOCKED_HIGH_RISK, "waive blocked: high risk")
        S.set_financial(session, "WAIVED")
        # Becoming WAIVED may satisfy the financial gate for readiness.
        S.bubble_up(session)
    return success(serialize.intake_session(session), status=200)
