"""Composite setup helpers for the Property Tax Assessment & Appeal API.

Each test runs against a freshly restarted, empty server, so every helper builds
its preconditions from scratch using only PRD-declared endpoints. Helpers use the
lenient get_success_data() so setup failures surface as clear "Setup failed".

Identity threading: Taxpayer is entity-backed (PRD §2.1). After creating an Owner,
ownership-gated Taxpayer calls use make_taxpayer_headers(owner["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_hearing_officer_headers,
    make_taxpayer_headers,
)
from . import factories as f

ASSESSOR = TEST_USERS["assessor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitive creators
# ---------------------------------------------------------------------------
def create_owner(**overrides) -> dict:
    return get_success_data(api_client.create_owner(f.create_owner_payload(**overrides), ASSESSOR))


def create_open_roll(**overrides) -> dict:
    """Create a tax roll and transition it DRAFT -> OPEN. Returns the OPEN roll."""
    roll = get_success_data(api_client.create_tax_roll(f.create_tax_roll_payload(**overrides), ASSESSOR))
    return get_success_data(api_client.open_tax_roll(roll["id"], ASSESSOR))


def create_parcel(owner_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_parcel(f.create_parcel_payload(owner_id, **overrides), ASSESSOR)
    )


def create_assessment(parcel_id, tax_roll_id, market_value, **overrides) -> dict:
    return get_success_data(
        api_client.create_assessment(
            f.create_assessment_payload(parcel_id, tax_roll_id, market_value, **overrides), ASSESSOR
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: assessment state progression
# ---------------------------------------------------------------------------
def setup_owner_roll_parcel(owner_overrides=None, roll_overrides=None, parcel_overrides=None):
    """Owner + OPEN roll + ACTIVE parcel. Returns (owner, roll, parcel)."""
    owner = create_owner(**(owner_overrides or {}))
    roll = create_open_roll(**(roll_overrides or {}))
    parcel = create_parcel(owner["id"], **(parcel_overrides or {}))
    return owner, roll, parcel


def setup_draft_assessment(market_value=100000, reassessment_event="NONE",
                           owner_overrides=None, roll_overrides=None, parcel_overrides=None):
    """Owner + OPEN roll + ACTIVE parcel + one DRAFT assessment.
    Returns (owner, roll, parcel, assessment)."""
    owner, roll, parcel = setup_owner_roll_parcel(owner_overrides, roll_overrides, parcel_overrides)
    assessment = create_assessment(parcel["id"], roll["id"], market_value,
                                   reassessment_event=reassessment_event)
    return owner, roll, parcel, assessment


def setup_noticed_assessment(market_value=100000, reassessment_event="SALE",
                             notice_headers=None,
                             owner_overrides=None, roll_overrides=None, parcel_overrides=None):
    """DRAFT assessment driven to NOTICED (no exemptions).
    notice_headers lets a test pin the noticing operator id for segregation-of-duties.
    Returns (owner, roll, parcel, assessment) where assessment is the NOTICED record."""
    owner, roll, parcel, assessment = setup_draft_assessment(
        market_value, reassessment_event, owner_overrides, roll_overrides, parcel_overrides
    )
    noticed = get_success_data(
        api_client.notice_assessment(assessment["id"], notice_headers or ASSESSOR)
    )
    return owner, roll, parcel, noticed


def setup_final_assessment(market_value=100000, reassessment_event="SALE",
                           owner_overrides=None, roll_overrides=None, parcel_overrides=None):
    """Assessment driven to FINAL (no exemptions, no appeal).
    Returns (owner, roll, parcel, assessment)."""
    owner, roll, parcel, noticed = setup_noticed_assessment(
        market_value, reassessment_event, None, owner_overrides, roll_overrides, parcel_overrides
    )
    final = get_success_data(api_client.finalize_assessment(noticed["id"], ASSESSOR))
    return owner, roll, parcel, final


def setup_certified_parcel(prior_capped_base=100000, roll_overrides=None,
                           owner_overrides=None, parcel_overrides=None):
    """Build a parcel whose last_certified_capped_base == prior_capped_base.

    Creates roll R1 (OPEN), one assessment at market==prior_capped_base with
    reassessment_event NONE (first-ever -> market_rebase, so capped_base == market),
    notices + finalizes it, then certifies R1 (copies capped_base into the parcel).
    Returns (owner, roll1, parcel)."""
    owner = create_owner(**(owner_overrides or {}))
    r1_over = dict(tax_year=2025)
    r1_over.update(roll_overrides or {})
    roll1 = create_open_roll(**r1_over)
    parcel = create_parcel(owner["id"], **(parcel_overrides or {}))
    asmt = create_assessment(parcel["id"], roll1["id"], prior_capped_base,
                             reassessment_event="NONE")
    get_success_data(api_client.notice_assessment(asmt["id"], ASSESSOR))
    get_success_data(api_client.finalize_assessment(asmt["id"], ASSESSOR))
    roll1 = get_success_data(api_client.certify_tax_roll(roll1["id"], ASSESSOR))
    return owner, roll1, parcel


def setup_successor_open_roll(prior_capped_base=100000, growth_cap_pct=0.02, mill_rate=10.0):
    """Certified parcel (last_certified_capped_base==prior_capped_base) plus a
    successor OPEN roll R2 rolling forward from R1.
    Returns (owner, roll1, parcel, roll2)."""
    owner, roll1, parcel = setup_certified_parcel(
        prior_capped_base=prior_capped_base,
        roll_overrides={"growth_cap_pct": growth_cap_pct, "mill_rate": mill_rate},
    )
    roll2 = create_open_roll(
        tax_year=2026, mill_rate=mill_rate, growth_cap_pct=growth_cap_pct,
        prior_roll_id=roll1["id"],
    )
    return owner, roll1, parcel, roll2


# ---------------------------------------------------------------------------
# Tier 2: exemptions
# ---------------------------------------------------------------------------
def claim_exemption(assessment_id, exemption_type, headers=None) -> dict:
    return get_success_data(
        api_client.create_exemption(
            f.create_exemption_payload(assessment_id, exemption_type), headers or ASSESSOR
        )
    )


def setup_draft_assessment_with_claimed_exemption(exemption_type, market_value=100000,
                                                  reassessment_event="NONE",
                                                  owner_overrides=None, parcel_overrides=None,
                                                  roll_overrides=None):
    """DRAFT assessment + one CLAIMED exemption of the given type.
    Returns (owner, roll, parcel, assessment, exemption)."""
    owner, roll, parcel, assessment = setup_draft_assessment(
        market_value, reassessment_event, owner_overrides, roll_overrides, parcel_overrides
    )
    exemption = claim_exemption(assessment["id"], exemption_type)
    return owner, roll, parcel, assessment, exemption


# ---------------------------------------------------------------------------
# Tier 3: appeals lifecycle
# ---------------------------------------------------------------------------
def file_appeal(assessment, owner_id, requested_taxable_value=80000):
    """File an appeal against a NOTICED assessment using the assessment's current
    version as expected_assessment_version. Returns the FILED appeal."""
    payload = f.create_appeal_payload(
        assessment["id"], owner_id, requested_taxable_value, assessment["version"]
    )
    return get_success_data(api_client.create_appeal(payload, make_taxpayer_headers(owner_id)))


def setup_filed_appeal(requested_taxable_value=80000, market_value=100000,
                       notice_operator_id="assessor-notice-op"):
    """NOTICED assessment + one FILED appeal (assessment now UNDER_APPEAL).
    The assessment is noticed by an explicit operator id so a distinct hearing
    officer can later accept it (segregation of duties).
    Returns (owner, roll, parcel, assessment, appeal)."""
    from .test_users import make_assessor_headers
    owner, roll, parcel, noticed = setup_noticed_assessment(
        market_value=market_value, reassessment_event="SALE",
        notice_headers=make_assessor_headers(notice_operator_id),
    )
    appeal = file_appeal(noticed, owner["id"], requested_taxable_value)
    return owner, roll, parcel, noticed, appeal


def setup_under_review_appeal(requested_taxable_value=80000, market_value=100000,
                              hearing_officer_id="hearing-officer-1",
                              notice_operator_id="assessor-notice-op"):
    """FILED appeal accepted by a HearingOfficer distinct from the noticing operator,
    so the appeal is UNDER_REVIEW.
    Returns (owner, roll, parcel, assessment, appeal, hearing_officer_id)."""
    owner, roll, parcel, noticed, appeal = setup_filed_appeal(
        requested_taxable_value, market_value, notice_operator_id
    )
    appeal = get_success_data(
        api_client.accept_appeal(appeal["id"], make_hearing_officer_headers(hearing_officer_id))
    )
    return owner, roll, parcel, noticed, appeal, hearing_officer_id


def setup_appeal_with_held_hearing(requested_taxable_value=80000, market_value=100000,
                                   hearing_officer_id="hearing-officer-1",
                                   notice_operator_id="assessor-notice-op"):
    """UNDER_REVIEW appeal with a HELD hearing (unlocks grant/deny).
    Returns (owner, roll, parcel, assessment, appeal, hearing, hearing_officer_id)."""
    owner, roll, parcel, noticed, appeal, ho_id = setup_under_review_appeal(
        requested_taxable_value, market_value, hearing_officer_id, notice_operator_id
    )
    ho_headers = make_hearing_officer_headers(ho_id)
    panel = get_success_data(api_client.create_board_panel(f.create_board_panel_payload(), ASSESSOR))
    hearing = get_success_data(
        api_client.create_hearing(
            f.create_hearing_payload(
                appeal["id"], panel["id"], ho_id,
                "2026-07-01T10:00:00.000Z", "2026-07-01T11:00:00.000Z",
            ),
            ho_headers,
        )
    )
    hearing = get_success_data(api_client.hold_hearing(hearing["id"], ho_headers))
    return owner, roll, parcel, noticed, appeal, hearing, ho_id


def setup_scheduled_hearing(market_value=100000, panel_overrides=None,
                            starts_at="2026-07-01T10:00:00.000Z",
                            ends_at="2026-07-01T11:00:00.000Z",
                            hearing_officer_id="hearing-officer-1",
                            notice_operator_id="assessor-notice-op"):
    """UNDER_REVIEW appeal with a SCHEDULED (not held) hearing on a panel.
    Returns (owner, roll, parcel, assessment, appeal, panel, hearing, hearing_officer_id)."""
    owner, roll, parcel, noticed, appeal, ho_id = setup_under_review_appeal(
        market_value=market_value, hearing_officer_id=hearing_officer_id,
        notice_operator_id=notice_operator_id,
    )
    ho_headers = make_hearing_officer_headers(ho_id)
    panel = get_success_data(
        api_client.create_board_panel(
            f.create_board_panel_payload(**(panel_overrides or {})), ASSESSOR
        )
    )
    hearing = get_success_data(
        api_client.create_hearing(
            f.create_hearing_payload(appeal["id"], panel["id"], ho_id, starts_at, ends_at),
            ho_headers,
        )
    )
    return owner, roll, parcel, noticed, appeal, panel, hearing, ho_id


# ---------------------------------------------------------------------------
# Tier 4: deferral ledger / accumulation
# ---------------------------------------------------------------------------
def setup_deferral_with_principal(principal_market=200000, annual_interest_rate=0.05,
                                  owner_overrides=None):
    """ACTIVE deferral with deferred_principal_cents == principal_market (one enrolled
    bill whose tax_amount_cents == principal_market, since mill_rate 10 on a SALE
    assessment makes tax_amount_cents == market_value).
    Returns (owner, roll, parcel, assessment, bill, deferral)."""
    o_over = {"birth_date": "1950-01-01T00:00:00.000Z"}
    o_over.update(owner_overrides or {})
    owner, roll, parcel, final = setup_final_assessment(
        market_value=principal_market, reassessment_event="SALE",
        owner_overrides=o_over, parcel_overrides={"is_primary_residence": True},
    )
    bill = get_success_data(api_client.issue_bill(final["id"], ASSESSOR))
    deferral = get_success_data(
        api_client.create_deferral(
            f.create_deferral_payload(parcel["id"], owner["id"], annual_interest_rate), ASSESSOR
        )
    )
    deferral = get_success_data(
        api_client.enroll_bill(deferral["id"], {"tax_bill_id": bill["id"]}, ASSESSOR)
    )
    return owner, roll, parcel, final, bill, deferral


def setup_deferral_with_accrual(principal_market=200000, annual_interest_rate=0.05,
                                owner_overrides=None):
    """ACTIVE deferral with principal enrolled and ONE accrual period run.
    With principal 200000 @0.05, the first accrual adds 10000 cents interest.
    Returns (owner, roll, parcel, assessment, bill, deferral) with the post-accrual
    deferral state."""
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_principal(
        principal_market, annual_interest_rate, owner_overrides
    )
    deferral = get_success_data(api_client.accrue_interest(deferral["id"], ASSESSOR))
    return owner, roll, parcel, final, bill, deferral


def setup_deferral_after_payment(principal_market=200000, annual_interest_rate=0.05,
                                 first_payment_cents=60000, owner_overrides=None):
    """ACTIVE deferral after principal enrolled, one accrual, and one applied payment.
    With first_payment_cents=60000 (10000 -> interest, 50000 -> principal), outstanding
    becomes 150000.
    Returns (owner, roll, parcel, assessment, bill, deferral)."""
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_accrual(
        principal_market, annual_interest_rate, owner_overrides
    )
    # POST /deferrals/{id}/payments returns the DeferralPayment event; re-fetch the
    # agreement for its post-payment ledger state and version.
    get_success_data(
        api_client.create_payment(
            deferral["id"],
            f.create_payment_payload(first_payment_cents, deferral["version"]),
            ASSESSOR,
        )
    )
    deferral = get_success_data(api_client.get_deferral(deferral["id"], ASSESSOR))
    return owner, roll, parcel, final, bill, deferral


def get_deferral(deferral_id) -> dict:
    return get_success_data(api_client.get_deferral(deferral_id, ASSESSOR))
