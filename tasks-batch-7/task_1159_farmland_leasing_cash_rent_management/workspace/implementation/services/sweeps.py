"""Logical-clock sweep pipeline (PRD 2.5). Runs in a fixed order."""
from decimal import Decimal
from datetime import timedelta
from db import db, CLOCK, new_common, touch, to_iso, add_days, add_year, days_between
from services.common import round_half_up_cents
from services.core import (
    recompute_landlord_totals, recompute_offering_scores,
    generate_installments, escalate_base_rent,
)

OPEN_LEAD_DAYS = 30
GRACE_DAYS = 10
LATE_FEE_PCT = Decimal("0.05")
CURE_DAYS = 30
NON_COMPLIANCE_PENALTY = 15
SUSPENSION_THRESHOLD = 50
SCORE_FLOOR = 0
SCORE_CAP = 100
WAIVER_AUTHORITY_CENTS = 100000


# ---------------------------------------------------------------------------
# Tenant suspension cascade (shared by manual suspend and compliance cascade)
# ---------------------------------------------------------------------------

def cascade_tenant_suspension(tenant):
    """Withdraw tenant's live bids; recompute affected offerings."""
    affected_offerings = set()
    for bid in db.bids.values():
        if bid["tenant_id"] == tenant["id"] and bid["status"] in ("SUBMITTED", "SHORTLISTED"):
            bid["status"] = "WITHDRAWN"
            touch(bid)
            affected_offerings.add(bid["offering_id"])
    for oid in affected_offerings:
        recompute_offering_scores(oid)


def suspend_tenant(tenant):
    tenant["status"] = "SUSPENDED"
    touch(tenant)
    cascade_tenant_suspension(tenant)


# ---------------------------------------------------------------------------
# Compliance NON_COMPLIANT cascade
# ---------------------------------------------------------------------------

def apply_noncompliant(record):
    record["status"] = "NON_COMPLIANT"
    record["noncompliant_at"] = CLOCK.get()
    touch(record)
    lease = db.leases.get(record["lease_id"])
    if lease is None:
        return
    tenant = db.tenants.get(lease["tenant_id"])
    if tenant is None:
        return
    tenant["compliance_score"] = max(SCORE_FLOOR, tenant["compliance_score"] - NON_COMPLIANCE_PENALTY)
    touch(tenant)
    if tenant["compliance_score"] < SUSPENSION_THRESHOLD and tenant["status"] == "APPROVED":
        suspend_tenant(tenant)


# ---------------------------------------------------------------------------
# Lease termination cascade (notice EFFECTIVE side effect)
# ---------------------------------------------------------------------------

AGREED_VALUE_RESIDUAL = [Decimal("1.0"), Decimal("0.75"), Decimal("0.55"),
                         Decimal("0.35"), Decimal("0.15"), Decimal("0.0")]
DAYS_PER_YEAR = 365


def compute_reimbursement(project, effective_date):
    elapsed_days = days_between(project["completed_at"], effective_date)
    if elapsed_days < 0:
        elapsed_days = 0
    if project["reimbursement_method"] == "STRAIGHT_LINE":
        total_days = project["amortization_years"] * DAYS_PER_YEAR
        if elapsed_days >= total_days:
            return 0
        remaining = total_days - elapsed_days
        return round_half_up_cents(Decimal(project["tenant_paid_cents"]) * Decimal(remaining) / Decimal(total_days))
    else:  # AGREED_VALUE
        bucket = elapsed_days // DAYS_PER_YEAR
        if bucket >= 5:
            pct = AGREED_VALUE_RESIDUAL[5]
        else:
            pct = AGREED_VALUE_RESIDUAL[bucket]
        return round_half_up_cents(Decimal(project["tenant_paid_cents"]) * pct)


def terminate_lease(lease, effective_date):
    """Lease TERMINATION_PENDING -> TERMINATED with full cascade."""
    lease["status"] = "TERMINATED"
    touch(lease)
    field = db.fields.get(lease["field_id"])
    if field is not None:
        # Field returns to AVAILABLE when no other ACTIVE/TERMINATION_PENDING lease
        still_leased = any(
            l["field_id"] == field["id"] and l["id"] != lease["id"]
            and l["status"] in ("ACTIVE", "TERMINATION_PENDING")
            for l in db.leases.values()
        )
        if not still_leased:
            field["status"] = "AVAILABLE"
            touch(field)
    # Improvements reimbursement
    for proj in db.improvements.values():
        if (proj.get("lease_id") == lease["id"] and proj["status"] == "COMPLETED"
                and proj["reimbursement_status"] == "NONE"):
            proj["reimbursement_due_cents"] = compute_reimbursement(proj, effective_date)
            proj["reimbursement_status"] = "DUE"
            touch(proj)
    # Absentee landlord auto-report (window: [final term start, effective_date])
    landlord = db.landlords.get(lease["landlord_id"])
    if landlord is not None and landlord.get("absentee"):
        # final term start = term_start_date advanced (term_index - 1) years
        term_start = lease["term_start_date"]
        for _ in range(lease["term_index"] - 1):
            term_start = add_year(term_start)
        create_report(landlord["id"], "TERMINATION", term_start, effective_date)
    recompute_landlord_totals(lease["landlord_id"])


