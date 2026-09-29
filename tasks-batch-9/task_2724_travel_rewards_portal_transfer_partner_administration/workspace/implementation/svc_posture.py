"""Fraud scoring, the derived account posture, and its asymmetric cascades (PRD 3.9)."""

from core import DB, add_days, clock_iso, ordered, parse_dt, touch
from svc_ledger import append_entry, refresh_account

SIGNAL_WEIGHTS = {
    "DEVICE_CHANGE": 30,
    "NEW_PAYEE": 25,
    "EMAIL_CHANGE": 20,
    "PASSWORD_RESET": 15,
    "GEO_ANOMALY": 10,
}

SIGNAL_MEMBERS = ("DEVICE_CHANGE", "EMAIL_CHANGE", "PASSWORD_RESET", "NEW_PAYEE", "GEO_ANOMALY")
CASE_TYPES = ("ACCOUNT_TAKEOVER", "POINTS_DRAIN", "REDEMPTION_ABUSE")

VELOCITY_STATUSES = ("SUBMITTED", "HELD", "QUEUED", "COMPLETED")


def instant_score(signals):
    total = sum(SIGNAL_WEIGHTS[s] for s in set(signals))
    return min(total, 100)


def velocity_term(account_id, case_created_at):
    anchor = parse_dt(case_created_at)
    floor_instant = add_days(anchor, -30)
    total = 0
    for transfer in DB["transfer_requests"].values():
        if transfer["account_id"] != account_id:
            continue
        if transfer["status"] not in VELOCITY_STATUSES:
            continue
        created = parse_dt(transfer["created_at"])
        if created > floor_instant and created <= anchor:
            total += transfer["points_out"]
    steps = (total // 50000) * 10
    return min(steps, 40)


def compute_review_score(case):
    base = case["instant_score"]
    velocity = velocity_term(case["account_id"], case["created_at"])
    credit = 0 if case["device_fingerprint_changed"] else 10
    score = base + velocity - credit
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return score


def risk_score(case):
    if case["status"] == "OPEN":
        return case["instant_score"]
    if case.get("review_score") is None:
        return case["instant_score"]
    return case["review_score"]


def sync_risk_score(case):
    case["risk_score"] = risk_score(case)
    return case


def account_cases(account_id):
    return ordered(
        "fraud_cases",
        [c for c in DB["fraud_cases"].values() if c["account_id"] == account_id],
    )


def derive_posture(account):
    """Four ordered tests; CLEARED cases never contribute."""
    cases = account_cases(account["id"])
    for case in cases:
        if case["status"] == "CONFIRMED":
            return "LOCKED"
    live = [c for c in cases if c["status"] in ("OPEN", "UNDER_REVIEW")]
    for case in live:
        if risk_score(case) >= 60:
            return "LOCKED"
    for case in live:
        if risk_score(case) >= 30:
            return "WATCH"
    if account["transfer_hold_count"] >= 2:
        return "WATCH"
    return "CLEAR"


# --------------------------------------------------------------------------
# cascades
# --------------------------------------------------------------------------
def _suspend(entitlement, reason):
    entitlement["status"] = "SUSPENDED"
    entitlement["suspension_reason"] = reason
    touch(entitlement)


def _reinstate(entitlement):
    entitlement["status"] = "ACTIVE"
    entitlement["suspension_reason"] = None
    touch(entitlement)


def _entitlements(account_id, statuses):
    rows = [
        e
        for e in DB["entitlements"].values()
        if e["account_id"] == account_id and e["status"] in statuses
    ]
    return ordered("entitlements", rows)


def reject_transfer_for_lock(account, transfer):
    transfer["status"] = "REJECTED"
    transfer["resolution_reason"] = "POSTURE_LOCKED"
    touch(transfer)
    append_entry(
        account,
        "TRANSFER_REVERSAL",
        transfer["points_out"],
        "TRANSFER_REQUEST",
        transfer["id"],
        "Transfer rejected by account posture lock",
    )


def _lock_cascade(account):
    in_flight = ordered(
        "transfer_requests",
        [
            t
            for t in DB["transfer_requests"].values()
            if t["account_id"] == account["id"]
            and t["status"] in ("SUBMITTED", "QUEUED", "HELD")
        ],
    )
    for transfer in in_flight:
        reject_transfer_for_lock(account, transfer)
    for entitlement in _entitlements(account["id"], ("ACTIVE",)):
        _suspend(entitlement, "POSTURE_LOCKED")


def _watch_from_clear_cascade(account):
    for entitlement in _entitlements(account["id"], ("ACTIVE",)):
        if entitlement["benefit_type"] == "LOUNGE_ACCESS":
            _suspend(entitlement, "POSTURE_WATCH")


def _recover_to_clear_cascade(account):
    for entitlement in _entitlements(account["id"], ("SUSPENDED",)):
        _reinstate(entitlement)


def _recover_to_watch_cascade(account):
    for entitlement in _entitlements(account["id"], ("SUSPENDED",)):
        if entitlement["benefit_type"] == "LOUNGE_ACCESS":
            entitlement["suspension_reason"] = "POSTURE_WATCH"
            touch(entitlement)
        else:
            _reinstate(entitlement)


def recompute_posture(account):
    """Recompute the derived posture and run whichever cascade the movement implies."""
    before = account["fraud_posture"]
    after = derive_posture(account)
    if after == before:
        return before
    account["fraud_posture"] = after
    touch(account)
    if after == "LOCKED":
        _lock_cascade(account)
    elif before == "CLEAR" and after == "WATCH":
        _watch_from_clear_cascade(account)
    elif after == "CLEAR":
        _recover_to_clear_cascade(account)
    elif before == "LOCKED" and after == "WATCH":
        _recover_to_watch_cascade(account)
    refresh_account(account)
    return after


def hold_transfer(account, transfer, hold_reason, held_by_user_id):
    """Shared by the analyst hold and the purchase-reversal cascade of PRD 3.4."""
    transfer["status"] = "HELD"
    transfer["hold_reason"] = hold_reason
    transfer["held_by_user_id"] = held_by_user_id
    transfer["scheduled_post_at"] = None
    touch(transfer)
    account["transfer_hold_count"] = account["transfer_hold_count"] + 1
    touch(account)
    recompute_posture(account)
    refresh_account(account)
    return transfer
