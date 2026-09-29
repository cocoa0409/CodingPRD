"""Sponsor invoice money: per-line rounding, the volume-credit tier, the
dispute loop's conservation invariant, and the aging epoch's boundaries.
"""

from test_helpers import (
    MANAGER_ONE,
    api_client,
    item_spec,
    make_manager_headers,
    post_charge,
    raise_invoice,
    read_charge,
    read_study,
    read_summary,
    remit,
    review_charge,
    run_aging,
    set_clock,
    setup_aged_sponsor_charge,
    setup_draft_invoice,
    setup_priced_study_with_sponsor_charges,
    setup_submitted_invoice,
    submit_invoice,
    validate_paginated,
)


def _invoices(study_id):
    """The study's invoices, ascending by ``sequence_number``."""
    rows, _meta = validate_paginated(
        api_client.list_study_sponsor_invoices(
            study_id, make_manager_headers(MANAGER_ONE)
        )
    )
    return rows


class TestInvoiceIndirectRoundsPerLine:
    """Two lines that each carry a fractional cent of indirect."""

    GRID = [
        item_spec(
            "J9999",
            classification="RESEARCH_PAID",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=15000,
            negotiated_unit_cents=12345,
            expected_occurrences=2,
        )
    ]
    CHARGES = [
        {"charge_code": "J9999", "service_date": "2026-08-01", "amount_cents": 12345},
        {"charge_code": "J9999", "service_date": "2026-08-02", "amount_cents": 12345},
    ]

    def test_01_invoice_indirect_is_the_sum_of_per_line_rounded_figures(self):
        """Two 12,345-cent lines at 32.0 percent each round 3,950.4 down to
        3,950, so the invoice indirect is 7,900.

        PRD §3.8: "`indirect_cents` is the sum of the per-line rounded indirect
        figures — each line rounded half up on its own, then added — which as
        §2.7 warns is not the same number as rounding the total indirect once."

        Design: Difficulty/combinatorial_formula/invoice_indirect_rounds_per_line_then_sums
        """
        ctx = setup_draft_invoice(
            self.CHARGES,
            item_specs=self.GRID,
            indirect_rate_pct=30.0,
            study_overrides={
                "protocol_number": "AMC-2390-E",
                "funding_source": "INDUSTRY_SPONSORED",
            },
            qct_basis=None,
        )
        invoice = ctx["invoice"]

        assert ctx["study"]["effective_indirect_rate_pct"] == 32.0
        assert invoice["line_count"] == 2
        assert invoice["subtotal_cents"] == 24690
        assert invoice["indirect_cents"] == 7900
        # Rounding the total indirect once would have produced 7,901.
        assert invoice["indirect_cents"] != 7901
        assert invoice["gross_total_cents"] == 32590
        assert invoice["volume_credit_cents"] == 0
        assert invoice["net_total_cents"] == 32590

    def test_02_the_budget_rounds_the_same_money_once_for_the_whole_subtotal(self):
        """On the very same 24,690 cents the budget's sum-then-round order
        produces 7,901 of uplift where the invoice produced 7,900.

        PRD §2.7: "On the study budget the order is **sum then round**: each
        subtotal is accumulated exactly, and the indirect uplift is rounded
        once, for the subtotal as a whole."

        Design: Difficulty/combinatorial_formula/invoice_indirect_rounds_per_line_then_sums
        """
        ctx = setup_draft_invoice(
            self.CHARGES,
            item_specs=self.GRID,
            indirect_rate_pct=30.0,
            study_overrides={
                "protocol_number": "AMC-2390-E",
                "funding_source": "INDUSTRY_SPONSORED",
            },
            qct_basis=None,
        )
        study = ctx["study"]

        assert study["per_patient_subtotal_cents"] == 24690
        assert study["per_patient_budget_cents"] == 32591
        budget_uplift = study["per_patient_budget_cents"] - study["per_patient_subtotal_cents"]
        assert budget_uplift == 7901
        assert budget_uplift != ctx["invoice"]["indirect_cents"]


