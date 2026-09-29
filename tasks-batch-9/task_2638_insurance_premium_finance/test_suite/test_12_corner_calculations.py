"""Calculation corners: the SIMPLE_INTEREST rounding order and its declining
schedule, the servicing sweep's doubly filtered input set, the two rebate
methods, the inclusive payoff boundary, the whole-only fee bucket with its
surplus rule, and the rebate decay curve with its reversal reset.
"""

from test_helpers import (
    MAX_OVERPAYMENT_CENTS,
    ApiErrorId,
    factories,
    fixtures,
    round_half_up,
    rule_of_78_rebate_cents,
    simple_interest_finance_charge_cents,
    simple_interest_periods,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import ANALYST_ORIGIN, COMPLIANCE


def _simple_interest_context(api):
    """A CA regime that prices under SIMPLE_INTEREST, plus a licence and parties."""
    fixtures.set_clock(api, "2026-08-15T00:00:00Z")
    ctx = fixtures.create_state_regime(
        api,
        rule_payload=factories.state_rate_rule(
            "CA", finance_charge_method="SIMPLE_INTEREST", max_term_months=12
        ),
        license_payload=factories.license_payload(license_number="PFC-CA-001"),
    )
    ctx.update(
        fixtures.create_parties(
            api,
            insured_payload=factories.insured(
                legal_name="Pacific Freight Cooperative", mailing_state_code="CA"
            ),
            agent_payload=factories.producer_agent(
                agency_name="Golden Gate Brokers", state_code="CA"
            ),
            insurer_payload=factories.insurer(
                carrier_name="Sierra Mutual", naic_code="20456"
            ),
        )
    )
    return ctx


def _simple_interest_note(api):
    """The 300000 CA note, activated: amount financed 251500 at 1800 bps."""
    ctx = _simple_interest_context(api)
    assert ctx["rule"]["finance_charge_method"] == "SIMPLE_INTEREST"
    return fixtures.active_agreement(
        api,
        ctx=ctx,
        policies=[
            factories.financed_policy(
                ctx["insurer_id"], policy_number="SM-PR-1", gross_premium_cents=300000
            )
        ],
        down_payment_cents=50000,
        service_fee_cents=1500,
        installment_count=6,
        first_installment_due_date="2026-10-01",
    )


class TestSimpleInterestRoundsEachPeriodBeforeSumming:
    """The rounding order and the rounding mode are both observable in the
    total."""

    def test_the_declining_balance_basis_is_the_amount_financed(self, api):
        """251500 sits in the first volume tier and is capped at the ceiling.

        The PRD states: "Second, `amount_financed_cents` is the premium basis minus
        `down_payment_cents`, plus `service_fee_cents`, plus
        `carried_over_balance_cents`."

        Design: Corner/calculations/precision_simple_interest_rounds_each_period_before_summing
        """
        bundle = _simple_interest_note(api)

        activated = bundle["activated"]
        assert activated["amount_financed_cents"] == 300000 - 50000 + 1500 == 251500
        assert activated["effective_annual_rate_bps"] == 1800, (
            "251500 takes the first tier's 1800 basis points, which is exactly the "
            "statutory ceiling"
        )

    def test_the_six_rounded_periods_are_summed_rather_than_the_exact_products(
        self, api
    ):
        """13205, not the 13204 that a single final rounding produces.

        The PRD states: "Every period is rounded before it is summed; summing exact
        products and rounding once at the end is a different and forbidden result."

        Design: Corner/calculations/precision_simple_interest_rounds_each_period_before_summing
        """
        bundle = _simple_interest_note(api)

        periods = simple_interest_periods(251500, 1800, 6)
        assert periods == [3773, 3144, 2515, 1886, 1258, 629]
        assert bundle["activated"]["finance_charge_cents"] == (
            simple_interest_finance_charge_cents(251500, 1800, 6)
        ) == 13205
        assert bundle["activated"]["finance_charge_cents"] != 13204, (
            "the exact products sum to 13203.90, which a single rounding would "
            "report as 13204"
        )

    def test_the_first_period_tie_is_carried_up(self, api):
        """3772.5 exactly, and half up means 3773.

        The PRD states: "Under `SIMPLE_INTEREST`, interest accrues on a declining
        balance over equal principal slices: let the base principal slice be
        `amount_financed_cents` divided by `installment_count` and truncated down to
        whole cents, and let the outstanding balance start at `amount_financed_cents`;
        then, for each installment position from the first to the last, the principal
        retired is the base slice for every position except the last, where it is the
        entire remaining outstanding balance, while that period's interest is the
        outstanding balance at the start of the period multiplied by
        `effective_annual_rate_bps`, divided by 10000 and by 12, and rounded half up to
        whole cents."

        Design: Corner/calculations/precision_simple_interest_rounds_each_period_before_summing
        """
        bundle = _simple_interest_note(api)

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert 251500 * 1800 * 2 == (3772 * 2 + 1) * 120000, (
            "period one is exactly 3772.5, the midpoint that separates half up from "
            "the banker's rule"
        )
        assert rows[0]["finance_charge_component_cents"] == 3773

    def test_each_later_period_is_driven_by_its_own_opening_balance(self, api):
        """3144 and 629 are independent roundings, not a shared quotient.

        The PRD states: "Each period's rounded interest is added to
        `finance_charge_cents` and the period's principal is then subtracted from the
        outstanding balance."

        Design: Corner/calculations/precision_simple_interest_rounds_each_period_before_summing
        """
        bundle = _simple_interest_note(api)

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[1]["finance_charge_component_cents"] == 3144, (
            "3143.76 rounds up"
        )
        assert rows[5]["finance_charge_component_cents"] == 629, "628.8 rounds up"

    def test_the_total_and_the_opening_charge_balance_agree_with_the_sum(self, api):
        """264705 financed and 13205 of charge still owed at activation.

        The PRD states: "Finally, `total_of_payments_cents` is `amount_financed_cents`
        plus `finance_charge_cents`."

        Design: Corner/calculations/precision_simple_interest_rounds_each_period_before_summing
        """
        bundle = _simple_interest_note(api)

        activated = bundle["activated"]
        assert activated["total_of_payments_cents"] == 251500 + 13205 == 264705
        assert activated["unpaid_finance_charge_cents"] == 13205

    def test_the_provisional_quote_used_the_same_arithmetic(self, api):
        """The attestation confirmed the quoted premium, so the two agree.

        The PRD states: "The fifth step branches on the regime's
        `finance_charge_method`, and the two branches are genuinely different
        arithmetic."

        Design: Corner/calculations/precision_simple_interest_rounds_each_period_before_summing
        """
        ctx = _simple_interest_context(api)
        bundle = fixtures.submitted_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"],
                    policy_number="SM-PR-1",
                    gross_premium_cents=300000,
                )
            ],
            down_payment_cents=50000,
            service_fee_cents=1500,
            installment_count=6,
            first_installment_due_date="2026-10-01",
        )

        assert bundle["submitted"]["finance_charge_cents"] == 13205, (
            "any divergence from the final figure on this fixture is a rounding "
            "fault rather than a basis fault"
        )


