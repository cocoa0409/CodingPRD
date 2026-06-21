"""Replacement endpoints (PRD §3.10)."""
from flask import Blueprint, request

import serialize
from db import store
from errors import (
    err, ERR_INVALID_STATE, ERR_EDUCATION_REQUIRED,
)
from middleware import require_roles
from response import success, success_list
from validation import (
    get_json_body, as_nonempty_str, as_enum, parse_pagination, paginate,
)
from services.core import (
    get_license_or_404, get_replacement_or_404, compute_replacement_admin_fee,
    check_residency_restriction,
)

bp = Blueprint("replacements", __name__)

REASONS = {"LOST", "DAMAGED", "STOLEN"}


@bp.route("/replacements", methods=["POST"])
@require_roles("LicenseAgent", "DrawOfficer")
def create_replacement():
    body = get_json_body()
    original_license_id = as_nonempty_str(body, "original_license_id", required=True)
    reason = as_enum(body, "reason", REASONS, required=True)

    # FK existence (PRD §2.5).
    original = get_license_or_404(original_license_id)

    # State: the original license must be ISSUED (PRD §3.10).
    if original["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "Original license is not ISSUED")

    product = store.license_products[original["license_product_id"]]
    applicant = store.applicants[original["applicant_id"]]

    # Education prerequisite and residency restriction apply (PRD §3.10).
    if product["requires_education"] and not applicant["education_certified"]:
        raise err(ERR_EDUCATION_REQUIRED, "Applicant is not education-certified")
    check_residency_restriction(product, applicant)

    # Atomic cascade.
    admin_fee = compute_replacement_admin_fee(original, reason)

    # Mint replacement License: same product/applicant, copy draw_application_id,
    # OVER_THE_COUNTER, fee_charged_cents = 0 (PRD §3.10).
    new_license = {
        "applicant_id": original["applicant_id"],
        "license_product_id": original["license_product_id"],
        "draw_application_id": original["draw_application_id"],
        "issued_via": "OVER_THE_COUNTER",
        "fee_charged_cents": 0,
        "status": "ISSUED",
        "superseded_by_id": None,
    }
    store.stamp_new(new_license)
    store.licenses[new_license["id"]] = new_license

    # Void the original.
    original["status"] = "VOIDED"
    original["superseded_by_id"] = new_license["id"]
    store.touch(original)

    # Re-link the original's still-SUBMITTED harvest reports to the replacement.
    for hr in store.harvest_reports.values():
        if hr["license_id"] == original["id"] and hr["status"] == "SUBMITTED":
            hr["license_id"] = new_license["id"]
            store.touch(hr)

    record = {
        "original_license_id": original_license_id,
        "reason": reason,
        "replacement_license_id": new_license["id"],
        "admin_fee_cents": admin_fee,
    }
    store.stamp_new(record)
    store.replacements[record["id"]] = record
    return success(serialize.replacement(record), status=201, response_type="object")


@bp.route("/replacements/<id>", methods=["GET"])
@require_roles("DrawOfficer", "LicenseAgent", "Applicant")
def get_replacement(id):
    record = get_replacement_or_404(id)
    return success(serialize.replacement(record), status=200, response_type="object")


@bp.route("/replacements", methods=["GET"])
@require_roles("DrawOfficer", "LicenseAgent", "Applicant")
def list_replacements():
    limit, offset = parse_pagination()
    items = list(store.replacements.values())
    original_license_id = request.args.get("original_license_id")
    if original_license_id is not None:
        items = [r for r in items if r["original_license_id"] == original_license_id]
    replacement_license_id = request.args.get("replacement_license_id")
    if replacement_license_id is not None:
        items = [r for r in items if r["replacement_license_id"] == replacement_license_id]
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize.replacement(r) for r in page], limit, offset, total
    )
