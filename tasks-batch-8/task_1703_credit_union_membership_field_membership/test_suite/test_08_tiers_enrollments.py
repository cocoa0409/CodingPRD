"""Member service tiers: dual evaluation bases, inclusive thresholds, and
tier-gated product enrollment."""
from test_helpers import (
    ApiErrorId,
    assert_product_enrollment,
    create_enrollment_payload,
    create_member,
    enroll,
    get_member,
    open_account,
    post_transaction,
    set_clock,
    setup_charter,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

FILER = TEST_USERS["membership_officer_headers"]
OPS = TEST_USERS["operations_officer_headers"]


class TestDualTierEvaluation:
    def _setup(self, api):
        """Member approved 2025-05-01 with a 100,000 PRIMARY; a 900,000
        deposit lands 2026-07-25; evaluation date 2026-08-01."""
        set_clock("2025-05-01")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Tess Tier",
                                  date_of_birth="1988-03-03")
        acct = open_account(member_id, initial_deposit_cents=100_000)
        set_clock("2026-07-25")
        post_transaction(acct["id"], "DEPOSIT", 900_000, "2026-07-25")
        set_clock("2026-08-01")
        return member_id, acct

    def test_enrollment_tier_uses_current_point_in_time(self, api):
        """PRD §3.6: "Eligibility is evaluated at enrollment on the
        current-point-in-time basis — the same tenure thresholds and inclusive
        boundaries as §3.4 (PREMIER at no less than 36 full months and
        2,500,000 cents, SELECT at no less than 12 full months and 500,000
        cents), but applied to the instantaneous sum of `balance_cents` across
        the member's OPEN accounts rather than to the materialized tier or any
        trailing average, so a member with a recent large deposit qualifies
        immediately."
        PRD §3.6: "The computed tier is recorded on the enrollment as
        `tier_at_enrollment` alongside the `required_tier`."

        Design: Difficulty/dual_variant_calc/tier_current_vs_trailing90_same_member_same_day
        """
        member_id, acct = self._setup(api)
        enrollment = validate_success(api.create_product_enrollment(
            create_enrollment_payload(member_id, acct["id"]), FILER), 201)
        assert_product_enrollment(enrollment)
        assert enrollment["tier_at_enrollment"] == "SELECT", (
            "Current balance 1,000,000 >= 500,000 and tenure 15 >= 12")
        assert enrollment["required_tier"] == "SELECT"
        assert enrollment["status"] == "ACTIVE"

    def test_tier_review_uses_trailing_90_average_same_day(self, api):
        """PRD §3.4: "A tier review evaluates the member on the
        trailing-ninety-day-average basis: for each day in the ninety-day
        window comprising the evaluation date and the eighty-nine days
        preceding it, the member's daily aggregate end-of-day balance is the
        sum across the share accounts open on that day, and the balance basis
        is the average of those daily aggregates."
        PRD §3.4: "Because the enrollment-time evaluation of §3.6 uses the
        instantaneous balance rather than the trailing average, the same member
        on the same day can qualify for a product at enrollment yet evaluate to
        a lower tier at review, and the materialized tier never changes except
        through this review."

        Design: Difficulty/dual_variant_calc/tier_current_vs_trailing90_same_member_same_day
        """
        member_id, acct = self._setup(api)
        enrollment = enroll(member_id, acct["id"])

        reviewed = validate_success(api.tier_review(member_id, OPS))
        assert reviewed["tier"] == "STANDARD", (
            "Trailing-90 average 180,000 (82 days @100,000 + 8 days "
            "@1,000,000) < 500,000")
        assert reviewed["last_tier_review_at"] is not None

        stored = validate_success(
            api.get_product_enrollment(enrollment["id"], FILER))
        assert stored["tier_at_enrollment"] == "SELECT", (
            "The enrollment-time record is unchanged by the later review")
        assert get_member(member_id)["tier"] == "STANDARD"


class TestTierThresholdBoundary:
    def _setup(self, api):
        """Member approved 2025-07-01; PRIMARY 500,000 never touched; review at
        2026-07-01."""
        set_clock("2025-07-01")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Boundary Bea",
                                  date_of_birth="1986-06-06")
        open_account(member_id, initial_deposit_cents=500_000)
        set_clock("2026-07-01")
        return member_id

    def test_tenure_exact_anniversary_counts_full_months(self, api):
        """PRD §3.4: "The `tenure_months` of a member is the number of full
        calendar months between `membership_effective_date` and the current
        date: twelve times the calendar-year difference plus the calendar-month
        difference, reduced by one when the current day-of-month precedes the
        effective date's day-of-month."

        Design: Difficulty/boundary_precision_check/tier_thresholds_exact_boundary_qualifies
        """
        member_id = self._setup(api)
        reviewed = validate_success(api.tier_review(member_id, OPS))
        assert reviewed["membership_effective_date"] == "2025-07-01"
        assert reviewed["tenure_months"] == 12, (
            "2025-07-01 -> 2026-07-01: the exact anniversary counts because "
            "day 01 does not precede day 01")

    def test_tier_thresholds_exact_boundary_qualifies(self, api):
        """PRD §3.4: "PREMIER requires tenure of at least 36 full months and a
        balance basis of at least 2,500,000 cents; failing that, SELECT
        requires at least 12 full months and at least 500,000 cents; otherwise
        the member is STANDARD. Both thresholds are inclusive — a member
        sitting exactly on a boundary qualifies for the higher tier."

        Design: Difficulty/boundary_precision_check/tier_thresholds_exact_boundary_qualifies
        """
        member_id = self._setup(api)
        reviewed = validate_success(api.tier_review(member_id, OPS))
        assert reviewed["tier"] == "SELECT", (
            "Balance boundary 500,000 >= 500,000 and tenure 12 >= 12 are both "
            "inclusive")
        assert reviewed["last_tier_review_at"] is not None, (
            "The review stamps last_tier_review_at")


