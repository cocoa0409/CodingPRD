"""Cascading side effects and audit trail (PRD §2.8, §2.11, §3.2, §3.5).
"""

import pytest

from test_helpers import (
    OPERATOR_HEADERS,
    advance_clock,
    create_active_personnel,
    create_customer,
    create_service_item,
    drive_order_to,
    get_order,
    get_personnel,
    iso_in,
    make_customer_headers,
    run_recert_sweep,
    setup_basic_scenario,
    submit_new_order,
    validate_success,
)


# =============================================================================
# Recertification sweep cascade (PRD §3.2, §2.8)
# =============================================================================


def test_recert_sweep_expires_cert_and_recomputes_skill_tags(api):
    """PRD §3.2: "For each ACTIVE certification whose expires_at has been
    reached or passed (current_time >= expires_at), the certification moves
    to EXPIRED, the personnel's skill_tags is recomputed (remove this
    skill_tag if no other ACTIVE cert for it remains)."

    Claim: after advancing past expires_at and running the recert sweep, the
    cert is EXPIRED and personnel.skill_tags drops the corresponding tag.
    """
    p, cert = create_active_personnel(
        skill_tag="CLEANING", cert_expires_in_days=1
    )
    assert "CLEANING" in p["skill_tags"]
    # Advance past the cert expiry (1 day + 1 minute).
    advance_clock(24 * 3600 + 60)
    run_recert_sweep()
    refreshed = get_personnel(p["id"])
    assert "CLEANING" not in refreshed["skill_tags"]


def test_recert_sweep_suspends_personnel_when_skill_tags_empty(api):
    """PRD §3.2: "if skill_tags becomes empty while the personnel is still in
    ACTIVE — the same sweep continues the cascade by suspending the personnel
    and reverting any dispatched orders as above."

    Claim: after the only cert expires, the recert sweep transitions the
    personnel from ACTIVE to SUSPENDED.
    """
    p, _ = create_active_personnel(
        skill_tag="CLEANING", cert_expires_in_days=1
    )
    advance_clock(24 * 3600 + 60)
    run_recert_sweep()
    refreshed = get_personnel(p["id"])
    assert refreshed["status"] == "SUSPENDED"


def test_recert_sweep_reverts_dispatched_order(api):
    """PRD §2.8: "When the recertification sweep transitions a personnel from
    ACTIVE to SUSPENDED because health certification has lapsed or no ACTIVE
    SkillCertification remains, every Order currently assigned to that
    personnel in DISPATCHED state is reverted to PENDING_DISPATCH, its
    assigned_personnel_id is cleared, and an AuditLogEntry with action_type
    set to DISPATCH_EXPIRED is appended."

    Claim: when the personnel's only cert expires while an order is
    DISPATCHED, the recert sweep reverts the order to PENDING_DISPATCH with
    null assigned_personnel_id and writes a DISPATCH_EXPIRED audit row.
    """
    # Build customer + item + personnel whose cert expires in ~1 day.
    customer = create_customer()
    item = create_service_item(required_skill_tag="CLEANING")
    p, _ = create_active_personnel(
        skill_tag="CLEANING", cert_expires_in_days=1
    )
    # Submit + dispatch one order. dispatch_deadline_at far enough in the
    # future that it isn't the cause of revert.
    ctx = {
        "customer": customer,
        "service_item": item,
        "personnel": p,
        "certification": None,
    }
    order = drive_order_to(ctx, "DISPATCHED")
    # Advance past cert expiry (>24h).
    advance_clock(24 * 3600 + 60)
    run_recert_sweep()
    refreshed = get_order(order["id"])
    assert refreshed["status"] == "PENDING_DISPATCH"
    assert refreshed.get("assigned_personnel_id") is None
    # Audit row exists
    log_res = api.list_audit_logs(
        OPERATOR_HEADERS,
        params={
            "subject_type": "Order",
            "subject_id": order["id"],
            "action_type": "DISPATCH_EXPIRED",
            "limit": 50,
        },
    )
    rows = log_res.json()["data"]
    rows = rows if isinstance(rows, list) else rows.get("entries", [])
    assert any(r["action_type"] == "DISPATCH_EXPIRED" for r in rows)


# =============================================================================
# Audit trail (PRD §2.11, §3.5)
# =============================================================================


def test_dispatch_writes_dispatch_audit_row(api):
    """PRD §3.5: "an AuditLogEntry with action_type of DISPATCH is appended."

    Claim: dispatching an order writes one DISPATCH AuditLogEntry whose
    subject_type=Order and subject_id matches the order id.
    """
    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "DISPATCHED")
    res = api.list_audit_logs(
        OPERATOR_HEADERS,
        params={
            "subject_type": "Order",
            "subject_id": order["id"],
            "action_type": "DISPATCH",
            "limit": 50,
        },
    )
    rows = res.json()["data"]
    rows = rows if isinstance(rows, list) else rows.get("entries", [])
    assert any(
        r["action_type"] == "DISPATCH" and r["subject_id"] == order["id"]
        for r in rows
    ), f"No DISPATCH audit row found for order {order['id']}: {rows}"


def test_reject_writes_dispatch_expired_audit_row(api):
    """PRD §3.5: "the previous personnel is added to the order's in-memory
    exclusion set so the next dispatch will not pick them, and an
    AuditLogEntry with action_type of DISPATCH_EXPIRED is appended."

    Claim: rejecting a DISPATCHED order writes a DISPATCH_EXPIRED audit row.
    """
    from test_helpers import make_personnel_headers, reject_order

    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "DISPATCHED")
    reject_order(order)
    res = api.list_audit_logs(
        OPERATOR_HEADERS,
        params={
            "subject_type": "Order",
            "subject_id": order["id"],
            "action_type": "DISPATCH_EXPIRED",
            "limit": 50,
        },
    )
    rows = res.json()["data"]
    rows = rows if isinstance(rows, list) else rows.get("entries", [])
    assert any(r["action_type"] == "DISPATCH_EXPIRED" for r in rows)
