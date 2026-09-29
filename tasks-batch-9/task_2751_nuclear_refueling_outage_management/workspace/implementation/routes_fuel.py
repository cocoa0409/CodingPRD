"""Fuel reload design and spent fuel pool capacity (PRD 3.3)."""
from flask import Blueprint, request

import calc
import lookup
import projections
from auth import ALL_ROLES, authorize, current_user_id
from db import all_rows, create_row, store, touch
from errors import api_error
from response import ok, paginated, parse_pagination
from serializers import serialize
from validators import F, body, no_body

bp = Blueprint("fuel", __name__)

PURPOSES = ("DISCHARGE", "FRESH_STAGING", "CONTINGENCY")
PROTECTED_PURPOSES = ("DISCHARGE", "FRESH_STAGING")


# ---------------------------------------------------------------------------
# core loading patterns
# ---------------------------------------------------------------------------
@bp.route("/outages/<outage_id>/core-load-patterns", methods=["POST"])
@authorize("ReactorEngineer")
def create_core_load_pattern(outage_id):
    outage = lookup.outage(outage_id)
    payload = body([
        F("cycle_length_mwd_mtu", "num", gt=0),
        F("fresh_assembly_count", "int", ge=1),
        F("discharge_assembly_count", "int", ge=0),
        F("expected_outage_version", "int"),
    ])
    if payload["expected_outage_version"] != outage["version"]:
        raise api_error("ERR_OUTAGE_VERSION_STALE",
                        "expected_outage_version does not match the stored outage version.")
    margin = calc.reactivity_margin(payload["cycle_length_mwd_mtu"],
                                    payload["fresh_assembly_count"])
    if margin < calc.MIN_SHUTDOWN_MARGIN_PCM:
        raise api_error("ERR_SHUTDOWN_MARGIN_INSUFFICIENT",
                        "The computed reactivity margin is below the minimum shutdown margin.")

    pattern = create_row(store.core_load_patterns, {
        "outage_id": outage["id"],
        "cycle_length_mwd_mtu": calc.q2(payload["cycle_length_mwd_mtu"]),
        "fresh_assembly_count": payload["fresh_assembly_count"],
        "discharge_assembly_count": payload["discharge_assembly_count"],
        "reactivity_margin_pcm": margin,
        "status": "DRAFT",
        "created_by_user_id": current_user_id(),
        "approved_by_user_id": None,
    })
    for other in projections.patterns_of_outage(outage["id"]):
        if other["id"] == pattern["id"]:
            continue
        if other["status"] == "DRAFT":
            other["status"] = "SUPERSEDED"
            touch(other)
    touch(outage)
    return ok(serialize(pattern), 201)


@bp.route("/core-load-patterns/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_core_load_pattern(row_id):
    return ok(serialize(lookup.core_load_pattern(row_id)))


@bp.route("/outages/<outage_id>/core-load-patterns", methods=["GET"])
@authorize(*ALL_ROLES)
def list_core_load_patterns(outage_id):
    outage = lookup.outage(outage_id)
    limit, offset = parse_pagination(request.args)
    rows = projections.patterns_of_outage(outage["id"])
    wanted = request.args.get("status")
    if wanted is not None:
        rows = [r for r in rows if r["status"] == wanted]
    return paginated(rows, limit, offset, serialize)


@bp.route("/core-load-patterns/<row_id>/approve", methods=["POST"])
@authorize("OutageDirector", "ReactorEngineer")
def approve_core_load_pattern(row_id):
    pattern = lookup.core_load_pattern(row_id)
    no_body()
    if pattern["status"] != "DRAFT":
        raise api_error("ERR_CORE_LOAD_PATTERN_STATE_INVALID",
                        "Approval requires the pattern to be in DRAFT.")
    outage = store.outages[pattern["outage_id"]]
    if outage["status"] != "PLANNING":
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "Approval requires the owning outage to be in PLANNING.")
    if pattern["reactivity_margin_pcm"] < calc.MIN_SHUTDOWN_MARGIN_PCM:
        raise api_error("ERR_SHUTDOWN_MARGIN_INSUFFICIENT",
                        "The pattern's reactivity margin is below the minimum shutdown margin.")
    if current_user_id() == pattern["created_by_user_id"]:
        raise api_error("ERR_SEGREGATION_OF_DUTIES",
                        "The approver must differ from the pattern's author.")

    pattern["status"] = "APPROVED"
    pattern["approved_by_user_id"] = current_user_id()
    touch(pattern)
    for other in projections.patterns_of_outage(outage["id"]):
        if other["id"] == pattern["id"]:
            continue
        if other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            touch(other)
    touch(outage)
    return ok(serialize(pattern))