class TestEnrollmentTierGating:
    def _setup(self, api):
        """Member B approved 2025-07-01 (500,000); member A approved
        2026-07-15 (600,000); evaluation at 2026-08-01."""
        set_clock("2025-07-01")
        _charter, seg_ids = setup_charter()
        m_b = create_member(segment_id=seg_ids[0], name="Tenured Tom",
                            date_of_birth="1984-04-04")
        acct_b = open_account(m_b, initial_deposit_cents=500_000)
        set_clock("2026-07-15")
        m_a = create_member(segment_id=seg_ids[0], name="Rich Rick",
                            date_of_birth="1996-06-06")
        acct_a = open_account(m_a, initial_deposit_cents=600_000)
        set_clock("2026-08-01")
        return m_a, acct_a, m_b, acct_b

    def test_enrollment_denied_when_tenure_forces_standard(self, api):
        """PRD §3.6: "Falling short of the product's tier is rejected with
        `ERR_TIER_REQUIREMENT_NOT_MET`."
        PRD §3.6: "Each product names its `required_tier`: MONEY_MARKET and
        SHARE_CERTIFICATE require SELECT, and PREMIER_LOAN requires PREMIER."

        Design: Difficulty/cross_entity_state_dependency/product_enrollment_gated_by_member_tier
        """
        m_a, acct_a, _m_b, _acct_b = self._setup(api)
        resp = api.create_product_enrollment(
            create_enrollment_payload(m_a, acct_a["id"]), FILER)
        # Balance 600,000 qualifies, but tenure 0 months (< 12) forces
        # STANDARD, below the required SELECT.
        validate_error(resp, ApiErrorId.ERR_TIER_REQUIREMENT_NOT_MET)

    def test_enrollment_succeeds_for_tenured_member(self, api):
        """PRD §3.6: "An enrollment begins ACTIVE and closes only when its
        funding account closes, ending CLOSED with closure reason
        FORCED_ACCOUNT_CLOSURE."
        PRD §3.6: "Eligibility is evaluated at enrollment on the
        current-point-in-time basis"

        Design: Difficulty/cross_entity_state_dependency/product_enrollment_gated_by_member_tier
        """
        _m_a, _acct_a, m_b, acct_b = self._setup(api)
        enrollment = validate_success(api.create_product_enrollment(
            create_enrollment_payload(m_b, acct_b["id"]), FILER), 201)
        assert_product_enrollment(enrollment)
        assert enrollment["tier_at_enrollment"] == "SELECT", (
            "Tenure 13 >= 12 and balance 500,000 >= 500,000")
        assert enrollment["status"] == "ACTIVE"


class TestEnrollmentValidation:
    def test_enrollment_duplicate_and_funding_account_ownership(self, api):
        """PRD §3.6: "The funding account must belong to that member and be
        OPEN, otherwise `ERR_PRODUCT_FUNDING_ACCOUNT_INVALID`. A member may
        hold only one ACTIVE enrollment per product code; a duplicate is
        rejected with `ERR_ALREADY_ENROLLED`."

        Design: Corner/validations/enrollment_duplicate_and_funding_account_ownership
        """
        set_clock("2025-07-01")
        _charter, seg_ids = setup_charter()
        m_a = create_member(segment_id=seg_ids[0], name="Enroll Ann")
        acct_a = open_account(m_a, initial_deposit_cents=500_000)
        m_b = create_member(segment_id=seg_ids[0], name="Enroll Bob",
                            date_of_birth="1990-02-02")
        open_account(m_b, initial_deposit_cents=500_000)

        set_clock("2026-08-01")
        enroll(m_a, acct_a["id"])  # A holds an ACTIVE MONEY_MARKET enrollment

        foreign = api.create_product_enrollment(
            create_enrollment_payload(m_b, acct_a["id"],
                                      product_code="SHARE_CERTIFICATE"),
            FILER)
        validate_error(foreign, ApiErrorId.ERR_PRODUCT_FUNDING_ACCOUNT_INVALID)

        dup = api.create_product_enrollment(
            create_enrollment_payload(m_a, acct_a["id"]), FILER)
        validate_error(dup, ApiErrorId.ERR_ALREADY_ENROLLED)
