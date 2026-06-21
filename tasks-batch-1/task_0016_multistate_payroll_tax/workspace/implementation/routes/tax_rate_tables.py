"""TaxRateTable endpoints (PlatformAdmin seeds; everyone reads)."""
from flask import Blueprint, request

import db
import response
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_roles
from services import serialize, pagination
from services import validation as V


bp = Blueprint("tax_rate_tables", __name__)


@bp.post("/tax-rate-tables")
@require_roles("PlatformAdmin")
def create_table():
    body = V.require_dict(request.get_json(silent=True) or {})
    jurisdiction = V.require_str(body, "jurisdiction")
    if jurisdiction not in V.JURISDICTIONS:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"jurisdiction must be one of {sorted(V.JURISDICTIONS)}")
    tax_year = V.require_int(body, "tax_year")
    filing_status = V.require_enum(body, "filing_status", V.FILING_STATUSES)
    brackets = body.get("brackets_json")
    if brackets is None or not isinstance(brackets, list):
        raise APIError(ERR_INVALID_REQUEST, 400, "brackets_json must be an array")
    for b in brackets:
        if not isinstance(b, dict):
            raise APIError(ERR_INVALID_REQUEST, 400, "bracket entries must be objects")
        # Permissive: only require key shapes the calculation expects.
        if "lower_cents" not in b or "rate_basis_points" not in b:
            raise APIError(ERR_INVALID_REQUEST, 400,
                           "bracket must have lower_cents and rate_basis_points")
    supplemental_bp = V.require_int(body, "supplemental_flat_basis_points")

    # "Insert or replace" semantics on (jurisdiction, tax_year, filing_status).
    existing_id = None
    for tid, t in db.tax_rate_tables.items():
        if (t["jurisdiction"] == jurisdiction
                and t["tax_year"] == tax_year
                and t["filing_status"] == filing_status):
            existing_id = tid
            break

    if existing_id:
        # Replace: keep id + created_at; overwrite payload.
        t = db.tax_rate_tables[existing_id]
        t["brackets_json"] = brackets
        t["supplemental_flat_basis_points"] = supplemental_bp
        return response.success_object(serialize.tax_rate_table(t), status=201)

    t = {
        "id": db.new_id(),
        "jurisdiction": jurisdiction,
        "tax_year": tax_year,
        "filing_status": filing_status,
        "brackets_json": brackets,
        "supplemental_flat_basis_points": supplemental_bp,
    }
    # TaxRateTable only carries id + created_at (no updated_at / version).
    t["created_at"] = db.now_utc()
    db.tax_rate_tables[t["id"]] = t
    return response.success_object(serialize.tax_rate_table(t), status=201)


@bp.get("/tax-rate-tables")
@require_roles("HRClerk", "PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin")
def list_tables():
    limit, offset = pagination.parse_limit_offset()
    jurisdiction = V.opt_str(request.args, "jurisdiction")
    raw_year = request.args.get("tax_year")
    tax_year = None
    if raw_year is not None:
        try:
            tax_year = int(raw_year)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 400, "tax_year must be an integer")
    filing_status = V.opt_enum(request.args, "filing_status", V.FILING_STATUSES)

    items = list(db.tax_rate_tables.values())
    if jurisdiction:
        items = [t for t in items if t["jurisdiction"] == jurisdiction]
    if tax_year is not None:
        items = [t for t in items if t["tax_year"] == tax_year]
    if filing_status:
        items = [t for t in items if t["filing_status"] == filing_status]

    page, total = pagination.slice_sorted(items, limit, offset)
    return response.success_array(
        [serialize.tax_rate_table(x) for x in page],
        limit=limit, offset=offset, total_count=total,
    )
