"""NIL deal submission, FMV computation, PATCH, review, and approval.

PRD §3.5 (submission, FMV calc), §3.6 (review, approval, segregation
of duties, approved_value pinning), §2.5 (optimistic concurrency on
PATCH).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    approve_nil_deal,
    assert_approved_value_pinned_to_min,
    assert_nil_deal,
    create_athlete,
    create_eligibility_record,
    create_nil_deal_payload,
    create_program,
    make_athlete_headers,
    patch_nil_deal_payload,
    review_nil_deal,
    setup_approved_nil_deal,
    setup_enrolled_athlete,
    submit_nil_deal,
    transition_nil_deal_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.5 NIL deal submission and FMV computation
# ===========================================================================
class TestNILDealSubmit:
    """PRD §3.5: "On submission the deal starts in SUBMITTED status;
    fmv_calculated_cents and pay_for_play_flag are computed
    immediately, and approved_value_cents and review_started_at remain
    null." """

    def test_submit_initializes_status_and_computes_fmv(
        self, api, officer_headers,
    ):
        """PRD §3.5: "On submission the deal starts in SUBMITTED
        status; fmv_calculated_cents and pay_for_play_flag are computed
        immediately."

        Claim: a freshly submitted deal has status=SUBMITTED, an
        integer fmv_calculated_cents, and a boolean pay_for_play_flag.
        """
        athlete, _p, _s = setup_enrolled_athlete()
        d = submit_nil_deal(
            athlete["id"],
            deal_category="ENDORSEMENT",
            sponsor_is_booster=False,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            stated_value_cents=500_000,
        )
        assert_nil_deal(d)
        assert d["status"] == "SUBMITTED"
        assert isinstance(d["fmv_calculated_cents"], int)
        assert isinstance(d["pay_for_play_flag"], bool)
        assert d.get("approved_value_cents") in (None, "")
        assert d.get("review_started_at") in (None, "")

    def test_fmv_endorsement_non_booster_formula(self, api):
        """PRD §3.5: "It begins with a base equal to deliverables_hours
        multiplied by market_rate_cents_per_hour. The base is then
        multiplied by a category multiplier whose value depends on
        deal_category: 1.20 for ENDORSEMENT ... The result is then
        multiplied by a booster factor: 0.80 when sponsor_is_booster
        is true ... and 1.00 otherwise."

        Claim: 10h * 50000 cpch * 1.20 (ENDORSEMENT) * 1.00 (non-booster)
        = 600000.
        """
        athlete, _p, _s = setup_enrolled_athlete()
        d = submit_nil_deal(
            athlete["id"],
            deal_category="ENDORSEMENT",
            sponsor_is_booster=False,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            stated_value_cents=500_000,
        )
        assert d["fmv_calculated_cents"] == 600_000, (
            f"fmv = 10 * 50000 * 1.20 * 1.00 = 600000, got "
            f"{d['fmv_calculated_cents']}"
        )

    def test_fmv_endorsement_booster_factor_applied(self, api):
        """PRD §3.5: "0.80 when sponsor_is_booster is true (a more
        conservative valuation of booster-paid deals)."

        Claim: 10h * 50000 cpch * 1.20 (ENDORSEMENT) * 0.80 (booster)
        = 480000.
        """
        athlete, _p, _s = setup_enrolled_athlete()
        d = submit_nil_deal(
            athlete["id"],
            deal_category="ENDORSEMENT",
            sponsor_is_booster=True,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            stated_value_cents=400_000,
        )
        assert d["fmv_calculated_cents"] == 480_000, (
            f"fmv = 10 * 50000 * 1.20 * 0.80 = 480000, got "
            f"{d['fmv_calculated_cents']}"
        )

    @pytest.mark.parametrize(
        "category,expected_mult",
        [
            ("ENDORSEMENT", 1.20),
            ("APPEARANCE", 1.10),
            ("SOCIAL_MEDIA_POST", 1.00),
            ("AUTOGRAPH_SIGNING", 0.90),
            ("CAMP_INSTRUCTION", 1.05),
        ],
    )
    def test_fmv_each_category_multiplier(
        self, api, category, expected_mult,
    ):
        """PRD §3.5: "1.20 for ENDORSEMENT, 1.10 for APPEARANCE, 1.00
        for SOCIAL_MEDIA_POST, 0.90 for AUTOGRAPH_SIGNING, and 1.05
        for CAMP_INSTRUCTION."

        Claim: each category multiplier produces 10h * 50000 *
        cat_mult * 1.00 = expected_mult * 500000.
        """
        athlete, _p, _s = setup_enrolled_athlete()
        d = submit_nil_deal(
            athlete["id"],
            deal_category=category,
            sponsor_is_booster=False,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            stated_value_cents=1_000_000,
        )
        expected = int(round(10 * 50_000 * expected_mult * 1.00))
        assert d["fmv_calculated_cents"] == expected, (
            f"fmv for {category} = 10*50000*{expected_mult}*1.00 = "
            f"{expected}, got {d['fmv_calculated_cents']}"
        )


