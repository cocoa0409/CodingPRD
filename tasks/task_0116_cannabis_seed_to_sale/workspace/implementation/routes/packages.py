"""Package endpoints (PRD §3.4, §3.5, §3.8) plus reverse-reachability reads."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
from errors import err
from helpers import (get_json_body, require_fields, is_number, paginate,
                     sort_by_created, stamp_create, touch)
from middleware import require_auth, get_identity
from response import object_response, array_response
from serializers import (package_view, lab_result_view,
                         reconciliation_count_view, waste_event_view,
                         manifest_line_view, sale_line_view)
from services import recompute_harvest_yield

bp = Blueprint("packages", __name__)

ALL_READ = ["Cultivator", "ComplianceManager", "DistributionAgent", "Budtender",
            "QALabUser", "InventoryAuditor", "StateRegulator"]


def get_package_or_404(package_id):
    p = db.packages.get(package_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Package not found.")
    return p


@bp.route("/compliance/packages", methods=["POST"])
@require_auth(["Cultivator", "ComplianceManager"])
def create_package():
    body = get_json_body()
    require_fields(body, ["harvest_id", "package_tag", "product_category", "quantity_grams"])

    harvest_id = body["harvest_id"]
    package_tag = body["package_tag"]
    product_category = body["product_category"]
    quantity = body["quantity_grams"]

    if not isinstance(package_tag, str) or not package_tag:
        raise err("ERR_INVALID_REQUEST", "package_tag must be a non-empty string.")
    if product_category not in constants.PRODUCT_CATEGORIES:
        raise err("ERR_INVALID_REQUEST", "Invalid product_category.")
    if not is_number(quantity) or quantity <= 0:
        raise err("ERR_INVALID_REQUEST", "quantity_grams must be > 0.")

    # Existence: harvest (priority 3).
    harvest = db.harvests.get(harvest_id)
    if harvest is None:
        raise err("ERR_NOT_FOUND", "Harvest not found.")

    # Parent state (priority 17): harvest must be CURED.
    if harvest["status"] != "CURED":
        raise err("ERR_INVALID_PARENT_STATE", "Harvest must be CURED to package from.")

    # License-active (priority 5): owning license must be ACTIVE.
    lic = db.licenses.get(harvest["license_id"])
    if lic is None:
        raise err("ERR_NOT_FOUND", "Owning license not found.")
    if lic["status"] != "ACTIVE":
        raise err("ERR_LICENSE_NOT_ACTIVE", "Owning license is not ACTIVE.")

    # Tag uniqueness (priority 10).
    for p in db.packages.values():
        if p["package_tag"] == package_tag:
            raise err("ERR_DUPLICATE_TAG", "package_tag already exists.")

    # Quantity sufficiency (priority 11): must not exceed harvest remaining.
    remaining = harvest.get("remaining_weight_grams")
    if remaining is None:
        raise err("ERR_INVALID_PARENT_STATE", "Harvest remaining weight is undefined.")
    if Decimal(str(quantity)) > Decimal(str(remaining)):
        raise err("ERR_INSUFFICIENT_QUANTITY", "quantity_grams exceeds harvest remaining_weight_grams.")

    rec = {
        "id": db.new_id(),
        "harvest_id": harvest_id,
        "license_id": harvest["license_id"],  # custodying license, initially harvest's
        "package_tag": package_tag,
        "product_category": product_category,
        "quantity_grams": quantity,
        "remaining_grams": quantity,
        "status": "TESTING",
        "lab_hold": True,
        "thc_pct": None,
    }
    stamp_create(rec)
    db.packages[rec["id"]] = rec

    # Cascade: recompute harvest yield + bump harvest version.
    recompute_harvest_yield(harvest)
    touch(harvest)

    return object_response(package_view(rec), 201)


@bp.route("/compliance/packages", methods=["GET"])
@require_auth(ALL_READ, open_read=True)
def list_packages():
    items = list(db.packages.values())
    harvest_id = request.args.get("harvest_id")
    license_id = request.args.get("license_id")
    status = request.args.get("status")
    if harvest_id is not None:
        items = [r for r in items if r["harvest_id"] == harvest_id]
    if license_id is not None:
        items = [r for r in items if r["license_id"] == license_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([package_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/packages/<package_id>", methods=["GET"])
@require_auth(ALL_READ, open_read=True)
def get_package(package_id):
    return object_response(package_view(get_package_or_404(package_id)))


@bp.route("/compliance/packages/<package_id>/lab-results", methods=["GET"])
@require_auth(["Cultivator", "ComplianceManager", "QALabUser", "StateRegulator", "InventoryAuditor"], open_read=True)
def list_package_lab_results(package_id):
    get_package_or_404(package_id)
    items = [r for r in db.lab_results.values() if r["package_id"] == package_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([lab_result_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/packages/<package_id>/reconciliation-counts", methods=["GET"])
@require_auth(["ComplianceManager", "InventoryAuditor", "StateRegulator"], open_read=True)
def list_package_recounts(package_id):
    get_package_or_404(package_id)
    items = [r for r in db.reconciliation_counts.values() if r["package_id"] == package_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([reconciliation_count_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/packages/<package_id>/waste-events", methods=["GET"])
@require_auth(["ComplianceManager", "Cultivator", "InventoryAuditor", "StateRegulator"], open_read=True)
def list_package_waste_events(package_id):
    get_package_or_404(package_id)
    items = [r for r in db.waste_events.values() if r.get("package_id") == package_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([waste_event_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/packages/<package_id>/manifest-lines", methods=["GET"])
@require_auth(["DistributionAgent", "ComplianceManager", "StateRegulator"], open_read=True)
def list_package_manifest_lines(package_id):
    get_package_or_404(package_id)
    items = [r for r in db.manifest_lines.values() if r["package_id"] == package_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([manifest_line_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/packages/<package_id>/sale-lines", methods=["GET"])
@require_auth(["Budtender", "ComplianceManager", "StateRegulator"], open_read=True)
def list_package_sale_lines(package_id):
    get_package_or_404(package_id)
    items = [r for r in db.sale_lines.values() if r["package_id"] == package_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([sale_line_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/packages/<package_id>/release", methods=["POST"])
@require_auth(["ComplianceManager"])
def release_package(package_id):
    pkg = get_package_or_404(package_id)
    user_id, _ = get_identity()

    # State (priority 4): must be PASSED.
    if pkg["status"] != "PASSED":
        raise err("ERR_INVALID_STATE", "Package must be PASSED to release.")
    # lab_hold must be false (it is on PASS, but guard anyway).
    if pkg.get("lab_hold"):
        raise err("ERR_INVALID_STATE", "Package is on lab hold.")

    # Segregation of duties (priority 7): releaser != QALabUser who recorded PASS.
    if pkg.get("_pass_lab_user_id") is not None and pkg["_pass_lab_user_id"] == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Releasing operator cannot be the QALabUser who recorded the PASS result.")

    pkg["status"] = "ACTIVE"
    touch(pkg)
    return object_response(package_view(pkg))


@bp.route("/compliance/packages/<package_id>/clear-hold", methods=["POST"])
@require_auth(["ComplianceManager"])
def clear_hold(package_id):
    pkg = get_package_or_404(package_id)
    user_id, _ = get_identity()

    # State (priority 4): must be ON_HOLD.
    if pkg["status"] != "ON_HOLD":
        raise err("ERR_INVALID_STATE", "Package must be ON_HOLD to clear.")

    # Segregation of duties (priority 7): clearer != auditor who placed the hold.
    if pkg.get("_hold_auditor_user_id") is not None and pkg["_hold_auditor_user_id"] == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Clearing operator cannot be the InventoryAuditor whose count placed the hold.")

    pkg["status"] = "ACTIVE"
    touch(pkg)
    return object_response(package_view(pkg))
