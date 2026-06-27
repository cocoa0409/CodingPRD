"""Cross-entity domain operations: drawer aggregation, customer risk/velocity
cascades. Each mutated resource independently bumps its own version/updated_at
(PRD §2.4)."""
from clock import clock, add_hours
from db import db, touch

from services import calculations as calc


def recompute_drawer_expected_cash(drawer):
    """Recompute expected_cash_cents from scratch over all POSTED transactions
    on the drawer (PRD §3.5, §2.9). Bumps the drawer version/updated_at."""
    cash_out = 0
    cash_in = 0
    for txn in db.transactions.values():
        if txn["drawer_id"] != drawer["id"]:
            continue
        if txn["lifecycle_state"] != "POSTED":
            continue
        if txn["txn_type"] == "CHECK_CASH":
            cash_out += txn["face_amount_cents"] - txn["fee_cents"]
        else:
            cash_in += txn["face_amount_cents"] + txn["fee_cents"]
    drawer["expected_cash_cents"] = drawer["opening_float_cents"] - cash_out + cash_in
    touch(drawer)


def apply_risk_delta(customer, delta):
    """Add a confirmed risk delta to the customer's score (clamped 0..1000) and
    re-derive risk_tier (PRD §3.8). Bumps the customer version/updated_at."""
    new_score = calc.clamp_score(customer["risk_score"] + delta)
    customer["risk_score"] = new_score
    customer["risk_tier"] = calc.risk_tier_for_score(new_score)
    touch(customer)


def roll_velocity_window_if_needed(customer):
    """Lazily roll the rolling-24h window before a velocity check (PRD §3.8).
    Half-open: a posting whose clock time is at or after opened_at+24h rolls.
    Does NOT bump version (counters are advanced by the caller on success)."""
    now = clock.now()
    opened = customer.get("limit_window_opened_at")
    if opened is None or now >= add_hours(opened, 24):
        customer["limit_window_opened_at"] = now
        customer["daily_transaction_count"] = 0
        customer["daily_cashed_amount_cents"] = 0
