"""Entity -> response-dict serializers.

Records are stored as plain dicts shaped close to the output contract; serializers
return fresh dicts (omitting internal bookkeeping like _seq) so callers cannot
mutate the store and internal fields never leak into responses.
"""


def serialize_program(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "name": p["name"],
        "single_limit_cents": p["single_limit_cents"],
        "aggregate_limit_cents": p["aggregate_limit_cents"],
        "referral_threshold_cents": p["referral_threshold_cents"],
        "loss_alert_threshold_cents": p["loss_alert_threshold_cents"],
        "aggregate_committed_cents": p["aggregate_committed_cents"],
        "aggregate_available_cents": p["aggregate_limit_cents"] - p["aggregate_committed_cents"],
        "status": p["status"],
    }


def serialize_principal(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "legal_name": p["legal_name"],
        "credit_score": p["credit_score"],
        "working_capital_cents": p["working_capital_cents"],
        "credit_tier": p["credit_tier"],
        "indemnity_on_file": p["indemnity_on_file"],
    }


def serialize_indemnity_agreement(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "principal_id": a["principal_id"],
        "indemnitor_count": a["indemnitor_count"],
        "required_signature_count": a["required_signature_count"],
        "collected_signature_count": a["collected_signature_count"],
        "status": a["status"],
    }


def serialize_application(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "principal_id": a["principal_id"],
        "program_id": a["program_id"],
        "bond_type": a["bond_type"],
        "requested_penal_sum_cents": a["requested_penal_sum_cents"],
        "term_months": a["term_months"],
        "quoted_premium_rate_bps": a["quoted_premium_rate_bps"],
        "quoted_premium_cents": a["quoted_premium_cents"],
        "status": a["status"],
        "decline_reason": a["decline_reason"],
    }


def serialize_bond(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "application_id": b["application_id"],
        "principal_id": b["principal_id"],
        "program_id": b["program_id"],
        "superseded_by_bond_id": b["superseded_by_bond_id"],
        "bond_type": b["bond_type"],
        "penal_sum_cents": b["penal_sum_cents"],
        "term_months": b["term_months"],
        "power_of_attorney_number": b["power_of_attorney_number"],
        "premium_rate_bps": b["premium_rate_bps"],
        "written_premium_cents": b["written_premium_cents"],
        "earned_premium_cents": b["earned_premium_cents"],
        "ceded_penal_sum_cents": b["ceded_penal_sum_cents"],
        "net_retained_cents": b["penal_sum_cents"] - b["ceded_penal_sum_cents"],
        "incurred_loss_cents": b["incurred_loss_cents"],
        "status": b["status"],
    }


def serialize_claim(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "bond_id": c["bond_id"],
        "claimant_name": c["claimant_name"],
        "demand_cents": c["demand_cents"],
        "reserve_cents": c["reserve_cents"],
        "paid_loss_cents": c["paid_loss_cents"],
        "salvage_cents": c["salvage_cents"],
        "status": c["status"],
    }


def serialize_rider(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "bond_id": r["bond_id"],
        "rider_type": r["rider_type"],
        "penal_sum_delta_cents": r["penal_sum_delta_cents"],
        "additional_premium_cents": r["additional_premium_cents"],
        "status": r["status"],
    }


def serialize_treaty(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "name": t["name"],
        "cession_pct_bps": t["cession_pct_bps"],
        "treaty_capacity_cents": t["treaty_capacity_cents"],
        "ceded_committed_cents": t["ceded_committed_cents"],
        "ceded_available_cents": t["treaty_capacity_cents"] - t["ceded_committed_cents"],
        "status": t["status"],
    }


def serialize_cession(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "bond_id": c["bond_id"],
        "treaty_id": c["treaty_id"],
        "ceded_penal_sum_cents": c["ceded_penal_sum_cents"],
        "status": c["status"],
    }
