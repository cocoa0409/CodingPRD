"""AddOn endpoints — PRD §3.10, §4.

PROPOSED -> {APPLIED, REJECTED}. ADD_ON appends a unit; UPGRADE replaces one.
Apply triggers a three-deep cascade (schedule -> lease financed -> lessee credit
+ lessor portfolio) and creates a new equipment unit.
"""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_roles, ALL_ROLES
from response import object_response, array_response
from services.common import (
    get_json_body, require_enum, require_string, require_positive_int,
    serialize, paginate, sort_by_created,
)
from services import domain
from services import calculations as calc

bp = Blueprint("add_ons", __name__)

ADDON_KINDS = {"ADD_ON", "UPGRADE"}


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/add-ons")
def propose_add_on(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        lease = domain.get_lease(lessor_id, lease_id)
        body = get_json_body()
        kind = require_enum(body, "kind", ADDON_KINDS)
        added_cost_cents = require_positive_int(body, "added_cost_cents")
        serial_number = require_string(body, "serial_number")
        description = require_string(body, "description")
        # replaces_equipment_unit_id required iff UPGRADE, forbidden iff ADD_ON.
        replaces = body.get("replaces_equipment_unit_id")
        if kind == "UPGRADE":
            if replaces is None or not isinstance(replaces, str) or replaces.strip() == "":
                raise errors.invalid_request("replaces_equipment_unit_id required for UPGRADE")
        else:  # ADD_ON
            if replaces is not None:
                raise errors.invalid_request("replaces_equipment_unit_id forbidden for ADD_ON")
        rec = db.init_record({
            "lessor_id": lessor_id,
            "lease_id": lease_id,
            "kind": kind,
            "replaces_equipment_unit_id": replaces if kind == "UPGRADE" else None,
            "added_cost_cents": added_cost_cents,
            "serial_number": serial_number,
            "description": description,
            "incremental_payment_cents": 0,
            "status": "PROPOSED",
        })
        db.add_ons[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/lessors/<lessor_id>/add-ons/<addon_id>")
def get_add_on(lessor_id, addon_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_add_on(lessor_id, addon_id)
        return object_response(serialize(rec), 200)


@bp.get("/lessors/<lessor_id>/leases/<lease_id>/add-ons")
def list_add_ons_for_lease(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        domain.get_lease(lessor_id, lease_id)
        items = [a for a in db.add_ons.values() if a["lease_id"] == lease_id]
        status = request.args.get("status")
        if status is not None and status != "":
            items = [a for a in items if a["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.get("/lessors/<lessor_id>/equipment/<equip_id>/add-ons")
def list_add_ons_for_equipment(lessor_id, equip_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        domain.get_equipment(lessor_id, equip_id)
        items = [a for a in db.add_ons.values()
                 if a.get("replaces_equipment_unit_id") == equip_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/add-ons/<addon_id>/apply")
def apply_add_on(lessor_id, lease_id, addon_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        lease = domain.get_lease(lessor_id, lease_id)
        rec = domain.get_add_on(lessor_id, addon_id)
        # The add-on must belong to the lease in the path.
        if rec["lease_id"] != lease_id:
            raise errors.not_found("Add-on not found on this lease")
        if rec["status"] != "PROPOSED":
            raise errors.invalid_state("Add-on is not PROPOSED")
        # Lease must be ACTIVE.
        if lease["lifecycle_status"] != "ACTIVE":
            raise errors.conflict(errors.ERR_LEASE_NOT_ACTIVE, "lease is not ACTIVE")
        # Credit check.
        lessee = db.lessees.get(lease["lessee_id"])
        if lessee["available_credit_cents"] < rec["added_cost_cents"]:
            raise errors.conflict(errors.ERR_CREDIT_LIMIT_EXCEEDED,
                                  "available credit insufficient for added cost")
        # UPGRADE: replaces_equipment_unit_id references a unit on this lease ON_LEASE.
        if rec["kind"] == "UPGRADE":
            replaced = db.equipment.get(rec["replaces_equipment_unit_id"])
            if (replaced is None or replaced["lease_id"] != lease_id
                    or replaced["status"] != "ON_LEASE"):
                raise errors.invalid_request("replaces_equipment_unit_id invalid")
        # Serial discipline for the new unit.
        domain.check_serial_available(lessor, rec["serial_number"])

        # Compute incremental payment over remaining SCHEDULED lines.
        scheduled = [s for s in domain.schedule_lines_for_lease(lease_id)
                     if s["status"] == "SCHEDULED"]
        incremental = calc.addon_incremental_payment(
            rec["added_cost_cents"], lease["monthly_rate_factor_bps"], len(scheduled),
        )
        rec["incremental_payment_cents"] = incremental
        rec["status"] = "APPLIED"
        db.touch(rec)

        # Cascade: bump base_rent on remaining SCHEDULED lines.
        for s in scheduled:
            s["base_rent_cents"] += incremental
            db.touch(s)
        # Lease financed += added_cost.
        lease["financed_amount_cents"] += rec["added_cost_cents"]
        db.touch(lease)
        # Create the new equipment unit (ON_LEASE).
        new_unit = db.init_record({
            "lessor_id": lessor_id,
            "lease_id": lease_id,
            "serial_number": rec["serial_number"],
            "description": rec["description"],
            "original_cost_cents": rec["added_cost_cents"],
            "status": "ON_LEASE",
            "disposed_clock_utc": None,
            "sale_proceeds_cents": None,
        })
        db.equipment[new_unit["id"]] = new_unit
        # UPGRADE: replaced unit DISPOSED.
        if rec["kind"] == "UPGRADE":
            replaced = db.equipment.get(rec["replaces_equipment_unit_id"])
            replaced["status"] = "DISPOSED"
            replaced["disposed_clock_utc"] = lessor["clock_utc"]
            db.touch(replaced)
        # Credit + portfolio cascades.
        domain.recompute_lessee_credit(lessee)
        domain.recompute_lessor_portfolio(lessor)
        return object_response(serialize(rec), 200)


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/add-ons/<addon_id>/reject")
def reject_add_on(lessor_id, lease_id, addon_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        domain.get_lease(lessor_id, lease_id)
        rec = domain.get_add_on(lessor_id, addon_id)
        if rec["lease_id"] != lease_id:
            raise errors.not_found("Add-on not found on this lease")
        if rec["status"] != "PROPOSED":
            raise errors.invalid_state("Add-on is not PROPOSED")
        rec["status"] = "REJECTED"
        db.touch(rec)
        return object_response(serialize(rec), 200)
