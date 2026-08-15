"""Routes: sites, staff, members, guardians, scholarship funds and awards."""

from flask import Blueprint, request

import db
from clock_util import CLOCK
from errors import err
from middleware import ALL_ROLES, authenticate, authorize
from response import success
from services import core, finance
from validators import get_body, reject_unknown, require_fields, parse_pagination, paginate

bp = Blueprint("core_ops", __name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _list_response(records, filters):
    for key, value in filters.items():
        if value is not None:
            records = [r for r in records if r.get(key) == value]
    limit, offset = parse_pagination()
    page, meta = paginate(records, limit, offset)
    return success(page, 200, is_list=True, pagination=meta)


def _validate_meal_rates(obj):
    if not isinstance(obj, dict):
        raise err("ERR_VALIDATION", "meal_rates_cents must be an object")
    for key in obj:
        if key not in core.MEAL_TYPES:
            raise err("ERR_VALIDATION", "unknown meal type in meal_rates_cents: %s" % key)
    for meal_type in core.MEAL_TYPES:
        if meal_type not in obj:
            raise err("ERR_VALIDATION", "meal_rates_cents missing meal type %s" % meal_type)
        rates = obj[meal_type]
        if not isinstance(rates, dict):
            raise err("ERR_VALIDATION", "meal_rates_cents[%s] must be an object" % meal_type)
        for key in rates:
            if key not in core.TIERS:
                raise err("ERR_VALIDATION", "unknown tier in meal_rates_cents[%s]: %s" % (meal_type, key))
        for tier in core.TIERS:
            if tier not in rates:
                raise err("ERR_VALIDATION", "meal_rates_cents[%s] missing tier %s" % (meal_type, tier))
            v = rates[tier]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise err("ERR_VALIDATION", "meal_rates_cents[%s][%s] must be a non-negative integer" % (meal_type, tier))


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

@bp.post("/sites")
def create_site():
    role, _ = _auth_any()
    authorize(role, ["PlatformAdmin"])
    body = get_body()
    reject_unknown(body, {"name", "youth_capacity", "standard_ratio", "elevated_ratio",
                          "base_weekly_fee_cents", "registration_fee_cents", "max_arrears_cents",
                          "meal_rates_cents", "fee_accrual_weekday"})
    vals = require_fields(body, {
        "name": {"type": "string", "required": True},
        "youth_capacity": {"type": "integer", "required": True, "positive": True},
        "standard_ratio": {"type": "integer", "required": True, "positive": True},
        "elevated_ratio": {"type": "integer", "required": True, "positive": True},
        "base_weekly_fee_cents": {"type": "integer", "required": True, "nonnegative": True},
        "registration_fee_cents": {"type": "integer", "required": True, "nonnegative": True},
        "max_arrears_cents": {"type": "integer", "required": True, "nonnegative": True},
        "meal_rates_cents": {"type": "object", "required": True},
        "fee_accrual_weekday": {"type": "integer", "required": False, "min": 1, "max": 7},
    })
    _validate_meal_rates(vals["meal_rates_cents"])
    now = db.now_iso()
    site = {
        "id": db.new_id(),
        "name": vals["name"],
        "youth_capacity": vals["youth_capacity"],
        "standard_ratio": vals["standard_ratio"],
        "elevated_ratio": vals["elevated_ratio"],
        "base_weekly_fee_cents": vals["base_weekly_fee_cents"],
        "registration_fee_cents": vals["registration_fee_cents"],
        "max_arrears_cents": vals["max_arrears_cents"],
        "meal_rates_cents": vals["meal_rates_cents"],
        "fee_accrual_weekday": vals.get("fee_accrual_weekday", 5),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("sites", site)
    return success(site, 201)


@bp.get("/sites/<site_id>")
def read_site(site_id):
    _auth_any()
    site = core.require("sites", site_id)
    return success(site, 200)


def _auth_any():
    role, user_id = authenticate()
    authorize(role, ALL_ROLES)
    request._role = role
    request._user_id = user_id
    return role, user_id


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

@bp.post("/staff")
def create_staff():
    role, _ = _auth_any()
    authorize(role, ["PlatformAdmin"])
    body = get_body()
    reject_unknown(body, {"site_id", "full_name", "position"})
    vals = require_fields(body, {
        "site_id": {"type": "string", "required": True},
        "full_name": {"type": "string", "required": True},
        "position": {"type": "string", "required": True, "enum": ["DIRECTOR", "FRONTLINE"]},
    })
    core.resolve_fk("sites", vals["site_id"])
    now = db.now_iso()
    staff = {
        "id": db.new_id(),
        "site_id": vals["site_id"],
        "full_name": vals["full_name"],
        "position": vals["position"],
        "status": "HIRED",
        "background_check_expires_at": None,
        "training_expires_at": None,
        "compliance_status": "INCOMPLETE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("staff", staff)
    return success(staff, 201)


@bp.get("/staff/<staff_id>")
def read_staff(staff_id):
    _auth_any()
    staff = core.require("staff", staff_id)
    return success(staff, 200)


@bp.get("/sites/<site_id>/staff")
def list_staff(site_id):
    _auth_any()
    core.require("sites", site_id)
    records = db.find("staff", site_id=site_id)
    filters = {
        "position": request.args.get("position"),
        "status": request.args.get("status"),
    }
    return _list_response(records, filters)


@bp.post("/staff/<staff_id>/credentials")
def post_credentials(staff_id):
    role, _ = _auth_any()
    authorize(role, ["PlatformAdmin"])
    staff = core.require("staff", staff_id)
    body = get_body()
    reject_unknown(body, {"kind", "expires_at"})
    vals = require_fields(body, {
        "kind": {"type": "string", "required": True, "enum": ["BACKGROUND_CHECK", "TRAINING"]},
        "expires_at": {"type": "string", "required": True, "datetime": True},
    })
    # Normalize the stored expiry to UTC ISO-8601 with milliseconds.
    expires_dt = core._parse_dt(vals["expires_at"])
    expires_iso = CLOCK.format(expires_dt)
    if vals["kind"] == "BACKGROUND_CHECK":
        staff["background_check_expires_at"] = expires_iso
    else:
        staff["training_expires_at"] = expires_iso
    staff["compliance_status"] = core.compute_compliance(staff)
    now = CLOCK.now()
    bg = staff["background_check_expires_at"]
    tr = staff["training_expires_at"]
    if staff["status"] == "HIRED" and bg is not None and tr is not None:
        if core._parse_dt(bg) >= now and core._parse_dt(tr) >= now:
            staff["status"] = "ACTIVE"
    db.touch(staff)
    if staff["compliance_status"] == "LAPSED":
        core.lapse_cascade(staff)
    return success(staff, 200)


@bp.get("/staff/<staff_id>/rotation-assignments")
def list_staff_rotations(staff_id):
    _auth_any()
    core.require("staff", staff_id)
    records = db.find("rotations", staff_id=staff_id)
    filters = {
        "club_day_id": request.args.get("club_day_id"),
        "status": request.args.get("status"),
    }
    return _list_response(records, filters)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@bp.post("/members")
def create_member():
    role, _ = _auth_any()
    authorize(role, ["SiteDirector", "FrontlineStaff"])
    body = get_body()
    reject_unknown(body, {"site_id", "legal_name", "date_of_birth", "grade",
                          "household_size", "household_income_cents", "walker_ok"})
    vals = require_fields(body, {
        "site_id": {"type": "string", "required": True},
        "legal_name": {"type": "string", "required": True},
        "date_of_birth": {"type": "string", "required": True, "date": True},
        "grade": {"type": "integer", "required": True, "min": 0, "max": 12},
        "household_size": {"type": "integer", "required": True, "positive": True},
        "household_income_cents": {"type": "integer", "required": True, "nonnegative": True},
        "walker_ok": {"type": "boolean", "required": False},
    })
    core.resolve_fk("sites", vals["site_id"])
    now = db.now_iso()
    member = {
        "id": db.new_id(),
        "site_id": vals["site_id"],
        "legal_name": vals["legal_name"],
        "date_of_birth": vals["date_of_birth"],
        "grade": vals["grade"],
        "household_size": vals["household_size"],
        "household_income_cents": vals["household_income_cents"],
        "walker_ok": vals.get("walker_ok", False),
        "status": "APPLIED",
        "eligibility_tier": None,
        "weekly_fee_cents": None,
        "fee_balance_cents": 0,
        "behavior_points": 0,
        "discipline_watch": False,
        "approved_at": None,
        "withdrawn_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("members", member)
    return success(member, 201)


@bp.get("/members/<member_id>")
def read_member(member_id):
    _auth_any()
    member = core.require("members", member_id)
    core.recompute_behavior_points(member)
    return success(member, 200)


@bp.get("/sites/<site_id>/members")
def list_members(site_id):
    _auth_any()
    core.require("sites", site_id)
    records = db.find("members", site_id=site_id)
    filters = {
        "status": request.args.get("status"),
        "eligibility_tier": request.args.get("eligibility_tier"),
    }
    return _list_response(records, filters)


@bp.post("/members/<member_id>/decide")
def decide_member(member_id):
    role, _ = _auth_any()
    authorize(role, ["SiteDirector"])
    member = core.require("members", member_id)
    body = get_body()
    reject_unknown(body, {"decision"})
    vals = require_fields(body, {
        "decision": {"type": "string", "required": True, "enum": ["APPROVE", "DENY"]},
    })
    if member["status"] != "APPLIED":
        raise err("ERR_MEMBER_NOT_APPLIED", "member is not in APPLIED status")
    if vals["decision"] == "DENY":
        member["status"] = "DENIED"
        db.touch(member)
        return success(member, 200)
    site = db.get("sites", member["site_id"])
    tier = finance.determine_eligibility_tier(member["household_size"], member["household_income_cents"])
    member["eligibility_tier"] = tier
    member["weekly_fee_cents"] = finance.gross_weekly_fee(site, tier)
    member["fee_balance_cents"] += site["registration_fee_cents"]
    member["approved_at"] = CLOCK.now_iso()
    member["status"] = "ACTIVE"
    db.touch(member)
    return success(member, 200)


@bp.post("/members/<member_id>/withdraw")
def withdraw_member(member_id):
    role, _ = _auth_any()
    authorize(role, ["SiteDirector"])
    member = core.require("members", member_id)
    get_body(allow_empty=True)
    if member["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_MEMBER_NOT_ACTIVE", "only ACTIVE or SUSPENDED members can be withdrawn")
    member["status"] = "WITHDRAWN"
    member["withdrawn_at"] = CLOCK.now_iso()
    db.touch(member)
    today = CLOCK.today()
    # Cascade: PENDING awards -> CANCELLED; ACTIVE awards -> REVOKED (fund release).
    for award in db.find("awards", member_id=member["id"]):
        if award["status"] == "PENDING":
            award["status"] = "CANCELLED"
            db.touch(award)
        elif award["status"] == "ACTIVE":
            award["status"] = "REVOKED"
            fund = db.get("funds", award["fund_id"])
            fund["reserved_cents"] -= award["remaining_cap_cents"]
            finance.recompute_fund_available(fund)
            db.touch(fund)
            db.touch(award)
    # Cascade: ACTIVE rides -> ENDED (no date rewrite).
    for ride in db.find("rides", member_id=member["id"]):
        if ride["status"] == "ACTIVE":
            ride["status"] = "ENDED"
            db.touch(ride)
    # Cascade: future SCHEDULED rotation assignments -> CANCELLED.
    affected_days = set()
    for ra in db.find("rotations", member_id=member["id"]):
        if ra["status"] != "SCHEDULED":
            continue
        day = db.get("club_days", ra["club_day_id"])
        if day is None or day["date"] < today:
            continue
        ra["status"] = "CANCELLED"
        db.touch(ra)
        affected_days.add(day["id"])
    for day_id in affected_days:
        core.recompute_posture(db.get("club_days", day_id))
    return success(member, 200)


@bp.post("/members/<member_id>/fee-payments")
def post_fee_payment(member_id):
    role, _ = _auth_any()
    authorize(role, ["SiteDirector"])
    member = core.require("members", member_id)
    body = get_body()
    reject_unknown(body, {"amount_cents", "expected_member_version"})
    vals = require_fields(body, {
        "amount_cents": {"type": "integer", "required": True, "positive": True},
        "expected_member_version": {"type": "integer", "required": True},
    })
    if vals["amount_cents"] > member["fee_balance_cents"]:
        raise err("ERR_OVERPAYMENT", "amount_cents exceeds fee_balance_cents")
    if vals["expected_member_version"] != member["version"]:
        raise err("ERR_STALE_VERSION", "member version has advanced")
    member["fee_balance_cents"] -= vals["amount_cents"]
    db.touch(member)
    return success(member, 200)


# ---------------------------------------------------------------------------
# Guardians
# ---------------------------------------------------------------------------

@bp.post("/guardians")
def create_guardian():
    role, _ = _auth_any()
    authorize(role, ["SiteDirector", "FrontlineStaff"])
    body = get_body()
    reject_unknown(body, {"member_id", "full_name", "relation", "phone"})
    vals = require_fields(body, {
        "member_id": {"type": "string", "required": True},
        "full_name": {"type": "string", "required": True},
        "relation": {"type": "string", "required": True},
        "phone": {"type": "string", "required": False},
    })
    member = core.resolve_fk("members", vals["member_id"])
    if member["status"] in ("DENIED", "WITHDRAWN"):
        raise err("ERR_MEMBER_NOT_ACTIVE", "guardians cannot be added for a terminal member")
    now = db.now_iso()
    guardian = {
        "id": db.new_id(),
        "member_id": vals["member_id"],
        "full_name": vals["full_name"],
        "relation": vals["relation"],
        "phone": vals.get("phone"),
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("guardians", guardian)
    return success(guardian, 201)


@bp.get("/members/<member_id>/guardians")
def list_guardians(member_id):
    _auth_any()
    core.require("members", member_id)
    records = db.find("guardians", member_id=member_id)
    filters = {"status": request.args.get("status")}
    return _list_response(records, filters)


@bp.post("/guardians/<guardian_id>/revoke")
def revoke_guardian(guardian_id):
    role, _ = _auth_any()
    authorize(role, ["SiteDirector", "FrontlineStaff"])
    guardian = core.require("guardians", guardian_id)
    get_body(allow_empty=True)
    if guardian["status"] != "ACTIVE":
        raise err("ERR_GUARDIAN_NOT_ACTIVE", "guardian is not ACTIVE")
    guardian["status"] = "REVOKED"
    db.touch(guardian)
    return success(guardian, 200)


# ---------------------------------------------------------------------------
# Scholarship funds
# ---------------------------------------------------------------------------

@bp.post("/scholarship-funds")
def create_fund():
    role, _ = _auth_any()
    authorize(role, ["PlatformAdmin"])
    body = get_body()
    reject_unknown(body, {"site_id", "name", "budget_cents"})
    vals = require_fields(body, {
        "site_id": {"type": "string", "required": True},
        "name": {"type": "string", "required": True},
        "budget_cents": {"type": "integer", "required": True, "positive": True},
    })
    core.resolve_fk("sites", vals["site_id"])
    now = db.now_iso()
    fund = {
        "id": db.new_id(),
        "site_id": vals["site_id"],
        "name": vals["name"],
        "budget_cents": vals["budget_cents"],
        "reserved_cents": 0,
        "disbursed_cents": 0,
        "available_cents": vals["budget_cents"],
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("funds", fund)
    return success(fund, 201)


@bp.get("/scholarship-funds/<fund_id>")
def read_fund(fund_id):
    _auth_any()
    fund = core.require("funds", fund_id)
    return success(fund, 200)


@bp.get("/sites/<site_id>/scholarship-funds")
def list_funds(site_id):
    _auth_any()
    core.require("sites", site_id)
    records = db.find("funds", site_id=site_id)
    filters = {"status": request.args.get("status")}
    return _list_response(records, filters)


@bp.post("/scholarship-funds/<fund_id>/close")
def close_fund(fund_id):
    role, _ = _auth_any()
    authorize(role, ["PlatformAdmin"])
    fund = core.require("funds", fund_id)
    get_body(allow_empty=True)
    if fund["status"] != "OPEN":
        raise err("ERR_FUND_NOT_OPEN", "fund is not OPEN")
    fund["status"] = "CLOSED"
    for award in db.find("awards", fund_id=fund["id"]):
        if award["status"] == "PENDING":
            award["status"] = "CANCELLED"
            db.touch(award)
    db.touch(fund)
    return success(fund, 200)


@bp.get("/scholarship-funds/<fund_id>/awards")
def list_fund_awards(fund_id):
    _auth_any()
    core.require("funds", fund_id)
    records = db.find("awards", fund_id=fund_id)
    filters = {"status": request.args.get("status")}
    return _list_response(records, filters)


# ---------------------------------------------------------------------------
# Scholarship awards
# ---------------------------------------------------------------------------

@bp.post("/scholarship-awards")
def create_award():
    role, _ = _auth_any()
    authorize(role, ["SiteDirector"])
    body = get_body()
    reject_unknown(body, {"fund_id", "member_id", "discount_pct", "weekly_cap_cents", "annual_cap_cents"})
    vals = require_fields(body, {
        "fund_id": {"type": "string", "required": True},
        "member_id": {"type": "string", "required": True},
        "discount_pct": {"type": "number", "required": True},
        "weekly_cap_cents": {"type": "integer", "required": True, "positive": True},
        "annual_cap_cents": {"type": "integer", "required": True, "positive": True},
    })
    # Body FK resolution in field order: fund_id, then member_id.
    fund = core.resolve_fk("funds", vals["fund_id"])
    member = core.resolve_fk("members", vals["member_id"])
    if not (vals["discount_pct"] > 0 and vals["discount_pct"] <= 1):
        raise err("ERR_VALIDATION", "discount_pct must be greater than 0 and at most 1")
    if member["status"] != "ACTIVE":
        raise err("ERR_MEMBER_NOT_ACTIVE", "award creation requires an ACTIVE member")
    if fund["status"] != "OPEN":
        raise err("ERR_FUND_NOT_OPEN", "award creation requires an OPEN fund")
    now = db.now_iso()
    award = {
        "id": db.new_id(),
        "fund_id": vals["fund_id"],
        "member_id": vals["member_id"],
        "discount_pct": vals["discount_pct"],
        "weekly_cap_cents": vals["weekly_cap_cents"],
        "annual_cap_cents": vals["annual_cap_cents"],
        "disbursed_cents": 0,
        "remaining_cap_cents": vals["annual_cap_cents"],
        "status": "PENDING",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("awards", award)
    return success(award, 201)


@bp.get("/members/<member_id>/scholarship-awards")
def list_member_awards(member_id):
    _auth_any()
    core.require("members", member_id)
    records = db.find("awards", member_id=member_id)
    filters = {"status": request.args.get("status")}
    return _list_response(records, filters)


@bp.post("/scholarship-awards/<award_id>/activate")
def activate_award(award_id):
    role, _ = _auth_any()
    authorize(role, ["SiteDirector"])
    award = core.require("awards", award_id)
    body = get_body()
    reject_unknown(body, {"expected_fund_version"})
    vals = require_fields(body, {
        "expected_fund_version": {"type": "integer", "required": True},
    })
    if award["status"] != "PENDING":
        raise err("ERR_AWARD_NOT_PENDING", "award is not PENDING")
    fund = db.get("funds", award["fund_id"])
    if fund["status"] != "OPEN":
        raise err("ERR_FUND_NOT_OPEN", "fund is not OPEN")
    if finance.fund_available(fund) < award["annual_cap_cents"]:
        raise err("ERR_FUND_INSUFFICIENT", "fund available_cents below annual_cap_cents")
    if vals["expected_fund_version"] != fund["version"]:
        raise err("ERR_STALE_VERSION", "fund version has advanced")
    fund["reserved_cents"] += award["annual_cap_cents"]
    finance.recompute_fund_available(fund)
    db.touch(fund)
    award["status"] = "ACTIVE"
    db.touch(award)
    return success(award, 200)


@bp.post("/scholarship-awards/<award_id>/revoke")
def revoke_award(award_id):
    role, _ = _auth_any()
    authorize(role, ["SiteDirector"])
    award = core.require("awards", award_id)
    get_body(allow_empty=True)
    if award["status"] != "ACTIVE":
        raise err("ERR_AWARD_NOT_ACTIVE", "award is not ACTIVE")
    fund = db.get("funds", award["fund_id"])
    fund["reserved_cents"] -= award["remaining_cap_cents"]
    finance.recompute_fund_available(fund)
    db.touch(fund)
    award["status"] = "REVOKED"
    db.touch(award)
    return success(award, 200)
