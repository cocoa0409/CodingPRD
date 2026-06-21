"""UseTaxAccrual endpoints (§3.8)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from middleware import require
from response import object_response, array_response
from services import common, serializers

bp = Blueprint("use_tax", __name__)

READ_ROLES = ["Seller", "PlatformAdmin", "TaxPreparer", "TaxApprover", "Auditor"]


@bp.post("/use-tax-accruals")
@require("Seller", "TaxPreparer")
def create_accrual():
    body = common.get_body()
    seller_id = common.require_str(body, "seller_id")
    jurisdiction_id = common.require_str(body, "jurisdiction_id")
    purchase_amount = common.require_number(body, "purchase_amount", minimum=0, exclusive_min=True)

    common.resolve_fk(db.sellers, seller_id, "seller_id")
    j = common.resolve_fk(db.tax_jurisdictions, jurisdiction_id, "jurisdiction_id")

    accrued = Decimal(str(purchase_amount)) * Decimal(str(j["combined_rate"]))
    accrued = accrued.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    rec = {
        "seller_id": seller_id,
        "jurisdiction_id": jurisdiction_id,
        "purchase_amount": purchase_amount,
        "accrued_use_tax": float(accrued),
        "status": "ACCRUED",
        "tax_return_id": None,
    }
    common.stamp_create(rec)
    db.use_tax_accruals[rec["id"]] = rec
    return object_response(serializers.use_tax_accrual(rec), 201)


@bp.get("/use-tax-accruals/<rec_id>")
@require(*READ_ROLES)
def get_accrual(rec_id):
    rec = common.get_or_404(db.use_tax_accruals, rec_id, "use-tax accrual")
    return object_response(serializers.use_tax_accrual(rec))


@bp.get("/use-tax-accruals")
@require(*READ_ROLES)
def list_accruals():
    records = list(db.use_tax_accruals.values())
    a = request.args
    if a.get("seller_id") is not None:
        records = [r for r in records if r["seller_id"] == a.get("seller_id")]
    if a.get("jurisdiction_id") is not None:
        records = [r for r in records if r["jurisdiction_id"] == a.get("jurisdiction_id")]
    if a.get("tax_return_id") is not None:
        records = [r for r in records if r["tax_return_id"] == a.get("tax_return_id")]
    items, limit, offset, total = common.paginate(records, serializers.use_tax_accrual)
    return array_response(items, limit, offset, total)
