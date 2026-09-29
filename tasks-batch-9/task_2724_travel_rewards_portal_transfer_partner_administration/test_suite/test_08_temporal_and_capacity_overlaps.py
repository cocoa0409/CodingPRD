"""
Three different occupation semantics on three different resources: half-open
rotation windows, closed promotional windows with a buffer, and offer seat capacity.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BONUS_EVENT_WINDOW_CONFLICT,
    ERR_ROTATION_WINDOW_OVERLAP,
    ERR_SEAT_UNAVAILABLE,
)
from test_helpers.assertions import assert_account_aggregates, assert_timestamp_equals
from test_helpers.test_users import ADMIN_HEADERS, APPROVER_HEADERS
from test_helpers.types import (
    CATEGORY_GROCERY,
    EVENT_SCHEDULED,
    OFFER_OPEN,
    PARITY_IN,
    ROTATION_DRAFT,
)

GROCERY_MCC = "5411"


def _september_grocery_rotation(api):
    """One drafted rotation occupying [2026-09-01, 2026-10-01)."""
    category = fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )
    first = validate_success(
        api.create_rotation(
            f.rotation_payload(
                merchant_category_id=category["id"],
                rotation_code="SEP-GROCERY",
                bonus_multiplier=2.0,
                capped_spend_cents=50000,
                window_start="2026-09-01T00:00:00.000Z",
                window_end="2026-10-01T00:00:00.000Z",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    return category, first


def test_a_rotation_starting_exactly_where_the_incumbent_ends_is_admitted(api):
    """
    "Touching endpoints do not intersect: a new rotation whose `window_start` is
    exactly an existing rotation's `window_end` is accepted, and so is the mirror
    case."

    Design: Difficulty/resource_temporal_overlap/overlap_rotation_half_open_windows_admit_touching_endpoints
    """
    category, _ = _september_grocery_rotation(api)

    touching = validate_success(
        api.create_rotation(
            f.rotation_payload(
                merchant_category_id=category["id"],
                rotation_code="OCT-GROCERY",
                bonus_multiplier=3.0,
                capped_spend_cents=60000,
                window_start="2026-10-01T00:00:00.000Z",
                window_end="2026-11-01T00:00:00.000Z",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )

    assert touching["status"] == ROTATION_DRAFT
    assert_timestamp_equals(touching["window_start"], "2026-10-01T00:00:00.000Z")


def test_a_rotation_intersecting_the_interior_of_a_draft_window_is_refused(api):
    """
    "A new rotation is rejected with `ERR_ROTATION_WINDOW_OVERLAP` when another
    rotation on the same `merchant_category_id` whose `status` is `DRAFT`,
    `SCHEDULED`, or `ACTIVE` has a half-open window intersecting the new one."

    Design: Difficulty/resource_temporal_overlap/overlap_rotation_half_open_windows_admit_touching_endpoints
    """
    category, _ = _september_grocery_rotation(api)

    validate_error(
        api.create_rotation(
            f.rotation_payload(
                merchant_category_id=category["id"],
                rotation_code="MID-GROCERY",
                bonus_multiplier=4.0,
                capped_spend_cents=70000,
                window_start="2026-09-15T00:00:00.000Z",
                window_end="2026-10-15T00:00:00.000Z",
            ),
            ADMIN_HEADERS,
        ),
        ERR_ROTATION_WINDOW_OVERLAP,
        409,
    )


def test_the_refused_rotation_is_never_persisted_beside_the_two_legal_ones(api):
    """
    "At most one live rotation may cover any given instant on any given category, and
    that is enforced at creation."

    Design: Difficulty/resource_temporal_overlap/overlap_rotation_half_open_windows_admit_touching_endpoints
    """
    category, _ = _september_grocery_rotation(api)
    validate_success(
        api.create_rotation(
            f.rotation_payload(
                merchant_category_id=category["id"],
                rotation_code="OCT-GROCERY",
                bonus_multiplier=3.0,
                capped_spend_cents=60000,
                window_start="2026-10-01T00:00:00.000Z",
                window_end="2026-11-01T00:00:00.000Z",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    validate_error(
        api.create_rotation(
            f.rotation_payload(
                merchant_category_id=category["id"],
                rotation_code="MID-GROCERY",
                bonus_multiplier=4.0,
                capped_spend_cents=70000,
                window_start="2026-09-15T00:00:00.000Z",
                window_end="2026-10-15T00:00:00.000Z",
            ),
            ADMIN_HEADERS,
        ),
        ERR_ROTATION_WINDOW_OVERLAP,
        409,
    )

    rows, meta = validate_paginated(
        api.list_rotations(
            ADMIN_HEADERS, {"merchant_category_id": category["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["rotation_code"] for row in rows) == [
        "OCT-GROCERY",
        "SEP-GROCERY",
    ]


def _early_september_promotion(api):
    """One `SCHEDULED` event holding the closed window [2026-09-01, 2026-09-10]."""
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
        transfer_latency_hours=48,
        reversal_window_hours=72,
        settlement_cost_cents_per_1k=900,
    )
    first = fx.new_bonus_event(
        api,
        agreement["id"],
        ADMIN_HEADERS,
        event_code="SEP-EARLY-30",
        bonus_bps=3000,
        window_start="2026-09-01T00:00:00.000Z",
        window_end="2026-09-10T00:00:00.000Z",
        cap_points_per_account=6000,
    )
    return agreement, first


def test_an_event_starting_exactly_twenty_four_hours_later_is_still_a_conflict(api):
    """
    "A new event is accepted only when its `window_start` is strictly later than an
    existing live event's `window_end` plus 24 hours, or its `window_end` is strictly
    earlier than that event's `window_start` minus 24 hours"

    Design: Difficulty/resource_temporal_overlap/overlap_bonus_event_closed_windows_enforce_24_hour_buffer
    """
    agreement, _ = _early_september_promotion(api)

    validate_error(
        api.create_bonus_event(
            f.bonus_event_payload(
                partner_agreement_id=agreement["id"],
                event_code="SEP-EXACT-BUFFER",
                bonus_bps=2000,
                window_start="2026-09-11T00:00:00.000Z",
                window_end="2026-09-15T00:00:00.000Z",
                cap_points_per_account=6000,
            ),
            ADMIN_HEADERS,
        ),
        ERR_BONUS_EVENT_WINDOW_CONFLICT,
        409,
    )


def test_an_event_clearing_the_dead_air_is_scheduled_alongside_the_incumbent(api):
    """
    "Windows that merely touch, or that sit adjacent inside the 24-hour buffer, are
    rejected with `ERR_BONUS_EVENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/overlap_bonus_event_closed_windows_enforce_24_hour_buffer
    """
    agreement, first = _early_september_promotion(api)
    validate_error(
        api.create_bonus_event(
            f.bonus_event_payload(
                partner_agreement_id=agreement["id"],
                event_code="SEP-EXACT-BUFFER",
                bonus_bps=2000,
                window_start="2026-09-11T00:00:00.000Z",
                window_end="2026-09-15T00:00:00.000Z",
                cap_points_per_account=6000,
            ),
            ADMIN_HEADERS,
        ),
        ERR_BONUS_EVENT_WINDOW_CONFLICT,
        409,
    )

    later = validate_success(
        api.create_bonus_event(
            f.bonus_event_payload(
                partner_agreement_id=agreement["id"],
                event_code="SEP-LATE-20",
                bonus_bps=2000,
                window_start="2026-09-12T00:00:00.000Z",
                window_end="2026-09-16T00:00:00.000Z",
                cap_points_per_account=6000,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )

    assert later["status"] == EVENT_SCHEDULED
    assert (
        validate_success(api.get_bonus_event(first["id"], ADMIN_HEADERS))["status"]
        == EVENT_SCHEDULED
    )
    rows, meta = validate_paginated(
        api.list_bonus_events(
            ADMIN_HEADERS, {"partner_agreement_id": agreement["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["event_code"] for row in rows) == [
        "SEP-EARLY-30",
        "SEP-LATE-20",
    ]


def _two_seats_then_a_shrinking_resync(api):
    """Two committed seats that saturate the offer only after it is shrunk to two."""
    account, cardholder = fx.funded_account(
        api, 40000, cardholder_name="Kai Osterman", email="kai@example.com"
    )
    _, offer, supplier = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Bare Fare Consolidators",
            "contracted_markup_bps": 0,
            "parity_tolerance_bps": 0,
        },
        itinerary_code="DEN-YYZ-02",
        net_rate_cents=10000,
        agency_public_price_cents=10000,
        agency_public_seats=4,
        portal_seats=4,
        tax_cents=0,
    )
    first = fx.book(api, offer, account["id"], cardholder, traveler_name="Kai Osterman")
    second = fx.book(
        api,
        fx.read_offer(api, offer["id"], supplier),
        account["id"],
        cardholder,
        traveler_name="Kai Osterman",
    )
    validate_success(
        api.resync_offer(
            offer["id"],
            f.resync_payload(
                net_rate_cents=10000,
                agency_public_price_cents=10000,
                agency_public_seats=4,
                portal_seats=2,
            ),
            supplier,
        )
    )
    return account, cardholder, fx.read_offer(api, offer["id"], supplier), first, second


def test_the_third_booking_collides_with_the_seats_the_resync_took_away(api):
    """
    "`seats_committed` must be strictly below `portal_seats` at booking time, or the
    booking is refused with `ERR_SEAT_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/overlap_offer_seat_capacity_collides_after_downward_resync
    """
    account, cardholder, offer, _, _ = _two_seats_then_a_shrinking_resync(api)

    validate_error(
        api.book_offer(
            offer["id"],
            f.book_payload(
                account_id=account["id"],
                expected_offer_version=offer["version"],
                traveler_name="Kai Osterman",
            ),
            cardholder,
        ),
        ERR_SEAT_UNAVAILABLE,
        409,
    )

    after = fx.read_offer(api, offer["id"], ADMIN_HEADERS)
    assert after["portal_seats"] == 2
    assert after["seats_committed"] == 2
    assert after["status"] == OFFER_OPEN
    assert after["parity_status"] == PARITY_IN


def test_the_two_surviving_quotes_keep_their_points_and_their_reservation(api):
    """
    "`seats_committed` counts the redemption orders against this offer whose
    `fulfillment_status` is `QUOTED`, `CONFIRMED`, or `TICKETED`."

    Design: Difficulty/resource_temporal_overlap/overlap_offer_seat_capacity_collides_after_downward_resync
    """
    account, cardholder, offer, first, second = _two_seats_then_a_shrinking_resync(api)

    validate_error(
        api.book_offer(
            offer["id"],
            f.book_payload(
                account_id=account["id"],
                expected_offer_version=offer["version"],
                traveler_name="Kai Osterman",
            ),
            cardholder,
        ),
        ERR_SEAT_UNAVAILABLE,
        409,
    )

    assert first["points_debited"] == 10000
    assert second["points_debited"] == 10000
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=40000,
        points_pending_redemption=20000,
    )
    rows, meta = validate_paginated(
        api.list_orders(ADMIN_HEADERS, {"inventory_offer_id": offer["id"], "limit": 100})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
