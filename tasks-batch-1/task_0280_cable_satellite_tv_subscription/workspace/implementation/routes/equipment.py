"""Equipment-lease endpoints (PRD §3.5)."""

from flask import Blueprint, request

import db
import errors
from middleware import get_identity, require_role
from response import object_response
from services import common
from services import accounts as acc_svc

bp = Blueprint("equipment", __name__)


@bp.route("/accounts/<account_id>/equipment-leases", methods=["POST"])
def assign_equipment(account_id):
    _, role = get_identity()
    require_role(role, {"CustomerServiceAgent", "FieldTechnician"})
    acc = common.get_account_or_404(account_id)
    body = common.get_json_body()
    equipment_model_id = common.require_str(body, "equipment_model_id")
    model = common.get_active_catalog(db.equipment_models, equipment_model_id)
    quantity = common.require_int(body, "quantity", minimum=1)

    # Account activity gate (PRD §2.8).
    if acc["lifecycle_status"] != "ACTIVE":
        raise errors.account_not_active()

    created_at, updated_at, version = db.stamp_new()
    lease = {
        "id": db.new_id(),
        "account_id": account_id,
        "equipment_model_id": equipment_model_id,
        "quantity": quantity,
        "status": "ASSIGNED",
        "monthly_lease_cents": model["monthly_lease_cents"] * quantity,
        "unreturned_charge_cents": 0,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.equipment_leases[lease["id"]] = lease
    acc_svc.recompute_recurring_only(acc)
    db.touch(acc)
    return object_response(lease, 201)


@bp.route("/accounts/<account_id>/equipment-leases", methods=["GET"])
def list_account_equipment(account_id):
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "FieldTechnician"})
    common.get_account_or_404(account_id)
    items = [e for e in db.equipment_leases.values() if e["account_id"] == account_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return common.paginate_and_respond(items)


@bp.route("/accounts/<account_id>/equipment-leases/<lid>/return", methods=["POST"])
def return_equipment(account_id, lid):
    _, role = get_identity()
    require_role(role, {"CustomerServiceAgent", "FieldTechnician"})
    acc = common.get_account_or_404(account_id)
    lease = db.equipment_leases.get(lid)
    if lease is None or lease["account_id"] != account_id:
        raise errors.subresource_not_found("Equipment lease not found under account")
    if lease["status"] != "ASSIGNED":
        raise errors.invalid_state("Lease must be ASSIGNED to return")
    lease["status"] = "RETURNED"
    # unreturned_charge_cents stays 0
    db.touch(lease)
    acc_svc.recompute_recurring_only(acc)
    db.touch(acc)
    return object_response(lease, 200)
