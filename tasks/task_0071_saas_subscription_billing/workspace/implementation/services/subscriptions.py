"""Subscription lifecycle service."""
from clock import clock, iso, parse_iso

from db import store, new_id, now_iso
from errors import (
    raise_error,
    ERR_SUBSCRIPTION_NOT_FOUND,
)
from services.audit import write_audit, emit_sync_event
from services.calculations import (
    add_billing_cycle,
    proration_amount,
    cycle_days,
)
from services.invoices import (
    create_draft_invoice,
    issue_invoice_record,
    recompute_invoice_totals,
    recompute_tenant_outstanding,
)
from services.packages import resolve_package_or_404


def get_subscription_for_tenant(tenant_id: str, sub_id: str):
    sub = store.subscriptions.get(sub_id)
    if sub is None or sub.get("tenant_id") != tenant_id:
        raise_error(ERR_SUBSCRIPTION_NOT_FOUND,
                    f"Subscription {sub_id} not found for tenant {tenant_id}")
    return sub


def create_subscription(tenant, package_code: str, selected_addons):
    """Create a new subscription in TRIAL state for an existing TRIAL tenant."""
    now = clock.now()
    pkg = resolve_package_or_404(package_code, now)
    # Currency match check happens at endpoint layer per priority order

    sub_id = new_id()
    created = now_iso()
    cycle_start = iso(now)
    cycle_end = iso(add_billing_cycle(now, pkg["billing_cycle"]))

    subscription = {
        "id": sub_id,
        "created_at": created,
        "updated_at": created,
        "version": 1,
        "tenant_id": tenant["id"],
        "package_code": package_code,
        "package_version_id": pkg["id"],
        "selected_addons": list(selected_addons or []),
        "subscription_status": "TRIAL",
        "payment_status": "CURRENT",
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "pending_change_package_version_id": None,
        "quota_consumed": {},
        "quota_carry_forward": {},
    }
    store.subscriptions[sub_id] = subscription
    write_audit(tenant["id"], "SUBSCRIPTION_CREATE", "Subscription", sub_id,
                {}, dict(subscription))
    recompute_tenant_outstanding(tenant)
    return subscription, pkg


def convert_trial(subscription, tenant):
    """Trial-to-paid conversion (subscription_status TRIAL -> ACTIVE)."""
    now = clock.now()
    pkg = store.package_versions[subscription["package_version_id"]]
    before = dict(subscription)
    subscription["subscription_status"] = "ACTIVE"
    subscription["cycle_start"] = iso(now)
    subscription["cycle_end"] = iso(add_billing_cycle(now, pkg["billing_cycle"]))
    subscription["updated_at"] = now_iso()
    subscription["version"] = int(subscription["version"]) + 1

    # Cascade tenant TRIAL -> ACTIVE
    tenant_before = dict(tenant)
    if tenant["tenant_status"] == "TRIAL":
        tenant["tenant_status"] = "ACTIVE"
        tenant["updated_at"] = now_iso()
        tenant["version"] = int(tenant["version"]) + 1
        write_audit(tenant["id"], "TENANT_STATUS_CHANGE", "Tenant",
                    tenant["id"],
                    {"tenant_status": tenant_before["tenant_status"]},
                    {"tenant_status": "ACTIVE"})

    # Issue PREPAID invoice if needed
    if pkg["pricing_model"] in ("PREPAID", "HYBRID"):
        # Build line items for base+addons (no usage yet)
        from services.invoices import build_line_items_for_subscription
        lines, subtotal = build_line_items_for_subscription(subscription, pkg)
        issue_invoice_record(subscription, tenant, pkg,
                             line_items=lines,
                             subtotal_override=subtotal,
                             pricing_model_override=pkg["pricing_model"])

    emit_sync_event(tenant["id"], "PAYMENT_PAY", "SUBSCRIPTION_CREATED",
                    dict(subscription))
    write_audit(tenant["id"], "SUBSCRIPTION_CREATE", "Subscription",
                subscription["id"], before, dict(subscription))
    recompute_tenant_outstanding(tenant)
    return subscription


