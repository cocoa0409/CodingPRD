"""External event ingestion: POST /_events/emit."""
import copy
import json

from flask import Blueprint

from clock import format_iso, get_now
from common import get_json_body, stamp_new
from db import db, new_id
from errors import api_error
from middleware import require_roles
from response import success
from services.audit import append_audit, append_rights_chain

bp = Blueprint("events", __name__)


VALID_SOURCES = {"PAYMENT", "E_SIGN", "COPYRIGHT_AUTHORITY", "DISTRIBUTION_PLATFORM"}
VALID_EVENT_TYPES = {
    "PAYMENT_RECEIVED",
    "PAYMENT_REFUNDED",
    "SIGNATURE_VERIFIED",
    "SIGNATURE_REJECTED",
    "REGISTRATION_APPROVED",
    "REGISTRATION_REJECTED",
    "TAKEDOWN_ACKED",
    "DISTRIBUTION_REVENUE_REPORTED",
}


def _payload_equal(a, b) -> bool:
    try:
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    except Exception:
        return a == b


@bp.route("/_events/emit", methods=["POST"])
def emit_event():
    user_id, role = require_roles(["PlatformAdmin"])
    body = get_json_body()

    source = body.get("source")
    event_type = body.get("event_type")
    ref_entity = body.get("ref_entity")
    ref_id = body.get("ref_id")
    payload = body.get("payload") or {}
    external_event_id = body.get("external_event_id")

    if source not in VALID_SOURCES:
        raise api_error("ERR_VALIDATION", "invalid source")
    if event_type not in VALID_EVENT_TYPES:
        raise api_error("ERR_VALIDATION", "invalid event_type")
    if not external_event_id:
        raise api_error("ERR_VALIDATION", "external_event_id required")

    # Idempotency.
    key = (source, external_event_id)
    if key in db.external_event_index:
        existing_id = db.external_event_index[key]
        existing = db.external_events.get(existing_id)
        if existing and _payload_equal(existing.get("payload"), payload):
            return success(existing)
        raise api_error("ERR_DUPLICATE_EXTERNAL_EVENT",
                        "(source, external_event_id) already seen with different payload")

    event = {
        "source": source,
        "event_type": event_type,
        "ref_entity": ref_entity,
        "ref_id": ref_id,
        "payload": copy.deepcopy(payload),
        "external_event_id": external_event_id,
        "applied": False,
        "applied_at": None,
    }
    event["id"] = new_id()
    event["created_at"] = format_iso(get_now())
    db.external_events[event["id"]] = event
    db.external_event_index[key] = event["id"]

    # Apply side effects per (source, event_type).
    try:
        _apply_event(event)
    except Exception:
        # Roll back the event row + index on failure so retry works.
        db.external_events.pop(event["id"], None)
        db.external_event_index.pop(key, None)
        raise

    event["applied"] = True
    event["applied_at"] = format_iso(get_now())

    return success(event)