class TestVolumeCreditTieredOnGross:
    """The credit is tiered on the pre-credit gross and never re-evaluated."""

    GRID = [
        item_spec(
            "J9999",
            classification="RESEARCH_PAID",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=700000,
            negotiated_unit_cents=600000,
            expected_occurrences=1,
        ),
        item_spec(
            "96413",
            classification="RESEARCH_PAID",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=200000,
            negotiated_unit_cents=165000,
            expected_occurrences=1,
        ),
    ]
    CHARGES = [
        {"charge_code": "J9999", "service_date": "2026-08-03", "amount_cents": 600000},
        {"charge_code": "96413", "service_date": "2026-08-04", "amount_cents": 165000},
    ]

    def _draft(self):
        return setup_draft_invoice(
            self.CHARGES,
            item_specs=self.GRID,
            indirect_rate_pct=32.0,
            study_overrides={
                "protocol_number": "AMC-2390-F",
                "funding_source": "INDUSTRY_SPONSORED",
            },
            qct_basis=None,
        )

    def test_03_a_gross_above_the_threshold_earns_two_percent_of_that_gross(self):
        """A 1,009,800-cent gross earns a 20,196-cent credit even though the
        resulting net falls back below the million-cent threshold.

        PRD §3.8: "The tier is never re-evaluated against the net — an invoice
        grossing 1,009,800 cents keeps its 20,196-cent credit even though the
        resulting net of 989,604 cents sits below the threshold, and
        `line_count` records how many charges were selected."

        Design: Difficulty/combinatorial_formula/invoice_volume_credit_tiered_on_gross_never_on_net
        """
        invoice = self._draft()["invoice"]

        assert invoice["line_count"] == 2
        assert invoice["subtotal_cents"] == 765000
        assert invoice["indirect_cents"] == 244800
        assert invoice["gross_total_cents"] == 1009800
        assert invoice["volume_credit_cents"] == 20196
        assert invoice["net_total_cents"] == 989604
        assert invoice["net_total_cents"] < 1000000

    def test_04_the_credit_is_never_computed_from_the_post_credit_net(self):
        """Two percent of the net would have been 19,792 cents.

        PRD §3.8: "The volume credit is then tiered on that pre-credit gross and
        never on the net: `volume_credit_cents` is 2.0 percent of
        `gross_total_cents`, rounded half up to a whole cent, when
        `gross_total_cents` is at least 1,000,000 cents, and zero otherwise."

        Design: Difficulty/combinatorial_formula/invoice_volume_credit_tiered_on_gross_never_on_net
        """
        invoice = self._draft()["invoice"]

        assert invoice["volume_credit_cents"] == 20196
        assert invoice["volume_credit_cents"] != 19792
        assert (
            invoice["gross_total_cents"] - invoice["volume_credit_cents"]
            == invoice["net_total_cents"]
        )


