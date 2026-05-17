"""Portal message endpoints: create, get, mark-read, archive, triage, escalate."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from ..auth import (
    ROLE_NURSE,
    ROLE_PATIENT_PORTAL,
    ROLE_PROVIDER,
    require_roles,
)
from ..clock import now
from ..errors import (
    err_forbidden,
    err_invalid_encounter_state,
    err_portal_disabled,
)
from ..helpers import (
    assert_string,
    new_uuid,
    occ_check,
    require_json_object,
)
from ..responses import created, ok
from ..services.lookups import get_patient, get_portal_message, get_provider
from ..services.mutations import bump
from ..services.serialize import portal_message_to_dict
from ..store import store

bp = Blueprint("portal", __name__)


def _enforce_portal_self_for_message(msg: dict, caller_id: str, caller_role: str) -> None:
    s = store()
    patient = s.patients.get(msg["patient_id"])
    if caller_role == ROLE_PATIENT_PORTAL:
        if patient is None or not patient.get("portal_enabled"):
            raise err_portal_disabled()
        if patient["id"] != caller_id:
            raise err_portal_disabled()


@bp.route("/portal/messages", methods=["POST"])
@require_roles(ROLE_PATIENT_PORTAL, ROLE_PROVIDER)
def create_portal_message(*, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        patient_id = assert_string(body.get("patient_id"), "patient_id")
        # reference check
        patient = get_patient(patient_id, source="body")
        provider_id = assert_string(body.get("provider_id"), "provider_id")
        provider = get_provider(provider_id, source="body")
        body_text = assert_string(body.get("body"), "body", min_len=1, max_len=2000)

        # Portal access constraint: §2.12 — Patient.portal_enabled true AND PatientPortalUser AND X-User-ID=patient.id
        if _caller_role == ROLE_PATIENT_PORTAL:
            if not patient.get("portal_enabled"):
                raise err_portal_disabled()
            if patient["id"] != _caller_id:
                raise err_portal_disabled()

        # Provider thread participant must equal Patient.pcp_provider_id
        if patient.get("pcp_provider_id") != provider_id:
            raise err_invalid_encounter_state(
                "provider_id must equal Patient.pcp_provider_id"
            )

        sender_role = "PATIENT" if _caller_role == ROLE_PATIENT_PORTAL else "PROVIDER"

        ts = now()
        row = {
            "id": new_uuid(),
            "patient_id": patient_id,
            "provider_id": provider_id,
            "sender_role": sender_role,
            "body": body_text,
            "status": "UNREAD",
            "triage_status": "NEW",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.portal_messages[row["id"]] = row
    return created(portal_message_to_dict(row))


@bp.route("/portal/messages/<mid>", methods=["GET"])
@require_roles(ROLE_PATIENT_PORTAL, ROLE_PROVIDER, ROLE_NURSE)
def get_portal_message_route(mid: str, *, _caller_id: str, _caller_role: str):
    s = store()
    with s.lock:
        msg = get_portal_message(mid)
        _enforce_portal_self_for_message(msg, _caller_id, _caller_role)
    return ok(portal_message_to_dict(msg))


@bp.route("/portal-messages/<mid>/mark-read", methods=["POST"])
@require_roles(ROLE_PATIENT_PORTAL, ROLE_PROVIDER)
def mark_read(mid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        msg = get_portal_message(mid)
        _enforce_portal_self_for_message(msg, _caller_id, _caller_role)
        if msg["status"] != "UNREAD":
            raise err_invalid_encounter_state(
                f"mark-read requires UNREAD status; current: {msg['status']}"
            )
        occ_check(body.get("version"), msg["version"])
        msg["status"] = "READ"
        bump(msg)
    return ok(portal_message_to_dict(msg))


@bp.route("/portal-messages/<mid>/archive", methods=["POST"])
@require_roles(ROLE_PATIENT_PORTAL, ROLE_PROVIDER)
def archive_message(mid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        msg = get_portal_message(mid)
        _enforce_portal_self_for_message(msg, _caller_id, _caller_role)
        if msg["status"] != "READ":
            raise err_invalid_encounter_state(
                f"archive requires READ status; current: {msg['status']}"
            )
        occ_check(body.get("version"), msg["version"])
        msg["status"] = "ARCHIVED"
        bump(msg)
    return ok(portal_message_to_dict(msg))


@bp.route("/portal-messages/<mid>/triage", methods=["POST"])
@require_roles(ROLE_NURSE)
def triage_message(mid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        msg = get_portal_message(mid)
        if msg["triage_status"] != "NEW":
            raise err_invalid_encounter_state(
                f"triage requires NEW triage_status; current: {msg['triage_status']}"
            )
        if msg["sender_role"] != "PATIENT":
            raise err_invalid_encounter_state(
                "only PATIENT-authored messages may be triaged"
            )
        occ_check(body.get("version"), msg["version"])
        msg["triage_status"] = "TRIAGED"
        bump(msg)
    return ok(portal_message_to_dict(msg))


@bp.route("/portal-messages/<mid>/escalate", methods=["POST"])
@require_roles(ROLE_NURSE)
def escalate_message(mid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        msg = get_portal_message(mid)
        if msg["triage_status"] != "TRIAGED":
            raise err_invalid_encounter_state(
                f"escalate requires TRIAGED triage_status; current: {msg['triage_status']}"
            )
        occ_check(body.get("version"), msg["version"])
        msg["triage_status"] = "ESCALATED"
        bump(msg)

        # Cascade: auto-schedule a CONSULTATION encounter within 24h with patient's bound PCP
        patient = s.patients.get(msg["patient_id"])
        if patient is not None and patient.get("pcp_provider_id"):
            ts = now()
            start = ts + timedelta(hours=1)
            end = start + timedelta(minutes=30)
            enc = {
                "id": new_uuid(),
                "patient_id": patient["id"],
                "provider_id": patient["pcp_provider_id"],
                "encounter_type": "CONSULTATION",
                "scheduled_start": start,
                "scheduled_end": end,
                "actual_start": None,
                "actual_end": None,
                "chief_complaint": "Auto-scheduled from escalated portal message",
                "vital_signs": None,
                "bmi": None,
                "status": "SCHEDULED",
                "created_at": ts,
                "updated_at": ts,
                "version": 1,
            }
            s.encounters[enc["id"]] = enc
    return ok(portal_message_to_dict(msg))
