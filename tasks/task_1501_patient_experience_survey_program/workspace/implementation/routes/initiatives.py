"""ImprovementInitiative endpoints (PRD 3.8): create, activate (pins the
baseline), replan, cancel, list/get with live progress fields."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_BASELINE_CYCLE_NOT_PUBLISHED,
    ERR_CROSS_PROGRAM_REFERENCE,
    ERR_INVALID_EVALUATION_CYCLE,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import initiative_view
from services.core import check_initiative_window
from util import (
    get_json_body, reject_unknown_fields, require_string, require_enum,
    require_target_score, get_or_404, parse_pagination, paginate,
    sort_created, query_arg,
)

bp = Blueprint("initiatives", __name__)

DOMAINS = {"NURSE_COMM", "DOCTOR_COMM", "CLEANLINESS", "OVERALL_RATING"}
CREATE_FIELDS = {"unit_id", "domain", "baseline_cycle_id", "evaluation_cycle_id",
                 "target_score"}
REPLAN_FIELDS = {"evaluation_cycle_id", "target_score"}


def _check_cross_program(unit: dict, *cycle_ids: str) -> None:
    for cid in cycle_ids:
        cycle = db.cycles.get(cid)
        if cycle is None or cycle["program_id"] != unit["program_id"]:
            raise_err(ERR_CROSS_PROGRAM_REFERENCE,
                      "Referenced cycles must belong to the unit's program")


def _check_evaluation_cycle(unit: dict, baseline_cycle_id: str,
                            evaluation_cycle_id: str) -> None:
    """Window-validity guards shared by activate and replan (PRD 3.8)."""
    _check_cross_program(unit, evaluation_cycle_id)
    eval_cycle = db.cycles[evaluation_cycle_id]
    base_cycle = db.cycles[baseline_cycle_id]
    if eval_cycle["status"] == "VOIDED" or eval_cycle["cycle_index"] <= base_cycle["cycle_index"]:
        raise_err(ERR_INVALID_EVALUATION_CYCLE,
                  "evaluation cycle must not be VOIDED and its cycle_index must "
                  "strictly exceed the baseline cycle's")


@bp.route("/api/initiatives", methods=["POST"])
@require_roles("ProgramAdmin")
def create_initiative(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    unit_id = require_string(body, "unit_id")
    domain = require_enum(body, "domain", DOMAINS)
    baseline_cycle_id = require_string(body, "baseline_cycle_id")
    evaluation_cycle_id = require_string(body, "evaluation_cycle_id")
    target_score = require_target_score(body, "target_score")

    unit = get_or_404(db.units, unit_id, "CareUnit")
    get_or_404(db.cycles, baseline_cycle_id, "SurveyCycle")
    get_or_404(db.cycles, evaluation_cycle_id, "SurveyCycle")

    # Referential scope: both referenced cycles must belong to the unit's
    # program. Window guards (index ordering, overlap) run at activation.
    _check_cross_program(unit, baseline_cycle_id, evaluation_cycle_id)

    initiative = db.stamp_new({
        "unit_id": unit_id,
        "program_id": unit["program_id"],
        "domain": domain,
        "baseline_cycle_id": baseline_cycle_id,
        "evaluation_cycle_id": evaluation_cycle_id,
        "target_score": target_score,
        "baseline_score": None,
        "status": "DRAFT",
        "achieved_at": None,
    })
    db.initiatives[initiative["id"]] = initiative
    return success_object(initiative_view(initiative), 201)


@bp.route("/api/initiatives", methods=["GET"])
@require_roles("Any")
def list_initiatives(_user_id: str, _role: str):
    items = list(db.initiatives.values())
    for param in ("unit_id", "program_id", "baseline_cycle_id",
                  "evaluation_cycle_id", "status"):
        value = query_arg(param)
        if value is not None:
            items = [i for i in items if i[param] == value]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([initiative_view(i) for i in page], limit, offset, total)


@bp.route("/api/initiatives/<initiativeId>", methods=["GET"])
@require_roles("Any")
def get_initiative(initiativeId: str, _user_id: str, _role: str):
    initiative = get_or_404(db.initiatives, initiativeId, "ImprovementInitiative")
    return success_object(initiative_view(initiative))


@bp.route("/api/initiatives/<initiativeId>/activate", methods=["POST"])
@require_roles("ProgramAdmin")
def activate_initiative(initiativeId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    initiative = get_or_404(db.initiatives, initiativeId, "ImprovementInitiative")
    if initiative["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "activate requires the initiative to be DRAFT")

    baseline = db.cycles.get(initiative["baseline_cycle_id"])
    if baseline is None or baseline["status"] != "PUBLISHED":
        raise_err(ERR_BASELINE_CYCLE_NOT_PUBLISHED,
                  "The baseline cycle must be PUBLISHED at activation")

    unit = db.units.get(initiative["unit_id"])
    _check_evaluation_cycle(unit, initiative["baseline_cycle_id"],
                            initiative["evaluation_cycle_id"])
    check_initiative_window(initiative, initiative["evaluation_cycle_id"],
                            initiative["baseline_cycle_id"], initiative["id"])

    # Pin the baseline: the unit's published adjusted top-box pct for the
    # domain, read from the baseline cycle's scored_unit_breakdown.
    from services.core import unit_adjusted_pct
    initiative["baseline_score"] = unit_adjusted_pct(
        baseline, initiative["unit_id"], initiative["domain"])
    initiative["status"] = "ACTIVE"
    db.touch(initiative)
    return success_object(initiative_view(initiative))


@bp.route("/api/initiatives/<initiativeId>/replan", methods=["POST"])
@require_roles("ProgramAdmin")
def replan_initiative(initiativeId: str, _user_id: str, _role: str):
    initiative = get_or_404(db.initiatives, initiativeId, "ImprovementInitiative")
    body = get_json_body()
    reject_unknown_fields(body, REPLAN_FIELDS)
    evaluation_cycle_id = require_string(body, "evaluation_cycle_id")
    target_score = require_target_score(body, "target_score")

    if initiative["status"] != "TARGET_MISSED":
        raise_err(ERR_INVALID_STATE, "replan requires the initiative to be TARGET_MISSED")

    get_or_404(db.cycles, evaluation_cycle_id, "SurveyCycle")
    unit = db.units.get(initiative["unit_id"])
    _check_evaluation_cycle(unit, initiative["baseline_cycle_id"], evaluation_cycle_id)
    check_initiative_window(initiative, evaluation_cycle_id,
                            initiative["baseline_cycle_id"], initiative["id"])

    # Replan loop TARGET_MISSED -> ACTIVE: window and target replaced;
    # baseline_score unchanged; progress fields recompute live (null until the
    # new evaluation cycle publishes).
    initiative["evaluation_cycle_id"] = evaluation_cycle_id
    initiative["target_score"] = target_score
    initiative["status"] = "ACTIVE"
    db.touch(initiative)
    return success_object(initiative_view(initiative))


@bp.route("/api/initiatives/<initiativeId>/cancel", methods=["POST"])
@require_roles("ProgramAdmin")
def cancel_initiative(initiativeId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    initiative = get_or_404(db.initiatives, initiativeId, "ImprovementInitiative")
    if initiative["status"] not in ("DRAFT", "ACTIVE", "TARGET_MISSED"):
        raise_err(ERR_INVALID_STATE,
                  "Only a DRAFT, ACTIVE, or TARGET_MISSED initiative can be cancelled")
    initiative["status"] = "CANCELLED"
    db.touch(initiative)
    return success_object(initiative_view(initiative))
