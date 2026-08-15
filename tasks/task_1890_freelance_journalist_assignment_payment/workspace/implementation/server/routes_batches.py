"""Payment batch endpoints: add-invoice, lock, release (OCC), cancel."""

from flask import request

from . import cascade
from .auth import require
from .blueprint import bp
from .envelope import ok_list, ok_obj
from .errors import ApiError, bad_request, invalid_state, not_found
from .serialize import ser_payment_batch
from .store import STORE, new_entity, touch
from .util import body, opt_str, paged, pagination_params, req_dt, sort_created

ROLES = ["FinanceUser"]
READ_ROLES = ["DeskAdmin", "FinanceUser"]


def _get_batch_or_404(bid):
    b = STORE.payment_batches.get(bid)
    if b is None:
        not_found("PaymentBatch")
    return b


@bp.post("/freelance-desk/payment-batches")
def create_payment_batch():
    require(ROLES)
    b = body()
    scheduled = req_dt(b, "scheduled_pay_date")
    e = new_entity()
    e.update({
        "scheduled_pay_date": scheduled,
        "status": "OPEN",
        "total_gross_cents": 0,
        "total_withholding_cents": 0,
        "total_net_cents": 0,
        "locked_by_user_id": None,
    })
    STORE.payment_batches[e["id"]] = e
    return ok_obj(ser_payment_batch(e), 201)


@bp.get("/freelance-desk/payment-batches")
def list_payment_batches():
    require(READ_ROLES)
    items = list(STORE.payment_batches.values())
    status = request.args.get("status")
    if status:
        items = [b for b in items if b["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_payment_batch(b) for b in page], limit, offset, total)


@bp.get("/freelance-desk/payment-batches/<bid>")
def get_payment_batch(bid):
    require(READ_ROLES)
    return ok_obj(ser_payment_batch(_get_batch_or_404(bid)))


@bp.post("/freelance-desk/payment-batches/<bid>/add-invoice")
def add_invoice(bid):
    require(ROLES)
    batch = _get_batch_or_404(bid)
    if batch["status"] != "OPEN":
        raise ApiError("ERR_BATCH_NOT_OPEN", 409, "Invoices can only be added to an OPEN batch")
    b = body()
    invoice_id = opt_str(b, "invoice_id")
    if invoice_id is None:
        bad_request("invoice_id is required")
    inv = STORE.invoices.get(invoice_id)
    if inv is None:
        not_found("Invoice")
    if inv["status"] != "APPROVED" or inv["payment_batch_id"] is not None:
        raise ApiError("ERR_BATCH_NOT_OPEN", 409, "Only an APPROVED invoice can be batched")
    inv["payment_batch_id"] = batch["id"]
    inv["status"] = "BATCHED"
    touch(inv)
    cascade.recompute_batch_totals(batch)
    touch(batch)
    return ok_obj(ser_payment_batch(batch))


@bp.post("/freelance-desk/payment-batches/<bid>/lock")
def lock_batch(bid):
    uid, role = require(ROLES)
    batch = _get_batch_or_404(bid)
    if batch["status"] != "OPEN":
        raise ApiError("ERR_BATCH_NOT_OPEN", 409, "Only an OPEN batch can be locked")
    if not cascade.batch_members(batch):
        raise ApiError("ERR_BATCH_NOT_OPEN", 409, "Cannot lock an empty batch")
    cascade.recompute_batch_totals(batch)
    batch["locked_by_user_id"] = uid
    batch["status"] = "LOCKED"
    touch(batch)
    return ok_obj(ser_payment_batch(batch))


@bp.post("/freelance-desk/payment-batches/<bid>/release")
def release_batch_endpoint(bid):
    uid, role = require(ROLES)
    batch = _get_batch_or_404(bid)
    if batch["status"] != "LOCKED":
        invalid_state("Only a LOCKED batch can be released")
    # Priority 7: segregation of duties
    if batch["locked_by_user_id"] is not None and uid == batch["locked_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The FinanceUser who locked the batch may not release it",
        )
    b = body()
    if "expected_batch_version" not in b or b["expected_batch_version"] is None:
        bad_request("expected_batch_version is required")
    expected = b["expected_batch_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        bad_request("expected_batch_version must be an integer")
    # Priority 19: OCC, evaluated after every other rule
    if expected != batch["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412, "expected_batch_version does not match current version"
        )
    cascade.release_batch(batch)
    return ok_obj(ser_payment_batch(batch))


@bp.post("/freelance-desk/payment-batches/<bid>/cancel")
def cancel_batch(bid):
    require(ROLES)
    batch = _get_batch_or_404(bid)
    if batch["status"] != "OPEN":
        invalid_state("Only an OPEN batch can be cancelled")
    for inv in cascade.batch_members(batch):
        inv["status"] = "APPROVED"
        inv["payment_batch_id"] = None
        touch(inv)
    cascade.recompute_batch_totals(batch)
    batch["status"] = "CANCELLED"
    touch(batch)
    return ok_obj(ser_payment_batch(batch))
