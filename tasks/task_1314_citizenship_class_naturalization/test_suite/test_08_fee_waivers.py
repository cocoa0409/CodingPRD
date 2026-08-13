"""Fee waiver requests: provisional assessment and verified decision (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_fee_waiver_request,
    create_approved_fee_waiver,
    create_fee_waiver,
    create_program,
    create_screened_applicant,
    decide_fee_waiver,
    get_fee_waiver,
    submit_fee_waiver,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["intake_coordinator_headers"]


class TestProvisionalTier:
    def test_fee_waiver_provisional_vs_verified_tier(self, api):
        """PRD §3.7: "The first derived value is the `provisional_tier`, an advisory
        assessment that never gates money."
        PRD §3.7: "The verified tier runs the identical formula as the provisional
        one, but over the documented values."
        PRD §3.7: "On approval the request stores the verified tier as `final_tier`
        and records the deciding operator's `X-User-ID` in `decided_by`."

        Design: Difficulty/dual_variant_calc/fee_waiver_provisional_vs_verified_tier
        """
        create_program()
        applicant, _ = create_screened_applicant()
        # Self-reported income 2,000,000 cents: 2000000*100 <= 1565000*150, so the
        # provisional tier is FULL.
        request = create_fee_waiver(applicant["id"], household_size=1,
                                    self_reported_income_cents=2000000)
        assert_fee_waiver_request(request)
        assert request["provisional_tier"] == "FULL"
        assert request["status"] == "DRAFT"
        assert request["final_tier"] is None

        submit_fee_waiver(request["id"], 2)
        # Documented income 2,600,000 cents: above the 150% cap but within the 200%
        # cap, so the verified tier is PARTIAL — the same formula over different
        # inputs diverges on the same request row.
        decided = decide_fee_waiver(request["id"], "APPROVED", 2600000, False)
        assert decided["status"] == "APPROVED"
        assert decided["provisional_tier"] == "FULL"
        assert decided["final_tier"] == "PARTIAL"
        assert decided["provisional_tier"] != decided["final_tier"]
        assert decided["decided_by"] == ADMIN["X-User-ID"]

    def test_fee_waiver_verified_denial_blocks_approval_despite_provisional(self, api):
        """PRD §3.7: "When `self_reported_benefit` is true, the tier is `FULL`
        regardless of income."
        PRD §3.7: "A decision of `APPROVED` stands only when the verified tier
        computes to `FULL` or `PARTIAL`; when it computes to `DENIED`, the approval
        rejects with `ERR_TIER_INELIGIBLE`."

        Design: Difficulty/dual_variant_calc/fee_waiver_provisional_vs_verified_tier
        """
        create_program()
        applicant, _ = create_screened_applicant()
        # Benefit flag makes the provisional tier FULL regardless of income.
        request = create_fee_waiver(applicant["id"], household_size=1,
                                    self_reported_income_cents=2000000,
                                    self_reported_benefit=True)
        assert request["provisional_tier"] == "FULL"
        assert request["required_document_count"] == 2

        submit_fee_waiver(request["id"], 2)
        # The documented record shows no benefit and 5,000,000 cents of income:
        # 5000000*100 > 1565000*200, so the verified tier computes to DENIED.
        response = api.decide_fee_waiver_request(
            request["id"],
            {"decision": "APPROVED", "documented_income_cents": 5000000,
             "documented_benefit": False},
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_TIER_INELIGIBLE)
        after = get_fee_waiver(request["id"])
        assert after["status"] == "SUBMITTED"
        assert after["final_tier"] is None
        assert after["provisional_tier"] == "FULL"


class TestTierFormulaInteraction:
    def test_fee_waiver_household_size_income_benefit_interaction(self, api):
        """PRD §3.7: "The poverty guideline for the household is `poverty_base_cents`
        plus `poverty_per_additional_cents` multiplied by the household size minus
        one."
        PRD §3.7: "Otherwise, when the income multiplied by one hundred is no greater
        than the guideline multiplied by `full_waiver_threshold_pct`, the tier is
        `FULL`. Otherwise, when the income multiplied by one hundred is no greater
        than the guideline multiplied by `partial_waiver_threshold_pct`, the tier is
        `PARTIAL`. In every remaining case the tier is `DENIED`."
        PRD §3.7: "All comparisons run in integer cents and every boundary is
        inclusive: income exactly at a threshold qualifies for that threshold's tier."

        Design: Difficulty/combinatorial_formula/fee_waiver_household_size_income_benefit_interaction
        """
        create_program()
        # Household 4: guideline 1,565,000 + 3*550,000 = 3,215,000; the FULL cap is
        # 3,215,000 * 150 / 100 = 4,822,500 cents.
        applicant_a, _ = create_screened_applicant()
        at_cap = create_fee_waiver(applicant_a["id"], household_size=4,
                                   self_reported_income_cents=4822500)
        assert at_cap["provisional_tier"] == "FULL", (
            "income exactly at the 150% cap qualifies for FULL (inclusive)"
        )

        applicant_b, _ = create_screened_applicant()
        one_over = create_fee_waiver(applicant_b["id"], household_size=4,
                                     self_reported_income_cents=4822501)
        assert one_over["provisional_tier"] == "PARTIAL", (
            "one cent over the FULL cap falls to PARTIAL (still within 200%)"
        )

        applicant_c, _ = create_screened_applicant()
        benefit_based = create_fee_waiver(applicant_c["id"], household_size=1,
                                          self_reported_income_cents=9999900,
                                          self_reported_benefit=True)
        assert benefit_based["provisional_tier"] == "FULL", (
            "the benefit branch overrides income entirely"
        )
        assert benefit_based["required_document_count"] == 2

    def test_fee_waiver_household_doc_count_and_denied_tier(self, api):
        """PRD §3.7: "The second derived value is `required_document_count`: exactly 2
        when the request is benefit-based, otherwise the household size plus one."
        PRD §3.7: "Otherwise, when the income multiplied by one hundred is no greater
        than the guideline multiplied by `partial_waiver_threshold_pct`, the tier is
        `PARTIAL`. In every remaining case the tier is `DENIED`."

        Design: Difficulty/combinatorial_formula/fee_waiver_household_size_income_benefit_interaction
        """
        create_program()
        # Household 3 without benefit: required documents = household size + 1 = 4.
        # Guideline = 1,565,000 + 2*550,000 = 2,665,000; the FULL cap is
        # 2,665,000*150/100 = 3,997,500 and the PARTIAL cap is
        # 2,665,000*200/100 = 5,330,000, so income 4,500,000 cents is PARTIAL.
        applicant_a, _ = create_screened_applicant()
        partial = create_fee_waiver(applicant_a["id"], household_size=3,
                                    self_reported_income_cents=4500000)
        assert partial["required_document_count"] == 4
        assert partial["provisional_tier"] == "PARTIAL"

        # Household 4: income one cent over the 200% cap (6,430,000) is DENIED.
        applicant_b, _ = create_screened_applicant()
        denied = create_fee_waiver(applicant_b["id"], household_size=4,
                                   self_reported_income_cents=6430001)
        assert denied["provisional_tier"] == "DENIED"
        assert denied["required_document_count"] == 5


class TestIncomeBoundaries:
    def test_fee_waiver_income_exactly_at_150pct_boundary(self, api):
        """PRD §3.7: "Otherwise, when the income multiplied by one hundred is no
        greater than the guideline multiplied by `full_waiver_threshold_pct`, the tier
        is `FULL`."
        PRD §3.7: "All comparisons run in integer cents and every boundary is
        inclusive: income exactly at a threshold qualifies for that threshold's tier."

        Design: Difficulty/boundary_precision_check/fee_waiver_income_exactly_at_150pct_boundary
        """
        create_program()
        # Household 1: guideline 1,565,000; the FULL cap is exactly 2,347,500 cents.
        applicant_at, _ = create_screened_applicant()
        at_boundary = create_fee_waiver(applicant_at["id"], household_size=1,
                                        self_reported_income_cents=2347500)
        assert at_boundary["provisional_tier"] == "FULL", (
            "2,347,500 cents is exactly 150% of the guideline and qualifies"
        )

        applicant_over, _ = create_screened_applicant()
        one_over = create_fee_waiver(applicant_over["id"], household_size=1,
                                     self_reported_income_cents=2347501)
        assert one_over["provisional_tier"] == "PARTIAL", (
            "one cent over the boundary drops to PARTIAL"
        )

    def test_fee_waiver_income_exactly_at_200pct_boundary(self, api):
        """PRD §3.7: "Otherwise, when the income multiplied by one hundred is no
        greater than the guideline multiplied by `partial_waiver_threshold_pct`, the
        tier is `PARTIAL`. In every remaining case the tier is `DENIED`."
        PRD §3.7: "All comparisons run in integer cents and every boundary is
        inclusive: income exactly at a threshold qualifies for that threshold's tier."

        Design: Difficulty/boundary_precision_check/fee_waiver_income_exactly_at_150pct_boundary
        """
        create_program()
        # Household 1: the PARTIAL cap is exactly 1,565,000 * 200 / 100 = 3,130,000.
        applicant_at, _ = create_screened_applicant()
        at_boundary = create_fee_waiver(applicant_at["id"], household_size=1,
                                        self_reported_income_cents=3130000)
        assert at_boundary["provisional_tier"] == "PARTIAL"

        applicant_over, _ = create_screened_applicant()
        one_over = create_fee_waiver(applicant_over["id"], household_size=1,
                                     self_reported_income_cents=3130001)
        assert one_over["provisional_tier"] == "DENIED"


class TestSubmissionAndDecision:
    def test_fee_waiver_submit_docs_below_required(self, api):
        """PRD §3.7: "Submission moves `DRAFT` → `SUBMITTED` (applicant or
        coordinator; `ERR_INVALID_STATE` from any other status) and supplies the
        `attached_document_count`; when that count falls short of
        `required_document_count` the submission rejects with
        `ERR_FEE_WAIVER_DOCS_INSUFFICIENT`."

        Design: Corner/validations/fee_waiver_submit_docs_below_required
        """
        create_program()
        applicant, _ = create_screened_applicant()
        request = create_fee_waiver(applicant["id"], household_size=3,
                                    self_reported_income_cents=2000000)
        assert request["required_document_count"] == 4, "household size 3 plus one"

        response = api.submit_fee_waiver_request(
            request["id"], {"attached_document_count": 3}, COORD
        )
        validate_error(response, ApiErrorId.ERR_FEE_WAIVER_DOCS_INSUFFICIENT)
        after = get_fee_waiver(request["id"])
        assert after["status"] == "DRAFT"
        assert after["attached_document_count"] == 0

    def test_decide_approved_with_denied_verified_tier_rejected(self, api):
        """PRD §3.7: "A decision of `APPROVED` stands only when the verified tier
        computes to `FULL` or `PARTIAL`; when it computes to `DENIED`, the approval
        rejects with `ERR_TIER_INELIGIBLE`."

        Design: Corner/validations/decide_approved_with_denied_verified_tier_rejected
        """
        create_program()
        applicant, _ = create_screened_applicant()
        request = create_fee_waiver(applicant["id"], household_size=1,
                                    self_reported_income_cents=1000000)
        submit_fee_waiver(request["id"], 2)

        # Documented income 5,000,000 cents: 5000000*100 > 1565000*200, so the
        # verified tier computes to DENIED and the approval cannot stand.
        response = api.decide_fee_waiver_request(
            request["id"],
            {"decision": "APPROVED", "documented_income_cents": 5000000,
             "documented_benefit": False},
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_TIER_INELIGIBLE)
        after = get_fee_waiver(request["id"])
        assert after["status"] == "SUBMITTED"
        assert after["final_tier"] is None

    def test_fee_waiver_decide_twice_rejected(self, api):
        """PRD §3.7: "Adjudication belongs to a `ProgramAdmin`, who decides a
        `SUBMITTED` request by supplying a `decision` together with the verified
        evidence `documented_income_cents` and `documented_benefit`."
        PRD §3.7: "`APPROVED` is terminal; `DENIED` is deliberately not — an applicant
        or coordinator may resubmit a denied request, returning it to `DRAFT`,
        resetting `attached_document_count` to zero, clearing the documented values,
        and recomputing `provisional_tier` from the unchanged self-reported inputs,
        ready for a fresh attempt."

        Design: Corner/state_machines/fee_waiver_decide_twice_rejected
        """
        create_program()
        applicant, _ = create_screened_applicant()
        approved = create_approved_fee_waiver(applicant["id"], household_size=1,
                                              income=1000000)
        assert approved["status"] == "APPROVED"
        assert approved["final_tier"] == "FULL"

        response = api.decide_fee_waiver_request(
            approved["id"],
            {"decision": "DENIED", "documented_income_cents": 1000000,
             "documented_benefit": False},
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        after = get_fee_waiver(approved["id"])
        assert after["status"] == "APPROVED"
        assert after["final_tier"] == "FULL"

    def test_fee_waiver_second_active_rejected(self, api):
        """PRD §3.7: "only one non-terminal request may exist per applicant — a second
        request while a `DRAFT` or `SUBMITTED` one exists rejects with
        `ERR_FEE_WAIVER_ALREADY_ACTIVE`"

        Design: Corner/endpoints/fee_waiver_second_active_rejected
        """
        create_program()
        applicant, _ = create_screened_applicant()
        first = create_fee_waiver(applicant["id"], household_size=1,
                                  self_reported_income_cents=1000000)
        assert first["status"] == "DRAFT"

        response = api.create_fee_waiver_request(
            applicant["id"],
            {"household_size": 2, "self_reported_income_cents": 900000,
             "self_reported_benefit": True},
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_FEE_WAIVER_ALREADY_ACTIVE)

        rows, meta = validate_paginated(
            api.list_fee_waiver_requests(COORD, params={"applicant_id": applicant["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
