"""ArtifactCase endpoints: design, placements, conservation ruling and mount making
(PRD §3.4, §3.5)."""

from flask import Blueprint

import calc
import cascades
import helpers
import serializers
from auth import (ALL_ROLES, ROLE_CONSERVATOR, ROLE_CURATOR, ROLE_PROJECT_MANAGER, endpoint)
from envelope import list_response, object_response, pagination, query_filter
from errors import ApiError
from helpers import touch
from store import db, new_row
from validate import bad, body_object, v_enum, v_id, v_int, v_num, v_str

bp = Blueprint("cases", __name__)

SECURITY_TIERS = ("BASIC", "ENHANCED", "HIGH_VALUE")
CASE_DECISIONS = ("APPROVE", "APPROVE_WITH_CONDITIONS", "REJECT")


@bp.route("/exhibit-projects/<pid>/artifact-cases", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER, ROLE_CURATOR])
def create_case(pid):
    project = helpers.get_project(pid)
    body = body_object()
    zone_id = v_id(body, "zone_id")
    case_code = v_str(body, "case_code", 1, 40)
    objective_code = v_str(body, "objective_code", 1, None, required=False, default=None)
    security_tier = v_enum(body, "security_tier", SECURITY_TIERS)
    target_rh = v_num(body, "target_rh_pct", gt=0, lt=100)
    rh_tolerance = v_num(body, "rh_tolerance_pct", ge=0, le=20)
    target_lux = v_num(body, "target_lux", ge=0)
    uv = v_num(body, "uv_microwatt_per_lumen", ge=0)
    length = v_num(body, "interior_l_cm", gt=0)
    width = v_num(body, "interior_w_cm", gt=0)
    height = v_num(body, "interior_h_cm", gt=0)
    exchanges = v_num(body, "air_exchanges_per_day", gt=0)
    if objective_code is not None and objective_code not in project["objective_codes"]:
        # A code outside the commission's declared objectives is a malformed request.
        bad("objective_code must name one of the project's objective_codes.")

    zone = helpers.get_zone(zone_id)
    helpers.require_same_project(project, zone)
    helpers.require_unique(db.cases, project["id"], "case_code", case_code)
    # Step 10: cases may be designed only in SCHEMATIC or DESIGN_DEV.
    helpers.require_phase(project, ("SCHEMATIC", "DESIGN_DEV"))

    case = new_row("cases", {
        "project_id": project["id"],
        "zone_id": zone["id"],
        "case_code": case_code,
        "objective_code": objective_code,
        "security_tier": security_tier,
        "target_rh_pct": target_rh,
        "rh_tolerance_pct": rh_tolerance,
        "target_lux": target_lux,
        "uv_microwatt_per_lumen": uv,
        "interior_l_cm": length,
        "interior_w_cm": width,
        "interior_h_cm": height,
        "air_exchanges_per_day": exchanges,
        "status": "DRAFT",
        "mount_status": "NOT_STARTED",
        "conditions": None,
        "decided_at": None,
    })
    db.cases[case["id"]] = case
    # Designing a case does not touch the zone's slot counters.
    return object_response(serializers.case_json(case), 201)


