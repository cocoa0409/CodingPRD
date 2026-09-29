"""Install work orders (survey fork-join) and CPE equipment assignments."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import db
import domain
import middleware as mw
import resolve
import response
from errors import ApiError
from util import dec

bp = Blueprint("field", __name__)

WORK_ORDER_STATUSES = ("SCHEDULED", "EXCEPTION_PENDING", "MOUNT_APPROVED",
                       "RESURVEY_REQUIRED", "INSTALLED", "SURVEY_FAILED", "CANCELLED")
EXCEPTION_DECISIONS = ("APPROVE", "REQUEST_RESURVEY", "REJECT")
MOUNTING_TYPES = ("WALL_BRACKET", "NON_PEN_ROOF_TRIPOD", "ROOF_MAST_GUYED",
                  "GROUND_POLE_MAST")
RETURN_CONDITIONS = ("GOOD", "DAMAGED")

OPEN_WORK_ORDER_STATUSES = ("SCHEDULED", "EXCEPTION_PENDING", "RESURVEY_REQUIRED",
                            "MOUNT_APPROVED")


# ---------------------------------------------------------------------------
# install work orders
# ---------------------------------------------------------------------------
@bp.post("/install-work-orders")
def create_work_order():
    mw.require(mw.ROLE_FIELD_TECH, mw.ROLE_SALES_AGENT)
    payload = mw.body()
    subscriber_id = mw.v_ref(payload, "subscriber_id")
    scheduled_at = mw.v_ts(payload, "scheduled_at")

    subscriber = resolve.subscriber(subscriber_id)
    # Rung 8 -- a cancelled account never takes another truck roll.
    if subscriber["service_status"] == "CANCELLED":
        raise ApiError("ERR_SUBSCRIBER_NOT_ACTIVE")
    # Rung 13 -- only one open work order per account.
    for order in domain.subscriber_work_orders(subscriber["id"]):
        if order["status"] in OPEN_WORK_ORDER_STATUSES:
            raise ApiError("ERR_WORK_ORDER_ALREADY_OPEN")

    order = db.base_record(
        subscriber_id=subscriber["id"],
        scheduled_at=scheduled_at,
        status="SCHEDULED",
        measured_tree_line_height_m=None,
        measured_roof_height_m=None,
        structure_penetration_allowed=None,
        field_los_margin_m=None,
        recommended_mast_height_m=None,
        recommended_mounting_type=None,
        approved_mounting_type=None,
        surveyed_by_user_id=None,
        exception_approved_by_user_id=None,
        resurvey_count=0,
        installed_mast_height_m=None,
        radio_serial=None,
        install_invoice_total_cents=None,
        installed_at=None,
    )
    db.install_work_orders[order["id"]] = order
    return response.created(domain.work_order_view(order))


@bp.get("/install-work-orders/<work_order_id>")
def read_work_order(work_order_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_SALES_AGENT, mw.ROLE_FIELD_TECH,
               mw.ROLE_BILLING_ADMIN)
    order = resolve.work_order(work_order_id)
    return response.object_response(domain.work_order_view(order))


@bp.post("/install-work-orders/<work_order_id>/survey")
def survey_work_order(work_order_id):
    """The fork: one trigger, four disjoint target states (PRD 3.7)."""
    mw.require(mw.ROLE_FIELD_TECH)
    payload = mw.body()
    trees = mw.v_num(payload, "measured_tree_line_height_m", minimum="0.0",
                     maximum="60.0", places=1)
    roof = mw.v_num(payload, "measured_roof_height_m", minimum="0.0",
                    maximum="20.0", places=1)
    penetration = mw.v_bool(payload, "structure_penetration_allowed")
    mw.v_str(payload, "note", required=False)

    order = resolve.work_order(work_order_id)
    if order["status"] != "SCHEDULED":
        raise ApiError("ERR_WORK_ORDER_STATE_INVALID")

    subscriber = db.subscribers.get(order["subscriber_id"])
    if subscriber is None:
        raise ApiError("ERR_SUBSCRIBER_NOT_FOUND")
    enquiry = db.serviceability_requests.get(subscriber["serviceability_request_id"])
    if enquiry is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    tower = db.towers.get(enquiry["candidate_tower_id"])
    if tower is None:
        raise ApiError("ERR_TOWER_NOT_FOUND")

    order["measured_tree_line_height_m"] = trees
    order["measured_roof_height_m"] = roof
    order["structure_penetration_allowed"] = penetration
    order["surveyed_by_user_id"] = g.user_id

    # FIELD_SURVEY variant: the measured heights replace the desktop study's,
    # the premise geometry and obstruction class still come from the enquiry.
    geometry = calc.los_geometry(
        tower["ground_elevation_m"], tower["antenna_agl_m"],
        enquiry["premise_ground_elevation_m"], trees, roof,
        enquiry["obstruction_class"], enquiry["path_distance_km"],
    )
    margin = geometry["los_margin_m"]
    mast = geometry["required_mast_height_m"]
    mounting = geometry["mounting_type"]

    order["field_los_margin_m"] = margin
    order["recommended_mast_height_m"] = mast
    order["recommended_mounting_type"] = mounting

    if margin < 0 or mast > calc.MAX_MAST_HEIGHT_M:
        # Branch 4 -- terminal; the account is NOT auto-cancelled.
        order["status"] = "SURVEY_FAILED"
    elif mounting in calc.LIGHT_MOUNTINGS:
        # Branch 1 -- no engineering exception needed for the light bands.
        order["status"] = "MOUNT_APPROVED"
        order["approved_mounting_type"] = mounting
    elif mounting == "ROOF_MAST_GUYED" and not penetration:
        # Branch 3 -- a guyed roof mast is impossible without penetration.
        order["status"] = "RESURVEY_REQUIRED"
        order["resurvey_count"] = int(order["resurvey_count"]) + 1
    else:
        # Branch 2 -- the tall-mast bands need a NetworkEngineer.
        order["status"] = "EXCEPTION_PENDING"

    db.touch(order)
    return response.object_response(domain.work_order_view(order))


@bp.post("/install-work-orders/<work_order_id>/exception-decision")
def decide_exception(work_order_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    decision = mw.v_enum(payload, "decision", EXCEPTION_DECISIONS)
    mounting = mw.v_enum(payload, "approved_mounting_type", MOUNTING_TYPES,
                         required=False)
    mw.v_str(payload, "note")

    order = resolve.work_order(work_order_id)
    if order["status"] != "EXCEPTION_PENDING":
        raise ApiError("ERR_WORK_ORDER_STATE_INVALID")

    # Rung 11 -- physics before process: a supplied band must actually carry the
    # recommended mast.
    if mounting is not None:
        ceiling = calc.MOUNTING_CEILINGS[mounting]
        recommended = order.get("recommended_mast_height_m")
        if recommended is not None and dec(recommended) > ceiling:
            raise ApiError("ERR_MOUNTING_INCOMPATIBLE")

    # Rung 12 -- segregation of duties runs before resurvey exhaustion.
    if g.user_id == order.get("surveyed_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "REQUEST_RESURVEY":
        if int(order["resurvey_count"]) >= calc.RESURVEY_LIMIT:
            raise ApiError("ERR_RESURVEY_LIMIT_REACHED")

    if decision == "APPROVE":
        order["approved_mounting_type"] = mounting or order["recommended_mounting_type"]
        order["exception_approved_by_user_id"] = g.user_id
        order["status"] = "MOUNT_APPROVED"
    elif decision == "REQUEST_RESURVEY":
        order["resurvey_count"] = int(order["resurvey_count"]) + 1
        order["field_los_margin_m"] = None
        order["recommended_mast_height_m"] = None
        order["recommended_mounting_type"] = None
        order["status"] = "RESURVEY_REQUIRED"
    else:
        order["exception_approved_by_user_id"] = g.user_id
        order["status"] = "SURVEY_FAILED"

    db.touch(order)
    return response.object_response(domain.work_order_view(order))


@bp.post("/install-work-orders/<work_order_id>/reschedule")
def reschedule_work_order(work_order_id):
    mw.require(mw.ROLE_FIELD_TECH)
    payload = mw.body()
    scheduled_at = mw.v_ts(payload, "scheduled_at")

    order = resolve.work_order(work_order_id)
    if order["status"] != "RESURVEY_REQUIRED":
        raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
    if int(order["resurvey_count"]) > calc.RESURVEY_LIMIT:
        raise ApiError("ERR_RESURVEY_LIMIT_REACHED")

    order["scheduled_at"] = scheduled_at
    order["status"] = "SCHEDULED"
    db.touch(order)
    return response.object_response(domain.work_order_view(order))


@bp.post("/install-work-orders/<work_order_id>/completion")
def complete_work_order(work_order_id):
    """Cascade chain Z, depth 4: work order -> subscriber -> assignment -> charge."""
    mw.require(mw.ROLE_FIELD_TECH)
    payload = mw.body()
    installed_mast = mw.v_num(payload, "installed_mast_height_m", minimum="0.0",
                              maximum="12.0", places=1)
    radio_serial = mw.v_str(payload, "radio_serial")

    order = resolve.work_order(work_order_id)
    # Rung 8 with the pinned carve-out: EXCEPTION_PENDING reports the missing
    # engineering approval rather than the status label.
    if order["status"] == "EXCEPTION_PENDING":
        raise ApiError("ERR_MOUNT_EXCEPTION_REQUIRED")
    if order["status"] != "MOUNT_APPROVED":
        raise ApiError("ERR_WORK_ORDER_STATE_INVALID")

    subscriber = db.subscribers.get(order["subscriber_id"])
    if subscriber is None:
        raise ApiError("ERR_SUBSCRIBER_NOT_FOUND")
    if subscriber["service_status"] != "PENDING_INSTALL":
        raise ApiError("ERR_SUBSCRIBER_NOT_ACTIVE")

    approved = order["approved_mounting_type"]
    if approved is None:
        raise ApiError("ERR_MOUNT_EXCEPTION_REQUIRED")
    if dec(installed_mast) > calc.MOUNTING_CEILINGS[approved]:
        raise ApiError("ERR_MAST_EXCEEDS_STRUCTURAL_LIMIT")

    moment = db.now()
    order["installed_mast_height_m"] = installed_mast
    order["radio_serial"] = radio_serial
    order["installed_at"] = moment
    order["install_invoice_total_cents"] = \
        calc.install_invoice_total_cents(approved, installed_mast)["total_cents"]
    order["status"] = "INSTALLED"
    db.touch(order)

    # link 2 of the chain -- the account goes live
    subscriber["service_status"] = "ACTIVE"
    subscriber["service_start_date"] = moment
    subscriber["cycle_start_date"] = moment.date()

    # link 3 -- the CPE is deployed, which moves the monthly charge (link 4)
    for assignment in domain.subscriber_assignments(subscriber["id"]):
        if assignment["status"] != "ASSIGNED":
            continue
        assignment["status"] = "DEPLOYED"
        assignment["deployed_at"] = moment
        assignment["radio_serial"] = radio_serial
        db.touch(assignment)

    db.touch(subscriber)
    return response.object_response(domain.work_order_view(order))


# ---------------------------------------------------------------------------
# equipment assignments
# ---------------------------------------------------------------------------
@bp.get("/equipment-assignments/<assignment_id>")
def read_assignment(assignment_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_FIELD_TECH, mw.ROLE_BILLING_ADMIN,
               mw.ROLE_FINANCE_APPROVER)
    assignment = resolve.assignment(assignment_id)
    return response.object_response(domain.assignment_view(assignment))


@bp.post("/equipment-assignments/<assignment_id>/return")
def return_assignment(assignment_id):
    mw.require(mw.ROLE_FIELD_TECH)
    payload = mw.body()
    condition = mw.v_enum(payload, "return_condition", RETURN_CONDITIONS)

    assignment = resolve.assignment(assignment_id)
    if assignment["status"] != "RETURN_PENDING":
        raise ApiError("ERR_ASSIGNMENT_NOT_RETURNABLE")

    moment = db.now()
    assignment["status"] = "RETURNED"
    assignment["returned_at"] = moment
    assignment["return_condition"] = condition
    months = calc.months_in_service(assignment["deployed_at"], moment)
    assignment["months_in_service"] = months
    cents, basis = calc.settle_equipment(assignment, "RETURNED", months)
    assignment["settlement_cents"] = cents
    assignment["settlement_basis"] = basis
    db.touch(assignment)
    # Subscriber.settlement_balance_cents is a roll-up: it moves with the
    # assignment and carries no version of its own.
    return response.object_response(domain.assignment_view(assignment))


@bp.post("/equipment-assignments/<assignment_id>/unreturned-settlement")
def bill_unreturned_assignment(assignment_id):
    mw.require(mw.ROLE_BILLING_ADMIN)
    payload = mw.body()
    mw.v_str(payload, "note", required=False)

    assignment = resolve.assignment(assignment_id)
    if assignment["status"] != "RETURN_PENDING":
        raise ApiError("ERR_ASSIGNMENT_NOT_RETURNABLE")
    due = assignment.get("return_due_at")
    if due is None or db.now() < due:
        raise ApiError("ERR_RETURN_WINDOW_OPEN")

    moment = db.now()
    months = calc.months_in_service(assignment["deployed_at"], moment)
    assignment["months_in_service"] = months
    cents, basis = calc.settle_equipment(assignment, "UNRETURNED", months)
    assignment["status"] = "UNRETURNED_BILLED"
    assignment["settlement_cents"] = cents
    assignment["settlement_basis"] = basis
    db.touch(assignment)
    return response.object_response(domain.assignment_view(assignment))
