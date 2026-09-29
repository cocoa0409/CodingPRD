"""Bid events: creation, the lane package, the lane-scope lock, invitations, rounds and
the award commit — PRD §3.3, §3.4 and §3.7."""
import re
from decimal import Decimal

from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError, bad_request
from numeric import D, q2
from services import bidding, contracts as contract_svc, lanes as lane_svc

bp = Blueprint("events", __name__)

COST_BASES = ("FORECAST", "HISTORICAL")
EQUIPMENT_TYPES = ("DRY_VAN", "REEFER", "FLATBED")
INCUMBENT_VISIBILITIES = ("HIDDEN", "RANK_ONLY", "FULL")
ZIP3_PATTERN = re.compile(r"^\d{3}$")

DEFAULT_FUEL_INDEX_PER_MILE = Decimal("0.4500")
DEFAULT_ACCESSORIAL_INFLATION_FACTOR = Decimal("1.15")
DEFAULT_ROUNDS_ALLOWED = 2
DEFAULT_DIVERSITY_MIN_PCT = Decimal("10.00")
DEFAULT_MAX_AWARD_SHARE_PCT = Decimal("60.00")
DEFAULT_MAX_CARRIERS_PER_LANE = 3
DEFAULT_SEASONALITY_PEAK_INDEX = Decimal("1.00")


@bp.post("/freight-procurement/bid-events")
@auth.roles_required("ProcurementAnalyst")
def create_event():
    payload = v.body()
    name = v.string_field(payload, "name", min_len=1, max_len=120)
    cost_basis = v.enum_field(payload, "cost_basis", COST_BASES)
    fuel = v.dec_field(payload, "fuel_index_per_mile", required=False,
                       default=DEFAULT_FUEL_INDEX_PER_MILE)
    inflation = v.dec_field(payload, "accessorial_inflation_factor", required=False,
                           default=DEFAULT_ACCESSORIAL_INFLATION_FACTOR,
                           minimum=Decimal("1.00"), maximum=Decimal("2.00"))
    rate_floor = v.dec_field(payload, "rate_floor_per_mile", exclusive_min=True)
    rounds_allowed = v.int_field(payload, "rounds_allowed", required=False,
                                 default=DEFAULT_ROUNDS_ALLOWED, minimum=1, maximum=4)
    cost_weight = v.dec_field(payload, "cost_weight", maximum=Decimal("1.00"))
    service_weight = v.dec_field(payload, "service_weight", maximum=Decimal("1.00"))
    capacity_weight = v.dec_field(payload, "capacity_weight", maximum=Decimal("1.00"))
    diversity_weight = v.dec_field(payload, "diversity_weight", maximum=Decimal("1.00"))
    diversity_min = v.dec_field(payload, "diversity_min_pct", required=False,
                                default=DEFAULT_DIVERSITY_MIN_PCT)
    max_share = v.dec_field(payload, "max_award_share_pct", required=False,
                            default=DEFAULT_MAX_AWARD_SHARE_PCT)
    max_carriers = v.int_field(payload, "max_carriers_per_lane", required=False,
                               default=DEFAULT_MAX_CARRIERS_PER_LANE, minimum=1,
                               maximum=3)
    effective_from = v.dt_field(payload, "contract_effective_from")
    effective_to = v.dt_field(payload, "contract_effective_to")
    v.interval(effective_from, effective_to, "contract_effective_from",
               "contract_effective_to")

    if (cost_weight + service_weight + capacity_weight + diversity_weight
            != Decimal("1.00")):
        raise bad_request("The four objective weights must sum to exactly 1.00.")

    event = store.new_row(
        name=name,
        cost_basis=cost_basis,
        fuel_index_per_mile=fuel,
        accessorial_inflation_factor=inflation,
        rate_floor_per_mile=rate_floor,
        rounds_allowed=rounds_allowed,
        current_round_no=0,
        cost_weight=cost_weight,
        service_weight=service_weight,
        capacity_weight=capacity_weight,
        diversity_weight=diversity_weight,
        diversity_min_pct=diversity_min,
        max_award_share_pct=max_share,
        max_carriers_per_lane=max_carriers,
        contract_effective_from=effective_from,
        contract_effective_to=effective_to,
        status="DRAFT",
        lane_count=0,
        invited_carrier_count=0,
        accepted_invitation_count=0,
        total_scope_volume_loads=0,
        baseline_cost_usd=None,
        award_cost_usd=None,
        savings_pct=None,
        coverage_pct=Decimal("0.00"),
        diversity_pct=Decimal("0.00"),
        awarded_at=None,
    )
    store.events[event["id"]] = event
    return responses.created(event)


