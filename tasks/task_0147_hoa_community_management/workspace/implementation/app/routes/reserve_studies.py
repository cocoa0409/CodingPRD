"""ReserveStudy endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..calculations import compute_full_funding_target, compute_funded_ratio
from ..envelope import success_object
from ..errors import APIError, err_invalid_state
from ..serializers import serialize_reserve_study
from ..services.common import bump_version, check_version, require
from ..store import store
from ..util import new_uuid
from ._helpers import as_int, get_json_body, get_version, require_field

bp = Blueprint("reserve_studies", __name__)


def _recompute_study(study: dict) -> None:
    target = compute_full_funding_target(study["components"])
    study["full_funding_target_cents"] = target
    ratio, posture = compute_funded_ratio(study["current_reserve_balance_cents"], target)
    study["funded_ratio"] = ratio
    study["posture"] = posture


@bp.route("/hoa/reserve-studies", methods=["POST"])
@require_roles(["TreasurerRole"])
def create_reserve_study():
    body = get_json_body()
    study_year = as_int(require_field(body, "study_year"), "study_year")
    components = require_field(body, "components")
    current_balance = as_int(
        require_field(body, "current_reserve_balance_cents"), "current_reserve_balance_cents"
    )

    if not isinstance(components, list) or not components:
        raise APIError("ERR_INVALID_STATE", "components must be a non-empty array", 409)
    for c in components:
        if not isinstance(c, dict):
            raise APIError("ERR_INVALID_STATE", "component must be an object", 409)
        for key in ("component_name", "replacement_cost_cents", "useful_life_years", "remaining_life_years"):
            if key not in c:
                raise APIError("ERR_INVALID_STATE", f"component missing '{key}'", 409)

    s = store()
    now = s.now()
    study = {
        "id": new_uuid(),
        "study_year": study_year,
        "components": components,
        "current_reserve_balance_cents": current_balance,
        "full_funding_target_cents": 0,
        "funded_ratio": None,
        "posture": "OK",
        "adopted_resolution_id": None,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    _recompute_study(study)
    s.insert("reserve_studies", study)
    return jsonify(success_object(serialize_reserve_study(study))), 201


@bp.route("/hoa/reserve-studies/<study_id>", methods=["GET"])
@require_roles(["Member", "SecretaryRole", "TreasurerRole", "PresidentRole", "DirectorRole"])
def get_reserve_study(study_id: str):
    study = require("reserve_studies", study_id)
    return jsonify(success_object(serialize_reserve_study(study))), 200


@bp.route("/hoa/reserve-studies/<study_id>/adopt", methods=["POST"])
@require_roles(["TreasurerRole"])
def adopt_reserve_study(study_id: str):
    study = require("reserve_studies", study_id)
    body = get_json_body()
    resolution_id = require_field(body, "resolution_id")
    version = get_version(body)
    check_version(study, version)

    if study["status"] != "DRAFT":
        raise err_invalid_state(f"Study is {study['status']}, cannot adopt")

    s = store()
    resolution = s.board_resolutions.get(resolution_id)
    if resolution is None:
        raise err_invalid_state("resolution_id does not resolve")
    if (
        resolution["subject"] != "RESERVE_STUDY_ADOPTION"
        or resolution["status"] != "PASSED"
        or resolution["target_id"] != study_id
    ):
        raise err_invalid_state("Resolution is not a PASSED RESERVE_STUDY_ADOPTION for this study")

    now = s.now()
    study["adopted_resolution_id"] = resolution_id
    study["status"] = "ADOPTED"
    bump_version(study, now)

    resolution["status"] = "EXECUTED"
    bump_version(resolution, now)

    # Supersede prior ADOPTED studies with study_year <= this one
    for other in s.reserve_studies.values():
        if other["id"] == study["id"]:
            continue
        if other["status"] == "ADOPTED" and other["study_year"] <= study["study_year"]:
            other["status"] = "SUPERSEDED"
            bump_version(other, now)

    return jsonify(success_object(serialize_reserve_study(study))), 200
