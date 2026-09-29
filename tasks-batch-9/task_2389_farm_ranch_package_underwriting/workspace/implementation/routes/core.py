"""Accounts, policies, the exposure schedule and the labor profile."""

from flask import Blueprint

import calc
import services
from auth import AGENT, ALL_ROLES, COMPLIANCE, authenticate, guard_account, is_agent, user_id
from db import by_created, fmt_datetime, new_row, now_dt, parse_date, store, today, touch
from errors import ApiError
from response import created, ok, ok_list, paginate
from validation import enum_filter, field, pagination, read_body, str_filter, validate

bp = Blueprint("core", __name__)

OPERATION_TYPES = ("CROP", "LIVESTOCK", "DAIRY", "RANCH", "MIXED")
UW_STATUSES = ("DRAFT", "RATED", "REFERRED", "BOUND", "DECLINED", "CANCELLED")
COMPLIANCE_STATUSES = ("NOT_INSPECTED", "RECS_OPEN", "RECS_OVERDUE", "SUSPENDED", "COMPLIANT")
ITEM_CLASSES = ("DWELLING", "FARM_STRUCTURE", "EQUIPMENT", "STORED_CROP", "HAY", "INPUTS")
VALUATION_BASES = ("RC", "ACV")
CONDITION_GRADES = ("A", "B", "C", "D")
ITEM_STATUSES = ("ACTIVE", "REMOVED")
SPECIES = ("CATTLE", "SWINE", "POULTRY", "SHEEP", "EQUINE")
LIMIT_BASES = ("PER_HEAD", "BLANKET")
PERIL_SCOPES = ("FULL_PERIL", "NAMED_PERIL", "CATASTROPHE_ONLY")
EXPOSURE_TYPES = ("GENERAL_FARM", "CUSTOM_FARMING", "AGRITOURISM", "ROADSIDE_STAND")

MIN_TERM_DAYS = 90


def _policy_and_account(policy_id):
    policy = services.require(store.policies, policy_id, "ERR_FARM_POLICY_NOT_FOUND")
    account = services.account_of_policy(policy)
    guard_account(account)
    return policy, account


def _guard_exposure_write(policy):
    services.guard_policy_open(policy)
    if policy["uw_status"] not in ("DRAFT", "RATED"):
        raise ApiError("ERR_POLICY_NOT_IN_DRAFT")


# -------------------------------------------------------------------- accounts

@bp.route("/farm-accounts", methods=["POST"])
def create_account():
    authenticate(AGENT)
    body = validate(read_body(), [
        field("legal_name", "string", required=True, minlen=1, maxlen=160),
        field("state_code", "string", required=True, minlen=2, maxlen=2, pattern=r"^[A-Z]{2}$"),
        field("county_name", "string", required=True, minlen=1, maxlen=60),
        field("cat_zone_code", "string", required=True, minlen=1, maxlen=24),
        field("acreage", "int", required=True, ge=1),
        field("operation_type", "string", required=True, enum=OPERATION_TYPES),
    ])
    row = new_row(
        agent_id=user_id(),
        legal_name=body["legal_name"],
        state_code=body["state_code"],
        county_name=body["county_name"],
        cat_zone_code=body["cat_zone_code"],
        acreage=body["acreage"],
        operation_type=body["operation_type"],
    )
    store.accounts[row["id"]] = row
    return created(row)


