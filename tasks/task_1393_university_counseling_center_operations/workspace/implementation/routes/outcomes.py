"""OutcomeMeasure endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_NOT_FOUND
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("outcomes", __name__)

INSTRUMENTS = {"PHQ9", "GAD7", "CCAPS"}
PHASES = {"BASELINE", "MID", "DISCHARGE"}


@bp.route("/ucc/outcome-measures", methods=["POST"])
@require_roles("Counselor", "ClinicalDirector")
def create_outcome(_user_id: str, _role: str):
    body = get_json_body()
    episode_id = require_string(body, "episode_id")
    instrument = require_enum(body, "instrument", INSTRUMENTS)
    phase = require_enum(body, "phase", PHASES)
    score = require_int(body, "score", minimum=0)

    if db.episodes.get(episode_id) is None:
        raise_err(ERR_NOT_FOUND, "episode_id does not resolve")

    outcome = {
        "episode_id": episode_id,
        "instrument": instrument,
        "phase": phase,
        "score": score,
    }
    db.stamp_new_light(outcome)
    db.outcome_measures[outcome["id"]] = outcome
    return success_object(serialize(outcome), 201)


@bp.route("/ucc/outcome-measures/<outcome_id>", methods=["GET"])
@require_roles("Counselor", "ClinicalDirector")
def get_outcome(outcome_id: str, _user_id: str, _role: str):
    o = db.outcome_measures.get(outcome_id)
    if o is None:
        raise_err(ERR_NOT_FOUND, "OutcomeMeasure id does not exist")
    return success_object(serialize(o))


@bp.route("/ucc/outcome-measures", methods=["GET"])
@require_roles("Counselor", "ClinicalDirector")
def list_outcomes(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.outcome_measures.values()))
    items = apply_filters(items, ["episode_id", "instrument", "phase"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)
