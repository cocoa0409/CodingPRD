"""RentIncreaseRequest endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.helpers import get_or_404, landlord_of_contract, assert_landlord_owns
from services.calculations import (
    rent_reasonableness, hap_split, find_payment_standard, _parse_iso_date,
)

bp = Blueprint("rent_increase_requests", __name__)


def serialize_request(r):
    return {
        "id": r["id"],
        "contract_id": r["contract_id"],
        "requested_rent_cents": r["requested_rent_cents"],
        "effective_date": r["effective_date"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/hcv/rent-increase-requests", methods=["POST"])
def create_request():
    role, user_id = require_roles("Landlord")
    body = request.get_json(force=True, silent=True) or {}
    contract_id = body.get("contract_id")
    requested_rent_cents = body.get("requested_rent_cents")
    effective_date = body.get("effective_date")

    contract = get_or_404(db.hap_contracts, contract_id, "HAPContract")

    # State: contract must be ACTIVE for a rent increase to make sense
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Parent HAPContract must be ACTIVE")

    # Ownership
    owner = landlord_of_contract(contract)
    assert_landlord_owns(user_id, owner)

    # Priority 8: effective_date >= contract.next_recert_due_date
    if contract.get("next_recert_due_date") is None:
        raise errors.increase_too_early("Contract has no next_recert_due_date yet")
    ed = _parse_iso_date(effective_date)
    nrd = _parse_iso_date(contract["next_recert_due_date"])
    if ed < nrd:
        raise errors.increase_too_early()

    # Priority 12: requested rent > 0
    if not isinstance(requested_rent_cents, int) or requested_rent_cents <= 0:
        raise errors.invalid_amount("requested_rent_cents must be > 0")

    rec = db.make_record({
        "contract_id": contract_id,
        "requested_rent_cents": requested_rent_cents,
        "effective_date": effective_date,
        "status": "PENDING",
    })
    db.rent_increase_requests[rec["id"]] = rec
    return success_object(serialize_request(rec), 201)


@bp.route("/hcv/rent-increase-requests/<rid>", methods=["GET"])
def get_request(rid):
    require_roles("HousingAuthorityAdmin", "Landlord")
    r = get_or_404(db.rent_increase_requests, rid, "RentIncreaseRequest")
    return success_object(serialize_request(r))


@bp.route("/hcv/rent-increase-requests/<rid>/approve", methods=["POST"])
def approve_request(rid):
    require_roles("HousingAuthorityAdmin")
    r = get_or_404(db.rent_increase_requests, rid, "RentIncreaseRequest")
    if r["status"] != "PENDING":
        raise errors.invalid_state("RentIncreaseRequest must be PENDING to approve")
    contract = db.hap_contracts.get(r["contract_id"])
    if contract is None:
        raise errors.not_found("Parent HAPContract not found")
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Parent HAPContract must be ACTIVE")

    # Priority 8: effective_date >= next_recert_due_date
    if contract.get("next_recert_due_date") is None:
        raise errors.increase_too_early()
    ed = _parse_iso_date(r["effective_date"])
    nrd = _parse_iso_date(contract["next_recert_due_date"])
    if ed < nrd:
        raise errors.increase_too_early()

    # Priority 13: rent reasonableness ceiling
    unit = db.units.get(contract["unit_id"])
    prop = db.properties.get(unit["property_id"]) if unit else None
    if unit is None or prop is None:
        raise errors.not_found("Unit/Property chain broken")
    # Re-run rent_reasonableness with requested rent as the "contract_rent"
    approved_ceiling = rent_reasonableness(
        r["requested_rent_cents"], prop["zip_code"], unit["bedroom_count"], ed
    )
    if r["requested_rent_cents"] > approved_ceiling:
        raise errors.rent_not_reasonable()

    # Apply: update contract rents and portions
    family = db.voucher_families.get(contract["family_id"])
    ps = find_payment_standard(prop["zip_code"], unit["bedroom_count"], ed)
    ps_amount = ps["amount_cents"] if ps else 0
    tenant_portion, hap_portion = hap_split(
        r["requested_rent_cents"], family["annual_income_cents"], ps_amount
    )

    contract["contract_rent_cents"] = r["requested_rent_cents"]
    contract["approved_rent_cents"] = r["requested_rent_cents"]
    contract["tenant_portion_cents"] = tenant_portion
    contract["hap_portion_cents"] = hap_portion
    db.touch(contract)

    r["status"] = "APPROVED"
    db.touch(r)
    return success_object(serialize_request(r))


@bp.route("/hcv/rent-increase-requests/<rid>/deny", methods=["POST"])
def deny_request(rid):
    require_roles("HousingAuthorityAdmin")
    r = get_or_404(db.rent_increase_requests, rid, "RentIncreaseRequest")
    if r["status"] != "PENDING":
        raise errors.invalid_state("RentIncreaseRequest must be PENDING to deny")
    r["status"] = "DENIED"
    db.touch(r)
    return success_object(serialize_request(r))


@bp.route("/hcv/rent-increase-requests/<rid>/withdraw", methods=["POST"])
def withdraw_request(rid):
    role, user_id = require_roles("Landlord")
    r = get_or_404(db.rent_increase_requests, rid, "RentIncreaseRequest")
    if r["status"] != "PENDING":
        raise errors.invalid_state("RentIncreaseRequest must be PENDING to withdraw")
    contract = db.hap_contracts.get(r["contract_id"])
    if contract is None:
        raise errors.not_found("Parent HAPContract not found")
    owner = landlord_of_contract(contract)
    assert_landlord_owns(user_id, owner)
    r["status"] = "WITHDRAWN"
    db.touch(r)
    return success_object(serialize_request(r))
