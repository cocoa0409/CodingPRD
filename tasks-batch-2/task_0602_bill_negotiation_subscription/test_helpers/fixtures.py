"""Composite setup helpers for the bill-negotiation domain.

Every helper builds its preconditions from scratch via PRD-declared endpoints,
because the server database is empty at the start of each test. Fixtures use the
lenient get_success_data() validator internally so setup problems surface as
"Setup failed" rather than confusing assertion errors.

Identity threading: after creating an entity_backed Member or ConciergeAgent,
ownership-gated calls use make_member_headers(member["id"]) /
make_agent_headers(agent["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import make_member_headers, make_agent_headers, make_admin_headers
from . import factories


# ---------------------------------------------------------------------------
# Tier 1: primitive creators returning the created entity dict
# ---------------------------------------------------------------------------

def create_member(**overrides):
    """Register a fresh ACTIVE member. Returns the member dict."""
    resp = api_client.create_member(factories.create_member_payload(**overrides))
    return get_success_data(resp)


def create_agent(max_open_cases=5, display_name="Agent A"):
    """Create a concierge agent profile via PlatformAdmin. Returns the profile dict."""
    resp = api_client.create_concierge_agent(
        factories.create_concierge_agent_payload(display_name=display_name, max_open_cases=max_open_cases),
        headers=make_admin_headers(),
    )
    return get_success_data(resp)


def create_linked_account(member_id, **overrides):
    resp = api_client.create_linked_account(
        factories.create_linked_account_payload(member_id, **overrides),
        headers=make_member_headers(member_id),
    )
    return get_success_data(resp)


def create_savings_account(member_id, **overrides):
    resp = api_client.create_savings_account(
        factories.create_savings_account_payload(member_id, **overrides),
        headers=make_member_headers(member_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: member + linked account + recurring charge in a chosen state
# ---------------------------------------------------------------------------

def setup_member_with_linked_account(account_type="CHECKING"):
    """Returns (member, linked_account). Member ACTIVE, account LINKED."""
    member = create_member()
    la = create_linked_account(member["id"], account_type=account_type)
    return member, la


def setup_detected_charge(amount_cents=5000, cadence="MONTHLY", category="STREAMING",
                          merchant_name="StreamCo", account_type="CHECKING"):
    """Member + LINKED account + a DETECTED charge. Returns (member, la, charge)."""
    member, la = setup_member_with_linked_account(account_type=account_type)
    resp = api_client.create_recurring_charge(
        factories.create_recurring_charge_payload(
            la["id"], amount_cents=amount_cents, cadence=cadence,
            category=category, merchant_name=merchant_name,
        ),
        headers=make_member_headers(member["id"]),
    )
    charge = get_success_data(resp)
    return member, la, charge


def setup_confirmed_charge(amount_cents=5000, cadence="MONTHLY", category="STREAMING",
                           merchant_name="StreamCo", account_type="CHECKING"):
    """Member + LINKED account + a CONFIRMED charge. Returns (member, la, charge)."""
    member, la, charge = setup_detected_charge(
        amount_cents=amount_cents, cadence=cadence, category=category,
        merchant_name=merchant_name, account_type=account_type,
    )
    resp = api_client.confirm_recurring_charge(charge["id"], headers=make_member_headers(member["id"]))
    charge = get_success_data(resp)
    return member, la, charge


# ---------------------------------------------------------------------------
# Tier 3: subscriptions
# ---------------------------------------------------------------------------

def setup_active_subscription(monthly_cost_cents=5000, charge_amount_cents=5000, **sub_overrides):
    """Member + CONFIRMED charge + ACTIVE Subscription. Returns (member, charge, subscription)."""
    member, la, charge = setup_confirmed_charge(amount_cents=charge_amount_cents)
    resp = api_client.create_subscription(
        factories.create_subscription_payload(
            member["id"], charge["id"], monthly_cost_cents=monthly_cost_cents, **sub_overrides
        ),
        headers=make_member_headers(member["id"]),
    )
    sub = get_success_data(resp)
    return member, charge, sub


def setup_trial_subscription(trial_end_utc, trial_reminder_lead_days=3, monthly_cost_cents=1500):
    """Member + CONFIRMED charge + free-trial Subscription. Returns (member, charge, subscription)."""
    member, la, charge = setup_confirmed_charge(
        amount_cents=1500, category="SOFTWARE", merchant_name="TrialCo"
    )
    resp = api_client.create_subscription(
        factories.create_subscription_payload(
            member["id"], charge["id"], plan_name="Trial",
            monthly_cost_cents=monthly_cost_cents, is_free_trial=True,
            trial_end_utc=trial_end_utc, trial_reminder_lead_days=trial_reminder_lead_days,
        ),
        headers=make_member_headers(member["id"]),
    )
    sub = get_success_data(resp)
    return member, charge, sub


def setup_cancel_failed_subscription(monthly_cost_cents=1000):
    """Drive a subscription to CANCEL_FAILED. Returns (member, agent, subscription)."""
    member, charge, sub = setup_active_subscription(
        monthly_cost_cents=monthly_cost_cents, charge_amount_cents=1000
    )
    agent = create_agent()
    api_client.request_cancel_subscription(
        sub["id"], {"expected_subscription_version": sub["version"]},
        headers=make_member_headers(member["id"]),
    )
    resp = api_client.fail_cancel_subscription(sub["id"], headers=make_agent_headers(agent["id"]))
    sub = get_success_data(resp)
    return member, agent, sub


def setup_cancel_requested_subscription(monthly_cost_cents=1000):
    """Drive a subscription to CANCEL_REQUESTED. Returns (member, agent, subscription)."""
    member, charge, sub = setup_active_subscription(
        monthly_cost_cents=monthly_cost_cents, charge_amount_cents=1000
    )
    agent = create_agent()
    resp = api_client.request_cancel_subscription(
        sub["id"], {"expected_subscription_version": sub["version"]},
        headers=make_member_headers(member["id"]),
    )
    sub = get_success_data(resp)
    return member, agent, sub


# ---------------------------------------------------------------------------
# Tier 4: negotiation cases
# ---------------------------------------------------------------------------

def setup_open_case(charge_amount_cents=5000, cadence="MONTHLY", max_open_cases=5):
    """Member + CONFIRMED charge + agent + OPEN NegotiationCase.
    Returns (member, agent, charge, case)."""
    member, la, charge = setup_confirmed_charge(amount_cents=charge_amount_cents, cadence=cadence)
    agent = create_agent(max_open_cases=max_open_cases)
    resp = api_client.create_negotiation_case(
        factories.create_negotiation_case_payload(member["id"], charge["id"], agent["id"]),
        headers=make_member_headers(member["id"]),
    )
    case = get_success_data(resp)
    return member, agent, charge, case


def setup_proposed_case(offered_annual_cost_cents, charge_amount_cents=5000, cadence="MONTHLY"):
    """OPEN case proposed once -> PROPOSED. Returns (member, agent, charge, case)."""
    member, agent, charge, case = setup_open_case(
        charge_amount_cents=charge_amount_cents, cadence=cadence
    )
    resp = api_client.propose_negotiation(
        case["id"], {"offered_annual_cost_cents": offered_annual_cost_cents},
        headers=make_agent_headers(agent["id"]),
    )
    case = get_success_data(resp)
    return member, agent, charge, case


def setup_won_case(offered_annual_cost_cents=48000, charge_amount_cents=5000, cadence="MONTHLY"):
    """Drive a case to WON via propose+accept. Returns (member, agent, charge, case)."""
    member, agent, charge, case = setup_proposed_case(
        offered_annual_cost_cents, charge_amount_cents=charge_amount_cents, cadence=cadence
    )
    resp = api_client.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"]))
    case = get_success_data(resp)
    return member, agent, charge, case


def get_ledger_entry_for_member(member_id):
    """Return the first SavingsLedgerEntry for the member (e.g., one booked by a WON case)."""
    resp = api_client.list_ledger_entries(
        headers=make_member_headers(member_id), params={"member_id": member_id}
    )
    entries = get_success_data(resp)
    return entries[0]


# ---------------------------------------------------------------------------
# Tier 5: savings sweeps + refund claims
# ---------------------------------------------------------------------------

def setup_pending_ledger_with_savings_account(offered_annual_cost_cents=48000):
    """Member with an OPEN SavingsAccount linked as destination, plus a PENDING
    ledger entry (net 7800) from a WON case, balance 0.
    Returns (member, agent, savings_account, ledger_entry)."""
    member = create_member()
    sa = create_savings_account(member["id"])
    api_client.patch_member(
        member["id"], {"savings_account_id": sa["id"]},
        headers=make_member_headers(member["id"]),
    )
    la = create_linked_account(member["id"])
    resp = api_client.create_recurring_charge(
        factories.create_recurring_charge_payload(la["id"], amount_cents=5000, cadence="MONTHLY"),
        headers=make_member_headers(member["id"]),
    )
    charge = get_success_data(resp)
    get_success_data(api_client.confirm_recurring_charge(charge["id"], headers=make_member_headers(member["id"])))
    agent = create_agent()
    case = get_success_data(api_client.create_negotiation_case(
        factories.create_negotiation_case_payload(member["id"], charge["id"], agent["id"]),
        headers=make_member_headers(member["id"]),
    ))
    api_client.propose_negotiation(
        case["id"], {"offered_annual_cost_cents": offered_annual_cost_cents},
        headers=make_agent_headers(agent["id"]),
    )
    api_client.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"]))
    entry = get_ledger_entry_for_member(member["id"])
    return member, agent, sa, entry


def setup_transferred_ledger_with_savings_account(offered_annual_cost_cents=48000):
    """As above but the ledger entry has been TRANSFERRED (balance bumped).
    Returns (member, agent, savings_account, ledger_entry)."""
    member, agent, sa, entry = setup_pending_ledger_with_savings_account(offered_annual_cost_cents)
    resp = api_client.transfer_ledger_entry(entry["id"], headers=make_member_headers(member["id"]))
    entry = get_success_data(resp)
    return member, agent, sa, entry


def setup_filed_refund_claim(claim_type="PRICE_DROP", observed_old_amount_cents=2000,
                             observed_new_amount_cents=1500, charge_amount_cents=2000):
    """Member + CONFIRMED charge + a FILED RefundClaim. Returns (member, charge, claim)."""
    member, la, charge = setup_confirmed_charge(
        amount_cents=charge_amount_cents, category="OTHER", merchant_name="NewsCo"
    )
    resp = api_client.create_refund_claim(
        factories.create_refund_claim_payload(
            member["id"], charge["id"], claim_type=claim_type,
            observed_old_amount_cents=observed_old_amount_cents,
            observed_new_amount_cents=observed_new_amount_cents,
        ),
        headers=make_member_headers(member["id"]),
    )
    claim = get_success_data(resp)
    return member, charge, claim


def setup_under_review_claim(claim_type="DOUBLE_BILL", observed_old_amount_cents=4000,
                             observed_new_amount_cents=0, charge_amount_cents=4000):
    """FILED claim moved to UNDER_REVIEW. Returns (member, agent, charge, claim)."""
    member, charge, claim = setup_filed_refund_claim(
        claim_type=claim_type, observed_old_amount_cents=observed_old_amount_cents,
        observed_new_amount_cents=observed_new_amount_cents, charge_amount_cents=charge_amount_cents,
    )
    agent = create_agent()
    resp = api_client.start_review_refund_claim(claim["id"], headers=make_agent_headers(agent["id"]))
    claim = get_success_data(resp)
    return member, agent, charge, claim


def setup_denied_claim(claim_type="DOUBLE_BILL", observed_old_amount_cents=2000,
                       observed_new_amount_cents=0, charge_amount_cents=2000):
    """A DENIED RefundClaim (filed -> under_review -> denied).
    Returns (member, agent, charge, claim)."""
    member, agent, charge, claim = setup_under_review_claim(
        claim_type=claim_type, observed_old_amount_cents=observed_old_amount_cents,
        observed_new_amount_cents=observed_new_amount_cents, charge_amount_cents=charge_amount_cents,
    )
    resp = api_client.deny_refund_claim(claim["id"], headers=make_agent_headers(agent["id"]))
    claim = get_success_data(resp)
    return member, agent, charge, claim


def set_clock(to_iso8601):
    """Advance the logical clock via PlatformAdmin."""
    return get_success_data(api_client.set_clock(to_iso8601, headers=make_admin_headers()))
