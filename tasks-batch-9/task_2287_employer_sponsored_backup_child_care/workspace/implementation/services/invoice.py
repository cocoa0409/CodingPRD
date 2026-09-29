"""employer_invoice_totals plus the invoice lifecycle side effects."""

from datetime import date

from db import clock, db
from util import D, rhu_int

from services.core import created_key, new_plain_row, new_row, sort_created, touch


def invoice_lines(invoice_id):
    return sort_created(
        [l for l in db.invoice_lines.values() if l["employer_invoice_id"] == invoice_id]
    )


def billed_reservation_ids(invoice_id):
    """Distinct reservation ids across the invoice's lines, in line order."""
    seen = []
    for line in invoice_lines(invoice_id):
        if line["reservation_id"] not in seen:
            seen.append(line["reservation_id"])
    return seen


def billable_scope(employer, period_start, period_end):
    employee_ids = set(
        e["id"] for e in db.employees.values() if e["employer_id"] == employer["id"]
    )
    scope = []
    for reservation in db.reservations.values():
        if reservation["employee_id"] not in employee_ids:
            continue
        if reservation["billing_status"] != "ACCRUED":
            continue
        if reservation["fulfillment_status"] not in ("COMPLETED", "NO_SHOW", "CANCELLED"):
            continue
        care_date = date.fromisoformat(reservation["care_date"])
        if not (period_start <= care_date <= period_end):
            continue
        scope.append(reservation)
    scope.sort(key=lambda r: (r["care_date"], created_key(r)))
    return scope


def _emit(invoice, reservation, line_type, quantity, unit_cents):
    amount = rhu_int(D(quantity) * D(unit_cents))
    if amount == 0:
        return None
    line = new_plain_row(
        {
            "employer_invoice_id": invoice["id"],
            "reservation_id": reservation["id"],
            "employee_id": reservation["employee_id"],
            "line_type": line_type,
            "quantity": D(quantity),
            "unit_cents": int(unit_cents),
            "amount_cents": amount,
        }
    )
    db.invoice_lines[line["id"]] = line
    return line


def build_invoice(employer, period_start, period_end):
    invoice = new_row(
        {
            "employer_id": employer["id"],
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "copay_cents": 0,
            "overage_cents": 0,
            "penalty_cents": 0,
            "subtotal_cents": 0,
            "admin_fee_cents": 0,
            "total_cents": 0,
            "line_count": 0,
            "reservation_count": 0,
            "invoice_status": "DRAFT",
            "issued_at": None,
            "paid_amount_cents": 0,
            "void_reason_code": None,
        }
    )
    db.employer_invoices[invoice["id"]] = invoice

    lines = []
    swept = []
    for reservation in billable_scope(employer, period_start, period_end):
        if reservation["fulfillment_status"] in ("COMPLETED", "NO_SHOW"):
            line = _emit(
                invoice,
                reservation,
                "CARE_COPAY",
                reservation.get("_covered_qty", D(0)),
                reservation.get("_copay_unit", 0),
            )
            if line is not None:
                lines.append(line)
            line = _emit(
                invoice,
                reservation,
                "CARE_OVERAGE",
                reservation.get("_overage_qty", D(0)),
                reservation.get("_overage_unit", 0),
            )
            if line is not None:
                lines.append(line)
        if reservation["fulfillment_status"] == "NO_SHOW":
            line = _emit(
                invoice, reservation, "NO_SHOW_CHARGE", D(1), reservation["penalty_cents"]
            )
            if line is not None:
                lines.append(line)
        if reservation["fulfillment_status"] == "CANCELLED" and reservation[
            "penalty_cents"
        ] > 0:
            line = _emit(
                invoice,
                reservation,
                "LATE_CANCEL_CHARGE",
                D(1),
                reservation["penalty_cents"],
            )
            if line is not None:
                lines.append(line)
        swept.append(reservation)

    copay = sum(l["amount_cents"] for l in lines if l["line_type"] == "CARE_COPAY")
    overage = sum(l["amount_cents"] for l in lines if l["line_type"] == "CARE_OVERAGE")
    penalty = sum(
        l["amount_cents"]
        for l in lines
        if l["line_type"] in ("NO_SHOW_CHARGE", "LATE_CANCEL_CHARGE")
    )
    subtotal = sum(l["amount_cents"] for l in lines)
    admin_fee = rhu_int(D(subtotal) * D(employer["admin_fee_pct"]))

    invoice["copay_cents"] = copay
    invoice["overage_cents"] = overage
    invoice["penalty_cents"] = penalty
    invoice["subtotal_cents"] = subtotal
    invoice["admin_fee_cents"] = admin_fee
    invoice["total_cents"] = subtotal + admin_fee
    invoice["line_count"] = len(lines)
    invoice["reservation_count"] = len(set(l["reservation_id"] for l in lines))

    for reservation in swept:
        reservation["billing_status"] = "INVOICED"
        touch(reservation)

    return invoice


def issue_invoice(invoice):
    invoice["invoice_status"] = "ISSUED"
    invoice["issued_at"] = clock()
    touch(invoice)


def pay_invoice(invoice, paid_amount_cents):
    invoice["invoice_status"] = "PAID"
    invoice["paid_amount_cents"] = paid_amount_cents
    touch(invoice)
    for reservation_id in billed_reservation_ids(invoice["id"]):
        reservation = db.reservations.get(reservation_id)
        if reservation is not None and reservation["billing_status"] == "INVOICED":
            reservation["billing_status"] = "PAID"
            touch(reservation)


def void_invoice(invoice, reason_code):
    reservation_ids = billed_reservation_ids(invoice["id"])
    for line in invoice_lines(invoice["id"]):
        del db.invoice_lines[line["id"]]

    invoice["invoice_status"] = "VOID"
    invoice["void_reason_code"] = reason_code
    invoice["copay_cents"] = 0
    invoice["overage_cents"] = 0
    invoice["penalty_cents"] = 0
    invoice["subtotal_cents"] = 0
    invoice["admin_fee_cents"] = 0
    invoice["total_cents"] = 0
    invoice["line_count"] = 0
    invoice["reservation_count"] = 0
    touch(invoice)

    for reservation_id in reservation_ids:
        reservation = db.reservations.get(reservation_id)
        if reservation is not None and reservation["billing_status"] == "INVOICED":
            reservation["billing_status"] = "ACCRUED"
            touch(reservation)


def period_overlaps(employer_id, period_start, period_end):
    for invoice in db.employer_invoices.values():
        if invoice["employer_id"] != employer_id:
            continue
        if invoice["invoice_status"] == "VOID":
            continue
        existing_start = date.fromisoformat(invoice["period_start"])
        existing_end = date.fromisoformat(invoice["period_end"])
        if period_start <= existing_end and existing_start <= period_end:
            return True
    return False
