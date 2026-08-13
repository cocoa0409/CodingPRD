"""Entity -> JSON serializers. Field names and sets follow SCAFFOLD section 1.1.

Decimal-typed computed numbers are emitted as JSON numbers (float);
money stays integer cents. DataSharingElection is append-only: it carries
id + created_at only (no updated_at, no version).
"""
import db


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def period_out(p):
    d = _common(p)
    d.update({
        "aco_tax_id": p["aco_tax_id"],
        "aco_name": p["aco_name"],
        "performance_start_date": p["performance_start_date"],
        "performance_end_date": p["performance_end_date"],
        "track": p["track"],
        "status": p["status"],
    })
    return d


def participant_out(p):
    d = _common(p)
    d.update({
        "agreement_period_id": p["agreement_period_id"],
        "tin": p["tin"],
        "legal_name": p["legal_name"],
        "share_weight_bp": p["share_weight_bp"],
    })
    return d


def beneficiary_out(b):
    d = _common(b)
    d.update({
        "medicare_id": b["medicare_id"],
        "birth_year": b["birth_year"],
        "dual_eligible": b["dual_eligible"],
        "disabled": b["disabled"],
        "esrd": b["esrd"],
    })
    return d


def election_out(e):
    return {
        "id": e["id"],
        "beneficiary_id": e["beneficiary_id"],
        "direction": e["direction"],
        "effective_date": e["effective_date"],
        "created_at": e["created_at"],
    }


def alignment_run_out(r):
    d = _common(r)
    d.update({
        "agreement_period_id": r["agreement_period_id"],
        "methodology": r["methodology"],
        "window_start_date": r["window_start_date"],
        "window_end_date": r["window_end_date"],
        "records_created_count": r["records_created_count"],
        "status": r["status"],
    })
    return d


def attribution_record_out(r):
    d = _common(r)
    d.update({
        "agreement_period_id": r["agreement_period_id"],
        "beneficiary_id": r["beneficiary_id"],
        "alignment_run_id": r["alignment_run_id"],
        "participant_id": r["participant_id"],
        "plurality_cost_cents": r["plurality_cost_cents"],
        "methodology": r["methodology"],
        "status": r["status"],
    })
    return d


def claim_out(c):
    d = _common(c)
    d.update({
        "agreement_period_id": c["agreement_period_id"],
        "beneficiary_id": c["beneficiary_id"],
        "participant_id": c["participant_id"],
        "service_date": c["service_date"],
        "allowed_amount_cents": c["allowed_amount_cents"],
        "claim_type": c["claim_type"],
        "review_excluded": c["review_excluded"],
        "status": c["status"],
    })
    return d


def benchmark_out(b):
    d = _common(b)
    d.update({
        "agreement_period_id": b["agreement_period_id"],
        "variant": b["variant"],
        "beneficiary_months": b["beneficiary_months"],
        "risk_score_sum": float(b["risk_score_sum"]),
        "update_factor_used": float(b["update_factor_used"]),
        "total_benchmark_cents": b["total_benchmark_cents"],
        "status": b["status"],
    })
    return d


def quality_score_out(s):
    d = _common(s)
    d.update({
        "agreement_period_id": s["agreement_period_id"],
        "measure_code": s["measure_code"],
        "numerator": s["numerator"],
        "denominator": s["denominator"],
        "max_points": s["max_points"],
        "performance_rate": float(s["performance_rate"]),
        "earned_points": float(s["earned_points"]),
        "reported_by_user_id": s["reported_by_user_id"],
        "status": s["status"],
    })
    return d


def settlement_out(s):
    d = _common(s)
    d.update({
        "agreement_period_id": s["agreement_period_id"],
        "benchmark_id": s["benchmark_id"],
        "expenditure_total_cents": s["expenditure_total_cents"],
        "gross_savings_cents": s["gross_savings_cents"],
        "msr_threshold_cents": s["msr_threshold_cents"],
        "quality_score_snapshot": float(s["quality_score_snapshot"]),
        "quality_multiplier_snapshot": float(s["quality_multiplier_snapshot"]),
        "shared_savings_pre_sequestration_cents": s["shared_savings_pre_sequestration_cents"],
        "sequestration_levy_cents": s["sequestration_levy_cents"],
        "net_shared_savings_cents": s["net_shared_savings_cents"],
        "shared_loss_cents": s["shared_loss_cents"],
        "distributable_pool_cents": s["distributable_pool_cents"],
        "reconciliation_balance_cents": s["reconciliation_balance_cents"],
        "last_distribution_run_by_user_id": s["last_distribution_run_by_user_id"],
        "finalized_at": (db.render_logical(s["finalized_at_dt"])
                         if s.get("finalized_at_dt") else None),
        "status": s["status"],
    })
    return d


def distribution_line_out(line):
    d = _common(line)
    d.update({
        "settlement_id": line["settlement_id"],
        "participant_id": line["participant_id"],
        "amount_cents": line["amount_cents"],
        "status": line["status"],
    })
    return d


def high_cost_review_out(r):
    d = _common(r)
    d.update({
        "agreement_period_id": r["agreement_period_id"],
        "beneficiary_id": r["beneficiary_id"],
        "flagged_expenditure_cents": r["flagged_expenditure_cents"],
        "dismissal_reason": r["dismissal_reason"],
        "determined_by_user_id": r["determined_by_user_id"],
        "rationale": r["rationale"],
        "status": r["status"],
    })
    return d


def appeal_out(a):
    d = _common(a)
    d.update({
        "agreement_period_id": a["agreement_period_id"],
        "subject_type": a["subject_type"],
        "subject_id": a["subject_id"],
        "filed_by_participant_id": a["filed_by_participant_id"],
        "grounds": a["grounds"],
        "round_count": a["round_count"],
        "decided_outcome": a["decided_outcome"],
        "status": a["status"],
    })
    return d


def adjustment_out(a):
    d = _common(a)
    d.update({
        "settlement_id": a["settlement_id"],
        "appeal_id": a["appeal_id"],
        "direction": a["direction"],
        "amount_cents": a["amount_cents"],
        "reason_code": a["reason_code"],
        "status": a["status"],
    })
    return d
