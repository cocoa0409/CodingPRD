"""FPL percentage computation and eligibility decision boundary tests.

Exercises PRD §3.2 (FPL computation) and PRD §3.3 (eligibility decision
preconditions).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_applicant,
    add_income,
    create_application,
    create_household,
    create_state_policy,
    decide_application,
    decide_application_payload,
    get_application,
    get_household,
    setup_basic_household,
    setup_eligible_application,
    submit_application,
    validate_error,
    validate_success,
)


# ===========================================================================
# Effective size and fpl_threshold — PRD §3.2
# ===========================================================================
class TestEffectiveSize:

    def test_fpl_threshold_amount_formula(self, api, intake_worker_headers):
        """PRD §3.2: "the FPL threshold amount is computed as
        fpl_base_amount plus the quantity (effective size minus one)
        multiplied by fpl_per_member_amount."

        Claim: with fpl_base=15000, fpl_per_member=5000 and 3 non-
        EXCLUDED applicants, fpl_threshold = 15000 + 2*5000 = 25000.
        """
        _sp, household, _ = setup_basic_household(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
            },
            applicants=[
                {"dependent_status": "PRIMARY"},
                {"dependent_status": "SPOUSE"},
                {"dependent_status": "DEPENDENT"},
            ],
        )
        h = get_household(household["id"])
        assert float(h["fpl_threshold_amount"]) == pytest.approx(25_000.00), (
            "fpl_threshold_amount must be fpl_base + (size-1)*fpl_per_member "
            f"per PRD §3.2; expected 25000, got {h['fpl_threshold_amount']}"
        )

    def test_excluded_does_not_contribute_to_threshold(
            self, api, intake_worker_headers):
        """PRD §3.2: "an effective household size is computed as the
        count of Applicants whose dependent_status is not EXCLUDED, plus
        the count of applicants whose is_pregnant flag is true."

        Claim: a household with one PRIMARY and one EXCLUDED applicant
        has effective_size=1 and fpl_threshold = fpl_base.
        """
        _sp, household, _ = setup_basic_household(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
            },
            applicants=[
                {"dependent_status": "PRIMARY"},
                {"dependent_status": "EXCLUDED"},
            ],
        )
        h = get_household(household["id"])
        assert float(h["fpl_threshold_amount"]) == pytest.approx(15_000.00), (
            "EXCLUDED applicants must NOT contribute to fpl_threshold "
            f"per PRD §3.2; expected 15000, got {h['fpl_threshold_amount']}"
        )


# ===========================================================================
# fpl_percent rounding — PRD §3.2, §2.6
# ===========================================================================
class TestFplPercentRounding:

    def test_fpl_percent_round_half_up_two_decimals(
            self, api, intake_worker_headers):
        """PRD §3.2: "that raw percentage is rounded to two decimal
        places using the round-half-up rule, and the rounded value is
        what the system stores as fpl_percent and snapshots into
        snapshot_fpl_percent."

        Claim: with fpl_base=15000, fpl_per_member=5000, 2 applicants
        (threshold=20000), wages=27601 → raw_pct = 27601/20000*100 =
        138.005 → HALF_UP → 138.01.

        # difficulty: boundary_precision_check/fpl_percent_inclusive_ceiling
        """
        _sp, household, _, application = setup_eligible_application(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
            },
            rule_variant="STATE",
            applicants=[
                {"dependent_status": "PRIMARY"},
                {"dependent_status": "SPOUSE"},
            ],
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 27_601.00, "frequency": "ANNUAL"},
            ],
        )
        assert float(application["snapshot_fpl_percent"]) == pytest.approx(
            138.01
        ), (
            "27601/20000*100 = 138.005 must HALF_UP to 138.01 per PRD §3.2; "
            f"got snapshot_fpl_percent={application['snapshot_fpl_percent']}"
        )


# ===========================================================================
# Eligibility comparison (inclusive ceiling) — PRD §3.2, §3.3
# ===========================================================================
class TestEligibilityCeiling:

    def test_at_ceiling_is_eligible(self, api):
        """PRD §3.2: "the household is fiscally eligible when fpl_percent
        is less than or equal to magi_income_limit_pct (inclusive at
        the ceiling)."

        Claim: with magi_limit=138.0 and snapshot_fpl_percent=138.00,
        /decide APPROVE succeeds.

        # difficulty: boundary_precision_check/fpl_percent_inclusive_ceiling
        """
        _sp, household, _, application = setup_eligible_application(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
            },
            rule_variant="STATE",
            applicants=[
                {"dependent_status": "PRIMARY"},
                {"dependent_status": "SPOUSE"},
            ],
            incomes=[
                # 27600/20000*100 = 138.00 (exact, at the ceiling).
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 27_600.00, "frequency": "ANNUAL"},
            ],
        )
        assert float(application["snapshot_fpl_percent"]) == pytest.approx(
            138.00
        )
        determination = decide_application(
            household=household, application=application, decision="APPROVE",
        )
        assert determination["outcome"] == "ELIGIBLE", (
            "fpl_percent==magi_income_limit_pct must be ELIGIBLE per "
            f"PRD §3.2; got outcome={determination['outcome']!r}"
        )

    def test_above_ceiling_returns_not_eligible(self, api):
        """PRD §3.3: "the application's snapshot_fpl_percent is at most
        the household's StatePolicy.magi_income_limit_pct ... otherwise
        ERR_NOT_ELIGIBLE."

        Claim: with magi_limit=138.0 and snapshot_fpl_percent=138.01,
        /decide APPROVE returns ERR_NOT_ELIGIBLE (422).
        """
        _sp, household, _, application = setup_eligible_application(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
            },
            rule_variant="STATE",
            applicants=[
                {"dependent_status": "PRIMARY"},
                {"dependent_status": "SPOUSE"},
            ],
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 27_601.00, "frequency": "ANNUAL"},
            ],
        )
        res = api.decide_application(
            household["id"], application["id"],
            decide_application_payload(decision="APPROVE"),
            headers=TEST_USERS["eligibility_caseworker_headers"],
        )
        validate_error(res, "ERR_NOT_ELIGIBLE")
