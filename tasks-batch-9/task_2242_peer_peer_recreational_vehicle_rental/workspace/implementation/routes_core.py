"""Clock, participants, qualification evidence and the configuration catalogues."""

from flask import Blueprint

import calc
import enums
import serializers as ser
import services as svc
import validation as v
from envelope import list_response, object_response
from errors import fail
from store import clock_date, creation_order, db, iso, new_record, parse_date, parse_dt, touch
from web import paged, route

bp = Blueprint("core", __name__)


def _collection(name):
    return creation_order(list(getattr(db, name).values()))


# ------------------------------------------------------------------- clock -----
@route(bp, "/_clock/set_current_utc", ["POST"], ("PlatformAdmin",))
def set_clock(user_id, role):
    body = v.body()
    target = v.get_datetime(body, "to_iso8601")
    db.clock = parse_dt(target)
    return object_response({"current_utc": iso(db.clock)})


# ------------------------------------------------------------------ owners -----
@route(bp, "/owners", ["POST"], ("PlatformAdmin",))
def create_owner(user_id, role):
    body = v.body()
    display_name = v.get_str(body, "display_name", min_len=1, max_len=80)
    email = v.get_email(body, "email")
    payout_state_code = v.get_state_code(body, "payout_state_code")
    if any(o["email"] == email for o in db.owners.values()):
        fail("ERR_INVALID_REQUEST", "email is already registered to another owner.")
    owner = new_record(display_name=display_name, email=email,
                       payout_state_code=payout_state_code, status="ACTIVE",
                       owner_penalty_points=0, payout_balance_cents=0,
                       listed_listing_count=0)
    db.owners[owner["id"]] = owner
    return object_response(ser.dump("owner", owner), 201)


