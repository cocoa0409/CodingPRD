"""Members, goodwill point adjustments and the point ledger."""

from flask import Blueprint, request

import db
import middleware
import support
import validate
from errors import ApiError
from middleware import ADMIN, AGENT, AUDITOR, MEMBER
from services import calc, derive

bp = Blueprint("members", __name__)


@bp.route("/loyalty/members", methods=["POST"])
def create_member():
    middleware.require(ADMIN, AGENT)
    payload = validate.body()
    email = validate.req_str(payload, "email", 1)
    full_name = validate.req_str(payload, "full_name", 1)
    enrollment_date = validate.opt_date(payload, "enrollment_date")
    if "@" not in email:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'email' must contain an at-sign.")
    for existing in db.store.members.values():
        if existing["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'email' must be unique across the programme.")
    if enrollment_date is None:
        enrollment = db.date_str(db.clock_date())
    else:
        enrollment = db.date_str(enrollment_date)

    record = {}
    db.stamp_full(record)
    record.update({
        "email": email,
        "full_name": full_name,
        "enrollment_date": enrollment,
        "elite_tier": "BASE",
        "qualifying_nights_ytd": 0,
        "qualifying_revenue_cents_ytd": 0,
        "point_balance": 0,
        "lifetime_points_earned": 0,
        "points_purchased_current_year": 0,
    })
    support.tail(record)
    db.store.members[record["id"]] = record
    return support.created(record)


@bp.route("/loyalty/members/<member_id>", methods=["GET"])
def get_member(member_id):
    caller = middleware.require(ADMIN, AUDITOR, AGENT, MEMBER)
    middleware.own_member(caller, member_id)
    return support.one(validate.get_member(member_id))


@bp.route("/loyalty/members", methods=["GET"])
def list_members():
    middleware.require(ADMIN, AUDITOR, AGENT)
    return support.listing(db.store.members.values(), ("elite_tier", "email"))


# ---------------------------------------------------------------------------
# goodwill adjustments
# ---------------------------------------------------------------------------

@bp.route("/loyalty/point-adjustments", methods=["POST"])
def create_adjustment():
    middleware.require(ADMIN, AGENT)
    payload = validate.body()
    member = validate.get_member(validate.fk(payload, "member_id"))
    points = validate.req_int(payload, "points")
    reason = validate.req_str(payload, "adjustment_reason", 1)
    expected_version = validate.req_int(payload, "expected_member_version")
    validate.non_zero("points", points)
    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION")
    if derive.fund_is_impaired():
        raise ApiError("ERR_FUND_IMPAIRED")

    entry = derive.add_entry(member["id"], "GOODWILL", points,
                            adjustment_reason=reason)
    derive.recompute_member(member)
    derive.recompute_fund()
    return support.created(entry)


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------

@bp.route("/loyalty/point-ledger-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    caller = middleware.require(ADMIN, AUDITOR, AGENT, MEMBER)
    entry = validate.get_entry(entry_id)
    middleware.own_member(caller, entry["member_id"])
    return support.one(entry)


@bp.route("/loyalty/point-ledger-entries", methods=["GET"])
def list_entries():
    caller = middleware.require(ADMIN, AUDITOR, AGENT, MEMBER)
    middleware.scope_filter(caller, request.args, hotel_key=None)
    extra = None
    if caller.is_member:
        extra = lambda r: r["member_id"] == caller.user_id
    return support.listing(
        db.store.ledger_entries.values(),
        ("member_id", "source_stay_id", "source_redemption_id", "source_purchase_id",
         "reversal_of_entry_id", "entry_type"),
        extra)
