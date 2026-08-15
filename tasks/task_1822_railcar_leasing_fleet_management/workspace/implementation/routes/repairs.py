"""Repair authorizations and the responsibility split (PRD 3.9)."""
from flask import Blueprint, g, request

import domain
from calc import repair_split
from envelope import ok, ok_list
from errors import ApiError, invalid_state, not_found
from http_util import (
    DEFECT_CAUSES, get_body, parse_pagination, require_roles,
    v_bool, v_enum, v_int, v_str,
)
from store import db, new_entity, today, touch

bp_repairs = Blueprint("repairs", __name__)

READ_ROLES = (
    "SystemAdmin", "LeaseAdmin", "FleetPlanner", "MaintenanceController",
    "BillingAnalyst", "ComplianceOfficer", "LesseeRep",
)


def _load_repair(repair_id):
    r = db.repairs.get(repair_id)
    if r is None:
        raise not_found("ERR_REPAIR_NOT_FOUND", f"Repair authorization {repair_id} not found")
    return r


def _lease_of(repair):
    if not repair["lease_assignment_id"]:
        return None
    a = db.assignments.get(repair["lease_assignment_id"])
    return db.leases.get(a["lease_id"]) if a else None


def _recompute_split(repair, cost):
    lease = _lease_of(repair)
    lease_type = lease["lease_type"] if lease else "FULL_SERVICE"
    lessee, lessor = repair_split(lease_type, repair["defect_cause"], cost)
    repair["lessee_share_cents"] = lessee
    repair["lessor_share_cents"] = lessor
    repair["lessee_preauth_required"] = (
        lease is not None and lessee > lease["authorized_repair_cap_cents"]
    )


def _owner_lessee_id(repair):
    lease = _lease_of(repair)
    return lease["lessee_id"] if lease else None


@bp_repairs.route("/repair-authorizations", methods=["POST"])
@require_roles("MaintenanceController")
def create_repair():
    body = get_body()
    railcar_id = v_str(body, "railcar_id")
    assignment_id = v_str(body, "lease_assignment_id", required=False)
    description = v_str(body, "defect_description")
    cause = v_enum(body, "defect_cause", DEFECT_CAUSES)
    estimate = v_int(body, "estimate_cents", min=1)
    requires_shop = v_bool(body, "requires_shop")

    if railcar_id not in db.railcars:
        raise not_found("ERR_RAILCAR_NOT_FOUND", f"Railcar {railcar_id} not found")
    if assignment_id is not None and assignment_id not in db.assignments:
        raise not_found("ERR_ASSIGNMENT_NOT_FOUND", f"Lease assignment {assignment_id} not found")

    repair = new_entity(
        {
            "railcar_id": railcar_id,
            "lease_assignment_id": assignment_id,
            "defect_description": description,
            "defect_cause": cause,
            "estimate_cents": estimate,
            "requires_shop": requires_shop,
            "approved_amount_cents": None,
            "final_cost_cents": None,
            "lessee_share_cents": 0,
            "lessor_share_cents": 0,
            "lessee_preauth_required": False,
            "lessee_preauthorized": False,
            "revision_count": 0,
            "shop_entry_date": None,
            "completion_date": None,
            "status": "UNDER_REVIEW",
        }
    )
    _recompute_split(repair, estimate)
    db.repairs[repair["id"]] = repair
    return ok(domain.serialize_repair(repair), status=201)


@bp_repairs.route("/repair-authorizations", methods=["GET"])
@require_roles(*READ_ROLES)
def list_repairs():
    limit, offset = parse_pagination()
    items = sorted(db.repairs.values(), key=lambda r: (r["created_at"], r["_created_seq"]))
    if g.user_role == "LesseeRep":
        items = [
            r
            for r in items
            if _owner_lessee_id(r) is None or _owner_lessee_id(r) == g.user_id
        ]
    railcar_id = request.args.get("railcar_id")
    assignment_id = request.args.get("lease_assignment_id")
    status = request.args.get("status")
    if railcar_id is not None:
        items = [r for r in items if r["railcar_id"] == railcar_id]
    if assignment_id is not None:
        items = [r for r in items if r["lease_assignment_id"] == assignment_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_repair(r) for r in page], limit, offset, total)


@bp_repairs.route("/repair-authorizations/<repair_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_repair(repair_id):
    r = _load_repair(repair_id)
    owner = _owner_lessee_id(r)
    if owner is not None:
        domain.check_lessee_ownership(owner)
    return ok(domain.serialize_repair(r))


@bp_repairs.route("/repair-authorizations/<repair_id>/preauthorize", methods=["POST"])
@require_roles("LesseeRep")
def preauthorize_repair(repair_id):
    r = _load_repair(repair_id)
    owner = _owner_lessee_id(r)
    if owner is None or g.user_id != owner:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", 403,
            "Only a LesseeRep of the owning lessee may pre-authorize this repair",
        )
    if r["status"] not in ("UNDER_REVIEW", "REVISION_REQUESTED"):
        raise invalid_state(
            f"Repair in status {r['status']} cannot be pre-authorized"
        )
    r["lessee_preauthorized"] = True
    touch(r)
    return ok(domain.serialize_repair(r))