@route(bp, "/owners/<owner_id>", ["GET"], ("Owner", "PlatformAdmin", "ClaimsAdjuster"))
def get_owner(user_id, role, owner_id):
    owner = svc.lookup("owners", owner_id)
    if role == "Owner" and owner["id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "An owner may only read their own record.")
    return object_response(ser.dump("owner", owner))


@route(bp, "/owners/<owner_id>/penalty-adjustments", ["POST"], ("PlatformAdmin",))
def adjust_owner_points(user_id, role, owner_id):
    body = v.body()
    points_delta = v.get_int(body, "points_delta")
    v.get_str(body, "reason", min_len=1)
    owner = svc.lookup("owners", owner_id)
    svc.apply_owner_points(owner, points_delta)
    touch(owner)
    return object_response(ser.dump("owner", owner))


# ----------------------------------------------------------------- renters -----
@route(bp, "/renters", ["POST"], ("PlatformAdmin",))
def create_renter(user_id, role):
    body = v.body()
    display_name = v.get_str(body, "display_name", min_len=1, max_len=80)
    email = v.get_email(body, "email")
    date_of_birth = v.get_date(body, "date_of_birth")
    license_state_code = v.get_state_code(body, "license_state_code")
    if parse_date(date_of_birth) >= clock_date():
        fail("ERR_INVALID_REQUEST", "date_of_birth must fall before the current date.")
    if any(r["email"] == email for r in db.renters.values()):
        fail("ERR_INVALID_REQUEST", "email is already registered to another renter.")
    renter = new_record(display_name=display_name, email=email,
                        date_of_birth=date_of_birth,
                        license_state_code=license_state_code,
                        wallet_credit_cents=0, renter_penalty_points=0,
                        driving_record_points=0, driving_record_status="NONE",
                        towing_verified_tier="NONE")
    db.renters[renter["id"]] = renter
    return object_response(ser.dump("renter", renter), 201)


@route(bp, "/renters/<renter_id>", ["GET"], ("Renter", "PlatformAdmin", "ClaimsAdjuster"))
def get_renter(user_id, role, renter_id):
    renter = svc.lookup("renters", renter_id)
    if role == "Renter" and renter["id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "A renter may only read their own record.")
    calc.recompute_renter_qualification(renter)
    return object_response(ser.dump("renter", renter))


@route(bp, "/renters/<renter_id>/wallet-adjustments", ["POST"], ("PlatformAdmin",))
def adjust_wallet(user_id, role, renter_id):
    body = v.body()
    amount_cents_delta = v.get_int(body, "amount_cents_delta")
    v.get_str(body, "reason", min_len=1)
    renter = svc.lookup("renters", renter_id)
    if renter["wallet_credit_cents"] + amount_cents_delta < 0:
        fail("ERR_INSUFFICIENT_RENTER_FUNDS",
             "The adjustment would drive the wallet balance negative.")
    renter["wallet_credit_cents"] += amount_cents_delta
    touch(renter)
    return object_response(ser.dump("renter", renter))


@route(bp, "/renters/<renter_id>/penalty-adjustments", ["POST"], ("PlatformAdmin",))
def adjust_renter_points(user_id, role, renter_id):
    body = v.body()
    points_delta = v.get_int(body, "points_delta")
    v.get_str(body, "reason", min_len=1)
    renter = svc.lookup("renters", renter_id)
    renter["renter_penalty_points"] = max(
        0, renter["renter_penalty_points"] + points_delta)
    touch(renter)
    return object_response(ser.dump("renter", renter))


# --------------------------------------------------- renter qualifications -----
@route(bp, "/renter-qualifications", ["POST"], ("PlatformAdmin",))
def create_qualification(user_id, role):
    body = v.body()
    renter_id = v.get_str(body, "renter_id")
    check_type = v.get_enum(body, "check_type", enums.CHECK_TYPE)
    result = v.get_enum(body, "result", enums.QUALIFICATION_RESULT)
    violation_points = v.get_int(body, "violation_points", 0, 20, required=False, default=0)
    checked_at = v.get_datetime(body, "checked_at")
    expires_on = v.get_date(body, "expires_on")
    if check_type == "DRIVING_RECORD" and result not in enums.DRIVING_RESULTS:
        fail("ERR_INVALID_REQUEST", "result is not valid for a DRIVING_RECORD check.")
    if check_type == "TOWING_EXPERIENCE":
        if result not in enums.TOWING_RESULTS:
            fail("ERR_INVALID_REQUEST", "result is not valid for a TOWING_EXPERIENCE check.")
        if violation_points != 0:
            fail("ERR_INVALID_REQUEST",
                 "violation_points must be 0 on a TOWING_EXPERIENCE check.")
    renter = svc.lookup("renters", renter_id)
    record = new_record(with_version=False, renter_id=renter_id, check_type=check_type,
                        result=result, violation_points=violation_points,
                        checked_at=checked_at, expires_on=expires_on,
                        _checked_at=parse_dt(checked_at))
    db.renter_qualifications[record["id"]] = record
    calc.recompute_renter_qualification(renter)
    touch(renter)
    return object_response(ser.dump("renter_qualification", record), 201)


@route(bp, "/renter-qualifications/<qualification_id>", ["GET"],
       ("Renter", "PlatformAdmin", "ClaimsAdjuster"))
def get_qualification(user_id, role, qualification_id):
    record = svc.lookup("renter_qualifications", qualification_id)
    return object_response(ser.dump("renter_qualification", record))


@route(bp, "/renter-qualifications", ["GET"],
       ("Renter", "PlatformAdmin", "ClaimsAdjuster"))
def list_qualifications(user_id, role):
    limit, offset = v.pagination()
    renter_id = v.query_str("renter_id")
    check_type = v.query_enum("check_type", enums.CHECK_TYPE)
    rows = _collection("renter_qualifications")
    if renter_id is not None:
        rows = [r for r in rows if r["renter_id"] == renter_id]
    if check_type is not None:
        rows = [r for r in rows if r["check_type"] == check_type]
    return list_response(ser.dump_all("renter_qualification", paged(rows, limit, offset)),
                         limit, offset, len(rows))


# ------------------------------------------------------------ protection -------
@route(bp, "/protection-plans", ["POST"], ("PlatformAdmin",))
def create_plan(user_id, role):
    body = v.body()
    tier = v.get_enum(body, "tier", enums.PLAN_TIER)
    daily_premium_cents = v.get_int(body, "daily_premium_cents", 0)
    premium_pct_of_base_bp = v.get_int(body, "premium_pct_of_base_bp", 0, 5000)
    deductible_cents = v.get_int(body, "deductible_cents", 0)
    coverage_ceiling_cents = v.get_int(body, "coverage_ceiling_cents", 0)
    excluded_causes = v.get_str_array(body, "excluded_causes", enums.CAUSE_CODE)
    eligible_vehicle_classes = v.get_str_array(body, "eligible_vehicle_classes",
                                               enums.VEHICLE_CLASS, non_empty=True)
    if any(p["tier"] == tier for p in db.protection_plans.values()):
        fail("ERR_INVALID_REQUEST", "A protection plan already exists for that tier.")
    plan = new_record(tier=tier, daily_premium_cents=daily_premium_cents,
                      premium_pct_of_base_bp=premium_pct_of_base_bp,
                      deductible_cents=deductible_cents,
                      coverage_ceiling_cents=coverage_ceiling_cents,
                      excluded_causes=excluded_causes,
                      eligible_vehicle_classes=eligible_vehicle_classes)
    db.protection_plans[plan["id"]] = plan
    return object_response(ser.dump("protection_plan", plan), 201)


@route(bp, "/cancellation-policies", ["POST"], ("PlatformAdmin",))
def create_policy(user_id, role):
    body = v.body()
    tier = v.get_enum(body, "tier", enums.POLICY_TIER)
    full_refund_hours_before = v.get_int(body, "full_refund_hours_before", 0)
    partial_refund_pct_bp = v.get_int(body, "partial_refund_pct_bp", 0, 10000)
    renter_cancel_penalty_points = v.get_int(body, "renter_cancel_penalty_points", 0, 10)
    owner_cancel_penalty_points = v.get_int(body, "owner_cancel_penalty_points", 0, 12)
    owner_cancel_fee_bp = v.get_int(body, "owner_cancel_fee_bp", 0, 5000)
    if any(p["tier"] == tier for p in db.cancellation_policies.values()):
        fail("ERR_INVALID_REQUEST", "A cancellation policy already exists for that tier.")
    policy = new_record(tier=tier, full_refund_hours_before=full_refund_hours_before,
                        partial_refund_pct_bp=partial_refund_pct_bp,
                        renter_cancel_penalty_points=renter_cancel_penalty_points,
                        owner_cancel_penalty_points=owner_cancel_penalty_points,
                        owner_cancel_fee_bp=owner_cancel_fee_bp)
    db.cancellation_policies[policy["id"]] = policy
    return object_response(ser.dump("cancellation_policy", policy), 201)


# -------------------------------------------------------- pricing seasons ------
@route(bp, "/pricing-seasons", ["POST"], ("PlatformAdmin",))
def create_season(user_id, role):
    body = v.body()
    season_code = v.get_enum(body, "season_code", enums.SEASON_CODE)
    start_month_day = v.get_month_day(body, "start_month_day")
    end_month_day = v.get_month_day(body, "end_month_day")
    multiplier_bp = v.get_int(body, "multiplier_bp", 1000, 30000)
    if end_month_day < start_month_day:
        fail("ERR_INVALID_REQUEST",
             "end_month_day must not sort before start_month_day.")
    season = new_record(season_code=season_code, start_month_day=start_month_day,
                        end_month_day=end_month_day, multiplier_bp=multiplier_bp)
    db.pricing_seasons[season["id"]] = season
    return object_response(ser.dump("pricing_season", season), 201)


@route(bp, "/pricing-seasons", ["GET"], ("Owner", "PlatformAdmin"))
def list_seasons(user_id, role):
    limit, offset = v.pagination()
    season_code = v.query_enum("season_code", enums.SEASON_CODE)
    rows = _collection("pricing_seasons")
    if season_code is not None:
        rows = [r for r in rows if r["season_code"] == season_code]
    return list_response(ser.dump_all("pricing_season", paged(rows, limit, offset)),
                         limit, offset, len(rows))


# ------------------------------------------------------------ campgrounds ------
@route(bp, "/campgrounds", ["POST"], ("PlatformAdmin",))
def create_campground(user_id, role):
    body = v.body()
    name = v.get_str(body, "name", min_len=1, max_len=120)
    state_code = v.get_state_code(body, "state_code")
    max_rig_length_ft = v.get_int(body, "max_rig_length_ft", 10, 60)
    daily_dropoff_capacity = v.get_int(body, "daily_dropoff_capacity", 1)
    dropoff_buffer_minutes = v.get_int(body, "dropoff_buffer_minutes", 0, 240)
    status = v.get_enum(body, "status", enums.CAMPGROUND_STATUS, required=False,
                        default="ACCEPTING")
    campground = new_record(name=name, state_code=state_code,
                            max_rig_length_ft=max_rig_length_ft,
                            daily_dropoff_capacity=daily_dropoff_capacity,
                            dropoff_buffer_minutes=dropoff_buffer_minutes,
                            status=status, scheduled_assignment_count=0)
    db.campgrounds[campground["id"]] = campground
    return object_response(ser.dump("campground", campground), 201)


@route(bp, "/campgrounds/<campground_id>", ["GET"], ("Owner", "PlatformAdmin"))
def get_campground(user_id, role, campground_id):
    campground = svc.lookup("campgrounds", campground_id)
    return object_response(ser.dump("campground", campground))
