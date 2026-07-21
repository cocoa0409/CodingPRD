"""Business calculations, denormalized-stat recompute, and cascades."""
from decimal import Decimal, ROUND_HALF_UP

import store


def round_half_up(numerator, denominator):
    """round_half_up(numerator/denominator) to an integer."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


# ---------------------------------------------------------------------------
# payment_on_time_status
# ---------------------------------------------------------------------------
def compute_on_time(paid_date, due_date):
    if paid_date is None:
        return False
    boundary = (due_date.date())
    from datetime import timedelta
    return paid_date.date() <= due_date.date() + timedelta(days=store.GRACE_DAYS)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def tenant_payments(tenant_id):
    """All RentPayments (any status) on the tenant's leases."""
    lease_ids = {l["id"] for l in store.leases.values() if l["tenant_id"] == tenant_id}
    return [p for p in store.rent_payments.values() if p["lease_id"] in lease_ids]


def tenant_effective_items(tenant_id):
    return [r for r in store.reported_items.values()
            if r["tenant_id"] == tenant_id and r["status"] in ("REPORTED", "DISPUTED")]


def tenant_enrollment(tenant_id):
    """Best enrollment for a tenant: prefer ACTIVE, then PENDING_PAYMENT, else latest non-cancelled, else latest."""
    ens = [e for e in store.enrollments.values() if e["tenant_id"] == tenant_id]
    if not ens:
        return None
    ens.sort(key=lambda e: e["_seq"])
    for e in ens:
        if e["status"] == "ACTIVE":
            return e
    for e in ens:
        if e["status"] == "PENDING_PAYMENT":
            return e
    non_cancelled = [e for e in ens if e["status"] != "CANCELLED"]
    if non_cancelled:
        return non_cancelled[-1]
    return ens[-1]


def month_covered(lease_id, period_month):
    """True if a non-retracted ReportedItem already covers (lease_id, period_month)."""
    for r in store.reported_items.values():
        if r["lease_id"] == lease_id and r["period_month"] == period_month and r["status"] != "RETRACTED":
            return True
    return False


# ---------------------------------------------------------------------------
# tenant_on_time_rate (both variants) + denormalized-stat recompute
# ---------------------------------------------------------------------------
def compute_rates(tenant_id):
    pays = tenant_payments(tenant_id)
    if not pays:
        as_paid = None
    else:
        on_time = sum(1 for p in pays if p["on_time"])
        as_paid = round_half_up(100 * on_time, len(pays))

    items = tenant_effective_items(tenant_id)
    if not items:
        as_reported = None
    else:
        on_time = sum(1 for r in items if r["on_time"])
        as_reported = round_half_up(100 * on_time, len(items))

    return {
        "as_paid": as_paid,
        "as_reported": as_reported,
        "total_payments": len(pays),
        "effective_reported_items": len(items),
    }


def recompute_tenant(tenant_id):
    tenant = store.tenants.get(tenant_id)
    if tenant is None:
        return
    r = compute_rates(tenant_id)
    tenant["reported_on_time_rate_pct"] = r["as_reported"]
    tenant["effective_reported_items"] = r["effective_reported_items"]
    store.touch(tenant)


# ---------------------------------------------------------------------------
# back_report_fee
# ---------------------------------------------------------------------------
def back_report_fee(n_requested, included_months):
    billable = max(0, n_requested - included_months)
    fee = min(billable * store.BACK_REPORT_PER_MONTH_CENTS, store.BACK_REPORT_FEE_CAP_CENTS)
    return billable, fee


# ---------------------------------------------------------------------------
# cancellation_settlement (prorated_refund variant)
# ---------------------------------------------------------------------------
def cancellation_settlement(enrollment, cancelled_at):
    start = enrollment["current_period_start"]
    end = enrollment["current_period_end"]
    days_in_period = (end - start).days
    used_raw = (cancelled_at - start).days
    days_used = max(0, min(used_raw, days_in_period))

    sub_invoice = subscription_invoice(enrollment["id"])
    paid_this_period = enrollment["monthly_fee_cents"] if (sub_invoice and sub_invoice["status"] == "PAID") else 0

    if days_in_period <= 0:
        earned = 0
    else:
        earned = round_half_up(enrollment["monthly_fee_cents"] * days_used, days_in_period)
    refund = max(0, paid_this_period - earned)
    return refund, earned


def subscription_invoice(enrollment_id):
    for inv in store.invoices.values():
        if inv["enrollment_id"] == enrollment_id and inv["kind"] == "SUBSCRIPTION":
            return inv
    return None


# ---------------------------------------------------------------------------
# latest_score_by_bureau
# ---------------------------------------------------------------------------
def latest_scores(tenant_id):
    result = {}
    for bureau in store.BUREAUS:
        candidates = [s for s in store.score_snapshots.values()
                      if s["tenant_id"] == tenant_id and s["bureau"] == bureau]
        if not candidates:
            result[bureau] = None
        else:
            best = max(candidates, key=lambda s: (s["as_of_month"], s["created_at"]))
            result[bureau] = best["score"]
    return result


# ---------------------------------------------------------------------------
# Cascade: Enrollment ACTIVE -> CANCELLED terminates verified leases,
# which retract still-effective tradelines, then recompute tenant stats.
# ---------------------------------------------------------------------------
def cascade_cancel_terminations(tenant_id):
    for lease in list(store.leases.values()):
        if lease["tenant_id"] == tenant_id and lease["verification_status"] == "VERIFIED":
            lease["verification_status"] = "TERMINATED"
            store.touch(lease)
            for item in list(store.reported_items.values()):
                if item["lease_id"] == lease["id"] and item["status"] in ("REPORTED", "DISPUTED"):
                    item["status"] = "RETRACTED"
                    item["bureau_statuses"] = {b: "DELETED" for b in store.BUREAUS}
                    store.touch(item)
    recompute_tenant(tenant_id)
