"""Engagement booking, risk assessment, deposits, confirmation, cancellation."""

from flask import Blueprint

import calc
import derive
from envelope import array_response, object_response
from errors import ApiError
from helpers import (
    auth,
    body,
    floor_days,
    opt_bool,
    page,
    query_filter,
    req_dt,
    req_enum,
    req_int,
    req_str,
)
from lookup import (
    find_artist,
    find_client,
    find_engagement,
    find_space,
)
from store import public, stamp, store, touch, touch_time_only

bp = Blueprint("engagements", __name__)

ENGAGEMENT_TYPES = ("PRESENTED", "RENTAL")
OCCUPYING_STATES = ("DRAFT", "CONFIRMED", "PERFORMED", "SETTLED")
PROGRAM_TYPES = ("STUDENT_MATINEE", "MASTERCLASS", "COMMUNITY_WORKSHOP")


def _minutes(dt, minutes):
    from datetime import timedelta

    return dt + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
@bp.post("/engagements")
def create_engagement():
    auth("ProgrammingDirector", "RentalManager")
    data = body()

    # Step 6 - body-referenced resources exist.
    space = None
    if data.get("space_id") is not None:
        space = find_space(data["space_id"])
    artist = None
    if data.get("artist_id") is not None:
        artist = find_artist(data["artist_id"])
    client = None
    if data.get("rental_client_id") is not None:
        client = find_client(data["rental_client_id"])

    # Step 7 - input schema.
    engagement_type = req_enum(data, "engagement_type", ENGAGEMENT_TYPES)
    space_id = req_str(data, "space_id")
    title = req_str(data, "title")
    load_in_raw, load_in_dt = req_dt(data, "load_in_start_utc")
    perf_start_raw, perf_start_dt = req_dt(data, "performance_start_utc")
    perf_end_raw, perf_end_dt = req_dt(data, "performance_end_utc")
    load_out_raw, load_out_dt = req_dt(data, "load_out_end_utc")
    if not (load_in_dt <= perf_start_dt <= perf_end_dt <= load_out_dt):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "The engagement's four instants must be in non-decreasing order.",
        )
    performance_day_count = req_int(data, "performance_day_count", minimum=1)
    load_in_day_count = req_int(data, "load_in_day_count", minimum=0)

    # Step 10 - engagement-type agreement.
    if engagement_type == "PRESENTED":
        if artist is None or client is not None:
            raise ApiError(
                "ERR_ENGAGEMENT_TYPE_MISMATCH",
                "A PRESENTED engagement requires artist_id and forbids rental_client_id.",
            )
    else:
        if client is None or artist is not None:
            raise ApiError(
                "ERR_ENGAGEMENT_TYPE_MISMATCH",
                "A RENTAL engagement requires rental_client_id and forbids artist_id.",
            )

    # Step 11 - hall online.
    if space["status"] != "ACTIVE":
        raise ApiError("ERR_SPACE_OFFLINE")

    # Step 12 - hall occupancy.
    buffer_minutes = space["changeover_buffer_minutes"]
    new_end = _minutes(load_out_dt, buffer_minutes)
    for other in store.engagements.values():
        if other["space_id"] != space["id"]:
            continue
        if other["lifecycle_status"] not in OCCUPYING_STATES:
            continue
        other_end = _minutes(other["_load_out_end"], buffer_minutes)
        if load_in_dt < other_end and other["_load_in_start"] < new_end:
            raise ApiError("ERR_SPACE_OCCUPANCY_CONFLICT")

    # Step 13 - artist routing.
    if engagement_type == "PRESENTED":
        if perf_start_dt < artist["_routing_start"] or perf_end_dt > artist["_routing_end"]:
            raise ApiError("ERR_ROUTING_WINDOW_VIOLATION")
        min_days = artist["min_days_between_engagements"]
        for other in store.engagements.values():
            if other["artist_id"] != artist["id"]:
                continue
            if other["lifecycle_status"] == "CANCELLED":
                continue
            if perf_start_dt >= other["_performance_end"]:
                gap = floor_days(perf_start_dt, other["_performance_end"])
            elif other["_performance_start"] >= perf_end_dt:
                gap = floor_days(other["_performance_start"], perf_end_dt)
            else:
                gap = 0
            if gap < min_days:
                raise ApiError("ERR_ROUTING_WINDOW_VIOLATION")

    record = {
        "engagement_type": engagement_type,
        "space_id": space_id,
        "artist_id": artist["id"] if artist is not None else None,
        "rental_client_id": client["id"] if client is not None else None,
        "title": title,
        "load_in_start_utc": load_in_raw,
        "performance_start_utc": perf_start_raw,
        "performance_end_utc": perf_end_raw,
        "load_out_end_utc": load_out_raw,
        "performance_day_count": performance_day_count,
        "load_in_day_count": load_in_day_count,
        "lifecycle_status": "DRAFT",
        "financial_clearance": "UNASSESSED",
        "ticketing_status": "TICKETING_UNSET",
        "negotiated_fee_cents": 0,
        "artist_share_pct": 0,
        "facility_fee_cents": 0,
        "labor_estimate_total_cents": 0,
        "additional_equipment_cost_cents": 0,
        "deposit_required_cents": 0,
        "deposit_paid_cents": 0,
        "risk_score": 0,
        "risk_tier": "LOW",
        "projected_gross_cents": 0,
        "projected_margin_cents": 0,
        "realized_gross_cents": 0,
        "realized_margin_cents": 0,
        "negotiation_round_count": 0,
        "fee_accepted_by_user_id": None,
        "cancellation_fee_cents": 0,
        "_load_in_start": load_in_dt,
        "_performance_start": perf_start_dt,
        "_performance_end": perf_end_dt,
        "_load_out_end": load_out_dt,
    }
    if engagement_type == "RENTAL":
        record["facility_fee_cents"] = calc.facility_fee(
            space, performance_day_count, load_in_day_count, client["is_nonprofit"]
        )
        record["deposit_required_cents"] = calc.deposit_requirement(record, client)
    stamp(record)
    store.engagements[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/engagements/<engagement_id>")
def read_engagement(engagement_id):
    auth(
        "ProgrammingDirector",
        "RentalManager",
        "ArtistRepresentative",
        "RentalClientContact",
        "TechnicalDirector",
        "BoxOfficeManager",
        "FinanceController",
        "CenterAdmin",
    )
    return object_response(public(find_engagement(engagement_id)))


@bp.get("/engagements")
def list_engagements():
    auth(
        "ProgrammingDirector",
        "RentalManager",
        "FinanceController",
        "BoxOfficeManager",
        "CenterAdmin",
    )
    items = list(store.engagements.values())
    for field in ("space_id", "artist_id", "rental_client_id", "lifecycle_status"):
        value = query_filter(field)
        if value is not None:
            items = [e for e in items if e[field] == value]
    from store import ordered

    window, meta = page(ordered(items))
    return array_response([public(e) for e in window], meta)


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------
@bp.post("/engagements/<engagement_id>/assess-risk")
def assess_risk(engagement_id):
    auth("FinanceController")
    engagement = find_engagement(engagement_id)
    data = body()
    expected_version = req_int(data, "expected_engagement_version")
    override = opt_bool(data, "override_escalation", None)

    if engagement["lifecycle_status"] not in ("DRAFT", "CONFIRMED"):
        raise ApiError(
            "ERR_ENGAGEMENT_NOT_DRAFT",
            "Risk assessment requires a DRAFT or CONFIRMED engagement.",
        )
    if expected_version != engagement["version"]:
        raise ApiError("ERR_STALE_ENGAGEMENT_VERSION")

    gross, _margin = derive.recompute_projection(engagement)
    basis = derive.fee_basis_cents(engagement)
    lead_days = floor_days(engagement["_performance_start"], store.clock_dt)

    if engagement["engagement_type"] == "PRESENTED":
        artist = store.artists.get(engagement["artist_id"])
        slack_start = floor_days(engagement["_performance_start"], artist["_routing_start"])
        slack_end = floor_days(artist["_routing_end"], engagement["_performance_end"])
        routing_slack = min(slack_start, slack_end)
        score = calc.presented_risk_score(
            basis,
            gross,
            routing_slack,
            lead_days,
            artist["historical_sell_through_pct"],
        )
    else:
        client = store.clients.get(engagement["rental_client_id"])
        score = calc.rental_risk_score(
            client["credit_rating"],
            client["outstanding_balance_cents"],
            engagement["deposit_required_cents"],
            lead_days,
        )

    tier = calc.risk_band(score)
    engagement["risk_score"] = score
    engagement["risk_tier"] = tier
    engagement["financial_clearance"] = calc.resolve_clearance(
        tier, override, engagement["financial_clearance"]
    )
    touch(engagement)
    return object_response(public(engagement))


# ---------------------------------------------------------------------------
# Deposits
# ---------------------------------------------------------------------------
@bp.post("/engagements/<engagement_id>/record-deposit")
def record_deposit(engagement_id):
    user_id, role = auth("RentalManager", "RentalClientContact")
    engagement = find_engagement(engagement_id)
    if role == "RentalClientContact" and user_id != engagement["rental_client_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    data = body()
    amount_cents = req_int(data, "amount_cents", minimum=0)
    if engagement["engagement_type"] != "RENTAL":
        raise ApiError(
            "ERR_ENGAGEMENT_TYPE_MISMATCH",
            "Deposits apply to RENTAL engagements only.",
        )
    engagement["deposit_paid_cents"] += amount_cents
    touch(engagement)
    return object_response(public(engagement))


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------
@bp.post("/engagements/<engagement_id>/confirm")
def confirm_engagement(engagement_id):
    auth("ProgrammingDirector", "RentalManager")
    engagement = find_engagement(engagement_id)

    if engagement["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_ENGAGEMENT_NOT_DRAFT")
    riders = derive.engagement_riders(engagement["id"])
    if not any(r["review_status"] == "CLEARED" for r in riders):
        raise ApiError(
            "ERR_RIDER_INVALID_STATE",
            "Confirmation requires a CLEARED technical rider.",
        )
    if engagement["engagement_type"] == "PRESENTED":
        rounds = derive.engagement_negotiations(engagement["id"])
        if not any(r["status"] == "ACCEPTED" for r in rounds):
            raise ApiError(
                "ERR_NEGOTIATION_NOT_OPEN",
                "Confirmation requires an ACCEPTED fee negotiation round.",
            )
    space = store.spaces.get(engagement["space_id"])
    if space is not None and space["status"] != "ACTIVE":
        raise ApiError("ERR_SPACE_OFFLINE")
    clearance = engagement["financial_clearance"]
    if clearance == "BLOCKED":
        raise ApiError("ERR_CLEARANCE_BLOCKED")
    if clearance not in ("CLEARED", "ESCALATED_APPROVED"):
        raise ApiError("ERR_CLEARANCE_REQUIRED")
    if engagement["engagement_type"] == "RENTAL":
        if engagement["deposit_paid_cents"] < engagement["deposit_required_cents"]:
            raise ApiError("ERR_DEPOSIT_SHORTFALL")

    engagement["lifecycle_status"] = "CONFIRMED"
    if engagement["ticketing_status"] == "TICKETING_UNSET":
        engagement["ticketing_status"] = "TIERS_DRAFT"
    touch(engagement)
    return object_response(public(engagement))


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------
@bp.post("/engagements/<engagement_id>/cancel")
def cancel_engagement(engagement_id):
    auth("ProgrammingDirector", "RentalManager")
    engagement = find_engagement(engagement_id)
    data = body()
    req_str(data, "reason")
    opt_bool(data, "cancelled_by_client", None)
    if engagement["lifecycle_status"] not in ("DRAFT", "CONFIRMED"):
        raise ApiError("ERR_ENGAGEMENT_NOT_DRAFT")

    from_confirmed = engagement["lifecycle_status"] == "CONFIRMED"

    # 1 - retained fee.
    if from_confirmed:
        days = floor_days(engagement["_performance_start"], store.clock_dt)
        engagement["cancellation_fee_cents"] = calc.cancellation_fee(
            days, engagement["facility_fee_cents"], engagement["negotiated_fee_cents"]
        )
    else:
        engagement["cancellation_fee_cents"] = 0

    # 2 - ESTIMATED labor calls cancelled.
    for call in derive.engagement_calls(engagement["id"]):
        if call["status"] == "ESTIMATED":
            call["status"] = "CANCELLED"
            touch(call)

    # 3 - RESERVED equipment lines released; item counters re-derived.
    affected_items = []
    for line in derive.engagement_lines(engagement["id"]):
        if line["status"] == "RESERVED":
            line["status"] = "RELEASED"
            touch(line)
            affected_items.append(line["equipment_item_id"])
    for item_id in dict.fromkeys(affected_items):
        item = store.equipment.get(item_id)
        if item is not None:
            derive.recompute_item_reserved(item)

    # 4 - rider and engagement equipment cost re-derived.
    for rider in derive.engagement_riders(engagement["id"]):
        derive.recompute_rider_equipment(rider)
    derive.recompute_engagement_equipment(engagement)

    # 5 - labor estimate re-derived.
    derive.recompute_labor_estimate(engagement)

    # 6 - deposit requirement recomputed exactly once.
    derive.recompute_deposit(engagement)

    # 7 - confirmed path only: refund single ticket sales.
    if from_confirmed:
        touched_tiers = []
        for sale in derive.engagement_sales(engagement["id"]):
            if sale["status"] == "SOLD":
                sale["status"] = "REFUNDED"
                touch(sale)
                touched_tiers.append(sale["price_tier_id"])
        for tier_id in dict.fromkeys(touched_tiers):
            tier = store.tiers.get(tier_id)
            if tier is not None:
                derive.recompute_tier_counters(tier)
        derive.recompute_realized_gross(engagement)

    # 8 - funded education programs cancelled with subsidy refunds.
    for program in derive.engagement_programs(engagement["id"]):
        if program["status"] == "FUNDED":
            program["status"] = "CANCELLED_WITH_ENGAGEMENT"
            touch(program)
            derive.append_ledger(
                "EDUCATION_SUBSIDY_REFUND",
                program["subsidy_approved_cents"],
                "Education subsidy refunded on engagement cancellation.",
                engagement["id"],
            )

    # 9 - confirmed path only: rental client billed the retained fee net of deposit.
    if from_confirmed and engagement["engagement_type"] == "RENTAL":
        client = store.clients.get(engagement["rental_client_id"])
        if client is not None:
            client["outstanding_balance_cents"] += (
                engagement["cancellation_fee_cents"] - engagement["deposit_paid_cents"]
            )
            touch(client)

    # 10 - ticketing closed and ACTIVE tiers closed.
    engagement["ticketing_status"] = "CLOSED"
    for tier in derive.engagement_tiers(engagement["id"]):
        if tier["status"] == "ACTIVE":
            derive.apply_changes(tier, {"status": "CLOSED"})

    # 11 - terminal booking state and version increment.
    engagement["lifecycle_status"] = "CANCELLED"
    touch(engagement)
    return object_response(public(engagement))


# ---------------------------------------------------------------------------
# Box-office statement
# ---------------------------------------------------------------------------
@bp.get("/engagements/<engagement_id>/box-office-statement")
def box_office_statement(engagement_id):
    auth("BoxOfficeManager", "FinanceController")
    engagement = find_engagement(engagement_id)
    tiers = derive.engagement_tiers(engagement["id"])
    single_gross = sum(t["gross_cents"] for t in tiers)
    subscription_revenue = sum(t["subscription_revenue_cents"] for t in tiers)
    box_office_gross = single_gross + subscription_revenue
    restoration = 0
    for sale in derive.engagement_sales(engagement["id"]):
        if sale["status"] == "SOLD":
            restoration += sale["restoration_fee_cents"]
    return object_response(
        {
            "engagement_id": engagement["id"],
            "tier_count": len(tiers),
            "seats_allocated_total": sum(t["seats_allocated"] for t in tiers),
            "sold_qty_total": sum(t["sold_qty"] for t in tiers),
            "subscription_held_qty_total": sum(t["subscription_held_qty"] for t in tiers),
            "single_ticket_gross_cents": single_gross,
            "subscription_revenue_cents": subscription_revenue,
            "restoration_fees_cents": restoration,
            "box_office_gross_cents": box_office_gross,
            "adjusted_gross_cents": box_office_gross - restoration,
        }
    )


# ---------------------------------------------------------------------------
# Education programs
# ---------------------------------------------------------------------------
@bp.post("/engagements/<engagement_id>/education-programs")
def create_education_program(engagement_id):
    auth("ProgrammingDirector")
    engagement = find_engagement(engagement_id)
    data = body()
    program_type = req_enum(data, "program_type", PROGRAM_TYPES)
    participant_capacity = req_int(data, "participant_capacity", minimum=1)
    subsidy_requested = req_int(data, "subsidy_requested_cents", minimum=1)

    if engagement["engagement_type"] != "PRESENTED":
        raise ApiError(
            "ERR_ENGAGEMENT_TYPE_MISMATCH",
            "Education programs belong to PRESENTED engagements only.",
        )

    approved = calc.education_subsidy(program_type, participant_capacity, subsidy_requested)
    balance_before = derive.reserve_balance()
    if balance_before - approved < calc.EDUCATION_RESERVE_FLOOR_CENTS:
        raise ApiError("ERR_RESERVE_INSUFFICIENT")

    record = {
        "engagement_id": engagement["id"],
        "program_type": program_type,
        "participant_capacity": participant_capacity,
        "subsidy_requested_cents": subsidy_requested,
        "subsidy_approved_cents": approved,
        "status": "FUNDED",
    }
    stamp(record)
    store.programs[record["id"]] = record
    derive.append_ledger(
        "EDUCATION_SUBSIDY_DRAW",
        -approved,
        "Education subsidy drawn for program %s." % record["id"],
        engagement["id"],
    )
    return object_response(public(record), 201)


@bp.get("/engagements/<engagement_id>/education-programs")
def list_education_programs(engagement_id):
    auth("ProgrammingDirector", "FinanceController", "CenterAdmin")
    engagement = find_engagement(engagement_id)
    items = derive.engagement_programs(engagement["id"])
    status = query_filter("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, meta = page(items)
    return array_response([public(p) for p in window], meta)
