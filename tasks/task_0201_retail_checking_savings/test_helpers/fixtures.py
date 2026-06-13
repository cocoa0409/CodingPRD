"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Uses get_success_data() (lenient validator) so a broken precondition surfaces as a
clear "Setup step failed" error rather than a confusing assertion failure.

Every helper builds its state from scratch through PRD-declared endpoints only — the
test harness restarts the server (empty DB) before every test, so nothing is carried
over. Identity threading is mandatory: after a fixture opens an account it threads the
real Customer.id into make_account_holder_headers() for every ownership-gated call
(PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_apy_tier_payload,
    create_customer_payload,
    create_application_payload,
    reject_application_payload,
    courtesy_pay_payload,
    transaction_payload,
    stop_payment_payload,
    ach_origination_payload,
    ach_leg_payload,
    settle_payload,
    clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_holder_headers,
    make_officer_headers,
    make_teller_headers,
)

# Canonical opaque operator ids used throughout fixtures (PRD §2.1, §3.3).
TELLER_ID = "teller-1"
OFFICER_ID = "officer-1"
OFFICER2_ID = "officer-2"


# ─── Tier 0: Clock + tier configuration ───────────────────────────────
def set_clock(to_iso8601: str):
    """Advance the ledger clock to a fixed UTC instant (PRD §3.15)."""
    return get_success_data(
        api_client.set_clock(clock_payload(to_iso8601), make_officer_headers(OFFICER_ID))
    )


def create_apy_tier(code="CHK_STD", product_type="CHECKING", min_balance_cents=0,
                    annual_rate_bps=0):
    """Create one published APY tier (PRD §3.11)."""
    return get_success_data(
        api_client.create_apy_tier(
            create_apy_tier_payload(
                code=code, product_type=product_type,
                min_balance_cents=min_balance_cents, annual_rate_bps=annual_rate_bps,
            ),
            make_officer_headers(OFFICER_ID),
        )
    )


# ─── Tier 1: Customer / Application lifecycle ─────────────────────────
def create_customer(legal_name="Test Person", date_of_birth="1990-01-01",
                    tax_id_last4="1234", country_of_residence="US"):
    """Create a pre-CIP customer (PRD §3.1). Returns the Customer dict."""
    return get_success_data(
        api_client.create_customer(
            create_customer_payload(
                legal_name=legal_name, date_of_birth=date_of_birth,
                tax_id_last4=tax_id_last4, country_of_residence=country_of_residence,
            ),
            make_teller_headers(TELLER_ID),
        )
    )


def create_draft_application(customer_id, product_type="CHECKING",
                             requested_apy_tier_code="CHK_STD"):
    """Open a DRAFT application (PRD §3.1). Returns the Application dict."""
    return get_success_data(
        api_client.create_application(
            create_application_payload(
                customer_id, product_type=product_type,
                requested_apy_tier_code=requested_apy_tier_code,
            ),
            make_teller_headers(TELLER_ID),
        )
    )


def create_submitted_application(customer_id, product_type="CHECKING",
                                 requested_apy_tier_code="CHK_STD",
                                 submitted_by=TELLER_ID):
    """Open + submit an application (PRD §3.1, §3.3). Returns the SUBMITTED Application.

    submitted_by stamps submitted_by_user_id (the SoD anchor).
    """
    app = create_draft_application(customer_id, product_type, requested_apy_tier_code)
    return get_success_data(
        api_client.submit_application(app["id"], make_teller_headers(submitted_by))
    )


def open_account(customer_id=None, product_type="CHECKING",
                 requested_apy_tier_code="CHK_STD",
                 submitted_by=TELLER_ID, approved_by=OFFICER_ID,
                 customer_overrides=None):
    """Full happy-path account opening (PRD §3.1, §3.3): create customer (if needed)
    -> application -> submit -> approve. Returns (customer, account).

    The approving officer differs from the submitting teller, so segregation of duties
    is satisfied.
    """
    if customer_id is None:
        cust = create_customer(**(customer_overrides or {}))
        customer_id = cust["id"]
    else:
        cust = get_success_data(
            api_client.get_customer(customer_id, make_officer_headers(OFFICER_ID))
        )
    app = create_submitted_application(
        customer_id, product_type, requested_apy_tier_code, submitted_by
    )
    approved = get_success_data(
        api_client.approve_application(app["id"], make_officer_headers(approved_by))
    )
    account = get_success_data(
        api_client.get_account(
            approved["opened_account_id"], make_officer_headers(OFFICER_ID)
        )
    )
    return cust, account


