"""Consensus rounds, source estimates and disagreement records."""

from flask import Blueprint, g

from db import db, make_record, now_iso, ordered, touch
from errors import fail
from middleware import authorize, body, opt_int, req_enum, req_int, req_str, validation
from response import object_response
from routes.helpers import (
    cycle_or_404,
    disagreement_or_404,
    estimate_or_404,
    listing,
    round_or_404,
    source_or_404,
)
from services import calc, cascade
from util import BPS_SCALE, rhu

bp = Blueprint("rounds", __name__)

READ_ROLES = ("ForecastDirector", "ExecutiveEconomist", "LegislativeEconomist", "RatingAnalyst")
ECONOMISTS = ("ExecutiveEconomist", "LegislativeEconomist")
RESOLUTION_METHODS = ("EXEC_VALUE", "LEG_VALUE", "MIDPOINT", "DIRECTOR_OVERRIDE")
JUDGMENTAL_CAP_BPS = 1000
RATIONALE_MIN = 20


def _body_of_role(role):
    return "EXECUTIVE" if role == "ExecutiveEconomist" else "LEGISLATIVE"


def _judgmental_cap_check(weighted, policy, judgmental):
    if abs(judgmental) * BPS_SCALE > abs(weighted + policy) * JUDGMENTAL_CAP_BPS:
        fail("ERR_JUDGMENTAL_ADJUSTMENT_CAP",
             "the judgmental overlay may not exceed 1000 bps of the formula components")


# ------------------------------------------------------------------ reads ----
@bp.get("/consensus-rounds")
@authorize(*READ_ROLES)
def list_rounds():
    return listing(ordered(db.rounds),
                   {"cycle_id": ("cycle_id", str), "status": ("status", str)})


@bp.get("/consensus-rounds/<round_id>")
@authorize(*READ_ROLES)
def get_round(round_id):
    return object_response(round_or_404(round_id))


@bp.get("/source-estimates")
@authorize(*READ_ROLES)
def list_estimates():
    return listing(
        ordered(db.estimates),
        {"round_id": ("round_id", str), "source_id": ("source_id", str), "body": ("body", str)},
    )


@bp.get("/source-estimates/<estimate_id>")
@authorize(*READ_ROLES)
def get_estimate(estimate_id):
    return object_response(estimate_or_404(estimate_id))


@bp.get("/disagreement-records")
@authorize(*READ_ROLES)
def list_disagreements():
    return listing(
        ordered(db.disagreements),
        {"round_id": ("round_id", str), "source_id": ("source_id", str),
         "status": ("status", str)},
    )


@bp.get("/disagreement-records/<record_id>")
@authorize(*READ_ROLES)
def get_disagreement(record_id):
    return object_response(disagreement_or_404(record_id))


# ----------------------------------------------------------------- writes ----
@bp.post("/consensus-rounds")
@authorize("ForecastDirector")
def create_round():
    data = body()

    cycle = None
    if data.get("cycle_id") is not None:
        if not isinstance(data["cycle_id"], str):
            validation("cycle_id must be a string")
        cycle = cycle_or_404(data["cycle_id"])
    if cycle is None:
        validation("cycle_id is required")

    variance_tol = req_int(data, "variance_tolerance_bps", minimum=0, maximum=10000)
    source_tol = req_int(data, "per_source_tolerance_bps", minimum=0, maximum=10000)
    expected = req_int(data, "expected_cycle_version", minimum=0)

    if expected != cycle["version"]:
        fail("ERR_STALE_CYCLE_VERSION",
             "expected_cycle_version %d does not match the cycle's current version %d"
             % (expected, cycle["version"]))
    if cycle["status"] not in ("INPUTS_LOCKED", "IN_CONSENSUS"):
        fail("ERR_CYCLE_NOT_LOCKED", "a round may only be opened on a locked cycle")

    number = len(calc.rounds_of(cycle["id"])) + 1
    cascade.supersede_rounds_of(cycle["id"])

    rec = make_record(
        {
            "cycle_id": cycle["id"],
            "round_number": number,
            "variance_tolerance_bps": variance_tol,
            "per_source_tolerance_bps": source_tol,
            "status": "OPEN",
            "exec_submission_status": "PENDING",
            "leg_submission_status": "PENDING",
            "exec_total_cents": None,
            "leg_total_cents": None,
            "variance_bps": None,
            "reconciled_total_cents": None,
            "open_disagreement_count": 0,
            "ratified_at": None,
        }
    )
    db.rounds[rec["id"]] = rec
    cycle["status"] = "IN_CONSENSUS"
    touch(cycle)
    return object_response(rec, 201)


