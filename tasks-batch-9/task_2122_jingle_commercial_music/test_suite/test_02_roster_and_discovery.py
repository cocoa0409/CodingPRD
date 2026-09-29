"""Standing reference data, list discovery and the not-found catalogue."""
from test_helpers import (
    ApiErrorId,
    add_cue_entry,
    assert_musician,
    assert_studio_room,
    book_musician,
    create_client,
    create_composer,
    create_deliverable,
    create_musician,
    create_reuse_extension,
    create_studio_room,
    get_project,
    make_afm_steward_headers,
    make_producer_headers,
    make_rights_admin_headers,
    pitch_demo,
    schedule_session_call,
    set_clock,
    setup_engagement_in_demo,
    setup_engagement_in_production,
    setup_engagement_with_deal,
    setup_engagement_with_deliverable,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_license_deal_payload,
    create_musician_payload,
    create_project_payload,
)


def test_room_status_defaults_to_active_and_player_starts_non_union(api):
    """PRD §3.1: "A room's `status` may be supplied at registration and defaults to
    `ACTIVE`; the only other value is `MAINTENANCE`, and a room in `MAINTENANCE` cannot
    host a newly scheduled call."
    PRD §3.1: "A newly registered player always starts at `NON_UNION` signatory
    standing and **cannot be booked onto any session in that state**."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row, cascade-driven mutations
    included."

    Design: Corner/entities/corner_studio_room_status_and_musician_clearance_defaults
    """
    room = validate_success(api.create_studio_room(
        {"name": "Room D", "hourly_rate_cents": 25_000, "capacity_players": 4},
        make_producer_headers()), 201)
    assert_studio_room(room)
    assert room["status"] == "ACTIVE", (
        f"An omitted room status must default to ACTIVE; got {room['status']}")

    musician = validate_success(api.create_musician(
        {"full_name": "Ivo Blake", "instrument": "CELLO", "scale_hourly_cents": 7_000},
        make_producer_headers()), 201)
    assert_musician(musician)
    assert musician["afm_member_status"] == "NON_UNION", (
        f"A fresh player must start NON_UNION; got {musician['afm_member_status']}")
    assert musician["version"] == 1, f"Expected version 1, got {musician['version']}"


def test_unknown_signatory_standing_value_is_rejected(api):
    """PRD §3.1: "Only an `AFMSteward` may change a player's `afm_member_status`,
    setting it to `SIGNATORY_CLEARED`, back to `NON_UNION`, or to `SUSPENDED` when the
    federation withdraws standing."
    PRD §2.5: "**Request shape.** On every write endpoint, all required body fields are
    present, every enum-typed value is a declared member, every integer respects its
    declared range, and every array field is non-empty and free of duplicates —
    otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "Booking a player whose standing is anything other than
    `SIGNATORY_CLEARED` is refused with `ERR_MUSICIAN_NOT_SIGNATORY_CLEARED`."

    Design: Corner/entities/corner_afm_clearance_with_unknown_enum_member_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production()
    musician = validate_success(api.create_musician(
        create_musician_payload(full_name="Ivo Blake", instrument="CELLO",
                                scale_hourly_cents=7_000),
        make_producer_headers()), 201)
    assert musician["afm_member_status"] == "NON_UNION"

    validate_error(
        api.set_afm_clearance(musician["id"], {"afm_member_status": "GOLD_CARD"},
                              make_afm_steward_headers()),
        ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    # The rejected write left the player outside signatory standing, so the
    # player still cannot be booked onto a session.
    room = create_studio_room()
    call = schedule_session_call(env["project"]["id"], room["id"])
    validate_error(
        api.create_booking(call["id"], {"musician_id": musician["id"]}, make_producer_headers()),
        ApiErrorId.ERR_MUSICIAN_NOT_SIGNATORY_CLEARED.value, 422)


def test_demo_list_paginates_and_filters_by_engagement(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted, accepts a minimum of 1 and a
    maximum of 100; `offset` defaults to 0 and may not be negative."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` counts every row matching the
    filters before the window is applied and `has_more` is true when rows remain beyond
    the current window."
    PRD §2.10: "Demos may be filtered by `project_id`, by `composer_id` and by
    `status`."

    Design: Corner/entities/corner_demo_list_paginates_and_filters_by_project
    """
    env = setup_engagement_in_demo(budget_cents=4_000_000, target_markets=["US_LOCAL"],
                                   required_lengths=[30])
    composers = [create_composer(index=i) for i in range(3)]
    for index, composer in enumerate(composers):
        pitch_demo(env["project"]["id"], composer["id"],
                   title=f"Cut {index + 1}", demo_fee_cents=100_000,
                   submitted_length_seconds=30)

    response = api.list_demos(make_producer_headers(),
                              params={"project_id": env["project"]["id"], "limit": 2, "offset": 0})
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array", "A list read must answer response_type array"
    assert meta["total_count"] == 3, f"Expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True, "Three rows behind a limit of 2 must report has_more true"
    assert len(rows) == 2, f"Expected 2 rows in the window, got {len(rows)}"

    _, second_meta = validate_paginated(api.list_demos(
        make_producer_headers(), params={"composer_id": composers[1]["id"]}))
    assert second_meta["total_count"] == 1, (
        f"The composer_id filter must isolate one demo; got {second_meta['total_count']}")


