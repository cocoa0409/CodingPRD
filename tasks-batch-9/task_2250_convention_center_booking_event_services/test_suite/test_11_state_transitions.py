"""State transitions of the booking, hold, license and settlement machines."""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    BALLROOM_B,
    BALLROOM_C,
    EVENT_SERVICES,
    FACILITIES_PLANNER,
    MEETING_ROOM_301,
    NATIONAL_WIDGET_ASSOCIATION,
    RIVERBEND_ROTARY,
    SALES_MANAGER,
    VENUE_ADMIN,
    assert_fields,
    assert_money_cents,
    assert_settlement_money,
    booking_payload,
    create_booking,
    draft_license,
    finalize_settlement_after_dispute_window,
    issue_license,
    make_licensee_headers,
    place_hold,
    publish_window,
    read_booking,
    read_client,
    read_hold,
    read_license,
    read_settlement,
    read_space,
    register_client,
    register_space,
    set_clock,
    setup_event_lifecycle,
    validate_error,
    validate_success,
)

# The suite has no shared instant comparator, so this file carries its own: the
# stamped instants below are compared as points in time, which lets a server
# render them with or without the fractional part.


def _instant(value: str) -> datetime:
    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_same_instant(actual: str, expected: str, label: str) -> None:
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def test_booking_initial_state_is_tentative_with_open_posture(api):
    """PRD §3.2: "The booking is created in `status` `TENTATIVE` with `order_posture` `OPEN`, and the server resolves `policy_window_id` by looking up the published policy window whose `event_class` equals the submitted one — a lookup that must succeed, or the request fails with `ERR_POLICY_WINDOW_MISSING` before the dates are even inspected."

    PRD §3.2: "A separate derived field, `hold_count`, counts the holds on this booking whose `status` is `ACTIVE`, `CHALLENGED` or `CONFIRMED`, and starts at 0."
    PRD §2.4: "`version` (integer): a counter that starts at 1 on creation and increments by exactly 1 on every mutation of that resource, including mutations the server performs on its own initiative as part of a cascade."

    Design: Corner/state_machines/booking_initial_state_is_tentative_with_open_posture
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    client = register_client(api)

    response = api.create_booking(
        payload=booking_payload(client["id"], space["id"]),
        headers=SALES_MANAGER,
    )
    booking = validate_success(response, 201)

    assert_fields(
        booking,
        status="TENTATIVE",
        order_posture="OPEN",
        hold_count=0,
        version=1,
    )


def test_hold_confirm_first_option_moves_active_to_confirmed(api):
    """PRD §3.3: "**Confirming first option** drives `ACTIVE → CONFIRMED` and is the step that converts a queue position into a commitment; a `SalesManager` may take it only on a hold that is `ACTIVE`, whose `hold_rank` is exactly 1 — a hold at rank 2 or worse is refused with `ERR_HOLD_NOT_FIRST_OPTION` — and only while the logical clock instant is at or before `release_deadline_utc`, with a lapsed deadline refused as `ERR_RELEASE_DEADLINE_PASSED`."

    PRD §3.3: "The hold records its `booking_id`, copies the booking's `move_in_start_date` into `interval_start_date` and its `move_out_end_date` into `interval_end_date` as the two edges of its closed occupation interval, starts in `status` `ACTIVE` with `challenge_round` 0, `challenged_by_hold_id` null and `challenge_deadline_utc` null, and receives a `release_deadline_utc` stamped at midnight UTC of `show_start_date` less three whole months."
    PRD §3.3: "The booking's `hold_count` rises by 1 and its `version` rises by 1."

    Design: Corner/state_machines/hold_confirm_first_option_moves_active_to_confirmed
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B)
    client = register_client(api)
    booking = create_booking(
        api,
        client["id"],
        space["id"],
        event_name="Sunbelt Home Show",
        move_in_start_date="2027-06-08",
        show_start_date="2027-06-10",
        show_end_date="2027-06-12",
        move_out_end_date="2027-06-13",
    )
    hold = place_hold(api, booking["id"])

    response = api.confirm_first_option(hold["id"], headers=SALES_MANAGER)
    validate_success(response, 200)

    confirmed = read_hold(api, hold["id"])
    assert_fields(
        confirmed,
        status="CONFIRMED",
        hold_rank=1,
        challenge_round=0,
        interval_start_date="2027-06-08",
        interval_end_date="2027-06-13",
    )
    _assert_same_instant(
        confirmed["release_deadline_utc"], "2027-03-10T00:00:00Z", "release_deadline_utc"
    )
    assert_fields(read_booking(api, booking["id"]), hold_count=1)


