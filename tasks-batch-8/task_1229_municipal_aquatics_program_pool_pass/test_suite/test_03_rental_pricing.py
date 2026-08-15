"""Facility rental pricing: quote vs final, residency multiplier, party fee,
overtime blocks, and the cancellation window (PRD §3.7)."""
from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    assert_rental,
    create_rental_payload,
    make_facility, make_pass_holder, make_rental, approve_rental,
    set_clock, facility_version, make_passholder_headers,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]


def test_rental_quoted_price_at_creation(api):
    """PRD §3.7: "The quote first derives whole hours by rounding the rental
    duration up to the next hour. The base rate is 15000 cents per hour. A
    residency multiplier is then applied — 1.0 for `RESIDENT` holders, 1.5 for
    `NON_RESIDENT` holders — and the result is rounded half-up to the cent. A
    party fee is then added: the first 25 attendees are included, and every
    attendee beyond 25 adds 300 cents."

    Design: Difficulty/dual_variant_calc/rental_quote_vs_final_with_overtime
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=4)
    holder = make_pass_holder(
        full_name="Renter R", date_of_birth="1985-06-01T00:00:00Z",
        residency_status="RESIDENT",
    )
    set_clock("2026-07-01T00:00:00Z")
    rental = validate_success(
        api.create_rental(
            create_rental_payload(
                facility["id"], holder["id"],
                party_size=10,
                start_datetime="2026-07-15T14:00:00Z",
                end_datetime="2026-07-15T17:00:00Z",
            ),
            make_passholder_headers(holder["id"]),
        ),
        expected_status=201,
    )
    assert_rental(rental)
    # 3 hours * 15000 * 1.0 + max(0, 10-25)*300 = 45000
    assert rental["quoted_price_cents"] == 45000, (
        f"RESIDENT 3h/10p quote must be 45000, "
        f"got {rental['quoted_price_cents']}"
    )
    assert rental["status"] == "REQUESTED"


def test_rental_final_price_includes_overtime_blocks(api):
    """PRD §3.7: "Check-out moves the rental to `COMPLETED`, subtracts
    `party_size` from `current_bather_count`, and computes `final_price_cents`
    as the locked `quoted_price_cents` plus overtime. Overtime is zero when
    the actual exit is at or before `end_datetime`; otherwise the overage is
    divided into 15-minute blocks with any partial block rounded up, and each
    block adds 5000 cents."

    Design: Difficulty/dual_variant_calc/rental_quote_vs_final_with_overtime
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=4)
    holder = make_pass_holder(
        full_name="Renter R", date_of_birth="1985-06-01T00:00:00Z",
        residency_status="RESIDENT",
    )
    set_clock("2026-07-01T00:00:00Z")
    rental = make_rental(
        facility["id"], holder["id"],
        party_size=10,
        start_datetime="2026-07-15T14:00:00Z",
        end_datetime="2026-07-15T17:00:00Z",
    )
    approve_rental(rental["id"], facility["id"])
    set_clock("2026-07-15T14:00:00Z")
    get_success_data(api.check_in_rental(rental["id"], GATE))
    # Exit 22 minutes late -> ceil(22/15) = 2 blocks -> 2 * 5000 = 10000
    set_clock("2026-07-15T17:22:00Z")
    data = validate_success(api.check_out_rental(rental["id"], GATE))
    assert_rental(data)
    assert data["status"] == "COMPLETED"
    assert data["quoted_price_cents"] == 45000
    assert data["final_price_cents"] == 55000, (
        f"final price must be 45000 + 2*5000 = 55000, "
        f"got {data['final_price_cents']}"
    )
    assert data["final_price_cents"] - data["quoted_price_cents"] == 10000