def _apply_event(event):
    src = event["source"]
    et = event["event_type"]
    ref_id = event.get("ref_id")
    payload = event.get("payload") or {}

    if src == "COPYRIGHT_AUTHORITY":
        work = db.works.get(ref_id)
        if not work:
            raise api_error("ERR_NOT_FOUND", "work not found")
        if work.get("registration_status") != "UNDER_REVIEW":
            raise api_error("ERR_INVALID_STATE",
                            "Work must be UNDER_REVIEW for registration event")
        from common import stamp_update
        if et == "REGISTRATION_APPROVED":
            before = {"registration_status": work["registration_status"]}
            work["registration_status"] = "REGISTERED"
            work["certificate_id"] = new_id()
            work["certificate_issued_at"] = format_iso(get_now())
            stamp_update(work)
            append_audit("system", "Work", work["id"], "LICENSE_CHANGED",
                         before, {"registration_status": "REGISTERED",
                                  "certificate_id": work["certificate_id"]})
            append_rights_chain(work["id"], "REGISTERED", "system",
                                "Work", work["id"], {})
        elif et == "REGISTRATION_REJECTED":
            before = {"registration_status": work["registration_status"]}
            work["registration_status"] = "REJECTED"
            stamp_update(work)
            append_audit("system", "Work", work["id"], "LICENSE_CHANGED",
                         before, {"registration_status": "REJECTED"})
        return

    if src == "PAYMENT":
        statement = db.royalty_statements.get(ref_id)
        if not statement:
            raise api_error("ERR_NOT_FOUND", "statement not found")
        if et == "PAYMENT_RECEIVED":
            license_obj = db.licenses.get(statement.get("license_id"))
            if not license_obj or license_obj.get("status") != "EFFECTIVE":
                raise api_error("ERR_LICENSE_NOT_EFFECTIVE",
                                "license must be EFFECTIVE to settle")
            if statement.get("status") != "DRAFT":
                raise api_error("ERR_INVALID_STATE", "statement must be DRAFT to settle")
            if statement.get("variant") != "FINAL":
                raise api_error("ERR_INVALID_STATE",
                                "only FINAL statements may settle")
            amount = payload.get("amount_cents")
            if not isinstance(amount, int) or amount != statement.get("net_payable_cents"):
                raise api_error("ERR_PAYMENT_AMOUNT_MISMATCH",
                                "payment amount must equal net_payable_cents")
            from common import stamp_update
            before = {"status": statement["status"]}
            statement["status"] = "SETTLED"
            statement["settled_at"] = format_iso(get_now())
            stamp_update(statement)
            license_obj["cumulative_advance_recouped_cents"] = (
                int(license_obj.get("cumulative_advance_recouped_cents", 0))
                + int(statement.get("advance_recouped_cents", 0))
            )
            stamp_update(license_obj)
            append_audit("system", "RoyaltyStatement", statement["id"], "LICENSE_CHANGED",
                         before, {"status": "SETTLED"})
            return
        if et == "PAYMENT_REFUNDED":
            # The ref_id points at the reversal entry.
            if statement.get("reversal_of_id") is None:
                raise api_error("ERR_INVALID_REVERSAL",
                                "ref_id must be a reversal entry")
            original = db.royalty_statements.get(statement.get("reversal_of_id"))
            if not original:
                raise api_error("ERR_NOT_FOUND", "original statement not found")
            if original.get("status") != "SETTLED":
                raise api_error("ERR_INVALID_STATE",
                                "original statement must be SETTLED")
            amount = payload.get("amount_cents")
            if not isinstance(amount, int) or amount != statement.get("refund_cents"):
                raise api_error("ERR_PAYMENT_AMOUNT_MISMATCH",
                                "refund amount must equal reversal entry refund_cents")
            from common import stamp_update
            before = {"status": original["status"]}
            original["status"] = "REVERSED"
            stamp_update(original)
            # Mark reversal entry itself as SETTLED (it is a SETTLED ledger entry).
            statement["status"] = "SETTLED"
            statement["settled_at"] = format_iso(get_now())
            stamp_update(statement)
            # License compensating action.
            license_obj = db.licenses.get(original.get("license_id"))
            if license_obj:
                license_obj["cumulative_advance_recouped_cents"] = (
                    int(license_obj.get("cumulative_advance_recouped_cents", 0))
                    - int(original.get("advance_recouped_cents", 0))
                )
                stamp_update(license_obj)
            append_audit("system", "RoyaltyStatement", original["id"], "ROYALTY_REVERSED",
                         before, {"status": "REVERSED"})
            return

    if src == "E_SIGN":
        # SIGNATURE_VERIFIED / SIGNATURE_REJECTED are no-op acknowledgments here;
        # the platform's signing ledger is governed by /contracts/{id}/signatures.
        return

    if src == "DISTRIBUTION_PLATFORM":
        # DISTRIBUTION_REVENUE_REPORTED is informational; no required side effect.
        return

    # Fallthrough: nothing to do.
