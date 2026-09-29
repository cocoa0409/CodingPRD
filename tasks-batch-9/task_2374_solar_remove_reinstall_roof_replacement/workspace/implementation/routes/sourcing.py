"""Replacement sourcing under the mismatched-model rules (PRD 3.8)."""

import calc
import errors as E
import services
from errors import ApiError
from flask import Blueprint, g
from db import db, new_row, touch
from middleware import endpoint
from response import ok_row
from routes.helpers import (
    MATCH_CLASSES,
    ORDER_STATUSES,
    get_order,
    get_project,
    get_unit,
    invalid_state,
    paged,
    resolve_fk,
)
from routes.projects import check_project_version
from validation import (
    enum_field,
    enum_query,
    get_body,
    int_field,
    str_field,
    str_query,
)

bp = Blueprint("sourcing", __name__)

READ_ROLES = ("ProjectCoordinator", "SolarContractor", "SystemOwner", "SolarOwner")


@bp.route("/reroof/sourcing-orders", methods=["POST"])
@endpoint("ProjectCoordinator")
def create_order():
    body = get_body()
    project = resolve_fk(body, "project_id", get_project)
    unit = resolve_fk(body, "hardware_unit_id", get_unit)
    project_id = str_field(body, "project_id", required=True)
    hardware_unit_id = str_field(body, "hardware_unit_id", required=True)
    requested_model_code = str_field(body, "requested_model_code", required=True)
    offered_manufacturer = str_field(body, "offered_manufacturer", required=True)
    offered_model_code = str_field(body, "offered_model_code", required=True)
    offered_rated_watts = int_field(body, "offered_rated_watts", required=True, minimum=1)
    unit_cost_cents = int_field(body, "unit_cost_cents", required=True, minimum=0)
    waiver_ref = str_field(body, "waiver_ref", required=False, default=None)
    int_field(body, "expected_project_version", required=True)

    # Priority 7
    check_project_version(body, project)

    # Priority 8
    if unit["condition_grade"] != "DAMAGED":
        raise invalid_state(
            "the target unit's condition_grade must be DAMAGED, not %s"
            % unit["condition_grade"]
        )
    if unit["handling_status"] not in ("REMOVED", "STORED"):
        raise invalid_state(
            "the target unit's handling_status must be REMOVED or STORED, not %s"
            % unit["handling_status"]
        )

    # Priority 15
    if unit["project_id"] != project_id:
        raise ApiError(
            E.ERR_CROSS_PROJECT_REFERENCE,
            "hardware_unit_id does not belong to the supplied project_id",
            422,
        )

    # Steps 1 to 4 of the pinned classification order; the project snapshot is
    # read before step 5 mutates it.
    snapshot_notice_status = project["warranty_notice_status"]
    watt_delta_pct, tolerance_pct, match_class, status = calc.classify_replacement(
        unit,
        offered_manufacturer,
        offered_model_code,
        offered_rated_watts,
        waiver_ref,
        snapshot_notice_status,
        project["ownership_model"],
    )
    # Priority 18
    if status is None:
        raise ApiError(
            E.ERR_MODEL_MISMATCH_NOT_WAIVED,
            "a MISMATCHED offered part requires a waiver_ref",
            422,
        )

    snapshot = services.project_snapshot(project)
    order = new_row(
        {
            "project_id": project_id,
            "hardware_unit_id": hardware_unit_id,
            "requested_model_code": requested_model_code,
            "offered_manufacturer": offered_manufacturer,
            "offered_model_code": offered_model_code,
            "offered_rated_watts": offered_rated_watts,
            "unit_cost_cents": unit_cost_cents,
            "waiver_ref": waiver_ref,
            "watt_delta_pct": watt_delta_pct,
            "tolerance_pct": tolerance_pct,
            "match_class": match_class,
            "status": status,
            "review_note": None,
            "received_serial_number": None,
            "received_at": None,
        }
    )
    db.orders[order["id"]] = order

    # Step 5: the mutation.
    if match_class != "EXACT" and snapshot_notice_status == "FILED":
        project["warranty_notice_status"] = "PENDING"
    services.rollup_project(project)
    services.commit_project(project, snapshot, force=True)
    return ok_row(order, 201)


