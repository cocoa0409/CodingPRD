"""Contract endpoints + lifecycle transitions."""
from flask import Blueprint, request

import errors
from db import db, base_fields, public, touch
from middleware import get_identity, require_role
from response import success, list_success
from validation import (get_json_body, require_int, require_datetime,
                        require_enum, optional_int, parse_pagination, paginate)
from services.calculations import compute_contract_total

bp = Blueprint("contracts", __name__)

CONTRACT_TYPES = {"COMMERCIAL", "HOA", "EVENT"}


def _get_client_or_404(client_id):
    rec = db.clients.get(client_id)
    if rec is None:
        raise errors.not_found("Client not found")
    return rec


def _get_contract_or_404(contract_id):
    rec = db.contracts.get(contract_id)
    if rec is None:
        raise errors.not_found("Contract not found")
    return rec


def _owning_client_id(contract):
    return contract["client_id"]


def _check_owner(user_id, contract):
    """ClientContact ownership check (priority 3)."""
    if user_id != _owning_client_id(contract):
        raise errors.not_resource_owner()


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------
@bp.post("/clients/<client_id>/contracts")
def create_contract(client_id):
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    client = _get_client_or_404(client_id)
    body = get_json_body()
    contract_type = require_enum(body, "contract_type", CONTRACT_TYPES)
    season_year = require_int(body, "season_year")
    early_bird_deadline = require_datetime(body, "early_bird_deadline")
    surcharge = optional_int(body, "custom_design_surcharge_cents", default=0, minimum=0)

    # business rule (priority 9): contract_type == Client.account_type
    if contract_type != client["account_type"]:
        raise errors.contract_type_mismatch()

    rec = base_fields()
    rec.update({
        "client_id": client_id,
        "renewed_from_contract_id": None,
        "contract_type": contract_type,
        "season_year": season_year,
        "early_bird_deadline": early_bird_deadline,
        "custom_design_surcharge_cents": surcharge,
        "install_fee_cents": None,
        "storage_fee_cents": None,
        "early_bird_discount_cents": None,
        "total_amount_cents": None,
        "status": "DRAFT",
    })
    db.contracts[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/clients/<client_id>/contracts")
def list_client_contracts(client_id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "ClientContact", "PlatformAdmin"])
    _get_client_or_404(client_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = [c for c in db.contracts.values() if c["client_id"] == client_id]
    if status is not None:
        records = [c for c in records if c["status"] == status]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/contracts/<id>")
def get_contract(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "ClientContact", "PlatformAdmin"])
    rec = _get_contract_or_404(id)
    return success(public(rec))


@bp.get("/contracts")
def list_contracts():
    _, role = get_identity()
    require_role(role, ["AccountManager", "PlatformAdmin"])
    limit, offset = parse_pagination()
    status = request.args.get("status")
    renewed_from = request.args.get("renewed_from_contract_id")
    records = list(db.contracts.values())
    if status is not None:
        records = [c for c in records if c["status"] == status]
    if renewed_from is not None:
        records = [c for c in records if c.get("renewed_from_contract_id") == renewed_from]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
@bp.post("/clients/<client_id>/contracts/<contract_id>/propose")
def propose_contract(client_id, contract_id):
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    _get_client_or_404(client_id)
    contract = _get_contract_or_404(contract_id)
    if contract["status"] != "DRAFT":
        raise errors.invalid_state()
    has_submitted = any(
        p["contract_id"] == contract_id and p["status"] == "SUBMITTED"
        for p in db.design_proposals.values()
    )
    if not has_submitted:
        raise errors.invalid_state("No SUBMITTED proposal under this contract")
    contract["status"] = "PROPOSED"
    touch(contract)
    return success(public(contract))


@bp.post("/clients/<client_id>/contracts/<contract_id>/sign")
def sign_contract(client_id, contract_id):
    user_id, role = get_identity()
    require_role(role, ["ClientContact"])
    _get_client_or_404(client_id)
    contract = _get_contract_or_404(contract_id)
    _check_owner(user_id, contract)
    if contract["status"] != "PROPOSED":
        raise errors.invalid_state()
    accepted = [p for p in db.design_proposals.values()
                if p["contract_id"] == contract_id and p["status"] == "ACCEPTED"]
    if len(accepted) != 1:
        raise errors.invalid_state("Exactly one ACCEPTED proposal required to sign")
    accepted_proposal = accepted[0]

    install, storage, eb_discount, total = compute_contract_total(contract, accepted_proposal)
    contract["install_fee_cents"] = install
    contract["storage_fee_cents"] = storage
    contract["early_bird_discount_cents"] = eb_discount
    contract["total_amount_cents"] = total
    contract["status"] = "SIGNED"
    touch(contract)
    return success(public(contract))


@bp.post("/clients/<client_id>/contracts/<contract_id>/activate")
def activate_contract(client_id, contract_id):
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    _get_client_or_404(client_id)
    contract = _get_contract_or_404(contract_id)
    if contract["status"] != "SIGNED":
        raise errors.invalid_state()
    contract["status"] = "ACTIVE"
    touch(contract)
    return success(public(contract))


@bp.post("/clients/<client_id>/contracts/<contract_id>/cancel")
def cancel_contract(client_id, contract_id):
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    _get_client_or_404(client_id)
    contract = _get_contract_or_404(contract_id)
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state()
    # precondition: no WorkOrder for this contract in DISPATCHED
    dispatched = any(
        wo["contract_id"] == contract_id and wo["schedule_status"] == "DISPATCHED"
        for wo in db.work_orders.values()
    )
    if dispatched:
        raise errors.invalid_state("A work order is DISPATCHED")

    # cascade: cancel non-terminal (UNSCHEDULED/SCHEDULED) work orders
    for wo in db.work_orders.values():
        if wo["contract_id"] == contract_id and wo["schedule_status"] in ("UNSCHEDULED", "SCHEDULED"):
            wo["schedule_status"] = "CANCELLED"
            touch(wo)
    # cascade: release RESERVED/STORED storage lots
    for lot in db.storage_lots.values():
        if lot["contract_id"] == contract_id and lot["status"] in ("RESERVED", "STORED"):
            lot["status"] = "RELEASED"
            touch(lot)

    contract["status"] = "CANCELLED"
    touch(contract)
    return success(public(contract))
