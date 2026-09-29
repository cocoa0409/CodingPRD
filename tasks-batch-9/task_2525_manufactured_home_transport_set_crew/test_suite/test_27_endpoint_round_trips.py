"""Round trips across the plain reads and writes of the installation API.

Each test builds every row it needs from an empty database, then walks one
endpoint family end to end: create, single read, amendment, filtered list, and
the derived side effects the PRD attaches to each step.
"""

from test_helpers import (
    amend_section_payload,
    api_client,
    assert_crew_minutes_match_reservations,
    assert_escort_assignment,
    assert_home_section,
    assert_order_summary,
    assert_site,
    add_route_leg,
    arrive_leg,
    create_escort_assignment_payload,
    depart_leg,
    inspect_site,
    make_inspector_headers,
    make_network_admin_headers,
    make_plant_dispatcher_headers,
    make_transport_manager_headers,
    measure_and_release_section,
    open_damage_claim,
    open_order,
    pay_and_issue_permit,
    read_escort_assignment,
    read_escort_crew,
    read_order,
    read_order_summary,
    read_section,
    record_section,
    register_hauler,
    register_plant,
    register_set_crew,
    register_site,
    request_permit,
    reserve_escort,
    set_logical_clock,
    setup_leg_awaiting_escorts,
    validate_paginated,
    validate_success,
    SITE_INSPECTOR_USER_ID,
)

READ_HEADERS = make_network_admin_headers()