# ---------------------------------------------------------------------------
# Owner report aggregation (calc owner_report_aggregation) — shared by
# POST /reports and the auto-created TERMINATION report.
# ---------------------------------------------------------------------------

def compute_report_aggregates(landlord_id, period_start, period_end):
    lease_ids = {l["id"] for l in db.leases.values() if l["landlord_id"] == landlord_id}
    rent_collected = 0
    for inst in db.installments.values():
        if inst["lease_id"] in lease_ids and inst.get("last_payment_at") is not None:
            if period_start <= inst["last_payment_at"] <= period_end:
                rent_collected += inst.get("paid_cents", 0)
    expenses_approved = 0
    for exp in db.expenses.values():
        if (exp["lease_id"] in lease_ids and exp["status"] == "APPROVED"
                and exp.get("approved_at") is not None
                and period_start <= exp["approved_at"] <= period_end):
            expenses_approved += exp["landlord_share_cents"]
    noncompliant_count = 0
    for rec in db.compliance_records.values():
        if (rec["lease_id"] in lease_ids and rec.get("noncompliant_at") is not None
                and period_start <= rec["noncompliant_at"] <= period_end):
            noncompliant_count += 1
    return rent_collected, expenses_approved, noncompliant_count


def create_report(landlord_id, report_type, period_start, period_end):
    rent_collected, expenses_approved, noncompliant_count = compute_report_aggregates(
        landlord_id, period_start, period_end)
    rec = new_common()
    rec.update({
        "landlord_id": landlord_id,
        "report_type": report_type,
        "period_start": period_start,
        "period_end": period_end,
        "rent_collected_cents": rent_collected,
        "expenses_approved_cents": expenses_approved,
        "noncompliant_count": noncompliant_count,
        "sent_at": None,
        "ack_due_date": None,
        "acknowledged_at": None,
        "escalation_required": False,
        "status": "DRAFT",
    })
    db.reports[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# The sweep pipeline (order pinned by PRD 2.5)
# ---------------------------------------------------------------------------

def run_sweeps():
    """Run all due sweeps. Returns number of sweeps applied (transitions fired)."""
    clock = CLOCK.get()
    sweeps = 0

    # 1. Installments SCHEDULED -> OPEN -> LATE
    #    Iterate until fixpoint so an installment created long past can flip
    #    SCHEDULED->OPEN and then OPEN->LATE in the same clock set.
    changed = True
    while changed:
        changed = False
        for inst in sorted(db.installments.values(),
                           key=lambda i: (i["due_date"], i["created_at"])):
            if inst["status"] == "SCHEDULED" and clock >= add_days(inst["due_date"], -OPEN_LEAD_DAYS):
                inst["status"] = "OPEN"
                touch(inst)
                sweeps += 1
                changed = True
            if inst["status"] == "OPEN" and clock > add_days(inst["due_date"], GRACE_DAYS):
                if inst["paid_cents"] < inst["amount_cents"] + inst.get("late_fee_cents", 0):
                    inst["status"] = "LATE"
                    inst["late_fee_cents"] = round_half_up_cents(
                        Decimal(inst["amount_cents"]) * LATE_FEE_PCT)
                    touch(inst)
                    sweeps += 1
                    changed = True

    # Landlord totals after installment sweeps
    for landlord_id in list(db.landlords.keys()):
        recompute_landlord_totals(landlord_id)

    # 2. Compliance cure-deadline cascade
    for rec in list(db.compliance_records.values()):
        if rec["status"] in ("PENDING", "EVIDENCE_SUBMITTED", "REJECTED"):
            if clock > rec["cure_deadline"]:
                apply_noncompliant(rec)
                sweeps += 1

    # 3. Lease auto-renewal
    for lease in list(db.leases.values()):
        if lease["status"] != "ACTIVE":
            continue
        has_served_notice = any(
            n["lease_id"] == lease["id"] and n["status"] == "SERVED"
            for n in db.notices.values())
        if has_served_notice:
            continue
        if clock > lease["current_notice_deadline"]:
            lease["term_index"] += 1
            lease["term_end_date"] = add_year(lease["term_end_date"])
            lease["current_notice_deadline"] = add_days(
                lease["term_end_date"], -lease["notice_lead_days"])
            escalate_base_rent(lease)
            touch(lease)  # increments Lease.version
            generate_installments(lease)
            sweeps += 1

    # 4. Termination notices SERVED -> EFFECTIVE
    for notice in list(db.notices.values()):
        if notice["status"] == "SERVED" and clock >= notice["effective_date"]:
            notice["status"] = "EFFECTIVE"
            touch(notice)
            lease = db.leases.get(notice["lease_id"])
            if lease is not None and lease["status"] == "TERMINATION_PENDING":
                terminate_lease(lease, notice["effective_date"])
            sweeps += 1

    # 5. Owner-report escalation flags
    for report in db.reports.values():
        landlord = db.landlords.get(report["landlord_id"])
        if (landlord is not None and landlord.get("absentee")
                and report["status"] == "SENT"
                and report.get("ack_due_date") is not None
                and clock > report["ack_due_date"]):
            if not report.get("escalation_required"):
                report["escalation_required"] = True
                from db import now_iso
                report["updated_at"] = now_iso()
                sweeps += 1

    return sweeps
