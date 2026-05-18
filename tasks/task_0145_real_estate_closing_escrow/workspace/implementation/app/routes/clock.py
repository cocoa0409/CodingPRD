"""Test-driving clock endpoints.

POST /_clock/now    -> read the current logical clock
POST /_clock/advance -> move the clock forward to a supplied instant
                       and run system-actor sweeps.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from app import store
from app.audit import append_audit
from app.auth import require_role
from app.envelope import success_envelope
from app.errors import ApiError
from app.idempotency import lookup as idem_lookup, remember as idem_remember, require_idempotency_key
from app.request_helpers import get_json_body
from app.util import now_ts, parse_iso_dt, require_str

bp = Blueprint("clock", __name__)


def _sweep_exchanges() -> None:
    """When the logical clock advances, fail any §1031 exchange whose deadline lapsed."""
    server_now = store.clock.now()
    for ex in list(store.exchanges.values()):
        if ex["status"] in {"CLOSED_DEFERRED", "FAILED_TAXABLE"}:
            continue
        ident_dl = parse_iso_dt(ex["identification_deadline_at"])
        exch_dl = parse_iso_dt(ex["exchange_deadline_at"])
        if ex["status"] == "INITIATED" and server_now > ident_dl:
            ex["status"] = "FAILED_TAXABLE"
            ex["recognized_gain"] = ex["realized_gain"]
            ex["deferred_gain"] = 0
            ex["updated_at"] = now_ts()
            ex["version"] = int(ex.get("version", 1)) + 1
            append_audit(
                escrow_file_id=ex["escrow_file_id"],
                subject_kind="EXCHANGE_1031",
                subject_id=ex["id"],
                actor_user_id="system",
                actor_role="system",
                action="EXCHANGE_FAILED_45D_LAPSED",
                payload_body={},
            )
        elif ex["status"] == "IDENTIFIED" and server_now > exch_dl:
            ex["status"] = "FAILED_TAXABLE"
            ex["recognized_gain"] = ex["realized_gain"]
            ex["deferred_gain"] = 0
            ex["updated_at"] = now_ts()
            ex["version"] = int(ex.get("version", 1)) + 1
            append_audit(
                escrow_file_id=ex["escrow_file_id"],
                subject_kind="EXCHANGE_1031",
                subject_id=ex["id"],
                actor_user_id="system",
                actor_role="system",
                action="EXCHANGE_FAILED_180D_LAPSED",
                payload_body={},
            )


@bp.post("/_clock/now")
def clock_now():
    require_role(["EscrowOfficer", "TitleOfficer", "DisbursementApprover", "Buyer", "Seller"])
    return jsonify(success_envelope({"now": _iso(store.clock.now())})), 200


@bp.post("/_clock/advance")
def clock_advance():
    require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    to_str = require_str(body, "to")
    new_now = parse_iso_dt(to_str)
    if new_now < store.clock.now():
        raise ApiError("ERR_BAD_REQUEST", "Clock can only advance forward.")
    store.clock.set(new_now)
    _sweep_exchanges()
    response = success_envelope({"now": _iso(store.clock.now())})
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


def _iso(dt) -> str:
    return now_ts(dt)
