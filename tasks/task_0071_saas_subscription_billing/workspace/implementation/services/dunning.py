"""Dunning sweep and clock-advance side effects."""
from clock import clock, parse_iso, iso
from datetime import timedelta

from db import store, now_iso
from services.audit import emit_sync_event, write_audit
from services.calculations import (
    add_billing_cycle,
    late_fee_accrual,
)
from services.invoices import (
    recompute_invoice_totals,
    recompute_tenant_outstanding,
    issue_invoice_record,
    GRACE_DAYS_TIER1,
    GRACE_DAYS_TIER2,
    GRACE_DAYS_TIER3,
    TERMINATION_GRACE_DAYS,
)


def days_between(later_dt, earlier_dt) -> int:
    return (later_dt - earlier_dt).days


def run_dunning_sweep():
    """Advance payment_status tiers, cascade restriction/suspension."""
    now = clock.now()
    scanned = 0
    transitioned = 0

    # 1) Process each tenant in deterministic order
    tenant_ids = sorted(store.tenants.keys(), key=lambda t: store.tenants[t]["created_at"])
    for tid in tenant_ids:
        tenant = store.tenants[tid]
        if tenant["tenant_status"] in ("TERMINATED",):
            continue

        # Iterate invoices for this tenant in created_at order
        tenant_invoices = [inv for inv in store.invoices.values()
                           if inv["tenant_id"] == tid]
        tenant_invoices.sort(key=lambda i: i["created_at"])

        # First, evaluate active invoices for tier advancement.
        # We'll move the subscription payment_status to the highest applicable tier
        # based on the worst (most-overdue) invoice with amount_due_cents>0.
        worst_tier = None  # "DUE", "OVERDUE_TIER1", "OVERDUE_TIER2", "OVERDUE_TIER3"
        worst_days_past = -1

        for inv in tenant_invoices:
            scanned += 1
            if inv["invoice_status"] not in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
                continue
            if inv.get("due_at") is None:
                continue
            due = parse_iso(inv["due_at"])
            if int(inv.get("amount_due_cents", 0)) <= 0:
                continue
            dpast = days_between(now, due)
            if dpast > worst_days_past:
                worst_days_past = dpast

        # Determine target tier
        target_tier = None
        if worst_days_past < 0:
            # Not past due yet on any invoice
            target_tier = None
        elif worst_days_past < GRACE_DAYS_TIER1:
            target_tier = "DUE"
        elif worst_days_past < GRACE_DAYS_TIER2:
            target_tier = "OVERDUE_TIER1"
        elif worst_days_past < GRACE_DAYS_TIER3:
            target_tier = "OVERDUE_TIER2"
        else:
            target_tier = "OVERDUE_TIER3"

        # Apply per-invoice late_fee recompute and possibly invoice status change
        for inv in tenant_invoices:
            if inv["invoice_status"] in ("ISSUED", "PARTIALLY_PAID", "OVERDUE") and inv.get("due_at"):
                due = parse_iso(inv["due_at"])
                dp = days_between(now, due)
                if int(inv.get("amount_due_cents", 0)) > 0:
                    new_fee = late_fee_accrual(int(inv["amount_due_cents"]), inv["due_at"], now)
                    if new_fee != int(inv.get("late_fee_cents", 0)):
                        inv["late_fee_cents"] = new_fee
                        prelim_total = (int(inv.get("subtotal_cents", 0))
                                        - int(inv.get("discount_cents", 0))
                                        + int(inv.get("tax_cents", 0))
                                        - int(inv.get("credit_applied_cents", 0))
                                        + new_fee)
                        if prelim_total < 0:
                            prelim_total = 0
                        inv["total_cents"] = prelim_total
                        inv["amount_due_cents"] = max(prelim_total - int(inv.get("amount_paid_cents", 0)), 0)
                        inv["updated_at"] = now_iso()
                        inv["version"] = int(inv.get("version", 1)) + 1
                    # Invoice status -> OVERDUE if past GRACE_DAYS_TIER1
                    if dp >= GRACE_DAYS_TIER1 and inv["invoice_status"] != "OVERDUE":
                        inv["invoice_status"] = "OVERDUE"
                        inv["updated_at"] = now_iso()
                        inv["version"] = int(inv.get("version", 1)) + 1

        # Find the active subscription for this tenant (TRIAL/ACTIVE/PENDING_DOWNGRADE)
        active_sub = None
        for sub in store.subscriptions.values():
            if sub["tenant_id"] != tid:
                continue
            if sub["subscription_status"] in ("ACTIVE", "PENDING_DOWNGRADE", "TRIAL"):
                active_sub = sub
                break

        # Apply target_tier to subscription.payment_status
        if active_sub is not None and target_tier is not None:
            prior_status = active_sub.get("payment_status", "CURRENT")
            tier_order = ["CURRENT", "DUE", "OVERDUE_TIER1", "OVERDUE_TIER2", "OVERDUE_TIER3"]
            try:
                if tier_order.index(target_tier) > tier_order.index(prior_status):
                    active_sub["payment_status"] = target_tier
                    active_sub["updated_at"] = now_iso()
                    active_sub["version"] = int(active_sub.get("version", 1)) + 1
                    transitioned += 1
            except ValueError:
                active_sub["payment_status"] = target_tier
                active_sub["updated_at"] = now_iso()
                active_sub["version"] = int(active_sub.get("version", 1)) + 1
                transitioned += 1

        # Apply cascades on tenant restriction_level / tenant_status
        if active_sub is not None:
            payment_status = active_sub.get("payment_status", "CURRENT")
            if tenant["tenant_status"] == "ACTIVE":
                # restriction_level cascade
                desired_level = "NONE"
                if payment_status == "OVERDUE_TIER1":
                    desired_level = "READ_ONLY"
                elif payment_status == "OVERDUE_TIER2":
                    desired_level = "FEATURE_RESTRICTED"
                elif payment_status == "OVERDUE_TIER3":
                    desired_level = "NONE"  # suspended supersedes
                if tenant["restriction_level"] != desired_level:
                    tenant["restriction_level"] = desired_level
                    tenant["updated_at"] = now_iso()
                    tenant["version"] = int(tenant.get("version", 1)) + 1
                if payment_status == "OVERDUE_TIER3" and tenant["tenant_status"] == "ACTIVE":
                    # ACTIVE -> SUSPENDED
                    before = {"tenant_status": "ACTIVE"}
                    tenant["tenant_status"] = "SUSPENDED"
                    tenant["restriction_level"] = "NONE"
                    tenant["updated_at"] = now_iso()
                    tenant["version"] = int(tenant.get("version", 1)) + 1
                    store.suspension_started[tid] = iso(now)
                    emit_sync_event(tid, "CRM", "TENANT_SUSPENDED", dict(tenant))
                    write_audit(tid, "TENANT_STATUS_CHANGE", "Tenant", tid,
                                before, {"tenant_status": "SUSPENDED"})

        # 2) SUSPENDED -> TERMINATED after grace
        if tenant["tenant_status"] == "SUSPENDED":
            suspended_at_iso = store.suspension_started.get(tid)
            if suspended_at_iso is not None:
                suspended_at = parse_iso(suspended_at_iso)
                if (now - suspended_at).days > TERMINATION_GRACE_DAYS:
                    before = {"tenant_status": "SUSPENDED"}
                    tenant["tenant_status"] = "TERMINATED"
                    tenant["updated_at"] = now_iso()
                    tenant["version"] = int(tenant.get("version", 1)) + 1
                    # Cancel subscription
                    if active_sub is not None and active_sub["subscription_status"] != "CANCELLED":
                        active_sub["subscription_status"] = "CANCELLED"
                        active_sub["updated_at"] = now_iso()
                        active_sub["version"] = int(active_sub.get("version", 1)) + 1
                    # Write off OVERDUE invoices
                    for inv in store.invoices.values():
                        if inv["tenant_id"] == tid and inv["invoice_status"] == "OVERDUE":
                            inv["invoice_status"] = "WRITTEN_OFF"
                            inv["updated_at"] = now_iso()
                            inv["version"] = int(inv.get("version", 1)) + 1
                    emit_sync_event(tid, "ACCOUNTING", "SUBSCRIPTION_CHANGED", dict(tenant))
                    write_audit(tid, "TENANT_STATUS_CHANGE", "Tenant", tid,
                                before, {"tenant_status": "TERMINATED"})
                    store.suspension_started.pop(tid, None)

        recompute_tenant_outstanding(tenant)

    return {"scanned": scanned, "transitioned": transitioned}


