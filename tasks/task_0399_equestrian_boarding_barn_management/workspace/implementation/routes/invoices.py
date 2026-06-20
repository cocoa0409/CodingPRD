"""Invoice routes & settlement lifecycle (PRD §3.8, §3.9, §2.10 OCC)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_caller, require_role
from response import success
from services.common import (
    new_common, touch, require_str, require_int, parse_pagination, paginate, sort_by_created,
)
from services.serialize import view, view_list
from services.lookups import get_owner, get_invoice, require_owner_owns
from services.invoicing import collect_lines, compute_totals
from services.standing import recompute_committed

bp = Blueprint("invoices", __name__)


@bp.route("/invoices", methods=["POST"])
def create_invoice():
    caller = get_caller()
    require_role(caller, ["BarnManager"])
    body = request.get_json(silent=True) or {}
    owner_id = require_str(body, "owner_id")
    period_label = require_str(body, "period_label")
    owner = get_owner(owner_id)
    invoice = new_common()
    invoice.update({
        "owner_id": owner["id"],
        "period_label": period_label,
        "gross_amount_cents": 0,
        "multi_horse_discount_cents": 0,
        "deposit_applied_cents": 0,
        "amount_due_cents": 0,
        "paid_amount_cents": 0,
        "status": "OPEN",
    })
    db.invoices[invoice["id"]] = invoice
    return success(view(invoice), 201)


@bp.route("/owners/<owner_id>/invoices", methods=["GET"])
def list_owner_invoices(owner_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    owner = get_owner(owner_id)
    require_owner_owns(caller, owner["id"])
    limit, offset = parse_pagination(request.args)
    items = [i for i in db.invoices.values() if i["owner_id"] == owner["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.route("/invoices/<invoice_id>/transition", methods=["POST"])
def transition_invoice(invoice_id):
    caller = get_caller()
    require_role(caller, ["BarnManager"])
    invoice = get_invoice(invoice_id)
    body = request.get_json(silent=True) or {}
    target = body.get("target_status")
    if target not in ("FINALIZED", "PAID", "VOID"):
        raise err("ERR_INVALID_STATE", "Unknown or illegal target_status")
    if target == "FINALIZED":
        return _finalize(invoice, body)
    if target == "PAID":
        return _pay(invoice, body)
    return _void(invoice)


def _finalize(invoice, body):
    owner = db.owners[invoice["owner_id"]]
    # state guard (priority 7)
    if invoice["status"] != "OPEN":
        raise err("ERR_INVOICE_NOT_OPEN", "Invoice is not OPEN")
    # billable-lines guard (priority 17)
    lines, boarding_horse_ids = collect_lines(owner)
    if not lines:
        raise err("ERR_NO_BILLABLE_LINES", "No unbilled billable lines for the owner")
    # OCC guard (priority 20) — expected_owner_version is non-optional on finalize
    expected = require_int(body, "expected_owner_version")
    if expected != owner["version"]:
        raise err("ERR_STALE_OWNER_VERSION", "expected_owner_version does not match owner version")

    totals = compute_totals(owner, lines, boarding_horse_ids)
    invoice["gross_amount_cents"] = totals["gross_amount_cents"]
    invoice["multi_horse_discount_cents"] = totals["multi_horse_discount_cents"]
    invoice["deposit_applied_cents"] = totals["deposit_applied_cents"]
    invoice["amount_due_cents"] = totals["amount_due_cents"]
    invoice["status"] = "FINALIZED"

    owner["deposit_held_cents"] -= totals["deposit_applied_cents"]
    owner["account_balance_cents"] += totals["amount_due_cents"]
    # mark swept lines invoiced; remember exactly which lines this invoice swept so
    # a later void reverts only these (not lines swept by some other invoice)
    swept = []
    for _, ref in lines:
        ref["invoiced"] = True
        touch(ref)
        swept.append(ref["id"])
    invoice["_swept_line_ids"] = swept
    owner["version"] += 1
    touch(invoice)
    # recompute committed standing (also touches owner with its own version bump)
    recompute_committed(owner)
    return success(view(invoice), 200)


def _pay(invoice, body):
    owner = db.owners[invoice["owner_id"]]
    if invoice["status"] != "FINALIZED":
        raise err("ERR_INVOICE_NOT_FINALIZED", "Invoice is not FINALIZED")
    amount = require_int(body, "amount_cents")
    if invoice["paid_amount_cents"] + amount > invoice["amount_due_cents"]:
        raise err("ERR_OVERPAYMENT", "Payment would exceed amount_due_cents")
    invoice["paid_amount_cents"] += amount
    owner["account_balance_cents"] -= amount
    if invoice["paid_amount_cents"] == invoice["amount_due_cents"]:
        invoice["status"] = "PAID"
    touch(invoice)
    recompute_committed(owner)
    return success(view(invoice), 200)


def _void(invoice):
    owner = db.owners[invoice["owner_id"]]
    if invoice["status"] == "OPEN":
        # no deposit applied while OPEN; just move to VOID (PRD §3.8)
        invoice["status"] = "VOID"
        touch(invoice)
        return success(view(invoice), 200)
    if invoice["status"] == "FINALIZED":
        if invoice["paid_amount_cents"] > 0:
            raise err("ERR_INVOICE_HAS_PAYMENTS", "Cannot void a FINALIZED invoice with payments")
        # fully reverse finalization (PRD §3.8)
        owner["deposit_held_cents"] += invoice["deposit_applied_cents"]
        owner["account_balance_cents"] -= invoice["amount_due_cents"]
        # un-invoice exactly the lines this invoice swept
        _revert_swept_lines(invoice)
        owner["version"] += 1
        invoice["status"] = "VOID"
        touch(invoice)
        recompute_committed(owner)
        return success(view(invoice), 200)
    raise err("ERR_INVOICE_NOT_OPEN", "Void requires OPEN or FINALIZED invoice")


def _revert_swept_lines(invoice):
    """Revert to invoiced=false exactly the lines this invoice swept at finalization
    (PRD §3.8). Tracked by id so concurrent invoices don't un-sweep each other."""
    swept = invoice.get("_swept_line_ids", [])
    stores = (db.lessons, db.visits, db.entries, db.agreements)
    for line_id in swept:
        for store in stores:
            ref = store.get(line_id)
            if ref is not None:
                ref["invoiced"] = False
                touch(ref)
                break
