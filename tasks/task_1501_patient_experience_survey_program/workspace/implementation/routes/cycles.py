"""SurveyCycle endpoints (PRD 3.3, 3.5, 3.6, 3.7): lifecycle transitions,
scoring snapshot, publication cascade, star rating, attribution report,
VBP projection, and mode-transition analysis."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NO_ACTIVE_VENDOR,
    ERR_CYCLE_NOT_SAMPLING_OPEN,
    ERR_NO_CASES_SAMPLED,
    ERR_CYCLE_NOT_FIELDING,
    ERR_FIELDING_WINDOW_NOT_CLOSED,
    ERR_CYCLE_NOT_RECONCILING,
    ERR_REOPEN_WINDOW_EXPIRED,
    ERR_UNADJUDICATED_RESPONSES,
    ERR_CYCLE_NOT_SCORED,
    ERR_BELOW_PUBLICATION_THRESHOLD,
    ERR_CYCLE_NOT_PUBLISHED,
    ERR_CROSS_PROGRAM_REFERENCE,
    ERR_CYCLE_WINDOW_OVERLAP,
    ERR_DUPLICATE_CYCLE_INDEX,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import cycle_view
from services.core import (
    active_vendor_for_program,
    compute_scoring_snapshot,
    counted_responses,
    evaluate_initiatives_at_publish,
    recompute_cycle_derived,
    recompute_vendor_budget,
    star_rating_from_snapshot,
    vbp_projection,
)
from util import (
    get_json_body, reject_unknown_fields, require_string, require_int,
    require_date, get_or_404, parse_pagination, paginate, sort_created,
    query_arg, parse_iso_date, clock_date, is_number, pct2, share4,
    round_half_up,
)

bp = Blueprint("cycles", __name__)

CREATE_FIELDS = {
    "program_id", "label", "cycle_index", "discharge_window_start",
    "discharge_window_end", "fielding_start_date", "fielding_end_date",
    "target_sample_size",
}

VBP_OVERRIDE_FIELDS = {
    "nurse_comm_pct", "doctor_comm_pct", "cleanliness_pct", "overall_rating_pct",
}


def _new_cycle(program_id, label, cycle_index, dw_start, dw_end, f_start, f_end, target):
    return db.stamp_new({
        "program_id": program_id,
        "label": label,
        "cycle_index": cycle_index,
        "discharge_window_start": dw_start,
        "discharge_window_end": dw_end,
        "fielding_start_date": f_start,
        "fielding_end_date": f_end,
        "target_sample_size": target,
        "status": "DRAFT",
        "sampled_count": 0,
        "completed_responses": 0,
        "eligible_denominator": 0,
        "response_rate": None,
        "publication_eligible": False,
        "scored_raw_composite_pcts": None,
        "scored_adjusted_composite_pcts": None,
        "scored_unit_breakdown": None,
        "scored_provider_breakdown": None,
        "scored_response_rate": None,
        "scored_completed_responses": None,
        "published_star_rating": None,
        "published_at": None,
    })


@bp.route("/api/cycles", methods=["POST"])
@require_roles("ProgramAdmin")
def create_cycle(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    program_id = require_string(body, "program_id")
    label = require_string(body, "label")
    cycle_index = require_int(body, "cycle_index")
    dw_start = require_date(body, "discharge_window_start")
    dw_end = require_date(body, "discharge_window_end")
    f_start = require_date(body, "fielding_start_date")
    f_end = require_date(body, "fielding_end_date")
    target = require_int(body, "target_sample_size", minimum=1)

    get_or_404(db.programs, program_id, "SurveyProgram")

    # Temporal (priority 7): the fielding window is a CLOSED interval; touching
    # dates conflict with any non-VOIDED cycle of the same program.
    new_start = parse_iso_date(f_start, "fielding_start_date")
    new_end = parse_iso_date(f_end, "fielding_end_date")
    for other in db.cycles.values():
        if other["program_id"] != program_id or other["status"] == "VOIDED":
            continue
        o_start = parse_iso_date(other["fielding_start_date"])
        o_end = parse_iso_date(other["fielding_end_date"])
        if new_start <= o_end and o_start <= new_end:
            raise_err(
                ERR_CYCLE_WINDOW_OVERLAP,
                "Fielding window overlaps another non-VOIDED cycle of this program",
            )

    # Constraint (priority 8): cycle_index unique per program.
    for other in db.cycles.values():
        if other["program_id"] == program_id and other["cycle_index"] == cycle_index:
            raise_err(ERR_DUPLICATE_CYCLE_INDEX,
                      f"cycle_index {cycle_index} already exists in this program")

    cycle = _new_cycle(program_id, label, cycle_index, dw_start, dw_end,
                       f_start, f_end, target)
    db.cycles[cycle["id"]] = cycle
    return success_object(cycle_view(cycle), 201)


@bp.route("/api/cycles", methods=["GET"])
@require_roles("Any")
def list_cycles(_user_id: str, _role: str):
    items = list(db.cycles.values())
    program_id = query_arg("program_id")
    status = query_arg("status")
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([cycle_view(c) for c in page], limit, offset, total)


@bp.route("/api/cycles/<cycleId>", methods=["GET"])
@require_roles("Any")
def get_cycle(cycleId: str, _user_id: str, _role: str):
    cycle = get_or_404(db.cycles, cycleId, "SurveyCycle")
    return success_object(cycle_view(cycle))


@bp.route("/api/cycles/<cycleId>/open-sampling", methods=["POST"])
@require_roles("ProgramAdmin")
def open_sampling(cycleId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    cycle = get_or_404(db.cycles, cycleId, "SurveyCycle")
    # Cycle-posture errors precede entity-local state errors (PRD 2.6 tier 7).
    if active_vendor_for_program(cycle["program_id"]) is None:
        raise_err(ERR_NO_ACTIVE_VENDOR,
                  "Program has no ACTIVE vendor to charge sample cases to")
    if cycle["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "open-sampling requires the cycle to be DRAFT")
    cycle["status"] = "SAMPLING_OPEN"
    db.touch(cycle)
    return success_object(cycle_view(cycle))


@bp.route("/api/cycles/<cycleId>/start-fielding", methods=["POST"])
@require_roles("ProgramAdmin")
def start_fielding(cycleId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    cycle = get_or_404(db.cycles, cycleId, "SurveyCycle")
    if cycle["status"] != "SAMPLING_OPEN":
        raise_err(ERR_CYCLE_NOT_SAMPLING_OPEN,
                  "start-fielding requires the cycle to be SAMPLING_OPEN")
    sampled = [c for c in db.sample_cases.values()
               if c["cycle_id"] == cycle["id"] and c["status"] == "SAMPLED"]
    if len(sampled) < 1:
        raise_err(ERR_NO_CASES_SAMPLED,
                  "start-fielding requires at least one SAMPLED case")
    for case in sorted(sampled, key=lambda c: c.get("_seq", 0)):
        case["status"] = "IN_FIELD"
        db.touch(case)
    cycle["sampled_count"] = len(sampled)
    cycle["status"] = "FIELDING"
    recompute_cycle_derived(cycle)
    db.touch(cycle)
    return success_object(cycle_view(cycle))


@bp.route("/api/cycles/<cycleId>/close-fielding", methods=["POST"])
@require_roles("ProgramAdmin")
def close_fielding(cycleId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    cycle = get_or_404(db.cycles, cycleId, "SurveyCycle")
    if cycle["status"] != "FIELDING":
        raise_err(ERR_CYCLE_NOT_FIELDING,
                  "close-fielding requires the cycle to be FIELDING")
    if clock_date(db.clock_now()) < parse_iso_date(cycle["fielding_end_date"]):
        raise_err(ERR_FIELDING_WINDOW_NOT_CLOSED,
                  "The logical clock date has not reached fielding_end_date")
    for case in db.sample_cases.values():
        if case["cycle_id"] == cycle["id"] and case["status"] == "IN_FIELD":
            case["status"] = "NONRESPONSE"
            db.touch(case)
    cycle["status"] = "RECONCILIATION"
    recompute_cycle_derived(cycle)
    db.touch(cycle)
    return success_object(cycle_view(cycle))


@bp.route("/api/cycles/<cycleId>/reopen-fielding", methods=["POST"])
@require_roles("ProgramAdmin")
def reopen_fielding(cycleId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    cycle = get_or_404(db.cycles, cycleId, "SurveyCycle")
    if cycle["status"] != "RECONCILIATION":
        raise_err(ERR_CYCLE_NOT_RECONCILING,
                  "reopen-fielding requires the cycle to be RECONCILIATION")
    if clock_date(db.clock_now()) > parse_iso_date(cycle["fielding_end_date"]):
        raise_err(ERR_REOPEN_WINDOW_EXPIRED,
                  "The logical clock date is past fielding_end_date")
    for case in db.sample_cases.values():
        if case["cycle_id"] == cycle["id"] and case["status"] == "NONRESPONSE":
            case["status"] = "IN_FIELD"
            db.touch(case)
    cycle["status"] = "FIELDING"
    recompute_cycle_derived(cycle)
    db.touch(cycle)
    return success_object(cycle_view(cycle))


@bp.route("/api/cycles/<cycleId>/begin-scoring", methods=["POST"])
@require_roles("ProgramAdmin")
def begin_scoring(cycleId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    cycle = get_or_404(db.cycles, cycleId, "SurveyCycle")
    if cycle["status"] != "RECONCILIATION":
        raise_err(ERR_CYCLE_NOT_RECONCILING,
                  "begin-scoring requires the cycle to be RECONCILIATION")
    for r in db.responses.values():
        if r["cycle_id"] == cycle["id"] and r["status"] == "PENDING_REVIEW":
            raise_err(ERR_UNADJUDICATED_RESPONSES,
                      "All PENDING_REVIEW responses must be adjudicated first")
    cycle["status"] = "SCORING"
    compute_scoring_snapshot(cycle)
    db.touch(cycle)
    return success_object(cycle_view(cycle))


@bp.route("/api/cycles/<cycleId>/publish", methods=["POST"])
@require_roles("ProgramAdmin")
def publish_cycle(cycleId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    cycle = get_or_404(db.cycles, cycleId, "SurveyCycle")
    if cycle["status"] != "SCORING":
        raise_err(ERR_CYCLE_NOT_SCORED, "publish requires the cycle to be SCORING")
    completed = cycle["scored_completed_responses"] or 0
    rate = cycle["scored_response_rate"]
    if completed < 25 or rate is None or Decimal(str(rate)) < Decimal("10.0"):
        raise_err(
            ERR_BELOW_PUBLICATION_THRESHOLD,
            "publish requires scored_completed_responses >= 25 and scored_response_rate >= 10.0",
        )
    stars, _, _ = star_rating_from_snapshot(cycle)
    cycle["published_star_rating"] = stars
    cycle["published_at"] = db.clock_now()
    cycle["status"] = "PUBLISHED"
    db.touch(cycle)
    # Initiative evaluation cascade (hops B -> C -> D, PRD 3.6).
    evaluate_initiatives_at_publish(cycle)
    return success_object(cycle_view(cycle))


@bp.route("/api/cycles/<cycleId>/void", methods=["POST"])
@require_roles("ProgramAdmin")
def void_cycle(cycleId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    cycle = get_or_404(db.cycles, cycleId, "SurveyCycle")
    if cycle["status"] in ("PUBLISHED", "VOIDED"):
        raise_err(ERR_INVALID_STATE, "A terminal cycle cannot be voided")

    credited_vendors = set()
    for case in db.sample_cases.values():
        if case["cycle_id"] != cycle["id"]:
            continue
        if case["status"] in ("SAMPLED", "IN_FIELD", "NONRESPONSE", "UNDELIVERABLE"):
            case["status"] = "VOIDED"
            if case["billing_status"] == "CHARGED":
                case["billing_status"] = "CREDITED"
                credited_vendors.add(case["vendor_id"])
            db.touch(case)
    for r in db.responses.values():
        if r["cycle_id"] == cycle["id"] and r["status"] in (
            "ACCEPTED", "PENDING_REVIEW", "INCLUDED",
        ):
            r["status"] = "VOIDED"
            db.touch(r)
    for vendor_id in credited_vendors:
        vendor = db.vendors.get(vendor_id)
        if vendor is not None:
            recompute_vendor_budget(vendor)
            db.touch(vendor)

    cycle["status"] = "VOIDED"
    recompute_cycle_derived(cycle)
    db.touch(cycle)
    return success_object(cycle_view(cycle))


@bp.route("/api/cycles/<cycleId>/star-rating", methods=["GET"])
@require_roles("Any")
def star_rating(cycleId: str, _user_id: str, _role: str):
    cycle = get_or_404(db.cycles, cycleId, "SurveyCycle")
    if cycle["status"] not in ("SCORING", "PUBLISHED"):
        raise_err(ERR_CYCLE_NOT_SCORED,
                  "star rating is available once the cycle is SCORING or PUBLISHED")
    stars, rating_status, capped = star_rating_from_snapshot(cycle)
    adjusted = cycle.get("scored_adjusted_composite_pcts") or {}
    return success_object({
        "cycle_id": cycle["id"],
        "rating_status": rating_status,
        "stars": stars,
        "capped": capped,
        "adjusted_overall_topbox_pct": adjusted.get("overall_rating"),
        "response_rate": cycle["scored_response_rate"],
        "completed_responses": cycle["scored_completed_responses"],
    })


@bp.route("/api/cycles/<cycleId>/attribution-report", methods=["GET"])
@require_roles("Any")
def attribution_report(cycleId: str, _user_id: str, _role: str):
    cycle = get_or_404(db.cycles, cycleId, "SurveyCycle")
    unit_id = query_arg("unit_id")
    provider_id = query_arg("provider_id")
    # Exactly one of unit_id / provider_id selects the reporting scope.
    if (unit_id is None) == (provider_id is None):
        raise_err(ERR_INVALID_REQUEST,
                  "Exactly one of unit_id or provider_id is required")
    if cycle["status"] not in ("SCORING", "PUBLISHED"):
        raise_err(ERR_CYCLE_NOT_SCORED,
                  "attribution report is available once the cycle is SCORING or PUBLISHED")

    null_pcts = {k: None for k in ("nurse_comm", "doctor_comm", "cleanliness", "overall_rating")}
    if unit_id is not None:
        scope, subject_id = "UNIT", unit_id
        breakdown = cycle.get("scored_unit_breakdown") or []
        entry = next((e for e in breakdown if e["unit_id"] == unit_id), None)
    else:
        scope, subject_id = "PROVIDER", provider_id
        breakdown = cycle.get("scored_provider_breakdown") or []
        entry = next((e for e in breakdown if e["provider_id"] == provider_id), None)

    if entry is None:
        completed, raw_pcts, adjusted_pcts = 0, dict(null_pcts), dict(null_pcts)
    else:
        completed = entry["completed_responses"]
        raw_pcts = entry["raw_pcts"]
        adjusted_pcts = entry["adjusted_pcts"]

    return success_object({
        "cycle_id": cycle["id"],
        "scope": scope,
        "subject_id": subject_id,
        "completed_responses": completed,
        "raw_pcts": raw_pcts,
        "adjusted_pcts": adjusted_pcts,
    })


@bp.route("/api/cycles/<cycleId>/vbp-projection", methods=["POST"])
@require_roles("ProgramAdmin")
def vbp_projection_endpoint(cycleId: str, _user_id: str, _role: str):
    cycle = get_or_404(db.cycles, cycleId, "SurveyCycle")
    body = get_json_body()
    reject_unknown_fields(body, VBP_OVERRIDE_FIELDS)
    overrides: dict = {}
    for name in VBP_OVERRIDE_FIELDS:
        if name in body and body[name] is not None:
            if not is_number(body[name]):
                raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
            overrides[name] = body[name]
    if cycle["status"] not in ("SCORING", "PUBLISHED"):
        raise_err(ERR_CYCLE_NOT_SCORED,
                  "vbp-projection is available once the cycle is SCORING or PUBLISHED")
    # What-if only: nothing is persisted (PRD 3.7).
    return success_object(vbp_projection(cycle, overrides))


@bp.route("/api/cycles/<cycleId>/mode-transition-analysis", methods=["GET"])
@require_roles("Any")
def mode_transition_analysis(cycleId: str, _user_id: str, _role: str):
    cycle_b = get_or_404(db.cycles, cycleId, "SurveyCycle")
    compare_id = query_arg("compare_to_cycle_id")
    if compare_id is None:
        raise_err(ERR_INVALID_REQUEST, "Query parameter compare_to_cycle_id is required")
    if compare_id not in db.cycles:
        raise_err(ERR_NOT_FOUND, f"SurveyCycle not found: {compare_id}")
    cycle_a = db.cycles[compare_id]
    if cycle_b["status"] != "PUBLISHED" or cycle_a["status"] != "PUBLISHED":
        raise_err(ERR_CYCLE_NOT_PUBLISHED,
                  "mode-transition analysis requires both cycles to be PUBLISHED")
    if cycle_a["program_id"] != cycle_b["program_id"]:
        raise_err(ERR_CROSS_PROGRAM_REFERENCE,
                  "Both cycles must belong to the same program")

    def mode_share(cycle, mode):
        rs = counted_responses(cycle["id"])
        total = len(rs)
        if total == 0:
            return Decimal("0")
        used = sum(1 for r in rs if r["mode_used"] == mode)
        return Decimal(used) / Decimal(total)

    def overall(cycle, key):
        snapshot = cycle.get(key) or {}
        value = snapshot.get("overall_rating")
        return Decimal(str(value)) if value is not None else Decimal("0")

    mail_delta = share4(mode_share(cycle_b, "MAIL") - mode_share(cycle_a, "MAIL"))
    phone_delta = share4(mode_share(cycle_b, "PHONE") - mode_share(cycle_a, "PHONE"))
    raw_delta = pct2(overall(cycle_b, "scored_raw_composite_pcts")
                     - overall(cycle_a, "scored_raw_composite_pcts"))
    adj_delta = pct2(overall(cycle_b, "scored_adjusted_composite_pcts")
                     - overall(cycle_a, "scored_adjusted_composite_pcts"))
    meff_b = overall(cycle_b, "scored_raw_composite_pcts") - overall(
        cycle_b, "scored_adjusted_composite_pcts")
    meff_a = overall(cycle_a, "scored_raw_composite_pcts") - overall(
        cycle_a, "scored_adjusted_composite_pcts")
    meff_delta = pct2(meff_b - meff_a)

    return success_object({
        "cycle_id": cycle_b["id"],
        "compare_to_cycle_id": cycle_a["id"],
        "mail_share_delta": mail_delta,
        "phone_share_delta": phone_delta,
        "raw_overall_delta": raw_delta,
        "adjusted_overall_delta": adj_delta,
        "mode_effect_delta": meff_delta,
    })
