from flask import request

from db import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_OWNERSHIP_VIOLATION,
    ERR_PROVIDER_NOT_FOUND,
    raise_error,
)
from middleware import get_auth, require_roles
from response import paginate, success
from services import make_provider, serialise_program, serialise_provider
from validate import (
    ACCESS_ENUM,
    LANG_ENUM,
    parse_pagination,
    require_body,
    require_enum_subset,
    require_number,
    require_str,
)


def _provider_or_404(pid: str):
    p = db.providers.get(pid)
    if not p:
        raise_error(ERR_PROVIDER_NOT_FOUND, f"provider {pid} not found")
    return p


def _check_provider_ownership(p: dict) -> None:
    uid, role = get_auth()
    if role == "ProviderStaff" and uid != p["id"]:
        raise_error(ERR_OWNERSHIP_VIOLATION, "ProviderStaff does not own this provider")


def register(app):
    @app.post("/providers")
    @require_roles("PlatformAdmin")
    def create_provider():
        body = require_body(request.get_json(silent=True))
        legal_name = require_str(body, "legal_name")
        lat = require_number(body, "location_lat")
        lng = require_number(body, "location_lng")
        if lat < -90.0 or lat > 90.0:
            raise_error(ERR_INVALID_REQUEST, "location_lat out of range")
        if lng < -180.0 or lng > 180.0:
            raise_error(ERR_INVALID_REQUEST, "location_lng out of range")
        features = require_enum_subset(body, "accessibility_features", ACCESS_ENUM, non_empty=False)
        langs = require_enum_subset(body, "languages_supported", LANG_ENUM, non_empty=True)
        entity = make_provider(legal_name, lat, lng, features, langs)
        return success(serialise_provider(entity), 201)

    @app.get("/providers/<pid>")
    @require_roles("PlatformAdmin", "ProviderStaff", "Caseworker")
    def get_provider(pid):
        p = _provider_or_404(pid)
        _check_provider_ownership(p)
        return success(serialise_provider(p), 200)

    @app.get("/providers/<pid>/programs")
    @require_roles("PlatformAdmin", "ProviderStaff", "Caseworker")
    def list_provider_programs(pid):
        p = _provider_or_404(pid)
        _check_provider_ownership(p)
        limit, offset = parse_pagination(request.args)
        items = [pr for pr in db.programs.values() if pr["provider_id"] == pid]
        items.sort(key=lambda x: x["created_at"])
        window, pg = paginate(items, limit, offset)
        return success([serialise_program(pr) for pr in window], 200, "array", pg)