def test_hold_confirm_first_option_on_a_second_rank_hold_rejected(api):
    """PRD §3.3: "**Confirming first option** drives `ACTIVE → CONFIRMED` and is the step that converts a queue position into a commitment; a `SalesManager` may take it only on a hold that is `ACTIVE`, whose `hold_rank` is exactly 1 — a hold at rank 2 or worse is refused with `ERR_HOLD_NOT_FIRST_OPTION` — and only while the logical clock instant is at or before `release_deadline_utc`, with a lapsed deadline refused as `ERR_RELEASE_DEADLINE_PASSED`."

    PRD §3.3: "The new hold's `hold_rank` is one greater than the number of holds in that set, so a hold with no competitors ranks 1 and the third overlapping hold on a hall ranks 3."

    Design: Corner/state_machines/hold_confirm_first_option_on_a_second_rank_hold_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B)
    sunbelt = register_client(api)
    riverbend = register_client(api, **RIVERBEND_ROTARY)

    interval = {
        "move_in_start_date": "2027-06-08",
        "show_start_date": "2027-06-10",
        "show_end_date": "2027-06-12",
        "move_out_end_date": "2027-06-13",
    }
    booking_one = create_booking(
        api, sunbelt["id"], space["id"], event_name="Sunbelt Home Show", **interval
    )
    booking_two = create_booking(
        api, riverbend["id"], space["id"], event_name="Rotary Antiques Fair", **interval
    )
    hold_one = place_hold(api, booking_one["id"])
    hold_two = place_hold(api, booking_two["id"])

    response = api.confirm_first_option(hold_two["id"], headers=SALES_MANAGER)
    validate_error(response, ApiErrorId.HOLD_NOT_FIRST_OPTION.value)

    assert_fields(read_hold(api, hold_one["id"]), hold_rank=1, status="ACTIVE")
    assert_fields(read_hold(api, hold_two["id"]), hold_rank=2, status="ACTIVE")


def test_license_issue_escrows_the_deposit_and_stamps_issued_at(api):
    """PRD §3.4: "On success `deposit_held_cents` is set to `deposit_required_cents`, the client's `credit_balance_cents` is decreased by exactly that amount, and `issued_at_utc` is stamped with the logical clock instant."

    PRD §3.4: "The license opens in `status` `DRAFT` with `deposit_held_cents` 0, `amendment_round` 0, `pending_amendment_note` null, and both `issued_at_utc` and `executed_at_utc` null."
    PRD §3.1: "`total_deposits_paid_cents` is therefore a historical fact while `credit_balance_cents` is a live balance; the two diverge the moment a license is issued."

    Design: Corner/state_machines/license_issue_escrows_the_deposit_and_stamps_issued_at
    """
    lifecycle = setup_event_lifecycle(
        api, stage="license_draft", space=MEETING_ROOM_301, deposit_cents=200_000
    )

    response = api.issue_license(lifecycle["license"]["id"], headers=SALES_MANAGER)
    validate_success(response, 200)

    issued = read_license(api, lifecycle["license"]["id"])
    assert_fields(issued, status="ISSUED")
    assert_money_cents(issued["deposit_held_cents"], 90_900, "deposit_held_cents")
    _assert_same_instant(issued["issued_at_utc"], "2026-08-01T00:00:00Z", "issued_at_utc")
    assert issued["executed_at_utc"] is None, (
        f"executed_at_utc must still be null, got {issued['executed_at_utc']!r}"
    )

    client = read_client(api, lifecycle["client"]["id"])
    assert_money_cents(client["credit_balance_cents"], 109_100, "credit_balance_cents")
    assert_money_cents(
        client["total_deposits_paid_cents"], 200_000, "total_deposits_paid_cents"
    )


def test_booking_open_show_directly_from_tentative_rejected(api):
    """PRD §3.8: "**Opening the show floor** drives the booking `DEFINITE → IN_HOUSE` and belongs to the `EventServicesManager`."

    PRD §2.11: "The target resource is in a state from which the requested transition is declared, else the state-invalid code of the entity whose state fails the guard: `ERR_BOOKING_STATE_INVALID`, `ERR_HOLD_STATE_INVALID`, `ERR_LICENSE_STATE_INVALID`, `ERR_SERVICE_ORDER_STATE_INVALID`, `ERR_LABOR_CALL_STATE_INVALID`, `ERR_CATERING_STATE_INVALID`, `ERR_SETTLEMENT_STATE_INVALID`, `ERR_BLACKOUT_STATE_INVALID` — all HTTP 409."
    PRD §2.11: "Checks are evaluated in this order, and the first failure short-circuits the request:"
    PRD §2.10: "`OPEN` otherwise — that is, when the booking is `TENTATIVE`, `DEFINITE` or `IN_HOUSE` and its client stands `GOOD`."

    Design: Corner/state_machines/booking_open_show_directly_from_tentative_rejected
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    client = register_client(api)
    booking = create_booking(api, client["id"], space["id"])
    set_clock(api, "2027-03-01T08:00:00Z")

    response = api.open_show(booking["id"], headers=EVENT_SERVICES)
    validate_error(response, ApiErrorId.BOOKING_STATE_INVALID.value)

    assert_fields(
        read_booking(api, booking["id"]), status="TENTATIVE", order_posture="OPEN"
    )