def process_clock_side_effects():
    """Run after every /_clock/advance call.

    1) TRIAL -> TERMINATED if now > trial_expires_at and no Subscription has gone ACTIVE.
    2) PENDING_DOWNGRADE -> ACTIVE cycle_rollover if now >= cycle_end.
    """
    now = clock.now()
    # Tenant trial expiry
    for tenant in list(store.tenants.values()):
        if tenant["tenant_status"] != "TRIAL":
            continue
        exp_iso = tenant.get("trial_expires_at")
        if not exp_iso:
            continue
        try:
            exp = parse_iso(exp_iso)
        except Exception:
            continue
        if now <= exp:
            continue
        # Check if any subscription has been ACTIVE
        had_active = False
        for sub in store.subscriptions.values():
            if sub["tenant_id"] != tenant["id"]:
                continue
            if sub["subscription_status"] in ("ACTIVE", "PENDING_DOWNGRADE"):
                had_active = True
                break
        if had_active:
            continue
        # TRIAL -> TERMINATED
        before = {"tenant_status": "TRIAL"}
        tenant["tenant_status"] = "TERMINATED"
        tenant["updated_at"] = now_iso()
        tenant["version"] = int(tenant.get("version", 1)) + 1
        # Cancel pending subscriptions
        for sub in store.subscriptions.values():
            if sub["tenant_id"] != tenant["id"]:
                continue
            if sub["subscription_status"] in ("PENDING", "TRIAL"):
                sub["subscription_status"] = "CANCELLED"
                sub["updated_at"] = now_iso()
                sub["version"] = int(sub.get("version", 1)) + 1
        write_audit(tenant["id"], "TENANT_STATUS_CHANGE", "Tenant", tenant["id"],
                    before, {"tenant_status": "TERMINATED"})

    # PENDING_DOWNGRADE -> ACTIVE cycle_rollover
    for sub in list(store.subscriptions.values()):
        if sub["subscription_status"] != "PENDING_DOWNGRADE":
            continue
        if not sub.get("cycle_end"):
            continue
        ce = parse_iso(sub["cycle_end"])
        if now < ce:
            continue
        # Roll over
        old_pkg = store.package_versions.get(sub["package_version_id"])
        new_pkg = store.package_versions.get(sub.get("pending_change_package_version_id"))
        if new_pkg is None:
            continue
        old_consumed = dict(sub.get("quota_consumed") or {})
        sub["package_version_id"] = new_pkg["id"]
        sub["package_code"] = new_pkg["package_code"]
        sub["pending_change_package_version_id"] = None
        # cycle_start = old cycle_end, cycle_end = + new package's billing cycle
        sub["cycle_start"] = sub["cycle_end"]
        sub["cycle_end"] = iso(add_billing_cycle(parse_iso(sub["cycle_start"]), new_pkg["billing_cycle"]))
        sub["subscription_status"] = "ACTIVE"
        # Quota carry-forward rule
        carry = {}
        if new_pkg["billing_cycle"] == "ANNUAL" and new_pkg["pricing_model"] in ("PREPAID", "HYBRID"):
            old_inc = int((old_pkg or {}).get("included_quotas", {}).get("seats", 0))
            old_used = int(old_consumed.get("seats", 0))
            carry_val = max(old_inc - old_used, 0)
            if carry_val > 0:
                carry["seats"] = carry_val
        sub["quota_carry_forward"] = carry
        sub["quota_consumed"] = {}
        sub["updated_at"] = now_iso()
        sub["version"] = int(sub.get("version", 1)) + 1

        # Issue next-cycle Invoice for PREPAID/HYBRID
        if new_pkg["pricing_model"] in ("PREPAID", "HYBRID"):
            tenant = store.tenants.get(sub["tenant_id"])
            from services.invoices import build_line_items_for_subscription
            lines, subtotal = build_line_items_for_subscription(sub, new_pkg)
            if subtotal > 0:
                try:
                    issue_invoice_record(sub, tenant, new_pkg,
                                         line_items=lines,
                                         subtotal_override=subtotal,
                                         pricing_model_override=new_pkg["pricing_model"])
                except Exception:
                    pass
