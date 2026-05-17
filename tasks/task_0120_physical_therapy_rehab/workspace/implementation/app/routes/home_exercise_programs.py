"""HomeExerciseProgram endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_PATIENT, ROLE_THERAPIST, require_roles
from ..errors import err_validation
from ..helpers import (
    assert_array,
    assert_string,
    occ_check,
    require_json_object,
)
from ..responses import created, ok
from ..services.lookups import get_episode_or_404, get_hep_or_404
from ..services.mutations import acknowledge_hep, create_hep, issue_hep
from ..services.serialize import hep_to_dict
from ..store import store

bp = Blueprint("home_exercise_programs", __name__)


@bp.route("/episodes/<eid>/home-exercise-programs", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def create_hep_route(eid: str, **_kwargs):
    body = require_json_object()
    poc_id = assert_string(body.get("plan_of_care_id"), "plan_of_care_id")
    prescriber = assert_string(body.get("prescribing_clinician_id"), "prescribing_clinician_id")
    items = assert_array(body.get("exercise_items"), "exercise_items", min_len=1)
    for it in items:
        if not isinstance(it, dict):
            raise err_validation("exercise_items entries must be objects")
    s = store()
    with s.lock:
        episode = get_episode_or_404(eid)
        row = create_hep(episode, poc_id, prescriber, items)
    return created(hep_to_dict(row))


@bp.route("/home-exercise-programs/<hid>/issue", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def issue_hep_route(hid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        hep = get_hep_or_404(hid)
        occ_check(body.get("version"), hep["version"])
        row = issue_hep(hep)
    return ok(hep_to_dict(row))


@bp.route("/home-exercise-programs/<hid>/acknowledge", methods=["POST"])
@require_roles(ROLE_PATIENT)
def ack_hep_route(hid: str, *, _caller_id: str, _caller_role: str):
    s = store()
    with s.lock:
        hep = get_hep_or_404(hid)
        row = acknowledge_hep(hep, _caller_id)
    return ok(hep_to_dict(row))