def test_release_of_a_settled_booking_rejected(api):
    """PRD §3.2: "**Releasing** a booking, which a `SalesManager` may do from `TENTATIVE` and a `VenueAdmin` may do from `DEFINITE`, drives `TENTATIVE → RELEASED` or `DEFINITE → RELEASED`; both require that no settlement yet exists for the booking, and an attempt on a booking that already has one is refused with `ERR_SETTLEMENT_ALREADY_EXISTS`."

    PRD §3.2: "The booking's `status` moves through seven values — `TENTATIVE`, `DEFINITE`, `IN_HOUSE`, `CLOSED`, `SETTLED`, `RELEASED` and `CANCELLED` — of which the last three, `SETTLED`, `RELEASED` and `CANCELLED`, are terminal."
    PRD §3.9: "`deposit_applied_cents` is set to the license's `deposit_held_cents` for this booking, and that field is then set to 0, moving the escrowed money onto the settlement and preserving the monetary invariant of §2.9."
    PRD §2.9: "`SpaceUnit.committed_space_days` is the sum of `space_days_committed` over the bookings placed on that space or on any of its descendant spaces whose `status` is one of `TENTATIVE`, `DEFINITE`, `IN_HOUSE`, `CLOSED` or `SETTLED`."

    Design: Corner/state_machines/release_of_a_settled_booking_rejected
    """
    lifecycle = setup_event_lifecycle(
        api,
        stage="settlement_issued",
        space=BALLROOM_C,
        deposit_cents=1_300_000,
        booking={
            "event_name": "Sunbelt Boat Show",
            "move_in_start_date": "2027-06-09",
            "show_start_date": "2027-06-10",
            "show_end_date": "2027-06-12",
            "move_out_end_date": "2027-06-13",
        },
    )
    finalize_settlement_after_dispute_window(api, lifecycle["settlement"]["id"])

    response = api.release_booking(lifecycle["booking"]["id"], headers=VENUE_ADMIN)
    validate_error(response, ApiErrorId.BOOKING_STATE_INVALID.value)

    assert_fields(read_booking(api, lifecycle["booking"]["id"]), status="SETTLED")
    settlement = read_settlement(api, lifecycle["settlement"]["id"])
    assert_fields(settlement, status="FINAL")
    assert_settlement_money(
        settlement, deposit_applied_cents=1_250_000, grand_total_cents=4_100_000
    )
    assert_fields(read_space(api, lifecycle["space"]["id"]), committed_space_days=5)
    assert_fields(read_hold(api, lifecycle["hold"]["id"]), status="CONFIRMED")