class TestVolumeCreditThresholdBoundary:
    """One invoice grosses 999,995 cents; the next grosses exactly 1,000,000."""

    GRID = [
        item_spec(
            "J9999",
            classification="RESEARCH_PAID",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=800000,
            negotiated_unit_cents=757576,
            expected_occurrences=1,
        )
    ]
    STUDY = {
        "protocol_number": "AMC-2390-R",
        "funding_source": "INDUSTRY_SPONSORED",
    }

    def test_05_five_cents_below_the_threshold_earns_no_credit(self):
        """A 757,572-cent line grosses 999,995 cents and earns nothing.

        PRD §3.8: "The volume credit is then tiered on that pre-credit gross and
        never on the net: `volume_credit_cents` is 2.0 percent of
        `gross_total_cents`, rounded half up to a whole cent, when
        `gross_total_cents` is at least 1,000,000 cents, and zero otherwise."

        Design: Difficulty/boundary_precision_check/invoice_volume_credit_threshold_met_exactly_at_gross_1000000
        """
        ctx = setup_draft_invoice(
            [
                {
                    "charge_code": "J9999",
                    "service_date": "2026-08-01",
                    "amount_cents": 757572,
                }
            ],
            item_specs=self.GRID,
            indirect_rate_pct=32.0,
            study_overrides=self.STUDY,
            qct_basis=None,
        )
        invoice = ctx["invoice"]

        assert ctx["study"]["effective_indirect_rate_pct"] == 32.0
        assert invoice["invoice_number"] == "INV-AMC-2390-R-001"
        assert invoice["sequence_number"] == 1
        assert invoice["subtotal_cents"] == 757572
        assert invoice["indirect_cents"] == 242423
        assert invoice["gross_total_cents"] == 999995
        assert invoice["volume_credit_cents"] == 0
        assert invoice["net_total_cents"] == 999995

    def test_06_a_gross_landing_exactly_on_the_threshold_earns_the_credit(self):
        """A second invoice whose 757,576-cent line grosses exactly 1,000,000
        cents earns 20,000 — the tier's at-least bound is inclusive.

        PRD §3.8: "`volume_credit_cents` is 2.0 percent of `gross_total_cents`,
        rounded half up to a whole cent, when `gross_total_cents` is at least
        1,000,000 cents, and zero otherwise."

        Design: Difficulty/boundary_precision_check/invoice_volume_credit_threshold_met_exactly_at_gross_1000000
        """
        ctx = setup_draft_invoice(
            [
                {
                    "charge_code": "J9999",
                    "service_date": "2026-08-01",
                    "amount_cents": 757572,
                }
            ],
            item_specs=self.GRID,
            indirect_rate_pct=32.0,
            study_overrides=self.STUDY,
            qct_basis=None,
        )
        # The first invoice has already claimed the control charge, so the next
        # selection sees only the trigger charge.
        trigger = post_charge(
            ctx["study"]["id"],
            charge_code="J9999",
            service_date="2026-08-02",
            amount_cents=757576,
        )
        review_charge(trigger["id"], "HOLD_FOR_SPONSOR")

        second = raise_invoice(ctx["study"]["id"])

        assert second["sequence_number"] == 2
        assert second["invoice_number"] == "INV-AMC-2390-R-002"
        assert second["line_count"] == 1
        assert second["subtotal_cents"] == 757576
        assert second["indirect_cents"] == 242424
        assert second["gross_total_cents"] == 1000000
        assert second["volume_credit_cents"] == 20000
        assert second["net_total_cents"] == 980000
        assert [row["sequence_number"] for row in _invoices(ctx["study"]["id"])] == [1, 2]


