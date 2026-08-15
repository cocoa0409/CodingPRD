"""Transaction ingest (single + batch settlement file) and reads (PRD 3.3)."""

from flask import Blueprint, g, request

from db import db
from errors import ApiError
from middleware import is_merchant_user
from records import new_transaction
from response import ok_object
from routes.common import ALL_ROLES, authenticate, get_or_404, hide_if_cross_merchant, json_body, list_response
from serializers import serialize_transaction
from services.reserve import apply_transaction_ingest_side_effects
from util import Body, NETWORKS, TRANSACTION_STATUSES, filter_enum

bp = Blueprint("transactions", __name__)


def _check_merchant_active(merchant):
    """Priority 6 compliance gate for ingest."""
    if merchant["status"] != "ACTIVE":
        raise ApiError(409, "ERR_MERCHANT_NOT_ACTIVE", "Merchant is not ACTIVE")


def _external_ref_taken(merchant_id, external_ref):
    return any(t for t in db.transactions.values()
               if t["merchant_id"] == merchant_id and t["external_ref"] == external_ref)


@bp.post("/acquirer/transactions")
def create_transaction():
    authenticate(("AcquirerOps",))
    b = Body(json_body())
    merchant_id = b.req_str("merchant_id")
    external_ref = b.req_str("external_ref")
    network = b.req_enum("network", NETWORKS)
    amount_cents = b.req_int("amount_cents")
    occurred_at = b.req_dt("occurred_at")

    # Priority 3: body-referenced merchant must exist.
    merchant = None
    if merchant_id is not None:
        merchant = get_or_404(db.merchants, merchant_id, "Merchant")
    # Priority 6: merchant must be ACTIVE.
    if merchant is not None:
        _check_merchant_active(merchant)
    # Priority 7: external_ref unique within the merchant.
    if merchant is not None and external_ref is not None and _external_ref_taken(merchant["id"], external_ref):
        raise ApiError(409, "ERR_DUPLICATE_EXTERNAL_REF", "external_ref already used by another transaction of this merchant")
    # Priority 11: payload shape (amount strictly positive etc.).
    if amount_cents is not None and amount_cents <= 0:
        b._fail(("ERR_INVALID_REQUEST", 400), "Field 'amount_cents' must be > 0")
    b.raise_pending()

    txn = new_transaction(merchant["id"], external_ref, network, amount_cents, occurred_at)
    db.transactions[txn["id"]] = txn
    apply_transaction_ingest_side_effects(merchant, txn)
    return ok_object(serialize_transaction(txn), status=201)


@bp.post("/acquirer/transactions/batch")
def create_transactions_batch():
    authenticate(("AcquirerOps",))
    b = Body(json_body())
    merchant_id = b.req_str("merchant_id")
    network = b.req_enum("network", NETWORKS)
    count = b.req_int("count", minv=1)
    amount_cents = b.req_int("amount_cents")
    occurred_at = b.req_dt("occurred_at")
    prefix = b.req_str("external_ref_prefix")

    merchant = None
    if merchant_id is not None:
        merchant = get_or_404(db.merchants, merchant_id, "Merchant")
    if merchant is not None:
        _check_merchant_active(merchant)

    # Priority 7: pre-validate every generated external_ref before creating any
    # (atomic batch: a duplicate rejects the whole file).
    refs = []
    if merchant is not None and count is not None and prefix is not None:
        for i in range(1, count + 1):
            ref = "%s-%04d" % (prefix, i)
            if ref in refs or _external_ref_taken(merchant["id"], ref):
                raise ApiError(409, "ERR_DUPLICATE_EXTERNAL_REF",
                               "external_ref '%s' already used by another transaction of this merchant" % ref)
            refs.append(ref)

    if amount_cents is not None and amount_cents <= 0:
        b._fail(("ERR_INVALID_REQUEST", 400), "Field 'amount_cents' must be > 0")
    b.raise_pending()

    created = []
    for i, ref in enumerate(refs, start=1):
        txn = new_transaction(merchant["id"], ref, network, amount_cents, occurred_at)
        db.transactions[txn["id"]] = txn
        # Same per-transaction side effects as single ingest, ascending sequence order.
        apply_transaction_ingest_side_effects(merchant, txn)
        created.append(txn)
    return ok_object({
        "created_count": len(created),
        "first_external_ref": created[0]["external_ref"],
        "last_external_ref": created[-1]["external_ref"],
    }, status=201)


@bp.get("/acquirer/transactions")
def list_transactions():
    authenticate(ALL_ROLES)
    merchant_id = request.args.get("merchant_id")
    status = filter_enum(request.args, "status", TRANSACTION_STATUSES)
    records = list(db.transactions.values())
    if is_merchant_user():
        records = [t for t in records if t["merchant_id"] == g.uid]
    elif merchant_id is not None:
        records = [t for t in records if t["merchant_id"] == merchant_id]
    if status is not None:
        records = [t for t in records if t["status"] == status]
    return list_response(records, serialize_transaction)


@bp.get("/acquirer/transactions/<tid>")
def get_transaction(tid):
    authenticate(ALL_ROLES)
    txn = get_or_404(db.transactions, tid, "Transaction")
    hide_if_cross_merchant(txn["merchant_id"])
    return ok_object(serialize_transaction(txn))
