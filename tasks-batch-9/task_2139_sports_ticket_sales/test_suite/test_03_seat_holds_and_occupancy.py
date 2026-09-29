"""Seat holds, their half-open geometry, the census identity and the seat OCC token."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_season_census_invariant,
    assert_seat_hold,
    create_account_with_rep,
    create_game,
    create_order,
    create_published_plan,
    create_rep,
    create_season,
    create_seat_hold_payload,
    mint_seats,
    open_renewal,
    place_hold,
    read_account,
    read_hold,
    read_season,
    read_seat,
    release_hold,
    seat_version,
    set_clock,
    setup_selling_world,
    validate_error,
    validate_paginated,
    validate_success,
    OPS_HEADERS,
)



def _four_zone_c_world():
    return setup_selling_world(
        seat_ranges=[
            {"section_code": "104", "row_label": "A", "price_zone": "ZONE_C",
             "seat_number_from": 1, "seat_number_to": 4}
        ],
        plan={"min_seats": 1, "max_seats": 8},
        account={"account_type": "GROUP"},
    )


def _two_zone_c_world():
    return setup_selling_world(account={"account_type": "GROUP"})


def test_hold_window_touching_an_existing_end_instant_is_accepted():
    """PRD 3.3: "The window is half-open: the start instant is inclusive, the end instant is exclusive, and the end must be strictly after the start. A new hold's window must not intersect the window of any `ACTIVE` hold on the same seat; because the intervals are half-open, touching endpoints do not intersect, so a new window that starts exactly when an existing one ends — or ends exactly when an existing one starts — is accepted, while any genuine overlap is `ERR_HOLD_WINDOW_CONFLICT`."
    PRD 3.3: "A successful hold is minted in `ACTIVE` status with a null `released_reason` and, unless it was minted by order creation, a null `origin_order_id`."

    Design: Difficulty/resource_temporal_overlap/seat_hold_half_open_windows_accept_adjacency_and_reject_intersection
    """
    world = _two_zone_c_world()
    seat = world["seats"][0]
    place_hold(
        seat["id"], world["account_id"], world["rep_headers"],
        hold_type="GROUP_HOLD",
        hold_window_start_utc="2026-08-05T00:00:00Z",
        hold_window_end_utc="2026-08-10T00:00:00Z",
    )

    response = api_client.create_seat_hold(
        create_seat_hold_payload(
            seat["id"], world["account_id"], seat_version(seat["id"]),
            hold_type="GROUP_HOLD",
            hold_window_start_utc="2026-08-10T00:00:00Z",
            hold_window_end_utc="2026-08-15T00:00:00Z",
        ),
        world["rep_headers"],
    )
    adjacent = validate_success(response, 201)

    assert_seat_hold(adjacent)
    assert adjacent["hold_status"] == "ACTIVE"
    assert adjacent["hold_window_start_utc"] == "2026-08-10T00:00:00.000Z"
    assert adjacent["origin_order_id"] is None
    _, meta = validate_paginated(
        api_client.list_seat_holds(
            OPS_HEADERS, params={"seat_id": seat["id"], "hold_status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 2
    # Neither window covers the current instant, so the seat is still free.
    assert read_seat(seat["id"])["seat_status"] == "AVAILABLE"
    season = read_season(world["season_id"])
    assert season["available_seat_count"] == 2
    assert season["held_seat_count"] == 0


def test_hold_window_overlapping_an_active_hold_is_rejected():
    """PRD 3.3: "A new hold's window must not intersect the window of any `ACTIVE` hold on the same seat; because the intervals are half-open, touching endpoints do not intersect, so a new window that starts exactly when an existing one ends — or ends exactly when an existing one starts — is accepted, while any genuine overlap is `ERR_HOLD_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/seat_hold_half_open_windows_accept_adjacency_and_reject_intersection
    """
    world = _two_zone_c_world()
    seat = world["seats"][0]
    place_hold(
        seat["id"], world["account_id"], world["rep_headers"],
        hold_type="GROUP_HOLD",
        hold_window_start_utc="2026-08-05T00:00:00Z",
        hold_window_end_utc="2026-08-10T00:00:00Z",
    )

    response = api_client.create_seat_hold(
        create_seat_hold_payload(
            seat["id"], world["account_id"], seat_version(seat["id"]),
            hold_type="GROUP_HOLD",
            hold_window_start_utc="2026-08-09T23:59:59Z",
            hold_window_end_utc="2026-08-12T00:00:00Z",
        ),
        world["rep_headers"],
    )

    validate_error(response, ApiErrorId.ERR_HOLD_WINDOW_CONFLICT.value, 409)
    _, meta = validate_paginated(
        api_client.list_seat_holds(
            OPS_HEADERS, params={"seat_id": seat["id"], "hold_status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1, "the overlapping hold must not be minted"


def test_hold_on_an_occupied_seat_reports_seat_not_available():
    """PRD 2.9: "**Seat freedom.** Hold creation requires each requested seat's `seat_status` to be `AVAILABLE`. Order creation and relocation require each requested seat to have a null `assigned_account_id` and to be either `AVAILABLE` or covered by an `ACTIVE` hold belonging to the same account. A violation is `ERR_SEAT_NOT_AVAILABLE` (409), and it guards hold creation, order creation and relocation."
    PRD 2.9: "**Seat-hold interval geometry** — `ERR_HOLD_WINDOW_CONFLICT` (409), guarding hold creation."

    Design: Difficulty/priority_pair_validation_conflict/seat_not_available_outranks_hold_window_conflict
    """
    world = _two_zone_c_world()
    seat = world["seats"][0]
    place_hold(
        seat["id"], world["account_id"], world["rep_headers"],
        hold_type="GROUP_HOLD",
        hold_window_start_utc="2026-08-01T00:00:00Z",
        hold_window_end_utc="2026-09-01T00:00:00Z",
    )
    assert read_seat(seat["id"])["seat_status"] == "HELD"

    response = api_client.create_seat_hold(
        create_seat_hold_payload(
            seat["id"], world["account_id"], seat_version(seat["id"]),
            hold_type="GROUP_HOLD",
            hold_window_start_utc="2026-08-15T00:00:00Z",
            hold_window_end_utc="2026-08-20T00:00:00Z",
        ),
        world["rep_headers"],
    )

    error = validate_error(response, ApiErrorId.ERR_SEAT_NOT_AVAILABLE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_HOLD_WINDOW_CONFLICT.value


def test_seat_not_available_leaves_the_existing_hold_and_census_untouched():
    """PRD 2.9: "**Seat freedom.** Hold creation requires each requested seat's `seat_status` to be `AVAILABLE`. Order creation and relocation require each requested seat to have a null `assigned_account_id` and to be either `AVAILABLE` or covered by an `ACTIVE` hold belonging to the same account. A violation is `ERR_SEAT_NOT_AVAILABLE` (409), and it guards hold creation, order creation and relocation."
    PRD 2.7: "`available_seat_count`, `held_seat_count` and `assigned_seat_count` are the numbers of those seats whose recomputed `seat_status` is `AVAILABLE`, `HELD` and `ASSIGNED` respectively."

    Design: Difficulty/priority_pair_validation_conflict/seat_not_available_outranks_hold_window_conflict
    """
    world = _two_zone_c_world()
    seat = world["seats"][0]
    place_hold(
        seat["id"], world["account_id"], world["rep_headers"],
        hold_type="GROUP_HOLD",
        hold_window_start_utc="2026-08-01T00:00:00Z",
        hold_window_end_utc="2026-09-01T00:00:00Z",
    )

    api_client.create_seat_hold(
        create_seat_hold_payload(
            seat["id"], world["account_id"], seat_version(seat["id"]),
            hold_type="GROUP_HOLD",
            hold_window_start_utc="2026-08-15T00:00:00Z",
            hold_window_end_utc="2026-08-20T00:00:00Z",
        ),
        world["rep_headers"],
    )

    assert read_seat(seat["id"])["seat_status"] == "HELD"
    _, meta = validate_paginated(
        api_client.list_seat_holds(OPS_HEADERS, params={"seat_id": seat["id"]})
    )
    assert meta["total_count"] == 1
    season = read_season(world["season_id"])
    assert season["held_seat_count"] == 1
    assert_season_census_invariant(season)


def test_releasing_a_hold_restores_the_seat_census_identity():
    """PRD 2.7: "These four figures satisfy a standing invariant: the available, held and assigned counts always sum to exactly the total seat count."
    PRD 3.3: "**Release** is the manual door, available to a `SalesRep` or `TicketOpsAdmin` on an `ACTIVE` hold with an optional `release_reason`; the hold becomes `RELEASED` with its `released_reason` recorded, the census re-runs so that the available, held and assigned counts once again sum to the total seat count with the seat back in its pre-hold bucket, and both the hold's `version` and the seat's `version` increment by 1."

    Design: Difficulty/compensating_invariant/hold_release_restores_the_seat_census_identity
    """
    world = _four_zone_c_world()
    seat = world["seats"][0]
    hold = place_hold(
        seat["id"], world["account_id"], world["rep_headers"],
        hold_type="GROUP_HOLD",
        hold_window_start_utc="2026-08-01T00:00:00Z",
        hold_window_end_utc="2026-09-01T00:00:00Z",
    )
    before = read_season(world["season_id"])
    assert before["total_seat_count"] == 4
    assert before["available_seat_count"] == 3
    assert before["held_seat_count"] == 1
    assert before["assigned_seat_count"] == 0
    assert_season_census_invariant(before)

    release_hold(hold["id"], world["rep_headers"], release_reason="customer declined")

    after = read_season(world["season_id"])
    assert after["available_seat_count"] == 4
    assert after["held_seat_count"] == 0
    assert after["assigned_seat_count"] == 0
    assert after["total_seat_count"] == 4
    assert_season_census_invariant(after)


def test_releasing_a_hold_records_its_reason_and_frees_the_seat():
    """PRD 3.3: "**Release** is the manual door, available to a `SalesRep` or `TicketOpsAdmin` on an `ACTIVE` hold with an optional `release_reason`; the hold becomes `RELEASED` with its `released_reason` recorded, the census re-runs so that the available, held and assigned counts once again sum to the total seat count with the seat back in its pre-hold bucket, and both the hold's `version` and the seat's `version` increment by 1."
    PRD 2.7: "The rule is a three-way decision evaluated in order: a seat whose `assigned_account_id` is not null is `ASSIGNED`; otherwise, a seat is `HELD` when some seat hold on that seat is in `ACTIVE` status and its occupation window covers the current instant — that is, the hold's `hold_window_start_utc` is at or before the current instant and its `hold_window_end_utc` is strictly after it, a half-open interval; otherwise the seat is `AVAILABLE`."

    Design: Difficulty/compensating_invariant/hold_release_restores_the_seat_census_identity
    """
    world = _four_zone_c_world()
    seat = world["seats"][0]
    hold = place_hold(
        seat["id"], world["account_id"], world["rep_headers"],
        hold_type="GROUP_HOLD",
        hold_window_start_utc="2026-08-01T00:00:00Z",
        hold_window_end_utc="2026-09-01T00:00:00Z",
    )

    released = release_hold(
        hold["id"], world["rep_headers"], release_reason="customer declined"
    )

    assert released["hold_status"] == "RELEASED"
    assert released["released_reason"] == "customer declined"
    freed = read_seat(seat["id"])
    assert freed["seat_status"] == "AVAILABLE"
    assert freed["assigned_account_id"] is None


def test_releasing_an_already_released_hold_is_rejected():
    """PRD 3.3: "Releasing a hold that is `CONVERTED`, `RELEASED` or `EXPIRED` is `ERR_HOLD_NOT_ACTIVE`."

    Design: Corner/state_machines/sm_released_hold_cannot_be_released_again
    """
    world = _two_zone_c_world()
    seat = world["seats"][0]
    hold = place_hold(
        seat["id"], world["account_id"], world["rep_headers"],
        hold_type="GROUP_HOLD",
        hold_window_start_utc="2026-08-01T00:00:00Z",
        hold_window_end_utc="2026-09-01T00:00:00Z",
    )
    release_hold(hold["id"], world["rep_headers"], release_reason="first release")

    response = api_client.release_seat_hold(
        hold["id"], {"release_reason": "second release"}, world["rep_headers"]
    )

    validate_error(response, ApiErrorId.ERR_HOLD_NOT_ACTIVE.value, 409)
    unchanged = read_hold(hold["id"])
    assert unchanged["hold_status"] == "RELEASED"
    assert unchanged["released_reason"] == "first release"
    season = read_season(world["season_id"])
    assert season["available_seat_count"] == 2
    assert season["held_seat_count"] == 0


def test_renewal_hold_after_the_deadline_is_rejected_while_other_hold_types_pass():
    """PRD 3.3: "A hold whose `hold_type` is `RENEWAL_HOLD` may be created only while the current instant is strictly before the season's `renewal_deadline_utc`; at or after that instant the request is refused with `ERR_RENEWAL_DEADLINE_PASSED`."
    PRD 3.3: "When the hold's `hold_type` is `RENEWAL_HOLD`, the holding account's `renewal_priority_active` flag becomes true — that flag is true exactly while the account holds at least one `ACTIVE` `RENEWAL_HOLD`, and it is what the renewal campaign reads to decide who is still engaged."

    Design: Corner/validations/val_renewal_hold_requested_after_the_deadline_rejected
    """
    world = setup_selling_world(account={"tenure_years": 3})
    seat = world["seats"][0]
    set_clock("2026-09-16T00:00:00Z")
    current_version = seat_version(seat["id"])

    refused = api_client.create_seat_hold(
        create_seat_hold_payload(
            seat["id"], world["account_id"], current_version,
            hold_type="RENEWAL_HOLD",
            hold_window_start_utc="2026-09-16T00:00:00Z",
            hold_window_end_utc="2026-09-30T00:00:00Z",
        ),
        world["rep_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_RENEWAL_DEADLINE_PASSED.value, 422)
    assert read_season(world["season_id"])["season_status"] == "RENEWAL_OPEN"

    accepted = api_client.create_seat_hold(
        create_seat_hold_payload(
            seat["id"], world["account_id"], current_version,
            hold_type="GROUP_HOLD",
            hold_window_start_utc="2026-09-16T00:00:00Z",
            hold_window_end_utc="2026-09-30T00:00:00Z",
        ),
        world["rep_headers"],
    )
    group_hold = validate_success(accepted, 201)
    assert group_hold["hold_status"] == "ACTIVE"
    assert read_account(world["account_id"])["renewal_priority_active"] is False
    assert read_season(world["season_id"])["held_seat_count"] == 1


def test_hold_create_with_a_stale_seat_version_is_rejected():
    """PRD 2.8: "**Seat-hold creation** requires a non-optional `expected_seat_version` field in its request body, carrying the client's last observed `version` of the target `Seat`. The server compares that value to the seat's stored `version`. If they differ — because some other writer has placed, released or converted a hold on that seat since the client read it — the create is rejected with `ERR_STALE_SEAT_VERSION` (HTTP 412) and no hold is minted."

    Design: Corner/cross_cutting_layers/occ_hold_create_with_a_stale_seat_version_rejected
    """
    world = _two_zone_c_world()
    seat = world["seats"][0]
    stale_version = seat_version(seat["id"])
    hold = place_hold(
        seat["id"], world["account_id"], world["rep_headers"],
        hold_type="GROUP_HOLD",
        hold_window_start_utc="2026-08-01T00:00:00Z",
        hold_window_end_utc="2026-09-01T00:00:00Z",
    )
    release_hold(hold["id"], world["rep_headers"], release_reason="customer changed plans")
    assert read_seat(seat["id"])["seat_status"] == "AVAILABLE"

    response = api_client.create_seat_hold(
        create_seat_hold_payload(
            seat["id"], world["account_id"], stale_version,
            hold_type="GROUP_HOLD",
            hold_window_start_utc="2026-08-02T00:00:00Z",
            hold_window_end_utc="2026-08-20T00:00:00Z",
        ),
        world["rep_headers"],
    )

    validate_error(response, ApiErrorId.ERR_STALE_SEAT_VERSION.value, 412)
    assert read_seat(seat["id"])["seat_status"] == "AVAILABLE"
    _, meta = validate_paginated(
        api_client.list_seat_holds(OPS_HEADERS, params={"seat_id": seat["id"]})
    )
    assert meta["total_count"] == 1, "no second hold row may be minted"
    assert read_season(world["season_id"])["held_seat_count"] == 0


def test_hold_create_with_the_current_seat_version_succeeds_and_bumps_it():
    """PRD 2.8: "**Seat-hold creation** requires a non-optional `expected_seat_version` field in its request body, carrying the client's last observed `version` of the target `Seat`. The server compares that value to the seat's stored `version`."
    PRD 3.3: "A successful hold is minted in `ACTIVE` status with a null `released_reason` and, unless it was minted by order creation, a null `origin_order_id`. It re-runs the occupancy census, bumps the seat's `version` by 1 and the season's `version` by 1."

    Design: Corner/cross_cutting_layers/occ_hold_create_with_the_current_seat_version_succeeds_and_bumps_it
    """
    world = _two_zone_c_world()
    seat = world["seats"][0]
    hold = place_hold(
        seat["id"], world["account_id"], world["rep_headers"],
        hold_type="GROUP_HOLD",
        hold_window_start_utc="2026-08-01T00:00:00Z",
        hold_window_end_utc="2026-09-01T00:00:00Z",
    )
    release_hold(hold["id"], world["rep_headers"], release_reason="customer changed plans")
    fresh_version = seat_version(seat["id"])

    response = api_client.create_seat_hold(
        create_seat_hold_payload(
            seat["id"], world["account_id"], fresh_version,
            hold_type="GROUP_HOLD",
            hold_window_start_utc="2026-08-01T00:00:00Z",
            hold_window_end_utc="2026-08-20T00:00:00Z",
        ),
        world["rep_headers"],
    )
    second_hold = validate_success(response, 201)

    assert second_hold["hold_status"] == "ACTIVE"
    refreshed_seat = read_seat(seat["id"])
    assert refreshed_seat["seat_status"] == "HELD"
    assert refreshed_seat["version"] == fresh_version + 1
    season = read_season(world["season_id"])
    assert season["held_seat_count"] == 1
    assert season["available_seat_count"] == 1


def test_seat_census_is_recomputed_inside_every_seat_touching_request():
    """PRD 2.7: "Any operation that releases, expires or converts a hold, mints seats, assigns seats to an order, or frees seats on cancellation re-runs this census in the same request, and the invariant is restored before the response is written."
    PRD 3.4: "For each seat in `seat_ids` the server mints one seat hold of `hold_type` `ORDER_HOLD`, whose window runs from the current instant for seventy-two hours — that is, `hold_window_start_utc` at the current instant and `hold_window_end_utc` three days later — with `origin_order_id` set to the new order's `id`; the exception is a seat on which the same account already holds an `ACTIVE` hold, for which no duplicate `ORDER_HOLD` is minted."

    Design: Corner/consistency_model/cons_seat_census_is_recomputed_inside_each_seat_touching_request
    """
    season = create_season()
    assert season["total_seat_count"] == 0
    assert season["available_seat_count"] == 0
    game = create_game(season["id"])
    create_rep()
    account, rep_headers = create_account_with_rep(account_type="GROUP")

    seats = mint_seats(
        season["id"], section_code="104", row_label="A", price_zone="ZONE_C",
        seat_number_from=1, seat_number_to=4,
    )
    plan = create_published_plan(
        season["id"], [game["id"]], min_seats=1, max_seats=8
    )
    opened = open_renewal(season["id"])
    assert opened["total_seat_count"] == 4
    assert opened["available_seat_count"] == 4
    assert opened["held_seat_count"] == 0
    assert_season_census_invariant(opened)

    order = create_order(
        account["id"], plan["id"], [s["id"] for s in seats], rep_headers
    )

    after_order = read_season(season["id"])
    assert after_order["held_seat_count"] == 4
    assert after_order["available_seat_count"] == 0
    assert_season_census_invariant(after_order)
    _, meta = validate_paginated(
        api_client.list_seat_holds(
            OPS_HEADERS, params={"origin_order_id": order["id"], "hold_status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 4
