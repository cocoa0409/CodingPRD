"""PartOrder, RobotInspection, ComplianceViolation, TravelBooking (PRD 3.3, 3.4, 3.8)."""
from flask import Blueprint, request

from auth import require_roles
from db import store, stamp_new, touch, now
from envelope import success, paginated
from errors import (
    ApiError,
    ERR_BUDGET_EXCEEDED,
    ERR_BUMPERS_NONCOMPLIANT,
    ERR_EVENT_WRONG_STATUS,
    ERR_FRAME_TOO_LARGE,
    ERR_INSPECTOR_NOT_CLEARED,
    ERR_INSPECTOR_SELF,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MILESTONE_MISSING,
    ERR_NOT_BUILD_SEASON,
    ERR_NOT_QUALIFIED,
    ERR_PERSON_NOT_FOUND,
    ERR_REIMBURSEMENT_CAP_EXCEEDED,
    ERR_ROBOT_OVERWEIGHT,
    ERR_SEGREGATION_VIOLATION,
    ERR_STOP_BUILD_PASSED,
)
from services import (
    MAX_FRAME_PERIMETER_CM,
    MAX_ROBOT_WEIGHT_KG,
    MODE_CAPS,
    compute_reimbursement,
    milestones_of_event,
    recompute_counts,
    recompute_posture,
)
from util import (
    TERMINAL,
    check_from_state,
    gate_posture,
    get_body,
    public,
    req_bool,
    req_dt,
    req_enum,
    req_int,
    req_num,
    req_str,
    resolve_event,
    resolve_team,
    resolve_order,
    resolve_inspection,
    resolve_violation,
    resolve_booking,
)

bp = Blueprint("procurement", __name__)

# ---------------------------------------------------------------------------
# PartOrder
# ---------------------------------------------------------------------------

ORDER_GET_ROLES = ("EventDirector", "TeamLead", "ProcurementOfficer")


@bp.route("/frc-events/<eventId>/teams/<teamId>/part-orders", methods=["POST"])
def create_part_order(eventId, teamId):
    user_id, _ = require_roles("TeamLead")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    gate_posture(event)
    body = get_body()
    sku = req_str(body, "sku")
    quantity = req_int(body, "quantity", minimum=1)
    unit_cost_cents = req_int(body, "unit_cost_cents", minimum=0)
    order = {
        "team_id": teamId,
        "event_id": eventId,
        "sku": sku,
        "quantity": quantity,
        "unit_cost_cents": unit_cost_cents,
        "status": "DRAFT",
        "submitted_at": None,
        "order_total_cents": quantity * unit_cost_cents,
        "_created_by": user_id,
        "_submitted_by": None,
    }
    stamp_new(order)
    store.part_orders[order["id"]] = order
    return success(public(order), code=201)


