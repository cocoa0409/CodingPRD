"""Public serializers: build the API view of each entity, resolving the
denormalised computed back-pointers per their field descriptions (SCAFFOLD §1.1)."""
from db import db


def _account_active_subscription_id(account_id):
    """active_subscription_id: id of the account's current ACTIVE or GRACE
    subscription, or null."""
    for sub in db.subscriptions.values():
        if sub["account_id"] == account_id and sub["status"] in ("ACTIVE", "GRACE"):
            return sub["id"]
    return None


def _account_pet_count(account_id):
    """pet_count: count of Pets whose account_id == this account and
    status != ARCHIVED."""
    return sum(
        1 for p in db.pets.values()
        if p["account_id"] == account_id and p["status"] != "ARCHIVED"
    )


def _account_purge_pending(account_id):
    """purge_pending: True when a DELETE-type DataRequest for this account is
    in GRACE or PURGING state."""
    for dr in db.data_requests.values():
        if (dr["account_id"] == account_id and dr["kind"] == "DELETE"
                and dr["status"] in ("GRACE", "PURGING")):
            return True
    return False


def serialize_account(rec):
    return {
        "id": rec["id"],
        "email": rec["email"],
        "full_name": rec["full_name"],
        "data_residency": rec["data_residency"],
        "active_subscription_id": _account_active_subscription_id(rec["id"]),
        "relative_finder_opt_in": rec["relative_finder_opt_in"],
        "pet_count": _account_pet_count(rec["id"]),
        "purge_pending": _account_purge_pending(rec["id"]),
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_pet(rec):
    return {
        "id": rec["id"],
        "account_id": rec["account_id"],
        "name": rec["name"],
        "species": rec["species"],
        "birth_year": rec["birth_year"],
        "relative_finder_opt_in": rec["relative_finder_opt_in"],
        "status": rec["status"],
        "finalized_report_id": rec["finalized_report_id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_kit(rec):
    return {
        "id": rec["id"],
        "account_id": rec["account_id"],
        "barcode": rec["barcode"],
        "product_tier": rec["product_tier"],
        "status": rec["status"],
        "activated_pet_id": rec["activated_pet_id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_sample(rec):
    return {
        "id": rec["id"],
        "kit_id": rec["kit_id"],
        "pet_id": rec["pet_id"],
        "status": rec["status"],
        "qc_score": rec["qc_score"],
        "retest_of_sample_id": rec["retest_of_sample_id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_genotyping_run(rec):
    return {
        "id": rec["id"],
        "sample_id": rec["sample_id"],
        "call_rate": rec["call_rate"],
        "het_rate": rec["het_rate"],
        "contamination": rec["contamination"],
        "qc_score": rec["qc_score"],
        "outcome": rec["outcome"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_report(rec):
    return {
        "id": rec["id"],
        "sample_id": rec["sample_id"],
        "pet_id": rec["pet_id"],
        "includes_health": rec["includes_health"],
        "status": rec["status"],
        "breed_composition": rec["breed_composition"],
        "at_risk_marker_count": rec["at_risk_marker_count"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_health_marker_result(rec):
    # Lightweight: only id and created_at (no updated_at, no version) — PRD §2.4
    return {
        "id": rec["id"],
        "report_id": rec["report_id"],
        "marker_code": rec["marker_code"],
        "genotype": rec["genotype"],
        "review_status": rec["review_status"],
        "created_at": rec["created_at"],
    }


def serialize_relative_match(rec):
    return {
        "id": rec["id"],
        "pet_id": rec["pet_id"],
        "relative_pet_id": rec["relative_pet_id"],
        "shared_cm": rec["shared_cm"],
        "relationship_pct": rec["relationship_pct"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_share_link(rec):
    return {
        "id": rec["id"],
        "report_id": rec["report_id"],
        "vet_email": rec["vet_email"],
        "token": rec["token"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_subscription(rec):
    return {
        "id": rec["id"],
        "account_id": rec["account_id"],
        "tier": rec["tier"],
        "status": rec["status"],
        "started_on": rec["started_on"],
        "term_days": rec["term_days"],
        "annual_fee_cents": rec["annual_fee_cents"],
        "last_charge_cents": rec["last_charge_cents"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_data_request(rec):
    return {
        "id": rec["id"],
        "account_id": rec["account_id"],
        "kind": rec["kind"],
        "status": rec["status"],
        "grace_until": rec["grace_until"],
        "export_payload": rec["export_payload"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_marker_catalog_entry(rec):
    # Lightweight: only id and created_at — PRD §2.4 / §3.9
    return {
        "id": rec["id"],
        "marker_code": rec["marker_code"],
        "category": rec["category"],
        "species": rec["species"],
        "created_at": rec["created_at"],
    }
