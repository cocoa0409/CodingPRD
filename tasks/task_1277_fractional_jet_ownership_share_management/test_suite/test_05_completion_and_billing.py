"""Flight completion, provisional-vs-final billing variants, per-line rounding, quotes."""
import pytest

from test_helpers import (
    ApiErrorId,
    assign_booking_ok,
    complete_booking_ok,
    create_aircraft,
    create_booking_ok,
    create_completed_booking,
    create_confirmed_booking,
    create_invoice_ok,
    create_transfer_listing_ok,
    get_aircraft,
    get_booking,
    get_share,
    issue_invoice_ok,
    make_owner_headers,
    set_clock,
    setup_program_with_share,
    share_version,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
FLEET = TEST_USERS["fleet_ops_headers"]
FIN = TEST_USERS["finance_ops_headers"]


def _completed_peak_booking(program_code="FJX-DV1"):
    """MID share 1/8; peak day 2026-09-07; booking est 2.00h completed at 2.50h."""
    sc = setup_program_with_share(
        program_code=program_code, class_code="MID", peak_day_calendar=["2026-09-07"],
    )
    tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N100DV")
    booking = create_booking_ok(
        sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
        "2026-09-07T15:00:00Z", 2.00, expected_share_version=sc["share"]["version"],
    )
    sc["booking"] = booking
    sc["tail"] = tail
    return sc


class TestProvisionalVsFinalBilling:
    def test_provisional_quote_prices_estimate_at_requested_rate(self, api):
        """PRD §3.3: "The quote prices the owner's `estimated_block_hours` at the
        requested class's hourly rate regardless of any interchange that may later occur,
        so it can differ from the final bill whenever actuals differ from estimates or a
        different class flies the leg."

        Design: Difficulty/dual_variant_calc/occupied_hours_provisional_vs_final_billing
        """
        sc = _completed_peak_booking()
        from test_helpers import confirm_booking_ok
        confirm_booking_ok(sc["booking"]["id"], sc["owner"]["id"])
        assign_booking_ok(sc["booking"]["id"], sc["tail"]["id"])
        resp = api.get_booking_quote(sc["booking"]["id"], FLEET)
        quote = validate_success(resp, 200)
        assert quote["provisional_total_cents"] == 900000, (
            f"provisional basis is 2.00h x 450000 = 900000, got {quote['provisional_total_cents']}"
        )

    def test_final_invoice_uses_actuals_plus_peak_surcharge(self, api):
        """PRD §3.6: "a base charge of the leg's actual hours multiplied by the requested
        class's hourly rate, rounded half-up per line, posted as an `OCCUPIED_HOURS`
        line. When the leg's `peak_day_flag` is set, a `PEAK_SURCHARGE` line adds 15
        percent of that base — 1500 basis points — again rounded half-up per line."
        PRD §3.5: "The booking moves to `COMPLETED` with `billing_status` `FINALLY_BILLED`"

        Design: Difficulty/dual_variant_calc/occupied_hours_provisional_vs_final_billing
        """
        sc = _completed_peak_booking("FJX-DV1B")
        from test_helpers import confirm_booking_ok
        confirm_booking_ok(sc["booking"]["id"], sc["owner"]["id"])
        assign_booking_ok(sc["booking"]["id"], sc["tail"]["id"])
        # Completion stamps completed_at from the clock (PRD §3.5); advance into the
        # September billing month so the leg aggregates into the 2026-09 invoice.
        set_clock("2026-09-08T00:00:00Z")
        complete_booking_ok(sc["booking"]["id"], 2.50)
        booking = get_booking(sc["booking"]["id"])
        assert booking["billing_status"] == "FINALLY_BILLED"
        assert booking["booking_status"] == "COMPLETED"

        invoice = create_invoice_ok(sc["owner"]["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        issued = issue_invoice_ok(invoice["id"])
        # base 2.50 x 450000 = 1125000; peak 15% = 168750; total 1293750.
        # The same booking quoted 900000 provisionally — two valid variants diverge.
        assert issued["occupied_hours_fee_cents"] == 1293750, (
            f"final billing must use actuals plus peak surcharge, got {issued['occupied_hours_fee_cents']}"
        )
        assert issued["occupied_hours_fee_cents"] != 900000


class TestPerLineRoundingOrder:
    def _fixture(self, program_code):
        """LIGHT share 1/4; two peak-day legs of 1.05h and 1.07h at rate 301337."""
        sc = setup_program_with_share(
            program_code=program_code, class_code="LIGHT", fraction=(1, 4),
            purchase_price_cents=4800000, peak_day_calendar=["2026-09-07"],
            hourly_rate_cents=301337,
        )
        tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N200CF")
        # Confirm and assign while the departures are still in the future, then advance
        # the clock into the September billing month: completion stamps completed_at
        # from the clock (PRD §3.5), and only September completions aggregate into the
        # 2026-09 invoice.
        b1 = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-07T10:00:00Z", 1.10,
        )
        assign_booking_ok(b1["id"], tail["id"])
        b2 = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-07T18:00:00Z", 1.10,
        )
        assign_booking_ok(b2["id"], tail["id"])
        set_clock("2026-09-08T00:00:00Z")
        complete_booking_ok(b1["id"], 1.05)
        complete_booking_ok(b2["id"], 1.07)
        invoice = create_invoice_ok(sc["owner"]["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        sc["invoice"] = invoice
        return sc

    def test_invoice_total_uses_per_line_rounding(self, api):
        """PRD §2.6: "Invoice aggregation obeys a pinned rounding order: each line
        component is rounded to whole cents individually, and only then are the line
        amounts summed into invoice totals. Summing raw values and rounding once at the
        invoice level is forbidden, because the two orders produce different cents."

        Design: Difficulty/combinatorial_formula/occupied_hours_per_line_rounding_order
        """
        sc = self._fixture("FJX-CF1")
        issued = issue_invoice_ok(sc["invoice"]["id"])
        # per-line: round(1.05 x 301337) = 316404, round(316404 x 0.15) = 47461;
        #           round(1.07 x 301337) = 322431, round(322431 x 0.15) = 48365.
        # total 734661; the forbidden sum-then-round order yields 734660.
        assert issued["occupied_hours_fee_cents"] == 734661, (
            f"per-line rounding is pinned, got {issued['occupied_hours_fee_cents']}"
        )

    def test_line_components_rounded_individually(self, api):
        """PRD §3.6: "a base charge of the leg's actual hours multiplied by the requested
        class's hourly rate, rounded half-up per line, posted as an `OCCUPIED_HOURS`
        line. When the leg's `peak_day_flag` is set, a `PEAK_SURCHARGE` line adds 15
        percent of that base — 1500 basis points — again rounded half-up per line."

        Design: Difficulty/combinatorial_formula/occupied_hours_per_line_rounding_order
        """
        sc = self._fixture("FJX-CF1B")
        issue_invoice_ok(sc["invoice"]["id"])
        lines, _meta = validate_paginated(api.list_invoice_lines(sc["invoice"]["id"], FIN))
        bases = sorted(ln["amount_cents"] for ln in lines if ln["line_kind"] == "OCCUPIED_HOURS")
        peaks = sorted(ln["amount_cents"] for ln in lines if ln["line_kind"] == "PEAK_SURCHARGE")
        assert bases == [316404, 322431], f"base lines rounded per line, got {bases}"
        assert peaks == [47461, 48365], f"peak lines rounded from the rounded base, got {peaks}"


class TestCompletionImmediateConsistency:
    def test_completion_effects_visible_immediately(self, api):
        """PRD §3.5: "The provisional debit is unwound and the actual debit applied in
        its place: the share's remaining hours are adjusted by the difference between the
        estimated and actual hours — the estimate added back, the actuals taken out — and
        this reconciliation is the one movement permitted to push the balance below zero
        into overdraft. The booking moves to `COMPLETED` with `billing_status`
        `FINALLY_BILLED`, the tail's `total_hours_flown` grows by the actual hours, the
        `version` of both the share and the aircraft advances by one"

        Design: Corner/consistency_model/completion_effects_visible_immediately
        """
        sc = setup_program_with_share(
            program_code="FJX-CM1", class_code="MID", fraction=(1, 4),
            purchase_price_cents=24000000,
        )
        tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N888CM")
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 2.00,
        )
        assign_booking_ok(booking["id"], tail["id"])
        leg = complete_booking_ok(booking["id"], 2.50)
        assert leg["actual_block_hours"] == pytest.approx(2.50, abs=0.005)

        # 200.00 entitlement: confirm debits 2.00 -> 198.00; completion reconciles
        # +2.00 - 2.50 -> 197.50, all visible in the same read epoch.
        share = get_share(sc["share"]["id"])
        assert share["hours_remaining_cy"] == pytest.approx(197.50, abs=0.005), (
            f"delta reconciliation must be visible immediately, got {share['hours_remaining_cy']}"
        )
        aircraft = get_aircraft(tail["id"])
        assert aircraft["total_hours_flown"] == pytest.approx(2.50, abs=0.005)
        booking_after = get_booking(booking["id"])
        assert booking_after["billing_status"] == "FINALLY_BILLED"
        assert booking_after["booking_status"] == "COMPLETED"


class TestFlightLegRecord:
    def test_flight_leg_is_append_only_without_version(self, api):
        """PRD §2.5: "A FlightLeg, an InvoiceLine, and a DepreciationSchedule each carry
        only `id` and `created_at`; both `updated_at` and `version` are absent on all
        three, because none of them is ever mutated in place after creation."
        PRD §3.5: "a `peak_day_flag` that is set when the scheduled departure's UTC
        calendar date appears in the program's `peak_day_calendar`"

        Design: Corner/entities/flight_leg_immutable_no_update_endpoint
        """
        sc = setup_program_with_share(
            program_code="FJX-EN6", class_code="LIGHT", fraction=(1, 4),
            purchase_price_cents=4800000,
        )
        tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N800EN")
        resp = api.complete_booking(
            create_assigned_for_leg(sc, tail), {"actual_block_hours": 1.25}, FLEET
        )
        leg = validate_success(resp, 201)
        assert "id" in leg and "created_at" in leg
        assert "version" not in leg, "FlightLeg is append-only and must not carry version"
        assert "updated_at" not in leg, "FlightLeg is append-only and must not carry updated_at"
        assert leg["peak_day_flag"] is False, "2026-09-10 is not in the peak calendar"
        assert leg["actual_block_hours"] == pytest.approx(1.25, abs=0.005)


def create_assigned_for_leg(sc, tail):
    booking = create_confirmed_booking(
        sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
        "2026-09-10T15:00:00Z", 1.00,
    )
    assign_booking_ok(booking["id"], tail["id"])
    return booking["id"]


class TestCompleteBlockedWhileListed:
    def test_completion_blocked_while_share_listed(self, api):
        """PRD §3.5: "Completion requires the booking `CONFIRMED` with an
        `assigned_aircraft_id` recorded, and the funding share still `ACTIVE`: a share
        that is `LISTED` or `IN_EXIT` blocks completion, even though its bookings could
        be created and confirmed earlier."

        Design: Corner/validations/booking_complete_blocked_while_share_listed
        """
        sc = setup_program_with_share(program_code="FJX-VA7", class_code="MID")
        tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N555VA")
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 1.00,
        )
        assign_booking_ok(booking["id"], tail["id"])
        create_transfer_listing_ok(
            sc["share"]["id"], sc["owner"]["id"], asking_price_cents=10000000,
        )
        resp = api.complete_booking(booking["id"], {"actual_block_hours": 1.00}, FLEET)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        assert get_booking(booking["id"])["booking_status"] == "CONFIRMED"


class TestQuoteSideEffectFree:
    def test_quote_is_a_pure_read(self, api):
        """PRD §3.3: "Before committing to a departure, the owner or operations staff may
        read a provisional quote on the booking, which returns a `provisional_total_cents`
        figure alongside the `notice_tier` that confirmation would freeze."

        Design: Corner/endpoints/quote_endpoint_is_side_effect_free
        """
        sc = setup_program_with_share(program_code="FJX-EP1", class_code="MID")
        booking = create_booking_ok(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 2.00, expected_share_version=sc["share"]["version"],
        )
        headers = make_owner_headers(sc["owner"]["id"])
        q1 = validate_success(api.get_booking_quote(booking["id"], headers), 200)
        q2 = validate_success(api.get_booking_quote(booking["id"], headers), 200)
        assert q1["provisional_total_cents"] == 900000
        assert q2["provisional_total_cents"] == q1["provisional_total_cents"], (
            "repeated reads must return the same figure"
        )
        share = get_share(sc["share"]["id"])
        assert share["hours_remaining_cy"] == pytest.approx(100.00, abs=0.005), (
            "a quote must not debit the entitlement ledger"
        )
        assert share["version"] == sc["share"]["version"] + 1, (
            "a quote must not mutate the share (only the booking create bumped its version)"
        )
