"""Experience-rating projection (dual variants, tiers, surcharges, rounding),
charge-statement reconciliation, model supersession, and posture thresholds."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_employer,
    create_model,
    create_separation,
    create_state_rule,
    create_statement,
    create_claim,
    file_protest,
    finalize_model,
    get_employer,
    get_line_item,
    get_model,
    get_statement,
    get_success_data,
    post_line,
    review_protest,
    set_clock,
    setup_employer_with_late_strikes,
    sustain_protest,
    validate_error,
    validate_success,
)

RATER = TEST_USERS["rating_analyst_headers"]
AUDITOR = TEST_USERS["charge_auditor_headers"]


class TestRatingDualVariant:
    def test_reserve_vs_benefit_ratio_same_inputs_differ(self, api):
        """PRD §3.7: "Under the `RESERVE_RATIO` variant the ratio is the
        employer's `reserve_balance_cents` divided by its
        `taxable_payroll_cents`; a higher reserve yields a lower ratio and
        therefore a lower rate"
        PRD §3.7: "Under the `BENEFIT_RATIO` variant the ratio is the benefit
        charges divided by `taxable_payroll_cents`; here higher charges yield a
        higher ratio and a higher rate, the reverse direction, so identical
        inputs produce a different rate under the two variants."

        Design: Difficulty/dual_variant_calc/rating_reserve_vs_benefit_ratio
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        emp_r = create_employer(legal_name="ResCo",
                                merit_rating_method="RESERVE_RATIO",
                                reserve_balance_cents=50_000_000)
        emp_b = create_employer(legal_name="BenCo",
                                merit_rating_method="BENEFIT_RATIO")
        sep_b = create_separation(emp_b["id"], claimant_name="Sam",
                                  ssn_last4="2222")
        claim_b = create_claim(emp_b["id"], sep_b["id"],
                               max_benefit_cents=50_000_000)
        stmt_b = create_statement(emp_b["id"])
        post_line(stmt_b["id"], claim_b["id"], 30_000_000, benefit_weeks=20)

        model_r = create_model(emp_r["id"], variant="RESERVE_RATIO", kind="OFFICIAL")
        model_b = create_model(emp_b["id"], variant="BENEFIT_RATIO", kind="OFFICIAL")
        # Reserve ratio 50,000,000 / 1e9 = 0.05 -> tier (0.04, 0.06] -> 360.
        assert model_r["projected_rate_bps"] == 360
        # Benefit ratio 30,000,000 / 1e9 = 0.03 -> tier (0.02, 0.04] -> 270.
        assert model_b["projected_rate_bps"] == 270
        assert model_r["projected_rate_bps"] != model_b["projected_rate_bps"]

    def test_what_if_other_variant_computed_for_comparison(self, api):
        """PRD §3.7: "an `OFFICIAL` model's `variant` must match the employer's
        `merit_rating_method` (otherwise `ERR_MODEL_VARIANT_MISMATCH`), while
        the other variant remains computable as a `WHAT_IF` comparison"
        PRD §3.7: "First, benefit charges are summed: the amounts of every
        charge line on the employer's claims whose status is `PENDING` or
        `SUSTAINED` — `REVERSED` and `WAIVED` lines are excluded."

        Design: Difficulty/dual_variant_calc/rating_reserve_vs_benefit_ratio
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="CmpCo",
                                   merit_rating_method="RESERVE_RATIO",
                                   reserve_balance_cents=50_000_000)
        official = create_model(employer["id"], variant="RESERVE_RATIO",
                                kind="OFFICIAL")
        what_if = create_model(employer["id"], variant="BENEFIT_RATIO",
                               kind="WHAT_IF")
        assert official["projected_rate_bps"] == 360
        # No charge lines: benefit ratio 0.00 -> tier (-0.05, 0.00] -> 120.
        assert what_if["projected_rate_bps"] == 120


class TestTieredLookupSurchargeAndRounding:
    def test_tiered_rate_with_sanctioned_surcharge(self, api):
        """PRD §3.7: "Fourth, posture surcharges apply: a `SANCTIONED`
        employer adds 50 basis points, a `WATCH` employer adds 20, and a
        `CLEAR` employer adds nothing."
        PRD §2.10: "An effective count of at least four yields `SANCTIONED`"

        Design: Difficulty/combinatorial_formula/rating_tiered_lookup_with_posture_surcharge
        """
        employer = setup_employer_with_late_strikes(
            4, legal_name="TierCo", reserve_balance_cents=20_000_000)
        assert employer["late_response_strikes"] == 4
        assert employer["compliance_posture"] == "SANCTIONED"

        model = create_model(employer["id"], variant="RESERVE_RATIO",
                             kind="OFFICIAL")
        # Ratio 20,000,000 / 1e9 = 0.02 -> tier (0.00, 0.02] -> 180, + 50 = 230.
        assert model["projected_rate_bps"] == 230

    def test_tiered_rate_with_watch_surcharge(self, api):
        """PRD §3.7: "a `SANCTIONED` employer adds 50 basis points, a `WATCH`
        employer adds 20, and a `CLEAR` employer adds nothing."
        PRD §2.10: "an effective count of at least two but fewer than four
        yields `WATCH`"

        Design: Difficulty/combinatorial_formula/rating_tiered_lookup_with_posture_surcharge
        """
        employer = setup_employer_with_late_strikes(
            2, legal_name="WatchCo", reserve_balance_cents=20_000_000)
        assert employer["late_response_strikes"] == 2
        assert employer["compliance_posture"] == "WATCH"

        model = create_model(employer["id"], variant="RESERVE_RATIO",
                             kind="OFFICIAL")
        # 180 tier + 20 WATCH surcharge = 200.
        assert model["projected_rate_bps"] == 200

    def test_boundary_ratio_tiers_on_unrounded_ratio(self, api):
        """PRD §3.7: "the unrounded ratio selects a base rate from the rate
        table by taking the first row whose ceiling is greater than or equal to
        the ratio: a ratio at or below −0.05 maps to 60 basis points; above
        −0.05 and at or below 0.00, to 120; above 0.00 and at or below 0.02, to
        180"
        PRD §2.7: "the ratio is carried as an exact rational number and is
        never rounded before the tier lookup; the tiered rate is an integer
        number of basis points; and the projected liability is computed from
        that integer rate and then rounded down to a whole cent."

        Design: Difficulty/combinatorial_formula/rounding_order_liability_from_integer_rate
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="RoundCo",
                                   reserve_balance_cents=20_000_000)
        model = create_model(employer["id"], variant="RESERVE_RATIO",
                             kind="WHAT_IF")
        # Ratio exactly 0.02 lands in the 180 tier (not 270).
        assert model["projected_rate_bps"] == 180
        # floor(180 * 1,000,000,000 / 10,000) = 18,000,000.
        assert model["projected_liability_cents"] == 18_000_000

    def test_liability_floored_from_integer_rate(self, api):
        """PRD §3.7: "Sixth and last, `projected_liability_cents` is the
        integer projected rate multiplied by `taxable_payroll_cents`, divided
        by ten thousand, and rounded down to a whole cent. The rounding order
        is pinned: the ratio stays an exact rational through tiering, and only
        the final liability is rounded — down."

        Design: Difficulty/combinatorial_formula/rounding_order_liability_from_integer_rate
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="FloorCo",
                                   taxable_payroll_cents=99_999_999,
                                   reserve_balance_cents=1_999_999)
        model = create_model(employer["id"], variant="RESERVE_RATIO",
                             kind="WHAT_IF")
        # Ratio 1,999,999 / 99,999,999 ~= 0.01999999 <= 0.02 -> 180 tier.
        assert model["projected_rate_bps"] == 180
        # floor(180 * 99,999,999 / 10,000) = floor(1,799,999.982) = 1,799,999.
        assert model["projected_liability_cents"] == 1_799_999


class TestPostureThresholds:
    def test_exactly_two_strikes_is_watch(self, api):
        """PRD §2.10: "An effective count of at least four yields `SANCTIONED`;
        an effective count of at least two but fewer than four yields `WATCH`;
        anything lower yields `CLEAR`. Both boundaries are inclusive: exactly
        2.0 effective strikes is `WATCH`, and exactly 4.0 is `SANCTIONED`."

        Design: Difficulty/boundary_precision_check/posture_threshold_exactly_two_strikes_watch
        """
        employer = setup_employer_with_late_strikes(2, legal_name="PostCo")
        assert employer["late_response_strikes"] == 2
        assert employer["compliance_posture"] == "WATCH"

        summary = get_success_data(api.get_rating_summary(employer["id"], RATER))
        assert summary["late_response_strikes"] == 2
        assert summary["compliance_posture"] == "WATCH"

    def test_one_strike_remains_clear(self, api):
        """PRD §2.10: "an effective count of at least two but fewer than four
        yields `WATCH`; anything lower yields `CLEAR`."

        Design: Difficulty/boundary_precision_check/posture_threshold_exactly_two_strikes_watch
        """
        employer = setup_employer_with_late_strikes(1, legal_name="ClearCo")
        assert employer["late_response_strikes"] == 1
        assert employer["compliance_posture"] == "CLEAR"


class TestReconcileCascade:
    def _setup_sustained_protest_with_finalized_model(self, api):
        """Employer with a 500,000-cent DUPLICATE_LINE charge, a FINALIZED
        OFFICIAL model, and a sustained protest (line REVERSED)."""
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="CascCo")
        separation = create_separation(employer["id"], claimant_name="Ivy",
                                       ssn_last4="8001")
        claim = create_claim(employer["id"], separation["id"])
        statement = create_statement(employer["id"])
        line = post_line(statement["id"], claim["id"], 500_000, benefit_weeks=4,
                         erroneous_reason="DUPLICATE_LINE")
        assert get_employer(employer["id"])["reserve_balance_cents"] == -500_000
        model = create_model(employer["id"], variant="RESERVE_RATIO",
                             kind="OFFICIAL")
        finalize_model(employer["id"], model["id"])
        assert get_model(model["id"])["status"] == "FINALIZED"

        protest = file_protest(line["id"], statement["id"],
                               protest_basis="DUPLICATE_LINE")
        assert protest["evidence_strength"] == 65
        review_protest(protest["id"])
        sustain_protest(protest["id"])
        return {"employer": employer, "claim": claim, "statement": statement,
                "line": line, "model": model, "protest": protest}

    def test_sustain_reconcile_supersedes_model_chain(self, api):
        """PRD §3.6: "Reconciliation moves the statement to `RECONCILED` and
        credits the employer's `protest_credits_cents` by the sum of the
        amounts of its `REVERSED` lines — the audit-trail credit counter."
        PRD §3.6: "Finally, the employer's experience-rating models for the
        current model year move to `SUPERSEDED`, their derived inputs now
        stale, and are recomputed on next read."
        PRD §3.6: "Completing the audit requires that no line on the statement
        is still `PROTESTED` (otherwise `ERR_PROTESTS_IN_FLIGHT`)"

        Design: Difficulty/transitive_cascade/protest_sustain_reconcile_model_supersede_chain
        """
        ctx = self._setup_sustained_protest_with_finalized_model(api)
        assert get_line_item(ctx["line"]["id"])["status"] == "REVERSED"

        validate_success(api.complete_audit(ctx["statement"]["id"], AUDITOR), 200)
        reconciled = validate_success(
            api.reconcile_statement(ctx["statement"]["id"], AUDITOR), 200)
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["total_charged_cents"] == 0

        employer_after = get_employer(ctx["employer"]["id"])
        assert employer_after["protest_credits_cents"] == 500_000
        assert employer_after["reserve_balance_cents"] == 0
        assert get_model(ctx["model"]["id"])["status"] == "SUPERSEDED"

    def test_reconcile_performs_no_second_reserve_credit(self, api):
        """PRD §3.6: "It performs no additional reserve movement whatsoever:
        the reserve was already credited at each line's `REVERSED` transition,
        and a second credit is forbidden."

        Design: Difficulty/transitive_cascade/protest_sustain_reconcile_model_supersede_chain
        """
        ctx = self._setup_sustained_protest_with_finalized_model(api)
        # The reversal at sustain time already restored the reserve to 0.
        reserve_at_reversal = get_employer(ctx["employer"]["id"])["reserve_balance_cents"]
        assert reserve_at_reversal == 0

        validate_success(api.complete_audit(ctx["statement"]["id"], AUDITOR), 200)
        validate_success(api.reconcile_statement(ctx["statement"]["id"], AUDITOR), 200)

        employer_after = get_employer(ctx["employer"]["id"])
        assert employer_after["reserve_balance_cents"] == reserve_at_reversal
        assert employer_after["protest_credits_cents"] == 500_000


class TestModelFinalizeGuards:
    def test_official_model_finalize_wrong_variant_rejected(self, api):
        """PRD §3.7: "an `OFFICIAL` model's `variant` must match the employer's
        `merit_rating_method` (otherwise `ERR_MODEL_VARIANT_MISMATCH`), while
        the other variant remains computable as a `WHAT_IF` comparison"

        Design: Corner/endpoints/official_model_finalize_wrong_variant_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="VarModCo",
                                   merit_rating_method="RESERVE_RATIO")
        model = create_model(employer["id"], variant="BENEFIT_RATIO",
                             kind="OFFICIAL")
        version = get_employer(employer["id"])["version"]
        err = api.finalize_model(employer["id"], model["id"], version, RATER)
        validate_error(err, ApiErrorId.ERR_MODEL_VARIANT_MISMATCH, 422)
        assert get_model(model["id"])["status"] == "DRAFT"

    def test_what_if_model_finalize_ignores_variant_match(self, api):
        """PRD §3.7: "The model must be `DRAFT` (otherwise
        `ERR_MODEL_NOT_DRAFT`); an `OFFICIAL` model's `variant` must match the
        employer's `merit_rating_method` (otherwise
        `ERR_MODEL_VARIANT_MISMATCH`), while the other variant remains
        computable as a `WHAT_IF` comparison"
        PRD §3.7: "Finalization moves the model to `FINALIZED` and increments
        the employer's `version` by one."

        Design: Corner/endpoints/official_model_finalize_wrong_variant_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="WhatIfCo",
                                   merit_rating_method="RESERVE_RATIO")
        model = create_model(employer["id"], variant="BENEFIT_RATIO",
                             kind="WHAT_IF")
        finalized = finalize_model(employer["id"], model["id"])
        assert finalized["status"] == "FINALIZED"

    def test_occ_finalize_supersedes_prior_official(self, api):
        """PRD §2.9: "requires `expected_employer_version` carrying the client's
        last observed `version` of the parent employer account. Finalization
        supersedes the prior finalized official model for the same employer and
        year, so the server refuses to supersede on inputs the client has not
        observed."
        PRD §3.7: "Finalization moves the model to `FINALIZED` and increments
        the employer's `version` by one."

        Design: Corner/cross_cutting_layers/occ_finalize_supersedes_prior_official
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="Occ3Co")
        stale_version = get_employer(employer["id"])["version"]
        m1 = create_model(employer["id"], model_year=2027, kind="OFFICIAL")
        m2 = create_model(employer["id"], model_year=2027, kind="OFFICIAL")

        finalize_model(employer["id"], m1["id"])
        finalize_model(employer["id"], m2["id"])
        # Exactly one finalized official model per employer and year survives.
        assert get_model(m1["id"])["status"] == "SUPERSEDED"
        assert get_model(m2["id"])["status"] == "FINALIZED"

        m3 = create_model(employer["id"], model_year=2028, kind="OFFICIAL")
        err = api.finalize_model(employer["id"], m3["id"], stale_version, RATER)
        validate_error(err, ApiErrorId.ERR_STALE_VERSION, 412)
        assert get_model(m3["id"])["status"] == "DRAFT"
