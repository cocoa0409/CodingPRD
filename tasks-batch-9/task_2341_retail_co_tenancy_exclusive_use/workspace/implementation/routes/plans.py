"""Redevelopment plans, pad sales and the protected-rights conserved quantity."""
from flask import Blueprint

import engine
import validate as v
from crud import apply_filters, base, paginate, resolve, strip
from db import store
from errors import ApiError
from middleware import LIST_READ_ROLES, SINGLE_READ_ROLES, authorize
from response import created, listing, ok

bp = Blueprint("plans", __name__)

PLAN_KINDS = ("PAD_SALE", "REDEMISE", "EXPANSION")


def get_plan(plan_id):
    return resolve(store.plans, plan_id, "ERR_PLAN_NOT_FOUND")


def _impacted_clause_count(center_id):
    total = 0
    for clause in engine.clauses_of_center(center_id):
        lease = store.leases.get(clause["lease_id"])
        if clause["status"] != "ACTIVE" or lease is None:
            continue
        if lease["premises_status"] == "TERMINATED":
            continue
        if clause["exclusivity_scope"] in ("CENTER_WIDE", "RADIUS_INCLUSIVE"):
            total += 1
    return total


def _impacted_condition_count(center, gla_after_sqft):
    figures = engine.snapshot(center, "SNAPSHOT_STRICT", engine.now(),
                              total_gla_sqft=gla_after_sqft)
    total = 0
    for cond in engine.conditions_of_center(center["id"]):
        if cond["condition_kind"] != "ONGOING" \
                or cond["measurement_basis"] != "GLA_PCT" \
                or cond["status"] not in ("SATISFIED", "CURED"):
            continue
        satisfied = engine.condition_satisfied(
            cond, figures["gla_occupancy_pct"], figures["open_store_count"],
            figures["open_anchor_count"], "SNAPSHOT_STRICT", engine.now())
        if not satisfied:
            total += 1
    return total


@bp.post("/centers/<center_id>/redevelopment-plans")
def create_plan(center_id):
    authorize(["AssetManager"])
    body = v.body()
    plan_kind = v.req_enum(body, "plan_kind", PLAN_KINDS)
    removed = v.opt_int(body, "removed_gla_sqft", default=0, minimum=0)
    pad_lease_id = v.opt_id(body, "pad_parcel_lease_id")

    center = resolve(store.centers, center_id, "ERR_CENTER_NOT_FOUND")
    if removed >= center["total_gla_sqft"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "removed_gla_sqft must be strictly less than the center's "
                       "total_gla_sqft")
    if plan_kind == "EXPANSION" and removed != 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "An EXPANSION plan must carry removed_gla_sqft of 0")

    pad_lease = None
    if pad_lease_id is not None:
        pad_lease = resolve(store.leases, pad_lease_id, "ERR_LEASE_NOT_FOUND")
        if pad_lease["center_id"] != center["id"]:
            raise ApiError("ERR_CENTER_SCOPE_MISMATCH")
        if pad_lease["parcel_kind"] != "PAD":
            raise ApiError("ERR_INVALID_REQUEST",
                           "pad_parcel_lease_id must name a lease whose parcel_kind "
                           "is PAD")

    gla_after = center["total_gla_sqft"] - removed
    clause_count = _impacted_clause_count(center["id"])
    condition_count = _impacted_condition_count(center, gla_after)
    consent_required = clause_count > 0 or condition_count > 0

    plan = base(engine.stamp())
    plan.update({
        "center_id": center["id"],
        "pad_parcel_lease_id": pad_lease_id,
        "plan_kind": plan_kind,
        "removed_gla_sqft": removed,
        "gla_after_sqft": gla_after,
        "impacted_clause_count": clause_count,
        "impacted_condition_count": condition_count,
        "consent_required": consent_required,
        "status": "CONSENT_PENDING" if consent_required else "PLANNED",
        "recorded_at": None,
    })
    store.plans[plan["id"]] = plan
    engine.bump_center(center)
    return created(strip(plan))


@bp.get("/redevelopment-plans/<plan_id>")
def read_plan(plan_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(get_plan(plan_id)))


@bp.get("/redevelopment-plans")
def list_plans():
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    records = engine._ordered(list(store.plans.values()))
    records = apply_filters(records, [
        ("center_id", v.filter_value("center_id")),
        ("pad_parcel_lease_id", v.filter_value("pad_parcel_lease_id")),
        ("plan_kind", v.filter_value("plan_kind")),
        ("status", v.filter_value("status")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


@bp.post("/redevelopment-plans/<plan_id>/record")
def record_plan(plan_id):
    authorize(["AssetManager"])
    body = v.body()
    consent_confirmed = v.opt_bool(body, "consent_confirmed", default=False)
    plan = get_plan(plan_id)
    center = resolve(store.centers, plan["center_id"], "ERR_CENTER_NOT_FOUND")

    if center["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_CENTER_EXECUTION_FROZEN")
    if plan["status"] not in ("PLANNED", "CONSENT_PENDING"):
        raise ApiError("ERR_PLAN_STATE_INVALID")
    if plan["consent_required"] and not consent_confirmed:
        raise ApiError("ERR_PROTECTED_RIGHTS_CONSENT_REQUIRED")

    plan["status"] = "RECORDED"
    plan["recorded_at"] = engine.stamp()
    engine.touch(plan)

    center["total_gla_sqft"] = center["total_gla_sqft"] - plan["removed_gla_sqft"]

    if plan["consent_required"]:
        for clause in engine.clauses_of_center(center["id"]):
            if clause["status"] == "ACTIVE" \
                    and clause["exclusivity_scope"] == "CENTER_WIDE":
                clause["status"] = "SUSPENDED"
                clause["suspended_by_plan_id"] = plan["id"]
                engine.touch(clause)

    if plan.get("pad_parcel_lease_id"):
        for cond in engine.conditions_of_lease(plan["pad_parcel_lease_id"]):
            if cond["status"] in ("SATISFIED", "BREACHED", "CURED"):
                cond["status"] = "WAIVED"
                cond["breach_detected_at"] = None
                cond["consecutive_breach_days"] = 0
                engine.touch(cond)

    engine.recompute_center_derived(center)
    engine.evaluate_center_conditions(center, "LIVE_STRICT", kinds=("ONGOING",))
    engine.bump_center(center)
    return ok(strip(plan))


@bp.post("/redevelopment-plans/<plan_id>/abandon")
def abandon_plan(plan_id):
    authorize(["AssetManager"])
    body = v.body()
    v.opt_str(body, "abandon_reason_code")
    plan = get_plan(plan_id)
    center = resolve(store.centers, plan["center_id"], "ERR_CENTER_NOT_FOUND")

    if plan["status"] not in ("PLANNED", "CONSENT_PENDING", "RECORDED"):
        raise ApiError("ERR_PLAN_STATE_INVALID")
    was_recorded = plan["status"] == "RECORDED"

    plan["status"] = "ABANDONED"
    engine.touch(plan)

    if was_recorded:
        center["total_gla_sqft"] = center["total_gla_sqft"] + plan["removed_gla_sqft"]
        for clause in engine.clauses_of_center(center["id"]):
            if clause.get("suspended_by_plan_id") == plan["id"]:
                clause["status"] = "ACTIVE"
                clause["suspended_by_plan_id"] = None
                engine.touch(clause)
        engine.recompute_center_derived(center)
        engine.evaluate_center_conditions(center, "LIVE_STRICT", kinds=("ONGOING",))

    engine.bump_center(center)
    return ok(strip(plan))
