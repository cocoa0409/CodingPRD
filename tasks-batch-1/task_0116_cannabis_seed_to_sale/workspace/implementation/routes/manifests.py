"""Manifest + ManifestLine endpoints (PRD §3.6)."""
from decimal import Decimal

from flask import Blueprint, request

import clock
import db
from errors import err
from helpers import (get_json_body, require_fields, is_number, is_int, round2,
                     paginate, sort_by_created, stamp_create, touch)
from middleware import require_auth
from response import object_response, array_response
from serializers import manifest_view, manifest_line_view

bp = Blueprint("manifests", __name__)

READ_ROLES = ["DistributionAgent", "ComplianceManager", "StateRegulator"]


def get_manifest_or_404(manifest_id):
    m = db.manifests.get(manifest_id)
    if m is None:
        raise err("ERR_NOT_FOUND", "Manifest not found.")
    return m


def recompute_manifest_aggregates(manifest):
    lines = [l for l in db.manifest_lines.values() if l["manifest_id"] == manifest["id"]]
    manifest["line_count"] = len(lines)
    total = Decimal("0")
    for l in lines:
        total += Decimal(str(l["grams"]))
    manifest["total_grams"] = round2(total)


@bp.route("/compliance/manifests", methods=["POST"])
@require_auth(["DistributionAgent"])
def create_manifest():
    body = get_json_body()
    require_fields(body, ["origin_license_id", "destination_license_id"])
    origin_id = body["origin_license_id"]
    dest_id = body["destination_license_id"]

    # Existence (priority 3): both licenses.
    origin = db.licenses.get(origin_id)
    if origin is None:
        raise err("ERR_NOT_FOUND", "Origin license not found.")
    dest = db.licenses.get(dest_id)
    if dest is None:
        raise err("ERR_NOT_FOUND", "Destination license not found.")

    rec = {
        "id": db.new_id(),
        "origin_license_id": origin_id,
        "destination_license_id": dest_id,
        "status": "DRAFT",
        "line_count": 0,
        "total_grams": 0,
        "departed_at": None,
    }
    stamp_create(rec)
    db.manifests[rec["id"]] = rec
    return object_response(manifest_view(rec), 201)


