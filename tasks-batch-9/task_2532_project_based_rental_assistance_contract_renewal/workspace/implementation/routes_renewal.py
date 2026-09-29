"""Renewal cases: the two parallel tracks, rent approval, execution and the
opt-out cascade (PRD 3.2, 3.3, 3.6, 3.7)."""
from decimal import Decimal

from flask import Blueprint, g

from core import (
    ROLE_CA, ROLE_HFO, ROLE_OWNER, ROLE_PHA, add_months, clock_date,
    clock_date_str, create, days_between, fail, json_body, need_enum, need_int,
    need_str, parse_date, respond_object, rhu, touch,
)
import calcs
from guards import (
    body_fk, deny_transition, endpoint, eq_filter, list_response, own_case,
    own_contract, require_state, resolve,
)

bp = Blueprint("renewal", __name__)

ALL_ROLES = (ROLE_OWNER, ROLE_CA, ROLE_HFO, ROLE_PHA)


# --------------------------------------------------------------------------
# Opening a case inside the expiration calendar (PRD 3.2)
# --------------------------------------------------------------------------
@bp.post("/renewal-cases")
@endpoint(ROLE_OWNER)
def create_case():
    body = json_body()
    contract = body_fk(body, "contract_id", "contracts")
    if contract is not None:
        own_contract(contract)
    need_str(body, "contract_id")
    if contract["lifecycle_status"] in ("RENEWED", "EXPIRED_OPT_OUT"):
        deny_transition("The contract lifecycle is terminal.")
    for existing in calcs.cases_of_contract(contract["id"]):
        if existing["rent_track_status"] != "EXECUTED":
            fail("ERR_OPEN_RENEWAL_CASE_EXISTS",
                 "A renewal case whose rent track has not reached EXECUTED already exists.")
    if contract["lifecycle_status"] != "ACTIVE":
        deny_transition("A renewal case may only be opened on an ACTIVE contract.")
    opened = clock_date()
    expiration = parse_date(contract["expiration_date"])
    days = days_between(opened, expiration)
    if not (0 < days <= calcs.RENEWAL_WINDOW_DAYS):
        fail("ERR_OUTSIDE_RENEWAL_WINDOW",
             "The contract expiration is not inside the renewal window.")
    case = create("cases", {
        "contract_id": contract["id"],
        "rent_track_status": "TERMS_PENDING",
        "notice_track_status": "NOTICES_PENDING",
        "renewal_option": None,
        "adjustment_method": None,
        "opened_on_date": opened.isoformat(),
        "days_to_expiration_at_open": days,
        "rcs_required": False,
        "comparable_market_rent_cents": None,
        "ocaf_rent_per_unit_cents": None,
        "budget_rent_per_unit_cents": None,
        "approved_rent_per_unit_cents": None,
        "challenge_reviewer_user_id": None,
        "rents_approver_user_id": None,
        "opt_out_notice_id": None,
    })
    contract["lifecycle_status"] = "RENEWAL_PENDING"
    touch(contract)
    return respond_object(case, 201)


@bp.get("/renewal-cases/<case_id>")
@endpoint(*ALL_ROLES)
def read_case(case_id):
    return respond_object(resolve("cases", case_id), 200)


# --------------------------------------------------------------------------
# Electing the option and the adjustment method (PRD 3.3)
# --------------------------------------------------------------------------
@bp.post("/renewal-cases/<case_id>/select-option")
@endpoint(ROLE_OWNER)
def select_option(case_id):
    case = own_case(resolve("cases", case_id))
    body = json_body()
    option = need_enum(body, "renewal_option", calcs.RENEWAL_OPTIONS)
    require_state(case, "rent_track_status", "TERMS_PENDING")
    contract = calcs.contract_of_case(case)
    permitted = calcs.OPTION_TYPE_MATRIX.get(contract["contract_type"], ())
    if option not in permitted:
        fail("ERR_OPTION_NOT_PERMITTED_FOR_TYPE",
             "Renewal option %s is not permitted for contract type %s."
             % (option, contract["contract_type"]))
    case["renewal_option"] = option
    case["rent_track_status"] = "OPTION_SELECTED"
    calcs.recompute_rcs_required(case)
    calcs.recompute_case_candidate_rents(case)
    touch(case)
    return respond_object(case, 200)


