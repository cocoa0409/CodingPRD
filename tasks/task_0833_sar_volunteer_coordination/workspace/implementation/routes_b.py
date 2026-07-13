"""Routes: callouts, resources, resource-assignments, ground-tracks, clues,
reimbursement-claims, after-action-reports."""
from datetime import timedelta

from flask import Blueprint

import store
import calc
import cascades
from serializers import serialize
from errors import ApiError
from core import (
    auth, get_or_404, body_json, ok, created, paginate_and_respond,
    vstr, venum, vnum, vint, vbool, vdt, vfk,
)

bp = Blueprint("routes_b", __name__)

ALL_ROLES = {"Coordinator", "IncidentCommander", "FinanceOfficer", "Member"}
RESOURCE_TYPES = {"K9", "HELICOPTER", "FIXED_WING", "DRONE", "UTV", "BOAT"}
CLUE_PRIORITIES = {"URGENT", "SIGNIFICANT", "ROUTINE"}
CALLOUT_NON_TERMINAL = {"REQUESTED", "ACKNOWLEDGED", "STANDBY", "DEPLOYED"}
REST_BUFFER = timedelta(minutes=calc.MEMBER_REST_BUFFER_MIN)


def require_state(rec, allowed):
    if rec["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE")


def require_owner(role, uid, member_id):
    """Ownership check applies only to the entity-backed Member role."""
    if role == "Member" and member_id != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER")


# =========================================================================
# Callouts
# =========================================================================
@bp.route("/sar/callouts", methods=["POST"])
def create_callout():
    auth({"Coordinator", "IncidentCommander"})
    d = body_json()
    rec = store.base_record("Callout")
    rec["task_id"] = vfk(d, "task_id", store.tasks)
    rec["member_id"] = vfk(d, "member_id", store.members)
    # Capacity: non-terminal callouts on the task must be below max_responders.
    task = store.tasks[rec["task_id"]]
    active = sum(
        1 for c in store.callouts.values()
        if c["task_id"] == rec["task_id"] and c["status"] in CALLOUT_NON_TERMINAL
    )
    if active >= task["max_responders"]:
        raise ApiError("ERR_TASK_AT_CAPACITY")
    rec["status"] = "REQUESTED"
    rec["requested_at"] = store.clock_iso()
    rec["deployed_at"] = None
    store.callouts[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/sar/callouts/<callout_id>", methods=["GET"])
def get_callout(callout_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.callouts, callout_id)))


@bp.route("/sar/callouts", methods=["GET"])
def list_callouts():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.callouts.values(), serialize,
        [("task_id", "task_id"), ("member_id", "member_id"), ("status", "status")],
    )


@bp.route("/sar/callouts/<callout_id>/acknowledge", methods=["POST"])
def acknowledge_callout(callout_id):
    uid, role = auth({"Member"})
    co = get_or_404(store.callouts, callout_id)
    require_owner(role, uid, co["member_id"])
    require_state(co, {"REQUESTED"})
    co["status"] = "ACKNOWLEDGED"
    store.mutate(co)
    return ok(serialize(co))


@bp.route("/sar/callouts/<callout_id>/decline", methods=["POST"])
def decline_callout(callout_id):
    uid, role = auth({"Member"})
    co = get_or_404(store.callouts, callout_id)
    require_owner(role, uid, co["member_id"])
    require_state(co, {"REQUESTED", "ACKNOWLEDGED"})
    co["status"] = "DECLINED"
    store.mutate(co)
    return ok(serialize(co))


@bp.route("/sar/callouts/<callout_id>/standby", methods=["POST"])
def standby_callout(callout_id):
    auth({"Coordinator", "IncidentCommander"})
    co = get_or_404(store.callouts, callout_id)
    require_state(co, {"ACKNOWLEDGED"})
    member = store.members.get(co["member_id"])
    team = store.teams.get(member["team_id"]) if member else None
    if team is None or team["status"] != "ACTIVE":
        raise ApiError("ERR_TEAM_INACTIVE")
    co["status"] = "STANDBY"
    store.mutate(co)
    if not cascades.member_has_other_deployed(member["id"], None):
        if member["status"] != "STANDBY":
            member["status"] = "STANDBY"
            store.mutate(member)
    return ok(serialize(co))


