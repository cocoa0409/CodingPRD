"""The six named cascades of PRD 2.8 plus the shared funding links."""
from db import db
from middleware import touch
from services.calc import DELAYED_PAYOUT_LAG_DAYS, NORMAL_PAYOUT_LAG_DAYS
from services.ledger import append_entry
from services.metrics import (
    batches_cascade_order,
    merchant_alerts,
    recompute_open_alert_count,
    recompute_pending_payout,
    reserve_account_of,
    terminations_of,
)
from util import date_plus


# --------------------------------------------------------------------------
# shared links
# --------------------------------------------------------------------------
def _freeze_batches(merchant):
    for batch in batches_cascade_order(merchant["id"], ("SCHEDULED", "DELAYED")):
        batch["payout_state"] = "HELD"
        batch["scheduled_payout_date"] = None
        touch(batch)


def hold_funding(merchant, reason_code):
    """funding_state -> HELD and freeze every unpaid batch."""
    merchant["funding_state"] = "HELD"
    merchant["funding_hold_reason_code"] = reason_code
    merchant["delayed_payout_days"] = 0
    touch(merchant)
    _freeze_batches(merchant)
    recompute_pending_payout(merchant)


def release_funding(merchant, clock_date):
    """PRD 3.8: the resulting posture follows the merchant's risk posture."""
    if merchant["account_state"] == "ACTIVE":
        merchant["funding_state"] = "NORMAL"
        merchant["delayed_payout_days"] = 0
        merchant["funding_hold_reason_code"] = None
        touch(merchant)
        for batch in batches_cascade_order(merchant["id"], ("HELD",)):
            batch["payout_state"] = "SCHEDULED"
            batch["scheduled_payout_date"] = date_plus(
                batch["period_end_date"], NORMAL_PAYOUT_LAG_DAYS)
            touch(batch)
    else:
        merchant["funding_state"] = "DELAYED"
        merchant["delayed_payout_days"] = DELAYED_PAYOUT_LAG_DAYS
        merchant["funding_hold_reason_code"] = None
        touch(merchant)
        for batch in batches_cascade_order(merchant["id"], ("HELD",)):
            batch["payout_state"] = "DELAYED"
            batch["scheduled_payout_date"] = date_plus(clock_date, DELAYED_PAYOUT_LAG_DAYS)
            touch(batch)
    recompute_pending_payout(merchant)


# --------------------------------------------------------------------------
# CB-BREACH (PRD 3.7)
# --------------------------------------------------------------------------
def cb_breach(merchant, as_of_date):
    if merchant["account_state"] != "ACTIVE":
        return
    merchant["account_state"] = "RESTRICTED"
    merchant["remediation_required"] = True
    touch(merchant)
    if merchant["funding_state"] == "NORMAL":
        merchant["funding_state"] = "DELAYED"
        merchant["delayed_payout_days"] = DELAYED_PAYOUT_LAG_DAYS
        touch(merchant)
        for batch in batches_cascade_order(merchant["id"], ("SCHEDULED",)):
            batch["payout_state"] = "DELAYED"
            batch["scheduled_payout_date"] = date_plus(as_of_date, DELAYED_PAYOUT_LAG_DAYS)
            touch(batch)
        recompute_pending_payout(merchant)


# --------------------------------------------------------------------------
# ALERT-ESCALATION (PRD 3.8)
# --------------------------------------------------------------------------
def alert_escalation(merchant, alert):
    if alert["alert_type"] not in ("CARD_TESTING", "LAUNDERING_PATTERN"):
        return
    if merchant["account_state"] == "TERMINATED":
        return
    if merchant["funding_state"] not in ("NORMAL", "DELAYED"):
        return
    reason = "CARD_TESTING" if alert["alert_type"] == "CARD_TESTING" else "SUSPECTED_LAUNDERING"
    hold_funding(merchant, reason)


# --------------------------------------------------------------------------
# REMEDIATION-PASS (PRD 3.11)
# --------------------------------------------------------------------------
def remediation_pass(merchant):
    if merchant["account_state"] != "RESTRICTED":
        return
    blocking = [t for t in terminations_of(merchant["id"])
                if t["state"] in ("PROPOSED", "APPROVED")]
    if blocking:
        return
    merchant["account_state"] = "ACTIVE"
    merchant["remediation_required"] = False
    touch(merchant)
    if merchant["funding_state"] != "DELAYED":
        return
    merchant["funding_state"] = "NORMAL"
    merchant["delayed_payout_days"] = 0
    touch(merchant)
    for batch in batches_cascade_order(merchant["id"], ("DELAYED",)):
        batch["payout_state"] = "SCHEDULED"
        batch["scheduled_payout_date"] = date_plus(
            batch["period_end_date"], NORMAL_PAYOUT_LAG_DAYS)
        touch(batch)
    for alert in merchant_alerts(merchant["id"]):
        if alert["alert_type"] == "CHARGEBACK_THRESHOLD" and alert["state"] == "ESCALATED":
            alert["state"] = "CLOSED"
            touch(alert)
    recompute_open_alert_count(merchant)
    recompute_pending_payout(merchant)


