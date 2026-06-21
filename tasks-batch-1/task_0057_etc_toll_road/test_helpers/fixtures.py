"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"setup failed" errors, not confusing assertion failures.

Identity threading: after creating an Account, every ownership-gated AccountHolder call
(binding, end-binding, hov-window, contest, pay) uses make_account_holder_headers(account_id)
— never the shared TEST_USERS constant (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_account_payload, create_vehicle_payload, create_transponder_payload,
    create_transponder_binding_payload, create_hov_window_payload, create_plaza_payload,
    create_toll_transaction_payload, create_interop_agency_payload,
)
from .test_users import TEST_USERS, make_account_holder_headers

OP = TEST_USERS["toll_operator_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
CLERK = TEST_USERS["interop_clerk_headers"]


# ─── Tier 1: Primitive creators ──────────────────────────────────────────────

def create_account(**overrides) -> dict:
    """Create an account (TollOperator). Returns the Account dict."""
    res = api_client.create_account(create_account_payload(**overrides), OP)
    return get_success_data(res)


def credit_account(account_id: str, amount_cents: int) -> dict:
    res = api_client.credit_account(account_id, {"amount_cents": amount_cents}, OP)
    return get_success_data(res)


def create_vehicle(account_id: str, **overrides) -> dict:
    res = api_client.create_vehicle(create_vehicle_payload(account_id, **overrides), OP)
    return get_success_data(res)


def create_transponder(account_id: str, serial: str) -> dict:
    res = api_client.create_transponder(create_transponder_payload(account_id, serial), OP)
    return get_success_data(res)


def create_plaza(**overrides) -> dict:
    res = api_client.create_plaza(create_plaza_payload(**overrides), OP)
    return get_success_data(res)


def create_interop_agency(**overrides) -> dict:
    res = api_client.create_interop_agency(create_interop_agency_payload(**overrides), ADMIN)
    return get_success_data(res)


# ─── Tier 2: Bound transponder / vehicle scaffolding ─────────────────────────

def bind_transponder(account_id: str, transponder_id: str, vehicle_id: str,
                     vehicle_version: int, effective_from: str = "2026-01-01T00:00:00Z",
                     effective_to: str = None) -> dict:
    """Bind a transponder to a vehicle as the owning AccountHolder. Returns binding dict."""
    payload = create_transponder_binding_payload(
        transponder_id, vehicle_id, effective_from, vehicle_version)
    if effective_to is not None:
        payload["effective_to"] = effective_to
    res = api_client.create_transponder_binding(payload, make_account_holder_headers(account_id))
    return get_success_data(res)


def setup_bound_account(serial: str = "TP-SETUP", credit: int = 0, vehicle_overrides=None,
                        account_overrides=None):
    """
    Active account + vehicle + transponder bound to it. Optionally credit the balance.
    Returns (account, vehicle, transponder, binding).
    """
    account = create_account(**(account_overrides or {}))
    if credit:
        credit_account(account["id"], credit)
    vehicle = create_vehicle(account["id"], **(vehicle_overrides or {}))
    transponder = create_transponder(account["id"], serial)
    binding = bind_transponder(account["id"], transponder["id"], vehicle["id"],
                               vehicle["version"])
    return account, vehicle, transponder, binding


# ─── Tier 3: Toll-transaction lifecycle helpers ──────────────────────────────

def record_transponder_read(plaza_id: str, transponder_id: str, read_at: str,
                            is_peak: bool, declared_axles: int = 2) -> dict:
    res = api_client.create_toll_transaction(
        create_toll_transaction_payload(
            plaza_id, "TRANSPONDER", read_at, is_peak,
            declared_axles=declared_axles, transponder_id=transponder_id),
        OP)
    return get_success_data(res)


def record_plate_read(plaza_id: str, plate_number: str, plate_state_code: str, read_at: str,
                      is_peak: bool, declared_axles: int = 2, interop_agency_id: str = None,
                      as_headers=None) -> dict:
    payload = create_toll_transaction_payload(
        plaza_id, "PLATE", read_at, is_peak,
        declared_axles=declared_axles, plate_number=plate_number,
        plate_state_code=plate_state_code)
    if interop_agency_id is not None:
        payload["interop_agency_id"] = interop_agency_id
    res = api_client.create_toll_transaction(payload, as_headers or OP)
    return get_success_data(res)


def price(txn_id: str) -> dict:
    return get_success_data(api_client.price_toll_transaction(txn_id, OP))


def setup_priced_transponder_read(base_rate_cents: int, is_peak: bool, declared_axles: int = 2,
                                  credit: int = 100000, plaza_overrides=None,
                                  vehicle_overrides=None, account_overrides=None,
                                  serial: str = "TP-PR"):
    """
    Funded account + bound transponder + plaza + one PRICED transponder transaction.
    Returns (account, vehicle, transponder, plaza, txn).
    """
    account, vehicle, transponder, _ = setup_bound_account(
        serial=serial, credit=credit, vehicle_overrides=vehicle_overrides,
        account_overrides=account_overrides)
    pl_over = dict(plaza_overrides or {})
    pl_over.setdefault("base_rate_cents", base_rate_cents)
    plaza = create_plaza(**pl_over)
    txn = record_transponder_read(plaza["id"], transponder["id"], "2026-02-01T08:00:00Z",
                                  is_peak, declared_axles=declared_axles)
    txn = price(txn["id"])
    return account, vehicle, transponder, plaza, txn


def setup_plate_violation(plaza_overrides=None, account_overrides=None,
                          plate_number: str = "PLT1"):
    """
    Account (no transponder) + REGISTERED vehicle + plaza + PLATE read that has been
    PRICED and left UNSETTLED, then escalated into an ASSESSED Violation.
    Returns (account, vehicle, plaza, txn, violation).
    """
    account = create_account(**(account_overrides or {}))
    vehicle = create_vehicle(account["id"], plate_number=plate_number)
    pl_over = dict(plaza_overrides or {})
    pl_over.setdefault("base_rate_cents", 400)
    pl_over.setdefault("peak_multiplier_bps", 2500)
    pl_over.setdefault("plate_surcharge_bps", 5000)
    plaza = create_plaza(**pl_over)
    txn = record_plate_read(plaza["id"], plate_number, "NY", "2026-02-01T08:00:00Z",
                            is_peak=True, declared_axles=2)
    txn = price(txn["id"])
    viol = get_success_data(api_client.create_violation({"toll_transaction_id": txn["id"]}, OP))
    return account, vehicle, plaza, txn, viol


def setup_priced_unsettled_plate_read(plaza_overrides=None, plate_number: str = "PLT2"):
    """
    Account + REGISTERED vehicle + plaza + PLATE read PRICED & still UNSETTLED (no violation).
    Returns (account, vehicle, plaza, txn).
    """
    account = create_account()
    vehicle = create_vehicle(account["id"], plate_number=plate_number)
    pl_over = dict(plaza_overrides or {})
    pl_over.setdefault("base_rate_cents", 400)
    pl_over.setdefault("peak_multiplier_bps", 2500)
    pl_over.setdefault("plate_surcharge_bps", 5000)
    plaza = create_plaza(**pl_over)
    txn = record_plate_read(plaza["id"], plate_number, "NY", "2026-02-01T08:00:00Z",
                            is_peak=True, declared_axles=2)
    txn = price(txn["id"])
    return account, vehicle, plaza, txn


# ─── Tier 4: Auto-reload / threshold targeting ───────────────────────────────

def setup_account_near_threshold(seed_balance: int, threshold: int = 1000,
                                 reload_amount: int = 4000, reload_policy: str = "FIXED",
                                 target_balance: int = 5000, base_rate_cents: int = 400,
                                 serial: str = "TP-AR"):
    """
    Account with auto-reload armed, balance seeded to `seed_balance`, bound transponder,
    and an off-peak plaza of `base_rate_cents` plus one PENDING transponder read.
    The test triggers .../price to drive the balance across the threshold.
    Returns (account, txn).
    """
    acct_over = {
        "auto_reload_enabled": True,
        "reload_policy": reload_policy,
        "low_balance_threshold_cents": threshold,
    }
    if reload_policy == "FIXED":
        acct_over["reload_amount_cents"] = reload_amount
    else:
        acct_over["target_balance_cents"] = target_balance
    account, vehicle, transponder, _ = setup_bound_account(
        serial=serial, credit=seed_balance, account_overrides=acct_over)
    plaza = create_plaza(base_rate_cents=base_rate_cents)
    txn = record_transponder_read(plaza["id"], transponder["id"], "2026-02-01T03:00:00Z",
                                  is_peak=False, declared_axles=2)
    return account, txn


# ─── Tier 5: Account lifecycle / terminal helpers ────────────────────────────

def setup_suspended_account_with_bound_transponder(serial: str = "TP-SUS"):
    """Active account + bound transponder, then suspend the account.
    Returns (account, vehicle, transponder, binding) (post-suspend states must be re-fetched)."""
    account, vehicle, transponder, binding = setup_bound_account(serial=serial)
    api_client.suspend_account(account["id"], OP)
    return account, vehicle, transponder, binding


def setup_delinquent_account_contested():
    """
    Account driven DELINQUENT by its sole violation, then that violation CONTESTED.
    Returns (account, vehicle, plaza, txn, violation).
    """
    account, vehicle, plaza, txn, viol = setup_plate_violation(plate_number="DEL1")
    api_client.contest_violation(viol["id"], {"dispute_reason": "wrong plate"},
                                 make_account_holder_headers(account["id"]))
    return account, vehicle, plaza, txn, viol
