"""GuarantySale endpoints — PRD §3.8, §2.9 (OCC), §4."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response, array_response
from services import calculations as calc
from services.common import (
    serialize, get_json_body, require_string, require_nonneg_int,
    require_int,
)

bp = Blueprint("guaranty_sales", __name__)


@bp.post("/sba/guaranty-sales")
def create_guaranty_sale():
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    investor_user_id = require_string(body, "investor_user_id")
    # sold_principal_cents must equal guaranteed_amount_cents (PRD §3.8). That figure
    # is 0 before authorization, so 0 is a valid (non-negative) value here; the PRD
    # declares no strict-positive requirement for this field.
    sold_principal = require_nonneg_int(body, "sold_principal_cents")
    premium_bps = require_int(body, "premium_bps")
    # premium_bps constrained 0..1500 inclusive.
    if not (0 <= premium_bps <= 1500):
        raise errors.invalid_request("premium_bps must be between 0 and 1500")
    with db.LOCK:
        app = db.applications.get(application_id)
        if app is None:
            raise errors.invalid_request("application_id does not reference an existing Application")
        # business rule: sold_principal must equal guaranteed_amount_cents.
        if sold_principal != app["guaranteed_amount_cents"]:
            raise errors.err(errors.ERR_SALE_PRINCIPAL_MISMATCH, 422,
                             "sold_principal_cents must equal guaranteed_amount_cents")
        rec = db.init_record({
            "application_id": application_id,
            "lender_id": app["lender_id"],  # copied from Application
            "investor_user_id": investor_user_id,
            "sold_principal_cents": sold_principal,
            "premium_bps": premium_bps,
            "premium_cents": 0,
            "status": "OFFERED",
        })
        db.guaranty_sales[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/applications/<application_id>/guaranty-sales")
def list_app_guaranty_sales(application_id):
    user_id, role = get_user_context()
    require_roles(role, ["SbaOfficer", "LoanOfficer", "CreditApprover", "InvestorServicer"])
    from services.common import paginate, sort_by_created
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.not_found("Application not found")
        items = [s for s in db.guaranty_sales.values() if s["application_id"] == application_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/sba/guaranty-sales/<sale_id>/settle")
def settle_guaranty_sale(sale_id):
    user_id, role = get_user_context()
    require_roles(role, ["InvestorServicer"])
    body = get_json_body()
    # expected_application_version is a required input (PRD §2.9).
    if "expected_application_version" not in body or body["expected_application_version"] is None:
        raise errors.invalid_request("expected_application_version is required")
    expected = body["expected_application_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_application_version must be an integer")
    with db.LOCK:
        sale = db.guaranty_sales.get(sale_id)
        if sale is None:
            raise errors.not_found("GuarantySale not found")
        app = db.applications.get(sale["application_id"])
        # state precedence: sale OFFERED, else ERR_INVALID_STATE.
        if sale["status"] != "OFFERED":
            raise errors.invalid_state("GuarantySale is not OFFERED")
        # OCC check: stale expected_application_version -> 412.
        if expected != app["version"]:
            raise errors.err(errors.ERR_STALE_APPLICATION_VERSION, 412,
                             "expected_application_version does not match current version")
        # business precondition: app status AUTHORIZED/DISBURSING/CLOSED.
        if app["status"] not in ("AUTHORIZED", "DISBURSING", "CLOSED"):
            raise errors.err(errors.ERR_GUARANTY_NOT_SELLABLE, 409,
                             "Application status does not permit guaranty sale")
        # settle + cascades.
        sale["status"] = "SETTLED"
        sale["premium_cents"] = calc.secondary_market_premium(
            sale["sold_principal_cents"], sale["premium_bps"])
        db.touch(sale)
        app["guaranty_status"] = "SOLD"
        app["sold_guaranteed_principal_cents"] = sale["sold_principal_cents"]
        # touch() bumps version by one (the OCC increment per §2.9).
        db.touch(app)
        lender = db.lenders[sale["lender_id"]]
        lender["sold_guaranty_balance_cents"] += sale["sold_principal_cents"]
        db.touch(lender)
        return object_response(serialize(sale), 200)


@bp.post("/sba/guaranty-sales/<sale_id>/repurchase")
def repurchase_guaranty_sale(sale_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    with db.LOCK:
        sale = db.guaranty_sales.get(sale_id)
        if sale is None:
            raise errors.not_found("GuarantySale not found")
        app = db.applications.get(sale["application_id"])
        if sale["status"] != "SETTLED":
            raise errors.invalid_state("GuarantySale is not SETTLED")
        sale["status"] = "REPURCHASED"
        db.touch(sale)
        app["guaranty_status"] = "REPURCHASED"
        app["sold_guaranteed_principal_cents"] = 0
        db.touch(app)
        lender = db.lenders[sale["lender_id"]]
        lender["sold_guaranty_balance_cents"] -= sale["sold_principal_cents"]
        db.touch(lender)
        return object_response(serialize(sale), 200)
