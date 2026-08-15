"""Invoice endpoints (PRD 3.9): DRAFT creation with OCC on the work package,
live line recomputation while DRAFT, freeze at submit, approval chain, and the
transient billing preview (final vs provisional variants)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_FORBIDDEN, ERR_OPEN_REWORK, ERR_NO_BILLABLE_UNITS,
    ERR_BILLING_PERIOD_OVERLAP, ERR_INVALID_DATE_RANGE,
)
from middleware import authorized
from response import success_object
from routes.helpers import serialize, list_response, get_one
from routes.work_packages import require_contract_active
from services.billing import compute_lines, totals_as_numbers, line_total_units
from services.core import (
    new_record, touch, contract_of_work_package, rework_open_count,
)
from util import parse_date
from validate import (
    get_body, req_date, req_int, req_enum, require_path_resource,
)

bp = Blueprint("invoices", __name__)

INVOICE_CREATE_STATES = ("IN_PROGRESS", "PUNCH", "COMPLETED")


@bp.post("/work-packages/<work_package_id>/invoices")
def create_invoice(work_package_id):
    authorized(["CONTRACTOR_PM"])
    body = get_body()
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    expected_wp_version = req_int(body, "expected_work_package_version")
    wp = require_path_resource("work_packages", work_package_id)
    # OCC (priority 5) precedes state evaluation.
    if expected_wp_version != wp["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_work_package_version does not match the work "
                    "package's current version")
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    if wp["status"] not in INVOICE_CREATE_STATES:
        raise_error(ERR_INVALID_STATE,
                    "invoice creation requires work package IN_PROGRESS, "
                    "PUNCH, or COMPLETED")
    ps, pe = parse_date(period_start), parse_date(period_end)
    if pe < ps:
        raise_error(ERR_INVALID_DATE_RANGE, "period_end must be >= period_start")
    # Fiscal rule: billing periods of non-VOID invoices of this work package
    # must not overlap (adjacency allowed).
    for inv in db["invoices"].values():
        if inv["work_package_id"] != wp["id"] or inv["status"] == "VOID":
            continue
        is_, ie = parse_date(inv["period_start"]), parse_date(inv["period_end"])
        if not (ps > ie or is_ > pe):
            raise_error(ERR_BILLING_PERIOD_OVERLAP,
                        "period overlaps another non-VOID invoice of this work package")
    rec = new_record("invoices", {
        "work_package_id": wp["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "frozen_lines": None,
        "frozen_subtotal": None,
        "frozen_retainage_amount": None,
        "frozen_amount_due": None,
    })
    touch(wp)  # invoice creation increments the work package's version
    return success_object(serialize("invoices", rec), status=201)


@bp.get("/invoices")
def list_invoices():
    filters = {
        "work_package_id": request.args.get("work_package_id"),
        "status": request.args.get("status"),
    }
    return list_response("invoices", filters)


@bp.get("/invoices/<invoice_id>")
def get_invoice(invoice_id):
    return get_one("invoices", invoice_id)


# Per-transition actor roles; endpoint-level roles checked by authorized().
_TRANSITION_ACTORS = {
    "SUBMITTED": "CONTRACTOR_PM",
    "APPROVED": "UTILITY_INSPECTOR",
    "REJECTED": "UTILITY_INSPECTOR",
    "PAID": "UTILITY_DISPATCHER",
    "DRAFT": "CONTRACTOR_PM",
    "VOID": "CONTRACTOR_PM",
}

_TRANSITION_SOURCES = {
    "SUBMITTED": ("DRAFT",),
    "APPROVED": ("SUBMITTED",),
    "REJECTED": ("SUBMITTED",),
    "PAID": ("APPROVED",),
    "DRAFT": ("REJECTED",),
    "VOID": ("DRAFT", "SUBMITTED", "REJECTED"),
}


@bp.post("/invoices/<invoice_id>/transition")
def transition_invoice(invoice_id):
    role = authorized(["CONTRACTOR_PM", "UTILITY_INSPECTOR", "UTILITY_DISPATCHER"])
    body = get_body()
    to = req_enum(body, "to", set(_TRANSITION_ACTORS.keys()))
    invoice = require_path_resource("invoices", invoice_id)
    wp = require_path_resource("work_packages", invoice["work_package_id"])
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    if role != _TRANSITION_ACTORS[to]:
        raise_error(ERR_FORBIDDEN,
                    f"invoice transition to {to} requires role "
                    f"{_TRANSITION_ACTORS[to]}")
    if invoice["status"] not in _TRANSITION_SOURCES[to]:
        raise_error(ERR_INVALID_STATE,
                    f"cannot transition invoice from {invoice['status']} to {to}")

    if to == "SUBMITTED":
        if rework_open_count(wp["id"]) != 0:
            raise_error(ERR_OPEN_REWORK,
                        "open rework blocks invoice submission")
        # Freeze the final-variant computation at submission time.
        lines, subtotal, retainage, amount_due = compute_lines(
            wp, invoice["period_start"], invoice["period_end"], "final")
        if not any(line_total_units(l) > 0 for l in lines):
            raise_error(ERR_NO_BILLABLE_UNITS,
                        "invoice has no line with billable units")
        s, r, a = totals_as_numbers(subtotal, retainage, amount_due)
        invoice["frozen_lines"] = lines
        invoice["frozen_subtotal"] = s
        invoice["frozen_retainage_amount"] = r
        invoice["frozen_amount_due"] = a
    elif to == "DRAFT":
        # Revise: unfreeze; lines resume live recomputation and the frozen
        # unit pool is released (billed_quantity derives from frozen lines of
        # SUBMITTED/APPROVED/PAID invoices only).
        invoice["frozen_lines"] = None
        invoice["frozen_subtotal"] = None
        invoice["frozen_retainage_amount"] = None
        invoice["frozen_amount_due"] = None
    elif to == "VOID" and invoice["status"] == "DRAFT":
        # Keep a stable snapshot of the last live computation for audit.
        lines, subtotal, retainage, amount_due = compute_lines(
            wp, invoice["period_start"], invoice["period_end"], "final")
        s, r, a = totals_as_numbers(subtotal, retainage, amount_due)
        invoice["frozen_lines"] = lines
        invoice["frozen_subtotal"] = s
        invoice["frozen_retainage_amount"] = r
        invoice["frozen_amount_due"] = a

    invoice["status"] = to
    touch(invoice)
    return success_object(serialize("invoices", invoice))


@bp.get("/work-packages/<work_package_id>/billing-preview")
def billing_preview(work_package_id):
    """Transient invoice-shaped preview; variant=provisional widens the
    eligible-units basis to SUBMITTED + ACCEPTED. Persists nothing."""
    authorized(["CONTRACTOR_PM", "FOREMAN", "UTILITY_INSPECTOR", "UTILITY_DISPATCHER"])
    period_start = request.args.get("period_start")
    period_end = request.args.get("period_end")
    variant = request.args.get("variant", "final")
    if not period_start or not period_end:
        raise_error(ERR_INVALID_REQUEST,
                    "period_start and period_end query parameters are required")
    if variant not in ("final", "provisional"):
        raise_error(ERR_INVALID_REQUEST, "variant must be final or provisional")
    try:
        ps, pe = parse_date(period_start), parse_date(period_end)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "period_start/period_end must be ISO dates")
    wp = require_path_resource("work_packages", work_package_id)
    if pe < ps:
        raise_error(ERR_INVALID_DATE_RANGE, "period_end must be >= period_start")
    lines, subtotal, retainage, amount_due = compute_lines(
        wp, period_start, period_end, variant)
    s, r, a = totals_as_numbers(subtotal, retainage, amount_due)
    preview = {
        "work_package_id": wp["id"],
        "period_start": period_start,
        "period_end": period_end,
        "variant": variant,
        "status": "DRAFT",
        "lines": lines,
        "subtotal": s,
        "retainage_amount": r,
        "amount_due": a,
        "hold_reason": None,
    }
    return success_object(preview)