# ===========================================================================
# §3.5 PATCH while SUBMITTED recomputes FMV
# ===========================================================================
class TestNILDealPatch:
    """PRD §3.5: "While the deal is still in SUBMITTED, the submitter
    (or any role permitted on the deal) may edit deliverables_hours,
    market_rate_cents_per_hour, and stated_value_cents — each such
    edit re-runs the fair-market and pay-for-play computations." """

    def test_patch_deliverables_hours_recomputes_fmv(self, api):
        """PRD §3.5: "each such edit re-runs the fair-market and
        pay-for-play computations."

        Claim: a PATCH that doubles deliverables_hours doubles
        fmv_calculated_cents (proportional in the FMV formula).
        """
        athlete, _p, _s = setup_enrolled_athlete()
        d = submit_nil_deal(
            athlete["id"],
            deal_category="ENDORSEMENT",
            sponsor_is_booster=False,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            stated_value_cents=2_000_000,
        )
        # fmv = 10 * 50000 * 1.20 * 1.00 = 600000
        assert d["fmv_calculated_cents"] == 600_000
        res = api.patch_nil_deal(
            d["id"],
            patch_nil_deal_payload(deliverables_hours=20.0),
            make_athlete_headers(athlete["id"]),
        )
        patched = validate_success(res)
        # fmv = 20 * 50000 * 1.20 * 1.00 = 1200000
        assert patched["fmv_calculated_cents"] == 1_200_000, (
            f"fmv after doubling hours = 20*50000*1.20*1.00 = 1200000, "
            f"got {patched['fmv_calculated_cents']}"
        )


