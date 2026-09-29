"""Reservation intake: the two calendar geometries, occupancy and the charge."""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    types,
    validate_error,
    validate_success,
)
from test_helpers.test_users import make_guest_headers


def test_the_turnover_buffer_pushes_the_blocked_window_past_the_check_out_date(api):
    """A one-night cleaning gap blocks an arrival on the departing stay's last day.

    The standing stay runs 2026-08-10 to 2026-08-12, and the buffer extends the
    blocked span to 2026-08-13 exclusive, so an arrival on 08-12 lands inside it.
    The arriving guest holds no bookings of her own anywhere, so the guest-timeline
    clause cannot be what fires — the refusal has to name the listing calendar.

    PRD: "The listing clause is property-scoped and half-open. For each live booking of the same listing, the blocked span begins on that booking's `check_in` and runs up to but not including its `check_out` extended forward by the listing's `turnover_buffer_nights`."
    PRD: "With `turnover_buffer_nights` at 0, a new booking beginning exactly on an existing booking's `check_out` date is therefore accepted; with `turnover_buffer_nights` at 1, that same booking conflicts."
    PRD: "**Listing calendar.** No conflict with the listing's own live bookings, refused with `ERR_PROPERTY_CALENDAR_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/property_calendar_half_open_window_extended_by_turnover_buffer
    """
    cast = fixtures.setup_deposit_listing(
        api, guest_name="Vera Lund", guest_email="vera@guest.test"
    )
    assertions.assert_fields(cast.property, "property", turnover_buffer_nights=1)
    arriving = fixtures.add_guest(api, cast, "Wes Amara", "wes@guest.test")

    standing = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-12"
    )
    fixtures.confirm_stay(api, cast, standing["id"])
    live_version = fixtures.read_property(api, cast)["version"]

    validate_error(
        api.create_reservation(
            make_guest_headers(arriving["id"]),
            **factories.reservation_payload(
                arriving["id"],
                cast.property_id,
                live_version,
                check_in="2026-08-12",
                check_out="2026-08-14",
            )
        ),
        ApiErrorId.ERR_PROPERTY_CALENDAR_CONFLICT,
        expected_status=409,
    )

    assertions.assert_page(
        api.list_reservations(cast.host_headers, guest_id=arriving["id"]),
        total_count=0,
    )
    assertions.assert_page(
        api.list_reservations(cast.host_headers, property_id=cast.property_id),
        total_count=1,
    )
    assertions.assert_fields(
        validate_success(api.get_reservation(standing["id"], cast.host_headers)),
        "reservation",
        stay_state="CONFIRMED",
    )


def test_an_arrival_one_day_past_the_buffer_is_accepted_and_priced(api):
    """Immediately outside the extended window the same listing is bookable again.

    2026-08-13 is the first date the buffered span no longer covers, so this
    arrival must succeed, and its charge is computed against the listing as it
    stands: a deposit product, so no waiver fee and a hold frozen at the listing's
    deposit amount.

    PRD: "The listing clause is property-scoped and half-open. For each live booking of the same listing, the blocked span begins on that booking's `check_in` and runs up to but not including its `check_out` extended forward by the listing's `turnover_buffer_nights`."
    PRD: "On a `DEPOSIT` listing the reverse holds: `waiver_fee_cents` is 0 and `deposit_hold_cents` is frozen at the listing's `deposit_amount_cents`."
    PRD: "When `pre_fee_subtotal_cents` is below 100000 cents — that is, below 1,000.00 in major units — `trust_fee_pct` is 0.035; at 100000 cents or above it is 0.025."

    Design: Difficulty/resource_temporal_overlap/property_calendar_half_open_window_extended_by_turnover_buffer
    """
    cast = fixtures.setup_deposit_listing(
        api, guest_name="Vera Lund", guest_email="vera@guest.test"
    )
    arriving = fixtures.add_guest(api, cast, "Wes Amara", "wes@guest.test")
    standing = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-12"
    )
    fixtures.confirm_stay(api, cast, standing["id"])
    live_version = fixtures.read_property(api, cast)["version"]

    arrival = validate_success(
        api.create_reservation(
            make_guest_headers(arriving["id"]),
            **factories.reservation_payload(
                arriving["id"],
                cast.property_id,
                live_version,
                check_in="2026-08-13",
                check_out="2026-08-15",
            )
        ),
        expected_status=201,
    )

    types.assert_is_reservation(arrival)
    assertions.assert_fields(
        arrival,
        "reservation",
        stay_state="REQUESTED",
        check_in="2026-08-13",
        check_out="2026-08-15",
        nights=2,
        deposit_state="NONE",
        deposit_hold_cents=50000,
    )

    breakdown = validate_success(
        api.get_charge_breakdown(arrival["id"], make_guest_headers(arriving["id"]))
    )
    assertions.assert_charge(
        breakdown,
        nights=2,
        accommodation_cents=40000,
        waiver_fee_cents=0,
        pre_fee_subtotal_cents=40000,
        trust_fee_pct=0.035,
        trust_fee_cents=1400,
        total_charged_cents=41400,
        deposit_hold_cents=50000,
        label="charge_breakdown",
    )
    assertions.assert_charge_internally_consistent(breakdown)
    assertions.assert_page(
        api.list_reservations(cast.host_headers, property_id=cast.property_id),
        total_count=2,
    )