@bp.route("/farm-accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    authenticate(*ALL_ROLES)
    account = services.require(store.accounts, account_id, "ERR_FARM_ACCOUNT_NOT_FOUND")
    guard_account(account)
    return ok(account)


@bp.route("/farm-accounts", methods=["GET"])
def list_accounts():
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    agent_id = str_filter("agent_id")
    cat_zone_code = str_filter("cat_zone_code")
    operation_type = enum_filter("operation_type", OPERATION_TYPES)
    rows = [
        a for a in store.accounts.values()
        if (agent_id is None or a["agent_id"] == agent_id)
        and (cat_zone_code is None or a["cat_zone_code"] == cat_zone_code)
        and (operation_type is None or a["operation_type"] == operation_type)
        and (not is_agent() or a["agent_id"] == user_id())
    ]
    window, total = paginate(by_created(rows), limit, offset)
    return ok_list(window, limit, offset, total)


# -------------------------------------------------------------------- policies

@bp.route("/farm-policies", methods=["POST"])
def create_policy():
    authenticate(AGENT)
    body = validate(read_body(), [
        field("account_id", "string", required=True, minlen=1),
        field("term_start_date", "date", required=True),
        field("term_end_date", "date", required=True),
        field("deductible_cents", "int", required=True, ge=0),
    ])
    start = parse_date(body["term_start_date"])
    end = parse_date(body["term_end_date"])
    if end <= start or (end - start).days < MIN_TERM_DAYS:
        raise ApiError("ERR_INVALID_TERM_DATES")
    account = services.require(store.accounts, body["account_id"], "ERR_FARM_ACCOUNT_NOT_FOUND")
    guard_account(account)
    row = new_row(
        account_id=account["id"],
        term_start_date=body["term_start_date"],
        term_end_date=body["term_end_date"],
        deductible_cents=body["deductible_cents"],
        uw_status="DRAFT",
        compliance_status="NOT_INSPECTED",
        property_premium_cents=0,
        livestock_premium_cents=0,
        liability_premium_cents=0,
        endorsement_premium_cents=0,
        base_premium_cents=0,
        cat_load_cents=0,
        total_premium_cents=0,
        exposed_tiv_cents=0,
        rating_valuation_date=None,
        quote_expires_at=None,
        referred_at=None,
        referred_by_user_id=None,
        referral_reason_code=None,
        bound_at=None,
        bound_by_user_id=None,
        closure_reason=None,
    )
    row["_term_start"] = start
    row["_term_end"] = end
    store.policies[row["id"]] = row
    return created(row)


@bp.route("/farm-policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    authenticate(*ALL_ROLES)
    policy, _ = _policy_and_account(policy_id)
    return ok(policy)


@bp.route("/farm-policies", methods=["GET"])
def list_policies():
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    account_id = str_filter("account_id")
    uw_status = enum_filter("uw_status", UW_STATUSES)
    compliance_status = enum_filter("compliance_status", COMPLIANCE_STATUSES)
    rows = []
    for policy in store.policies.values():
        if account_id is not None and policy["account_id"] != account_id:
            continue
        if uw_status is not None and policy["uw_status"] != uw_status:
            continue
        if compliance_status is not None and policy["compliance_status"] != compliance_status:
            continue
        account = services.account_of_policy(policy)
        if is_agent() and (account is None or account["agent_id"] != user_id()):
            continue
        rows.append(policy)
    window, total = paginate(by_created(rows), limit, offset)
    return ok_list(window, limit, offset, total)


# ------------------------------------------------------------- scheduled items

def _check_peak_coupling(item_class, peak_value, start_month, end_month, stated_value):
    trio = (peak_value, start_month, end_month)
    if item_class in calc.SEASONAL_CLASSES:
        if any(v is None for v in trio):
            raise ApiError("ERR_PEAK_SEASON_FIELDS_REQUIRED")
        if peak_value < stated_value:
            raise ApiError("ERR_PEAK_SEASON_FIELDS_REQUIRED")
    elif any(v is not None for v in trio):
        raise ApiError("ERR_PEAK_SEASON_FIELDS_REQUIRED")


@bp.route("/farm-policies/<policy_id>/scheduled-items", methods=["POST"])
def create_scheduled_item(policy_id):
    authenticate(AGENT)
    body = validate(read_body(), [
        field("item_class", "string", required=True, enum=ITEM_CLASSES),
        field("description", "string", required=True, minlen=1, maxlen=160),
        field("valuation_basis", "string", required=True, enum=VALUATION_BASES),
        field("stated_value_cents", "int", required=True, gt=0),
        field("age_years", "int", required=True, ge=0, le=100),
        field("condition_grade", "string", required=True, enum=CONDITION_GRADES),
        field("peak_season_value_cents", "int", gt=0),
        field("peak_season_start_month", "int", ge=1, le=12),
        field("peak_season_end_month", "int", ge=1, le=12),
    ])
    policy, _ = _policy_and_account(policy_id)
    _guard_exposure_write(policy)
    _check_peak_coupling(
        body["item_class"],
        body.get("peak_season_value_cents"),
        body.get("peak_season_start_month"),
        body.get("peak_season_end_month"),
        body["stated_value_cents"],
    )
    row = new_row(
        policy_id=policy["id"],
        item_class=body["item_class"],
        description=body["description"],
        valuation_basis=body["valuation_basis"],
        stated_value_cents=body["stated_value_cents"],
        age_years=body["age_years"],
        condition_grade=body["condition_grade"],
        peak_season_value_cents=body.get("peak_season_value_cents"),
        peak_season_start_month=body.get("peak_season_start_month"),
        peak_season_end_month=body.get("peak_season_end_month"),
        insured_value_cents=0,
        valued_at=None,
        status="ACTIVE",
    )
    services.revalue_item(row, now_dt())
    store.scheduled_items[row["id"]] = row
    services.revert_if_rated(policy)
    return created(row)


@bp.route("/farm-policies/<policy_id>/scheduled-items", methods=["GET"])
def list_scheduled_items(policy_id):
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", ITEM_STATUSES)
    item_class = enum_filter("item_class", ITEM_CLASSES)
    policy, _ = _policy_and_account(policy_id)
    rows = [
        r for r in services.items_of_policy(policy["id"])
        if (status is None or r["status"] == status)
        and (item_class is None or r["item_class"] == item_class)
    ]
    window, total = paginate(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/scheduled-items/<item_id>", methods=["GET"])
def get_scheduled_item(item_id):
    authenticate(*ALL_ROLES)
    item = services.require(store.scheduled_items, item_id, "ERR_SCHEDULED_ITEM_NOT_FOUND")
    policy = store.policies.get(item["policy_id"])
    guard_account(services.account_of_policy(policy))
    return ok(item)


@bp.route("/scheduled-items/<item_id>", methods=["PATCH"])
def patch_scheduled_item(item_id):
    authenticate(AGENT)
    body = validate(read_body(), [
        field("valuation_basis", "string", enum=VALUATION_BASES),
        field("stated_value_cents", "int", gt=0),
        field("age_years", "int", ge=0, le=100),
        field("condition_grade", "string", enum=CONDITION_GRADES),
        field("status", "string", enum=ITEM_STATUSES),
        field("peak_season_value_cents", "int", gt=0, nullable=True),
        field("peak_season_start_month", "int", ge=1, le=12, nullable=True),
        field("peak_season_end_month", "int", ge=1, le=12, nullable=True),
    ])
    item = services.require(store.scheduled_items, item_id, "ERR_SCHEDULED_ITEM_NOT_FOUND")
    policy = store.policies.get(item["policy_id"])
    guard_account(services.account_of_policy(policy))
    _guard_exposure_write(policy)

    merged = dict(item)
    for key in (
        "valuation_basis", "stated_value_cents", "age_years", "condition_grade", "status",
        "peak_season_value_cents", "peak_season_start_month", "peak_season_end_month",
    ):
        if key in body:
            merged[key] = body[key]
    _check_peak_coupling(
        merged["item_class"],
        merged["peak_season_value_cents"],
        merged["peak_season_start_month"],
        merged["peak_season_end_month"],
        merged["stated_value_cents"],
    )
    for key in (
        "valuation_basis", "stated_value_cents", "age_years", "condition_grade", "status",
        "peak_season_value_cents", "peak_season_start_month", "peak_season_end_month",
    ):
        item[key] = merged[key]
    services.revalue_item(item, now_dt())
    touch(item)
    services.revert_if_rated(policy)
    return ok(item)


# ------------------------------------------------------------ livestock groups

@bp.route("/farm-policies/<policy_id>/livestock-groups", methods=["POST"])
def create_livestock_group(policy_id):
    authenticate(AGENT)
    body = validate(read_body(), [
        field("species", "string", required=True, enum=SPECIES),
        field("head_count", "int", required=True, ge=1),
        field("per_head_value_cents", "int", required=True, gt=0),
        field("limit_basis", "string", required=True, enum=LIMIT_BASES),
        field("blanket_limit_cents", "int", gt=0),
        field("peril_scope", "string", required=True, enum=PERIL_SCOPES),
    ])
    policy, _ = _policy_and_account(policy_id)
    _guard_exposure_write(policy)
    blanket = body.get("blanket_limit_cents")
    if body["limit_basis"] == "BLANKET" and blanket is None:
        raise ApiError("ERR_BLANKET_LIMIT_REQUIRED")
    if body["limit_basis"] == "PER_HEAD" and blanket is not None:
        raise ApiError("ERR_BLANKET_LIMIT_REQUIRED")
    row = new_row(
        policy_id=policy["id"],
        species=body["species"],
        head_count=body["head_count"],
        per_head_value_cents=body["per_head_value_cents"],
        limit_basis=body["limit_basis"],
        blanket_limit_cents=blanket,
        peril_scope=body["peril_scope"],
        covered_limit_cents=calc.livestock_covered_limit(
            body["limit_basis"], body["head_count"], body["per_head_value_cents"], blanket
        ),
    )
    store.livestock_groups[row["id"]] = row
    services.revert_if_rated(policy)
    return created(row)


@bp.route("/farm-policies/<policy_id>/livestock-groups", methods=["GET"])
def list_livestock_groups(policy_id):
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    species = enum_filter("species", SPECIES)
    policy, _ = _policy_and_account(policy_id)
    rows = [
        r for r in services.livestock_of_policy(policy["id"])
        if species is None or r["species"] == species
    ]
    window, total = paginate(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# --------------------------------------------------------- liability exposures

@bp.route("/farm-policies/<policy_id>/liability-exposures", methods=["POST"])
def create_liability_exposure(policy_id):
    authenticate(AGENT)
    body = validate(read_body(), [
        field("exposure_type", "string", required=True, enum=EXPOSURE_TYPES),
        field("annual_receipts_cents", "int", required=True, ge=0),
        field("annual_visitor_count", "int", ge=0),
    ])
    policy, account = _policy_and_account(policy_id)
    _guard_exposure_write(policy)
    visitors = body.get("annual_visitor_count")
    if body["exposure_type"] == "AGRITOURISM" and visitors is None:
        raise ApiError("ERR_VISITOR_COUNT_REQUIRED")
    if body["exposure_type"] != "AGRITOURISM" and visitors is not None:
        raise ApiError("ERR_VISITOR_COUNT_REQUIRED")
    row = new_row(
        policy_id=policy["id"],
        exposure_type=body["exposure_type"],
        annual_receipts_cents=body["annual_receipts_cents"],
        annual_visitor_count=visitors,
        exposure_premium_cents=calc.liability_exposure_premium(
            body["exposure_type"], body["annual_receipts_cents"], visitors, account["acreage"]
        ),
    )
    store.liability_exposures[row["id"]] = row
    services.revert_if_rated(policy)
    return created(row)


@bp.route("/farm-policies/<policy_id>/liability-exposures", methods=["GET"])
def list_liability_exposures(policy_id):
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    exposure_type = enum_filter("exposure_type", EXPOSURE_TYPES)
    policy, _ = _policy_and_account(policy_id)
    rows = [
        r for r in services.liability_of_policy(policy["id"])
        if exposure_type is None or r["exposure_type"] == exposure_type
    ]
    window, total = paginate(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# ------------------------------------------------------------- labor profiles

@bp.route("/farm-policies/<policy_id>/labor-profile", methods=["PUT"])
def upsert_labor_profile(policy_id):
    authenticate(AGENT)
    body = validate(read_body(), [
        field("full_time_count", "int", required=True, ge=0),
        field("seasonal_count", "int", required=True, ge=0),
        field("migrant_h2a_count", "int", required=True, ge=0),
        field("wc_carrier_name", "string", minlen=1),
        field("wc_policy_number", "string", minlen=1),
        field("wc_expiry_date", "date"),
    ])
    policy, _ = _policy_and_account(policy_id)
    services.guard_policy_open(policy)

    units = calc.labor_exposure_units(
        body["full_time_count"], body["seasonal_count"], body["migrant_h2a_count"]
    )
    wc_required = units >= calc.WC_REQUIRED_THRESHOLD
    profile = services.labor_profile_of_policy(policy["id"])
    is_new = profile is None
    if is_new:
        profile = new_row(policy_id=policy["id"])
        store.labor_profiles[profile["id"]] = profile
    profile["full_time_count"] = body["full_time_count"]
    profile["seasonal_count"] = body["seasonal_count"]
    profile["migrant_h2a_count"] = body["migrant_h2a_count"]
    profile["labor_exposure_units"] = units
    profile["wc_required"] = wc_required
    profile["wc_carrier_name"] = body.get("wc_carrier_name")
    profile["wc_policy_number"] = body.get("wc_policy_number")
    profile["wc_expiry_date"] = body.get("wc_expiry_date")
    profile["coordination_status"] = "PENDING_PROOF" if wc_required else "NOT_REQUIRED"
    profile["verified_at"] = None
    profile["verified_by_user_id"] = None
    if is_new:
        return created(profile)
    touch(profile)
    return ok(profile)


@bp.route("/farm-policies/<policy_id>/labor-profile", methods=["GET"])
def get_policy_labor_profile(policy_id):
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    policy, _ = _policy_and_account(policy_id)
    profile = services.labor_profile_of_policy(policy["id"])
    rows = [profile] if profile is not None else []
    window, total = paginate(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/labor-profiles/<profile_id>", methods=["GET"])
def get_labor_profile(profile_id):
    authenticate(*ALL_ROLES)
    profile = services.require(store.labor_profiles, profile_id, "ERR_LABOR_PROFILE_NOT_FOUND")
    policy = store.policies.get(profile["policy_id"])
    guard_account(services.account_of_policy(policy))
    return ok(profile)


@bp.route("/labor-profiles/<profile_id>/wc-verification", methods=["POST"])
def verify_wc(profile_id):
    user, _role = authenticate(COMPLIANCE)
    validate(read_body(), [field("note", "string", minlen=1)])
    profile = services.require(store.labor_profiles, profile_id, "ERR_LABOR_PROFILE_NOT_FOUND")
    if profile["coordination_status"] != "PENDING_PROOF":
        raise ApiError("ERR_WC_STATE_INVALID")
    if not (
        profile.get("wc_carrier_name")
        and profile.get("wc_policy_number")
        and profile.get("wc_expiry_date")
    ):
        raise ApiError("ERR_WC_PROOF_MISSING")
    expiry = parse_date(profile["wc_expiry_date"])
    if expiry is None or expiry < today():
        raise ApiError("ERR_WC_PROOF_EXPIRED")
    profile["coordination_status"] = "VERIFIED"
    profile["verified_at"] = fmt_datetime(now_dt())
    profile["verified_by_user_id"] = user
    touch(profile)
    return ok(profile)
