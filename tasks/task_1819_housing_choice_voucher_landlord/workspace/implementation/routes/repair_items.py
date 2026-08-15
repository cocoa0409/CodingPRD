"""RepairItem endpoints (mark-repaired, verify with abatement-cure cascade)."""

from datetime import date, timedelta

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.helpers import (
    get_or_404, landlord_of_repair_item, assert_landlord_owns,
)
from services.calculations import abatement_proration, _parse_iso_date

bp = Blueprint("repair_items", __name__)


def serialize_repair_item(ri):
    return {
        "id": ri["id"],
        "inspection_id": ri["inspection_id"],
        "description": ri["description"],
        "is_life_threatening": ri["is_life_threatening"],
        "status": ri["status"],
        "created_at": ri["created_at"],
        "updated_at": ri["updated_at"],
        "version": ri["version"],
    }


@bp.route("/hcv/repair-items/<rid>/mark-repaired", methods=["POST"])
def mark_repaired(rid):
    role, user_id = require_roles("Landlord")
    ri = get_or_404(db.repair_items, rid, "RepairItem")
    if ri["status"] not in ("OPEN", "FAILED_VERIFICATION"):
        raise errors.invalid_state("RepairItem must be OPEN or FAILED_VERIFICATION to mark repaired")
    owner = landlord_of_repair_item(ri)
    assert_landlord_owns(user_id, owner)
    ri["status"] = "REPAIRED"
    db.touch(ri)
    return success_object(serialize_repair_item(ri))


def _cure_abatement(contract, cure_date: date):
    """Contract ABATED -> ACTIVE cascade: unit back, payments recomputed."""
    abate_start_str = contract.get("abatement_start_date")
    abate_start = _parse_iso_date(abate_start_str) if abate_start_str else cure_date
    abate_end = cure_date  # exclusive

    contract["status"] = "ACTIVE"
    contract["abatement_start_date"] = None
    db.touch(contract)

    unit = db.units.get(contract["unit_id"])
    if unit and unit["status"] == "SUSPENDED_ABATEMENT":
        unit["status"] = "UNDER_CONTRACT"
        db.touch(unit)

    # Recompute ABATED_HELD payments in period_month ASC order
    rows = [p for p in db.hap_payments.values()
            if p["contract_id"] == contract["id"] and p["disbursement_status"] == "ABATED_HELD"]
    rows.sort(key=lambda p: p["period_month"])
    for p in rows:
        p["hap_amount_cents"] = abatement_proration(
            contract["hap_portion_cents"], p["period_month"], abate_start, abate_end
        )
        p["disbursement_status"] = "SCHEDULED"


@bp.route("/hcv/repair-items/<rid>/verify", methods=["POST"])
def verify_repair_item(rid):
    require_roles("Inspector")
    ri = get_or_404(db.repair_items, rid, "RepairItem")
    body = request.get_json(force=True, silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in ("PASS", "FAIL"):
        raise errors.invalid_amount("outcome must be PASS or FAIL")
    if ri["status"] != "REPAIRED":
        raise errors.invalid_state("RepairItem must be REPAIRED to verify")
    insp = db.inspections.get(ri["inspection_id"])
    if insp is None:
        raise errors.not_found("Parent Inspection not found")
    if insp["status"] != "REPAIR_VERIFICATION":
        raise errors.invalid_state("Parent Inspection must be REPAIR_VERIFICATION")

    today = db.current_logical_date()

    if outcome == "FAIL":
        ri["status"] = "FAILED_VERIFICATION"
        db.touch(ri)
        # Inspection REPAIR_VERIFICATION -> FAILED; repair-deadline clock restarts
        insp["status"] = "FAILED"
        insp["result_recorded_date"] = today.isoformat()
        db.touch(insp)
        return success_object(serialize_repair_item(ri))

    # outcome == PASS
    ri["status"] = "VERIFIED"
    db.touch(ri)

    # If this was the last non-VERIFIED item, close the inspection
    items = [x for x in db.repair_items.values() if x["inspection_id"] == insp["id"]]
    if all(x["status"] == "VERIFIED" for x in items):
        insp["status"] = "CLOSED"
        db.touch(insp)
        contract = db.hap_contracts.get(insp["contract_id"])
        if contract and contract["status"] == "ABATED":
            _cure_abatement(contract, today)

    return success_object(serialize_repair_item(ri))