@bp.route("/exhibit-projects/<pid>/artifact-cases", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_cases(pid):
    project = helpers.get_project(pid)
    limit, offset = pagination()
    status = query_filter("status")
    mount_status = query_filter("mount_status")
    zone_id = query_filter("zone_id")
    rows = helpers.rows_of_project(db.cases, project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if mount_status is not None:
        rows = [r for r in rows if r["mount_status"] == mount_status]
    if zone_id is not None:
        rows = [r for r in rows if r["zone_id"] == zone_id]
    return list_response(rows, serializers.case_json, limit, offset)


@bp.route("/artifact-cases/<case_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def get_case(case_id):
    case = helpers.get_case(case_id)
    return object_response(serializers.case_json(case))


@bp.route("/artifact-cases/<case_id>/placements", methods=["POST"])
@endpoint(roles=[ROLE_CURATOR, ROLE_CONSERVATOR])
def create_placement(case_id):
    case = helpers.get_case(case_id)
    project = helpers.owning_project(case)
    body = body_object()
    expected_case_version = v_int(body, "expected_case_version")
    artifact_id = v_id(body, "artifact_id")

    artifact = helpers.get_artifact(artifact_id)
    helpers.require_same_project(project, artifact)

    # Step 7: optimistic concurrency on the case version.
    if expected_case_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")
    # Step 11: reserving an object into a case is one of the frozen-blocked operations.
    helpers.require_not_frozen(project)
    # Step 12: the case's conservation status.
    if case["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_CASE_STATE")
    # Step 13: the placement chain, in the stated order.
    if artifact["placement_status"] != "UNPLACED":
        raise ApiError("ERR_ARTIFACT_ALREADY_PLACED")
    if artifact["condition_status"] == "UNSTABLE":
        raise ApiError("ERR_ARTIFACT_CONDITION_UNSTABLE")
    if calc.SECURITY_RANK[case["security_tier"]] < calc.SECURITY_RANK[artifact["security_class"]]:
        raise ApiError("ERR_SECURITY_TIER_INSUFFICIENT")
    # The envelope is recomputed WITH the incoming object included.
    envelope = helpers.case_envelope_of(case, extra=artifact)
    if not envelope["env_feasible"]:
        raise ApiError("ERR_ENV_ENVELOPE_INFEASIBLE")

    artifact["assigned_case_id"] = case["id"]
    artifact["placement_status"] = "RESERVED"
    touch(artifact)
    touch(case)
    # The response is the updated object, not the case.
    return object_response(serializers.artifact_json(artifact), 201)


@bp.route("/artifact-cases/<case_id>/placements", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_placements(case_id):
    case = helpers.get_case(case_id)
    limit, offset = pagination()
    placement_status = query_filter("placement_status")
    rows = helpers.artifacts_assigned_to_case(case["id"])
    if placement_status is not None:
        rows = [r for r in rows if r["placement_status"] == placement_status]
    return list_response(rows, serializers.artifact_json, limit, offset)


@bp.route("/artifact-cases/<case_id>/placements/<artifact_id>", methods=["DELETE"])
@endpoint(roles=[ROLE_CURATOR, ROLE_CONSERVATOR])
def delete_placement(case_id, artifact_id):
    case = helpers.get_case(case_id)
    artifact = helpers.get_artifact(artifact_id)
    project = helpers.owning_project(case)
    helpers.require_same_project(project, artifact)

    if (artifact["assigned_case_id"] != case["id"]
            or artifact["placement_status"] not in ("RESERVED", "PLACED")):
        raise ApiError("ERR_ARTIFACT_NOT_IN_CASE")

    if artifact["placement_status"] == "RESERVED":
        # The reservation is released and the object returns to the unplaced pool.
        artifact["placement_status"] = "UNPLACED"
        artifact["assigned_case_id"] = None
    else:
        # A physically installed object is de-installed and keeps its case for the record.
        artifact["placement_status"] = "DEINSTALLED"
    touch(artifact)
    touch(case)
    return object_response(serializers.artifact_json(artifact))


@bp.route("/artifact-cases/<case_id>/submit-for-conservation", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER, ROLE_CURATOR])
def submit_case(case_id):
    case = helpers.get_case(case_id)
    project = helpers.owning_project(case)
    # Step 11: a frozen project refuses the submission outright.  §3.5: the rework
    # path opens once every *other* conservation block has cleared, so this case's
    # own rejection is not counted against it.
    helpers.require_not_frozen(project, exclude_case_id=case["id"])
    # Step 12.
    if case["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_CASE_STATE")
    # Step 13: an empty case has no envelope to review.
    if helpers.placed_artifact_count(case) < 1:
        raise ApiError("ERR_CASE_HAS_NO_ARTIFACTS")

    # Submitting from REJECTED clears that rejection's conservation block; because the
    # counter is derived from case status, leaving REJECTED performs the decrement.
    case["status"] = "CONSERVATOR_REVIEW"
    touch(case)
    return object_response(serializers.case_json(case))


@bp.route("/artifact-cases/<case_id>/conservator-decision", methods=["POST"])
@endpoint(roles=[ROLE_CONSERVATOR])
def decide_case(case_id):
    case = helpers.get_case(case_id)
    body = body_object()
    decision = v_enum(body, "decision", CASE_DECISIONS)
    conditions = v_str(body, "conditions", None, None, required=False, default=None)
    if decision == "APPROVE_WITH_CONDITIONS" and (conditions is None or conditions.strip() == ""):
        bad("A conditional approval requires a non-blank 'conditions' string.")

    # Step 12: the case must be under review.
    if case["status"] != "CONSERVATOR_REVIEW":
        raise ApiError("ERR_INVALID_CASE_STATE")

    zone = db.zones.get(case["zone_id"], None)
    if decision in ("APPROVE", "APPROVE_WITH_CONDITIONS"):
        # Step 13, in the order §3.5 states: envelope, security, then the slot pool.
        envelope = helpers.case_envelope_of(case)
        if not envelope["env_feasible"]:
            raise ApiError("ERR_ENV_ENVELOPE_INFEASIBLE")
        if not envelope["security_ok"]:
            raise ApiError("ERR_SECURITY_TIER_INSUFFICIENT")
        if zone is None or helpers.zone_available_slots(zone) < 1:
            raise ApiError("ERR_ZONE_CASE_SLOTS_EXHAUSTED")
        if decision == "APPROVE":
            case["status"] = "APPROVED"
            case["conditions"] = None
        else:
            case["status"] = "CONDITIONALLY_APPROVED"
            case["conditions"] = conditions
        # The zone reserves the slot; capacity == reserved + available is preserved.
        touch(zone)
    else:
        # A conservator may always refuse: no envelope or slot precondition at all.
        case["status"] = "REJECTED"
        cascades.release_reserved_objects(case)

    case["decided_at"] = db.now()
    touch(case)
    touch(helpers.owning_project(case))
    return object_response(serializers.case_json(case))


@bp.route("/artifact-cases/<case_id>/mount-advance", methods=["POST"])
@endpoint(roles=[ROLE_CONSERVATOR])
def mount_advance(case_id):
    case = helpers.get_case(case_id)
    project = helpers.owning_project(case)
    body = body_object()
    destination = v_enum(body, "to_mount_status", helpers.MOUNT_LADDER)

    # Step 10: only the installation step carries a phase requirement.
    if destination == "MOUNT_INSTALLED":
        helpers.require_phase(project, ("INSTALLATION",))
    # Step 11: mount advance is one of the operations the conservation freeze blocks.
    helpers.require_not_frozen(project)
    # Step 12: the destination must be the immediate successor of the stored value.
    if helpers.MOUNT_SUCCESSOR.get(case["mount_status"], None) != destination:
        raise ApiError("ERR_INVALID_MOUNT_STATE")
    # Step 12: the three couplings to the conservation dimension.
    if destination == "MOUNT_DESIGN":
        if case["status"] not in ("CONSERVATOR_REVIEW", "CONDITIONALLY_APPROVED", "APPROVED"):
            raise ApiError("ERR_INVALID_CASE_STATE")
    else:
        if case["status"] not in ("APPROVED", "CONDITIONALLY_APPROVED"):
            raise ApiError("ERR_INVALID_CASE_STATE")
    if destination == "MOUNT_FABRICATED":
        cleared = [d for d in helpers.drawings_of_case(case["id"])
                   if d["status"] in ("APPROVED", "APPROVED_AS_NOTED")]
        if not cleared:
            raise ApiError("ERR_INVALID_MOUNT_STATE",
                           "No shop drawing detailing this case has been cleared.")
    if destination == "MOUNT_INSTALLED":
        # A window running on a sibling zone of the same project does not unlock the mount.
        running = [w for w in helpers.windows_of_zone(case["zone_id"])
                   if w["status"] == "IN_PROGRESS"]
        if not running:
            raise ApiError("ERR_INVALID_WINDOW_STATE")

    case["mount_status"] = destination
    touch(case)
    return object_response(serializers.case_json(case))
