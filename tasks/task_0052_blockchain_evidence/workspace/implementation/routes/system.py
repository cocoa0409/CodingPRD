"""Test-driving endpoints: /_clock, /_chain, /_sweep, /_events/*."""
from flask import Blueprint

import db
from clock import iso, parse_iso, set_now, now
from errors import err
from middleware import require_auth
from response import success
from services import lifecycle
from services.lookup import (
    get_judicial_package, get_notarization, get_on_chain_tx, get_recharge,
)
from services.validation import get_body, require_int, require_str


bp = Blueprint("system", __name__)


def _tx_public(t: dict) -> dict:
    return {
        "id": t["id"],
        "evidence_id": t.get("evidence_id"),
        "batch_id": t.get("batch_id"),
        "chain_id": t["chain_id"],
        "anchored_hash": t["anchored_hash"],
        "tx_hash": t.get("tx_hash"),
        "block_height": t.get("block_height"),
        "confirmations": t.get("confirmations", 0),
        "status": t["status"],
        "attempt_index": t["attempt_index"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def _recharge_public(r: dict) -> dict:
    return {
        "id": r["id"],
        "customer_id": r["customer_id"],
        "amount_cents": r["amount_cents"],
        "external_payment_ref": r["external_payment_ref"],
        "status": r["status"],
        "created_at": r["created_at"],
    }


def _notar_public(n: dict) -> dict:
    return {
        "id": n["id"],
        "evidence_id": n["evidence_id"],
        "tsa_provider": n["tsa_provider"],
        "notary_office_id": n.get("notary_office_id"),
        "trusted_time": n.get("trusted_time"),
        "tsa_token": n.get("tsa_token"),
        "created_at": n["created_at"],
    }


def _pkg_public(p: dict) -> dict:
    return {
        "id": p["id"],
        "evidence_id": p["evidence_id"],
        "case_number": p["case_number"],
        "party_info": p["party_info"],
        "authority_code": p["authority_code"],
        "include_original_data": p["include_original_data"],
        "status": p["status"],
        "official_seal_id": p.get("official_seal_id"),
        "delivered_at": p.get("delivered_at"),
        "surcharge_cents": p.get("surcharge_cents"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def clock_advance():
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except ValueError as e:
        raise err("ERR_VALIDATION_FAILED", str(e))
    set_now(dt)
    return success({"now": iso(dt)}, 200)


@bp.route("/_chain/confirm", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def chain_confirm():
    body = get_body()
    tx_id = require_str(body, "tx_id")
    block_height = require_int(body, "block_height", min_val=0)
    confirmations = require_int(body, "confirmations", min_val=0)
    tx = get_on_chain_tx(tx_id)
    lifecycle.chain_confirm(tx, block_height, confirmations)
    return success(_tx_public(tx), 200)


@bp.route("/_chain/fail", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def chain_fail():
    body = get_body()
    tx_id = require_str(body, "tx_id")
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise err("ERR_VALIDATION_FAILED", "reason must be a string when provided")
    tx = get_on_chain_tx(tx_id)
    lifecycle.chain_fail(tx, reason or "")
    return success(_tx_public(tx), 200)


@bp.route("/_sweep/run", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def sweep_run():
    summary = lifecycle.expiry_sweep()
    return success(summary, 200)


@bp.route("/_events/payment", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def event_payment():
    body = get_body()
    external_payment_ref = require_str(body, "external_payment_ref")
    status = require_str(body, "status")
    if status not in ("SUCCESS", "FAILURE"):
        raise err("ERR_VALIDATION_FAILED", "status must be SUCCESS or FAILURE")

    r_id = db.recharge_ref_index.get(external_payment_ref)
    if r_id is None:
        raise err("ERR_NOT_FOUND",
                  f"No Recharge for external_payment_ref {external_payment_ref}")
    r = db.recharges[r_id]
    if r["status"] != "PENDING":
        raise err("ERR_DUPLICATE_PAYMENT_REF",
                  "Recharge already settled for this external_payment_ref")
    if status == "SUCCESS":
        lifecycle.recharge_complete(r)
    else:
        lifecycle.recharge_fail(r)
    return success(_recharge_public(r), 200)


@bp.route("/_events/judicial-ack", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def event_judicial_ack():
    body = get_body()
    pkg_id = require_str(body, "judicial_package_id")
    pkg = get_judicial_package(pkg_id)
    lifecycle.judicial_deliver(pkg, system_actor=True)
    return success(_pkg_public(pkg), 200)


@bp.route("/_events/notary-callback", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def event_notary_callback():
    body = get_body()
    n_id = require_str(body, "timestamp_notarization_id")
    trusted_time = require_str(body, "trusted_time")
    tsa_token = require_str(body, "tsa_token")
    try:
        parse_iso(trusted_time)
    except ValueError as e:
        raise err("ERR_VALIDATION_FAILED", str(e))
    n = get_notarization(n_id)
    n["trusted_time"] = trusted_time
    n["tsa_token"] = tsa_token
    return success(_notar_public(n), 200)
