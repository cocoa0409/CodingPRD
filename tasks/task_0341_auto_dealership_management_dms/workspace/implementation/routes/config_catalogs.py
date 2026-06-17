from flask import Blueprint

import db
import response
from middleware import require_roles
from routes.lookup import get_path
from services import serialize
from util import base_record, get_json_body, require_bool, require_enum, require_int, require_str

bp = Blueprint("config_catalogs", __name__)


# ---------------- LenderProgram ----------------
@bp.post("/lender-programs")
@require_roles("FinanceManager")
def create_lender_program():
    body = get_json_body()
    rec = base_record()
    rec.update({
        "lender_name": require_str(body, "lender_name"),
        "tier": require_enum(body, "tier", ("TIER_A", "TIER_B", "TIER_C", "TIER_D")),
        "buy_rate_bps": require_int(body, "buy_rate_bps", minimum=0),
        "max_markup_bps": require_int(body, "max_markup_bps", minimum=0),
        "max_ltv_bps": require_int(body, "max_ltv_bps", gt=0),
        "max_pti_bps": require_int(body, "max_pti_bps", gt=0),
        "max_term_months": require_int(body, "max_term_months", gt=0),
        "active": require_bool(body, "active", required=False, default=True),
    })
    db.lender_programs[rec["id"]] = rec
    return response.success(serialize.lender_program(rec), status=201)


@bp.get("/lender-programs/<lpid>")
@require_roles("FinanceManager", "SalesManager")
def get_lender_program(lpid):
    rec = get_path(db.lender_programs, lpid)
    return response.success(serialize.lender_program(rec))


# ---------------- FinanceProduct ----------------
@bp.post("/finance-products")
@require_roles("FinanceManager")
def create_finance_product():
    body = get_json_body()
    rec = base_record()
    rec.update({
        "code": require_str(body, "code"),
        "name": require_str(body, "name"),
        "cost_cents": require_int(body, "cost_cents", minimum=0),
        "max_retail_cents": require_int(body, "max_retail_cents", minimum=0),
        "taxable": require_bool(body, "taxable", required=False, default=False),
    })
    db.finance_products[rec["id"]] = rec
    return response.success(serialize.finance_product(rec), status=201)


@bp.get("/finance-products/<fpid>")
@require_roles("FinanceManager", "SalesManager")
def get_finance_product(fpid):
    rec = get_path(db.finance_products, fpid)
    return response.success(serialize.finance_product(rec))


# ---------------- OEMIncentive ----------------
@bp.post("/oem-incentives")
@require_roles("SalesManager", "FinanceManager")
def create_oem_incentive():
    body = get_json_body()
    rec = base_record()
    rec.update({
        "program_code": require_str(body, "program_code"),
        "rebate_cents": require_int(body, "rebate_cents", minimum=0),
        "eligible_condition": require_enum(body, "eligible_condition", ("NEW", "USED", "ANY")),
        "eligible_make": require_str(body, "eligible_make", required=False, default=None),
        "min_model_year": require_int(body, "min_model_year", required=False, default=None),
        "stackable_with_finance": require_bool(body, "stackable_with_finance", required=False, default=True),
        "active": require_bool(body, "active", required=False, default=True),
    })
    db.oem_incentives[rec["id"]] = rec
    return response.success(serialize.oem_incentive(rec), status=201)


@bp.get("/oem-incentives/<oid>")
@require_roles("SalesManager", "FinanceManager")
def get_oem_incentive(oid):
    rec = get_path(db.oem_incentives, oid)
    return response.success(serialize.oem_incentive(rec))