@bp.post("/renewal-cases/<case_id>/elect-adjustment")
@endpoint(ROLE_OWNER)
def elect_adjustment(case_id):
    case = own_case(resolve("cases", case_id))
    body = json_body()
    method = need_enum(body, "adjustment_method", calcs.ADJUSTMENT_METHODS)
    if case["rent_track_status"] != "OPTION_SELECTED" or case["adjustment_method"] is not None:
        deny_transition("The adjustment method election is a one-shot act at OPTION_SELECTED.")
    if case["renewal_option"] == "OPTION_1_MARK_UP_TO_MARKET" and method != "OCAF":
        fail("ERR_ADJUSTMENT_METHOD_CONFLICT",
             "Mark-up-to-market admits the operating-cost adjustment factor only.")
    case["adjustment_method"] = method
    calcs.recompute_rcs_required(case)
    calcs.recompute_case_candidate_rents(case)
    touch(case)
    return respond_object(case, 200)


# --------------------------------------------------------------------------
# Approving the rents and executing (PRD 3.6)
# --------------------------------------------------------------------------
@bp.post("/renewal-cases/<case_id>/approve-rents")
@endpoint(ROLE_CA)
def approve_rents(case_id):
    case = resolve("cases", case_id)
    track = case["rent_track_status"]
    method = case["adjustment_method"]
    if track == "RCS_IN_PROGRESS":
        pass
    elif track == "OPTION_SELECTED" and case["rcs_required"] is False and method == "OCAF":
        pass
    else:
        deny_transition("Rents cannot be approved from rent track %s." % track)
    if case["rcs_required"]:
        accepted = [s for s in calcs.studies_of_case(case["id"]) if s["state"] == "ACCEPTED"]
        if not accepted:
            fail("ERR_RCS_NOT_ACCEPTED",
                 "This case requires a rent comparability study in state ACCEPTED.")
    if case["challenge_reviewer_user_id"] is not None \
            and case["challenge_reviewer_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The reviewer who challenged this case's study may not approve its rents.")
    market = case["comparable_market_rent_cents"]
    if method == "OCAF":
        candidate = case["ocaf_rent_per_unit_cents"]
        ceiling = market if case["rcs_required"] else None
        ceiling_error = "ERR_RENT_EXCEEDS_COMPARABLE"
    elif method == "BUDGET_BASED":
        candidate = case["budget_rent_per_unit_cents"]
        ceiling = None if market is None else rhu(calcs.BUDGET_RENT_CAP_PCT * Decimal(market))
        ceiling_error = "ERR_BUDGET_RENT_EXCEEDS_CAP"
    else:
        return deny_transition("No adjustment method has been elected.")
    if candidate is None:
        calcs.recompute_case_candidate_rents(case)
        candidate = (case["ocaf_rent_per_unit_cents"] if method == "OCAF"
                     else case["budget_rent_per_unit_cents"])
    if ceiling is not None and candidate > ceiling:
        fail(ceiling_error,
             "The candidate rent %d exceeds its ceiling of %d." % (candidate, ceiling))
    case["approved_rent_per_unit_cents"] = candidate
    case["rents_approver_user_id"] = g.user_id
    case["rent_track_status"] = "RENTS_APPROVED"
    touch(case)
    return respond_object(case, 200)


@bp.post("/renewal-cases/<case_id>/execute-renewal")
@endpoint(ROLE_CA)
def execute_renewal(case_id):
    case = resolve("cases", case_id)
    body = json_body()
    expected = need_int(body, "expected_contract_version")
    contract = calcs.contract_of_case(case)
    if expected != contract["version"]:
        fail("ERR_STALE_CONTRACT_VERSION",
             "expected_contract_version does not match the contract's current version.")
    if case["rent_track_status"] != "RENTS_APPROVED":
        deny_transition("Execution requires rent_track_status RENTS_APPROVED.")
    if case["notice_track_status"] != "RENEWAL_NOTICED":
        deny_transition("Execution requires notice_track_status RENEWAL_NOTICED.")
    if contract["lifecycle_status"] != "RENEWAL_PENDING":
        deny_transition("Execution requires contract lifecycle RENEWAL_PENDING.")
    approved = case["approved_rent_per_unit_cents"]
    new_expiration = add_months(parse_date(contract["expiration_date"]),
                                contract["term_months"]).isoformat()
    case["rent_track_status"] = "EXECUTED"
    touch(case)
    contract["contract_rent_per_unit_cents"] = approved
    contract["renewed_rent_per_unit_cents"] = approved
    contract["renewed_option"] = case["renewal_option"]
    contract["renewed_expiration_date"] = new_expiration
    contract["expiration_date"] = new_expiration
    contract["lifecycle_status"] = "RENEWED"
    touch(contract)
    return respond_object(case, 200)


