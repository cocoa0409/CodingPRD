"""Restructuring determinations (fork-join) and enhanced vouchers
(PRD 3.5 and 3.7)."""
from decimal import Decimal

from flask import Blueprint, g

from core import (
    ROLE_CA, ROLE_HFO, ROLE_OWNER, ROLE_PHA, clock_date_str, create, fail,
    json_body, need_str, respond_object, rhu, table, touch,
)
import calcs
from guards import (
    body_fk, deny_transition, endpoint, require_state, resolve,
)

bp = Blueprint("restructuring", __name__)

ALL_ROLES = (ROLE_OWNER, ROLE_CA, ROLE_HFO, ROLE_PHA)

BRANCH_OPTION = {
    "MUTM_ELIGIBLE": "OPTION_1_MARK_UP_TO_MARKET",
    "M2M_REFERRED": "OPTION_3_MARK_TO_MARKET",
}


def _snapshots(determination, case):
    contract = calcs.contract_of_case(case)
    prop = calcs.property_of(contract) if contract else None
    determination["market_rent_per_unit_cents"] = case["comparable_market_rent_cents"]
    determination["current_rent_per_unit_cents"] = (
        contract["contract_rent_per_unit_cents"] if contract else None)
    determination["fmr_per_unit_cents"] = prop["published_fmr_cents"] if prop else None
    return contract, prop


# --------------------------------------------------------------------------
# Restructuring determinations
# --------------------------------------------------------------------------
@bp.post("/restructuring-determinations")
@endpoint(ROLE_CA)
def create_determination():
    body = json_body()
    case = body_fk(body, "renewal_case_id", "cases")
    need_str(body, "renewal_case_id")
    determination = create("determinations", {
        "renewal_case_id": case["id"],
        "determination_state": "DRAFT",
        "market_rent_per_unit_cents": None,
        "current_rent_per_unit_cents": None,
        "fmr_per_unit_cents": None,
        "eligibility_reason_code": None,
        "post_restructure_rent_per_unit_cents": None,
        "approved_by_user_id": None,
    })
    _snapshots(determination, case)
    return respond_object(determination, 201)


@bp.get("/restructuring-determinations/<determination_id>")
@endpoint(ROLE_OWNER, ROLE_CA, ROLE_HFO)
def read_determination(determination_id):
    return respond_object(resolve("determinations", determination_id), 200)


@bp.post("/restructuring-determinations/<determination_id>/evaluate")
@endpoint(ROLE_CA)
def evaluate_determination(determination_id):
    determination = resolve("determinations", determination_id)
    require_state(determination, "determination_state", "DRAFT")
    case = table("cases").get(determination["renewal_case_id"])
    if case is None:
        deny_transition("The determination's renewal case is missing.")
    contract, prop = _snapshots(determination, case)
    if contract is None or prop is None:
        deny_transition("The determination cannot be evaluated without its contract chain.")
    state, reason = calcs.restructuring_eligibility(determination, contract, prop)
    determination["determination_state"] = state
    determination["eligibility_reason_code"] = reason
    touch(determination)
    return respond_object(determination, 200)


@bp.post("/restructuring-determinations/<determination_id>/approve")
@endpoint(ROLE_HFO)
def approve_determination(determination_id):
    determination = resolve("determinations", determination_id)
    require_state(determination, "determination_state", "MUTM_ELIGIBLE", "M2M_REFERRED")
    branch = determination["determination_state"]
    case = table("cases").get(determination["renewal_case_id"])
    required_option = BRANCH_OPTION[branch]
    if case is None or case["renewal_option"] != required_option:
        fail("ERR_MUTM_OPTION_MISMATCH",
             "Approving a %s determination requires renewal_option %s."
             % (branch, required_option))
    market = determination["market_rent_per_unit_cents"] or 0
    if branch == "MUTM_ELIGIBLE":
        rent = market
    else:
        rent = rhu(calcs.M2M_RENT_PCT_OF_MARKET * Decimal(market))
    determination["determination_state"] = "APPROVED"
    determination["approved_by_user_id"] = g.user_id
    determination["post_restructure_rent_per_unit_cents"] = rent
    touch(determination)
    case["ocaf_rent_per_unit_cents"] = rent
    touch(case)
    return respond_object(determination, 200)


# --------------------------------------------------------------------------
# Enhanced vouchers
# --------------------------------------------------------------------------
@bp.get("/enhanced-vouchers/<voucher_id>")
@endpoint(*ALL_ROLES)
def read_voucher(voucher_id):
    return respond_object(resolve("vouchers", voucher_id), 200)


@bp.post("/enhanced-vouchers/<voucher_id>/issue")
@endpoint(ROLE_PHA)
def issue_voucher(voucher_id):
    voucher = resolve("vouchers", voucher_id)
    require_state(voucher, "state", "PENDING")
    household = table("households").get(voucher["tenant_id"])
    if household is None or household["status"] != "OPT_OUT_NOTICED":
        deny_transition("The household must be in status OPT_OUT_NOTICED.")
    case = table("cases").get(voucher["renewal_case_id"])
    contract = calcs.contract_of_case(case) if case else None
    if contract is None or contract["lifecycle_status"] != "OPT_OUT_PENDING":
        deny_transition("The case's contract must be in lifecycle OPT_OUT_PENDING.")
    if not (voucher["entitlement_cents"] > 0):
        fail("ERR_NO_ENHANCEMENT_ENTITLEMENT",
             "A voucher with a zero enhancement entitlement cannot be issued.")
    voucher["state"] = "ISSUED"
    voucher["issuing_pha_user_id"] = g.user_id
    voucher["issued_on_date"] = clock_date_str()
    touch(voucher)
    household["status"] = "EV_ISSUED"
    touch(household)
    prop = table("properties").get(household["property_id"])
    if prop is not None:
        prop["units_under_hap_count"] = prop["units_under_hap_count"] - 1
        prop["enhanced_voucher_unit_count"] = prop["enhanced_voucher_unit_count"] + 1
        touch(prop)
    return respond_object(voucher, 200)


@bp.post("/enhanced-vouchers/<voucher_id>/rescind")
@endpoint(ROLE_PHA)
def rescind_voucher(voucher_id):
    voucher = resolve("vouchers", voucher_id)
    body = json_body()
    need_str(body, "reason")
    require_state(voucher, "state", "ISSUED")
    household = table("households").get(voucher["tenant_id"])
    if household is None or household["status"] != "EV_ISSUED":
        deny_transition("The household must still be in status EV_ISSUED.")
    voucher["state"] = "RESCINDED"
    touch(voucher)
    household["status"] = "OPT_OUT_NOTICED"
    touch(household)
    prop = table("properties").get(household["property_id"])
    if prop is not None:
        prop["enhanced_voucher_unit_count"] = prop["enhanced_voucher_unit_count"] - 1
        prop["units_under_hap_count"] = prop["units_under_hap_count"] + 1
        touch(prop)
    return respond_object(voucher, 200)
