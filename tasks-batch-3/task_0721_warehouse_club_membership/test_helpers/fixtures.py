"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty database before each
test). Fixtures use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors.

Identity threading: after creating a Membership, ownership-gated calls use
make_member_headers(membership["id"]) — never the shared Member constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as api
from .test_users import (
    TEST_USERS, make_member_headers,
)
from .factories import (
    create_basic_plan_payload, create_executive_plan_payload,
    create_membership_payload, create_product_payload,
    create_instant_saving_payload, create_payment_payload,
    create_household_card_payload, create_line_payload,
    create_return_payload,
)

ADMIN = TEST_USERS["club_admin_headers"]
CLERK = TEST_USERS["register_clerk_headers"]
SVC = TEST_USERS["service_desk_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# --------------------------------------------------------------------------
# Plans / products / promotions (config)
# --------------------------------------------------------------------------
def create_basic_plan(**overrides):
    return get_success_data(api.create_plan(create_basic_plan_payload(**overrides), ADMIN))


def create_executive_plan(**overrides):
    return get_success_data(api.create_plan(create_executive_plan_payload(**overrides), ADMIN))


def create_product(sku, **overrides):
    return get_success_data(api.create_product(create_product_payload(sku, **overrides), ADMIN))


def create_instant_saving(product_id, **overrides):
    return get_success_data(api.create_instant_saving(
        create_instant_saving_payload(product_id, **overrides), ADMIN))


# --------------------------------------------------------------------------
# Tier 1: Membership state progression
# --------------------------------------------------------------------------
def create_pending_membership(plan_id, **overrides):
    """Signup -> PENDING_PAYMENT membership.

    Signup is permitted only to Anonymous / ClubAdmin (PRD endpoint table:
    POST /memberships -> Anonymous, ClubAdmin). A prospective signer is not yet
    a Member, so we sign up as ClubAdmin (a permitted signer)."""
    return get_success_data(api.create_membership(
        create_membership_payload(plan_id, **overrides), ADMIN))


def activate_membership(membership_id):
    """SUCCEEDED SIGNUP payment -> ACTIVE."""
    return get_success_data(api.create_payment(
        create_payment_payload(membership_id, purpose="SIGNUP", outcome="SUCCEEDED"),
        make_member_headers(membership_id)))


def create_active_membership(plan_id, **overrides):
    """Signup + activate. Returns the ACTIVE membership entity (re-read)."""
    m = create_pending_membership(plan_id, **overrides)
    activate_membership(m["id"])
    return get_membership(m["id"])


def create_active_basic_membership(plan_overrides=None, **membership_overrides):
    plan = create_basic_plan(**(plan_overrides or {}))
    m = create_active_membership(plan["id"], **membership_overrides)
    return plan, m


def create_active_executive_membership(plan_overrides=None, **membership_overrides):
    plan = create_executive_plan(**(plan_overrides or {}))
    m = create_active_membership(plan["id"], **membership_overrides)
    return plan, m


def get_membership(membership_id):
    return get_success_data(api.get_membership(membership_id, make_member_headers(membership_id)))


def get_membership_version(membership_id):
    return get_membership(membership_id)["version"]


# --------------------------------------------------------------------------
# Tier 2/3: Transactions and lines
# --------------------------------------------------------------------------
def open_transaction(membership_id):
    return get_success_data(api.create_transaction({"membership_id": membership_id}, CLERK))


def add_line(transaction_id, product_id, qty):
    return get_success_data(api.add_line(transaction_id, create_line_payload(product_id, qty), CLERK))


def finalize_transaction(transaction_id):
    return get_success_data(api.finalize_transaction(transaction_id, CLERK))


def create_finalized_transaction(membership_id, product_id, qty):
    """Open -> add one line -> finalize. Returns (transaction, line)."""
    txn = open_transaction(membership_id)
    line = add_line(txn["id"], product_id, qty)
    txn = finalize_transaction(txn["id"])
    return txn, line


# --------------------------------------------------------------------------
# Returns
# --------------------------------------------------------------------------
def create_receipted_return(membership_id, transaction_id, product_id, qty):
    return get_success_data(api.create_return(
        create_return_payload(membership_id, product_id, qty, transaction_id=transaction_id), SVC))


def create_no_receipt_return(membership_id, product_id, qty):
    return get_success_data(api.create_return(
        create_return_payload(membership_id, product_id, qty), SVC))


def approve_return(return_id):
    return get_success_data(api.approve_return(return_id, SVC))


# --------------------------------------------------------------------------
# Reverse-reachability reads
# --------------------------------------------------------------------------
def list_fee_events(membership_id, **params):
    p = {"membership_id": membership_id}
    p.update(params)
    resp = api.list_fee_events(make_member_headers(membership_id), params=p)
    return resp.json()["data"]


def find_fee_event(membership_id, kind):
    """Return the first FeeEvent of the given kind for a membership, or None."""
    for fe in list_fee_events(membership_id, kind=kind):
        if fe["kind"] == kind:
            return fe
    return None


def list_reward_ledger(membership_id, **params):
    p = {"membership_id": membership_id}
    p.update(params)
    resp = api.list_reward_ledger(make_member_headers(membership_id), params=p)
    return resp.json()["data"]


# --------------------------------------------------------------------------
# Tier 4: accrual / reward-bearing scenarios
# --------------------------------------------------------------------------
def setup_executive_with_accrued_reward(qty=5, member_price=8000, clock=None,
                                        plan_overrides=None, product_sku="P-ACCR"):
    """
    EXECUTIVE ACTIVE member with a FINALIZED reward_eligible transaction.
    Returns (plan, membership, product, transaction, line).
    With defaults (rate 200 bps, qty 5, member 8000 -> net 40000) accrues 800.
    """
    if clock:
        set_clock(clock)
    plan = create_executive_plan(**(plan_overrides or {}))
    product = create_product(product_sku, member_price_cents=member_price, reward_eligible=True)
    m = create_active_membership(plan["id"], auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], qty)
    return plan, get_membership(m["id"]), product, txn, line