def test_second_countersign_of_an_executed_license_rejected(api):
    """PRD §3.4: "**Countersigning** drives `ISSUED → EXECUTED` and is reserved to the `Licensee` itself: the acting `X-User-ID` must equal the `client_id` of the license's booking, or the request is `ERR_NOT_RESOURCE_OWNER`."

    PRD §2.11: "The target resource is in a state from which the requested transition is declared, else the state-invalid code of the entity whose state fails the guard: `ERR_BOOKING_STATE_INVALID`, `ERR_HOLD_STATE_INVALID`, `ERR_LICENSE_STATE_INVALID`, `ERR_SERVICE_ORDER_STATE_INVALID`, `ERR_LABOR_CALL_STATE_INVALID`, `ERR_CATERING_STATE_INVALID`, `ERR_SETTLEMENT_STATE_INVALID`, `ERR_BLACKOUT_STATE_INVALID` — all HTTP 409."
    PRD §3.4: "On success `deposit_held_cents` is set to `deposit_required_cents`, the client's `credit_balance_cents` is decreased by exactly that amount, and `issued_at_utc` is stamped with the logical clock instant."

    Design: Corner/state_machines/second_countersign_of_an_executed_license_rejected
    """
    lifecycle = setup_event_lifecycle(
        api, stage="license_executed", space=MEETING_ROOM_301, deposit_cents=200_000
    )
    executed_version = lifecycle["license"]["version"]

    response = api.countersign_license(
        lifecycle["license"]["id"],
        headers=make_licensee_headers(lifecycle["client"]["id"]),
    )
    validate_error(response, ApiErrorId.LICENSE_STATE_INVALID.value)

    license_row = read_license(api, lifecycle["license"]["id"])
    assert_fields(license_row, status="EXECUTED", version=executed_version)
    assert_money_cents(license_row["deposit_held_cents"], 90_900, "deposit_held_cents")
    assert_money_cents(
        read_client(api, lifecycle["client"]["id"])["credit_balance_cents"],
        109_100,
        "credit_balance_cents",
    )