@bp.post("/source-estimates")
@authorize(*ECONOMISTS)
def create_estimate():
    data = body()

    rnd = None
    source = None
    if data.get("round_id") is not None:
        if not isinstance(data["round_id"], str):
            validation("round_id must be a string")
        rnd = round_or_404(data["round_id"])
    if data.get("source_id") is not None:
        if not isinstance(data["source_id"], str):
            validation("source_id must be a string")
        source = source_or_404(data["source_id"])
    if rnd is None:
        validation("round_id is required")
    if source is None:
        validation("source_id is required")
    judgmental = opt_int(data, "judgmental_adjustment_cents", default=0, allow_negative=True)

    if rnd["status"] not in ("OPEN", "COMPARED"):
        fail("ERR_ROUND_NOT_OPEN", "estimates may only be filed in an open round")
    if source["status"] != "ACTIVE":
        fail("ERR_SOURCE_RETIRED", "a RETIRED source is out of scope for estimates")

    estimating_body = _body_of_role(g.role)
    if calc.estimate_for(rnd["id"], source["id"], estimating_body) is not None:
        fail("ERR_DUPLICATE_ESTIMATE",
             "this body already filed an estimate for that source in this round")

    cycle = db.cycles.get(rnd["cycle_id"])
    weighted = calc.weighted_scenario_cents(cycle, source)
    policy = calc.policy_adjustment_cents(source, cycle["fiscal_year"])
    _judgmental_cap_check(weighted, policy, judgmental)

    one_time = calc.one_time_cents(cycle["id"], source["id"])
    recurring = weighted + policy + judgmental
    rec = make_record(
        {
            "round_id": rnd["id"],
            "source_id": source["id"],
            "body": estimating_body,
            "submitted_by_user_id": g.user_id,
            "weighted_scenario_cents": weighted,
            "policy_adjustment_cents": policy,
            "judgmental_adjustment_cents": judgmental,
            "one_time_cents": one_time,
            "recurring_component_cents": recurring,
            "estimate_amount_cents": recurring + one_time,
            "locked": False,
        }
    )
    db.estimates[rec["id"]] = rec
    return object_response(rec, 201)


@bp.patch("/source-estimates/<estimate_id>")
@authorize(*ECONOMISTS)
def patch_estimate(estimate_id):
    est = estimate_or_404(estimate_id)
    data = body()
    judgmental = req_int(data, "judgmental_adjustment_cents", allow_negative=True)

    rnd = db.rounds.get(est["round_id"])
    if rnd is None or rnd["status"] not in ("OPEN", "COMPARED"):
        fail("ERR_ROUND_NOT_OPEN", "estimates may only be revised in an open round")
    if est["locked"]:
        fail("ERR_ESTIMATE_LOCKED", "a ratified round's estimates are immutable")
    _judgmental_cap_check(est["weighted_scenario_cents"], est["policy_adjustment_cents"],
                          judgmental)

    est["judgmental_adjustment_cents"] = judgmental
    est["recurring_component_cents"] = (
        est["weighted_scenario_cents"] + est["policy_adjustment_cents"] + judgmental
    )
    est["estimate_amount_cents"] = est["recurring_component_cents"] + est["one_time_cents"]
    touch(est)
    cascade.recompute_round(rnd)
    return object_response(est)


