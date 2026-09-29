"""Article processing charges: invoice issuance and settlement."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
import validate as v
from auth import authorise
from db import now_iso, ordered, stamp_new, store, touch
from errors import ApiError
from response import list_response, object_response
from routes.manuscripts import find_manuscript

bp = Blueprint("fees", __name__)

ACTIONS = ("PAY", "WAIVE", "CANCEL")
INVOICE_READ_ROLES = ("SystemAdmin", "EditorInChief", "ProductionStaff", "Author")


def find_invoice(iid):
    invoice = store.invoices.get(iid)
    if invoice is None:
        raise ApiError("ERR_APC_INVOICE_NOT_FOUND")
    return invoice


@bp.post("/manuscripts/<mid>/apc-invoices")
def issue_invoice(mid):
    authorise("ProductionStaff")
    manuscript = find_manuscript(mid)
    data = v.body()
    expected = v.req_int(data, "expected_manuscript_version")
    page_charge_count = v.opt_int(data, "page_charge_count", default=0, minimum=0)
    color_figure_count = v.opt_int(data, "color_figure_count", default=0, minimum=0)

    if expected != int(manuscript["version"]):
        raise ApiError("ERR_STALE_MANUSCRIPT_VERSION")

    svc.guard_manuscript_terminal(manuscript)
    if calc.has_high_ethics_hold(mid):
        raise ApiError("ERR_ETHICS_HOLD")

    journal = calc.journal_of(manuscript)
    author = calc.author_of(manuscript)
    license_at_issue = manuscript["oa_license"]
    row = {
        "manuscript_id": mid,
        "license_at_issue": license_at_issue,
        "page_charge_count": page_charge_count,
        "color_figure_count": color_figure_count,
    }
    row.update(
        calc.price_invoice(
            journal, license_at_issue, author, page_charge_count, color_figure_count
        )
    )
    row["status"] = "ISSUED"
    row["waiver_reason"] = None
    row["settled_at"] = None
    stamp_new(row)
    store.invoices[row["id"]] = row

    journal["apc_receivable_cents"] = int(journal["apc_receivable_cents"]) + int(
        row["total_due_cents"]
    )
    touch(journal)
    if int(row["total_due_cents"]) == 0:
        svc.advance_fee_clearance(manuscript, ignore_invoice_id=row["id"])
    touch(manuscript)
    return object_response(ser.invoice_out(row), 201)


@bp.post("/apc-invoices/<iid>/settlement")
def settle_invoice(iid):
    authorise("ProductionStaff", "SystemAdmin")
    invoice = find_invoice(iid)
    data = v.body()
    action = v.req_enum(data, "action", ACTIONS)
    amount_cents = v.opt_int(data, "amount_cents", minimum=0)
    waiver_reason = v.opt_string(data, "waiver_reason")

    svc.guard_invoice_terminal(invoice)
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_INVOICE_STATE")

    manuscript = store.manuscripts.get(invoice["manuscript_id"])
    journal = calc.journal_of(manuscript) if manuscript is not None else None
    total = int(invoice["total_due_cents"])

    if action == "PAY":
        if amount_cents is None:
            v.bad("amount_cents", "is required for a PAY settlement")
        if total <= 0 or amount_cents != total:
            raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")
        invoice["status"] = "PAID"
    elif action == "WAIVE":
        if waiver_reason is None or waiver_reason.strip() == "":
            raise ApiError("ERR_WAIVER_NOT_ALLOWED", "A non-empty waiver_reason is required.")
        invoice["status"] = "WAIVED"
        invoice["waiver_reason"] = waiver_reason
    else:
        job = (
            calc.production_job_of_manuscript(invoice["manuscript_id"])
            if manuscript is not None
            else None
        )
        if job is not None and job["clearance_stage"] != "LICENSE_PENDING":
            raise ApiError(
                "ERR_WAIVER_NOT_ALLOWED",
                "The clearance dimension has already moved past LICENSE_PENDING.",
            )
        invoice["status"] = "CANCELLED"

    invoice["settled_at"] = now_iso()
    touch(invoice)

    if journal is not None:
        journal["apc_receivable_cents"] = int(journal["apc_receivable_cents"]) - total
        if action == "WAIVE":
            journal["apc_waived_cents"] = int(journal["apc_waived_cents"]) + total
        touch(journal)

    if action in ("PAY", "WAIVE") and manuscript is not None:
        svc.advance_fee_clearance(manuscript)
    return object_response(ser.invoice_out(invoice), 200)


# ==========================================================================
# reads
# ==========================================================================
@bp.get("/apc-invoices/<iid>")
def get_invoice(iid):
    authorise(*INVOICE_READ_ROLES)
    return object_response(ser.invoice_out(find_invoice(iid)), 200)


@bp.get("/manuscripts/<mid>/apc-invoices")
def list_manuscript_invoices(mid):
    authorise(*INVOICE_READ_ROLES)
    find_manuscript(mid)
    limit, offset = v.pagination()
    status = v.query_str("status")
    rows = [
        i
        for i in calc.invoices_of_manuscript(mid)
        if status is None or i["status"] == status
    ]
    rows = ordered(rows)
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.invoice_out), limit, offset, len(rows))


@bp.get("/manuscripts/<mid>/apc-invoices/<iid>")
def get_manuscript_invoice(mid, iid):
    authorise(*INVOICE_READ_ROLES)
    find_manuscript(mid)
    invoice = find_invoice(iid)
    if invoice["manuscript_id"] != mid:
        raise ApiError("ERR_PARENT_MISMATCH")
    return object_response(ser.invoice_out(invoice), 200)
