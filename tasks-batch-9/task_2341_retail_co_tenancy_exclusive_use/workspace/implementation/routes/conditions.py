"""Co-tenancy conditions and their named-anchor requirements."""
from flask import Blueprint

import engine
import validate as v
from crud import apply_filters, base, paginate, resolve, strip
from db import store
from errors import ApiError
from middleware import LIST_READ_ROLES, SINGLE_READ_ROLES, authorize
from response import created, listing, ok
from util import D, q2

bp = Blueprint("conditions", __name__)

CONDITION_KINDS = ("OPENING", "ONGOING")
BASES = ("GLA_PCT", "STORE_COUNT")
REMEDY_TYPES = ("RENT_REDUCTION_ONLY", "RENT_REDUCTION_THEN_TERMINATION",
                "TERMINATION_ONLY")


def get_condition(condition_id):
    return resolve(store.conditions, condition_id, "ERR_CONDITION_NOT_FOUND")


@bp.post("/leases/<lease_id>/co-tenancy-conditions")
def create_condition(lease_id):
    authorize(["LeaseAdministrator"])
    body = v.body()
    condition_kind = v.req_enum(body, "condition_kind", CONDITION_KINDS)
    measurement_basis = v.req_enum(body, "measurement_basis", BASES)
    remedy_type = v.req_enum(body, "remedy_type", REMEDY_TYPES)
    required_pct = v.opt_pct(body, "required_occupancy_pct", default=None,
                             exclusive_min=0)
    required_stores = v.opt_int(body, "required_open_store_count", default=None)
    required_anchors = v.opt_int(body, "required_anchor_count", default=0, minimum=0)
    grace_days = v.opt_int(body, "grace_period_days", default=30, minimum=0)
    cure_days = v.opt_int(body, "cure_period_days", default=120, minimum=0)
    max_reduction = v.opt_pct(body, "max_reduction_pct", default=D(50),
                              exclusive_min=0)

    lease = resolve(store.leases, lease_id, "ERR_LEASE_NOT_FOUND")

    # rung 24 - measurement basis coherence
    if measurement_basis == "GLA_PCT":
        if required_pct is None or required_stores is not None:
            raise ApiError("ERR_MEASUREMENT_BASIS_MISMATCH")
    else:
        if required_stores is None or required_pct is not None:
            raise ApiError("ERR_MEASUREMENT_BASIS_MISMATCH")
        if required_stores < 1:
            raise ApiError("ERR_MEASUREMENT_BASIS_MISMATCH")

    # rung 28 - condition kind coherence
    if condition_kind == "OPENING" and lease["premises_status"] == "OPEN":
        raise ApiError("ERR_CONDITION_KIND_INVALID")
    if condition_kind == "ONGOING" and lease["premises_status"] == "DRAFT":
        raise ApiError("ERR_CONDITION_KIND_INVALID")

    cond = base(engine.stamp())
    cond.update({
        "lease_id": lease["id"],
        "condition_kind": condition_kind,
        "measurement_basis": measurement_basis,
        "required_occupancy_pct": q2(required_pct) if required_pct is not None else None,
        "required_open_store_count": required_stores,
        "required_anchor_count": required_anchors,
        "grace_period_days": grace_days,
        "cure_period_days": cure_days,
        "remedy_type": remedy_type,
        "max_reduction_pct": q2(max_reduction),
        "status": "SATISFIED",
        "breach_detected_at": None,
        "consecutive_breach_days": 0,
        "last_evaluated_measurement_id": None,
    })
    store.conditions[cond["id"]] = cond

    # evaluated immediately under the live strict engine
    engine.evaluate_condition(cond, "LIVE_STRICT")
    center = engine.center_of_lease(lease)
    if center is not None:
        engine.bump_center(center)
    return created(strip(cond))


@bp.get("/co-tenancy-conditions/<condition_id>")
def read_condition(condition_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(get_condition(condition_id)))


@bp.get("/co-tenancy-conditions")
def list_conditions():
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    records = engine._ordered(list(store.conditions.values()))
    records = apply_filters(records, [
        ("lease_id", v.filter_value("lease_id")),
        ("last_evaluated_measurement_id",
         v.filter_value("last_evaluated_measurement_id")),
        ("condition_kind", v.filter_value("condition_kind")),
        ("status", v.filter_value("status")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


@bp.post("/co-tenancy-conditions/<condition_id>/waive")
def waive_condition(condition_id):
    authorize(["AssetManager"])
    body = v.body()
    v.opt_str(body, "waiver_reason_code")
    cond = get_condition(condition_id)
    if cond["status"] not in ("SATISFIED", "CURED", "BREACHED"):
        raise ApiError("ERR_CONDITION_STATE_INVALID")

    cond["status"] = "WAIVED"
    cond["breach_detected_at"] = None
    cond["consecutive_breach_days"] = 0
    engine.touch(cond)

    lease = store.leases.get(cond["lease_id"])
    if lease is not None:
        for election in engine.elections_of_lease(lease["id"]):
            if election["status"] == "ELECTED" \
                    and election.get("condition_id") == cond["id"]:
                election["status"] = "RESCINDED"
                election["abated_to_date_cents"] = 0
                engine.touch(election)
        if engine.recompute_lease_money(lease):
            engine.touch_lease(lease)
        engine.release_remedy(lease)
        center = engine.center_of_lease(lease)
        if center is not None:
            engine.bump_center(center)
    return ok(strip(cond))


@bp.post("/co-tenancy-conditions/<condition_id>/anchor-requirements")
def create_requirement(condition_id):
    authorize(["LeaseAdministrator"])
    body = v.body()
    anchor_lease_id = v.req_str(body, "anchor_lease_id")
    substitution_allowed = v.opt_bool(body, "substitution_allowed", default=False)
    min_substitute = v.opt_int(body, "min_substitute_gla_sqft", default=0, minimum=0)

    cond = get_condition(condition_id)
    anchor = resolve(store.leases, anchor_lease_id, "ERR_LEASE_NOT_FOUND")

    benefited = store.leases.get(cond["lease_id"])
    if benefited is None or anchor["center_id"] != benefited["center_id"]:
        raise ApiError("ERR_CENTER_SCOPE_MISMATCH")
    if anchor["parcel_kind"] != "ANCHOR_BOX":
        raise ApiError("ERR_INVALID_REQUEST",
                       "anchor_lease_id must name a lease whose parcel_kind is "
                       "ANCHOR_BOX")

    requirement = base(engine.stamp(), audited=False)
    requirement.update({
        "condition_id": cond["id"],
        "anchor_lease_id": anchor["id"],
        "substitution_allowed": substitution_allowed,
        "min_substitute_gla_sqft": min_substitute,
    })
    store.anchor_requirements[requirement["id"]] = requirement

    engine.evaluate_condition(cond, "LIVE_STRICT")
    center = engine.center_of_lease(benefited)
    if center is not None:
        engine.bump_center(center)
    return created(strip(requirement))


@bp.get("/anchor-requirements/<requirement_id>")
def read_requirement(requirement_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(resolve(store.anchor_requirements, requirement_id,
                            "ERR_REQUIREMENT_NOT_FOUND")))


@bp.get("/anchor-requirements")
def list_requirements():
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    records = engine._ordered(list(store.anchor_requirements.values()))
    records = apply_filters(records, [
        ("condition_id", v.filter_value("condition_id")),
        ("anchor_lease_id", v.filter_value("anchor_lease_id")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)
