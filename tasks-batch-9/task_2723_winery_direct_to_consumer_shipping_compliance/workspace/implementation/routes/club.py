"""Wine-club subscriptions, weather holds and the run scheduler (PRD 3.8)."""
from flask import Blueprint

import clock
import response
import validate
from errors import ApiError
from middleware import require, own_both, own_winery
from routes import common
from services import club_svc, derive, serialize, volume
from store import db, base_row, touch

bp = Blueprint("club", __name__)

CADENCES = ("MONTHLY", "QUARTERLY")
SUB_STATUSES = ("ACTIVE", "WEATHER_HELD", "SUSPENDED_COMPLIANCE")
HOLD_REASONS = ("WEATHER_HEAT", "WEATHER_FREEZE", "CONSUMER_REQUEST")


@bp.route("/dtc/club-subscriptions", methods=["POST"])
def create_subscription():
    uid, role = require("WineryOperator", "ComplianceOfficer")
    own_winery(uid, role, validate.raw_body().get("winery_id"))
    b = validate.body()
    consumer_id = validate.field_str(b, "consumer_id")
    winery_id = validate.field_str(b, "winery_id")
    cadence = validate.field_enum(b, "cadence", CADENCES)
    sku = validate.field_str(b, "sku")
    bottles = validate.field_int(b, "bottles_per_shipment", minimum=1)
    bottle_ml = validate.field_int(b, "bottle_ml", minimum=1)
    unit_price = validate.field_int(b, "unit_price_cents", minimum=0)
    next_raw, _next_date = validate.field_date(b, "next_run_date")
    allotment = validate.field_int(b, "annual_allotment", minimum=1)

    consumer = common.consumer(consumer_id)
    winery = common.winery(winery_id)

    if winery["status"] == "SUSPENDED":
        raise ApiError("ERR_WINERY_SUSPENDED",
                       "The winery is suspended; no subscription may be opened.")
    if volume.screening_tier(consumer) == "ELEVATED":
        raise ApiError("ERR_ELEVATED_RISK_REVIEW_REQUIRED",
                       "The consumer's screening tier is ELEVATED.")

    row = base_row()
    row.update({
        "consumer_id": consumer_id,
        "winery_id": winery_id,
        "cadence": cadence,
        "sku": sku,
        "bottles_per_shipment": bottles,
        "bottle_ml": bottle_ml,
        "unit_price_cents": unit_price,
        "next_run_date": next_raw,
        "status": "ACTIVE",
        "hold_start_date": None,
        "hold_release_date": None,
        "hold_reason": None,
        "last_hold_release_date": None,
        "missed_run_count": 0,
        "annual_allotment": allotment,
    })
    db.club_subscriptions[row["id"]] = row
    return response.obj(serialize.club_subscription(row), 201)


@bp.route("/dtc/club-subscriptions/<sid>", methods=["GET"])
def read_subscription(sid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "Consumer")
    sub = common.club_subscription(sid)
    own_both(uid, role, sub["winery_id"], sub["consumer_id"])
    return response.obj(serialize.club_subscription(sub))


@bp.route("/dtc/club-subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "Consumer")
    winery_id = common.scope_winery(common.arg("winery_id"), uid, role)
    consumer_id = common.scope_consumer(common.arg("consumer_id"), uid, role)
    status = validate.query_enum("status", SUB_STATUSES)
    rows = [s for s in db.club_subscriptions.values()
            if (winery_id is None or s["winery_id"] == winery_id)
            and (consumer_id is None or s["consumer_id"] == consumer_id)
            and (status is None or s["status"] == status)]
    return common.listing(rows, serialize.club_subscription)


@bp.route("/dtc/club-subscriptions/<sid>/weather-hold", methods=["POST"])
def weather_hold(sid):
    uid, role = require("WineryOperator", "ComplianceOfficer")
    sub = common.club_subscription(sid)
    own_winery(uid, role, sub["winery_id"])
    b = validate.body()
    start_raw, start = validate.field_date(b, "hold_start_date")
    release_raw, release = validate.field_date(b, "hold_release_date")
    reason = validate.field_enum(b, "hold_reason", HOLD_REASONS)

    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A weather hold is only available from ACTIVE.")
    if release <= start:
        raise ApiError("ERR_HOLD_WINDOW_CONFLICT",
                       "hold_release_date must be strictly after hold_start_date.")
    last = clock.parse_date(sub.get("last_hold_release_date"))
    if last is not None:
        earliest = clock.plus_days(last, club_svc.HOLD_BUFFER_DAYS)
        if start < earliest:
            raise ApiError("ERR_HOLD_WINDOW_CONFLICT",
                           "hold_start_date must be at least %d days after the previous release."
                           % club_svc.HOLD_BUFFER_DAYS)

    sub["status"] = "WEATHER_HELD"
    sub["hold_start_date"] = start_raw
    sub["hold_release_date"] = release_raw
    sub["hold_reason"] = reason
    touch(sub)
    return response.obj(serialize.club_subscription(sub))


@bp.route("/dtc/club-subscriptions/<sid>/release-hold", methods=["POST"])
def release_hold(sid):
    uid, role = require("WineryOperator", "ComplianceOfficer")
    sub = common.club_subscription(sid)
    own_winery(uid, role, sub["winery_id"])
    b = validate.body()
    reset = validate.field_bool(b, "reset_missed_runs", required=False, default=False)

    status = sub["status"]
    if status == "WEATHER_HELD":
        club_svc.release_hold_fields(sub)
        if reset:
            sub["missed_run_count"] = 0
        touch(sub)
    elif status == "SUSPENDED_COMPLIANCE":
        if role != "ComplianceOfficer":
            raise ApiError("ERR_COMPLIANCE_REINSTATE_FORBIDDEN",
                           "Compliance reinstatement is reserved to a ComplianceOfficer.")
        if not reset:
            validate.bad("reset_missed_runs must be true to reinstate a suspended subscription.")
        sub["status"] = "ACTIVE"
        sub["missed_run_count"] = 0
        sub["next_run_date"] = clock.date_iso(clock.today())
        touch(sub)
        winery = db.wineries.get(sub["winery_id"])
        if winery is not None:
            derive.bump_winery(winery)
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The subscription is already ACTIVE.")
    return response.obj(serialize.club_subscription(sub))


@bp.route("/dtc/club-runs", methods=["POST"])
def club_run():
    uid, role = require("WineryOperator", "ComplianceOfficer")
    own_winery(uid, role, validate.raw_body().get("winery_id"))
    b = validate.body()
    winery_id = validate.field_str(b, "winery_id")
    run_raw, run_date = validate.field_date(b, "run_date")
    winery = common.winery(winery_id)
    if winery["status"] == "SUSPENDED":
        raise ApiError("ERR_WINERY_SUSPENDED",
                       "The winery is suspended; the club run is blocked.")
    if run_date > clock.today():
        raise ApiError("ERR_RUN_DATE_IN_FUTURE",
                       "run_date may not fall after the logical clock date.")
    result = club_svc.run(winery, run_date)
    result["run_date"] = run_raw
    return response.obj(result)
