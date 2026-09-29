"""Endpoint round trips, action endpoints and derived read-side figures.

A write-then-read pair, two action endpoints, the bulk membership sweep, the
box-office rollup projected onto a screening, and the four-condition completion.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_distributor,
    assert_fresh_resource,
    assert_screen_block,
    assert_seat_conservation,
    assert_special_event,
    close_showtime_sales,
    distributor_payload,
    enrol_member,
    lodge_donation,
    open_showtime_sales,
    pay_for_order,
    place_showtime,
    plan_event,
    read_booking,
    read_clearance,
    read_kdm,
    read_member,
    read_showtime,
    sell_seats,
    set_logical_clock,
    setup_programming_baseline,
    setup_screening_on_sale,
    setup_verified_screening,
    sweep_memberships,
    validate_error,
    validate_paginated,
    validate_success,
)

PROGRAMMER = TEST_USERS["programmer_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
EXECUTIVE_DIRECTOR = TEST_USERS["executive_director_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


class TestWriteThenRead:

    def test_distributor_create_then_read_round_trip(self, api):
        """PRD §3.1: "Distributors and licensors are registered by a `Programmer`
        or an `ExecutiveDirector` with a trading `name`, a booking-desk
        `contact_email`, and the terms this counterparty normally demands:
        `default_terms_variant`, which is one of `SLIDING_SCALE_90_10`,
        `PERCENTAGE_FLOOR` or `FLAT_FEE`; `default_min_run_days`, at least 1
        playing day; `default_distributor_share_pct`, a fraction between 0 and 1
        inclusive; and `requires_advance_guarantee`, a flag defaulting to false."

        PRD §2.4: "`version` is an integer that starts at 1 and increments by
        exactly 1 on every mutation of that row, including mutations produced by a
        cascade rather than by a direct call to that resource."

        Design: Corner/endpoints/distributor_create_then_read_round_trip
        """
        created = validate_success(
            api.create_distributor(
                distributor_payload(
                    name="Coyote Films",
                    contact_email="book@coyote.example",
                    default_terms_variant="SLIDING_SCALE_90_10",
                    default_min_run_days=4,
                    default_distributor_share_pct=0.35,
                    requires_advance_guarantee=False,
                ),
                PROGRAMMER,
            ),
            expected_status=201,
        )

        # The read-back is issued by a different permitted role.
        read = validate_success(
            api.get_distributor(created["id"], EXECUTIVE_DIRECTOR), expected_status=200
        )

        assert read["id"] == created["id"], (
            f"Expected the same id, got {read['id']} vs {created['id']}"
        )
        assert_distributor(read)
        assert read["name"] == "Coyote Films", (
            f"Expected 'Coyote Films', got {read['name']!r}"
        )
        assert read["contact_email"] == "book@coyote.example", (
            f"Expected book@coyote.example, got {read['contact_email']!r}"
        )
        assert read["default_terms_variant"] == "SLIDING_SCALE_90_10", (
            f"Expected SLIDING_SCALE_90_10, got {read['default_terms_variant']}"
        )
        assert read["default_min_run_days"] == 4, (
            f"Expected default_min_run_days 4, got {read['default_min_run_days']}"
        )
        assert read["default_distributor_share_pct"] == 0.35, (
            "Expected the fraction 0.35 preserved, got "
            f"{read['default_distributor_share_pct']!r}"
        )
        assert read["requires_advance_guarantee"] is False, (
            "Expected the posted false preserved rather than coerced, got "
            f"{read['requires_advance_guarantee']!r}"
        )
        assert_fresh_resource(read)


class TestActionEndpoints:

    def test_clearance_request_changes_moves_the_licence_and_records_the_note(
        self, api
    ):
        """PRD §3.3: "A `RightsManager` or an `ExecutiveDirector` may send a
        `SUBMITTED` licence back for amendment, which moves it `SUBMITTED →
        CHANGES_REQUESTED` and stores the supplied `change_request_note`."

        PRD §3.3: "Creation *is* submission: the licence appears directly in
        `SUBMITTED`, its `submitted_by_user_id` recorded from the acting
        `X-User-ID` as the segregation-of-duties subject, its `screenings_used` at
        0 and its `screenings_remaining` equal to `max_screenings`, with
        `cleared_by_user_id`, `change_request_note` and `revoked_reason` all null."

        Design: Corner/endpoints/request_changes_action_moves_the_clearance_and_records_the_note
        """
        world = setup_programming_baseline(clear=False)
        clearance_id = world["clearance"]["id"]
        assert world["clearance"]["status"] == "SUBMITTED", (
            f"Expected SUBMITTED, got {world['clearance']['status']}"
        )

        amended = validate_success(
            api.request_clearance_changes(
                clearance_id,
                {"change_request_note": "Territory must exclude US-NY-BROOKLYN"},
                EXECUTIVE_DIRECTOR,
            ),
            expected_status=200,
        )

        assert amended["status"] == "CHANGES_REQUESTED", (
            f"Expected CHANGES_REQUESTED, got {amended['status']}"
        )
        assert amended["change_request_note"] == (
            "Territory must exclude US-NY-BROOKLYN"
        ), f"Expected the posted note stored, got {amended['change_request_note']!r}"
        assert amended["cleared_by_user_id"] is None, (
            "Requesting changes is not a clearance, so cleared_by_user_id must "
            f"stay null, got {amended['cleared_by_user_id']!r}"
        )
        assert amended["submitted_by_user_id"] == "u-rm-1", (
            "Expected the original lodger still recorded, got "
            f"{amended['submitted_by_user_id']!r}"
        )
        assert amended["screenings_used"] == 0, (
            f"Expected screenings_used 0, got {amended['screenings_used']}"
        )
        assert amended["screenings_remaining"] == 6, (
            f"Expected screenings_remaining 6, got {amended['screenings_remaining']}"
        )
        assert amended["version"] == 2, (
            f"Expected version 2 after exactly one write, got {amended['version']}"
        )
        assert read_clearance(clearance_id)["status"] == "CHANGES_REQUESTED", (
            "The stored row must agree with the action response"
        )

    def test_special_event_links_to_its_showtime_without_extending_the_block(
        self, api
    ):
        """PRD §3.6: "The event is created in `PLANNED` with an empty
        `displaced_showtime_ids` list, and — this is the part that surprises
        people — the screening's block is **not** yet extended. A planned event
        changes nothing about the calendar."

        PRD §3.5: "The screening's on-screen content runs for the auditorium's
        `trailer_reel_minutes` plus the title's `runtime_minutes` plus the
        screening's own `extra_minutes`, which is 0 at creation; `end_at` is
        `start_at` advanced by that total number of minutes, and `blocked_until`
        is `end_at` advanced by the auditorium's `turnaround_minutes`."

        Design: Corner/endpoints/special_event_links_to_its_showtime_without_extending_the_block
        """
        world = setup_programming_baseline()
        showtime = place_showtime(world, "2026-08-14T12:00:00Z")
        assert_screen_block(
            showtime, "2026-08-14T13:56:00.000Z", "2026-08-14T14:21:00.000Z"
        )

        event = plan_event(
            showtime["id"],
            guest_name="Rina Okada",
            extra_minutes=30,
            surcharge_cents=500,
            guest_fee_cents=40000,
        )

        assert_special_event(event)
        assert event["status"] == "PLANNED", (
            f"Expected PLANNED, got {event['status']}"
        )
        assert event["showtime_id"] == showtime["id"], (
            f"Expected the link to {showtime['id']}, got {event['showtime_id']}"
        )
        assert event["event_type"] == "FILMMAKER_QA", (
            f"Expected FILMMAKER_QA, got {event['event_type']}"
        )
        assert event["guest_name"] == "Rina Okada", (
            f"Expected 'Rina Okada', got {event['guest_name']!r}"
        )
        assert event["extra_minutes"] == 30, (
            f"Expected extra_minutes 30 on the event, got {event['extra_minutes']}"
        )
        assert event["surcharge_cents"] == 500, (
            f"Expected surcharge_cents 500, got {event['surcharge_cents']}"
        )
        assert event["guest_fee_cents"] == 40000, (
            f"Expected guest_fee_cents 40000, got {event['guest_fee_cents']}"
        )
        assert event["displaced_showtime_ids"] == [], (
            f"Nothing may be displaced yet, got {event['displaced_showtime_ids']}"
        )

        after = read_showtime(showtime["id"])
        assert after["extra_minutes"] == 0, (
            "The screening's own extra_minutes stays 0 until confirmation, got "
            f"{after['extra_minutes']}"
        )
        assert after["surcharge_cents"] == 0, (
            f"Expected the screening surcharge still 0, got {after['surcharge_cents']}"
        )
        assert_screen_block(
            after, "2026-08-14T13:56:00.000Z", "2026-08-14T14:21:00.000Z"
        )
        rows, _meta = validate_paginated(
            api.list_special_events(PROGRAMMER, params={"showtime_id": showtime["id"]})
        )
        assert len(rows) == 1, f"Expected exactly 1 event on the screening, got {len(rows)}"

    def test_membership_sweep_lapses_only_the_expired_member(self, api):
        """PRD §3.7: "Lapsing is a batch operation the `ExecutiveDirector` runs:
        it moves every `ACTIVE` member whose `expires_at` is **strictly** earlier
        than the logical clock to `LAPSED`, so a member whose `expires_at` equals
        the clock exactly does **not** lapse."

        PRD §3.7: "The sweep's response is not a member object but a summary
        carrying `swept_count`, the integer number of memberships lapsed,
        `lapsed_member_ids`, the list of their ids, and `evaluated_at`, the logical
        instant the sweep was evaluated against."

        PRD §3.7: "The sweep recomputes standing for each swept member at the
        sweep clock, so `discount_pct`, `advance_access_hours` and
        `comp_tickets_remaining` all follow from the recomputed `effective_tier` —
        in practice a member lapses because their giving has fallen out of both
        windows, so those benefits fall away — while `credit_balance_cents` and
        the `donations` history are retained untouched and are never zeroed."

        Design: Corner/endpoints/membership_sweep_lapses_only_the_expired_member
        """
        ada = enrol_member(full_name="Ada Wells", email="ada@example.com")
        ada = lodge_donation(ada["id"], 20000, "2026-03-01T10:00:00Z")
        assert ada["expires_at"] == "2027-03-01T10:00:00.000Z", (
            f"Expected expires_at 2027-03-01T10:00:00.000Z, got {ada['expires_at']}"
        )

        bo = enrol_member(full_name="Bo Lin", email="bo@example.com")
        bo = lodge_donation(bo["id"], 8000, "2026-07-15T10:00:00Z")
        assert bo["expires_at"] == "2027-07-15T10:00:00.000Z", (
            f"Expected expires_at 2027-07-15T10:00:00.000Z, got {bo['expires_at']}"
        )
        assert bo["status"] == "ACTIVE", f"Expected ACTIVE, got {bo['status']}"
        bo_version_before = read_member(bo["id"])["version"]

        # The sweep instant deliberately straddles the two expiry stamps.
        set_logical_clock("2027-04-01T00:00:00Z")
        summary = sweep_memberships()

        assert summary["swept_count"] == 1, (
            f"Expected swept_count 1, got {summary['swept_count']}"
        )
        assert summary["lapsed_member_ids"] == [ada["id"]], (
            f"Expected only Ada lapsed, got {summary['lapsed_member_ids']}"
        )
        assert summary["evaluated_at"] == "2027-04-01T00:00:00.000Z", (
            f"Expected evaluated_at 2027-04-01T00:00:00.000Z, got {summary['evaluated_at']}"
        )

        lapsed = read_member(ada["id"])
        assert lapsed["status"] == "LAPSED", (
            f"Expected LAPSED, got {lapsed['status']}"
        )
        assert lapsed["rolling_donation_cents"] == 0, (
            "The 2026-03-01 gift has fallen out of the trailing 365 days, so the "
            f"rolling figure must be 0, got {lapsed['rolling_donation_cents']}"
        )
        assert lapsed["expires_at"] == "2027-03-01T10:00:00.000Z", (
            "Lapsing records the fact rather than rewriting history, got "
            f"{lapsed['expires_at']}"
        )
        assert lapsed["credit_balance_cents"] == 0, (
            f"Expected credit retained at 0, got {lapsed['credit_balance_cents']}"
        )
        assert lapsed["discount_pct"] == 0.00, (
            f"Expected discount_pct 0.00 after recomputation, got {lapsed['discount_pct']}"
        )
        assert lapsed["advance_access_hours"] == 0, (
            f"Expected advance_access_hours 0, got {lapsed['advance_access_hours']}"
        )
        assert len(lapsed["donations"]) == 1, (
            f"The donation history is never zeroed, got {lapsed['donations']}"
        )

        # The non-qualifying row was skipped, not failed on and not rewritten.
        survivor = read_member(bo["id"])
        assert survivor["status"] == "ACTIVE", (
            f"Expected Bo still ACTIVE, got {survivor['status']}"
        )
        assert survivor["rolling_donation_cents"] == 8000, (
            f"Expected rolling 8000, got {survivor['rolling_donation_cents']}"
        )
        assert survivor["version"] == bo_version_before, (
            f"Expected the untouched row still at version {bo_version_before}, "
            f"got {survivor['version']}"
        )

        second = sweep_memberships()
        assert second["swept_count"] == 0, (
            f"A repeat sweep has nothing left to do, got {second['swept_count']}"
        )
        assert second["lapsed_member_ids"] == [], (
            f"Expected an empty list, got {second['lapsed_member_ids']}"
        )


class TestDerivedReads:

    def test_showtime_read_exposes_the_rollup_derived_from_its_orders(self, api):
        """PRD §2.10: "A screening's `seats_sold` is the sum of `quantity` across
        its orders whose status is reserved or paid; its `seats_available` is the
        venue's `seat_capacity` less the venue's `house_hold_seats` less
        `seats_sold`, and never falls below zero; its `gross_cents` is the sum of
        `total_cents` across its paid orders and its `admissions_count` the sum of
        their `quantity`."

        PRD §2.10: "After every mutation, including every cascade, the identity
        holds that `seats_sold` plus `seats_available` plus the venue's
        `house_hold_seats` equals the venue's `seat_capacity` — the house hold
        seats are permanently withheld from sale and are never sellable."

        Design: Corner/endpoints/showtime_read_exposes_the_rollup_derived_from_its_orders
        """
        world = setup_screening_on_sale("2026-08-14T12:00:00Z")
        showtime_id = world["showtime"]["id"]

        paid = sell_seats(
            showtime_id, 3, headers=ANONYMOUS, purchaser_email="paid@example.com"
        )
        pay_for_order(paid["id"])
        reserved = sell_seats(
            showtime_id, 2, headers=ANONYMOUS, purchaser_email="hold@example.com"
        )
        assert reserved["status"] == "RESERVED", (
            f"Expected RESERVED, got {reserved['status']}"
        )

        # POST /ticket-orders and GET /showtimes/{id} both list the anonymous
        # role, so a walk-up browser may read the same projection.
        anonymous_view = validate_success(
            api.get_showtime(showtime_id, ANONYMOUS), expected_status=200
        )

        assert anonymous_view["seats_sold"] == 5, (
            "Both RESERVED and PAID orders hold seats, so seats_sold must be 5, "
            f"got {anonymous_view['seats_sold']}"
        )
        assert anonymous_view["seats_available"] == 3, (
            f"Expected seats_available 3, got {anonymous_view['seats_available']}"
        )
        assert anonymous_view["gross_cents"] == 4800, (
            "Only the paid order contributes money, so gross_cents must be 4800, "
            f"got {anonymous_view['gross_cents']}"
        )
        assert anonymous_view["admissions_count"] == 3, (
            "admissions_count follows the paid seats rather than the sold seats, "
            f"got {anonymous_view['admissions_count']}"
        )
        assert anonymous_view["sale_status"] == "ON_SALE", (
            f"Expected ON_SALE while seats remain, got {anonymous_view['sale_status']}"
        )
        assert_seat_conservation(anonymous_view, world["venue"])

        staff_view = validate_success(
            api.get_showtime(showtime_id, BOX_OFFICE), expected_status=200
        )
        for field in (
            "seats_sold", "seats_available", "gross_cents", "admissions_count",
            "sale_status",
        ):
            assert staff_view[field] == anonymous_view[field], (
                f"The projection must not vary by caller: {field} read "
                f"{staff_view[field]} for staff and {anonymous_view[field]} "
                "for a walk-up"
            )

    def test_showtime_complete_is_refused_until_sales_playback_and_clock_agree(
        self, api
    ):
        """PRD §3.8: "Four conditions must hold, and any failure yields
        `ERR_SHOWTIME_INVALID_STATE`: the screening's status is `SCHEDULED`, its
        `sale_status` is `SALES_CLOSED`, its `playback_status` is
        `PLAYBACK_VERIFIED`, and the logical clock has reached or passed its
        `end_at`."

        PRD §3.8: "Completion moves the screening `SCHEDULED → COMPLETED` and
        freezes `gross_cents` and `admissions_count` from its paid orders. If the
        owning engagement is still `CONFIRMED`, this is also the moment it bubbles
        up to `RUNNING`."

        Design: Corner/endpoints/complete_is_refused_until_sales_playback_and_the_clock_all_agree
        """
        # An encrypted package walked to INGESTED, a covering key and a PASS booth
        # test, so playback_status is already PLAYBACK_VERIFIED.
        world = setup_verified_screening("2026-08-14T12:00:00Z")
        showtime_id = world["showtime"]["id"]
        assert world["showtime"]["playback_status"] == "PLAYBACK_VERIFIED", (
            f"Expected PLAYBACK_VERIFIED, got {world['showtime']['playback_status']}"
        )
        assert_screen_block(
            world["showtime"], "2026-08-14T13:56:00.000Z", "2026-08-14T14:21:00.000Z"
        )

        open_showtime_sales(showtime_id)
        paid = sell_seats(
            showtime_id, 3, headers=ANONYMOUS, purchaser_email="paid@example.com"
        )
        pay_for_order(paid["id"])
        closed = close_showtime_sales(showtime_id)
        assert closed["sale_status"] == "SALES_CLOSED", (
            f"Expected SALES_CLOSED, got {closed['sale_status']}"
        )

        # Three of the four conditions hold; the clock is still 2026-08-01.
        refused = api.complete_showtime(showtime_id, BOX_OFFICE)
        validate_error(refused, ApiErrorId.ERR_SHOWTIME_INVALID_STATE.value)

        assert read_showtime(showtime_id)["status"] == "SCHEDULED", (
            "The refused completion must leave the screening SCHEDULED"
        )
        assert read_booking(world["booking"]["id"])["status"] == "CONFIRMED", (
            "Nothing may bubble up on a refused completion"
        )

        set_logical_clock("2026-08-14T14:00:00Z")
        completed = validate_success(
            api.complete_showtime(showtime_id, BOX_OFFICE), expected_status=200
        )

        assert completed["status"] == "COMPLETED", (
            f"Expected COMPLETED, got {completed['status']}"
        )
        assert completed["gross_cents"] == 4800, (
            f"Expected gross_cents frozen at 4800, got {completed['gross_cents']}"
        )
        assert completed["admissions_count"] == 3, (
            f"Expected admissions_count 3, got {completed['admissions_count']}"
        )
        assert completed["sale_status"] == "SALES_CLOSED", (
            f"Expected SALES_CLOSED preserved, got {completed['sale_status']}"
        )
        assert completed["playback_status"] == "PLAYBACK_VERIFIED", (
            f"Expected PLAYBACK_VERIFIED preserved, got {completed['playback_status']}"
        )
        assert read_booking(world["booking"]["id"])["status"] == "RUNNING", (
            "The CONFIRMED to RUNNING bubble-up must fire on completion"
        )
        assert read_kdm(world["key"]["id"])["status"] == "ISSUED", (
            "valid_until 14:30 is still ahead of the clock, so the key stands"
        )