def test_a_guest_collides_with_herself_on_the_shared_turnover_date(api):
    """The guest timeline is closed at both ends, so back-to-back stays touch.

    The listing carries no turnover buffer, so its own half-open clause is happy
    with an arrival on the departing stay's check-out date. The obstacle is that
    this is the same guest: 2026-08-13 is the last day of one span and the first
    day of the other, and the guest clause counts both ends.

    PRD: "The guest clause is guest-scoped, spans every listing on the platform, and is closed at both ends. For each live booking of the same guest anywhere, the requested span from `check_in` through `check_out` inclusive must not intersect that booking's span from its `check_in` through its `check_out` inclusive."
    PRD: "The consequence is that a guest's own back-to-back stays at two different listings collide on the shared turnover date, even though the listing clause would have permitted each booking on its own."
    PRD: "**Guest calendar.** No conflict with the guest's own live bookings anywhere on the platform, refused with `ERR_GUEST_STAY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/guest_closed_interval_self_overlap_on_shared_turnover_date
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Yara Bloom", guest_email="yara@guest.test"
    )
    assertions.assert_fields(cast.property, "property", turnover_buffer_nights=0)
    standing = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-13"
    )
    fixtures.confirm_stay(api, cast, standing["id"])
    live_version = fixtures.read_property(api, cast)["version"]

    validate_error(
        api.create_reservation(
            cast.guest_headers,
            **factories.reservation_payload(
                cast.guest_id,
                cast.property_id,
                live_version,
                check_in="2026-08-13",
                check_out="2026-08-15",
            )
        ),
        ApiErrorId.ERR_GUEST_STAY_OVERLAP,
        expected_status=409,
    )

    assertions.assert_page(
        api.list_reservations(cast.host_headers, guest_id=cast.guest_id),
        total_count=1,
    )


def test_a_second_guest_takes_the_same_shared_date_without_objection(api):
    """The identical dates are accepted for someone else, so the calendar was clear.

    This is the control for the collision above: the request differs only in whose
    timeline it lands on. A zero-buffer listing permits the arrival on the departing
    stay's check-out date, and the new booking is priced at the ELEVATED multiplier
    like any other fresh account.

    PRD: "The listing clause is property-scoped and half-open. For each live booking of the same listing, the blocked span begins on that booking's `check_in` and runs up to but not including its `check_out` extended forward by the listing's `turnover_buffer_nights`."
    PRD: "The guest clause is guest-scoped, spans every listing on the platform, and is closed at both ends. For each live booking of the same guest anywhere, the requested span from `check_in` through `check_out` inclusive must not intersect that booking's span from its `check_in` through its `check_out` inclusive."
    PRD: "On a `WAIVER` listing, `deposit_hold_cents` is 0 and `waiver_fee_cents` is the listing's `waiver_nightly_fee_cents` multiplied by `nights` and again by a risk multiplier read from the pinned `risk_tier_at_booking` — 1.00 at `LOW`, 1.25 at `ELEVATED`, 1.60 at `HIGH` and 2.00 at `CRITICAL` — with the product rounded half up to a whole cent."

    Design: Difficulty/resource_temporal_overlap/guest_closed_interval_self_overlap_on_shared_turnover_date
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Yara Bloom", guest_email="yara@guest.test"
    )
    other = fixtures.add_guest(api, cast, "Zane Pryor", "zane@guest.test")
    standing = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-13"
    )
    fixtures.confirm_stay(api, cast, standing["id"])
    live_version = fixtures.read_property(api, cast)["version"]

    accepted = validate_success(
        api.create_reservation(
            make_guest_headers(other["id"]),
            **factories.reservation_payload(
                other["id"],
                cast.property_id,
                live_version,
                check_in="2026-08-13",
                check_out="2026-08-15",
            )
        ),
        expected_status=201,
    )
    assertions.assert_fields(
        accepted,
        "reservation",
        guest_id=other["id"],
        stay_state="REQUESTED",
        nights=2,
        risk_tier_at_booking="ELEVATED",
    )

    breakdown = validate_success(
        api.get_charge_breakdown(accepted["id"], make_guest_headers(other["id"]))
    )
    assertions.assert_charge(
        breakdown,
        nights=2,
        accommodation_cents=60000,
        waiver_fee_cents=7500,
        pre_fee_subtotal_cents=67500,
        trust_fee_pct=0.035,
        trust_fee_cents=2363,
        total_charged_cents=69863,
        deposit_hold_cents=0,
        label="charge_breakdown",
    )
    assertions.assert_page(
        api.list_reservations(cast.host_headers, property_id=cast.property_id),
        total_count=2,
    )