def open_account_with_deposit(deposit_cents, product_type="CHECKING",
                              requested_apy_tier_code="CHK_STD",
                              customer_overrides=None):
    """Open an account and post an initial DEPOSIT (PRD §3.3, §3.5).
    Returns (customer, account_after_deposit)."""
    cust, account = open_account(
        product_type=product_type,
        requested_apy_tier_code=requested_apy_tier_code,
        customer_overrides=customer_overrides,
    )
    holder = make_account_holder_headers(cust["id"])
    get_success_data(
        api_client.create_transaction(
            account["id"], transaction_payload("DEPOSIT", deposit_cents), holder
        )
    )
    account = get_success_data(api_client.get_account(account["id"], holder))
    return cust, account


def open_account_with_courtesy_pay(deposit_cents, limit_cents,
                                   product_type="CHECKING",
                                   requested_apy_tier_code="CHK_STD"):
    """Open an account, opt into courtesy pay with the given limit, and deposit
    (PRD §3.3, §3.5). Returns (customer, account_after)."""
    cust, account = open_account(
        product_type=product_type, requested_apy_tier_code=requested_apy_tier_code
    )
    holder = make_account_holder_headers(cust["id"])
    get_success_data(
        api_client.set_courtesy_pay(
            account["id"], courtesy_pay_payload(True, limit_cents), holder
        )
    )
    if deposit_cents:
        get_success_data(
            api_client.create_transaction(
                account["id"], transaction_payload("DEPOSIT", deposit_cents), holder
            )
        )
    account = get_success_data(api_client.get_account(account["id"], holder))
    return cust, account


def reject_application(customer_id, product_type="CHECKING",
                      requested_apy_tier_code="CHK_STD",
                      reason="DUPLICATE", submitted_by=TELLER_ID,
                      rejected_by=OFFICER_ID):
    """Open -> submit -> reject an application (PRD §3.3). Returns the REJECTED Application."""
    app = create_submitted_application(
        customer_id, product_type, requested_apy_tier_code, submitted_by
    )
    return get_success_data(
        api_client.reject_application(
            app["id"], reject_application_payload(rejection_reason_code=reason),
            make_officer_headers(rejected_by),
        )
    )


# ─── Tier 2: Stop-payment setup ───────────────────────────────────────
def place_stop_payment(account_id, customer_id, check_number, max_amount_cents,
                       expires_on):
    """Place a stop-payment order on an owned account (PRD §3.10). Returns the StopPayment."""
    holder = make_account_holder_headers(customer_id)
    return get_success_data(
        api_client.create_stop_payment(
            account_id,
            stop_payment_payload(check_number, max_amount_cents, expires_on),
            holder,
        )
    )


# ─── Tier 3: ACH origination setup ────────────────────────────────────
def stage_ach_origination(debtor_account_id, creditor_account_id,
                          posting_order="CHRONOLOGICAL"):
    """Stage an ACH batch (PRD §3.12). Returns the STAGED AchOrigination."""
    return get_success_data(
        api_client.create_ach_origination(
            ach_origination_payload(
                debtor_account_id, creditor_account_id, posting_order
            ),
            make_officer_headers(OFFICER_ID),
        )
    )


def add_leg(origination_id, leg_role, amount_cents, expected_version):
    """Add one leg to a STAGED batch (PRD §3.12). Returns the AchLeg (carries the
    bumped origination version)."""
    return get_success_data(
        api_client.add_ach_leg(
            origination_id,
            ach_leg_payload(leg_role, amount_cents, expected_version),
            make_officer_headers(OFFICER_ID),
        )
    )


