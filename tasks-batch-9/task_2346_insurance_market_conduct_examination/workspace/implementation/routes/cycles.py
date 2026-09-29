"""Market-analysis cycles: composite scoring and target selection (PRD §3.2)."""

from flask import Blueprint

import validation as v
from db import db, new_record, now_iso, touch
from errors import ApiError, invalid
from middleware import (
    ROLE_MARKET_ANALYST,
    ROLE_SUPERVISING_EXAMINER,
    authorize,
)
from response import paginated, success
from routes.common import bool_query, filter_equals, str_query
from services import calculations as calc
from services import derive, serialize
from services.guards import get_cycle

bp = Blueprint("cycles", __name__)

EXAM_MODES = ("ON_SITE", "DESK")
SCORABLE_LICENSE_STATUSES = ("LICENSED", "SUSPENDED")


def _rank_key(score):
    return (
        -score["composite_score"],
        -score["complaint_ratio_at_scoring"],
        score["created_at"],
        score["_seq"],
    )


@bp.post("/analysis-cycles")
@authorize(ROLE_MARKET_ANALYST)
def create_cycle():
    payload = v.body()
    label = v.get_str(payload, "cycle_label", min_len=1, max_len=40)
    period_start = v.get_date(payload, "reference_period_start")
    period_end = v.get_date(payload, "reference_period_end")
    v.require_after(period_end, period_start, "reference_period_end")
    capacity = v.get_int(payload, "target_slot_capacity", minimum=1)
    fieldwork_start = v.get_date(payload, "default_fieldwork_start")
    fieldwork_end = v.get_date(payload, "default_fieldwork_end")
    v.require_after(fieldwork_end, fieldwork_start, "default_fieldwork_end")
    mode = v.get_enum(
        payload, "default_exam_mode", EXAM_MODES, required=False, default="ON_SITE"
    )

    if any(row["cycle_label"] == label for row in db.cycles.values()):
        raise ApiError(
            "ERR_DUPLICATE_IDENTIFIER", "That cycle_label already exists on another cycle."
        )

    cycle = new_record(
        {
            "cycle_label": label,
            "reference_period_start": period_start,
            "reference_period_end": period_end,
            "target_slot_capacity": capacity,
            "default_fieldwork_start": fieldwork_start,
            "default_fieldwork_end": fieldwork_end,
            "default_exam_mode": mode,
            "status": "DRAFT",
            "scored_at": None,
            "closed_at": None,
        }
    )
    db.cycles[cycle["id"]] = cycle
    return success(serialize.cycle(cycle), 201)


@bp.get("/analysis-cycles")
@authorize(ROLE_MARKET_ANALYST, ROLE_SUPERVISING_EXAMINER)
def list_cycles():
    rows = derive.by_creation_cycles()
    rows = filter_equals(rows, "status", str_query("status"))
    return paginated(rows, serialize.cycle)


@bp.get("/analysis-cycles/<cycle_id>")
@authorize(ROLE_MARKET_ANALYST, ROLE_SUPERVISING_EXAMINER)
def read_cycle(cycle_id):
    return success(serialize.cycle(get_cycle(cycle_id)))


@bp.post("/analysis-cycles/<cycle_id>/score")
@authorize(ROLE_MARKET_ANALYST)
def score_cycle(cycle_id):
    cycle = get_cycle(cycle_id)
    if cycle["status"] != "DRAFT":
        raise ApiError(
            "ERR_CYCLE_STATE_INVALID",
            "Scoring requires a cycle in DRAFT; this cycle is %s." % cycle["status"],
        )
    scorable = [
        insurer
        for insurer in derive.by_creation_insurers()
        if insurer["license_status"] in SCORABLE_LICENSE_STATUSES
    ]
    if not scorable:
        raise invalid(
            "The scoring pass requires at least one LICENSED or SUSPENDED carrier."
        )

    created = []
    for insurer in scorable:
        ratio = insurer["complaint_ratio_per_1k"]
        components = calc.composite_analysis_score(
            ratio,
            insurer["financial_stress_score"],
            insurer["consumer_trend_score"],
            insurer["annual_premium_written_cents"],
        )
        score = new_record(
            {
                "cycle_id": cycle["id"],
                "insurer_id": insurer["id"],
                "complaint_ratio_at_scoring": ratio,
                "complaint_component": components["complaint_component"],
                "financial_component": components["financial_component"],
                "trend_component": components["trend_component"],
                "volume_multiplier": components["volume_multiplier"],
                "composite_score": components["composite_score"],
                "rank_position": None,
                "selected": False,
                "selection_reason": None,
            }
        )
        db.analysis_scores[score["id"]] = score
        created.append(score)

    for position, score in enumerate(sorted(created, key=_rank_key), start=1):
        score["rank_position"] = position

    cycle["status"] = "SCORED"
    cycle["scored_at"] = now_iso()
    touch(cycle)
    return success(serialize.cycle(cycle))


