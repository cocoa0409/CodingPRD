"""DischargeAssessment endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_THERAPIST, require_roles
from ..helpers import (
    assert_enum,
    assert_integer,
    assert_string,
    occ_check,
    require_json_object,
)
from ..responses import created, ok
from ..services.lookups import get_discharge_or_404, get_episode_or_404
from ..services.mutations import create_discharge_assessment, sign_discharge
from ..services.serialize import discharge_to_dict
from ..store import store

bp = Blueprint("discharge", __name__)

OUTCOMES = ["GOALS_MET", "PARTIAL", "PLATEAU", "ADVERSE_EVENT", "PATIENT_WITHDREW"]


@bp.route("/episodes/<eid>/discharge-assessments", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def create_discharge_route(eid: str, **_kwargs):
    body = require_json_object()
    discharging_clinician_id = assert_string(body.get("discharging_clinician_id"), "discharging_clinician_id")
    discharge_outcome = assert_enum(body.get("discharge_outcome"), "discharge_outcome", OUTCOMES)
    final_score = assert_integer(body.get("final_functional_score"), "final_functional_score", minimum=0, maximum=100)
    s = store()
    with s.lock:
        episode = get_episode_or_404(eid)
        row = create_discharge_assessment(episode, discharging_clinician_id, discharge_outcome, final_score)
    return created(discharge_to_dict(row))


@bp.route("/discharge-assessments/<did>/sign", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def sign_discharge_route(did: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        discharge = get_discharge_or_404(did)
        occ_check(body.get("version"), discharge["version"])
        row = sign_discharge(discharge, _caller_id)
    return ok(discharge_to_dict(row))
