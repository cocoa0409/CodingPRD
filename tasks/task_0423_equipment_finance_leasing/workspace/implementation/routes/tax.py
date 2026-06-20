"""TaxAssessment endpoints — PRD §3.8, §4.

SALES_USE assessments are auto-generated on funding; PROPERTY assessments are
generated on demand by a Servicer.
"""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_roles, ALL_ROLES
from response import object_response, array_response
from services.common import (
    get_json_body, require_enum, serialize, paginate, sort_by_created,
)
from services import domain
from services import calculations as calc

bp = Blueprint("tax", __name__)

# Only PROPERTY may be generated on demand; SALES_USE is system-only (on funding).
ON_DEMAND_TAX_TYPES = {"PROPERTY"}


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/tax-assessments")
def create_tax_assessment(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        lease = domain.get_lease(lessor_id, lease_id)
        body = get_json_body()
        tax_type = require_enum(body, "tax_type", ON_DEMAND_TAX_TYPES)
        # PROPERTY base = sum of assessed_value over non-DISPOSED units.
        base = 0
        for u in domain.units_for_lease(lease_id):
            if u["status"] != "DISPOSED":
                base += domain.current_assessed_value(u, lessor)
        amount = calc.assessment_tax_amount(base, lessor["property_tax_rate_bps"])
        rec = db.init_record({
            "lessor_id": lessor_id,
            "lease_id": lease_id,
            "tax_type": "PROPERTY",
            "assessment_clock_utc": lessor["clock_utc"],
            "taxable_base_cents": base,
            "tax_amount_cents": amount,
            "status": "ASSESSED",
        })
        db.tax_assessments[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/lessors/<lessor_id>/tax-assessments/<tax_id>")
def get_tax_assessment(lessor_id, tax_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_tax_assessment(lessor_id, tax_id)
        return object_response(serialize(rec), 200)


@bp.get("/lessors/<lessor_id>/leases/<lease_id>/tax-assessments")
def list_tax_assessments(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        domain.get_lease(lessor_id, lease_id)
        items = [t for t in db.tax_assessments.values() if t["lease_id"] == lease_id]
        for key in ("tax_type", "status"):
            val = request.args.get(key)
            if val is not None and val != "":
                items = [t for t in items if t[key] == val]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/lessors/<lessor_id>/tax-assessments/<tax_id>/remit")
def remit_tax_assessment(lessor_id, tax_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_tax_assessment(lessor_id, tax_id)
        if rec["status"] != "ASSESSED":
            raise errors.invalid_state("Assessment is not ASSESSED")
        rec["status"] = "REMITTED"
        db.touch(rec)
        return object_response(serialize(rec), 200)