@bp.get("/freight-procurement/bid-events/<event_id>")
@auth.roles_required("ProcurementAnalyst", "ComplianceOfficer", "CategoryManager",
                     "ContractAdmin")
def get_event(event_id):
    return responses.ok(helpers.get_event(event_id))


@bp.post("/freight-procurement/bid-events/<event_id>/lanes")
@auth.roles_required("ProcurementAnalyst")
def create_lane(event_id):
    event = helpers.get_event(event_id)
    payload = v.body()
    lane_code = v.string_field(payload, "lane_code", min_len=1, max_len=32)
    origin = v.string_field(payload, "origin_zip3", min_len=3, max_len=3,
                            pattern=ZIP3_PATTERN)
    dest = v.string_field(payload, "dest_zip3", min_len=3, max_len=3,
                          pattern=ZIP3_PATTERN)
    equipment = v.enum_field(payload, "equipment_type", EQUIPMENT_TYPES)
    mileage = v.int_field(payload, "mileage", minimum=1)
    annual = v.int_field(payload, "annual_volume_loads", minimum=1)
    service_days = v.int_field(payload, "service_days_required", minimum=1)
    accessorial = v.dec_field(payload, "accessorial_history_usd_per_load")
    trailing = v.int_field(payload, "trailing_12m_actual_loads", required=False,
                           default=None, minimum=0)
    seasonality = v.dec_field(payload, "seasonality_peak_index", required=False,
                              default=DEFAULT_SEASONALITY_PEAK_INDEX,
                              minimum=Decimal("1.00"), maximum=Decimal("2.00"))
    incumbent_carrier_id = v.id_field(payload, "incumbent_carrier_id", required=False,
                                      default=None)
    incumbent_rate = v.dec_field(payload, "incumbent_rate_per_mile", required=False,
                                 default=None, exclusive_min=True)

    if incumbent_carrier_id is not None:
        helpers.get_carrier(incumbent_carrier_id)
    if event["status"] != "DRAFT":
        raise ApiError("ERR_LANE_NOT_VALIDATED",
                       "The lane scope of this event is no longer open for changes.")
    for other in store.lanes.values():
        if other["bid_event_id"] == event["id"] and other["lane_code"] == lane_code:
            raise ApiError("ERR_DUPLICATE_LANE_CODE")

    lane = store.new_row(
        bid_event_id=event["id"],
        lane_code=lane_code,
        origin_zip3=origin,
        dest_zip3=dest,
        equipment_type=equipment,
        mileage=mileage,
        annual_volume_loads=annual,
        trailing_12m_actual_loads=trailing,
        seasonality_peak_index=seasonality,
        accessorial_history_usd_per_load=q2(accessorial),
        incumbent_carrier_id=incumbent_carrier_id,
        incumbent_rate_per_mile=incumbent_rate,
        service_days_required=service_days,
        status="DRAFT",
        data_quality_flags=[],
        unallocated_volume_loads=annual,
        awarded_coverage_pct=Decimal("0.00"),
        baseline_cost_usd=None,
        validated_at=None,
    )
    lane_svc.refresh_flags(lane)
    store.lanes[lane["id"]] = lane

    lane_svc.recompute_lane_count(event)
    store.touch(event)
    return responses.created(lane)


@bp.post("/freight-procurement/bid-events/<event_id>/lock-lanes")
@auth.roles_required("ProcurementAnalyst")
def lock_lanes(event_id):
    event = helpers.get_event(event_id)
    v.body()

    lanes = lane_svc.event_lanes(event["id"])
    if event["status"] != "DRAFT" or not lanes:
        raise ApiError("ERR_LANE_NOT_VALIDATED")
    if any(lane["status"] != "VALIDATED" for lane in lanes):
        raise ApiError("ERR_LANE_NOT_VALIDATED")
    for lane in lanes:
        lane_svc.refresh_flags(lane)
        if lane_svc.has_blocking_flag(lane):
            raise ApiError("ERR_LANE_DATA_QUALITY_BLOCKED")

    for lane in lanes:
        lane["status"] = "LOCKED"
        lane["baseline_cost_usd"] = lane_svc.baseline_cost(lane)
        store.touch(lane)

    lane_svc.recompute_scope(event)
    event["status"] = "LANES_LOCKED"
    store.touch(event)
    return responses.ok(event)


