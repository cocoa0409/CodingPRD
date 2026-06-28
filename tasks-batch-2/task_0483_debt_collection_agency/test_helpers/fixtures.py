"""Composite setup helpers for the Debt Collection Agency API.

Each test runs against a freshly restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) so a setup failure surfaces as a clear "Setup failed"
error rather than a confusing assertion mismatch.

The Creditor role is entity-backed (PRD §2.1): ownership checks compare an
account's creditor foreign key to the caller's X-User-ID. Therefore every
ownership-gated Creditor call (place / recall / close) uses
make_creditor_headers(creditor["id"]) with the real Creditor id rather than the
shared constant. The other four roles are opaque.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_creditor_payload,
    create_consumer_payload,
    create_account_payload,
    create_arrangement_payload,
    create_communication_attempt_payload,
    create_payment_payload,
    create_dispute_payload,
    create_bureau_furnishing_payload,
    create_bureau_dispute_payload,
)
from .test_users import TEST_USERS, make_creditor_headers

COLLECTOR = TEST_USERS["collector_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
BUREAU = TEST_USERS["bureau_operator_headers"]
SYSTEM = TEST_USERS["system_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Set the logical clock to a fixed instant (PRD §2.4)."""
    return get_success_data(api_client.set_clock(iso, SYSTEM))


# ---------------------------------------------------------------------------
# Atomic creators (return the resource dict and, where relevant, owner headers)
# ---------------------------------------------------------------------------
def create_creditor(**overrides):
    """Create a Creditor and return (creditor, creditor_headers) where the headers
    carry the creditor's own id (entity-backed ownership)."""
    # A creditor record is itself created by a creditor-role caller; use the shared
    # constant for the create then switch to id-bound headers for ownership calls.
    res = api_client.create_creditor(
        create_creditor_payload(**overrides), TEST_USERS["creditor_headers"]
    )
    creditor = get_success_data(res)
    return creditor, make_creditor_headers(creditor["id"])


def create_consumer(**overrides):
    res = api_client.create_consumer(create_consumer_payload(**overrides), COLLECTOR)
    return get_success_data(res)


