"""Composite setup helpers for the Pension DB Administration API.

Every helper builds its preconditions from scratch via PRD-declared endpoints,
because the server's database is empty at the start of each test. Helpers use
get_success_data() (lenient) so a setup failure surfaces as a clear "Setup failed".

The canonical "330000 gross" participant: a FAP plan with fap_accrual_rate=0.015,
a participant hired 2000-01-01 / DOB 1962-01-01, terminated 2024-01-01 (24.0y
credited service, FULLY_VESTED, vested_pct 1.0), and three comp rows
(2021:10M, 2022:11M, 2023:12M) so final_average_pay_cents = (10M+11M+12M)/3
= 11,000,000. gross = round(11,000,000 * 0.015 * 24.0 * 1.0 / 12) = 330000.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_payload,
    create_participant_payload,
    create_compensation_payload,
    create_filing_payload,
    create_election_payload,
    create_qdro_payload,
    create_spousal_consent_payload,
    certify_payload,
)
from .test_users import TEST_USERS, make_benefits_admin_headers

_SPONSOR = TEST_USERS["plan_sponsor_headers"]
_ACTUARY = TEST_USERS["plan_actuary_headers"]
_ADMIN = TEST_USERS["benefits_admin_headers"]
_ADM_A = TEST_USERS["benefits_admin_a_headers"]
_ADM_B = TEST_USERS["benefits_admin_b_headers"]


# ----------------------------------------------------------------------------
# Tier 1: plan + participant primitives
# ----------------------------------------------------------------------------
def create_plan(**overrides) -> dict:
    """Create an ACTIVE plan. Default FAP, fap_accrual_rate 0.015, cola 0.0."""
    resp = api_client.create_plan(create_plan_payload(**overrides), _SPONSOR)
    return get_success_data(resp)


def create_participant(plan_id, **overrides) -> dict:
    resp = api_client.create_participant(create_participant_payload(plan_id, **overrides), _ADMIN)
    return get_success_data(resp)


def add_compensation(participant_id, plan_year, gross_comp_cents) -> dict:
    resp = api_client.create_compensation(
        create_compensation_payload(participant_id, plan_year, gross_comp_cents), _ADMIN
    )
    return get_success_data(resp)


def terminate_participant(participant_id, termination_date) -> dict:
    resp = api_client.terminate_participant(
        participant_id, _ADMIN, {"termination_date": termination_date}
    )
    return get_success_data(resp)


def add_standard_comp_330k(participant_id):
    """Three comp rows (10M/11M/12M for 2021/2022/2023) -> FAP 11,000,000."""
    add_compensation(participant_id, 2021, 10_000_000)
    add_compensation(participant_id, 2022, 11_000_000)
    add_compensation(participant_id, 2023, 12_000_000)


# ----------------------------------------------------------------------------
# Tier 1/2: a TERMINATED FULLY_VESTED participant producing gross 330000
# ----------------------------------------------------------------------------
def setup_terminated_vested_participant_330k(plan_id=None, **plan_overrides):
    """Return (plan, participant). Participant is TERMINATED, FULLY_VESTED, FAP 11M.

    A subsequent SINGLE_LIFE election submitted on this participant yields
    gross_accrued_monthly_cents == 330000.
    """
    if plan_id is None:
        plan = create_plan(**plan_overrides)
        plan_id = plan["id"]
    else:
        plan = None
    participant = create_participant(
        plan_id, date_of_birth="1962-01-01", hire_date="2000-01-01"
    )
    add_standard_comp_330k(participant["id"])
    participant = terminate_participant(participant["id"], "2024-01-01")
    return plan, participant


# ----------------------------------------------------------------------------
# Tier 3: election lifecycle shortcuts
# ----------------------------------------------------------------------------
def draft_election(participant_id, payment_form="SINGLE_LIFE",
                   annuity_start_date="2024-06-01", **overrides) -> dict:
    resp = api_client.create_election(
        create_election_payload(participant_id, payment_form, annuity_start_date, **overrides),
        _ADMIN,
    )
    return get_success_data(resp)


def submit_election(election_id, submitter_headers=None) -> dict:
    resp = api_client.submit_election(election_id, submitter_headers or _ADM_A)
    return get_success_data(resp)


def create_submitted_single_life_election(participant_id, submitter_headers=None,
                                          annuity_start_date="2024-06-01") -> dict:
    """Draft + submit a SINGLE_LIFE election. Returns the SUBMITTED election."""
    election = draft_election(participant_id, "SINGLE_LIFE", annuity_start_date)
    return submit_election(election["id"], submitter_headers or _ADM_A)


def create_approved_single_life_election(participant_id, submitter_headers=None,
                                         approver_headers=None,
                                         annuity_start_date="2024-06-01") -> dict:
    """Draft + submit (ADM_A) + approve (ADM_B) a SINGLE_LIFE election. Returns APPROVED."""
    election = create_submitted_single_life_election(
        participant_id, submitter_headers or _ADM_A, annuity_start_date
    )
    resp = api_client.approve_election(election["id"], approver_headers or _ADM_B)
    return get_success_data(resp)


def setup_commenced_single_life(plan_overrides=None):
    """Full lifecycle to a COMMENCED SINGLE_LIFE election (gross 330000).

    Returns (plan, participant, election, payment). The payment is in
    PENDING_SETUP; the participant is RETIRED (commence cascade).
    """
    plan_overrides = plan_overrides or {}
    plan, participant = setup_terminated_vested_participant_330k(**plan_overrides)
    election = create_approved_single_life_election(participant["id"])
    resp = api_client.commence_election(election["id"], _ADM_B)
    election = get_success_data(resp)
    payments = _list_payments_for_participant(participant["id"])
    payment = payments[0] if payments else None
    # Re-fetch participant for its post-commence (RETIRED) state.
    participant = get_success_data(api_client.get_participant(participant["id"], _ADMIN))
    return plan, participant, election, payment


def setup_in_pay_payment(plan_overrides=None):
    """Full lifecycle to an IN_PAY BenefitPayment (current 330000).

    Returns (plan, participant, election, payment). Plan honours plan_overrides
    (e.g. cola_pct).
    """
    plan, participant, election, payment = setup_commenced_single_life(plan_overrides)
    resp = api_client.activate_payment(payment["id"], _ADMIN)
    payment = get_success_data(resp)
    return plan, participant, election, payment


# ----------------------------------------------------------------------------
# Tier 3: QDRO helpers
# ----------------------------------------------------------------------------
def draft_qdro(participant_id, alternate_payee_kind="FORMER_SPOUSE",
               split_method="PERCENTAGE", **overrides) -> dict:
    resp = api_client.create_qdro(
        create_qdro_payload(participant_id, alternate_payee_kind, split_method, **overrides),
        _ADMIN,
    )
    return get_success_data(resp)


def create_submitted_percentage_qdro(participant_id, award_pct,
                                     alternate_payee_kind="FORMER_SPOUSE") -> dict:
    qdro = draft_qdro(participant_id, alternate_payee_kind, "PERCENTAGE", award_pct=award_pct)
    resp = api_client.submit_qdro(qdro["id"], _ADMIN)
    return get_success_data(resp)


def create_qualified_percentage_qdro(participant_id, award_pct,
                                     alternate_payee_kind="FORMER_SPOUSE") -> dict:
    qdro = create_submitted_percentage_qdro(participant_id, award_pct, alternate_payee_kind)
    resp = api_client.qualify_qdro(qdro["id"], _ADMIN)
    return get_success_data(resp)


# ----------------------------------------------------------------------------
# Tier 3: J&S / LUMP_SUM election helpers (for spousal-consent workflows)
# ----------------------------------------------------------------------------
def create_submitted_js_election(participant_id, js_survivor_pct=0.50,
                                 spouse_date_of_birth="1965-01-01",
                                 annuity_start_date="2024-06-01",
                                 submitter_headers=None) -> dict:
    """Draft + submit a JOINT_AND_SURVIVOR election (auto -> SPOUSAL_CONSENT_PENDING)."""
    election = draft_election(
        participant_id, "JOINT_AND_SURVIVOR", annuity_start_date,
        js_survivor_pct=js_survivor_pct, spouse_date_of_birth=spouse_date_of_birth,
    )
    resp = api_client.submit_election(election["id"], submitter_headers or _ADM_A)
    return get_success_data(resp)


def create_submitted_lump_sum_election(participant_id, annuity_start_date="2024-06-01",
                                       submitter_headers=None) -> dict:
    """Draft + submit a LUMP_SUM election (auto -> SPOUSAL_CONSENT_PENDING)."""
    election = draft_election(participant_id, "LUMP_SUM", annuity_start_date)
    resp = api_client.submit_election(election["id"], submitter_headers or _ADM_A)
    return get_success_data(resp)


def record_spousal_consent(election_id, consenting_spouse_dob, notary_reference="NOTARY-1",
                           waives_qjsa=True) -> dict:
    resp = api_client.create_spousal_consent(
        election_id,
        create_spousal_consent_payload(consenting_spouse_dob, notary_reference, waives_qjsa),
        _ADMIN,
    )
    return get_success_data(resp)


# ----------------------------------------------------------------------------
# Tier 4 / 5: filing certification + funded-status posture targeting
# ----------------------------------------------------------------------------
def create_filing(plan_id, plan_year, plan_assets_cents, funding_target_cents) -> dict:
    resp = api_client.create_filing(
        create_filing_payload(plan_id, plan_year, plan_assets_cents, funding_target_cents),
        _ACTUARY,
    )
    return get_success_data(resp)


def certify_filing(filing_id, expected_plan_version) -> dict:
    resp = api_client.certify_filing(filing_id, certify_payload(expected_plan_version), _ACTUARY)
    return get_success_data(resp)


def setup_plan_with_certified_aftap(plan_assets_cents, funding_target_cents,
                                    plan_year=2024, **plan_overrides):
    """Create a plan and certify one filing to drive funding_posture.

    Returns (plan, filing) where `plan` is re-fetched AFTER certification so its
    funding_posture / latest_certified_filing_id / version reflect the certify.
    """
    plan = create_plan(**plan_overrides)
    filing = create_filing(plan["id"], plan_year, plan_assets_cents, funding_target_cents)
    certify_filing(filing["id"], plan["version"])
    plan = get_success_data(api_client.get_plan(plan["id"], _ACTUARY))
    filing = get_success_data(api_client.get_filing(filing["id"], _ACTUARY))
    return plan, filing


def setup_frozen_plan(**plan_overrides):
    """Plan with a CERTIFIED filing at aftap 0.50 -> FROZEN. Returns (plan, filing)."""
    return setup_plan_with_certified_aftap(
        5_000_000_000, 10_000_000_000, plan_year=2024, **plan_overrides
    )


def setup_restricted_plan(**plan_overrides):
    """Plan with a CERTIFIED filing at aftap 0.65 -> RESTRICTED. Returns (plan, filing)."""
    return setup_plan_with_certified_aftap(
        6_500_000_000, 10_000_000_000, plan_year=2024, **plan_overrides
    )


# ----------------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------------
def _list_payments_for_participant(participant_id):
    resp = api_client.list_payments(_ADMIN, params={"participant_id": participant_id})
    # For a list endpoint (response_type "array") get_success_data returns the array.
    return get_success_data(resp)


def list_payments_for_participant(participant_id):
    """Public wrapper used by tests that need the payment list directly."""
    return _list_payments_for_participant(participant_id)
