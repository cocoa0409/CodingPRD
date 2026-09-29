"""The daily close: six phases in a fixed order (PRD Section 2.5)."""

from db import by_creation, clock_date, db, touch
from services import calc
from services.cascades import flag_invoice_delinquent


def run_daily_close():
    today = clock_date()

    # --- Phase 1: qualified appraisals that have aged past expiry -------
    for appraisal in by_creation(list(db.appraisals.values())):
        if appraisal["status"] != "QUALIFIED":
            continue
        if today <= appraisal["expires_on"]:
            continue
        was_controlling = appraisal["is_controlling"]
        appraisal["status"] = "EXPIRED"
        appraisal["is_controlling"] = False
        touch(appraisal)
        if was_controlling:
            lease = db.leases.get(appraisal["lease_id"])
            # An appraisal simply ageing out is not a compliance finding: the
            # lease status is deliberately left at FMV_CERTIFIED.
            if lease is not None and lease["status"] == "FMV_CERTIFIED":
                lease["fmv_certification_status"] = "STALE"
                # A lease whose certification status reads STALE is carried at
                # the rate card again: effective_base_rent_annual equals the
                # provisional figure and the three certified figures are null
                # (PRD Section 3.4).
                calc.apply_rent_variant(lease)
                touch(lease)

    # --- Phase 2: issued invoices past grace, plus the full cascade -----
    for invoice in by_creation(list(db.rent_invoices.values())):
        if invoice["status"] == "DELINQUENT":
            # days_past_due keeps growing on later closes; days_past_due_at_flag
            # and delinquency_tier_weight stay frozen (PRD Section 3.7).
            invoice["days_past_due"] = max(0, calc.live_days_past_due(invoice))
            continue
        if invoice["status"] != "ISSUED":
            continue
        if calc.live_days_past_due(invoice) > calc.RENT_GRACE_DAYS:
            flag_invoice_delinquent(invoice)

    # --- Phase 3: active leases past term end roll into holdover -------
    for lease in by_creation(list(db.leases.values())):
        if lease["status"] != "ACTIVE":
            continue
        if today <= lease["term_end"]:
            continue
        lease["status"] = "HOLDOVER"
        lease["holdover_premium_applied"] = True
        calc.apply_rent_variant(lease)
        touch(lease)

    # --- Phase 4: remediation deadlines that have passed ---------------
    for case in by_creation(list(db.compliance_cases.values())):
        if case["status"] != "REMEDIATION_PLANNED":
            continue
        if case["remediation_due_on"] is None or case["remediation_due_on"] >= today:
            continue
        case["status"] = "OPEN"
        case["reopen_count"] += 1
        if case["reopen_count"] >= 2:
            case["severity"] = "HIGH"
        touch(case)
        tenant = db.tenants.get(case["tenant_id"])
        if tenant is not None:
            tenant["compliance_watch_status"] = "WATCH"
            touch(tenant)

    # --- Phase 5: booked windows that have ended -----------------------
    for booking in by_creation(list(db.bookings.values())):
        if booking["status"] != "BOOKED":
            continue
        if booking["window_end"] <= db.clock:
            booking["status"] = "COMPLETED"
            touch(booking)

    # --- Phase 6: whole-estate tenant score and watch sweep ------------
    for tenant in by_creation(list(db.tenants.values())):
        calc.recompute_tenant_risk(tenant)
