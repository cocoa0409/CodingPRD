"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors, not confusing assertion failures. Each helper builds
its preconditions from scratch — the server DB is empty before every test.

Operator-id convention (PRD §2.7 segregation of duties): transactions are created
by the Teller "teller-1"; managers resolve them as "manager-9" (distinct id) so
SoD is satisfied on release/reject/void unless a test deliberately reuses an id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_compliance_screen_payload,
    create_fee_schedule_payload, create_cash_drawer_payload,
    create_check_cash_payload, create_money_order_payload,
    return_payload, recover_payload, close_payload,
    GOVT_SCHEDULE, PAYROLL_DIVERGENT_SCHEDULE,
)
from .test_users import make_teller_headers, make_store_manager_headers

TELLER = make_teller_headers("teller-1")
MANAGER = make_store_manager_headers("manager-9")


# ─── Clock ────────────────────────────────────────────
def set_clock(iso8601: str):
    """Advance the server logical clock (StoreManager-only, PRD §3.8)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, MANAGER))


# ─── Tier 1: Primitive entities ───────────────────────
def create_customer(full_name="Test Customer", id_type="DRIVERS_LICENSE",
                    id_number="DL-1", date_of_birth="1990-01-01"):
    """Register a PENDING customer (PRD §3.1)."""
    res = api_client.create_customer(
        create_customer_payload(full_name=full_name, id_type=id_type,
                                id_number=id_number, date_of_birth=date_of_birth),
        TELLER)
    return get_success_data(res)


def screen_customer(customer_id, ofac_list_hit=False, kyc_documents_valid=True):
    """Run a compliance screen; writes outcome to Customer.kyc_status (PRD §3.1)."""
    res = api_client.create_compliance_screen(
        create_compliance_screen_payload(customer_id, ofac_list_hit, kyc_documents_valid),
        MANAGER)
    return get_success_data(res)


def create_verified_customer(full_name="Verified Customer", id_type="DRIVERS_LICENSE",
                             id_number="DL-V", date_of_birth="1990-01-01"):
    """Register + screen VERIFIED. Returns the post-screen customer (kyc_status VERIFIED)."""
    cust = create_customer(full_name, id_type, id_number, date_of_birth)
    screen_customer(cust["id"], ofac_list_hit=False, kyc_documents_valid=True)
    return get_success_data(api_client.get_customer(cust["id"], TELLER))


def create_fee_schedule(**overrides):
    """Create a fee schedule (StoreManager, PRD §3.2). Defaults to GOVERNMENT schedule."""
    payload = create_fee_schedule_payload(**overrides)
    return get_success_data(api_client.create_fee_schedule(payload, MANAGER))


def create_govt_schedule():
    return get_success_data(api_client.create_fee_schedule(dict(GOVT_SCHEDULE), MANAGER))


def create_payroll_divergent_schedule():
    return get_success_data(api_client.create_fee_schedule(dict(PAYROLL_DIVERGENT_SCHEDULE), MANAGER))


def open_drawer(store_code="S1", business_date="2026-05-01", opening_float_cents=1000000):
    """Open a cash drawer (StoreManager, PRD §3.3)."""
    res = api_client.create_cash_drawer(
        create_cash_drawer_payload(store_code=store_code, business_date=business_date,
                                   opening_float_cents=opening_float_cents),
        MANAGER)
    return get_success_data(res)


# ─── Tier 2: Common scenarios ─────────────────────────
def setup_verified_customer_and_drawer(store_code="S1", opening_float_cents=1000000,
                                       business_date="2026-05-01"):
    """VERIFIED customer + OPEN drawer (no fee schedule). Returns (customer, drawer)."""
    cust = create_verified_customer(id_number=f"DL-{store_code}")
    drawer = open_drawer(store_code=store_code, business_date=business_date,
                         opening_float_cents=opening_float_cents)
    return cust, drawer


def setup_verified_customer_drawer_and_schedule(store_code="S1", opening_float_cents=1000000,
                                                schedule_overrides=None):
    """VERIFIED customer + OPEN drawer + active GOVERNMENT fee schedule.
    Returns (customer, drawer, schedule)."""
    cust, drawer = setup_verified_customer_and_drawer(store_code, opening_float_cents)
    overrides = schedule_overrides or {}
    sched = create_fee_schedule(**overrides) if overrides else create_govt_schedule()
    return cust, drawer, sched


# ─── Tier 3: Posting shortcuts ────────────────────────
def post_check_cash(customer_id, drawer_id, schedule_id, face_amount_cents,
                    maker_account_risk="LOW", teller_id="teller-1"):
    """POST a CHECK_CASH transaction. Returns the Transaction (POSTED if auto-cleared,
    DRAFT if RISK_HELD) (PRD §3.4, §3.5)."""
    res = api_client.create_transaction(
        create_check_cash_payload(customer_id, drawer_id, face_amount_cents,
                                  schedule_id, maker_account_risk),
        make_teller_headers(teller_id))
    return get_success_data(res)


def post_money_order(customer_id, drawer_id, face_amount_cents, payee_name="Acme",
                     teller_id="teller-1"):
    """POST a MONEY_ORDER (auto-posts, settles, mints child) (PRD §3.4, §3.6)."""
    res = api_client.create_transaction(
        create_money_order_payload(customer_id, drawer_id, face_amount_cents, payee_name),
        make_teller_headers(teller_id))
    return get_success_data(res)


def get_check_item_for_transaction(transaction_id, headers=None):
    """Return the single CheckItem dict backing a CHECK_CASH transaction (PRD §3.5)."""
    res = api_client.list_transaction_check_items(transaction_id, headers or MANAGER)
    data = get_success_data(res)
    items = data if isinstance(data, list) else data.get("data", data)
    assert items, f"expected one check item for transaction {transaction_id}"
    return items[0]


def setup_risk_held_check(store_code="S5", face_amount_cents=350000,
                          maker_account_risk="LOW", teller_id="teller-1",
                          schedule="payroll"):
    """VERIFIED customer + drawer + schedule + a RISK_HELD CHECK_CASH check.

    With face >= 300000 (AMOUNT_THRESHOLD) or maker HIGH the check is held and the
    parent transaction stays DRAFT. Returns (customer, drawer, schedule, transaction,
    check_item)."""
    cust, drawer = setup_verified_customer_and_drawer(store_code,
                                                      opening_float_cents=2000000)
    sched = (create_payroll_divergent_schedule() if schedule == "payroll"
             else create_govt_schedule())
    txn = post_check_cash(cust["id"], drawer["id"], sched["id"], face_amount_cents,
                          maker_account_risk=maker_account_risk, teller_id=teller_id)
    check = get_check_item_for_transaction(txn["id"])
    return cust, drawer, sched, txn, check


def setup_returned_check(store_code="S6", face_amount_cents=100000,
                         return_reason="NSF", teller_id="teller-1"):
    """VERIFIED customer + GOVT schedule + OPEN drawer + a POSTED+SETTLED CHECK_CASH
    that is then RETURNED. Returns (customer, drawer, schedule, transaction, returned_item).
    total_owed = face + RETURN_FEE_CENTS(2500)."""
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code, opening_float_cents=1000000)
    txn = post_check_cash(cust["id"], drawer["id"], sched["id"], face_amount_cents,
                          maker_account_risk="LOW", teller_id=teller_id)
    ri = get_success_data(api_client.return_transaction(
        txn["id"], return_payload(return_reason), MANAGER))
    return cust, drawer, sched, txn, ri


def setup_partially_recovered_check(store_code="S-PR", face_amount_cents=100000,
                                    first_recovery=40000, teller_id="teller-1"):
    """A RETURNED CHECK_CASH (total_owed = face + 2500) with `first_recovery` already
    applied, leaving the item PARTIALLY_RECOVERED. Returns (customer, drawer, schedule,
    transaction, returned_item)."""
    cust, drawer, sched, txn, ri = setup_returned_check(
        store_code=store_code, face_amount_cents=face_amount_cents, teller_id=teller_id)
    get_success_data(api_client.recover_returned_item(
        ri["id"], recover_payload(first_recovery), make_teller_headers(teller_id)))
    ri = get_success_data(api_client.get_returned_item(ri["id"], MANAGER))
    return cust, drawer, sched, txn, ri


# ─── Tier 4: Drawer reconciliation ────────────────────
def reconcile_drawer(drawer_id):
    """Move a drawer OPEN -> RECONCILING (PRD §3.7)."""
    return get_success_data(api_client.begin_reconcile_drawer(drawer_id, MANAGER))


def current_drawer_version(drawer_id):
    """Fetch the drawer's current version (used for OCC close, PRD §2.10)."""
    return get_success_data(api_client.get_cash_drawer(drawer_id, MANAGER))["version"]