def upgrade_subscription(subscription, tenant, target_pkg):
    """Apply an upgrade with prorated charge."""
    now = clock.now()
    current_pkg = store.package_versions[subscription["package_version_id"]]
    before = dict(subscription)

    prorated = proration_amount(
        int(current_pkg["base_price_cents"]),
        int(target_pkg["base_price_cents"]),
        subscription["cycle_start"],
        subscription["cycle_end"],
        now,
    )
    if prorated < 0:
        prorated = 0  # upgrade math should be positive but guard anyway

    # Replace package_version_id
    subscription["package_version_id"] = target_pkg["id"]
    subscription["package_code"] = target_pkg["package_code"]
    # Reset quota_consumed and quota_carry_forward
    subscription["quota_consumed"] = {}
    subscription["quota_carry_forward"] = {}
    subscription["updated_at"] = now_iso()
    subscription["version"] = int(subscription["version"]) + 1

    # Create SubscriptionChange
    sc_id = new_id()
    sc = {
        "id": sc_id,
        "created_at": now_iso(),
        "subscription_id": subscription["id"],
        "tenant_id": tenant["id"],
        "change_type": "UPGRADE",
        "from_package_version_id": current_pkg["id"],
        "to_package_version_id": target_pkg["id"],
        "effective_at": iso(now),
        "prorated_charge_cents": prorated,
    }
    store.subscription_changes[sc_id] = sc

    # Issue prorated Invoice — line_items reflect the prorated charge
    proration_line = [{
        "kind": "PRORATION",
        "description": "Prorated upgrade charge",
        "quantity": 1,
        "unit_price_cents": prorated,
        "line_total_cents": prorated,
    }] if prorated > 0 else []

    if proration_line:
        # Use a cycle_start that is guaranteed distinct from any existing
        # invoice for this (subscription, pricing_model) tuple. PRD §3.9
        # only requires uniqueness on (subscription_id, cycle_start,
        # pricing_model); the prorated upgrade invoice covers the partial
        # cycle from the upgrade moment, so we mint a unique cycle_start
        # by walking forward in 1ms increments until no collision.
        proration_cycle_start = _unique_cycle_start_for_proration(
            subscription["id"], target_pkg["pricing_model"], iso(now),
        )
        issue_invoice_record(subscription, tenant, target_pkg,
                             line_items=proration_line,
                             subtotal_override=prorated,
                             pricing_model_override=target_pkg["pricing_model"],
                             cycle_start_override=proration_cycle_start,
                             cycle_end_override=subscription["cycle_end"])

    emit_sync_event(tenant["id"], "ACCOUNTING", "SUBSCRIPTION_CHANGED",
                    dict(subscription))
    write_audit(tenant["id"], "SUBSCRIPTION_UPGRADE", "Subscription",
                subscription["id"], before, dict(subscription))
    recompute_tenant_outstanding(tenant)
    return subscription, sc


def _unique_cycle_start_for_proration(sub_id, pricing_model, candidate_iso):
    """Find a cycle_start string that doesn't collide with any existing
    invoice for (sub_id, pricing_model). Walks forward by 1ms increments.
    """
    from datetime import timedelta
    dt = parse_iso(candidate_iso)
    while True:
        candidate = iso(dt)
        collision = any(
            inv["subscription_id"] == sub_id
            and inv["cycle_start"] == candidate
            and inv["pricing_model"] == pricing_model
            and inv["invoice_status"] != "WRITTEN_OFF"
            for inv in store.invoices.values()
        )
        if not collision:
            return candidate
        dt = dt + timedelta(milliseconds=1)


def downgrade_end_of_cycle(subscription, tenant, target_pkg):
    """Schedule a downgrade at cycle_end."""
    before = dict(subscription)
    current_pkg_id = subscription["package_version_id"]
    subscription["pending_change_package_version_id"] = target_pkg["id"]
    subscription["subscription_status"] = "PENDING_DOWNGRADE"
    subscription["updated_at"] = now_iso()
    subscription["version"] = int(subscription["version"]) + 1

    sc_id = new_id()
    sc = {
        "id": sc_id,
        "created_at": now_iso(),
        "subscription_id": subscription["id"],
        "tenant_id": tenant["id"],
        "change_type": "DOWNGRADE_END_OF_CYCLE",
        "from_package_version_id": current_pkg_id,
        "to_package_version_id": target_pkg["id"],
        "effective_at": subscription["cycle_end"],
        "prorated_charge_cents": 0,
    }
    store.subscription_changes[sc_id] = sc

    write_audit(tenant["id"], "SUBSCRIPTION_DOWNGRADE", "Subscription",
                subscription["id"], before, dict(subscription))
    return subscription, sc


