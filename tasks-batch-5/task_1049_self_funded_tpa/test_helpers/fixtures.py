"""Composite setup helpers.

The runner restarts the server (empty DB, clock reset to 2026-07-01T00:00:00Z)
before every test, so every helper builds its preconditions from scratch using
only PRD-declared endpoints. Setup calls use the lenient get_success_data()
validator so a broken precondition surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as api
from .test_users import TEST_USERS, make_examiner_headers
from .factories import (
    create_plan_payload, create_provider_payload, create_member_payload,
    create_stop_loss_policy_payload, create_laser_payload, create_claim_payload,
)

ADMIN = TEST_USERS["tpa_admin_headers"]
FUND = TEST_USERS["fund_manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---- Clock -----------------------------------------------------------------
def set_clock(iso: str):
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN))


# ---- Single-entity builders ------------------------------------------------
def create_plan(**overrides) -> dict:
    return get_success_data(api.create_plan(create_plan_payload(**overrides), ADMIN))


def create_provider(**overrides) -> dict:
    return get_success_data(api.create_provider(create_provider_payload(**overrides), ADMIN))


def create_member(plan_id: str, **overrides) -> dict:
    payload = create_member_payload(plan_id=plan_id, **overrides)
    return get_success_data(api.create_member(payload, ADMIN))


def terminate_member(member_id: str, termination_date: str) -> dict:
    return get_success_data(
        api.terminate_member(member_id, {"termination_date": termination_date}, ADMIN))


def terminate_plan(plan_id: str, termination_date: str) -> dict:
    return get_success_data(
        api.terminate_plan(plan_id, {"termination_date": termination_date}, ADMIN))


def create_policy(plan_id: str, **overrides) -> dict:
    payload = create_stop_loss_policy_payload(plan_id=plan_id, **overrides)
    return get_success_data(api.create_stop_loss_policy(payload, ADMIN))


def create_active_policy(plan_id: str, **overrides) -> dict:
    """Create a stop-loss policy under a plan and activate it. Returns the
    ACTIVE policy (re-fetched)."""
    pol = create_policy(plan_id, **overrides)
    get_success_data(api.activate_stop_loss_policy(pol["id"], ADMIN))
    return get_success_data(api.get_stop_loss_policy(pol["id"], ADMIN))


def create_laser(policy_id: str, member_id: str, **overrides) -> dict:
    payload = create_laser_payload(
        stop_loss_policy_id=policy_id, member_id=member_id, **overrides)
    return get_success_data(api.create_laser(payload, ADMIN))


# ---- Claim helpers ---------------------------------------------------------
def submit_claim(member_id: str, provider_id: str, examiner_id: str = "ex-1", **overrides) -> dict:
    payload = create_claim_payload(member_id=member_id, provider_id=provider_id, **overrides)
    return get_success_data(api.create_claim(payload, make_examiner_headers(examiner_id)))


def adjudicate_claim(claim_id: str, examiner_id: str = "ex-1") -> dict:
    return get_success_data(api.adjudicate_claim(claim_id, make_examiner_headers(examiner_id)))


def create_adjudicated_claim(member_id: str, provider_id: str, examiner_id: str = "ex-1",
                             **overrides) -> dict:
    """Submit a claim then adjudicate it. Returns the ADJUDICATED claim (re-fetched)."""
    c = submit_claim(member_id, provider_id, examiner_id, **overrides)
    adjudicate_claim(c["id"], examiner_id)
    return get_success_data(api.get_claim(c["id"], ADMIN))


# ---- Fund / check-run helpers ---------------------------------------------
def create_fund_account(plan_id: str) -> dict:
    return get_success_data(api.create_fund_account({"plan_id": plan_id}, FUND))


def deposit(fund_account_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api.deposit_fund_account(fund_account_id, {"amount_cents": amount_cents}, FUND))


def create_check_run(fund_account_id: str, claim_ids: list) -> dict:
    return get_success_data(
        api.create_check_run({"fund_account_id": fund_account_id, "claim_ids": claim_ids}, FUND))


def release_check_run(check_run_id: str, expected_fund_account_version: int) -> dict:
    return get_success_data(api.release_check_run(
        check_run_id, {"expected_fund_account_version": expected_fund_account_version}, FUND))


# ---- Composite scenarios ---------------------------------------------------
def setup_plan_provider_member(plan_overrides=None, provider_overrides=None,
                               member_overrides=None):
    """Active plan + provider + one member. The most common preamble.
    Returns (plan, provider, member)."""
    plan = create_plan(**(plan_overrides or {}))
    provider = create_provider(**(provider_overrides or {}))
    member = create_member(plan["id"], **(member_overrides or {}))
    return plan, provider, member


def setup_funded_adjudicated_claim(deposit_cents=100000, plan_overrides=None,
                                   provider_overrides=None, claim_overrides=None):
    """Plan + provider + member + one ADJUDICATED claim + a fund with
    `deposit_cents` deposited. Returns (plan, provider, member, claim, fund,
    fund_version) where fund_version is the version observed right after deposit.
    """
    plan, provider, member = setup_plan_provider_member(
        plan_overrides, provider_overrides)
    claim = create_adjudicated_claim(member["id"], provider["id"],
                                     **(claim_overrides or {}))
    fund = create_fund_account(plan["id"])
    fund = deposit(fund["id"], deposit_cents)
    return plan, provider, member, claim, fund, fund["version"]
