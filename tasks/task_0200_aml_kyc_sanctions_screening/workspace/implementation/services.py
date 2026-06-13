"""Cross-entity domain logic: audit trail, derived-field recomputation, and
cascades shared across multiple route modules (PRD §2.5, §2.10, §2.12)."""

import db


# ---------------------------------------------------------------------------
# Audit trail (PRD §2.10)
# ---------------------------------------------------------------------------
def audit(entity_type, entity_id, action, user_id, role):
    """Append an immutable AuditEvent (id + created_at only; §2.4)."""
    base = db.light_create_fields()
    event = {
        **base,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "actor_user_id": user_id,
        "actor_role": role,
    }
    db.audit_events[event["id"]] = event
    return event


# ---------------------------------------------------------------------------
# Customer derived gates (PRD §2.12, calc edd_gate)
# ---------------------------------------------------------------------------
def customer_open_hits(customer_id):
    return [
        h
        for h in db.screening_hits.values()
        if h["customer_id"] == customer_id and h["disposition"] in ("PENDING", "ESCALATED")
    ]


def has_confirmed_derogatory(customer_id):
    return any(
        h["customer_id"] == customer_id
        and h["disposition"] == "CONFIRMED"
        and h["is_derogatory"]
        for h in db.screening_hits.values()
    )


def recompute_customer_gates(customer):
    """Recompute open_hit_count and edd_required (calc edd_gate, §2.12).

    edd_required = (risk_rating==HIGH) OR (open_hit_count>0)
                   OR (exists CONFIRMED derogatory hit)
    """
    cid = customer["id"]
    open_count = len(customer_open_hits(cid))
    customer["open_hit_count"] = open_count
    customer["edd_required"] = bool(
        customer.get("risk_rating") == "HIGH"
        or open_count > 0
        or has_confirmed_derogatory(cid)
    )


# ---------------------------------------------------------------------------
# Account cascades driven by Customer lifecycle (PRD §3.1, §3.6)
# ---------------------------------------------------------------------------
def customer_accounts(customer_id):
    return [a for a in db.accounts.values() if a["customer_id"] == customer_id]


def cascade_block_freeze_accounts(customer):
    """REJECTED/OFFBOARDED: each account with monitoring_status != FROZEN ->
    kyc_status=KYC_BLOCKED, monitoring_status=FROZEN. Each touched (§2.5)."""
    for acc in customer_accounts(customer["id"]):
        if acc["monitoring_status"] != "FROZEN":
            acc["kyc_status"] = "KYC_BLOCKED"
            acc["monitoring_status"] = "FROZEN"
            db.touch(acc)


def cascade_approve_accounts(customer):
    """On APPROVED: accounts in PENDING_KYC -> KYC_OK (§3.1)."""
    for acc in customer_accounts(customer["id"]):
        if acc["kyc_status"] == "PENDING_KYC":
            acc["kyc_status"] = "KYC_OK"
            db.touch(acc)


def cascade_reopen_accounts(customer):
    """On APPROVED->EDD_REQUIRED (new confirmed derogatory): accounts in KYC_OK
    cascade back to PENDING_KYC for re-review (§3.5, §3.6)."""
    for acc in customer_accounts(customer["id"]):
        if acc["kyc_status"] == "KYC_OK":
            acc["kyc_status"] = "PENDING_KYC"
            db.touch(acc)


# ---------------------------------------------------------------------------
# Account monitoring revert (PRD §3.6, §3.8)
# ---------------------------------------------------------------------------
def maybe_revert_account_monitoring(account):
    """An account in UNDER_INVESTIGATION reverts to ACTIVE once no alert against
    it remains LINKED (§3.6)."""
    if account["monitoring_status"] != "UNDER_INVESTIGATION":
        return
    still_linked = any(
        al["account_id"] == account["id"] and al["status"] == "LINKED"
        for al in db.alerts.values()
    )
    if not still_linked:
        account["monitoring_status"] = "ACTIVE"
        db.touch(account)
