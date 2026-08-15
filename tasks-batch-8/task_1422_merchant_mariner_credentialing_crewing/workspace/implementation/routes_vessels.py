"""Vessels, safe-manning billets, rotation plans, compliance (PRD 3.6)."""

from flask import Blueprint, request

from db import store
from errors import err
from helpers import (
    get_body,
    opt_bool,
    opt_enum,
    opt_int,
    opt_str,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_str,
    require_roles,
    sorted_items,
)
from response import success
from serialize import ser_manning_slot, ser_rotation_plan, ser_vessel
from services import (
    ASSIGNMENT_OPEN_STATES,
    active_rotation_plan,
    cancel_assignment_cascade,
    recompute_vessel,
)

bp = Blueprint("vessels", __name__)

VESSEL_CLASSES = ("TANKER", "CONTAINER", "BULK", "PASSENGER", "OSV")
RANK_TRACKS = ("DECK", "ENGINE", "STEWARD")

ALL_ROLES = (
    "FleetAdmin",
    "CrewingManager",
    "CredentialingOfficer",
    "PortCaptain",
    "UnionDispatcher",
    "Mariner",
)


def _get_vessel(vessel_id):
    v = store.vessels.get(vessel_id)
    if v is None:
        raise err("ERR_VESSEL_NOT_FOUND", "Vessel %s not found" % vessel_id)
    return v


def _get_slot_under_vessel(vessel_id, slot_id):
    s = store.manning_slots.get(slot_id)
    if s is None or s["vessel_id"] != vessel_id:
        raise err("ERR_MANNING_SLOT_NOT_FOUND", "Manning slot %s not found" % slot_id)
    return s


def _get_plan_under_vessel(vessel_id, plan_id):
    p = store.rotation_plans.get(plan_id)
    if p is None or p["vessel_id"] != vessel_id:
        raise err("ERR_ROTATION_PLAN_NOT_FOUND", "Rotation plan %s not found" % plan_id)
    return p


# ---------------------------------------------------------------------------
# Vessels
# ---------------------------------------------------------------------------


@bp.route("/vessels", methods=["POST"])
@require_roles("FleetAdmin")
def create_vessel():
    body = get_body()
    name = req_str(body, "vessel_name")
    imo = req_str(body, "imo_number")
    vclass = req_enum(body, "vessel_class", VESSEL_CLASSES)
    flag = req_str(body, "flag_state")
    if any(v["imo_number"] == imo for v in store.vessels.values()):
        raise err("ERR_INVALID_REQUEST", "imo_number %s already exists" % imo)
    v = {
        "vessel_name": name,
        "imo_number": imo,
        "vessel_class": vclass,
        "flag_state": flag,
        "status": "REGISTERED",
        "compliance_posture": "COMPLIANT",
        "slots_total": 0,
        "slots_covered": 0,
    }
    store.stamp(v)
    store.vessels[v["id"]] = v
    return success(ser_vessel(v), code=201)


@bp.route("/vessels", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_vessels():
    items = list(store.vessels.values())
    status = request.args.get("status")
    vclass = request.args.get("vessel_class")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    if vclass is not None:
        items = [v for v in items if v["vessel_class"] == vclass]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_vessel(v) for v in page], response_type="array", pagination=meta
    )


