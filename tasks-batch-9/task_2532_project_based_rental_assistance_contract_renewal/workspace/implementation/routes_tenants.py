"""Households, certifications, departures and statutory notices
(PRD 3.7 and 3.8)."""
from datetime import timedelta

from flask import Blueprint

from core import (
    ROLE_CA, ROLE_HFO, ROLE_OWNER, ROLE_PHA, bad_request, clock_date_str,
    create, fail, json_body, need_date, need_enum, need_int, need_str, opt_str,
    parse_date, respond_object, rows, table, touch,
)
import calcs
from guards import (
    body_fk, endpoint, eq_filter, list_response, own_case, own_household,
    own_notice, own_property, require_state, resolve,
)

bp = Blueprint("tenants", __name__)

ALL_ROLES = (ROLE_OWNER, ROLE_CA, ROLE_HFO, ROLE_PHA)


# --------------------------------------------------------------------------
# Households
# --------------------------------------------------------------------------
@bp.post("/tenant-households")
@endpoint(ROLE_OWNER)
def create_household():
    body = json_body()
    prop = body_fk(body, "property_id", "properties")
    if prop is not None:
        own_property(prop)
    need_str(body, "property_id")
    unit_number = need_str(body, "unit_number")
    household_name = need_str(body, "household_name")
    adjusted = need_int(body, "annual_adjusted_income_cents", minimum=0)
    gross = need_int(body, "annual_gross_income_cents", minimum=0)
    if gross < adjusted:
        bad_request("annual_gross_income_cents may not be lower than "
                    "annual_adjusted_income_cents.")
    family_size = need_int(body, "family_size", minimum=1)
    for existing in calcs.households_of_property(prop["id"]):
        if existing["unit_number"] == unit_number and existing["status"] != "MOVED_OUT":
            fail("ERR_DUPLICATE_UNIT_NUMBER",
                 "This unit number is already occupied at the property.")
    household = create("households", {
        "property_id": prop["id"],
        "unit_number": unit_number,
        "household_name": household_name,
        "annual_adjusted_income_cents": adjusted,
        "annual_gross_income_cents": gross,
        "family_size": family_size,
        "status": "ACTIVE",
        "move_out_date": None,
        "current_ttp_cents": None,
        "current_hap_cents": None,
        "ev_eligible": False,
    })
    return respond_object(household, 201)


@bp.get("/tenant-households/<household_id>")
@endpoint(*ALL_ROLES)
def read_household(household_id):
    return respond_object(resolve("households", household_id), 200)


@bp.post("/tenant-households/<household_id>/move-out")
@endpoint(ROLE_OWNER)
def move_out(household_id):
    household = own_household(resolve("households", household_id))
    body = json_body()
    move_out_date = need_date(body, "move_out_date")
    active = calcs.active_certification(household["id"])
    if active is not None \
            and parse_date(move_out_date) < parse_date(active["effective_date"]):
        bad_request("move_out_date may not be earlier than the ACTIVE "
                    "certification's effective_date.")
    require_state(household, "status", "ACTIVE", "EV_ISSUED")
    was_ev = household["status"] == "EV_ISSUED"
    household["status"] = "MOVED_OUT"
    household["move_out_date"] = move_out_date
    touch(household)
    prop = table("properties").get(household["property_id"])
    if prop is not None:
        prop["released_unit_count"] = prop["released_unit_count"] + 1
        if was_ev:
            prop["enhanced_voucher_unit_count"] = prop["enhanced_voucher_unit_count"] - 1
        else:
            prop["units_under_hap_count"] = prop["units_under_hap_count"] - 1
        touch(prop)
    return respond_object(household, 200)


@bp.get("/tenant-households/<household_id>/certifications")
@endpoint(*ALL_ROLES)
def list_household_certifications(household_id):
    household = resolve("households", household_id)
    items = eq_filter(calcs.certifications_of(household["id"]), "status")
    items = eq_filter(items, "cert_type")
    return list_response(items, sort_key=lambda r: (r["effective_date"], r["_seq"]))


@bp.get("/tenant-households/<household_id>/notices")
@endpoint(*ALL_ROLES)
def list_household_notices(household_id):
    household = resolve("households", household_id)
    items = [n for n in rows("notices") if n["tenant_id"] == household["id"]]
    return list_response(eq_filter(items, "status"))


@bp.get("/tenant-households/<household_id>/enhanced-vouchers")
@endpoint(*ALL_ROLES)
def list_household_vouchers(household_id):
    household = resolve("households", household_id)
    items = [v for v in rows("vouchers") if v["tenant_id"] == household["id"]]
    return list_response(eq_filter(items, "state"))


