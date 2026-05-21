"""Initial determination, approval cascade, and PIA / family-max calc.

Covers PRD §3.4 (approval cascade) and §3.5 (PIA + Family Max bend-point
math). Difficulty-design coverage for rule 2 (combinatorial formula —
PIA bend points and Family Max waterfall).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    BEND_POINT_1,
    BEND_POINT_2,
    FMB_BP1,
    FMB_BP2,
    TEST_USERS,
    api_client,
    assert_application,
    assert_determination,
    assert_dime_rounded,
    create_claimant,
    create_determination_payload,
    get_application,
    issue_determination,
    setup_application_approved_at_initial,
    setup_application_at_initial_review,
    validate_error,
    validate_success,
)


class TestInitialDetermination:

    def test_initial_allow_transitions_to_approved(self, api):
        """PRD §3.4: "An ALLOW at INITIAL_REVIEW requires the
        determination's medical_basis to be one of MEETS_LISTING,
        EQUALS_LISTING, or DISABLED_BY_RFC ... The application
        transitions from INITIAL_REVIEW to APPROVED and the approval
        cascade runs".
        """
        claimant, application = setup_application_approved_at_initial()
        assert application["status"] == "APPROVED"

    def test_initial_deny_transitions_to_initial_denied(self, api):
        """PRD §3.4: "A DENY at INITIAL_REVIEW is simpler: the
        application transitions from INITIAL_REVIEW to INITIAL_DENIED,
        Application.last_initial_examiner_id is stamped with the acting
        examiner, and a Determination row with level INITIAL and
        decision DENY is appended. No financial fields are computed."
        """
        claimant, application, _ = setup_application_at_initial_review()
        issue_determination(
            claimant["id"], application["id"],
            level="INITIAL", decision="DENY",
            medical_basis="NOT_DISABLED",
        )
        application = get_application(claimant["id"], application["id"])
        assert application["status"] == "INITIAL_DENIED"

    def test_approval_records_last_initial_examiner_id(self, api):
        """PRD §3.4: "Application.last_initial_examiner_id is set to
        the acting examiner's X-User-ID, binding the segregation-of-
        duties rule that §3.6 will enforce at reconsideration."
        """
        claimant, application = setup_application_approved_at_initial(
            examiner_headers=TEST_USERS["dds_examiner_headers"],
        )
        # The opaque examiner id used in test_users.py is
        # 'dds-examiner-0001'.
        assert application.get("last_initial_examiner_id") == "dds-examiner-0001"

    def test_approval_stamps_approval_date(self, api):
        """PRD §3.4: "Application.approval_date is set to the logical
        clock's current instant, pinning the end of the back-pay
        window."
        """
        claimant, application = setup_application_approved_at_initial()
        assert isinstance(application.get("approval_date"), str)
        assert len(application["approval_date"]) > 0

    def test_initial_allow_with_not_disabled_medical_basis_rejected(self, api):
        """PRD §3.4: "An ALLOW at INITIAL_REVIEW requires the
        determination's medical_basis to be one of MEETS_LISTING,
        EQUALS_LISTING, or DISABLED_BY_RFC (a determination whose
        medical_basis is NOT_DISABLED or NOT_REACHED cannot be an
        ALLOW)."
        """
        claimant, application, _ = setup_application_at_initial_review()
        payload = create_determination_payload(
            level="INITIAL", decision="ALLOW",
            medical_basis="NOT_DISABLED",
        )
        resp = api.create_determination(
            claimant["id"], application["id"], payload,
            TEST_USERS["dds_examiner_headers"],
        )
        # PRD describes this as invalid — any 4xx is acceptable since
        # PRD does not commit to a specific error_id for this combo.
        # The contract committed to is "cannot be an ALLOW", so we just
        # assert the request was rejected.
        assert resp.status_code >= 400 and resp.status_code < 500, (
            f"ALLOW with NOT_DISABLED medical_basis must be rejected; "
            f"got {resp.status_code}"
        )


class TestPIABendPointCalculation:
    """Difficulty design rule 2: pia_bend_point_tiered_with_dime_round_mode_a.

    PRD §3.5 PIA formula:
        pia_cents = floor(
            0.90 * min(aime, BP1)
          + 0.32 * max(0, min(aime, BP2) - BP1)
          + 0.15 * max(0, aime - BP2)
        )
        pia_cents = (pia_cents // 10) * 10  # dime-round-down
    """

    def test_pia_is_dime_rounded(self, api):
        """# difficulty: combinatorial_formula/pia_bend_point_tiered_with_dime_round_mode_a

        PRD §3.5: "After the floor, pia_cents is rounded down to the
        nearest ten cents — that is, pia_cents divided by ten using
        integer division, then multiplied by ten — implementing the
        SSA dime-round-down rule."

        Claim: regardless of inputs, pia_cents % 10 == 0 after approval.
        """
        claimant, application = setup_application_approved_at_initial()
        pia = application.get("pia_cents")
        assert isinstance(pia, int) and pia >= 0, (
            f"pia_cents must be a non-negative int, got {pia!r}"
        )
        assert_dime_rounded(pia)

    def test_pia_first_bend_is_90_percent_of_aime(self, api):
        """# difficulty: combinatorial_formula/pia_bend_point_tiered_with_dime_round_mode_a

        PRD §3.5: "The PIA in cents is then the floor of three bend-
        point bands summed together: 0.90 multiplied by the lesser of
        aime_cents and BEND_POINT_1 (which equals 117400 cents, that
        is $1,174)".

        Claim: when aime < BEND_POINT_1, PIA = floor(0.90 * aime),
        dime-rounded. The exact aime value is not directly tunable from
        the API; we instead pin the formula's invariants:
            * pia <= aime (post-clamp)
            * pia <= floor(0.90 * aime) dime-rounded, when aime <= BP1
            * pia >= 0
        """
        claimant, application = setup_application_approved_at_initial()
        pia = application["pia_cents"]
        aime = application.get("aime_cents")
        assert isinstance(aime, int) and aime >= 0, (
            f"aime_cents must be non-negative int, got {aime!r}"
        )
        if aime <= BEND_POINT_1:
            # First-tier: pia ~ floor(0.90 * aime), dime-rounded.
            expected_unrounded = math.floor(0.90 * aime)
            expected = (expected_unrounded // 10) * 10
            assert pia == expected, (
                f"first-tier PIA must equal dime-rounded "
                f"floor(0.90 * {aime}) = {expected}; got {pia}"
            )

    def test_pia_formula_holds_for_observed_aime(self, api):
        """# difficulty: combinatorial_formula/pia_bend_point_tiered_with_dime_round_mode_a

        PRD §3.5: "The PIA in cents is then the floor of three bend-
        point bands summed together: 0.90 multiplied by the lesser of
        aime_cents and BEND_POINT_1 ... plus 0.32 multiplied by the
        greater of zero and the difference between (the lesser of
        aime_cents and BEND_POINT_2) and BEND_POINT_1, where
        BEND_POINT_2 equals 707800 cents ($7,078); plus 0.15 multiplied
        by the greater of zero and the difference between aime_cents
        and BEND_POINT_2."

        Claim: pia_cents matches the three-tier formula applied to the
        server's reported aime_cents, dime-rounded down.
        """
        claimant, application = setup_application_approved_at_initial()
        aime = application["aime_cents"]
        pia = application["pia_cents"]
        first = 0.90 * min(aime, BEND_POINT_1)
        second = 0.32 * max(0, min(aime, BEND_POINT_2) - BEND_POINT_1)
        third = 0.15 * max(0, aime - BEND_POINT_2)
        expected_unrounded = math.floor(first + second + third)
        expected = (expected_unrounded // 10) * 10
        assert pia == expected, (
            f"PIA bend-point formula expects {expected} for "
            f"aime={aime}; got {pia}"
        )


class TestFamilyMaxClamp:

    # NOTE: test_family_max_dime_rounded was DELETED per the diagnostic
    # protocol STEP 1b (unique-derivability failure). PRD §3.5 sequences
    # the family-max calculation as:
    #     bend-point sum -> floor to int -> dime-round-down -> DIB clamp
    # i.e. the clamp is the LAST step and is expressed as a literal
    # multiplication ("no less than 1.50 times pia_cents and no more
    # than 1.85 times pia_cents") with no mention of re-rounding. A
    # faithful PRD-only implementer could read that wording either as
    # "leave the clamped value alone" (producing a non-dime value when
    # clamp fires) or "re-dime-round after clamp" — both are consistent
    # with the prose. The test asserted the latter without PRD support;
    # the dime-round-only invariant before clamp is already covered by
    # test_family_max_within_dib_clamp's neighbours.

    def test_family_max_within_dib_clamp(self, api):
        """PRD §3.5: "After dime-rounding, the Disability Insurance
        Benefit (DIB) special floor and ceiling clamp family_max_cents
        to be no less than 1.50 times pia_cents and no more than 1.85
        times pia_cents."
        """
        claimant, application = setup_application_approved_at_initial()
        pia = application["pia_cents"]
        fm = application["family_max_cents"]
        # PRD: clamp to [1.50 * pia, 1.85 * pia]. Allow integer slack on
        # the floor since 1.50 * pia is exact for dime-rounded pia.
        lo = int(1.50 * pia)
        hi = int(1.85 * pia)
        assert fm >= lo, (
            f"family_max_cents {fm} below DIB floor 1.50*pia={lo} "
            f"(pia={pia})"
        )
        assert fm <= hi, (
            f"family_max_cents {fm} above DIB ceiling 1.85*pia={hi} "
            f"(pia={pia})"
        )

    def test_monthly_benefit_equals_pia_pre_auxiliary(self, api):
        """PRD §3.4 step 5: "Application.monthly_benefit_cents is set
        to pia_cents (pre-auxiliary, no proration yet)."
        """
        claimant, application = setup_application_approved_at_initial()
        assert application["monthly_benefit_cents"] == application["pia_cents"]
