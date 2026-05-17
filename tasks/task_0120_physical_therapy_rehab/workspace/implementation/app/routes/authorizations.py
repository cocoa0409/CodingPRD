"""Authorization endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_BILLER, ROLE_CLINIC_ADMIN, ROLE_THERAPIST, require_roles
from ..helpers import (
    assert_enum,
    assert_integer,
    assert_string,
    parse_iso8601,
    require_json_object,
)
from ..responses import created, ok
from ..services.lookups import get_authorization_or_404, get_episode_or_404
from ..services.mutations import create_authorization
from ..services.serialize import authorization_to_dict
from ..store import store

bp = Blueprint("authorizations", __name__)

SOURCES = ["COMMERCIAL_PAYER", "MEDICARE_AUTO", "VA_REFERRAL"]


@bp.route("/episodes/<eid>/authorizations", methods=["POST"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST)
def create_auth_route(eid: str, **_kwargs):
    body = require_json_object()
    poc_id = assert_string(body.get("plan_of_care_id"), "plan_of_care_id")
    source = assert_enum(body.get("source"), "source", SOURCES)
    external_reference = assert_string(body.get("external_reference"), "external_reference")
    unit_quota = assert_integer(body.get("unit_quota"), "unit_quota", minimum=1)
    valid_from_raw = body.get("valid_from")
    valid_through_raw = body.get("valid_through")
    parse_iso8601(valid_from_raw, "valid_from")
    parse_iso8601(valid_through_raw, "valid_through")
    s = store()
    with s.lock:
        episode = get_episode_or_404(eid)
        row = create_authorization(
            episode,
            poc_id,
            source,
            external_reference,
            unit_quota,
            valid_from_raw,
            valid_through_raw,
        )
    return created(authorization_to_dict(row))


@bp.route("/authorizations/<aid>", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER)
def get_auth_route(aid: str, **_kwargs):
    s = store()
    with s.lock:
        row = get_authorization_or_404(aid)
    return ok(authorization_to_dict(row))
