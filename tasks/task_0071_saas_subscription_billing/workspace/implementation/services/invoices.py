"""Invoice service: creation, totals, payment cascades, dunning."""
from clock import clock, iso, parse_iso

from db import store, new_id, now_iso
from errors import (
    raise_error,
    ERR_INVOICE_CYCLE_ALREADY_ISSUED,
    ERR_JURISDICTION_NOT_FOUND,
)
from services.calculations import (
    compute_addon_lines,
    compute_overage_lines,
    compute_tiered_lines,
    late_fee_accrual,
    tax_calculation,
)
from services.audit import emit_sync_event


DEFAULT_DUE_DAYS = 14  # invoice due window after issuance

# Grace day thresholds (in whole days past due_at)
GRACE_DAYS_TIER1 = 1
GRACE_DAYS_TIER2 = 31
GRACE_DAYS_TIER3 = 61

# Suspension-to-termination grace
TERMINATION_GRACE_DAYS = 30


def build_line_items_for_subscription(subscription, package):
    """Build the line_items array for the current subscription state.

    Returns: (line_items list, subtotal_cents)
    """
    pricing_model = package["pricing_model"]
    package_type = package["package_type"]

    # Step 1: base line
    if pricing_model == "POSTPAID":
        base_line_cents = 0
    else:
        base_line_cents = int(package.get("base_price_cents", 0))

    lines = []
    if base_line_cents > 0:
        lines.append({
            "kind": "BASE",
            "description": "Recurring base charge",
            "quantity": 1,
            "unit_price_cents": base_line_cents,
            "line_total_cents": base_line_cents,
        })

    # Step 2 + 3: tiered & overage
    quota_consumed = subscription.get("quota_consumed") or {}
    if package_type in ("TIERED", "HYBRID"):
        tiered_lines, residuals = compute_tiered_lines(quota_consumed, package)
        lines.extend(tiered_lines)
    else:
        residuals = {}

    if package_type in ("USAGE_BASED", "HYBRID"):
        overage_lines = compute_overage_lines(quota_consumed, package, residuals)
        lines.extend(overage_lines)

    # Step 4: addons
    addon_lines = compute_addon_lines(package, subscription.get("selected_addons") or [])
    lines.extend(addon_lines)

    subtotal = sum(int(l["line_total_cents"]) for l in lines)
    return lines, subtotal


def get_unapplied_credits_for_tenant(tenant_id):
    return [c for c in store.credit_notes.values()
            if c["tenant_id"] == tenant_id and c.get("applied_to_invoice_id") is None]