def downgrade_immediate_refund(subscription, tenant, target_pkg):
    """Apply an immediate-refund downgrade and issue a CreditNote."""
    now = clock.now()
    current_pkg = store.package_versions[subscription["package_version_id"]]
    before = dict(subscription)

    prorated = proration_amount(
        int(current_pkg["base_price_cents"]),
        int(target_pkg["base_price_cents"]),
        subscription["cycle_start"],
        subscription["cycle_end"],
        now,
    )
    # Expect negative (refund)
    if prorated > 0:
        prorated = -prorated

    subscription["package_version_id"] = target_pkg["id"]
    subscription["package_code"] = target_pkg["package_code"]
    subscription["quota_consumed"] = {}
    subscription["quota_carry_forward"] = {}
    subscription["updated_at"] = now_iso()
    subscription["version"] = int(subscription["version"]) + 1

    sc_id = new_id()
    sc = {
        "id": sc_id,
        "created_at": now_iso(),
        "subscription_id": subscription["id"],
        "tenant_id": tenant["id"],
        "change_type": "DOWNGRADE_IMMEDIATE_REFUND",
        "from_package_version_id": current_pkg["id"],
        "to_package_version_id": target_pkg["id"],
        "effective_at": iso(now),
        "prorated_charge_cents": prorated,
    }
    store.subscription_changes[sc_id] = sc

    refund_amount = abs(prorated)
    # Issue CreditNote auto-applied to most-recent ISSUED invoice for this subscription
    cn_id = new_id()
    cn = {
        "id": cn_id,
        "created_at": now_iso(),
        "tenant_id": tenant["id"],
        "origin": "REFUND_DOWNGRADE",
        "amount_cents": refund_amount,
        "applied_to_invoice_id": None,
        "applied_cents": 0,
    }
    store.credit_notes[cn_id] = cn

    target_invoice = None
    issued_invoices = [inv for inv in store.invoices.values()
                       if inv["subscription_id"] == subscription["id"]
                       and inv["invoice_status"] == "ISSUED"]
    if issued_invoices:
        issued_invoices.sort(key=lambda i: i["created_at"], reverse=True)
        target_invoice = issued_invoices[0]

    if target_invoice is not None:
        cn["applied_to_invoice_id"] = target_invoice["id"]
        # Recompute target_invoice totals — credit_applied_cents updates accordingly
        # Determine cap
        taxable_base = int(target_invoice.get("subtotal_cents", 0)) - int(target_invoice.get("discount_cents", 0))
        cap = max(taxable_base + int(target_invoice.get("tax_cents", 0)), 0)
        already_applied = sum(int(c.get("applied_cents", 0))
                              for c in store.credit_notes.values()
                              if c.get("applied_to_invoice_id") == target_invoice["id"]
                              and c["id"] != cn_id)
        remaining_cap = max(cap - already_applied, 0)
        take = min(refund_amount, remaining_cap)
        cn["applied_cents"] = take
        recompute_invoice_totals(target_invoice, recompute_late_fee=False)
        target_invoice["updated_at"] = now_iso()
        target_invoice["version"] = int(target_invoice.get("version", 1)) + 1

    emit_sync_event(tenant["id"], "ACCOUNTING", "SUBSCRIPTION_CHANGED",
                    dict(subscription))
    write_audit(tenant["id"], "SUBSCRIPTION_DOWNGRADE", "Subscription",
                subscription["id"], before, dict(subscription))
    recompute_tenant_outstanding(tenant)
    return subscription, sc, cn


def cancel_subscription(subscription, tenant):
    """Cancel a subscription. From TRIAL: no invoice. From ACTIVE/PENDING_DOWNGRADE:
    final POSTPAID invoice if pricing_model includes POSTPAID and current cycle has usage."""
    before = dict(subscription)
    prior_status = subscription["subscription_status"]
    pkg = store.package_versions.get(subscription["package_version_id"])

    subscription["subscription_status"] = "CANCELLED"
    subscription["updated_at"] = now_iso()
    subscription["version"] = int(subscription["version"]) + 1

    if prior_status != "TRIAL" and pkg is not None:
        if pkg["pricing_model"] in ("POSTPAID", "HYBRID"):
            quota_consumed = subscription.get("quota_consumed") or {}
            has_usage = any(int(v) > 0 for v in quota_consumed.values())
            if has_usage or pkg["pricing_model"] == "POSTPAID":
                # Issue final POSTPAID invoice. Note: pricing_model_override=POSTPAID
                from services.invoices import build_line_items_for_subscription
                # For HYBRID cancel-final, charge overage only (base is prepaid already)
                # We'll build with pricing_model_override=POSTPAID so base_line=0,
                # and the lines built will reflect tiered+overage on existing quota.
                pseudo_pkg = dict(pkg)
                pseudo_pkg["pricing_model"] = "POSTPAID"
                lines, subtotal = build_line_items_for_subscription(subscription, pseudo_pkg)
                if subtotal > 0:
                    try:
                        issue_invoice_record(subscription, tenant, pseudo_pkg,
                                             line_items=lines,
                                             subtotal_override=subtotal,
                                             pricing_model_override="POSTPAID")
                    except Exception:
                        pass

    emit_sync_event(tenant["id"], "CRM", "SUBSCRIPTION_CHANGED", dict(subscription))
    write_audit(tenant["id"], "SUBSCRIPTION_DOWNGRADE", "Subscription",
                subscription["id"], before, dict(subscription))
    recompute_tenant_outstanding(tenant)
    return subscription


def has_in_flight_change(subscription) -> bool:
    """A subscription has an in-flight change if a recent SubscriptionChange
    matches this subscription and predates the request by < some small window
    or if status is PENDING_DOWNGRADE. The PRD uses Subscription.version as the
    serialization token, so we treat 'in flight' as 'PENDING_DOWNGRADE' state
    (an unresolved change). Plus any SubscriptionChange created within the
    current request batch — but in a single-threaded in-memory model this is
    only relevant when subscription_status == PENDING_DOWNGRADE."""
    return subscription.get("subscription_status") == "PENDING_DOWNGRADE"
