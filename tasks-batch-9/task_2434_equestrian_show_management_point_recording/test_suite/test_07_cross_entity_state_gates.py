"""Gates that read another entity's state: veterinary coverage before a start, licence before an open."""

from test_helpers import api_client, validate_error, validate_success
from test_helpers.fixtures import (
    activate_coverage_shift,
    build_judge_and_steward,
    build_scheduled_class,
    build_show_with_class_list,
    card_judge_and_steward,
    create_coverage_shift,
    decide_license,
    get_class,
    get_show,
    get_slot,
    set_clock,
    submit_license,
)
from test_helpers.test_users import TEST_USERS

COMPETITION_DAY_CLOCK = "2026-09-10T13:30:00Z"


def _staffed_slot_with_three_scheduled_shifts():
    """A fully officiated 14:00-14:20 occupancy and three coverage windows, none checked in."""
    ctx = build_scheduled_class(entry_count=0, slot_start_utc="2026-09-10T14:00:00Z")
    ctx.update(build_judge_and_steward())
    card_judge_and_steward(ctx["slot_id"], ctx["judge_id"], ctx["steward_id"])
    ctx["vet_full"] = create_coverage_shift(ctx["show_id"])
    ctx["farrier"] = create_coverage_shift(
        ctx["show_id"], coverage_type="FARRIER", provider_name="Ridgeline Farriers"
    )
    ctx["vet_late"] = create_coverage_shift(
        ctx["show_id"],
        start_utc="2026-09-10T14:10:00Z",
        end_utc="2026-09-10T16:00:00Z",
        provider_name="Late Vet Service",
    )
    set_clock(COMPETITION_DAY_CLOCK)
    return ctx


