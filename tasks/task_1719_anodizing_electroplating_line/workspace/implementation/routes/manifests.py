"""Waste manifest endpoints: create/get, line items, finalize, ship, receive."""
from flask import Blueprint

from db import store
from errors import (
    ERR_DISCHARGE_EXCEEDANCE_HOLD,
    ERR_INVALID_REQUEST,
    ERR_MANIFEST_EMPTY,
    ERR_MANIFEST_NOT_DRAFT,
    ERR_MANIFEST_NOT_FINALIZED,
    ERR_MANIFEST_NOT_SHIPPED,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    raise_err,
)
from helpers import (
    body_json,
    check_enum,
    check_number,
    check_string,
    get_or_404,
    is_int,
    paginate,
    parse_pagination,
    stamp_new,
    touch,
)
from middleware import require_roles, STAFF_ROLES
from response import no_content, success_list, success_object
from serializers import manifest_line_item_view, manifest_view
from services.manifest_calc import line_mass_kg, recompute_manifest_total

bp = Blueprint("manifests", __name__)

SOURCE_TYPES = {"BATH_DUMP", "SLUDGE_PRESS", "RINSE_CONCENTRATE"}
MANIFEST_ROLES = {"EHSOfficer", "ShopManager"}


@bp.route("/waste-manifests", methods=["POST"])
def create_manifest():
    user_id, role = require_roles(MANIFEST_ROLES)
    data = body_json()
    generator_epa_id = check_string(data, "generator_epa_id", required=True)
    transporter_name = check_string(data, "transporter_name", required=False)

    manifest = stamp_new({
        "generator_epa_id": generator_epa_id,
        "transporter_name": transporter_name,
        "created_by_user_id": user_id,
        "finalized_by_user_id": None,
        "total_mass_kg": 0.0,
        "status": "DRAFT",
    })
    store.manifests[manifest["id"]] = manifest
    return success_object(manifest_view(manifest), status=201)


@bp.route("/waste-manifests/<manifest_id>", methods=["GET"])
def get_manifest(manifest_id):
    user_id, role = require_roles(STAFF_ROLES)
    manifest = get_or_404(store.manifests, manifest_id)
    return success_object(manifest_view(manifest))


@bp.route("/waste-manifests/<manifest_id>/line-items", methods=["POST"])
def add_line_item(manifest_id):
    user_id, role = require_roles(MANIFEST_ROLES)
    manifest = get_or_404(store.manifests, manifest_id)
    data = body_json()
    waste_code = check_string(data, "waste_code", required=True)
    source_type = check_enum(data, "source_type", SOURCE_TYPES, required=True)
    description = check_string(data, "description", required=True)
    volume_liters = check_number(data, "volume_liters", required=True, gt=0)
    expected_manifest_version = data.get("expected_manifest_version")
    if expected_manifest_version is None or not is_int(expected_manifest_version):
        raise_err(ERR_INVALID_REQUEST, "expected_manifest_version is required and must be an integer")

    # Tier 6: OCC
    if expected_manifest_version != manifest["version"]:
        raise_err(ERR_STALE_VERSION, "expected_manifest_version does not match the manifest's current version")

    # Tier 7: manifest must be DRAFT
    if manifest["status"] != "DRAFT":
        raise_err(ERR_MANIFEST_NOT_DRAFT, "line items may only be added to a DRAFT manifest")

    line = stamp_new({
        "manifest_id": manifest["id"],
        "waste_code": waste_code,
        "source_type": source_type,
        "description": description,
        "volume_liters": volume_liters,
        "mass_kg": line_mass_kg(source_type, volume_liters),
        "origin_bath_id": None,
    })
    store.manifest_line_items[line["id"]] = line
    recompute_manifest_total(manifest)
    touch(manifest)
    return success_object(manifest_line_item_view(line), status=201)