# --------------------------------------------------------------------------
# The opt-out cascade (PRD 3.7)
# --------------------------------------------------------------------------
@bp.post("/renewal-cases/<case_id>/record-opt-out")
@endpoint(ROLE_OWNER)
def record_opt_out(case_id):
    case = own_case(resolve("cases", case_id))
    contract = calcs.contract_of_case(case)
    if case["notice_track_status"] != "NOTICES_PENDING":
        deny_transition("The opt-out is recorded from notice track NOTICES_PENDING.")
    if contract["lifecycle_status"] != "RENEWAL_PENDING":
        deny_transition("The contract lifecycle must be RENEWAL_PENDING.")
    notice = None
    for row in calcs.notices_of_case(case["id"]):
        if row["notice_type"] == "OPT_OUT_ONE_YEAR" and row["status"] == "ISSUED":
            notice = row
    if notice is None:
        fail("ERR_OPT_OUT_NOTICE_MISSING",
             "An ISSUED one-year opt-out notice is required on this case.")
    prop = calcs.property_of(contract)
    case["notice_track_status"] = "OPT_OUT_NOTICED"
    case["opt_out_notice_id"] = notice["id"]
    touch(case)
    contract["lifecycle_status"] = "OPT_OUT_PENDING"
    touch(contract)
    for household in calcs.households_of_property(prop["id"]):
        if household["status"] != "ACTIVE":
            continue
        household["status"] = "OPT_OUT_NOTICED"
        household["ev_eligible"] = True
        touch(household)
        standard, ttp, entitlement = calcs.enhanced_voucher_entitlement(case, prop, household)
        create("vouchers", {
            "tenant_id": household["id"],
            "renewal_case_id": case["id"],
            "state": "PENDING",
            "payment_standard_cents": standard,
            "ttp_snapshot_cents": ttp,
            "entitlement_cents": entitlement,
            "issuing_pha_user_id": None,
            "issued_on_date": None,
        })
    return respond_object(case, 200)


@bp.post("/renewal-cases/<case_id>/finalize-opt-out")
@endpoint(ROLE_CA)
def finalize_opt_out(case_id):
    case = resolve("cases", case_id)
    contract = calcs.contract_of_case(case)
    if case["notice_track_status"] != "OPT_OUT_NOTICED":
        deny_transition("Finalization requires notice track OPT_OUT_NOTICED.")
    if contract["lifecycle_status"] != "OPT_OUT_PENDING":
        deny_transition("The contract lifecycle must be OPT_OUT_PENDING.")
    notice = None
    if case["opt_out_notice_id"] is not None:
        notice = calcs.table("notices").get(case["opt_out_notice_id"])
    effective = parse_date(notice["effective_date"]) if notice else None
    if effective is None or clock_date() < effective:
        fail("ERR_OPT_OUT_NOTICE_PERIOD_INCOMPLETE",
             "The one-year opt-out notice period has not fully elapsed.")
    prop = calcs.property_of(contract)
    for household in calcs.households_of_property(prop["id"]):
        if household["status"] != "OPT_OUT_NOTICED":
            continue
        issued = [v for v in calcs.rows("vouchers")
                  if v["tenant_id"] == household["id"] and v["state"] == "ISSUED"]
        if not issued:
            fail("ERR_TENANT_VOUCHER_UNRESOLVED",
                 "Every noticed household must hold an ISSUED enhanced voucher.")
    case["notice_track_status"] = "OPT_OUT_FINALIZED"
    touch(case)
    contract["lifecycle_status"] = "EXPIRED_OPT_OUT"
    contract["hap_ledger_balance_cents"] = 0
    touch(contract)
    prop["released_unit_count"] = prop["released_unit_count"] + prop["units_under_hap_count"]
    prop["units_under_hap_count"] = 0
    touch(prop)
    return respond_object(case, 200)


# --------------------------------------------------------------------------
# Reverse-reachability reads
# --------------------------------------------------------------------------
@bp.get("/renewal-cases/<case_id>/rent-comparability-studies")
@endpoint(*ALL_ROLES)
def list_case_studies(case_id):
    case = resolve("cases", case_id)
    return list_response(eq_filter(calcs.studies_of_case(case["id"]), "state"))


@bp.get("/renewal-cases/<case_id>/tenant-notices")
@endpoint(*ALL_ROLES)
def list_case_notices(case_id):
    case = resolve("cases", case_id)
    items = eq_filter(calcs.notices_of_case(case["id"]), "notice_type")
    return list_response(eq_filter(items, "status"))


@bp.get("/renewal-cases/<case_id>/restructuring-determinations")
@endpoint(ROLE_OWNER, ROLE_CA, ROLE_HFO)
def list_case_determinations(case_id):
    case = resolve("cases", case_id)
    items = [d for d in calcs.rows("determinations") if d["renewal_case_id"] == case["id"]]
    return list_response(items)


@bp.get("/renewal-cases/<case_id>/enhanced-vouchers")
@endpoint(*ALL_ROLES)
def list_case_vouchers(case_id):
    case = resolve("cases", case_id)
    return list_response(eq_filter(calcs.vouchers_of_case(case["id"]), "state"))
