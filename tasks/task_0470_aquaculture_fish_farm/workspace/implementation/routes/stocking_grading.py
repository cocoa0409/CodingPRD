"""StockingEvent + GradingEvent endpoints (PRD §3.5, §3.6)."""
from decimal import Decimal

from flask import Blueprint, request

import errors
import serializers
from common import (stamp_create, touch, get_body, require_str, require_number,
                    require_int, parse_dt, parse_iso, to_iso, must_get,
                    require_fk, paginate, D, round2)
from db import store
from middleware import require_roles, ALL_ROLES
from response import object_response, array_response
from domain import recompute_cohort_biomass, recompute_tank_biomass, tank_current_biomass

bp = Blueprint("stocking_grading", __name__)

IN_PRODUCTION = {"STOCKED", "GROWING", "HARVESTING"}


# ===========================================================================
# StockingEvent
# ===========================================================================
@bp.route("/stocking-events", methods=["POST"])
def create_stocking_event():
    require_roles({"FarmTechnician"})
    body = get_body()
    cohort_id, cohort = require_fk(body, "cohort_id", store.cohorts)
    tank_id, tank = require_fk(body, "tank_id", store.tanks)
    fish_count = require_int(body, "fish_count", gt=0)
    stocked_at = parse_dt(body, "stocked_at")
    expected_harvest_at = parse_dt(body, "expected_harvest_at")
    if not (expected_harvest_at > stocked_at):
        raise errors.invalid_request("expected_harvest_at must be strictly after stocked_at.")

    with store.lock:
        # Tank posture gate: stocking requires posture OPEN (PRD §3.6).
        if tank["posture"] != "OPEN":
            raise errors.tank_not_operational()

        # Occupancy overlap (PRD §3.6): half-open intervals on the same tank.
        new_start = stocked_at
        new_end = expected_harvest_at
        for ev in store.stocking_events.values():
            if ev["tank_id"] != tank_id:
                continue
            ex_start = parse_iso(ev["stocked_at"])
            ex_end = parse_iso(ev["expected_harvest_at"])
            # Half-open overlap: [a,b) overlaps [c,d) iff a < d and c < b.
            if new_start < ex_end and ex_start < new_end:
                raise errors.tank_occupancy_overlap()

        # Biomass capacity (PRD §3.6): must not push current_biomass above max.
        current = D(tank_current_biomass(tank_id))
        recompute_cohort_biomass(cohort)
        contribution = D(cohort["estimated_biomass_kg"]) if cohort["current_tank_id"] != tank_id else D(0)
        # The stocking event places fish into the tank; if the cohort already
        # resides there it is already counted, otherwise it adds its biomass.
        if round2(current + contribution) > D(tank["max_biomass_kg"]):
            raise errors.tank_biomass_exceeded()

        rec = {
            "cohort_id": cohort_id,
            "tank_id": tank_id,
            "fish_count": fish_count,
            "stocked_at": to_iso(stocked_at),
            "expected_harvest_at": to_iso(expected_harvest_at),
        }
        stamp_create(rec, with_version=False)
        store.stocking_events[rec["id"]] = rec
        data = serializers.stocking_event_out(rec)
    return object_response(data, 201)


@bp.route("/stocking-events", methods=["GET"])
def list_stocking_events():
    require_roles(ALL_ROLES)
    cohort_id = request.args.get("cohort_id")
    tank_id = request.args.get("tank_id")
    with store.lock:
        items = list(store.stocking_events.values())
        if cohort_id is not None:
            items = [e for e in items if e["cohort_id"] == cohort_id]
        if tank_id is not None:
            items = [e for e in items if e["tank_id"] == tank_id]
        window, limit, offset, total = paginate(items)
        data = [serializers.stocking_event_out(e) for e in window]
    return array_response(data, limit, offset, total)


@bp.route("/stocking-events/<eid>", methods=["GET"])
def get_stocking_event(eid):
    require_roles(ALL_ROLES)
    with store.lock:
        rec = must_get(store.stocking_events, eid)
        data = serializers.stocking_event_out(rec)
    return object_response(data, 200)


