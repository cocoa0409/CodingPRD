"""Recertification endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.helpers import get_or_404
from services.calculations import (
    hap_split, find_payment_standard, add_one_year, _parse_iso_date,
)

bp = Blueprint("recertifications", __name__)


def serialize_recertification(r):
    return {
        "id": r["id"],
        "contract_id": r["contract_id"],
        "due_date": r["due_date"],
        "new_family_income_cents": r["new_family_income_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/hcv/recertifications", methods=["POST"])
def create_recertification():
    require_roles("HousingAuthorityAdmin")
    body = request.get_json(force=True, silent=True) or {}
    contract_id = body.get("contract_id")
    due_date = body.get("due_date")
    new_family_income_cents = body.get("new_family_income_cents")

    contract = get_or_404(db.hap_contracts, contract_id, "HAPContract")
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Parent HAPContract must be ACTIVE")
    if not isinstance(new_family_income_cents, int) or new_family_income_cents < 0:
        raise errors.invalid_amount("new_family_income_cents must be >= 0")

    rec = db.make_record({
        "contract_id": contract_id,
        "due_date": due_date,
        "new_family_income_cents": new_family_income_cents,
        "status": "OPEN",
    })
    db.recertifications[rec["id"]] = rec
    return success_object(serialize_recertification(rec), 201)


@bp.route("/hcv/recertifications/<rid>", methods=["GET"])
def get_recertification(rid):
    require_roles("HousingAuthorityAdmin", "Landlord")
    r = get_or_404(db.recertifications, rid, "Recertification")
    return success_object(serialize_recertification(r))


@bp.route("/hcv/recertifications/<rid>/complete", methods=["POST"])
def complete_recertification(rid):
    require_roles("HousingAuthorityAdmin")
    r = get_or_404(db.recertifications, rid, "Recertification")
    if r["status"] != "OPEN":
        raise errors.invalid_state("Recertification must be OPEN to complete")
    contract = db.hap_contracts.get(r["contract_id"])
    if contract is None:
        raise errors.not_found("Parent HAPContract not found")
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Parent HAPContract must be ACTIVE")

    # OCC: expected_contract_version
    body = request.get_json(force=True, silent=True) or {}
    expected = body.get("expected_contract_version")
    if expected is None or expected != contract["version"]:
        raise errors.stale_version("expected_contract_version does not match contract's current version")

    # Side effects
    family = db.voucher_families.get(contract["family_id"])
    if family is not None:
        family["annual_income_cents"] = r["new_family_income_cents"]
        db.touch(family)

    # Recompute hap split with new income
    unit = db.units.get(contract["unit_id"])
    prop = db.properties.get(unit["property_id"]) if unit else None
    # use current anniversary as the target date for payment standard lookup
    current_nrd = _parse_iso_date(contract["next_recert_due_date"]) if contract.get("next_recert_due_date") else db.current_logical_date()
    ps = find_payment_standard(prop["zip_code"], unit["bedroom_count"], current_nrd) if prop and unit else None
    ps_amount = ps["amount_cents"] if ps else 0
    tenant_portion, hap_portion = hap_split(
        contract["approved_rent_cents"], r["new_family_income_cents"], ps_amount
    )
    contract["tenant_portion_cents"] = tenant_portion
    contract["hap_portion_cents"] = hap_portion
    new_nrd = add_one_year(current_nrd)
    contract["next_recert_due_date"] = new_nrd.isoformat()
    db.touch(contract)

    r["status"] = "COMPLETED"
    db.touch(r)

    # Auto-create a new Recertification with due_date = newly advanced next_recert_due_date
    new_rec = db.make_record({
        "contract_id": contract["id"],
        "due_date": new_nrd.isoformat(),
        "new_family_income_cents": r["new_family_income_cents"],
        "status": "OPEN",
    })
    db.recertifications[new_rec["id"]] = new_rec

    return success_object(serialize_recertification(r))
