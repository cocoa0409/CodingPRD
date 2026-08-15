"""Remittance posting, variance evaluation, and the underpayment queue (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    activate_contract,
    add_claim_line,
    add_contract_term,
    create_draft_contract,
    create_remittance_payload,
    create_test_claim,
    create_test_payer,
    get_claim,
    get_contract,
    get_single_case_for_claim,
    list_cases_for_claim,
    make_finance_director_headers,
    post_remittance,
    price_claim,
    setup_active_contract,
    setup_priced_claim,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AUD, CM, RIA


class TestRemittanceGuards:
    def test_remittance_against_unpriced_claim_rejected(self, api):
        """PRD §3.6: "A `RevenueIntegrityAnalyst` posts a payer remittance
        against a claim that must already be `PRICED` or `REPRICED` —
        remitting against an `UNPRICED` claim is rejected with
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/sm_remittance_against_unpriced_claim_rejected
        """
        payer = create_test_payer(name="Payer RU")
        claim = create_test_claim(
            payer["id"], claim_number="CL-RU1", service_category="LAB",
            admission_date="2026-06-01", discharge_date="2026-06-01",
            total_billed_charges_cents=1000,
        )
        resp = api.create_remittance(
            create_remittance_payload(claim["id"], paid_amount_cents=500), RIA
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        claim_after = get_claim(claim["id"])
        assert claim_after["remittance_status"] == "AWAITING_REMITTANCE"
        assert claim_after["paid_amount_cents"] in (None, 0)

    def test_remittance_exceeds_charges_rejected(self, api):
        """PRD §3.6: "One money guard applies at posting: the resulting total
        of `POSTED` remittances may not exceed the claim's
        `total_billed_charges_cents`, else `ERR_REMITTANCE_EXCEEDS_CHARGES`."

        Design: Corner/errors/err_remittance_exceeds_charges_rejected
        """
        ctx = setup_priced_claim(
            rate_model="CASE_RATE",
            claim_overrides={
                "claim_number": "CL-RX1",
                "admission_date": "2026-06-01",
                "discharge_date": "2026-06-02",
                "total_billed_charges_cents": 50000,
            },
            lines=[{"charge_cents": 50000}],
        )
        # Expected is the 100000 case rate; posting 60000 against 50000 billed.
        assert ctx["claim"]["expected_reimbursement_cents"] == 100000
        resp = api.create_remittance(
            create_remittance_payload(ctx["claim"]["id"], paid_amount_cents=60000),
            RIA,
        )
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_EXCEEDS_CHARGES.value)
        claim_after = get_claim(ctx["claim"]["id"])
        assert claim_after["remittance_status"] == "AWAITING_REMITTANCE"


class TestVarianceEvaluation:
    def test_immediate_visibility_after_remittance(self, api):
        """PRD §3.6: "The first `POSTED` remittance lifts a claim from
        `AWAITING_REMITTANCE` to `REMITTANCE_POSTED`, but that state is a
        transient observation point: the same mutation immediately
        re-evaluates variance and lands the claim on `VARIANCE_FLAGGED` or
        `RECONCILED`." and "if no active case exists for the claim, one is
        created in `QUEUED` status with `original_variance_cents` set to the
        current variance, `queued_date` set to today".

        Design: Corner/consistency_model/cm_immediate_visibility_after_remittance
        """
        ctx = setup_priced_claim(claim_overrides={"claim_number": "CL-IM1"})
        remittance = validate_success(
            api.create_remittance(
                create_remittance_payload(ctx["claim"]["id"], paid_amount_cents=150000),
                RIA,
            ),
            expected_status=201,
        )
        assert remittance["status"] == "POSTED"
        # The very next read (no clock move) already shows the full cascade.
        claim_after = validate_success(api.get_claim(ctx["claim"]["id"], AUD))
        assert claim_after["paid_amount_cents"] == 150000
        assert claim_after["variance_cents"] == 50000
        assert claim_after["remittance_status"] == "VARIANCE_FLAGGED"
        case = get_single_case_for_claim(ctx["claim"]["id"], headers=AUD)
        assert case["status"] == "QUEUED"
        assert case["original_variance_cents"] == 50000

    def test_second_variance_event_restates_existing_case(self, api):
        """PRD §3.6: "if an active case already exists it is restated instead,
        its `original_variance_cents` overwritten with the current variance
        and its outstanding recomputed. At most one non-terminal case may
        exist per claim — `ERR_CASE_ALREADY_ACTIVE` guards the system creation
        paths, and manual case creation is not offered at all."

        Design: Corner/state_machines/sm_second_variance_event_restates_existing_case
        """
        ctx = setup_priced_claim(claim_overrides={"claim_number": "CL-SV1"})
        post_remittance(ctx["claim"]["id"], 100000)
        case = get_single_case_for_claim(ctx["claim"]["id"])
        assert case["original_variance_cents"] == 100000

        post_remittance(ctx["claim"]["id"], 10000)
        cases = list_cases_for_claim(ctx["claim"]["id"])
        assert len(cases) == 1, "A second variance event must not create a second case"
        assert cases[0]["id"] == case["id"]
        # Restated to the new variance: 200000 - 110000 = 90000.
        assert cases[0]["original_variance_cents"] == 90000
        assert cases[0]["status"] == "QUEUED"

    def test_contract_open_underpayment_derived_at_read(self, api):
        """PRD §3.1: "Each contract also exposes `open_underpayment_cents`, a
        read-time rollup that sums `current_outstanding_cents` across the
        contract's underpayment cases whose status is not `RECOVERED`,
        `DENIED_FINAL`, `WRITTEN_OFF`, or `WITHDRAWN`. The figure is derived
        on read, never stored, and its movement never increments the
        contract's `version`."

        Design: Corner/entities/ent_contract_open_underpayment_derived_at_read
        """
        ctx = setup_priced_claim(
            rate_model="CASE_RATE",
            base_rate_cents=200000,
            claim_overrides={
                "claim_number": "CL-OU1",
                "admission_date": "2026-06-01",
                "discharge_date": "2026-06-02",
                "total_billed_charges_cents": 300000,
            },
            lines=[{"charge_cents": 300000}],
        )
        version_before = get_contract(ctx["contract"]["id"])["version"]
        post_remittance(ctx["claim"]["id"], 150000)
        case = get_single_case_for_claim(ctx["claim"]["id"])
        assert case["current_outstanding_cents"] == 50000

        contract_after = validate_success(
            api.get_payer_contract(ctx["contract"]["id"], AUD)
        )
        assert contract_after["open_underpayment_cents"] == 50000
        assert contract_after["version"] == version_before, (
            "Derived-at-read rollup movement must not bump the contract version"
        )


class TestParallelClaimDimensions:
    """Pricing and remittance dimensions move independently (PRD §3.5/§3.6)."""

    def test_pricing_moves_without_touching_remittance_dimension(self, api):
        """PRD §3.5: "the two dimensions evolve independently from that point
        on." PRD §3.6: "`variance_cents` is `expected_reimbursement_cents`
        minus `paid_amount_cents`, null until the claim is priced."

        Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_evolve_independently
        """
        ctx = setup_priced_claim(claim_overrides={"claim_number": "CL-PD1"})
        priced = ctx["claim"]
        assert priced["pricing_status"] == "PRICED"
        assert priced["remittance_status"] == "AWAITING_REMITTANCE"

        post_remittance(ctx["claim"]["id"], 100000)
        after_remittance = get_claim(ctx["claim"]["id"])
        # Pricing dimension untouched by the remittance mutation...
        assert after_remittance["pricing_status"] == "PRICED"
        # ...while the remittance dimension landed on VARIANCE_FLAGGED
        # (variance 100000 >= default threshold 5000).
        assert after_remittance["remittance_status"] == "VARIANCE_FLAGGED"

    def test_remittance_dimension_survives_repricing(self, api):
        """PRD §3.5: "Repricing — whether invoked by a
        `RevenueIntegrityAnalyst` or fired by the amendment and escalator-void
        cascades — moves the claim from `PRICED` to `REPRICED`, or keeps an
        already-`REPRICED` claim there" and "Each reprice recomputes
        `variance_cents`, re-evaluates the remittance dimension — flips
        between `RECONCILED` and `VARIANCE_FLAGGED` are allowed".

        Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_evolve_independently
        """
        ctx = setup_priced_claim(claim_overrides={"claim_number": "CL-PD1"})
        post_remittance(ctx["claim"]["id"], 100000)
        repriced = validate_success(api.reprice_claim(ctx["claim"]["id"], RIA))
        assert repriced["pricing_status"] == "REPRICED"
        # Rate set unchanged, so the expected amount and the flagged
        # remittance dimension are unchanged by the pricing-dimension move.
        assert repriced["expected_reimbursement_cents"] == 200000
        assert repriced["remittance_status"] == "VARIANCE_FLAGGED"
        assert repriced["variance_cents"] == 100000


class TestVarianceThresholdBoundary:
    """threshold = max(abs floor, relative floor); inclusive >= (PRD §3.6)."""

    def _setup_boundary_claim(self, api):
        return setup_priced_claim(
            rate_model="CASE_RATE",
            base_rate_cents=200000,
            contract_overrides={
                "contract_code": "BV-2026",
                "underpayment_threshold_cents": 10000,
                "underpayment_threshold_bp": 100,
            },
            claim_overrides={
                "claim_number": "CL-BV1",
                "admission_date": "2026-06-01",
                "discharge_date": "2026-06-02",
                "total_billed_charges_cents": 300000,
            },
            lines=[{"charge_cents": 300000}],
        )

    def test_variance_exactly_at_threshold_queues_case(self, api):
        """PRD §3.6: "The queue threshold is the greater of two legs: the
        contract's absolute floor `underpayment_threshold_cents`, and the
        relative floor computed as `expected_reimbursement_cents` times
        `underpayment_threshold_bp` divided by 10000, rounded half up to whole
        cents." and "A variance that reaches or exceeds the threshold — the
        boundary is inclusive — is an underpayment".

        Design: Difficulty/boundary_precision_check/variance_exactly_at_threshold_queues_case
        """
        ctx = self._setup_boundary_claim(api)
        # threshold = max(10000, round(200000 * 0.01)) = 10000.
        post_remittance(ctx["claim"]["id"], 190000)
        claim = get_claim(ctx["claim"]["id"])
        assert claim["variance_cents"] == 10000, "200000 - 190000 == threshold"
        assert claim["remittance_status"] == "VARIANCE_FLAGGED"
        cases = list_cases_for_claim(ctx["claim"]["id"])
        assert len(cases) == 1
        assert cases[0]["original_variance_cents"] == 10000

    def test_variance_one_cent_below_threshold_reconciles(self, api):
        """PRD §3.6: "A variance that reaches or exceeds the threshold — the
        boundary is inclusive — is an underpayment; anything below it,
        including a negative overpayment variance, reconciles the claim with
        no case."

        Design: Difficulty/boundary_precision_check/variance_exactly_at_threshold_queues_case
        """
        ctx = self._setup_boundary_claim(api)
        post_remittance(ctx["claim"]["id"], 190001)
        claim = get_claim(ctx["claim"]["id"])
        assert claim["variance_cents"] == 9999, "one cent below the 10000 threshold"
        assert claim["remittance_status"] == "RECONCILED"
        assert list_cases_for_claim(ctx["claim"]["id"]) == []


class TestRemittanceReversalLedger:
    """paid + variance == expected over POSTED remittances only (PRD §3.6)."""

    def _setup_posted(self, api):
        ctx = setup_priced_claim(claim_overrides={"claim_number": "CL-CI2"})
        remittance = post_remittance(ctx["claim"]["id"], 150000)
        ctx["remittance"] = remittance
        return ctx

    def test_posting_balances_paid_plus_variance(self, api):
        """PRD §3.6: "`paid_amount_cents` sums `paid_amount_cents` over
        `POSTED` remittances only — reversed ones stop counting.
        `variance_cents` is `expected_reimbursement_cents` minus
        `paid_amount_cents`, null until the claim is priced."

        Design: Difficulty/compensating_invariant/remittance_post_then_reverse_restores_claim_paid_variance_ledger
        """
        ctx = self._setup_posted(api)
        claim = get_claim(ctx["claim"]["id"])
        assert claim["paid_amount_cents"] == 150000
        assert claim["variance_cents"] == 50000
        assert claim["remittance_status"] == "VARIANCE_FLAGGED"
        # Invariant: paid + variance == expected.
        assert claim["paid_amount_cents"] + claim["variance_cents"] == 200000
        case = get_single_case_for_claim(ctx["claim"]["id"])
        assert case["original_variance_cents"] == 50000

    def test_reversal_restores_full_exposure_and_awaiting_remittance(self, api):
        """PRD §3.6: "When every `POSTED` remittance has been reversed and
        none remain, the claim falls back to `AWAITING_REMITTANCE`; the
        active case is restated and, with variance recomputed against zero
        payments, its outstanding reflects the full expected amount."

        Design: Difficulty/compensating_invariant/remittance_post_then_reverse_restores_claim_paid_variance_ledger
        """
        ctx = self._setup_posted(api)
        reversed_remittance = validate_success(
            api.reverse_remittance(
                ctx["remittance"]["id"], make_finance_director_headers("fd-9")
            )
        )
        assert reversed_remittance["status"] == "REVERSED"

        claim = get_claim(ctx["claim"]["id"])
        assert claim["paid_amount_cents"] == 0
        assert claim["variance_cents"] == 200000
        assert claim["remittance_status"] == "AWAITING_REMITTANCE"
        # Invariant restored: 0 + 200000 == 200000.
        assert claim["paid_amount_cents"] + claim["variance_cents"] == 200000
        case = get_single_case_for_claim(ctx["claim"]["id"])
        assert case["original_variance_cents"] == 200000
        assert case["current_outstanding_cents"] == 200000
