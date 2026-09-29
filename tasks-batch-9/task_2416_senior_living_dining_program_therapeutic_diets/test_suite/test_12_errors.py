"""Refusals: ballot resolution, tray safety, service suspension and period closure."""
from test_helpers import (
    BILLING_SPECIALIST,
    CLINICAL_STAFF,
    DIETITIAN,
    DINING_MANAGER,
    KITCHEN_LEAD,
    PROGRAM_ADMIN,
    ApiErrorId,
    add_menu_item,
    approve_diet_order,
    cast_ballot,
    create_community,
    create_diet_order,
    create_menu_cycle,
    create_reconciliation,
    create_reservation,
    create_resident,
    create_substitution_rule,
    create_venue,
    finalize_reconciliation,
    issue_and_serve_ticket,
    log_temperature,
    make_resident_representative_headers,
    read_menu_cycle,
    read_reconciliation,
    read_resident,
    read_tray_card,
    read_venue,
    record_observation,
    resident_version,
    reviews_for,
    set_clock,
    setup_published_menu_cycle,
    submit_menu_cycle,
    validate_error,
    validate_paginated,
    validate_success,
    venue_version,
)


def test_a_ballot_may_not_name_an_item_that_lives_on_a_sibling_cycle(api):
    """`C2-SOLE` is a real item code of the same community, yet against cycle one it resolves
    nowhere, so the ballot is refused, no feedback row is stored and the cycle's index stays at zero.

    PRD: "The `menu_item_code` is a natural key resolved against the `item_code` values of the menu
    items belonging to the addressed cycle; a code that resolves nowhere in that cycle is refused
    with `ERR_MENU_ITEM_NOT_IN_CYCLE`."

    Design: Corner/errors/committee_ballot_item_code_not_in_cycle_returns_422
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Ursula Pike", baseline_weight_kg=68.0
    )
    published = setup_published_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[
            {
                "item_code": "C1-COD",
                "name": "Baked Cod",
                "day_index": 1,
                "meal_period": "LUNCH",
                "base_texture": "REGULAR",
            }
        ],
    )
    sibling = create_menu_cycle(
        community["id"],
        cycle_number=2,
        week_count=1,
        effective_start_date="2026-08-17",
        effective_end_date="2026-08-23",
    )
    add_menu_item(
        sibling["id"],
        item_code="C2-SOLE",
        name="Lemon Sole",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )
    cycle_id = published["cycle"]["id"]

    refused = api.cast_committee_feedback(
        cycle_id,
        {
            "resident_id": resident["id"],
            "menu_item_code": "C2-SOLE",
            "sentiment": "NEGATIVE",
        },
        make_resident_representative_headers(resident["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_MENU_ITEM_NOT_IN_CYCLE, 422)

    _, meta = validate_paginated(
        api.list_cycle_committee_feedback(cycle_id, DINING_MANAGER)
    )
    assert meta["total_count"] == 0

    unchanged = read_menu_cycle(cycle_id)
    assert unchanged["status"] == "PUBLISHED"
    assert float(unchanged["refresh_index"]) == 0.00


def test_a_second_submitted_ballot_on_the_same_item_is_refused(api):
    """Uniqueness binds the triple of cycle, resident and item code: the repeat on `REG-COD` is
    refused even with the opposite sentiment, while the same resident's ballot on `REG-SOUP` is a
    different triple and is accepted.

    PRD: "Duplicate balloting is prevented at the level of the triple of cycle, resident and item
    code: while a ballot on that triple is still in `SUBMITTED` status a second one is refused with
    `ERR_DUPLICATE_BALLOT`, but once the earlier ballot has moved to `ACKNOWLEDGED` a fresh ballot on
    the same triple is accepted."

    Design: Corner/errors/second_submitted_ballot_on_same_triple_returns_409
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Viktor Aalto", baseline_weight_kg=82.0
    )
    published = setup_published_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[
            {
                "item_code": "REG-COD",
                "name": "Baked Cod",
                "day_index": 1,
                "meal_period": "LUNCH",
                "base_texture": "REGULAR",
            },
            {
                "item_code": "REG-SOUP",
                "name": "Barley Soup",
                "day_index": 2,
                "meal_period": "LUNCH",
                "base_texture": "REGULAR",
            },
        ],
    )
    cycle_id = published["cycle"]["id"]
    first = cast_ballot(cycle_id, resident["id"], "REG-COD", "POSITIVE")
    assert first["status"] == "SUBMITTED"

    repeat = api.cast_committee_feedback(
        cycle_id,
        {
            "resident_id": resident["id"],
            "menu_item_code": "REG-COD",
            "sentiment": "NEGATIVE",
        },
        make_resident_representative_headers(resident["id"]),
    )
    validate_error(repeat, ApiErrorId.ERR_DUPLICATE_BALLOT, 409)

    other_item = validate_success(
        api.cast_committee_feedback(
            cycle_id,
            {
                "resident_id": resident["id"],
                "menu_item_code": "REG-SOUP",
                "sentiment": "POSITIVE",
            },
            make_resident_representative_headers(resident["id"]),
        ),
        201,
    )
    assert other_item["menu_item_code"] == "REG-SOUP"
    assert other_item["id"] != first["id"]

    _, meta = validate_paginated(
        api.list_resident_committee_feedback(
            resident["id"], DIETITIAN, params={"status": "SUBMITTED"}
        )
    )
    assert meta["total_count"] == 2


