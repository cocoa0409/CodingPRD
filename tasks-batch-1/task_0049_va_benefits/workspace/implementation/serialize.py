"""Output serializers. Each returns exactly the fields the PRD/scaffold declare
for the entity, omitting internal bookkeeping (_seq, _yr_slot, etc.)."""


def veteran_out(v):
    return {
        "id": v["id"],
        "full_name": v["full_name"],
        "file_number": v["file_number"],
        "total_active_duty_days": v["total_active_duty_days"],
        "discharged_for_service_disability": v["discharged_for_service_disability"],
        "combined_rating_pct": v["combined_rating_pct"],
        "provisional_combined_rating_pct": v["provisional_combined_rating_pct"],
        "gi_bill_tier_pct": v["gi_bill_tier_pct"],
        "monthly_compensation_cents": v["monthly_compensation_cents"],
        "voc_rehab_entitlement_months": v["voc_rehab_entitlement_months"],
        "award_status": v["award_status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def claim_out(c):
    return {
        "id": c["id"],
        "veteran_id": c["veteran_id"],
        "claim_type": c["claim_type"],
        "received_date": c["received_date"],
        "status": c["status"],
        "remand_count": c["remand_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def condition_out(c):
    return {
        "id": c["id"],
        "veteran_id": c["veteran_id"],
        "claim_id": c["claim_id"],
        "diagnostic_code": c["diagnostic_code"],
        "body_side": c["body_side"],
        "is_extremity": c["is_extremity"],
        "proposed_rating_pct": c["proposed_rating_pct"],
        "final_rating_pct": c["final_rating_pct"],
        "service_connection": c["service_connection"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def dependent_out(d):
    # Dependent is leaner: only id + created_at, no updated_at / version
    # (PRD §2.4).
    return {
        "id": d["id"],
        "veteran_id": d["veteran_id"],
        "relationship": d["relationship"],
        "in_school_18_to_23": d["in_school_18_to_23"],
        "status": d["status"],
        "created_at": d["created_at"],
    }


def school_out(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "is_public": s["is_public"],
        "yellow_ribbon_participant": s["yellow_ribbon_participant"],
        "yellow_ribbon_max_contribution_cents": s["yellow_ribbon_max_contribution_cents"],
        "yellow_ribbon_slots_total": s["yellow_ribbon_slots_total"],
        "yellow_ribbon_slots_used": s["yellow_ribbon_slots_used"],
        "monthly_housing_rate_cents": s["monthly_housing_rate_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def enrollment_out(e):
    return {
        "id": e["id"],
        "veteran_id": e["veteran_id"],
        "school_id": e["school_id"],
        "term_start": e["term_start"],
        "term_end": e["term_end"],
        "credit_hours": e["credit_hours"],
        "full_time_credit_hours": e["full_time_credit_hours"],
        "tuition_charged_cents": e["tuition_charged_cents"],
        "requests_yellow_ribbon": e["requests_yellow_ribbon"],
        "rate_of_pursuit_pct": e["rate_of_pursuit_pct"],
        "monthly_housing_allowance_cents": e["monthly_housing_allowance_cents"],
        "estimated_mha_cents": e["estimated_mha_cents"],
        "yellow_ribbon_match_cents": e["yellow_ribbon_match_cents"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def voc_rehab_plan_out(p):
    return {
        "id": p["id"],
        "veteran_id": p["veteran_id"],
        "planned_months": p["planned_months"],
        "track": p["track"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }
