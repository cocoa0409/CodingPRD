"""Wallet endpoints."""
from flask import Blueprint, request

from .. import store
from ..auth import require_auth, current_user_id, current_role
from ..errors import ApiError
from ..pagination import get_pagination, paginate, sort_by_created_asc
from ..response import success
from ..validators import get_json_body, require_fields, require_enum
from ..services.paths import resolve_advertiser, resolve_wallet_tx
from ..services.wallet import create_wallet_tx, reverse_wallet_tx


bp = Blueprint("wallet", __name__)


TX_TYPES = ["RECHARGE", "REFUND", "ADJUSTMENT", "INVOICE_SETTLEMENT"]


@bp.post("/advertisers/<advertiser_id>/wallet/transactions")
@require_auth(["FinanceOfficer", "PlatformAdmin"])
def create_transaction(advertiser_id):
    adv = resolve_advertiser(advertiser_id)
    if adv.get("status") == "CLOSED":
        raise ApiError("ERR_ADVERTISER_CLOSED")
    body = get_json_body()
    require_fields(body, ["tx_type", "amount_cents", "idempotency_key"])
    tx_type = require_enum(body, "tx_type", TX_TYPES)
    amount = int(body["amount_cents"])

    audit_action = None
    if tx_type == "ADJUSTMENT":
        audit_action = "BALANCE_ADJUSTMENT"
    elif tx_type == "REFUND":
        audit_action = "REFUND"

    rec = create_wallet_tx(
        adv,
        tx_type=tx_type,
        amount_cents=amount,
        idempotency_key=body["idempotency_key"],
        reference_event_id=body.get("reference_event_id"),
        note=body.get("note"),
        actor_user_id=current_user_id(),
        actor_role=current_role(),
        audit_action=audit_action,
    )
    # First-time funding may trigger PENDING → ACTIVE on the advertiser.
    from ..services.qualification import maybe_activate_advertiser
    maybe_activate_advertiser(adv)
    store.touch(adv)
    return success(rec, status=201)


@bp.get("/advertisers/<advertiser_id>/wallet/transactions")
@require_auth(["PlatformAdmin", "AccountOwner", "FinanceOfficer"])
def list_transactions(advertiser_id):
    resolve_advertiser(advertiser_id)
    limit, offset = get_pagination()
    rows = [t for t in store.list_all("WalletTransaction") if t.get("advertiser_id") == advertiser_id]
    tx_type = request.args.get("tx_type")
    status = request.args.get("status")
    if tx_type:
        rows = [r for r in rows if r.get("tx_type") == tx_type]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows = sort_by_created_asc(rows)
    page, meta = paginate(rows, limit, offset)
    return success(page, pagination=meta)


@bp.post("/advertisers/<advertiser_id>/wallet/transactions/<tx_id>/reverse")
@require_auth(["FinanceOfficer", "PlatformAdmin"])
def reverse_transaction(advertiser_id, tx_id):
    adv, tx = resolve_wallet_tx(advertiser_id, tx_id)
    body = get_json_body()
    note = body.get("note")
    rec = reverse_wallet_tx(adv, tx, note)
    return success(rec)


@bp.get("/advertisers/<advertiser_id>/wallet/statement")
@require_auth(["PlatformAdmin", "AccountOwner", "FinanceOfficer"])
def wallet_statement(advertiser_id):
    adv = resolve_advertiser(advertiser_id)
    frm = request.args.get("from")
    to = request.args.get("to")

    inflow = 0
    outflow = 0
    consumption = 0
    refunds = 0
    n_txns = 0
    for tx in store.list_all("WalletTransaction"):
        if tx.get("advertiser_id") != advertiser_id:
            continue
        if tx.get("status") != "SETTLED":
            continue
        ts = tx.get("created_at", "")
        if frm and ts < frm:
            continue
        if to and ts > to:
            continue
        n_txns += 1
        amt = int(tx["amount_cents"])
        if amt > 0:
            inflow += amt
        else:
            outflow += -amt
        if tx["tx_type"] == "CONSUMPTION":
            consumption += -amt
        if tx["tx_type"] == "REFUND":
            refunds += amt
    return success(
        {
            "advertiser_id": advertiser_id,
            "from": frm,
            "to": to,
            "inflow_cents": inflow,
            "outflow_cents": outflow,
            "consumption_cents": consumption,
            "refund_cents": refunds,
            "transaction_count": n_txns,
            "balance_cents": int(adv.get("balance_cents", 0)),
            "consumed_cents": int(adv.get("consumed_cents", 0)),
            "balance_state": adv.get("balance_state"),
        }
    )
