"""Payload factories — one per writable resource, input fields only.

Each factory returns a dict the caller can override via **overrides.
Only fields the PRD marks as client-supplied input are emitted; computed
and system fields (id, status, version, allocated_qty, etc.) are never sent.
"""
import itertools

_email_counter = itertools.count(1)
_sku_counter = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{next(_email_counter)}@example.com"


def unique_sku(prefix: str = "SKU") -> str:
    return f"{prefix}-{next(_sku_counter)}"


# ─── SubscriptionPlan ─────────────────────────────────────────────────────
def create_plan_payload(**overrides) -> dict:
    """Required: name, cadence, period_price_cents, box_item_count.
    Optional: prepaid_terms_offered (default []), prepaid_discount_pct (default 0)."""
    defaults = {
        "name": "Test Plan",
        "cadence": "MONTHLY",
        "period_price_cents": 6000,
        "box_item_count": 1,
    }
    defaults.update(overrides)
    return defaults


# ─── Product ──────────────────────────────────────────────────────────────
def create_product_payload(**overrides) -> dict:
    """Required: sku, name, on_hand_qty."""
    defaults = {
        "sku": unique_sku(),
        "name": "Test Product",
        "on_hand_qty": 5,
    }
    defaults.update(overrides)
    return defaults


def restock_payload(add_qty: int, **overrides) -> dict:
    defaults = {"add_qty": add_qty}
    defaults.update(overrides)
    return defaults


# ─── Subscriber ───────────────────────────────────────────────────────────
def create_subscriber_payload(**overrides) -> dict:
    """Required: email, full_name."""
    defaults = {
        "email": unique_email(),
        "full_name": "Test Subscriber",
    }
    defaults.update(overrides)
    return defaults


# ─── WalletEntry (manual adjustment) ──────────────────────────────────────
def create_wallet_entry_payload(amount_cents: int, kind: str = "ADJUSTMENT", **overrides) -> dict:
    """Required: amount_cents, kind. Optional: source_ref_id."""
    defaults = {"amount_cents": amount_cents, "kind": kind}
    defaults.update(overrides)
    return defaults


# ─── Subscription ─────────────────────────────────────────────────────────
def create_subscription_payload(subscriber_id: str, plan_id: str, **overrides) -> dict:
    """Required: subscriber_id, plan_id."""
    defaults = {"subscriber_id": subscriber_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


def pause_payload(paused_until: str, **overrides) -> dict:
    defaults = {"paused_until": paused_until}
    defaults.update(overrides)
    return defaults


def cancel_payload(effective: str = "IMMEDIATE", **overrides) -> dict:
    defaults = {"effective": effective}
    defaults.update(overrides)
    return defaults


def prepay_payload(term_periods: int, expected_subscription_version: int, **overrides) -> dict:
    defaults = {
        "term_periods": term_periods,
        "expected_subscription_version": expected_subscription_version,
    }
    defaults.update(overrides)
    return defaults


def retry_charge_payload(outcome: str = "PAID", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


# ─── BoxSelection ─────────────────────────────────────────────────────────
def create_box_selection_payload(period_index: int, product_ids=None, skip=None, **overrides) -> dict:
    """Required: period_index. Optional: product_ids, skip."""
    defaults = {"period_index": period_index}
    if product_ids is not None:
        defaults["product_ids"] = product_ids
    if skip is not None:
        defaults["skip"] = skip
    defaults.update(overrides)
    return defaults


def swap_box_payload(product_ids=None, skip=None, **overrides) -> dict:
    defaults = {}
    if product_ids is not None:
        defaults["product_ids"] = product_ids
    if skip is not None:
        defaults["skip"] = skip
    defaults.update(overrides)
    return defaults


# ─── ShippingWave ─────────────────────────────────────────────────────────
def create_wave_payload(cutoff_at: str, ship_date: str, cadence: str = "MONTHLY",
                        capacity: int = 10, **overrides) -> dict:
    """Required: cadence, cutoff_at, ship_date, capacity."""
    defaults = {
        "cadence": cadence,
        "cutoff_at": cutoff_at,
        "ship_date": ship_date,
        "capacity": capacity,
    }
    defaults.update(overrides)
    return defaults


# ─── Allocation ───────────────────────────────────────────────────────────
def create_allocation_payload(subscription_id: str, wave_id: str, box_selection_id: str,
                              expected_wave_version: int, **overrides) -> dict:
    """Required: subscription_id, wave_id, box_selection_id, expected_wave_version."""
    defaults = {
        "subscription_id": subscription_id,
        "wave_id": wave_id,
        "box_selection_id": box_selection_id,
        "expected_wave_version": expected_wave_version,
    }
    defaults.update(overrides)
    return defaults


# ─── GiftGrant ────────────────────────────────────────────────────────────
def create_gift_grant_payload(plan_id: str, gifter_subscriber_id: str, term_periods: int,
                              recipient_email: str, **overrides) -> dict:
    """Required: plan_id, gifter_subscriber_id, term_periods, recipient_email."""
    defaults = {
        "plan_id": plan_id,
        "gifter_subscriber_id": gifter_subscriber_id,
        "term_periods": term_periods,
        "recipient_email": recipient_email,
    }
    defaults.update(overrides)
    return defaults


def redeem_gift_payload(redemption_code: str, subscriber_id: str, **overrides) -> dict:
    defaults = {"redemption_code": redemption_code, "subscriber_id": subscriber_id}
    defaults.update(overrides)
    return defaults


# ─── Test-driving clock + renewal ─────────────────────────────────────────
def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


def renewal_run_payload(subscription_id=None, charge_outcome=None, **overrides) -> dict:
    defaults = {}
    if subscription_id is not None:
        defaults["subscription_id"] = subscription_id
    if charge_outcome is not None:
        defaults["charge_outcome"] = charge_outcome
    defaults.update(overrides)
    return defaults
