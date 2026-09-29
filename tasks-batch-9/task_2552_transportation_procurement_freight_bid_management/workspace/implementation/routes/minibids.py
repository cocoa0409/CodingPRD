"""Mini-bid windows, proposals and the mid-contract money cascade — PRD §3.9."""
from decimal import Decimal

from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError
from numeric import D, q2, q4
from services import contracts as contract_svc, lanes as lane_svc

bp = Blueprint("minibids", __name__)

TRIGGER_REASONS = ("TENDER_REJECTION_RATE", "MARKET_INDEX", "CAPACITY_FAILURE")
CONFLICTING_STATUSES = ("REQUESTED", "OPEN", "APPLIED")
QUOTA_STATUSES = ("OPEN", "APPLIED")
QUOTA_LIMIT = 2
QUOTA_WINDOW_DAYS = 90
COOLDOWN_DAYS = 7
MAX_ADJUSTMENT_PCT = Decimal("12.00")
PROPOSAL_ALLOCATION_STATUSES = ("EXECUTED", "ACTIVE", "SUSPENDED_ROUTING")
LIVE_RECORD_STATUSES = ("LIVE", "AT_RISK")


def _lane_mini_bids(lane_id):
    return store.sorted_rows([m for m in store.mini_bids.values()
                              if m["lane_id"] == lane_id])


@bp.post("/freight-procurement/mini-bids")
@auth.roles_required("CategoryManager")
def create_mini_bid():
    payload = v.body()
    event_id = v.id_field(payload, "bid_event_id")
    lane_id = v.id_field(payload, "lane_id")
    record_id = v.id_field(payload, "rate_record_id")
    trigger_reason = v.enum_field(payload, "trigger_reason", TRIGGER_REASONS)
    window_open_at = v.dt_field(payload, "window_open_at")
    window_close_at = v.dt_field(payload, "window_close_at")
    v.interval(window_open_at, window_close_at, "window_open_at", "window_close_at")

    # Rung 5 — body foreign keys in declared order.
    event = helpers.get_event(event_id)
    lane = helpers.get_lane(lane_id)
    record = helpers.get_rate_record(record_id)

    open_at = store.parse_dt(window_open_at)
    close_at = store.parse_dt(window_close_at)

    # Rung 14 — window conflict, on closed intervals, so windows that merely touch at an
    # endpoint do conflict.  DENIED and REVERTED windows are ignored.
    for other in _lane_mini_bids(lane["id"]):
        if other["status"] not in CONFLICTING_STATUSES:
            continue
        other_open = store.dt_of(other["window_open_at"])
        other_close = store.dt_of(other["window_close_at"])
        if open_at <= other_close and other_open <= close_at:
            raise ApiError("ERR_MINI_BID_WINDOW_CONFLICT")

    # Rung 14 — cooldown measured from the lane's most recently applied mini-bid.
    latest_applied = None
    for other in _lane_mini_bids(lane["id"]):
        if other["status"] != "APPLIED" or other["applied_at"] is None:
            continue
        applied_at = store.dt_of(other["applied_at"])
        if latest_applied is None or applied_at > latest_applied:
            latest_applied = applied_at
    if latest_applied is not None and open_at < latest_applied + store.days(COOLDOWN_DAYS):
        raise ApiError("ERR_MINI_BID_COOLDOWN_ACTIVE")

    # Rung 16 — the rolling quota counts windows that actually reached negotiation or
    # adjustment, measured back from the requested window_open_at.
    quota_floor = open_at - store.days(QUOTA_WINDOW_DAYS)
    consumed = 0
    for other in _lane_mini_bids(lane["id"]):
        if other["status"] not in QUOTA_STATUSES:
            continue
        other_open = store.dt_of(other["window_open_at"])
        if quota_floor <= other_open <= open_at:
            consumed += 1
    if consumed >= QUOTA_LIMIT:
        raise ApiError("ERR_MINI_BID_QUOTA_EXCEEDED")

    mini_bid = store.new_row(
        bid_event_id=event["id"],
        lane_id=lane["id"],
        rate_record_id=record["id"],
        applied_rate_record_id=None,
        proposed_by_carrier_id=None,
        trigger_reason=trigger_reason,
        origin="MANUAL",
        status="REQUESTED",
        window_open_at=window_open_at,
        window_close_at=window_close_at,
        proposed_rate_per_mile=None,
        adjustment_pct=None,
        contract_value_before_usd=None,
        contract_value_after_usd=None,
        denial_reason=None,
        revert_reason=None,
        applied_at=None,
        reverted_at=None,
    )
    store.mini_bids[mini_bid["id"]] = mini_bid
    return responses.created(mini_bid)


@bp.get("/freight-procurement/mini-bids/<mini_bid_id>")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "ContractAdmin",
                     "CarrierRep")
def get_mini_bid(mini_bid_id):
    return responses.ok(helpers.get_mini_bid(mini_bid_id))


@bp.get("/freight-procurement/mini-bids")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "ContractAdmin",
                     "CarrierRep")
