"""Account domain: ledger reconciliation, commission, SOL, cadence, serialization.

The Account carries two parallel state dimensions (work_status, contact_status),
several computed ledger fields, and the cadence window count. Computed fields
that depend on the clock (time_barred, attempts_in_window_count, validation_deadline)
are derived on read.
"""
from clock import clock, parse_iso8601, format_iso8601, add_years, add_days
from db import db
from money import round_half_up


# ---------------------------------------------------------------------------
# SOL / re-aging guardrail (calculations.sol_status)
# ---------------------------------------------------------------------------
def compute_time_barred(account):
    basis = account.get("sol_anchor_basis", "CHARGE_OFF")
    charge_off = parse_iso8601(account["charge_off_date"])
    if basis == "CHARGE_OFF":
        anchor = charge_off
    else:  # LAST_PAYMENT
        lpd = account.get("last_payment_date")
        anchor = parse_iso8601(lpd) if lpd else charge_off
    expiry = add_years(anchor, account["sol_years"])
    # boundary: clock at or after expiry -> barred.
    return clock.now >= expiry


# ---------------------------------------------------------------------------
# Ledger reconciliation (calculations.account_balance)
# ---------------------------------------------------------------------------
def posted_payments_for_account(account_id):
    return [p for p in db.payments.values()
            if p["account_id"] == account_id and p["status"] == "POSTED"]


def recompute_ledger(account):
    """Recompute amount_collected_cents and balance_cents from POSTED payments
    and accumulated forgiveness. amount_settled_forgiven_cents is maintained
    incrementally at settlement fulfillment, so it is read here as stored."""
    posted = posted_payments_for_account(account["id"])
    collected = sum(p["amount_cents"] for p in posted)
    account["amount_collected_cents"] = collected
    forgiven = account.get("amount_settled_forgiven_cents", 0)
    balance = account["original_principal_cents"] - collected - forgiven
    account["balance_cents"] = max(0, balance)


# ---------------------------------------------------------------------------
# Commission (calculations.commission_earned) — dual variant
# ---------------------------------------------------------------------------
def recompute_commission(account):
    creditor = db.creditors.get(account["creditor_id"])
    if creditor is None:
        account["commission_earned_cents"] = 0
        return
    rate_bps = creditor["commission_rate_bps"]
    basis = creditor.get("commission_basis", "GROSS_OF_FEES")
    posted = posted_payments_for_account(account["id"])
    if basis == "GROSS_OF_FEES":
        # round each posted payment's commission to whole cents, then sum.
        total = 0
        for p in posted:
            total += round_half_up(p["amount_cents"] * rate_bps, 10000)
        account["commission_earned_cents"] = total
    else:  # NET_OF_FEES
        collected = sum(p["amount_cents"] for p in posted)
        net_base = max(0, collected - creditor.get("expense_recovery_cents", 0))
        account["commission_earned_cents"] = round_half_up(net_base * rate_bps, 10000)


# ---------------------------------------------------------------------------
# last_payment_date: most recent POSTED payment; never written backward.
# ---------------------------------------------------------------------------
def recompute_last_payment_date(account):
    posted = posted_payments_for_account(account["id"])
    if not posted:
        account["last_payment_date"] = None
        return
    latest = max(parse_iso8601(p["posted_at"]) for p in posted)
    account["last_payment_date"] = format_iso8601(latest)


def recompute_last_conversation_at(account):
    convos = [a for a in db.communication_attempts.values()
              if a["account_id"] == account["id"] and a["outcome"] == "CONVERSATION"]
    if not convos:
        account["last_conversation_at"] = None
        return
    latest = max(parse_iso8601(a["attempted_at"]) for a in convos)
    account["last_conversation_at"] = format_iso8601(latest)


# ---------------------------------------------------------------------------
# Cadence window count (calculations.cadence_window_count) — derived on read.
# trailing 7-day half-open window (clock - 7d, clock].
# ---------------------------------------------------------------------------
def cadence_window_count(account_id, at=None, exclude_id=None):
    now = at if at is not None else clock.now
    window_start = add_days(now, -7)
    count = 0
    for a in db.communication_attempts.values():
        if a["account_id"] != account_id:
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if not a.get("counts_toward_cadence", False):
            continue
        if a["outcome"] not in ("LOGGED", "CONVERSATION"):
            continue
        att = parse_iso8601(a["attempted_at"])
        if att > window_start and att <= now:
            count += 1
    return count


# ---------------------------------------------------------------------------
# validation_deadline (computed) = validation_notice_sent_at + 30 days
# ---------------------------------------------------------------------------
def validation_deadline_dt(account):
    sent = account.get("validation_notice_sent_at")
    if not sent:
        return None
    return add_days(parse_iso8601(sent), 30)


# ---------------------------------------------------------------------------
# Serialization — present the account with all computed/derived fields.
# ---------------------------------------------------------------------------
def serialize_account(account):
    deadline = validation_deadline_dt(account)
    return {
        "id": account["id"],
        "created_at": account["created_at"],
        "updated_at": account["updated_at"],
        "version": account["version"],
        "creditor_id": account["creditor_id"],
        "consumer_id": account["consumer_id"],
        "original_principal_cents": account["original_principal_cents"],
        "balance_cents": account["balance_cents"],
        "amount_collected_cents": account.get("amount_collected_cents", 0),
        "amount_settled_forgiven_cents": account.get("amount_settled_forgiven_cents", 0),
        "charge_off_date": account["charge_off_date"],
        "last_payment_date": account.get("last_payment_date"),
        "sol_years": account["sol_years"],
        "sol_anchor_basis": account.get("sol_anchor_basis", "CHARGE_OFF"),
        "placement_date": account["placement_date"],
        "validation_notice_sent_at": account.get("validation_notice_sent_at"),
        "validation_deadline": format_iso8601(deadline) if deadline else None,
        "work_status": account["work_status"],
        "contact_status": account["contact_status"],
        "attempts_in_window_count": cadence_window_count(account["id"]),
        "last_conversation_at": account.get("last_conversation_at"),
        "commission_earned_cents": account.get("commission_earned_cents", 0),
        "time_barred": compute_time_barred(account),
    }
