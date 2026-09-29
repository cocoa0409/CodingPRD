"""Forecast cycles, their scenarios and the computed scenario-estimate preview."""

from flask import Blueprint

from db import db, make_record, ordered, touch
from errors import fail
from middleware import authorize, body, opt_enum, opt_int, req_enum, req_int, validation
from response import object_response, raw_object_response
from routes.helpers import cycle_or_404, listing, scenario_or_404, source_or_404
from services import calc, cascade

bp = Blueprint("cycles", __name__)

ALL_ROLES = (
    "ForecastDirector",
    "ExecutiveEconomist",
    "LegislativeEconomist",
    "ReserveTreasurer",
    "LegislativeVoter",
    "RatingAnalyst",
)
CYCLE_TYPES = ("BASELINE", "REVISION")
POLICIES = ("MIDPOINT_AVERAGE", "LOWER_OF_TWO")
SCENARIO_LABELS = ("BASELINE", "OPTIMISTIC", "PESSIMISTIC", "ALTERNATIVE")


def _refresh_weight_total(cycle):
    cycle["scenario_weight_total_bps"] = sum(
        s["weight_bps"] for s in calc.scenarios_of(cycle["id"])
    )


# ------------------------------------------------------------------ reads ----
@bp.get("/forecast-cycles")
@authorize(*ALL_ROLES)
def list_cycles():
    return listing(
        ordered(db.cycles),
        {
            "fiscal_year": ("fiscal_year", int),
            "status": ("status", str),
            "cycle_type": ("cycle_type", str),
            "supersedes_cycle_id": ("supersedes_cycle_id", str),
            "ratified_round_id": ("ratified_round_id", str),
        },
    )


@bp.get("/forecast-cycles/<cycle_id>")
@authorize(*ALL_ROLES)
def get_cycle(cycle_id):
    return object_response(cycle_or_404(cycle_id))


@bp.get("/forecast-cycles/<cycle_id>/scenarios")
@authorize("ForecastDirector", "ExecutiveEconomist", "LegislativeEconomist", "RatingAnalyst")
def list_cycle_scenarios(cycle_id):
    cycle = cycle_or_404(cycle_id)
    return listing(calc.scenarios_of(cycle["id"]), {"label": ("label", str)})


@bp.get("/forecast-cycles/<cycle_id>/consensus-rounds")
@authorize("ForecastDirector", "ExecutiveEconomist", "LegislativeEconomist", "RatingAnalyst")
def list_cycle_rounds(cycle_id):
    cycle = cycle_or_404(cycle_id)
    return listing(calc.rounds_of(cycle["id"]), {"status": ("status", str)})


@bp.get("/forecast-cycles/<cycle_id>/scenario-estimates")
@authorize("ForecastDirector", "ExecutiveEconomist", "LegislativeEconomist")
def scenario_estimates(cycle_id):
    from flask import request

    cycle = cycle_or_404(cycle_id)
    source_id = request.args.get("source_id")
    if source_id is None or source_id == "":
        validation("source_id is required")
    source = source_or_404(source_id)

    weighted = calc.weighted_scenario_cents(cycle, source)
    policy = calc.policy_adjustment_cents(source, cycle["fiscal_year"])
    one_time = calc.one_time_cents(cycle["id"], source["id"])
    recurring = weighted + policy
    return raw_object_response(
        {
            "source_id": source["id"],
            "weighted_scenario_cents": weighted,
            "policy_adjustment_cents": policy,
            "one_time_cents": one_time,
            "recurring_component_cents": recurring,
            "estimate_amount_cents": recurring + one_time,
        }
    )