@bp.route("/sar/callouts/<callout_id>/deploy", methods=["POST"])
def deploy_callout(callout_id):
    auth({"Coordinator", "IncidentCommander"})
    co = get_or_404(store.callouts, callout_id)
    require_state(co, {"STANDBY"})
    task = store.tasks.get(co["task_id"])
    if task is None or task["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        raise ApiError("ERR_TASK_NOT_READY")
    member_id = co["member_id"]
    # Certification currency
    required = task["required_cert_types"]
    if required:
        valid_types = {
            c["cert_type"] for c in store.certifications.values()
            if c["member_id"] == member_id and calc.cert_status(c) == "VALID"
        }
        for req in required:
            if req not in valid_types:
                raise ApiError("ERR_CERT_REQUIREMENT_NOT_MET")
    # Double-booking within the rest buffer
    this_start = store.parse_dt(task["planned_start"])
    this_end = store.parse_dt(task["planned_end"])
    for other in store.callouts.values():
        if (other["member_id"] == member_id and other["status"] == "DEPLOYED"
                and other["id"] != co["id"]):
            ot = store.tasks.get(other["task_id"])
            if ot is None:
                continue
            os_ = store.parse_dt(ot["planned_start"])
            oe = store.parse_dt(ot["planned_end"])
            if this_start < oe + REST_BUFFER and os_ < this_end + REST_BUFFER:
                raise ApiError("ERR_MEMBER_DOUBLE_BOOKED")
    co["status"] = "DEPLOYED"
    co["deployed_at"] = store.clock_iso()
    store.mutate(co)
    member = store.members.get(member_id)
    if member is not None:
        member["status"] = "DEPLOYED"
        store.mutate(member)
    return ok(serialize(co))


@bp.route("/sar/callouts/<callout_id>/demobilize", methods=["POST"])
def demobilize_callout(callout_id):
    auth({"Coordinator", "IncidentCommander"})
    co = get_or_404(store.callouts, callout_id)
    require_state(co, {"DEPLOYED"})
    co["status"] = "DEMOBILIZED"
    store.mutate(co)
    cascades.restore_member_if_free(co["member_id"], co["id"])
    return ok(serialize(co))


# =========================================================================
# Resources
# =========================================================================
@bp.route("/sar/resources", methods=["POST"])
def create_resource():
    auth({"Coordinator"})
    d = body_json()
    rec = store.base_record("Resource")
    rec["name"] = vstr(d, "name")
    rec["resource_type"] = venum(d, "resource_type", RESOURCE_TYPES)
    rec["handler_member_id"] = vfk(d, "handler_member_id", store.members, required=False, default=None)
    if rec["resource_type"] == "K9" and rec["handler_member_id"] is None:
        raise ApiError("ERR_VALIDATION")
    rec["out_of_service"] = False
    rec["active_assignment_count"] = 0
    store.resources[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/sar/resources/<resource_id>", methods=["GET"])
def get_resource(resource_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.resources, resource_id)))


@bp.route("/sar/resources", methods=["GET"])
def list_resources():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.resources.values(), serialize,
        [("handler_member_id", "handler_member_id"), ("resource_type", "resource_type"),
         ("status", "status")],
    )


@bp.route("/sar/resources/<resource_id>/set-status", methods=["POST"])
def set_resource_status(resource_id):
    auth({"Coordinator"})
    res = get_or_404(store.resources, resource_id)
    d = body_json()
    res["out_of_service"] = vbool(d, "out_of_service")
    store.mutate(res)
    return ok(serialize(res))


