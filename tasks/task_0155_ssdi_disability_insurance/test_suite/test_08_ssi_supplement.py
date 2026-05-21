"""SSI Supplement creation, activation, exclusions and DIB offset.

Covers PRD §3.5 (ssi_calc) and difficulty-design rule 2 mode_c
(ssi_exclusion_spillover_then_dib_offset_mode_c).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    FBR_BY_LIVING_ARRANGEMENT,
    GENERAL_INCOME_EXCLUSION,
    SSI_RESOURCE_LIMIT_CENTS,
    TEST_USERS,
    activate_ssi,
    api_client,
    assert_ssi_supplement,
    create_claimant,
    create_ssi_supplement,
    create_ssi_supplement_payload,
    setup_application_approved_at_initial,
    setup_insured_claimant,
    validate_error,
    validate_success,
)


class TestSSICreation:

    def test_ssi_starts_in_draft(self, api):
        """PRD §3.5: "The supplement begins in status DRAFT."
        """
        claimant = setup_insured_claimant()
        resp = api.create_ssi_supplement(
            create_ssi_supplement_payload(
                claimant_id=claimant["id"],
                countable_income_cents=0,
                countable_resources_cents=100_00,
                living_arrangement="OWN_HOUSEHOLD",
            ),
            TEST_USERS["dds_examiner_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_ssi_supplement(data)
        assert data["status"] == "DRAFT"


class TestSSIResourceLimit:

    def test_activate_above_resource_limit_returns_resources_exceeded(self, api):
        """PRD §3.5: "Activation (DRAFT to ACTIVE) is exclusive to a
        DDS examiner and requires countable_resources_cents to be at
        most SSI_RESOURCE_LIMIT_CENTS (which is 200000 cents, that is
        $2,000 for an individual); otherwise the request is rejected
        with ERR_SSI_RESOURCES_EXCEEDED at HTTP status 422."
        """
        claimant = setup_insured_claimant()
        ss = create_ssi_supplement(
            claimant["id"],
            countable_resources_cents=SSI_RESOURCE_LIMIT_CENTS + 1,
        )
        resp = api.activate_ssi_supplement(
            ss["id"], TEST_USERS["dds_examiner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SSI_RESOURCES_EXCEEDED.value)

    def test_activate_at_exact_resource_limit_succeeds(self, api):
        """PRD §3.5: "requires countable_resources_cents to be at most
        SSI_RESOURCE_LIMIT_CENTS (which is 200000 cents, that is
        $2,000 for an individual)".

        Boundary: at exactly the limit, activation must succeed
        (resource gate alone).
        """
        claimant = setup_insured_claimant()
        ss = create_ssi_supplement(
            claimant["id"],
            countable_income_cents=0,
            countable_resources_cents=SSI_RESOURCE_LIMIT_CENTS,
        )
        result = activate_ssi(ss["id"])
        # PRD: when computed payment > 0 and resources within limit,
        # status is ACTIVE.
        assert result["status"] in (
            "ACTIVE", "TERMINATED_DIB_OFFSET",
            "TERMINATED_INCOME",
        ), (
            f"unexpected status after activation: {result['status']}"
        )


class TestSSIExclusionSpilloverModeC:
    """Difficulty design rule 2 mode_c."""

    def test_unearned_only_general_exclusion_applied(self, api):
        """# difficulty: combinatorial_formula/ssi_exclusion_spillover_then_dib_offset_mode_c

        PRD §3.5: "First, the unearned-income exclusion: subtract the
        lesser of unearned income and GENERAL_INCOME_EXCLUSION (which
        is 2000 cents, that is $20) from unearned income ... The
        countable income is the post-exclusion unearned income plus
        the halved post-exclusion earned income."
        PRD §3.5: "The Federal Benefit Rate is then looked up from
        FBR_BY_LIVING_ARRANGEMENT — 96700 cents ($967) for
        OWN_HOUSEHOLD".
        PRD §3.5: "The ssi_payment_cents is the FBR minus countable
        income, floored at zero."

        Scenario: unearned $900, earned 0, OWN_HOUSEHOLD ->
        countable = 900_00 - 20_00 = 88_000 cents
        payment = 96_700 - 88_000 = 8_700 cents
        """
        claimant = setup_insured_claimant()
        # Note: PRD says countable_income_cents is "Monthly countable
        # income in cents". The split between unearned/earned and the
        # exclusion math are described as operating on input
        # countable_income_cents. PRD §3.5 SSI math is built around the
        # input field countable_income_cents which holds unearned DIB.
        # We assume the PRD's worked example: countable_income_cents
        # is taken as unearned (no earned portion). The implementation
        # may choose either; we test only the inputs the PRD pin (no
        # earned income), so the spillover collapses cleanly.
        ss = create_ssi_supplement(
            claimant["id"],
            countable_income_cents=90_000,  # $900
            countable_resources_cents=100_00,
            living_arrangement="OWN_HOUSEHOLD",
        )
        result = activate_ssi(ss["id"])
        # Assert PRD-pinned formula: FBR(OWN_HOUSEHOLD)=96700
        # countable = max(0, 90000 - GENERAL_INCOME_EXCLUSION(2000)) = 88000
        # ssi_payment = max(0, 96700 - 88000) = 8700
        expected_payment = 8_700
        assert result["ssi_payment_cents"] == expected_payment, (
            f"PRD §3.5 SSI formula expects {expected_payment}, "
            f"got {result['ssi_payment_cents']}"
        )
        assert result["status"] == "ACTIVE", (
            f"non-zero ssi_payment_cents should yield ACTIVE; got "
            f"{result['status']}"
        )

    def test_zero_payment_with_dib_yields_dib_offset(self, api):
        """# difficulty: combinatorial_formula/ssi_exclusion_spillover_then_dib_offset_mode_c

        PRD §3.5: "If the computed payment is zero and the claimant
        has a live DIB benefit, activation does not move the
        supplement to ACTIVE; it instead places it directly into
        TERMINATED_DIB_OFFSET."

        Scenario: countable_income = $997, FBR(OWN_HOUSEHOLD)=$967,
        so countable_after_exclusion = $997 - $20 = $977,
        ssi_payment = max(0, 967_00 - 977_00) = 0
        Claimant has a live DIB -> status := TERMINATED_DIB_OFFSET.
        """
        # Establish DIB benefit by approving an application.
        claimant, application = setup_application_approved_at_initial()
        ss = create_ssi_supplement(
            claimant["id"],
            countable_income_cents=997_00,
            countable_resources_cents=100_00,
            living_arrangement="OWN_HOUSEHOLD",
        )
        result = activate_ssi(ss["id"])
        assert result["ssi_payment_cents"] == 0
        assert result["status"] == "TERMINATED_DIB_OFFSET", (
            f"zero SSI payment + live DIB -> TERMINATED_DIB_OFFSET; "
            f"got {result['status']}"
        )

    def test_fbr_by_living_arrangement_another_household(self, api):
        """PRD §3.5: "64470 cents ($644.70, reduced by one-third) for
        ANOTHER_HOUSEHOLD".
        """
        claimant = setup_insured_claimant()
        # countable=0 -> ssi_payment = FBR for ANOTHER_HOUSEHOLD
        ss = create_ssi_supplement(
            claimant["id"],
            countable_income_cents=0,
            countable_resources_cents=100_00,
            living_arrangement="ANOTHER_HOUSEHOLD",
        )
        result = activate_ssi(ss["id"])
        assert result["ssi_payment_cents"] == FBR_BY_LIVING_ARRANGEMENT["ANOTHER_HOUSEHOLD"]
        assert result["status"] == "ACTIVE"

    def test_fbr_by_living_arrangement_institution(self, api):
        """PRD §3.5: "3000 cents ($30 personal-needs allowance) for
        INSTITUTION".
        """
        claimant = setup_insured_claimant()
        ss = create_ssi_supplement(
            claimant["id"],
            countable_income_cents=0,
            countable_resources_cents=100_00,
            living_arrangement="INSTITUTION",
        )
        result = activate_ssi(ss["id"])
        assert result["ssi_payment_cents"] == FBR_BY_LIVING_ARRANGEMENT["INSTITUTION"]
