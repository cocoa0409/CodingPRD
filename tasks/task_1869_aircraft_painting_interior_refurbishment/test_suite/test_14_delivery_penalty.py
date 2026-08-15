"""Delay events and the dual-variant delivery penalty (PRD §3.10, §3.12)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_calendar_day,
    assert_delay_event,
    assert_invoice,
    create_delay_event,
    create_engagement,
    create_invoice,
    get_program,
    make_customer_rep_headers,
    set_logical_clock,
    setup_ready_for_delivery,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_delay_event_payload

_PM = TEST_USERS["program_manager_headers"]
_ADMIN = TEST_USERS["center_admin_headers"]
_FIN = TEST_USERS["finance_clerk_headers"]


class TestProjectionVsSettlement:
    def _ready_with_reported_delay(self):
        """READY_FOR_DELIVERY with one CUSTOMER_CAUSED 5-day DelayEvent left in
        REPORTED status; logical clock then advanced to 2026-09-08."""
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = setup_ready_for_delivery()
        # Report while still non-terminal — rebuild path keeps the event REPORTED.
        # (Reporting after READY is also permitted; the event simply stays pending.)
        event = create_delay_event(
            ctx["program"]["id"], category="CUSTOMER_CAUSED", impact_days=5,
            reason="Customer parts late",
        )
        set_logical_clock("2026-09-08T00:00:00Z")
        ctx["delay_event"] = event
        return ctx

    def test_projection_includes_still_reported_excusable_events(self, api):
        """PRD §3.10: "The **projection** variant — surfaced on every program
        read as `projected_penalty_cents` and recomputed on any delay or
        change-order mutation — includes confirmed excusable events *and*
        still-`REPORTED` excusable events, and takes its reference date as the
        later of the logical clock date and the adjusted committed date".

        Design: Difficulty/dual_variant_calc/penalty_projection_vs_settlement_diverge
        """
        ctx = self._ready_with_reported_delay()
        program = get_program(ctx["program"]["id"])
        # adjusted = 2026-09-01 + 5 = 2026-09-06; reference = max(2026-09-08,
        # 2026-09-06) = 2026-09-08; 2 days x 150000.
        assert program["projected_penalty_cents"] == 300000
        # The REPORTED event never moved the committed date.
        assert_calendar_day(
            program["committed_delivery_date"], "2026-09-01", "committed_delivery_date"
        )

    def test_settlement_excludes_reported_events_at_final_issuance(self, api):
        """PRD §3.10: "The **settlement** variant — computed when the `FINAL`
        invoice is issued and again at delivery, persisted as
        `penalty_final_cents` — excludes `REPORTED` and `DISPUTED` events
        entirely and takes its reference date as the actual delivery date (or
        the logical clock date at issuance if the aircraft has not yet been
        delivered)." PRD §3.12: a FINAL invoice carries "a penalty credit line
        equal to the negative of `penalty_final_cents` as fixed at issuance".

        Design: Difficulty/dual_variant_calc/penalty_projection_vs_settlement_diverge
        """
        ctx = self._ready_with_reported_delay()
        invoice = create_invoice(ctx["program"]["id"], "FINAL")
        issued = validate_success(api.issue_invoice(invoice["id"], _FIN))
        assert_invoice(issued)

        # Settlement: adjusted 2026-09-01 (REPORTED excluded); 7 days x 150000.
        program = get_program(ctx["program"]["id"])
        assert program["penalty_final_cents"] == 1050000
        credit = [l["amount_cents"] for l in issued["lines"] if l["amount_cents"] < 0]
        assert credit == [-1050000], "the penalty credit line is the negative settlement"
        # remainder 6172837 + booth 200000 - penalty 1050000.
        assert issued["total_cents"] == 5322837, (
            "projection (300000) and settlement (1050000) diverge on identical data"
        )


class TestPenaltyCap:
    def test_penalty_cap_rounds_half_up_and_binds(self, api):
        """PRD §3.10: "Second, the cap is that contract value multiplied by the
        program's `penalty_cap_pct`, rounded half-up to integer cents. ... Sixth
        and finally, the penalty is the smaller of the raw figure and the cap."

        Design: Corner/calculations/penalty_cap_binds_and_rounds
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = setup_ready_for_delivery()
        set_logical_clock("2026-09-10T00:00:00Z")  # 9 days past 2026-09-01

        invoice = create_invoice(ctx["program"]["id"], "FINAL")
        issued = validate_success(api.issue_invoice(invoice["id"], _FIN))

        # cap = round(12345673 x 0.10) = round(1234567.3) = 1234567;
        # raw = 9 x 150000 = 1350000 exceeds it, so the cap binds.
        program = get_program(ctx["program"]["id"])
        assert program["penalty_final_cents"] == 1234567
        # remainder 6172837 + booth 200000 - penalty 1234567.
        assert issued["total_cents"] == 5138270


class TestProjectionInputSet:
    def test_projection_excludes_disputed_events(self, api):
        """PRD §3.10: "The **projection** variant ... includes confirmed
        excusable events *and* still-`REPORTED` excusable events" — a DISPUTED
        event is neither — and "`REPORTED` and `DISPUTED` events contribute
        nothing" to the committed date.

        Design: Corner/calculations/projection_excludes_disputed_events
        """
        ctx = create_engagement()
        event = create_delay_event(
            ctx["program"]["id"], category="CUSTOMER_CAUSED", impact_days=5,
            reason="disputed scope wait",
        )
        disputed = validate_success(
            api.dispute_delay_event(
                event["id"], make_customer_rep_headers(ctx["customer"]["id"])
            )
        )
        assert disputed["status"] == "DISPUTED"
        set_logical_clock("2026-09-03T00:00:00Z")

        program = get_program(ctx["program"]["id"])
        assert_calendar_day(
            program["committed_delivery_date"], "2026-09-01", "committed_delivery_date"
        )
        # reference = max(2026-09-03, 2026-09-01) = 2026-09-03; 2 days x 150000.
        assert program["projected_penalty_cents"] == 300000


class TestDelayConfirmCategory:
    def test_confirm_shifts_date_only_for_excusable_categories(self, api):
        """PRD §3.10: "The program's `committed_delivery_date` is defined as
        the `contractual_delivery_date` plus the sum of `impact_days` over all
        confirmed events whose category is excusable — `CUSTOMER_CAUSED` or
        `FORCE_MAJEURE` — applied cumulatively in ascending `event_seq` order.
        `CENTER_CAUSED` events never shift the date, in either direction;
        `REPORTED` and `DISPUTED` events contribute nothing."

        Design: Corner/state_machines/delay_confirm_category_conditional_shift
        """
        ctx = create_engagement()
        ev1 = create_delay_event(
            ctx["program"]["id"], category="CUSTOMER_CAUSED", impact_days=4,
            reason="late seat selection",
        )
        ev2 = create_delay_event(
            ctx["program"]["id"], category="CENTER_CAUSED", impact_days=6,
            reason="paint booth downtime",
        )
        assert ev2["event_seq"] > ev1["event_seq"], (
            "event_seq is a per-program monotone replay-order key"
        )

        validate_success(api.confirm_delay_event(ev1["id"], _ADMIN))
        after_excusable = get_program(ctx["program"]["id"])
        assert_calendar_day(
            after_excusable["committed_delivery_date"], "2026-09-05",
            "committed_delivery_date",
        )

        validate_success(api.confirm_delay_event(ev2["id"], _ADMIN))
        after_center = get_program(ctx["program"]["id"])
        assert_calendar_day(
            after_center["committed_delivery_date"], "2026-09-05",
            "committed_delivery_date",
        )