def recompute_invoice_totals(invoice, recompute_late_fee=True):
    """Update subtotal_cents, tax_cents, total_cents, amount_paid_cents,
    amount_due_cents, credit_applied_cents on the invoice.

    Per bill_total_calc evaluation order — does NOT mutate stored credit
    application records. discount_cents is clamped; tax is computed AFTER
    discount; credit_applied_cents is computed AFTER tax (sum of unapplied
    credits clamped to taxable_base+tax); late_fee added LAST.
    Returns the invoice (mutated).
    """
    tenant = store.tenants.get(invoice["tenant_id"])
    subscription = store.subscriptions.get(invoice["subscription_id"])
    package = store.package_versions.get(subscription["package_version_id"]) if subscription else None

    if package is not None:
        lines, subtotal = build_line_items_for_subscription(subscription, package)
    else:
        lines = invoice.get("line_items") or []
        subtotal = sum(int(l["line_total_cents"]) for l in lines)

    invoice["subtotal_cents"] = subtotal
    invoice["line_items"] = lines

    discount = int(invoice.get("discount_cents", 0) or 0)
    if discount < 0:
        discount = 0
    if discount > subtotal:
        discount = subtotal
    # Store clamped value back; the validation layer already checks discount
    # constraints separately when the patch arrives.
    invoice["discount_cents"] = discount

    taxable_base = subtotal - discount

    # Tax via Jurisdiction
    jurisdiction = store.jurisdiction_by_code(tenant["jurisdiction_code"]) if tenant else None
    if jurisdiction is None:
        tax = 0
    else:
        tax = tax_calculation(lines, discount, jurisdiction)
    invoice["tax_cents"] = tax

    # Credits: sum unapplied for tenant, clamped to taxable_base + tax
    # BUT credit_applied_cents is what's actually been applied to THIS invoice,
    # not unapplied credits floating in tenant. Per the formula:
    #   credit_applied_cents = clamp( sum(unapplied for tenant), 0, taxable_base + tax )
    # However the persistent CreditNote.applied_to_invoice_id tracks which invoice
    # consumed it. So credit_applied_cents on the invoice should reflect credits
    # already applied + still-unapplied (clamped).
    # Sum credits already applied to this invoice
    applied_to_this = sum(int(c.get("applied_cents", 0)) for c in store.credit_notes.values()
                          if c.get("applied_to_invoice_id") == invoice["id"])
    # Sum still-unapplied for tenant
    unapplied_sum = sum(int(c["amount_cents"]) for c in store.credit_notes.values()
                        if c["tenant_id"] == invoice["tenant_id"]
                        and c.get("applied_to_invoice_id") is None)

    # Total credit applicable to this invoice = applied + cap (within taxable_base+tax)
    cap = max(taxable_base + tax, 0)
    credit_applied = applied_to_this
    if credit_applied > cap:
        credit_applied = cap
    invoice["credit_applied_cents"] = credit_applied

    if recompute_late_fee:
        # late fee uses current amount_due as of *before* this recompute pass;
        # but per PRD, it's computed on amount_due_cents.
        prelim_total = taxable_base + tax - credit_applied
        if prelim_total < 0:
            prelim_total = 0
        paid = sum(int(p["amount_cents"]) for p in store.payments.values()
                   if p["invoice_id"] == invoice["id"])
        prelim_due = max(prelim_total - paid, 0)
        if invoice.get("due_at"):
            invoice["late_fee_cents"] = late_fee_accrual(prelim_due, invoice["due_at"], clock.now())
        else:
            invoice["late_fee_cents"] = 0

    late_fee = int(invoice.get("late_fee_cents", 0))
    total = taxable_base + tax - credit_applied + late_fee
    if total < 0:
        total = 0
    invoice["total_cents"] = total

    paid_sum = sum(int(p["amount_cents"]) for p in store.payments.values()
                   if p["invoice_id"] == invoice["id"])
    invoice["amount_paid_cents"] = paid_sum
    invoice["amount_due_cents"] = max(total - paid_sum, 0)
    return invoice