def test_booking_release_cascades_down_to_hold_license_and_space_ledger(api):
    """PRD §3.2: "Whenever a booking reaches `RELEASED`, from whatever cause, the **release cascade** performs all of the following: every hold on the booking whose `status` is `ACTIVE`, `CHALLENGED` or `CONFIRMED` moves to `RELEASED`, driving `hold_count` down to 0, and each such release re-ranks the surviving holds on the same space by the ranking rule in §3.3; the booking's license agreement, if its `status` is `DRAFT` or `ISSUED`, moves to `VOIDED`, its `deposit_held_cents` returning to the client's `credit_balance_cents` and then being set to 0; every service order on the booking whose `approval_status` is `PENDING_APPROVAL` or `APPROVED` moves to `CANCELLED` with its `billing_status` moved to `VOID`; the space's `committed_space_days` decreases by this booking's `space_days_committed`; and `order_posture` is recomputed to `LOCKED`."

    Design: Corner/state_machines/booking_release_cascades_down_to_hold_license_and_space_ledger
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    client = register_client(api, deposit_cents=200_000)
    booking = create_booking(api, client["id"], space["id"])
    hold = place_hold(api, booking["id"])
    license_row = draft_license(api, booking["id"])
    issue_license(api, license_row["id"])

    response = api.release_booking(booking["id"], headers=SALES_MANAGER)
    validate_success(response, 200)

    assert_fields(read_booking(api, booking["id"]), status="RELEASED")
    assert_fields(read_hold(api, hold["id"]), status="RELEASED")
    voided = read_license(api, license_row["id"])
    assert_fields(voided, status="VOIDED")
    assert_money_cents(voided["deposit_held_cents"], 0, "deposit_held_cents")
    assert_money_cents(
        read_client(api, client["id"])["credit_balance_cents"],
        200_000,
        "credit_balance_cents",
    )
    assert_fields(read_space(api, space["id"]), committed_space_days=0)


def test_booking_creation_syncs_the_space_day_ledger_on_the_parent_space(api):
    """PRD §3.2: "`space_days_committed` is the inclusive number of days from `move_in_start_date` through `move_out_end_date` — the difference in calendar days plus one — and the named space's `committed_space_days` rises by exactly that figure."

    PRD §2.9: "`SpaceUnit.committed_space_days` is the sum of `space_days_committed` over the bookings placed on that space or on any of its descendant spaces whose `status` is one of `TENTATIVE`, `DEFINITE`, `IN_HOUSE`, `CLOSED` or `SETTLED`."

    Design: Corner/state_machines/booking_creation_syncs_the_space_day_ledger_on_the_parent_space
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B)
    client = register_client(api)
    first = create_booking(
        api,
        client["id"],
        space["id"],
        event_name="Sunbelt Home Show",
        move_in_start_date="2027-06-08",
        show_start_date="2027-06-10",
        show_end_date="2027-06-12",
        move_out_end_date="2027-06-13",
    )

    response = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="Sunbelt Autumn Market",
            move_in_start_date="2027-09-06",
            show_start_date="2027-09-08",
            show_end_date="2027-09-10",
            move_out_end_date="2027-09-11",
        ),
        headers=SALES_MANAGER,
    )
    second = validate_success(response, 201)

    space_after = validate_success(
        api.get_space(space["id"], headers=FACILITIES_PLANNER), 200
    )

    assert_fields(read_booking(api, first["id"]), space_days_committed=6)
    assert_fields(second, space_days_committed=6)
    assert_fields(space_after, committed_space_days=12)