def place_account(creditor, creditor_headers, consumer, **overrides):
    """Place an Account under the given creditor/consumer. Returns the account."""
    res = api_client.create_account(
        create_account_payload(creditor["id"], consumer["id"], **overrides),
        creditor_headers,
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: account state progression
# ---------------------------------------------------------------------------
def setup_placed_account(clock="2026-01-01T00:00:00Z", account_overrides=None,
                         consumer_overrides=None, creditor_overrides=None):
    """Clock + Creditor + Consumer + PLACED Account.

    Returns a context dict with keys:
      creditor, creditor_headers, consumer, account
    """
    set_clock(clock)
    creditor, creditor_headers = create_creditor(**(creditor_overrides or {}))
    consumer = create_consumer(**(consumer_overrides or {}))
    account = place_account(creditor, creditor_headers, consumer,
                            **(account_overrides or {}))
    return {
        "creditor": creditor,
        "creditor_headers": creditor_headers,
        "consumer": consumer,
        "account": account,
    }


def setup_validation_sent_account(clock="2026-01-01T00:00:00Z", **kwargs):
    """PLACED account advanced to VALIDATION_SENT (notice sent, work not begun).
    contact_status becomes CONTACTABLE."""
    ctx = setup_placed_account(clock=clock, **kwargs)
    acct = get_success_data(
        api_client.send_validation_notice(ctx["account"]["id"], COLLECTOR)
    )
    ctx["account"] = acct
    return ctx


def setup_working_account(clock="2026-01-01T00:00:00Z", **kwargs):
    """Account fully advanced to WORKING (notice sent + begin-work).
    contact_status CONTACTABLE."""
    ctx = setup_validation_sent_account(clock=clock, **kwargs)
    acct = get_success_data(api_client.begin_work(ctx["account"]["id"], COLLECTOR))
    ctx["account"] = acct
    return ctx


def refresh_account(ctx):
    """Re-read the account into ctx['account'] (Creditor read)."""
    acct = get_success_data(
        api_client.get_account(ctx["account"]["id"], ctx["creditor_headers"])
    )
    ctx["account"] = acct
    return acct


# ---------------------------------------------------------------------------
# Tier 3: arrangements + payments
# ---------------------------------------------------------------------------
def propose_arrangement(account_id, arrangement_type, **overrides):
    res = api_client.create_arrangement(
        create_arrangement_payload(account_id, arrangement_type, **overrides),
        COLLECTOR,
    )
    return get_success_data(res)


def accept_arrangement(arrangement_id):
    return get_success_data(api_client.accept_arrangement(arrangement_id, COLLECTOR))


def post_payment(account_id, amount_cents, arrangement_id=None):
    """Post a payment; returns the framework Response (so callers wrap it in
    get_success_data() for success or validate_error() for rejection), matching
    the log_phone_attempt convention."""
    overrides = {}
    if arrangement_id is not None:
        overrides["arrangement_id"] = arrangement_id
    return api_client.create_payment(
        create_payment_payload(account_id, amount_cents, **overrides), COLLECTOR
    )


def setup_working_account_with_accepted_plan(clock="2026-01-01T00:00:00Z",
                                             installment_count=4, **kwargs):
    """WORKING account + an ACCEPTED PLAN arrangement (no payments yet).
    Adds 'arrangement' to the context dict."""
    ctx = setup_working_account(clock=clock, **kwargs)
    arr = propose_arrangement(ctx["account"]["id"], "PLAN",
                              installment_count=installment_count)
    arr = accept_arrangement(arr["id"])
    ctx["arrangement"] = arr
    return ctx


def setup_working_account_with_plan_payment(clock="2026-01-01T00:00:00Z",
                                            payment_cents=30000,
                                            installment_count=4, **kwargs):
    """WORKING account + ACCEPTED PLAN + one POSTED payment tied to it.
    Adds 'arrangement' and 'payment' to context."""
    ctx = setup_working_account_with_accepted_plan(
        clock=clock, installment_count=installment_count, **kwargs
    )
    pay = get_success_data(
        post_payment(ctx["account"]["id"], payment_cents,
                     arrangement_id=ctx["arrangement"]["id"])
    )
    ctx["payment"] = pay
    refresh_account(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: cadence / cooldown / call-window targeting
# ---------------------------------------------------------------------------
def log_phone_attempt(account_id, attempted_at, outcome="LOGGED"):
    """Log a PHONE attempt; returns the framework Response (so callers can assert
    either success or rejection)."""
    return api_client.create_communication_attempt(
        create_communication_attempt_payload(account_id, "PHONE", attempted_at, outcome),
        COLLECTOR,
    )


def setup_working_account_with_n_phone_attempts(attempts_at, clock,
                                                consumer_overrides=None, **kwargs):
    """WORKING account with one PHONE LOGGED attempt per timestamp in attempts_at,
    all posted at the given clock. Used to fill the trailing cadence window.
    Returns the working-account context."""
    ctx = setup_working_account(
        clock=clock, consumer_overrides=consumer_overrides, **kwargs
    )
    for ts in attempts_at:
        get_success_data(log_phone_attempt(ctx["account"]["id"], ts, "LOGGED"))
    refresh_account(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------
def raise_dispute(account_id, dispute_type):
    res = api_client.create_dispute(
        account_id, create_dispute_payload(dispute_type), COMPLIANCE
    )
    return get_success_data(res)


def setup_working_account_with_verified_dispute(clock="2026-01-01T00:00:00Z", **kwargs):
    """WORKING account with one ACCURACY dispute resolved VERIFIED.
    Adds 'dispute' to context."""
    ctx = setup_working_account(clock=clock, **kwargs)
    disp = raise_dispute(ctx["account"]["id"], "ACCURACY")
    get_success_data(api_client.investigate_dispute(disp["id"], COMPLIANCE))
    disp = get_success_data(
        api_client.resolve_dispute(disp["id"], {"resolution": "VERIFIED"}, COMPLIANCE)
    )
    ctx["dispute"] = disp
    refresh_account(ctx)
    return ctx


def setup_working_account_with_open_accuracy_dispute(clock="2026-01-01T00:00:00Z",
                                                     **kwargs):
    """WORKING account with one OPEN ACCURACY dispute. Adds 'dispute' to context."""
    ctx = setup_working_account(clock=clock, **kwargs)
    disp = raise_dispute(ctx["account"]["id"], "ACCURACY")
    ctx["dispute"] = disp
    return ctx


# ---------------------------------------------------------------------------
# Bureau furnishings + disputes
# ---------------------------------------------------------------------------
def furnish_tradeline(account_id, bureau="EQUIFAX"):
    res = api_client.create_bureau_furnishing(
        create_bureau_furnishing_payload(account_id, bureau), COMPLIANCE
    )
    return get_success_data(res)


def open_bureau_dispute(furnishing_id):
    res = api_client.create_bureau_dispute(
        create_bureau_dispute_payload(furnishing_id), BUREAU
    )
    return get_success_data(res)
