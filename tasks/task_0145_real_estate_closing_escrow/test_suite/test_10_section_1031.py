"""§1031 like-kind exchange (PRD §3.8)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    api_client,
    assert_exchange_1031,
    assert_section_1031_invariant,
    create_emd_held,
    create_escrow_file_basic,
    create_exchange_initiated,
    create_party,
    create_property_entity,
    escrow_file_payload,
    exchange_payload,
    fail_exchange,
    identify_exchange,
    iso_utc,
    parse_iso,
    re_get_exchange,
    server_now_dt,
    setup_disbursement_settled,
    setup_emd_held,
    setup_confirmed_wire,
    setup_escrow_ready_to_close,
    validate_error,
    validate_success,
    version_only_payload,
    with_idempotency,
)


def _future_closing_str(*, hours_ahead: int = 1) -> str:
    """Compute a closing_date_planned that is strictly ahead of the
    current server clock, so the §1031 deadline arithmetic
    (closing + 45d / + 180d) lands at a future instant we can still
    advance to.

    The server clock can only advance forward (PRD §2.10), so tests
    must derive `closing_date_planned` relative to server_now rather
    than hard-coding a calendar date.
    """
    base = server_now_dt()
    target = base + timedelta(hours=hours_ahead)
    return iso_utc(target)


# ===========================================================================
# Initiate — PRD §3.8
# ===========================================================================
class TestExchangeInitiation:

    def test_create_exchange_freezes_gain_components(self, api):
        """PRD §3.8: "On creation the system freezes the gain
        calculation. The realized_gain is the relinquished_sale_price
        minus the relinquished_basis, rounded half-up to two decimal
        places. The boot total is the sum of cash_boot_received and
        mortgage_relief, rounded half-up to two decimal places. While
        the exchange is on a deferred path — that is, until it
        terminates at CLOSED_DEFERRED — the recognized_gain is the
        smaller of realized_gain and the boot total ... and
        deferred_gain is realized_gain minus recognized_gain".

        With basis=200000, sale_price=500000, boot=50000, relief=20000:
          realized_gain = 300000.00
          boot_total = 70000.00
          recognized_gain = min(300000, 70000) = 70000.00
          deferred_gain = 300000 - 70000 = 230000.00.

        Claim: exchange returns 201 with these exact values, INITIATED.

        # difficulty: dual_variant_calc/section_1031_deferred_vs_failed_recognition
        """
        bundle = setup_emd_held(is_1031_exchange=True, include_qi=True)
        ex = create_exchange_initiated(bundle["escrow_file"]["id"])
        assert_exchange_1031(ex)
        assert ex["status"] == "INITIATED"
        assert ex["realized_gain"] == pytest.approx(300000.00, abs=0.01)
        assert ex["recognized_gain"] == pytest.approx(70000.00, abs=0.01)
        assert ex["deferred_gain"] == pytest.approx(230000.00, abs=0.01)
        assert_section_1031_invariant(ex)

    def test_create_exchange_pins_45_and_180_day_deadlines(self, api):
        """PRD §3.8: "identification_deadline_at is 45 calendar days
        after the relinquished sale's closing_date_planned, and
        exchange_deadline_at is 180 calendar days after the same
        instant."

        Claim: identification_deadline_at = closing_date_planned + 45d;
        exchange_deadline_at = closing_date_planned + 180d.
        """
        closing_str = _future_closing_str()
        bundle = setup_emd_held(
            is_1031_exchange=True, include_qi=True,
            closing_date_planned=closing_str,
        )
        ex = create_exchange_initiated(bundle["escrow_file"]["id"])
        closing = parse_iso(closing_str)
        ident_dl = parse_iso(ex["identification_deadline_at"])
        exch_dl = parse_iso(ex["exchange_deadline_at"])
        assert (ident_dl - closing).days == 45
        assert (exch_dl - closing).days == 180


# ===========================================================================
# Identify — PRD §3.8 (difficulty rule 6 + rule 8)
# ===========================================================================
class TestExchangeIdentify:

    def test_identify_exactly_at_45_day_deadline_succeeds(self, api):
        """PRD §3.8: "The exchange advances to IDENTIFIED when the
        taxpayer identifies a replacement property, but only while
        server_now is less than or equal to identification_deadline_at".

        Claim: with server_now == identification_deadline_at, identify
        succeeds (inclusive boundary).

        # difficulty: boundary_precision_check/section_1031_45day_deadline_inclusive_endpoint
        """
        closing_str = _future_closing_str()
        bundle = setup_emd_held(
            is_1031_exchange=True, include_qi=True,
            closing_date_planned=closing_str,
        )
        ex = create_exchange_initiated(bundle["escrow_file"]["id"])
        # Advance clock to exactly identification_deadline_at.
        advance_clock_to(ex["identification_deadline_at"])
        result = identify_exchange(ex["id"], version=ex["version"])
        assert result["status"] == "IDENTIFIED"

    def test_identify_one_second_past_deadline_rejected(self, api):
        """PRD §3.8: "a request submitted after that moment is rejected
        with ERR_1031_45DAY_LAPSED."
        PRD §3.10: a clock advance that crosses the deadline triggers
        a system-actor sweep that moves the row to FAILED_TAXABLE
        (which then makes identify hit the priority-5
        ERR_INVALID_STATE check before the priority-10 45-day check).

        Claim: at identification_deadline_at + 1 second, identify is
        rejected with the 45-day error (or, equivalently under the
        sweep semantics §3.10, the state-class ERR_INVALID_STATE
        produced once the sweep has moved the row to FAILED_TAXABLE).

        # difficulty: boundary_precision_check/section_1031_45day_deadline_inclusive_endpoint
        """
        closing_str = _future_closing_str()
        bundle = setup_emd_held(
            is_1031_exchange=True, include_qi=True,
            closing_date_planned=closing_str,
        )
        ex = create_exchange_initiated(bundle["escrow_file"]["id"])
        dl = parse_iso(ex["identification_deadline_at"])
        advance_clock_to(iso_utc(dl + timedelta(seconds=1)))
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.identify_exchange(
            ex["id"], version_only_payload(version=ex["version"]), eo,
        )
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_1031_45DAY_LAPSED.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )

    def test_identify_with_weekends_inside_window(self, api):
        """PRD §3.8: deadlines are pinned by adding 45/180 CALENDAR
        days (per PRD §3.8: "is 45 calendar days after the relinquished
        sale's closing_date_planned"). Weekend days count.

        Claim: identifying at 44 calendar days after closing (which
        spans weekends) succeeds — confirming the window is calendar-
        day-counted, not business-day-counted.

        # difficulty: resource_temporal_overlap/section_1031_45_180_day_calendar_window_non_business_day
        """
        closing_str = _future_closing_str()
        bundle = setup_emd_held(
            is_1031_exchange=True, include_qi=True,
            closing_date_planned=closing_str,
        )
        ex = create_exchange_initiated(bundle["escrow_file"]["id"])
        # Advance to 44 calendar days after closing — still inside the
        # 45-day calendar window. The exact span includes weekends.
        closing = parse_iso(closing_str)
        advance_clock_to(iso_utc(closing + timedelta(days=44)))
        result = identify_exchange(ex["id"], version=ex["version"])
        assert result["status"] == "IDENTIFIED"


# ===========================================================================
# Close-deferred — PRD §3.8 (difficulty rule 7)
# ===========================================================================
class TestExchangeCloseDeferred:

    def test_close_deferred_without_qi_disbursement_settled_rejected(
        self, api,
    ):
        """PRD §3.8: "From IDENTIFIED the exchange reaches
        CLOSED_DEFERRED only when three conditions are met: server_now
        is less than or equal to exchange_deadline_at (otherwise
        ERR_1031_180DAY_LAPSED); a Disbursement to a
        QUALIFIED_INTERMEDIARY beneficiary on the same escrow file
        exists in SETTLED (otherwise ERR_CROSS_ENTITY_STATE)".

        Claim: without a SETTLED QI Disbursement, close-deferred yields
        ERR_CROSS_ENTITY_STATE.

        # difficulty: cross_entity_state_dependency/exchange_close_deferred_requires_qi_disbursement_settled
        """
        bundle = setup_emd_held(
            is_1031_exchange=True, include_qi=True,
            closing_date_planned=_future_closing_str(),
        )
        ex = create_exchange_initiated(bundle["escrow_file"]["id"])
        ex = identify_exchange(ex["id"], version=ex["version"])
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.close_deferred_exchange(
            ex["id"], version_only_payload(version=ex["version"]), eo,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE)

    def test_close_deferred_succeeds_with_qi_disbursement_settled(self, api):
        """PRD §3.8 + difficulty rule 7: with a SETTLED QI Disbursement,
        the exchange reaches CLOSED_DEFERRED.

        Claim: after creating + identifying + settling a QI
        Disbursement, close-deferred succeeds and status is
        CLOSED_DEFERRED with the deferred gain components intact.

        # difficulty: cross_entity_state_dependency/exchange_close_deferred_requires_qi_disbursement_settled
        # difficulty: dual_variant_calc/section_1031_deferred_vs_failed_recognition
        # difficulty: compensating_invariant/section_1031_gain_conservation
        """
        # Build a file ready-to-close with 1031 election. Use a
        # future-relative closing_date so the 180-day deadline is still
        # ahead of server_now after the ready-to-close fixture's clock
        # advances.
        bundle = setup_escrow_ready_to_close(
            is_1031_exchange=True, include_qi=True,
            closing_date_planned=_future_closing_str(),
        )
        ef = bundle["escrow_file"]
        # Create + identify exchange.
        ex = create_exchange_initiated(ef["id"])
        ex = identify_exchange(ex["id"], version=ex["version"])
        # Create + confirm + approve + send + settle a QI Disbursement.
        qi_wire = setup_confirmed_wire(
            ef["id"], "QUALIFIED_INTERMEDIARY",
            bundle["qi"]["id"],
        )
        qi_disb = setup_disbursement_settled(
            ef["id"], qi_wire["id"], 70000.00,
        )
        assert qi_disb["status"] == "SETTLED"
        # Now close-deferred.
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.close_deferred_exchange(
            ex["id"], version_only_payload(version=ex["version"]), eo,
        )
        data = validate_success(resp)
        assert data["status"] == "CLOSED_DEFERRED"
        assert data["recognized_gain"] == pytest.approx(70000.00, abs=0.01)
        assert data["deferred_gain"] == pytest.approx(230000.00, abs=0.01)
        assert_section_1031_invariant(data)


# ===========================================================================
# Fail — PRD §3.8 (failed variant of gain calc)
# ===========================================================================
class TestExchangeFail:

    def test_fail_exchange_recognizes_entire_gain(self, api):
        """PRD §3.8: "On failure the system rewrites the gain components
        into the failed-exchange variant: recognized_gain becomes the
        full realized_gain (the entire gain is recognized) and
        deferred_gain is set to zero."

        Claim: explicit POST /exchanges/{id}/fail moves status to
        FAILED_TAXABLE and rewrites recognized_gain := realized_gain,
        deferred_gain := 0.

        # difficulty: dual_variant_calc/section_1031_deferred_vs_failed_recognition
        # difficulty: compensating_invariant/section_1031_gain_conservation
        """
        bundle = setup_emd_held(
            is_1031_exchange=True, include_qi=True,
        )
        ex = create_exchange_initiated(bundle["escrow_file"]["id"])
        # Realized = 300000, recognized = 70000, deferred = 230000.
        result = fail_exchange(ex["id"], version=ex["version"])
        assert result["status"] == "FAILED_TAXABLE"
        assert result["recognized_gain"] == pytest.approx(300000.00, abs=0.01)
        assert result["deferred_gain"] == pytest.approx(0.0, abs=0.01)
        assert result["realized_gain"] == pytest.approx(300000.00, abs=0.01)
        assert_section_1031_invariant(result)

    def test_clock_advance_past_180_day_sweeps_to_failed_taxable(self, api):
        """PRD §3.10: "A clock advance that crosses an Exchange1031's
        identification_deadline_at or exchange_deadline_at triggers a
        system-actor sweep that fails the affected exchanges to
        FAILED_TAXABLE, rewriting recognized_gain to realized_gain and
        deferred_gain to zero".

        Claim: advancing past exchange_deadline_at sweeps an INITIATED
        or IDENTIFIED exchange to FAILED_TAXABLE.

        # difficulty: resource_temporal_overlap/section_1031_45_180_day_calendar_window_non_business_day
        """
        closing_str = _future_closing_str()
        bundle = setup_emd_held(
            is_1031_exchange=True, include_qi=True,
            closing_date_planned=closing_str,
        )
        ex = create_exchange_initiated(bundle["escrow_file"]["id"])
        # Advance past the 180-day exchange deadline (closing + 181d).
        closing = parse_iso(closing_str)
        advance_clock_to(iso_utc(closing + timedelta(days=181)))
        ex_after = re_get_exchange(ex["id"])
        assert ex_after["status"] == "FAILED_TAXABLE"
        assert ex_after["recognized_gain"] == pytest.approx(
            ex_after["realized_gain"], abs=0.01,
        )
        assert ex_after["deferred_gain"] == pytest.approx(0.0, abs=0.01)
        assert_section_1031_invariant(ex_after)
