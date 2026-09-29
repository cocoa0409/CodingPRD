"""Exact-boundary behaviour of the fee bands, the standing threshold and an empty input set."""

from test_helpers import (
    ANALYST_ONE,
    ANALYST_TWO,
    ApiClient,
    ApiErrorId,
    BALLROOM_C,
    EXHIBIT_HALL_C,
    RIVERBEND_ROTARY,
    append_line_item,
    assert_fields,
    assert_money_cents,
    assert_settlement_money,
    make_analyst_headers,
    read_booking,
    read_client,
    read_settlement,
    set_clock,
    setup_event_lifecycle,
    validate_error,
    validate_success,
)

BOAT_SHOW_DATES = {
    "event_name": "Sunbelt Boat Show",
    "move_in_start_date": "2027-06-09",
    "show_start_date": "2027-06-10",
    "show_end_date": "2027-06-12",
    "move_out_end_date": "2027-06-13",
}

AUTUMN_FAIR_DATES = {
    "event_name": "Riverbend Autumn Fair",
    "move_in_start_date": "2027-09-06",
    "show_start_date": "2027-09-08",
    "show_end_date": "2027-09-10",
    "move_out_end_date": "2027-09-12",
}


def _settlement_at_the_first_fee_breakpoint(api: ApiClient):
    """A Ballroom C booking whose contracted rental lands exactly on the first fee tier."""
    return setup_event_lifecycle(
        api,
        "settlement_issued",
        space=dict(BALLROOM_C),
        deposit_cents=1300000,
        booking=dict(BOAT_SHOW_DATES),
    )


def test_four_billable_units_price_to_exactly_five_million_cents(api: ApiClient):
    """One move-in day, three show days and one move-out day price to 5,000,000 cents.

    PRD: "The billable units are the show days plus one half of the sum of the
    move-in and move-out days."
    PRD: "`gross_rental_cents` is the space's `daily_base_rate_cents` multiplied by
    those billable units, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/facility_fee_tier_boundary_at_exactly_five_million_subtotal_takes_mid_rate
    """
    world = _settlement_at_the_first_fee_breakpoint(api)

    booking = read_booking(api, world["booking"]["id"])
    assert_money_cents(booking["contracted_rental_cents"], 5000000, "contracted_rental_cents")


def test_subtotal_exactly_on_the_breakpoint_takes_the_middle_fee_band(api: ApiClient):
    """A subtotal of exactly 5,000,000 cents is charged 7 percent, not 9 percent.

    PRD: "A subtotal strictly below 50,000 dollars — 5,000,000 cents — takes 9
    percent; a subtotal strictly below 200,000 dollars — 20,000,000 cents — takes 7
    percent; anything else takes 5.5 percent."
    PRD: "Both breakpoints are strict less-than comparisons, so a subtotal of
    exactly 5,000,000 cents falls into the middle band at 7 percent, and a subtotal
    of exactly 20,000,000 cents falls into the top band at 5.5 percent."

    Design: Difficulty/boundary_precision_check/facility_fee_tier_boundary_at_exactly_five_million_subtotal_takes_mid_rate
    """
    world = _settlement_at_the_first_fee_breakpoint(api)

    settlement = read_settlement(api, world["settlement"]["id"])
    assert_fields(settlement, status="ISSUED")
    assert_settlement_money(
        settlement,
        line_subtotal_cents=5000000,
        facility_service_fee_cents=350000,
        grand_total_cents=5350000,
    )
    assert settlement["facility_service_fee_cents"] != 450000, (
        "a subtotal of exactly 5,000,000 cents must not take the 9 percent band"
    )


def _settlement_totalling_exactly_the_standing_threshold(api: ApiClient):
    """A settlement whose grand total after escrow lands exactly on the standing threshold."""
    world = setup_event_lifecycle(
        api,
        "settlement_issued",
        space=dict(EXHIBIT_HALL_C),
        client=dict(RIVERBEND_ROTARY),
        deposit_cents=3100000,
        booking=dict(AUTUMN_FAIR_DATES),
        rental_line_cents=12000000,
        # PRD: "appending one does not recompute any settlement total - totals move
        # only when the settlement is issued." The reconciling adjustment that lands
        # the threshold exactly must therefore be appended before the issue.
        extra_lines=[("ADJUSTMENT", 149533)],
    )
    world["settlement"] = read_settlement(api, world["settlement"]["id"])
    set_clock(api, "2027-09-23T10:00:00Z")
    return world


def test_finalization_totals_exactly_ten_million_after_applying_escrow(api: ApiClient):
    """The rental, the adjustment, the 7 percent fee and the escrow net to 10,000,000 cents.

    PRD: "Step four: `deposit_applied_cents` is the license's `deposit_held_cents`
    at finalization, and zero at every earlier point."
    PRD: "The ordinary door drives `ISSUED → FINAL` and belongs to the
    `SettlementAnalyst`: the acting `X-User-ID` must differ from
    `issued_by_user_id` per §2.12, else `ERR_SEGREGATION_OF_DUTIES`, and the logical
    clock instant must be strictly past `dispute_deadline_utc`, else
    `ERR_DISPUTE_WINDOW_OPEN` — the licensee's window must have run out before the
    house may close the book."

    Design: Difficulty/boundary_precision_check/client_standing_threshold_at_exactly_ten_million_outstanding_stays_good
    """
    world = _settlement_totalling_exactly_the_standing_threshold(api)

    response = api.finalize_settlement(
        world["settlement"]["id"], headers=make_analyst_headers(ANALYST_TWO)
    )
    validate_success(response, expected_status=200)

    settlement = read_settlement(api, world["settlement"]["id"])
    assert_fields(settlement, status="FINAL")
    assert_settlement_money(
        settlement,
        line_subtotal_cents=12149533,
        facility_service_fee_cents=850467,
        deposit_applied_cents=3000000,
        grand_total_cents=10000000,
    )
    assert_fields(read_booking(api, world["booking"]["id"]), status="SETTLED")


def test_outstanding_balance_exactly_at_the_threshold_leaves_standing_good(api: ApiClient):
    """An outstanding balance of exactly 10,000,000 cents does not restrict the client.

    PRD: "`outstanding_balance_cents` is the sum of `grand_total_cents` over every
    settlement reachable from this client through its bookings whose `status` is
    `FINAL`; settlements sitting in `DRAFT`, `ISSUED`, `DISPUTED` or `ARBITRATION`
    contribute nothing."
    PRD: "Standing becomes `HOLD_RESTRICTED` when that outstanding total is strictly
    greater than 100,000 dollars — 10,000,000 cents — and is `GOOD` otherwise."
    PRD: "The comparison is strict: an outstanding balance of exactly 10,000,000
    cents leaves the client `GOOD`."

    Design: Difficulty/boundary_precision_check/client_standing_threshold_at_exactly_ten_million_outstanding_stays_good
    """
    world = _settlement_totalling_exactly_the_standing_threshold(api)

    api.finalize_settlement(world["settlement"]["id"], headers=make_analyst_headers(ANALYST_TWO))

    client = read_client(api, world["client"]["id"])
    assert_money_cents(client["outstanding_balance_cents"], 10000000, "outstanding_balance_cents")
    assert_fields(client, booking_standing="GOOD")


def _actual_usage_settlement_with_no_attested_days(api: ApiClient):
    """A closed booking with no usage records and a DRAFT ACTUAL_USAGE settlement."""
    world = setup_event_lifecycle(
        api,
        "settlement_draft",
        space=dict(BALLROOM_C),
        deposit_cents=1300000,
        booking=dict(BOAT_SHOW_DATES),
        settlement_basis="ACTUAL_USAGE",
    )
    append_line_item(
        api,
        world["settlement"]["id"],
        "RENTAL",
        100000,
        memo="placeholder rental",
        analyst_id=ANALYST_ONE,
    )
    return world


def test_actual_usage_issue_with_no_attested_days_is_refused(api: ApiClient):
    """An actual-usage settlement over an empty record set is refused, not summed to zero.

    PRD: "When the `basis` is `ACTUAL_USAGE`, at least one usage record must exist
    for the booking, else `ERR_NO_USAGE_RECORDS`."
    PRD: "17. **Settlement composition**, in this order: usage records present for
    an actual-usage basis (`ERR_NO_USAGE_RECORDS`), rental line agreement
    (`ERR_RENTAL_LINE_MISMATCH`), child obligations discharged before close
    (`ERR_SERVICE_ORDERS_NOT_RECONCILED`)."

    Design: Difficulty/boundary_precision_check/actual_usage_settlement_with_empty_usage_record_set_returns_4XX
    """
    world = _actual_usage_settlement_with_no_attested_days(api)

    response = api.issue_settlement(
        world["settlement"]["id"], headers=make_analyst_headers(ANALYST_ONE)
    )
    validate_error(response, ApiErrorId.NO_USAGE_RECORDS, expected_status=422)


def test_empty_usage_set_leaves_the_settlement_and_booking_where_they_stood(api: ApiClient):
    """The refused issue leaves a zero-valued DRAFT settlement over a CLOSED booking.

    PRD: "The settlement opens in `status` `DRAFT` with `revision_round` 0 and every
    money field at 0: `line_subtotal_cents`, `facility_service_fee_cents`,
    `deposit_applied_cents` and `grand_total_cents`."
    PRD: "Because usage records are immutable and append-only, every record for the
    booking participates with no status filter."

    Design: Difficulty/boundary_precision_check/actual_usage_settlement_with_empty_usage_record_set_returns_4XX
    """
    world = _actual_usage_settlement_with_no_attested_days(api)

    api.issue_settlement(world["settlement"]["id"], headers=make_analyst_headers(ANALYST_ONE))

    settlement = read_settlement(api, world["settlement"]["id"])
    assert_fields(settlement, status="DRAFT")
    assert_settlement_money(settlement, line_subtotal_cents=0, grand_total_cents=0)
    assert_fields(read_booking(api, world["booking"]["id"]), status="CLOSED")