@bp.route("/compliance/manifests", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def list_manifests():
    items = list(db.manifests.values())
    origin = request.args.get("origin_license_id")
    dest = request.args.get("destination_license_id")
    status = request.args.get("status")
    if origin is not None:
        items = [r for r in items if r["origin_license_id"] == origin]
    if dest is not None:
        items = [r for r in items if r["destination_license_id"] == dest]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([manifest_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/manifests/<manifest_id>", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def get_manifest(manifest_id):
    return object_response(manifest_view(get_manifest_or_404(manifest_id)))


@bp.route("/compliance/manifests/<manifest_id>/lines", methods=["POST"])
@require_auth(["DistributionAgent"])
def add_manifest_line(manifest_id):
    manifest = get_manifest_or_404(manifest_id)
    body = get_json_body()
    require_fields(body, ["package_id", "grams"])
    package_id = body["package_id"]
    grams = body["grams"]
    if not is_number(grams) or grams <= 0:
        raise err("ERR_INVALID_REQUEST", "grams must be > 0.")

    # Existence (priority 3): package.
    pkg = db.packages.get(package_id)
    if pkg is None:
        raise err("ERR_NOT_FOUND", "Package not found.")

    # Parent state (priority 17): manifest must be DRAFT.
    if manifest["status"] != "DRAFT":
        raise err("ERR_INVALID_PARENT_STATE", "Manifest must be DRAFT to attach a line.")

    # Quantity sufficiency (priority 11): grams <= package remaining.
    if Decimal(str(grams)) > Decimal(str(pkg["remaining_grams"])):
        raise err("ERR_INSUFFICIENT_QUANTITY", "grams exceed package remaining_grams.")

    # Manifest overlap (priority 12): package not on another open manifest line.
    for l in db.manifest_lines.values():
        if l["package_id"] == package_id:
            other = db.manifests.get(l["manifest_id"])
            if other is not None and other["status"] in ("DRAFT", "IN_TRANSIT"):
                raise err("ERR_MANIFEST_OVERLAP", "Package is already on an open manifest line.")

    rec = {
        "id": db.new_id(),
        "manifest_id": manifest_id,
        "package_id": package_id,
        "grams": grams,
    }
    stamp_create(rec, versioned=False)
    db.manifest_lines[rec["id"]] = rec

    recompute_manifest_aggregates(manifest)
    touch(manifest)
    return object_response(manifest_line_view(rec), 201)


@bp.route("/compliance/manifests/<manifest_id>/lines", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def list_manifest_lines(manifest_id):
    get_manifest_or_404(manifest_id)
    items = [l for l in db.manifest_lines.values() if l["manifest_id"] == manifest_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([manifest_line_view(r) for r in page], limit, offset, total)


def _manifest_packages(manifest_id):
    """Distinct packages referenced by this manifest's lines, in line order."""
    seen = set()
    result = []
    lines = sort_by_created([l for l in db.manifest_lines.values() if l["manifest_id"] == manifest_id])
    for l in lines:
        pid = l["package_id"]
        if pid in seen:
            continue
        seen.add(pid)
        pkg = db.packages.get(pid)
        if pkg is not None:
            result.append(pkg)
    return result


@bp.route("/compliance/manifests/<manifest_id>/depart", methods=["POST"])
@require_auth(["DistributionAgent"])
def depart_manifest(manifest_id):
    manifest = get_manifest_or_404(manifest_id)
    body = get_json_body()
    require_fields(body, ["expected_manifest_version"])
    expected = body["expected_manifest_version"]

    # State (priority 4): must be DRAFT.
    if manifest["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Manifest must be DRAFT to depart.")

    # has >= 1 line.
    lines = [l for l in db.manifest_lines.values() if l["manifest_id"] == manifest_id]
    if len(lines) < 1:
        raise err("ERR_INVALID_STATE", "Manifest must have at least one line to depart.")

    pkgs = _manifest_packages(manifest_id)

    # License-active (priority 5): origin license must be ACTIVE.
    origin = db.licenses.get(manifest["origin_license_id"])
    if origin is None:
        raise err("ERR_NOT_FOUND", "Origin license not found.")
    if origin["status"] != "ACTIVE":
        raise err("ERR_LICENSE_NOT_ACTIVE", "Origin license is not ACTIVE.")

    # Lab hold (priority 8): every line package lab_hold must be false.
    for pkg in pkgs:
        if pkg.get("lab_hold"):
            raise err("ERR_LAB_HOLD_ACTIVE", "A package on this manifest is on lab hold.")

    # Every line's package must be ACTIVE (state precondition, §3.6).
    for pkg in pkgs:
        if pkg["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Every line package must be ACTIVE to depart.")

    # OCC (priority 15): expected_manifest_version must match.
    if not is_int(expected):
        raise err("ERR_INVALID_REQUEST", "expected_manifest_version must be an integer.")
    if expected != manifest["version"]:
        raise err("ERR_STALE_VERSION", "expected_manifest_version does not match current version.")

    # Apply: manifest -> IN_TRANSIT; cascade packages -> IN_TRANSIT.
    manifest["status"] = "IN_TRANSIT"
    manifest["departed_at"] = clock.now_iso()
    for pkg in pkgs:
        pkg["status"] = "IN_TRANSIT"
        touch(pkg)
    touch(manifest)
    return object_response(manifest_view(manifest))


@bp.route("/compliance/manifests/<manifest_id>/recall", methods=["POST"])
@require_auth(["DistributionAgent"])
def recall_manifest(manifest_id):
    manifest = get_manifest_or_404(manifest_id)
    if manifest["status"] != "IN_TRANSIT":
        raise err("ERR_INVALID_STATE", "Manifest must be IN_TRANSIT to recall.")

    pkgs = _manifest_packages(manifest_id)
    manifest["status"] = "DRAFT"
    manifest["departed_at"] = None
    for pkg in pkgs:
        if pkg["status"] == "IN_TRANSIT":
            pkg["status"] = "ACTIVE"
            touch(pkg)
    touch(manifest)
    return object_response(manifest_view(manifest))


@bp.route("/compliance/manifests/<manifest_id>/receive", methods=["POST"])
@require_auth(["DistributionAgent"])
def receive_manifest(manifest_id):
    manifest = get_manifest_or_404(manifest_id)
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("accept", "reject"):
        raise err("ERR_INVALID_REQUEST", "decision must be 'accept' or 'reject'.")

    # State (priority 4): must be IN_TRANSIT.
    if manifest["status"] != "IN_TRANSIT":
        raise err("ERR_INVALID_STATE", "Manifest must be IN_TRANSIT to receive.")

    pkgs = _manifest_packages(manifest_id)

    if decision == "accept":
        # Destination license must be ACTIVE.
        dest = db.licenses.get(manifest["destination_license_id"])
        if dest is None:
            raise err("ERR_NOT_FOUND", "Destination license not found.")
        if dest["status"] != "ACTIVE":
            raise err("ERR_LICENSE_NOT_ACTIVE", "Destination license is not ACTIVE.")
        manifest["status"] = "RECEIVED"
        for pkg in pkgs:
            pkg["license_id"] = manifest["destination_license_id"]
            pkg["status"] = "ACTIVE"
            touch(pkg)
    else:  # reject
        manifest["status"] = "REJECTED"
        for pkg in pkgs:
            # custody stays at origin (license_id unchanged).
            pkg["status"] = "ACTIVE"
            touch(pkg)

    touch(manifest)
    return object_response(manifest_view(manifest))


@bp.route("/compliance/manifests/<manifest_id>/void", methods=["POST"])
@require_auth(["ComplianceManager"])
def void_manifest(manifest_id):
    manifest = get_manifest_or_404(manifest_id)
    if manifest["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Manifest must be DRAFT to void.")
    manifest["status"] = "VOIDED"
    touch(manifest)
    return object_response(manifest_view(manifest))
