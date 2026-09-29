"""Optimisation scenarios and routing-guide publication — PRD §3.6."""
from decimal import Decimal

from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError
from numeric import D
from services import optimize

bp = Blueprint("optimization", __name__)

RUN_EVENT_STATUSES = ("ROUND_CLOSED", "OPTIMIZING", "AWARDING")


@bp.post("/freight-procurement/optimization-runs")
@auth.roles_required("ProcurementAnalyst")
def create_run():
    payload = v.body()
    event_id = v.id_field(payload, "bid_event_id")
    expected_version = v.int_field(payload, "expected_bid_event_version", minimum=0)
    label = v.string_field(payload, "scenario_label", min_len=1, max_len=64)
    max_carriers = v.int_field(payload, "max_carriers_per_lane", required=False,
                               default=None, minimum=1, maximum=3)
    diversity_min = v.dec_field(payload, "diversity_min_pct", required=False,
                                default=None)
    min_coverage = v.dec_field(payload, "min_capacity_coverage_pct", required=False,
                               default=optimize.DEFAULT_MIN_CAPACITY_COVERAGE_PCT)

    event = helpers.get_event(event_id)

    if expected_version != event["version"]:
        raise ApiError("ERR_STALE_BID_EVENT_VERSION")

    for round_row in store.rounds.values():
        if round_row["bid_event_id"] == event["id"] and round_row["status"] == "OPEN":
            raise ApiError("ERR_ROUND_STILL_OPEN")
    if event["status"] not in RUN_EVENT_STATUSES:
        raise ApiError("ERR_EVENT_NOT_OPTIMIZING")

    optimize.supersede_history(event)

    run = store.new_row(
        bid_event_id=event["id"],
        scenario_label=label,
        max_carriers_per_lane=(max_carriers if max_carriers is not None
                               else event["max_carriers_per_lane"]),
        diversity_min_pct=(diversity_min if diversity_min is not None
                           else event["diversity_min_pct"]),
        min_capacity_coverage_pct=min_coverage,
        status="COMPLETED",
        total_cost_usd=Decimal("0.00"),
        coverage_pct=Decimal("0.00"),
        diversity_pct=Decimal("0.00"),
        objective_score=Decimal("0.00"),
        infeasible_lane_ids=[],
        proposed_primary_count=0,
        proposed_backup_count=0,
        published_at=None,
    )
    optimize.evaluate_run(event, run)
    store.runs[run["id"]] = run

    event["status"] = "OPTIMIZING"
    store.touch(event)
    return responses.created(run)


@bp.get("/freight-procurement/optimization-runs/<run_id>")
@auth.roles_required("ProcurementAnalyst", "CategoryManager")
def get_run(run_id):
    return responses.ok(helpers.get_run(run_id))


@bp.post("/freight-procurement/optimization-runs/<run_id>/routing-guide")
@auth.roles_required("ProcurementAnalyst")
def publish_routing_guide(run_id):
    run = helpers.get_run(run_id)
    v.body()
    event = helpers.event_of(run)

    if event is None or event["status"] != "OPTIMIZING":
        raise ApiError("ERR_EVENT_NOT_OPTIMIZING")
    if run["status"] == "FAILED":
        raise ApiError("ERR_NO_FEASIBLE_ALLOCATION")
    if run["status"] != "COMPLETED":
        raise ApiError("ERR_EVENT_NOT_OPTIMIZING",
                       "Only a COMPLETED scenario may be published.")
    if D(run["coverage_pct"]) < D(run["min_capacity_coverage_pct"]):
        raise ApiError("ERR_COVERAGE_BELOW_MINIMUM")

    optimize.publish_guide(event, run)

    run["status"] = "PUBLISHED"
    run["published_at"] = store.now_iso()
    store.touch(run)

    event["status"] = "AWARDING"
    store.touch(event)
    return responses.ok(run)