def origination_version(origination_id):
    """Read the origination's current `version` (PRD §2.4, §2.6). Each leg add
    advances the origination's version by one (PRD §3.12); the bumped value lives on
    the AchOrigination resource, not on the freshly created AchLeg (whose own version
    begins at its initial value per PRD §2.4), so the next leg add / settle reads it
    back from the origination."""
    return get_success_data(
        api_client.get_ach_origination(origination_id, make_officer_headers(OFFICER_ID))
    )["version"]


def stage_batch_with_legs(debtor_account_id, creditor_account_id, legs,
                          posting_order="CHRONOLOGICAL"):
    """Stage a batch and append legs in order (PRD §3.12).

    legs: list of (leg_role, amount_cents) tuples, appended oldest-first.
    Returns (origination_id, current_version) where current_version is the
    origination version after the last leg add (the value a correct settle must use).

    The version threaded into each leg add and the final settle is the ORIGINATION's
    current version (PRD §2.6: "adding ... a leg ... legitimately bumps the version"),
    re-read from the origination after each add — not the leg's own version field.
    """
    origination = stage_ach_origination(
        debtor_account_id, creditor_account_id, posting_order
    )
    version = origination["version"]
    for leg_role, amount_cents in legs:
        add_leg(origination["id"], leg_role, amount_cents, version)
        version = origination_version(origination["id"])
    return origination["id"], version


def settle_batch(origination_id, expected_version):
    """Settle a STAGED batch (PRD §3.13). Returns the SETTLED AchOrigination."""
    return get_success_data(
        api_client.settle_ach_origination(
            origination_id, settle_payload(expected_version),
            make_officer_headers(OFFICER_ID),
        )
    )


# ─── Tier 4: Dormancy / escheat staging ───────────────────────────────
def open_account_then_make_dormant(open_clock, scan_clock, deposit_cents=30000):
    """Open a checking account at open_clock, deposit, advance the clock to scan_clock,
    and run the dormancy scan so the account is DORMANT (PRD §3.7).

    Returns (customer, account_after_scan). Caller is responsible for having created
    the CHK_STD tier and for any clock the opening needs; this helper sets the clock
    itself at the two given instants.
    """
    set_clock(open_clock)
    cust, account = open_account()
    holder = make_account_holder_headers(cust["id"])
    if deposit_cents:
        get_success_data(
            api_client.create_transaction(
                account["id"], transaction_payload("DEPOSIT", deposit_cents), holder
            )
        )
    set_clock(scan_clock)
    account = get_success_data(
        api_client.run_dormancy_scan(account["id"], make_officer_headers(OFFICER_ID))
    )
    return cust, account


# ─── Read helpers ─────────────────────────────────────────────────────
def account_holder_headers_for(customer_id):
    """Sugar: AccountHolder headers bound to a real Customer.id (PRD §2.1)."""
    return make_account_holder_headers(customer_id)


def list_all_fee_assessments(account_id, customer_id):
    """List every fee assessment on an account (PRD §3.6). Returns the data list."""
    holder = make_account_holder_headers(customer_id)
    data, _meta = _paginate_all(
        lambda offset: api_client.list_account_fee_assessments(
            account_id, holder, params={"limit": 100, "offset": offset}
        )
    )
    return data


def list_all_transactions(account_id, customer_id):
    """List every transaction on an account (PRD §3.4). Returns the data list."""
    holder = make_account_holder_headers(customer_id)
    data, _meta = _paginate_all(
        lambda offset: api_client.list_account_transactions(
            account_id, holder, params={"limit": 100, "offset": offset}
        )
    )
    return data


def _paginate_all(call):
    """Drain a paginated list endpoint (PRD §2.3). Returns (all_items, last_meta)."""
    items = []
    offset = 0
    last_meta = {}
    while True:
        resp = call(offset)
        body = resp.json()
        page = body["data"]
        last_meta = body.get("meta", {})
        items.extend(page)
        if not last_meta.get("has_more"):
            break
        offset += len(page) or 100
        if not page:
            break
    return items, last_meta