def list_mini_bids():
    rows = store.sorted_rows(store.mini_bids.values())
    rows = helpers.filter_rows(rows, {
        "bid_event_id": "bid_event_id",
        "lane_id": "lane_id",
        "rate_record_id": "rate_record_id",
        "applied_rate_record_id": "applied_rate_record_id",
        "proposed_by_carrier_id": "proposed_by_carrier_id",
        "status": "status",
    })
    return responses.listing(rows)


def _adjustment_pct(proposed, current):
    """Positive for an increase, negative for a decrease, measured against the rate as it
    is currently stored — never against the rate originally awarded."""
    return q2((D(proposed) - D(current)) * Decimal("100.00") / D(current))


@bp.post("/freight-procurement/mini-bids/<mini_bid_id>/proposal")
@auth.roles_required("CarrierRep")
def propose(mini_bid_id):
    mini_bid = helpers.get_mini_bid(mini_bid_id)
    payload = v.body()
    carrier_id = v.id_field(payload, "carrier_id")
    proposed = v.dec_field(payload, "proposed_rate_per_mile", exclusive_min=True)

    auth.own_carrier_or_raise(carrier_id)
    carrier = helpers.get_carrier(carrier_id)

    if mini_bid["status"] != "REQUESTED":
        raise ApiError("ERR_MINI_BID_NOT_OPEN")

    # The window is a closed interval on both ends.
    now = store.now()
    if not (store.dt_of(mini_bid["window_open_at"]) <= now
            <= store.dt_of(mini_bid["window_close_at"])):
        raise ApiError("ERR_MINI_BID_NOT_OPEN")

    # A carrier not routed on the lane has nothing to re-price.
    routed = any(a["lane_id"] == mini_bid["lane_id"]
                 and a["carrier_id"] == carrier_id
                 and a["status"] in PROPOSAL_ALLOCATION_STATUSES
                 for a in store.allocations.values())
    if not routed:
        raise ApiError("ERR_MINI_BID_NOT_OPEN")

    helpers.check_fitness(carrier)

    record = store.rate_records.get(mini_bid["rate_record_id"])
    current_rate = D(record["rate_per_mile"]) if record else Decimal("0")
    adjustment = _adjustment_pct(proposed, current_rate)
    if abs(adjustment) > MAX_ADJUSTMENT_PCT:
        raise ApiError("ERR_ADJUSTMENT_EXCEEDS_CAP")

    event = helpers.event_of(mini_bid)
    if event is not None and D(proposed) < D(event["rate_floor_per_mile"]):
        raise ApiError("ERR_RATE_BELOW_FLOOR")

    mini_bid["proposed_rate_per_mile"] = q4(proposed)
    mini_bid["proposed_by_carrier_id"] = carrier_id
    mini_bid["adjustment_pct"] = adjustment
    mini_bid["status"] = "OPEN"
    store.touch(mini_bid)
    return responses.ok(mini_bid)


