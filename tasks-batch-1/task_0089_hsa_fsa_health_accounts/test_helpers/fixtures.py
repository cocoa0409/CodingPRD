"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server before each
test), so each helper builds its full precondition chain from PRD-declared endpoints.
All setup calls use get_success_data() so setup failures surface as clear "Setup failed"
errors rather than confusing assertion failures downstream.

Identity threading: a Participant's X-User-ID must equal the Participant entity's id on any
ownership-gated call, so claim filing/resubmit on behalf of a participant uses
make_participant_headers(participant["id"]). Opaque roles (PlanAdmin / Adjudicator /
FundDisburser) use the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, make_participant_headers, make_adjudicator_headers, make_disburser_headers,
)
from .factories import (
    create_participant_payload, create_plan_year_payload, create_account_payload,
    create_contribution_payload, create_claim_payload, create_batch_payload,
)
from .constants import (
    DEFAULT_CLOCK_IN_WINDOW, DEFAULT_CLOCK_PAST_DEADLINE,
)

ADMIN = TEST_USERS["plan_admin_headers"]


# --- Low-level primitives -------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_participant(**overrides):
    payload = create_participant_payload(**overrides)
    return get_success_data(api_client.create_participant(payload, ADMIN))


def create_plan_year(**overrides):
    payload = create_plan_year_payload(**overrides)
    return get_success_data(api_client.create_plan_year(payload, ADMIN))


def create_account(participant_id, plan_year_id, account_type, **overrides):
    payload = create_account_payload(participant_id, plan_year_id, account_type, **overrides)
    return get_success_data(api_client.create_account(payload, ADMIN))


def activate_account(account_id):
    return get_success_data(api_client.activate_account(account_id, ADMIN))


def get_account(account_id):
    return get_success_data(api_client.get_account(account_id, ADMIN))


def post_contribution(account_id, amount_cents, expected_account_version, **overrides):
    payload = create_contribution_payload(amount_cents, expected_account_version, **overrides)
    return get_success_data(api_client.create_contribution(account_id, payload, ADMIN))


def approve_claim(claim_id, adjudicator_user_id="adj-1"):
    headers = make_adjudicator_headers(adjudicator_user_id)
    return get_success_data(api_client.adjudicate_claim(claim_id, {"decision": "APPROVE"}, headers))


# --- Tier 1: State progression --------------------------------------------------------

def create_and_activate_hsa(participant_id, plan_year_id, coverage_tier="SELF_ONLY",
                            elected_amount_cents=437500, **overrides):
    """Open + activate an HSA. Returns the activated account dict."""
    acc = create_account(participant_id, plan_year_id, "HSA",
                         coverage_tier=coverage_tier,
                         elected_amount_cents=elected_amount_cents, **overrides)
    return activate_account(acc["id"])


def create_and_activate_fsa(participant_id, plan_year_id, account_type="HEALTH_FSA",
                            elected_amount_cents=100000,
                            auto_adjudication_threshold_cents=0, **overrides):
    """Open + activate a HEALTH_FSA or DCFSA. Returns the activated account dict."""
    acc = create_account(
        participant_id, plan_year_id, account_type,
        elected_amount_cents=elected_amount_cents,
        auto_adjudication_threshold_cents=auto_adjudication_threshold_cents, **overrides)
    return activate_account(acc["id"])


# --- Tier 2: Standard plan-year + participant setup -----------------------------------

def setup_plan_year_and_participant(clock=DEFAULT_CLOCK_IN_WINDOW,
                                    plan_year_overrides=None,
                                    participant_overrides=None):
    """Set the clock in-window, create the standard plan year and a participant.
    Returns (plan_year, participant)."""
    if clock is not None:
        set_clock(clock)
    py = create_plan_year(**(plan_year_overrides or {}))
    p = create_participant(**(participant_overrides or {}))
    return py, p


def setup_active_hsa(elected_amount_cents=437500, coverage_tier="SELF_ONLY",
                     birth_date="1990-01-01", participant_overrides=None,
                     plan_year_overrides=None, account_overrides=None,
                     clock=DEFAULT_CLOCK_IN_WINDOW):
    """Standard plan year + HDHP participant + activated HSA.
    Returns (plan_year, participant, account)."""
    p_over = {"hdhp_covered": True, "birth_date": birth_date}
    p_over.update(participant_overrides or {})
    py, p = setup_plan_year_and_participant(
        clock=clock, plan_year_overrides=plan_year_overrides, participant_overrides=p_over)
    acc = create_and_activate_hsa(
        p["id"], py["id"], coverage_tier=coverage_tier,
        elected_amount_cents=elected_amount_cents, **(account_overrides or {}))
    return py, p, acc


