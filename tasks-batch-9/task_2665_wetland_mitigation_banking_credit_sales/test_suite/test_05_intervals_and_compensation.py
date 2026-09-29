"""Interval semantics on the monitoring calendar and the reservation calendar,
plus the append-only compensating entries that keep credits and money conserved.

The monitoring calendar of a bank uses half-open windows, so adjacency at a
shared instant is legal; a permit holder's reservation holds are closed at both
ends, so touching endpoints collide. Cancellation of a reservation and reversal
of a settled sale are both written as fresh compensating ledger rows rather than
by rewriting history.
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_append_only_event_fields,
    assert_cents,
    assert_credit_conservation,
    assert_credit_sale,
    assert_credits,
    assert_ledger_sequence,
    assert_ledger_shape,
    assert_monitoring_report,
    assert_score,
    bank_state,
    cancel_sale,
    cancel_sale_payload,
    create_monitoring_report_payload,
    credit_forecast,
    execute_sale,
    ledger_rows,
    measurements,
    open_monitoring_report,
    permittee_state,
    quote_credits,
    reserve_sale,
    reverse_sale,
    review_monitoring_report,
    sale_state,
    set_clock,
    setup_monitoring_ready_bank,
    setup_sellable_bank,
    submit_monitoring_report,
    validate_error,
    validate_paginated,
    validate_success,
)

# The four standards of the shared work plan: the two year-1 standards are the
# only ones effective in monitoring years 1 and 2.
YEAR12_MEASUREMENTS = measurements(HYDROPERIOD_DAYS=124, INVASIVE_COVER_PCT=9.0)
YEAR2_MEASUREMENTS = measurements(HYDROPERIOD_DAYS=126, INVASIVE_COVER_PCT=8.0)
YEAR3_MEASUREMENTS = measurements(
    HYDROPERIOD_DAYS=127,
    INVASIVE_COVER_PCT=7.5,
    NATIVE_COVER_PCT=84.0,
    STEM_DENSITY_PER_ACRE=415,
)


def _instant(value: str) -> datetime:
    """Parse a server-stamped ISO 8601 UTC timestamp into a comparable instant,
    so a three-fractional-digit stamp compares equal to a whole-second literal."""
    assert value is not None, "expected a timestamp, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _calendar_world() -> dict:
    """A bank in INSTRUMENT_EXECUTED with its four standards materialised, the
    clock moved to 2027-12-01 and a year-1 report occupying [2027-03-01,
    2027-06-01) in DRAFT."""
    world = setup_monitoring_ready_bank()
    set_clock("2027-12-01T00:00:00Z")
    world["reports"][1] = open_monitoring_report(
        world,
        monitoring_year=1,
        window_start="2027-03-01T00:00:00Z",
        window_end="2027-06-01T00:00:00Z",
        measurements_array=YEAR12_MEASUREMENTS,
    )
    return world


def test_monitoring_window_starting_at_an_existing_window_end_is_accepted():
    """A year-2 window whose start equals the year-1 window's end instant is
    admitted: half-open windows that merely touch do not intersect.

    PRD §3.7: "Those windows are half-open, so a new window whose start equals an
    existing window's end is perfectly acceptable adjacency; only a positive-length
    intersection with an occupying window is rejected, with
    `ERR_MONITORING_WINDOW_OVERLAP`."
    PRD §3.7: "A new report opens with its review status at `DRAFT`, its compliance
    status at `UNEVALUATED`, `return_count` at 0, `attainment_score` null,
    `failed_standard_codes` empty, and `reviewed_by_member_id`, `submitted_at` and
    `reviewed_at` all null."
    Design: Difficulty/resource_temporal_overlap/monitoring_windows_are_half_open_so_adjacency_is_legal
    """
    world = _calendar_world()
    year1 = world["reports"][1]
    assert year1["review_status"] == "DRAFT", (
        f"the year-1 report must occupy the calendar in DRAFT, got {year1['review_status']}"
    )

    adjacent = validate_success(
        api_client.create_monitoring_report(
            create_monitoring_report_payload(
                world["bank"]["id"],
                monitoring_year=2,
                window_start="2027-06-01T00:00:00Z",
                window_end="2027-09-01T00:00:00Z",
                measurements_array=YEAR2_MEASUREMENTS,
            ),
            world["sponsor_headers"],
        ),
        201,
    )

    assert_monitoring_report(adjacent)
    assert _instant(adjacent["window_start"]) == _instant(year1["window_end"]), (
        "the accepted year-2 window must start exactly where the year-1 window ended"
    )
    assert adjacent["review_status"] == "DRAFT", (
        f"a new report opens in DRAFT, got {adjacent['review_status']}"
    )
    assert adjacent["compliance_status"] == "UNEVALUATED", (
        f"a new report opens UNEVALUATED, got {adjacent['compliance_status']}"
    )
    assert adjacent["return_count"] == 0, "a new report opens with return_count 0"
    assert adjacent["attainment_score"] is None, "a new report carries no score yet"
    assert adjacent["failed_standard_codes"] == [], (
        "a new report opens with an empty failed_standard_codes list"
    )


def test_monitoring_window_overlapping_an_occupied_window_is_rejected():
    """A year-3 window that intersects the occupied year-2 window by 17 days is a
    positive-length intersection and is refused.

    PRD §3.7: "The monitoring windows of one bank may not overlap."
    PRD §3.7: "Those windows are half-open, so a new window whose start equals an
    existing window's end is perfectly acceptable adjacency; only a positive-length
    intersection with an occupying window is rejected, with
    `ERR_MONITORING_WINDOW_OVERLAP`."
    Design: Difficulty/resource_temporal_overlap/monitoring_windows_are_half_open_so_adjacency_is_legal
    """
    world = _calendar_world()
    open_monitoring_report(
        world,
        monitoring_year=2,
        window_start="2027-06-01T00:00:00Z",
        window_end="2027-09-01T00:00:00Z",
        measurements_array=YEAR2_MEASUREMENTS,
    )

    overlapping = api_client.create_monitoring_report(
        create_monitoring_report_payload(
            world["bank"]["id"],
            monitoring_year=3,
            window_start="2027-08-15T00:00:00Z",
            window_end="2027-11-15T00:00:00Z",
            measurements_array=YEAR3_MEASUREMENTS,
        ),
        world["sponsor_headers"],
    )

    validate_error(overlapping, ApiErrorId.ERR_MONITORING_WINDOW_OVERLAP, 409)

    rows, _meta = validate_paginated(
        api_client.list_monitoring_reports(
            world["sponsor_headers"],
            params={"bank_id": world["bank"]["id"], "limit": 100},
        )
    )
    assert len(rows) == 2, (
        f"the rejected creation must not have written a report row, got {len(rows)} reports"
    )


def test_returned_monitoring_report_releases_its_window_slot():
    """Once the year-2 report is RETURNED it stops occupying the calendar, so the
    previously overlapping year-3 window is admitted unchanged.

    PRD §3.7: "Occupying windows are again those of reports in `DRAFT`, `SUBMITTED`
    or `ACCEPTED`."
    PRD §3.7: "The monitoring year must be at least 1 and must be unique within the
    bank among reports whose review status is `DRAFT`, `SUBMITTED` or `ACCEPTED` — a
    duplicate is rejected with `ERR_DUPLICATE_MONITORING_YEAR`, while a `RETURNED`
    report releases its year and its window slot back."
    PRD §3.7: "Returning advances the review status `SUBMITTED → RETURNED`, raises
    `return_count` by one, records the acting member into `reviewed_by_member_id`,
    stamps `reviewed_at`, and requires a `return_reason`."
    PRD §3.7: "The return branch performs no scoring at all: the compliance status
    stays `UNEVALUATED`, no remedial action is created, no milestone is deferred, no
    posture changes, and the bank's `version` is *not* incremented."
    Design: Difficulty/resource_temporal_overlap/monitoring_windows_are_half_open_so_adjacency_is_legal
    """
    world = _calendar_world()
    year2 = open_monitoring_report(
        world,
        monitoring_year=2,
        window_start="2027-06-01T00:00:00Z",
        window_end="2027-09-01T00:00:00Z",
        measurements_array=YEAR2_MEASUREMENTS,
    )
    submit_monitoring_report(world, year2["id"])
    returned = review_monitoring_report(
        world,
        year2["id"],
        "RETURN",
        member_index=2,
        return_reason="Vegetation transect map does not match the recorded window.",
    )

    assert returned["review_status"] == "RETURNED", (
        f"the RETURN branch must land on RETURNED, got {returned['review_status']}"
    )
    assert returned["return_count"] == 1, (
        f"the RETURN branch raises return_count to 1, got {returned['return_count']}"
    )
    assert returned["compliance_status"] == "UNEVALUATED", (
        "the RETURN branch performs no scoring, so compliance stays UNEVALUATED"
    )
    assert _instant(returned["window_start"]) == _instant("2027-06-01T00:00:00Z"), (
        "the returned report keeps its original window_start"
    )
    assert _instant(returned["window_end"]) == _instant("2027-09-01T00:00:00Z"), (
        "the returned report keeps its original window_end"
    )

    freed = validate_success(
        api_client.create_monitoring_report(
            create_monitoring_report_payload(
                world["bank"]["id"],
                monitoring_year=3,
                window_start="2027-08-15T00:00:00Z",
                window_end="2027-11-15T00:00:00Z",
                measurements_array=YEAR3_MEASUREMENTS,
            ),
            world["sponsor_headers"],
        ),
        201,
    )

    assert freed["review_status"] == "DRAFT", (
        f"the freed year-3 window opens a DRAFT report, got {freed['review_status']}"
    )
    assert freed["compliance_status"] == "UNEVALUATED", (
        f"the freed year-3 report opens UNEVALUATED, got {freed['compliance_status']}"
    )

    rows, _meta = validate_paginated(
        api_client.list_monitoring_reports(
            world["sponsor_headers"],
            params={"bank_id": world["bank"]["id"], "limit": 100},
        )
    )
    assert len(rows) == 3, f"three report rows must exist for the bank, got {len(rows)}"

    bank = bank_state(world)
    assert bank["status"] == "INSTRUMENT_EXECUTED", (
        f"a RETURN moves no bank lifecycle status, got {bank['status']}"
    )


def _reservation_world():
    """A sellable bank, one permit holder holding two QUOTED sales of 4.00 credits
    each, and sale A reserved at 2026-08-15 so its closed hold interval runs
    [2026-08-15T00:00:00Z, 2026-09-14T00:00:00Z]."""
    world = setup_sellable_bank()
    set_clock("2026-08-15T00:00:00Z")
    sale_a = quote_credits(world, 4.00)
    sale_b = quote_credits(world, 4.00)
    reserved_a = reserve_sale(world, sale_a["id"])
    return world, sale_a, sale_b, reserved_a


def test_reservation_hold_touching_an_existing_expiry_instant_collides():
    """A second hold whose start equals the live hold's expiry instant is refused:
    reservation holds are closed at both ends, so touching endpoints intersect.

    PRD §3.8: "One further check protects the bank from a buyer sitting on
    overlapping options: the prospective hold, running from the current clock through
    30 days later, may not intersect the hold interval of any other reserved sale
    belonging to the same permit holder."
    PRD §3.8: "Both the prospective and the existing intervals are closed at both
    ends, so touching endpoints do collide — a new hold beginning exactly at an
    existing hold's expiry instant is rejected, precisely because the expiry sweep
    only releases a hold once the clock has passed strictly beyond it."
    PRD §3.8: "A collision is rejected with `ERR_RESERVATION_HOLD_CONFLICT`."
    Design: Difficulty/resource_temporal_overlap/reservation_holds_are_closed_so_touching_endpoints_collide
    """
    world, _sale_a, sale_b, reserved_a = _reservation_world()

    assert reserved_a["status"] == "RESERVED", (
        f"sale A must be RESERVED before the collision test, got {reserved_a['status']}"
    )
    assert _instant(reserved_a["hold_start_at"]) == _instant("2026-08-15T00:00:00Z"), (
        "hold_start_at is stamped with the current clock"
    )
    assert _instant(reserved_a["hold_expires_at"]) == _instant("2026-09-14T00:00:00Z"), (
        "hold_expires_at is stamped 30 days after hold_start_at"
    )

    set_clock("2026-09-14T00:00:00Z")
    collision = api_client.reserve_credit_sale(
        sale_b["id"], world["permittee_headers"]
    )
    validate_error(collision, ApiErrorId.ERR_RESERVATION_HOLD_CONFLICT, 409)

    refused = sale_state(sale_b["id"], world)
    assert refused["status"] == "QUOTED", (
        f"the refused reservation leaves sale B in QUOTED, got {refused['status']}"
    )
    assert refused["hold_start_at"] is None, (
        "the refused reservation stamps no hold_start_at on sale B"
    )
    assert refused["hold_expires_at"] is None, (
        "the refused reservation stamps no hold_expires_at on sale B"
    )

    bank = bank_state(world)
    assert_credits(bank["credits_on_hold"], 4.00, "credits_on_hold after the refusal")
    assert_credits(bank["credits_available"], 10.82, "credits_available after the refusal")
    assert_credit_conservation(bank)


def test_reservation_one_second_past_expiry_sweeps_the_old_hold_and_succeeds():
    """One second past the expiry instant the lazy sweep expires the old hold, and
    the identical reservation then succeeds with a fresh 30-day interval.

    PRD §3.8: "A reserved sale whose `hold_expires_at` lies **strictly** before the
    current logical clock moves `RESERVED → EXPIRED`, appends a `HOLD_RELEASED` entry
    returning its requested credits to the available pool, records a
    `cancelled_reason` of `HOLD_EXPIRED` and stamps `cancelled_at`."
    PRD §3.8: "Reservation stamps `hold_start_at` with the current clock and
    `hold_expires_at` 30 days later, appends a `HOLD_PLACED` entry carrying the
    requested credits as a negative delta and attributed through a source entity type
    of `CREDIT_SALE` and the sale's own identifier, recomputes the bank's credits on
    hold and available credits and its posture, recomputes the bank's
    `open_quote_count`, and increments the bank's `version` by one."
    Design: Difficulty/resource_temporal_overlap/reservation_holds_are_closed_so_touching_endpoints_collide
    """
    world, sale_a, sale_b, _reserved_a = _reservation_world()

    set_clock("2026-09-14T00:00:01Z")
    reserved_b = validate_success(
        api_client.reserve_credit_sale(sale_b["id"], world["permittee_headers"]), 200
    )

    assert_credit_sale(reserved_b)
    assert reserved_b["status"] == "RESERVED", (
        f"sale B must reserve once the old hold has lapsed, got {reserved_b['status']}"
    )
    assert _instant(reserved_b["hold_start_at"]) == _instant("2026-09-14T00:00:01Z"), (
        "sale B's hold_start_at is the clock at reservation time"
    )
    assert _instant(reserved_b["hold_expires_at"]) == _instant("2026-10-14T00:00:01Z"), (
        "sale B's hold_expires_at is 30 days after its hold_start_at"
    )

    swept = sale_state(sale_a["id"], world)
    assert swept["status"] == "EXPIRED", (
        f"the sweep must expire sale A once the clock passed its expiry, got {swept['status']}"
    )
    assert swept["cancelled_reason"] == "HOLD_EXPIRED", (
        f"the sweep records HOLD_EXPIRED, got {swept['cancelled_reason']}"
    )
    assert swept["cancelled_at"] is not None, "the sweep stamps cancelled_at"


def test_expired_hold_is_not_double_counted_in_the_ledger():
    """The sweep's HOLD_RELEASED row and the new HOLD_PLACED row are separate
    appends, so the lapsed hold is returned once and only once.

    PRD §2.11: "Each entry belongs to exactly one bank through its `bank_id` and
    carries a `sequence_number` that starts at 1 for that bank's first entry and
    increases by one for each subsequent append, in append order."
    PRD §2.11: "`credits_on_hold` is the negation of the total of the deltas of its
    `HOLD_PLACED` and `HOLD_RELEASED` entries taken together."
    PRD §2.11: "The invariant no endpoint may ever break is that released credits
    equal the sum of sold, on-hold and available credits, and that available credits
    equal the `balance_after` of the bank's highest-numbered ledger entry."
    Design: Difficulty/resource_temporal_overlap/reservation_holds_are_closed_so_touching_endpoints_collide
    """
    world, _sale_a, sale_b, _reserved_a = _reservation_world()

    set_clock("2026-09-14T00:00:01Z")
    validate_success(
        api_client.reserve_credit_sale(sale_b["id"], world["permittee_headers"]), 200
    )

    entries = ledger_rows(world)
    assert_ledger_sequence(entries)
    assert_ledger_shape(
        entries,
        [
            ("GENERATED", 0.00, 0.00),
            ("RELEASED", 14.82, 14.82),
            ("HOLD_PLACED", -4.00, 10.82),
            ("HOLD_RELEASED", 4.00, 14.82),
            ("HOLD_PLACED", -4.00, 10.82),
        ],
    )

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 14.82, "credits_released")
    assert_credits(bank["credits_sold"], 0.00, "credits_sold")
    assert_credits(bank["credits_on_hold"], 4.00, "credits_on_hold")
    assert_credits(bank["credits_available"], 10.82, "credits_available")
    assert_credit_conservation(bank)
    assert_credits(
        entries[-1]["balance_after"],
        bank["credits_available"],
        "the highest-numbered balance_after must equal credits_available",
    )


def _held_reservation_world():
    """A sellable bank whose 8.00-credit quote has been reserved, so 8.00 credits
    stand on hold and 6.82 remain available. The clock is still at 2026-08-01."""
    world = setup_sellable_bank()
    sale = quote_credits(world, 8.00)
    reserved = reserve_sale(world, sale["id"])
    return world, sale, reserved


def test_cancelling_a_reservation_restores_the_credit_conservation_identity():
    """The hold takes 8.00 credits out of the available pool and the compensating
    cancellation puts exactly those 8.00 back, with the identity holding at both
    observation points.

    PRD §3.8: "Cancelling a reservation advances `RESERVED → CANCELLED`, and
    additionally appends a `HOLD_RELEASED` entry returning the held credits to the
    available pool before recomputing the bank's on-hold and available credits and
    its posture."
    PRD §2.11: "The invariant no endpoint may ever break is that released credits
    equal the sum of sold, on-hold and available credits, and that available credits
    equal the `balance_after` of the bank's highest-numbered ledger entry."
    Design: Difficulty/compensating_invariant/reservation_cancellation_restores_credit_conservation
    """
    world, sale, reserved = _held_reservation_world()
    assert reserved["status"] == "RESERVED", (
        f"the sale must stand RESERVED before cancellation, got {reserved['status']}"
    )

    held = bank_state(world)
    assert_credits(held["credits_released"], 14.82, "credits_released while held")
    assert_credits(held["credits_sold"], 0.00, "credits_sold while held")
    assert_credits(held["credits_on_hold"], 8.00, "credits_on_hold while held")
    assert_credits(held["credits_available"], 6.82, "credits_available while held")
    assert_credit_conservation(held)

    cancel_sale(world, sale["id"], "BUYER_WITHDREW")

    after = bank_state(world)
    assert_credits(after["credits_released"], 14.82, "credits_released after cancellation")
    assert_credits(after["credits_sold"], 0.00, "credits_sold after cancellation")
    assert_credits(after["credits_on_hold"], 0.00, "credits_on_hold after cancellation")
    assert_credits(after["credits_available"], 14.82, "credits_available after cancellation")
    assert_credit_conservation(after)
    assert after["sales_posture"] == "OPEN", (
        f"the bank stays OPEN throughout the hold and its release, got {after['sales_posture']}"
    )


def test_cancelling_a_reservation_appends_a_row_without_rewriting_the_hold():
    """The compensation is a new HOLD_RELEASED append: the earlier HOLD_PLACED row is
    byte-for-byte untouched and no ledger row carries updated_at or version.

    PRD §2.11: "The ledger is append-only: no entry is ever amended and none is ever
    deleted, so every aggregate is recomputable from history alone."
    PRD §2.4: "A credit ledger entry is likewise append-only and never rewritten or
    deleted: it too carries only `id` and `created_at`, with no `updated_at` and no
    `version`."
    PRD §3.8: "Cancelling a reservation advances `RESERVED → CANCELLED`, and
    additionally appends a `HOLD_RELEASED` entry returning the held credits to the
    available pool before recomputing the bank's on-hold and available credits and
    its posture."
    Design: Difficulty/compensating_invariant/reservation_cancellation_restores_credit_conservation
    """
    world, sale, _reserved = _held_reservation_world()

    before = ledger_rows(world)
    assert len(before) == 3, (
        f"expected GENERATED, RELEASED and HOLD_PLACED before cancellation, got {len(before)} rows"
    )
    hold_placed_before = dict(before[2])

    cancel_sale(world, sale["id"], "BUYER_WITHDREW")

    entries = ledger_rows(world)
    assert_ledger_sequence(entries)
    assert_ledger_shape(
        entries,
        [
            ("GENERATED", 0.00, 0.00),
            ("RELEASED", 14.82, 14.82),
            ("HOLD_PLACED", -8.00, 6.82),
            ("HOLD_RELEASED", 8.00, 14.82),
        ],
    )
    assert entries[2] == hold_placed_before, (
        "the HOLD_PLACED row must be identical after the compensation: "
        f"{hold_placed_before} became {entries[2]}"
    )
    for entry in entries:
        assert_append_only_event_fields(entry)
    assert entries[3]["source_entity_type"] == "CREDIT_SALE", (
        "the compensating row is attributed to the credit sale"
    )
    assert entries[3]["source_id"] == sale["id"], (
        "the compensating row names the cancelled sale as its source"
    )


def test_cancelled_reservation_leaves_a_terminal_sale_and_no_open_quote():
    """The cancelled sale records its reason and stamp and leaves the bank's derived
    open-quote tally at zero.

    PRD §3.8: "Cancelling a reservation advances `RESERVED → CANCELLED`, and
    additionally appends a `HOLD_RELEASED` entry returning the held credits to the
    available pool before recomputing the bank's on-hold and available credits and
    its posture."
    PRD §3.8: "That counter is a derived tally rather than a hand-maintained number:
    it is the count of the bank's credit sales standing in either `QUOTED` or
    `RESERVED`, so a quote that is placed on hold continues to be counted, and a sale
    leaves the tally only when it settles, is withdrawn or expires."
    PRD §2.6: "Every timestamp the server stamps, every window comparison, every hold
    expiry and every demand quarter boundary is computed from that clock."
    Design: Difficulty/compensating_invariant/reservation_cancellation_restores_credit_conservation
    """
    world, sale, _reserved = _held_reservation_world()

    cancelled = validate_success(
        api_client.cancel_credit_sale(
            sale["id"],
            cancel_sale_payload("BUYER_WITHDREW"),
            world["permittee_headers"],
        ),
        200,
    )

    assert_credit_sale(cancelled)
    assert cancelled["status"] == "CANCELLED", (
        f"a withdrawn reservation lands on CANCELLED, got {cancelled['status']}"
    )
    assert cancelled["cancelled_reason"] == "BUYER_WITHDREW", (
        f"the supplied reason is recorded, got {cancelled['cancelled_reason']}"
    )
    assert _instant(cancelled["cancelled_at"]) == _instant("2026-08-01T00:00:00Z"), (
        "cancelled_at is stamped from the logical clock"
    )

    bank = bank_state(world)
    assert bank["open_quote_count"] == 0, (
        f"a terminal sale leaves the open quote tally at 0, got {bank['open_quote_count']}"
    )


def _executed_sale_world():
    """A sellable bank whose endowment sits at the interim gate (so the 8 percent
    stewardship surcharge applies) and a permit holder with a 40,000,000-cent deposit
    whose 8.00-credit sale has been quoted, reserved and settled at 2026-08-01."""
    world = setup_sellable_bank(permittee_deposit_cents=40_000_000)
    sale = quote_credits(world, 8.00)
    reserve_sale(world, sale["id"])
    executed = execute_sale(world, sale["id"])
    return world, sale, executed


def test_reversing_a_settled_sale_returns_the_whole_settled_price_to_escrow():
    """The compensating reversal returns the full 32,216,400-cent settled price to
    escrow while retaining that figure on the sale row for audit.

    PRD §3.9: "Reversal advances the sale `EXECUTED → CANCELLED` with a
    `cancelled_reason` of `IRT_REVERSAL` and a `cancelled_at` stamp, appends a
    `SALE_REVERSED` entry carrying the requested credits back as a positive delta, and
    recomputes the bank's sold credits and available credits so that the ledger
    balance returns exactly to its pre-settlement value with no drift whatsoever."
    PRD §3.9: "Because the reversed sale has left the settled-and-assigned set, the
    buyer's escrow balance is recomputed and the full settled price returns to escrow."
    PRD §3.9: "The settled price itself is deliberately **retained** on the sale row
    for audit rather than nulled out, so the record of what was charged survives the
    reversal."
    PRD §3.1: "`escrow_balance_cents` is the deposited total minus the sum of the
    settled prices of all of this holder's sales standing in `EXECUTED` or `ASSIGNED`
    status, and likewise starts at 0."
    Design: Difficulty/compensating_invariant/sale_reversal_restores_escrow_and_demand_index_exactly
    """
    world, sale, executed = _executed_sale_world()

    assert_cents(executed["quoted_price_cents"], 32216400, "quoted_price_cents")
    assert_cents(executed["executed_price_cents"], 32216400, "executed_price_cents")

    buyer_before = permittee_state(world)
    assert_cents(buyer_before["deposited_cents"], 40000000, "deposited_cents before reversal")
    assert_cents(
        buyer_before["escrow_balance_cents"], 7783600, "escrow_balance_cents before reversal"
    )

    reversed_sale = validate_success(
        api_client.reverse_credit_sale(sale["id"], world["chair_headers"]), 200
    )

    assert reversed_sale["status"] == "CANCELLED", (
        f"a reversed sale lands on CANCELLED, got {reversed_sale['status']}"
    )
    assert reversed_sale["cancelled_reason"] == "IRT_REVERSAL", (
        f"the reversal records IRT_REVERSAL, got {reversed_sale['cancelled_reason']}"
    )
    assert reversed_sale["cancelled_at"] is not None, "the reversal stamps cancelled_at"
    assert_cents(
        reversed_sale["executed_price_cents"],
        32216400,
        "executed_price_cents retained after reversal",
    )

    buyer_after = permittee_state(world)
    assert_cents(
        buyer_after["escrow_balance_cents"], 40000000, "escrow_balance_cents after reversal"
    )
    assert_cents(
        buyer_after["deposited_cents"], 40000000, "deposited_cents after reversal"
    )


def test_reversing_a_settled_sale_restores_the_ledger_balance_exactly():
    """Settlement's HOLD_RELEASED and SOLD pair and the reversal's SALE_REVERSED row
    are six append-only entries whose running balance returns to 14.82.

    PRD §3.8: "On success the settled price is stamped onto `executed_price_cents`,
    `executed_at` is stamped with the clock, and **two** ledger entries are appended
    in a pinned order: first a `HOLD_RELEASED` entry returning the requested credits
    as a positive delta, then a `SOLD` entry taking the same quantity away as a
    negative delta."
    PRD §2.11: "`credits_sold` is the negation of the total of the deltas of its
    `SOLD` and `SALE_REVERSED` entries taken together, so a reversal genuinely reduces
    the sold quantity rather than merely annotating it."
    PRD §2.11: "The ledger is append-only: no entry is ever amended and none is ever
    deleted, so every aggregate is recomputable from history alone."
    Design: Difficulty/compensating_invariant/sale_reversal_restores_escrow_and_demand_index_exactly
    """
    world, sale, _executed = _executed_sale_world()

    sold_state = bank_state(world)
    assert_credits(sold_state["credits_sold"], 8.00, "credits_sold before reversal")
    assert_credits(sold_state["credits_available"], 6.82, "credits_available before reversal")

    reverse_sale(world, sale["id"])

    entries = ledger_rows(world)
    assert_ledger_sequence(entries)
    assert_ledger_shape(
        entries,
        [
            ("GENERATED", 0.00, 0.00),
            ("RELEASED", 14.82, 14.82),
            ("HOLD_PLACED", -8.00, 6.82),
            ("HOLD_RELEASED", 8.00, 14.82),
            ("SOLD", -8.00, 6.82),
            ("SALE_REVERSED", 8.00, 14.82),
        ],
    )
    for entry in entries:
        assert_append_only_event_fields(entry)

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 14.82, "credits_released after reversal")
    assert_credits(bank["credits_sold"], 0.00, "credits_sold after reversal")
    assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold after reversal")
    assert_credits(bank["credits_available"], 14.82, "credits_available after reversal")
    assert_credit_conservation(bank)
    assert bank["sales_posture"] == "OPEN", (
        f"14.82 available credits leave the bank OPEN, got {bank['sales_posture']}"
    )


def test_reversed_sale_drops_out_of_the_demand_measurement():
    """The reversed sale leaves the EXECUTED/ASSIGNED input set, so the demand index
    falls from 0.3200 back to 0.0000 and the forecast reconciles against the ledger.

    PRD §3.8: "For each quarter the server sums the requested credits of the bank's
    sales standing in `EXECUTED` or `ASSIGNED` status whose `executed_at` falls inside
    that quarter; sales in `QUOTED`, `RESERVED`, `CANCELLED` or `EXPIRED` status are
    excluded entirely, which means a reversed sale drops straight out of the
    measurement."
    PRD §3.8: "The `demand_index` is that pressure divided by a normaliser of 10.00
    credits, capped at a ceiling of 3.0, with the result rounded half up to 4 decimal
    places."
    PRD §3.9: "`trailing_quarter_average_credits` is the total requested credits of
    the bank's sales standing in `EXECUTED` or `ASSIGNED` whose settlement instant
    falls inside the trailing 360-day window measured back from the current clock,
    divided by 4, rounded half up to 2 decimal places."
    Design: Difficulty/compensating_invariant/sale_reversal_restores_escrow_and_demand_index_exactly
    """
    world, sale, _executed = _executed_sale_world()

    # Read the forecast a fortnight after settlement, so the settlement instant lies
    # strictly inside both the most recent 90-day quarter and the trailing 360 days.
    set_clock("2026-08-15T00:00:00Z")
    before = credit_forecast(world)
    assert_score(before["demand_index"], 0.3200, "demand_index before reversal")
    assert_credits(
        before["trailing_quarter_average_credits"],
        2.00,
        "trailing_quarter_average_credits before reversal",
    )
    assert before["projected_quarters_to_sellout"] == 4, (
        "6.82 available credits over a 2.00-credit quarterly average round up to 4 "
        f"quarters, got {before['projected_quarters_to_sellout']}"
    )

    reverse_sale(world, sale["id"])

    after = credit_forecast(world)
    assert_score(after["demand_index"], 0.0000, "demand_index after reversal")
    assert_credits(
        after["trailing_quarter_average_credits"],
        0.00,
        "trailing_quarter_average_credits after reversal",
    )
    assert_credits(after["credits_available"], 14.82, "credits_available in the forecast")
    assert_credits(after["credits_sold"], 0.00, "credits_sold in the forecast")
    assert_credits(after["credits_on_hold"], 0.00, "credits_on_hold in the forecast")