@bp.route("/frc-events/<eventId>/teams/<teamId>/part-orders", methods=["GET"])
def list_part_orders(eventId, teamId):
    require_roles(*ORDER_GET_ROLES)
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    items = [o for o in store.part_orders.values() if o["team_id"] == team["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/teams/<teamId>/part-orders/<orderId>", methods=["GET"])
def get_part_order(eventId, teamId, orderId):
    require_roles(*ORDER_GET_ROLES)
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    order = resolve_order(team, orderId)
    return success(public(order))


@bp.route("/frc-events/<eventId>/teams/<teamId>/part-orders/<orderId>/submit", methods=["POST"])
def submit_part_order(eventId, teamId, orderId):
    user_id, _ = require_roles("TeamLead")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    order = resolve_order(team, orderId)
    if event["status"] != "BUILD_SEASON":
        raise ApiError(ERR_NOT_BUILD_SEASON, 409, "Part orders may only be submitted during BUILD_SEASON")
    gate_posture(event)
    check_from_state(order, "status", "DRAFT", TERMINAL["PartOrder"], "PartOrder")
    stop_build = [m for m in milestones_of_event(eventId) if m["kind"] == "STOP_BUILD"]
    if not stop_build:
        raise ApiError(ERR_MILESTONE_MISSING, 409, "STOP_BUILD milestone is missing")
    deadline = min(m["scheduled_at"] for m in stop_build)
    if now() > deadline:
        raise ApiError(ERR_STOP_BUILD_PASSED, 422, "STOP_BUILD deadline has passed")
    if team["registration_status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, 409, "Team must be CONFIRMED to submit part orders")
    order["status"] = "SUBMITTED"
    order["submitted_at"] = now()
    order["order_total_cents"] = order["quantity"] * order["unit_cost_cents"]
    order["_submitted_by"] = user_id
    touch(order)
    return success(public(order))


@bp.route("/frc-events/<eventId>/teams/<teamId>/part-orders/<orderId>/approve", methods=["POST"])
def approve_part_order(eventId, teamId, orderId):
    user_id, _ = require_roles("ProcurementOfficer")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    order = resolve_order(team, orderId)
    gate_posture(event)
    check_from_state(order, "status", "SUBMITTED", TERMINAL["PartOrder"], "PartOrder")
    submitter = order.get("_submitted_by") or order.get("_created_by")
    if submitter is not None and user_id == submitter:
        raise ApiError(ERR_SEGREGATION_VIOLATION, 403, "ProcurementOfficer cannot approve an order they submitted")
    cap = event.get("budget_cap_cents")
    if cap is not None:
        approved_spend = sum(
            o["order_total_cents"]
            for o in store.part_orders.values()
            if o["team_id"] == teamId and o["status"] in ("APPROVED", "VENDOR_PLACED", "RECEIVED")
        )
        if approved_spend + order["order_total_cents"] > cap:
            raise ApiError(ERR_BUDGET_EXCEEDED, 402, "Order exceeds the team's build-season budget cap")
    order["status"] = "APPROVED"
    touch(order)
    return success(public(order))


@bp.route("/frc-events/<eventId>/teams/<teamId>/part-orders/<orderId>/reject", methods=["POST"])
def reject_part_order(eventId, teamId, orderId):
    require_roles("ProcurementOfficer")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    order = resolve_order(team, orderId)
    gate_posture(event)
    check_from_state(order, "status", "SUBMITTED", TERMINAL["PartOrder"], "PartOrder")
    order["status"] = "REJECTED"
    touch(order)
    return success(public(order))


@bp.route("/frc-events/<eventId>/teams/<teamId>/part-orders/<orderId>/place-with-vendor", methods=["POST"])
def place_part_order(eventId, teamId, orderId):
    require_roles("ProcurementOfficer")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    order = resolve_order(team, orderId)
    gate_posture(event)
    check_from_state(order, "status", "APPROVED", TERMINAL["PartOrder"], "PartOrder")
    order["status"] = "VENDOR_PLACED"
    touch(order)
    return success(public(order))


@bp.route("/frc-events/<eventId>/teams/<teamId>/part-orders/<orderId>/receive", methods=["POST"])
def receive_part_order(eventId, teamId, orderId):
    require_roles("TeamLead")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    order = resolve_order(team, orderId)
    gate_posture(event)
    check_from_state(order, "status", "VENDOR_PLACED", TERMINAL["PartOrder"], "PartOrder")
    order["status"] = "RECEIVED"
    touch(order)
    return success(public(order))


@bp.route("/frc-events/<eventId>/teams/<teamId>/part-orders/<orderId>/cancel", methods=["POST"])
def cancel_part_order(eventId, teamId, orderId):
    require_roles("TeamLead")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    order = resolve_order(team, orderId)
    gate_posture(event)
    check_from_state(order, "status", {"DRAFT", "SUBMITTED"}, TERMINAL["PartOrder"], "PartOrder")
    order["status"] = "CANCELLED"
    touch(order)
    return success(public(order))


# ---------------------------------------------------------------------------
# RobotInspection
# ---------------------------------------------------------------------------

INSPECTION_GET_ROLES = ("EventDirector", "Inspector", "LeadInspector", "TeamLead")


@bp.route("/frc-events/<eventId>/teams/<teamId>/robot-inspections", methods=["POST"])
def create_robot_inspection(eventId, teamId):
    require_roles("Inspector")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    gate_posture(event)
    body = get_body()
    inspector_id = req_str(body, "inspector_id")
    weight_kg = req_num(body, "weight_kg", minimum_exclusive=0)
    frame_perimeter_cm = req_int(body, "frame_perimeter_cm")
    bumper_compliant = req_bool(body, "bumper_compliant")
    inspector = store.persons.get(inspector_id)
    if inspector is None or inspector.get("_event_id") != eventId:
        raise ApiError(ERR_PERSON_NOT_FOUND, 404, "Inspector person %s not found" % inspector_id)
    inspection = {
        "team_id": teamId,
        "inspector_id": inspector_id,
        "weight_kg": weight_kg,
        "frame_perimeter_cm": frame_perimeter_cm,
        "bumper_compliant": bumper_compliant,
        "status": "DRAFT",
    }
    stamp_new(inspection)
    store.robot_inspections[inspection["id"]] = inspection
    return success(public(inspection), code=201)


@bp.route("/frc-events/<eventId>/teams/<teamId>/robot-inspections", methods=["GET"])
def list_robot_inspections(eventId, teamId):
    require_roles(*INSPECTION_GET_ROLES)
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    items = [i for i in store.robot_inspections.values() if i["team_id"] == team["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/teams/<teamId>/robot-inspections/<inspectionId>", methods=["GET"])
def get_robot_inspection(eventId, teamId, inspectionId):
    require_roles(*INSPECTION_GET_ROLES)
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    inspection = resolve_inspection(team, inspectionId)
    return success(public(inspection))


@bp.route("/frc-events/<eventId>/teams/<teamId>/robot-inspections/<inspectionId>/submit", methods=["POST"])
def submit_robot_inspection(eventId, teamId, inspectionId):
    require_roles("Inspector")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    inspection = resolve_inspection(team, inspectionId)
    if event["status"] != "INSPECTION":
        raise ApiError(ERR_EVENT_WRONG_STATUS, 409, "Inspections may only be submitted while the event is INSPECTION")
    gate_posture(event)
    check_from_state(inspection, "status", "DRAFT", TERMINAL["RobotInspection"], "RobotInspection")
    inspector = store.persons.get(inspection["inspector_id"])
    if (
        inspector is None
        or inspector.get("role_kind") not in ("MENTOR", "VOLUNTEER")
        or inspector.get("screening_status") != "CLEARED"
    ):
        raise ApiError(ERR_INSPECTOR_NOT_CLEARED, 422, "Inspector must be a CLEARED MENTOR or VOLUNTEER")
    if inspector.get("team_id") == teamId:
        raise ApiError(ERR_INSPECTOR_SELF, 422, "Inspector cannot inspect their own team")
    inspection["status"] = "SUBMITTED"
    touch(inspection)
    if team["robot_inspection_status"] == "NOT_SUBMITTED":
        team["robot_inspection_status"] = "SUBMITTED"
        touch(team)
    return success(public(inspection))


@bp.route("/frc-events/<eventId>/teams/<teamId>/robot-inspections/<inspectionId>/pass", methods=["POST"])
def pass_robot_inspection(eventId, teamId, inspectionId):
    require_roles("LeadInspector")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    inspection = resolve_inspection(team, inspectionId)
    gate_posture(event)
    check_from_state(inspection, "status", "SUBMITTED", TERMINAL["RobotInspection"], "RobotInspection")
    if inspection["weight_kg"] > MAX_ROBOT_WEIGHT_KG:
        raise ApiError(ERR_ROBOT_OVERWEIGHT, 422, "Robot weight exceeds %s kg" % MAX_ROBOT_WEIGHT_KG)
    if inspection["frame_perimeter_cm"] > MAX_FRAME_PERIMETER_CM:
        raise ApiError(ERR_FRAME_TOO_LARGE, 422, "Frame perimeter exceeds %s cm" % MAX_FRAME_PERIMETER_CM)
    if inspection["bumper_compliant"] is not True:
        raise ApiError(ERR_BUMPERS_NONCOMPLIANT, 422, "Bumpers are not compliant")
    inspection["status"] = "PASSED"
    touch(inspection)
    team["robot_inspection_status"] = "PASSED"
    touch(team)
    for other in store.robot_inspections.values():
        if other["team_id"] == teamId and other["id"] != inspectionId and other["status"] == "SUBMITTED":
            other["status"] = "SUPERSEDED"
            touch(other)
    return success(public(inspection))


@bp.route("/frc-events/<eventId>/teams/<teamId>/robot-inspections/<inspectionId>/fail", methods=["POST"])
def fail_robot_inspection(eventId, teamId, inspectionId):
    user_id, _ = require_roles("LeadInspector")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    inspection = resolve_inspection(team, inspectionId)
    gate_posture(event)
    check_from_state(inspection, "status", "SUBMITTED", TERMINAL["RobotInspection"], "RobotInspection")
    inspection["status"] = "FAILED"
    touch(inspection)
    team["robot_inspection_status"] = "FAILED"
    touch(team)
    violation = {
        "team_id": teamId,
        "source_kind": "INSPECTION",
        "severity": "MAJOR",
        "description": "Robot inspection failed",
        "resolution_status": "OPEN",
        "opened_by_person_id": user_id,
    }
    stamp_new(violation)
    store.violations[violation["id"]] = violation
    recompute_posture(event)
    return success(public(inspection))


# ---------------------------------------------------------------------------
# ComplianceViolation
# ---------------------------------------------------------------------------

VIOLATION_GET_ROLES = ("EventDirector", "HeadReferee", "TeamLead")
VIOLATION_SOURCES = {"INSPECTION", "MATCH_REVIEW", "FIELD_SAFETY", "JUDGE_REFERRAL"}
VIOLATION_SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}


@bp.route("/frc-events/<eventId>/teams/<teamId>/violations", methods=["POST"])
def create_violation(eventId, teamId):
    require_roles("HeadReferee", "Inspector", "LeadInspector", "JudgeAdvisor")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    gate_posture(event)
    body = get_body()
    source_kind = req_enum(body, "source_kind", VIOLATION_SOURCES)
    severity = req_enum(body, "severity", VIOLATION_SEVERITIES)
    description = req_str(body, "description")
    opened_by_person_id = req_str(body, "opened_by_person_id")
    opener = store.persons.get(opened_by_person_id)
    if opener is None or opener.get("_event_id") != eventId:
        raise ApiError(ERR_PERSON_NOT_FOUND, 404, "Person %s not found" % opened_by_person_id)
    violation = {
        "team_id": teamId,
        "source_kind": source_kind,
        "severity": severity,
        "description": description,
        "resolution_status": "OPEN",
        "opened_by_person_id": opened_by_person_id,
    }
    stamp_new(violation)
    store.violations[violation["id"]] = violation
    recompute_posture(event)
    return success(public(violation), code=201)


@bp.route("/frc-events/<eventId>/teams/<teamId>/violations", methods=["GET"])
def list_violations(eventId, teamId):
    require_roles(*VIOLATION_GET_ROLES)
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    items = [v for v in store.violations.values() if v["team_id"] == team["id"]]
    rstatus = request.args.get("resolution_status")
    if rstatus is not None:
        items = [v for v in items if v["resolution_status"] == rstatus]
    severity = request.args.get("severity")
    if severity is not None:
        items = [v for v in items if v["severity"] == severity]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/teams/<teamId>/violations/<violationId>", methods=["GET"])
def get_violation(eventId, teamId, violationId):
    require_roles(*VIOLATION_GET_ROLES)
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    violation = resolve_violation(team, violationId)
    return success(public(violation))


@bp.route("/frc-events/<eventId>/teams/<teamId>/violations/<violationId>/ack", methods=["POST"])
def ack_violation(eventId, teamId, violationId):
    require_roles("TeamLead")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    violation = resolve_violation(team, violationId)
    gate_posture(event)
    check_from_state(violation, "resolution_status", "OPEN", TERMINAL["ComplianceViolation"], "ComplianceViolation")
    violation["resolution_status"] = "ACKED"
    touch(violation)
    return success(public(violation))


@bp.route("/frc-events/<eventId>/teams/<teamId>/violations/<violationId>/resolve", methods=["POST"])
def resolve_violation_endpoint(eventId, teamId, violationId):
    user_id, _ = require_roles("HeadReferee")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    violation = resolve_violation(team, violationId)
    gate_posture(event)
    check_from_state(violation, "resolution_status", "ACKED", TERMINAL["ComplianceViolation"], "ComplianceViolation")
    if user_id == violation["opened_by_person_id"]:
        raise ApiError(ERR_SEGREGATION_VIOLATION, 403, "HeadReferee cannot resolve a violation they opened")
    violation["resolution_status"] = "RESOLVED"
    touch(violation)
    recompute_posture(event)
    return success(public(violation))


@bp.route("/frc-events/<eventId>/teams/<teamId>/violations/<violationId>/escalate", methods=["POST"])
def escalate_violation(eventId, teamId, violationId):
    require_roles("HeadReferee")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    violation = resolve_violation(team, violationId)
    gate_posture(event)
    check_from_state(violation, "resolution_status", "OPEN", TERMINAL["ComplianceViolation"], "ComplianceViolation")
    if violation["severity"] != "CRITICAL":
        raise ApiError(ERR_INVALID_STATE, 409, "Only CRITICAL violations can be escalated")
    violation["resolution_status"] = "ESCALATED"
    touch(violation)
    recompute_posture(event)
    return success(public(violation))


# ---------------------------------------------------------------------------
# TravelBooking
# ---------------------------------------------------------------------------

BOOKING_GET_ROLES = ("EventDirector", "TeamLead", "TravelOfficer")
BOOKING_MODES = {"AIR", "RAIL", "BUS", "SELF_DRIVE"}


@bp.route("/frc-events/<eventId>/teams/<teamId>/travel-bookings", methods=["POST"])
def create_travel_booking(eventId, teamId):
    require_roles("TeamLead")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    gate_posture(event)
    body = get_body()
    mode = req_enum(body, "mode", BOOKING_MODES)
    booked_at = req_dt(body, "booked_at")
    cost_cents = req_int(body, "cost_cents", minimum=0)
    booking = {
        "team_id": teamId,
        "mode": mode,
        "booked_at": booked_at,
        "cost_cents": cost_cents,
        "reimbursement_status": "PENDING",
        "reimbursed_cents": 0,
    }
    stamp_new(booking)
    store.travel_bookings[booking["id"]] = booking
    return success(public(booking), code=201)


@bp.route("/frc-events/<eventId>/teams/<teamId>/travel-bookings", methods=["GET"])
def list_travel_bookings(eventId, teamId):
    require_roles(*BOOKING_GET_ROLES)
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    items = [b for b in store.travel_bookings.values() if b["team_id"] == team["id"]]
    rstatus = request.args.get("reimbursement_status")
    if rstatus is not None:
        items = [b for b in items if b["reimbursement_status"] == rstatus]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/teams/<teamId>/travel-bookings/<bookingId>", methods=["GET"])
def get_travel_booking(eventId, teamId, bookingId):
    require_roles(*BOOKING_GET_ROLES)
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    booking = resolve_booking(team, bookingId)
    return success(public(booking))


@bp.route("/frc-events/<eventId>/teams/<teamId>/travel-bookings/<bookingId>/approve", methods=["POST"])
def approve_travel_booking(eventId, teamId, bookingId):
    require_roles("TravelOfficer")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    booking = resolve_booking(team, bookingId)
    gate_posture(event)
    check_from_state(booking, "reimbursement_status", "PENDING", TERMINAL["TravelBooking"], "TravelBooking")
    if team.get("qualified_for_championship") is not True:
        raise ApiError(ERR_NOT_QUALIFIED, 409, "Team is not qualified for the championship")
    cap = MODE_CAPS[booking["mode"]]
    if booking["cost_cents"] > cap:
        raise ApiError(ERR_REIMBURSEMENT_CAP_EXCEEDED, 422, "Booking cost exceeds the %s cap" % booking["mode"])
    reimbursed = compute_reimbursement(booking)
    if not (reimbursed > 0):
        raise ApiError(ERR_INVALID_REQUEST, 422, "Computed reimbursement must be greater than zero")
    booking["reimbursement_status"] = "APPROVED"
    booking["reimbursed_cents"] = reimbursed
    touch(booking)
    return success(public(booking))


@bp.route("/frc-events/<eventId>/teams/<teamId>/travel-bookings/<bookingId>/mark-paid", methods=["POST"])
def mark_travel_booking_paid(eventId, teamId, bookingId):
    require_roles("TravelOfficer")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    booking = resolve_booking(team, bookingId)
    gate_posture(event)
    check_from_state(booking, "reimbursement_status", "APPROVED", TERMINAL["TravelBooking"], "TravelBooking")
    booking["reimbursement_status"] = "PAID"
    touch(booking)
    return success(public(booking))


@bp.route("/frc-events/<eventId>/teams/<teamId>/travel-bookings/<bookingId>/deny", methods=["POST"])
def deny_travel_booking(eventId, teamId, bookingId):
    require_roles("TravelOfficer")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    booking = resolve_booking(team, bookingId)
    gate_posture(event)
    check_from_state(booking, "reimbursement_status", "PENDING", TERMINAL["TravelBooking"], "TravelBooking")
    booking["reimbursement_status"] = "DENIED"
    booking["reimbursed_cents"] = 0
    touch(booking)
    return success(public(booking))
