"""EquipmentUnit endpoints — PRD §3.5, §3.12, §4.

Remarketing lifecycle: ON_LEASE -> RETURNED -> {LISTED, DISPOSED};
LISTED -> {SOLD, DISPOSED}. Terminal: SOLD, DISPOSED.
"""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles, ALL_ROLES
from response import object_response, array_response
from services.common import (
    get_json_body, require_string, require_positive_int, require_nonneg_int,
    serialize, paginate, sort_by_created,
)
from services import domain
from services import calculations as calc

bp = Blueprint("equipment", __name__)


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/equipment")
def attach_equipment(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ["FundingOfficer"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        lease = domain.get_lease(lessor_id, lease_id)
        body = get_json_body()
        serial_number = require_string(body, "serial_number")
        description = require_string(body, "description")
        original_cost_cents = require_positive_int(body, "original_cost_cents")
        # Serial discipline (PRD §3.5): duplicate then reuse-buffer.
        domain.check_serial_available(lessor, serial_number)
        rec = db.init_record({
            "lessor_id": lessor_id,
            "lease_id": lease_id,
            "serial_number": serial_number,
            "description": description,
            "original_cost_cents": original_cost_cents,
            "status": "ON_LEASE",
            "disposed_clock_utc": None,
            "sale_proceeds_cents": None,
        })
        db.equipment[rec["id"]] = rec
        # Adding a unit can change the portfolio if the lease is in the active book.
        domain.recompute_lessor_portfolio(lessor)
        return object_response(domain.serialize_equipment(rec, lessor), 201)


@bp.get("/lessors/<lessor_id>/equipment/<equip_id>")
def get_equipment(lessor_id, equip_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        rec = domain.get_equipment(lessor_id, equip_id)
        return object_response(domain.serialize_equipment(rec, lessor), 200)


@bp.get("/lessors/<lessor_id>/leases/<lease_id>/equipment")
def list_equipment(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        domain.get_lease(lessor_id, lease_id)
        items = domain.units_for_lease(lease_id)
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response(
            [domain.serialize_equipment(r, lessor) for r in page],
            limit, offset, total, 200,
        )


@bp.post("/lessors/<lessor_id>/equipment/<equip_id>/return")
def return_equipment(lessor_id, equip_id):
    user_id, role = get_user_context()
    require_roles(role, ["AssetManager"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        rec = domain.get_equipment(lessor_id, equip_id)
        if rec["status"] != "ON_LEASE":
            raise errors.invalid_state("Unit is not ON_LEASE")
        lease = db.leases.get(rec["lease_id"])
        # Owning lease must be END_OF_TERM.
        if lease["lifecycle_status"] != "END_OF_TERM":
            raise errors.conflict(errors.ERR_LEASE_NOT_END_OF_TERM,
                                  "owning lease is not END_OF_TERM")
        # Its election must be RETURN and EXERCISED.
        match = [e for e in domain.elections_for_lease(lease["id"])
                 if e["election"] == "RETURN" and e["status"] == "EXERCISED"]
        if not match:
            raise errors.conflict(errors.ERR_ELECTION_MISMATCH,
                                  "no RETURN/EXERCISED election for the lease")
        rec["status"] = "RETURNED"
        db.touch(rec)
        return object_response(domain.serialize_equipment(rec, lessor), 200)


@bp.post("/lessors/<lessor_id>/equipment/<equip_id>/list")
def list_unit(lessor_id, equip_id):
    user_id, role = get_user_context()
    require_roles(role, ["AssetManager"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        rec = domain.get_equipment(lessor_id, equip_id)
        if rec["status"] != "RETURNED":
            raise errors.invalid_state("Unit is not RETURNED")
        rec["status"] = "LISTED"
        db.touch(rec)
        return object_response(domain.serialize_equipment(rec, lessor), 200)


@bp.post("/lessors/<lessor_id>/equipment/<equip_id>/record-sale")
def record_sale(lessor_id, equip_id):
    user_id, role = get_user_context()
    require_roles(role, ["AssetManager"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        rec = domain.get_equipment(lessor_id, equip_id)
        body = get_json_body()
        sale_proceeds_cents = require_nonneg_int(body, "sale_proceeds_cents")
        if rec["status"] != "LISTED":
            raise errors.invalid_state("Unit is not LISTED")
        lease = db.leases.get(rec["lease_id"])
        rec["status"] = "SOLD"
        rec["sale_proceeds_cents"] = sale_proceeds_cents
        rec["remarketing_gain_loss_cents"] = calc.remarketing_gain_loss(
            sale_proceeds_cents, lease["residual_value_cents"],
        )
        db.touch(rec)
        domain.recompute_lessor_portfolio(lessor)
        return object_response(domain.serialize_equipment(rec, lessor), 200)


@bp.post("/lessors/<lessor_id>/equipment/<equip_id>/dispose")
def dispose_unit(lessor_id, equip_id):
    user_id, role = get_user_context()
    require_roles(role, ["AssetManager"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        rec = domain.get_equipment(lessor_id, equip_id)
        if rec["status"] not in ("RETURNED", "LISTED"):
            raise errors.invalid_state("Unit cannot be disposed from its current state")
        rec["status"] = "DISPOSED"
        rec["disposed_clock_utc"] = lessor["clock_utc"]
        db.touch(rec)
        domain.recompute_lessor_portfolio(lessor)
        return object_response(domain.serialize_equipment(rec, lessor), 200)