@bp.post("/freight-procurement/mini-bids/<mini_bid_id>/apply")
@auth.roles_required("ContractAdmin")
def apply_mini_bid(mini_bid_id):
    mini_bid = helpers.get_mini_bid(mini_bid_id)
    payload = v.body()
    expected_version = v.int_field(payload, "expected_contract_version")
    effective_from = v.dt_field(payload, "effective_from")
    effective_to = v.dt_field(payload, "effective_to")
    v.interval(effective_from, effective_to, "effective_from", "effective_to")

    record = helpers.get_rate_record(mini_bid["rate_record_id"])
    contract = store.contracts.get(record["contract_id"])

    # Rung 8 — the version guard of §2.8.
    if contract is None or int(expected_version) != int(contract["version"]):
        raise ApiError("ERR_STALE_CONTRACT_VERSION")

    # Rung 9 — state preconditions.
    if mini_bid["status"] != "OPEN":
        raise ApiError("ERR_MINI_BID_NOT_OPEN")
    if record["status"] not in LIVE_RECORD_STATUSES:
        raise ApiError("ERR_RATE_RECORD_NOT_LIVE")

    # Rung 14 — the replacement interval, under half-open semantics.  The record being
    # superseded leaves the basis in the same operation, so it does not conflict with its
    # own replacement.
    if contract_svc.interval_overlaps(record, effective_from, effective_to):
        raise ApiError("ERR_RATE_INTERVAL_OVERLAP")

    # Rung 17 — both limits are re-checked against the currently stored rate.
    proposed = D(mini_bid["proposed_rate_per_mile"])
    adjustment = _adjustment_pct(proposed, D(record["rate_per_mile"]))
    if abs(adjustment) > MAX_ADJUSTMENT_PCT:
        raise ApiError("ERR_ADJUSTMENT_EXCEEDS_CAP")
    event = helpers.event_of(mini_bid)
    if event is not None and proposed < D(event["rate_floor_per_mile"]):
        raise ApiError("ERR_RATE_BELOW_FLOOR")

    before = D(contract["total_committed_value_usd"] or 0)
    mini_bid["contract_value_before_usd"] = q2(before)

    # Link 1 — the replacement is minted directly in LIVE.
    replacement = store.new_row(
        contract_id=record["contract_id"],
        lane_id=record["lane_id"],
        carrier_id=record["carrier_id"],
        award_allocation_id=record["award_allocation_id"],
        superseded_by_rate_record_id=None,
        routing_position=record["routing_position"],
        rate_per_mile=q4(proposed),
        fuel_surcharge_included=record["fuel_surcharge_included"],
        effective_from=effective_from,
        effective_to=effective_to,
        committed_volume_loads=record["committed_volume_loads"],
        committed_value_usd=Decimal("0.00"),
        status="LIVE",
        tender_count=0,
        rejection_count=0,
        rejection_pct=Decimal("0.00"),
        acceptance_pct=Decimal("100.00"),
        loaded_at=None,
        live_at=store.now_iso(),
    )
    contract_event = helpers.event_of(contract)
    replacement["committed_value_usd"] = contract_svc.record_committed_value(
        replacement, contract_event)
    store.rate_records[replacement["id"]] = replacement

    record["status"] = "SUPERSEDED"
    record["superseded_by_rate_record_id"] = replacement["id"]
    store.touch(record)

    mini_bid["applied_rate_record_id"] = replacement["id"]
    mini_bid["applied_at"] = store.now_iso()

    # Link 2 — the contract amends over the new basis.
    if contract["status"] in ("EXECUTED", "AMENDED"):
        contract["status"] = "AMENDED"
    contract["amendment_count"] = int(contract["amendment_count"]) + 1
    contract_svc.recompute_rate_record_count(contract)
    contract_svc.recompute_committed_value(contract, contract_event)
    store.touch(contract)

    # Link 3 — the portfolio's committed value moved.
    if contract_event is not None:
        lane_svc.recompute_award_cost(contract_event)
        store.touch(contract_event)

    mini_bid["contract_value_after_usd"] = q2(
        D(contract["total_committed_value_usd"] or 0))

    # Applying the mini-bid also resolves a lane that the risk cascade had reopened.
    lane = store.lanes.get(mini_bid["lane_id"])
    allocation = store.allocations.get(record["award_allocation_id"])
    if lane is not None and lane["status"] == "UNDER_REBID":
        if allocation is not None and allocation["status"] == "SUSPENDED_ROUTING":
            allocation["status"] = "ACTIVE"
            store.touch(allocation)
        lane["status"] = "AWARDED"
        lane_svc.recompute_awarded_coverage(lane)
        store.touch(lane)

    mini_bid["status"] = "APPLIED"
    store.touch(mini_bid)
    return responses.ok(mini_bid)


@bp.post("/freight-procurement/mini-bids/<mini_bid_id>/deny")
@auth.roles_required("CategoryManager")
def deny(mini_bid_id):
    mini_bid = helpers.get_mini_bid(mini_bid_id)
    payload = v.body()
    reason = v.string_field(payload, "denial_reason", min_len=1)

    if mini_bid["status"] not in ("REQUESTED", "OPEN"):
        raise ApiError("ERR_MINI_BID_NOT_OPEN")

    # No rate record is created or changed, no contract value moves, and no lane or
    # allocation status changes.
    mini_bid["denial_reason"] = reason
    mini_bid["status"] = "DENIED"
    store.touch(mini_bid)
    return responses.ok(mini_bid)


@bp.post("/freight-procurement/mini-bids/<mini_bid_id>/revert")
@auth.roles_required("ContractAdmin")
def revert(mini_bid_id):
    mini_bid = helpers.get_mini_bid(mini_bid_id)
    payload = v.body()
    reason = v.string_field(payload, "revert_reason", min_len=1)

    if mini_bid["status"] != "APPLIED":
        raise ApiError("ERR_MINI_BID_NOT_APPLIED")

    replacement = store.rate_records.get(mini_bid["applied_rate_record_id"])
    if replacement is None or replacement["status"] != "LIVE":
        raise ApiError("ERR_RATE_RECORD_NOT_LIVE")

    # Link 1 — the exact compensating inverse of the apply.
    replacement["status"] = "ROLLED_BACK"
    store.touch(replacement)

    target = store.rate_records.get(mini_bid["rate_record_id"])
    if target is not None and target["status"] == "SUPERSEDED":
        target["status"] = "LIVE"
        target["superseded_by_rate_record_id"] = None
        store.touch(target)

    # Link 2 — the contract's committed value over the restored basis.
    contract = store.contracts.get(replacement["contract_id"])
    contract_event = helpers.event_of(contract) if contract else None
    if contract is not None:
        contract["amendment_count"] = max(0, int(contract["amendment_count"]) - 1)
        if contract["amendment_count"] == 0 and contract["status"] == "AMENDED":
            contract["status"] = "EXECUTED"
        contract_svc.recompute_rate_record_count(contract)
        contract_svc.recompute_committed_value(contract, contract_event)
        store.touch(contract)

    # Link 3 — the portfolio figures follow the contract.
    if contract_event is not None:
        lane_svc.recompute_award_cost(contract_event)
        store.touch(contract_event)

    mini_bid["revert_reason"] = reason
    mini_bid["reverted_at"] = store.now_iso()
    mini_bid["status"] = "REVERTED"
    store.touch(mini_bid)
    return responses.ok(mini_bid)