@bp.get("/analysis-cycles/<cycle_id>/scores")
@authorize(ROLE_MARKET_ANALYST, ROLE_SUPERVISING_EXAMINER)
def list_cycle_scores(cycle_id):
    cycle = get_cycle(cycle_id)
    rows = sorted(derive.scores_of_cycle(cycle["id"]), key=_rank_key)
    rows = filter_equals(rows, "selection_reason", str_query("selection_reason"))
    selected = bool_query("selected")
    if selected is not None:
        rows = [row for row in rows if row["selected"] is selected]
    return paginated(rows, serialize.analysis_score)


@bp.post("/analysis-cycles/<cycle_id>/select-targets")
@authorize(ROLE_MARKET_ANALYST)
def select_targets(cycle_id):
    cycle = get_cycle(cycle_id)
    payload = v.body()
    threshold = v.get_percentage(
        payload,
        "min_composite_score",
        required=False,
        default=calc.MIN_COMPOSITE_SCORE_DEFAULT,
    )
    if cycle["status"] != "SCORED":
        raise ApiError(
            "ERR_CYCLE_STATE_INVALID",
            "Target selection requires a cycle in SCORED; this cycle is %s."
            % cycle["status"],
        )
    if derive.cycle_counters(cycle)["slots_available"] <= 0:
        raise ApiError(
            "ERR_CYCLE_SLOTS_EXHAUSTED", "The cycle has no examiner slot left to commit."
        )

    rows = derive.scores_of_cycle(cycle["id"])
    candidates = []
    for score in rows:
        insurer = db.insurers.get(score["insurer_id"])
        if insurer is None or insurer["license_status"] != "LICENSED":
            score["selection_reason"] = "LICENSE_INELIGIBLE"
        elif score["composite_score"] < threshold:
            score["selection_reason"] = "BELOW_THRESHOLD"
        elif _has_window_conflict(insurer, cycle):
            score["selection_reason"] = "WINDOW_CONFLICT_DEFERRED"
        else:
            candidates.append(score)

    slots = derive.cycle_counters(cycle)["slots_available"]
    ranked = sorted(candidates, key=_rank_key)
    for score in ranked[:slots]:
        score["selected"] = True
        score["selection_reason"] = "SELECTED"
        _open_selected_examination(cycle, score)
    for score in ranked[slots:]:
        score["selection_reason"] = "CAPACITY_EXHAUSTED"

    for score in rows:
        touch(score)

    cycle["status"] = "TARGETS_SELECTED"
    touch(cycle)
    return success(serialize.cycle(cycle))


def _has_window_conflict(insurer, cycle):
    for exam in derive.examinations_of_insurer(insurer["id"]):
        if exam["status"] in derive.TERMINAL_EXAM_STATES:
            continue
        if derive.windows_overlap(
            exam["fieldwork_start_date"],
            exam["fieldwork_end_date"],
            cycle["default_fieldwork_start"],
            cycle["default_fieldwork_end"],
        ):
            return True
    return False


def _open_selected_examination(cycle, score):
    exam = new_record(
        {
            "insurer_id": score["insurer_id"],
            "cycle_id": cycle["id"],
            "predecessor_exam_id": None,
            "exam_type": "MARKET_CONDUCT_EXAM",
            "mode": cycle["default_exam_mode"],
            "lead_state_code": calc.DEPARTMENT_STATE_CODE,
            "fieldwork_start_date": cycle["default_fieldwork_start"],
            "fieldwork_end_date": cycle["default_fieldwork_end"],
            "status": "SCOPING",
            "scope_locked": False,
            "criticism_phase_opened_at": None,
            "report_published_at": None,
            "public_summary": None,
            "followup_required": False,
            "followup_due_date": None,
            "abort_reason": None,
        }
    )
    db.examinations[exam["id"]] = exam
    return exam