# --------------------------------------------------------------------------
# REMEDIATION-FAIL (PRD 3.11)
# --------------------------------------------------------------------------
def remediation_fail(program, merchant, month_chargeback_count):
    if month_chargeback_count < 100:
        return
    program["state"] = "NETWORK_ESCALATED"
    program["network_program_tier"] = (
        "EXCESSIVE" if (program["last_observed_ratio_bps"] or 0) >= 180 else "STANDARD")
    touch(program)
    hold_funding(merchant, "EXCESSIVE_CHARGEBACKS")


# --------------------------------------------------------------------------
# TERMINATION-EXEC (PRD 3.12)
# --------------------------------------------------------------------------
def termination_exec(merchant, clock_iso):
    merchant["account_state"] = "TERMINATED"
    merchant["terminated_at"] = clock_iso
    touch(merchant)
    merchant["funding_state"] = "HELD"
    merchant["funding_hold_reason_code"] = "TERMINATION_PENDING"
    merchant["delayed_payout_days"] = 0
    touch(merchant)
    _freeze_batches(merchant)
    account = reserve_account_of(merchant["id"])
    if account is not None and account["state"] in ("ACCRUING", "CAP_REACHED", "RELEASING"):
        account["state"] = "CLOSED"
        touch(account)
    for alert in merchant_alerts(merchant["id"]):
        if alert["state"] in ("OPEN", "UNDER_REVIEW", "ESCALATED"):
            alert["state"] = "CLOSED"
            touch(alert)
    recompute_open_alert_count(merchant)
    recompute_pending_payout(merchant)


# --------------------------------------------------------------------------
# APPEAL-GRANT (PRD 3.12)
# --------------------------------------------------------------------------
def appeal_grant(appeal, decision, merchant, clock_iso, clock_date, actor_user_id):
    decision["state"] = "REVERSED"
    decision["reversed_at"] = clock_iso
    touch(decision)

    merchant["account_state"] = "RESTRICTED"
    merchant["reinstated_at"] = clock_iso
    merchant["remediation_required"] = True
    merchant["terminated_at"] = None
    if appeal["reinstatement_reserve_pct_bps"] is not None:
        merchant["pinned_reserve_pct_bps"] = appeal["reinstatement_reserve_pct_bps"]
    touch(merchant)

    account = reserve_account_of(merchant["id"])
    if account is not None:
        account["reserve_pct_bps"] = merchant["pinned_reserve_pct_bps"]
        touch(account)

    if merchant["funding_state"] == "HELD":
        merchant["funding_state"] = "DELAYED"
        merchant["funding_hold_reason_code"] = None
        merchant["delayed_payout_days"] = DELAYED_PAYOUT_LAG_DAYS
        touch(merchant)
        for batch in batches_cascade_order(merchant["id"], ("HELD",)):
            batch["payout_state"] = "DELAYED"
            batch["scheduled_payout_date"] = date_plus(clock_date, DELAYED_PAYOUT_LAG_DAYS)
            touch(batch)
        if account is not None:
            _reopen_reserve_account(account, merchant, clock_date, actor_user_id)
        recompute_pending_payout(merchant)


def _reopen_reserve_account(account, merchant, clock_date, actor_user_id):
    if account["state"] == "CLOSED":
        account["state"] = "ACCRUING"
        touch(account)
    account["reserve_pct_bps"] = merchant["pinned_reserve_pct_bps"]
    touch(account)
    if account["held_balance_cents"] > 0:
        append_entry(
            account,
            entry_type="RELEASE",
            reason_code="REINSTATEMENT_RELEASE",
            amount_cents=account["held_balance_cents"],
            effective_date=clock_date,
            settlement_batch_id=None,
            recorded_by_user_id=actor_user_id,
        )
    merchant["reserve_balance_cents"] = account["held_balance_cents"]
    touch(merchant)


def clock_state():
    return db.clock_iso(), db.clock_date()
