"""Provider onboarding and listing endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import (
    ROLE_CLINIC_ADMIN,
    ROLE_NURSE,
    ROLE_PROVIDER,
    ROLE_RECEPTIONIST,
    require_roles,
)
from ..clock import now
from ..errors import err_invalid_input
from ..helpers import (
    assert_bool,
    assert_enum,
    assert_integer,
    assert_string,
    new_uuid,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.lookups import get_provider
from ..services.serialize import provider_to_dict
from ..store import store

bp = Blueprint("providers", __name__)

ROLE_TYPES = ["PCP_ONLY", "SPECIALIST_ONLY", "BOTH"]
NPI_PATTERN = r"^[0-9]{10}$"


@bp.route("/providers", methods=["POST"])
@require_roles(ROLE_CLINIC_ADMIN)
def create_provider(**_kwargs):
    body = require_json_object()
    npi = assert_string(body.get("npi"), "npi", pattern=NPI_PATTERN)
    full_name = assert_string(body.get("full_name"), "full_name")
    role_type = assert_enum(body.get("role_type"), "role_type", ROLE_TYPES)
    specialty = body.get("specialty")
    if role_type in {"SPECIALIST_ONLY", "BOTH"}:
        specialty = assert_string(specialty, "specialty")
    else:
        if specialty is not None and not isinstance(specialty, str):
            raise err_invalid_input("specialty must be a string when supplied")

    dea = body.get("dea_number")
    if dea is not None and not isinstance(dea, str):
        raise err_invalid_input("dea_number must be a string")
    epcs_enrolled = body.get("epcs_enrolled", False)
    if epcs_enrolled is None:
        epcs_enrolled = False
    epcs_enrolled = assert_bool(epcs_enrolled, "epcs_enrolled")

    panel_cap = body.get("panel_cap", 2000)
    if panel_cap is None:
        panel_cap = 2000
    panel_cap = assert_integer(panel_cap, "panel_cap", minimum=0)

    s = store()
    with s.lock:
        ts = now()
        row = {
            "id": new_uuid(),
            "npi": npi,
            "full_name": full_name,
            "role_type": role_type,
            "specialty": specialty,
            "dea_number": dea,
            "epcs_enrolled": bool(epcs_enrolled),
            "panel_size": 0,
            "panel_cap": panel_cap,
            "status": "ACTIVE",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.providers[row["id"]] = row
    return created(provider_to_dict(row))


@bp.route("/providers/<pid>", methods=["GET"])
@require_roles(ROLE_RECEPTIONIST, ROLE_NURSE, ROLE_PROVIDER, ROLE_CLINIC_ADMIN)
def get_provider_route(pid: str, **_kwargs):
    s = store()
    with s.lock:
        row = get_provider(pid)
    return ok(provider_to_dict(row))


@bp.route("/providers", methods=["GET"])
@require_roles(ROLE_RECEPTIONIST, ROLE_NURSE, ROLE_PROVIDER, ROLE_CLINIC_ADMIN)
def list_providers(**_kwargs):
    limit, offset = parse_pagination()
    role_type = request.args.get("role_type")
    specialty = request.args.get("specialty")
    s = store()
    with s.lock:
        items = list(s.providers.values())
        if role_type is not None:
            items = [p for p in items if p.get("role_type") == role_type]
        if specialty is not None:
            items = [p for p in items if p.get("specialty") == specialty]
        items.sort(key=lambda r: r["created_at"])
        total = len(items)
        page = paginate(items, limit, offset)
        out = [provider_to_dict(p) for p in page]
    return listing(out, total, limit, offset)
