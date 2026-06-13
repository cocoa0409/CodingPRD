"""Serializers: project stored records to API output, dropping internal fields."""

# Internal/computed bookkeeping keys never returned to clients.
_INTERNAL = {"_seq"}


def _public(record):
    return {k: v for k, v in record.items() if k not in _INTERNAL}


def ser_insurer(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "naic_code": r["naic_code"],
        "current_date": r["current_date"],
        "audit_waiver_threshold_cents": r["audit_waiver_threshold_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_insured(r):
    return {
        "id": r["id"],
        "insurer_id": r["insurer_id"],
        "legal_name": r["legal_name"],
        "fein": r["fein"],
        "primary_basis": r["primary_basis"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_holder(r):
    return {
        "id": r["id"],
        "insurer_id": r["insurer_id"],
        "holder_name": r["holder_name"],
        "address": r["address"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_policy(r):
    return {
        "id": r["id"],
        "insurer_id": r["insurer_id"],
        "insured_id": r["insured_id"],
        "policy_number": r["policy_number"],
        "coverage_trigger": r["coverage_trigger"],
        "retroactive_date": r["retroactive_date"],
        "effective_date": r["effective_date"],
        "expiration_date": r["expiration_date"],
        "each_occurrence_limit_cents": r["each_occurrence_limit_cents"],
        "general_aggregate_limit_cents": r["general_aggregate_limit_cents"],
        "products_aggregate_limit_cents": r["products_aggregate_limit_cents"],
        "premium_basis": r["premium_basis"],
        "rate_per_unit_cents": r["rate_per_unit_cents"],
        "minimum_premium_cents": r["minimum_premium_cents"],
        "estimated_exposure_units": r["estimated_exposure_units"],
        "estimated_premium_cents": r["estimated_premium_cents"],
        "audited_premium_cents": r["audited_premium_cents"],
        "general_aggregate_remaining_cents": r["general_aggregate_remaining_cents"],
        "products_aggregate_remaining_cents": r["products_aggregate_remaining_cents"],
        "posture": r["posture"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_endorsement(r):
    return {
        "id": r["id"],
        "policy_id": r["policy_id"],
        "certificate_holder_id": r["certificate_holder_id"],
        "form_number": r["form_number"],
        "scope": r["scope"],
        "ai_effective_date": r["ai_effective_date"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_certificate(r):
    return {
        "id": r["id"],
        "policy_id": r["policy_id"],
        "certificate_holder_id": r["certificate_holder_id"],
        "additional_insured_endorsement_id": r["additional_insured_endorsement_id"],
        "names_as_additional_insured": r["names_as_additional_insured"],
        "issue_date": r["issue_date"],
        "snapshot_each_occurrence_cents": r["snapshot_each_occurrence_cents"],
        "snapshot_general_aggregate_remaining_cents": r["snapshot_general_aggregate_remaining_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_claim(r):
    return {
        "id": r["id"],
        "policy_id": r["policy_id"],
        "claimant_name": r["claimant_name"],
        "loss_type": r["loss_type"],
        "occurrence_date": r["occurrence_date"],
        "reported_date": r["reported_date"],
        "aggregate_bucket": r["aggregate_bucket"],
        "incurred_cents": r["incurred_cents"],
        "recognized_incurred_cents": r["recognized_incurred_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_transaction(r):
    # Immutable ledger entry: only id and created_at (PRD §2.4). No updated_at/version.
    return {
        "id": r["id"],
        "claim_id": r["claim_id"],
        "txn_type": r["txn_type"],
        "amount_cents": r["amount_cents"],
        "posted_sequence": r["posted_sequence"],
        "memo": r["memo"],
        "created_at": r["created_at"],
    }


def ser_audit(r):
    return {
        "id": r["id"],
        "policy_id": r["policy_id"],
        "audit_basis": r["audit_basis"],
        "audited_exposure_units": r["audited_exposure_units"],
        "computed_audited_premium_cents": r["computed_audited_premium_cents"],
        "net_adjustment_cents": r["net_adjustment_cents"],
        "revision_round": r["revision_round"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_exposure(r):
    return {
        "id": r["id"],
        "premium_audit_id": r["premium_audit_id"],
        "class_code": r["class_code"],
        "basis_amount_units": r["basis_amount_units"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_loss_run(r):
    return {
        "id": r["id"],
        "policy_id": r["policy_id"],
        "as_of_date": r["as_of_date"],
        "total_incurred_cents": r["total_incurred_cents"],
        "general_incurred_cents": r["general_incurred_cents"],
        "products_incurred_cents": r["products_incurred_cents"],
        "claim_count": r["claim_count"],
        "open_claim_count": r["open_claim_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
