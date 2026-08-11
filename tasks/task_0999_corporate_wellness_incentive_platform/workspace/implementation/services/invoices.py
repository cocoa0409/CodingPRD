"""VendorInvoice endpoints (PRD §3.8)."""
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import current_identity, require_roles
from response import success
from services import serializers
from services.common import (
    get_invoice_or_404, get_program_or_404, parse_body, require_fields,
    stamp_new, touch,
)

bp = Blueprint("invoices", __name__)


def _round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _terminated_date(enrollment):
    if enrollment["terminated_at"] is None:
        return None
    return date_type.fromisoformat(enrollment["terminated_at"][:10])


def _compute_lines(program, employer, period_start, period_end):
    """vendor_invoice_total (scaffold §1.3): per-line round-half-up BEFORE
    summation; total is the exact sum of rounded line amounts."""
    lines = []
    days_in_period = (period_end - period_start).days + 1  # inclusive end
    enrollments = sorted(
        (e for e in DB.enrollments.values() if e["program_id"] == program["id"]),
        key=lambda e: e["created_at"],
    )
    for enr in enrollments:
        status = enr["participation_status"]
        term_date = _terminated_date(enr) if status == "TERMINATED" else None
        if status in ("ACTIVE", "SUSPENDED"):
            pass
        elif status == "TERMINATED" and term_date is not None and term_date >= period_start:
            pass
        else:
            continue
        member_start = max(enr["_created_date"], period_start)
        member_end = min(term_date if status == "TERMINATED" else period_end, period_end)
        member_days = max(0, (member_end - member_start).days + 1)
        if member_days > 0:
            amount = _round_half_up_cents(
                Decimal(employer["pmpm_fee_cents"]) * member_days / days_in_period
            )
            lines.append({
                "line_type": "MEMBER_MONTH",
                "ref_id": enr["id"],
                "amount_cents": amount,
                "note": None,
            })
    enr_ids = {e["id"] for e in enrollments}
    referrals = sorted(
        (r for r in DB.referrals.values() if r["enrollment_id"] in enr_ids),
        key=lambda r: r["created_at"],
    )
    for ref in referrals:
        n = sum(
            1
            for d in ref["session_dates"]
            if period_start <= date_type.fromisoformat(d) <= period_end
        )
        if n > 0:
            lines.append({
                "line_type": "COACHING_SESSION",
                "ref_id": ref["id"],
                "amount_cents": n * employer["coaching_session_fee_cents"],
                "note": None,
            })
    return lines


@bp.post("/wellness/vendor-invoices")
@require_roles("VendorManager")
def create_invoice():
    body = parse_body()
    vals = require_fields(body, [
        ("program_id", "string", True),
        ("vendor_name", "string", True),
        ("period_start", "date", True),
        ("period_end", "date", True),
    ])
    program = get_program_or_404(vals["program_id"])
    if program["status"] == "DRAFT":
        raise ApiError(
            "ERR_PROGRAM_NOT_ACTIVE",
            "Invoice creation requires program status ACTIVE or CLOSED",
        )
    if program["status"] == "SETTLED":
        raise ApiError(
            "ERR_PROGRAM_ALREADY_SETTLED",
            "No new invoices against a SETTLED program",
        )
    period_start, period_end = vals["period_start"], vals["period_end"]
    if period_end < period_start:
        from errors import invalid

        raise invalid("period_end must be on or after period_start")
    employer = DB.employers[program["employer_id"]]
    lines = _compute_lines(program, employer, period_start, period_end)
    rec = stamp_new({
        "program_id": program["id"],
        "vendor_name": vals["vendor_name"],
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "line_items": lines,
        "total_cents": sum(line["amount_cents"] for line in lines),
        "submitted_by": None,
        "status": "DRAFT",
    })
    DB.invoices[rec["id"]] = rec
    return success(serializers.invoice(rec), status=201)


@bp.post("/wellness/vendor-invoices/<iid>/adjustments")
@require_roles("VendorManager")
def add_adjustment(iid):
    inv = get_invoice_or_404(iid)
    body = parse_body()
    vals = require_fields(body, [
        ("amount_cents", "int", True),
        ("note", "string", True),
    ])
    if inv["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVOICE_NOT_EDITABLE",
            "Adjustments are allowed only while the invoice is DRAFT",
        )
    inv["line_items"].append({
        "line_type": "ADJUSTMENT",
        "ref_id": None,
        "amount_cents": vals["amount_cents"],
        "note": vals["note"],
    })
    inv["total_cents"] = sum(line["amount_cents"] for line in inv["line_items"])
    touch(inv)
    return success(serializers.invoice(inv), status=201)


@bp.post("/wellness/vendor-invoices/<iid>/submit")
@require_roles("VendorManager")
def submit_invoice(iid):
    inv = get_invoice_or_404(iid)
    if inv["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a DRAFT invoice may be submitted"
        )
    user_id, _ = current_identity()
    inv["submitted_by"] = user_id
    inv["status"] = "SUBMITTED"
    touch(inv)
    return success(serializers.invoice(inv))


@bp.post("/wellness/vendor-invoices/<iid>/approve")
@require_roles("PlatformAdmin")
def approve_invoice(iid):
    inv = get_invoice_or_404(iid)
    body = parse_body()
    vals = require_fields(body, [("override_limit", "bool", False)])
    if inv["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a SUBMITTED invoice may be approved"
        )
    user_id, _ = current_identity()
    # segregation of duties (stage 7) precedes the fiscal guard (stage 11)
    if inv["submitted_by"] is not None and inv["submitted_by"] == user_id:
        raise ApiError(
            "ERR_SOD_VIOLATION",
            "The approver must differ from the operator who submitted the invoice",
        )
    program = DB.programs[inv["program_id"]]
    employer = DB.employers[program["employer_id"]]
    if (
        inv["total_cents"] > employer["invoice_approval_limit_cents"]
        and not vals.get("override_limit", False)
    ):
        raise ApiError(
            "ERR_INVOICE_EXCEEDS_LIMIT",
            "total_cents exceeds the employer approval limit; pass override_limit=true",
        )
    inv["status"] = "APPROVED"
    touch(inv)
    return success(serializers.invoice(inv))


@bp.post("/wellness/vendor-invoices/<iid>/pay")
@require_roles("PlatformAdmin")
def pay_invoice(iid):
    inv = get_invoice_or_404(iid)
    if inv["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an APPROVED invoice may be paid"
        )
    inv["status"] = "PAID"
    touch(inv)
    return success(serializers.invoice(inv))


@bp.post("/wellness/vendor-invoices/<iid>/dispute")
@require_roles("PlatformAdmin")
def dispute_invoice(iid):
    inv = get_invoice_or_404(iid)
    body = parse_body()
    require_fields(body, [("note", "string", True)])
    if inv["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a SUBMITTED invoice may be disputed"
        )
    inv["status"] = "DISPUTED"
    touch(inv)
    return success(serializers.invoice(inv))


@bp.post("/wellness/vendor-invoices/<iid>/revise")
@require_roles("VendorManager")
def revise_invoice(iid):
    inv = get_invoice_or_404(iid)
    if inv["status"] != "DISPUTED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a DISPUTED invoice may be revised"
        )
    inv["submitted_by"] = None
    inv["status"] = "DRAFT"
    touch(inv)
    return success(serializers.invoice(inv))