def test_scheduled_veterinary_cover_and_an_active_farrier_both_fail_the_start_gate():
    """A veterinary window spanning the whole occupancy exists, but its provider has not checked
    in, so the call is refused. Checking in the farrier instead does nothing for the gate: the
    coverage type is part of the rule. After both refusals the occupancy is still SCHEDULED and
    its class still SCHEDULED — the transition is all-or-nothing.

    PRD §3.7: "There must exist a coverage window of the same show whose `coverage_type` is `VETERINARIAN` and whose `status` is `ACTIVE`, with its `start_utc` at or before the occupancy's `start_utc` and its `end_utc` at or after the occupancy's `end_utc` — the coverage must span the whole occupancy, and a `SCHEDULED` window whose provider has not checked in does not count."
    PRD §3.7: "A gap is `ERR_VET_COVERAGE_MISSING`."
    PRD §3.3: "The distinction between the two types is consequential: active veterinary coverage is a precondition for calling any class into a ring, while farrier coverage is recorded for the record and gates nothing."
    PRD §3.7: "On success the occupancy moves `SCHEDULED → RUNNING` and its class moves `SCHEDULED → IN_PROGRESS`; both `version` counters increment."

    Design: Difficulty/cross_entity_state_dependency/slot_start_requires_active_vet_coverage
    """
    ctx = _staffed_slot_with_three_scheduled_shifts()

    slot = get_slot(ctx["slot_id"])
    assert slot["status"] == "SCHEDULED"
    assert slot["end_utc"] == "2026-09-10T14:20:00Z"
    assert ctx["vet_full"]["status"] == "SCHEDULED"
    assert ctx["farrier"]["status"] == "SCHEDULED"
    assert ctx["vet_late"]["status"] == "SCHEDULED"

    validate_error(
        api_client.start_ring_slot(ctx["slot_id"], TEST_USERS["ring_master_headers"]),
        "ERR_VET_COVERAGE_MISSING",
        422,
    )

    activated = activate_coverage_shift(ctx["farrier"]["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["coverage_type"] == "FARRIER"

    validate_error(
        api_client.start_ring_slot(ctx["slot_id"], TEST_USERS["ring_master_headers"]),
        "ERR_VET_COVERAGE_MISSING",
        422,
    )

    assert get_slot(ctx["slot_id"])["status"] == "SCHEDULED"
    assert get_class(ctx["class_id"])["status"] == "SCHEDULED"


def test_veterinary_cover_must_span_the_whole_occupancy_not_merely_overlap_it():
    """An ACTIVE veterinary window running 14:10-16:00 begins after the 14:00 occupancy does, so
    it fails the containment test and the class still cannot be called. Checking in the
    12:00-20:00 window supplies the containment the gate wants and the class goes in the ring.
    The passing window is chosen by containment, not by being the only active vet: the late
    window is still ACTIVE alongside it.

    PRD §3.7: "There must exist a coverage window of the same show whose `coverage_type` is `VETERINARIAN` and whose `status` is `ACTIVE`, with its `start_utc` at or before the occupancy's `start_utc` and its `end_utc` at or after the occupancy's `end_utc` — the coverage must span the whole occupancy, and a `SCHEDULED` window whose provider has not checked in does not count."
    PRD §3.3: "A provider checks in by activating the window, moving it `SCHEDULED → ACTIVE` and incrementing its `version`."
    PRD §3.7: "On success the occupancy moves `SCHEDULED → RUNNING` and its class moves `SCHEDULED → IN_PROGRESS`; both `version` counters increment."

    Design: Difficulty/cross_entity_state_dependency/slot_start_requires_active_vet_coverage
    """
    ctx = _staffed_slot_with_three_scheduled_shifts()

    late = activate_coverage_shift(ctx["vet_late"]["id"])
    assert late["status"] == "ACTIVE"
    assert late["coverage_type"] == "VETERINARIAN"

    validate_error(
        api_client.start_ring_slot(ctx["slot_id"], TEST_USERS["ring_master_headers"]),
        "ERR_VET_COVERAGE_MISSING",
        422,
    )
    assert get_slot(ctx["slot_id"])["status"] == "SCHEDULED"

    spanning = activate_coverage_shift(ctx["vet_full"]["id"])
    assert spanning["status"] == "ACTIVE"

    started = validate_success(
        api_client.start_ring_slot(ctx["slot_id"], TEST_USERS["ring_master_headers"])
    )
    assert started["status"] == "RUNNING"
    assert get_class(ctx["class_id"])["status"] == "IN_PROGRESS"

    shifts = api_client.list_show_coverage_shifts(
        ctx["show_id"], TEST_USERS["show_secretary_headers"]
    ).json()["data"]
    by_id = {row["id"]: row for row in shifts}
    assert by_id[ctx["vet_full"]["id"]]["status"] == "ACTIVE"
    assert by_id[ctx["vet_late"]["id"]]["status"] == "ACTIVE"


def test_neither_draft_nor_submitted_licence_lets_a_class_open():
    """The class's own state is impeccably PLANNED; it is the parent that is not ready. Opening
    is refused while the licence is DRAFT and again while it is SUBMITTED, each time with the
    parent's error and never with the class's own state error. No purse is frozen by either
    refusal.

    PRD §3.1: "Conversely, opening a class for entries, submitting an entry and calling a class into the ring all require `license_status` to be exactly `APPROVED`, and each refuses with `ERR_SHOW_LICENSE_NOT_APPROVED` otherwise."
    PRD §3.2: "Only a class in `PLANNED` may be opened — otherwise `ERR_CLASS_NOT_PLANNED` — the owning show's licence must be `APPROVED`, and the owning division's `status` must be `ACTIVE`."
    PRD §3.2: "A newly created class has `status` of `PLANNED`, `entry_count` and `confirmed_entry_count` of 0, `class_purse_cents` and `awarded_prize_cents` of 0, `placed_count` of 0, `point_eligible` false, and both `estimated_minutes` and `actual_minutes` null."
    PRD §2.12: "The cross-entity licence gate — `ERR_SHOW_LICENSE_NOT_APPROVED` or `ERR_SHOW_LICENSE_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/class_open_requires_approved_show_license
    """
    ctx = build_show_with_class_list()
    assert ctx["show"]["license_status"] == "DRAFT"
    assert get_class(ctx["class_id"])["status"] == "PLANNED"

    response = api_client.open_class(ctx["class_id"], TEST_USERS["show_secretary_headers"])
    validate_error(response, "ERR_SHOW_LICENSE_NOT_APPROVED", 409)
    assert "ERR_CLASS_NOT_PLANNED" not in response.text
    assert get_class(ctx["class_id"])["status"] == "PLANNED"

    submitted = submit_license(ctx["show_id"])
    assert submitted["license_status"] == "SUBMITTED"
    assert submitted["revision_count"] == 0

    validate_error(
        api_client.open_class(ctx["class_id"], TEST_USERS["show_secretary_headers"]),
        "ERR_SHOW_LICENSE_NOT_APPROVED",
        409,
    )

    still_planned = get_class(ctx["class_id"])
    assert still_planned["status"] == "PLANNED"
    assert still_planned["class_purse_cents"] == 0


def test_approval_lets_the_class_open_once_and_then_its_own_state_rule_takes_over():
    """Approval both satisfies the parent gate and freezes the money, so the opening that was
    refused twice now succeeds and the class carries its 41721-cent purse. A second open finds
    nothing left to do at the parent level and is refused by the class's own state rule instead.

    PRD §3.1: "`APPROVE` moves the show `SUBMITTED → APPROVED` and is the only decision that requires the class list to still be substantive; a show with no class beneath its divisions cannot be approved, and the refusal is again `ERR_CLASS_LIST_INCOMPLETE`."
    PRD §3.2: "Opening a class for entries moves it `PLANNED → OPEN`."
    PRD §3.2: "Only a class in `PLANNED` may be opened — otherwise `ERR_CLASS_NOT_PLANNED` — the owning show's licence must be `APPROVED`, and the owning division's `status` must be `ACTIVE`."
    PRD §3.2: "Opening recomputes `class_purse_cents` and increments the class's `version`."

    Design: Difficulty/cross_entity_state_dependency/class_open_requires_approved_show_license
    """
    ctx = build_show_with_class_list()
    submit_license(ctx["show_id"])
    approved = decide_license(ctx["show_id"], "APPROVE")
    assert approved["license_status"] == "APPROVED"

    opened = validate_success(
        api_client.open_class(ctx["class_id"], TEST_USERS["show_secretary_headers"])
    )
    assert opened["status"] == "OPEN"
    assert opened["class_purse_cents"] == 41721

    validate_error(
        api_client.open_class(ctx["class_id"], TEST_USERS["show_secretary_headers"]),
        "ERR_CLASS_NOT_PLANNED",
        409,
    )

    assert get_class(ctx["class_id"])["status"] == "OPEN"
    assert get_show(ctx["show_id"])["license_status"] == "APPROVED"