# ----------------------------------------------------------------- writes ----
@bp.post("/forecast-cycles")
@authorize("ForecastDirector")
def create_cycle():
    data = body()

    # tier 5 — a body FK must resolve before the shape is judged
    supersedes = data.get("supersedes_cycle_id")
    target = None
    if supersedes is not None:
        if not isinstance(supersedes, str):
            validation("supersedes_cycle_id must be a string")
        target = cycle_or_404(supersedes)

    fiscal_year = req_int(data, "fiscal_year", minimum=2000, maximum=2100)
    cycle_type = req_enum(data, "cycle_type", CYCLE_TYPES)
    policy = req_enum(data, "reconciliation_policy", POLICIES)
    enacted = req_int(data, "enacted_appropriation_cents", minimum=1)
    prior = req_int(data, "prior_recurring_baseline_cents", minimum=0)

    if cycle_type == "REVISION":
        if target is None:
            fail("ERR_INVALID_SUPERSEDE_TARGET",
                 "a REVISION cycle must name the CERTIFIED cycle it supersedes")
        if target["status"] != "CERTIFIED" or target["fiscal_year"] != fiscal_year:
            fail("ERR_INVALID_SUPERSEDE_TARGET",
                 "the superseded cycle must be CERTIFIED and share the fiscal year")
    elif target is not None:
        fail("ERR_INVALID_SUPERSEDE_TARGET", "a BASELINE cycle may not supersede a cycle")

    rec = make_record(
        {
            "fiscal_year": fiscal_year,
            "cycle_type": cycle_type,
            "reconciliation_policy": policy,
            "supersedes_cycle_id": supersedes,
            "enacted_appropriation_cents": enacted,
            "prior_recurring_baseline_cents": prior,
            "status": "DRAFT",
            "scenario_weight_total_bps": 0,
            "ratified_round_id": None,
            "certified_total_cents": None,
            "certified_one_time_cents": None,
            "certified_recurring_total_cents": None,
            "certified_at": None,
            "shortfall_gap_cents": None,
            "shortfall_pct_bps": None,
            "reopen_count": 0,
        }
    )
    db.cycles[rec["id"]] = rec
    return object_response(rec, 201)


@bp.patch("/forecast-cycles/<cycle_id>")
@authorize("ForecastDirector")
def patch_cycle(cycle_id):
    cycle = cycle_or_404(cycle_id)
    data = body()
    enacted = opt_int(data, "enacted_appropriation_cents", minimum=1)
    prior = opt_int(data, "prior_recurring_baseline_cents", minimum=0)
    policy = opt_enum(data, "reconciliation_policy", POLICIES)

    if cycle["status"] != "DRAFT":
        fail("ERR_CYCLE_NOT_IN_DRAFT", "only a DRAFT cycle may be amended")

    if enacted is not None:
        cycle["enacted_appropriation_cents"] = enacted
    if prior is not None:
        cycle["prior_recurring_baseline_cents"] = prior
    if policy is not None:
        cycle["reconciliation_policy"] = policy
    touch(cycle)
    return object_response(cycle)


@bp.post("/forecast-cycles/<cycle_id>/scenarios")
@authorize("ForecastDirector", "ExecutiveEconomist")
def create_scenario(cycle_id):
    cycle = cycle_or_404(cycle_id)
    data = body()
    label = req_enum(data, "label", SCENARIO_LABELS)
    weight = req_int(data, "weight_bps", minimum=0, maximum=10000)
    employment = req_int(data, "employment_growth_bps", allow_negative=True)
    wage = req_int(data, "wage_income_bps", allow_negative=True)
    retail = req_int(data, "retail_sales_bps", allow_negative=True)
    asset = req_int(data, "asset_market_return_bps", allow_negative=True)

    if cycle["status"] != "DRAFT":
        fail("ERR_CYCLE_NOT_IN_DRAFT", "economic inputs may only change while the cycle is DRAFT")
    for existing in calc.scenarios_of(cycle["id"]):
        if existing["label"] == label:
            fail("ERR_DUPLICATE_SCENARIO_LABEL", "label %s already exists on this cycle" % label)

    rec = make_record(
        {
            "cycle_id": cycle["id"],
            "label": label,
            "weight_bps": weight,
            "employment_growth_bps": employment,
            "wage_income_bps": wage,
            "retail_sales_bps": retail,
            "asset_market_return_bps": asset,
        }
    )
    db.scenarios[rec["id"]] = rec
    _refresh_weight_total(cycle)
    touch(cycle)
    return object_response(rec, 201)


