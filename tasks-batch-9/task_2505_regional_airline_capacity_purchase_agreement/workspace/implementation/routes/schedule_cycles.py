"""Settlement months: publication, opening, closing and invoice creation."""

from flask import Blueprint

import calc
import derive
import enums
import lookup
import validate
from auth import (ROLE_CPA_ADMINISTRATOR, ROLE_MAINLINE_SCHEDULER, any_role,
                  require)
from core import ZERO2, ZERO3, clock
from db import new_entity, ordered, public, store, touch, values
from errors import fail
from response import object_response
from routes.common import collection_listing, guard_state

bp = Blueprint("schedule_cycles", __name__)

LIST_FILTERS = (
    ("agreement_id", "agreement_id", None),
    ("status", "status", enums.CYCLE_STATUS),
)

PASSTHROUGH_TERMINAL = ("RECONCILED", "REJECTED")


def _new_scorecard(cycle):
    figures = derive.scorecard_figures(cycle)
    card = new_entity({
        "cycle_id": cycle["id"],
        "status": "PUBLISHED",
        "completion_factor_pct": figures["completion_factor_pct"],
        "on_time_arrival_pct": figures["on_time_arrival_pct"],
        "mishandled_bags_per_1000": figures["mishandled_bags_per_1000"],
        "completion_factor_points": figures["completion_factor_points"],
        "on_time_points": figures["on_time_points"],
        "bag_points": figures["bag_points"],
        "performance_points": figures["performance_points"],
        "gross_performance_usd": figures["gross_performance_usd"],
        "incentive_usd": figures["incentive_usd"],
        "penalty_usd": figures["penalty_usd"],
        "brand_penalty_usd": figures["brand_penalty_usd"],
        "recompute_count": 0,
    })
    store.scorecards[card["id"]] = card
    return card


@bp.route("/schedule-cycles", methods=["POST"])
@require(ROLE_MAINLINE_SCHEDULER)
def publish_cycle():
    data = validate.body()
    agreement_id = validate.string_field(data, "agreement_id")
    agreement = lookup.reference("agreements", agreement_id)

    cycle_month = validate.month_field(data, "cycle_month")
    published_departures = validate.int_field(data, "published_departures",
                                              minimum=0)

    for cycle in store.schedule_cycles.values():
        if (cycle["agreement_id"] == agreement["id"]
                and cycle["cycle_month"] == cycle_month):
            fail("ERR_DUPLICATE_RESOURCE")

    cycle = new_entity({
        "agreement_id": agreement["id"],
        "cycle_month": cycle_month,
        "published_departures": published_departures,
        "status": "PLANNED",
        "recorded_completed_legs": 0,
        "open_leg_count": 0,
        "cancelled_controllable_count": 0,
        "cancelled_uncontrollable_count": 0,
        # The two ledger positions open at published_departures (PRD 3.4 / 2.8).
        "metric_completed_departures": published_departures,
        "departure_ledger_total": published_departures,
        "credited_block_hours": ZERO3,
        "enplaned_bags_total": 0,
        "mishandled_bags_total": 0,
        "on_time_leg_count": 0,
        "estimated_passthrough_total_usd": ZERO2,
        "passthrough_settlement_usd": ZERO2,
        "closed_at": None,
    })
    store.schedule_cycles[cycle["id"]] = cycle
    return object_response(public(cycle), 201)


@bp.route("/schedule-cycles", methods=["GET"])
@any_role()
def list_cycles():
    return collection_listing("schedule_cycles", LIST_FILTERS)


@bp.route("/schedule-cycles/<cycle_id>", methods=["GET"])
@any_role()
def read_cycle(cycle_id):
    return object_response(public(lookup.schedule_cycle(cycle_id)))


@bp.route("/schedule-cycles/<cycle_id>/open", methods=["POST"])
@require(ROLE_MAINLINE_SCHEDULER)
def open_cycle(cycle_id):
    cycle = lookup.schedule_cycle(cycle_id)
    agreement = store.agreements[cycle["agreement_id"]]
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")

    guard_state(cycle["status"] == "PLANNED")

    cycle["status"] = "OPEN"
    touch(cycle)
    return object_response(public(cycle))


@bp.route("/schedule-cycles/<cycle_id>/close", methods=["POST"])
@require(ROLE_MAINLINE_SCHEDULER)
def close_cycle(cycle_id):
    cycle = lookup.schedule_cycle(cycle_id)

    guard_state(cycle["status"] == "OPEN")
    if cycle["open_leg_count"] != 0:
        fail("ERR_CYCLE_HAS_OPEN_LEGS")

    cycle["status"] = "CLOSED"
    cycle["closed_at"] = clock.iso()
    derive.refresh_cycle(cycle)
    touch(cycle)

    _new_scorecard(cycle)

    return object_response(public(cycle))


@bp.route("/schedule-cycles/<cycle_id>/invoices", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def create_invoice(cycle_id):
    cycle = lookup.schedule_cycle(cycle_id)
    data = validate.body()
    variant = validate.enum_field(data, "variant", enums.INVOICE_VARIANT)
    expected_version = validate.int_field(data, "expected_schedule_cycle_version")

    if expected_version != cycle["version"]:
        fail("ERR_STALE_CYCLE_VERSION")

    if variant == "FINAL":
        guard_state(cycle["status"] == "CLOSED",
                    "A FINAL invoice requires a CLOSED settlement month")
        unreconciled = any(
            claim["cycle_id"] == cycle["id"]
            and claim["status"] not in PASSTHROUGH_TERMINAL
            for claim in store.passthrough_claims.values())
        if unreconciled:
            fail("ERR_PASSTHROUGH_UNRECONCILED")

    agreement = store.agreements[cycle["agreement_id"]]
    cards = derive.scorecards_of_cycle(cycle["id"])
    scorecard = cards[0] if cards else None
    components = calc.invoice_settlement(cycle, agreement, variant, scorecard)

    # A newer invoice supersedes the cycle's standing draft of the same variant.
    for standing in values(store.invoices):
        if standing["cycle_id"] != cycle["id"]:
            continue
        if standing["variant"] != variant or standing["status"] != "DRAFT":
            continue
        derive.void_invoice(standing, "AUTO_SUPERSEDED")

    invoice = new_entity({
        "cycle_id": cycle["id"],
        "variant": variant,
        "status": "DRAFT",
        "ownership_aircraft_count": components["ownership_aircraft_count"],
        "fixed_component_usd": components["fixed_component_usd"],
        "variable_component_usd": components["variable_component_usd"],
        "passthrough_component_usd": components["passthrough_component_usd"],
        "incentive_component_usd": components["incentive_component_usd"],
        "penalty_component_usd": components["penalty_component_usd"],
        "brand_penalty_component_usd": components["brand_penalty_component_usd"],
        "total_usd": components["total_usd"],
        "void_reason": None,
        "issued_final_at": None,
    })
    store.invoices[invoice["id"]] = invoice

    touch(cycle)
    derive.refresh_agreement(agreement)

    return object_response(public(invoice), 201)
