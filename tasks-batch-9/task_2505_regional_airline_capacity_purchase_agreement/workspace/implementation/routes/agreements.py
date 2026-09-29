"""Agreements (PRD 3.1) and the opening of an extension round (PRD 3.9)."""

from flask import Blueprint

import enums
import lookup
import validate
from auth import (ROLE_CPA_ADMINISTRATOR, ROLE_MAINLINE_SCHEDULER, any_role,
                  require)
from core import ZERO2, clock, parse_date
from db import new_entity, ordered, public, store, touch, values
from errors import fail
from response import object_response
from routes.common import collection_listing, guard_state

bp = Blueprint("agreements", __name__)

LIST_FILTERS = (("status", "status", enums.AGREEMENT_STATUS),)


@bp.route("/agreements", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def create_agreement():
    data = validate.body()
    mainline_partner_name = validate.string_field(data, "mainline_partner_name")
    regional_carrier_name = validate.string_field(data, "regional_carrier_name")
    fixed_monthly_fee_usd = validate.money_field(data, "fixed_monthly_fee_usd")
    block_hour_rate_usd = validate.money_field(data, "block_hour_rate_usd")
    departure_rate_usd = validate.money_field(data, "departure_rate_usd")
    aircraft_ownership_fee_usd = validate.money_field(data,
                                                     "aircraft_ownership_fee_usd")
    incentive_pool_cap_usd = validate.money_field(data, "incentive_pool_cap_usd",
                                                  allow_zero=True)
    penalty_cap_usd = validate.money_field(data, "penalty_cap_usd", allow_zero=True)
    term_end_date, _ = validate.date_field(data, "term_end_date")

    agreement = new_entity({
        "mainline_partner_name": mainline_partner_name,
        "regional_carrier_name": regional_carrier_name,
        "status": "DRAFT",
        "fixed_monthly_fee_usd": fixed_monthly_fee_usd,
        "block_hour_rate_usd": block_hour_rate_usd,
        "departure_rate_usd": departure_rate_usd,
        "aircraft_ownership_fee_usd": aircraft_ownership_fee_usd,
        "incentive_pool_cap_usd": incentive_pool_cap_usd,
        "penalty_cap_usd": penalty_cap_usd,
        "term_end_date": term_end_date,
        "extension_round_count": 0,
        "settled_to_date_usd": ZERO2,
        "open_invoice_count": 0,
        "activated_at": None,
    })
    store.agreements[agreement["id"]] = agreement
    return object_response(public(agreement), 201)


@bp.route("/agreements", methods=["GET"])
@any_role()
def list_agreements():
    return collection_listing("agreements", LIST_FILTERS)


@bp.route("/agreements/<agreement_id>", methods=["GET"])
@any_role()
def read_agreement(agreement_id):
    return object_response(public(lookup.agreement(agreement_id)))


@bp.route("/agreements/<agreement_id>/activate", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def activate_agreement(agreement_id):
    agreement = lookup.agreement(agreement_id)
    guard_state(agreement["status"] == "DRAFT")
    live_base = any(base["agreement_id"] == agreement["id"]
                    and base["lifecycle_status"] == "ACTIVE"
                    for base in store.crew_bases.values())
    guard_state(live_base, "The agreement has no ACTIVE crew base to operate from")

    agreement["status"] = "ACTIVE"
    agreement["activated_at"] = clock.iso()
    touch(agreement)
    return object_response(public(agreement))


@bp.route("/agreements/<agreement_id>/terminate", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def terminate_agreement(agreement_id):
    agreement = lookup.agreement(agreement_id)
    data = validate.body()
    validate.string_field(data, "termination_reason")

    guard_state(agreement["status"] in ("ACTIVE", "EXTENSION_PENDING"))
    open_cycle = any(cycle["agreement_id"] == agreement["id"]
                     and cycle["status"] == "OPEN"
                     for cycle in store.schedule_cycles.values())
    guard_state(not open_cycle,
                "A settlement month of this agreement is still OPEN")

    agreement["status"] = "TERMINATED"
    touch(agreement)

    # Hop 1: the agreement's live crew bases close.
    for base in values(store.crew_bases):
        if base["agreement_id"] != agreement["id"]:
            continue
        if base["lifecycle_status"] != "ACTIVE":
            continue
        base["lifecycle_status"] = "CLOSED"
        touch(base)
        # Hop 2, caused by hop 1: tails still awaiting induction there are withdrawn.
        for tail in values(store.aircraft):
            if tail["assigned_base_id"] != base["id"]:
                continue
            if tail["status"] != "PENDING_INDUCTION":
                continue
            tail["status"] = "WITHDRAWN"
            touch(tail)

    for negotiation in values(store.negotiations):
        if negotiation["agreement_id"] != agreement["id"]:
            continue
        if negotiation["status"] not in ("OFFERED", "COUNTERED"):
            continue
        negotiation["status"] = "WITHDRAWN"
        touch(negotiation)

    return object_response(public(agreement))


@bp.route("/agreements/<agreement_id>/extension-negotiations", methods=["POST"])
@require(ROLE_MAINLINE_SCHEDULER)
def open_extension_round(agreement_id):
    agreement = lookup.agreement(agreement_id)
    data = validate.body()
    proposed_term_end_date, proposed_term_end = validate.date_field(
        data, "proposed_term_end_date")
    proposed_block_hour_rate_usd = validate.money_field(
        data, "proposed_block_hour_rate_usd")
    expected_version = validate.int_field(data, "expected_agreement_version")

    if expected_version != agreement["version"]:
        fail("ERR_STALE_AGREEMENT_VERSION")

    guard_state(agreement["status"] == "ACTIVE")

    if proposed_term_end <= parse_date(agreement["term_end_date"]):
        fail("ERR_EXTENSION_TERM_NOT_LATER")

    # A successful offer supersedes every standing round on the same agreement.
    for standing in values(store.negotiations):
        if standing["agreement_id"] != agreement["id"]:
            continue
        if standing["status"] not in ("OFFERED", "COUNTERED"):
            continue
        standing["status"] = "WITHDRAWN"
        touch(standing)

    agreement["extension_round_count"] += 1
    agreement["status"] = "EXTENSION_PENDING"
    touch(agreement)

    negotiation = new_entity({
        "agreement_id": agreement["id"],
        "round_index": agreement["extension_round_count"],
        "proposed_term_end_date": proposed_term_end_date,
        "proposed_block_hour_rate_usd": proposed_block_hour_rate_usd,
        "counter_term_end_date": None,
        "counter_block_hour_rate_usd": None,
        "status": "OFFERED",
        "counter_round": 0,
    })
    store.negotiations[negotiation["id"]] = negotiation
    return object_response(public(negotiation), 201)