@bp.post("/forecast-cycles/<cycle_id>/lock-inputs")
@authorize("ForecastDirector")
def lock_inputs(cycle_id):
    cycle = cycle_or_404(cycle_id)
    if cycle["status"] != "DRAFT":
        fail("ERR_CYCLE_NOT_IN_DRAFT", "only a DRAFT cycle may be locked")
    scenarios = calc.scenarios_of(cycle["id"])
    total = sum(s["weight_bps"] for s in scenarios)
    if not scenarios or total != 10000:
        fail("ERR_SCENARIO_WEIGHTS_INVALID",
             "scenario weights must total exactly 10000 bps (found %d)" % total)
    cycle["status"] = "INPUTS_LOCKED"
    touch(cycle)
    return object_response(cycle)


@bp.post("/forecast-cycles/<cycle_id>/reopen")
@authorize("ForecastDirector")
def reopen(cycle_id):
    cycle = cycle_or_404(cycle_id)
    ratified = [r for r in calc.rounds_of(cycle["id"]) if r["status"] == "RATIFIED"]
    if cycle["status"] != "IN_CONSENSUS" or ratified:
        fail("ERR_CYCLE_ALREADY_RATIFIED",
             "only an IN_CONSENSUS cycle with no ratified round may be reopened")
    cascade.supersede_rounds_of(cycle["id"])
    cycle["reopen_count"] = cycle["reopen_count"] + 1
    cycle["ratified_round_id"] = None
    cycle["status"] = "DRAFT"
    touch(cycle)
    return object_response(cycle)


@bp.post("/forecast-cycles/<cycle_id>/certify")
@authorize("ForecastDirector")
def certify(cycle_id):
    cycle = cycle_or_404(cycle_id)
    if cycle["status"] != "CONSENSUS_REACHED" or not cycle.get("ratified_round_id"):
        fail("ERR_CYCLE_NOT_CONSENSUS_REACHED",
             "only a CONSENSUS_REACHED cycle may be certified")
    cascade.certify_cascade(cycle)
    return object_response(cycle)


# ------------------------------------------------------- economic scenarios --
@bp.get("/economic-scenarios/<scenario_id>")
@authorize("ForecastDirector", "ExecutiveEconomist", "LegislativeEconomist", "RatingAnalyst")
def get_scenario(scenario_id):
    return object_response(scenario_or_404(scenario_id))


@bp.patch("/economic-scenarios/<scenario_id>")
@authorize("ForecastDirector", "ExecutiveEconomist")
def patch_scenario(scenario_id):
    scenario = scenario_or_404(scenario_id)
    cycle = db.cycles.get(scenario["cycle_id"])
    data = body()
    label = opt_enum(data, "label", SCENARIO_LABELS)
    weight = opt_int(data, "weight_bps", minimum=0, maximum=10000)
    fields = {}
    for name in ("employment_growth_bps", "wage_income_bps", "retail_sales_bps",
                 "asset_market_return_bps"):
        value = opt_int(data, name, allow_negative=True)
        if value is not None:
            fields[name] = value

    if cycle is None or cycle["status"] != "DRAFT":
        fail("ERR_CYCLE_NOT_IN_DRAFT", "a scenario is immutable once its cycle leaves DRAFT")
    if label is not None:
        for other in calc.scenarios_of(cycle["id"]):
            if other["id"] != scenario["id"] and other["label"] == label:
                fail("ERR_DUPLICATE_SCENARIO_LABEL",
                     "label %s already exists on this cycle" % label)
        scenario["label"] = label
    if weight is not None:
        scenario["weight_bps"] = weight
    scenario.update(fields)
    touch(scenario)
    _refresh_weight_total(cycle)
    touch(cycle)
    return object_response(scenario)


@bp.delete("/economic-scenarios/<scenario_id>")
@authorize("ForecastDirector")
def delete_scenario(scenario_id):
    scenario = scenario_or_404(scenario_id)
    cycle = db.cycles.get(scenario["cycle_id"])
    if cycle is None or cycle["status"] != "DRAFT":
        fail("ERR_CYCLE_NOT_IN_DRAFT", "a scenario is immutable once its cycle leaves DRAFT")
    del db.scenarios[scenario["id"]]
    _refresh_weight_total(cycle)
    touch(cycle)
    return "", 204
