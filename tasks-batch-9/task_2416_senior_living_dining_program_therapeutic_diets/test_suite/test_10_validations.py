"""Business validations: uniqueness scope, closed-range overlap, future dates, caps and gates."""
from test_helpers import (
    BILLING_SPECIALIST,
    CLINICAL_STAFF,
    DIETITIAN,
    DINING_MANAGER,
    ApiErrorId,
    add_menu_item,
    add_verified_resident,
    create_community,
    create_menu_cycle,
    create_reconciliation,
    create_reservation,
    create_resident,
    create_venue,
    issue_ticket,
    list_observations,
    publish_menu_cycle,
    read_menu_cycle,
    read_reconciliation,
    read_resident,
    read_seat_availability,
    set_clock,
    setup_dining_program,
    submit_menu_cycle,
    validate_error,
    validate_paginated,
    validate_success,
    venue_version,
)


def _aldergate_draft_cycle(cycle_number=1, start="2026-08-10", end="2026-08-16", community=None):
    """A DRAFT cycle of the given community, created empty."""
    owner = community or create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    cycle = create_menu_cycle(
        owner["id"],
        cycle_number=cycle_number,
        week_count=1,
        effective_start_date=start,
        effective_end_date=end,
    )
    return owner, cycle


def test_an_item_code_may_not_repeat_inside_its_own_cycle(api):
    """Uniqueness is scoped to the owning cycle and reads no other column, so the same code on a
    different day and meal period is still a duplicate and nothing is persisted.

    PRD: "Items are added to a cycle by a `DiningServicesManager`, each with an `item_code` that must
    be unique among that cycle's items — a duplicate is refused with `ERR_DUPLICATE_ITEM_CODE` — a
    dish `name`, a `day_index` between 1 and the cycle's `week_count` multiplied by seven inclusive,
    a `meal_period` of `BREAKFAST`, `LUNCH` or `DINNER`, and a `base_texture` from the same
    four-value texture enumeration the diet orders use."

    Design: Corner/validations/duplicate_item_code_in_same_cycle_rejected
    """
    _, cycle = _aldergate_draft_cycle()
    add_menu_item(
        cycle["id"],
        item_code="REG-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )

    response = api.create_menu_item(
        cycle["id"],
        {
            "item_code": "REG-COD",
            "name": "Baked Cod Reprise",
            "day_index": 4,
            "meal_period": "DINNER",
            "base_texture": "REGULAR",
        },
        DINING_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ITEM_CODE, 409)

    rows, meta = validate_paginated(api.list_menu_items(cycle["id"], DINING_MANAGER))
    assert meta["total_count"] == 1
    assert rows[0]["item_code"] == "REG-COD"


def test_the_same_item_code_is_free_to_reappear_in_a_sibling_cycle(api):
    """The mirror image of the duplicate rule: the identical code in another cycle of the same
    community is accepted as a new row and leaves the first cycle's inventory alone.

    PRD: "Items are added to a cycle by a `DiningServicesManager`, each with an `item_code` that must
    be unique among that cycle's items — a duplicate is refused with `ERR_DUPLICATE_ITEM_CODE` — a
    dish `name`, a `day_index` between 1 and the cycle's `week_count` multiplied by seven inclusive,
    a `meal_period` of `BREAKFAST`, `LUNCH` or `DINNER`, and a `base_texture` from the same
    four-value texture enumeration the diet orders use."

    Design: Corner/validations/same_item_code_in_a_different_cycle_is_accepted
    """
    community, first_cycle = _aldergate_draft_cycle()
    first_item = add_menu_item(
        first_cycle["id"],
        item_code="REG-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )
    _, second_cycle = _aldergate_draft_cycle(
        cycle_number=2, start="2026-08-17", end="2026-08-23", community=community
    )

    response = api.create_menu_item(
        second_cycle["id"],
        {
            "item_code": "REG-COD",
            "name": "Baked Cod",
            "day_index": 1,
            "meal_period": "LUNCH",
            "base_texture": "REGULAR",
        },
        DINING_MANAGER,
    )
    second_item = validate_success(response, 201)

    assert second_item["id"] != first_item["id"]
    assert second_item["menu_cycle_id"] == second_cycle["id"]
    assert second_item["extension_coverage_status"] == "NOT_REQUIRED"

    _, meta = validate_paginated(api.list_menu_items(first_cycle["id"], DINING_MANAGER))
    assert meta["total_count"] == 1


def test_two_closed_ranges_sharing_one_boundary_day_cannot_both_publish(api):
    """A candidate starting on the incumbent's last day intersects it and is refused; a candidate
    starting one day later publishes and archives the incumbent, while the refused cycle keeps its
    sign-off state.

    PRD: "And no other cycle of the same community that is currently `PUBLISHED` may have a closed
    effective range that intersects this cycle's closed range, or publication is refused with
    `ERR_MENU_CYCLE_DATE_OVERLAP`; because both ranges are closed, two cycles that merely share a
    single boundary date do overlap."

    Design: Corner/validations/publish_overlapping_published_cycle_date_range_rejected
    """
    community, incumbent = _aldergate_draft_cycle()
    add_menu_item(
        incumbent["id"],
        item_code="C1-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )
    submit_menu_cycle(incumbent["id"])
    publish_menu_cycle(incumbent["id"])

    _, touching = _aldergate_draft_cycle(
        cycle_number=2, start="2026-08-16", end="2026-08-22", community=community
    )
    add_menu_item(
        touching["id"],
        item_code="C2-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )
    submit_menu_cycle(touching["id"])
    _, disjoint = _aldergate_draft_cycle(
        cycle_number=3, start="2026-08-17", end="2026-08-23", community=community
    )
    add_menu_item(
        disjoint["id"],
        item_code="C3-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )
    submit_menu_cycle(disjoint["id"])

    refused = api.publish_menu_cycle(touching["id"], DIETITIAN)
    validate_error(refused, ApiErrorId.ERR_MENU_CYCLE_DATE_OVERLAP, 409)

    published = publish_menu_cycle(disjoint["id"])

    assert published["status"] == "PUBLISHED"
    assert read_menu_cycle(touching["id"])["status"] == "PENDING_DIETITIAN_SIGNOFF"
    assert read_menu_cycle(incumbent["id"])["status"] == "ARCHIVED"


def test_an_observation_dated_after_the_clock_is_refused_while_today_is_accepted(api):
    """The comparison against the logical clock date is inclusive: tomorrow is refused and the
    clock's own date is accepted, leaving exactly one stored observation.

    PRD: "The `observation_date` must not fall after the logical clock date, or the write is refused
    with `ERR_OBSERVATION_FUTURE_DATE`, and the resident must not be `DISCHARGED`."

    Design: Corner/validations/observation_future_date_returns_422
    """
    set_clock("2026-08-10T09:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Otto Kesler", baseline_weight_kg=74.0
    )

    refused = api.create_intake_observation(
        resident["id"],
        {"observation_date": "2026-08-11", "meal_period": "LUNCH", "intake_pct": 70},
        CLINICAL_STAFF,
    )
    validate_error(refused, ApiErrorId.ERR_OBSERVATION_FUTURE_DATE, 422)

    accepted = validate_success(
        api.create_intake_observation(
            resident["id"],
            {"observation_date": "2026-08-10", "meal_period": "LUNCH", "intake_pct": 70},
            CLINICAL_STAFF,
        ),
        201,
    )

    assert accepted["observation_date"] == "2026-08-10"
    assert len(list_observations(resident["id"])) == 1


def test_the_sponsorship_cap_is_aggregate_and_spares_the_unsponsored_guest(api):
    """Each sponsored guest lunch is individually under a 2000-cent cap; the second one breaks the
    running balance and is refused, yet a more expensive unsponsored guest ticket is still accepted
    because it never touches the resident's balance.

    PRD: "Finally, for a `GUEST` or `TAKEOUT` ticket with a sponsoring resident, the resident's
    `guest_meal_charge_balance_cents` plus the amount this ticket is about to bill must be at most the
    community's `guest_meal_sponsor_cap_cents`, or the issue is refused with
    `ERR_SPONSOR_LIMIT_EXCEEDED` (HTTP 402) — note that the cap is tested against the newly computed
    amount, so pricing runs before the cap is evaluated."

    Design: Corner/validations/sponsor_cap_exceeded_by_second_guest_ticket
    """
    set_clock("2026-08-10T12:00:00Z")
    community = create_community(
        "Brookdale Aldergate", ["ASSISTED_LIVING"], guest_meal_sponsor_cap_cents=2000
    )
    venue = create_venue(
        community["id"],
        name="Aldergate Main Dining",
        venue_kind="MAIN_DINING",
        seat_capacity=20,
        care_levels_served=["ASSISTED_LIVING"],
    )
    resident = create_resident(
        community["id"], full_name="Priya Anand", baseline_weight_kg=58.0
    )
    assert community["guest_meal_sponsor_cap_cents"] == 2000
    assert resident["guest_meal_charge_balance_cents"] == 0

    first = issue_ticket(
        venue["id"], "GUEST", "2026-08-10", "LUNCH", resident_id=resident["id"]
    )
    assert first["billed_amount_cents"] == 1173
    assert read_resident(resident["id"])["guest_meal_charge_balance_cents"] == 1173

    refused = api.create_meal_ticket(
        {
            "venue_id": venue["id"],
            "ticket_type": "GUEST",
            "service_date": "2026-08-10",
            "meal_period": "LUNCH",
            "resident_id": resident["id"],
        },
        DINING_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_SPONSOR_LIMIT_EXCEEDED, 402)

    unsponsored = issue_ticket(venue["id"], "GUEST", "2026-08-10", "LUNCH")

    assert unsponsored["billed_amount_cents"] == 1341
    assert unsponsored["resident_id"] is None
    assert read_resident(resident["id"])["guest_meal_charge_balance_cents"] == 1173

    rows, meta = validate_paginated(
        api.list_meal_tickets(BILLING_SPECIALIST, params={"venue_id": venue["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], unsponsored["id"]}


def test_the_waitlist_flag_turns_the_capacity_refusal_into_a_waitlisted_row(api):
    """Without the flag the over-capacity booking is refused and bumps no venue version, so the same
    `expected_venue_version` still works when the flag is added; the waitlisted row consumes no seat.

    PRD: "With `allow_waitlist` true — and with every other precondition satisfied, capacity being
    the only failure — the row is created in `WAITLISTED` status instead of erroring."

    Design: Corner/validations/allow_waitlist_flag_turns_capacity_rejection_into_waitlisted
    """
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Aldergate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Aldergate Bistro",
        venue_kind="BISTRO",
        seat_capacity=2,
        resident_name="Resident A",
        baseline_weight_kg=70.0,
    )
    venue_id = program["venue"]["id"]
    resident_b = add_verified_resident(
        program["community"], "Resident B", baseline_weight_kg=71.0
    )
    create_reservation(
        program["resident"]["id"],
        venue_id,
        "2026-08-11",
        "LUNCH",
        "2026-08-11T12:00:00Z",
        party_size=2,
    )
    pinned_version = venue_version(venue_id)

    payload = {
        "resident_id": resident_b["id"],
        "venue_id": venue_id,
        "service_date": "2026-08-11",
        "meal_period": "LUNCH",
        "seat_start_utc": "2026-08-11T12:00:00Z",
        "party_size": 1,
        "expected_venue_version": pinned_version,
    }
    refused = api.create_reservation(payload, DINING_MANAGER)
    validate_error(refused, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED, 409)
    assert venue_version(venue_id) == pinned_version

    waitlisted = validate_success(
        api.create_reservation(dict(payload, allow_waitlist=True), DINING_MANAGER), 201
    )

    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["allow_waitlist"] is True
    assert waitlisted["suspension_hold"] is False

    availability = read_seat_availability(venue_id, "2026-08-11", "LUNCH")
    assert availability["committed_seats"] == 2
    assert availability["open_seats"] == 0


def test_finalize_demands_the_variance_note_before_it_will_close_the_period(api):
    """A never-seated reservation makes the census read 650 against a ledger of 0, so the variance of
    -650 exceeds the community's 100-cent tolerance: the empty finalize is refused specifically for
    the missing note — not as stale — and the same call with a note closes the period unchanged.

    PRD: "Second, the **variance gate**: when the absolute value of `variance_cents` exceeds the
    community's `variance_tolerance_cents`, a non-empty `variance_note` must be supplied, or finalize
    is refused with `ERR_VARIANCE_UNRESOLVED`; a variance whose absolute value is at or under the
    tolerance needs no note."

    Design: Corner/validations/finalize_requires_variance_note_when_tolerance_exceeded
    """
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Aldergate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Aldergate Main Dining",
        seat_capacity=6,
        resident_name="Quentin Astor",
        baseline_weight_kg=81.0,
        community_overrides={"variance_tolerance_cents": 100},
    )
    assert program["community"]["variance_tolerance_cents"] == 100
    reservation = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=1,
    )
    assert reservation["status"] == "RESERVED"

    reconciliation = create_reconciliation(
        program["community"]["id"], "2026-08-10", "2026-08-10"
    )
    assert reconciliation["ticket_ledger_total_cents"] == 0
    assert reconciliation["census_projection_total_cents"] == 650
    assert reconciliation["variance_cents"] == -650
    assert reconciliation["net_billable_total_cents"] == 0
    assert reconciliation["status"] == "RECONCILED"

    refused = api.finalize_reconciliation(reconciliation["id"], {}, BILLING_SPECIALIST)
    error = validate_error(refused, ApiErrorId.ERR_VARIANCE_UNRESOLVED, 409)
    assert error["error_id"] != ApiErrorId.ERR_RECONCILIATION_STALE.value

    midway = read_reconciliation(reconciliation["id"])
    assert midway["status"] == "RECONCILED"
    assert midway["variance_note"] is None

    finalized = validate_success(
        api.finalize_reconciliation(
            reconciliation["id"],
            {"variance_note": "resident no-show on 2026-08-10, census not adjusted"},
            BILLING_SPECIALIST,
        )
    )

    assert finalized["status"] == "FINALIZED"
    assert finalized["variance_note"] == (
        "resident no-show on 2026-08-10, census not adjusted"
    )
    assert finalized["variance_cents"] == -650
    assert finalized["net_billable_total_cents"] == 0
