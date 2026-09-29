"""Logical clock, owners, properties and HAP contracts (PRD 3.1)."""
from flask import Blueprint, g

from core import (
    CLOCK, ROLE_CA, ROLE_HFO, ROLE_OWNER, ROLE_PHA, bad_request, clock_date_str,
    create, fail, iso_ms, json_body, need_bool, need_date, need_enum, need_int,
    need_str, parse_instant, respond_object, rows, touch,
)
import calcs
from guards import (
    body_fk, endpoint, eq_filter, list_response, own_contract, own_property,
    resolve,
)

bp = Blueprint("portfolio", __name__)

ALL_ROLES = (ROLE_OWNER, ROLE_CA, ROLE_HFO, ROLE_PHA)


# --------------------------------------------------------------------------
# The logical clock (PRD 2.4)
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@endpoint(*ALL_ROLES)
def set_clock():
    body = json_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or not raw.strip():
        bad_request("Field 'to_iso8601' must be an ISO 8601 instant string.")
    moment = parse_instant(raw)
    if moment is None:
        bad_request("Field 'to_iso8601' must be a valid ISO 8601 instant.")
    CLOCK.value = moment
    return respond_object({"current_utc": iso_ms()}, 200)


# --------------------------------------------------------------------------
# Owners
# --------------------------------------------------------------------------
@bp.post("/owners")
@endpoint(ROLE_CA, ROLE_HFO)
def create_owner():
    body = json_body()
    legal_name = need_str(body, "legal_name")
    tin = need_str(body, "tin")
    contact_email = need_str(body, "contact_email")
    for existing in rows("owners"):
        if existing["tin"] == tin:
            fail("ERR_DUPLICATE_TIN", "An owner with this tin already exists.")
    owner = create("owners", {
        "legal_name": legal_name,
        "tin": tin,
        "contact_email": contact_email,
        "portfolio_property_count": 0,
        "compliance_flag": "OK",
    })
    return respond_object(owner, 201)


@bp.get("/owners/<owner_id>")
@endpoint(*ALL_ROLES)
def read_owner(owner_id):
    return respond_object(resolve("owners", owner_id), 200)


@bp.get("/owners/<owner_id>/properties")
@endpoint(*ALL_ROLES)
def list_owner_properties(owner_id):
    owner = resolve("owners", owner_id)
    items = [p for p in rows("properties") if p["owner_id"] == owner["id"]]
    return list_response(items)


# --------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------
@bp.post("/properties")
@endpoint(ROLE_OWNER)
def create_property():
    body = json_body()
    claimed = body.get("owner_id")
    if isinstance(claimed, str) and claimed.strip() and claimed != g.user_id:
        fail("ERR_NOT_PROPERTY_OWNER",
             "A property may only be registered under the acting owner-agent.")
    owner = body_fk(body, "owner_id", "owners")
    need_str(body, "owner_id")
    project_name = need_str(body, "project_name")
    state_code = need_enum(body, "state_code", calcs.STATE_CODES)
    total_units = need_int(body, "total_units", minimum=1)
    assisted = need_int(body, "assisted_unit_count", minimum=1)
    if assisted > total_units:
        bad_request("Field 'assisted_unit_count' may not exceed 'total_units'.")
    published_fmr = need_int(body, "published_fmr_cents", minimum=1)
    baseline_ua = need_int(body, "baseline_utility_allowance_cents", minimum=0)
    has_fha = need_bool(body, "has_fha_insured_mortgage", default=False)
    prop = create("properties", {
        "owner_id": owner["id"],
        "project_name": project_name,
        "state_code": state_code,
        "total_units": total_units,
        "assisted_unit_count": assisted,
        "published_fmr_cents": published_fmr,
        "baseline_utility_allowance_cents": baseline_ua,
        "current_utility_allowance_cents": baseline_ua,
        "has_fha_insured_mortgage": has_fha,
        "units_under_hap_count": assisted,
        "enhanced_voucher_unit_count": 0,
        "released_unit_count": 0,
        "last_applied_ua_effective_date": None,
    })
    owner["portfolio_property_count"] = owner["portfolio_property_count"] + 1
    touch(owner)
    return respond_object(prop, 201)


