"""Contract routes (PRD 3.4) — lifecycle, termination cascade, weekly pay."""

from flask import Blueprint, request

from db import store
from errors import ERR_INVALID_STATE, ERR_VALIDATION, ApiError, conflict
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from services import recompute_headcount, weekly_pay_quote
from util import (json_body, new_record, opt_int, parse_dt, req_enum, req_int,
                  req_str, to_public, touch)

bp = Blueprint("contracts", __name__)

ENGAGEMENT_TYPES = ("PRINCIPAL", "COVER", "CHORUS", "ORCHESTRA")
TARGET_STATES = ("OFFERED", "DRAFT", "SIGNED", "DECLINED", "ACTIVE",
                 "TERMINATED", "CLOSED")
REMOVABLE_PARTICIPANT_STATES = ("INVITED", "WAIVER_PENDING", "CONFIRMED", "CHECKED_IN")
ACTIVATION_PHASES = ("BUILD", "REHEARSAL", "IN_REPERTORY")


@bp.post("/opera/contracts")
def create_contract():
    uid, _ = require_roles("ContractsOfficer")
    body = json_body()
    production_id = req_str(body, "production_id")
    artist_id = req_str(body, "artist_id")
    engagement_type = req_enum(body, "engagement_type", ENGAGEMENT_TYPES)
    hourly_rate = req_int(body, "hourly_rate_cents", min_value=1)
    weekly_cap = req_int(body, "weekly_hours_cap", min_value=1)
    rest_floor = opt_int(body, "rest_floor_hours", default=12, min_value=0)
    prod = get_or_404(store.productions, production_id, "Production")
    artist = get_or_404(store.artists, artist_id, "Artist")
    rec = new_record(
        production_id=prod["id"],
        artist_id=artist["id"],
        engagement_type=engagement_type,
        hourly_rate_cents=hourly_rate,
        weekly_hours_cap=weekly_cap,
        rest_floor_hours=rest_floor,
        created_by_user_id=uid,
        status="DRAFT",
    )
    store.contracts[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/contracts")
def list_contracts():
    require_roles("Any")
    return list_response(
        store.contracts.values(),
        [("production_id", "production_id"), ("artist_id", "artist_id"),
         ("status", "status")],
    )


@bp.get("/opera/contracts/<cid>")
def get_contract(cid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.contracts, cid, "Contract")))


def _terminate_cascade(contract):
    """Move every non-terminal participant of the contract to REMOVED and
    recompute each affected call's confirmed_headcount."""
    affected_calls = set()
    for p in store.call_participants.values():
        if p["contract_id"] == contract["id"] and p["status"] in REMOVABLE_PARTICIPANT_STATES:
            p["status"] = "REMOVED"
            touch(p)
            affected_calls.add(p["call_id"])
    for call_id in affected_calls:
        call = store.rehearsal_calls.get(call_id)
        if call is not None:
            recompute_headcount(call)


@bp.post("/opera/contracts/<cid>/transition")
def transition_contract(cid):
    require_roles("ContractsOfficer")
    body = json_body()
    to_state = req_enum(body, "to_state", TARGET_STATES)
    contract = get_or_404(store.contracts, cid, "Contract")
    cur = contract["status"]

    if cur == "DRAFT" and to_state == "OFFERED":
        pass
    elif cur == "OFFERED" and to_state == "DRAFT":
        pass  # recall-to-revise loop
    elif cur == "OFFERED" and to_state == "SIGNED":
        pass
    elif cur == "OFFERED" and to_state == "DECLINED":
        pass
    elif cur == "SIGNED" and to_state == "ACTIVE":
        prod = store.productions[contract["production_id"]]
        if prod["status"] not in ACTIVATION_PHASES:
            raise conflict(ERR_INVALID_STATE,
                           "Contract activation requires the production in "
                           "BUILD, REHEARSAL, or IN_REPERTORY")
    elif cur in ("SIGNED", "ACTIVE") and to_state == "TERMINATED":
        _terminate_cascade(contract)
    elif cur == "ACTIVE" and to_state == "CLOSED":
        # Blocked by open commitments: participants still in play on open calls.
        for p in store.call_participants.values():
            if p["contract_id"] != contract["id"]:
                continue
            if p["status"] not in ("INVITED", "WAIVER_PENDING", "CONFIRMED"):
                continue
            call = store.rehearsal_calls.get(p["call_id"])
            if call is not None and call["status"] in ("DRAFT", "PUBLISHED"):
                raise conflict(ERR_INVALID_STATE,
                               "Contract has open call participation")
    else:
        raise conflict(ERR_INVALID_STATE,
                       f"Contract cannot transition {cur} -> {to_state}")

    contract["status"] = to_state
    touch(contract)
    return ok_object(to_public(contract))


@bp.get("/opera/contracts/<cid>/pay-quote")
def pay_quote(cid):
    require_roles("Any")
    contract = get_or_404(store.contracts, cid, "Contract")
    raw_week = request.args.get("week_start")
    if raw_week is None:
        raise ApiError(ERR_VALIDATION, 400, "Query parameter 'week_start' is required")
    week_start = parse_dt(raw_week, "week_start")
    # The window begins at week_start 00:00:00 UTC (PRD 3.4).
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    mode = request.args.get("mode")
    if mode is not None and mode not in ("PROJECTED", "FINAL"):
        raise ApiError(ERR_VALIDATION, 400, "mode must be PROJECTED or FINAL")
    return ok_object(weekly_pay_quote(contract, week_start))