@bp.route("/waste-manifests/<manifest_id>/line-items/<line_item_id>", methods=["DELETE"])
def remove_line_item(manifest_id, line_item_id):
    user_id, role = require_roles(MANIFEST_ROLES)
    # Tier 4: path ids left-to-right
    manifest = store.manifests.get(manifest_id)
    if manifest is None:
        raise_err(ERR_NOT_FOUND, "manifest not found")
    line = store.manifest_line_items.get(line_item_id)
    if line is None or line["manifest_id"] != manifest["id"]:
        raise_err(ERR_NOT_FOUND, "line item not found")

    # Tier 7: manifest must be DRAFT
    if manifest["status"] != "DRAFT":
        raise_err(ERR_MANIFEST_NOT_DRAFT, "line items may only be removed from a DRAFT manifest")

    del store.manifest_line_items[line_item_id]
    recompute_manifest_total(manifest)
    touch(manifest)
    return no_content()


@bp.route("/waste-manifests/<manifest_id>/line-items", methods=["GET"])
def list_line_items(manifest_id):
    user_id, role = require_roles(STAFF_ROLES)
    manifest = get_or_404(store.manifests, manifest_id)
    limit, offset = parse_pagination()
    items = [li for li in store.manifest_line_items.values() if li["manifest_id"] == manifest["id"]]
    items.sort(key=lambda li: (li["created_at"], li["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([manifest_line_item_view(li) for li in page], limit, offset, total)


@bp.route("/waste-manifests/<manifest_id>/finalize", methods=["POST"])
def finalize_manifest(manifest_id):
    user_id, role = require_roles(MANIFEST_ROLES)
    manifest = get_or_404(store.manifests, manifest_id)

    # Tier 7: manifest must be DRAFT
    if manifest["status"] != "DRAFT":
        raise_err(ERR_MANIFEST_NOT_DRAFT, "finalize requires manifest DRAFT")

    # Tier 10: segregation of duties (before the tier-12 exceedance hold),
    # then manifest non-empty (both tier 10)
    if user_id == manifest["created_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "finalizer must differ from the manifest creator")
    has_lines = any(li["manifest_id"] == manifest["id"] for li in store.manifest_line_items.values())
    if not has_lines:
        raise_err(ERR_MANIFEST_EMPTY, "finalize requires at least one line item")

    # Tier 12: compliance hold
    for permit in store.permits.values():
        if permit.get("exceedance_active"):
            raise_err(ERR_DISCHARGE_EXCEEDANCE_HOLD, "a discharge permit has an active exceedance")

    manifest["finalized_by_user_id"] = user_id
    manifest["status"] = "FINALIZED"
    touch(manifest)
    return success_object(manifest_view(manifest))


@bp.route("/waste-manifests/<manifest_id>/ship", methods=["POST"])
def ship_manifest(manifest_id):
    user_id, role = require_roles(MANIFEST_ROLES)
    manifest = get_or_404(store.manifests, manifest_id)
    data = body_json()
    transporter_name = data.get("transporter_name")

    # Tier 7: manifest must be FINALIZED
    if manifest["status"] != "FINALIZED":
        raise_err(ERR_MANIFEST_NOT_FINALIZED, "ship requires manifest FINALIZED")
    # Schema: transporter required at ship
    if transporter_name is None or not isinstance(transporter_name, str) or not transporter_name:
        raise_err(ERR_INVALID_REQUEST, "transporter_name is required at ship")

    manifest["transporter_name"] = transporter_name
    manifest["status"] = "SHIPPED"
    touch(manifest)
    return success_object(manifest_view(manifest))


@bp.route("/waste-manifests/<manifest_id>/receive", methods=["POST"])
def receive_manifest(manifest_id):
    user_id, role = require_roles(MANIFEST_ROLES)
    manifest = get_or_404(store.manifests, manifest_id)
    if manifest["status"] != "SHIPPED":
        raise_err(ERR_MANIFEST_NOT_SHIPPED, "receive requires manifest SHIPPED")
    manifest["status"] = "RECEIVED"
    touch(manifest)
    return success_object(manifest_view(manifest))