def test_rental_quote_nonresident_with_party_fee(api):
    """PRD §3.7: "A residency multiplier is then applied — 1.0 for `RESIDENT`
    holders, 1.5 for `NON_RESIDENT` holders — and the result is rounded
    half-up to the cent. A party fee is then added: the first 25 attendees
    are included, and every attendee beyond 25 adds 300 cents. The sum of the
    residency-adjusted base and the party fee is the quote."

    Design: Difficulty/combinatorial_formula/rental_quote_residency_party_fee_mode_a
    """
    facility = make_facility(max_bather_capacity=200, lap_lane_count=6)
    holder = make_pass_holder(
        full_name="NonRes A", date_of_birth="1980-01-01T00:00:00Z",
        residency_status="NON_RESIDENT",
    )
    set_clock("2026-07-01T00:00:00Z")
    rental = validate_success(
        api.create_rental(
            create_rental_payload(
                facility["id"], holder["id"],
                party_size=30,
                start_datetime="2026-08-01T14:00:00Z",
                end_datetime="2026-08-01T16:00:00Z",
            ),
            make_passholder_headers(holder["id"]),
        ),
        expected_status=201,
    )
    assert_rental(rental)
    # hours=2, base=30000, NR mult 1.5 -> 45000; party_fee=(30-25)*300=1500
    assert rental["quoted_price_cents"] == 46500, (
        f"NON_RESIDENT 2h/30p quote must be 46500, "
        f"got {rental['quoted_price_cents']}"
    )


def test_rental_quote_party_fee_boundary(api):
    """PRD §3.7: "A party fee is then added: the first 25 attendees are
    included, and every attendee beyond 25 adds 300 cents."
    PRD §3.7: "The rounding sequence is contractual: residency multiplier
    first, round half-up to cent, then add the party fee."

    Design: Difficulty/combinatorial_formula/rental_quote_residency_party_fee_mode_a
    """
    facility = make_facility(max_bather_capacity=200, lap_lane_count=6)
    holder = make_pass_holder(
        date_of_birth="1980-01-01T00:00:00Z", residency_status="NON_RESIDENT"
    )
    set_clock("2026-07-01T00:00:00Z")
    # Exactly 25 attendees -> no party fee
    rental_25 = validate_success(
        api.create_rental(
            create_rental_payload(
                facility["id"], holder["id"],
                party_size=25,
                start_datetime="2026-08-01T14:00:00Z",
                end_datetime="2026-08-01T16:00:00Z",
            ),
            make_passholder_headers(holder["id"]),
        ),
        expected_status=201,
    )
    assert rental_25["quoted_price_cents"] == 45000, (
        f"25 attendees must incur no party fee: 2h*15000*1.5 = 45000, "
        f"got {rental_25['quoted_price_cents']}"
    )
    # 26 attendees -> exactly one extra person -> +300
    rental_26 = validate_success(
        api.create_rental(
            create_rental_payload(
                facility["id"], holder["id"],
                party_size=26,
                start_datetime="2026-08-02T14:00:00Z",
                end_datetime="2026-08-02T16:00:00Z",
            ),
            make_passholder_headers(holder["id"]),
        ),
        expected_status=201,
    )
    assert rental_26["quoted_price_cents"] == 45300, (
        f"26 attendees must add 300: 45000 + 300 = 45300, "
        f"got {rental_26['quoted_price_cents']}"
    )


def test_rental_cancel_fee_over_72h_window(api):
    """PRD §3.7: "Cancelling an `APPROVED` rental is free when the
    cancellation is at least 72 hours before `start_datetime`; inside that
    window — strictly less than 72 hours — a 25 percent cancellation fee on
    `quoted_price_cents`, rounded half-up to the cent, is withheld. A
    cancellation at exactly 72.0 hours before start incurs no fee."

    Design: Corner/calculations/rental_cancel_fee_over_72h_window
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=0)
    holder = make_pass_holder(
        full_name="P", date_of_birth="1990-01-01T00:00:00Z",
        residency_status="RESIDENT",
    )
    set_clock("2026-08-01T00:00:00Z")
    rental = make_rental(
        facility["id"], holder["id"],
        party_size=10,
        start_datetime="2026-08-10T14:00:00Z",
        end_datetime="2026-08-10T16:00:00Z",
    )
    approve_rental(rental["id"], facility["id"])
    # 80 hours before start -> outside the fee window -> free cancellation
    set_clock("2026-08-07T06:00:00Z")
    data = validate_success(
        api.cancel_rental(rental["id"], make_passholder_headers(holder["id"]))
    )
    assert_rental(data)
    assert data["status"] == "CANCELLED"
