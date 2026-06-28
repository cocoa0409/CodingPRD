"""DesignProposal + ProposalLineItem endpoints."""
from flask import Blueprint, request

import errors
from db import db, base_fields, public, touch
from middleware import get_identity, require_role
from response import success, list_success
from validation import (get_json_body, require_str, require_int,
                        optional_bool, parse_pagination, paginate)

bp = Blueprint("proposals", __name__)


def _get_contract_or_404(contract_id):
    rec = db.contracts.get(contract_id)
    if rec is None:
        raise errors.not_found("Contract not found")
    return rec


def _get_proposal_or_404(proposal_id):
    rec = db.design_proposals.get(proposal_id)
    if rec is None:
        raise errors.not_found("Design proposal not found")
    return rec


def _owning_contract(proposal):
    return db.contracts.get(proposal["contract_id"])


def _check_owner(user_id, proposal):
    contract = _owning_contract(proposal)
    if contract is None or user_id != contract["client_id"]:
        raise errors.not_resource_owner()


def _recompute_total_unit_count(proposal):
    proposal["total_unit_count"] = sum(
        li["quantity"] for li in db.proposal_line_items.values()
        if li["proposal_id"] == proposal["id"]
    )


# ---------------------------------------------------------------------------
# Proposal create/read
# ---------------------------------------------------------------------------
@bp.post("/contracts/<contract_id>/design-proposals")
def create_proposal(contract_id):
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    _get_contract_or_404(contract_id)
    body = get_json_body()
    theme = require_str(body, "theme")
    is_custom = optional_bool(body, "is_custom", default=False)

    rec = base_fields()
    rec.update({
        "contract_id": contract_id,
        "theme": theme,
        "is_custom": is_custom,
        "total_unit_count": 0,
        "status": "DRAFT",
    })
    db.design_proposals[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/contracts/<contract_id>/design-proposals")
def list_proposals(contract_id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "ClientContact", "PlatformAdmin"])
    _get_contract_or_404(contract_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = [p for p in db.design_proposals.values() if p["contract_id"] == contract_id]
    if status is not None:
        records = [p for p in records if p["status"] == status]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/design-proposals/<id>")
def get_proposal(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "ClientContact", "PlatformAdmin"])
    rec = _get_proposal_or_404(id)
    return success(public(rec))


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------
@bp.post("/design-proposals/<id>/line-items")
def add_line_item(id):
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    proposal = _get_proposal_or_404(id)
    body = get_json_body()
    inventory_item_id = require_str(body, "inventory_item_id")
    quantity = require_int(body, "quantity", minimum=1)
    unit_install_cents = require_int(body, "unit_install_cents", minimum=0)

    # body FK existence (priority 5)
    if inventory_item_id not in db.inventory_items:
        raise errors.reference_not_found("inventory_item_id does not exist")

    rec = base_fields()
    rec.update({
        "proposal_id": id,
        "inventory_item_id": inventory_item_id,
        "quantity": quantity,
        "unit_install_cents": unit_install_cents,
    })
    db.proposal_line_items[rec["id"]] = rec
    _recompute_total_unit_count(proposal)
    touch(proposal)
    return success(public(rec), status=201)


@bp.get("/design-proposals/<id>/line-items")
def list_line_items(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "ClientContact", "PlatformAdmin"])
    _get_proposal_or_404(id)
    limit, offset = parse_pagination()
    records = [li for li in db.proposal_line_items.values() if li["proposal_id"] == id]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Proposal transitions
# ---------------------------------------------------------------------------
@bp.post("/design-proposals/<id>/submit")
def submit_proposal(id):
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    proposal = _get_proposal_or_404(id)
    if proposal["status"] != "DRAFT":
        raise errors.invalid_state()
    line_items = [li for li in db.proposal_line_items.values() if li["proposal_id"] == id]
    if not line_items:
        raise errors.invalid_state("Proposal has no line items")
    _recompute_total_unit_count(proposal)
    proposal["status"] = "SUBMITTED"
    touch(proposal)
    return success(public(proposal))


@bp.post("/design-proposals/<id>/accept")
def accept_proposal(id):
    user_id, role = get_identity()
    require_role(role, ["ClientContact"])
    proposal = _get_proposal_or_404(id)
    _check_owner(user_id, proposal)
    body = get_json_body()
    expected_version = require_int(body, "expected_contract_version")

    contract = _owning_contract(proposal)
    # OCC check (priority 7) — before state-machine guard
    if contract is None or expected_version != contract["version"]:
        raise errors.stale_contract_version()

    # state-machine guard (priority 8)
    if proposal["status"] != "SUBMITTED":
        raise errors.invalid_state()

    # business rule (priority 10): contract PROPOSED + no sibling ACCEPTED
    if contract["status"] != "PROPOSED":
        raise errors.proposal_already_decided()
    sibling_accepted = any(
        p["contract_id"] == contract["id"] and p["id"] != id and p["status"] == "ACCEPTED"
        for p in db.design_proposals.values()
    )
    if sibling_accepted:
        raise errors.proposal_already_decided()

    # cascade: supersede sibling DRAFT/SUBMITTED proposals
    for p in db.design_proposals.values():
        if p["contract_id"] == contract["id"] and p["id"] != id and p["status"] in ("DRAFT", "SUBMITTED"):
            p["status"] = "SUPERSEDED"
            touch(p)

    proposal["status"] = "ACCEPTED"
    touch(proposal)
    # advance the owning contract's version
    touch(contract)
    return success(public(proposal))


@bp.post("/design-proposals/<id>/reject")
def reject_proposal(id):
    user_id, role = get_identity()
    require_role(role, ["ClientContact"])
    proposal = _get_proposal_or_404(id)
    _check_owner(user_id, proposal)
    if proposal["status"] != "SUBMITTED":
        raise errors.invalid_state()
    proposal["status"] = "REJECTED"
    touch(proposal)
    return success(public(proposal))