# ===========================================================================
# GradingEvent
# ===========================================================================
def _validate_splits(splits):
    """ERR_GRADING_SPLIT_EMPTY: empty array or a split with fish_count <= 0.
    Each split must be a well-formed dict with the required keys."""
    if not isinstance(splits, list) or len(splits) == 0:
        raise errors.grading_split_empty()
    for s in splits:
        if not isinstance(s, dict):
            raise errors.invalid_request("Each planned split must be an object.")
        if "fish_count" not in s or not isinstance(s["fish_count"], int) or isinstance(s["fish_count"], bool):
            raise errors.invalid_request("Each planned split needs an integer fish_count.")
        if s["fish_count"] <= 0:
            raise errors.grading_split_empty()
        if "target_tank_id" not in s or not isinstance(s["target_tank_id"], str) or s["target_tank_id"] == "":
            raise errors.invalid_request("Each planned split needs a target_tank_id.")
        if "label" not in s or not isinstance(s["label"], str):
            raise errors.invalid_request("Each planned split needs a label.")
        if "avg_weight_g" not in s or isinstance(s["avg_weight_g"], bool) or not isinstance(s["avg_weight_g"], (int, float)):
            raise errors.invalid_request("Each planned split needs a numeric avg_weight_g.")


@bp.route("/grading-events", methods=["POST"])
def create_grading_event():
    require_roles({"FarmTechnician"})
    body = get_body()
    source_id, _ = require_fk(body, "source_cohort_id", store.cohorts)
    if "planned_splits" not in body or body["planned_splits"] is None:
        raise errors.invalid_request("Missing required field 'planned_splits'.")
    splits = body["planned_splits"]
    _validate_splits(splits)
    with store.lock:
        rec = {
            "source_cohort_id": source_id,
            "planned_splits": splits,
            "status": "DRAFT",
            "child_cohort_ids": [],
        }
        stamp_create(rec)
        store.grading_events[rec["id"]] = rec
        data = serializers.grading_event_out(rec)
    return object_response(data, 201)


@bp.route("/grading-events", methods=["GET"])
def list_grading_events():
    require_roles(ALL_ROLES)
    source_id = request.args.get("source_cohort_id")
    with store.lock:
        items = list(store.grading_events.values())
        if source_id is not None:
            items = [g for g in items if g["source_cohort_id"] == source_id]
        window, limit, offset, total = paginate(items)
        data = [serializers.grading_event_out(g) for g in window]
    return array_response(data, limit, offset, total)


@bp.route("/grading-events/<gid>", methods=["GET"])
def get_grading_event(gid):
    require_roles(ALL_ROLES)
    with store.lock:
        rec = must_get(store.grading_events, gid)
        data = serializers.grading_event_out(rec)
    return object_response(data, 200)


@bp.route("/grading-events/<gid>/plan", methods=["POST"])
def plan_grading_event(gid):
    require_roles({"FarmTechnician"})
    with store.lock:
        grading = must_get(store.grading_events, gid)
        if grading["status"] != "DRAFT":
            raise errors.invalid_state()
        source = store.cohorts.get(grading["source_cohort_id"])
        if source is None:
            raise errors.not_found()

        splits = grading["planned_splits"]
        _validate_splits(splits)
        # Fish-count conservation (PRD §3.5).
        if sum(s["fish_count"] for s in splits) != source["fish_count"]:
            raise errors.fish_count_mismatch()
        # Target-tank posture must be OPEN.
        for s in splits:
            target = store.tanks.get(s["target_tank_id"])
            if target is None:
                raise errors.not_found()
            if target["posture"] != "OPEN":
                raise errors.invalid_split_target()

        grading["status"] = "PLANNED"
        touch(grading)
        data = serializers.grading_event_out(grading)
    return object_response(data, 200)


@bp.route("/grading-events/<gid>/revise", methods=["POST"])
def revise_grading_event(gid):
    require_roles({"FarmTechnician"})
    with store.lock:
        grading = must_get(store.grading_events, gid)
        if grading["status"] != "PLANNED":
            raise errors.invalid_state()
        body = get_body()
        if "planned_splits" in body and body["planned_splits"] is not None:
            splits = body["planned_splits"]
            _validate_splits(splits)
            grading["planned_splits"] = splits
        grading["status"] = "DRAFT"
        touch(grading)
        data = serializers.grading_event_out(grading)
    return object_response(data, 200)


