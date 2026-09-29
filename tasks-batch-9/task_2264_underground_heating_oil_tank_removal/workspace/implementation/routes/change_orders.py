"""Remediation change orders: draft, submit and compliance decision."""

from flask import Blueprint

import calculations as calc
from db import assign, create, db
from errors import ApiError
from middleware import (authenticate, body, filter_arg, opt_id, opt_str, pagination,
                        req_enum, req_int, req_num, resolve)
from response import entity_response, list_response
from services import project as svc

bp = Blueprint("change_orders", __name__)

READ_ROLES = ("ProjectCoordinator", "LicensedSiteProfessional", "ComplianceOfficer")


@bp.post("/change-orders")
def create_change_order():
    user_id, role = authenticate(("LicensedSiteProfessional",))
    payload = body()
    project_id = opt_id(payload, "tank_project_id")
    project = resolve("tank_projects", project_id) if project_id else None
    supersedes_id = opt_id(payload, "supersedes_change_order_id")
    supersedes = resolve("change_orders", supersedes_id) if supersedes_id else None
    if project is None:
        raise ApiError("ERR_INVALID_REQUEST", "tank_project_id is required.")

    additional = req_num(payload, "additional_cubic_yards", exclusive_min=0)
    unit_rate_cents = req_int(payload, "unit_rate_cents", exclusive_min=0)
    disposal_class = req_enum(payload, "disposal_class", calc.DISPOSAL_CLASSES)
    expected_version = req_int(payload, "expected_project_version")

    if expected_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    if project["status"] != "REMEDIATION_ACTIVE":
        raise ApiError("ERR_PROJECT_STATE_INVALID")
    if supersedes is not None:
        if supersedes["tank_project_id"] != project["id"] \
                or supersedes["status"] != "APPROVED":
            raise ApiError("ERR_SUPERSEDE_TARGET_INVALID")

    change_order = create("change_orders", {
        "tank_project_id": project["id"],
        "supersedes_change_order_id": supersedes["id"] if supersedes else None,
        "requested_by_user_id": user_id,
        "approved_by_user_id": None,
        "additional_cubic_yards": additional,
        "unit_rate_cents": unit_rate_cents,
        "disposal_class": disposal_class,
        "line_amount_cents": None,
        "decision_note": None,
        "decided_at": None,
        "status": "DRAFT",
    })
    svc.recompute_blockers(project)
    svc.bump_project_version(project)
    return entity_response(change_order, 201)


@bp.get("/change-orders")
def list_change_orders():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    project_id = filter_arg("tank_project_id")
    supersedes_id = filter_arg("supersedes_change_order_id")
    status = filter_arg("status")
    rows = list(db.change_orders.values())
    if project_id is not None:
        rows = [r for r in rows if r["tank_project_id"] == project_id]
    if supersedes_id is not None:
        rows = [r for r in rows if r["supersedes_change_order_id"] == supersedes_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, limit, offset)


@bp.get("/change-orders/<change_order_id>")
def read_change_order(change_order_id):
    authenticate(READ_ROLES)
    return entity_response(resolve("change_orders", change_order_id))


@bp.post("/change-orders/<change_order_id>/submit")
def submit_change_order(change_order_id):
    authenticate(("LicensedSiteProfessional",))
    change_order = resolve("change_orders", change_order_id)
    project = db.tank_projects.get(change_order["tank_project_id"])

    if change_order["status"] != "DRAFT":
        raise ApiError("ERR_CHANGE_ORDER_STATE_INVALID")
    if project is None or project["status"] != "REMEDIATION_ACTIVE":
        raise ApiError("ERR_PROJECT_STATE_INVALID")

    assign(change_order, "status", "SUBMITTED")
    svc.recompute_blockers(project)
    return entity_response(change_order)


@bp.post("/change-orders/<change_order_id>/decision")
def decide_change_order(change_order_id):
    user_id, role = authenticate(("ComplianceOfficer",))
    change_order = resolve("change_orders", change_order_id)
    payload = body()
    decision = req_enum(payload, "decision", ("APPROVED", "REJECTED"))
    decision_note = opt_str(payload, "decision_note")
    project = db.tank_projects.get(change_order["tank_project_id"])

    if change_order["status"] != "SUBMITTED":
        raise ApiError("ERR_CHANGE_ORDER_STATE_INVALID")

    if decision == "REJECTED":
        assign(change_order, "status", "REJECTED")
        assign(change_order, "approved_by_user_id", user_id)
        assign(change_order, "decided_at", db.now())
        if decision_note is not None:
            assign(change_order, "decision_note", decision_note)
        if project is not None:
            svc.recompute_blockers(project)
        return entity_response(change_order)

    if project is None or project["status"] != "REMEDIATION_ACTIVE":
        raise ApiError("ERR_PROJECT_STATE_INVALID")

    superseded = None
    if change_order["supersedes_change_order_id"] is not None:
        superseded = db.change_orders.get(change_order["supersedes_change_order_id"])
        if superseded is None or superseded["tank_project_id"] != project["id"] \
                or superseded["status"] != "APPROVED":
            raise ApiError("ERR_SUPERSEDE_TARGET_INVALID")

    # rule 14 — prospective excavation ceiling.
    prospective = calc.dec(project["baseline_scope_cubic_yards"])
    for row in svc.approved_change_orders(project):
        if superseded is not None and row["id"] == superseded["id"]:
            continue
        prospective += calc.dec(row["additional_cubic_yards"])
    prospective += calc.dec(change_order["additional_cubic_yards"])
    if prospective > calc.dec(project["excavation_limit_cubic_yards"]):
        raise ApiError("ERR_EXCAVATION_LIMIT_EXCEEDED")

    assign(change_order, "status", "APPROVED")
    assign(change_order, "approved_by_user_id", user_id)
    assign(change_order, "decided_at", db.now())
    if decision_note is not None:
        assign(change_order, "decision_note", decision_note)
    assign(change_order, "line_amount_cents", calc.line_amount_cents(
        change_order["additional_cubic_yards"], change_order["unit_rate_cents"],
        change_order["disposal_class"]))
    if superseded is not None:
        assign(superseded, "status", "SUPERSEDED")
        assign(superseded, "decided_at", None)
    svc.recompute_approved_scope(project)
    svc.recompute_cost(project)
    svc.recompute_blockers(project)
    return entity_response(change_order)
