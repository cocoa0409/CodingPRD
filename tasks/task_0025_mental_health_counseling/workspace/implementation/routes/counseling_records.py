"""Counseling record endpoints (encrypted notes)."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from clock import now, iso, parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import audit
from services.validation import get_body, require_str


bp = Blueprint("counseling_records", __name__)


RISK_KEYWORDS = ["suicide", "self-harm", "kill myself", "end it"]


def _public(r: dict, *, include_blob: bool = True) -> dict:
    out = {k: v for k, v in r.items() if not k.startswith("_") and k != "content_key_wrapped"}
    if not include_blob:
        out.pop("encrypted_note_blob", None)
    return out


def _has_risk_keyword(text: str) -> str:
    """Scan PRD §3.6 risk-keyword set over the supplied note.

    The API field is ``encrypted_note_blob`` (base64-armored ciphertext per
    SCAFFOLD; PRD §3.6 prose describes scanning "the supplied note"
    case-insensitive). To recover plaintext from a base64 blob the scan
    decodes first, falling back to the raw string if decoding fails so a
    plaintext-only blob still matches.
    """
    if not isinstance(text, str):
        return None
    candidates = [text]
    try:
        import base64
        decoded = base64.b64decode(text, validate=False).decode("utf-8", errors="ignore")
        if decoded:
            candidates.append(decoded)
    except Exception:
        pass
    for cand in candidates:
        lc = cand.lower()
        for kw in RISK_KEYWORDS:
            if kw in lc:
                return kw
    return None


def _owns_appointment(counselor_id, appt_id):
    appt = db.appointments.get(appt_id)
    return appt is not None and appt["counselor_id"] == counselor_id


def _is_supervisor_of_record(supervisor_user_id, record):
    """A Supervisor may read records of supervisees whose SupervisionSession lists them."""
    counselor_id = record["counselor_id"]
    for s in db.supervision_sessions.values():
        if s["counselor_id"] == counselor_id and s["supervisor_id"] == supervisor_user_id:
            return True
    return False


@bp.route("/counseling/counseling-records", methods=["POST"])
@require_auth(roles={"Counselor"})
def create_record():
    body = get_body()
    appointment_id = require_str(body, "appointment_id")
    encrypted_note_blob = require_str(body, "encrypted_note_blob")
    crisis_acknowledged = bool(body.get("crisis_acknowledged", False))

    appt = db.appointments.get(appointment_id)
    if appt is None:
        raise err("ERR_REF_NOT_FOUND", f"appointment_id {appointment_id} not found")
    if appt["counselor_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "Counselor may only write records for own appointments")
    if appt["status"] != "COMPLETED" and appt["status"] != "IN_SESSION":
        raise err("ERR_INVALID_STATE",
                  f"Cannot write record for appointment in status {appt['status']}")

    # Uniqueness on appointment_id
    for r in db.counseling_records.values():
        if r["appointment_id"] == appointment_id:
            raise err("ERR_RECORD_ALREADY_EXISTS",
                      "CounselingRecord already exists for this appointment")

    # Risk-keyword scan (only when not acknowledged)
    if not crisis_acknowledged:
        kw = _has_risk_keyword(encrypted_note_blob)
        if kw is not None:
            # Auto-create CrisisIncident
            inc = {
                "appointment_id": appointment_id,
                "client_id": appt["client_id"],
                "detection_source": "KEYWORD_DETECTOR",
                "trigger_keyword": kw,
                "severity": "MEDIUM",
                "status": "DETECTED",
                "assigned_responder_id": None,
                "handover_at": None,
                "emergency_notified_at": None,
                "follow_up_due_at": None,
                "follow_up_completed_at": None,
            }
            db.stamp_create(inc, common_fields=True)
            db.crisis_incidents[inc["id"]] = inc
            audit.append(
                actor_role=g.user_role, actor_user_id=g.user_id,
                action="CRISIS_DETECTED",
                target_entity="CrisisIncident", target_id=inc["id"],
                payload_summary={"trigger_keyword": kw, "source": "KEYWORD_DETECTOR"},
            )
            raise err("ERR_CRISIS_AUTO_RAISED",
                      f"Risk keyword detected; CrisisIncident {inc['id']} auto-raised. "
                      f"Re-submit with crisis_acknowledged=true to commit.")

    cur = now()
    rec = {
        "appointment_id": appointment_id,
        "counselor_id": appt["counselor_id"],
        "client_id": appt["client_id"],
        "encrypted_note_blob": encrypted_note_blob,
        "content_key_wrapped": "wrapped:" + encrypted_note_blob[:8],
        "redaction_status": "ACTIVE",
        "retention_expires_at": iso(cur + timedelta(days=365 * 7)),
        "last_accessed_at": None,
    }
    db.stamp_create(rec, common_fields=False)
    db.counseling_records[rec["id"]] = rec
    return success(_public(rec), 201)


@bp.route("/counseling/counseling-records/<id>", methods=["GET"])
@require_auth(roles={"Counselor", "Supervisor", "PlatformAdmin"})
def get_record(id):
    rec = db.counseling_records.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", f"CounselingRecord {id} not found")
    if rec["redaction_status"] == "PURGED":
        raise err("ERR_RECORD_PURGED", "Record has been purged")

    if g.user_role == "Counselor":
        if rec["counselor_id"] != g.user_id:
            raise err("ERR_FORBIDDEN", "Counselor may only read own records")
    elif g.user_role == "Supervisor":
        if not _is_supervisor_of_record(g.user_id, rec):
            raise err("ERR_FORBIDDEN", "Supervisor not authorized for this record")
    # PlatformAdmin: full access

    rec["last_accessed_at"] = iso(now())
    audit.append(
        actor_role=g.user_role, actor_user_id=g.user_id,
        action="RECORD_READ",
        target_entity="CounselingRecord", target_id=rec["id"],
        payload_summary={},
    )
    return success(_public(rec))


@bp.route("/counseling/counseling-records/<id>/export", methods=["POST"])
@require_auth(roles={"Counselor", "PlatformAdmin"})
def export_record(id):
    rec = db.counseling_records.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", f"CounselingRecord {id} not found")
    if rec["redaction_status"] == "PURGED":
        raise err("ERR_RECORD_PURGED", "Record has been purged")

    if g.user_role == "Counselor" and rec["counselor_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "Counselor may only export own records")

    body = get_body()
    if body.get("export_consent") is not True:
        raise err("ERR_EXPORT_CONSENT_MISSING",
                  "export_consent must be true")

    audit.append(
        actor_role=g.user_role, actor_user_id=g.user_id,
        action="RECORD_EXPORT",
        target_entity="CounselingRecord", target_id=rec["id"],
        payload_summary={},
    )
    return success({
        "record_id": rec["id"],
        "encrypted_note_blob": rec["encrypted_note_blob"],
        "exported_at": iso(now()),
    })


@bp.route("/counseling/counseling-records", methods=["GET"])
@require_auth(roles={"Counselor", "Supervisor", "PlatformAdmin"})
def list_records():
    limit, offset = get_pagination()
    counselor_id = request.args.get("counselor_id")
    client_id = request.args.get("client_id")
    redaction_status = request.args.get("redaction_status")

    items = list(db.counseling_records.values())
    if g.user_role == "Counselor":
        items = [r for r in items if r["counselor_id"] == g.user_id]
    elif g.user_role == "Supervisor":
        items = [r for r in items if _is_supervisor_of_record(g.user_id, r)]
    if counselor_id:
        items = [r for r in items if r["counselor_id"] == counselor_id]
    if client_id:
        items = [r for r in items if r["client_id"] == client_id]
    if redaction_status:
        items = [r for r in items if r["redaction_status"] == redaction_status]

    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    # List endpoints never return the encrypted blob
    return success_list([_public(r, include_blob=False) for r in page], limit, offset, total)
