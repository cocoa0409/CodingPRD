"""Trust sub-ledgers, append-only trust transactions, and retainer holds."""

from flask import Blueprint, request

import db
import errors
from common import (get_json_body, stamp_create, touch, require_int,
                    require_enum, require_datetime, optional_int, paginate)
from clock import server_now_iso
from middleware import authenticate, require_role
from middleware import ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY
from response import object_response, array_response
import serializers

bp = Blueprint("trust", __name__)

ALL_ROLES = {ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY}
TX_KINDS = {"DEPOSIT", "DISBURSEMENT", "SWEEP_TO_OPERATING"}


def _signed(kind, amount):
    if kind == "DEPOSIT":
        return amount
    return -amount  # DISBURSEMENT and SWEEP_TO_OPERATING


# ---------------- Trust sub-ledgers ----------------

@bp.route("/firm/trust-ledgers", methods=["POST"])
def open_ledger():
    _uid, role = authenticate()
    require_role(role, {ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK})
    body = get_json_body()
    account_id = body.get("trust_account_id")
    client_id = body.get("client_id")
    if account_id is None or not isinstance(account_id, str):
        raise errors.invalid_request("Missing required field 'trust_account_id'.")
    if client_id is None or not isinstance(client_id, str):
        raise errors.invalid_request("Missing required field 'client_id'.")
    retainer_floor = optional_int(body, "retainer_floor_cents", default=0, minimum=0)

    if db.trust_accounts.get(account_id) is None:
        raise errors.not_found("Trust account not found.")
    if db.clients.get(client_id) is None:
        raise errors.not_found("Client not found.")

    with db.LOCK:
        # Idempotent per (account, client): return the existing ledger.
        for l in db.client_trust_ledgers.values():
            if l["trust_account_id"] == account_id and l["client_id"] == client_id:
                return object_response(serializers.s_trust_ledger(l), status=201)
        rec = {
            "trust_account_id": account_id,
            "client_id": client_id,
            "balance_cents": 0,
            "retainer_floor_cents": retainer_floor,
        }
        stamp_create(rec)
        db.client_trust_ledgers[rec["id"]] = rec
    return object_response(serializers.s_trust_ledger(rec), status=201)


@bp.route("/firm/trust-ledgers/<lid>", methods=["GET"])
def get_ledger(lid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.client_trust_ledgers.get(lid)
    if rec is None:
        raise errors.not_found()
    return object_response(serializers.s_trust_ledger(rec))


@bp.route("/firm/trust-ledgers", methods=["GET"])
def list_ledgers():
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    items = list(db.client_trust_ledgers.values())
    for key in ("trust_account_id", "client_id"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l.get(key) == val]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_trust_ledger(l) for l in page], limit, offset, total)


@bp.route("/firm/trust-ledgers/<lid>/transactions", methods=["GET"])
def list_ledger_transactions(lid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.client_trust_ledgers.get(lid) is None:
        raise errors.not_found()
    items = [t for t in db.trust_transactions.values() if t["client_trust_ledger_id"] == lid]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_trust_transaction(t) for t in page], limit, offset, total)


# ---------------- Trust transactions (DEPOSIT / DISBURSEMENT) ----------------

@bp.route("/firm/trust-transactions", methods=["POST"])
def post_transaction():
    uid, role = authenticate()
    require_role(role, {ROLE_BILLING_CLERK, ROLE_ATTORNEY, ROLE_PLATFORM_ADMIN})
    body = get_json_body()
    ledger_id = body.get("client_trust_ledger_id")
    if ledger_id is None or not isinstance(ledger_id, str):
        raise errors.invalid_request("Missing required field 'client_trust_ledger_id'.")
    kind = require_enum(body, "kind", TX_KINDS)
    # SWEEP_TO_OPERATING is created only via the trust-sweep endpoint.
    if kind == "SWEEP_TO_OPERATING":
        raise errors.invalid_request("SWEEP_TO_OPERATING is created via the trust-sweep endpoint.")
    amount = require_int(body, "amount_cents", positive=True)
    initiated_by = body.get("initiated_by_user_id")
    if initiated_by is None or not isinstance(initiated_by, str):
        raise errors.invalid_request("Missing required field 'initiated_by_user_id'.")

    ledger = db.client_trust_ledgers.get(ledger_id)
    if ledger is None:
        raise errors.not_found("Client trust ledger not found.")

    approved_by = None
    if kind == "DISBURSEMENT":
        # SoD (priority 7): approving Attorney's X-User-ID must differ from initiator.
        if uid == initiated_by:
            raise errors.sod_same_actor()
        approved_by = uid

    with db.LOCK:
        signed = _signed(kind, amount)
        # No-overdraw (priority 9) for outflows.
        if signed < 0 and ledger["balance_cents"] + signed < 0:
            raise errors.trust_overdraw()

        tx = {
            "client_trust_ledger_id": ledger_id,
            "kind": kind,
            "amount_cents": amount,
            "status": "PENDING",
            "invoice_id": None,
            "initiated_by_user_id": initiated_by,
            "approved_by_user_id": approved_by,
            "id": db.new_id(),
            "created_at": server_now_iso(),
            "_seq": db.next_seq(),
        }
        db.trust_transactions[tx["id"]] = tx

        # Book + client ledger move immediately; bank lags.
        ledger["balance_cents"] += signed
        touch(ledger)
        account = db.trust_accounts.get(ledger["trust_account_id"])
        if account is not None:
            account["book_balance_cents"] += signed
            touch(account)
    return object_response(serializers.s_trust_transaction(tx), status=201)


