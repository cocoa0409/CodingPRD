"""Output serializers. Each returns exactly the fields the PRD/scaffold declare
for the entity, omitting internal bookkeeping (_seq)."""


def _common(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def client_out(c):
    return {
        **_common(c),
        "full_name": c["full_name"],
        "date_of_birth": c["date_of_birth"],
        "caregiver_user_id": c["caregiver_user_id"],
        "insurance_payer_id": c["insurance_payer_id"],
        "status": c["status"],
    }


def payer_out(p):
    return {
        **_common(p),
        "name": p["name"],
        "allowed_rate_cents": p["allowed_rate_cents"],
        "coinsurance_pct": p["coinsurance_pct"],
        "supervision_ratio_pct": p["supervision_ratio_pct"],
    }


def provider_out(p):
    return {
        **_common(p),
        "full_name": p["full_name"],
        "credential": p["credential"],
        "npi": p["npi"],
        "supervising_bcba_id": p["supervising_bcba_id"],
        "status": p["status"],
    }


def evaluation_out(e):
    return {
        **_common(e),
        "client_id": e["client_id"],
        "evaluator_bcba_id": e["evaluator_bcba_id"],
        "assessment_score": e["assessment_score"],
        "severity_level": e["severity_level"],
        "recommended_weekly_units": e["recommended_weekly_units"],
        "status": e["status"],
    }


def plan_out(p):
    return {
        **_common(p),
        "client_id": p["client_id"],
        "evaluation_id": p["evaluation_id"],
        "author_bcba_id": p["author_bcba_id"],
        "requested_direct_units": p["requested_direct_units"],
        "requested_supervision_units": p["requested_supervision_units"],
        "requested_parent_training_units": p["requested_parent_training_units"],
        "status": p["status"],
    }


def authorization_out(a):
    return {
        **_common(a),
        "treatment_plan_id": a["treatment_plan_id"],
        "payer_id": a["payer_id"],
        "authorized_direct_units": a["authorized_direct_units"],
        "authorized_supervision_units": a["authorized_supervision_units"],
        "authorized_parent_training_units": a["authorized_parent_training_units"],
        "period_start": a["period_start"],
        "period_end": a["period_end"],
        "reserved_direct_units": a["reserved_direct_units"],
        "delivered_direct_units": a["delivered_direct_units"],
        "reserved_supervision_units": a["reserved_supervision_units"],
        "delivered_supervision_units": a["delivered_supervision_units"],
        "reserved_parent_training_units": a["reserved_parent_training_units"],
        "delivered_parent_training_units": a["delivered_parent_training_units"],
        "remaining_direct_units": a["remaining_direct_units"],
        "supervision_status": a["supervision_status"],
        "status": a["status"],
        "superseded_by_id": a["superseded_by_id"],
    }


def session_out(s):
    return {
        **_common(s),
        "authorization_id": s["authorization_id"],
        "provider_id": s["provider_id"],
        "service_line": s["service_line"],
        "scheduled_start": s["scheduled_start"],
        "scheduled_end": s["scheduled_end"],
        "scheduled_units": s["scheduled_units"],
        "delivered_units": s["delivered_units"],
        "status": s["status"],
    }


def claim_out(c):
    return {
        **_common(c),
        "session_id": c["session_id"],
        "payer_id": c["payer_id"],
        "billed_cents": c["billed_cents"],
        "allowed_cents": c["allowed_cents"],
        "patient_responsibility_cents": c["patient_responsibility_cents"],
        "payer_paid_cents": c["payer_paid_cents"],
        "denial_reason": c["denial_reason"],
        "status": c["status"],
    }
