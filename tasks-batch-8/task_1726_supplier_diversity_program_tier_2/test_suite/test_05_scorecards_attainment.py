"""Scorecards: accrual-vs-cash attribution, include_tier2 branching, boundary
coverage, revocation recompute, publication lock, and rating rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_publish_goal,
    create_approved_tier2_report,
    create_business_unit,
    create_supplier,
    create_supplier_with_verified_cert,
    generate_scorecard,
    generate_scorecard_payload,
    get_success_data,
    import_spend,
    open_audit_case,
    record_audit_outcome,
    submit_certification,
    tier2_line,
    validate_error,
    validate_success,
)

ADMIN1 = TEST_USERS["admin_1_headers"]
ANALYST1 = TEST_USERS["analyst_1_headers"]


class TestDualBasisAttribution:
    def _setup_accrual_cash_scenario(self, api):
        """BU with a PUBLISHED 50.00 PERCENT_OF_SPEND goal; one certified
        diverse supplier and one prime; three spend records whose accrual and
        cash dates fall in different quarters."""
        bu = create_business_unit(inclusion_min_diverse_bidders=1)
        create_and_publish_goal(bu, target_value=50.00, include_tier2=True)
        diverse, _cert = create_supplier_with_verified_cert(
            legal_name="Diverse Parts Co", tax_id="T-100",
            certificate_number="C-100")
        prime = create_supplier(legal_name="Prime Build Inc", tax_id="T-200",
                                kind="PRIME", contact_email="p@x.com")
        import_spend(diverse["id"], bu["id"], 100000,
                     transaction_date="2026-03-15", payment_date="2026-04-20")
        import_spend(diverse["id"], bu["id"], 200000,
                     transaction_date="2026-03-25", payment_date="2026-05-10")
        import_spend(prime["id"], bu["id"], 50000,
                     transaction_date="2026-02-01", payment_date="2026-02-15")
        return bu

    def test_spend_attribution_accrual_basis(self, api):
        """PRD §3.6: "the basis is `ACCRUAL` or `CASH`, is immutable after
        generation, and selects which spend-record date the pipeline reads —
        `transaction_date` under `ACCRUAL`, `payment_date` under `CASH`, so
        identical underlying records can produce different totals under the
        two bases."
        PRD §3.6: "Attribution first expands `reporting_period` into its
        inclusive calendar quarter range — Q1 is January 1 through March 31,
        Q2 April 1 through June 30, Q3 July 1 through September 30, Q4 October
        1 through December 31."

        Design: Difficulty/dual_variant_calc/spend_attribution_accrual_vs_cash_basis
        """
        bu = self._setup_accrual_cash_scenario(api)
        scorecard = generate_scorecard(bu["id"], reporting_period="2026-Q1",
                                       attribution_basis="ACCRUAL")
        assert scorecard["total_spend_cents"] == 350000, (
            "All three transaction dates fall inside 2026-Q1 under ACCRUAL"
        )
        assert scorecard["direct_diverse_spend_cents"] == 300000, (
            "The two diverse-supplier records are attributable; the prime "
            "record is not"
        )
        # actual_pct = round_half_up(100*300000/350000, 2) = 85.71;
        # attainment = round_half_up(100*85.71/50.00, 2) = 171.42.
        assert scorecard["attainment_pct"] == pytest.approx(171.42, abs=0.005)
        assert scorecard["rating"] == "EXCEEDS"

    def test_spend_attribution_cash_basis_diverges(self, api):
        """PRD §3.6: "the basis is `ACCRUAL` or `CASH`, is immutable after
        generation, and selects which spend-record date the pipeline reads —
        `transaction_date` under `ACCRUAL`, `payment_date` under `CASH`, so
        identical underlying records can produce different totals under the
        two bases."

        Design: Difficulty/dual_variant_calc/spend_attribution_accrual_vs_cash_basis
        """
        bu = self._setup_accrual_cash_scenario(api)
        accrual = generate_scorecard(bu["id"], reporting_period="2026-Q1",
                                     attribution_basis="ACCRUAL")
        cash = generate_scorecard(bu["id"], reporting_period="2026-Q1",
                                  attribution_basis="CASH")
        assert cash["total_spend_cents"] == 50000, (
            "Only the prime record's payment_date falls inside 2026-Q1"
        )
        assert cash["direct_diverse_spend_cents"] == 0
        assert cash["attainment_pct"] == pytest.approx(0.00, abs=0.005)
        assert cash["rating"] == "BELOW"
        divergence = (accrual["direct_diverse_spend_cents"]
                      - cash["direct_diverse_spend_cents"])
        assert divergence == 300000, (
            "Identical records, two bases: diverse totals differ by exactly "
            "300000 cents"
        )


class TestIncludeTier2Branching:
    def _setup_include_tier2_scenario(self, api):
        """Two BUs with identical spend and identical APPROVED tier-2 reports
        (filed by two distinct primes so the per-(prime, period) supersession
        invariant never interacts across the BUs); the PUBLISHED
        ABSOLUTE_AMOUNT 250000-cent goal includes tier-2 on BU-A and excludes
        it on BU-B."""
        bu_a = create_business_unit(name="Aero A", code="AERO-A",
                                    lead_user_id="lead-1")
        bu_b = create_business_unit(name="Aero B", code="AERO-B",
                                    lead_user_id="lead-2")
        create_and_publish_goal(bu_a, goal_type="ABSOLUTE_AMOUNT",
                                target_value=250000, include_tier2=True)
        create_and_publish_goal(bu_b, goal_type="ABSOLUTE_AMOUNT",
                                target_value=250000, include_tier2=False)
        diverse, _cert = create_supplier_with_verified_cert(
            legal_name="Diverse Parts Co", tax_id="T-100",
            certificate_number="C-100")
        prime_a = create_supplier(legal_name="Prime A", tax_id="T-PA",
                                  kind="PRIME", contact_email="a@x.com")
        prime_b = create_supplier(legal_name="Prime B", tax_id="T-PB",
                                  kind="PRIME", contact_email="b@x.com")
        import_spend(diverse["id"], bu_a["id"], 200000,
                     transaction_date="2026-02-10", payment_date="2026-02-10")
        import_spend(diverse["id"], bu_b["id"], 200000,
                     transaction_date="2026-02-10", payment_date="2026-02-10")
        create_approved_tier2_report(
            prime_a["id"], bu_a["id"], reporting_period="2026-Q1",
            lines=[tier2_line(diverse["id"], 100000, 100.00)])
        create_approved_tier2_report(
            prime_b["id"], bu_b["id"], reporting_period="2026-Q1",
            lines=[tier2_line(diverse["id"], 100000, 100.00)])
        return bu_a, bu_b

    def test_attainment_include_tier2_true_branch(self, api):
        """PRD §3.6: "the effective diverse spend is
        `direct_diverse_spend_cents` plus `tier2_diverse_spend_cents` when the
        goal's `include_tier2` is true, and `direct_diverse_spend_cents`
        alone when it is false."
        PRD §3.6: "For an `ABSOLUTE_AMOUNT` goal, `attainment_pct` is one
        hundred times the effective diverse spend divided by the goal's
        `target_value`, rounded half-up to 2 decimals."

        Design: Difficulty/combinatorial_formula/scorecard_attainment_include_tier2_branching
        """
        bu_a, _bu_b = self._setup_include_tier2_scenario(api)
        scorecard = generate_scorecard(bu_a["id"], reporting_period="2026-Q1",
                                       attribution_basis="ACCRUAL")
        assert scorecard["tier2_diverse_spend_cents"] == 100000
        # effective = 200000 + 100000 = 300000; 100*300000/250000 = 120.00.
        assert scorecard["attainment_pct"] == pytest.approx(120.00, abs=0.005)
        assert scorecard["rating"] == "EXCEEDS"

    def test_attainment_include_tier2_false_branch(self, api):
        """PRD §3.6: "the effective diverse spend is
        `direct_diverse_spend_cents` plus `tier2_diverse_spend_cents` when the
        goal's `include_tier2` is true, and `direct_diverse_spend_cents`
        alone when it is false."
        PRD §3.6: "The tier-2 roll-up then sets `tier2_diverse_spend_cents`
        to the sum of `total_diverse_tier2_cents` over reports for this
        business unit and reporting period that are currently `APPROVED`."

        Design: Difficulty/combinatorial_formula/scorecard_attainment_include_tier2_branching
        """
        bu_a, bu_b = self._setup_include_tier2_scenario(api)
        scorecard_a = generate_scorecard(bu_a["id"], reporting_period="2026-Q1",
                                         attribution_basis="ACCRUAL")
        scorecard_b = generate_scorecard(bu_b["id"], reporting_period="2026-Q1",
                                         attribution_basis="ACCRUAL")
        assert scorecard_b["tier2_diverse_spend_cents"] == 100000, (
            "The roll-up runs regardless of the goal's include_tier2 flag"
        )
        # effective = 200000 alone; 100*200000/250000 = 80.00.
        assert scorecard_b["attainment_pct"] == pytest.approx(80.00, abs=0.005)
        assert scorecard_b["rating"] == "NEAR"
        assert (scorecard_a["attainment_pct"] - scorecard_b["attainment_pct"]
                ) == pytest.approx(40.00, abs=0.005), (
            "Only the include_tier2 branch differs between the two scorecards"
        )


class TestWindowBoundaryAttribution:
    def _setup_boundary_scenario(self, api):
        """Diverse supplier certified for [2026-10-01, 2026-11-15]; one spend
        record on the boundary day 2026-11-15 and one on 2026-11-16, both
        inside 2026-Q4. No program goal exists."""
        bu = create_business_unit()
        diverse, _cert = create_supplier_with_verified_cert(
            legal_name="Boundary Co", tax_id="T-BND", certificate_number="M-BND",
            valid_from="2026-10-01", valid_to="2026-11-15")
        import_spend(diverse["id"], bu["id"], 100000,
                     transaction_date="2026-11-15", payment_date="2026-11-15")
        import_spend(diverse["id"], bu["id"], 50000,
                     transaction_date="2026-11-16", payment_date="2026-11-16")
        return bu

    def test_certification_window_boundary_day_included(self, api):
        """PRD §3.6: "A record in the input set is diverse-attributable
        exactly when there exists a certification for the record's supplier
        whose status is `VERIFIED` or `EXPIRED` — never `REVOKED`, and never
        a pre-verification status — and whose closed validity window covers
        the record's basis date, boundary days included."

        Design: Difficulty/boundary_precision_check/certification_window_inclusive_end_boundary
        """
        bu = self._setup_boundary_scenario(api)
        scorecard = generate_scorecard(bu["id"], reporting_period="2026-Q4",
                                       attribution_basis="ACCRUAL")
        assert scorecard["total_spend_cents"] == 150000, (
            "Both records fall inside 2026-Q4"
        )
        assert scorecard["direct_diverse_spend_cents"] == 100000, (
            "The 2026-11-15 record is covered (closed window includes "
            "valid_to); the 2026-11-16 record is not"
        )
        assert scorecard["spend_by_category"] == {"MBE": 100000}

    def test_no_goal_rating_and_null_attainment(self, api):
        """PRD §3.6: "When no such goal exists, `attainment_pct` is null,
        `rating` is `NO_GOAL`, and `goal_id` is null."

        Design: Difficulty/boundary_precision_check/certification_window_inclusive_end_boundary
        """
        bu = self._setup_boundary_scenario(api)
        scorecard = generate_scorecard(bu["id"], reporting_period="2026-Q4",
                                       attribution_basis="ACCRUAL")
        assert scorecard["rating"] == "NO_GOAL"
        assert scorecard.get("attainment_pct") is None
        assert scorecard.get("goal_id") is None


class TestCertificationStateDependency:
    def _setup_revocation_scenario(self, api):
        """Certified supplier + 100000 POSTED spend in Q1 + a GENERATED
        scorecard, then a FAILED audit revoking the certification."""
        bu = create_business_unit()
        supplier, cert = create_supplier_with_verified_cert(
            legal_name="Self Cert Co", tax_id="T-SCC", cert_type="SELF_CERT",
            certificate_number="SC-1")
        import_spend(supplier["id"], bu["id"], 100000,
                     transaction_date="2026-02-05", payment_date="2026-02-05")
        scorecard = generate_scorecard(bu["id"], reporting_period="2026-Q1",
                                       attribution_basis="ACCRUAL")
        assert scorecard["direct_diverse_spend_cents"] == 100000, (
            "Attributable while the certification is VERIFIED"
        )
        case = open_audit_case(supplier["id"], cert["id"],
                               reason="DATA_QUALITY_FLAG")
        record_audit_outcome(case["id"], "FAILED")
        return bu, scorecard

    def test_scorecard_snapshot_not_mutated_by_revocation(self, api):
        """PRD §3.6: "A scorecard is a point-in-time snapshot of one business
        unit for one quarter."
        PRD §3.6: "A `GENERATED` scorecard can be recomputed from current
        underlying data; recompute refreshes every computed field under the
        scorecard's stored `attribution_basis` and bumps the scorecard's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/scorecard_attribution_depends_on_certification_state
        """
        _bu, scorecard = self._setup_revocation_scenario(api)
        stored = validate_success(api.get_scorecard(scorecard["id"], ADMIN1))
        assert stored["direct_diverse_spend_cents"] == 100000, (
            "The generated snapshot keeps its figure after the FAILED audit "
            "cascade"
        )

    def test_scorecard_recompute_after_revocation_excludes_revoked(self, api):
        """PRD §3.6: "A record in the input set is diverse-attributable
        exactly when there exists a certification for the record's supplier
        whose status is `VERIFIED` or `EXPIRED` — never `REVOKED`, and never
        a pre-verification status — and whose closed validity window covers
        the record's basis date, boundary days included."

        Design: Difficulty/cross_entity_state_dependency/scorecard_attribution_depends_on_certification_state
        """
        _bu, scorecard = self._setup_revocation_scenario(api)
        recomputed = validate_success(
            api.recompute_scorecard(scorecard["id"], ANALYST1))
        assert recomputed["direct_diverse_spend_cents"] == 0, (
            "REVOKED certifications never qualify after recompute"
        )
        assert recomputed["total_spend_cents"] == 100000, (
            "Revocation does not change total spend"
        )


class TestScorecardRules:
    def test_multiple_covering_certifications_latest_valid_from_wins(
            self, api):
        """PRD §3.6: "when more than one certification covers the same record,
        the amount is attributed to the certification whose `valid_from` is
        latest, with ties on `valid_from` broken by the certification's
        `created_at` ascending, and only categories with a positive amount
        appear in the map."

        Design: Corner/calculations/multiple_covering_certifications_latest_valid_from_wins
        """
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Multi Cert Co", tax_id="T-MUL")
        c1 = submit_certification(supplier["id"], cert_type="MBE",
                                  certificate_number="M-MUL",
                                  valid_from="2026-01-01",
                                  valid_to="2026-12-31")
        get_success_data(api.begin_review_certification(c1["id"], ANALYST1))
        get_success_data(api.verify_certification(c1["id"], ADMIN1))
        # Different cert_type: the same-type overlap guard does not apply.
        c2 = submit_certification(supplier["id"], cert_type="WBE",
                                  certificate_number="W-MUL",
                                  valid_from="2026-06-01",
                                  valid_to="2026-12-31")
        get_success_data(api.begin_review_certification(c2["id"], ANALYST1))
        get_success_data(api.verify_certification(c2["id"], ADMIN1))
        import_spend(supplier["id"], bu["id"], 60000,
                     transaction_date="2026-08-10", payment_date="2026-08-10")
        scorecard = generate_scorecard(bu["id"], reporting_period="2026-Q3",
                                       attribution_basis="ACCRUAL")
        assert scorecard["direct_diverse_spend_cents"] == 60000
        assert scorecard["spend_by_category"] == {"WBE": 60000}, (
            "The later valid_from (2026-06-01) wins the category attribution"
        )

    def test_scorecard_recompute_after_publish_locked(self, api):
        """PRD §3.6: "Publishing moves a `GENERATED` scorecard to `PUBLISHED`,
        locking the snapshot: recompute on a `PUBLISHED` scorecard is rejected
        with `ERR_SCORECARD_LOCKED`."

        Design: Corner/state_machines/scorecard_recompute_after_publish_locked
        """
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Plain Co", tax_id="T-PLN",
                                   kind="PRIME", contact_email="p@x.com")
        import_spend(supplier["id"], bu["id"], 50000,
                     transaction_date="2026-02-01", payment_date="2026-02-01")
        scorecard = generate_scorecard(bu["id"], reporting_period="2026-Q1",
                                       attribution_basis="ACCRUAL")
        assert scorecard["total_spend_cents"] == 50000
        published = validate_success(
            api.publish_scorecard(scorecard["id"], ADMIN1))
        assert published["status"] == "PUBLISHED"
        resp = api.recompute_scorecard(scorecard["id"], ANALYST1)
        validate_error(resp, ApiErrorId.ERR_SCORECARD_LOCKED)
        stored = validate_success(api.get_scorecard(scorecard["id"], ADMIN1))
        assert stored["total_spend_cents"] == 50000, (
            "The locked snapshot's stored figures do not change"
        )

    def test_scorecard_invalid_period_returns_invalid_request(self, api):
        """PRD §3.4: "The `reporting_period` is a quarter label in the shape
        `YYYY-Qn` with the quarter digit between 1 and 4; a malformed period
        is `ERR_INVALID_REQUEST`."
        PRD §3.6: "Attribution first expands `reporting_period` into its
        inclusive calendar quarter range — Q1 is January 1 through March 31,
        Q2 April 1 through June 30, Q3 July 1 through September 30, Q4 October
        1 through December 31."

        Design: Corner/validations/scorecard_invalid_period_returns_invalid_request
        """
        bu = create_business_unit()
        resp = api.generate_scorecard(
            bu["id"],
            generate_scorecard_payload(reporting_period="2026-Q5",
                                       attribution_basis="ACCRUAL"),
            ANALYST1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
