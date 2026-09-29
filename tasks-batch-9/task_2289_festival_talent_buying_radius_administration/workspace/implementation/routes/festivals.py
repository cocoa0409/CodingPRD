"""Festival, budget tier and stage routes."""

from flask import Blueprint

from db import apply_changes, db, new_row, public, public_list, touch
from errors import fail
from middleware import endpoint
from response import paginate, respond_array, respond_object
from services import calc, derive
from validators import (
    body,
    check_version,
    date_str,
    load,
    opt_bool,
    opt_enum,
    opt_int,
    opt_number,
    pagination,
    query_bool,
    query_enum,
    req_date,
    req_enum,
    req_int,
    req_number,
    req_string,
    body_fk,
)

bp = Blueprint("festivals", __name__)

TIER_CODES = ("HEADLINER", "DIRECT_SUPPORT", "MID_CARD", "EMERGING")
GENRES = ("ELECTRONIC", "HIP_HOP", "ROCK", "POP", "LATIN", "JAZZ_SOUL", "COUNTRY")
GENRE_FOCUS = GENRES + ("MIXED",)


# --------------------------------------------------------------------------- #
# Festival
# --------------------------------------------------------------------------- #
@bp.post("/festivals")
@endpoint(["TalentBuyer"])
def create_festival():
    payload = body()
    name = req_string(payload, "name", 1, 120)
    edition_year = req_int(payload, "edition_year", 2020, 2100)
    market_latitude = req_number(payload, "market_latitude", -90.0, 90.0)
    market_longitude = req_number(payload, "market_longitude", -180.0, 180.0)
    event_start_date = req_date(payload, "event_start_date")
    event_end_date = req_date(payload, "event_end_date")
    talent_budget_cents = req_int(payload, "talent_budget_cents", 100000, None)
    contingency_reserve_pct = opt_number(
        payload, "contingency_reserve_pct", 0.05, 0.00, 0.25
    )
    if event_start_date > event_end_date:
        fail("ERR_INVALID_REQUEST", "event_start_date may not fall after event_end_date")

    row = new_row(
        name=name,
        edition_year=edition_year,
        market_latitude=market_latitude,
        market_longitude=market_longitude,
        event_start_date=date_str(event_start_date),
        event_end_date=date_str(event_end_date),
        talent_budget_cents=talent_budget_cents,
        contingency_reserve_pct=contingency_reserve_pct,
        allocatable_budget_cents=calc.allocatable_from_budget(
            talent_budget_cents, contingency_reserve_pct
        ),
        committed_budget_cents=0,
        tiers_allocated=False,
        announcement_phase="PRESALE",
        lineup_posture="OPEN",
        headliner_anchor_count=0,
    )
    db.festivals[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/festivals/<festival_id>")
@endpoint(["TalentBuyer", "BusinessAffairs", "ProductionManager", "FinanceController"])
def get_festival(festival_id):
    return respond_object(public(load("festivals", festival_id)))


@bp.post("/festivals/<festival_id>/allocate-tiers")
@endpoint(["TalentBuyer"])
def allocate_tiers(festival_id):
    payload = body()
    req_int(payload, "expected_festival_version")
    festival = load("festivals", festival_id)
    check_version(
        payload, "expected_festival_version", festival, "ERR_STALE_FESTIVAL_VERSION"
    )

    tiers = calc.waterfall_order(festival_id)
    if not calc.allocation_pct_closes(tiers):
        fail("ERR_ALLOCATION_PCT_INVALID", "allocation_pct values must close to 1.00")
    if festival["committed_budget_cents"] != 0:
        fail("ERR_ALLOCATION_LOCKED", "the edition already carries commitments")

    figures = calc.run_waterfall(festival, tiers)
    for tier, allocation in zip(tiers, figures):
        tier["allocation_cents"] = allocation
        derive.recompute_tier(tier)
        touch(tier)
    festival["tiers_allocated"] = True
    derive.recompute_festival(festival)
    touch(festival)
    return respond_array(public_list(tiers))


@bp.post("/festivals/<festival_id>/advance-phase")
@endpoint(["TalentBuyer"])
def advance_phase(festival_id):
    payload = body()
    target_phase = req_enum(payload, "target_phase", calc.PHASE_LADDER)
    festival = load("festivals", festival_id)

    current = festival["announcement_phase"]
    index = calc.PHASE_LADDER.index(current)
    successor = (
        calc.PHASE_LADDER[index + 1] if index + 1 < len(calc.PHASE_LADDER) else None
    )
    if successor is None or target_phase != successor:
        fail("ERR_PHASE_PREREQ_UNMET", "target_phase must be the immediate successor")
    waves = [
        w
        for w in db.announcement_waves.values()
        if w["festival_id"] == festival_id and w["phase"] == current
    ]
    if not waves or any(w["status"] != "PUBLISHED" for w in waves):
        fail(
            "ERR_PHASE_PREREQ_UNMET",
            "every announcement wave of the phase being left must be PUBLISHED",
        )

    festival["announcement_phase"] = target_phase
    derive.recompute_festival(festival)
    touch(festival)
    return respond_object(public(festival))


@bp.get("/festivals/<festival_id>/budget-summary")
@endpoint(["TalentBuyer", "BusinessAffairs", "FinanceController"])
def budget_summary(festival_id):
    festival = load("festivals", festival_id)
    tiers = calc.festival_tiers(festival_id)
    tier_sum = sum(t["committed_cents"] for t in tiers)
    booking_sum = 0
    for booking in calc.festival_bookings(festival_id):
        if booking["contract_status"] == "CANCELLED":
            continue
        booking_sum += booking["guarantee_cents"] + booking["production_fee_cents"]
    ratio = calc.committed_ratio(festival)
    return respond_object(
        {
            "allocatable_budget_cents": festival["allocatable_budget_cents"],
            "committed_budget_cents": festival["committed_budget_cents"],
            "tier_committed_sum_cents": tier_sum,
            "booking_committed_sum_cents": booking_sum,
            "committed_ratio": float(ratio),
            "lineup_posture": festival["lineup_posture"],
            "open_tier_count": len([t for t in tiers if t["status"] == "OPEN"]),
            "closed_tier_count": len([t for t in tiers if t["status"] == "CLOSED"]),
            "headliner_anchor_count": festival["headliner_anchor_count"],
        }
    )


@bp.get("/festivals/<festival_id>/budget-tiers")
@endpoint(["TalentBuyer", "BusinessAffairs", "FinanceController"])
def list_festival_tiers(festival_id):
    status = query_enum("status", ("OPEN", "CLOSED"))
    limit, offset = pagination()
    load("festivals", festival_id)
    rows = calc.festival_tiers(festival_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = calc.sorted_rows(rows, [("tier_rank", False)])
    window, meta = paginate(rows, limit, offset)
    return respond_array(public_list(window), pagination=meta)


@bp.get("/festivals/<festival_id>/stages")
@endpoint(["TalentBuyer", "BusinessAffairs", "ProductionManager", "FinanceController"])
def list_festival_stages(festival_id):
    is_flagship = query_bool("is_flagship")
    limit, offset = pagination()
    load("festivals", festival_id)
    rows = [s for s in db.stages.values() if s["festival_id"] == festival_id]
    if is_flagship is not None:
        rows = [r for r in rows if r["is_flagship"] == is_flagship]
    rows = calc.sorted_rows(rows, [("is_flagship", True), ("name", False)])
    window, meta = paginate(rows, limit, offset)
    return respond_array(public_list(window), pagination=meta)


# --------------------------------------------------------------------------- #
# BudgetTier
# --------------------------------------------------------------------------- #
@bp.post("/budget-tiers")
@endpoint(["TalentBuyer"])
def create_budget_tier():
    payload = body()
    req_string(payload, "festival_id", 1)
    tier_code = req_enum(payload, "tier_code", TIER_CODES)
    tier_rank = req_int(payload, "tier_rank", 1, 4)
    allocation_pct = req_number(payload, "allocation_pct", 0.01, 1.00)
    max_slots = req_int(payload, "max_slots", 1, 40)
    genre_focus = opt_enum(payload, "genre_focus", GENRE_FOCUS, "MIXED")

    festival = body_fk(payload, "festival_id", "festivals")

    for tier in calc.festival_tiers(festival["id"]):
        if tier["tier_code"] == tier_code or tier["tier_rank"] == tier_rank:
            fail(
                "ERR_DUPLICATE_TIER_CODE",
                "tier_code and tier_rank must be unique within the edition",
            )

    row = new_row(
        festival_id=festival["id"],
        tier_code=tier_code,
        tier_rank=tier_rank,
        allocation_pct=allocation_pct,
        max_slots=max_slots,
        genre_focus=genre_focus,
        allocation_cents=0,
        committed_cents=0,
        slots_committed=0,
        status="OPEN",
    )
    db.budget_tiers[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/budget-tiers/<tier_id>")
@endpoint(["TalentBuyer", "BusinessAffairs", "FinanceController"])
def get_budget_tier(tier_id):
    return respond_object(public(load("budget_tiers", tier_id)))


# --------------------------------------------------------------------------- #
# Stage
# --------------------------------------------------------------------------- #
@bp.post("/stages")
@endpoint(["ProductionManager"])
def create_stage():
    payload = body()
    req_string(payload, "festival_id", 1)
    name = req_string(payload, "name", 1, 80)
    capacity = req_int(payload, "capacity", 500, None)
    daily_curfew_minute = req_int(payload, "daily_curfew_minute", 600, 1560)
    daily_program_minutes_cap = req_int(
        payload, "daily_program_minutes_cap", 60, 1200
    )
    changeover_buffer_minutes = opt_int(
        payload, "changeover_buffer_minutes", 20, 0, 90
    )
    is_flagship = opt_bool(payload, "is_flagship", False)

    festival = body_fk(payload, "festival_id", "festivals")

    for stage in db.stages.values():
        if stage["festival_id"] == festival["id"] and stage["name"] == name:
            fail("ERR_DUPLICATE_STAGE_NAME", "stage name must be unique in the edition")

    row = new_row(
        festival_id=festival["id"],
        name=name,
        capacity=capacity,
        changeover_buffer_minutes=changeover_buffer_minutes,
        daily_curfew_minute=daily_curfew_minute,
        daily_program_minutes_cap=daily_program_minutes_cap,
        is_flagship=is_flagship,
        booked_minutes=0,
    )
    db.stages[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/stages/<stage_id>")
@endpoint(["TalentBuyer", "BusinessAffairs", "ProductionManager", "FinanceController"])
def get_stage(stage_id):
    return respond_object(public(load("stages", stage_id)))
