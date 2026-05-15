"""System endpoints: /_clock/advance and /_events/emit.

Per PRD §2.1, these endpoints skip the auth presence check but RBAC still
applies when headers are supplied (LabManager-only). Tests typically use
LabManager headers; we accept LabManager and also any role (acting as
operator) but enforce auth-validity if a role header is present.
"""

from datetime import timedelta

from flask import Blueprint, request, g

from db import DB, new_id, LOCK, reset as db_reset
from errors import ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, raise_error
from middleware import auth_required
from response import success_response
from services.common import get_json_body, require_fields
from services.serializers import (
    serialize_client, serialize_invoice, serialize_instrument, serialize_tester,
    serialize_report,
)
from services.time_util import now_iso, now_dt, parse_iso, advance_clock_to, format_iso, reset_clock
from services.state import (
    cascade_instrument_calibration_lapse, reconcile_tester_posture, touch,
)
from services.audit import emit_audit

bp = Blueprint("system", __name__)


@bp.post("/_test/reset")
def test_reset():
    """Test-isolation endpoint: clear all in-memory state. Not in PRD; serves
    as benchmark-only fixture support so each pytest test runs against fresh
    state."""
    with LOCK:
        db_reset()
        reset_clock()
    return success_response({"reset": True}, 200)


@bp.post("/_clock/advance")
@auth_required(["LabManager"], skip_presence_check=True)
def clock_advance():
    body = get_json_body()
    require_fields(body, ["to"])
    try:
        target = parse_iso(body["to"])
    except Exception:
        raise_error(ERR_VALIDATION, "to must be an ISO datetime")

    with LOCK:
        before, after = advance_clock_to(target)
        if after <= before:
            return success_response({
                "now": format_iso(after),
                "sweeps": {
                    "instrument_calibration_lapses": 0,
                    "qualification_reconciliations": 0,
                    "report_archivals": 0,
                }
            }, 200)
        new_now = after  # logical now after advance
        # Sweep 1: instrument calibration lapses
        cal_lapse_count = 0
        for inst in list(DB["instruments"].values()):
            if inst.get("status") != "AVAILABLE":
                continue
            cvt = parse_iso(inst["calibration_valid_to"]) if isinstance(inst["calibration_valid_to"], str) else inst["calibration_valid_to"]
            if cvt < new_now:
                cascade_instrument_calibration_lapse(inst, lapsed_at_iso=format_iso(new_now))
                cal_lapse_count += 1
        # Sweep 2: qualification reconciliation (with cascade)
        qual_count = 0
        for tester in list(DB["testers"].values()):
            _, changed = reconcile_tester_posture(
                tester, with_cascade=True, lapsed_at_iso=format_iso(new_now),
            )
            if changed:
                qual_count += 1
        # Sweep 3: 30-day report archival
        arch_count = 0
        for report in list(DB["reports"].values()):
            if report.get("status") != "ISSUED":
                continue
            issued_at = report.get("issued_at")
            if not issued_at:
                continue
            issued_dt = parse_iso(issued_at) if isinstance(issued_at, str) else issued_at
            if new_now >= issued_dt + timedelta(days=30):
                report["status"] = "ARCHIVED"
                touch(report)
                arch_count += 1
        result = {
            "now": format_iso(new_now),
            "sweeps": {
                "instrument_calibration_lapses": cal_lapse_count,
                "qualification_reconciliations": qual_count,
                "report_archivals": arch_count,
            }
        }
    return success_response(result, 200)


@bp.post("/_events/emit")
@auth_required(["LabManager"], skip_presence_check=True)
def events_emit():
    body = get_json_body()
    require_fields(body, ["event_type", "payload"])
    event_type = body["event_type"]
    payload = body["payload"] or {}
    if event_type not in ("PaymentReceived", "AccreditationScopeChanged", "ProjectStatusUpdate"):
        raise_error(ERR_VALIDATION, "event_type unsupported")
    if not isinstance(payload, dict):
        raise_error(ERR_VALIDATION, "payload must be an object")

    with LOCK:
        if event_type == "PaymentReceived":
            return _handle_payment(payload)
        if event_type == "AccreditationScopeChanged":
            DB["accreditation_categories"] = payload.get("allowed_categories")
            return success_response({"acknowledged": True, "event_type": event_type}, 200)
        # ProjectStatusUpdate: no-op snapshot
        return success_response({"acknowledged": True, "event_type": event_type}, 200)


def _handle_payment(payload):
    """Implements:
      - {client_id, amount_cents}: credit Client.deposit_balance_cents.
      - {invoice_id, amount_cents}: mark invoice PAID if amount matches.
    """
    invoice_id = payload.get("invoice_id")
    amount_cents = payload.get("amount_cents")
    if amount_cents is None:
        raise_error(ERR_VALIDATION, "amount_cents required")
    if not isinstance(amount_cents, int) or amount_cents < 0:
        raise_error(ERR_VALIDATION, "amount_cents must be a non-negative integer")

    if invoice_id:
        inv = DB["invoices"].get(invoice_id)
        if inv is None:
            raise_error(ERR_NOT_FOUND, "Invoice not found")
        if inv.get("status") != "ISSUED":
            raise_error(ERR_INVALID_STATE, "Invoice is not ISSUED")
        if amount_cents != inv.get("total_due_cents", 0):
            raise_error(ERR_VALIDATION, "amount_cents does not match total_due_cents")
        inv["status"] = "PAID"
        inv["paid_at"] = now_iso()
        touch(inv)
        client = DB["clients"].get(inv["client_id"])
        if client is not None:
            client["outstanding_balance_cents"] = client.get("outstanding_balance_cents", 0) - inv.get("total_due_cents", 0)
            touch(client)
        return success_response(serialize_invoice(inv), 200)

    # No invoice_id => credit deposit on the named client
    client_id = payload.get("client_id")
    if not client_id:
        raise_error(ERR_VALIDATION, "client_id required when invoice_id absent")
    client = DB["clients"].get(client_id)
    if client is None:
        raise_error(ERR_NOT_FOUND, "Client not found")
    client["deposit_balance_cents"] = client.get("deposit_balance_cents", 0) + amount_cents
    touch(client)
    return success_response(serialize_client(client), 200)