def test_the_breakdown_reproduces_the_whole_chain_for_a_four_night_waiver_stay(api):
    """Every link of the pricing chain is asserted, not just the total.

    Four nights at 30000 make 120000; the nightly waiver fee of 3000 is multiplied
    by four nights and by the ELEVATED multiplier of 1.25 to make 15000; the
    subtotal of 135000 sits at or above the fee break, so the cheaper rate applies.

    PRD: "`accommodation_cents` is the listing's `nightly_rate_cents` multiplied by `nights`."
    PRD: "On a `WAIVER` listing, `deposit_hold_cents` is 0 and `waiver_fee_cents` is the listing's `waiver_nightly_fee_cents` multiplied by `nights` and again by a risk multiplier read from the pinned `risk_tier_at_booking` — 1.00 at `LOW`, 1.25 at `ELEVATED`, 1.60 at `HIGH` and 2.00 at `CRITICAL` — with the product rounded half up to a whole cent."
    PRD: "When `pre_fee_subtotal_cents` is below 100000 cents — that is, below 1,000.00 in major units — `trust_fee_pct` is 0.035; at 100000 cents or above it is 0.025."
    PRD: "`trust_fee_cents` is then `pre_fee_subtotal_cents` multiplied by `trust_fee_pct`, rounded half up to a whole cent, and `total_charged_cents` is `pre_fee_subtotal_cents` plus `trust_fee_cents`."

    Design: Corner/calculations/charge_breakdown_matches_formula_for_four_night_waiver_stay
    """
    cast = fixtures.setup_waiver_listing(api)
    reservation = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-14"
    )
    assertions.assert_booking_snapshot(reservation, 35, "ELEVATED")

    breakdown = validate_success(
        api.get_charge_breakdown(reservation["id"], cast.host_headers)
    )
    assertions.assert_charge(
        breakdown,
        nights=4,
        accommodation_cents=120000,
        waiver_fee_cents=15000,
        pre_fee_subtotal_cents=135000,
        trust_fee_pct=0.025,
        trust_fee_cents=3375,
        total_charged_cents=138375,
        deposit_hold_cents=0,
        label="charge_breakdown",
    )
    assertions.assert_charge_internally_consistent(breakdown)
    assert breakdown["waiver_fee_cents"] == assertions.waiver_fee_cents(
        3000, 4, "ELEVATED"
    ), "the waiver fee must be the rounded full product, never a per-night rounding"


