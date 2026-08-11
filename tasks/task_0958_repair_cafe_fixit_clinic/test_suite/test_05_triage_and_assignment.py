"""Triage scoring, OCC re-triage, assignment gating and the auto-selection
policy (PRD §2.8, §3.3, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, ApiErrorId, make_fixer_headers,
    create_triage_record_payload,
    set_logical_clock, create_event, create_station, register_fixer, add_skill,
    sign_up_shift, confirm_shift, check_in_shift, publish_event, open_station,
    open_intake, pause_station, register_visitor, sign_waiver, intake_item,
    triage_item, enqueue_item, assign_item, start_item_repair,
    record_item_outcome, make_part_stock, reserve_part,
    setup_intake_open_event, progress_item_to_queued,
    progress_item_to_in_repair,
)

COORD = TEST_USERS["coordinator_headers"]


# ─── triage priority scoring with clamp ─────────────────────────────────────

def test_triage_priority_ordinary_scoring(api):
    """PRD §3.3: "Every triage creation — first or subsequent — recomputes the
    item's `priority_score`: start from a category base of 10 points for
    `ELECTRONICS`, 5 for `TEXTILE`, and 7 for `BIKE`; add 8 points per unit of
    `severity`; add 2 points per unit of `estimated_difficulty`; add a further
    15 points when the item's `hazard_flag` is set; then clamp the total into
    the range 0 through 100."
    PRD §3.3: "The item's `required_skill_level` is set equal to the triage
    record's `estimated_difficulty` (0 before triage)."

    Design: Difficulty/combinatorial_formula/triage_priority_weighted_scoring_with_clamp
    """
    ctx = setup_intake_open_event(event_name="Cafe Gamma", skill_level=5)
    item = intake_item(ctx["event"]["id"], ctx["visitor"]["id"],
                       category="ELECTRONICS", description="Toaster",
                       weight_kg_estimated=3.0)
    triage_item(item["id"], ctx["fixer"]["id"], severity=3,
                estimated_difficulty=2, diagnosis="fuse")
    item_after = validate_success(api.get_repair_item(item["id"], COORD), 200)
    # ELECTRONICS base 10 + 8*3 severity + 2*2 difficulty + no hazard = 38.
    assert item_after["priority_score"] == 38
    assert item_after["required_skill_level"] == 2


def test_triage_priority_clamped_and_auto_incident(api):
    """PRD §3.3: "Every triage creation — first or subsequent — recomputes the
    item's `priority_score`: start from a category base of 10 points for
    `ELECTRONICS`, 5 for `TEXTILE`, and 7 for `BIKE`; add 8 points per unit of
    `severity`; add 2 points per unit of `estimated_difficulty`; add a further
    15 points when the item's `hazard_flag` is set; then clamp the total into
    the range 0 through 100."
    PRD §3.3: "Whenever a triage record's `severity` is 8 or higher, the system
    automatically creates a `SafetyIncident` of severity `CRITICAL` linked to
    the item and its event, with `reported_by_user_id` set to the acting
    fixer's id, and recomputes the event's `posture` — which, since a
    `CRITICAL` reported incident now exists, flips intake to `RESTRICTED`."

    Design: Difficulty/combinatorial_formula/triage_priority_weighted_scoring_with_clamp
    """
    ctx = setup_intake_open_event(event_name="Cafe Gamma", skill_level=5)
    item = intake_item(ctx["event"]["id"], ctx["visitor"]["id"],
                       category="ELECTRONICS", description="Mains heater",
                       weight_kg_estimated=6.0, hazard_flag=True)
    triage_item(item["id"], ctx["fixer"]["id"], severity=10,
                estimated_difficulty=5, diagnosis="cracked element")
    item_after = validate_success(api.get_repair_item(item["id"], COORD), 200)
    # Raw 10 + 8*10 + 2*5 + 15 hazard = 115, clamped into 0..100 -> 100.
    assert item_after["priority_score"] == 100

    incidents, meta = validate_paginated(
        api.list_safety_incidents(COORD, params={"item_id": item["id"]}))
    assert meta["total_count"] == 1, (
        "severity >= 8 auto-creates exactly one SafetyIncident")
    incident = incidents[0]
    assert incident["severity"] == "CRITICAL"
    assert incident["status"] == "REPORTED"
    assert incident["event_id"] == ctx["event"]["id"]
    assert incident["reported_by_user_id"] == ctx["fixer"]["id"]


# ─── cyclic RepairItem: return / reassign / reopen ─────────────────────────

def test_repair_item_full_cycle_return_reassign_reopen(api):
    """PRD §3.4: "From there the item can be sent back to the queue
    (`IN_REPAIR → QUEUED`) by the assigned fixer, by a `Coordinator`, or by the
    system during a suspension cascade; return-to-queue clears both assigned
    fields but deliberately keeps any `RESERVED` part reservations attached to
    the item."
    PRD §3.5: "When the latest outcome for an item (by creation time) is
    `NOT_REPAIRABLE` and still `RECORDED`, a `Coordinator` may reopen the item
    (`OUTCOME_RECORDED → QUEUED`) for a second opinion; the outcome record
    itself is left in `RECORDED` for audit."
    PRD §2.7: "The `version` field is an integer that starts on creation and
    increments by exactly 1 on every mutation, including mutations driven by
    system cascades, and it anchors optimistic concurrency control (§2.8)."

    Design: Difficulty/non_linear_state_machine/repair_item_cycle_return_reassign_reopen
    """
    ctx = setup_intake_open_event(event_name="Cafe Epsilon")
    item = intake_item(ctx["event"]["id"], ctx["visitor"]["id"],
                       category="ELECTRONICS", description="Dead TV",
                       weight_kg_estimated=8.0)
    created_version = item["version"]
    fid = ctx["fixer"]["id"]

    # Cycle: triage, enqueue, assign, start, return, assign, start, outcome.
    triage_item(item["id"], fid, severity=5, estimated_difficulty=3,
                diagnosis="board")
    enqueue_item(item["id"])
    assign_item(item["id"])
    start_item_repair(item["id"], fid)
    returned = validate_success(
        api.return_to_queue(item["id"], make_fixer_headers(fid)), 200)
    assert returned["status"] == "QUEUED"
    assert returned["assigned_fixer_id"] is None
    assert returned["assigned_station_id"] is None

    assign_item(item["id"])
    start_item_repair(item["id"], fid)
    record_item_outcome(item["id"], fid, outcome="NOT_REPAIRABLE")

    # Second-opinion reopen: OUTCOME_RECORDED (NOT_REPAIRABLE) -> QUEUED.
    reopened = validate_success(api.reopen_item(item["id"], COORD), 200)
    assert reopened["status"] == "QUEUED"
    assert reopened["assigned_fixer_id"] is None
    assert reopened["assigned_station_id"] is None
    # Nine mutations after creation: triage, enqueue, assign, start, return,
    # assign, start, outcome, reopen — each increments version by exactly 1.
    assert reopened["version"] == created_version + 9


def test_return_to_queue_keeps_part_reservations(api):
    """PRD §3.4: "From there the item can be sent back to the queue
    (`IN_REPAIR → QUEUED`) by the assigned fixer, by a `Coordinator`, or by the
    system during a suspension cascade; return-to-queue clears both assigned
    fields but deliberately keeps any `RESERVED` part reservations attached to
    the item."

    Design: Difficulty/non_linear_state_machine/repair_item_cycle_return_reassign_reopen
    """
    ctx = setup_intake_open_event(event_name="Cafe Epsilon-2")
    item = progress_item_to_in_repair(ctx, description="Amp",
                                      weight_kg_estimated=4.0)
    stock = make_part_stock(name="470uF cap", unit_cost_cents=120,
                            quantity_on_hand=10)
    reservation = reserve_part(stock["id"], item["id"], 3, ctx["fixer"]["id"])

    returned = validate_success(api.return_to_queue(
        item["id"], make_fixer_headers(ctx["fixer"]["id"])), 200)
    assert returned["status"] == "QUEUED"
    assert returned["assigned_fixer_id"] is None
    assert returned["assigned_station_id"] is None

    reservation_after = validate_success(
        api.get_part_reservation(reservation["id"], COORD), 200)
    assert reservation_after["status"] == "RESERVED", (
        "return-to-queue deliberately keeps RESERVED reservations")
    stock_after = validate_success(api.get_part_stock(stock["id"], COORD), 200)
    assert stock_after["quantity_reserved"] == 3


# ─── assignment gated by station state ──────────────────────────────────────

def test_assign_gated_by_station_open_paused_station(api):
    """PRD §3.4: "The target station must be `OPEN` (`ERR_STATION_NOT_OPEN`),
    must belong to the same event as the item, and its `category` must equal
    the item's `category` — a station-category mismatch is reported as
    `ERR_SKILL_MISMATCH`, and an event mismatch as `ERR_EVENT_STATION_MISMATCH`."

    Design: Difficulty/cross_entity_state_dependency/assign_gated_by_station_open
    """
    ctx = setup_intake_open_event(event_name="Cafe Nu")
    item = progress_item_to_queued(ctx, description="Iron",
                                   weight_kg_estimated=1.2, severity=2,
                                   estimated_difficulty=1)
    pause_station(ctx["station"]["id"])
    res = api.assign_item(item["id"],
                          {"fixer_id": ctx["fixer"]["id"],
                           "station_id": ctx["station"]["id"]},
                          COORD)
    validate_error(res, ApiErrorId.ERR_STATION_NOT_OPEN)
    item_after = validate_success(api.get_repair_item(item["id"], COORD), 200)
    assert item_after["status"] == "QUEUED"


def test_assign_gated_by_station_open_setup_station(api):
    """PRD §3.4: "The target station must be `OPEN` (`ERR_STATION_NOT_OPEN`),
    must belong to the same event as the item, and its `category` must equal
    the item's `category` — a station-category mismatch is reported as
    `ERR_SKILL_MISMATCH`, and an event mismatch as `ERR_EVENT_STATION_MISMATCH`."
    PRD §2.5: "When several rules could reject the same request, checks fire in
    a fixed priority order, and the first failure determines the error
    returned."

    Design: Difficulty/cross_entity_state_dependency/assign_gated_by_station_open
    """
    ctx = setup_intake_open_event(event_name="Cafe Nu-2")
    # A second station on the same event that was never opened (still SETUP).
    station2 = create_station(ctx["event"]["id"], category="ELECTRONICS",
                              label="E2", capacity=1)
    item = progress_item_to_queued(ctx, description="Iron",
                                   weight_kg_estimated=1.2, severity=2,
                                   estimated_difficulty=1)
    # Explicit assignment against the SETUP station: the station-state rule
    # (priority 4) fires before any fixer-eligibility rule (priority 10).
    res = api.assign_item(item["id"],
                          {"fixer_id": ctx["fixer"]["id"],
                           "station_id": station2["id"]},
                          COORD)
    validate_error(res, ApiErrorId.ERR_STATION_NOT_OPEN)
    item_after = validate_success(api.get_repair_item(item["id"], COORD), 200)
    assert item_after["status"] == "QUEUED"


# ─── OCC re-triage with supersession ────────────────────────────────────────

def test_occ_retriage_stale_version_then_supersession(api):
    """PRD §2.8: "First, creating a triage record for a repair item requires
    the request to carry `expected_item_version`, holding the item's `version`
    as last observed by the client. If the item's current `version` has
    advanced since that observation, the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412); because re-triage legitimately supersedes
    the prior current record, a writer holding a stale version would otherwise
    silently supersede a record it never saw."
    PRD §3.3: "In both cases the previously current record's
    `superseded_by_id` is set to the new record's `id` and its `is_current`
    flag becomes false, while the new record is the one with `is_current` true;
    priority and required-skill fields are recomputed from the new record."

    Design: Corner/cross_cutting_complexity_layers/occ_retriage_stale_version_then_supersession
    """
    ctx = setup_intake_open_event(event_name="Cafe Tav")
    item = intake_item(ctx["event"]["id"], ctx["visitor"]["id"],
                       category="ELECTRONICS", description="Monitor",
                       weight_kg_estimated=3.3)
    stale_version = item["version"]
    fid = ctx["fixer"]["id"]
    first = triage_item(item["id"], fid, severity=3, estimated_difficulty=2,
                        diagnosis="backlight")

    # Replay the pre-first-triage version: the item's version has advanced.
    res = api.create_triage_record(
        item["id"],
        create_triage_record_payload(stale_version, severity=5,
                                     estimated_difficulty=3, diagnosis="panel"),
        make_fixer_headers(fid))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    # Re-triage with the fresh version succeeds and supersedes the first.
    fresh = validate_success(api.get_repair_item(item["id"], COORD), 200)
    second = validate_success(api.create_triage_record(
        item["id"],
        create_triage_record_payload(fresh["version"], severity=5,
                                     estimated_difficulty=3, diagnosis="panel"),
        make_fixer_headers(fid)), 201)
    assert second["is_current"] is True

    item_after = validate_success(api.get_repair_item(item["id"], COORD), 200)
    # ELECTRONICS base 10 + 8*5 + 2*3 = 56, recomputed from the new record.
    assert item_after["priority_score"] == 56
    assert item_after["required_skill_level"] == 3

    first_after = validate_success(
        api.get_triage_record(first["id"], COORD), 200)
    assert first_after["is_current"] is False
    assert first_after["superseded_by_id"] == second["id"]


# ─── auto-selection policy ──────────────────────────────────────────────────

def test_auto_assign_selector_tiebreak_by_checked_in_at(api):
    """PRD §3.4: "When `fixer_id` is omitted, the selector policy ranks the
    eligible pool by `reliability_score` descending, breaking ties by the
    fixer's shift `checked_in_at` ascending — earlier check-ins first — and
    picks the leader."

    Design: Corner/calculations/auto_assign_selector_tiebreak_by_checked_in_at
    """
    set_logical_clock()
    event = create_event(name="Cafe Vav")
    station = create_station(event["id"], category="ELECTRONICS", capacity=2)
    fixer_a = register_fixer(display_name="Fixer A")
    fixer_b = register_fixer(display_name="Fixer B")
    add_skill(fixer_a["id"], category="ELECTRONICS", level=4)
    add_skill(fixer_b["id"], category="ELECTRONICS", level=4)
    shift_a = sign_up_shift(fixer_a["id"], station["id"], event["id"])
    shift_b = sign_up_shift(fixer_b["id"], station["id"], event["id"])
    publish_event(event["id"])
    confirm_shift(shift_a["id"])
    confirm_shift(shift_b["id"])
    check_in_shift(shift_a["id"], fixer_a["id"])       # checked in at 09:00
    set_logical_clock("2026-06-01T09:05:00Z")
    check_in_shift(shift_b["id"], fixer_b["id"])       # checked in at 09:05
    open_station(station["id"])
    open_intake(event["id"])
    visitor = register_visitor()
    sign_waiver(visitor["id"], safety_clause=True)
    item = intake_item(event["id"], visitor["id"], category="ELECTRONICS",
                       description="Keyboard", weight_kg_estimated=0.7)
    triage_item(item["id"], fixer_a["id"], severity=2, estimated_difficulty=2,
                diagnosis="keys")
    enqueue_item(item["id"])

    # Both fixers tie on reliability (100 each): the earlier check-in wins.
    assigned = validate_success(api.assign_item(item["id"], None, COORD), 200)
    assert assigned["assigned_fixer_id"] == fixer_a["id"], (
        "reliability tie breaks by checked_in_at ascending: 09:00 before 09:05")
    assert assigned["assigned_station_id"] == station["id"]
    assert assigned["status"] == "ASSIGNED"


def test_auto_assign_empty_pool_returns_no_eligible_fixer(api):
    """PRD §3.4: "The chosen fixer must be checked in at that station; must
    hold a skill whose category matches the item's `category` with a `level` at
    least the item's `required_skill_level` (`ERR_SKILL_LEVEL_INSUFFICIENT`
    when the level falls short); must carry a `reliability_score` of at least
    40 (`ERR_RELIABILITY_TOO_LOW`); must be `ACTIVE` (`ERR_FIXER_SUSPENDED`);
    and must not already have another item in `ASSIGNED` or `IN_REPAIR`
    (`ERR_FIXER_BUSY`)."
    PRD §3.4: "An empty eligible pool is reported as `ERR_NO_ELIGIBLE_FIXER`."

    Design: Corner/calculations/auto_assign_empty_pool_returns_no_eligible_fixer
    """
    ctx = setup_intake_open_event(event_name="Cafe Zayin", skill_level=1)
    # required_skill_level 3 vs the only checked-in fixer's skill level 1.
    item = progress_item_to_queued(ctx, description="Console",
                                   weight_kg_estimated=2.8, severity=4,
                                   estimated_difficulty=3,
                                   diagnosis="board rework")
    res = api.assign_item(item["id"], None, COORD)
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_FIXER)
    item_after = validate_success(api.get_repair_item(item["id"], COORD), 200)
    assert item_after["status"] == "QUEUED"
