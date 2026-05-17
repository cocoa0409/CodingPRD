"""Form 1099-R issuance, listing, box-value assembly, correction, and
voiding.

Coverage targets (PRD §3.9):
- box7_distribution_code mapping from distribution_reason:
  EARLY -> 1, NORMAL -> 7, RMD -> 7, DEATH -> 4, CONVERSION -> G,
  EXCESS_PENALTY -> 8.
- box2a_taxable_amount_cents:
  TRADITIONAL distribution -> gross; ROTH distribution -> 0;
  CONVERSION backdoor=true -> 0; CONVERSION backdoor=false -> gross.
- Listing excludes VOIDED forms.
- Void requires the underlying source event to be REVERSED (only
  EXCESS_PENALTY whose backing ContributionEvent was reversed).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_form_1099r,
    create_distribution_payload,
    create_participant_born,
    get_clock_state,
    list_forms_1099r,
    open_account,
    post_contribution,
    setup_owner_rmd_eligible,
    take_distribution,
    validate_error,
    validate_success,
)


# ===========================================================================
# Distribution -> 1099-R box rules — PRD §3.9
# ===========================================================================
class TestDistributionFormRules:

    def test_normal_distribution_yields_box7_seven_and_traditional_box2a(
        self, api, custodian_headers,
    ):
        """PRD §3.9: "box7_distribution_code is 1 when the underlying
        distribution_reason is EARLY, 7 when it is NORMAL or RMD, and
        4 when it is DEATH. box2a_taxable_amount_cents equals the
        gross amount when the source account is TRADITIONAL".

        Claim: NORMAL distribution from TRADITIONAL -> box7=7 and
        box2a == gross.
        """
        p = create_participant_born(1960)
        a = open_account(p["id"], account_type="TRADITIONAL")
        post_contribution(a["id"], amount_cents=300_000)
        take_distribution(a["id"], gross_amount_cents=100_000,
                          distribution_reason="NORMAL")
        clock = get_clock_state()
        ty = int(clock.get("clock_year",
                           clock.get("current_year", 2026)))
        forms, _ = list_forms_1099r(p["id"], tax_year=ty)
        dist_forms = [
            f for f in forms
            if f.get("source_event_type") == "DISTRIBUTION"
        ]
        assert len(dist_forms) >= 1
        f = dist_forms[0]
        assert_form_1099r(f)
        assert str(f["box7_distribution_code"]) == "7"
        assert f["box2a_taxable_amount_cents"] == 100_000
        assert f["box1_gross_distribution_cents"] == 100_000

    def test_early_distribution_yields_box7_one(self, api,
                                                custodian_headers):
        """PRD §3.9: "box7_distribution_code is 1 when the underlying
        distribution_reason is EARLY".

        Claim: EARLY distribution -> box7 == "1".
        """
        p = create_participant_born(1990)  # under 59
        a = open_account(p["id"], account_type="TRADITIONAL")
        post_contribution(a["id"], amount_cents=500_000)
        take_distribution(a["id"], gross_amount_cents=100_000,
                          distribution_reason="EARLY")
        clock = get_clock_state()
        ty = int(clock.get("clock_year",
                           clock.get("current_year", 2026)))
        forms, _ = list_forms_1099r(p["id"], tax_year=ty)
        dist_forms = [
            f for f in forms
            if f.get("source_event_type") == "DISTRIBUTION"
        ]
        assert len(dist_forms) >= 1
        # PRD §3.9 distribution-form rules; locate the EARLY-coded form.
        early = [
            f for f in dist_forms
            if str(f.get("box7_distribution_code")) == "1"
        ]
        assert len(early) >= 1, (
            f"expected at least one box7='1' form, got {dist_forms}"
        )

    def test_death_distribution_yields_box7_four(self, api,
                                                 custodian_headers):
        """PRD §3.9: "4 when it is DEATH".

        Claim: DEATH distribution -> box7 == "4".
        """
        p = create_participant_born(1960)
        a = open_account(p["id"], account_type="TRADITIONAL")
        post_contribution(a["id"], amount_cents=500_000)
        take_distribution(a["id"], gross_amount_cents=100_000,
                          distribution_reason="DEATH")
        clock = get_clock_state()
        ty = int(clock.get("clock_year",
                           clock.get("current_year", 2026)))
        forms, _ = list_forms_1099r(p["id"], tax_year=ty)
        death = [
            f for f in forms
            if f.get("source_event_type") == "DISTRIBUTION"
            and str(f.get("box7_distribution_code")) == "4"
        ]
        assert len(death) >= 1, (
            f"expected at least one box7='4' DEATH form, got {forms}"
        )

    def test_rmd_distribution_yields_box7_seven_and_box4_matches_withholding(
        self, api, custodian_headers,
    ):
        """PRD §3.9: "7 when it is NORMAL or RMD. ...
        box4_federal_withholding_cents equals the distribution's
        federal_withholding_cents."

        Claim: RMD distribution -> box7=='7' and
        box4 == DistributionEvent.federal_withholding_cents.
        """
        p, a = setup_owner_rmd_eligible(
            target_age_on_dec31=73,
            prior_year_end_balance_cents=10_000_000,
        )
        rmd_d = take_distribution(
            a["id"], gross_amount_cents=377_358,
            distribution_reason="RMD",
        )
        # The setup fixture advances the clock several years to seed
        # prior_year_end_balance_cents; the RMD distribution's tax_year
        # equals the live clock_year, not a hard-coded 2026.
        clock = get_clock_state()
        ty = int(clock.get("clock_year",
                           clock.get("current_year", 2026)))
        forms, _ = list_forms_1099r(p["id"], tax_year=ty)
        rmd_forms = [
            f for f in forms
            if f.get("source_event_type") == "DISTRIBUTION"
            and str(f.get("box7_distribution_code")) == "7"
        ]
        assert len(rmd_forms) >= 1
        f = rmd_forms[0]
        assert f["box4_federal_withholding_cents"] == \
            rmd_d["federal_withholding_cents"]


# ===========================================================================
# Voided form excluded from list — PRD §3.9
#
# DELETED per Step 7 STEP 1b (unreachable scenario):
# PRD §3.9 says a form may be voided only when its underlying source
# event has been reversed, which is only possible for an EXCESS_PENALTY
# form whose backing ContributionEvent was reversed. But PRD §3.3's cap
# check rejects any over-cap posting at creation time, so no in-PRD
# path produces an EXCESS_PENALTY Form1099R whose backing contribution
# is reversible. The list-excludes-voided assertion cannot be exercised
# without PRD-silent state injection. The list-exclusion rule itself
# remains documented in PRD §3.9 but has no test-reachable trigger
# under a faithful implementation.
# ===========================================================================


# ===========================================================================
# Void precondition — PRD §3.9
# ===========================================================================
class TestVoidPrecondition:

    def test_void_distribution_form_rejected(
        self, api, custodian_headers, compliance_headers,
    ):
        """PRD §3.9: "A ComplianceOfficer may void a form
        (transitioning either ISSUED → VOIDED or CORRECTED → VOIDED),
        but only when the underlying source event has been reversed —
        which is only possible for an EXCESS_PENALTY form whose
        backing ContributionEvent was reversed."

        Claim: voiding a DISTRIBUTION-sourced 1099-R (whose source
        event cannot be 'reversed' per the contract) -> ERR_INVALID_STATE.
        """
        p = create_participant_born(1960)
        a = open_account(p["id"], account_type="TRADITIONAL")
        post_contribution(a["id"], amount_cents=300_000)
        take_distribution(a["id"], gross_amount_cents=100_000,
                          distribution_reason="NORMAL")
        clock = get_clock_state()
        ty = int(clock.get("clock_year",
                           clock.get("current_year", 2026)))
        forms, _ = list_forms_1099r(p["id"], tax_year=ty)
        dist_forms = [
            f for f in forms
            if f.get("source_event_type") == "DISTRIBUTION"
        ]
        assert len(dist_forms) >= 1
        target = dist_forms[0]
        resp = api.void_form_1099r(target["id"], compliance_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
