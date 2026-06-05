"""Medical provider routes (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint, request

from db import medical_providers, stamp_common
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import require_str, get_or_404_path


bp = Blueprint("medical_providers", __name__)


def _view(p: dict) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "contact": p["contact"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/medical-providers")
def create_provider():
    require_auth({"Paralegal"})()
    body = get_json_body()
    name = require_str(body, "name")
    contact = require_str(body, "contact")
    p = {"name": name, "contact": contact}
    stamp_common(p)
    medical_providers[p["id"]] = p
    return ok_object(_view(p), 201)


@bp.get("/medical-providers/<pid>")
def get_provider(pid):
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    p = get_or_404_path(medical_providers, pid, "MedicalProvider")
    return ok_object(_view(p), 200)


@bp.get("/medical-providers")
def list_providers():
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    limit, offset = paginate_params(request.args)
    items = list(medical_providers.values())
    items.sort(key=lambda p: p["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array([_view(p) for p in page], limit, offset, total, 200)