@bp.route("/vessels/<vessel_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_vessel(vessel_id):
    return success(ser_vessel(_get_vessel(vessel_id)))


@bp.route("/vessels/<vessel_id>/activate", methods=["POST"])
@require_roles("FleetAdmin")
def activate_vessel(vessel_id):
    v = _get_vessel(vessel_id)
    if v["status"] != "REGISTERED":
        raise err("ERR_INVALID_STATE", "Vessel must be REGISTERED to activate")
    if not any(
        s["vessel_id"] == v["id"] and s["status"] == "ACTIVE"
        for s in store.manning_slots.values()
    ):
        raise err(
            "ERR_NO_MANNING_SLOTS",
            "Vessel activation requires at least one ACTIVE manning slot",
        )
    v["status"] = "ACTIVE"
    store.bump(v)
    recompute_vessel(v)
    return success(ser_vessel(v))


@bp.route("/vessels/<vessel_id>/mark-underway", methods=["POST"])
@require_roles("PortCaptain")
def mark_underway(vessel_id):
    v = _get_vessel(vessel_id)
    body = get_body()
    waiver = opt_str(body, "waiver_justification")
    if v["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Vessel must be ACTIVE to mark underway")
    recompute_vessel(v)
    if v["compliance_posture"] == "CRITICAL_SHORTAGE":
        raise err(
            "ERR_VESSEL_NOT_COMPLIANT",
            "Vessel has a critical manning shortage and cannot sail",
        )
    if v["compliance_posture"] == "DEFICIENT" and not waiver:
        raise err(
            "ERR_VESSEL_NOT_COMPLIANT",
            "DEFICIENT vessels require a waiver_justification to sail",
        )
    v["status"] = "UNDERWAY"
    store.bump(v)
    return success(ser_vessel(v))


@bp.route("/vessels/<vessel_id>/return-to-port", methods=["POST"])
@require_roles("PortCaptain")
def return_to_port(vessel_id):
    v = _get_vessel(vessel_id)
    if v["status"] != "UNDERWAY":
        raise err("ERR_INVALID_STATE", "Vessel must be UNDERWAY to return to port")
    v["status"] = "ACTIVE"
    store.bump(v)
    return success(ser_vessel(v))


@bp.route("/vessels/<vessel_id>/lay-up", methods=["POST"])
@require_roles("PortCaptain")
def lay_up(vessel_id):
    v = _get_vessel(vessel_id)
    if v["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Vessel must be ACTIVE to lay up")
    slot_ids = {
        s["id"] for s in store.manning_slots.values() if s["vessel_id"] == v["id"]
    }
    if any(
        a["manning_slot_id"] in slot_ids and a["assignment_status"] == "ONBOARD"
        for a in store.assignments.values()
    ):
        raise err(
            "ERR_ACTIVE_CREW_ABOARD",
            "Vessel has ONBOARD crew and cannot be laid up",
        )
    v["status"] = "LAID_UP"
    store.bump(v)
    # Cascade: PROPOSED/CONFIRMED assignments on this vessel's slots -> CANCELLED.
    for a in store.assignments.values():
        if a["manning_slot_id"] in slot_ids and a["assignment_status"] in (
            "PROPOSED",
            "CONFIRMED",
        ):
            cancel_assignment_cascade(a)
    recompute_vessel(v)
    return success(ser_vessel(v))


@bp.route("/vessels/<vessel_id>/decommission", methods=["POST"])
@require_roles("FleetAdmin")
def decommission(vessel_id):
    v = _get_vessel(vessel_id)
    if v["status"] not in ("ACTIVE", "LAID_UP"):
        raise err(
            "ERR_INVALID_STATE", "Vessel must be ACTIVE or LAID_UP to decommission"
        )
    slot_ids = {
        s["id"] for s in store.manning_slots.values() if s["vessel_id"] == v["id"]
    }
    if v["status"] == "ACTIVE" and any(
        a["manning_slot_id"] in slot_ids
        and a["assignment_status"] in ASSIGNMENT_OPEN_STATES
        for a in store.assignments.values()
    ):
        raise err(
            "ERR_ACTIVE_CREW_ABOARD",
            "Vessel has open assignments and cannot be decommissioned",
        )
    v["status"] = "DECOMMISSIONED"
    store.bump(v)
    for s in store.manning_slots.values():
        if s["vessel_id"] == v["id"] and s["status"] != "RETIRED":
            s["status"] = "RETIRED"
            store.bump(s)
    plan = active_rotation_plan(v["id"])
    if plan is not None:
        plan["status"] = "SUPERSEDED"
        store.bump(plan)
    return success(ser_vessel(v))


@bp.route("/vessels/<vessel_id>/manning-compliance", methods=["GET"])
@require_roles(*ALL_ROLES)
def manning_compliance(vessel_id):
    v = _get_vessel(vessel_id)
    recompute_vessel(v)
    uncovered_critical = []
    uncovered_noncritical = []
    for s in sorted_items(
        [
            s
            for s in store.manning_slots.values()
            if s["vessel_id"] == v["id"]
            and s["status"] == "ACTIVE"
            and s["current_coverage"] == "UNCOVERED"
        ]
    ):
        if s["is_critical_position"]:
            uncovered_critical.append(s["id"])
        else:
            uncovered_noncritical.append(s["id"])
    return success(
        {
            "posture": v["compliance_posture"],
            "slots_total": v["slots_total"],
            "slots_covered": v["slots_covered"],
            "uncovered_critical_slot_ids": uncovered_critical,
            "uncovered_noncritical_slot_ids": uncovered_noncritical,
        }
    )


# ---------------------------------------------------------------------------
# Manning slots
# ---------------------------------------------------------------------------


@bp.route("/vessels/<vessel_id>/manning-slots", methods=["POST"])
@require_roles("PortCaptain")
def create_slot(vessel_id):
    v = _get_vessel(vessel_id)
    body = get_body()
    position_code = req_str(body, "position_code")
    rank_track = req_enum(body, "rank_track", RANK_TRACKS)
    min_rank_grade = req_int(body, "min_rank_grade", min_v=1, max_v=9)
    required_endorsement = req_str(body, "required_endorsement_code")
    is_critical = opt_bool(body, "is_critical_position", default=False)
    tour_days = req_int(body, "standard_tour_days")
    if v["status"] not in ("REGISTERED", "ACTIVE"):
        raise err(
            "ERR_VESSEL_NOT_ACTIVE",
            "Manning slots can only be defined while the vessel is REGISTERED or ACTIVE",
        )
    s = {
        "vessel_id": v["id"],
        "position_code": position_code,
        "rank_track": rank_track,
        "min_rank_grade": min_rank_grade,
        "required_endorsement_code": required_endorsement,
        "is_critical_position": is_critical,
        "standard_tour_days": tour_days,
        "status": "ACTIVE",
        "current_coverage": "UNCOVERED",
    }
    store.stamp(s)
    store.manning_slots[s["id"]] = s
    recompute_vessel(v)
    return success(ser_manning_slot(s), code=201)


@bp.route("/vessels/<vessel_id>/manning-slots", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_slots(vessel_id):
    v = _get_vessel(vessel_id)
    items = [s for s in store.manning_slots.values() if s["vessel_id"] == v["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_manning_slot(s) for s in page], response_type="array", pagination=meta
    )


@bp.route("/vessels/<vessel_id>/manning-slots/<slot_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_slot(vessel_id, slot_id):
    _get_vessel(vessel_id)
    return success(ser_manning_slot(_get_slot_under_vessel(vessel_id, slot_id)))


@bp.route("/vessels/<vessel_id>/manning-slots/<slot_id>", methods=["PUT"])
@require_roles("PortCaptain")
def update_slot(vessel_id, slot_id):
    _get_vessel(vessel_id)
    s = _get_slot_under_vessel(vessel_id, slot_id)
    body = get_body()
    # Schema validation of supplied fields (pipeline step 6).
    new_values = {}
    if "position_code" in body and body["position_code"] is not None:
        new_values["position_code"] = req_str(body, "position_code")
    if "rank_track" in body and body["rank_track"] is not None:
        new_values["rank_track"] = req_enum(body, "rank_track", RANK_TRACKS)
    if "min_rank_grade" in body and body["min_rank_grade"] is not None:
        new_values["min_rank_grade"] = req_int(
            body, "min_rank_grade", min_v=1, max_v=9
        )
    if (
        "required_endorsement_code" in body
        and body["required_endorsement_code"] is not None
    ):
        new_values["required_endorsement_code"] = req_str(
            body, "required_endorsement_code"
        )
    if "is_critical_position" in body and body["is_critical_position"] is not None:
        new_values["is_critical_position"] = opt_bool(body, "is_critical_position")
    if "standard_tour_days" in body and body["standard_tour_days"] is not None:
        new_values["standard_tour_days"] = req_int(body, "standard_tour_days")
    # OCC (pipeline step 7).
    expected = body.get("expected_manning_slot_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err(
            "ERR_INVALID_REQUEST",
            "Field 'expected_manning_slot_version' is required and must be an integer",
        )
    if expected != s["version"]:
        raise err(
            "ERR_STALE_VERSION",
            "expected_manning_slot_version %s does not match current version %s"
            % (expected, s["version"]),
        )
    # Open-assignment embargo (pipeline step 14).
    if any(
        a["manning_slot_id"] == s["id"]
        and a["assignment_status"] in ASSIGNMENT_OPEN_STATES
        for a in store.assignments.values()
    ):
        raise err(
            "ERR_SLOT_HAS_OPEN_ASSIGNMENTS",
            "Slot has open assignments and cannot be revised",
        )
    critical_changed = (
        "is_critical_position" in new_values
        and new_values["is_critical_position"] != s["is_critical_position"]
    )
    s.update(new_values)
    store.bump(s)
    if critical_changed:
        v = _get_vessel(vessel_id)
        recompute_vessel(v)
    return success(ser_manning_slot(s))


@bp.route("/vessels/<vessel_id>/manning-slots/<slot_id>/retire", methods=["POST"])
@require_roles("PortCaptain")
def retire_slot(vessel_id, slot_id):
    v = _get_vessel(vessel_id)
    s = _get_slot_under_vessel(vessel_id, slot_id)
    if s["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE slot can be retired")
    if any(
        a["manning_slot_id"] == s["id"]
        and a["assignment_status"] in ASSIGNMENT_OPEN_STATES
        for a in store.assignments.values()
    ):
        raise err(
            "ERR_SLOT_HAS_OPEN_ASSIGNMENTS",
            "Slot has open assignments and cannot be retired",
        )
    s["status"] = "RETIRED"
    store.bump(s)
    recompute_vessel(v)
    return success(ser_manning_slot(s))


# ---------------------------------------------------------------------------
# Rotation plans
# ---------------------------------------------------------------------------


@bp.route("/vessels/<vessel_id>/rotation-plans", methods=["POST"])
@require_roles("CrewingManager")
def create_rotation_plan(vessel_id):
    v = _get_vessel(vessel_id)
    body = get_body()
    effective_from = req_dt(body, "effective_from")
    effective_to = req_dt(body, "effective_to")
    tour_days = req_int(body, "standard_tour_days")
    max_overlap = opt_int(body, "max_handover_overlap_days", default=3, min_v=0)
    if not effective_to > effective_from:
        raise err(
            "ERR_INVALID_REQUEST",
            "effective_to must be strictly later than effective_from",
        )
    # OCC (pipeline step 7) precedes the vessel state check (step 9).
    expected = body.get("expected_vessel_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err(
            "ERR_INVALID_REQUEST",
            "Field 'expected_vessel_version' is required and must be an integer",
        )
    if expected != v["version"]:
        raise err(
            "ERR_STALE_VERSION",
            "expected_vessel_version %s does not match current version %s"
            % (expected, v["version"]),
        )
    if v["status"] not in ("ACTIVE", "UNDERWAY"):
        raise err(
            "ERR_VESSEL_NOT_ACTIVE",
            "Rotation plans require the vessel to be ACTIVE or UNDERWAY",
        )
    prior = active_rotation_plan(v["id"])
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        store.bump(prior)
    p = {
        "vessel_id": v["id"],
        "effective_from": effective_from,
        "effective_to": effective_to,
        "standard_tour_days": tour_days,
        "max_handover_overlap_days": max_overlap,
        "status": "ACTIVE",
    }
    store.stamp(p)
    store.rotation_plans[p["id"]] = p
    store.bump(v)  # plan creation supersedes rotation state; vessel version +1
    return success(ser_rotation_plan(p), code=201)


@bp.route("/vessels/<vessel_id>/rotation-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_rotation_plans(vessel_id):
    v = _get_vessel(vessel_id)
    items = [p for p in store.rotation_plans.values() if p["vessel_id"] == v["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_rotation_plan(p) for p in page], response_type="array", pagination=meta
    )


@bp.route(
    "/vessels/<vessel_id>/rotation-plans/<plan_id>/archive", methods=["POST"]
)
@require_roles("CrewingManager")
def archive_rotation_plan(vessel_id, plan_id):
    _get_vessel(vessel_id)
    p = _get_plan_under_vessel(vessel_id, plan_id)
    if p["status"] != "SUPERSEDED":
        raise err(
            "ERR_INVALID_STATE", "Only a SUPERSEDED rotation plan can be archived"
        )
    p["status"] = "ARCHIVED"
    store.bump(p)
    return success(ser_rotation_plan(p))
