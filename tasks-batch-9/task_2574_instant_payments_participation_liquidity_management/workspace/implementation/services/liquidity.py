"""The ledger identity, liquidity bands, alerts, posture and queue release."""

from db import bump, db, new_record, now, order_key
from timeutils import date_str, plus_minutes
from services import lookup
from services.constants import (
    CREDIT_ENTRY_TYPES,
    LIVE_ALERT_STATUSES,
    RESERVING_STATUSES,
)


# --- 2.8 the derived position ---------------------------------------------


def current_balance(account):
    total = account["opening_balance_cents"]
    for entry in db.ledger_entries.values():
        if entry["account_id"] == account["id"]:
            total += entry["amount_cents"]
    return total


def reserved(account):
    total = 0
    for row in db.credit_transfers.values():
        if row["originator_participant_id"] != account["participant_id"]:
            continue
        if row["direction"] != "OUTBOUND":
            continue
        if row["clearing_status"] in RESERVING_STATUSES:
            total += row["amount_cents"]
    return total


def available(account):
    return current_balance(account) - reserved(account)


# --- 2.9 bands and alerts --------------------------------------------------


def band_of(balance, account):
    if balance < account["floor_cents"]:
        return "BREACH"
    if balance <= account["critical_threshold_cents"]:
        return "RED"
    if balance <= account["warning_threshold_cents"]:
        return "AMBER"
    return "GREEN"


def _threshold_for_tier(account, tier):
    if tier == "AMBER":
        return account["warning_threshold_cents"]
    if tier == "RED":
        return account["critical_threshold_cents"]
    return account["floor_cents"]


def recompute_band(account, raised_by_user_id=None):
    """Recompute alert_tier and emit / retire alerts. Returns the new tier."""
    balance = current_balance(account)
    tier = band_of(balance, account)
    account["alert_tier"] = tier
    existing = lookup.alerts_of_account(account["id"])
    if tier != "GREEN":
        already = [
            a for a in existing
            if a["tier"] == tier and a["status"] in LIVE_ALERT_STATUSES
        ]
        if not already:
            alert = new_record()
            alert.update({
                "account_id": account["id"],
                "tier": tier,
                "threshold_cents": _threshold_for_tier(account, tier),
                "observed_balance_cents": balance,
                "status": "OPEN",
                "acknowledged_by_user_id": None,
                "remediation_plan": None,
                "escalated_at": None,
                "cleared_at": None,
                "_raised_by_user_id": raised_by_user_id,
            })
            db.liquidity_alerts[alert["id"]] = alert
    else:
        for alert in existing:
            if alert["status"] in LIVE_ALERT_STATUSES:
                alert["status"] = "CLEARED"
                alert["cleared_at"] = now()
                bump(alert)
    return tier


def post_ledger_entry(account, entry_type, magnitude_cents, related_transfer_id=None,
                      reference=None, raised_by_user_id=None):
    """Append one immutable, signed ledger entry and rebase the account."""
    signed = magnitude_cents if entry_type in CREDIT_ENTRY_TYPES else -magnitude_cents
    sequence_no = account["last_ledger_sequence_no"] + 1
    account["last_ledger_sequence_no"] = sequence_no
    entry = new_record(with_version=False)
    entry.update({
        "account_id": account["id"],
        "related_transfer_id": related_transfer_id,
        "entry_type": entry_type,
        "amount_cents": signed,
        "business_date": date_str(now()),
        "sequence_no": sequence_no,
        "reference": reference,
    })
    db.ledger_entries[entry["id"]] = entry
    entry["balance_after_cents"] = current_balance(account)
    bump(account)
    recompute_band(account, raised_by_user_id)
    return entry


# --- 2.9 the derived operational posture ----------------------------------


def covering_outages(participant_id):
    out = []
    for event in db.outage_events.values():
        if event["status"] != "DECLARED":
            continue
        if event["scope"] == "NETWORK_WIDE" or (
            event["scope"] == "PARTICIPANT" and event["participant_id"] == participant_id
        ):
            out.append(event)
    return sorted(out, key=order_key)


