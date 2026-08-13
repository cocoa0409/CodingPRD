"""Settlement computation: pinned money steps, creation/finalize gates, OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_beneficiary,
    add_participant,
    adjudicate,
    build_period_scenario,
    compute_benchmark,
    create_settlement_payload,
    current_period_version,
    finalize_settlement,
    ingest_claim,
    list_reviews,
    lock_period,
    make_actuary_headers,
    open_period,
    propose_settlement,
    reopen_settlement,
    report_score,
    review_score,
    run_alignment,
    setup_canonical_proposed_settlement,
    setup_lite_final_settlement,
    setup_lite_proposed_settlement,
    validate_error,
    validate_paginated,
    validate_success,
    void_claim,
    create_period,
)

ACTUARY = make_actuary_headers()


class TestSequestrationLevyBase:
    def test_sequestration_levy_computed_on_pre_sequestration_base(self, api):
        """PRD §3.6: "The sequestration levy is then computed on the
        **pre-sequestration** amount — never on the post-levy payment:
        `sequestration_levy_cents` is two percent of
        `shared_savings_pre_sequestration_cents`, rounded half-up".

        Design: Difficulty/combinatorial_formula/sequestration_levy_base_pre_not_post
        """
        ctx = setup_canonical_proposed_settlement(tax_id="ACO-SQ")
        settlement = ctx["settlement"]
        assert settlement["shared_savings_pre_sequestration_cents"] == 23524
        # levy base is the PRE-sequestration amount: round(0.02 x 23524) = 470
        assert settlement["sequestration_levy_cents"] == 470

    def test_net_shared_savings_is_pre_minus_levy(self, api):
        """PRD §3.6: "`net_shared_savings_cents` is the pre-sequestration amount
        minus the levy." and "`distributable_pool_cents` is the net shared
        savings when positive, else zero."

        Design: Difficulty/combinatorial_formula/sequestration_levy_base_pre_not_post
        """
        ctx = setup_canonical_proposed_settlement(tax_id="ACO-SQ2")
        settlement = ctx["settlement"]
        assert settlement["net_shared_savings_cents"] == 23054
        assert settlement["distributable_pool_cents"] == 23054


class TestMsrBoundaryAndSavingsCap:
    def test_gross_one_cent_below_msr_yields_zero_sharing(self, api):
        """PRD §3.6: "When gross is zero or positive, savings eligibility
        requires gross to be at least the MSR threshold — meeting the threshold
        exactly qualifies. An eligible settlement's
        `shared_savings_pre_sequestration_cents` is the smaller of two
        rounded-half-up quantities: gross multiplied by the track's base rate
        multiplied by the quality multiplier, and ten percent of B (the savings
        cap); an ineligible one is zero."

        Design: Difficulty/boundary_precision_check/msr_boundary_and_savings_cap_via_settlement
        """
        ctx = setup_canonical_proposed_settlement(tax_id="ACO-MSR",
                                                  bp_big_amount=1341671)
        settlement = ctx["settlement"]
        assert settlement["gross_savings_cents"] == 58809
        assert settlement["msr_threshold_cents"] == 58810
        assert settlement["shared_savings_pre_sequestration_cents"] == 0
        assert settlement["distributable_pool_cents"] == 0

    def test_savings_cap_clips_oversized_gross_after_void(self, api, claims_headers,
                                                          actuary_headers):
        """PRD §3.6: "An eligible settlement's
        `shared_savings_pre_sequestration_cents` is the smaller of two
        rounded-half-up quantities: gross multiplied by the track's base rate
        multiplied by the quality multiplier, and ten percent of B (the savings
        cap)".
        PRD §3.2: "Because voiding changes the expenditure basis, any settlement
        of the period still in `PROPOSED` is cascaded to `STALE` at the same
        time."

        Design: Difficulty/boundary_precision_check/msr_boundary_and_savings_cap_via_settlement
        """
        ctx = setup_canonical_proposed_settlement(tax_id="ACO-MSR2",
                                                  bp_big_amount=1341671)
        first = ctx["settlement"]
        big_claim = ctx["claims"][3]
        validate_success(api.void_claim(big_claim["id"], {"reason": "duplicate"},
                                        claims_headers), 200)
        stale = validate_success(api.get_settlement(first["id"], actuary_headers), 200)
        assert stale["status"] == "STALE"

        second = propose_settlement(ctx["period"]["id"])
        assert second["gross_savings_cents"] == 1400480
        # 0.40 x 1400480 = 560192, clipped by the 10% savings cap = 294048
        assert second["shared_savings_pre_sequestration_cents"] == 294048
        assert second["sequestration_levy_cents"] == 5881
        assert second["net_shared_savings_cents"] == 288167


class TestSettlementCreationGates:
    def test_unadjudicated_claims_block_settlement_create(self, api, claims_headers):
        """PRD §3.6: "no claim of the period may remain in `RECEIVED` (else
        `ERR_UNADJUDICATED_CLAIMS_EXIST`)".

        Design: Corner/validations/unadjudicated_claims_block_settlement_create
        """
        period = create_period(tax_id="ACO-V6")
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-V6", 1960, dual_eligible=True, disabled=True)
        open_period(period["id"])
        c1 = ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 20000,
                          "PART_B", participant_id=participant["id"])
        ingest_claim(period["id"], beneficiary["id"], "2026-03-01", 30000, "PART_A",
                     participant_id=participant["id"])  # stays RECEIVED
        adjudicate(c1["id"])
        run_alignment(period["id"])
        lock_period(period["id"])
        compute_benchmark(period["id"], variant="FINAL")
        report_score(period["id"], "M1", 3, 4, 10)
        review = api.list_quality_scores(ACTUARY,
                                         params={"agreement_period_id": period["id"]})
        for s in review.json()["data"]:
            review_score(s["id"], "VALIDATED")
        res = api.create_settlement(
            period["id"],
            create_settlement_payload(current_period_version(period["id"])),
            ACTUARY,
        )
        validate_error(res, ApiErrorId.ERR_UNADJUDICATED_CLAIMS_EXIST, expected_status=409)

    def test_settlement_create_without_final_benchmark_rejected(self, api):
        """PRD §3.6: "an `ACTIVE` benchmark of the `FINAL` variant must exist
        (else `ERR_NO_ACTIVE_BENCHMARK`)".

        Design: Corner/validations/settlement_create_without_final_benchmark_rejected
        """
        ctx = build_period_scenario(
            tax_id="ACO-V7",
            beneficiaries=({"medicare_id": "MBI-V7", "birth_year": 1980},),
            benchmark_variant=None,
            quality_scores=None,
        )
        res = api.create_settlement(
            ctx["period"]["id"],
            create_settlement_payload(current_period_version(ctx["period"]["id"])),
            ACTUARY,
        )
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_BENCHMARK, expected_status=409)

    def test_stale_version_on_settlement_create(self, api):
        """PRD §2.6: "Three creation endpoints guard against stale views of the
        agreement period: creating an alignment run, computing a benchmark, and
        computing a settlement. Each of these requests must carry
        `expected_agreement_period_version`, a non-optional integer carrying the
        client's last observed `version` of the target `AgreementPeriod`. If
        that value does not equal the period's current `version` — for example
        because another writer has since opened or locked the period, or has
        completed a run, benchmark, or settlement of their own — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_version_on_settlement_create
        """
        ctx = build_period_scenario(tax_id="ACO-X3", settlement=False)
        stale_version = current_period_version(ctx["period"]["id"])
        propose_settlement(ctx["period"]["id"])  # advances the period version
        res = api.create_settlement(
            ctx["period"]["id"], create_settlement_payload(stale_version), ACTUARY,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_settlement_create_while_final_exists_rejected(self, api):
        """PRD §3.6: "no settlement of the period may currently sit in `FINAL`
        or `SETTLED` (else `ERR_SETTLEMENT_ALREADY_FINAL`)".

        Design: Corner/errors/settlement_create_while_final_exists_rejected
        """
        ctx = setup_lite_final_settlement(tax_id="ACO-Z3")
        # Finalization pinned the ACTIVE FINAL benchmark to LOCKED (PRD §3.7), so
        # compute a fresh FINAL benchmark first; this leaves the ALREADY_FINAL
        # gate as the only settlement-creation prerequisite that can fail.
        compute_benchmark(ctx["period"]["id"], variant="FINAL")
        res = api.create_settlement(
            ctx["period"]["id"],
            create_settlement_payload(current_period_version(ctx["period"]["id"])),
            ACTUARY,
        )
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_ALREADY_FINAL, expected_status=409)


class TestFinalizeGates:
    def test_settlement_create_aggregates_validated_scores_only(self, api):
        """PRD §3.5: "The aggregate `quality_score` is the sum of `earned_points`
        across the period's `VALIDATED` scores divided by the sum of their
        `max_points`, rounded half-up to four decimal places".

        Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_unreviewed_quality_score
        """
        ctx = setup_canonical_proposed_settlement(
            tax_id="ACO-XD1",
            quality_scores=(("M1", 3, 4, 10), ("M2", 13, 20, 10)),
            validate_quality=False,
        )
        # Validate M1 only; leave M2 REPORTED.
        m1 = ctx["scores"][0]
        review_score(m1["id"], "VALIDATED")
        settlement = propose_settlement(ctx["period"]["id"])
        # aggregate over VALIDATED only: 7.50 / 10 = 0.7500
        assert settlement["quality_score_snapshot"] == pytest.approx(0.75)

    def test_finalize_rejected_while_score_reported(self, api, actuary_headers):
        """PRD §3.7: "every quality score of the period must be out of `REPORTED`
        and `REJECTED` (else `ERR_QUALITY_SCORES_INCOMPLETE`)".

        Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_unreviewed_quality_score
        """
        ctx = setup_canonical_proposed_settlement(
            tax_id="ACO-XD1B",
            quality_scores=(("M1", 3, 4, 10), ("M2", 13, 20, 10)),
            validate_quality=False,
        )
        review_score(ctx["scores"][0]["id"], "VALIDATED")
        settlement = propose_settlement(ctx["period"]["id"])
        res = api.finalize_settlement(settlement["id"], actuary_headers)
        validate_error(res, ApiErrorId.ERR_QUALITY_SCORES_INCOMPLETE, expected_status=409)
        after = validate_success(api.get_settlement(settlement["id"], actuary_headers), 200)
        assert after["status"] == "PROPOSED"

    def test_finalize_blocked_by_flagged_review(self, api, actuary_headers):
        """PRD §3.7: "no high-cost review of the period may remain `FLAGGED`
        (else `ERR_PENDING_REVIEWS_EXIST`)".

        Design: Corner/validations/finalize_blocked_by_flagged_review
        """
        ctx = build_period_scenario(
            tax_id="ACO-V16",
            claims=(
                {"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
                 "amount": 20000, "claim_type": "PART_B"},
                {"beneficiary": 0, "participant": 0, "service_date": "2026-03-01",
                 "amount": 6000000, "claim_type": "PART_A"},
                {"beneficiary": 0, "participant": 0, "service_date": "2026-04-01",
                 "amount": 4000000, "claim_type": "PART_A"},
            ),
            settlement=True,
        )
        reviews = list_reviews(beneficiary_id=ctx["beneficiaries"][0]["id"])
        assert len(reviews) == 1 and reviews[0]["status"] == "FLAGGED"
        res = api.finalize_settlement(ctx["settlement"]["id"], actuary_headers)
        validate_error(res, ApiErrorId.ERR_PENDING_REVIEWS_EXIST, expected_status=409)

    def test_finalize_on_final_settlement_rejected(self, api, actuary_headers):
        """PRD §3.7: "Calling it on a settlement in any other status is rejected
        with `ERR_SETTLEMENT_NOT_PROPOSED`."

        Design: Corner/errors/finalize_on_final_settlement_rejected
        """
        ctx = setup_lite_final_settlement(tax_id="ACO-Z2")
        assert ctx["settlement"]["status"] == "FINAL"
        res = api.finalize_settlement(ctx["settlement"]["id"], actuary_headers)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_NOT_PROPOSED, expected_status=409)

    def test_reopen_on_proposed_settlement_rejected(self, api, actuary_headers):
        """PRD §3.7: "The manual form requires the settlement to be `FINAL` —
        anything else draws `ERR_SETTLEMENT_NOT_FINAL`."

        Design: Corner/validations/reopen_on_proposed_settlement_rejected
        """
        ctx = setup_lite_proposed_settlement(tax_id="ACO-V14")
        res = api.reopen_settlement(ctx["settlement"]["id"], {"reason": "too early"},
                                    actuary_headers)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_NOT_FINAL, expected_status=409)


class TestReopenRefinalizeCycle:
    def _canonical_final_with_lines(self, tax_id):
        return build_period_scenario(
            tax_id=tax_id,
            participants=(("100000001", "PA", 5000), ("100000002", "PB", 3000),
                          ("100000003", "PC", 2000)),
            beneficiaries=(
                {"medicare_id": "MBI-SC-R", "birth_year": 1960,
                 "dual_eligible": True, "disabled": True},
                {"medicare_id": "MBI-SC-P", "birth_year": 1990},
            ),
            claims=(
                {"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
                 "amount": 20000, "claim_type": "PART_B"},
                {"beneficiary": 1, "participant": 0, "service_date": "2026-02-05",
                 "amount": 20000, "claim_type": "PART_B"},
                {"beneficiary": 0, "participant": 0, "service_date": "2026-03-01",
                 "amount": 1500000, "claim_type": "PART_A"},
                {"beneficiary": 1, "participant": 0, "service_date": "2026-03-02",
                 "amount": 1341670, "claim_type": "PART_A"},
            ),
            settlement=True, finalize=True, distribution=True,
        )

    def test_reopen_recomputes_and_voids_pending_lines(self, api, actuary_headers):
        """PRD §3.7: "Reopening moves the settlement to `REOPENED`, recomputes
        every computed money field against current inputs — the truncated
        expenditure, the `ACTIVE` `FINAL` benchmark, and the currently
        `VALIDATED` quality picture — and runs a compensation cascade: every
        distribution line in `PENDING` or `APPROVED` is voided".

        Design: Difficulty/non_linear_state_machine/settlement_final_reopen_refinalize_cycle
        """
        ctx = self._canonical_final_with_lines("ACO-SC")
        settlement_id = ctx["settlement"]["id"]
        reopened = reopen_settlement(settlement_id, reason="manual recheck")
        assert reopened["status"] == "REOPENED"
        assert reopened["distributable_pool_cents"] == 23054
        res = api.list_distribution_lines(actuary_headers,
                                          params={"settlement_id": settlement_id})
        lines, _meta = validate_paginated(res)
        assert len(lines) == 3
        assert all(line["status"] == "VOIDED" for line in lines)

    def test_refinalized_settlement_restores_final_with_same_pool(self, api,
                                                                  actuary_headers):
        """PRD §3.7: "Finalization, performed by a `SettlementActuary`, moves a
        settlement from `PROPOSED` — or from `REOPENED`, after an appeal-driven
        reopen — to `FINAL`."

        Design: Difficulty/non_linear_state_machine/settlement_final_reopen_refinalize_cycle
        """
        ctx = self._canonical_final_with_lines("ACO-SC2")
        settlement_id = ctx["settlement"]["id"]
        reopen_settlement(settlement_id, reason="manual recheck")
        refinalized = finalize_settlement(settlement_id)
        assert refinalized["status"] == "FINAL"
        assert refinalized["distributable_pool_cents"] == 23054