# =========================================================================
# Resource assignments
# =========================================================================
@bp.route("/sar/resource-assignments", methods=["POST"])
def create_resource_assignment():
    auth({"Coordinator", "IncidentCommander"})
    d = body_json()
    resource_id = vfk(d, "resource_id", store.resources)
    task_id = vfk(d, "task_id", store.tasks)
    window_start = vdt(d, "window_start")
    window_end = vdt(d, "window_end")
    expected_version = vint(d, "expected_resource_version")
    ws = store.parse_dt(window_start)
    we = store.parse_dt(window_end)
    if we <= ws:
        raise ApiError("ERR_VALIDATION")
    resource = store.resources[resource_id]
    # Sibling state: resource must be in service.
    if resource["out_of_service"]:
        raise ApiError("ERR_RESOURCE_UNAVAILABLE")
    # Temporal: half-open window overlap against RESERVED/ACTIVE assignments.
    for a in store.resource_assignments.values():
        if a["resource_id"] == resource_id and a["status"] in ("RESERVED", "ACTIVE"):
            a_start = store.parse_dt(a["window_start"])
            a_end = store.parse_dt(a["window_end"])
            if ws < a_end and a_start < we:
                raise ApiError("ERR_RESOURCE_WINDOW_CONFLICT")
    # OCC (checked last).
    if expected_version != resource["version"]:
        raise ApiError("ERR_STALE_VERSION")
    rec = store.base_record("ResourceAssignment")
    rec["resource_id"] = resource_id
    rec["task_id"] = task_id
    rec["window_start"] = window_start
    rec["window_end"] = window_end
    rec["status"] = "RESERVED"
    store.resource_assignments[rec["id"]] = rec
    resource["active_assignment_count"] += 1
    store.mutate(resource)
    return created(serialize(rec))


@bp.route("/sar/resource-assignments/<assignment_id>", methods=["GET"])
def get_resource_assignment(assignment_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.resource_assignments, assignment_id)))


@bp.route("/sar/resource-assignments", methods=["GET"])
def list_resource_assignments():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.resource_assignments.values(), serialize,
        [("resource_id", "resource_id"), ("task_id", "task_id"), ("status", "status")],
    )


@bp.route("/sar/resource-assignments/<assignment_id>/activate", methods=["POST"])
def activate_resource_assignment(assignment_id):
    auth({"Coordinator", "IncidentCommander"})
    a = get_or_404(store.resource_assignments, assignment_id)
    require_state(a, {"RESERVED"})
    task = store.tasks.get(a["task_id"])
    if task is None or task["status"] != "IN_PROGRESS":
        raise ApiError("ERR_TASK_NOT_READY")
    a["status"] = "ACTIVE"
    store.mutate(a)
    return ok(serialize(a))


@bp.route("/sar/resource-assignments/<assignment_id>/release", methods=["POST"])
def release_resource_assignment(assignment_id):
    auth({"Coordinator", "IncidentCommander"})
    a = get_or_404(store.resource_assignments, assignment_id)
    require_state(a, {"ACTIVE"})
    a["status"] = "RELEASED"
    store.mutate(a)
    cascades.dec_resource(a["resource_id"])
    return ok(serialize(a))


@bp.route("/sar/resource-assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_resource_assignment(assignment_id):
    auth({"Coordinator", "IncidentCommander"})
    a = get_or_404(store.resource_assignments, assignment_id)
    require_state(a, {"RESERVED"})
    a["status"] = "CANCELLED"
    store.mutate(a)
    cascades.dec_resource(a["resource_id"])
    return ok(serialize(a))


# =========================================================================
# Ground tracks (append-only)
# =========================================================================
@bp.route("/sar/ground-tracks", methods=["POST"])
def create_ground_track():
    uid, role = auth({"Coordinator", "Member"})
    d = body_json()
    task_id = vfk(d, "task_id", store.tasks)
    member_id = vfk(d, "member_id", store.members)
    recorded_at = vdt(d, "recorded_at")
    distance_km = vnum(d, "distance_km", ge=0)
    duration_min = vint(d, "duration_min", ge=0)
    coverage_area_sqkm = vnum(d, "coverage_area_sqkm", ge=0)
    require_owner(role, uid, member_id)
    rec = store.base_record("GroundTrack", common=False)
    rec["task_id"] = task_id
    rec["member_id"] = member_id
    rec["recorded_at"] = recorded_at
    rec["distance_km"] = distance_km
    rec["duration_min"] = duration_min
    rec["coverage_area_sqkm"] = coverage_area_sqkm
    store.ground_tracks[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/sar/ground-tracks/<ground_track_id>", methods=["GET"])
def get_ground_track(ground_track_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.ground_tracks, ground_track_id)))