@bp.get("/properties/<property_id>")
@endpoint(*ALL_ROLES)
def read_property(property_id):
    return respond_object(resolve("properties", property_id), 200)


@bp.get("/properties/<property_id>/hap-contracts")
@endpoint(*ALL_ROLES)
def list_property_contracts(property_id):
    prop = resolve("properties", property_id)
    return list_response(calcs.contracts_of_property(prop["id"]))


@bp.get("/properties/<property_id>/tenant-households")
@endpoint(*ALL_ROLES)
def list_property_households(property_id):
    prop = resolve("properties", property_id)
    items = eq_filter(calcs.households_of_property(prop["id"]), "status")
    return list_response(items)


@bp.get("/properties/<property_id>/utility-allowance-analyses")
@endpoint(*ALL_ROLES)
def list_property_analyses(property_id):
    prop = resolve("properties", property_id)
    items = eq_filter(calcs.analyses_of_property(prop["id"]), "state")
    return list_response(items)


# --------------------------------------------------------------------------
# HAP contracts
# --------------------------------------------------------------------------
@bp.post("/hap-contracts")
@endpoint(ROLE_CA)
def create_contract():
    body = json_body()
    prop = body_fk(body, "property_id", "properties")
    need_str(body, "property_id")
    contract_type = need_enum(body, "contract_type", calcs.CONTRACT_TYPES)
    expiration_date = need_date(body, "expiration_date")
    term_months = need_int(body, "term_months", minimum=12)
    rent = need_int(body, "contract_rent_per_unit_cents", minimum=1)
    debt = need_int(body, "monthly_debt_service_per_unit_cents", minimum=0)
    opex = need_int(body, "operating_expense_per_unit_cents", minimum=0)
    reserve = need_int(body, "reserve_deposit_per_unit_cents", minimum=0)
    authorized = need_int(body, "authorized_hap_budget_cents", minimum=0)
    contract = create("contracts", {
        "property_id": prop["id"],
        "contract_type": contract_type,
        "expiration_date": expiration_date,
        "term_months": term_months,
        "contract_rent_per_unit_cents": rent,
        "monthly_debt_service_per_unit_cents": debt,
        "operating_expense_per_unit_cents": opex,
        "reserve_deposit_per_unit_cents": reserve,
        "authorized_hap_budget_cents": authorized,
        "paid_hap_total_cents": 0,
        "paid_claims_total_cents": 0,
        "hap_ledger_balance_cents": authorized,
        "lifecycle_status": "ACTIVE",
        "renewed_rent_per_unit_cents": None,
        "renewed_expiration_date": None,
        "renewed_option": None,
    })
    return respond_object(contract, 201)


@bp.get("/hap-contracts/<contract_id>")
@endpoint(*ALL_ROLES)
def read_contract(contract_id):
    return respond_object(resolve("contracts", contract_id), 200)


@bp.get("/hap-contracts/<contract_id>/renewal-cases")
@endpoint(*ALL_ROLES)
def list_contract_cases(contract_id):
    contract = resolve("contracts", contract_id)
    return list_response(calcs.cases_of_contract(contract["id"]))


@bp.get("/hap-contracts/<contract_id>/voucher-submissions")
@endpoint(*ALL_ROLES)
def list_contract_submissions(contract_id):
    contract = resolve("contracts", contract_id)
    items = eq_filter(calcs.submissions_of_contract(contract["id"]), "state")
    return list_response(items, sort_key=lambda r: (r["period_month"], r["_seq"]))


@bp.get("/hap-contracts/<contract_id>/special-claims")
@endpoint(*ALL_ROLES)
def list_contract_claims(contract_id):
    contract = resolve("contracts", contract_id)
    items = eq_filter(calcs.claims_of_contract(contract["id"]), "state")
    items = eq_filter(items, "claim_type")
    return list_response(items)


@bp.get("/hap-contracts/<contract_id>/reconciliation")
@endpoint(ROLE_OWNER, ROLE_CA, ROLE_HFO)
def contract_reconciliation(contract_id):
    contract = resolve("contracts", contract_id)
    return respond_object(calcs.subsidy_reconciliation(contract), 200)
