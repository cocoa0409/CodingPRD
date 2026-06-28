"""Cohort endpoints + feed logs + summary (PRD §3.2, §3.3)."""
from flask import Blueprint, request

import errors
import serializers
import calculations
from common import (stamp_create, touch, get_body, require_str, require_number,
                    require_int, parse_dt, parse_iso, to_iso, must_get,
                    require_fk, optional_fk, paginate, D, round2)
from db import store
from middleware import require_roles, ALL_ROLES
from response import object_response, array_response
from domain import recompute_cohort_biomass

bp = Blueprint("cohorts", __name__)


# ---------------------------------------------------------------------------
# Cohort create / list / get
# ---------------------------------------------------------------------------
@bp.route("/cohorts", methods=["POST"])
def create_cohort():
    require_roles({"FarmTechnician"})
    body = get_body()
    label = require_str(body, "label")
    species_id, _ = require_fk(body, "species_id", store.species)
    tank_id, tank = require_fk(body, "current_tank_id", store.tanks)
    origin_id, brood = optional_fk(body, "origin_broodstock_id", store.broodstock_batches)
    parent_id, _ = optional_fk(body, "parent_cohort_id", store.cohorts)
    fish_count = require_int(body, "fish_count", ge=0)
    stocked_avg = require_number(body, "stocked_avg_weight_g", gt=0)
    stocked_at = parse_dt(body, "stocked_at")

    with store.lock:
        # Broodstock allocation (PRD §3.2): draw must not exceed remaining.
        if brood is not None:
            remaining = brood["fingerling_count"] - brood["allocated_count"]
            if fish_count > remaining:
                raise errors.broodstock_insufficient()

        rec = {
            "label": label,
            "species_id": species_id,
            "current_tank_id": tank_id,
            "origin_broodstock_id": origin_id,
            "parent_cohort_id": parent_id,
            "fish_count": fish_count,
            "stocked_avg_weight_g": stocked_avg,
            "stocked_at": to_iso(stocked_at),
            "cumulative_feed_kg": 0,
            "estimated_biomass_kg": 0,
            "lifecycle_status": "STOCKED",
            "health_status": "HEALTHY",
            "operational_status": "ACTIVE",
            "withdrawal_until": None,
        }
        stamp_create(rec)
        store.cohorts[rec["id"]] = rec

        # Apply the draw to the broodstock batch.
        if brood is not None:
            brood["allocated_count"] += fish_count
            if brood["allocated_count"] >= brood["fingerling_count"]:
                brood["status"] = "DEPLETED"
            touch(brood)

        data = serializers.cohort_out(rec)
    return object_response(data, 201)


@bp.route("/cohorts", methods=["GET"])
def list_cohorts():
    require_roles(ALL_ROLES)
    filters = {
        "species_id": request.args.get("species_id"),
        "current_tank_id": request.args.get("current_tank_id"),
        "origin_broodstock_id": request.args.get("origin_broodstock_id"),
        "parent_cohort_id": request.args.get("parent_cohort_id"),
        "lifecycle_status": request.args.get("lifecycle_status"),
        "health_status": request.args.get("health_status"),
    }
    with store.lock:
        items = list(store.cohorts.values())
        for field, val in filters.items():
            if val is not None:
                items = [c for c in items if c[field] == val]
        window, limit, offset, total = paginate(items)
        data = [serializers.cohort_out(c) for c in window]
    return array_response(data, limit, offset, total)


@bp.route("/cohorts/<cid>", methods=["GET"])
def get_cohort(cid):
    require_roles(ALL_ROLES)
    with store.lock:
        rec = must_get(store.cohorts, cid)
        data = serializers.cohort_out(rec)
    return object_response(data, 200)


@bp.route("/cohorts/<cid>/summary", methods=["GET"])
def cohort_summary(cid):
    require_roles(ALL_ROLES)
    with store.lock:
        cohort = must_get(store.cohorts, cid)
        # Recompute biomass against the logical clock (read-only computation).
        recompute_cohort_biomass(cohort)
        prov_fcr = calculations.provisional_fcr(cohort)
        stocked_at = parse_iso(cohort["stocked_at"])
        days = calculations.days_elapsed_since(stocked_at)
        if days < 0:
            days = 0
        data = {
            "cohort_id": cohort["id"],
            "estimated_biomass_kg": cohort["estimated_biomass_kg"],
            "provisional_fcr": prov_fcr,
            "cumulative_feed_kg": cohort["cumulative_feed_kg"],
            "days_elapsed": days,
        }
    return object_response(data, 200)


# ---------------------------------------------------------------------------
# Feed logs
# ---------------------------------------------------------------------------
@bp.route("/cohorts/<cid>/feed-logs", methods=["POST"])
def create_feed_log(cid):
    require_roles({"FarmTechnician"})
    with store.lock:
        cohort = must_get(store.cohorts, cid)
        body = get_body()
        fed_at = parse_dt(body, "fed_at")
        amount = require_number(body, "amount_kg", gt=0)
        feed_type = require_str(body, "feed_type")

        # State gate (PRD §2.12 priority 4, §3.3): feeding is a transition defined
        # only out of STOCKED (-> GROWING) or GROWING (continues). A cohort in a
        # terminal lifecycle state (HARVESTING/HARVESTED) is "not in a state from
        # which the requested transition is defined" -> ERR_INVALID_STATE. This
        # state check precedes business rules and the clock-consistency check.
        if cohort["lifecycle_status"] not in {"STOCKED", "GROWING"}:
            raise errors.invalid_state()

        # Operational/posture gate (PRD §3.3): feeding requires the cohort ACTIVE
        # and the residing tank posture OPEN or RESTRICTED.
        tank = store.tanks.get(cohort["current_tank_id"])
        if cohort["operational_status"] != "ACTIVE":
            raise errors.tank_not_operational()
        if tank is None or tank["posture"] not in {"OPEN", "RESTRICTED"}:
            raise errors.tank_not_operational()

        # Clock consistency (PRD §2.11): a feeding event must not lie in the
        # future relative to the logical clock, and must not precede the cohort's
        # logical-timeline anchor (its stocked_at — the start of the growth clock).
        stocked_at = parse_iso(cohort["stocked_at"])
        if fed_at > store.clock or (stocked_at is not None and fed_at < stocked_at):
            raise errors.clock_backwards()

        log = {
            "cohort_id": cid,
            "fed_at": to_iso(fed_at),
            "amount_kg": amount,
            "feed_type": feed_type,
        }
        stamp_create(log, with_version=False)
        store.feed_logs[log["id"]] = log

        # Recompute cumulative feed + biomass; first feed advances lifecycle.
        total_feed = D(0)
        for fl in store.feed_logs.values():
            if fl["cohort_id"] == cid:
                total_feed += D(fl["amount_kg"])
        cohort["cumulative_feed_kg"] = round2(total_feed)
        if cohort["lifecycle_status"] == "STOCKED":
            cohort["lifecycle_status"] = "GROWING"
        recompute_cohort_biomass(cohort)
        touch(cohort)

        data = serializers.feed_log_out(log)
    return object_response(data, 201)


@bp.route("/cohorts/<cid>/feed-logs", methods=["GET"])
def list_feed_logs(cid):
    require_roles(ALL_ROLES)
    with store.lock:
        must_get(store.cohorts, cid)
        items = [fl for fl in store.feed_logs.values() if fl["cohort_id"] == cid]
        window, limit, offset, total = paginate(items)
        data = [serializers.feed_log_out(fl) for fl in window]
    return array_response(data, limit, offset, total)
