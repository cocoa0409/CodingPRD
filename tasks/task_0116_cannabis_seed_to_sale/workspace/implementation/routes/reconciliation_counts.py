"""ReconciliationCount endpoints (PRD §3.8). Append-only; DISCREPANCY -> ON_HOLD."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
from errors import err
from helpers import (get_json_body, require_fields, is_number, round2,
                     paginate, sort_by_created, stamp_create, touch)
from middleware import require_auth
from response import object_response, array_response
from serializers import reconciliation_count_view

bp = Blueprint("reconciliation_counts", __name__)

READ_ROLES = ["InventoryAuditor", "ComplianceManager", "StateRegulator"]


@bp.route("/compliance/reconciliation-counts", methods=["POST"])
@require_auth(["InventoryAuditor"])
def create_reconciliation_count():
    body = get_json_body()
    require_fields(body, ["package_id", "counted_by_user_id", "counted_grams", "counted_at"])
    package_id = body["package_id"]
    counted_by_user_id = body["counted_by_user_id"]
    counted_grams = body["counted_grams"]
    counted_at = body["counted_at"]

    if not is_number(counted_grams) or counted_grams < 0:
        raise err("ERR_INVALID_REQUEST", "counted_grams must be >= 0.")

    # Existence (priority 3): package.
    pkg = db.packages.get(package_id)
    if pkg is None:
        raise err("ERR_NOT_FOUND", "Package not found.")

    # Compute variance + outcome.
    expected = Decimal(str(pkg["remaining_grams"]))
    variance = round2(Decimal(str(counted_grams)) - expected)
    tolerance = Decimal(constants.RECON_TOLERANCE_GRAMS)
    outcome = "MATCH" if abs(Decimal(str(variance))) <= tolerance else "DISCREPANCY"

    rec = {
        "id": db.new_id(),
        "package_id": package_id,
        "counted_by_user_id": counted_by_user_id,
        "counted_grams": counted_grams,
        "expected_grams": round2(expected),
        "variance_grams": variance,
        "outcome": outcome,
        "counted_at": counted_at,
    }
    stamp_create(rec, versioned=False)
    db.reconciliation_counts[rec["id"]] = rec

    # Cascade: DISCREPANCY drives an ACTIVE package to ON_HOLD.
    if outcome == "DISCREPANCY" and pkg["status"] == "ACTIVE":
        pkg["status"] = "ON_HOLD"
        # remember the auditor (counted_by_user_id) for segregation of duties.
        pkg["_hold_auditor_user_id"] = counted_by_user_id
        touch(pkg)

    return object_response(reconciliation_count_view(rec), 201)


@bp.route("/compliance/reconciliation-counts", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def list_reconciliation_counts():
    items = list(db.reconciliation_counts.values())
    package_id = request.args.get("package_id")
    outcome = request.args.get("outcome")
    if package_id is not None:
        items = [r for r in items if r["package_id"] == package_id]
    if outcome is not None:
        items = [r for r in items if r["outcome"] == outcome]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([reconciliation_count_view(r) for r in page], limit, offset, total)