def test_hold_release_compensates_by_renumbering_the_surviving_holds(api):
    """PRD §3.3: "When a hold leaves the hierarchy by moving to `RELEASED`, the surviving members of *that* hold's competitor set are re-ranked: order them by their existing `hold_rank` ascending and break ties by `created_at` ascending — never by `id` — and reassign ranks 1, 2, 3 and so on down the list."

    PRD §3.3: "**Releasing a hold** voluntarily drives `ACTIVE → RELEASED`; a `SalesManager` or a `VenueAdmin` may do it on any `ACTIVE` hold, decrementing the booking's `hold_count` by 1 and re-ranking the survivors."

    Design: Corner/state_machines/hold_release_compensates_by_renumbering_the_surviving_holds
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B)
    sunbelt = register_client(api)
    riverbend = register_client(api, **RIVERBEND_ROTARY)
    national = register_client(api, **NATIONAL_WIDGET_ASSOCIATION)

    interval = {
        "move_in_start_date": "2027-06-08",
        "show_start_date": "2027-06-10",
        "show_end_date": "2027-06-12",
        "move_out_end_date": "2027-06-13",
    }
    booking_one = create_booking(
        api, sunbelt["id"], space["id"], event_name="Sunbelt Home Show", **interval
    )
    booking_two = create_booking(
        api, riverbend["id"], space["id"], event_name="Rotary Antiques Fair", **interval
    )
    booking_three = create_booking(
        api, national["id"], space["id"], event_name="Widget Regional Expo", **interval
    )
    hold_one = place_hold(api, booking_one["id"])
    hold_two = place_hold(api, booking_two["id"])
    hold_three = place_hold(api, booking_three["id"])

    response = api.release_hold(hold_one["id"], headers=SALES_MANAGER)
    validate_success(response, 200)

    assert_fields(read_hold(api, hold_one["id"]), status="RELEASED")
    assert_fields(read_hold(api, hold_two["id"]), hold_rank=1, status="ACTIVE")
    assert_fields(read_hold(api, hold_three["id"]), hold_rank=2, status="ACTIVE")
    assert_fields(read_booking(api, booking_one["id"]), hold_count=0, status="TENTATIVE")
    assert_fields(read_booking(api, booking_two["id"]), hold_count=1)


def test_hold_sweep_releases_only_the_hold_whose_release_deadline_has_passed(api):
    """PRD §3.3: "Every hold whose `status` is `CHALLENGED` and whose `challenge_deadline_utc` has strictly passed moves `CHALLENGED → RELEASED`; every hold whose `status` is `ACTIVE` and whose `release_deadline_utc` has strictly passed likewise moves to `RELEASED`."

    PRD §3.3: "Each release decrements the owning booking's `hold_count` by 1, and a booking whose `hold_count` reaches 0 while its `status` is `TENTATIVE` moves to `RELEASED` and runs the full release cascade — which voids a `DRAFT` or `ISSUED` license, returns its `deposit_held_cents` to the client's `credit_balance_cents`, and cancels every service order in `PENDING_APPROVAL` or `APPROVED` with `billing_status` `VOID`."
    PRD §3.3: "The sweep reports four counters: `expired_challenge_count`, `released_hold_count`, `promoted_hold_count` and `released_booking_count`."

    Design: Corner/state_machines/hold_sweep_releases_only_the_hold_whose_release_deadline_has_passed
    """
    publish_window(api, "CONSUMER_SHOW")
    publish_window(api, "LOCAL_EVENT")
    ballroom_b = register_space(api, **BALLROOM_B)
    ballroom_c = register_space(api, **BALLROOM_C)
    sunbelt = register_client(api)
    riverbend = register_client(api, **RIVERBEND_ROTARY)

    booking_near = create_booking(
        api,
        sunbelt["id"],
        ballroom_b["id"],
        event_name="Sunbelt Home Show",
        move_in_start_date="2027-06-08",
        show_start_date="2027-06-10",
        show_end_date="2027-06-12",
        move_out_end_date="2027-06-13",
    )
    booking_far = create_booking(
        api,
        riverbend["id"],
        ballroom_c["id"],
        event_name="Rotary Summer Gala",
        event_class="LOCAL_EVENT",
        move_in_start_date="2028-06-08",
        show_start_date="2028-06-10",
        show_end_date="2028-06-12",
        move_out_end_date="2028-06-13",
    )
    hold_near = place_hold(api, booking_near["id"])
    hold_far = place_hold(api, booking_far["id"])
    set_clock(api, "2027-03-11T00:00:00Z")

    sweep = validate_success(api.run_hold_sweep(headers=VENUE_ADMIN), 200)
    assert_fields(
        sweep,
        expired_challenge_count=0,
        released_hold_count=1,
        promoted_hold_count=0,
        released_booking_count=1,
    )

    assert_fields(read_hold(api, hold_near["id"]), status="RELEASED")
    assert_fields(read_hold(api, hold_far["id"]), status="ACTIVE", hold_rank=1)
    assert_fields(read_booking(api, booking_near["id"]), status="RELEASED")
    assert_fields(read_booking(api, booking_far["id"]), status="TENTATIVE")
    assert_fields(read_space(api, ballroom_b["id"]), committed_space_days=0)
    assert_fields(read_space(api, ballroom_c["id"]), committed_space_days=6)
