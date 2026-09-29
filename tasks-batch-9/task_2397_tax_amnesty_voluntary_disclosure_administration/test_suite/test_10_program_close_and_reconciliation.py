"""Closing the window and freezing the accounting.

PRD §3.8 makes closing the only producer of an expired pre-clearance, a lapsed
agreement and a raised non-participant flag, and it makes the realization band
depend on a value that is rounded to four places before it is compared.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CANONICAL_TOTAL_DUE_CENTS,
    CANONICAL_WAIVED_AMOUNT_CENTS,
    CANONICAL_WINDOW_CLOSE_AT,
    assert_fields,
    close_window,
    draft_return,
    read_agreement,
    read_payment,
    read_program,
    read_return,
    read_revenue_summary,
    read_taxpayer,
    reconcile,
    remit_payment,
    reverse_payment_payload,
    setup_drafted_agreement,
    setup_filed_return,
    setup_flagged_nonparticipant,
    validate_success,
)

REALIZATION_FORECAST_CENTS = 1166667
REALIZATION_TAXPAYER = {"legal_name": "Copper Loom Textiles Inc", "tin_last4": "8817"}


def _agreement_paid_to_the_boundary(api):
    """The canonical filed return paid off in two tranches, one cent apart."""
    ctx = setup_filed_return(
        api,
        program_overrides={"revenue_forecast_cents": REALIZATION_FORECAST_CENTS},
        taxpayer_overrides=REALIZATION_TAXPAYER,
    )
    remit_payment(api, ctx, 1049900, payment_reference="BULK-1")
    ctx["tail_payment"] = remit_payment(api, ctx, 100, payment_reference="TAIL-1")
    return ctx


class TestClosingCascades:
    """Two chains run at close, and neither one reaches into the other."""

    def test_the_primary_chain_expires_the_negotiation_and_flags_the_client(
        self, api
    ):
        """A disclosed request that never accepted costs the taxpayer 25 points.

        PRD §3.8: "Hop one expires the unfinished negotiations: every
        pre-clearance of this program whose `status` is `SUBMITTED`,
        `UNDER_REVIEW`, `TERMS_OFFERED` or `COUNTERED` advances to `EXPIRED`. Hop
        two, caused by hop one, punishes the ones that had already named their
        client: for each request that just became `EXPIRED` and whose
        `disclosed_taxpayer_id` is not null, that taxpayer's `nonparticipant_flag`
        is set true and the program's `nonparticipant_count` is recomputed."

        PRD §3.8: "Hop three, caused by hop two, re-resolves the
        `escalation_tier` of each taxpayer whose flag just flipped, by the tier
        rules of §3.2, so a flagged taxpayer with at least one `OPEN` case lands
        in `T2` and one with none lands in `T1`. Hop four, caused by hop three,
        recomputes each such taxpayer's `compliance_behavior_score` under the
        `HISTORICAL` variant, which now carries the 25-point non-participant
        penalty."

        Design: Difficulty/transitive_cascade/program_close_cascades_two_independent_chains
        """
        ctx = setup_flagged_nonparticipant(
            api,
            taxpayer_overrides={
                "legal_name": "Willow Ridge Bottling Inc",
                "tin_last4": "5511",
            },
            pre_clearance_overrides={
                "anonymous_alias": "CLIENT-12",
                "estimated_liability_cents": 900000,
                "earliest_unfiled_period_start": "2024-04-01",
            },
        )

        assert_fields(
            ctx["program"],
            status="CLOSED",
            nonparticipant_count=1,
            participant_count=0,
        )
        assert ctx["program"]["closed_at"].startswith("2026-12-01T00:00:00")
        assert_fields(ctx["pre_clearance"], status="EXPIRED")
        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]),
            nonparticipant_flag=True,
            escalation_tier="T1",
            compliance_behavior_score=75,
        )

    def test_the_secondary_chain_lapses_the_unsigned_draft_and_voids_its_return(
        self, api
    ):
        """An agreement never executed lapses, and its draft return is voided.

        PRD §3.8: "The secondary chain has two hops and runs over agreements that
        never got signed. Hop one advances every agreement of this program whose
        `status` is `DRAFTED` to `LAPSED`. Hop two, caused by that transition,
        advances every return of a lapsed agreement whose `status` is `DRAFT` to
        `VOIDED`."

        PRD §3.8: "A request that expired while still anonymous flags nobody —
        the department never learned who to pursue."

        Design: Difficulty/transitive_cascade/program_close_cascades_two_independent_chains
        """
        ctx = setup_drafted_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Pinnacle Grain Co",
                "tin_last4": "6072",
            },
        )
        pending = draft_return(api, ctx, reported_tax_cents=400000)
        assert_fields(pending, status="DRAFT")

        program = close_window(api, ctx["program"]["id"])
        assert_fields(
            program,
            status="CLOSED",
            nonparticipant_count=0,
            participant_count=0,
        )
        assert_fields(read_agreement(api, ctx["agreement"]["id"]), status="LAPSED")
        assert_fields(read_return(api, pending["id"]), status="VOIDED")
        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]),
            nonparticipant_flag=False,
            escalation_tier="T0",
            compliance_behavior_score=100,
        )


class TestRealizationRounding:
    """The band is read off the rounded percentage, never the raw ratio."""

    def test_a_raw_ratio_below_the_band_rounds_up_into_on_track(self, api):
        """1,050,000 over 1,166,667 is 0.89999974 raw and 0.9000 rounded.

        PRD §3.8: "The `realization_pct` is collections divided by forecast,
        rounded half up to four decimal places. The `forecast_status` band is then
        derived from that **rounded** value: `ON_TRACK` when `realization_pct` is
        at least 0.9000, otherwise `WATCH` when it is at least 0.7000, otherwise
        `SHORTFALL`. Because the rounding precedes the comparison, a raw ratio of
        0.89999974 rounds to 0.9000 and reports `ON_TRACK`."

        Design: Difficulty/boundary_precision_check/realization_rounds_to_four_places_before_the_forecast_comparison
        """
        ctx = _agreement_paid_to_the_boundary(api)

        assert_fields(
            read_revenue_summary(api, ctx["program"]["id"]),
            revenue_forecast_cents=REALIZATION_FORECAST_CENTS,
            collected_cents=CANONICAL_TOTAL_DUE_CENTS,
            realization_pct=0.9000,
            forecast_status="ON_TRACK",
            waived_total_cents=CANONICAL_WAIVED_AMOUNT_CENTS,
            participant_count=1,
        )
        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            paid_total_cents=CANONICAL_TOTAL_DUE_CENTS,
            payment_status="PAID_IN_FULL",
        )

    def test_reversing_the_last_cent_drops_the_band_to_watch(self, api):
        """One cent short rounds to 0.8999, which is below the `ON_TRACK` floor.

        PRD §3.8: "Collections are the sum of `amount_cents` over every payment
        whose `status` is `APPLIED` across the program's agreements, reported as
        `collected_cents` alongside the program's own `revenue_forecast_cents`."

        PRD §3.6: "Reversing advances the payment `APPLIED → REVERSED` and records
        the supplied `reversal_reason`."

        Design: Difficulty/boundary_precision_check/realization_rounds_to_four_places_before_the_forecast_comparison
        """
        ctx = _agreement_paid_to_the_boundary(api)

        reversed_tail = validate_success(
            api.reverse_payment(
                ctx["tail_payment"]["id"],
                reverse_payment_payload(reversal_reason="BANK_RETURNED_ITEM"),
                ADMIN_HEADERS,
            )
        )
        assert_fields(
            reversed_tail, status="REVERSED", reversal_reason="BANK_RETURNED_ITEM"
        )

        assert_fields(
            read_revenue_summary(api, ctx["program"]["id"]),
            collected_cents=1049900,
            realization_pct=0.8999,
            forecast_status="WATCH",
        )
        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            paid_total_cents=1049900,
            payment_status="PARTIAL",
        )
        assert_fields(read_return(api, ctx["disclosure_return"]["id"]), status="FILED")

    def test_reconciliation_freezes_the_rounded_percentage(self, api):
        """The frozen figure is the rounded one the band was read from.

        PRD §3.8: "Reconciling sets `final_realization_pct` to the realization
        percentage computed at that instant, frozen there permanently, and
        advances the program's `version` by one. Before reconciliation
        `final_realization_pct` is null."

        Design: Difficulty/boundary_precision_check/realization_rounds_to_four_places_before_the_forecast_comparison
        """
        ctx = _agreement_paid_to_the_boundary(api)
        validate_success(
            api.reverse_payment(
                ctx["tail_payment"]["id"],
                reverse_payment_payload(reversal_reason="BANK_RETURNED_ITEM"),
                ADMIN_HEADERS,
            )
        )
        assert_fields(read_payment(api, ctx["tail_payment"]["id"]), status="REVERSED")
        assert_fields(
            read_program(api, ctx["program"]["id"]), final_realization_pct=None
        )

        close_window(api, ctx["program"]["id"], at=CANONICAL_WINDOW_CLOSE_AT)
        reconciled = reconcile(api, ctx["program"]["id"])

        assert_fields(
            reconciled,
            status="RECONCILED",
            final_realization_pct=0.8999,
            collected_cents=1049900,
        )