@bp.route("/reroof/sourcing-orders/<order_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_order(order_id):
    return ok_row(get_order(order_id))


@bp.route("/reroof/sourcing-orders", methods=["GET"])
@endpoint(*READ_ROLES)
def list_orders():
    project_id = str_query("project_id")
    hardware_unit_id = str_query("hardware_unit_id")
    status = enum_query("status", ORDER_STATUSES)
    match_class = enum_query("match_class", MATCH_CLASSES)

    rows = []
    for order in db.orders.values():
        if project_id is not None and order["project_id"] != project_id:
            continue
        if hardware_unit_id is not None and order["hardware_unit_id"] != hardware_unit_id:
            continue
        if status is not None and order["status"] != status:
            continue
        if match_class is not None and order["match_class"] != match_class:
            continue
        rows.append(order)
    return paged(rows)


@bp.route("/reroof/sourcing-orders/<order_id>/review", methods=["POST"])
@endpoint("SystemOwner")
def review_order(order_id):
    order = get_order(order_id)
    project = db.projects.get(order["project_id"])
    body = get_body()
    decision = enum_field(body, "decision", ("APPROVE", "REJECT"), required=True)
    review_note = str_field(body, "review_note", required=False, default=None)

    # Priority 6
    if g.get("actor_id") != project.get("system_owner_party_id"):
        raise ApiError(
            E.ERR_PARTY_NOT_ON_PROJECT,
            "only the project's system owner may review a sourcing order",
            403,
        )
    # Priority 8
    if order["status"] != "PENDING_REVIEW":
        raise invalid_state(
            "cannot review a sourcing order in %s" % order["status"]
        )

    if review_note is not None:
        order["review_note"] = review_note
    order["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    touch(order)
    return ok_row(order)


@bp.route("/reroof/sourcing-orders/<order_id>/receipt", methods=["POST"])
@endpoint("ProjectCoordinator")
def receive_order(order_id):
    order = get_order(order_id)
    project = db.projects.get(order["project_id"])
    unit = db.units.get(order["hardware_unit_id"])
    body = get_body()
    received_serial_number = str_field(body, "received_serial_number", required=True)

    # Priority 8
    if order["status"] != "APPROVED":
        raise invalid_state(
            "cannot receive a sourcing order in %s" % order["status"]
        )

    # Priority 19: circuit watt spread as if the receipt had already landed.
    watts = []
    for sibling in services.circuit_units(unit["array_circuit_id"]):
        if sibling["unit_type"] != unit["unit_type"]:
            continue
        if sibling["handling_status"] == "SCRAPPED":
            continue
        if sibling["id"] == unit["id"]:
            watts.append(order["offered_rated_watts"])
        else:
            watts.append(sibling["rated_watts"])
    if calc.watt_spread_exceeded(watts):
        raise ApiError(
            E.ERR_CIRCUIT_WATT_SPREAD_EXCEEDED,
            "the resulting circuit watt spread exceeds 3.00 percent",
            422,
        )

    # Priority 25
    for sibling in services.project_units(unit["project_id"]):
        if sibling["id"] == unit["id"]:
            continue
        if sibling["serial_number"] == received_serial_number:
            raise ApiError(
                E.ERR_DUPLICATE_SERIAL,
                "received_serial_number must be unique within the project",
                409,
            )

    snapshot = services.project_snapshot(project)
    order["status"] = "RECEIVED"
    order["received_serial_number"] = received_serial_number
    order["received_at"] = db.now()
    touch(order)

    unit["condition_grade"] = "REPLACED"
    unit["manufacturer"] = order["offered_manufacturer"]
    unit["model_code"] = order["offered_model_code"]
    unit["rated_watts"] = order["offered_rated_watts"]
    unit["serial_number"] = received_serial_number
    touch(unit)

    services.rollup_project(project)
    services.commit_project(project, snapshot)
    return ok_row(order)
