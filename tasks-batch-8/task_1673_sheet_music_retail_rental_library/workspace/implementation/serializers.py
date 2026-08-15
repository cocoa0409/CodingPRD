"""Entity serializers: exact output field sets and per-field formats.

Business loan/PO dates are ISO dates (day granularity, e.g. "2026-09-04");
perusal hold/ship fields are clock instants (e.g. "2026-08-29T00:00:00Z");
created_at/updated_at carry three fractional digits.
"""
from util import fmt_ts0, fmt_ts3
import services


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_ts3(rec["created_at"]),
        "updated_at": fmt_ts3(rec["updated_at"]),
        "version": rec["version"],
    }


def _day(d):
    return d.isoformat() if d is not None else None


def _instant(dt):
    return fmt_ts0(dt) if dt is not None else None


def ser_publisher(p):
    out = _common(p)
    out.update(
        {
            "name": p["name"],
            "rental_discount_pct": p["rental_discount_pct"],
            "allows_digital_perusal": p["allows_digital_perusal"],
            "print_only_rental": p["print_only_rental"],
            "out_of_print": p["out_of_print"],
            "status": p["status"],
        }
    )
    return out


def ser_work(w):
    out = _common(w)
    out.update(
        {
            "publisher_id": w["publisher_id"],
            "title": w["title"],
            "catalog_number": w["catalog_number"],
            "ensemble_tier": w["ensemble_tier"],
            "base_rental_rate_cents": w["base_rental_rate_cents"],
            "sale_price_cents": w["sale_price_cents"],
            "license_format": w["license_format"],
            "perusal_allowed": w["perusal_allowed"],
            "rights_class": w["rights_class"],
            "status": w["status"],
        }
    )
    return out


def ser_rental_set(s):
    out = _common(s)
    out.update(
        {
            "work_id": s["work_id"],
            "set_code": s["set_code"],
            "copy_count": s["copy_count"],
            "available_copy_count": services.compute_available_copy_count(s),
            "condition_grade": s["condition_grade"],
            "replacement_value_cents": s["replacement_value_cents"],
            "status": s["status"],
        }
    )
    return out


def ser_account(a):
    open_x, settled = services.compute_exposures(a["id"])
    out = _common(a)
    out.update(
        {
            "account_name": a["account_name"],
            "account_kind": a["account_kind"],
            "credit_tier": a["credit_tier"],
            "credit_limit_cents": a["credit_limit_cents"],
            "open_exposure_cents": open_x,
            "settled_exposure_cents": settled,
            "standing": a["standing"],
            "requires_purchase_order": a["requires_purchase_order"],
        }
    )
    return out


def ser_po(po):
    out = _common(po)
    out.update(
        {
            "account_id": po["account_id"],
            "po_number": po["po_number"],
            "authorized_amount_cents": po["authorized_amount_cents"],
            "encumbered_cents": services.compute_encumbered(po),
            "valid_from": _day(po["valid_from"]),
            "valid_until": _day(po["valid_until"]),
            "status": po["status"],
        }
    )
    return out


def ser_order(o):
    out = _common(o)
    out.update(
        {
            "account_id": o["account_id"],
            "rental_set_id": o["rental_set_id"],
            "purchase_order_id": o.get("purchase_order_id"),
            "fulfillment_format": o["fulfillment_format"],
            "copies_requested": o["copies_requested"],
            "checkout_date": _day(o["checkout_date"]),
            "due_date": _day(o["due_date"]),
            "loan_periods": o["loan_periods"],
            "estimated_fee_cents": o["estimated_fee_cents"],
            "final_fee_cents": o["final_fee_cents"],
            "renewal_count": o["renewal_count"],
            "prepayment_cents": o["prepayment_cents"],
            "status": o["status"],
        }
    )
    return out


def ser_line(ln):
    out = _common(ln)
    out.update(
        {
            "rental_order_id": ln["rental_order_id"],
            "copy_seq": ln["copy_seq"],
            "checkout_condition": ln["checkout_condition"],
            "return_condition": ln["return_condition"],
            "status": ln["status"],
        }
    )
    return out


def ser_report(r):
    out = _common(r)
    out.update(
        {
            "rental_line_id": r["rental_line_id"],
            "assessor_user_id": r["assessor_user_id"],
            "observed_grade": r["observed_grade"],
            "findings": r["findings"],
            "assessed_charge_cents": r["assessed_charge_cents"],
            "status": r["status"],
        }
    )
    return out


def ser_invoice(inv):
    out = _common(inv)
    out.update(
        {
            "rental_line_id": inv["rental_line_id"],
            "condition_report_id": inv["condition_report_id"],
            "account_id": inv["account_id"],
            "amount_cents": inv["amount_cents"],
            "issuer_user_id": inv["issuer_user_id"],
            "status": inv["status"],
        }
    )
    return out


def ser_perusal(p):
    out = _common(p)
    out.update(
        {
            "account_id": p["account_id"],
            "work_id": p["work_id"],
            "format": p["format"],
            "ship_date": _instant(p["ship_date"]),
            "return_due_date": _instant(p["return_due_date"]),
            "hold_start": _instant(p["hold_start"]),
            "hold_end": _instant(p["hold_end"]),
            "converted_target_kind": p["converted_target_kind"],
            "converted_target_id": p["converted_target_id"],
            "status": p["status"],
        }
    )
    return out


def ser_sale(s):
    out = _common(s)
    out.update(
        {
            "account_id": s["account_id"],
            "work_id": s["work_id"],
            "quantity": s["quantity"],
            "unit_price_cents": s["unit_price_cents"],
            "total_cents": s["total_cents"],
            "balance_due_cents": s["balance_due_cents"],
            "perusal_request_id": s["perusal_request_id"],
            "status": s["status"],
        }
    )
    return out


def ser_case(c):
    out = _common(c)
    out.update(
        {
            "account_id": c["account_id"],
            "work_id": c["work_id"],
            "venue_kind": c["venue_kind"],
            "question": c["question"],
            "determination": c["determination"],
            "decided_by_user_id": c["decided_by_user_id"],
            "status": c["status"],
        }
    )
    return out