def test_a_cancelled_stay_no_longer_occupies_the_calendar(api):
    """Only live bookings conflict, so a cancelled window is released.

    The first guest books, confirms and then withdraws, which drops the listing's
    open-booking counter to zero. A second guest may then take the identical window,
    and the counter climbs back to one — the cancelled row still exists, it is simply
    outside the set the conflict scan looks at.

    PRD: "Both consider only reservations whose `stay_state` is `REQUESTED`, `CONFIRMED` or `IN_STAY`; rows already `CANCELLED` or `COMPLETED` never conflict with anything."
    PRD: "`open_reservation_count` is the number of reservations of this listing whose `stay_state` is `REQUESTED`, `CONFIRMED` or `IN_STAY`."

    Design: Corner/calculations/cancelled_reservation_excluded_from_calendar_conflict
    """
    cast = fixtures.setup_waiver_listing(
        api,
        guest_name="Filter Guest A",
        guest_email="filter-a@guest.test",
        host_name="Corner Stays LLC",
        host_email="calchost2@stays.test",
    )
    second = fixtures.add_guest(api, cast, "Filter Guest B", "filter-b@guest.test")

    withdrawn = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-13"
    )
    fixtures.confirm_stay(api, cast, withdrawn["id"])
    cancelled = validate_success(
        api.cancel_reservation(withdrawn["id"], cast.guest_headers)
    )
    assertions.assert_fields(cancelled, "reservation", stay_state="CANCELLED")

    released = fixtures.read_property(api, cast)
    assertions.assert_fields(released, "property", open_reservation_count=0)

    replacement = validate_success(
        api.create_reservation(
            make_guest_headers(second["id"]),
            **factories.reservation_payload(
                second["id"],
                cast.property_id,
                released["version"],
                check_in="2026-08-10",
                check_out="2026-08-13",
            )
        ),
        expected_status=201,
    )
    assertions.assert_fields(
        replacement,
        "reservation",
        stay_state="REQUESTED",
        check_in="2026-08-10",
        check_out="2026-08-13",
    )

    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", open_reservation_count=1
    )
    assertions.assert_page(
        api.list_reservations(cast.host_headers, property_id=cast.property_id),
        total_count=2,
    )


def test_a_party_of_exactly_the_effective_cap_books_but_is_routed_to_review(api):
    """The occupancy gate is strict, and the screening table is not.

    The effective ceiling here is the listing's own maximum of four, and a party of
    exactly four passes validation because only a strictly larger party is refused.
    That same equality then trips the full-house screening clause, so the accepted
    booking is parked for an adjudicator instead of being cleared. Five guests are
    refused outright.

    PRD: "`guest_count` must not exceed the effective occupancy ceiling, which is the smaller of the listing's `max_occupancy` and the jurisdiction's `max_occupancy_cap`. Equality is accepted; only a strictly larger party is refused, with `ERR_OCCUPANCY_LIMIT_EXCEEDED`."
    PRD: "`risk_tier_at_booking` is `ELEVATED`, no event declared, and `guest_count` is greater than or equal to the listing's `max_occupancy` — the verdict is `MANUAL_REVIEW` with reason `ELEVATED_FULL_HOUSE`."
    PRD: "And clause 6 compares `guest_count` against the listing's own `max_occupancy` using \"greater than or equal\", whereas the occupancy validation earlier in the request compares `guest_count` against the *effective* ceiling using strictly \"greater than\" — so a booking for exactly `max_occupancy` guests passes validation and is then routed to `MANUAL_REVIEW`."

    Design: Corner/validations/occupancy_at_effective_cap_is_accepted
    """
    cast = fixtures.setup_deposit_listing(api)
    assertions.assert_fields(cast.property, "property", max_occupancy=4)
    assert cast.jurisdiction_rule["max_occupancy_cap"] == 8, (
        "the listing's own maximum must be the binding half of the effective ceiling"
    )
    live_version = fixtures.read_property(api, cast)["version"]

    at_cap = validate_success(
        api.create_reservation(
            cast.guest_headers,
            **factories.reservation_payload(
                cast.guest_id,
                cast.property_id,
                live_version,
                check_in="2026-08-10",
                check_out="2026-08-12",
                guest_count=4,
            )
        ),
        expected_status=201,
    )
    assertions.assert_fields(
        at_cap,
        "reservation",
        guest_count=4,
        stay_state="REQUESTED",
        screening_state="MANUAL_REVIEW",
        screening_reason_code="ELEVATED_FULL_HOUSE",
        deposit_state="NONE",
    )
    assertions.assert_booking_snapshot(at_cap, 35, "ELEVATED")

    validate_error(
        api.create_reservation(
            cast.guest_headers,
            **factories.reservation_payload(
                cast.guest_id,
                cast.property_id,
                fixtures.read_property(api, cast)["version"],
                check_in="2026-08-20",
                check_out="2026-08-22",
                guest_count=5,
            )
        ),
        ApiErrorId.ERR_OCCUPANCY_LIMIT_EXCEEDED,
        expected_status=422,
    )