@bp_repairs.route("/repair-authorizations/<repair_id>/approve", methods=["POST"])
@require_roles("MaintenanceController")
def approve_repair(repair_id):
    r = _load_repair(repair_id)
    body = get_body()
    approved = v_int(body, "approved_amount_cents", min=1)
    if r["status"] != "UNDER_REVIEW":
        raise invalid_state(f"Repair in status {r['status']} cannot be approved")
    if r["lessee_preauth_required"] and not r["lessee_preauthorized"]:
        raise ApiError(
            "ERR_REPAIR_PREAUTH_REQUIRED", 422,
            "Lessee share exceeds the authorized repair cap without pre-authorization",
        )
    r["approved_amount_cents"] = approved
    r["status"] = "APPROVED"
    touch(r)
    return ok(domain.serialize_repair(r))


@bp_repairs.route("/repair-authorizations/<repair_id>/request-revision", methods=["POST"])
@require_roles("MaintenanceController")
def request_revision(repair_id):
    r = _load_repair(repair_id)
    body = get_body()
    v_str(body, "notes")
    if r["status"] != "UNDER_REVIEW":
        raise invalid_state(f"Repair in status {r['status']} cannot be sent for revision")
    r["status"] = "REVISION_REQUESTED"
    touch(r)
    return ok(domain.serialize_repair(r))


@bp_repairs.route("/repair-authorizations/<repair_id>/revise", methods=["POST"])
@require_roles("MaintenanceController")
def revise_repair(repair_id):
    r = _load_repair(repair_id)
    body = get_body()
    estimate = v_int(body, "estimate_cents", min=1)
    if r["status"] != "REVISION_REQUESTED":
        raise invalid_state(f"Repair in status {r['status']} cannot be revised")
    r["estimate_cents"] = estimate
    r["revision_count"] += 1
    _recompute_split(r, estimate)
    r["lessee_preauthorized"] = False
    r["status"] = "UNDER_REVIEW"
    touch(r)
    return ok(domain.serialize_repair(r))


@bp_repairs.route("/repair-authorizations/<repair_id>/reject", methods=["POST"])
@require_roles("MaintenanceController")
def reject_repair(repair_id):
    r = _load_repair(repair_id)
    body = get_body()
    v_str(body, "reason")
    if r["status"] != "UNDER_REVIEW":
        raise invalid_state(f"Repair in status {r['status']} cannot be rejected")
    r["status"] = "REJECTED"
    touch(r)
    return ok(domain.serialize_repair(r))


@bp_repairs.route("/repair-authorizations/<repair_id>/start-work", methods=["POST"])
@require_roles("MaintenanceController")
def start_work(repair_id):
    r = _load_repair(repair_id)
    if r["status"] != "APPROVED":
        raise invalid_state(f"Repair in status {r['status']} cannot start work")
    if r["requires_shop"]:
        car = db.railcars.get(r["railcar_id"])
        # PRD 3.2: two overlapping shop repairs keep the car IN_SHOP until both
        # complete — a second start-work while IN_SHOP only raises the count and
        # must not overwrite the saved pre-shop status.
        if car is None or car["status"] not in ("AVAILABLE", "ON_LEASE", "IN_SHOP"):
            raise ApiError(
                "ERR_RAILCAR_NOT_AVAILABLE", 409,
                "Railcar must be AVAILABLE, ON_LEASE, or IN_SHOP for shop work",
            )
        if car["status"] != "IN_SHOP":
            car["status_before_shop"] = car["status"]
            car["status"] = "IN_SHOP"
        car["open_shop_repair_count"] += 1
        touch(car)
        r["shop_entry_date"] = today()
    r["status"] = "IN_PROGRESS"
    touch(r)
    return ok(domain.serialize_repair(r))


@bp_repairs.route("/repair-authorizations/<repair_id>/complete", methods=["POST"])
@require_roles("MaintenanceController")
def complete_repair(repair_id):
    r = _load_repair(repair_id)
    body = get_body()
    final_cost = v_int(body, "final_cost_cents", min=1)
    if r["status"] != "IN_PROGRESS":
        raise invalid_state(f"Repair in status {r['status']} cannot be completed")
    r["final_cost_cents"] = final_cost
    _recompute_split(r, final_cost)
    r["completion_date"] = today()
    r["status"] = "COMPLETED"
    touch(r)

    lease = _lease_of(r)
    if lease is not None and r["lessee_share_cents"] > 0:
        lessee = db.lessees.get(lease["lessee_id"])
        if lessee is not None:
            domain.balance_add(lessee, r["lessee_share_cents"])

    if r["requires_shop"]:
        car = db.railcars.get(r["railcar_id"])
        if car is not None:
            car["open_shop_repair_count"] -= 1
            if car["open_shop_repair_count"] <= 0:
                car["open_shop_repair_count"] = 0
                car["status"] = car["status_before_shop"]
                car["status_before_shop"] = None
            touch(car)
    return ok(domain.serialize_repair(r))
