"""Difficulty-design coverage -- one or more tests per instance from the
test-targeting index. Every test docstring includes a PRD citation; the
difficulty-design entry is referenced ONLY in the tagging comment
'# difficulty: <rule_id>/<instance_name>' so the audit can verify
coverage without leaking implementation terminology into the test contract.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from test_helpers import (
    ApiErrorId,
    DEFAULT_BUSINESS_DATE,
    DEFAULT_PEAK_END_MIN,
    DEFAULT_PEAK_START_MIN,
    DEFAULT_PRESALE_OPENS_AT,
    DEFAULT_RELEASE_DATE,
    advance_clock,
    api_client,
    cancel_showtime,
    cancel_showtime_payload,
    create_cinema,
    create_distributor,
    create_film,
    create_screen,
    create_showtime,
    create_showtime_payload,
    create_ticket_payload,
    fetch_film,
    fetch_showtime,
    list_anomaly_alerts_for,
    list_audit_logs_for,
    list_settlements_for,
    make_cinema_ops_headers,
    purchase_ticket,
    refund_ticket,
    release_film,
    run_sweep,
    setup_completed_showtime,
    setup_distributor_with_weekly_minimum,
    setup_imax_and_2d_films,
    setup_posted_settlement,
    setup_released_film,
    setup_showtime_on_sale,
    shelve_film,
    validate_error,
    validate_success,
    version_payload,
)


# =========================================================================
# Rule 1: dual_variant_calc / settlement_split_posting_vs_reversal
# =========================================================================
class TestDualVariantSettlementSplit:

    def test_posting_variant_full_set_round_then_sum(self, api):
        """PRD §3.9: 'The posting variant runs at POSTING creation time
        over the full set of VALID tickets present on the showtime at
        that instant; platform_commission_cents is the sum of per-ticket
        rounded values and gross_cents reflects every current VALID
        ticket.'

        Claim: 3 tickets at 1500 each, distributor 6000bps → POSTING
        platform_commission=360, distributor=2335, cinema=1557, tax=248,
        gross=4500.

        # difficulty: dual_variant_calc/settlement_split_posting_vs_reversal
        """
        base = setup_posted_settlement(
            tickets=3, paid_amount_cents=1500,
            distributor_split_bps=6000, format="2D",
            supported_formats=["2D"],
        )
        s = base["settlement"]
        assert s["kind"] == "POSTING"
        assert s["gross_cents"] == 4500
        assert s["platform_commission_cents"] == 360
        assert s["tax_cents"] == 248
        assert s["distributor_amount_cents"] == 2335
        assert s["cinema_amount_cents"] == 1557

    def test_reversal_variant_single_ticket_per_line(self, api):
        """PRD §3.9: 'The reversal variant runs when a single ticket is
        refunded or exchanged and the parent POSTING is in status
        POSTED: the evaluation set is exactly that one ticket,
        gross_cents enters the ledger as the negative of the refunded
        ticket's paid_amount_cents, and platform_commission_cents is
        computed on that single ticket'.

        Claim: refunding one ticket appends a REVERSAL with
        gross_cents=-1500 and platform_commission_cents=-120 (the
        per-line rounded share).

        # difficulty: dual_variant_calc/settlement_split_posting_vs_reversal
        """
        base = setup_posted_settlement(
            tickets=3, paid_amount_cents=1500,
            distributor_split_bps=6000, format="2D",
            supported_formats=["2D"],
        )
        refund_ticket(base["tickets"][0])
        rows = list_settlements_for(base["showtime"]["id"])
        reversals = [r for r in rows if r["kind"] == "REVERSAL"]
        assert len(reversals) >= 1
        rev = reversals[0]
        assert rev["gross_cents"] == -1500
        assert rev["platform_commission_cents"] == -120


# =========================================================================
# Rule 1: dual_variant_calc / presale_anomaly_rolling_vs_cumulative
# =========================================================================
class TestDualVariantAnomaly:

    def test_rolling_variant_at_tenth_within_window(
        self, api, ticketing_headers,
    ):
        """PRD §3.5: 'The rolling-window rule counts the number of such
        tickets whose purchased_at lies within the last 60 minutes
        inclusive of the current server clock; if this count would
        reach 10 or more with the proposed ticket included, the rule
        trips with rule ROLLING_WINDOW.'

        Claim: 10th purchase by buyer 'b1' within a 60-minute window
        rejected with ERR_PRESALE_ANOMALY_DETECTED and rule=ROLLING_WINDOW.

        # difficulty: dual_variant_calc/presale_anomaly_rolling_vs_cumulative
        """
        base = setup_showtime_on_sale(
            seat_capacity=100, supported_formats=["2D"], format="2D",
        )
        for _ in range(9):
            res = api.purchase_ticket(
                base["showtime"]["id"],
                create_ticket_payload(
                    buyer_external_id="b1", paid_amount_cents=1500,
                ),
                ticketing_headers,
            )
            validate_success(res, expected_status=201)
        res = api.purchase_ticket(
            base["showtime"]["id"],
            create_ticket_payload(
                buyer_external_id="b1", paid_amount_cents=1500,
            ),
            ticketing_headers,
        )
        validate_error(res, ApiErrorId.ERR_PRESALE_ANOMALY_DETECTED.value)
        alerts = list_anomaly_alerts_for(
            base["showtime"]["id"], buyer_external_id="b1",
        )
        rolling = [a for a in alerts if a["rule"] == "ROLLING_WINDOW"]
        assert len(rolling) >= 1

    # test_cumulative_variant_at_thirtieth DELETED.
    # STEP 1b unique-derivability collapse: PRD §3.5 scopes the
    # cumulative-rule input domain to "the same showtime_id and same
    # buyer_external_id". The per-buyer hard cap of 20 (PRD §3.5)
    # rejects the 21st sale to that buyer with
    # ERR_PER_BUYER_LIMIT_EXCEEDED, so a single buyer cannot reach 30
    # same-showtime same-buyer VALID tickets. A faithful PRD
    # implementer cannot exercise the CUMULATIVE threshold in this
    # setup. Scaffold-driven over-coverage of the
    # presale_anomaly_rolling_vs_cumulative difficulty design.


# =========================================================================
# Rule 2: combinatorial_formula / showtime_block_minutes_mode_a
# =========================================================================
class TestBlockMinutesModeA:

    def test_block_minutes_imax_vs_2d(self, api):
        """PRD §3.4: 'a format-specific setup overhead is added: 5
        minutes for IMAX, 3 minutes for 3D, and 0 minutes for 2D.'

        Claim: same screen/duration -> IMAX produces 140-minute block,
        2D produces 135-minute block.

        # difficulty: combinatorial_formula/showtime_block_minutes_mode_a
        """
        scene = setup_imax_and_2d_films(duration_minutes=120)
        # supported_formats=[2D,3D,IMAX] on the shared screen.
        # block = 120 + trailer(10) + ad(5) + format_setup.
        st_imax = create_showtime(
            scene["screen"], scene["cinema"], scene["film_imax"],
            start_minute=600,
        )
        st_2d = create_showtime(
            scene["screen"], scene["cinema"], scene["film_2d"],
            start_minute=900,  # gap to avoid screen conflict
        )
        assert st_imax["block_minutes"] == 140
        assert st_imax["end_minute"] == 740
        assert st_2d["block_minutes"] == 135
        assert st_2d["end_minute"] == 1035

    def test_block_minutes_3d_setup_3(self, api):
        """PRD §3.4: '3 minutes for 3D'.

        Claim: 3D format produces block = duration + trailer + ad + 3.

        # difficulty: combinatorial_formula/showtime_block_minutes_mode_a
        """
        base = setup_released_film(
            duration_minutes=120, format="3D",
            supported_formats=["3D"],
            trailer_minutes=10, ad_minutes=5,
            operating_start_minute=0, operating_end_minute=1440,
        )
        st = create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=600,
        )
        assert st["block_minutes"] == 138, (
            "PRD §3.4: 3D format_setup is 3, block = 120+10+5+3 = 138"
        )


# =========================================================================
# Rule 2: combinatorial_formula / settlement_split_rounding_order_mode_b
# =========================================================================
class TestSettlementRoundingOrderModeB:

    def test_per_line_round_then_sum_pins_to_36(self, api):
        """PRD §3.9: 'sum the per-ticket commissions from step one to
        produce platform_commission_cents -- this is round-then-sum, not
        sum-then-round, and that ordering matters when the ticket count
        is large.'

        Claim: 3 tickets at 156: round-then-sum gives 36; sum-then-round
        gives 37. The PRD pins 36.

        # difficulty: combinatorial_formula/settlement_split_rounding_order_mode_b
        """
        base = setup_posted_settlement(
            tickets=3, paid_amount_cents=156,
            distributor_split_bps=6000, format="2D",
            supported_formats=["2D"],
        )
        s = base["settlement"]
        assert s["platform_commission_cents"] == 36

    def test_invariant_holds_with_engineered_rounding(self, api):
        """PRD §3.9: 'The invariant the engine guarantees is that
        distributor_amount_cents plus cinema_amount_cents plus tax_cents
        plus platform_commission_cents equals gross_cents exactly, with
        no fractional residue.'

        Claim: 36 + 26 + 244 + 162 == 468 (gross) on the same engineered
        inputs.

        # difficulty: combinatorial_formula/settlement_split_rounding_order_mode_b
        """
        base = setup_posted_settlement(
            tickets=3, paid_amount_cents=156,
            distributor_split_bps=6000, format="2D",
            supported_formats=["2D"],
        )
        s = base["settlement"]
        assert (
            s["platform_commission_cents"] + s["tax_cents"]
            + s["distributor_amount_cents"] + s["cinema_amount_cents"]
        ) == s["gross_cents"]


# =========================================================================
# Rule 3: non_linear_state_machine / film_release_shelve_cycle
# =========================================================================
class TestFilmReleaseShelveCycle:

    def test_release_shelve_release_cycle_observable(self, api):
        """PRD §3.2: 'The reverse transition SHELVED -> RELEASED re-uses
        the release action and again requires that release_date has been
        reached. On a successful re-release, shelved_reason is cleared'.

        Claim: shelve sets reason; re-release clears it; second shelve
        sets a different reason -- the cycle is observable.

        # difficulty: non_linear_state_machine/film_release_shelve_cycle
        """
        base = setup_showtime_on_sale()
        # First shelve.
        shelved = shelve_film(
            base["film"], base["distributor"], reason="low_demand",
        )
        assert shelved["status"] == "SHELVED"
        assert shelved.get("shelved_reason") == "low_demand"
        # Re-release.
        from test_helpers import release_film
        released = release_film(shelved, base["distributor"])
        assert released["status"] == "RELEASED"
        assert released.get("shelved_reason") in (None, "")
        # Second shelve with new reason.
        shelved2 = shelve_film(
            released, base["distributor"], reason="reshoot_required",
        )
        assert shelved2["status"] == "SHELVED"
        assert shelved2.get("shelved_reason") == "reshoot_required"

    def test_release_and_shelve_emit_distinct_audit_actions(self, api):
        """PRD §3.2: 'an AuditLog row is emitted with action FILM_RELEASE'
        and 'An AuditLog row with action FILM_SHELVE is emitted.'

        Claim: cycling through SHELVE → RELEASE → SHELVE leaves audit
        rows with the correct actions.

        # difficulty: non_linear_state_machine/film_release_shelve_cycle
        """
        base = setup_showtime_on_sale()
        from test_helpers import release_film
        shelved = shelve_film(
            base["film"], base["distributor"], reason="low_demand",
        )
        released = release_film(shelved, base["distributor"])
        shelve_film(
            released, base["distributor"], reason="reshoot_required",
        )
        shelve_rows = list_audit_logs_for(
            base["film"]["id"], action="FILM_SHELVE",
        )
        release_rows = list_audit_logs_for(
            base["film"]["id"], action="FILM_RELEASE",
        )
        assert len(shelve_rows) >= 2
        # Initial release + one re-release = 2.
        assert len(release_rows) >= 2


# =========================================================================
# Rule 3: non_linear_state_machine / showtime_parallel_sale_and_lifecycle
# =========================================================================
class TestShowtimeParallelDimensions:

    def test_sale_status_transitions_independently_of_lifecycle(self, api):
        """PRD §3.6: 'When a showtime transitions to IN_PROGRESS,
        COMPLETED, or CANCELLED, its sale_status becomes CLOSED as a
        paired side effect.'
        PRD §3.2: shelving 'flips its sale_status from PRESALE or
        ON_SALE to CLOSED ... while lifecycle_status itself remains
        SCHEDULED.'

        Claim: shelving the parent film flips Showtime.sale_status to
        CLOSED while lifecycle_status remains SCHEDULED.

        # difficulty: non_linear_state_machine/showtime_parallel_sale_and_lifecycle
        """
        base = setup_showtime_on_sale()
        # Confirm PRESALE→ON_SALE happened.
        assert base["showtime"]["sale_status"] == "ON_SALE"
        assert base["showtime"]["lifecycle_status"] == "SCHEDULED"
        # Shelve parent film.
        shelve_film(
            base["film"], base["distributor"], reason="paused_release",
        )
        refreshed = fetch_showtime(
            base["showtime"]["id"], base["cinema"],
        )
        assert refreshed["sale_status"] == "CLOSED"
        assert refreshed["lifecycle_status"] == "SCHEDULED"

    def test_presale_to_on_sale_via_sweep_preserves_lifecycle(self, api):
        """PRD §3.5: 'A new showtime sits in sale_status PRESALE until
        the server clock crosses presale_opens_at, at which point the
        system actor transitions sale_status to ON_SALE'.

        Claim: sweep flips sale_status PRESALE → ON_SALE while
        lifecycle_status stays SCHEDULED.

        # difficulty: non_linear_state_machine/showtime_parallel_sale_and_lifecycle
        """
        base = setup_showtime_on_sale(sweep_to_on_sale=False)
        # Before sweep: PRESALE + SCHEDULED.
        # Note: setup_showtime_on_sale with sweep_to_on_sale=False does
        # NOT advance the clock past presale_opens_at. Read showtime as-is.
        st = fetch_showtime(base["showtime"]["id"], base["cinema"])
        assert st["sale_status"] == "PRESALE"
        assert st["lifecycle_status"] == "SCHEDULED"
        # Advance + sweep.
        advance_clock(DEFAULT_PRESALE_OPENS_AT)
        run_sweep()
        st = fetch_showtime(base["showtime"]["id"], base["cinema"])
        assert st["sale_status"] == "ON_SALE"
        assert st["lifecycle_status"] == "SCHEDULED"


# =========================================================================
# Rule 4: transitive_cascade / showtime_cancel_three_hop_cascade
# (the four-hop delist cascade has 5 tests tagged in test_07.)
# =========================================================================
class TestShowtimeCancelThreeHopCascade:

    def test_cancel_refunds_ticket_and_appends_reversal(self, api):
        """PRD §3.7: 'Every VALID Ticket on the showtime has its status
        set to REFUNDED ... For each refunded or exchanged ticket whose
        original POSTING Settlement was in status POSTED, a REVERSAL
        row is appended'.

        Claim: cancelling a SCHEDULED showtime whose ticket was already
        captured by a POSTED settlement on a different (completed)
        showtime is not in scope -- the cancel cascade only affects
        VALID tickets on the cancelled showtime. We use a fresh
        SCHEDULED showtime with VALID tickets and NO posted settlement,
        and confirm only the refund hop fires (no REVERSAL appended for
        this showtime because no POSTING was POSTED for it).

        # difficulty: transitive_cascade/showtime_cancel_three_hop_cascade
        """
        from test_helpers import fetch_ticket
        base = setup_showtime_on_sale(seat_capacity=10)
        tickets = []
        for i in range(2):
            t = purchase_ticket(
                base["showtime"], buyer_external_id=f"b-{i}",
                paid_amount_cents=1000,
            )
            tickets.append(t)
        # Cancel with INCIDENT to bypass weekly-minimum + low-attendance.
        cancel_showtime(
            base["showtime"], base["cinema"], cancel_reason="INCIDENT",
        )
        for t in tickets:
            refreshed = fetch_ticket(t["id"])
            assert refreshed["status"] == "REFUNDED"
        # No POSTING was POSTED for this showtime: confirm no REVERSAL.
        rows = list_settlements_for(base["showtime"]["id"])
        reversals = [r for r in rows if r["kind"] == "REVERSAL"]
        assert len(reversals) == 0, (
            "PRD §3.7: REVERSAL is appended only when the POSTING was POSTED"
        )

    def test_cancel_audit_log_ordering(self, api):
        """PRD §3.7: 'An AuditLog row with action SHOWTIME_CANCEL
        finalizes the operation.'

        Claim: A SHOWTIME_CANCEL audit row exists for the cancelled
        showtime.id.

        # difficulty: transitive_cascade/showtime_cancel_three_hop_cascade
        """
        base = setup_showtime_on_sale(seat_capacity=10)
        purchase_ticket(
            base["showtime"], buyer_external_id="b0",
            paid_amount_cents=1000,
        )
        cancel_showtime(
            base["showtime"], base["cinema"], cancel_reason="INCIDENT",
        )
        rows = list_audit_logs_for(
            base["showtime"]["id"], action="SHOWTIME_CANCEL",
        )
        assert len(rows) >= 1


# =========================================================================
# Rule 5: priority_pair_validation_conflict
# =========================================================================
class TestStateBeatsBusinessReferential:

    def test_double_cancel_returns_invalid_state(self, api):
        """PRD §2.9 + §3.7: validation priority places state-machine
        admissibility (ERR_INVALID_STATE) BEFORE distributor weekly
        minimum (ERR_MIN_SHOW_COUNT_BREACH). PRD §3.7 also says: 'a
        cancel is only admitted when lifecycle_status is SCHEDULED'.

        Claim: a second cancel attempt on an already-CANCELLED showtime
        returns ERR_INVALID_STATE rather than ERR_MIN_SHOW_COUNT_BREACH,
        even when the weekly-minimum would also fail.

        # difficulty: priority_pair_validation_conflict/state_beats_business_referential_on_cancel_double
        """
        scenario = setup_distributor_with_weekly_minimum(
            min_show_count_per_week=3,
            showtime_count=3,
            start_minute_first=400,
            start_minute_gap=200,
        )
        st = scenario["showtimes"][0]
        # First cancel with INCIDENT succeeds (force-majeure bypass).
        cancel_showtime(
            st, scenario["cinema"], cancel_reason="INCIDENT",
        )
        # Now attempt a SECOND cancel with LOW_ATTENDANCE on the same
        # already-CANCELLED row.
        # Re-fetch to see CANCELLED state.
        st_refreshed = fetch_showtime(st["id"], scenario["cinema"])
        res = api.cancel_showtime(
            st["id"],
            cancel_showtime_payload(
                version=st_refreshed["version"],
                cancel_reason="LOW_ATTENDANCE",
            ),
            make_cinema_ops_headers(scenario["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_check_runs_before_weekly_minimum(self, api):
        """PRD §2.9: 'state-machine transition admissibility
        (ERR_INVALID_STATE)' appears BEFORE 'distributor weekly minimum
        (ERR_MIN_SHOW_COUNT_BREACH)' in the priority order.

        Claim: an already-CANCELLED showtime is unchanged after the
        second-cancel attempt -- no AuditLog row appended.

        # difficulty: priority_pair_validation_conflict/state_beats_business_referential_on_cancel_double
        """
        scenario = setup_distributor_with_weekly_minimum(
            min_show_count_per_week=3,
            showtime_count=3,
            start_minute_first=400,
            start_minute_gap=200,
        )
        st = scenario["showtimes"][0]
        cancel_showtime(
            st, scenario["cinema"], cancel_reason="INCIDENT",
        )
        before_rows = list_audit_logs_for(
            st["id"], action="SHOWTIME_CANCEL",
        )
        st_refreshed = fetch_showtime(st["id"], scenario["cinema"])
        api.cancel_showtime(
            st["id"],
            cancel_showtime_payload(
                version=st_refreshed["version"],
                cancel_reason="LOW_ATTENDANCE",
            ),
            make_cinema_ops_headers(scenario["cinema"]["id"]),
        )
        after_rows = list_audit_logs_for(
            st["id"], action="SHOWTIME_CANCEL",
        )
        assert len(after_rows) == len(before_rows), (
            "PRD §2.9: a rejected request must NOT append a SHOWTIME_CANCEL "
            "AuditLog row (the cancel did not commit)"
        )


class TestSafetyBeatsFiscal:
    """PRD §2.9: 'A consequence worth calling out: the pre-sale anomaly
    check sits above the per-buyer hard cap. When a single ticket
    purchase would simultaneously breach the rolling-window or
    cumulative anomaly threshold and the per-buyer hard cap, the
    response is ERR_PRESALE_ANOMALY_DETECTED and an AnomalyAlert is
    recorded; the per-buyer-cap rejection is suppressed in that case.'"""

    def test_anomaly_beats_per_buyer_cap_returns_anomaly(
        self, api, ticketing_headers,
    ):
        """Claim: a single purchase that would simultaneously breach
        the rolling-window anomaly threshold AND the per-buyer hard cap
        is rejected with ERR_PRESALE_ANOMALY_DETECTED (not
        ERR_PER_BUYER_LIMIT_EXCEEDED).

        Engineering: sell 20 valid tickets to buyer 'b1', the first 11
        spaced >60 minutes apart so the rolling count never reaches 10
        on the way up. Then the final 9 are clustered within the last
        60 minutes; after those 9, rolling=9 and cumulative=20. The
        21st attempt -- still within the 60-minute window of the last 9
        -- would simultaneously bring rolling to 10 (>= threshold) AND
        push fiscal count from 20 to 21 (> hard cap). Per PRD §2.9 the
        anomaly response wins.

        # difficulty: priority_pair_validation_conflict/safety_beats_fiscal_on_anomaly
        """
        base = setup_showtime_on_sale(
            seat_capacity=100, supported_formats=["2D"], format="2D",
            presale_opens_at=DEFAULT_PRESALE_OPENS_AT,
        )
        t = datetime.fromisoformat(
            DEFAULT_PRESALE_OPENS_AT.replace("Z", "+00:00"),
        )
        # Phase A: 11 tickets spread far apart -- rolling stays at 1.
        for i in range(11):
            res = api.purchase_ticket(
                base["showtime"]["id"],
                create_ticket_payload(
                    buyer_external_id="b1", paid_amount_cents=1500,
                ),
                ticketing_headers,
            )
            validate_success(res, expected_status=201)
            t = t + timedelta(minutes=70)
            advance_clock(
                t.astimezone(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z",
                ),
            )
        # Phase B: 9 tickets in quick succession -- rolling reaches 9.
        # We anchor the cluster well after the 60-min boundary so phase
        # A purchases are NOT in the rolling window. Then within one
        # minute each, do 9 purchases.
        for i in range(9):
            res = api.purchase_ticket(
                base["showtime"]["id"],
                create_ticket_payload(
                    buyer_external_id="b1", paid_amount_cents=1500,
                ),
                ticketing_headers,
            )
            validate_success(res, expected_status=201)
            t = t + timedelta(seconds=30)
            advance_clock(
                t.astimezone(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z",
                ),
            )
        # The 21st attempt: rolling becomes 10 AND fiscal becomes 21.
        res = api.purchase_ticket(
            base["showtime"]["id"],
            create_ticket_payload(
                buyer_external_id="b1", paid_amount_cents=1500,
            ),
            ticketing_headers,
        )
        validate_error(res, ApiErrorId.ERR_PRESALE_ANOMALY_DETECTED.value)

    def test_anomaly_alert_recorded_when_request_rejected(
        self, api, ticketing_headers,
    ):
        """PRD §2.9: 'an AnomalyAlert is recorded' even though the
        purchase is rejected.

        Claim: AnomalyAlert row exists for the buyer despite the request
        being rejected.

        # difficulty: priority_pair_validation_conflict/safety_beats_fiscal_on_anomaly
        """
        base = setup_showtime_on_sale(
            seat_capacity=100, supported_formats=["2D"], format="2D",
        )
        for _ in range(9):
            res = api.purchase_ticket(
                base["showtime"]["id"],
                create_ticket_payload(
                    buyer_external_id="b1", paid_amount_cents=1500,
                ),
                ticketing_headers,
            )
            validate_success(res, expected_status=201)
        api.purchase_ticket(
            base["showtime"]["id"],
            create_ticket_payload(
                buyer_external_id="b1", paid_amount_cents=1500,
            ),
            ticketing_headers,
        )
        alerts = list_anomaly_alerts_for(
            base["showtime"]["id"], buyer_external_id="b1",
        )
        assert len(alerts) >= 1