@bp.route("/firm/trust-transactions/<txid>", methods=["GET"])
def get_transaction(txid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.trust_transactions.get(txid)
    if rec is None:
        raise errors.not_found()
    return object_response(serializers.s_trust_transaction(rec))


@bp.route("/firm/trust-transactions", methods=["GET"])
def list_transactions():
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    items = list(db.trust_transactions.values())
    for key in ("client_trust_ledger_id", "invoice_id", "status", "kind"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t.get(key) == val]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_trust_transaction(t) for t in page], limit, offset, total)


@bp.route("/firm/trust-transactions/<txid>/confirm", methods=["POST"])
def confirm_transaction(txid):
    _uid, role = authenticate()
    require_role(role, {ROLE_BILLING_CLERK, ROLE_PLATFORM_ADMIN})
    tx = db.trust_transactions.get(txid)
    if tx is None:
        raise errors.not_found()
    if tx["status"] != "PENDING":
        raise errors.invalid_state("Only a PENDING transaction may be confirmed.")
    with db.LOCK:
        tx["status"] = "CONFIRMED"
        signed = _signed(tx["kind"], tx["amount_cents"])
        ledger = db.client_trust_ledgers.get(tx["client_trust_ledger_id"])
        if ledger is not None:
            account = db.trust_accounts.get(ledger["trust_account_id"])
            if account is not None:
                account["bank_balance_cents"] += signed
                touch(account)
    return object_response(serializers.s_trust_transaction(tx))


@bp.route("/firm/trust-transactions/<txid>/reverse", methods=["POST"])
def reverse_transaction(txid):
    uid, role = authenticate()
    require_role(role, {ROLE_ATTORNEY, ROLE_PLATFORM_ADMIN})
    tx = db.trust_transactions.get(txid)
    if tx is None:
        raise errors.not_found()
    if tx["status"] not in ("PENDING", "CONFIRMED"):
        raise errors.invalid_state("Only a PENDING or CONFIRMED transaction may be reversed.")
    # SoD (priority 7): reverser must differ from initiator.
    if uid == tx["initiated_by_user_id"]:
        raise errors.sod_same_actor()
    with db.LOCK:
        was_confirmed = tx["status"] == "CONFIRMED"
        signed = _signed(tx["kind"], tx["amount_cents"])
        tx["status"] = "VOIDED"
        ledger = db.client_trust_ledgers.get(tx["client_trust_ledger_id"])
        if ledger is not None:
            ledger["balance_cents"] -= signed
            touch(ledger)
            account = db.trust_accounts.get(ledger["trust_account_id"])
            if account is not None:
                account["book_balance_cents"] -= signed
                if was_confirmed:
                    account["bank_balance_cents"] -= signed
                touch(account)
    return object_response(serializers.s_trust_transaction(tx))


# ---------------- Retainer holds ----------------

@bp.route("/firm/retainer-holds", methods=["POST"])
def create_hold():
    _uid, role = authenticate()
    require_role(role, {ROLE_BILLING_CLERK, ROLE_ATTORNEY, ROLE_PLATFORM_ADMIN})
    body = get_json_body()
    ledger_id = body.get("client_trust_ledger_id")
    if ledger_id is None or not isinstance(ledger_id, str):
        raise errors.invalid_request("Missing required field 'client_trust_ledger_id'.")
    amount = require_int(body, "amount_cents", positive=True)
    start = require_datetime(body, "hold_start_at")
    end = require_datetime(body, "hold_end_at")
    if not (end > start):
        raise errors.invalid_request("hold_end_at must be strictly after hold_start_at.")

    ledger = db.client_trust_ledgers.get(ledger_id)
    if ledger is None:
        raise errors.not_found("Client trust ledger not found.")

    with db.LOCK:
        # Closed-interval overlap with ACTIVE holds on the same ledger:
        # [a,b] overlaps [c,d] iff a <= d and c <= b (touching endpoints collide).
        from clock import parse_iso8601
        for h in db.retainer_holds.values():
            if h["client_trust_ledger_id"] != ledger_id:
                continue
            if h["status"] != "ACTIVE":
                continue
            h_start = parse_iso8601(h["hold_start_at"])
            h_end = parse_iso8601(h["hold_end_at"])
            if start <= h_end and h_start <= end:
                raise errors.hold_overlap()
        rec = {
            "client_trust_ledger_id": ledger_id,
            "amount_cents": amount,
            "hold_start_at": body["hold_start_at"],
            "hold_end_at": body["hold_end_at"],
            "status": "ACTIVE",
        }
        stamp_create(rec)
        db.retainer_holds[rec["id"]] = rec
    return object_response(serializers.s_retainer_hold(rec), status=201)


@bp.route("/firm/retainer-holds/<hid>", methods=["GET"])
def get_hold(hid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.retainer_holds.get(hid)
    if rec is None:
        raise errors.not_found()
    return object_response(serializers.s_retainer_hold(rec))


@bp.route("/firm/retainer-holds", methods=["GET"])
def list_holds():
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    items = list(db.retainer_holds.values())
    for key in ("client_trust_ledger_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [h for h in items if h.get(key) == val]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_retainer_hold(h) for h in page], limit, offset, total)


@bp.route("/firm/retainer-holds/<hid>/release", methods=["POST"])
def release_hold(hid):
    _uid, role = authenticate()
    require_role(role, {ROLE_BILLING_CLERK, ROLE_ATTORNEY, ROLE_PLATFORM_ADMIN})
    rec = db.retainer_holds.get(hid)
    if rec is None:
        raise errors.not_found()
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE hold may be released.")
    with db.LOCK:
        rec["status"] = "RELEASED"
        touch(rec)
    return object_response(serializers.s_retainer_hold(rec))