class TestSimpleInterestScheduleDeclinesAcrossItsSixRows:
    """Flat principal, shrinking finance charge, declining instalment."""

    def test_the_schedule_has_six_rows_over_the_final_quote(self, api):
        """One row per instalment, over 251500 and 13205.

        The PRD states: "With the final quote in hand the platform cuts the schedule,
        inserting exactly `installment_count` installment rows in `SCHEDULED` status,
        each carrying a 1-based `installment_number`, a `due_date`, an `amount_cents`,
        its split into `principal_component_cents` and
        `finance_charge_component_cents`, and a `paid_cents` of 0."

        Design: Corner/calculations/correct_result_simple_interest_declining_installment_schedule
        """
        bundle = _simple_interest_note(api)

        rows, meta = validate_paginated(
            api.list_installments(bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 100})
        )
        assert meta["total_count"] == 6
        assert [row["installment_number"] for row in rows] == [1, 2, 3, 4, 5, 6]
        assert bundle["activated"]["amount_financed_cents"] == 251500
        assert bundle["activated"]["finance_charge_cents"] == 13205
        assert bundle["activated"]["total_of_payments_cents"] == 264705

    def test_no_two_installment_amounts_are_equal(self, api):
        """45689 down to 42549, which the ADD_ON branch never produces.

        The PRD states: "Under `SIMPLE_INTEREST` the installments decline instead."

        Design: Corner/calculations/correct_result_simple_interest_declining_installment_schedule
        """
        bundle = _simple_interest_note(api)

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        amounts = [row["amount_cents"] for row in rows]
        assert amounts == [45689, 45060, 44431, 43802, 43174, 42549]
        assert len(set(amounts)) == 6

    def test_the_principal_slice_is_flat_with_the_remainder_at_the_end(self, api):
        """41916 five times, then 41920.

        The PRD states: "Walking the positions in order, each installment's
        `principal_component_cents` is the base slice, except the last, which takes the
        entire remaining outstanding balance; its `finance_charge_component_cents` is the
        outstanding balance at the start of that period multiplied by
        `effective_annual_rate_bps`, divided by 10000 and by 12, and rounded half up;
        its `amount_cents` is the sum of the two components; and the outstanding balance
        is then reduced by that installment's principal component before the next
        position is computed."

        Design: Corner/calculations/correct_result_simple_interest_declining_installment_schedule
        """
        bundle = _simple_interest_note(api)

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert 251500 // 6 == 41916
        assert [row["principal_component_cents"] for row in rows[:5]] == [41916] * 5
        assert rows[5]["principal_component_cents"] == 41920, (
            "the four-cent remainder rides on the final position"
        )
        assert rows[0]["amount_cents"] == 41916 + 3773

    def test_all_three_columns_close_on_the_quote(self, api):
        """Amounts, principal and finance charge each sum exactly.

        The PRD states: "The arithmetic remainder always lands on the final installment
        so that the installment amounts sum to `total_of_payments_cents` exactly and the
        finance-charge components sum to `finance_charge_cents` exactly; rounding each
        installment independently would leave a one-cent drift and is wrong."

        Design: Corner/calculations/correct_result_simple_interest_declining_installment_schedule
        """
        bundle = _simple_interest_note(api)

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        assert sum(row["amount_cents"] for row in rows) == 264705
        assert sum(row["principal_component_cents"] for row in rows) == 251500
        assert sum(row["finance_charge_component_cents"] for row in rows) == 13205

    def test_the_due_dates_walk_whole_months_across_the_year_boundary(self, api):
        """2026-10-01 through 2027-03-01.

        The PRD states: "Due dates walk forward by whole calendar months from
        `first_installment_due_date`: installment number 1 falls on that date, and
        installment *k* falls one month later than installment *k* minus one."

        Design: Corner/calculations/correct_result_simple_interest_declining_installment_schedule
        """
        bundle = _simple_interest_note(api)

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["due_date"] == "2026-10-01"
        assert rows[5]["due_date"] == "2027-03-01"


