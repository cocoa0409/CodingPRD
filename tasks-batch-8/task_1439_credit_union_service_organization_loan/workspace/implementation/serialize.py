"""Entity serializers. Derived (source: computed) fields are evaluated at
read time from the live store, so cross-entity aggregates are always exact."""
import db

OPEN_CERT_STATUSES = {"PENDING_DILIGENCE", "COMMITTED", "ACTIVE", "EXCEPTION"}


def _common(e):
    return {
        "id": e["id"],
        "created_at": db.iso(e["created_at"]),
        "updated_at": db.iso(e["updated_at"]),
        "version": e["version"],
    }


def _dt(v):
    return None if v is None else db.iso(v)


# --- derived aggregates -----------------------------------------------------

def cu_total_committed(cu_id):
    return sum(
        c["committed_amount_cents"]
        for c in db.certificates.values()
        if c["buyer_id"] == cu_id and c["status"] in OPEN_CERT_STATUSES
    )


def cuso_total_approved(cuso_id):
    return sum(
        i["amount_cents"]
        for i in db.investments.values()
        if i["cuso_id"] == cuso_id and i["status"] == "APPROVED"
    )


def cuso_open_critical(cuso_id):
    exam_ids = [e["id"] for e in db.exams.values() if e["cuso_id"] == cuso_id]
    return sum(
        1
        for f in db.findings.values()
        if f["exam_id"] in exam_ids
        and f["severity"] == "CRITICAL"
        and f["status"] in ("OPEN", "VERIFYING", "REOPENED")
    )


def offering_committed(offering_id):
    return sum(
        c["committed_amount_cents"]
        for c in db.certificates.values()
        if c["offering_id"] == offering_id and c["status"] in OPEN_CERT_STATUSES
    )


# --- serializers ------------------------------------------------------------

def credit_union(e):
    d = _common(e)
    d.update({
        "charter_number": e["charter_number"],
        "legal_name": e["legal_name"],
        "cu_type": e["cu_type"],
        "total_assets_cents": e["total_assets_cents"],
        "net_worth_cents": e["net_worth_cents"],
        "concentration_cap_pct": e["concentration_cap_pct"],
        "status": e["status"],
        "net_worth_ratio": (e["net_worth_cents"] / e["total_assets_cents"])
        if e["total_assets_cents"] else 0,
        "total_committed_principal_cents": cu_total_committed(e["id"]),
    })
    return d


def cuso(e):
    d = _common(e)
    d.update({
        "legal_name": e["legal_name"],
        "service_line": e["service_line"],
        "status": e["status"],
        "total_approved_investment_cents": cuso_total_approved(e["id"]),
        "open_critical_finding_count": cuso_open_critical(e["id"]),
    })
    return d


def investment(e):
    d = _common(e)
    d.update({
        "credit_union_id": e["credit_union_id"],
        "cuso_id": e["cuso_id"],
        "amount_cents": e["amount_cents"],
        "approval_basis": e["approval_basis"],
        "status": e["status"],
        "post_approval_aggregate_cents": e["post_approval_aggregate_cents"],
        "decided_at": _dt(e["decided_at"]),
    })
    return d


def agreement(e):
    d = _common(e)
    d.update({
        "cuso_id": e["cuso_id"],
        "originator_id": e["originator_id"],
        "servicing_fee_bps": e["servicing_fee_bps"],
        "remittance_due_day": e["remittance_due_day"],
        "grace_period_days": e["grace_period_days"],
        "cure_period_days": e["cure_period_days"],
        "day_count_convention": e["day_count_convention"],
        "late_remittance_threshold": e["late_remittance_threshold"],
        "late_remittance_count": e["late_remittance_count"],
        "status": e["status"],
    })
    return d


def offering(e):
    committed = offering_committed(e["id"])
    d = _common(e)
    d.update({
        "servicing_agreement_id": e["servicing_agreement_id"],
        "pool_name": e["pool_name"],
        "pool_principal_cents": e["pool_principal_cents"],
        "min_share_pct": e["min_share_pct"],
        "yield_rate_bps": e["yield_rate_bps"],
        "loss_basis": e["loss_basis"],
        "open_at": _dt(e["open_at"]),
        "close_at": _dt(e["close_at"]),
        "status": e["status"],
        "committed_principal_cents": committed,
        "remaining_principal_cents": e["pool_principal_cents"] - committed,
    })
    return d


