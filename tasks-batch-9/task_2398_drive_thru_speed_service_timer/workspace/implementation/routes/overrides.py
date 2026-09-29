"""Forecast overrides: propose, adjudicate, and put into force under the cap."""

from decimal import Decimal

from flask import Blueprint

from constants import ALL_ROLES, FO_SOURCES, FO_STATES, OVERRIDE_AGGREGATE_CAP
from db import base_row, db, dec, touch
from errors import fail
from middleware import authenticate, get_override, get_restaurant, require_not_frozen, scope
from response import ok
from routes.helpers import list_rows
from serialize import forecast_override as override_json
from services.rollup import recompute
from validation import (
    body_or_400,
    opt_num,
    q_enum,
    q_str,
    raw_body,
    req_dt,
    req_enum,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("overrides", __name__)


def _store_of(override):
    return db.restaurants.get(override["restaurant_id"])


@bp.route("/forecast-overrides", methods=["POST"])
def create_override():
    actor = authenticate(("Operator",))
    scope(actor, raw_body().get("restaurant_id"))
    body = body_or_400()

    restaurant_id = req_str(body, "restaurant_id")
    source = req_enum(body, "source", FO_SOURCES)
    effective_start_at = req_dt(body, "effective_start_at")
    effective_end_at = req_dt(body, "effective_end_at")
    delta = req_num(body, "projected_cars_delta_pct",
                    minimum=Decimal("-0.50"), maximum=Decimal("1.00"))
    relief_override = opt_num(body, "target_relief_pct_override",
                              minimum=Decimal("0"), maximum=Decimal("0.20"))
    expected_version = req_int(body, "expected_restaurant_version", minimum=0)

    restaurant = get_restaurant(restaurant_id)

    if expected_version != restaurant["version"]:
        fail("ERR_STALE_RESTAURANT_VERSION",
             "expected_restaurant_version %s does not match the store's current version %s"
             % (expected_version, restaurant["version"]))

    # No frozen gate here — proposing an override is one of the eight exemptions.

    if effective_end_at <= effective_start_at:
        fail("ERR_WINDOW_BOUNDS_INVALID", "effective_end_at must be after effective_start_at")

    row = base_row()
    row.update({
        "restaurant_id": restaurant_id,
        "source": source,
        "effective_start_at": effective_start_at,
        "effective_end_at": effective_end_at,
        "projected_cars_delta_pct": delta,
        "target_relief_pct_override": relief_override,
        "approved_by_user_id": None,
        "rejection_reason": None,
        "fo_state": "PROPOSED",
    })
    db.forecast_overrides[row["id"]] = row

    touch(restaurant)
    return ok(override_json(row), 201)


@bp.route("/forecast-overrides/<override_id>/approve", methods=["POST"])
def approve_override(override_id):
    actor = authenticate(("ProgramAdmin",))
    override = get_override(override_id)

    if override["fo_state"] != "PROPOSED":
        fail("ERR_INVALID_OVERRIDE_STATE",
             "approval requires fo_state PROPOSED, found %s" % override["fo_state"])

    override["fo_state"] = "APPROVED"
    override["approved_by_user_id"] = actor.user_id
    touch(override)
    return ok(override_json(override))


@bp.route("/forecast-overrides/<override_id>/reject", methods=["POST"])
def reject_override(override_id):
    authenticate(("ProgramAdmin",))
    override = get_override(override_id)
    body = body_or_400()
    reason = req_str(body, "rejection_reason")

    if override["fo_state"] != "PROPOSED":
        fail("ERR_INVALID_OVERRIDE_STATE",
             "rejection requires fo_state PROPOSED, found %s" % override["fo_state"])

    override["fo_state"] = "REJECTED"
    override["rejection_reason"] = reason
    override["approved_by_user_id"] = None
    touch(override)
    return ok(override_json(override))


@bp.route("/forecast-overrides/<override_id>/apply", methods=["POST"])
def apply_override(override_id):
    actor = authenticate(("Operator",))
    override = get_override(override_id)
    scope(actor, override["restaurant_id"])
    restaurant = _store_of(override)
    require_not_frozen(restaurant)

    if override["fo_state"] != "APPROVED":
        fail("ERR_INVALID_OVERRIDE_STATE",
             "putting into force requires fo_state APPROVED, found %s" % override["fo_state"])

    total = abs(dec(override["projected_cars_delta_pct"]))
    for row in db.forecast_overrides.values():
        if row["id"] == override["id"]:
            continue
        if row["restaurant_id"] != override["restaurant_id"]:
            continue
        if row["fo_state"] != "APPLIED":
            continue
        # Closed intervals; touching endpoints count as intersecting.
        if (row["effective_start_at"] <= override["effective_end_at"]
                and override["effective_start_at"] <= row["effective_end_at"]):
            total += abs(dec(row["projected_cars_delta_pct"]))
    if total > OVERRIDE_AGGREGATE_CAP:
        fail("ERR_OVERRIDE_AGGREGATE_CAP",
             "the aggregate projected delta across overlapping applied overrides would be %s"
             % total)

    override["fo_state"] = "APPLIED"
    touch(override)

    recompute(restaurant)
    return ok(override_json(override))


@bp.route("/forecast-overrides", methods=["GET"])
def list_overrides():
    authenticate(ALL_ROLES)
    return list_rows(db.forecast_overrides, override_json, (
        ("restaurant_id", q_str("restaurant_id")),
        ("fo_state", q_enum("fo_state", FO_STATES)),
        ("source", q_enum("source", FO_SOURCES)),
    ))


@bp.route("/forecast-overrides/<override_id>", methods=["GET"])
def read_override(override_id):
    authenticate(ALL_ROLES)
    return ok(override_json(get_override(override_id)))
