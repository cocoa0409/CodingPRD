"""Operations gated on the state of a different entity's row."""

from test_helpers import (
    ADMIN,
    assert_entitlement_counters,
    assert_reservation_state,
    book_member_stay,
    create_active_agreement,
    create_affiliate_open_park,
    create_park,
    create_president_tier,
    make_agreement_status_change_payload,
    make_reservation_payload,
    open_park,
    read_agreement,
    read_membership,
    read_reservation,
    reset_clock,
    sell_membership_to_new_member,
    validate_error,
    validate_paginated,
    validate_success,
)


def _closed_park_and_a_ready_member(api):
    """A freshly created park, still shut for the season, and a paid-up contract."""
    reset_clock(api)
    tier = create_president_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dev Marchetti", "email": "dev@example.com"},
        upfront_paid_cents=1850000,
    )
    park = create_park(
        api,
        name="Blue Mesa RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    assert park["park_status"] == "SEASONAL_CLOSED", "a new park is not yet open for business"
    return holder, park


def test_booking_is_refused_while_the_park_is_shut_for_the_season(api):
    """The park's own state, not the request, is what refuses the booking.

    PRD §2.8: "Park open for business — `ERR_PARK_NOT_OPEN` (HTTP 422), on member booking and
    transient booking: the target park's `park_status` must be `OPEN`, so bookings are refused
    at `SEASONAL_CLOSED` and `MAINTENANCE_HOLD` parks."

    Design: Difficulty/cross_entity_state_dependency/reservation_create_blocked_until_park_state_is_open
    """
    holder, park = _closed_park_and_a_ready_member(api)

    response = api.create_reservation(
        make_reservation_payload(
            park["id"], holder["membership_id"], "2026-09-14", "2026-09-17"
        ),
        holder["headers"],
    )
    validate_error(response, "ERR_PARK_NOT_OPEN", 422)

    rows, _meta = validate_paginated(
        api.list_reservations(ADMIN, {"membership_id": holder["membership_id"]})
    )
    assert rows == [], "the refused booking left no reservation row"
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_b=0, annual=0
    )


def test_opening_the_season_admits_the_byte_identical_booking(api):
    """Nothing about the request changes; only the park's state does.

    PRD §3.2: "Opening the park for its season advances `park_status` from `SEASONAL_CLOSED`
    to `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/reservation_create_blocked_until_park_state_is_open
    """
    holder, park = _closed_park_and_a_ready_member(api)
    validate_error(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-09-14", "2026-09-17"
            ),
            holder["headers"],
        ),
        "ERR_PARK_NOT_OPEN",
        422,
    )

    opened = open_park(api, park["id"])
    assert opened["park_status"] == "OPEN"

    accepted = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-09-14", "2026-09-17"
            ),
            holder["headers"],
        ),
        201,
    )
    assert_reservation_state(
        accepted, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=3
    )
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_b=3, annual=3
    )


def _affiliate_park_with_two_eligible_members(api):
    """An ACTIVE partner agreement, its affiliate park, and two PRESIDENT contracts."""
    reset_clock(api)
    tier = create_president_tier(api)
    agreement = create_active_agreement(
        api,
        partner_name="Trailhead Partners",
        annual_member_night_quota=40,
        reciprocity_ratio=1.5,
        min_tier_rank=2,
        advance_window_cap_days=45,
        per_stay_night_cap=7,
        settlement_rate_cents_per_night=1500,
    )
    assert agreement["status"] == "ACTIVE"
    park = create_affiliate_open_park(
        api,
        agreement["id"],
        name="Trailhead Pines",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    assert park["network_type"] == "AFFILIATE", "naming an agreement makes the park affiliate"

    ines = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Ines Falk", "email": "ines@example.com"},
        upfront_paid_cents=1850000,
    )
    onur = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Onur Baptiste", "email": "onur@example.com"},
        upfront_paid_cents=1850000,
    )
    return agreement, park, ines, onur


def test_active_agreement_booking_consumes_reciprocity_inflated_quota(api):
    """Three nights at a partner park cost the club five quota nights.

    PRD §3.2: "When a member stay at a park under an agreement takes effect, the quota nights
    it charges are the stay's `nights` multiplied by the agreement's `reciprocity_ratio`,
    **rounded up** to the next whole night — never rounded half up."

    Design: Difficulty/cross_entity_state_dependency/affiliate_park_booking_blocked_when_partner_agreement_leaves_active
    """
    agreement, park, ines, _onur = _affiliate_park_with_two_eligible_members(api)

    reservation = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], ines["membership_id"], "2026-09-10", "2026-09-13"
            ),
            ines["headers"],
        ),
        201,
    )
    assert_reservation_state(reservation, "CONFIRMED", entitlement_nights_charged=3)
    assert reservation["affiliate_nights_charged"] == 5, "ceil(3 * 1.5) is five quota nights"

    after = read_agreement(api, agreement["id"])
    assert after["nights_consumed_ytd"] == 5, "the quota tally takes the inflated figure"
    assert after["settlement_owed_cents"] == 7500, "5 quota nights at 1500 cents each"


def test_suspending_the_agreement_refuses_the_next_partner_booking(api):
    """A suspension is forward-only: the standing stay and its quota are untouched.

    PRD §3.2: "An `ACTIVE` agreement may be moved to `SUSPENDED`, after which new bookings at
    its parks are refused with `ERR_AFFILIATE_AGREEMENT_INACTIVE` while reservations already
    `CONFIRMED` or `CHECKED_IN` are left entirely untouched."

    Design: Difficulty/cross_entity_state_dependency/affiliate_park_booking_blocked_when_partner_agreement_leaves_active
    """
    agreement, park, ines, onur = _affiliate_park_with_two_eligible_members(api)
    standing = book_member_stay(
        api, ines["headers"], park["id"], ines["membership_id"], "2026-09-10", "2026-09-13"
    )

    suspended = validate_success(
        api.change_affiliate_agreement_status(
            agreement["id"], make_agreement_status_change_payload("SUSPENDED"), ADMIN
        ),
        200,
    )
    assert suspended["status"] == "SUSPENDED"

    response = api.create_reservation(
        make_reservation_payload(
            park["id"], onur["membership_id"], "2026-09-10", "2026-09-13"
        ),
        onur["headers"],
    )
    validate_error(response, "ERR_AFFILIATE_AGREEMENT_INACTIVE", 409)
    assert_entitlement_counters(read_membership(api, onur["membership_id"]), class_b=0, annual=0)

    assert read_reservation(api, standing["id"])["status"] == "CONFIRMED", (
        "the stay booked while the agreement was ACTIVE stands"
    )
    assert read_agreement(api, agreement["id"])["nights_consumed_ytd"] == 5, (
        "suspension neither refunds nor re-bills the quota already consumed"
    )