def test_unknown_demo_reference_on_a_licence_draft_is_a_body_reference_404(api):
    """PRD §2.5: "**Body reference existence.** Every foreign identifier supplied in the
    request body resolves, on engagement creation, session-call scheduling, player
    booking, licence-deal drafting and cue-sheet line creation — otherwise
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_DEMO_NOT_FOUND`,
    `ERR_COMPOSER_NOT_FOUND`, `ERR_MUSICIAN_NOT_FOUND` or `ERR_STUDIO_ROOM_NOT_FOUND`
    (404)."

    Design: Corner/entities/corner_license_deal_body_fk_to_unknown_demo_returns_demo_not_found
    """
    env = setup_engagement_in_production(target_markets=["US_LOCAL"])
    project = get_project(env["project"]["id"])
    response = api.create_license_deal(
        create_license_deal_payload(
            project["id"], "4c9f1a22-77bd-4d0e-9a11-5e3c0b7a2d90", project["version"],
            license_structure="BUYOUT", market_codes=["US_LOCAL"], creative_fee_cents=400_000),
        make_rights_admin_headers())
    validate_error(response, ApiErrorId.ERR_DEMO_NOT_FOUND.value, 404)

    _, meta = validate_paginated(api.list_license_deals(
        make_producer_headers(), params={"project_id": project["id"]}))
    assert meta["total_count"] == 0, (
        f"No deal may be stored behind a 404; got {meta['total_count']}")


