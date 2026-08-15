"""Invoice endpoints (PRD section 3.12).

FREIGHT invoices are generated per booking (one per booking, non-VOID);
per-line rounding is pinned (each line rounds half-up independently, the total
sums rounded lines). Issue stamps issued_at/due_date and may auto-suspend the
shipper; payments drive ISSUED -> PARTIALLY_PAID -> PAID; adjustments to a
DRAFT invoice are OCC-guarded.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BOOKING_INVALID_STATE,
    ERR_BOOKING_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_EMPTY,
    ERR_INVOICE_EXISTS,
    ERR_INVOICE_INVALID_STATE,
    ERR_INVOICE_NOT_FOUND,
    ERR_OVERPAYMENT,
    ERR_STALE_INVOICE_VERSION,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    dec,
    get_json_body,
    has_field,
    paginate,
    parse_pagination,
    pub,
    require_enum,
    require_int,
    require_number,
    require_string,
    round_half_up_int,
    sort_by_created_at,
)

bp = Blueprint("invoices", __name__)

INVOICE_TYPES = {"FREIGHT", "DEMURRAGE_DETENTION", "CANCELLATION"}
INVOICE_BOOKING_STATES = {"CONFIRMED", "DOCUMENTATION_CLEARED", "LOADED", "DEPARTED", "ARRIVED"}


def _get_invoice(invoice_id: str) -> dict:
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise_err(ERR_INVOICE_NOT_FOUND, "Invoice id does not exist")
    return inv


def _refresh_shipper_for_invoice(inv: dict) -> None:
    booking = db.bookings.get(inv["booking_id"])
    shipper = db.shippers.get(booking["shipper_id"]) if booking else None
    if shipper is not None:
        domain.recompute_shipper_exposure(shipper)


@bp.route("/freight/invoices", methods=["POST"])
@require_roles("FinanceController")
def create_invoice(_user_id: str, _role: str):
    body = get_json_body()

    # Band 3: booking FK existence.
    booking = None
    if has_field(body, "booking_id"):
        booking = db.bookings.get(body["booking_id"])
        if booking is None:
            raise_err(ERR_BOOKING_NOT_FOUND, "booking_id does not exist")

    # Band 5: body shape.
    require_string(body, "booking_id")
    invoice_type = require_enum(body, "invoice_type", INVOICE_TYPES)

    # Band 6: booking state permits invoicing.
    if booking["status"] not in INVOICE_BOOKING_STATES:
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking state does not permit invoice generation")

    if invoice_type == "FREIGHT":
        # Band 10: at most one non-VOID FREIGHT invoice per booking.
        for other in db.invoices.values():
            if (
                other["booking_id"] == booking["id"]
                and other["invoice_type"] == "FREIGHT"
                and other["status"] != "VOID"
            ):
                raise_err(ERR_INVOICE_EXISTS, "A FREIGHT invoice already exists for this booking")
        lines = domain.build_freight_invoice_lines(booking)
    else:
        # D&D and CANCELLATION invoices are auto-created by the system; a manual
        # creation carries no auto-derived lines.
        lines = []

    inv = {
        "booking_id": booking["id"],
        "invoice_number": f"INV-{db.next_seq('invoice')}",
        "invoice_type": invoice_type,
        "lines": lines,
        "total_cents": 0,
        "paid_cents": 0,
        "balance_cents": 0,
        "issued_at": None,
        "due_date": None,
        "status": "DRAFT",
    }
    db.stamp_new(inv)
    domain.invoice_recompute_totals(inv)
    db.invoices[inv["id"]] = inv
    _refresh_shipper_for_invoice(inv)
    return success_object(pub(inv), 201)


@bp.route("/freight/invoices", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_invoices(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.invoices.values()))
    items = apply_filters(items, ["booking_id", "invoice_type", "status"])
    page, total = paginate(items, limit, offset)
    return success_list([pub(i) for i in page], limit, offset, total)


@bp.route("/freight/invoices/<invoice_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_invoice(invoice_id: str, _user_id: str, _role: str):
    return success_object(pub(_get_invoice(invoice_id)))


@bp.route("/freight/invoices/<invoice_id>/issue", methods=["POST"])
@require_roles("FinanceController")
def issue_invoice(invoice_id: str, _user_id: str, _role: str):
    inv = _get_invoice(invoice_id)
    get_json_body()
    if inv["status"] != "DRAFT":
        raise_err(ERR_INVOICE_INVALID_STATE, "Invoice must be DRAFT to issue")
    if inv["total_cents"] <= 0:
        raise_err(ERR_INVOICE_EMPTY, "Invoice total must be greater than zero to issue")

    inv["issued_at"] = db.now_domain_iso()
    booking = db.bookings.get(inv["booking_id"])
    shipper = db.shippers.get(booking["shipper_id"]) if booking else None
    terms = shipper["credit_terms"] if shipper is not None else "PREPAID_ONLY"
    inv["due_date"] = domain.compute_due_date(inv["issued_at"], terms)
    inv["status"] = "ISSUED"
    db.touch(inv)

    if shipper is not None:
        domain.recompute_shipper_exposure(shipper)
        domain.auto_suspend_if_over_limit(shipper)
    return success_object(pub(inv))


@bp.route("/freight/invoices/<invoice_id>/payments", methods=["POST"])
@require_roles("FinanceController")
def record_payment(invoice_id: str, _user_id: str, _role: str):
    inv = _get_invoice(invoice_id)
    body = get_json_body()

    # Band 5: amount present and an integer.
    amount_cents = require_int(body, "amount_cents")

    # Band 6: state.
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise_err(ERR_INVOICE_INVALID_STATE, "Invoice must be ISSUED or PARTIALLY_PAID to accept payments")

    # Band 13: 0 < amount <= balance.
    if amount_cents <= 0 or amount_cents > inv["balance_cents"]:
        raise_err(ERR_OVERPAYMENT, "Payment amount must be > 0 and <= balance_cents")

    inv["paid_cents"] += amount_cents
    domain.invoice_recompute_totals(inv)
    inv["status"] = "PAID" if inv["paid_cents"] == inv["total_cents"] else "PARTIALLY_PAID"
    db.touch(inv)
    _refresh_shipper_for_invoice(inv)
    return success_object(pub(inv))


@bp.route("/freight/invoices/<invoice_id>/void", methods=["POST"])
@require_roles("FinanceController")
def void_invoice(invoice_id: str, _user_id: str, _role: str):
    inv = _get_invoice(invoice_id)
    get_json_body()
    if inv["status"] == "DRAFT":
        pass
    elif inv["status"] == "ISSUED" and inv["paid_cents"] == 0:
        pass
    else:
        raise_err(
            ERR_INVOICE_INVALID_STATE,
            "Invoice must be DRAFT, or ISSUED with zero payments, to void",
        )
    inv["status"] = "VOID"
    db.touch(inv)
    _refresh_shipper_for_invoice(inv)
    return success_object(pub(inv))


@bp.route("/freight/invoices/<invoice_id>/adjustments", methods=["POST"])
@require_roles("FinanceController")
def add_adjustment(invoice_id: str, _user_id: str, _role: str):
    inv = _get_invoice(invoice_id)
    body = get_json_body()

    # Band 5: body shape.
    description = require_string(body, "description")
    quantity = require_number(body, "quantity")
    unit_rate_cents = require_int(body, "unit_rate_cents")
    if not has_field(body, "expected_invoice_version"):
        raise_err(ERR_INVALID_REQUEST, "expected_invoice_version is required")
    expected = body["expected_invoice_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_invoice_version must be an integer")

    # Band 6: DRAFT only.
    if inv["status"] != "DRAFT":
        raise_err(ERR_INVOICE_INVALID_STATE, "Adjustments require a DRAFT invoice")

    # Band 14: OCC on the invoice version.
    if expected != inv["version"]:
        raise_err(ERR_STALE_INVOICE_VERSION, "Invoice version has advanced since the client's view")

    # Pinned per-line rounding: each line rounds half-up independently.
    amount = round_half_up_int(dec(quantity) * unit_rate_cents)
    inv["lines"].append(
        {
            "line_type": "MANUAL_ADJUSTMENT",
            "description": description,
            "quantity": quantity,
            "unit_rate_cents": unit_rate_cents,
            "amount_cents": amount,
        }
    )
    domain.invoice_recompute_totals(inv)
    db.touch(inv)
    _refresh_shipper_for_invoice(inv)
    return success_object(pub(inv))
