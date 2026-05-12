"""External-event ingress (idempotent) and the periodic sweep."""

from __future__ import annotations

import db
from config import EVENT_TYPES
from errors import AppError, ERR_NOT_FOUND, ERR_VALIDATION_FAILED
from services import application as app_svc
from services import audit
from services import validators as V


def emit_event(body: dict) -> tuple[dict, bool]:
    """Process an inbound event. Returns (record, was_duplicate)."""
    body = V.must_be_dict(body)
    event_type = V.require_str(body, "event_type")
    if event_type not in EVENT_TYPES:
        raise AppError(ERR_VALIDATION_FAILED,
                       f"event_type must be one of {sorted(EVENT_TYPES)}", 422)
    idempotency_key = V.require_str(body, "idempotency_key")
    subject_application_id = V.require_str(body, "subject_application_id")
    payload = body.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise AppError(ERR_VALIDATION_FAILED, "payload must be an object", 422)

    # Idempotency: lookup (event_type, idempotency_key).
    existing = db.find_one("external_events",
                           event_type=event_type,
                           idempotency_key=idempotency_key)
    if existing:
        return existing, True

    app = db.find_by_id("applications", subject_application_id)
    if not app:
        raise AppError(ERR_NOT_FOUND,
                       f"subject application not found: {subject_application_id}",
                       404)

    record = db.insert("external_events", {
        "event_type": event_type,
        "idempotency_key": idempotency_key,
        "subject_application_id": subject_application_id,
        "payload": payload,
        "processed": False,
    })

    # Apply side effects.
    if event_type == "IDENTITY_VERIFIED":
        db.update("applications", subject_application_id,
                  {"identity_verified": True})
    elif event_type == "PAYMENT_SETTLED":
        if app["payment_status"] == "PENDING":
            db.update("applications", subject_application_id,
                      {"payment_status": "PAID"})
    # SIGNATURE_AFFIXED and DATA_SHARED — accepted, recorded, no state effect.

    db.update("external_events", record["id"], {"processed": True}, bump=False)

    # If gates met, drive into review.
    app_svc.maybe_enter_under_review(subject_application_id)

    return db.find_by_id("external_events", record["id"]), False


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def run_sweep() -> dict:
    expired_notices = 0
    rejected_apps = 0
    expired_certs = 0

    now_dt = db.now_dt()

    # Expire correction notices.
    for notice in list(db.find_many("correction_notices", status="OPEN")):
        due_dt = db.parse_iso(notice["due_at"])
        if now_dt > due_dt:
            db.update("correction_notices", notice["id"], {"status": "EXPIRED"})
            expired_notices += 1
            # Cascade: Application -> REJECTED.
            app = db.find_by_id("applications", notice["application_id"])
            if app and app["review_status"] == "AWAITING_CORRECTION":
                version = db.find_by_id("matter_versions",
                                        app["matter_version_id"])
                updates = {"review_status": "REJECTED"}
                if app["payment_status"] == "PAID" and version["fee_amount_cents"] > 0:
                    updates["payment_status"] = "REFUNDED"
                db.update("applications", app["id"], updates)
                # Skip non-terminal review tasks.
                from config import REVIEW_TASK_TERMINAL
                for t in db.find_many("review_tasks",
                                      application_id=app["id"]):
                    if t["status"] not in REVIEW_TASK_TERMINAL:
                        db.update("review_tasks", t["id"], {"status": "SKIPPED"})
                audit.write("REJECT", "Application", app["id"],
                            {"reason": "CORRECTION_FAILURE"})
                rejected_apps += 1

    # Expire certificates.
    for cert in list(db.find_many("certificates", status="ACTIVE")):
        if cert["expires_at"]:
            exp_dt = db.parse_iso(cert["expires_at"])
            if now_dt >= exp_dt:
                db.update("certificates", cert["id"], {"status": "EXPIRED"})
                expired_certs += 1

    return {
        "expired_correction_notices": expired_notices,
        "rejected_applications": rejected_apps,
        "expired_certificates": expired_certs,
        "ran_at": db.now_iso(),
    }