# ===========================================================================
# §3.6 Segregation of duties on review
# ===========================================================================
class TestSegregationOfDutiesOnReview:
    """PRD §3.6: "The acting officer's X-User-ID must differ from the
    X-User-ID that submitted the deal — a submitter may never start
    their own deal's review — otherwise ERR_SEGREGATION_OF_DUTIES." """

    def test_same_officer_cannot_review_own_submission(
        self, api, officer_headers,
    ):
        """PRD §3.6: "The acting officer's X-User-ID must differ from
        the X-User-ID that submitted the deal — a submitter may never
        start their own deal's review — otherwise
        ERR_SEGREGATION_OF_DUTIES."

        Claim: officer-A submits the deal, then officer-A attempts
        SUBMITTED -> UNDER_REVIEW -> ERR_SEGREGATION_OF_DUTIES.
        """
        athlete, _p, _s = setup_enrolled_athlete()
        # Submit as ComplianceOfficer A (PRIMARY).
        d = submit_nil_deal(
            athlete["id"], headers=officer_headers,
        )
        # Try to review as the SAME officer.
        res = api.transition_nil_deal(
            d["id"],
            transition_nil_deal_payload(to_status="UNDER_REVIEW"),
            officer_headers,
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")

    def test_different_officer_can_review(
        self, api, officer_headers, officer_headers_secondary,
    ):
        """PRD §3.6: "The acting officer's X-User-ID must differ from
        the X-User-ID that submitted the deal."

        Claim: officer-A submits, officer-B reviews ->
        UNDER_REVIEW succeeds and review_started_at is pinned.
        """
        athlete, _p, _s = setup_enrolled_athlete()
        d = submit_nil_deal(
            athlete["id"], headers=officer_headers,
        )
        res = api.transition_nil_deal(
            d["id"],
            transition_nil_deal_payload(to_status="UNDER_REVIEW"),
            officer_headers_secondary,
        )
        data = validate_success(res)
        assert data["status"] == "UNDER_REVIEW"
        # PRD §3.6: "review_started_at is pinned to the request timestamp."
        assert data.get("review_started_at"), (
            "review_started_at must be set on SUBMITTED->UNDER_REVIEW"
        )


# ===========================================================================
# §3.6 Approval and approved_value_cents pinning
# ===========================================================================
class TestNILDealApproval:
    """PRD §3.6: "On success, approved_value_cents is pinned to the
    minimum of stated_value_cents and fmv_calculated_cents — the
    system caps approved compensation at fair market when the stated
    payment exceeds it, but honors the stated value when it falls
    below fair market." """

    def test_approved_value_pinned_to_min_stated_lower(self, api):
        """PRD §3.6: "approved_value_cents is pinned to the minimum of
        stated_value_cents and fmv_calculated_cents".

        Claim: stated=500000, fmv=600000 (10*50000*1.20*1.00) -> min
        is stated=500000, so approved_value_cents == 500000.
        """
        athlete, _p, _s = setup_enrolled_athlete()
        d = setup_approved_nil_deal(
            athlete["id"],
            stated_value_cents=500_000,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            deal_category="ENDORSEMENT",
            sponsor_is_booster=False,
        )
        assert d["status"] == "APPROVED"
        assert d["fmv_calculated_cents"] == 600_000
        assert d["approved_value_cents"] == 500_000
        assert_approved_value_pinned_to_min(d)

    def test_approved_value_pinned_to_min_fmv_lower(self, api):
        """PRD §3.6: "approved_value_cents is pinned to the minimum of
        stated_value_cents and fmv_calculated_cents — the system caps
        approved compensation at fair market when the stated payment
        exceeds it."

        Claim: stated=2000000, fmv=600000 -> min is fmv=600000, so
        approved_value_cents == 600000.
        """
        athlete, _p, _s = setup_enrolled_athlete()
        d = setup_approved_nil_deal(
            athlete["id"],
            stated_value_cents=2_000_000,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            deal_category="ENDORSEMENT",
            sponsor_is_booster=False,
        )
        # stated:2000000, fmv:600000 -> min is 600000.
        # NOTE: stated/fmv ratio = 2000000/600000 = 3.33 — would trip
        # pay-for-play if sponsor were booster. sponsor_is_booster is
        # False here, so the ratio rule does NOT fire (per PRD §3.5
        # condition (a) requires sponsor_is_booster=true).
        assert d["approved_value_cents"] == 600_000
        assert_approved_value_pinned_to_min(d)

    def test_approve_updates_athlete_lifetime_value(self, api):
        """PRD §3.6: "The athlete's nil_deal_lifetime_value_cents is
        recomputed as the sum of approved_value_cents across that
        athlete's deals whose status is APPROVED."

        Claim: after one approval at approved_value=500000, the
        athlete's nil_deal_lifetime_value_cents equals 500000.
        """
        athlete, _p, _s = setup_enrolled_athlete()
        d = setup_approved_nil_deal(
            athlete["id"],
            stated_value_cents=500_000,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
        )
        a_resp = api.get_athlete(
            athlete["id"], TEST_USERS["officer_headers"],
        )
        a_data = validate_success(a_resp)
        assert a_data["nil_deal_lifetime_value_cents"] == 500_000


# ===========================================================================
# §3.6 Athlete-state precondition on approval
# ===========================================================================
class TestNILDealApprovalAthleteState:
    """PRD §3.6: "the athlete's status must be COMMITTED or ENROLLED
    (otherwise ERR_ATHLETE_NOT_ENROLLED); and the athlete's
    amateur_status must be AMATEUR (otherwise
    ERR_AMATEUR_STATUS_LOST)." """

    def test_approve_prospective_athlete_rejected(
        self, api, officer_headers_secondary,
    ):
        """PRD §3.6: "the athlete's status must be COMMITTED or
        ENROLLED (otherwise ERR_ATHLETE_NOT_ENROLLED)."

        Claim: approval on a deal whose athlete is still PROSPECTIVE
        (current_program_id is null) -> ERR_ATHLETE_NOT_ENROLLED.
        """
        # Create PROSPECTIVE athlete (no slot, no eligibility).
        athlete = create_athlete()
        # Submit a small deal (avoid pay-for-play inducement trigger
        # for uncommitted athletes — stated_value < 5_000_000).
        d = submit_nil_deal(
            athlete["id"],
            stated_value_cents=100_000,
            deliverables_hours=2.0,
            market_rate_cents_per_hour=50_000,
            deal_category="APPEARANCE",
            sponsor_is_booster=False,
        )
        review_nil_deal(d["id"])
        res = api.transition_nil_deal(
            d["id"],
            transition_nil_deal_payload(to_status="APPROVED"),
            officer_headers_secondary,
        )
        validate_error(res, "ERR_ATHLETE_NOT_ENROLLED")


# ===========================================================================
# §3.6 Rejection
# ===========================================================================
class TestNILDealRejection:
    """PRD §3.6: "Rejection — UNDER_REVIEW -> REJECTED — is terminal
    and has no business preconditions beyond the priority-ordered ones
    in §2.8." """

    def test_reject_from_under_review(self, api, officer_headers_secondary):
        """PRD §3.6: "Rejection — UNDER_REVIEW -> REJECTED — is
        terminal."

        Claim: UNDER_REVIEW -> REJECTED succeeds and the deal lands in
        REJECTED.
        """
        athlete, _p, _s = setup_enrolled_athlete()
        d = submit_nil_deal(athlete["id"])
        review_nil_deal(d["id"])
        res = api.transition_nil_deal(
            d["id"],
            transition_nil_deal_payload(to_status="REJECTED"),
            officer_headers_secondary,
        )
        data = validate_success(res)
        assert data["status"] == "REJECTED"


# ===========================================================================
# §2.1 Athlete ownership on POST /nil-deals
# ===========================================================================
class TestAthleteOwnershipOnSubmission:
    """PRD §2.1: "an Athlete who supplies someone else's athlete_id
    when submitting an NIL deal or entering the portal is rejected
    with ERR_FORBIDDEN." """

    def test_athlete_cannot_submit_deal_for_other_athlete(self, api):
        """PRD §2.1: "an Athlete who supplies someone else's
        athlete_id when submitting an NIL deal or entering the portal
        is rejected with ERR_FORBIDDEN."

        Claim: Athlete A1 calling POST /nil-deals with
        athlete_id=A2 -> ERR_FORBIDDEN.
        """
        a1, _p, _s = setup_enrolled_athlete()
        a2, _p2, _s2 = setup_enrolled_athlete()
        res = api.create_nil_deal(
            create_nil_deal_payload(athlete_id=a2["id"]),
            make_athlete_headers(a1["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")
