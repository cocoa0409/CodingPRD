"""Report routes: markers, finalize, revoke (PRD §3.4)."""
from flask import Blueprint, request

from db import db, create_versioned, create_light, touch
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_HEALTH_NOT_INCLUDED,
    ERR_STALE_VERSION,
)
from helpers import (
    get_json_body, require_fields, require_enum, parse_pagination, paginate,
)
from middleware import require_roles
from response import success, list_success
from serializers import (
    serialize_report, serialize_health_marker_result,
)
from services.common import get_or_404, require_account_owner
from services.report_service import (
    compute_at_risk_marker_count, recompute_pet_finalized_report_id,
)
from services.cascades import revoke_active_share_links_for_report

reports_bp = Blueprint("reports", __name__)


def _report_owner_account_id(report):
    pet = db.pets.get(report["pet_id"])
    return pet["account_id"] if pet else None


@reports_bp.route("/dna/reports/<rid>", methods=["GET"])
def get_report(rid):
    user_id, role = require_roles({"PlatformAdmin", "Account", "LabTechnician"})
    rec = get_or_404(db.reports, rid)
    if role == "Account":
        require_account_owner(_report_owner_account_id(rec), user_id, role)
    return success(serialize_report(rec), status=200)


@reports_bp.route("/dna/reports", methods=["GET"])
def list_reports():
    user_id, role = require_roles({"PlatformAdmin", "Account", "LabTechnician"})
    limit, offset = parse_pagination()
    sample_id = request.args.get("sample_id")
    pet_id = request.args.get("pet_id")

    items = list(db.reports.values())
    if sample_id is not None:
        items = [r for r in items if r["sample_id"] == sample_id]
    if pet_id is not None:
        items = [r for r in items if r["pet_id"] == pet_id]
    if role == "Account":
        owned_pet_ids = {p["id"] for p in db.pets.values() if p["account_id"] == user_id}
        items = [r for r in items if r["pet_id"] in owned_pet_ids]

    window, total = paginate(items, limit, offset)
    return list_success([serialize_report(r) for r in window], limit, offset, total)


@reports_bp.route("/dna/reports/<rid>/markers", methods=["POST"])
def add_marker(rid):
    require_roles({"LabTechnician"})
    report = get_or_404(db.reports, rid)

    body = get_json_body()
    require_fields(body, ["marker_code", "genotype"])
    require_enum(body["genotype"], {"CLEAR", "CARRIER", "AT_RISK"}, "genotype")
    review_status = body.get("review_status", "PASS")
    require_enum(review_status, {"PASS", "REVIEWED"}, "review_status")

    # Health section requires the originating kit product_tier == BREED_HEALTH;
    # i.e. report.includes_health must be true (priority 14).
    if not report["includes_health"]:
        raise err(ERR_HEALTH_NOT_INCLUDED,
                  "Report's kit does not include the genetic-health section")

    marker = create_light(db.health_marker_results, {
        "report_id": report["id"],
        "marker_code": body["marker_code"],
        "genotype": body["genotype"],
        "review_status": review_status,
    })

    # Recompute at_risk_marker_count (preliminary variant) and bump report version.
    report["at_risk_marker_count"] = compute_at_risk_marker_count(
        report["id"], finalized=(report["status"] == "FINALIZED")
    )
    touch(report)

    return success(serialize_health_marker_result(marker), status=201)


@reports_bp.route("/dna/reports/<rid>/markers", methods=["GET"])
def list_markers(rid):
    user_id, role = require_roles({"PlatformAdmin", "Account", "LabTechnician"})
    report = get_or_404(db.reports, rid)
    if role == "Account":
        require_account_owner(_report_owner_account_id(report), user_id, role)
    limit, offset = parse_pagination()
    items = [m for m in db.health_marker_results.values()
             if m["report_id"] == report["id"]]
    window, total = paginate(items, limit, offset)
    return list_success(
        [serialize_health_marker_result(m) for m in window], limit, offset, total
    )


@reports_bp.route("/dna/reports/<rid>/finalize", methods=["POST"])
def finalize_report(rid):
    require_roles({"LabTechnician"})
    report = get_or_404(db.reports, rid)

    # State precondition (priority 5): report PRELIMINARY.
    if report["status"] != "PRELIMINARY":
        raise err(ERR_INVALID_STATE, "Report is not in PRELIMINARY state")

    body = get_json_body()
    # expected_report_version is mandatory; absence -> invalid request (§2.9).
    require_fields(body, ["expected_report_version"])

    # Sample must be PASS, breed_composition sums to 100.00 (business precond).
    sample = db.samples.get(report["sample_id"])
    if sample is None or sample["status"] != "PASS":
        raise err(ERR_INVALID_STATE, "Report's sample is not in PASS state")

    # OCC check (priority 16): expected must equal live version.
    if body["expected_report_version"] != report["version"]:
        raise err(ERR_STALE_VERSION, "expected_report_version does not match")

    report["status"] = "FINALIZED"
    # Recompute at_risk_marker_count under finalized rule (includes REVIEWED).
    report["at_risk_marker_count"] = compute_at_risk_marker_count(
        report["id"], finalized=True
    )
    touch(report)

    # Set the report's pet's finalized_report_id to this report's id.
    pet = db.pets.get(report["pet_id"])
    if pet is not None:
        pet["finalized_report_id"] = report["id"]
        touch(pet)

    return success(serialize_report(report), status=200)


@reports_bp.route("/dna/reports/<rid>/revoke", methods=["POST"])
def revoke_report(rid):
    user_id, role = require_roles({"Account"})
    report = get_or_404(db.reports, rid)
    require_account_owner(_report_owner_account_id(report), user_id, role)

    # Revocable from PRELIMINARY or FINALIZED.
    if report["status"] not in ("PRELIMINARY", "FINALIZED"):
        raise err(ERR_INVALID_STATE, "Report cannot be revoked from its current state")

    was_finalized = report["status"] == "FINALIZED"
    report["status"] = "REVOKED"

    # Cascade: revoke all ACTIVE share links for this report.
    revoke_active_share_links_for_report(report["id"])

    # If this report is the pet's finalized_report_id, recompute back-pointer.
    pet = db.pets.get(report["pet_id"])
    if pet is not None and was_finalized and pet.get("finalized_report_id") == report["id"]:
        pet["finalized_report_id"] = recompute_pet_finalized_report_id(report["pet_id"])
        touch(pet)

    touch(report)
    return success(serialize_report(report), status=200)
