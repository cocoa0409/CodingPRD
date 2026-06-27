"""Composite setup helpers for multi-step test prerequisites (Kids Allowance & Chore Card).

Every helper builds its preconditions from scratch using only PRD-declared endpoints, because
the server is restarted (empty DB) before every test. Setup calls use get_success_data()
(lenient) so a setup failure surfaces clearly rather than as a confusing assertion failure.

Identity threading: Child is entity_backed:ChildAccount. Ownership-gated child calls
(submit/resubmit/lock/authorize/orders on own resources) use make_child_headers(child["id"]).
Parents are opaque: each fixture registers its family with a distinct parent operator id and
reuses make_parent_headers(parent_id) for all calls on that family.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_family_payload, deposit_payload, alert_thresholds_payload,
    create_child_payload, fund_jar_payload, create_chore_payload,
    create_control_payload, authorize_payload, settle_payload, lock_payload,
    create_schedule_payload, configure_interest_payload, accrue_payload,
    order_payload, set_clock_payload,
)
from .test_users import make_parent_headers, make_child_headers, make_admin_headers

# Unique parent operator ids so distinct fixture invocations never collide on ownership.
_parent_seq = itertools.count(1)


def _next_parent_id() -> str:
    return f"parent-{next(_parent_seq)}"


ADMIN = make_admin_headers()


# ─── Clock ────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Set the logical clock (PlatformAdmin). Returns the response data."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


# ─── Tier 1: Family + Child base scaffolding ──────────
def create_family(deposit_cents: int = 0, family_name: str = "Test Family"):
    """Register a family and (optionally) deposit funding. Returns (family, parent_headers)."""
    parent_id = _next_parent_id()
    parent_headers = make_parent_headers(parent_id)
    fam = get_success_data(api_client.create_family(
        create_family_payload(family_name=family_name), parent_headers))
    if deposit_cents:
        fam = get_success_data(api_client.deposit(
            fam["id"], deposit_payload(deposit_cents), parent_headers))
    return fam, parent_headers


def create_child(family_id, parent_headers, birthdate: str = "2015-01-01", display_name: str = "Test Child"):
    """Create a child under a family. Returns the child (auto-creates jars/card/config)."""
    return get_success_data(api_client.create_child_account(
        family_id, create_child_payload(display_name=display_name, birthdate=birthdate),
        parent_headers))


def get_spend_jar_id(child_id, parent_headers) -> str:
    jars = get_success_data(api_client.list_jars(child_id, parent_headers, params={"jar_type": "SPEND"}))
    return jars[0]["id"]


def get_save_jar_id(child_id, parent_headers) -> str:
    jars = get_success_data(api_client.list_jars(child_id, parent_headers, params={"jar_type": "SAVE"}))
    return jars[0]["id"]


def get_card(child_id, parent_headers) -> dict:
    cards = get_success_data(api_client.list_debit_cards(child_id, parent_headers))
    return cards[0]


def get_interest_config_id(child_id, parent_headers) -> str:
    cfgs = get_success_data(api_client.get_child_interest_config(child_id, parent_headers))
    return cfgs[0]["id"]


def setup_family_with_child(deposit_cents: int = 0, birthdate: str = "2015-01-01"):
    """Family (optionally funded) + one child. Returns (family, child, parent_headers)."""
    fam, parent_headers = create_family(deposit_cents=deposit_cents)
    child = create_child(fam["id"], parent_headers, birthdate=birthdate)
    return fam, child, parent_headers


# ─── Tier 2: Funded-jar / card-ready scenarios ────────
def setup_child_with_funded_spend_jar(spend_cents: int, deposit_cents: int = None):
    """
    Family + child with `spend_cents` credited to the SPEND jar (card becomes FUNDED).
    deposit_cents defaults to spend_cents + a buffer so fund-jar always succeeds.
    Returns (family, child, card, spend_jar_id, parent_headers).
    """
    if deposit_cents is None:
        deposit_cents = spend_cents + 50_000
    fam, child, parent_headers = setup_family_with_child(deposit_cents=deposit_cents)
    spend_jar_id = get_spend_jar_id(child["id"], parent_headers)
    if spend_cents:
        get_success_data(api_client.fund_jar(
            child["id"], fund_jar_payload("SPEND", spend_cents), parent_headers))
    card = get_card(child["id"], parent_headers)
    return fam, child, card, spend_jar_id, parent_headers


def lock_card(card_id, card_version, headers):
    """Lock a card with the supplied (current) version. Returns the updated card."""
    return get_success_data(api_client.lock_card(card_id, lock_payload(card_version), headers))


def setup_locked_card(spend_cents: int = 0, deposit_cents: int = 0):
    """
    Family + child whose card is LOCKED. Optionally funds the SPEND jar (funding evolves
    independently of lock). Returns (family, child, card_after_lock, spend_jar_id, parent_headers).
    The card is locked at its initial version BEFORE any funding so the lock version is fresh.
    """
    fam, child, parent_headers = setup_family_with_child(deposit_cents=deposit_cents)
    spend_jar_id = get_spend_jar_id(child["id"], parent_headers)
    card = get_card(child["id"], parent_headers)
    locked = lock_card(card["id"], card["version"], parent_headers)
    if spend_cents:
        get_success_data(api_client.fund_jar(
            child["id"], fund_jar_payload("SPEND", spend_cents), parent_headers))
        locked = get_success_data(api_client.get_debit_card(card["id"], parent_headers))
    return fam, child, locked, spend_jar_id, parent_headers


def place_authorization(card_id, child_id, amount_cents, merchant_id="M1", category="FOOD", **extra):
    """Place an authorization as the owning Child. Returns the created Transaction."""
    child_headers = make_child_headers(child_id)
    payload = authorize_payload(merchant_id, category, amount_cents, **extra)
    return get_success_data(api_client.authorize(card_id, payload, child_headers))


def setup_pending_authorization(spend_cents: int, auth_cents: int,
                                merchant_id="M1", category="FOOD"):
    """
    Family + child with SPEND jar funded `spend_cents`, then one PENDING authorization for
    `auth_cents` placed by the child. Returns
    (family, child, card, spend_jar_id, txn, parent_headers).
    """
    fam, child, card, spend_jar_id, parent_headers = setup_child_with_funded_spend_jar(
        spend_cents, deposit_cents=spend_cents + 50_000)
    txn = place_authorization(card["id"], child["id"], auth_cents,
                              merchant_id=merchant_id, category=category)
    card = get_success_data(api_client.get_debit_card(card["id"], parent_headers))
    return fam, child, card, spend_jar_id, txn, parent_headers


def create_limit_control(card, match_value, control_kind, cap_cents, parent_headers):
    """Create an active LIMIT control on a card. Returns (control, refreshed_card)."""
    ctl = get_success_data(api_client.create_control(
        card["id"],
        create_control_payload(control_kind, match_value, "LIMIT", card["version"],
                               per_period_cap_cents=cap_cents),
        parent_headers))
    refreshed = get_success_data(api_client.get_debit_card(card["id"], parent_headers))
    return ctl, refreshed


def create_block_control(card, match_value, control_kind, parent_headers):
    """Create an active BLOCK control on a card. Returns (control, refreshed_card)."""
    ctl = get_success_data(api_client.create_control(
        card["id"],
        create_control_payload(control_kind, match_value, "BLOCK", card["version"]),
        parent_headers))
    refreshed = get_success_data(api_client.get_debit_card(card["id"], parent_headers))
    return ctl, refreshed


# ─── Tier 3: Chore-to-reward pipeline shortcuts ───────
def create_chore(child_id, parent_headers, reward_cents=500, payout_jar_type=None,
                 title="Test Chore", is_recurring=None):
    overrides = {}
    if payout_jar_type is not None:
        overrides["payout_jar_type"] = payout_jar_type
    if is_recurring is not None:
        overrides["is_recurring"] = is_recurring
    return get_success_data(api_client.create_chore(
        child_id, create_chore_payload(title=title, reward_cents=reward_cents, **overrides),
        parent_headers))


def submit_chore(chore_id, child_id):
    """Child submits a chore; returns the created ChoreCompletion (PENDING_REVIEW)."""
    return get_success_data(api_client.submit_chore(chore_id, make_child_headers(child_id)))


def setup_pending_completion(deposit_cents: int, reward_cents: int, payout_jar_type=None,
                             birthdate: str = "2015-01-01"):
    """
    Family funded `deposit_cents` + child + chore (reward_cents) submitted to a PENDING_REVIEW
    completion. Returns (family, child, chore, completion, parent_headers).
    """
    fam, child, parent_headers = setup_family_with_child(deposit_cents=deposit_cents, birthdate=birthdate)
    chore = create_chore(child["id"], parent_headers, reward_cents=reward_cents,
                         payout_jar_type=payout_jar_type)
    completion = submit_chore(chore["id"], child["id"])
    return fam, child, chore, completion, parent_headers


# ─── Tier 4: Allowance schedule scenarios ─────────────
def create_schedule(child_id, parent_headers, amount_cents, cadence_days, next_run_at,
                    payout_jar_type=None):
    overrides = {}
    if payout_jar_type is not None:
        overrides["payout_jar_type"] = payout_jar_type
    return get_success_data(api_client.create_allowance_schedule(
        child_id,
        create_schedule_payload(amount_cents, cadence_days, next_run_at, **overrides),
        parent_headers))


def setup_due_schedule(deposit_cents: int, amount_cents: int, clock_iso: str,
                       next_run_at: str, cadence_days: int = 7, payout_jar_type=None):
    """
    Clock set to `clock_iso`; family funded `deposit_cents`; child with one ACTIVE schedule due
    at `next_run_at`. Returns (family, child, schedule, spend_jar_id, parent_headers).
    """
    set_clock(clock_iso)
    fam, child, parent_headers = setup_family_with_child(deposit_cents=deposit_cents)
    spend_jar_id = get_spend_jar_id(child["id"], parent_headers)
    sched = create_schedule(child["id"], parent_headers, amount_cents, cadence_days,
                            next_run_at, payout_jar_type=payout_jar_type)
    return fam, child, sched, spend_jar_id, parent_headers


def run_due_allowances():
    """Trigger the allowance sweep (PlatformAdmin). Returns the list of created runs."""
    return get_success_data(api_client.run_due_allowances(ADMIN))


# ─── Tier 5: Interest match scenarios ─────────────────
def setup_enabled_interest(save_cents: int, annual_rate_bps: int, monthly_cap_cents: int,
                           accrual_method: str = "WHOLE_PERIOD", clock_iso: str = None,
                           deposit_cents: int = 200_000):
    """
    Clock optionally set; family funded; child with SAVE jar holding `save_cents` and an ENABLED
    InterestMatchConfig. Returns (family, child, save_jar_id, config_id, parent_headers).
    """
    if clock_iso:
        set_clock(clock_iso)
    fam, child, parent_headers = setup_family_with_child(deposit_cents=deposit_cents)
    save_jar_id = get_save_jar_id(child["id"], parent_headers)
    if save_cents:
        get_success_data(api_client.fund_jar(
            child["id"], fund_jar_payload("SAVE", save_cents), parent_headers))
    cfg_id = get_interest_config_id(child["id"], parent_headers)
    get_success_data(api_client.configure_interest(
        cfg_id,
        configure_interest_payload(annual_rate_bps, monthly_cap_cents, accrual_method),
        parent_headers))
    return fam, child, save_jar_id, cfg_id, parent_headers


# ─── Tier 6: Teen investing scenarios ─────────────────
def setup_teen_investment_account(cash_cents: int = 0, save_seed_cents: int = 60_000,
                                  clock_iso: str = "2026-06-26T00:00:00Z",
                                  deposit_cents: int = 100_000):
    """
    Clock set so the child (born 2010) is a teen; family funded; child with SAVE jar seeded and an
    ACTIVE InvestmentAccount. If cash_cents > 0, funds that much investing cash from the SAVE jar.
    Returns (family, child, inv, parent_headers).
    """
    set_clock(clock_iso)
    fam, child, parent_headers = setup_family_with_child(
        deposit_cents=deposit_cents, birthdate="2010-01-01")
    if save_seed_cents:
        get_success_data(api_client.fund_jar(
            child["id"], fund_jar_payload("SAVE", save_seed_cents), parent_headers))
    inv = get_success_data(api_client.enable_investing(child["id"], parent_headers))
    if cash_cents:
        inv = get_success_data(api_client.fund_investment(
            inv["id"], deposit_payload(cash_cents), parent_headers))
    return fam, child, inv, parent_headers


def place_order(inv_id, parent_headers, side, symbol, shares_milli, price_cents_per_share):
    return get_success_data(api_client.place_order(
        inv_id, order_payload(side, symbol, shares_milli, price_cents_per_share), parent_headers))