def issue_invoice_record(subscription, tenant, package, *,
                         line_items=None, subtotal_override=None,
                         status_after_issue="ISSUED",
                         pricing_model_override=None,
                         cycle_start_override=None,
                         cycle_end_override=None,
                         discount_cents=0,
                         emit_event=True):
    """Create and ISSUE an invoice in one shot (used by system-issued invoices).

    Enforces (subscription_id, cycle_start, pricing_model) uniqueness.
    Returns the persisted Invoice dict (status=ISSUED).
    """
    cycle_start = cycle_start_override or subscription["cycle_start"]
    cycle_end = cycle_end_override or subscription["cycle_end"]
    pricing_model = pricing_model_override or package["pricing_model"]

    # Uniqueness check
    for inv in store.invoices.values():
        if (inv["subscription_id"] == subscription["id"]
                and inv["cycle_start"] == cycle_start
                and inv["pricing_model"] == pricing_model
                and inv["invoice_status"] != "WRITTEN_OFF"):
            raise_error(ERR_INVOICE_CYCLE_ALREADY_ISSUED,
                        "An invoice for this subscription cycle and pricing model already exists")

    inv_id = new_id()
    created = now_iso()
    invoice = {
        "id": inv_id,
        "created_at": created,
        "updated_at": created,
        "version": 1,
        "tenant_id": tenant["id"],
        "subscription_id": subscription["id"],
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "invoice_status": "DRAFT",
        "currency": tenant["currency"],
        "subtotal_cents": 0,
        "discount_cents": int(discount_cents or 0),
        "credit_applied_cents": 0,
        "tax_cents": 0,
        "late_fee_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "amount_due_cents": 0,
        "due_at": None,
        "line_items": [],
        "pricing_model": pricing_model,
    }
    store.invoices[inv_id] = invoice

    if line_items is not None:
        invoice["line_items"] = line_items
        invoice["subtotal_cents"] = subtotal_override if subtotal_override is not None else \
            sum(int(l["line_total_cents"]) for l in line_items)
        # Tax/credits/total
        from datetime import timedelta
        # Compute tax & credits via bill_total_calc-style helper, then total
        tenant_ref = store.tenants.get(invoice["tenant_id"])
        jurisdiction = store.jurisdiction_by_code(tenant_ref["jurisdiction_code"])
        # Discount clamp
        discount = min(invoice["discount_cents"], invoice["subtotal_cents"])
        if discount < 0:
            discount = 0
        invoice["discount_cents"] = discount
        taxable_base = invoice["subtotal_cents"] - discount
        if jurisdiction is None:
            tax = 0
        else:
            tax = tax_calculation(line_items, discount, jurisdiction)
        invoice["tax_cents"] = tax
        # Apply unapplied credits
        unapplied = [c for c in store.credit_notes.values()
                     if c["tenant_id"] == tenant["id"]
                     and c.get("applied_to_invoice_id") is None]
        cap = max(taxable_base + tax, 0)
        credit_applied = 0
        # Greedily consume credits in created_at order
        unapplied_sorted = sorted(unapplied, key=lambda c: c["created_at"])
        for c in unapplied_sorted:
            if credit_applied >= cap:
                break
            take = min(int(c["amount_cents"]), cap - credit_applied)
            c["applied_to_invoice_id"] = inv_id
            c["applied_cents"] = take
            credit_applied += take
        invoice["credit_applied_cents"] = credit_applied
        # late_fee at issuance = 0
        invoice["late_fee_cents"] = 0
        total = taxable_base + tax - credit_applied
        if total < 0:
            total = 0
        invoice["total_cents"] = total
        invoice["amount_paid_cents"] = 0
        invoice["amount_due_cents"] = total
    else:
        # Use the standard rebuild from subscription state
        recompute_invoice_totals(invoice, recompute_late_fee=False)

    # Now issue it: set due_at, freeze (already frozen by line_items),
    # update status, version, updated_at, emit SyncEvent
    now = clock.now()
    from datetime import timedelta
    invoice["due_at"] = iso(now + timedelta(days=DEFAULT_DUE_DAYS))
    invoice["invoice_status"] = status_after_issue
    invoice["updated_at"] = now_iso()
    invoice["version"] = invoice["version"] + 1 if invoice["version"] >= 1 else 1
    # version starts at 1 per common-fields rule for new resources; we'll set 1 here
    invoice["version"] = 1

    if emit_event and status_after_issue == "ISSUED":
        emit_sync_event(tenant["id"], "ACCOUNTING", "INVOICE_ISSUED", dict(invoice))
    return invoice


def create_draft_invoice(subscription, tenant, package, *,
                        pricing_model_override=None,
                        cycle_start_override=None,
                        cycle_end_override=None,
                        discount_cents=0):
    """Create a DRAFT invoice (no issuance). Used by PATCH discount flow or
    when an operator wants to manually build totals before issuance."""
    cycle_start = cycle_start_override or subscription["cycle_start"]
    cycle_end = cycle_end_override or subscription["cycle_end"]
    pricing_model = pricing_model_override or package["pricing_model"]

    inv_id = new_id()
    created = now_iso()
    invoice = {
        "id": inv_id,
        "created_at": created,
        "updated_at": created,
        "version": 1,
        "tenant_id": tenant["id"],
        "subscription_id": subscription["id"],
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "invoice_status": "DRAFT",
        "currency": tenant["currency"],
        "subtotal_cents": 0,
        "discount_cents": int(discount_cents or 0),
        "credit_applied_cents": 0,
        "tax_cents": 0,
        "late_fee_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "amount_due_cents": 0,
        "due_at": None,
        "line_items": [],
        "pricing_model": pricing_model,
    }
    store.invoices[inv_id] = invoice
    recompute_invoice_totals(invoice, recompute_late_fee=False)
    return invoice


def get_invoice(invoice_id):
    return store.invoices.get(invoice_id)