def derive_posture(participant):
    if covering_outages(participant["id"]):
        return "OFFLINE"
    if participant["enrollment_status"] in ("SUSPENDED", "WITHDRAWN"):
        return "SEND_FROZEN"
    account = lookup.account_of_participant(participant["id"])
    if account is None:
        return "NORMAL"
    if account["alert_tier"] in ("RED", "BREACH"):
        return "SEND_FROZEN"
    if account["alert_tier"] == "AMBER":
        return "THROTTLED"
    return "NORMAL"


def park_initiated(participant):
    """Step one of propagation: freeze parks INITIATED sends."""
    parked = 0
    for transfer in lookup.transfers_of_participant(participant["id"], ("INITIATED",)):
        transfer["clearing_status"] = "QUEUED_THROTTLED"
        transfer["queued_at"] = now()
        bump(transfer)
        parked += 1
    return parked


def release_waterfall(participant):
    """Step two of propagation: a strict-stop waterfall over the queue."""
    account = lookup.account_of_participant(participant["id"])
    if account is None:
        return 0
    running = current_balance(account) - reserved(account)
    floor = account["floor_cents"]
    candidates = lookup.transfers_of_participant(participant["id"], ("QUEUED_THROTTLED",))
    candidates.sort(key=lambda t: (0 if t.get("rfp_id") else 1, t["created_at"], t["_seq"]))
    released = 0
    for transfer in candidates:
        if running - transfer["amount_cents"] >= floor:
            transfer["clearing_status"] = "INITIATED"
            transfer["queued_at"] = None
            bump(transfer)
            running -= transfer["amount_cents"]
            released += 1
        else:
            break
    return released


def rederive_posture(participant, bump_participant=True):
    """Re-derive the posture and run the pinned two-step propagation.

    ``bump_participant`` is false when the calling request already bumps the
    participant's version for the lifecycle hop that triggered the
    re-derivation, so that one request never moves the version twice.
    """
    previous = participant["operational_posture"]
    new_posture = derive_posture(participant)
    if new_posture != previous:
        participant["operational_posture"] = new_posture
        if bump_participant:
            bump(participant)
    parked = 0
    if new_posture in ("SEND_FROZEN", "OFFLINE"):
        parked = park_initiated(participant)
    elif new_posture in ("NORMAL", "THROTTLED") and previous in ("SEND_FROZEN", "OFFLINE"):
        release_waterfall(participant)
    return parked


# --- 3.3 the twenty-four hour projection ----------------------------------


def projection(account):
    participant_id = account["participant_id"]
    horizon_start = now()
    horizon_end = plus_minutes(horizon_start, 1440)
    own_accounts = set(
        row["id"] for row in db.customer_accounts.values()
        if row["participant_id"] == participant_id
    )
    scheduled_outflow = 0
    expected_inflow = 0
    for rfp in db.request_for_payments.values():
        expiry = rfp["expiry_at"]
        if not (horizon_start <= expiry < horizon_end):
            continue
        if rfp["debtor_customer_account_id"] in own_accounts and rfp["status"] in ("DELIVERED", "ACCEPTED"):
            scheduled_outflow += rfp["amount_cents"]
        if rfp["requestor_participant_id"] == participant_id and rfp["status"] == "ACCEPTED":
            expected_inflow += rfp["amount_cents"]
    balance = current_balance(account)
    reserved_now = reserved(account)
    projected_balance = balance - scheduled_outflow + expected_inflow
    return {
        "current_balance_cents": balance,
        "reserved_cents": reserved_now,
        "available_cents": balance - reserved_now,
        "scheduled_outflow_cents": scheduled_outflow,
        "expected_inflow_cents": expected_inflow,
        "projected_balance_cents": projected_balance,
        "projected_available_cents": projected_balance - reserved_now,
        "projected_alert_tier": band_of(projected_balance, account),
        "horizon_end": horizon_end,
    }
