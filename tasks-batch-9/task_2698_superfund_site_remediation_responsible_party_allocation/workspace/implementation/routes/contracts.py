"""Procurement, field work and construction completion."""

from datetime import timedelta

from flask import Blueprint

import calc
import constants as K
import derive
import logical_clock
import serialize
import shape
import store
import txn
from authz import require
from errors import ApiError
from routes import common

bp = Blueprint("contracts", __name__)

BUFFER = timedelta(hours=K.MOBILIZATION_BUFFER_HOURS)


@bp.post("/sites/<site_id>/remediation-contracts")
def create_contract(site_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    rod_id = shape.str_field(body, "record_of_decision_id")
    reference = shape.str_field(body, "solicitation_reference")
    estimate = shape.money_field(body, "engineer_estimate_cents", strictly_positive=True)
    site = common.get_site(site_id)
    rod = common.get_rod(rod_id)
    if rod["site_id"] != site["id"]:
        raise ApiError("ERR_RECORD_OF_DECISION_NOT_FOUND")
    common.deny_deleted(site)
    if rod["status"] != "SIGNED":
        raise ApiError("ERR_ROD_NOT_SIGNED")

    contract = common.new_record(
        {
            "site_id": site["id"],
            "record_of_decision_id": rod["id"],
            "solicitation_reference": reference,
            "engineer_estimate_cents": estimate,
            "status": "SOLICITATION",
            "contractor_name": None,
            "awarded_amount_cents": None,
            "max_concurrent_windows": K.DEFAULT_MAX_CONCURRENT_WINDOWS,
            "awarded_at": None,
            "completion_date": None,
            "punch_list_items": 0,
            "work_window_count": 0,
        }
    )
    store.remediation_contracts[contract["id"]] = contract
    return common.respond(contract, serialize.remediation_contract, 201)


@bp.post("/remediation-contracts/<contract_id>/award")
def award_contract(contract_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    contractor = shape.str_field(body, "contractor_name")
    amount = shape.money_field(body, "awarded_amount_cents", minimum=0)
    capacity = shape.int_field(body, "max_concurrent_windows", required=False, lo=1, hi=5)
    contract = common.get_contract(contract_id)
    site = store.sites[contract["site_id"]]
    # An award against a frozen site reports the freeze, because that is the
    # condition that actually holds.
    common.deny_frozen(site)
    common.deny_restricted(site)
    common.state(contract["status"] == "SOLICITATION")
    common.deny_deleted(site)
    rod = store.records_of_decision[contract["record_of_decision_id"]]
    if rod["status"] != "SIGNED":
        raise ApiError("ERR_ROD_NOT_SIGNED")
    if not calc.bid_ceiling_ok(amount, contract["engineer_estimate_cents"]):
        raise ApiError("ERR_BID_EXCEEDS_ESTIMATE")

    txn.watch(contract)
    contract["status"] = "AWARDED"
    contract["contractor_name"] = contractor
    contract["awarded_amount_cents"] = amount
    if capacity is not None:
        contract["max_concurrent_windows"] = capacity
    contract["awarded_at"] = logical_clock.now()
    if site["listing_status"] == "ROD_SIGNED":
        txn.watch(site)
        site["listing_status"] = "CONSTRUCTION"
    # The awarded amount now enters the response-cost basis.
    derive.recompute_site_derived(site)
    return common.respond(contract, serialize.remediation_contract)


@bp.post("/remediation-contracts/<contract_id>/work-windows")
def create_window(contract_id):
    actor = require(K.ROLE_CONTRACTOR)
    body = shape.get_body()
    activity = shape.enum_field(body, "activity_type", K.ACTIVITY_TYPES)
    start_at = shape.datetime_field(body, "start_at")
    end_at = shape.datetime_field(body, "end_at")
    crew_size = shape.int_field(body, "crew_size", lo=1, hi=200)
    description = shape.str_field(body, "description", required=False)
    if end_at <= start_at:
        shape.bad("Field 'end_at' must fall strictly after 'start_at'.")
    contract = common.get_contract(contract_id)
    # Only on its own contract.
    common.identity(actor, contract["id"])
    site = store.sites[contract["site_id"]]
    common.deny_frozen(site)
    common.deny_restricted(site)
    common.deny_deleted(site)

    buffered_start = start_at - BUFFER
    buffered_end = end_at + BUFFER
    # Half-open contention over the mobilisation-buffered intervals: a buffered
    # end coinciding exactly with another's buffered start does not intersect.
    concurrent = 0
    for other in derive.contract_windows(contract["id"]):
        if buffered_start < other["buffered_end_at"] and other["buffered_start_at"] < buffered_end:
            concurrent += 1
    if concurrent + 1 > contract["max_concurrent_windows"]:
        raise ApiError("ERR_WORK_WINDOW_CAPACITY_EXCEEDED")

    window = common.new_record(
        {
            "remediation_contract_id": contract["id"],
            "activity_type": activity,
            "start_at": start_at,
            "end_at": end_at,
            "crew_size": crew_size,
            "description": description,
            "buffered_start_at": buffered_start,
            "buffered_end_at": buffered_end,
        },
        mutable=False,
    )
    store.work_windows[window["id"]] = window
    txn.watch(contract)
    contract["work_window_count"] = len(derive.contract_windows(contract["id"]))
    return common.respond(window, serialize.work_window, 201)


@bp.post("/remediation-contracts/<contract_id>/construction-completion")
def complete_construction(contract_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    punch_list = shape.int_field(body, "punch_list_items", lo=0)
    contract = common.get_contract(contract_id)
    site = store.sites[contract["site_id"]]
    # A contract that certifies completion having never scheduled any work is
    # an invalid transition.
    common.state(contract["status"] == "AWARDED" and contract["work_window_count"] >= 1)
    common.deny_deleted(site)

    completion_day = logical_clock.today()
    txn.watch(contract)
    contract["status"] = "CONSTRUCTION_COMPLETE"
    contract["punch_list_items"] = punch_list
    contract["completion_date"] = completion_day

    txn.watch(site)
    if site["listing_status"] == "CONSTRUCTION":
        site["listing_status"] = "OM_PHASE"
    complete_at = logical_clock.midnight(completion_day)
    site["construction_complete_at"] = complete_at
    site["five_year_review_due_at"] = logical_clock.plus_days(
        complete_at, K.FIVE_YEAR_REVIEW_DAYS
    )
    derive.terminate_eligible_decrees(site)
    derive.recompute_site_derived(site)
    return common.respond(contract, serialize.remediation_contract)