@bp.route("/sar/ground-tracks", methods=["GET"])
def list_ground_tracks():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.ground_tracks.values(), serialize,
        [("task_id", "task_id"), ("member_id", "member_id")],
    )


# =========================================================================
# Clues
# =========================================================================
@bp.route("/sar/clues", methods=["POST"])
def create_clue():
    auth({"Coordinator", "IncidentCommander", "Member"})
    d = body_json()
    rec = store.base_record("Clue")
    rec["incident_id"] = vfk(d, "incident_id", store.incidents)
    rec["task_id"] = vfk(d, "task_id", store.tasks, required=False, default=None)
    rec["clue_number"] = vstr(d, "clue_number")
    rec["clue_priority"] = venum(d, "clue_priority", CLUE_PRIORITIES, required=False, default="ROUTINE")
    rec["description"] = vstr(d, "description")
    rec["found_at"] = vdt(d, "found_at")
    rec["status"] = "LOGGED"
    store.clues[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/sar/clues/<clue_id>", methods=["GET"])
def get_clue(clue_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.clues, clue_id)))


@bp.route("/sar/clues", methods=["GET"])
def list_clues():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.clues.values(), serialize,
        [("incident_id", "incident_id"), ("task_id", "task_id"),
         ("status", "status"), ("clue_priority", "clue_priority")],
    )


@bp.route("/sar/clues/<clue_id>/promote", methods=["POST"])
def promote_clue(clue_id):
    auth({"IncidentCommander"})
    clue = get_or_404(store.clues, clue_id)
    require_state(clue, {"LOGGED"})
    clue["status"] = "ACTIONABLE"
    store.mutate(clue)
    return ok(serialize(clue))


@bp.route("/sar/clues/<clue_id>/dismiss", methods=["POST"])
def dismiss_clue(clue_id):
    auth({"IncidentCommander"})
    clue = get_or_404(store.clues, clue_id)
    require_state(clue, {"LOGGED", "ACTIONABLE"})
    clue["status"] = "DISMISSED"
    store.mutate(clue)
    return ok(serialize(clue))


@bp.route("/sar/clues/<clue_id>/resolve", methods=["POST"])
def resolve_clue(clue_id):
    auth({"IncidentCommander"})
    clue = get_or_404(store.clues, clue_id)
    require_state(clue, {"ACTIONABLE"})
    clue["status"] = "RESOLVED"
    store.mutate(clue)
    return ok(serialize(clue))


# =========================================================================
# Reimbursement claims
# =========================================================================
@bp.route("/sar/reimbursement-claims", methods=["POST"])
def create_claim():
    uid, role = auth({"Coordinator", "Member"})
    d = body_json()
    rec = store.base_record("ReimbursementClaim")
    rec["member_id"] = vfk(d, "member_id", store.members)
    rec["incident_id"] = vfk(d, "incident_id", store.incidents)
    rec["declared_mileage_miles"] = vint(d, "declared_mileage_miles", ge=0)
    rec["meal_count"] = vint(d, "meal_count", required=False, default=0, ge=0)
    rec["lodging_nights"] = vint(d, "lodging_nights", required=False, default=0, ge=0)
    require_owner(role, uid, rec["member_id"])
    # Uniqueness: at most one non-REJECTED claim per (member, incident).
    for c in store.claims.values():
        if (c["member_id"] == rec["member_id"] and c["incident_id"] == rec["incident_id"]
                and c["status"] != "REJECTED"):
            raise ApiError("ERR_DUPLICATE_CLAIM")
    rec["status"] = "DRAFT"
    rec["estimated_amount_cents"] = None
    rec["final_amount_cents"] = None
    store.claims[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/sar/reimbursement-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.claims, claim_id)))


@bp.route("/sar/reimbursement-claims", methods=["GET"])
def list_claims():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.claims.values(), serialize,
        [("member_id", "member_id"), ("incident_id", "incident_id"), ("status", "status")],
    )


@bp.route("/sar/reimbursement-claims/<claim_id>/submit", methods=["POST"])
def submit_claim(claim_id):
    uid, role = auth({"Member"})
    claim = get_or_404(store.claims, claim_id)
    require_owner(role, uid, claim["member_id"])
    require_state(claim, {"DRAFT", "RETURNED"})
    claim["estimated_amount_cents"] = calc.reimbursement_cents(
        claim["declared_mileage_miles"], claim["meal_count"], claim["lodging_nights"])
    claim["status"] = "SUBMITTED"
    store.mutate(claim)
    return ok(serialize(claim))