class TestDisputeReleaseConservesSponsorPosition:
    """Submission and dispute are compensating moves on one conserved sum."""

    GRID = [
        item_spec(
            "J9999",
            classification="RESEARCH_PAID",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=50000,
            negotiated_unit_cents=40000,
            expected_occurrences=1,
        )
    ]
    CHARGES = [
        {"charge_code": "J9999", "service_date": "2026-08-01", "amount_cents": 40000}
    ]

    def _submitted(self):
        return setup_submitted_invoice(
            self.CHARGES,
            item_specs=self.GRID,
            indirect_rate_pct=32.0,
            study_overrides={
                "protocol_number": "AMC-2390-AA",
                "funding_source": "INDUSTRY_SPONSORED",
            },
            qct_basis=None,
        )

    def test_07_unbilled_plus_receivable_is_invariant_across_submit_and_dispute(self):
        """The 40,000 cents moves from unbilled to receivable and all the way
        back, and the sum of the two positions never changes.

        PRD §2.8: "The **sponsor position** — `sponsor_unbilled_cents` plus
        `sponsor_receivable_cents` — is unchanged both by submitting an invoice
        and by a dispute releasing its lines."

        Design: Difficulty/compensating_invariant/invoice_dispute_release_conserves_sponsor_position_and_aging
        """
        ctx = self._submitted()
        after_submit = read_study(ctx["study"]["id"])
        assert after_submit["sponsor_unbilled_cents"] == 0
        assert after_submit["sponsor_receivable_cents"] == 40000
        submitted_position = (
            after_submit["sponsor_unbilled_cents"]
            + after_submit["sponsor_receivable_cents"]
        )

        set_clock("2026-09-15T09:00:00Z")
        disputed = remit(ctx["invoice"]["id"], "DISPUTED")
        after_dispute = read_study(ctx["study"]["id"])

        assert disputed["status"] == "DISPUTED"
        assert disputed["line_count"] == 0
        assert disputed["subtotal_cents"] == 0
        assert disputed["indirect_cents"] == 0
        assert disputed["gross_total_cents"] == 0
        assert disputed["volume_credit_cents"] == 0
        assert disputed["net_total_cents"] == 0
        assert after_dispute["sponsor_unbilled_cents"] == 40000
        assert after_dispute["sponsor_receivable_cents"] == 0
        assert (
            after_dispute["sponsor_unbilled_cents"]
            + after_dispute["sponsor_receivable_cents"]
            == submitted_position
            == 40000
        )

        summary = read_summary(ctx["study"]["id"])
        assert summary["sponsor_unbilled_cents"] == 40000
        assert summary["sponsor_receivable_cents"] == 0

    def test_08_a_disputed_charge_keeps_its_original_unbilled_baseline(self):
        """The released charge re-enters the pool with its original
        ``unbilled_since``, so the aging epoch reads 45 days rather than zero,
        and the re-submission re-selects it.

        PRD §3.8: "Every charge carrying this invoice's identifier moves
        `INVOICED_SPONSOR → UNBILLED` and has its `sponsor_invoice_id` cleared
        to null, while `unbilled_since` is left **unchanged** so that age keeps
        accruing across the dispute — a disputed charge does not get a fresh
        aging baseline."

        Design: Difficulty/compensating_invariant/invoice_dispute_release_conserves_sponsor_position_and_aging
        """
        ctx = self._submitted()
        charge_id = ctx["charges"][0]["id"]
        baseline = ctx["charges"][0]["unbilled_since"]
        assert baseline == "2026-08-01T00:00:00.000Z"
        assert ctx["invoice"]["net_total_cents"] == 52800

        set_clock("2026-09-15T09:00:00Z")
        remit(ctx["invoice"]["id"], "DISPUTED")

        released = read_charge(charge_id)
        assert released["routing_state"] == "ROUTED_SPONSOR"
        assert released["billing_state"] == "UNBILLED"
        assert released["sponsor_invoice_id"] is None
        assert released["unbilled_since"] == baseline

        run = run_aging(ctx["study"]["id"])
        assert run["run_date"] == "2026-09-15"
        assert run["charges_aged_count"] == 1
        aged = read_charge(charge_id)
        assert aged["aging_days"] == 45
        assert aged["aging_bucket"] == "AGING_31_60"

        resubmitted = submit_invoice(ctx["invoice"]["id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["line_count"] == 1
        assert resubmitted["net_total_cents"] == 52800


class TestAgingEpochBoundary:
    """Thirty days is ``CURRENT``; thirty-one is ``AGING_31_60``."""

    STUDY = {
        "protocol_number": "AMC-2390-N",
        "funding_source": "INDUSTRY_SPONSORED",
    }

    def test_09_exactly_thirty_days_unbilled_is_still_current(self):
        """An unbilled charge from 2026-08-10 read on a 2026-09-09 run is 30
        days old, which the inclusive upper bound keeps in ``CURRENT``.

        PRD §3.9: "and then assigns `aging_bucket` by inclusive upper bounds:
        `CURRENT` at 30 days or fewer, `AGING_31_60` above 30 and at most 60,
        `AGING_61_90` above 60 and at most 90, and `DELINQUENT_90_PLUS` above 90
        — so 30 days is `CURRENT`, 31 is `AGING_31_60`, 90 is `AGING_61_90`, and
        91 is `DELINQUENT_90_PLUS`."

        Design: Difficulty/boundary_precision_check/aging_bucket_flips_at_day_31_and_is_stale_between_runs
        """
        ctx = setup_aged_sponsor_charge(
            unbilled_at="2026-08-10T00:00:00Z",
            run_at="2026-09-09T23:00:00Z",
            study_overrides=self.STUDY,
        )
        assert ctx["charge"]["unbilled_since"] == "2026-08-10T00:00:00.000Z"

        run = run_aging(ctx["study"]["id"])
        assert run["run_date"] == "2026-09-09"
        assert run["charges_aged_count"] == 1
        assert run["delinquent_charge_count"] == 0
        assert run["delinquent_sponsor_cents"] == 0

        charge = read_charge(ctx["charge"]["id"])
        assert charge["aging_days"] == 30
        assert charge["aging_bucket"] == "CURRENT"

    def test_10_the_bucket_is_stale_until_the_next_run_and_then_flips(self):
        """Moving the clock past the boundary changes nothing until the manager
        runs the epoch again, and the next run reads 31 days.

        PRD §2.10: "Every cascade in this system completes inside the request
        that triggers it — there is no deferred or background reconciliation —
        with exactly one exception: a charge's `aging_days` and `aging_bucket`
        are refreshed only by the aging epoch job and are deliberately stale
        between runs."

        Design: Difficulty/boundary_precision_check/aging_bucket_flips_at_day_31_and_is_stale_between_runs
        """
        ctx = setup_aged_sponsor_charge(
            unbilled_at="2026-08-10T00:00:00Z",
            run_at="2026-09-09T23:00:00Z",
            study_overrides=self.STUDY,
        )
        run_aging(ctx["study"]["id"])

        set_clock("2026-09-10T00:30:00Z")
        stale = read_charge(ctx["charge"]["id"])
        assert stale["aging_days"] == 30
        assert stale["aging_bucket"] == "CURRENT"

        run = run_aging(ctx["study"]["id"])
        assert run["run_date"] == "2026-09-10"
        assert run["charges_aged_count"] == 1

        flipped = read_charge(ctx["charge"]["id"])
        assert flipped["aging_days"] == 31
        assert flipped["aging_bucket"] == "AGING_31_60"


class TestInvoiceLineSelectorStopsAtTheGrossCap:
    """The selector breaks at the first candidate that would breach a cap."""

    GRID = [
        item_spec(
            "J9999",
            classification="RESEARCH_PAID",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=1500000,
            negotiated_unit_cents=1200000,
            expected_occurrences=1,
        )
    ]

    def test_11_the_selector_stops_rather_than_skipping_to_a_smaller_candidate(self):
        """With 1,200,000 taken, the 900,000 candidate would breach the
        2,000,000-cent cap, so the walk stops and never reaches the 100,000
        candidate behind it.

        PRD §3.8: "It **stops** — it does not skip the candidate and continue —
        the moment either of two caps would be breached: taking this candidate
        would make the number of selected lines exceed 25, or the running
        subtotal plus this candidate's `amount_cents` plus the running indirect
        plus this line's indirect would be strictly greater than 2,000,000
        cents."

        Design: Corner/calculations/invoice_line_selection_stops_at_the_gross_cap_and_does_not_skip_ahead
        """
        ctx = setup_priced_study_with_sponsor_charges(
            [
                {
                    "charge_code": "J9999",
                    "service_date": "2026-08-01",
                    "amount_cents": 1200000,
                },
                {
                    "charge_code": "J9999",
                    "service_date": "2026-08-02",
                    "amount_cents": 900000,
                },
                {
                    "charge_code": "J9999",
                    "service_date": "2026-08-03",
                    "amount_cents": 100000,
                },
            ],
            item_specs=self.GRID,
            indirect_rate_pct=40.0,
            study_overrides={
                "protocol_number": "AMC-2390-C24",
                "funding_source": "INVESTIGATOR_INITIATED",
            },
            qct_basis=None,
        )
        assert ctx["study"]["effective_indirect_rate_pct"] == 0.0
        assert ctx["study"]["sponsor_unbilled_cents"] == 2200000

        invoice = raise_invoice(ctx["study"]["id"])

        assert invoice["invoice_number"] == "INV-AMC-2390-C24-001"
        assert invoice["line_count"] == 1
        assert invoice["subtotal_cents"] == 1200000
        assert invoice["indirect_cents"] == 0
        assert invoice["gross_total_cents"] == 1200000
        assert invoice["volume_credit_cents"] == 24000
        assert invoice["net_total_cents"] == 1176000
        # Stamping the invoice does not bill anything yet.
        assert read_study(ctx["study"]["id"])["sponsor_unbilled_cents"] == 2200000
        rows, _meta = validate_paginated(
            api_client.list_charges(
                make_manager_headers(MANAGER_ONE),
                params={"study_id": ctx["study"]["id"]},
            )
        )
        remaining = [row for row in rows if row["sponsor_invoice_id"] is None]
        assert sorted(row["amount_cents"] for row in remaining) == [100000, 900000]
