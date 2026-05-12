"""Test-driver / admin endpoints: clock advance, sweeps, synthetic events."""

from flask import Blueprint

import clock
import db
import errors
import helpers
import response
from middleware import auth_required
from serializers import audit_log_entry_dict
from services import audit
from helpers import bump


bp = Blueprint("admin", __name__)


VALID_EXTERNAL_SYSTEMS = {"BANK", "REGULATOR", "ENERGY_DATA"}


@bp.route("/_clock/advance", methods=["POST"])
@auth_required("Regulator")
def clock_advance():
    body = helpers.get_json_body()
    helpers.require_fields(body, ["target_timestamp"])
    target = clock.parse_iso(body["target_timestamp"])
    clock.advance_to(target)
    return response.ok({"now": clock.iso_format(clock.now())})


@bp.route("/_sweep/run", methods=["POST"])
@auth_required("Regulator")
def sweep_run():
    now = clock.now()
    swept = 0
    for p in db.penalty_orders.values():
        if p["payment_status"] == "UNPAID" and now > p["payment_due_at"]:
            p["payment_status"] = "OVERDUE"
            p["credit_record_reported"] = True
            bump(p)
            audit.append(
                subject_type="QUOTA_CHANGE",
                subject_id=p["id"],
                enterprise_id=p["enterprise_id"],
                action="PENALTY_OVERDUE",
                external_system="REGULATOR",
            )
            swept += 1
    return response.ok({"swept_count": swept})


@bp.route("/_events/emit", methods=["POST"])
@auth_required("Regulator")
def emit_event():
    body = helpers.get_json_body()
    helpers.require_fields(body, ["external_system", "event_type", "payload"])
    if body["external_system"] not in VALID_EXTERNAL_SYSTEMS:
        errors.raise_error(errors.ERR_INVALID_INPUT, "Invalid external_system.")
    payload = body["payload"]
    if not isinstance(payload, dict):
        errors.raise_error(errors.ERR_INVALID_INPUT, "payload must be an object.")
    event_id = payload.get("event_id")

    # Idempotency: skip if event_id already processed.
    if event_id is not None and event_id in db.processed_event_ids:
        # Find the previously appended audit log entry tied to this event_id (best effort).
        # We re-emit the most recent matching entry rather than appending again.
        for a in reversed(db.audit_log_entries):
            if (a["subject_type"] == "EXTERNAL_SYNC"
                    and a.get("subject_id") == event_id):
                return response.created(audit_log_entry_dict(a))
        # Fallback: just return empty 200-ish.
        return response.created({})

    if event_id is not None:
        db.processed_event_ids.add(event_id)

    enterprise_id = None
    delta_quota = 0
    delta_ccer = 0

    # Handle BANK_PAYMENT_CONFIRMED -> mark UNPAID penalty PAID (idempotent on event_id).
    if (body["event_type"] == "BANK_PAYMENT_CONFIRMED"
            and body["external_system"] == "BANK"):
        penalty_id = payload.get("penalty_id")
        if penalty_id is not None:
            p = db.penalty_orders.get(penalty_id)
            if p is not None and p["payment_status"] == "UNPAID":
                p["payment_status"] = "PAID"
                p["paid_at"] = clock.now()
                p["credit_record_reported"] = True
                bump(p)
                d = db.compliance_declarations.get(p["declaration_id"])
                if d is not None and d["status"] == "NON_COMPLIANT":
                    d["status"] = "PENALIZED"
                    bump(d)
                db.pending_deductions.append({
                    "enterprise_id": p["enterprise_id"],
                    "amount": helpers.to_dec(p["mandatory_deduction_amount"]),
                    "source_penalty_id": p["id"],
                    "recorded_at": clock.now(),
                })
                enterprise_id = p["enterprise_id"]

    entry = audit.append(
        subject_type="EXTERNAL_SYNC",
        subject_id=event_id if event_id is not None else db.new_id(),
        enterprise_id=enterprise_id,
        action=body["event_type"],
        delta_quota=delta_quota,
        delta_ccer=delta_ccer,
        external_system=body["external_system"],
    )
    return response.created(audit_log_entry_dict(entry))
