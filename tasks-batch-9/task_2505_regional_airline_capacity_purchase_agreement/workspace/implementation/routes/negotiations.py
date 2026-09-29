"""Extension negotiation rounds (PRD 3.9)."""

from flask import Blueprint

import enums
import lookup
import validate
from auth import (ROLE_MAINLINE_SCHEDULER, ROLE_REGIONAL_OPS_CONTROLLER, any_role,
                  current_role, require)
from core import parse_date
from db import public, store, touch
from errors import fail
from response import object_response
from routes.common import collection_listing, guard_state, guard_terminal

bp = Blueprint("negotiations", __name__)

LIST_FILTERS = (
    ("agreement_id", "agreement_id", None),
    ("status", "status", enums.NEGOTIATION_STATUS),
)

MAX_COUNTER_ROUNDS = 2


def _agreement(negotiation):
    return store.agreements[negotiation["agreement_id"]]


@bp.route("/extension-negotiations", methods=["GET"])
@any_role()
def list_negotiations():
    return collection_listing("negotiations", LIST_FILTERS)


@bp.route("/extension-negotiations/<negotiation_id>", methods=["GET"])
@any_role()
def read_negotiation(negotiation_id):
    return object_response(public(lookup.negotiation(negotiation_id)))


@bp.route("/extension-negotiations/<negotiation_id>/counter", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def counter_negotiation(negotiation_id):
    negotiation = lookup.negotiation(negotiation_id)
    data = validate.body()
    counter_term_end_date, counter_term_end = validate.date_field(
        data, "counter_term_end_date")
    counter_block_hour_rate_usd = validate.money_field(
        data, "counter_block_hour_rate_usd")

    guard_terminal(negotiation, enums.NEGOTIATION_TERMINAL)
    guard_state(negotiation["status"] == "OFFERED")
    agreement = _agreement(negotiation)
    guard_state(agreement["status"] == "EXTENSION_PENDING")

    if negotiation["counter_round"] >= MAX_COUNTER_ROUNDS:
        fail("ERR_COUNTER_ROUNDS_EXHAUSTED")

    if counter_term_end <= parse_date(agreement["term_end_date"]):
        fail("ERR_EXTENSION_TERM_NOT_LATER")

    negotiation["status"] = "COUNTERED"
    negotiation["counter_term_end_date"] = counter_term_end_date
    negotiation["counter_block_hour_rate_usd"] = counter_block_hour_rate_usd
    negotiation["counter_round"] += 1
    touch(negotiation)
    return object_response(public(negotiation))


@bp.route("/extension-negotiations/<negotiation_id>/revise-offer", methods=["POST"])
@require(ROLE_MAINLINE_SCHEDULER)
def revise_offer(negotiation_id):
    negotiation = lookup.negotiation(negotiation_id)
    data = validate.body()
    proposed_term_end_date, proposed_term_end = validate.date_field(
        data, "proposed_term_end_date")
    proposed_block_hour_rate_usd = validate.money_field(
        data, "proposed_block_hour_rate_usd")

    guard_terminal(negotiation, enums.NEGOTIATION_TERMINAL)
    guard_state(negotiation["status"] == "COUNTERED")
    agreement = _agreement(negotiation)
    guard_state(agreement["status"] == "EXTENSION_PENDING")

    if proposed_term_end <= parse_date(agreement["term_end_date"]):
        fail("ERR_EXTENSION_TERM_NOT_LATER")

    negotiation["status"] = "OFFERED"
    negotiation["proposed_term_end_date"] = proposed_term_end_date
    negotiation["proposed_block_hour_rate_usd"] = proposed_block_hour_rate_usd
    negotiation["counter_term_end_date"] = None
    negotiation["counter_block_hour_rate_usd"] = None
    touch(negotiation)
    return object_response(public(negotiation))


@bp.route("/extension-negotiations/<negotiation_id>/accept", methods=["POST"])
@require(ROLE_MAINLINE_SCHEDULER, ROLE_REGIONAL_OPS_CONTROLLER)
def accept_negotiation(negotiation_id):
    negotiation = lookup.negotiation(negotiation_id)

    guard_terminal(negotiation, enums.NEGOTIATION_TERMINAL)
    guard_state(negotiation["status"] in ("OFFERED", "COUNTERED"))

    # PRD 2.11: the authoring side may not accept its own round.
    role = current_role()
    if negotiation["status"] == "OFFERED":
        if role != ROLE_REGIONAL_OPS_CONTROLLER:
            fail("ERR_SEGREGATION_OF_DUTIES")
        term_end_date = negotiation["proposed_term_end_date"]
        block_hour_rate_usd = negotiation["proposed_block_hour_rate_usd"]
    else:
        if role != ROLE_MAINLINE_SCHEDULER:
            fail("ERR_SEGREGATION_OF_DUTIES")
        term_end_date = negotiation["counter_term_end_date"]
        block_hour_rate_usd = negotiation["counter_block_hour_rate_usd"]

    negotiation["status"] = "ACCEPTED"
    touch(negotiation)

    agreement = _agreement(negotiation)
    agreement["term_end_date"] = term_end_date
    agreement["block_hour_rate_usd"] = block_hour_rate_usd
    agreement["status"] = "ACTIVE"
    touch(agreement)

    return object_response(public(negotiation))


@bp.route("/extension-negotiations/<negotiation_id>/withdraw", methods=["POST"])
@require(ROLE_MAINLINE_SCHEDULER)
def withdraw_negotiation(negotiation_id):
    negotiation = lookup.negotiation(negotiation_id)

    guard_terminal(negotiation, enums.NEGOTIATION_TERMINAL)
    guard_state(negotiation["status"] in ("OFFERED", "COUNTERED"))

    negotiation["status"] = "WITHDRAWN"
    touch(negotiation)

    agreement = _agreement(negotiation)
    agreement["status"] = "ACTIVE"
    touch(agreement)

    return object_response(public(negotiation))