def certificate(e):
    off = db.offerings.get(e["offering_id"])
    pool = off["pool_principal_cents"] if off else 0
    d = _common(e)
    d.update({
        "offering_id": e["offering_id"],
        "buyer_id": e["buyer_id"],
        "committed_amount_cents": e["committed_amount_cents"],
        "share_pct": (e["committed_amount_cents"] / pool) if pool else 0,
        "status": e["status"],
        "funded_amount_cents": e["funded_amount_cents"],
        "outstanding_principal_cents": e["outstanding_principal_cents"],
        "cumulative_interest_cents": e["cumulative_interest_cents"],
        "cumulative_loss_cents": e["cumulative_loss_cents"],
        "diligence_decision_at": _dt(e["diligence_decision_at"]),
        "funded_at": _dt(e["funded_at"]),
    })
    return d


def doc_exception(e):
    d = _common(e)
    d.update({
        "certificate_id": e["certificate_id"],
        "exception_type": e["exception_type"],
        "description": e["description"],
        "detected_at": _dt(e["detected_at"]),
        "cure_deadline": _dt(e["cure_deadline"]),
        "status": e["status"],
        "cure_notes": e["cure_notes"],
        "cure_attempt_count": e["cure_attempt_count"],
    })
    return d


def remittance(e):
    d = _common(e)
    d.update({
        "certificate_id": e["certificate_id"],
        "period_start": _dt(e["period_start"]),
        "period_end": _dt(e["period_end"]),
        "collections_cents": e["collections_cents"],
        "due_at": _dt(e["due_at"]),
        "interest_portion_cents": e["interest_portion_cents"],
        "servicing_fee_cents": e["servicing_fee_cents"],
        "principal_portion_cents": e["principal_portion_cents"],
        "penalty_cents": e["penalty_cents"],
        "status": e["status"],
        "paid_at": _dt(e["paid_at"]),
    })
    return d


def report(e):
    d = _common(e)
    d.update({
        "servicing_agreement_id": e["servicing_agreement_id"],
        "period_start": _dt(e["period_start"]),
        "period_end": _dt(e["period_end"]),
        "weighting_basis": e["weighting_basis"],
        "status": e["status"],
        "total_outstanding_principal_cents": e["total_outstanding_principal_cents"],
        "active_certificate_count": e["active_certificate_count"],
        "weighted_avg_yield_bps": e["weighted_avg_yield_bps"],
        "delinquent_remittance_count": e["delinquent_remittance_count"],
    })
    return d


def exam(e):
    d = _common(e)
    d.update({
        "cuso_id": e["cuso_id"],
        "start_date": _dt(e["start_date"]),
        "end_date": _dt(e["end_date"]),
        "status": e["status"],
        "finalized_at": _dt(e["finalized_at"]),
    })
    return d


def finding(e):
    d = _common(e)
    d.update({
        "exam_id": e["exam_id"],
        "severity": e["severity"],
        "description": e["description"],
        "remediation_due_date": _dt(e["remediation_due_date"]),
        "recorded_by_user_id": e["recorded_by_user_id"],
        "status": e["status"],
        "remediation_notes": e["remediation_notes"],
    })
    return d


def loss_event(e):
    d = _common(e)
    d.update({
        "offering_id": e["offering_id"],
        "loss_amount_cents": e["loss_amount_cents"],
        "defaulted_at": _dt(e["defaulted_at"]),
        "loss_basis_used": e["loss_basis_used"],
        "allocations": e["allocations"],
        "status": e["status"],
    })
    return d


def repurchase_case(e):
    d = _common(e)
    d.update({
        "certificate_id": e["certificate_id"],
        "trigger_reason": e["trigger_reason"],
        "documentation_exception_id": e["documentation_exception_id"],
        "repurchase_price_cents": e["repurchase_price_cents"],
        "status": e["status"],
    })
    return d
