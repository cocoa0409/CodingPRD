"""Business logic: membership lifecycle, ledger, recomputation, clock-driven transitions."""
from datetime import timedelta

from clock import clock
from db import db, iso

TERM_DAYS = 365
NO_RECEIPT_WINDOW_DAYS = 90


# --------------------------------------------------------------------------- #
# Ledger entries / fee events (config/audit; id + created_at only)
# --------------------------------------------------------------------------- #
def add_ledger_entry(membership_id, entry_type, amount_cents, term_start_utc,
                     source_transaction_id=None):
    entry = {
        "membership_id": membership_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "source_transaction_id": source_transaction_id,
        "term_start_utc": term_start_utc,
    }
    db.stamp_config(entry)
    db.reward_ledger[entry["id"]] = entry
    return entry


def add_fee_event(membership_id, kind, amount_cents, term_start_utc):
    fe = {
        "membership_id": membership_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "term_start_utc": term_start_utc,
    }
    db.stamp_config(fe)
    db.fee_events[fe["id"]] = fe
    return fe


# --------------------------------------------------------------------------- #
# Derived-field recomputation on a membership
# --------------------------------------------------------------------------- #
def recompute_household_card_count(m):
    count = sum(
        1 for c in db.household_cards.values()
        if c["membership_id"] == m["id"] and c["status"] == "ACTIVE"
    )
    m["household_card_count"] = count


def recompute_fees_paid(m):
    """Sum of FeeEvents for the current term (term_start_utc == membership term)."""
    term = m.get("term_start_utc")
    total = 0
    for fe in db.fee_events.values():
        if fe["membership_id"] == m["id"] and fe["term_start_utc"] == term:
            total += fe["amount_cents"]
    m["fees_paid_cents"] = total


# --------------------------------------------------------------------------- #
# Term helpers
# --------------------------------------------------------------------------- #
def set_term(m, start_dt):
    end_dt = start_dt + timedelta(days=TERM_DAYS)
    m["term_start_utc"] = iso(start_dt)
    m["term_end_utc"] = iso(end_dt)


def get_plan(m):
    return db.plans.get(m["plan_id"])


# --------------------------------------------------------------------------- #
# Clock-driven term-boundary processing (lapse / auto-renew)
# --------------------------------------------------------------------------- #
def process_term_boundary(m):
    """If clock has advanced at/past term_end on an ACTIVE membership, lapse or
    auto-renew. Returns True if a mutation happened."""
    if m["status"] != "ACTIVE":
        return False
    term_end = m.get("term_end_utc")
    if not term_end:
        return False
    now = iso(clock.get())
    if now < term_end:
        return False

    plan = get_plan(m)
    term_start = m["term_start_utc"]

    if m.get("auto_renew") and _has_succeeded_renewal_payment(m):
        # Auto-renew: stay ACTIVE, same side effects as manual renewal.
        _expire_unredeemed_reward(m, term_start)
        # roll term: new start = old end
        old_end = m["term_end_utc"]
        from helpers import parse_dt
        new_start = parse_dt(old_end)
        set_term(m, new_start)
        m["reward_accrued_cents"] = 0
        m["reward_redeemed_cents"] = 0
        annual_fee = plan["annual_fee_cents"]
        add_fee_event(m["id"], "RENEWAL", annual_fee, m["term_start_utc"])
        recompute_fees_paid(m)
        db.touch(m)
        return True
    else:
        # Lapse to EXPIRED.
        _expire_unredeemed_reward(m, term_start)
        m["status"] = "EXPIRED"
        m["reward_accrued_cents"] = 0
        _revoke_all_cards(m)
        recompute_household_card_count(m)
        db.touch(m)
        return True


def _has_succeeded_renewal_payment(m):
    for p in db.payments.values():
        if (p["membership_id"] == m["id"] and p["purpose"] == "RENEWAL"
                and p["outcome"] == "SUCCEEDED"):
            return True
    return False


def _expire_unredeemed_reward(m, term_start):
    """Write an EXPIRY ledger entry zeroing unredeemed reward from the term."""
    unredeemed = m["reward_accrued_cents"] - m["reward_redeemed_cents"]
    if unredeemed > 0:
        add_ledger_entry(m["id"], "EXPIRY", -unredeemed, term_start, None)


def _revoke_all_cards(m):
    for c in db.household_cards.values():
        if c["membership_id"] == m["id"] and c["status"] == "ACTIVE":
            c["status"] = "REVOKED"
            db.touch(c)


def reconcile(m):
    """Recompute derived fields + apply clock-driven boundary transitions for reads."""
    process_term_boundary(m)
    recompute_household_card_count(m)
    recompute_fees_paid(m)


# --------------------------------------------------------------------------- #
# Calculations
# --------------------------------------------------------------------------- #
def block_round(value_total, num, denom):
    """floor(value_total * num / denom)."""
    if denom == 0:
        return 0
    return (value_total * num) // denom


def cancel_refund(m, plan):
    from helpers import parse_dt
    now = clock.get()
    term_start = parse_dt(m["term_start_utc"])
    elapsed_seconds = (now - term_start).total_seconds()
    elapsed_days = int(elapsed_seconds // 86400)
    remaining_days = max(0, TERM_DAYS - elapsed_days)
    base_fee = plan["annual_fee_cents"]
    gross_refund = block_round(base_fee, remaining_days, TERM_DAYS)
    net_refund = max(0, gross_refund - m["reward_redeemed_cents"])
    return net_refund