@bp.route("/grading-events/<gid>/commit", methods=["POST"])
def commit_grading_event(gid):
    require_roles({"FarmTechnician"})
    with store.lock:
        grading = must_get(store.grading_events, gid)
        body = get_body()
        expected = require_int(body, "expected_source_cohort_version")

        if grading["status"] != "PLANNED":
            raise errors.invalid_state()
        source = store.cohorts.get(grading["source_cohort_id"])
        if source is None:
            raise errors.not_found()

        # OCC (PRD §2.8) — precedes business rules (priority 5).
        if expected != source["version"]:
            raise errors.stale_version()

        # Operational gate (PRD §3.5): source must be ACTIVE.
        if source["operational_status"] != "ACTIVE":
            raise errors.tank_not_operational()
        # Lifecycle must be STOCKED or GROWING.
        if source["lifecycle_status"] not in {"STOCKED", "GROWING"}:
            raise errors.tank_not_operational()

        splits = grading["planned_splits"]
        _validate_splits(splits)
        # Fish-count conservation at commit (PRD §3.5).
        if sum(s["fish_count"] for s in splits) != source["fish_count"]:
            raise errors.fish_count_mismatch()

        # Target tanks must exist and be OPEN (re-check at commit).
        for s in splits:
            target = store.tanks.get(s["target_tank_id"])
            if target is None:
                raise errors.not_found()
            if target["posture"] != "OPEN":
                raise errors.invalid_split_target()

        # Biomass capacity per target tank (PRD §3.5). Aggregate per target the
        # estimated biomass the new children would add, then check against max.
        species = store.species.get(source["species_id"])
        added_per_tank = {}
        for s in splits:
            tid = s["target_tank_id"]
            child_avg = s["avg_weight_g"]
            # Estimate child biomass at stocking-day 0: fish_count * avg_weight / 1000.
            child_biomass = round2(D(s["fish_count"]) * D(child_avg) / Decimal("1000"))
            added_per_tank[tid] = added_per_tank.get(tid, D(0)) + D(child_biomass)
        for tid, added in added_per_tank.items():
            target = store.tanks[tid]
            current = D(tank_current_biomass(tid))
            if round2(current + added) > D(target["max_biomass_kg"]):
                raise errors.tank_biomass_exceeded()

        # Create child cohorts (conservation invariant).
        now_iso = source["stocked_at"]
        child_ids = []
        for s in splits:
            child = {
                "label": s["label"],
                "species_id": source["species_id"],
                "current_tank_id": s["target_tank_id"],
                "origin_broodstock_id": None,
                "parent_cohort_id": source["id"],
                "fish_count": s["fish_count"],
                "stocked_avg_weight_g": s["avg_weight_g"],
                "stocked_at": now_iso,
                "cumulative_feed_kg": 0,
                "estimated_biomass_kg": 0,
                "lifecycle_status": "STOCKED",
                "health_status": "HEALTHY",
                "operational_status": "ACTIVE",
                "withdrawal_until": None,
            }
            stamp_create(child)
            recompute_cohort_biomass(child)
            store.cohorts[child["id"]] = child
            child_ids.append(child["id"])

        # Consume the source.
        source["fish_count"] = 0
        source["lifecycle_status"] = "HARVESTED"
        touch(source)

        grading["child_cohort_ids"] = child_ids
        grading["status"] = "COMMITTED"
        touch(grading)
        data = serializers.grading_event_out(grading)
    return object_response(data, 200)


@bp.route("/grading-events/<gid>/cancel", methods=["POST"])
def cancel_grading_event(gid):
    require_roles({"FarmTechnician"})
    with store.lock:
        grading = must_get(store.grading_events, gid)
        if grading["status"] != "DRAFT":
            raise errors.invalid_state()
        grading["status"] = "CANCELLED"
        touch(grading)
        data = serializers.grading_event_out(grading)
    return object_response(data, 200)
