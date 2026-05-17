"""CriticalNotification endpoints: fetch, list, acknowledge."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import ROLE_LAB_DIRECTOR, ROLE_ORDERING_PROVIDER, require_roles
from ..clock import now
from ..errors import (
    err_ack_by_wrong_recipient,
    err_already_acknowledged,
    err_invalid_state,
    err_readback_incomplete,
)
from ..helpers import (
    assert_string,
    new_uuid,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services import calculations as calc
from ..services.audit import write_audit_event
from ..services.lookups import (
    get_clinician,
    get_critical_notification,
    get_lab_order,
    get_lab_result,
    get_test_panel,
)
from ..services.serialize import ack_receipt_view, critical_notification_view
from ..services.workflows import bump
from ..store import store

bp = Blueprint("notifications", __name__)


def _notif_view_external(notif: dict) -> dict:
    # Strip internal-only fields from the response.
    return critical_notification_view(notif)


@bp.route("/notifications/<nid>", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_DIRECTOR)
def fetch_notification(nid, **_):
    row = get_critical_notification(nid)
    return ok(_notif_view_external(row))


@bp.route("/notifications", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_DIRECTOR)
def list_notifications(**_):
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    recipient_f = request.args.get("recipient_clinician_id")
    items = list(store().critical_notifications.values())
    if status_f:
        items = [r for r in items if r["status"] == status_f]
    if recipient_f:
        items = [r for r in items if r["recipient_clinician_id"] == recipient_f]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return listing([_notif_view_external(r) for r in page], total, limit, offset)


@bp.route("/notifications/<nid>/acknowledge", methods=["POST"])
@require_roles(ROLE_ORDERING_PROVIDER)
def acknowledge(nid, **_):
    body = require_json_object()
    ack_id = assert_string(body.get("acknowledged_by_id"), "acknowledged_by_id")
    # read_back_text: must be a string and present; PRD permits empty string —
    # the §3.5 read-back completeness check (priority 10) handles content.
    rb_raw = body.get("read_back_text")
    if rb_raw is None:
        from ..errors import err_validation
        raise err_validation("read_back_text is required")
    if not isinstance(rb_raw, str):
        from ..errors import err_validation
        raise err_validation("read_back_text must be a string")
    read_back = rb_raw

    with store().lock:
        notif = get_critical_notification(nid)
        # Body FK: acknowledged_by clinician existence
        get_clinician(ack_id)

        result = get_lab_result(notif["lab_result_id"])
        order = get_lab_order(result["lab_order_id"])
        panel = get_test_panel(order["panel_id"])

        # State checks — special ordering:
        #   - already ACKNOWLEDGED -> ERR_ALREADY_ACKNOWLEDGED
        #   - FAILED -> ERR_INVALID_STATE
        # Then business-referential: wrong recipient (priority 9), read-back (priority 10)
        # Per scaffold validations priority order:
        #   5 state (ERR_INVALID_STATE)
        #   9 ERR_ACK_BY_WRONG_RECIPIENT
        #  10 ERR_READBACK_INCOMPLETE
        #  15 ERR_ALREADY_ACKNOWLEDGED
        # But PRD §2.12 says: a second ack after ACKNOWLEDGED is rejected with ERR_ALREADY_ACKNOWLEDGED
        # specifically (distinct from generic state error). So:
        #   if ACKNOWLEDGED -> ERR_ALREADY_ACKNOWLEDGED  (special-cased ahead of generic state)
        #   if not in PENDING/ESCALATED -> ERR_INVALID_STATE
        if notif["status"] == "ACKNOWLEDGED":
            raise err_already_acknowledged()
        if notif["status"] not in ("PENDING", "ESCALATED"):
            raise err_invalid_state(f"Notification status is {notif['status']}")

        # Wrong recipient (priority 9)
        if ack_id != notif["recipient_clinician_id"]:
            raise err_ack_by_wrong_recipient()

        # Read-back completeness for HIGH (priority 10)
        if panel["clia_complexity"] == "HIGH":
            scoped_codes = notif.get("_scoped_analyte_codes") or [
                f["analyte_code"] for f in result["critical_flags"]
            ]
            lowered = read_back.lower()
            missing = [c for c in scoped_codes if c.lower() not in lowered]
            if missing:
                raise err_readback_incomplete(f"read_back_text missing analyte codes: {missing}")

        # Create acknowledgement receipt
        ack_at = now()
        latency = calc.ack_latency_minutes(notif["first_sent_at"], ack_at)
        receipt = {
            "id": new_uuid(),
            "created_at": ack_at,
            "critical_notification_id": notif["id"],
            "acknowledged_by_id": ack_id,
            "acknowledged_at": ack_at,
            "read_back_text": read_back,
            "ack_latency_minutes": latency,
        }
        store().acknowledgement_receipts[receipt["id"]] = receipt

        notif["status"] = "ACKNOWLEDGED"
        bump(notif)

        write_audit_event(
            event_type="CRITICAL_ACKED",
            lab_order_id=order["id"],
            actor_id=ack_id,
            payload={
                "notification_id": notif["id"],
                "latency_minutes": latency,
                "ack_latency_minutes": latency,
            },
        )
    return ok(ack_receipt_view(receipt))