@bp.post("/freight-procurement/bid-events/<event_id>/invitations")
@auth.roles_required("ProcurementAnalyst")
def create_invitation(event_id):
    event = helpers.get_event(event_id)
    payload = v.body()
    carrier_id = v.id_field(payload, "carrier_id")
    nda_required = v.bool_field(payload, "nda_required", required=False, default=True)

    carrier = helpers.get_carrier(carrier_id)
    if event["status"] == "DRAFT":
        raise ApiError("ERR_LANES_NOT_LOCKED")
    helpers.check_fitness(carrier)
    for other in store.invitations.values():
        if (other["bid_event_id"] == event["id"]
                and other["carrier_id"] == carrier["id"]
                and other["status"] != "REVOKED"):
            raise ApiError("ERR_DUPLICATE_INVITATION")

    invitation = store.new_row(
        bid_event_id=event["id"],
        carrier_id=carrier["id"],
        status="SENT",
        nda_required=nda_required,
        nda_signed=False,
        qualification_snapshot_score=carrier["composite_score"],
        qualification_snapshot_carrier_version=carrier["version"],
        snapshot_stale=False,
        decline_reason=None,
        responded_at=None,
        revoked_reason=None,
    )
    store.invitations[invitation["id"]] = invitation

    _recount_invitations(event)
    if event["status"] == "LANES_LOCKED":
        event["status"] = "INVITING"
    store.touch(event)
    return responses.created(invitation)


def _recount_invitations(event):
    """PRD §2.12 — both counters read status sets rather than running increments."""
    invitations = [i for i in store.invitations.values()
                   if i["bid_event_id"] == event["id"]]
    event["invited_carrier_count"] = sum(
        1 for i in invitations if i["status"] in ("SENT", "ACCEPTED", "DECLINED"))
    event["accepted_invitation_count"] = sum(
        1 for i in invitations if i["status"] == "ACCEPTED")


@bp.post("/freight-procurement/bid-events/<event_id>/bid-rounds")
@auth.roles_required("ProcurementAnalyst")
def open_round(event_id):
    event = helpers.get_event(event_id)
    payload = v.body()
    visibility = v.enum_field(payload, "incumbent_visibility", INCUMBENT_VISIBILITIES)
    closes_at = v.dt_field(payload, "closes_at")
    target = v.dec_field(payload, "target_reduction_pct", required=False,
                         default=Decimal("0.00"), maximum=Decimal("50.00"))

    status = event["status"]
    if status == "DRAFT":
        raise ApiError("ERR_LANES_NOT_LOCKED")
    if status == "ROUND_OPEN":
        raise ApiError("ERR_ROUND_STILL_OPEN")
    if status not in ("LANES_LOCKED", "INVITING", "ROUND_CLOSED"):
        raise ApiError("ERR_ROUND_LIMIT_EXCEEDED")
    if status in ("LANES_LOCKED", "INVITING") and event["accepted_invitation_count"] < 1:
        raise ApiError("ERR_INVITATION_NOT_ACCEPTED",
                       "There is no point opening a round nobody can bid into.")
    if event["current_round_no"] >= event["rounds_allowed"]:
        raise ApiError("ERR_ROUND_LIMIT_EXCEEDED")

    round_row = store.new_row(
        bid_event_id=event["id"],
        round_no=event["current_round_no"] + 1,
        status="OPEN",
        incumbent_visibility=visibility,
        target_reduction_pct=target,
        opens_at=store.now_iso(),
        closes_at=closes_at,
        submitted_bid_count=0,
        lowest_rate_per_mile=None,
        closed_at=None,
    )
    store.rounds[round_row["id"]] = round_row

    event["current_round_no"] += 1
    event["status"] = "ROUND_OPEN"
    store.touch(event)
    return responses.created(round_row)


@bp.get("/freight-procurement/bid-events/<event_id>/bid-rounds")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "CarrierRep")
def list_rounds(event_id):
    event = helpers.get_event(event_id)
    rows = [r for r in store.rounds.values() if r["bid_event_id"] == event["id"]]
    rows.sort(key=lambda r: (r["round_no"], r["_seq"]))
    return responses.listing(rows)


