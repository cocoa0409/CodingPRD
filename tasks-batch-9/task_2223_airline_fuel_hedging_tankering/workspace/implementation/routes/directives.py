"""TankeringDirective disposition endpoints (PRD 3.8)."""

from flask import Blueprint, g

import calc
import domain
import fetch
import serializers as ser
import validators as v
from calc import r2
from db import db
from errors import fail
from middleware import (FUEL_ANALYST, FUEL_OPS_CONTROLLER, RISK_POLICY_ADMIN,
                        STATION_COORDINATOR, endpoint, touch)
from response import ok

bp = Blueprint("directives", __name__)


def _leg_of(directive):
    return db.legs.get(directive["flight_leg_id"])


def _require_status(directive, *allowed):
    if directive["status"] not in allowed:
        fail("ERR_DIRECTIVE_INVALID_STATE",
             "This transition is not declared from status %s." % directive["status"])


@bp.get("/fuel/tankering-directives/<directive_id>")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, FUEL_OPS_CONTROLLER, STATION_COORDINATOR)
def read_directive(directive_id):
    return ok(ser.directive(fetch.directive(directive_id)))


@bp.post("/fuel/tankering-directives/<directive_id>/approve")
@endpoint(FUEL_OPS_CONTROLLER)
def approve_directive(directive_id):
    directive = fetch.directive(directive_id)
    _require_status(directive, "PROPOSED")

    leg = _leg_of(directive)
    cap = domain.leg_uplift_cap(leg)
    if directive["requested_uplift_gallons"] > cap:
        fail("ERR_TANKERING_WEIGHT_LIMIT",
             "requested_uplift_gallons %s exceeds the leg's uplift cap of %s."
             % (directive["requested_uplift_gallons"], cap))

    origin_contract, destination_contract = domain.directive_contracts(leg)

    origin_station = db.stations.get(leg["origin_station_id"])
    _effective, _days, posture = domain.station_derived(origin_station)
    if posture == "SHORT":
        fail("ERR_STATION_INVENTORY_SHORT",
             "The origin station's supply posture is SHORT.")

    if directive["planned_net_savings_usd"] is None \
            or directive["planned_net_savings_usd"] <= 0:
        if not domain.has_approved_exception("TANKERING_UNECONOMIC",
                                            directive_id=directive["id"]):
            fail("ERR_TANKERING_NOT_ECONOMIC",
                 "planned_net_savings_usd is not strictly positive and no approved "
                 "TANKERING_UNECONOMIC exception references this directive.")

    directive["pinned_origin_price_usd_per_gal"] = domain.contract_all_in_price(origin_contract)
    directive["pinned_destination_price_usd_per_gal"] = domain.contract_all_in_price(
        destination_contract)
    directive["pinned_origin_contract_ref"] = origin_contract["contract_ref"]
    directive["status"] = "APPROVED"
    directive["approved_by_user_id"] = g.user_id
    touch(directive)
    return ok(ser.directive(directive))


@bp.post("/fuel/tankering-directives/<directive_id>/reject")
@endpoint(FUEL_OPS_CONTROLLER)
def reject_directive(directive_id):
    data = v.body()
    v.get_string(data, "reject_reason", min_len=1)

    directive = fetch.directive(directive_id)
    _require_status(directive, "PROPOSED")

    directive["status"] = "REJECTED"
    touch(directive)
    return ok(ser.directive(directive))


@bp.post("/fuel/tankering-directives/<directive_id>/request-revision")
@endpoint(FUEL_OPS_CONTROLLER)
def request_revision(directive_id):
    data = v.body()
    v.get_string(data, "revision_note", min_len=1)

    directive = fetch.directive(directive_id)
    _require_status(directive, "PROPOSED")

    directive["status"] = "NEEDS_REVISION"
    touch(directive)
    return ok(ser.directive(directive))


@bp.post("/fuel/tankering-directives/<directive_id>/revise")
@endpoint(FUEL_ANALYST)
def revise_directive(directive_id):
    data = v.body()
    uplift = v.get_number(data, "requested_uplift_gallons")

    directive = fetch.directive(directive_id)
    _require_status(directive, "NEEDS_REVISION")

    if uplift <= 0:
        fail("ERR_ZERO_UPLIFT", "requested_uplift_gallons must be greater than zero.")

    leg = _leg_of(directive)
    origin_contract, destination_contract = domain.directive_contracts(leg)

    directive["requested_uplift_gallons"] = uplift
    domain.apply_planned_basis(directive, leg, origin_contract, destination_contract)
    directive["status"] = "PROPOSED"
    directive["revision_count"] = directive["revision_count"] + 1
    touch(directive)
    return ok(ser.directive(directive))


@bp.post("/fuel/tankering-directives/<directive_id>/execute")
@endpoint(FUEL_OPS_CONTROLLER)
def execute_directive(directive_id):
    directive = fetch.directive(directive_id)
    _require_status(directive, "APPROVED")

    leg = _leg_of(directive)
    station = db.stations.get(leg["origin_station_id"])
    uplift = directive["requested_uplift_gallons"]
    if station is None or station["inventory_gallons"] < uplift:
        fail("ERR_STATION_INVENTORY_SHORT",
             "The origin station does not hold enough airline-owned gallons to load "
             "this uplift.")

    station["inventory_gallons"] = r2(station["inventory_gallons"] - uplift)
    touch(station)
    directive["status"] = "EXECUTED"
    touch(directive)
    return ok(ser.directive(directive))


@bp.post("/fuel/tankering-directives/<directive_id>/reconcile")
@endpoint(FUEL_OPS_CONTROLLER)
def reconcile_directive(directive_id):
    data = v.body()
    actual_uplift = v.get_number(data, "actual_uplift_gallons")
    actual_block = v.get_int(data, "actual_block_minutes", exclusive_minimum=0)

    directive = fetch.directive(directive_id)
    _require_status(directive, "EXECUTED")

    leg = _leg_of(directive)
    cap = domain.leg_uplift_cap(leg)
    if actual_uplift > cap:
        fail("ERR_TANKERING_WEIGHT_LIMIT",
             "actual_uplift_gallons %s exceeds the leg's uplift cap of %s."
             % (actual_uplift, cap))
    if actual_uplift <= 0:
        fail("ERR_ZERO_UPLIFT", "actual_uplift_gallons must be greater than zero.")

    leg["actual_uplift_gallons"] = actual_uplift
    leg["actual_block_minutes"] = actual_block
    touch(leg)

    penalty = calc.burn_penalty(leg, actual_uplift, actual_block)
    price_origin = directive["pinned_origin_price_usd_per_gal"]
    price_destination = directive["pinned_destination_price_usd_per_gal"]
    _gross, _penalty_cost, net = calc.net_savings(actual_uplift, penalty,
                                                 price_origin, price_destination)
    directive["reconciled_burn_penalty_gallons"] = penalty
    directive["reconciled_net_savings_usd"] = net
    directive["savings_variance_usd"] = r2(net - directive["planned_net_savings_usd"])

    station = db.stations.get(leg["origin_station_id"])
    if station is not None:
        delta = directive["requested_uplift_gallons"] - actual_uplift
        station["inventory_gallons"] = r2(station["inventory_gallons"] + delta)
        touch(station)

    directive["status"] = "RECONCILED"
    touch(directive)
    return ok(ser.directive(directive))
