"""PlanOfCare endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_BILLER, ROLE_CLINIC_ADMIN, ROLE_THERAPIST, require_roles
from ..helpers import (
    assert_integer,
    assert_string,
    occ_check,
    require_json_object,
)
from ..responses import created, ok
from ..services.lookups import get_episode_or_404, get_poc_or_404
from ..services.mutations import (
    certify_plan_of_care,
    create_plan_of_care,
    revoke_plan_of_care,
)
from ..services.serialize import plan_of_care_to_dict
from ..store import store

bp = Blueprint("plan_of_cares", __name__)

NPI_PATTERN = r"^[0-9]{10}$"


@bp.route("/episodes/<eid>/plan-of-cares", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def create_poc_route(eid: str, **_kwargs):
    body = require_json_object()
    evaluation_id = assert_string(body.get("evaluation_id"), "evaluation_id")
    cert_npi = assert_string(body.get("certifying_physician_npi"), "certifying_physician_npi", pattern=NPI_PATTERN)
    planned_visit_count = assert_integer(body.get("planned_visit_count"), "planned_visit_count", minimum=1)
    planned_units_per_visit = assert_integer(body.get("planned_units_per_visit"), "planned_units_per_visit", minimum=1)
    cert_start = assert_string(body.get("cert_period_start"), "cert_period_start")
    cert_end = assert_string(body.get("cert_period_end"), "cert_period_end")
    s = store()
    with s.lock:
        episode = get_episode_or_404(eid)
        row = create_plan_of_care(
            episode,
            evaluation_id,
            cert_npi,
            planned_visit_count,
            planned_units_per_visit,
            cert_start,
            cert_end,
        )
    return created(plan_of_care_to_dict(row))


@bp.route("/plan-of-cares/<pid>/certify", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def certify_poc_route(pid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        poc = get_poc_or_404(pid)
        occ_check(body.get("version"), poc["version"])
        row = certify_plan_of_care(poc)
    return ok(plan_of_care_to_dict(row))


@bp.route("/plan-of-cares/<pid>/revoke", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def revoke_poc_route(pid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        poc = get_poc_or_404(pid)
        occ_check(body.get("version"), poc["version"])
        row = revoke_plan_of_care(poc, _caller_id)
    return ok(plan_of_care_to_dict(row))


@bp.route("/plan-of-cares/<pid>", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER)
def get_poc_route(pid: str, **_kwargs):
    s = store()
    with s.lock:
        row = get_poc_or_404(pid)
    return ok(plan_of_care_to_dict(row))
