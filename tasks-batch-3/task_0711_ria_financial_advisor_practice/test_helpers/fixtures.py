"""Composite setup helpers for the RIA Practice API.

Each test runs against a freshly launched, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) internally so setup failures surface clearly.

All three roles use opaque X-User-IDs (PRD §2.1); separation-of-duties scenarios
thread explicit operator ids via the make_*_headers builders.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import (
    TEST_USERS, make_advisor_headers, make_compliance_headers, make_billing_headers,
)
from . import factories as f
from .constants import DEFAULT_CLOCK


ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
BILLING = TEST_USERS["billing_headers"]


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
def set_clock(iso=DEFAULT_CLOCK, headers=None):
    """Set the server logical clock (PRD §2.4)."""
    return get_success_data(api.set_clock(iso, headers or BILLING))


# --------------------------------------------------------------------------- #
# Primitive creators (return the data dict)
# --------------------------------------------------------------------------- #
def create_fee_schedule(**overrides):
    return get_success_data(api.create_fee_schedule(f.fee_schedule_payload(**overrides), BILLING))


def create_flat_fee_schedule(**overrides):
    return get_success_data(api.create_fee_schedule(f.flat_fee_schedule_payload(**overrides), BILLING))


def create_household(fee_schedule_id=None, **overrides):
    if fee_schedule_id is None:
        fee_schedule_id = create_flat_fee_schedule()["id"]
    return get_success_data(api.create_household(f.household_payload(fee_schedule_id, **overrides), ADVISOR))


def create_client(household_id, **overrides):
    return get_success_data(api.create_client(f.client_payload(household_id, **overrides), ADVISOR))


def create_portfolio(**overrides):
    return get_success_data(api.create_portfolio(f.portfolio_payload(**overrides), ADVISOR))


def create_published_portfolio(**overrides):
    pf = create_portfolio(**overrides)
    get_success_data(api.publish_portfolio(pf["id"], ADVISOR))
    return pf


def create_account(household_id, client_id, **overrides):
    return get_success_data(api.create_account(f.account_payload(household_id, client_id, **overrides), ADVISOR))


# --------------------------------------------------------------------------- #
# Tier 1: state progression
# --------------------------------------------------------------------------- #
def create_kyc_verified_client(household_id, **overrides):
    """Create a PROSPECT client and VERIFY_KYC it -> KYC_VERIFIED (PRD §3.1)."""
    c = create_client(household_id, **overrides)
    get_success_data(api.client_state(c["id"], "VERIFY_KYC", ADVISOR))
    return get_success_data(api.get_client(c["id"], ADVISOR))


def activate_account(account_id):
    """ACTIVATE a PENDING account -> ACTIVE (PRD §3.3)."""
    return get_success_data(api.account_state(account_id, "ACTIVATE", ADVISOR))


def ensure_ips_signed(client_id):
    """Advance a KYC_VERIFIED client to IPS_SIGNED so its accounts may be
    activated (PRD §3.3: account activation requires the owning client's
    onboarding_status to be IPS_SIGNED or ACTIVE; PRD §3.1: SIGN_IPS requires an
    APPROVED IPS to exist for the client).

    Idempotent: if the client is already IPS_SIGNED/ACTIVE it is a no-op. If the
    client already has an APPROVED IPS (e.g. created by the test for drift), that
    statement is reused for signing so the drift model is preserved; only when no
    APPROVED IPS exists does this build a throwaway published portfolio + approved
    IPS to satisfy the signing precondition.
    """
    c = get_success_data(api.get_client(client_id, ADVISOR))
    if c["onboarding_status"] in {"IPS_SIGNED", "ACTIVE"}:
        return
    if c["onboarding_status"] != "KYC_VERIFIED":
        return
    existing = get_success_data(
        api.list_ips(ADVISOR, params={"client_id": client_id}))
    has_approved = any(i["status"] == "APPROVED" for i in existing)
    if not has_approved:
        pf = create_published_portfolio()
        create_approved_ips(client_id, pf["id"])
    get_success_data(api.client_state(client_id, "SIGN_IPS", ADVISOR))


def create_active_billable_account(household_id, client_id, market_value_cents,
                                   equity_value_cents=0, **overrides):
    """KYC must already be done on the client. Drive the client to IPS_SIGNED
    (PRD §3.3 activation gate), create an account, activate it (PENDING -> ACTIVE,
    recomputes household AUM). Returns the ACTIVE account."""
    a = create_account(household_id, client_id,
                        market_value_cents=market_value_cents,
                        equity_value_cents=equity_value_cents, **overrides)
    ensure_ips_signed(client_id)
    activate_account(a["id"])
    return get_success_data(api.get_account(a["id"], ADVISOR))


# --------------------------------------------------------------------------- #
# Tier 2 / 3: IPS approval lifecycle
# --------------------------------------------------------------------------- #
def create_approved_ips(client_id, portfolio_id, max_equity_pct=80,
                        drift_tolerance_bps=500,
                        advisor_id="adv-1", officer_id="co-1"):
    """DRAFT -> PROPOSE (by advisor) -> APPROVE (by a distinct officer).
    The portfolio must already be published. Returns the APPROVED IPS.

    Separation of duties (PRD §3.2): the approving officer's X-User-ID differs
    from the proposing advisor's X-User-ID.
    """
    ips = get_success_data(api.create_ips(
        f.ips_payload(client_id, portfolio_id,
                      max_equity_pct=max_equity_pct,
                      drift_tolerance_bps=drift_tolerance_bps),
        make_advisor_headers(advisor_id)))
    get_success_data(api.ips_state(ips["id"], "PROPOSE", make_advisor_headers(advisor_id)))
    get_success_data(api.ips_state(ips["id"], "APPROVE", make_compliance_headers(officer_id)))
    return get_success_data(api.get_ips(ips["id"], COMPLIANCE))


def create_proposed_ips(client_id, portfolio_id, max_equity_pct=80,
                        drift_tolerance_bps=500, advisor_id="adv-1"):
    """DRAFT -> PROPOSE. Portfolio must be published. Returns PROPOSED IPS."""
    ips = get_success_data(api.create_ips(
        f.ips_payload(client_id, portfolio_id,
                      max_equity_pct=max_equity_pct,
                      drift_tolerance_bps=drift_tolerance_bps),
        make_advisor_headers(advisor_id)))
    get_success_data(api.ips_state(ips["id"], "PROPOSE", make_advisor_headers(advisor_id)))
    return get_success_data(api.get_ips(ips["id"], ADVISOR))


def create_draft_ips(client_id, portfolio_id, max_equity_pct=80,
                     drift_tolerance_bps=500, advisor_id="adv-1"):
    """Create a DRAFT IPS (never proposed). Returns the DRAFT IPS."""
    return get_success_data(api.create_ips(
        f.ips_payload(client_id, portfolio_id,
                      max_equity_pct=max_equity_pct,
                      drift_tolerance_bps=drift_tolerance_bps),
        make_advisor_headers(advisor_id)))


def setup_account_with_approved_ips(market_value_cents=1000000,
                                    equity_value_cents=600000,
                                    model_equity_pct=60,
                                    max_equity_pct=80,
                                    drift_tolerance_bps=500):
    """Full chain to an ACTIVE account whose client has an APPROVED IPS targeting
    a published model portfolio. Returns dict of created entities.
    """
    sched = create_flat_fee_schedule()
    hh = create_household(sched["id"])
    pf = create_published_portfolio(model_equity_pct=model_equity_pct)
    client = create_kyc_verified_client(hh["id"])
    ips = create_approved_ips(client["id"], pf["id"],
                              max_equity_pct=max_equity_pct,
                              drift_tolerance_bps=drift_tolerance_bps)
    acct = create_active_billable_account(hh["id"], client["id"],
                                          market_value_cents=market_value_cents,
                                          equity_value_cents=equity_value_cents)
    return {
        "fee_schedule": sched, "household": hh, "portfolio": pf,
        "client": client, "ips": ips, "account": acct,
    }


# --------------------------------------------------------------------------- #
# Tier 4: fee-run threshold / calculation targeting
# --------------------------------------------------------------------------- #
def setup_household_with_active_account(market_value_cents, equity_value_cents=0,
                                        tiers=None, minimum_annual_fee_cents=0,
                                        billing_method="ARREARS", **account_overrides):
    """Schedule + ARREARS/ADVANCE household + KYC client + one ACTIVE billable
    account at the given value. Returns dict including the household's current
    version (re-read after the activate that bumped it).
    """
    if tiers is None:
        sched = create_flat_fee_schedule()
    else:
        sched = create_fee_schedule(tiers=tiers,
                                    minimum_annual_fee_cents=minimum_annual_fee_cents)
    hh = create_household(sched["id"], billing_method=billing_method)
    client = create_kyc_verified_client(hh["id"])
    acct = create_active_billable_account(hh["id"], client["id"],
                                          market_value_cents=market_value_cents,
                                          equity_value_cents=equity_value_cents,
                                          **account_overrides)
    hh = get_success_data(api.get_household(hh["id"], BILLING))
    return {"fee_schedule": sched, "household": hh, "client": client, "account": acct}


def create_calculated_fee_run(household_id, expected_household_version,
                              period_start="2026-01-01", period_end="2026-03-31",
                              creator_id="billing-1"):
    """Create a DRAFT fee run (OCC), then CALCULATE it -> CALCULATED.
    Returns the CALCULATED fee run.
    """
    run = get_success_data(api.create_fee_run(
        f.fee_run_payload(household_id, expected_household_version,
                          period_start=period_start, period_end=period_end),
        make_billing_headers(creator_id)))
    return get_success_data(api.fee_run_state(run["id"], "CALCULATE", make_billing_headers(creator_id)))


def create_finalized_fee_run(household_id, expected_household_version,
                             period_start="2026-01-01", period_end="2026-03-31",
                             creator_id="billing-1", finalizer_id="billing-2"):
    """Create -> CALCULATE -> FINALIZE (distinct finalizer per SoD, PRD §3.5).
    Returns the FINALIZED fee run. Finalize bumps Household.version by 1.
    """
    run = create_calculated_fee_run(household_id, expected_household_version,
                                    period_start=period_start, period_end=period_end,
                                    creator_id=creator_id)
    return get_success_data(api.fee_run_state(run["id"], "FINALIZE", make_billing_headers(finalizer_id)))


def household_version(household_id, headers=None):
    """Re-read the current Household.version (OCC source, PRD §2.6)."""
    return get_success_data(api.get_household(household_id, headers or BILLING))["version"]


# --------------------------------------------------------------------------- #
# Tier 5: rebalance lifecycle
# --------------------------------------------------------------------------- #
def create_proposed_rebalance(account_id, advisor_id="adv-1"):
    """Propose a rebalance order on an account whose client has an APPROVED IPS
    (PRD §3.7). Returns the PROPOSED order."""
    return get_success_data(api.create_rebalance_order({"account_id": account_id},
                                                       make_advisor_headers(advisor_id)))


def create_approved_rebalance(account_id, advisor_id="adv-1", officer_id="co-1"):
    """Propose then APPROVE a rebalance order. Returns the APPROVED order."""
    ro = create_proposed_rebalance(account_id, advisor_id=advisor_id)
    get_success_data(api.rebalance_order_state(ro["id"], "APPROVE", make_compliance_headers(officer_id)))
    return get_success_data(api.get_rebalance_order(ro["id"], COMPLIANCE))


# --------------------------------------------------------------------------- #
# Financial plan / goal
# --------------------------------------------------------------------------- #
def create_draft_plan(household_id=None, **overrides):
    """Create a DRAFT financial plan (lifecycle DRAFT, review NEEDS_REVIEW)."""
    if household_id is None:
        household_id = create_household()["id"]
    return get_success_data(api.create_financial_plan(
        f.financial_plan_payload(household_id, **overrides), ADVISOR))


def create_goal(plan_id, **overrides):
    return get_success_data(api.create_goal(f.goal_payload(plan_id, **overrides), ADVISOR))


def create_active_plan_with_goal(household_id=None, goal_overrides=None, **plan_overrides):
    """Create a DRAFT plan + one goal, then ACTIVATE the plan -> ACTIVE
    (requires a goal, recomputes goal projections; PRD §3.6).
    Returns (plan, goal) both re-read post-activation.
    """
    plan = create_draft_plan(household_id, **plan_overrides)
    goal = create_goal(plan["id"], **(goal_overrides or {}))
    get_success_data(api.financial_plan_state(plan["id"], "ACTIVATE", ADVISOR))
    plan = get_success_data(api.get_financial_plan(plan["id"], ADVISOR))
    goal = get_success_data(api.get_goal(goal["id"], ADVISOR))
    return plan, goal


# --------------------------------------------------------------------------- #
# Compliance item
# --------------------------------------------------------------------------- #
def create_compliance_item(subject_type, subject_id, **overrides):
    return get_success_data(api.create_compliance_item(
        f.compliance_item_payload(subject_type, subject_id, **overrides), COMPLIANCE))