# --------------------------------------------------------------------------
# Certifications
# --------------------------------------------------------------------------
@bp.post("/tenant-certifications")
@endpoint(ROLE_OWNER)
def create_certification():
    body = json_body()
    household = body_fk(body, "tenant_id", "households")
    if household is not None:
        own_household(household)
    need_str(body, "tenant_id")
    cert_type = need_enum(body, "cert_type", calcs.CLIENT_CERT_TYPES)
    effective_date = need_date(body, "effective_date")
    expected = need_int(body, "expected_tenant_version")
    if expected != household["version"]:
        fail("ERR_STALE_TENANT_VERSION",
             "expected_tenant_version does not match the household's current version.")
    previous = calcs.active_certification(household["id"])
    if previous is not None:
        boundary = parse_date(previous["effective_date"]) \
            + timedelta(days=calcs.CERT_BUFFER_DAYS)
        if parse_date(effective_date) <= boundary:
            fail("ERR_CERT_INTERVAL_CONFLICT",
                 "A certification must take effect strictly more than %d days after "
                 "the ACTIVE certification." % calcs.CERT_BUFFER_DAYS)
    prop = table("properties").get(household["property_id"])
    allowance = prop["current_utility_allowance_cents"] if prop else 0
    contract = calcs.contract_of_property(household["property_id"])
    unit_rent = calcs.in_force_unit_rent(contract) if contract else 0
    money = calcs.tenant_rent_recalculation(household, allowance, unit_rent)
    certification = create("certifications", {
        "tenant_id": household["id"],
        "cert_type": cert_type,
        "effective_date": effective_date,
        "utility_allowance_cents": allowance,
        "contract_rent_per_unit_cents": unit_rent,
        "gross_rent_cents": money["gross_rent_cents"],
        "ttp_cents": money["ttp_cents"],
        "tenant_rent_cents": money["tenant_rent_cents"],
        "utility_reimbursement_cents": money["utility_reimbursement_cents"],
        "hap_cents": money["hap_cents"],
        "status": "ACTIVE",
    })
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        touch(previous)
    household["current_ttp_cents"] = money["ttp_cents"]
    household["current_hap_cents"] = money["hap_cents"]
    touch(household)
    return respond_object(certification, 201)


@bp.get("/tenant-certifications/<certification_id>")
@endpoint(*ALL_ROLES)
def read_certification(certification_id):
    return respond_object(resolve("certifications", certification_id), 200)


# --------------------------------------------------------------------------
# Notices
# --------------------------------------------------------------------------
@bp.post("/tenant-notices")
@endpoint(ROLE_OWNER)
def create_notice():
    body = json_body()
    case = body_fk(body, "renewal_case_id", "cases")
    if case is not None:
        own_case(case)
    household = body_fk(body, "tenant_id", "households")
    need_str(body, "renewal_case_id")
    notice_type = need_enum(body, "notice_type", calcs.NOTICE_TYPES)
    effective_date = need_date(body, "effective_date")
    opt_str(body, "tenant_id")
    issued_date = clock_date_str()
    lead_days, required, compliant = calcs.notice_window(
        issued_date, effective_date, notice_type)
    if not compliant:
        fail("ERR_NOTICE_WINDOW_NOT_MET",
             "The notice provides %d lead days but %d are required."
             % (lead_days, required))
    notice = create("notices", {
        "renewal_case_id": case["id"],
        "tenant_id": household["id"] if household else None,
        "notice_type": notice_type,
        "issued_date": issued_date,
        "effective_date": effective_date,
        "lead_days": lead_days,
        "required_lead_days": required,
        "status": "ISSUED",
        "rescind_reason": None,
    })
    if notice_type == "RENEWAL_INTENT" and case["notice_track_status"] == "NOTICES_PENDING":
        case["notice_track_status"] = "RENEWAL_NOTICED"
        touch(case)
    elif notice_type == "OPT_OUT_ONE_YEAR":
        case["opt_out_notice_id"] = notice["id"]
        touch(case)
    return respond_object(notice, 201)


@bp.get("/tenant-notices/<notice_id>")
@endpoint(*ALL_ROLES)
def read_notice(notice_id):
    return respond_object(resolve("notices", notice_id), 200)


@bp.post("/tenant-notices/<notice_id>/rescind")
@endpoint(ROLE_OWNER)
def rescind_notice(notice_id):
    notice = own_notice(resolve("notices", notice_id))
    body = json_body()
    reason = need_str(body, "reason")
    require_state(notice, "status", "ISSUED")
    case = table("cases").get(notice["renewal_case_id"])
    if notice["notice_type"] == "OPT_OUT_ONE_YEAR" and case is not None:
        for voucher in calcs.vouchers_of_case(case["id"]):
            if voucher["state"] == "ISSUED":
                fail("ERR_ENHANCED_VOUCHER_ISSUED_BLOCKS_RESCIND",
                     "An issued enhanced voucher blocks rescission of the opt-out notice.")
    notice["status"] = "RESCINDED"
    notice["rescind_reason"] = reason
    touch(notice)
    unwinds = (case is not None
               and case.get("opt_out_notice_id") == notice["id"]
               and case["notice_track_status"] == "OPT_OUT_NOTICED")
    if not unwinds:
        return respond_object(notice, 200)
    case["notice_track_status"] = "NOTICES_PENDING"
    case["opt_out_notice_id"] = None
    touch(case)
    contract = calcs.contract_of_case(case)
    if contract is not None and contract["lifecycle_status"] == "OPT_OUT_PENDING":
        contract["lifecycle_status"] = "RENEWAL_PENDING"
        touch(contract)
    prop = calcs.property_of(contract) if contract else None
    if prop is not None:
        for household in calcs.households_of_property(prop["id"]):
            if household["status"] != "OPT_OUT_NOTICED":
                continue
            household["status"] = "ACTIVE"
            household["ev_eligible"] = False
            touch(household)
    for voucher in calcs.vouchers_of_case(case["id"]):
        if voucher["state"] != "PENDING":
            continue
        voucher["state"] = "RESCINDED"
        touch(voucher)
    return respond_object(notice, 200)