@bp.get("/freight-procurement/bid-events/<event_id>/optimization-runs")
@auth.roles_required("ProcurementAnalyst", "CategoryManager")
def list_runs(event_id):
    event = helpers.get_event(event_id)
    rows = store.sorted_rows([r for r in store.runs.values()
                              if r["bid_event_id"] == event["id"]])
    return responses.listing(rows)


@bp.post("/freight-procurement/bid-events/<event_id>/award")
@auth.roles_required("CategoryManager")
def commit_award(event_id):
    event = helpers.get_event(event_id)
    v.body()

    if event["status"] != "AWARDING":
        raise ApiError("ERR_EVENT_NOT_OPTIMIZING")
    published = None
    for run in store.sorted_rows(store.runs.values()):
        if run["bid_event_id"] == event["id"] and run["status"] == "PUBLISHED":
            published = run
    if published is None:
        raise ApiError("ERR_EVENT_NOT_OPTIMIZING")

    run_allocations = [a for a in store.sorted_rows(store.allocations.values())
                       if a["optimization_run_id"] == published["id"]]
    if any(a["status"] == "PROPOSED" for a in run_allocations):
        raise ApiError("ERR_ALLOCATION_NOT_PROPOSED")

    approved = [a for a in run_allocations if a["status"] == "APPROVED"]
    for allocation in approved:
        if D(allocation["allocated_pct"]) > D(event["max_award_share_pct"]):
            raise ApiError("ERR_AWARD_SHARE_EXCEEDED")
    if D(event["diversity_pct"]) < D(event["diversity_min_pct"]):
        raise ApiError("ERR_DIVERSITY_MINIMUM_NOT_MET")
    if D(event["coverage_pct"]) < D(published["min_capacity_coverage_pct"]):
        raise ApiError("ERR_COVERAGE_BELOW_MINIMUM")

    # Link 1 (status and stamp; the cost figures are rolled up once link 4 has run).
    event["status"] = "AWARDED"
    event["awarded_at"] = store.now_iso()

    # Link 2 — allocations execute and their bids record the seat they won.
    pairings = []
    for allocation in approved:
        allocation["status"] = "EXECUTED"
        store.touch(allocation)
        bid = store.lane_bids.get(allocation["lane_bid_id"])
        if bid is not None and bid["status"] == "SHORTLISTED":
            bid["status"] = ("AWARDED_PRIMARY"
                             if allocation["routing_position"] == "PRIMARY"
                             else "AWARDED_BACKUP")
            store.touch(bid)
        pair = (event["id"], allocation["carrier_id"])
        if pair not in pairings:
            pairings.append(pair)

    # Link 3 — every lane holding an executed allocation is awarded.
    for allocation in approved:
        lane = store.lanes.get(allocation["lane_id"])
        if lane is None:
            continue
        if lane["status"] == "LOCKED":
            lane["status"] = "AWARDED"
        lane_svc.recompute_awarded_coverage(lane)
        store.touch(lane)

    # Link 4 — one contract per distinct pairing of event and carrier.
    for _, carrier_id in pairings:
        contract = store.new_row(
            bid_event_id=event["id"],
            carrier_id=carrier_id,
            status="DRAFT",
            signature_status="PENDING_BOTH",
            rate_load_status="NOT_STAGED",
            effective_from=event["contract_effective_from"],
            effective_to=event["contract_effective_to"],
            carrier_signed_by_user_id=None,
            carrier_signed_at=None,
            shipper_signed_by_user_id=None,
            shipper_signed_at=None,
            base_committed_value_usd=Decimal("0.00"),
            volume_discount_pct=Decimal("0.000"),
            volume_discount_usd=Decimal("0.00"),
            accessorial_allowance_pct=Decimal("0.000"),
            accessorial_allowance_usd=Decimal("0.00"),
            total_committed_value_usd=Decimal("0.00"),
            amendment_count=0,
            rate_record_count=0,
        )
        store.contracts[contract["id"]] = contract
        contract_svc.recompute_committed_value(contract, event)

    # Link 5 — the carriers now holding contracts re-derive their commitment rollups.
    for _, carrier_id in pairings:
        carrier = store.carriers.get(carrier_id)
        if carrier is not None:
            contract_svc.recompute_carrier_commitments(carrier)
            store.touch(carrier)

    lane_svc.recompute_award_cost(event)
    store.touch(event)
    return responses.ok(event)