def test_the_tray_card_needs_a_published_cycle_covering_the_requested_date(api):
    """A cycle that covers the date but has not been published does not count, and neither does the
    gap between two cycles; the inclusive last day of the published range still resolves.

    PRD: "Resolution begins by locating the menu cycle to serve from: the resident's community must
    have a cycle in `PUBLISHED` status whose closed range from `effective_start_date` through
    `effective_end_date` contains the requested `service_date`."

    Design: Corner/errors/tray_card_without_published_cycle_returns_409
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Wanda Ilves", baseline_weight_kg=61.0
    )
    setup_published_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[
            {
                "item_code": "C1-COD",
                "name": "Baked Cod",
                "day_index": 1,
                "meal_period": "LUNCH",
                "base_texture": "REGULAR",
            }
        ],
    )
    unsigned = create_menu_cycle(
        community["id"],
        cycle_number=2,
        week_count=1,
        effective_start_date="2026-08-24",
        effective_end_date="2026-08-30",
    )
    add_menu_item(
        unsigned["id"],
        item_code="C2-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )
    submitted = submit_menu_cycle(unsigned["id"])
    assert submitted["status"] == "PENDING_DIETITIAN_SIGNOFF"

    covered_but_unpublished = api.get_tray_card(
        resident["id"], "2026-08-25", "LUNCH", CLINICAL_STAFF
    )
    validate_error(covered_but_unpublished, ApiErrorId.ERR_NO_PUBLISHED_MENU_CYCLE, 409)

    in_the_gap = api.get_tray_card(resident["id"], "2026-08-17", "LUNCH", CLINICAL_STAFF)
    validate_error(in_the_gap, ApiErrorId.ERR_NO_PUBLISHED_MENU_CYCLE, 409)

    last_day = read_tray_card(resident["id"], "2026-08-16", "LUNCH")
    assert last_day["day_index"] == 7
    assert last_day["tray_status"] == "CLEAR"


def test_a_venue_that_does_not_serve_the_care_level_cannot_be_booked(api):
    """Both venues belong to the resident's own community, so the refusal is the care-level gate
    rather than a community-boundary error, and the satellite that does serve `MEMORY_CARE` books.

    PRD: "The resident's `care_level` must be a member of the venue's `care_levels_served`, or the
    booking is refused with `ERR_CARE_LEVEL_NOT_SERVED`."

    Design: Corner/errors/reserve_at_venue_not_serving_care_level_returns_422
    """
    set_clock("2026-08-10T09:00:00Z")
    community = create_community(
        "Brookdale Aldergate", ["ASSISTED_LIVING", "MEMORY_CARE"]
    )
    assisted_living_only = create_venue(
        community["id"],
        name="Aldergate Main Dining",
        venue_kind="MAIN_DINING",
        seat_capacity=20,
        care_levels_served=["ASSISTED_LIVING"],
    )
    memory_care = create_venue(
        community["id"],
        name="Aldergate Satellite",
        venue_kind="SATELLITE",
        seat_capacity=8,
        care_levels_served=["MEMORY_CARE"],
    )
    resident = create_resident(
        community["id"],
        full_name="Xenia Faber",
        care_level="MEMORY_CARE",
        baseline_weight_kg=59.0,
    )
    order = create_diet_order(resident["id"])
    approve_diet_order(order["id"])

    refused = api.create_reservation(
        {
            "resident_id": resident["id"],
            "venue_id": assisted_living_only["id"],
            "service_date": "2026-08-11",
            "meal_period": "LUNCH",
            "seat_start_utc": "2026-08-11T12:00:00Z",
            "party_size": 1,
            "expected_venue_version": venue_version(assisted_living_only["id"]),
        },
        DINING_MANAGER,
    )
    error = validate_error(refused, ApiErrorId.ERR_CARE_LEVEL_NOT_SERVED, 422)
    assert error["error_id"] != ApiErrorId.ERR_CROSS_COMMUNITY_REFERENCE.value

    reservation = create_reservation(
        resident["id"],
        memory_care["id"],
        "2026-08-11",
        "LUNCH",
        "2026-08-11T12:00:00Z",
        party_size=1,
    )

    assert reservation["venue_id"] == memory_care["id"]
    assert reservation["status"] == "RESERVED"


def test_seating_is_blocked_until_the_allergen_line_has_a_substitution(api):
    """With no rule the shellfish bisque leaves the tray `BLOCKED`, so seating is refused; a single
    `ALLERGEN` rule resolves the line and the same seating then succeeds at the current clock.

    PRD: "The tray card for the reservation's `service_date` and `meal_period` is resolved at this
    moment, and its resolved status must not be `BLOCKED`: neither an `ALLERGEN_UNRESOLVED` line, nor
    an `EXTENSION_PENDING` line, nor a resident-level `tray_card_state` of `BLOCKED` may be present,
    or seating is refused with `ERR_UNSAFE_TRAY_NO_SUBSTITUTION`."

    Design: Corner/errors/seat_resident_with_unresolved_allergen_returns_422
    """
    set_clock("2026-08-10T11:55:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    venue = create_venue(
        community["id"],
        name="Aldergate Main Dining",
        venue_kind="MAIN_DINING",
        seat_capacity=6,
        care_levels_served=["ASSISTED_LIVING"],
    )
    resident = create_resident(
        community["id"],
        full_name="Yara Lindqvist",
        baseline_weight_kg=67.0,
        allergens=["SHELLFISH"],
    )
    order = create_diet_order(resident["id"])
    approve_diet_order(order["id"])
    setup_published_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[
            {
                "item_code": "SHRIMP-BISQUE",
                "name": "Shrimp Bisque",
                "day_index": 1,
                "meal_period": "LUNCH",
                "base_texture": "REGULAR",
                "allergen_tags": ["SHELLFISH"],
            }
        ],
    )
    reservation = create_reservation(
        resident["id"],
        venue["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=1,
    )
    assert reservation["status"] == "RESERVED"

    blocked = read_tray_card(resident["id"], "2026-08-10", "LUNCH")
    assert blocked["tray_status"] == "BLOCKED"
    assert blocked["blocked_item_codes"] == ["SHRIMP-BISQUE"]
    assert blocked["lines"][0]["reason"] == "ALLERGEN_UNRESOLVED"

    refused = api.seat_reservation(reservation["id"], DINING_MANAGER)
    validate_error(refused, ApiErrorId.ERR_UNSAFE_TRAY_NO_SUBSTITUTION, 422)

    create_substitution_rule(
        resident["id"], "ALLERGEN", "SHELLFISH", "GARDEN-BISQUE", priority_rank=1
    )
    assert read_tray_card(resident["id"], "2026-08-10", "LUNCH")["tray_status"] == "CLEAR"

    seated = validate_success(api.seat_reservation(reservation["id"], DINING_MANAGER))

    assert seated["status"] == "SEATED"
    assert seated["seated_at"].startswith("2026-08-10T11:55:00")


def test_an_open_review_forbids_the_liberalizing_order_but_not_a_stricter_one(api):
    """The gate is directional: with a review `OPEN` against the `MINCED_MOIST` order the `REGULAR`
    proposal is refused, while a `PUREED` order — more restrictive, not less — is accepted.

    PRD: "So when the resident already has an `ACTIVE` order and the proposed `texture_level` has a
    **strictly lower** texture rank than that active order's `texture_level`, the resident must not
    have any plan-of-care review in `OPEN` status; if one is open, the create is refused with
    `ERR_TEXTURE_REQUIRES_DIETITIAN`."

    Design: Corner/errors/texture_liberalization_with_open_review_returns_422
    """
    set_clock("2026-08-02T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Zofia Kaminski", baseline_weight_kg=78.0
    )
    active_order = create_diet_order(
        resident["id"], texture_level="MINCED_MOIST", liquid_consistency="THIN"
    )
    approve_diet_order(active_order["id"])
    record_observation(resident["id"], "2026-08-02", "LUNCH", 80, weight_kg=80.0)
    set_clock("2026-08-20T08:00:00Z")
    record_observation(resident["id"], "2026-08-20", "LUNCH", 80, weight_kg=76.0)

    open_reviews = reviews_for(resident["id"], status="OPEN")
    assert len(open_reviews) == 1

    pinned_version = resident_version(resident["id"])
    liberalizing = api.create_diet_order(
        {
            "resident_id": resident["id"],
            "texture_level": "REGULAR",
            "liquid_consistency": "THIN",
            "expected_resident_version": pinned_version,
            "supersedes_order_id": active_order["id"],
        },
        CLINICAL_STAFF,
    )
    validate_error(liberalizing, ApiErrorId.ERR_TEXTURE_REQUIRES_DIETITIAN, 422)

    stricter = validate_success(
        api.create_diet_order(
            {
                "resident_id": resident["id"],
                "texture_level": "PUREED",
                "liquid_consistency": "MILDLY_THICK",
                "expected_resident_version": pinned_version,
                "supersedes_order_id": active_order["id"],
            },
            CLINICAL_STAFF,
        ),
        201,
    )

    assert stricter["texture_level"] == "PUREED"
    assert stricter["clinical_status"] == "PENDING_REVIEW"
    assert stricter["review_status"] == "AWAITING_DIETITIAN"


def test_a_suspended_venue_refuses_the_ticket_before_the_posture_restriction(api):
    """Three reheat violations suspend the venue, and the suspension is reported as a service
    refusal rather than the `WATCH`-level posture restriction, leaving the ticket list empty.

    PRD: "The `status` field distinguishes `OPEN` from `CLOSED`; a `CLOSED` venue cannot be reserved,
    seated or ticketed, and reports `ERR_VENUE_SERVICE_SUSPENDED` just as a suspended posture does."

    Design: Corner/errors/ticket_at_suspended_venue_returns_409
    """
    set_clock("2026-08-10T12:00:00Z")
    community = create_community("Brookdale Aldergate", ["MEMORY_CARE"])
    venue = create_venue(
        community["id"],
        name="Aldergate Satellite",
        venue_kind="SATELLITE",
        seat_capacity=8,
        care_levels_served=["MEMORY_CARE"],
    )
    resident = create_resident(
        community["id"],
        full_name="Aksel Norheim",
        care_level="MEMORY_CARE",
        baseline_weight_kg=75.0,
    )
    order = create_diet_order(resident["id"])
    approve_diet_order(order["id"])
    log_temperature(venue["id"], "REHEAT", 150.0)
    log_temperature(venue["id"], "REHEAT", 150.0)
    third = log_temperature(venue["id"], "REHEAT", 150.0)

    assert third["in_range"] is False
    assert third["violation_sequence_index"] == 3
    assert read_venue(venue["id"])["temp_compliance_posture"] == "SUSPENDED"

    refused = api.create_meal_ticket(
        {
            "venue_id": venue["id"],
            "ticket_type": "RESIDENT",
            "service_date": "2026-08-10",
            "meal_period": "LUNCH",
            "resident_id": resident["id"],
        },
        KITCHEN_LEAD,
    )
    error = validate_error(refused, ApiErrorId.ERR_VENUE_SERVICE_SUSPENDED, 409)
    assert error["error_id"] != ApiErrorId.ERR_VENUE_POSTURE_RESTRICTED.value

    _, meta = validate_paginated(
        api.list_meal_tickets(KITCHEN_LEAD, params={"venue_id": venue["id"]})
    )
    assert meta["total_count"] == 0


def test_a_ticket_served_after_the_reading_makes_the_finalize_stale(api):
    """Finalize recomputes the ledger and refuses to close over figures that have moved; the stored
    reading is left untouched at zero and a fresh reconciliation of the same period reads 650.

    PRD: "First, **freshness**: both readings and the whole fee waterfall are recomputed at finalize
    time, and the recomputation must reproduce the stored `ticket_ledger_total_cents`,
    `census_projection_total_cents` and `net_billable_total_cents`; if activity since the
    reconciliation was created has moved any of them, finalize is refused with
    `ERR_RECONCILIATION_STALE` and the specialist must reconcile afresh."

    Design: Corner/errors/finalize_after_a_new_ticket_returns_reconciliation_stale
    """
    set_clock("2026-08-10T12:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    venue = create_venue(
        community["id"],
        name="Aldergate Main Dining",
        venue_kind="MAIN_DINING",
        seat_capacity=10,
        care_levels_served=["ASSISTED_LIVING"],
    )
    resident = create_resident(
        community["id"], full_name="Bea Cortland", baseline_weight_kg=64.0
    )
    order = create_diet_order(resident["id"])
    approve_diet_order(order["id"])

    reconciliation = create_reconciliation(community["id"], "2026-08-10", "2026-08-10")
    assert reconciliation["ticket_ledger_total_cents"] == 0
    assert reconciliation["census_projection_total_cents"] == 0
    assert reconciliation["status"] == "RECONCILED"

    served = issue_and_serve_ticket(
        venue["id"], "RESIDENT", "2026-08-10", "LUNCH", resident_id=resident["id"]
    )
    assert served["status"] == "SERVED"
    assert served["billed_amount_cents"] == 650

    refused = api.finalize_reconciliation(reconciliation["id"], {}, BILLING_SPECIALIST)
    validate_error(refused, ApiErrorId.ERR_RECONCILIATION_STALE, 409)

    stale = read_reconciliation(reconciliation["id"])
    assert stale["status"] == "RECONCILED"
    assert stale["ticket_ledger_total_cents"] == 0

    afresh = create_reconciliation(community["id"], "2026-08-10", "2026-08-10")
    assert afresh["ticket_ledger_total_cents"] == 650
    assert afresh["status"] == "RECONCILED"


def test_a_finalized_period_is_closed_to_tickets_and_to_new_reconciliations(api):
    """Closure works on both sides of the ledger: a ticket dated inside the finalized day is
    refused, a reconciliation whose range merely intersects that day is refused too, and the day
    after remains open.

    PRD: "That link is what turns a subsequent void of one of those tickets into a chargeback credit
    against a later period, and it is also what closes the period against new tickets: once
    finalized, any ticket issue for a `service_date` inside the range reports `ERR_PERIOD_CLOSED`."

    Design: Corner/errors/ticket_in_finalized_period_returns_period_closed
    """
    set_clock("2026-08-11T12:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    venue = create_venue(
        community["id"],
        name="Aldergate Main Dining",
        venue_kind="MAIN_DINING",
        seat_capacity=10,
        care_levels_served=["ASSISTED_LIVING"],
    )
    resident = create_resident(
        community["id"], full_name="Cyrus Delacroix", baseline_weight_kg=73.0
    )
    order = create_diet_order(resident["id"])
    approve_diet_order(order["id"])
    reconciliation = create_reconciliation(community["id"], "2026-08-10", "2026-08-10")
    assert reconciliation["variance_cents"] == 0
    assert finalize_reconciliation(reconciliation["id"])["status"] == "FINALIZED"

    inside = api.create_meal_ticket(
        {
            "venue_id": venue["id"],
            "ticket_type": "RESIDENT",
            "service_date": "2026-08-10",
            "meal_period": "LUNCH",
            "resident_id": resident["id"],
        },
        DINING_MANAGER,
    )
    validate_error(inside, ApiErrorId.ERR_PERIOD_CLOSED, 409)

    overlapping = api.create_reconciliation(
        {
            "community_id": community["id"],
            "period_start_date": "2026-08-08",
            "period_end_date": "2026-08-12",
        },
        BILLING_SPECIALIST,
    )
    validate_error(overlapping, ApiErrorId.ERR_PERIOD_CLOSED, 409)

    outside = validate_success(
        api.create_meal_ticket(
            {
                "venue_id": venue["id"],
                "ticket_type": "RESIDENT",
                "service_date": "2026-08-11",
                "meal_period": "LUNCH",
                "resident_id": resident["id"],
            },
            DINING_MANAGER,
        ),
        201,
    )

    assert outside["service_date"] == "2026-08-11"
    assert outside["billed_amount_cents"] == 650


def test_each_missing_path_id_reports_the_error_of_its_own_entity(api):
    """Every probe is a well-formed uuid that resolves to nothing, and each read answers with the
    404 belonging to the entity that segment addresses — including the nested item read, which
    reports the missing item rather than a generic failure.

    PRD: "Depending on which segment fails, the error is `ERR_COMMUNITY_NOT_FOUND`,
    `ERR_VENUE_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_DIET_ORDER_NOT_FOUND`,
    `ERR_RESERVATION_NOT_FOUND`, `ERR_MENU_CYCLE_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`,
    `ERR_EXTENSION_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_RECONCILIATION_NOT_FOUND` or
    `ERR_REVIEW_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/not_found_family_each_entity_returns_its_own_id
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Dagny Sorensen", baseline_weight_kg=69.0
    )
    assert read_resident(resident["id"])["community_id"] == community["id"]
    ghost = "00000000-0000-4000-8000-0000000000{:02x}"

    validate_error(
        api.get_community(ghost.format(1), PROGRAM_ADMIN),
        ApiErrorId.ERR_COMMUNITY_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_venue(ghost.format(2), DINING_MANAGER),
        ApiErrorId.ERR_VENUE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_diet_order(ghost.format(3), CLINICAL_STAFF),
        ApiErrorId.ERR_DIET_ORDER_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_reservation(ghost.format(4), DINING_MANAGER),
        ApiErrorId.ERR_RESERVATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_menu_cycle(ghost.format(5), DINING_MANAGER),
        ApiErrorId.ERR_MENU_CYCLE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_menu_item(ghost.format(6), DINING_MANAGER),
        ApiErrorId.ERR_MENU_ITEM_NOT_FOUND,
        404,
    )
    validate_error(
        api.list_therapeutic_extensions(ghost.format(6), DIETITIAN),
        ApiErrorId.ERR_MENU_ITEM_NOT_FOUND,
        404,
    )
    validate_error(
        api.submit_therapeutic_extension(ghost.format(7), DIETITIAN),
        ApiErrorId.ERR_EXTENSION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_meal_ticket(ghost.format(8), BILLING_SPECIALIST),
        ApiErrorId.ERR_TICKET_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_reconciliation(ghost.format(9), BILLING_SPECIALIST),
        ApiErrorId.ERR_RECONCILIATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_plan_of_care_review(ghost.format(10), DIETITIAN),
        ApiErrorId.ERR_REVIEW_NOT_FOUND,
        404,
    )