def reconcile_and_close(drawer_id, counted_cash_cents):
    """begin-reconcile -> read version -> close with a matching count.
    Returns the closed drawer (PRD §3.7)."""
    reconcile_drawer(drawer_id)
    version = current_drawer_version(drawer_id)
    return get_success_data(api_client.close_drawer(
        drawer_id, close_payload(counted_cash_cents, version), MANAGER))


def setup_reconciling_drawer(store_code="C8", opening_float_cents=500000):
    """An OPEN drawer with no postings, moved to RECONCILING (expected == opening_float).
    Returns (drawer, version) where version is read AFTER begin-reconcile."""
    drawer = open_drawer(store_code=store_code, opening_float_cents=opening_float_cents)
    reconcile_drawer(drawer["id"])
    version = current_drawer_version(drawer["id"])
    return drawer, version


def setup_closed_drawer(store_code="C7", opening_float_cents=300000):
    """An OPEN drawer with no postings, begin-reconciled then CLOSED with a matching
    count. Returns the closed drawer (terminal CLOSED state)."""
    drawer = open_drawer(store_code=store_code, opening_float_cents=opening_float_cents)
    return reconcile_and_close(drawer["id"], opening_float_cents)


# ─── Tier 5: Velocity saturation ──────────────────────
def setup_velocity_saturated_customer(store_code="S16", clock="2026-05-01T08:00:00Z",
                                      n=12, face_amount_cents=1000):
    """Set clock, create a VERIFIED customer and OPEN drawer, then post `n` MONEY_ORDERs
    (each face=`face_amount_cents`) inside the window so daily_transaction_count == n.
    Returns (customer, drawer)."""
    set_clock(clock)
    cust, drawer = setup_verified_customer_and_drawer(store_code,
                                                      opening_float_cents=1000000)
    for i in range(n):
        post_money_order(cust["id"], drawer["id"], face_amount_cents,
                         payee_name=f"P{i + 1}")
    return cust, drawer