def test_every_child_is_reachable_from_its_parent(api):
    """PRD §2.10: "The filters available on the top-level lists are the reverse of the
    links that build the graph."
    PRD §2.10: "Engagements may be filtered by `client_id`, by `status` and by
    `budget_posture`."
    PRD §2.10: "An engagement's briefs are read as a sub-resource list and may
    additionally be narrowed by `status`; a deal's re-use extensions and a deal's
    delivery packages are read as sub-resource lists that accept pagination only."

    Design: Corner/endpoints/corner_reverse_reachability_lists_resolve_every_child_from_its_parent
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deal(
        stage="ACTIVE",
        deal_overrides={"license_structure": "TERM", "term_months": 12,
                        "market_codes": ["US_NATIONAL"], "creative_fee_cents": 800_000})
    extension = create_reuse_extension(env["deal"]["id"], "EU_NATIONAL")
    deliverable = create_deliverable(env["deal"]["id"])
    entry = add_cue_entry(deliverable["id"], env["composer"]["id"])
    room = create_studio_room()
    musician = create_musician(index=0)
    call = schedule_session_call(env["project"]["id"], room["id"])
    booking = book_musician(call["id"], musician["id"])

    headers = make_producer_headers()
    checks = [
        (api.list_projects(headers, params={"client_id": env["client"]["id"]}),
         env["project"]["id"], "projects by client_id"),
        (api.list_project_briefs(env["project"]["id"], headers),
         env["brief"]["id"], "briefs of the engagement"),
        (api.list_session_calls(headers, params={"project_id": env["project"]["id"],
                                                 "studio_room_id": room["id"]}),
         call["id"], "session calls by project and room"),
        (api.list_bookings(headers, params={"session_call_id": call["id"],
                                            "musician_id": musician["id"]}),
         booking["id"], "bookings by call and player"),
        (api.list_license_deals(headers, params={"project_id": env["project"]["id"],
                                                 "demo_id": env["demo"]["id"]}),
         env["deal"]["id"], "deals by project and demo"),
        (api.list_reuse_extensions(env["deal"]["id"], headers),
         extension["id"], "re-use extensions of the deal"),
        (api.list_deliverables(env["deal"]["id"], headers),
         deliverable["id"], "delivery packages of the deal"),
        (api.list_cue_entries(headers, params={"deliverable_id": deliverable["id"],
                                               "composer_id": env["composer"]["id"]}),
         entry["id"], "cue-sheet lines by package and writer"),
    ]
    for response, expected_id, label in checks:
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array", f"{label} must answer array"
        assert meta["total_count"] == 1, (
            f"{label} must resolve exactly one row; got {meta['total_count']}")
        assert meta["has_more"] is False, f"{label} must report has_more false"
        assert rows[0]["id"] == expected_id, (
            f"{label} must return {expected_id}; got {rows[0]['id']}")


def test_each_collection_answers_its_own_not_found_code(api):
    """PRD §2.5: "**Path existence.** Every identifier embedded in the request path
    resolves to a live row, validated from left to right, on every endpoint that has
    one — otherwise `ERR_PROJECT_NOT_FOUND`, `ERR_BRIEF_NOT_FOUND`, `ERR_DEMO_NOT_FOUND`,
    `ERR_MUSICIAN_NOT_FOUND`, `ERR_SESSION_CALL_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_LICENSE_DEAL_NOT_FOUND`, `ERR_DELIVERABLE_NOT_FOUND` or
    `ERR_CUE_ENTRY_NOT_FOUND` (404)."

    Design: Corner/errors/corner_unknown_path_ids_return_entity_specific_not_found_codes
    """
    client = create_client(name="Harborline Foods")
    producer = make_producer_headers()
    cases = [
        (api.get_demo("11111111-1111-4111-8111-111111111111", producer),
         ApiErrorId.ERR_DEMO_NOT_FOUND.value),
        (api.get_session_call("22222222-2222-4222-8222-222222222222", producer),
         ApiErrorId.ERR_SESSION_CALL_NOT_FOUND.value),
        (api.get_booking("33333333-3333-4333-8333-333333333333", producer),
         ApiErrorId.ERR_BOOKING_NOT_FOUND.value),
        (api.get_license_deal("44444444-4444-4444-8444-444444444444", producer),
         ApiErrorId.ERR_LICENSE_DEAL_NOT_FOUND.value),
        (api.get_deliverable("55555555-5555-4555-8555-555555555555", producer),
         ApiErrorId.ERR_DELIVERABLE_NOT_FOUND.value),
        (api.get_cue_entry("66666666-6666-4666-8666-666666666666", producer),
         ApiErrorId.ERR_CUE_ENTRY_NOT_FOUND.value),
        (api.approve_brief("77777777-7777-4777-8777-777777777777",
                           {"X-User-ID": client["id"], "X-User-Role": "ClientRep",
                            "Content-Type": "application/json"}),
         ApiErrorId.ERR_BRIEF_NOT_FOUND.value),
        (api.set_afm_clearance("88888888-8888-4888-8888-888888888888",
                               {"afm_member_status": "SIGNATORY_CLEARED"},
                               make_afm_steward_headers()),
         ApiErrorId.ERR_MUSICIAN_NOT_FOUND.value),
    ]
    for response, expected_error in cases:
        assert response.status_code == 404, (
            f"Expected HTTP 404 for {expected_error}, got {response.status_code}")
        validate_error(response, expected_error, 404)


def test_body_foreign_keys_resolve_before_any_business_rule(api):
    """PRD §2.5: "**Body reference existence.** Every foreign identifier supplied in the
    request body resolves, on engagement creation, session-call scheduling, player
    booking, licence-deal drafting and cue-sheet line creation — otherwise
    `ERR_CLIENT_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_DEMO_NOT_FOUND`,
    `ERR_COMPOSER_NOT_FOUND`, `ERR_MUSICIAN_NOT_FOUND` or `ERR_STUDIO_ROOM_NOT_FOUND`
    (404)."

    Design: Corner/errors/corner_body_foreign_keys_resolve_before_any_business_rule
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(stage="ACTIVE")

    validate_error(
        api.create_project(
            create_project_payload("99999999-9999-4999-8999-999999999999", title="Orphan",
                                   budget_cents=100_000),
            make_producer_headers()),
        ApiErrorId.ERR_CLIENT_NOT_FOUND.value, 404)
    validate_error(
        api.create_session_call(
            {"project_id": env["project"]["id"],
             "studio_room_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
             "scheduled_start_utc": "2026-09-10T09:00:00Z",
             "scheduled_end_utc": "2026-09-10T13:00:00Z"},
            make_producer_headers()),
        ApiErrorId.ERR_STUDIO_ROOM_NOT_FOUND.value, 404)
    validate_error(
        api.create_cue_entry(
            env["deliverable"]["id"],
            {"composer_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "role": "COMPOSER",
             "declared_weight": 1},
            make_rights_admin_headers()),
        ApiErrorId.ERR_COMPOSER_NOT_FOUND.value, 404)

    deliverable = validate_success(
        api.get_deliverable(env["deliverable"]["id"], make_producer_headers()))
    assert deliverable["unallocated_bps"] == 10_000, (
        "A rejected cue-sheet line must leave the whole 10000 basis points unallocated; "
        f"got {deliverable['unallocated_bps']}")
