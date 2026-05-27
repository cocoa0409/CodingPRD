"""Calculations corner cases: low-AIME PIA tier-1 only; CA state supplement;
child auxiliary base amount; CDR MIE default schedule."""
import pytest
from test_helpers import (
    validate_success, get_success_data, api_client, TEST_USERS,
    set_clock,
    setup_application_awarded,
    create_child_auxiliary,
    fetch_cdr_for_award,
)


# =========================================================================
# Instance: pia_low_aime_only_tier1_applies
# =========================================================================

def test_pia_low_aime_only_tier1_applies(api):
    """PRD §3.6: "The PIA in cents is the sum of three rounded tier
    contributions: 0.90 of the first tier rounded half up to the nearest
    cent, plus 0.32 of the second tier rounded half up to the nearest
    cent, plus 0.15 of the third tier rounded half up to the nearest
    cent."

    Design: Corner/calculations/pia_low_aime_only_tier1_applies
    """
    set_clock("2026-01-15T00:00:00Z")
    # 12 years * 1_200_000 → AIME = 100000, all in tier1.
    # PIA = round(0.9 * 100000) = 90000.
    ctx = setup_application_awarded(
        claimant_overrides={
            "ssn_last4": "2001",
            "full_name": "Low PIA",
            "date_of_birth": "1980-01-01T00:00:00Z",
            "filing_state": "TX",
        },
        earnings_cents=1_200_000,
        medical_clock_override="2026-04-15T00:00:00Z",
    )
    award = ctx["award"]
    assert award["primary_insurance_amount_cents"] == 90_000, \
        f"Expected PIA=90000 (tier1-only), got {award['primary_insurance_amount_cents']}"
    assert award["monthly_benefit_cents"] == 90_000


# =========================================================================
# Instance: ssi_state_supplement_ca_value
# =========================================================================

def test_ssi_state_supplement_ca_value(api):
    """PRD §3.7: "Finally, `state_supplement_cents` is read from a lookup
    table keyed by the claimant's `filing_state`: California adds 2050
    cents, New York adds 8700 cents, and every other state adds 0 cents."

    Design: Corner/calculations/ssi_state_supplement_ca_value
    """
    set_clock("2026-01-15T00:00:00Z")
    ctx = setup_application_awarded(
        claimant_overrides={
            "ssn_last4": "2002",
            "full_name": "CA Sup",
            "date_of_birth": "1980-01-01T00:00:00Z",
            "filing_state": "CA",
            "monthly_income_cents": 0,
            "countable_resources_cents": 100_000,
        },
        application_overrides={
            "alleged_onset_date": "2024-01-01T00:00:00Z",
            "protective_filing_date": "2026-01-15T00:00:00Z",
            "claim_type": "CONCURRENT_SSDI_SSI",
        },
        earnings_cents=1_200_000,
        medical_clock_override="2026-04-15T00:00:00Z",
    )
    app = ctx["application"]
    res = api_client.list_ssi_supplements(TEST_USERS["benefits_admin_headers"],
                                            params={"application_id": app["id"]})
    sups = get_success_data(res)
    assert len(sups) == 1
    sup = sups[0]
    assert sup["state_supplement_cents"] == 2050, \
        f"Expected CA state_supplement=2050, got {sup['state_supplement_cents']}"
    assert sup["status"] == "ACTIVE"


# =========================================================================
# Instance: child_auxiliary_amount_full_base_with_headroom
# =========================================================================

def test_child_auxiliary_amount_full_base_with_headroom(api):
    """PRD §3.8: "The base monthly auxiliary amount is half the primary
    insurance amount, computed as the award's
    `primary_insurance_amount_cents` multiplied by 0.50, rounded half up
    to the nearest cent."
    PRD §3.8: "Otherwise the auxiliary's `monthly_amount_cents` is the
    smaller of the base amount and the available headroom"

    Design: Corner/calculations/child_auxiliary_amount_full_base_with_headroom
    """
    set_clock("2026-01-15T00:00:00Z")
    ctx = setup_application_awarded(
        claimant_overrides={
            "ssn_last4": "2003",
            "full_name": "First Child",
            "date_of_birth": "1980-01-01T00:00:00Z",
            "filing_state": "TX",
        },
        earnings_cents=4_800_000,
        medical_clock_override="2026-04-15T00:00:00Z",
    )
    award = ctx["award"]
    # PIA=196092, base=round(196092*0.50)=98046, family_max=round(196092*1.75)=343161.
    # headroom = 343161 - 196092 - 0 = 147069.
    # min(98046, 147069) = 98046.
    child = create_child_auxiliary(
        award["id"],
        expected_benefit_award_version=award["version"],
        child_full_name="Solo Child",
        child_date_of_birth="2015-01-01T00:00:00Z",
    )
    assert child["monthly_amount_cents"] == 98_046, \
        f"Expected base=98046 for PIA=196092, got {child['monthly_amount_cents']}"
    assert child["status"] == "ACTIVE"


# =========================================================================
# Instance: cdr_schedule_mie_default_18_months
# =========================================================================

def test_cdr_schedule_mie_default_18_months(api):
    """PRD §3.9: "The schedule depends on the medical improvement diary
    classification: when `diary_classification` is `MIE` (Medical
    Improvement Expected), the next review is set to 18 months from the
    current server time"
    PRD §3.9: "On first scheduling the diary defaults to `MIE`."

    Design: Corner/calculations/cdr_schedule_mie_default_18_months
    """
    set_clock("2026-01-15T00:00:00Z")
    ctx = setup_application_awarded(
        claimant_overrides={
            "ssn_last4": "2005",
            "full_name": "Mie Def",
            "date_of_birth": "1980-01-01T00:00:00Z",
            "filing_state": "TX",
        },
        earnings_cents=4_800_000,
    )
    cdr = fetch_cdr_for_award(ctx["award"]["id"])
    assert cdr["diary_classification"] == "MIE"
    # PRD §3.9 + §2.8: "scheduled_review_date" computed at day resolution
    # from NOW + 18 months. NOW at the moment of cascade-creation was
    # 2026-01-15 (no clock override). 2026-01-15 + 18 months = 2027-07-15.
    assert cdr["scheduled_review_date"].startswith("2027-07-15"), \
        f"Expected scheduled_review_date 2027-07-15, got {cdr['scheduled_review_date']}"
