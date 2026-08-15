"""Invoice endpoints: list/get (late fee evaluated at read) and transitions
(pay exact amount, dispute, resolve, void)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch
from errors import (
    raise_err,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_OWNERSHIP_VIOLATION,
    ERR_PAYMENT_AMOUNT_MISMATCH,
)
from middleware import require_roles, forbid
from response import success_object, success_list
from services import domain
from services.serializers import invoice_view
from util import (
    get_json_body,
    get_or_404,
    optional_int,
    parse_pagination,
    paginate,
    query_arg,
    require_field,
    sort_created,
)

bp = Blueprint("invoices", __name__, url_prefix="/api/invoices")

PM = "ProgramManager"
UC = "UtilityCoordinator"
FA = "FinanceAnalyst"

TRANSITION_TARGETS = {"PAID", "DISPUTED", "ISSUED", "VOID"}


@bp.route("", methods=["GET"])
@require_roles(PM, UC, FA)
def list_invoices(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.invoices.values())
    run_id = query_arg("true_up_run_id")
    participation_id = query_arg("participation_id")
    status = query_arg("status")
    if run_id:
        items = [i for i in items if i["true_up_run_id"] == run_id]
    if participation_id:
        items = [i for i in items if i["participation_id"] == participation_id]
    if status:
        items = [i for i in items if i["status"] == status]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([invoice_view(i) for i in page], limit, offset, total)


@bp.route("/<iid>", methods=["GET"])
@require_roles(PM, UC, FA)
def get_invoice(iid: str, _user_id: str, _role: str):
    return success_object(invoice_view(get_or_404(db.invoices, iid, "Invoice")))


@bp.route("/<iid>/transition", methods=["POST"])
@require_roles(UC, PM)
def transition_invoice(iid: str, _user_id: str, _role: str):
    invoice = get_or_404(db.invoices, iid, "Invoice")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in TRANSITION_TARGETS:
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(TRANSITION_TARGETS)}")

    # Per-transition actors: pay/dispute belong to the owning coordinator;
    # resolve/void belong to the ProgramManager.
    if to in {"PAID", "DISPUTED"}:
        if _role != UC:
            forbid("only the owning UtilityCoordinator may pay or dispute")
        if invoice["participation_id"] != _user_id:
            raise_err(ERR_OWNERSHIP_VIOLATION,
                      "UtilityCoordinator may only pay or dispute its own invoices")
    else:
        if _role != PM:
            forbid("only ProgramManager may resolve or void an invoice")

    current = invoice["status"]
    if current in {"PAID", "VOID"}:
        raise_err(ERR_INVALID_STATE, f"invoice is terminal ({current})")

    if to == "PAID":
        if current != "ISSUED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> PAID")
        paid_amount = require_field(body, "paid_amount_cents")
        from util import is_int as _is_int
        if not _is_int(paid_amount):
            raise_err(ERR_VALIDATION, "paid_amount_cents must be an integer")
        amount_due = invoice["principal_cents"] + domain.invoice_late_fee(invoice)
        if paid_amount != amount_due:
            raise_err(ERR_PAYMENT_AMOUNT_MISMATCH,
                      f"paid_amount_cents {paid_amount} != amount due {amount_due}")
        invoice["status"] = "PAID"
        invoice["paid_on"] = domain.clock_str()
        touch(invoice)
        # Cascade: when every invoice of the participation is PAID|VOID, the
        # participation settles (BILLED -> SETTLED).
        part = db.participations.get(invoice["participation_id"])
        if part is not None and part["status"] == "BILLED":
            open_invoices = [i for i in db.invoices.values()
                             if i["participation_id"] == part["id"]
                             and i["status"] not in {"PAID", "VOID"}]
            if not open_invoices:
                part["status"] = "SETTLED"
                touch(part)

    elif to == "DISPUTED":
        if current != "ISSUED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> DISPUTED")
        invoice["status"] = "DISPUTED"
        touch(invoice)

    elif to == "ISSUED":
        # Dispute resolution: optionally replace the principal.
        if current != "DISPUTED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> ISSUED")
        adjusted = optional_int(body, "adjusted_principal_cents")
        if adjusted is not None:
            if adjusted <= 0:
                raise_err(ERR_VALIDATION,
                          "adjusted_principal_cents must be > 0 when provided")
            invoice["principal_cents"] = adjusted
        invoice["status"] = "ISSUED"
        touch(invoice)

    elif to == "VOID":
        if current not in {"ISSUED", "DISPUTED"}:
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> VOID")
        invoice["status"] = "VOID"
        touch(invoice)

    return success_object(invoice_view(invoice))
