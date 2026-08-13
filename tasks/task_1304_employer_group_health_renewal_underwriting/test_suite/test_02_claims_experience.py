"""Claims experience: intake, submission gates, review, rating cascade."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    create_broker,
    create_case_in_claims_pending,
    create_case_in_rating,
    add_claims_record,
    submit_claims_record,
    create_claims_payload,
    make_underwriter_headers,
    make_senior_underwriter_headers,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]
SU = TEST_USERS["senior_underwriter_headers"]


class TestClaimsSubmission:
    def test_claims_submit_computes_period_fields(self):
        """PRD section 3.3: "On successful submission three derived values are
        computed: `months_of_experience` as the count of whole months between start
        and end inclusive; `pooled_claims_cents` as the portion of paid claims
        sitting above the pooling threshold; and `experience_claim_cost_cents` as
        the net claim cost feeding experience rating, namely
        `total_paid_claims_cents` with `pooled_claims_cents` removed."

        Design: Corner/entities/claims_submit_computes_period_fields
        """
        broker = create_broker()
        case, _ = create_case_in_claims_pending(broker["id"])
        claims = add_claims_record(case["id"])
        data = submit_claims_record(claims["id"])
        assert data["status"] == "SUBMITTED"
        assert data["months_of_experience"] == 24
        assert data["pooled_claims_cents"] == 0
        assert data["experience_claim_cost_cents"] == 38400000

    def test_claims_invalid_period_order(self):
        """PRD section 3.3: "the period end must fall strictly after the period
        start (else `ERR_INVALID_EXPERIENCE_PERIOD`, HTTP 400)".

        Design: Corner/validations/claims_invalid_period_order
        """
        broker = create_broker()
        case, _ = create_case_in_claims_pending(broker["id"])
        claims = add_claims_record(
            case["id"],
            experience_period_start="2025-01-01T00:00:00Z",
            experience_period_end="2024-06-30T00:00:00Z",
        )
        resp = api_client.submit_claims(
            claims["id"], make_underwriter_headers("uw-001")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_EXPERIENCE_PERIOD)
        claims = get_success_data(api_client.get_claims_experience(claims["id"], UW))
        assert claims["status"] == "PENDING"

    def test_submit_claims_twice_fails(self):
        """PRD section 3.3: "it must still be `PENDING` (else
        `ERR_CLAIMS_NOT_PENDING`)".

        Design: Corner/validations/submit_claims_twice_fails
        """
        broker = create_broker()
        case, _ = create_case_in_claims_pending(broker["id"])
        claims = add_claims_record(case["id"])
        submit_claims_record(claims["id"])
        resp = api_client.submit_claims(
            claims["id"], make_underwriter_headers("uw-001")
        )
        validate_error(resp, ApiErrorId.ERR_CLAIMS_NOT_PENDING)
        claims = get_success_data(api_client.get_claims_experience(claims["id"], UW))
        assert claims["status"] == "SUBMITTED"

    def test_review_pending_claims_fails(self):
        """PRD section 3.3: "the record must also be in `SUBMITTED` (else
        `ERR_CLAIMS_NOT_SUBMITTED`)".

        Design: Corner/validations/review_pending_claims_fails
        """
        broker = create_broker()
        case, _ = create_case_in_claims_pending(broker["id"])
        claims = add_claims_record(case["id"])
        resp = api_client.review_claims(
            claims["id"], make_senior_underwriter_headers("su-001")
        )
        validate_error(resp, ApiErrorId.ERR_CLAIMS_NOT_SUBMITTED)
        claims = get_success_data(api_client.get_claims_experience(claims["id"], UW))
        assert claims["status"] == "PENDING"

    def test_claims_review_by_submitter_forbidden(self):
        """PRD section 3.3: "the desk enforces segregation of duties: the reviewer
        must not be the same user who submitted the record, or the review is
        refused with `ERR_SAME_REVIEWER_AS_SUBMITTER` (HTTP 403)".

        Design: Corner/validations/claims_review_by_submitter_forbidden
        """
        broker = create_broker()
        case, _ = create_case_in_claims_pending(broker["id"])
        claims = add_claims_record(case["id"])
        submit_claims_record(claims["id"])  # submitted by uw-001
        resp = api_client.review_claims(
            claims["id"], make_senior_underwriter_headers("uw-001")
        )
        validate_error(resp, ApiErrorId.ERR_SAME_REVIEWER_AS_SUBMITTER)
        ok = api_client.review_claims(
            claims["id"], make_senior_underwriter_headers("su-001")
        )
        data = validate_success(ok)
        assert data["status"] == "REVIEWED"


class TestClaimsPeriodBoundaries:
    def test_claims_period_inclusive_month_span_short_rejected(self):
        """PRD section 3.3: "the experience must span at least twelve whole months
        (else `ERR_INSUFFICIENT_EXPERIENCE_MONTHS`)".

        Design: Difficulty/resource_temporal_overlap/claims_period_inclusive_month_span
        """
        broker = create_broker()
        case, _ = create_case_in_claims_pending(broker["id"])
        short = add_claims_record(
            case["id"],
            experience_period_start="2024-01-01T00:00:00Z",
            experience_period_end="2024-11-30T00:00:00Z",
            total_paid_claims_cents=17600000,
            total_enrollment_months=4400,
        )
        resp = api_client.submit_claims(
            short["id"], make_underwriter_headers("uw-001")
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_EXPERIENCE_MONTHS)
        short = get_success_data(api_client.get_claims_experience(short["id"], UW))
        assert short["status"] == "PENDING"

    def test_claims_period_inclusive_month_span_exact_accepted(self):
        """PRD section 3.3: "the experience must span at least twelve whole months
        (else `ERR_INSUFFICIENT_EXPERIENCE_MONTHS`)" and "`months_of_experience`
        as the count of whole months between start and end inclusive".

        Design: Difficulty/resource_temporal_overlap/claims_period_inclusive_month_span
        """
        broker = create_broker()
        case, _ = create_case_in_claims_pending(broker["id"])
        exact = add_claims_record(
            case["id"],
            experience_period_start="2024-01-01T00:00:00Z",
            experience_period_end="2024-12-31T00:00:00Z",
            total_paid_claims_cents=19200000,
            total_enrollment_months=4800,
        )
        resp = api_client.submit_claims(
            exact["id"], make_underwriter_headers("uw-001")
        )
        data = validate_success(resp)
        assert data["status"] == "SUBMITTED"
        assert data["months_of_experience"] == 12


class TestGroupSizeGate:
    def test_group_size_25_passes_experience_gate(self):
        """PRD section 3.3: "requesting claims data requires the case to be in
        `CENSUS_RECEIVED` (else `ERR_CASE_NOT_IN_CENSUS_RECEIVED`) and requires
        `group_size` of at least 25 (else `ERR_GROUP_TOO_SMALL_EXPERIENCE`).
        Success moves the case to `CLAIMS_PENDING`."

        Design: Difficulty/boundary_precision_check/group_size_25_experience_rating_gate
        """
        broker = create_broker()
        from test_helpers import create_case_in_census_received
        case25, _ = create_case_in_census_received(
            broker["id"],
            census_overrides={
                "total_employees": 25,
                "enrolled_employees": 20,
                "dependent_count": 8,
                "tier_distribution": {"EE": 20, "ES": 0, "EC": 0, "EF": 0},
            },
            group_size=25,
            current_premium_annual=1200000,
        )
        resp = api_client.request_claims(case25["id"], UW)
        data = validate_success(resp)
        assert data["status"] == "CLAIMS_PENDING"

    def test_group_size_24_fails_experience_gate(self):
        """PRD section 3.3: "requires `group_size` of at least 25 (else
        `ERR_GROUP_TOO_SMALL_EXPERIENCE`)".

        Design: Difficulty/boundary_precision_check/group_size_25_experience_rating_gate
        """
        broker = create_broker()
        from test_helpers import create_case_in_census_received
        case24, _ = create_case_in_census_received(
            broker["id"],
            census_overrides={
                "total_employees": 24,
                "enrolled_employees": 20,
                "dependent_count": 8,
                "tier_distribution": {"EE": 20, "ES": 0, "EC": 0, "EF": 0},
            },
            group_size=24,
            current_premium_annual=1152000,
        )
        resp = api_client.request_claims(case24["id"], UW)
        validate_error(resp, ApiErrorId.ERR_GROUP_TOO_SMALL_EXPERIENCE)
        case24 = get_success_data(api_client.get_case(case24["id"], UW))
        assert case24["status"] == "CENSUS_RECEIVED"


class TestClaimsReviewCascade:
    def test_claims_review_cascades_case_rating_recompute(self):
        """PRD section 3.3: "A successful review moves the record to
        `REVIEWED`, computes the `completion_ratio` — the IBNR completion
        factor, an exact two-decimal lookup by months of experience: 1.00 at 24
        months or more, 0.98 from 18 up to but not including 24 months, 0.95
        from 12 up to but not including 18 months, and 0.85 below 12 months (a
        period that short would already have been refused at submission) — and,
        if the parent case is sitting in `CLAIMS_PENDING`, advances it
        automatically to `RATING_IN_PROGRESS`."
        PRD section 3.3: "The result, rounded half-up to whole cents, becomes
        the case's `experience_rate_cents`."

        Design: Difficulty/transitive_cascade/claims_review_cascades_case_rating_recompute
        """
        broker = create_broker()
        case, _ = create_case_in_claims_pending(broker["id"])
        claims = add_claims_record(case["id"])
        submit_claims_record(claims["id"])
        reviewed = validate_success(
            api_client.review_claims(
                claims["id"], make_senior_underwriter_headers("su-001")
            )
        )
        assert reviewed["status"] == "REVIEWED"
        assert reviewed["completion_ratio"] == pytest.approx(1.0, abs=1e-9)
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "RATING_IN_PROGRESS"
        assert case["experience_rate_cents"] == 5338
        assert case["credibility_factor"] == pytest.approx(1.0, abs=1e-9)
        assert case["blended_rate_cents"] == 5338
        assert case["is_rate_cap_applied"] is False

    def test_claims_review_leaves_case_fields_consistent_on_reread(self):
        """PRD section 3.3: "With both pillars present the **blended rate** is a
        credibility-weighted average: the credibility factor times
        `experience_rate_cents` plus one-minus-the-credibility-factor times
        `manual_rate_cents`."

        Design: Difficulty/transitive_cascade/claims_review_cascades_case_rating_recompute
        """
        broker = create_broker()
        case, claims = create_case_in_rating(broker["id"])
        reread = get_success_data(api_client.get_case(case["id"], UW))
        assert reread["experience_rate_cents"] == 5338
        assert reread["blended_rate_cents"] == 5338
        assert reread["status"] == "RATING_IN_PROGRESS"
        claims_reread = get_success_data(
            api_client.get_claims_experience(claims["id"], UW)
        )
        assert claims_reread["status"] == "REVIEWED"
        assert claims_reread["completion_ratio"] == pytest.approx(1.0, abs=1e-9)


class TestConservativeMarginLoad:
    def test_experience_rate_base_variant_at_full_credibility(self):
        """PRD section 3.3: "When a `SeniorUnderwriter` reviewing the file judges
        the experience thin and the credibility factor is below 0.5, a
        conservative variant applies: a ten percent margin load multiplies the
        experience rate by 1.10 before rounding."

        Design: Difficulty/dual_variant_calc/claims_experience_conservative_margin_load
        """
        broker = create_broker()
        # group 500 -> credibility 1.0 (>= 0.5): no margin load
        case, _claims = create_case_in_rating(broker["id"], group_size=500)
        assert case["credibility_factor"] == pytest.approx(1.0, abs=1e-9)
        assert case["experience_rate_cents"] == 5338

    def test_experience_rate_conservative_variant_below_half_credibility(self):
        """PRD section 3.3: "When a `SeniorUnderwriter` reviewing the file judges
        the experience thin and the credibility factor is below 0.5, a
        conservative variant applies: a ten percent margin load multiplies the
        experience rate by 1.10 before rounding."

        Design: Difficulty/dual_variant_calc/claims_experience_conservative_margin_load
        """
        broker = create_broker()
        # group 100 -> credibility 0.2 (< 0.5): margin load applies.
        case, _claims = create_case_in_rating(
            broker["id"],
            claims_overrides={
                "total_paid_claims_cents": 7680000,
                "total_enrollment_months": 1920,
            },
            census_overrides={
                "total_employees": 100,
                "enrolled_employees": 80,
                "dependent_count": 40,
                "tier_distribution": {"EE": 40, "ES": 16, "EC": 12, "EF": 12},
            },
            group_size=100,
        )
        assert case["credibility_factor"] == pytest.approx(0.2, abs=1e-9)
        assert case["experience_rate_cents"] == 5871


class TestCompletionRatioTiers:
    def test_completion_ratio_at_18_months(self):
        """PRD section 3.3: "the `completion_ratio` — the IBNR completion factor,
        an exact two-decimal lookup by months of experience: 1.00 at 24 months or
        more, 0.98 from 18 up to but not including 24 months".

        Design: Corner/calculations/completion_ratio_tier_lookup_at_18_months
        """
        broker = create_broker()
        case, claims = create_case_in_rating(
            broker["id"],
            claims_overrides={
                "experience_period_start": "2024-01-01T00:00:00Z",
                "experience_period_end": "2025-06-30T00:00:00Z",
                "total_paid_claims_cents": 28800000,
                "total_enrollment_months": 7200,
            },
        )
        claims = get_success_data(api_client.get_claims_experience(claims["id"], UW))
        assert claims["completion_ratio"] == pytest.approx(0.98, abs=1e-9)
        assert claims["months_of_experience"] == 18
        assert case["experience_rate_cents"] == 5446
        assert case["credibility_factor"] == pytest.approx(0.75, abs=1e-9)


class TestDerivedFieldReconciliation:
    def test_case_derived_fields_reconciled_after_review(self):
        """PRD section 3.2: "at census-validation time no claims experience exists
        yet, so the months factor contributes nothing and the credibility reflects
        size alone until claims arrive."
        PRD section 3.3: "The credibility factor itself is re-derived at this
        point blending census size with claims months as described in §3.2."

        Design: Corner/complexity_layers/case_derived_fields_reconciled_after_review
        """
        from test_helpers import (
            create_case_in_census_received,
            review_claims_record,
        )
        broker = create_broker()
        case, _census = create_case_in_census_received(
            broker["id"],
            census_overrides={
                "total_employees": 100,
                "enrolled_employees": 80,
                "dependent_count": 40,
                "tier_distribution": {"EE": 40, "ES": 16, "EC": 12, "EF": 12},
            },
            group_size=100,
        )
        assert case["credibility_factor"] == pytest.approx(0.2, abs=1e-9)
        assert case["experience_rate_cents"] == 0
        resp = api_client.request_claims(case["id"], UW)
        validate_success(resp)
        claims = add_claims_record(
            case["id"],
            total_paid_claims_cents=7680000,
            total_enrollment_months=1920,
        )
        submit_claims_record(claims["id"])
        review_claims_record(claims["id"])
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["experience_rate_cents"] == 5871
        assert case["credibility_factor"] == pytest.approx(0.2, abs=1e-9)
        assert case["status"] == "RATING_IN_PROGRESS"