@bp.route("/sar/reimbursement-claims/<claim_id>/return", methods=["POST"])
def return_claim(claim_id):
    auth({"FinanceOfficer"})
    claim = get_or_404(store.claims, claim_id)
    require_state(claim, {"SUBMITTED"})
    claim["status"] = "RETURNED"
    store.mutate(claim)
    return ok(serialize(claim))


@bp.route("/sar/reimbursement-claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    auth({"FinanceOfficer"})
    claim = get_or_404(store.claims, claim_id)
    require_state(claim, {"SUBMITTED"})
    incident = store.incidents.get(claim["incident_id"])
    if incident is None or incident["status"] not in ("DEMOBILIZING", "CLOSED"):
        raise ApiError("ERR_INCIDENT_NOT_DEMOBILIZING")
    reconciled = calc.reconciled_mileage_miles(claim["member_id"], claim["incident_id"])
    claim["final_amount_cents"] = calc.reimbursement_cents(
        reconciled, claim["meal_count"], claim["lodging_nights"])
    claim["status"] = "APPROVED"
    store.mutate(claim)
    incident["total_approved_reimbursement_cents"] += claim["final_amount_cents"]
    store.mutate(incident)
    return ok(serialize(claim))


@bp.route("/sar/reimbursement-claims/<claim_id>/reject", methods=["POST"])
def reject_claim(claim_id):
    auth({"FinanceOfficer"})
    claim = get_or_404(store.claims, claim_id)
    require_state(claim, {"SUBMITTED", "APPROVED"})
    was_approved = claim["status"] == "APPROVED"
    claim["status"] = "REJECTED"
    store.mutate(claim)
    if was_approved:
        incident = store.incidents.get(claim["incident_id"])
        if incident is not None:
            incident["total_approved_reimbursement_cents"] -= claim["final_amount_cents"]
            store.mutate(incident)
    return ok(serialize(claim))


@bp.route("/sar/reimbursement-claims/<claim_id>/pay", methods=["POST"])
def pay_claim(claim_id):
    auth({"FinanceOfficer"})
    claim = get_or_404(store.claims, claim_id)
    require_state(claim, {"APPROVED"})
    claim["status"] = "PAID"
    store.mutate(claim)
    return ok(serialize(claim))


# =========================================================================
# After-action reports
# =========================================================================
@bp.route("/sar/after-action-reports", methods=["POST"])
def create_aar():
    auth({"Coordinator", "IncidentCommander"})
    d = body_json()
    rec = store.base_record("AfterActionReport")
    rec["incident_id"] = vfk(d, "incident_id", store.incidents)
    rec["summary"] = vstr(d, "summary")
    ll = d.get("lessons_learned", "")
    if ll is None:
        ll = ""
    if not isinstance(ll, str):
        raise ApiError("ERR_VALIDATION")
    rec["lessons_learned"] = ll
    rec["status"] = "DRAFT"
    store.aars[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/sar/after-action-reports/<aar_id>", methods=["GET"])
def get_aar(aar_id):
    auth(ALL_ROLES)
    return ok(serialize(get_or_404(store.aars, aar_id)))


@bp.route("/sar/after-action-reports", methods=["GET"])
def list_aars():
    auth(ALL_ROLES)
    return paginate_and_respond(
        store.aars.values(), serialize,
        [("incident_id", "incident_id"), ("status", "status")],
    )


@bp.route("/sar/after-action-reports/<aar_id>/finalize", methods=["POST"])
def finalize_aar(aar_id):
    auth({"IncidentCommander"})
    aar = get_or_404(store.aars, aar_id)
    require_state(aar, {"DRAFT"})
    incident = store.incidents.get(aar["incident_id"])
    if incident is None or incident["status"] != "CLOSED":
        raise ApiError("ERR_INCIDENT_NOT_CLOSED")
    aar["status"] = "FINALIZED"
    store.mutate(aar)
    return ok(serialize(aar))
