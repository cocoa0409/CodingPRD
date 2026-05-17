"""MIPS measure endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_BILLER, ROLE_CLINIC_ADMIN, ROLE_THERAPIST, require_roles
from ..helpers import (
    assert_bool,
    assert_enum,
    assert_string,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing
from ..services.lookups import get_episode_or_404
from ..services.mutations import create_mips_measure
from ..services.serialize import mips_to_dict
from ..store import store

bp = Blueprint("mips", __name__)

MEASURE_CODES = ["Q126_PAIN_ASSESSMENT", "Q127_FUNCTIONAL_STATUS", "Q128_FALL_RISK_SCREEN"]
EXCEPTION_REASONS = ["NONE", "MEDICAL", "PATIENT", "SYSTEM"]


@bp.route("/episodes/<eid>/mips-measures", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def create_mips_route(eid: str, **_kwargs):
    body = require_json_object()
    measure_code = assert_enum(body.get("measure_code"), "measure_code", MEASURE_CODES)
    visit_id = assert_string(body.get("visit_id"), "visit_id")
    numerator_met = assert_bool(body.get("numerator_met"), "numerator_met")
    exception_reason = assert_enum(body.get("exception_reason"), "exception_reason", EXCEPTION_REASONS)
    s = store()
    with s.lock:
        episode = get_episode_or_404(eid)
        row = create_mips_measure(episode, measure_code, visit_id, numerator_met, exception_reason)
    return created(mips_to_dict(row))


@bp.route("/episodes/<eid>/mips-measures", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER)
def list_mips_route(eid: str, **_kwargs):
    limit, offset = parse_pagination()
    s = store()
    with s.lock:
        get_episode_or_404(eid)
        items = [m for m in s.mips_measures.values() if m["episode_id"] == eid]
        items.sort(key=lambda r: r["created_at"])
        total = len(items)
        page = paginate(items, limit, offset)
        out = [mips_to_dict(r) for r in page]
    return listing(out, total, limit, offset)