# ---------------------------------------------------------------------------
# pool cell reservations
# ---------------------------------------------------------------------------
@bp.route("/pool-cell-reservations", methods=["POST"])
@authorize("ReactorEngineer")
def create_pool_cell_reservation():
    payload = body([
        F("outage_id", "str"),
        F("spent_fuel_pool_id", "str"),
        F("cells_requested", "int", ge=1),
        F("purpose", "str", enum=PURPOSES),
        F("expected_spent_fuel_pool_version", "int"),
    ])
    pool = lookup.spent_fuel_pool(payload["spent_fuel_pool_id"])
    outage = lookup.outage(payload["outage_id"])

    if payload["purpose"] == "DISCHARGE":
        if not any(p["status"] == "APPROVED"
                   for p in projections.patterns_of_outage(outage["id"])):
            raise api_error("ERR_CORE_LOAD_PATTERN_NOT_APPROVED",
                            "A DISCHARGE reservation requires an APPROVED core loading pattern.")

    if payload["expected_spent_fuel_pool_version"] != pool["version"]:
        raise api_error("ERR_POOL_VERSION_STALE",
                        "expected_spent_fuel_pool_version does not match the stored pool version.")

    variant = ("FULL_CORE_PROTECTED" if payload["purpose"] in PROTECTED_PURPOSES
               else "NOMINAL")
    headroom = (pool["protected_cells_available"] if variant == "FULL_CORE_PROTECTED"
                else pool["cells_available"])
    if payload["cells_requested"] > headroom:
        raise api_error("ERR_POOL_CAPACITY_EXCEEDED",
                        "The requested cells exceed the selected headroom.")

    reservation = create_row(store.pool_cell_reservations, {
        "outage_id": outage["id"],
        "spent_fuel_pool_id": pool["id"],
        "cells_requested": payload["cells_requested"],
        "purpose": payload["purpose"],
        "availability_variant": variant,
        "status": "RESERVED",
        "release_reason": None,
    })
    projections.recompute_pool(pool)
    touch(pool)
    return ok(serialize(reservation), 201)


@bp.route("/pool-cell-reservations/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_pool_cell_reservation(row_id):
    return ok(serialize(lookup.pool_cell_reservation(row_id)))


@bp.route("/pool-cell-reservations", methods=["GET"])
@authorize(*ALL_ROLES)
def list_pool_cell_reservations():
    limit, offset = parse_pagination(request.args)
    rows = all_rows(store.pool_cell_reservations)
    for key in ("outage_id", "spent_fuel_pool_id", "purpose", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginated(rows, limit, offset, serialize)


@bp.route("/pool-cell-reservations/<row_id>/consume", methods=["POST"])
@authorize("ReactorEngineer")
def consume_pool_cell_reservation(row_id):
    reservation = lookup.pool_cell_reservation(row_id)
    no_body()
    if reservation["status"] != "RESERVED":
        raise api_error("ERR_POOL_RESERVATION_STATE_INVALID",
                        "Consumption requires the reservation to be in RESERVED.")
    outage = store.outages[reservation["outage_id"]]
    if outage["status"] not in ("SCOPE_LOCKED", "EXECUTION"):
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "The owning outage is not in an admissible status.")
    reservation["status"] = "CONSUMED"
    touch(reservation)
    pool = store.spent_fuel_pools[reservation["spent_fuel_pool_id"]]
    projections.recompute_pool(pool)
    touch(pool)
    return ok(serialize(reservation))


@bp.route("/pool-cell-reservations/<row_id>/release", methods=["POST"])
@authorize("ReactorEngineer")
def release_pool_cell_reservation(row_id):
    reservation = lookup.pool_cell_reservation(row_id)
    payload = body([F("release_reason", "str", min_len=1, max_len=500)])
    if reservation["status"] != "RESERVED":
        raise api_error("ERR_POOL_RESERVATION_STATE_INVALID",
                        "Release requires the reservation to be in RESERVED.")
    reservation["status"] = "RELEASED"
    reservation["release_reason"] = payload["release_reason"]
    touch(reservation)
    pool = store.spent_fuel_pools[reservation["spent_fuel_pool_id"]]
    projections.recompute_pool(pool)
    touch(pool)
    return ok(serialize(reservation))