def setup_active_fsa(account_type="HEALTH_FSA", elected_amount_cents=100000,
                     auto_adjudication_threshold_cents=0, participant_overrides=None,
                     plan_year_overrides=None, account_overrides=None,
                     clock=DEFAULT_CLOCK_IN_WINDOW):
    """Standard plan year + participant + activated HEALTH_FSA/DCFSA.
    Returns (plan_year, participant, account)."""
    py, p = setup_plan_year_and_participant(
        clock=clock, plan_year_overrides=plan_year_overrides,
        participant_overrides=participant_overrides)
    acc = create_and_activate_fsa(
        p["id"], py["id"], account_type=account_type,
        elected_amount_cents=elected_amount_cents,
        auto_adjudication_threshold_cents=auto_adjudication_threshold_cents,
        **(account_overrides or {}))
    return py, p, acc


def setup_hsa_with_contribution(contribution_cents=100000, elected_amount_cents=437500,
                                coverage_tier="SELF_ONLY", birth_date="1990-01-01",
                                participant_overrides=None, plan_year_overrides=None,
                                clock=DEFAULT_CLOCK_IN_WINDOW):
    """Active HSA with one POSTED contribution. Returns (plan_year, participant, account)
    where account is re-fetched so balances/version reflect the contribution."""
    py, p, acc = setup_active_hsa(
        elected_amount_cents=elected_amount_cents, coverage_tier=coverage_tier,
        birth_date=birth_date, participant_overrides=participant_overrides,
        plan_year_overrides=plan_year_overrides, clock=clock)
    post_contribution(acc["id"], contribution_cents, acc["version"])
    return py, p, get_account(acc["id"])


# --- Tier 3: Claim lifecycle shortcuts ------------------------------------------------

def file_claim(account_id, participant_id, **overrides):
    """File a claim as the owning Participant (ownership-gated → entity-id headers)."""
    headers = make_participant_headers(participant_id)
    payload = create_claim_payload(account_id, **overrides)
    return get_success_data(api_client.create_claim(payload, headers))


def file_claim_as_admin(account_id, **overrides):
    """File a claim as PlanAdmin (no ownership gate). Returns the claim dict."""
    payload = create_claim_payload(account_id, **overrides)
    return get_success_data(api_client.create_claim(payload, ADMIN))


def create_approved_claim(account_id, participant_id=None, adjudicator_user_id="adj-1",
                          **claim_overrides):
    """File a claim then APPROVE it. Returns the approved claim dict.
    If participant_id is given the claim is filed by that participant, else by PlanAdmin."""
    if participant_id is not None:
        claim = file_claim(account_id, participant_id, **claim_overrides)
    else:
        claim = file_claim_as_admin(account_id, **claim_overrides)
    return approve_claim(claim["id"], adjudicator_user_id=adjudicator_user_id)


def create_batch(participant_id, claim_ids, disburser_user_id="disb-1"):
    headers = make_disburser_headers(disburser_user_id)
    payload = create_batch_payload(participant_id, claim_ids)
    return get_success_data(api_client.create_batch(payload, headers))


def disburse_batch(batch_id, account_id, disburser_user_id="disb-1"):
    """Disburse a batch, reading the live account version for the OCC field.
    Returns the batch dict after disbursement."""
    headers = make_disburser_headers(disburser_user_id)
    acc = get_account(account_id)
    payload = {"expected_account_version": acc["version"]}
    return get_success_data(api_client.disburse_batch(batch_id, payload, headers))


def reimburse_single_claim(participant_id, claim_id, account_id, disburser_user_id="disb-1"):
    """Create a one-claim batch and disburse it. Returns the settled/partial batch dict."""
    batch = create_batch(participant_id, [claim_id], disburser_user_id=disburser_user_id)
    return disburse_batch(batch["id"], account_id, disburser_user_id=disburser_user_id)


def setup_reimbursed_hsa(contribution_cents=100000, claim_cents=100000,
                         elected_amount_cents=437500):
    """HSA contributed `contribution_cents`, one substantiated MEDICAL claim of `claim_cents`
    approved and reimbursed. Returns (plan_year, participant, account, claim) with account/claim
    re-fetched post-reimbursement."""
    py, p, acc = setup_hsa_with_contribution(
        contribution_cents=contribution_cents, elected_amount_cents=elected_amount_cents)
    claim = create_approved_claim(
        acc["id"], service_date="2026-03-01", expense_category="MEDICAL",
        claimed_amount_cents=claim_cents, substantiated=True)
    reimburse_single_claim(p["id"], claim["id"], acc["id"])
    return py, p, get_account(acc["id"]), get_success_data(api_client.get_claim(claim["id"], ADMIN))


# --- Tier 4: Settlement targeting -----------------------------------------------------

def settle_plan_year(plan_year_id, clock_past_deadline=DEFAULT_CLOCK_PAST_DEADLINE):
    """Advance the clock past the filing deadline and run settlement.
    Returns the settled plan-year dict."""
    if clock_past_deadline is not None:
        set_clock(clock_past_deadline)
    return get_success_data(api_client.settle_plan_year(plan_year_id, ADMIN))


def find_carryover_account(source_account_id):
    """Return the single carryover-holding destination account created from a source
    account at settlement, or None if there is no such account."""
    resp = api_client.list_accounts(
        ADMIN, params={"carryover_source_account_id": source_account_id})
    data = get_success_data(resp)
    if isinstance(data, list):
        return data[0] if data else None
    return None
