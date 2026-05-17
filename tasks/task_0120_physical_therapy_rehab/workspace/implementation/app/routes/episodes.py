"""Episode endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import ROLE_BILLER, ROLE_CLINIC_ADMIN, ROLE_THERAPIST, require_roles
from ..helpers import (
    assert_enum,
    assert_string,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, no_content, ok
from ..services.lookups import get_episode_or_404, get_patient_ref
from ..services.mutations import (
    cancel_draft_episode,
    create_episode,
    recompute_episode_units,
)
from ..services.serialize import episode_to_dict
from ..store import store

bp = Blueprint("episodes", __name__)

BODY_REGIONS = ["LUMBAR", "CERVICAL", "KNEE", "SHOULDER", "HIP", "ANKLE", "OTHER"]
NPI_PATTERN = r"^[0-9]{10}$"


@bp.route("/episodes", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def create_episode_route(**_kwargs):
    body = require_json_object()
    patient_id = assert_string(body.get("patient_id"), "patient_id")
    referring_npi = assert_string(body.get("referring_provider_npi"), "referring_provider_npi", pattern=NPI_PATTERN)
    body_region = assert_enum(body.get("body_region"), "body_region", BODY_REGIONS)
    s = store()
    with s.lock:
        get_patient_ref(patient_id)
        row = create_episode(patient_id, referring_npi, body_region)
    return created(episode_to_dict(row))


@bp.route("/episodes/<eid>", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER)
def get_episode_route(eid: str, **_kwargs):
    s = store()
    with s.lock:
        row = get_episode_or_404(eid)
        recompute_episode_units(row)
    return ok(episode_to_dict(row))


@bp.route("/episodes", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER)
def list_episodes(**_kwargs):
    limit, offset = parse_pagination()
    patient_id = request.args.get("patient_id")
    status = request.args.get("status")
    s = store()
    with s.lock:
        items = list(s.episodes.values())
        if patient_id is not None:
            items = [r for r in items if r.get("patient_id") == patient_id]
        if status is not None:
            items = [r for r in items if r.get("status") == status]
        items.sort(key=lambda r: r["created_at"])
        for r in items:
            recompute_episode_units(r)
        total = len(items)
        page = paginate(items, limit, offset)
        out = [episode_to_dict(r) for r in page]
    return listing(out, total, limit, offset)


@bp.route("/episodes/<eid>", methods=["DELETE"])
@require_roles(ROLE_THERAPIST)
def delete_episode_route(eid: str, **_kwargs):
    s = store()
    with s.lock:
        row = get_episode_or_404(eid)
        cancel_draft_episode(row)
    return no_content()