class TestServicingSweepFiltersItsInputSetTwice:
    """Three notes on one regime, one of them carrying a paid instalment long
    past due."""

    def _three_notes(self, api):
        ctx = fixtures.origination_context(api)
        note_a = fixtures.active_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-IF-A")
            ],
        )
        fixtures.set_clock(api, "2026-09-05T00:00:00Z")
        note_a["payment"] = fixtures.post_payment(
            api, note_a["agreement_id"], 89941, "2026-09-05"
        )
        note_b = fixtures.submitted_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-IF-B")
            ],
        )
        note_c = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-IF-C")
            ],
        )
        return {"ctx": ctx, "a": note_a, "b": note_b, "c": note_c}

    def _swept(self, api):
        world = self._three_notes(api)
        world["run"] = fixtures.advance_and_service(api, "2026-11-12T00:00:00Z")
        return world

    def test_the_fixture_starts_with_one_paid_row_and_two_unactivated_notes(self, api):
        """Note A's instalment 1 is settled; notes B and C have no schedule.

        The PRD states: "Under the `STANDARD` variant, `rebate_applied_cents` stays 0
        and the money flows through four buckets in a fixed order."

        Design: Corner/calculations/input_set_filtering_servicing_run_skips_inactive_notes_and_paid_installments
        """
        world = self._three_notes(api)

        rows = fixtures.read_installments(api, world["a"]["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["status"] == "PAID"
        assert rows[0]["paid_cents"] == 89941
        assert world["b"]["submitted"]["status"] == "PENDING_VERIFICATION"
        assert world["c"]["agreement"]["status"] == "DRAFT"

    def test_the_sweep_counts_only_the_one_installment_it_may_touch(self, api):
        """One marked, one charged, one note advanced.

        The PRD states: "The pass reports three counts: `past_due_marked`,
        `late_fees_assessed` and `agreements_advanced_to_late`."

        Design: Corner/calculations/input_set_filtering_servicing_run_skips_inactive_notes_and_paid_installments
        """
        world = self._swept(api)

        assert world["run"]["past_due_marked"] == 1, (
            "instalment 1 is six weeks past its due date, but it is PAID and so "
            "outside the candidate set"
        )
        assert world["run"]["late_fees_assessed"] == 1
        assert world["run"]["agreements_advanced_to_late"] == 1

    def test_the_paid_row_is_untouched_and_the_future_row_is_left_alone(self, api):
        """PAID, PAST_DUE and SCHEDULED after one pass.

        The PRD states: "Only notes whose financing status is `ACTIVE` are considered,
        and only those whose `delinquency_stage` is `CURRENT`, `LATE` or `NOIC_ISSUED`;
        drafts, pending notes and terminal notes are skipped entirely, as are
        installments already `PAID` or `VOIDED`."

        Design: Corner/calculations/input_set_filtering_servicing_run_skips_inactive_notes_and_paid_installments
        """
        world = self._swept(api)

        rows = fixtures.read_installments(api, world["a"]["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["status"] == "PAID"
        assert rows[1]["status"] == "PAST_DUE"
        assert rows[2]["status"] == "SCHEDULED", (
            "instalment 3 falls due 2026-12-01, which is still in the future"
        )

    def test_the_single_fee_names_the_installment_that_earned_it(self, api):
        """Number 2, 4497, OUTSTANDING, assessed at the clock date.

        The PRD states: "The new assessment is written with that `amount_cents`, a
        `status` of `OUTSTANDING`, an `assessed_date` equal to the clock date, and the
        `installment_number` of the installment that triggered it — a plain integer
        identifying the position in the schedule, not a reference to the installment
        row."

        Design: Corner/calculations/input_set_filtering_servicing_run_skips_inactive_notes_and_paid_installments
        """
        world = self._swept(api)

        fees = fixtures.read_late_fees(api, world["a"]["agreement_id"], COMPLIANCE)
        assert len(fees) == 1
        assert fees[0]["installment_number"] == 2
        assert fees[0]["amount_cents"] == 4497
        assert fees[0]["status"] == "OUTSTANDING"
        assert fees[0]["assessed_date"] == "2026-11-12"

    def test_the_unactivated_notes_are_not_in_the_sweep_at_all(self, api):
        """Neither note B nor note C moved, and neither acquired a fee.

        The PRD states: "A `ComplianceOfficer` runs the pass, and it evaluates the whole
        book against the current logical clock in a pinned order: agreements are
        processed by `created_at` ascending, and within one agreement its installments
        are processed by `installment_number` ascending."

        Design: Corner/calculations/input_set_filtering_servicing_run_skips_inactive_notes_and_paid_installments
        """
        world = self._swept(api)

        note_b = fixtures.read_agreement(api, world["b"]["agreement_id"], COMPLIANCE)
        assert note_b["status"] == "PENDING_VERIFICATION"
        assert note_b["delinquency_stage"] == "CURRENT"
        assert note_b["late_fee_count"] == 0
        note_c = fixtures.read_agreement(api, world["c"]["agreement_id"], COMPLIANCE)
        assert note_c["status"] == "DRAFT"
        assert note_c["delinquency_stage"] == "CURRENT"
        assert note_c["late_fee_count"] == 0

        _rows, meta = validate_paginated(
            api.list_installments(
                world["b"]["agreement_id"], COMPLIANCE, {"limit": 100}
            )
        )
        assert meta["total_count"] == 0, (
            "a note with no schedule offers the sweep nothing to mark"
        )

    def test_exactly_one_note_of_the_three_is_delinquent(self, api):
        """The stage filter finds note A and nothing else.

        The PRD states: "An agreement that acquires a newly past-due installment while
        `CURRENT` advances `CURRENT` → `LATE` in the same pass."

        Design: Corner/calculations/input_set_filtering_servicing_run_skips_inactive_notes_and_paid_installments
        """
        world = self._swept(api)

        rows, meta = validate_paginated(
            api.list_agreements(
                COMPLIANCE,
                {
                    "state_rule_id": world["ctx"]["rule_id"],
                    "delinquency_stage": "LATE",
                    "limit": 50,
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == world["a"]["agreement_id"]


class TestRebateMethodDivergesOnIdenticalNotes:
    """Two notes identical in everything but their regime's rebate method."""

    def _two_regimes(self, api):
        ctx = fixtures.origination_context(api)
        nevada = fixtures.create_state_regime(
            api,
            rule_payload=factories.state_rate_rule("NV", rebate_method="ACTUARIAL"),
            license_payload=factories.license_payload(license_number="PFC-NV-001"),
        )
        ctx_nv = dict(ctx)
        ctx_nv["rule"] = nevada["rule"]
        ctx_nv["rule_id"] = nevada["rule_id"]
        return ctx, ctx_nv

    def _two_notes(self, api):
        ctx_tx, ctx_nv = self._two_regimes(api)
        texas = fixtures.active_agreement(
            api,
            ctx=ctx_tx,
            policies=[
                factories.financed_policy(ctx_tx["insurer_id"], policy_number="MC-VD-TX")
            ],
        )
        nevada = fixtures.active_agreement(
            api,
            ctx=ctx_nv,
            policies=[
                factories.financed_policy(ctx_nv["insurer_id"], policy_number="MC-VD-NV")
            ],
        )
        fixtures.set_clock(api, "2026-09-05T00:00:00Z")
        texas["payment"] = fixtures.post_payment(
            api, texas["agreement_id"], 179882, "2026-09-05"
        )
        nevada["payment"] = fixtures.post_payment(
            api, nevada["agreement_id"], 179882, "2026-09-05"
        )
        return texas, nevada

    def _quotes(self, api):
        texas, nevada = self._two_notes(api)
        texas["quote"] = validate_success(
            api.get_payoff_quote(
                texas["agreement_id"], ANALYST_ORIGIN, {"as_of_date": "2026-09-05"}
            ),
            200,
        )
        nevada["quote"] = validate_success(
            api.get_payoff_quote(
                nevada["agreement_id"], ANALYST_ORIGIN, {"as_of_date": "2026-09-05"}
            ),
            200,
        )
        return texas, nevada

    def test_the_two_notes_are_priced_and_paid_identically(self, api):
        """Same finance charge, same variant, same allocation.

        The PRD states: "Bucket three does the same for `SCHEDULED` installments while
        any money remains, always taking the lowest `installment_number` first and
        retiring finance charge before principal within each."

        Design: Corner/calculations/variant_divergence_rule_of_78_versus_actuarial_payoff_on_identical_notes
        """
        texas, nevada = self._two_notes(api)

        assert texas["activated"]["finance_charge_cents"] == 37650
        assert nevada["activated"]["finance_charge_cents"] == 37650
        for note in (texas, nevada):
            assert note["payment"]["allocation_variant"] == "STANDARD", (
                "179882 is far short of the 502000 net payoff at that date"
            )
            assert note["payment"]["applied_finance_charge_cents"] == 12550
            assert note["payment"]["applied_principal_cents"] == 167332
            agreement = fixtures.read_agreement(api, note["agreement_id"])
            assert agreement["principal_balance_cents"] == 334668
            assert agreement["unpaid_finance_charge_cents"] == 25100

    def test_both_notes_have_retired_exactly_two_installments(self, api):
        """The unpaid count that feeds the curve is 4 on each note.

        The PRD states: "Let *r* be the number of installments not yet retired:
        `installment_count` minus the count of the note's installments whose `status` is
        `PAID`."

        Design: Corner/calculations/variant_divergence_rule_of_78_versus_actuarial_payoff_on_identical_notes
        """
        texas, nevada = self._two_notes(api)

        for note in (texas, nevada):
            _rows, meta = validate_paginated(
                api.list_installments(
                    note["agreement_id"],
                    ANALYST_ORIGIN,
                    {"status": "PAID", "limit": 100},
                )
            )
            assert meta["total_count"] == 2

    def test_the_pre_rebate_position_of_the_two_quotes_is_the_same(self, api):
        """359768 gross on both, with no fees and no credit.

        The PRD states: "This computed read accepts an optional `as_of_date`, defaulting
        to the clock date, and returns that `as_of_date`, the `gross_balance_cents` (the
        note's `principal_balance_cents` plus its `unpaid_finance_charge_cents`), the
        `unearned_finance_charge_rebate_cents` the borrower would be granted, the
        `outstanding_late_fee_cents` still owed, the `unapplied_credit_cents` sitting in
        suspense, the resulting `net_payoff_cents`, and the `rebate_method` under which
        the figure was computed."

        Design: Corner/calculations/variant_divergence_rule_of_78_versus_actuarial_payoff_on_identical_notes
        """
        texas, nevada = self._quotes(api)

        assert texas["quote"]["gross_balance_cents"] == 334668 + 25100 == 359768
        assert nevada["quote"]["gross_balance_cents"] == 359768
        assert texas["quote"]["outstanding_late_fee_cents"] == 0
        assert texas["quote"]["unapplied_credit_cents"] == 0
        assert texas["quote"]["as_of_date"] == "2026-09-05", (
            "the quote echoes the requested date rather than the clock"
        )

    def test_the_sum_of_digits_curve_rebates_less_than_the_tail_carries(self, api):
        """17929 under the rule of 78s, inside the cap.

        The PRD states: "Under the `RULE_OF_78` method, the rebate is
        `finance_charge_cents` multiplied by *r*, multiplied by *r* plus one, divided by
        the product of `installment_count` and `installment_count` plus one, rounded half
        up — the sum-of-digits curve, which front-loads finance charge and therefore
        rebates *less* than a straight-line schedule actually allocated to the unpaid
        tail."

        Design: Corner/calculations/variant_divergence_rule_of_78_versus_actuarial_payoff_on_identical_notes
        """
        texas, _nevada = self._quotes(api)

        assert texas["quote"]["rebate_method"] == "RULE_OF_78"
        assert texas["quote"]["unearned_finance_charge_rebate_cents"] == (
            rule_of_78_rebate_cents(37650, 4, 6)
        ) == 17929
        assert 17929 < 25100, "the cap does not bind at this position"
        assert texas["quote"]["net_payoff_cents"] == 359768 - 17929 == 341839

    def test_the_actuarial_method_rebates_the_components_it_finds(self, api):
        """25100 is exactly the finance charge on installments 3 to 6.

        The PRD states: "Under the `ACTUARIAL` method, the rebate is instead the exact
        sum of `finance_charge_component_cents` over the note's installments whose
        `status` is `SCHEDULED` or `PAST_DUE`; no rounding occurs, because the components
        being summed are already whole cents."

        Design: Corner/calculations/variant_divergence_rule_of_78_versus_actuarial_payoff_on_identical_notes
        """
        _texas, nevada = self._quotes(api)

        assert nevada["quote"]["rebate_method"] == "ACTUARIAL"
        assert nevada["quote"]["unearned_finance_charge_rebate_cents"] == 6275 * 4 == 25100
        assert nevada["quote"]["net_payoff_cents"] == 359768 - 25100 == 334668

    def test_the_same_account_has_two_legal_payoff_figures(self, api):
        """A 7171-cent divergence created only by the statute.

        The PRD states: "For an identical `ADD_ON` schedule the actuarial figure is
        strictly larger than the sum-of-digits figure, so the same account genuinely has
        two different payoff numbers depending on which state wrote its statute."

        Design: Corner/calculations/variant_divergence_rule_of_78_versus_actuarial_payoff_on_identical_notes
        """
        texas, nevada = self._quotes(api)

        tx_rebate = texas["quote"]["unearned_finance_charge_rebate_cents"]
        nv_rebate = nevada["quote"]["unearned_finance_charge_rebate_cents"]
        assert nv_rebate > tx_rebate
        assert (
            texas["quote"]["net_payoff_cents"] - nevada["quote"]["net_payoff_cents"]
        ) == 7171


class TestPayoffVariantBoundaryIsInclusive:
    """One cent either side of the net payoff, on two identical notes."""

    def _two_notes(self, api):
        ctx = fixtures.origination_context(api)
        first = fixtures.active_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-VS-1")
            ],
        )
        second = fixtures.active_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-VS-2")
            ],
        )
        fixtures.set_clock(api, "2026-09-05T00:00:00Z")
        for note in (first, second):
            fixtures.post_payment(api, note["agreement_id"], 179882, "2026-09-05")
            note["quote"] = validate_success(
                api.get_payoff_quote(
                    note["agreement_id"], ANALYST_ORIGIN, {"as_of_date": "2026-09-05"}
                ),
                200,
            )
        return first, second

    def test_both_notes_sit_on_the_same_boundary(self, api):
        """341839 is the net payoff on each of them.

        The PRD states: "The net payoff is then `principal_balance_cents` plus
        `unpaid_finance_charge_cents`, minus the rebate, plus `late_fee_balance_cents`,
        minus `unapplied_credit_cents`."

        Design: Corner/calculations/variant_selection_payoff_boundary_at_exactly_net_payoff_cents
        """
        first, second = self._two_notes(api)

        assert first["quote"]["net_payoff_cents"] == 341839
        assert second["quote"]["net_payoff_cents"] == 341839

    def test_one_cent_below_the_boundary_runs_the_standard_variant(self, api):
        """No rebate is granted on a 341838 tender.

        The PRD states: "Allocation begins by choosing a variant, and the choice is made
        *before* any money moves: the payment runs as the `PAYOFF` variant when the
        tendered `amount_cents` is greater than or equal to the net payoff computed as of
        `received_date`, and as the `STANDARD` variant otherwise."

        Design: Corner/calculations/variant_selection_payoff_boundary_at_exactly_net_payoff_cents
        """
        first, _second = self._two_notes(api)

        payment = fixtures.post_payment(
            api, first["agreement_id"], 341838, "2026-09-05"
        )

        assert payment["allocation_variant"] == "STANDARD"
        assert payment["rebate_applied_cents"] == 0

    def test_the_standard_allocation_walks_the_remaining_four_rows(self, api):
        """25100 of charge and 316738 of principal, with nothing parked.

        The PRD states: "As the buckets fill, each installment's `paid_cents`
        accumulates and an installment whose `paid_cents` reaches its `amount_cents`
        moves to `PAID`; the note's `principal_balance_cents`,
        `unpaid_finance_charge_cents` and `late_fee_balance_cents` are decremented by
        exactly the amounts absorbed in buckets one to three; and
        `applied_late_fee_cents`, `applied_finance_charge_cents` and
        `applied_principal_cents` record the three totals."

        Design: Corner/calculations/variant_selection_payoff_boundary_at_exactly_net_payoff_cents
        """
        first, _second = self._two_notes(api)

        payment = fixtures.post_payment(
            api, first["agreement_id"], 341838, "2026-09-05"
        )

        assert payment["applied_late_fee_cents"] == 0
        assert payment["applied_finance_charge_cents"] == 6275 * 4 == 25100
        assert payment["applied_principal_cents"] == 316738
        assert payment["applied_unapplied_cents"] == 0
        assert 25100 + 316738 == 341838

    def test_one_cent_short_of_payoff_leaves_the_forgone_rebate_owing(self, api):
        """17930 of principal survives and the note stays ACTIVE.

        The PRD states: "The consequence is that the same tendered amount retires a
        strictly larger obligation under the payoff variant than under the standard one,
        because only the payoff variant grants the rebate."

        Design: Corner/calculations/variant_selection_payoff_boundary_at_exactly_net_payoff_cents
        """
        first, _second = self._two_notes(api)

        fixtures.post_payment(api, first["agreement_id"], 341838, "2026-09-05")

        agreement = fixtures.read_agreement(api, first["agreement_id"])
        assert agreement["status"] == "ACTIVE"
        assert agreement["principal_balance_cents"] == 17930, (
            "the forgone 17929 of rebate plus the missing cent"
        )
        assert agreement["unpaid_finance_charge_cents"] == 0
        assert agreement["unapplied_credit_cents"] == 0

        rows = fixtures.read_installments(api, first["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[5]["status"] == "SCHEDULED"
        assert rows[5]["paid_cents"] == 72015

    def test_exactly_at_the_boundary_runs_the_payoff_variant(self, api):
        """341839 grants the rebate before any bucket is touched.

        The PRD states: "Under the `PAYOFF` variant the rebate is granted first:
        `rebate_applied_cents` is stamped with the rebate figure and the note's
        `unpaid_finance_charge_cents` is reduced by it."

        Design: Corner/calculations/variant_selection_payoff_boundary_at_exactly_net_payoff_cents
        """
        _first, second = self._two_notes(api)

        payment = fixtures.post_payment(
            api, second["agreement_id"], 341839, "2026-09-05"
        )

        assert payment["allocation_variant"] == "PAYOFF", (
            "the comparison is greater-than-or-equal, so the boundary day itself pays "
            "the note off"
        )
        assert payment["rebate_applied_cents"] == 17929
        assert payment["applied_late_fee_cents"] == 0
        assert payment["applied_finance_charge_cents"] == 25100 - 17929 == 7171
        assert payment["applied_principal_cents"] == 334668
        assert payment["applied_unapplied_cents"] == 0

    def test_the_boundary_tender_settles_the_note_completely(self, api):
        """PAID_IN_FULL with six paid rows and no balances left.

        The PRD states: "If the allocation drives `principal_balance_cents`,
        `unpaid_finance_charge_cents` and `late_fee_balance_cents` all to zero, the
        financing dimension completes: the note moves `ACTIVE` → `PAID_IN_FULL`, every
        installment still `SCHEDULED` or `PAST_DUE` moves to `PAID`, and
        `refund_due_cents` is set to the surviving `unapplied_credit_cents`, which is the
        surplus the company owes back to the borrower."

        Design: Corner/calculations/variant_selection_payoff_boundary_at_exactly_net_payoff_cents
        """
        _first, second = self._two_notes(api)

        fixtures.post_payment(api, second["agreement_id"], 341839, "2026-09-05")

        agreement = fixtures.read_agreement(api, second["agreement_id"])
        assert agreement["status"] == "PAID_IN_FULL"
        assert agreement["principal_balance_cents"] == 0
        assert agreement["unpaid_finance_charge_cents"] == 0
        assert agreement["unapplied_credit_cents"] == 0

        _rows, meta = validate_paginated(
            api.list_installments(
                second["agreement_id"], ANALYST_ORIGIN, {"status": "PAID", "limit": 100}
            )
        )
        assert meta["total_count"] == 6


class TestFeeBucketIsWholeOnlyAndSurplusParksAsCredit:
    """A tender too small to settle a fee, and a tender larger than the whole
    note."""

    def _two_notes(self, api):
        ctx = fixtures.origination_context(api)
        delinquent = fixtures.active_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-WF-1")
            ],
        )
        current = fixtures.active_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-WF-2")
            ],
            first_installment_due_date="2026-10-14",
        )
        run = fixtures.advance_and_service(api, "2026-10-12T00:00:00Z")
        fees = fixtures.read_late_fees(api, delinquent["agreement_id"])
        delinquent["late_fee"] = fees[0]
        return {"run": run, "w1": delinquent, "w2": current}

    def test_the_sweep_touched_only_the_note_whose_installment_was_due(self, api):
        """One fee of 4497, on note W1 alone.

        The PRD states: "Then, if an installment is `PAST_DUE` and the clock date is
        *strictly after* its `due_date` advanced by the regime's `grace_period_days`, a
        late fee may be assessed against it."

        Design: Corner/calculations/waterfall_allocation_whole_only_fee_bucket_and_payoff_surplus_remainder
        """
        world = self._two_notes(api)

        assert world["run"]["past_due_marked"] == 1
        assert world["run"]["late_fees_assessed"] == 1
        assert world["w1"]["late_fee"]["amount_cents"] == 4497
        assert world["w1"]["late_fee"]["status"] == "OUTSTANDING"
        assert fixtures.read_late_fees(api, world["w2"]["agreement_id"]) == [], (
            "note W2's first installment does not fall due until 2026-10-14"
        )

    def test_a_tender_smaller_than_the_fee_does_not_chip_at_it(self, api):
        """3000 flows past the 4497 fee to the finance charge behind it.

        The PRD states: "Bucket one settles `OUTSTANDING` late fees, ordered by
        `assessed_date` ascending, then `installment_number` ascending, then `created_at`
        ascending; a fee is settled only if the unallocated remainder covers its
        `amount_cents` whole, and a remainder smaller than the fee leaves that fee
        `OUTSTANDING` and flows on rather than part-paying it."

        Design: Corner/calculations/waterfall_allocation_whole_only_fee_bucket_and_payoff_surplus_remainder
        """
        world = self._two_notes(api)

        payment = fixtures.post_payment(
            api, world["w1"]["agreement_id"], 3000, "2026-10-12"
        )

        assert payment["allocation_variant"] == "STANDARD"
        assert payment["applied_late_fee_cents"] == 0
        assert payment["applied_finance_charge_cents"] == 3000
        assert payment["applied_principal_cents"] == 0
        assert payment["applied_unapplied_cents"] == 0

    def test_the_partial_application_leaves_the_row_past_due(self, api):
        """Principal and the fee balance are untouched by the 3000.

        The PRD states: "Bucket two pays `PAST_DUE` installments, ordered by `due_date`
        ascending then `installment_number` ascending, and inside a single installment
        the `finance_charge_component_cents` is retired before the
        `principal_component_cents`; partial application is allowed here and leaves the
        installment `PAST_DUE`."

        Design: Corner/calculations/waterfall_allocation_whole_only_fee_bucket_and_payoff_surplus_remainder
        """
        world = self._two_notes(api)

        fixtures.post_payment(api, world["w1"]["agreement_id"], 3000, "2026-10-12")

        agreement = fixtures.read_agreement(api, world["w1"]["agreement_id"])
        assert agreement["principal_balance_cents"] == 502000
        assert agreement["unpaid_finance_charge_cents"] == 37650 - 3000 == 34650
        assert agreement["late_fee_balance_cents"] == 4497
        assert agreement["unapplied_credit_cents"] == 0
        assert agreement["delinquency_stage"] == "LATE"

        rows = fixtures.read_installments(api, world["w1"]["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["status"] == "PAST_DUE"
        assert rows[0]["paid_cents"] == 3000

    def test_the_surviving_fee_is_still_listed_as_outstanding(self, api):
        """One row, still 4497, after the partial payment.

        The PRD states: "Fees can be listed per note and filtered by `status`, which is
        one of `OUTSTANDING`, `PAID`, `WAIVED` or `REVERSED`."

        Design: Corner/calculations/waterfall_allocation_whole_only_fee_bucket_and_payoff_surplus_remainder
        """
        world = self._two_notes(api)
        fixtures.post_payment(api, world["w1"]["agreement_id"], 3000, "2026-10-12")

        rows, meta = validate_paginated(
            api.list_late_fees(
                world["w1"]["agreement_id"],
                ANALYST_ORIGIN,
                {"status": "OUTSTANDING", "limit": 50},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["amount_cents"] == 4497

    def test_a_late_fee_id_does_not_resolve_as_a_carrier_request(self, api):
        """The two identifier spaces are disjoint.

        The PRD states: "Identifiers in a request path are resolved strictly left to
        right, and the leftmost segment that fails to resolve decides the error."

        Design: Corner/calculations/waterfall_allocation_whole_only_fee_bucket_and_payoff_surplus_remainder
        """
        world = self._two_notes(api)

        validate_error(
            api.get_carrier_cancellation_request(
                world["w1"]["late_fee"]["id"], ANALYST_ORIGIN
            ),
            ApiErrorId.CANCEL_REQUEST_NOT_FOUND.value,
            404,
        )

    def test_a_tender_above_the_payoff_parks_the_surplus_as_credit(self, api):
        """507000 against a 502000 payoff leaves 5000 in suspense.

        The PRD states: "Bucket four parks whatever is left in the note's
        `unapplied_credit_cents`, and the same figure is recorded on the payment as
        `applied_unapplied_cents`."

        Design: Corner/calculations/waterfall_allocation_whole_only_fee_bucket_and_payoff_surplus_remainder
        """
        world = self._two_notes(api)

        payment = fixtures.post_payment(
            api, world["w2"]["agreement_id"], 507000, "2026-10-12"
        )

        assert payment["allocation_variant"] == "PAYOFF"
        assert payment["rebate_applied_cents"] == 37650, (
            "no installment has been retired, so the whole finance charge is unearned "
            "and the cap binds it to exactly that figure"
        )
        assert payment["applied_late_fee_cents"] == 0
        assert payment["applied_finance_charge_cents"] == 0
        assert payment["applied_principal_cents"] == 502000
        assert payment["applied_unapplied_cents"] == 507000 - 502000 == 5000

        agreement = fixtures.read_agreement(api, world["w2"]["agreement_id"])
        assert agreement["status"] == "PAID_IN_FULL"
        assert agreement["principal_balance_cents"] == 0
        assert agreement["unpaid_finance_charge_cents"] == 0
        assert agreement["unapplied_credit_cents"] == 5000

    def test_the_remainder_rule_has_a_hard_statutory_ceiling(self, api):
        """600000 overshoots note W1's payoff by far more than 50000.

        The PRD states: "The platform tolerates a modest overpayment but not an arbitrary
        one: an `amount_cents` exceeding the net payoff by more than 50000 cents — five
        hundred dollars — is refused with `ERR_PAYMENT_EXCEEDS_PAYOFF` (HTTP 422), where
        the net payoff is computed as of the payment's `received_date`."

        Design: Corner/calculations/waterfall_allocation_whole_only_fee_bucket_and_payoff_surplus_remainder
        """
        world = self._two_notes(api)
        fixtures.post_payment(api, world["w1"]["agreement_id"], 3000, "2026-10-12")

        quote = validate_success(
            api.get_payoff_quote(
                world["w1"]["agreement_id"],
                ANALYST_ORIGIN,
                {"as_of_date": "2026-10-12"},
            ),
            200,
        )
        assert quote["net_payoff_cents"] == 506497
        assert 600000 - 506497 == 93503
        assert 93503 > MAX_OVERPAYMENT_CENTS == 50000

        validate_error(
            api.create_payment(
                world["w1"]["agreement_id"],
                factories.payment(600000, "2026-10-12"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.PAYMENT_EXCEEDS_PAYOFF.value,
            422,
        )


class TestRebateDecaysWithPaidCountAndResetsOnReversal:
    """Three readings of the same curve at one frozen date."""

    def _note(self, api):
        bundle = fixtures.canonical_600k_note(api, policy_number="MC-DF-1")
        fixtures.set_clock(api, "2026-09-05T00:00:00Z")
        return bundle

    def _quote(self, api, agreement_id):
        return validate_success(
            api.get_payoff_quote(
                agreement_id, ANALYST_ORIGIN, {"as_of_date": "2026-09-05"}
            ),
            200,
        )

    def test_the_curve_starts_at_the_whole_finance_charge(self, api):
        """With no installment retired the raw figure equals the cap.

        The PRD states: "Whichever method applies, the rebate is finally capped at the
        note's `unpaid_finance_charge_cents`, so a rebate can never create finance charge
        that was never owed."

        Design: Corner/calculations/decay_function_rebate_declines_per_paid_installment_and_resets_on_reversal
        """
        bundle = self._note(api)

        quote = self._quote(api, bundle["agreement_id"])

        assert rule_of_78_rebate_cents(37650, 6, 6) == 37650
        assert quote["unearned_finance_charge_rebate_cents"] == 37650
        assert quote["gross_balance_cents"] == 539650
        assert quote["net_payoff_cents"] == 502000

    def test_retiring_one_installment_moves_the_curve_down_one_step(self, api):
        """26893 at r equal to five, well under the cap.

        The PRD states: "The rebate exists because a borrower who pays early should not
        pay interest for months they never used."

        Design: Corner/calculations/decay_function_rebate_declines_per_paid_installment_and_resets_on_reversal
        """
        bundle = self._note(api)
        payment = fixtures.post_payment(
            api, bundle["agreement_id"], 89941, "2026-09-05"
        )
        assert payment["allocation_variant"] == "STANDARD"
        assert payment["applied_finance_charge_cents"] == 6275
        assert payment["applied_principal_cents"] == 83666

        quote = self._quote(api, bundle["agreement_id"])

        assert quote["unearned_finance_charge_rebate_cents"] == (
            rule_of_78_rebate_cents(37650, 5, 6)
        ) == 26893
        assert round_half_up(37650 * 5 * 6, 42) == 26893
        assert quote["gross_balance_cents"] == 418334 + 31375 == 449709
        assert quote["net_payoff_cents"] == 449709 - 26893 == 422816

    def test_the_only_thing_that_moved_between_the_readings_is_the_paid_count(
        self, api
    ):
        """Both quotes are taken as of the same date.

        The PRD states: "If *r* is zero or negative, the rebate is zero."

        Design: Corner/calculations/decay_function_rebate_declines_per_paid_installment_and_resets_on_reversal
        """
        bundle = self._note(api)
        before = self._quote(api, bundle["agreement_id"])
        fixtures.post_payment(api, bundle["agreement_id"], 89941, "2026-09-05")
        after = self._quote(api, bundle["agreement_id"])

        assert before["as_of_date"] == after["as_of_date"] == "2026-09-05", (
            "no elapsed-time term can explain the change from 37650 to 26893"
        )
        assert before["unearned_finance_charge_rebate_cents"] == 37650
        assert after["unearned_finance_charge_rebate_cents"] == 26893

    def test_reversing_the_payment_puts_the_curve_back_exactly(self, api):
        """The third reading returns to the r equal to six point.

        The PRD states: "The reversal moves the payment `POSTED` → `REVERSED`, stamps
        `reversed_at` from the logical clock, and unwinds the allocation exactly:
        `principal_balance_cents` increases by `applied_principal_cents`;
        `unpaid_finance_charge_cents` increases by `applied_finance_charge_cents` *plus*
        `rebate_applied_cents`, because a rebate granted on a payoff that never cleared
        must be taken back too; `unapplied_credit_cents` decreases by
        `applied_unapplied_cents`; every fee the payment settled returns from `PAID` to
        `OUTSTANDING` and its amount is added back to `late_fee_balance_cents`; and every
        installment the payment touched has its `paid_cents` reduced by that payment's
        contribution, returning to `PAST_DUE` when its `due_date` is strictly earlier than
        the clock date and to `SCHEDULED` otherwise."

        Design: Corner/calculations/decay_function_rebate_declines_per_paid_installment_and_resets_on_reversal
        """
        bundle = self._note(api)
        payment = fixtures.post_payment(
            api, bundle["agreement_id"], 89941, "2026-09-05"
        )
        reversal = validate_success(
            api.reverse_payment(payment["id"], factories.reversal(), ANALYST_ORIGIN),
            200,
        )
        assert reversal["status"] == "REVERSED"

        quote = self._quote(api, bundle["agreement_id"])

        assert quote["unearned_finance_charge_rebate_cents"] == 37650, (
            "a forward-only decay counter could not recover this point"
        )
        assert quote["gross_balance_cents"] == 539650
        assert quote["net_payoff_cents"] == 502000

    def test_the_paid_count_itself_is_back_to_zero(self, api):
        """All six rows are scheduled again after the reversal.

        The PRD states: "Installments that are `VOIDED` count towards neither figure."

        Design: Corner/calculations/decay_function_rebate_declines_per_paid_installment_and_resets_on_reversal
        """
        bundle = self._note(api)
        payment = fixtures.post_payment(
            api, bundle["agreement_id"], 89941, "2026-09-05"
        )
        validate_success(
            api.reverse_payment(payment["id"], factories.reversal(), ANALYST_ORIGIN),
            200,
        )

        _rows, meta = validate_paginated(
            api.list_installments(
                bundle["agreement_id"],
                ANALYST_ORIGIN,
                {"status": "SCHEDULED", "limit": 100},
            )
        )
        assert meta["total_count"] == 6
