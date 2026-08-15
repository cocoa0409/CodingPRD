"""Rider endpoints: add, terminate, exercise, reads (PRD §3.10)."""
from datetime import date

from flask import Blueprint

import domain
import errors
from db import store
from middleware import require_auth, json_body, require_fields, ALL_ROLES
from response import ok_object
from routes.policies import get_policy_or_404, _paged
from services import calculations as calc
from services import engine

bp = Blueprint("riders", __name__)


def get_rider_or_404(policy, rid):
    rider = store.riders.get(rid)
    if rider is None or rider["policy_id"] != policy["id"]:
        raise errors.not_found(errors.ERR_RIDER_NOT_FOUND, "rider")
    return rider


@bp.route("/policies/<policy_id>/riders", methods=["POST"])
def create_rider(policy_id):
    require_auth(["Agent"])
    policy = get_policy_or_404(policy_id)
    if policy["form_status"] in domain.POLICY_FORM_TERMINAL:
        raise errors.already_terminal("Policy is in a terminal form state")
    if policy["form_status"] != "IN_FORCE":
        raise errors.incompatible_reference("Riders may only be added to an IN_FORCE policy")
    body = json_body(required=True)
    require_fields(body, ["rider_type", "rider_face_amount_cents"])
    rider_type = body["rider_type"]
    if rider_type not in domain.RIDER_TYPES:
        raise errors.invalid_request("invalid rider_type")
    face = body["rider_face_amount_cents"]
    if isinstance(face, bool) or not isinstance(face, int):
        raise errors.invalid_request("rider_face_amount_cents must be an integer")
    if rider_type in domain.ZERO_FACE_RIDER_TYPES and face != 0:
        raise errors.invalid_request(
            "rider_face_amount_cents must be 0 for %s" % rider_type)
    if face < 0:
        raise errors.invalid_request("rider_face_amount_cents must be >= 0")

    premium = calc.rider_monthly_premium(rider_type, face, policy)
    rider = domain.stamp_new({
        "policy_id": policy["id"],
        "rider_type": rider_type,
        "rider_face_amount_cents": face,
        "rider_monthly_premium_cents": premium,
        "status": "ACTIVE",
        "_cascade": None,
    })
    store.riders[rider["id"]] = rider
    return ok_object(domain.serialize_rider(rider), status=201)


@bp.route("/policies/<policy_id>/riders", methods=["GET"])
def list_riders(policy_id):
    require_auth(ALL_ROLES)
    policy = get_policy_or_404(policy_id)
    return _paged([r for r in store.riders.values() if r["policy_id"] == policy["id"]],
                  domain.serialize_rider)


def _unused_premium_refund(rider):
    """Pro-rated refund of the rider's monthly premium for the unused days of
    the current calendar month."""
    monthly = rider["rider_monthly_premium_cents"]
    if monthly <= 0:
        return 0
    today = store.current_date()
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    this_month = date(today.year, today.month, 1)
    days_in_month = (next_month - this_month).days
    days_remaining = max(0, (next_month - today).days)
    from util import dec, round_half_up
    return round_half_up(dec(monthly) * dec(days_remaining) / dec(days_in_month))


@bp.route("/policies/<policy_id>/riders/<rid>/terminate", methods=["POST"])
def terminate_rider(policy_id, rid):
    require_auth(["Agent"])
    policy = get_policy_or_404(policy_id)
    rider = get_rider_or_404(policy, rid)
    if rider["status"] in domain.RIDER_TERMINAL:
        raise errors.already_terminal("Rider is in a terminal state")
    rider["status"] = "TERMINATED"
    domain.touch(rider)
    refund = _unused_premium_refund(rider)
    if refund > 0:
        builds = domain.policy_builds_cash_value(policy)
        engine.post_ledger(policy, domain.ENTRY_RIDER_PREMIUM_DEBIT, -refund,
                           change_cents=(refund if builds else 0))
        domain.touch_policy(policy)
    return ok_object(domain.serialize_rider(rider))


@bp.route("/policies/<policy_id>/riders/<rid>/exercise", methods=["POST"])
def exercise_rider(policy_id, rid):
    require_auth(["Agent"])
    policy = get_policy_or_404(policy_id)
    rider = get_rider_or_404(policy, rid)
    if rider["status"] in domain.RIDER_TERMINAL:
        raise errors.already_terminal("Rider is in a terminal state")
    if rider["rider_type"] not in domain.EXERCISABLE_RIDER_TYPES:
        raise errors.invalid_request(
            "Only WAIVER_OF_PREMIUM and GUARANTEED_INSURABILITY riders can be exercised")
    if rider["rider_type"] == "WAIVER_OF_PREMIUM":
        if policy["premium_payment_status"] != "CURRENT":
            raise errors.invalid_state(
                "Waiver of premium requires premium_payment_status CURRENT")
        # Waive all current and future cycles while the rider stands EXERCISED
        for cycle in engine.policy_cycles(policy):
            if cycle["status"] in ("OPEN", "PARTIALLY_PAID", "GRACE"):
                cycle["status"] = "WAIVED"
                domain.touch(cycle)
    elif rider["rider_type"] == "GUARANTEED_INSURABILITY":
        if domain.policy_year_of(policy) < 3:
            raise errors.invalid_state(
                "Guaranteed insurability requires policy_year >= 3")
        policy["face_amount_cents"] += rider["rider_face_amount_cents"]
        domain.touch_policy(policy)
    rider["status"] = "EXERCISED"
    domain.touch(rider)
    return ok_object(domain.serialize_rider(rider))


# ---------------------------------------------------------------------------
# Flat filtered listings
# ---------------------------------------------------------------------------
@bp.route("/riders", methods=["GET"])
def list_all_riders():
    require_auth(ALL_ROLES)
    from flask import request
    records = list(store.riders.values())
    policy_id = request.args.get("policy_id")
    if policy_id is not None:
        records = [r for r in records if r["policy_id"] == policy_id]
    return _paged(records, domain.serialize_rider)


@bp.route("/riders/<row_id>", methods=["GET"])
def get_rider_flat(row_id):
    require_auth(ALL_ROLES)
    row = store.riders.get(row_id)
    if row is None:
        raise errors.not_found(errors.ERR_RIDER_NOT_FOUND, "rider")
    return ok_object(domain.serialize_rider(row))
