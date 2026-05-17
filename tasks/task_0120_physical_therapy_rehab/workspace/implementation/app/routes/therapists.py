"""Therapist endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import ROLE_BILLER, ROLE_CLINIC_ADMIN, ROLE_THERAPIST, require_roles
from ..errors import err_duplicate_npi
from ..helpers import (
    assert_enum,
    assert_string,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.lookups import get_therapist_or_404
from ..services.mutations import create_therapist
from ..services.serialize import therapist_to_dict
from ..store import store

bp = Blueprint("therapists", __name__)

CREDENTIALS = ["PT", "PTA", "DPT"]
NPI_PATTERN = r"^[0-9]{10}$"


@bp.route("/therapists", methods=["POST"])
@require_roles(ROLE_CLINIC_ADMIN)
def create_therapist_route(**_kwargs):
    body = require_json_object()
    full_name = assert_string(body.get("full_name"), "full_name")
    npi = assert_string(body.get("npi"), "npi", pattern=NPI_PATTERN)
    credential = assert_enum(body.get("credential"), "credential", CREDENTIALS)
    s = store()
    with s.lock:
        if npi in s.npi_index:
            raise err_duplicate_npi()
        row = create_therapist(full_name, npi, credential)
    return created(therapist_to_dict(row))


@bp.route("/therapists/<tid>", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER)
def get_therapist_route(tid: str, **_kwargs):
    s = store()
    with s.lock:
        row = get_therapist_or_404(tid)
    return ok(therapist_to_dict(row))


@bp.route("/therapists", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER)
def list_therapists(**_kwargs):
    limit, offset = parse_pagination()
    credential = request.args.get("credential")
    s = store()
    with s.lock:
        items = list(s.therapists.values())
        if credential is not None:
            items = [r for r in items if r.get("credential") == credential]
        items.sort(key=lambda r: r["created_at"])
        total = len(items)
        page = paginate(items, limit, offset)
        out = [therapist_to_dict(r) for r in page]
    return listing(out, total, limit, offset)