def test_an_arrival_before_the_logical_clock_is_refused_as_past_dated(api):
    """The past check reads the logical clock, and the date range is well ordered.

    July 25th to July 28th is a perfectly ordered three-night range, so the range
    gate passes; what fails is that the derived arrival instant sits behind the
    clock, which the process starts at the first of August.

    PRD: "The derived `check_in_at` instant must be strictly later than the logical clock; a stay may not be booked into the past or onto the current instant, and a violation is refused with `ERR_CHECK_IN_IN_PAST`."
    PRD: "`check_in_at` is `check_in` at 15:00 UTC, and it is the earliest instant the stay may be checked in."
    PRD: "`check_out` must be strictly later than `check_in`; equal or inverted dates are refused with `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/booking_check_in_in_the_past_rejected
    """
    cast = fixtures.setup_waiver_listing(
        api,
        guest_name="Past Guest",
        guest_email="past@guest.test",
        host_name="Corner Stays LLC",
        host_email="valhost3@stays.test",
    )
    live_version = fixtures.read_property(api, cast)["version"]

    validate_error(
        api.create_reservation(
            cast.guest_headers,
            **factories.reservation_payload(
                cast.guest_id,
                cast.property_id,
                live_version,
                check_in="2026-07-25",
                check_out="2026-07-28",
            )
        ),
        ApiErrorId.ERR_CHECK_IN_IN_PAST,
        expected_status=422,
    )

    assertions.assert_page(
        api.list_reservations(cast.host_headers, property_id=cast.property_id),
        total_count=0,
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", open_reservation_count=0
    )


def test_the_creation_response_already_carries_the_charge_and_the_snapshot(api):
    """Nothing about a new booking is deferred to a later read.

    The response to the creating request must already expose the pinned risk
    snapshot, the screening verdict, the whole charge and the three derived
    instants, and a re-read must agree with it field for field at the same version.

    PRD: "With the risk tier and the charge both pinned, a decision table runs top down; the first matching clause wins and no later clause is consulted."
    PRD: "In every case the reservation's own `version` is 1, the listing's `open_reservation_count` is recomputed, and the listing's `version` increases by 1."
    PRD: "Three derived instants are stamped at creation. `check_in_at` is `check_in` at 15:00 UTC, and it is the earliest instant the stay may be checked in. `check_out_at` is `check_out` at 11:00 UTC, and it is the earliest instant the stay may be completed. `claim_window_ends_at` is `check_out_at` plus 72 hours — three days — and it is the last instant a damage claim may be filed against the stay."

    Design: Corner/consistency model/reservation_create_response_exposes_charge_and_snapshot_immediately
    """
    cast = fixtures.setup_waiver_listing(
        api,
        guest_name="Immediate Guest",
        guest_email="immediate@guest.test",
        host_name="Corner Stays LLC",
        host_email="conshost1@stays.test",
    )
    live_version = fixtures.read_property(api, cast)["version"]

    created = validate_success(
        api.create_reservation(
            cast.guest_headers,
            **factories.reservation_payload(
                cast.guest_id,
                cast.property_id,
                live_version,
                check_in="2026-08-10",
                check_out="2026-08-13",
            )
        ),
        expected_status=201,
    )

    types.assert_is_reservation(created)
    assertions.assert_booking_snapshot(created, 35, "ELEVATED")
    assertions.assert_fields(
        created,
        "reservation",
        screening_state="CLEARED",
        screening_reason_code="LOW_RISK_AUTO_CLEAR",
        total_charged_cents=103781,
        version=1,
    )
    assert created["check_in_at"].startswith("2026-08-10T15:00:00"), (
        "check_in_at must be the arrival date at 15:00 UTC, got {0!r}".format(
            created["check_in_at"]
        )
    )
    assert created["check_out_at"].startswith("2026-08-13T11:00:00"), (
        "check_out_at must be the departure date at 11:00 UTC, got {0!r}".format(
            created["check_out_at"]
        )
    )
    assert created["claim_window_ends_at"].startswith("2026-08-16T11:00:00"), (
        "claim_window_ends_at must be 72 hours after check_out_at, got {0!r}".format(
            created["claim_window_ends_at"]
        )
    )

    reread = validate_success(api.get_reservation(created["id"], cast.guest_headers))
    assertions.assert_fields(
        reread, "reservation", total_charged_cents=103781, version=1
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", open_reservation_count=1
    )