@bp.post("/consensus-rounds/<round_id>/submit")
@authorize(*ECONOMISTS)
def submit_round(round_id):
    rnd = round_or_404(round_id)
    estimating_body = _body_of_role(g.role)
    dimension = ("exec_submission_status" if estimating_body == "EXECUTIVE"
                 else "leg_submission_status")

    if rnd["status"] != "OPEN":
        fail("ERR_ROUND_NOT_OPEN", "only an OPEN round accepts a submission")
    if rnd[dimension] != "PENDING":
        fail("ERR_BODY_ALREADY_SUBMITTED", "this body has already submitted")

    filed = {e["source_id"] for e in calc.estimates_of(rnd["id"])
             if e["body"] == estimating_body}
    for src in calc.active_sources():
        if src["id"] not in filed:
            fail("ERR_INCOMPLETE_SUBMISSION",
                 "an estimate is missing for at least one ACTIVE revenue source")

    rnd[dimension] = "SUBMITTED"
    total = sum(e["estimate_amount_cents"] for e in calc.estimates_of(rnd["id"])
                if e["body"] == estimating_body)
    if estimating_body == "EXECUTIVE":
        rnd["exec_total_cents"] = total
    else:
        rnd["leg_total_cents"] = total

    if rnd["exec_submission_status"] == "SUBMITTED" and rnd["leg_submission_status"] == "SUBMITTED":
        cascade.compare_round(rnd)
    touch(rnd)
    return object_response(rnd)


@bp.post("/consensus-rounds/<round_id>/ratify")
@authorize("ForecastDirector")
def ratify_round(round_id):
    rnd = round_or_404(round_id)
    if rnd["status"] != "COMPARED" or rnd["open_disagreement_count"] != 0:
        fail("ERR_ROUND_NOT_COMPARED",
             "only a COMPARED round with no open disagreements may be ratified")
    rnd["status"] = "RATIFIED"
    rnd["ratified_at"] = now_iso()
    for est in calc.estimates_of(rnd["id"]):
        est["locked"] = True
    touch(rnd)

    cycle = db.cycles.get(rnd["cycle_id"])
    if cycle is not None:
        cycle["status"] = "CONSENSUS_REACHED"
        cycle["ratified_round_id"] = rnd["id"]
        touch(cycle)
    return object_response(rnd)


@bp.post("/disagreement-records/<record_id>/resolve")
@authorize("ForecastDirector")
def resolve_disagreement(record_id):
    record = disagreement_or_404(record_id)
    data = body()
    method = req_enum(data, "resolution_method", RESOLUTION_METHODS)
    rationale = req_str(data, "rationale")
    amount = opt_int(data, "resolved_amount_cents", allow_negative=True)

    if record["status"] != "OPEN":
        fail("ERR_DISAGREEMENT_NOT_OPEN", "only an OPEN disagreement may be resolved")

    rnd = db.rounds.get(record["round_id"])
    for est in calc.estimates_of(record["round_id"]):
        if est["source_id"] == record["source_id"] and est["submitted_by_user_id"] == g.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "the resolver may not be an author of either estimate under dispute")

    low = min(record["exec_amount_cents"], record["leg_amount_cents"])
    high = max(record["exec_amount_cents"], record["leg_amount_cents"])
    if method == "DIRECTOR_OVERRIDE":
        if amount is None:
            validation("resolved_amount_cents is required for DIRECTOR_OVERRIDE")
        if amount < low or amount > high:
            fail("ERR_OVERRIDE_OUT_OF_RANGE",
                 "resolved_amount_cents must sit inside the two submissions' band")
        resolved = amount
    else:
        if amount is not None:
            fail("ERR_RESOLUTION_AMOUNT_NOT_ALLOWED",
                 "%s derives its own amount" % method)
        if method == "EXEC_VALUE":
            resolved = record["exec_amount_cents"]
        elif method == "LEG_VALUE":
            resolved = record["leg_amount_cents"]
        else:
            resolved = rhu(record["exec_amount_cents"] + record["leg_amount_cents"], 2)

    if len(rationale) < RATIONALE_MIN:
        fail("ERR_RATIONALE_TOO_SHORT",
             "rationale must be at least %d characters" % RATIONALE_MIN)

    record["status"] = "RESOLVED"
    record["resolution_method"] = method
    record["resolved_amount_cents"] = resolved
    record["resolved_by_user_id"] = g.user_id
    record["rationale"] = rationale
    record["resolved_at"] = now_iso()
    touch(record)

    if rnd is not None:
        remaining = len([r for r in calc.disagreements_of(rnd["id"]) if r["status"] == "OPEN"])
        rnd["open_disagreement_count"] = remaining
        rnd["reconciled_total_cents"] = calc.reconciled_total_cents(rnd)
        if remaining == 0 and rnd["status"] == "DISPUTED":
            rnd["status"] = "COMPARED"
        touch(rnd)
    return object_response(record)
