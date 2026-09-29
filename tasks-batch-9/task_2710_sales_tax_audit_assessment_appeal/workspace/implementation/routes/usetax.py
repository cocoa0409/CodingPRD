"""UseTaxPurchase endpoints (PRD 3.5)."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import bad, body, guard, opt_bool, opt_int, present, req_date, req_enum, req_id, req_int, req_str
from routes.common import ASSET_CLASSES, body_fk, one, path_get
from services import calc, derive

bp = Blueprint("usetax", __name__)


def _apportionment_inputs(data, current=None):
    """Reads the five optional treatment inputs, defaulting from `current`."""
    base = current or {}
    pct = opt_int(data, "in_state_usage_pct_bp", 0, 10000)
    if pct is None:
        pct = base.get("in_state_usage_pct_bp", 10000) if current else 10000
    elif pct < 1:
        bad("in_state_usage_pct_bp must be between 1 and 10000.")
    first_use = opt_bool(data, "first_use_outside_state", None)
    if first_use is None:
        first_use = base.get("first_use_outside_state", False) if current else False
    months = opt_int(data, "months_used_outside_state", 0, 600)
    if months is None:
        months = base.get("months_used_outside_state", 0) if current else 0
    fmv = None
    if present(data, "fair_market_value_at_entry_cents"):
        fmv = req_int(data, "fair_market_value_at_entry_cents", 1)
    elif current is not None:
        fmv = base.get("fair_market_value_at_entry_cents")
    paid = opt_int(data, "tax_paid_other_state_cents", 0)
    if paid is None:
        paid = base.get("tax_paid_other_state_cents", 0) if current else 0
    return pct, first_use, months, fmv, paid


def _write_amounts(rec, asset_class, pct, first_use, months, fmv, paid):
    if calc.needs_fmv(asset_class, first_use, months) and fmv is None:
        raise ApiError("ERR_CAPITAL_ASSET_FMV_REQUIRED")
    basis, gross, credit, due = calc.use_tax_row(
        asset_class, rec["purchase_price_cents"], pct, first_use, months, fmv, paid
    )
    rec["asset_class"] = asset_class
    rec["in_state_usage_pct_bp"] = pct
    rec["first_use_outside_state"] = bool(first_use)
    rec["months_used_outside_state"] = months
    rec["fair_market_value_at_entry_cents"] = fmv
    rec["tax_paid_other_state_cents"] = paid
    rec["taxable_basis_cents"] = basis
    rec["gross_use_tax_cents"] = gross
    rec["credit_applied_cents"] = credit
    rec["use_tax_due_cents"] = due
    return rec


@bp.post("/use-tax-purchases")
@guard("FieldAuditor")
def create_purchase():
    data = body()
    audit_id = req_id(data, "audit_id")
    vendor_name = req_str(data, "vendor_name", 1, None)
    invoice_date = req_date(data, "invoice_date")
    price = req_int(data, "purchase_price_cents", 1)
    asset_class = req_enum(data, "asset_class", ASSET_CLASSES)
    pct, first_use, months, fmv, paid = _apportionment_inputs(data)

    audit = body_fk("audits", audit_id)
    scope_start = db.parse_date(audit.get("scope_period_start"))
    scope_end = db.parse_date(audit.get("scope_period_end"))
    if scope_start is not None and (invoice_date < scope_start or invoice_date > scope_end):
        bad("invoice_date must fall inside the audit's scope period.")
    # PRD 3.5: "purchases may be neither created nor changed while the audit sits
    # in `REVIEW_COMPLETE`" -- that is the only state bar the PRD states.
    if audit["status"] == "REVIEW_COMPLETE":
        raise ApiError("ERR_INVALID_STATE")

    rec = db.new_record(
        {
            "audit_id": audit["id"],
            "vendor_name": vendor_name,
            "invoice_date": db.format_date(invoice_date),
            "purchase_price_cents": price,
            "asset_class": asset_class,
            "in_state_usage_pct_bp": pct,
            "first_use_outside_state": bool(first_use),
            "months_used_outside_state": months,
            "fair_market_value_at_entry_cents": fmv,
            "tax_paid_other_state_cents": paid,
            "taxable_basis_cents": 0,
            "gross_use_tax_cents": 0,
            "credit_applied_cents": 0,
            "use_tax_due_cents": 0,
            "reclassification_count": 0,
        }
    )
    _write_amounts(rec, asset_class, pct, first_use, months, fmv, paid)
    db.insert("use_tax_purchases", rec)
    derive.recompute_use_tax_deficiency(audit)
    derive.mark_projection_stale(audit)
    db.touch(audit)
    return one("use_tax_purchases", rec, 201)


@bp.get("/use-tax-purchases/<pid>")
@guard("FieldAuditor", "AuditSupervisor", "Taxpayer")
def read_purchase(pid):
    return one("use_tax_purchases", path_get("use_tax_purchases", pid))


@bp.post("/use-tax-purchases/<pid>/reclassify")
@guard("FieldAuditor")
def reclassify_purchase(pid):
    rec = path_get("use_tax_purchases", pid)
    data = body()
    asset_class = req_enum(data, "asset_class", ASSET_CLASSES)
    pct, first_use, months, fmv, paid = _apportionment_inputs(data, rec)

    audit = db.get("audits", rec["audit_id"])
    if audit is None or audit["status"] == "REVIEW_COMPLETE":
        raise ApiError("ERR_INVALID_STATE")

    _write_amounts(rec, asset_class, pct, first_use, months, fmv, paid)
    rec["reclassification_count"] = rec["reclassification_count"] + 1
    db.touch(rec)
    derive.recompute_use_tax_deficiency(audit)
    derive.mark_projection_stale(audit)
    db.touch(audit)
    return one("use_tax_purchases", rec)
