"""Party bookings: quote computation, deposit clamp, HELD initial state,
the confirm gates, the reschedule cycle, cancellation waterfall with cafe
and loyalty cascade, cleanup-buffer conflict semantics, and booking OCC
(PRD §2.7, §2.9, §3.7, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_DEFAULTS,
    set_clock, reset_clock, run_ops_as_admin,
    setup_staff_trio, make_staff, staff_headers,
    create_std_package, create_party_room, book_party, current_room_version,
    setup_party_context, setup_confirmed_booking, register_guardian,
    guardian_headers, create_menu_item, place_order, seed_points,
    create_sanitation_task, get_guardian_fresh,
    create_party_booking_payload, TEST_USERS,
)
from test_helpers import api_client

TEST_USERS_ADMIN = TEST_USERS["admin_headers"]


class TestBookingInitialState:
    def test_party_booking_created_in_held(self, api):
        """PRD §3.7: "A created booking starts `HELD`."

        Design: Corner/state_machines/party_booking_created_in_held
        """
        ctx = setup_party_context(email="gh@x.com")
        booking = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                             start_at=TEST_DEFAULTS["WEEKDAY_PARTY_START"],
                             child_count=10)
        assert booking["status"] == "HELD"
        assert booking["deposit_paid"] is False


class TestPartyQuote:
    def test_party_quote_multi_input_nonlinear(self, api):
        """PRD §3.7: "Extra children are the excess of `child_count` over the
        package's `included_children`, floored at zero; the subtotal is the
        `base_price_cents` plus one `extra_child_price_cents` per extra child.
        When the party starts on a Saturday or Sunday (UTC), a peak surcharge
        of fifteen percent of the subtotal, rounded half-up, is added. The
        membership discount fraction is the guardian's plan
        `party_discount_pct` when membership is `ACTIVE`, otherwise zero,
        capped at twenty-five percent; the discount is that fraction applied
        to the subtotal plus the surcharge, rounded half-up. The
        `quoted_total_cents` is the subtotal plus the surcharge minus the
        discount, and the `deposit_cents` is the greater of 5,000 cents and
        twenty percent of the quoted total rounded half-up".

        Saturday 14-child STD booking for a PLUS (10%) member: extra 4x1500,
        subtotal 36000, peak 5400, discount 4140 -> total 37260, deposit 7452.

        Design: Difficulty/combinatorial_formula/party_quote_multi_input_nonlinear
        """
        ctx = setup_party_context(with_plan=True, email="g3@x.com")
        booking = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                             start_at="2026-06-06T10:00:00Z",  # Saturday
                             child_count=14)
        assert booking["quoted_total_cents"] == 37260
        assert booking["deposit_cents"] == 7452
        assert booking["end_at"].startswith("2026-06-06T12:00:00")
        assert booking["status"] == "HELD"

    def test_party_discount_capped_at_twenty_five_percent(self, api):
        """PRD §3.7: "The membership discount fraction is the guardian's plan
        `party_discount_pct` when membership is `ACTIVE`, otherwise zero,
        capped at twenty-five percent; the discount is that fraction applied
        to the subtotal plus the surcharge, rounded half-up."

        A plan advertising 40% is capped at 25%: weekday 10-child STD booking
        -> subtotal 30000, discount 7500, total 22500, deposit
        max(5000, 4500) = 5000.

        Design: Difficulty/combinatorial_formula/party_quote_multi_input_nonlinear
        """
        ctx = setup_party_context(email="g3c@x.com")
        from test_helpers import create_plus_plan, enroll_guardian
        plan = create_plus_plan(party_discount_pct=0.40)
        enroll_guardian(ctx["guardian"], plan["id"])
        booking = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                             start_at="2026-06-08T10:00:00Z",  # Monday
                             child_count=10)
        assert booking["quoted_total_cents"] == 22500
        assert booking["deposit_cents"] == 5000


class TestDepositClamp:
    def test_party_deposit_minimum_clamp_applies(self, api):
        """PRD §3.7: "the `deposit_cents` is the greater of 5,000 cents and
        twenty percent of the quoted total rounded half-up — a fifty-dollar
        floor with a one-fifth rule above it."

        A 20,000-cent weekday quote puts twenty percent (4,000) below the
        floor, so the deposit is exactly 5,000.

        Design: Corner/calculations/party_deposit_minimum_clamp_applies
        """
        ctx = setup_party_context(
            email="gn@x.com",
            package_overrides={"name": "SMALL", "duration_minutes": 90,
                               "base_price_cents": 20000,
                               "extra_child_price_cents": 1200,
                               "cafe_credit_cents": 0})
        booking = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                             start_at="2026-06-08T10:00:00Z",  # Monday
                             child_count=8)
        assert booking["quoted_total_cents"] == 20000
        assert booking["deposit_cents"] == 5000


class TestConfirmGates:
    def test_party_confirm_gated_by_room_state(self, api):
        """PRD §3.7: "Confirming is the guardian's own act: it requires the
        room still `ACTIVE` (else `ERR_ROOM_INACTIVE`)".

        The booking sits in the correct HELD state, but a MAINTENANCE room
        gates the transition.

        Design: Difficulty/cross_entity_state_dependency/party_confirm_gated_by_room_state
        """
        ctx = setup_party_context(email="gr@x.com")
        booking = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                             start_at="2026-06-08T10:00:00Z", child_count=10)
        validate_success(api_client.patch_party_room(
            ctx["room"]["id"], {"status": "MAINTENANCE"},
            TEST_USERS_ADMIN), 200)

        res = api_client.confirm_party_booking(booking["id"], ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_ROOM_INACTIVE, expected_status=422)

        fresh = get_success_data(
            api_client.get_party_booking(booking["id"], ctx["g_headers"]))
        assert fresh["status"] == "HELD"
        assert fresh["deposit_paid"] is False

    def test_party_confirm_rejected_when_room_closed(self, api):
        """PRD §3.7: "it requires the room still `ACTIVE` (else
        `ERR_ROOM_INACTIVE`)".

        A CLOSED room fails the same gate.

        Design: Difficulty/cross_entity_state_dependency/party_confirm_gated_by_room_state
        """
        ctx = setup_party_context(email="gr2b@x.com")
        booking = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                             start_at="2026-06-08T10:00:00Z", child_count=10)
        validate_success(api_client.patch_party_room(
            ctx["room"]["id"], {"status": "CLOSED"}, TEST_USERS_ADMIN), 200)

        res = api_client.confirm_party_booking(booking["id"], ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_ROOM_INACTIVE, expected_status=422)
        fresh = get_success_data(
            api_client.get_party_booking(booking["id"], ctx["g_headers"]))
        assert fresh["status"] == "HELD"

    def test_booking_with_retired_package_rejected(self, api):
        """PRD §3.7: "Both the room and the package must be `ACTIVE` —
        otherwise `ERR_ROOM_INACTIVE` or `ERR_PACKAGE_RETIRED` respectively
        (both HTTP 422)".

        Design: Corner/validations/booking_with_retired_package_rejected
        """
        reset_clock()
        package = create_std_package()
        validate_success(api_client.patch_party_package(
            package["id"], {"status": "RETIRED"}, TEST_USERS_ADMIN), 200)
        room = create_party_room()
        guardian = register_guardian("G X", "gx2@x.com", "923")
        res = api_client.create_party_booking(
            create_party_booking_payload(
                room["id"], package["id"], guardian["id"],
                expected_party_room_version=current_room_version(room["id"]),
                start_at="2026-06-08T10:00:00Z", child_count=10),
            guardian_headers(guardian))
        validate_error(res, ApiErrorId.ERR_PACKAGE_RETIRED, expected_status=422)

    def test_sanitation_overdue_blocks_party_confirm(self, api):
        """PRD §3.7: "no `OVERDUE` sanitation task on that room (else
        `ERR_SANITATION_OVERDUE`, HTTP 422)".
        PRD §3.8: "The operations sweep flags any task whose `due_at` has been
        reached while still `SCHEDULED` or `IN_PROGRESS` as `OVERDUE`".

        Design: Corner/validations/sanitation_overdue_blocks_party_confirm
        """
        staff = setup_staff_trio()
        ctx = setup_party_context(email="gy2@x.com")
        task = create_sanitation_task(staff["mgr_headers"], ctx["room"],
                                      due_at="2026-06-02T00:00:00Z")
        set_clock("2026-06-03T08:00:00Z")
        # Booking created at the advanced clock: a HELD booking is expired by
        # the sweep 24h after created_at (PRD §3.7), so it must be younger
        # than the overdue sanitation task it is gated by.
        booking = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                             start_at="2026-06-08T10:00:00Z", child_count=10)
        run_ops_as_admin()

        res = api_client.confirm_party_booking(booking["id"], ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_SANITATION_OVERDUE,
                       expected_status=422)
        fresh = get_success_data(
            api_client.get_party_booking(booking["id"], ctx["g_headers"]))
        assert fresh["status"] == "HELD"


class TestRescheduleCycle:
    def test_party_booking_reschedule_cycle(self, api):
        """PRD §3.7: "The guardian may request a reschedule, moving
        `CONFIRMED` to `RESCHEDULE_REQUESTED` and recording a
        `proposed_start_at`". "Approval is a `Manager` decision: the proposed
        window is re-checked for room conflicts including the cleanup buffer
        (else `ERR_ROOM_TIME_CONFLICT`), and on approval the booking's
        `start_at` becomes the `proposed_start_at`, `end_at` is recomputed
        from the package duration, the full quote — peak flag included, since
        the new date may fall on a weekend — is recomputed, and the booking
        returns to `CONFIRMED`, completing the cycle."

        Saturday -> Sunday: both peak, so the quote is unchanged at 31,050
        (30,000 + 4,500 peak - 3,450 = 10% of 34,500).

        Design: Difficulty/non_linear_state_machine/party_booking_reschedule_cycle
        """
        staff = setup_staff_trio()
        ctx = setup_party_context(with_plan=True, email="g6@x.com")
        booking = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                             start_at="2026-06-06T10:00:00Z",  # Saturday
                             child_count=10)
        assert booking["quoted_total_cents"] == 31050
        validate_success(api_client.confirm_party_booking(
            booking["id"], ctx["g_headers"]), 200)

        requested = validate_success(api_client.request_reschedule(
            booking["id"], {"proposed_start_at": "2026-06-07T10:00:00Z"},
            ctx["g_headers"]), 200)
        assert requested["status"] == "RESCHEDULE_REQUESTED"

        approved = validate_success(api_client.approve_reschedule(
            booking["id"], staff["mgr_headers"]), 200)
        assert approved["status"] == "CONFIRMED"
        assert approved["start_at"].startswith("2026-06-07T10:00:00")
        assert approved["end_at"].startswith("2026-06-07T12:00:00")
        assert approved["quoted_total_cents"] == 31050, \
            "Sunday is also peak, so the re-quote is unchanged"

    def test_reschedule_to_weekday_drops_peak_surcharge(self, api):
        """PRD §3.7: "the full quote — peak flag included, since the new date
        may fall on a weekend — is recomputed".

        Saturday -> Tuesday: the peak surcharge falls away, so the re-quote is
        30,000 - 3,000 (10% member discount) = 27,000.

        Design: Difficulty/non_linear_state_machine/party_booking_reschedule_cycle
        """
        staff = setup_staff_trio()
        ctx = setup_party_context(with_plan=True, email="g6b@x.com")
        booking = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                             start_at="2026-06-06T10:00:00Z", child_count=10)
        validate_success(api_client.confirm_party_booking(
            booking["id"], ctx["g_headers"]), 200)
        validate_success(api_client.request_reschedule(
            booking["id"], {"proposed_start_at": "2026-06-09T10:00:00Z"},
            ctx["g_headers"]), 200)

        approved = validate_success(api_client.approve_reschedule(
            booking["id"], staff["mgr_headers"]), 200)
        assert approved["status"] == "CONFIRMED"
        assert approved["start_at"].startswith("2026-06-09T10:00:00")
        assert approved["quoted_total_cents"] == 27000

    def test_reschedule_inside_cutoff_rejected(self, api):
        """PRD §3.7: "The guardian may request a reschedule, moving
        `CONFIRMED` to `RESCHEDULE_REQUESTED` and recording a
        `proposed_start_at`, but only while the logical clock is at least 48
        hours before the current `start_at`; inside that cutoff the request
        is rejected with `ERR_RESCHEDULE_CUTOFF` (HTTP 422)."

        At T-24h the request is rejected.

        Design: Corner/validations/reschedule_inside_cutoff_rejected
        """
        ctx = setup_confirmed_booking(start_at="2026-06-06T10:00:00Z",
                                      email="gt2@x.com")
        set_clock("2026-06-05T10:00:00Z")  # 24h before start
        res = api_client.request_reschedule(
            ctx["booking"]["id"], {"proposed_start_at": "2026-06-09T10:00:00Z"},
            ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_RESCHEDULE_CUTOFF,
                       expected_status=422)
        fresh = get_success_data(api_client.get_party_booking(
            ctx["booking"]["id"], ctx["g_headers"]))
        assert fresh["status"] == "CONFIRMED"


class TestCleanupBufferSemantics:
    def test_party_room_cleanup_buffer_semantics(self, api):
        """PRD §2.9: "every party occupies its booked window plus a
        thirty-minute cleanup buffer, and that extended interval is what must
        stay clear of other non-terminal bookings on the room."
        PRD §3.7: "the occupied interval, running from `start_at` through
        `end_at` plus a thirty-minute cleanup buffer and half-open at both
        ends, must not intersect any non-terminal booking on the same room,
        else `ERR_ROOM_TIME_CONFLICT` (HTTP 409)."

        Booking A [10:00, 12:00) occupies until 12:30; a booking at 12:00
        conflicts, one at exactly 12:30 is accepted.

        Design: Difficulty/resource_temporal_overlap/party_room_cleanup_buffer_semantics
        """
        ctx = setup_party_context(email="gp@x.com")
        book_party(ctx["guardian"], ctx["room"], ctx["package"],
                   start_at="2026-06-08T10:00:00Z", child_count=10)  # A

        res = api_client.create_party_booking(
            create_party_booking_payload(
                ctx["room"]["id"], ctx["package"]["id"], ctx["guardian"]["id"],
                expected_party_room_version=current_room_version(ctx["room"]["id"]),
                start_at="2026-06-08T12:00:00Z", child_count=10),
            ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_ROOM_TIME_CONFLICT,
                       expected_status=409)

        booking_c = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                               start_at="2026-06-08T12:30:00Z", child_count=10)
        assert booking_c["status"] == "HELD"
        assert booking_c["end_at"].startswith("2026-06-08T14:30:00")

    def test_approve_reschedule_rechecks_conflict_including_buffer(self, api):
        """PRD §3.7: "Approval is a `Manager` decision: the proposed window is
        re-checked for room conflicts including the cleanup buffer (else
        `ERR_ROOM_TIME_CONFLICT`)".

        Booking A holds [10:00, 12:30); approving a reschedule that proposes
        12:00 for another booking is rejected.

        Design: Difficulty/resource_temporal_overlap/party_room_cleanup_buffer_semantics
        """
        staff = setup_staff_trio()
        ctx = setup_party_context(email="gp2b@x.com")
        book_party(ctx["guardian"], ctx["room"], ctx["package"],
                   start_at="2026-06-08T10:00:00Z", child_count=10)  # A
        booking_b = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                               start_at="2026-06-08T14:30:00Z",
                               child_count=10)
        validate_success(api_client.confirm_party_booking(
            booking_b["id"], ctx["g_headers"]), 200)
        validate_success(api_client.request_reschedule(
            booking_b["id"], {"proposed_start_at": "2026-06-08T12:00:00Z"},
            ctx["g_headers"]), 200)

        res = api_client.approve_reschedule(booking_b["id"],
                                            staff["mgr_headers"])
        validate_error(res, ApiErrorId.ERR_ROOM_TIME_CONFLICT,
                       expected_status=409)


class TestCancellationWaterfallAndCascade:
    def test_party_cancel_cascade_to_loyalty_reversal(self, api):
        """PRD §3.7: "cancelling after that point but at least 48 hours before
        `start_at` refunds half, rounded half-up". "The cascade then cancels
        every linked café order — those whose `party_booking_id` names this
        booking — still in `PLACED` or `PREPARING`, and each cancelled order
        restores its applied `points_redeemed` through a `REVERSAL` entry,
        recomputing the guardian's `points_balance`".

        At T-3d the 6,000 deposit refunds 3,000; the linked PLACED order that
        redeemed 300 points is cancelled and the points return.

        Design: Difficulty/transitive_cascade/party_cancel_cascade_to_loyalty_reversal
        """
        staff = setup_staff_trio()
        ctx = setup_party_context(email="g8@x.com")
        booking = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                             start_at="2026-06-08T10:00:00Z",  # Monday
                             child_count=10)
        assert booking["deposit_cents"] == 6000
        validate_success(api_client.confirm_party_booking(
            booking["id"], ctx["g_headers"]), 200)

        seed_points(ctx["guardian"], staff["mgr_headers"], 400, note="seed")
        latte = create_menu_item("Latte", 425, allergen_tags=["MILK"])
        order = place_order(ctx["guardian"],
                            [{"menu_item_id": latte["id"], "quantity": 2}],
                            points_to_redeem=300,
                            party_booking_id=booking["id"])
        assert order["status"] == "PLACED"
        assert order["points_redeemed"] == 300

        set_clock("2026-06-05T08:00:00Z")  # T-3d: 50% refund tier
        cancelled = validate_success(api_client.cancel_party_booking(
            booking["id"], ctx["g_headers"]), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refund_cents"] == 3000

        order_after = get_success_data(api_client.get_cafe_order(
            order["id"], staff["mgr_headers"]))
        assert order_after["status"] == "CANCELLED"

        g = get_guardian_fresh(ctx["guardian"]["id"], staff["mgr_headers"])
        assert g["points_balance"] == 400  # 400 - 300 REDEEM + 300 REVERSAL

    def test_cancel_at_least_seven_days_refunds_deposit_in_full(self, api):
        """PRD §3.7: "Cancelling at least seven days before `start_at` refunds
        the deposit in full". "The waterfall outcome is recorded in
        `refund_cents`."

        Design: Difficulty/transitive_cascade/party_cancel_cascade_to_loyalty_reversal
        """
        ctx = setup_confirmed_booking(start_at="2026-06-10T10:00:00Z",
                                      email="g8b@x.com")
        booking = ctx["booking"]
        assert booking["deposit_cents"] == 6000

        # Clock is 2026-06-01, nine days before the 2026-06-10 start.
        cancelled = validate_success(api_client.cancel_party_booking(
            booking["id"], ctx["g_headers"]), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refund_cents"] == 6000


class TestPartyBookingOCC:
    def test_party_booking_create_with_stale_room_version_rejected(self, api):
        """PRD §2.7: "Creating a party booking requires
        `expected_party_room_version` matching the target room's current
        `version`. Because each created booking itself bumps the room's
        `version` by 1, an availability view can go stale between reads; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/party_booking_create_with_stale_room_version_rejected
        """
        ctx = setup_party_context(email="gaf@x.com")
        stale_version = ctx["room"]["version"]
        book_party(ctx["guardian"], ctx["room"], ctx["package"],
                   start_at="2026-06-08T10:00:00Z", child_count=10)

        res = api_client.create_party_booking(
            create_party_booking_payload(
                ctx["room"]["id"], ctx["package"]["id"], ctx["guardian"]["id"],
                expected_party_room_version=stale_version,
                start_at="2026-06-09T10:00:00Z", child_count=10),
            ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