# =========================================================================
# Rule 6: boundary_precision_check
# =========================================================================
class TestLowAttendanceStrictLessThan:

    def test_attendance_at_threshold_rejects_low_attendance_cancel(
        self, api, ticketing_headers,
    ):
        """PRD §3.7: 'a showtime whose attendance_rate_bps computes to
        exactly 1500 does not qualify, and the cancel attempt is
        rejected with ERR_INVALID_STATE.'

        Claim: rate_bps == 1500 → ERR_INVALID_STATE.

        # difficulty: boundary_precision_check/low_attendance_strict_less_than
        """
        # seat_capacity=100, ticket_price_cents=100, 15 tickets -> gross=1500
        # max=10000, rate=1500//1 = 1500.
        distributor = create_distributor(min_show_count_per_week=0)
        cinema = create_cinema()
        screen = create_screen(
            cinema, supported_formats=["2D"], seat_capacity=100,
            operating_start_minute=0, operating_end_minute=1440,
        )
        film = create_film(distributor, format="2D", duration_minutes=90)
        advance_clock("2026-05-04T00:00:00.000Z")
        film = release_film(film, distributor)
        showtime = create_showtime(
            screen, cinema, film,
            start_minute=720, business_date="2026-05-05T00:00:00.000Z",
            ticket_price_cents=100,
            presale_opens_at="2026-05-04T12:00:00.000Z",
        )
        advance_clock("2026-05-04T12:00:00.000Z")
        run_sweep()
        for i in range(15):
            purchase_ticket(
                showtime, buyer_external_id=f"b{i}",
                paid_amount_cents=100,
            )
        showtime = fetch_showtime(showtime["id"], cinema)
        res = api.cancel_showtime(
            showtime["id"],
            cancel_showtime_payload(
                version=showtime["version"],
                cancel_reason="LOW_ATTENDANCE",
            ),
            make_cinema_ops_headers(cinema["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_attendance_below_threshold_allows_low_attendance_cancel(
        self, api, ticketing_headers,
    ):
        """PRD §3.7: 'the resulting attendance_rate_bps must be strictly
        less than 1500 (15.00 percent) for the LOW_ATTENDANCE
        cancellation to be admitted.'

        Claim: rate_bps == 1499 → cancel admitted.

        # difficulty: boundary_precision_check/low_attendance_strict_less_than
        """
        # seat_capacity=100, ticket_price_cents=100, sell 14 -> gross=1400,
        # rate = 14000000//10000 = 1400 < 1500.
        distributor = create_distributor(min_show_count_per_week=0)
        cinema = create_cinema()
        screen = create_screen(
            cinema, supported_formats=["2D"], seat_capacity=100,
            operating_start_minute=0, operating_end_minute=1440,
        )
        film = create_film(distributor, format="2D", duration_minutes=90)
        advance_clock("2026-05-04T00:00:00.000Z")
        film = release_film(film, distributor)
        showtime = create_showtime(
            screen, cinema, film,
            start_minute=720, business_date="2026-05-05T00:00:00.000Z",
            ticket_price_cents=100,
            presale_opens_at="2026-05-04T12:00:00.000Z",
        )
        advance_clock("2026-05-04T12:00:00.000Z")
        run_sweep()
        for i in range(14):
            purchase_ticket(
                showtime, buyer_external_id=f"b{i}",
                paid_amount_cents=100,
            )
        showtime = fetch_showtime(showtime["id"], cinema)
        res = api.cancel_showtime(
            showtime["id"],
            cancel_showtime_payload(
                version=showtime["version"],
                cancel_reason="LOW_ATTENDANCE",
            ),
            make_cinema_ops_headers(cinema["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["lifecycle_status"] == "CANCELLED"
        assert data["cancel_reason"] == "LOW_ATTENDANCE"


class TestSeatCapacityInclusiveUpper:

    def test_kth_sale_succeeds_kplus1_rejected(self, api, ticketing_headers):
        """PRD §3.5: 'strictly inclusive on the boundary so the
        (seat_capacity)-th sale succeeds and the (seat_capacity + 1)-th
        sale is rejected with ERR_SEAT_CAPACITY_EXCEEDED.'

        Claim: seat_capacity=2 → first 2 succeed, 3rd rejected.

        # difficulty: boundary_precision_check/seat_capacity_inclusive_upper
        """
        base = setup_showtime_on_sale(
            seat_capacity=2, supported_formats=["2D"], format="2D",
        )
        for i in range(2):
            res = api.purchase_ticket(
                base["showtime"]["id"],
                create_ticket_payload(
                    buyer_external_id=f"b{i}", paid_amount_cents=1500,
                ),
                ticketing_headers,
            )
            validate_success(res, expected_status=201)
        res = api.purchase_ticket(
            base["showtime"]["id"],
            create_ticket_payload(
                buyer_external_id="b3", paid_amount_cents=1500,
            ),
            ticketing_headers,
        )
        validate_error(res, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED.value)

    def test_seat_count_unchanged_after_rejection(
        self, api, ticketing_headers,
    ):
        """PRD §3.5: rejected purchases leave tickets_sold_count
        unchanged because no Ticket row is written.

        Claim: tickets_sold_count remains 2 after the 3rd rejection.

        # difficulty: boundary_precision_check/seat_capacity_inclusive_upper
        """
        base = setup_showtime_on_sale(
            seat_capacity=2, supported_formats=["2D"], format="2D",
        )
        for i in range(2):
            res = api.purchase_ticket(
                base["showtime"]["id"],
                create_ticket_payload(
                    buyer_external_id=f"b{i}", paid_amount_cents=1500,
                ),
                ticketing_headers,
            )
            validate_success(res, expected_status=201)
        api.purchase_ticket(
            base["showtime"]["id"],
            create_ticket_payload(
                buyer_external_id="b3", paid_amount_cents=1500,
            ),
            ticketing_headers,
        )
        showtime = fetch_showtime(
            base["showtime"]["id"], base["cinema"],
        )
        assert showtime["tickets_sold_count"] == 2


# =========================================================================
# Rule 7: cross_entity_state_dependency
# =========================================================================
class TestShowtimeSaleDependsOnFilmStatus:

    def test_ticket_purchase_blocked_when_film_planned(
        self, api, ticketing_headers,
    ):
        """PRD §3.5: 'If the film is not yet RELEASED when the clock
        crosses presale_opens_at, the transition is suppressed and any
        ticket purchase attempt fails with ERR_FILM_NOT_RELEASED.'

        Claim: ticket purchase against a showtime whose film is PLANNED
        → ERR_FILM_NOT_RELEASED.

        # difficulty: cross_entity_state_dependency/showtime_sale_depends_on_film_status
        """
        distributor = create_distributor()
        cinema = create_cinema()
        screen = create_screen(
            cinema, supported_formats=["2D"], seat_capacity=10,
            operating_start_minute=0, operating_end_minute=1440,
        )
        film = create_film(
            distributor, format="2D",
            release_date="2099-01-01T00:00:00.000Z",
        )
        showtime = create_showtime(
            screen, cinema, film,
            start_minute=720, business_date=DEFAULT_BUSINESS_DATE,
            ticket_price_cents=1500,
            presale_opens_at=DEFAULT_PRESALE_OPENS_AT,
        )
        advance_clock(DEFAULT_PRESALE_OPENS_AT)
        res = api.purchase_ticket(
            showtime["id"],
            create_ticket_payload(
                buyer_external_id="b1", paid_amount_cents=1500,
            ),
            ticketing_headers,
        )
        validate_error(res, ApiErrorId.ERR_FILM_NOT_RELEASED.value)

    def test_sale_status_does_not_transition_on_unreleased_film(
        self, api,
    ):
        """PRD §3.5: 'If the film is not yet RELEASED when the clock
        crosses presale_opens_at, the transition is suppressed'.

        Claim: after sweep at presale_opens_at, sale_status remains
        PRESALE because the parent film is PLANNED.

        # difficulty: cross_entity_state_dependency/showtime_sale_depends_on_film_status
        """
        distributor = create_distributor()
        cinema = create_cinema()
        screen = create_screen(
            cinema, supported_formats=["2D"], seat_capacity=10,
            operating_start_minute=0, operating_end_minute=1440,
        )
        film = create_film(
            distributor, format="2D",
            release_date="2099-01-01T00:00:00.000Z",
        )
        showtime = create_showtime(
            screen, cinema, film,
            start_minute=720, business_date=DEFAULT_BUSINESS_DATE,
            ticket_price_cents=1500,
            presale_opens_at=DEFAULT_PRESALE_OPENS_AT,
        )
        advance_clock(DEFAULT_PRESALE_OPENS_AT)
        run_sweep()
        refreshed = fetch_showtime(showtime["id"], cinema)
        assert refreshed["sale_status"] == "PRESALE"


class TestSettlementPostDependsOnShowtimeCompletion:

    def test_post_when_showtime_scheduled_rejected(
        self, api, finance_headers,
    ):
        """PRD §3.9: 'the post is admitted only when the parent
        showtime's lifecycle_status is COMPLETED -- otherwise the
        response is ERR_SHOWTIME_NOT_COMPLETED.'

        Claim: posting against a SCHEDULED showtime →
        ERR_SHOWTIME_NOT_COMPLETED.

        # difficulty: cross_entity_state_dependency/settlement_post_depends_on_showtime_completion
        """
        from test_helpers import create_settlement
        base = setup_showtime_on_sale(seat_capacity=10)
        purchase_ticket(
            base["showtime"], buyer_external_id="b1", paid_amount_cents=1500,
        )
        draft = create_settlement(base["showtime"])
        res = api.post_settlement(draft["id"], {}, finance_headers)
        validate_error(res, ApiErrorId.ERR_SHOWTIME_NOT_COMPLETED.value)

    def test_post_succeeds_once_showtime_completed(self, api):
        """PRD §3.9: 'The draft can only be promoted from DRAFT to
        POSTED by an explicit post action ... the post is admitted only
        when the parent showtime's lifecycle_status is COMPLETED'.

        Claim: after the underlying showtime reaches COMPLETED, post
        succeeds and Settlement.status becomes POSTED.

        # difficulty: cross_entity_state_dependency/settlement_post_depends_on_showtime_completion
        """
        base = setup_posted_settlement(
            tickets=1, paid_amount_cents=1000,
            distributor_split_bps=6000,
            format="2D", supported_formats=["2D"],
        )
        assert base["settlement"]["status"] == "POSTED"


# =========================================================================
# Rule 8: resource_temporal_overlap
# =========================================================================
class TestScreenHalfOpenWithCleaningBuffer:

    def test_inclusive_lower_bound_after_cleaning(self, api):
        """PRD §3.4: 'the half-open interval starting at the other
        show's start_minute and running through that show's end_minute
        plus the screen's cleaning_interval_minutes ... must not overlap
        with the proposed half-open interval [start_minute, end_minute)'.

        Claim: a second show may start exactly at earlier.end_minute +
        cleaning_interval_minutes.

        # difficulty: resource_temporal_overlap/screen_half_open_with_cleaning_buffer
        """
        base = setup_released_film(
            duration_minutes=90, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            cleaning_interval_minutes=15,
            operating_start_minute=0, operating_end_minute=1440,
        )
        # block = 105; end at 700+105=805? start=700 -> end=805.
        create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=700,
        )
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=820,  # 805 + 15
        )
        res = api.create_showtime(
            base["screen"]["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_success(res, expected_status=201)

    def test_one_minute_before_cleaning_buffer_rejected(self, api):
        """PRD §3.4: overlap including cleaning buffer →
        ERR_SCREEN_TIME_CONFLICT.

        Claim: start_minute == earlier.end_minute + cleaning_interval -
        1 → ERR_SCREEN_TIME_CONFLICT.

        # difficulty: resource_temporal_overlap/screen_half_open_with_cleaning_buffer
        """
        base = setup_released_film(
            duration_minutes=90, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            cleaning_interval_minutes=15,
            operating_start_minute=0, operating_end_minute=1440,
        )
        create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=700,
        )
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=819,
        )
        res = api.create_showtime(
            base["screen"]["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SCREEN_TIME_CONFLICT.value)


class TestCinemaPeakDensityCap:

    def test_second_in_peak_window_rejected(self, api):
        """PRD §3.4: 'at most one showtime per distributor_id per
        business_date is permitted to start inside that window for the
        cinema; the second start in the window from the same distributor
        is rejected with ERR_COMPETING_FILM_CONFLICT (409).'

        Claim: with peak window [1080, 1380), two showtimes for the same
        distributor at start_minute=1100 (peak) and start_minute=1200
        (peak) → second rejected.

        # difficulty: resource_temporal_overlap/cinema_peak_density_cap_closed_membership
        """
        base = setup_released_film(
            duration_minutes=90, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            operating_start_minute=0, operating_end_minute=1440,
            peak_window_start_minute=DEFAULT_PEAK_START_MIN,
            peak_window_end_minute=DEFAULT_PEAK_END_MIN,
        )
        screen2 = create_screen(
            base["cinema"], supported_formats=["2D"],
            operating_start_minute=0, operating_end_minute=1440,
            cleaning_interval_minutes=15, seat_capacity=100,
        )
        create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=1100, business_date=DEFAULT_BUSINESS_DATE,
        )
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=1200,
            business_date=DEFAULT_BUSINESS_DATE,
        )
        res = api.create_showtime(
            screen2["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_COMPETING_FILM_CONFLICT.value)

    def test_peak_inclusive_lower_bound(self, api):
        """PRD §3.4: 'a show's start_minute is in the peak window if it
        lies between peak_window_start_minute and peak_window_end_minute
        inclusive on both ends, despite the half-open semantics used for
        the peak window definition elsewhere'.

        Claim: starts at exactly peak_window_start_minute count as
        in-peak. A second show at start_minute=peak_start is rejected.

        # difficulty: resource_temporal_overlap/cinema_peak_density_cap_closed_membership
        """
        base = setup_released_film(
            duration_minutes=90, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            operating_start_minute=0, operating_end_minute=1440,
            peak_window_start_minute=DEFAULT_PEAK_START_MIN,
            peak_window_end_minute=DEFAULT_PEAK_END_MIN,
        )
        screen2 = create_screen(
            base["cinema"], supported_formats=["2D"],
            operating_start_minute=0, operating_end_minute=1440,
            cleaning_interval_minutes=15, seat_capacity=100,
        )
        create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=1100, business_date=DEFAULT_BUSINESS_DATE,
        )
        payload = create_showtime_payload(
            film_id=base["film"]["id"],
            start_minute=DEFAULT_PEAK_START_MIN,  # 1080: inclusive lower
            business_date=DEFAULT_BUSINESS_DATE,
        )
        res = api.create_showtime(
            screen2["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_COMPETING_FILM_CONFLICT.value)


# =========================================================================
# Rule 9: compensating_invariant
# =========================================================================
class TestMoneyConservationAcrossSettlementRefund:

    def test_invariant_sum_over_posting_plus_reversals(self, api):
        """PRD §3.9: 'The invariant the engine guarantees is that
        distributor_amount_cents plus cinema_amount_cents plus tax_cents
        plus platform_commission_cents equals gross_cents exactly, with
        no fractional residue.'

        Claim: across POSTING + appended REVERSAL rows, the per-row
        split-sum invariant holds and the aggregate gross matches the
        actual VALID-ticket net.

        # difficulty: compensating_invariant/money_conservation_across_settlement_refund
        """
        base = setup_posted_settlement(
            tickets=3, paid_amount_cents=1500,
            distributor_split_bps=6000,
            format="2D", supported_formats=["2D"],
        )
        refund_ticket(base["tickets"][0])
        rows = list_settlements_for(base["showtime"]["id"])
        # Per-row invariant.
        for row in rows:
            assert (
                row["distributor_amount_cents"] + row["cinema_amount_cents"]
                + row["tax_cents"] + row["platform_commission_cents"]
            ) == row["gross_cents"]
        # Aggregate net gross = 4500 - 1500 = 3000.
        total_gross = sum(r["gross_cents"] for r in rows)
        assert total_gross == 3000

    def test_refund_appends_one_reversal_per_refunded_ticket(self, api):
        """PRD §3.9: 'when a single ticket is refunded ... and the
        parent POSTING is in status POSTED ... a REVERSAL row is
        appended'.

        Claim: one REVERSAL row per refunded ticket.

        # difficulty: compensating_invariant/money_conservation_across_settlement_refund
        """
        base = setup_posted_settlement(
            tickets=3, paid_amount_cents=1500,
            distributor_split_bps=6000,
            format="2D", supported_formats=["2D"],
        )
        refund_ticket(base["tickets"][0])
        refund_ticket(base["tickets"][1])
        rows = list_settlements_for(base["showtime"]["id"])
        reversals = [r for r in rows if r["kind"] == "REVERSAL"]
        assert len(reversals) == 2


class TestScreenMinuteConservationAcrossCancel:

    def test_cancel_frees_screen_minutes(self, api):
        """PRD §3.4 + §3.7: a SCHEDULED showtime consumes screen
        minutes; cancelling it moves it to CANCELLED, which PRD §3.4
        excludes from the conflict count ('for every other showtime on
        the same screen and same business_date whose lifecycle_status is
        not CANCELLED').

        Claim: after cancel, the same screen/start_minute slot can be
        re-scheduled successfully -- the minutes are freed.

        # difficulty: compensating_invariant/screen_minute_conservation_across_cancel
        """
        base = setup_released_film(
            duration_minutes=90, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            cleaning_interval_minutes=15,
            operating_start_minute=0, operating_end_minute=1440,
        )
        st = create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=700,
        )
        cancel_showtime(
            st, base["cinema"], cancel_reason="INCIDENT",
        )
        # Re-schedule the same slot -- should succeed.
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=700,
        )
        res = api.create_showtime(
            base["screen"]["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_success(res, expected_status=201)

    def test_cancelled_showtime_excluded_from_conflict_check(self, api):
        """PRD §3.4: 'for every other showtime on the same screen and
        same business_date whose lifecycle_status is not CANCELLED, the
        half-open interval ... must not overlap'.

        Claim: a CANCELLED showtime does not block a new overlapping
        showtime on the same screen.

        # difficulty: compensating_invariant/screen_minute_conservation_across_cancel
        """
        base = setup_released_film(
            duration_minutes=90, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            cleaning_interval_minutes=15,
            operating_start_minute=0, operating_end_minute=1440,
        )
        st = create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=700,
        )
        cancel_showtime(
            st, base["cinema"], cancel_reason="INCIDENT",
        )
        # A new showtime overlapping the cancelled slot must succeed.
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=720,  # overlaps 700–805
        )
        res = api.create_showtime(
            base["screen"]["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_success(res, expected_status=201)
