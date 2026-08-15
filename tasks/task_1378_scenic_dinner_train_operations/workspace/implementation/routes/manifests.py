"""Provisioning manifests: LOCK (OCC on expected_manifest_version; freezes
counts and stamps locked_at) and MARK_PROVISIONED (actual_loaded_units must
cover galley_load_units)."""
from flask import Blueprint

import db
from auth import ALL_ROLES, require_roles
from db import clock_now, public, touch
from envelope import success_obj
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PROVISION_SHORTFALL,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
)
from services.core import manifest_view
from timeutil import iso_z
from validators import body, opt_int

bp = Blueprint("manifests", __name__)


def get_manifest_or_404(manifest_id):
    manifest = db.manifests.get(manifest_id)
    if manifest is None:
        raise ApiError(ERR_NOT_FOUND, "Provisioning manifest not found", 404)
    return manifest


@bp.get("/railroad/manifests/<mid>")
def get_manifest(mid):
    require_roles(*ALL_ROLES)
    return success_obj(manifest_view(get_manifest_or_404(mid)), 200)


@bp.post("/railroad/manifests/<mid>/events")
def manifest_event(mid):
    require_roles("CateringManager")
    manifest = get_manifest_or_404(mid)
    data = body()
    event_type = data.get("event_type")
    if event_type == "LOCK":
        if manifest["status"] != "DRAFT":
            raise ApiError(
                ERR_INVALID_STATE, "Only a DRAFT manifest can be locked", 409
            )
        # OCC (tier 6): a stale expected version is rejected with 412.
        expected = opt_int(data, "expected_manifest_version")
        if expected is not None and expected != manifest["version"]:
            raise ApiError(
                ERR_STALE_VERSION,
                "expected_manifest_version does not match the current version",
                412,
            )
        manifest["locked_at"] = iso_z(clock_now())
        manifest["status"] = "LOCKED"
        touch(manifest)
    elif event_type == "MARK_PROVISIONED":
        if manifest["status"] != "LOCKED":
            raise ApiError(
                ERR_INVALID_STATE,
                "Only a LOCKED manifest can be marked provisioned",
                409,
            )
        actual = opt_int(data, "actual_loaded_units")
        if actual is None:
            raise ApiError(
                ERR_VALIDATION, "actual_loaded_units is required", 400
            )
        if actual < manifest["galley_load_units"]:
            raise ApiError(
                ERR_PROVISION_SHORTFALL,
                "actual_loaded_units is below galley_load_units",
                409,
            )
        manifest["actual_loaded_units"] = actual
        manifest["status"] = "PROVISIONED"
        touch(manifest)
    else:
        raise ApiError(ERR_VALIDATION, "Unknown event_type: %r" % event_type, 400)
    return success_obj(manifest_view(manifest), 200)