def test_section_create_read_amend_and_filtered_list_round_trip():
    """PRD §3.2: "A floor's declared dimensions and its mate pointer may be
    amended by the same dispatcher while the floor is still `AT_PLANT`; the
    amendment accepts `declared_width_in`, `declared_height_in`,
    `declared_length_in` and `mates_to_section_id`, any subset of them, and once
    the floor has moved beyond `AT_PLANT` the amendment is refused by the
    generic state gate with `ERR_INVALID_STATE`."  PRD §3.2 also fixes the
    starting point: "A floor's `transit_status` starts at `AT_PLANT` and walks a
    branching path with two hold branches".

    Design: Corner/endpoints/section_crud_round_trip_create_read_amend_list
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    order = open_order(plant["id"], section_count=1)

    created = validate_success(
        api_client.create_section(
            {
                "order_id": order["id"],
                "section_index": 1,
                "declared_width_in": 168,
                "declared_height_in": 150,
                "declared_length_in": 720,
                "declared_weight_lb": 22000,
            },
            make_plant_dispatcher_headers(plant["id"]),
        ),
        201,
    )
    assert_home_section(created)
    assert created["transit_status"] == "AT_PLANT", (
        f"a recorded floor starts at AT_PLANT, got {created['transit_status']}"
    )
    assert created["version"] == 1, (
        f"version starts at 1 on creation, got {created['version']}"
    )

    read_back = read_section(created["id"])
    assert read_back["id"] == created["id"], "the single read addresses the same row"
    assert read_back["order_id"] == order["id"], (
        f"the floor belongs to order {order['id']}, got {read_back['order_id']}"
    )

    amended = validate_success(
        api_client.amend_section(
            created["id"],
            amend_section_payload(declared_width_in=176),
            make_plant_dispatcher_headers(plant["id"]),
        ),
        200,
    )
    assert amended["declared_width_in"] == 176, (
        f"the amendment writes declared_width_in 176, got {amended['declared_width_in']}"
    )
    assert amended["declared_height_in"] == 150, (
        "an omitted field is left alone, expected declared_height_in 150, got "
        f"{amended['declared_height_in']}"
    )
    assert amended["declared_length_in"] == 720, (
        "an omitted field is left alone, expected declared_length_in 720, got "
        f"{amended['declared_length_in']}"
    )
    assert amended["transit_status"] == "AT_PLANT", (
        f"the amendment leaves the floor AT_PLANT, got {amended['transit_status']}"
    )
    assert amended["version"] == 2, (
        f"version increases by exactly 1 on the amendment, got {amended['version']}"
    )


def test_section_list_filtered_by_order_reports_the_pre_window_total():
    """PRD §2.3: "Collections are always returned sorted by `created_at` in
    ascending order, so a stable window can be walked by advancing `offset`
    alone. List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters
    before the window is applied and `has_more` reports whether any matching row
    lies beyond the returned window."

    Design: Corner/endpoints/section_crud_round_trip_create_read_amend_list
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    order = open_order(plant["id"], section_count=2)
    first = record_section(order["id"], plant["id"], section_index=1)
    second = record_section(order["id"], plant["id"], section_index=2)

    data, meta = validate_paginated(
        api_client.list_sections(READ_HEADERS, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 2, (
        f"two floors match the order_id filter, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "no matching floor lies beyond the window"
    returned_ids = [row["id"] for row in data]
    assert returned_ids == [first["id"], second["id"]], (
        "the window is sorted by created_at ascending, expected "
        f"{[first['id'], second['id']]}, got {returned_ids}"
    )


def test_readiness_inspection_counts_defects_against_the_stored_pier_plan():
    """PRD §3.3: "The pier-plan dimension is satisfied only when the inspector
    passes the pier plan **and** the site's `pier_count` is at least six piers per
    declared section — so a two-section home needs at least twelve piers laid
    out, and a four-section home at least twenty-four, regardless of what the
    inspector says about the plan drawing."  And: "`blocking_defect_count` is
    then the number of those three dimensions that are **not** satisfied, so it
    always lands between 0 and 3 inclusive, and the site reads `READY` when the
    count is 0 and `READINESS_FAILED` otherwise."

    Design: Corner/endpoints/site_readiness_inspection_recomputes_status_and_round
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    order = open_order(plant["id"], section_count=2)
    site = register_site(order["id"], pad_type="RUNNER", pier_count=11)
    assert_site(site)
    assert site["readiness_status"] == "READINESS_PENDING", (
        f"a new site opens at READINESS_PENDING, got {site['readiness_status']}"
    )
    assert site["blocking_defect_count"] == 0, (
        f"a new site opens with blocking_defect_count 0, got {site['blocking_defect_count']}"
    )

    failed = validate_success(
        api_client.inspect_site_readiness(
            site["id"],
            {"pad_pass": False, "pier_plan_pass": False, "utility_pass": False},
            make_inspector_headers(SITE_INSPECTOR_USER_ID),
        ),
        200,
    )
    assert failed["blocking_defect_count"] == 3, (
        "three failed verdicts leave all three dimensions unsatisfied, expected 3, got "
        f"{failed['blocking_defect_count']}"
    )
    assert failed["readiness_status"] == "READINESS_FAILED", (
        f"a non-zero defect count reads READINESS_FAILED, got {failed['readiness_status']}"
    )

    reinspected = validate_success(
        api_client.inspect_site_readiness(
            site["id"],
            {"pad_pass": True, "pier_plan_pass": True, "utility_pass": True},
            make_inspector_headers("insp-site-2"),
        ),
        200,
    )
    assert reinspected["blocking_defect_count"] == 1, (
        "eleven piers fall short of the twelve a two-section home needs, so the "
        "pier-plan dimension stays unsatisfied even on a clean drawing verdict: "
        f"expected 1, got {reinspected['blocking_defect_count']}"
    )
    assert reinspected["readiness_status"] == "READINESS_FAILED", (
        "one blocking defect still reads READINESS_FAILED, got "
        f"{reinspected['readiness_status']}"
    )


def test_failed_reinspection_is_a_self_loop_that_only_advances_the_round():
    """PRD §3.3: "From `READINESS_FAILED` a further defective evaluation is a
    self-loop, `READINESS_FAILED → READINESS_FAILED`: it writes the new defect
    count, increments `inspection_round` by 1 and stamps `last_inspector_user_id`,
    but it does **not** re-derive the order's posture, because the site's
    contribution to the posture ladder has not changed."  PRD §3.3 also fixes the
    starting point: "A new site opens at `readiness_status` `READINESS_PENDING`,
    with `inspection_round` at 0, `blocking_defect_count` at 0 and
    `last_inspector_user_id` null."

    Design: Corner/endpoints/site_readiness_inspection_recomputes_status_and_round
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    order = open_order(plant["id"], section_count=2)
    site = register_site(order["id"], pad_type="RUNNER", pier_count=11)
    assert site["inspection_round"] == 0, (
        f"a new site opens with inspection_round 0, got {site['inspection_round']}"
    )
    assert site["last_inspector_user_id"] is None, (
        "a new site opens with last_inspector_user_id null, got "
        f"{site['last_inspector_user_id']}"
    )

    first = inspect_site(
        site["id"],
        pad_pass=False,
        pier_plan_pass=False,
        utility_pass=False,
        inspector_user_id=SITE_INSPECTOR_USER_ID,
    )
    assert first["inspection_round"] == 1, (
        f"the first verdict increments inspection_round to 1, got {first['inspection_round']}"
    )
    assert first["last_inspector_user_id"] == SITE_INSPECTOR_USER_ID, (
        "the acting inspector is stamped into last_inspector_user_id, expected "
        f"{SITE_INSPECTOR_USER_ID}, got {first['last_inspector_user_id']}"
    )
    order_before_self_loop = read_order(order["id"])

    second = inspect_site(
        site["id"],
        pad_pass=True,
        pier_plan_pass=True,
        utility_pass=True,
        inspector_user_id="insp-site-2",
    )
    assert second["readiness_status"] == "READINESS_FAILED", (
        "the self-loop lands back on READINESS_FAILED, got "
        f"{second['readiness_status']}"
    )
    assert second["inspection_round"] == 2, (
        f"the round counter advances to 2, got {second['inspection_round']}"
    )
    assert second["last_inspector_user_id"] == "insp-site-2", (
        "the re-inspecting operator is stamped, expected insp-site-2, got "
        f"{second['last_inspector_user_id']}"
    )
    assert second["version"] == first["version"] + 1, (
        "every readiness outcome raises the site's version, expected "
        f"{first['version'] + 1}, got {second['version']}"
    )

    order_after_self_loop = read_order(order["id"])
    assert order_after_self_loop["version"] == order_before_self_loop["version"], (
        "the self-loop does not re-derive the order's posture, so the order row is "
        f"left alone: expected version {order_before_self_loop['version']}, got "
        f"{order_after_self_loop['version']}"
    )
    assert order_after_self_loop["posture"] == order_before_self_loop["posture"], (
        "the site's contribution to the posture ladder has not changed, expected "
        f"{order_before_self_loop['posture']}, got {order_after_self_loop['posture']}"
    )


def test_order_summary_projects_the_counts_of_the_orders_descendant_rows():
    """PRD §2.11: "It returns `order_id`, the current `posture`,
    `section_count_declared` taken from the order's declared `section_count`,
    `section_count_actual` counting the home sections actually recorded,
    `sections_delivered_count` counting the floors that have reached delivery,
    `sections_on_hold_count` counting the floors sitting in either hold state,
    `site_readiness_status` reflecting the order's site, `issued_permit_count`
    counting the order's issued permits, `open_claim_count` counting the order's
    damage claims that have not yet reached a settled outcome,
    `network_chargeback_cents` reporting the conserved network chargeback total
    described in §2.9, and `invoice_total_cents` mirroring the order's invoice
    figure."

    Design: Corner/endpoints/order_summary_computed_read_matches_descendant_rows
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ"])
    set_crew = register_set_crew()
    order = open_order(plant["id"], section_count=2)
    first = record_section(order["id"], plant["id"], section_index=1)
    record_section(order["id"], plant["id"], section_index=2)

    measure_and_release_section(first["id"], plant["id"])
    permit = request_permit(first["id"], state_code="AZ", planned_leg_count=1)
    leg = add_route_leg(permit["id"], hauler["id"], sequence_no=1, state_code="AZ")
    pay_and_issue_permit(permit["id"], hauler["id"])
    depart_leg(leg["id"], hauler["id"])
    arrive_leg(leg["id"], hauler["id"])

    site = register_site(order["id"], pad_type="RUNNER", pier_count=12)
    inspect_site(site["id"])
    open_damage_claim(
        order["id"],
        first["id"],
        hauler["id"],
        set_crew["id"],
        discovered_stage="IN_TRANSIT",
        claimed_amount_cents=100000,
    )

    summary = read_order_summary(order["id"])
    assert_order_summary(summary)
    assert summary["order_id"] == order["id"], (
        f"the roll-up reports order_id {order['id']}, got {summary['order_id']}"
    )
    assert summary["section_count_declared"] == 2, (
        "section_count_declared mirrors the order's declared section_count, expected 2, "
        f"got {summary['section_count_declared']}"
    )
    assert summary["section_count_actual"] == 2, (
        "section_count_actual counts the floors actually recorded, expected 2, got "
        f"{summary['section_count_actual']}"
    )
    assert summary["sections_delivered_count"] == 1, (
        "only the first floor has reached delivery, expected 1, got "
        f"{summary['sections_delivered_count']}"
    )
    assert summary["sections_on_hold_count"] == 0, (
        "no floor sits in a hold state, expected 0, got "
        f"{summary['sections_on_hold_count']}"
    )
    assert summary["site_readiness_status"] == "READY", (
        "site_readiness_status reflects the order's site, expected READY, got "
        f"{summary['site_readiness_status']}"
    )
    assert summary["issued_permit_count"] == 1, (
        f"one permit reached ISSUED, expected 1, got {summary['issued_permit_count']}"
    )
    assert summary["open_claim_count"] == 1, (
        "the claim has not reached a settled outcome, expected 1, got "
        f"{summary['open_claim_count']}"
    )
    assert summary["network_chargeback_cents"] == 0, (
        "an unadjudicated claim charges nobody, expected 0, got "
        f"{summary['network_chargeback_cents']}"
    )
    assert summary["invoice_total_cents"] is None, (
        "no final inspection has passed, so the invoice figure is still null, got "
        f"{summary['invoice_total_cents']}"
    )
    assert summary["posture"] == read_order(order["id"])["posture"], (
        "the roll-up reports the order's current posture, expected "
        f"{read_order(order['id'])['posture']}, got {summary['posture']}"
    )


def test_escort_reservation_freezes_its_minutes_and_recomputes_the_crew_total():
    """PRD §3.5: "A reservation's own `reserved_minutes` is computed once, at
    creation, as the number of minutes between `window_start` and `window_end` —
    the elapsed seconds divided by sixty, rounded half up to a whole minute — and
    is frozen from then on. A crew's `reserved_minutes` is never incremented; it
    is recomputed in full as the sum of the frozen `reserved_minutes` of every one
    of that crew's reservations currently in `RESERVED` status."  PRD §2.9 adds
    that "reserving an escort raises the escort crew's `version`".

    Design: Corner/endpoints/escort_assignment_links_leg_and_crew_and_freezes_minutes
    """
    scenario = setup_leg_awaiting_escorts(
        escort_crews=[{"buffer_minutes": 15, "max_reserved_minutes": 1200}],
        window_start="2026-08-03T06:00:00.000Z",
        window_end="2026-08-03T18:00:00.000Z",
    )
    crew = scenario["escort_crews"][0]
    leg = scenario["leg"]
    assert crew["reserved_minutes"] == 0, (
        f"a new crew starts with reserved_minutes 0, got {crew['reserved_minutes']}"
    )

    reservation = validate_success(
        api_client.create_escort_assignment(
            create_escort_assignment_payload(
                leg["id"],
                crew["id"],
                role="ESCORT",
                window_start="2026-08-03T06:00:00.000Z",
                window_end="2026-08-03T12:00:00.000Z",
            ),
            make_transport_manager_headers(scenario["hauler"]["id"]),
        ),
        201,
    )
    assert_escort_assignment(reservation)
    assert reservation["route_leg_id"] == leg["id"], (
        f"the reservation covers leg {leg['id']}, got {reservation['route_leg_id']}"
    )
    assert reservation["escort_crew_id"] == crew["id"], (
        f"the reservation books crew {crew['id']}, got {reservation['escort_crew_id']}"
    )
    assert reservation["status"] == "RESERVED", (
        f"a new reservation opens at RESERVED, got {reservation['status']}"
    )
    assert reservation["reserved_minutes"] == 360, (
        "a six-hour window freezes at 360 minutes, got "
        f"{reservation['reserved_minutes']}"
    )

    refreshed = read_escort_crew(crew["id"])
    assert_crew_minutes_match_reservations(refreshed, 360)
    assert refreshed["status"] == "AVAILABLE", (
        "360 booked minutes do not exceed the crew's 1200-minute ceiling, so the crew "
        f"stays AVAILABLE, got {refreshed['status']}"
    )
    assert refreshed["version"] == crew["version"] + 1, (
        "reserving an escort raises the crew's version, expected "
        f"{crew['version'] + 1}, got {refreshed['version']}"
    )
    assert read_escort_assignment(reservation["id"])["reserved_minutes"] == 360, (
        "the frozen figure survives a re-read of the reservation"
    )


def test_escort_reservation_is_discoverable_from_both_the_leg_and_the_crew():
    """PRD §2.3: "Because collections are peers rather than nested resources,
    reverse navigation from a parent to its children is provided uniformly by
    filtered lists. Each child collection accepts every one of its own reference
    fields as an optional filter, alongside a status filter of the appropriate
    flavour".

    Design: Corner/endpoints/escort_assignment_links_leg_and_crew_and_freezes_minutes
    """
    scenario = setup_leg_awaiting_escorts(
        escort_crews=[{"buffer_minutes": 15, "max_reserved_minutes": 1200}],
        window_start="2026-08-03T06:00:00.000Z",
        window_end="2026-08-03T18:00:00.000Z",
    )
    crew = scenario["escort_crews"][0]
    leg = scenario["leg"]
    reservation = reserve_escort(
        leg["id"],
        crew["id"],
        scenario["hauler"]["id"],
        role="ESCORT",
        window_start="2026-08-03T06:00:00.000Z",
        window_end="2026-08-03T12:00:00.000Z",
    )

    by_leg, by_leg_meta = validate_paginated(
        api_client.list_escort_assignments(
            READ_HEADERS, params={"route_leg_id": leg["id"]}
        )
    )
    assert by_leg_meta["total_count"] == 1, (
        "the leg has exactly one reservation, got "
        f"{by_leg_meta['total_count']}"
    )
    assert by_leg[0]["id"] == reservation["id"], (
        "the route_leg_id filter finds the reservation just made, expected "
        f"{reservation['id']}, got {by_leg[0]['id']}"
    )

    by_crew, by_crew_meta = validate_paginated(
        api_client.list_escort_assignments(
            READ_HEADERS, params={"escort_crew_id": crew["id"]}
        )
    )
    assert by_crew_meta["total_count"] == 1, (
        f"the crew holds exactly one reservation, got {by_crew_meta['total_count']}"
    )
    assert by_crew[0]["id"] == reservation["id"], (
        "the escort_crew_id filter finds the same row, expected "
        f"{reservation['id']}, got {by_crew[0]['id']}"
    )