def recompute_tenant_outstanding(tenant):
    """Recompute outstanding_balance_cents and active_subscription_id on tenant."""
    total = 0
    for inv in store.invoices.values():
        if inv["tenant_id"] != tenant["id"]:
            continue
        if inv["currency"] != tenant["currency"]:
            continue
        if inv["invoice_status"] in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
            total += int(inv.get("amount_due_cents", 0))
    tenant["outstanding_balance_cents"] = total
    # active_subscription_id
    active_id = None
    for sub in store.subscriptions.values():
        if sub["tenant_id"] != tenant["id"]:
            continue
        if sub["subscription_status"] in ("TRIAL", "ACTIVE", "PENDING_DOWNGRADE"):
            active_id = sub["id"]
            break
    tenant["active_subscription_id"] = active_id


def apply_payment_cascade(invoice, payment):
    """Apply a Payment's cascade per §3.9 and dunning interactions.

    Returns the now-updated invoice.
    """
    tenant = store.tenants[invoice["tenant_id"]]
    subscription = store.subscriptions.get(invoice["subscription_id"])

    # Step 1: recompute late_fee BEFORE zero-out check (per §3.10)
    prelim_total = (int(invoice.get("subtotal_cents", 0))
                    - int(invoice.get("discount_cents", 0))
                    + int(invoice.get("tax_cents", 0))
                    - int(invoice.get("credit_applied_cents", 0)))
    if prelim_total < 0:
        prelim_total = 0
    paid_sum = sum(int(p["amount_cents"]) for p in store.payments.values()
                   if p["invoice_id"] == invoice["id"])
    # Recompute late fee against the *new* outstanding (paid_sum already includes
    # the new payment because we persist Payment before this call).
    prelim_due = max(prelim_total - paid_sum, 0)
    if invoice.get("due_at"):
        invoice["late_fee_cents"] = late_fee_accrual(prelim_due, invoice["due_at"], clock.now())
    else:
        invoice["late_fee_cents"] = 0

    total = prelim_total + int(invoice["late_fee_cents"])
    if total < 0:
        total = 0
    invoice["total_cents"] = total
    invoice["amount_paid_cents"] = paid_sum
    invoice["amount_due_cents"] = max(total - paid_sum, 0)

    cleared_now = invoice["amount_due_cents"] == 0
    prior_status = invoice["invoice_status"]

    # Status transitions on the invoice
    if invoice["invoice_status"] in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
        if cleared_now:
            invoice["invoice_status"] = "PAID"
            invoice["late_fee_cents"] = 0
            # Recompute totals one more time so total reflects cleared late-fee
            total_cleared = prelim_total + 0
            invoice["total_cents"] = total_cleared
            invoice["amount_due_cents"] = max(total_cleared - paid_sum, 0)
        else:
            if invoice["invoice_status"] == "ISSUED" and paid_sum > 0:
                invoice["invoice_status"] = "PARTIALLY_PAID"
    invoice["updated_at"] = now_iso()
    invoice["version"] = int(invoice.get("version", 1)) + 1

    # Always emit PAYMENT_RECEIVED on PAYMENT_PAY target
    emit_sync_event(tenant["id"], "PAYMENT_PAY", "PAYMENT_RECEIVED", dict(payment))

    # Recompute outstanding balance now
    recompute_tenant_outstanding(tenant)

    # Cascade reactivation if outstanding -> 0
    if tenant["outstanding_balance_cents"] == 0:
        # Reset payment_status on subscription
        if subscription and subscription.get("payment_status") != "CURRENT":
            subscription["payment_status"] = "CURRENT"
            subscription["updated_at"] = now_iso()
            subscription["version"] = int(subscription.get("version", 1)) + 1
        # Reset restriction level
        if tenant.get("restriction_level") != "NONE":
            tenant["restriction_level"] = "NONE"
            tenant["updated_at"] = now_iso()
            tenant["version"] = int(tenant.get("version", 1)) + 1
        # Lift SUSPENDED -> ACTIVE
        if tenant["tenant_status"] == "SUSPENDED":
            before = {"tenant_status": "SUSPENDED"}
            tenant["tenant_status"] = "ACTIVE"
            tenant["updated_at"] = now_iso()
            tenant["version"] = int(tenant.get("version", 1)) + 1
            store.suspension_started.pop(tenant["id"], None)
            emit_sync_event(tenant["id"], "CRM", "TENANT_REACTIVATED", dict(tenant))
            from services.audit import write_audit
            write_audit(tenant["id"], "TENANT_STATUS_CHANGE", "Tenant",
                        tenant["id"], before,
                        {"tenant_status": "ACTIVE"})
    return invoice
