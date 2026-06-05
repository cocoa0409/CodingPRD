"""Serializers project stored dicts to API output shape (PRD §1.1 entities).

Computed fields (occupied_lot_count, current_rent_cents, arrears_cents,
apportioned_total_cents, yes_count) are recomputed at read time so GET endpoints
always return their current computed form (PRD §2.5).
"""
import services


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _record(rec):
    # Append-only / immutable records: only id + created_at (PRD §2.4).
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }


def community_out(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "state_code": rec["state_code"],
        "ownership_model": rec["ownership_model"],
        "utility_apportionment_method": rec["utility_apportionment_method"],
        "occupied_lot_count": services.occupied_lot_count(rec["id"]),
        "total_metered_units": rec.get("total_metered_units", 0),
    })
    return out


def lot_out(rec):
    out = _common(rec)
    out.update({
        "community_id": rec["community_id"],
        "lot_number": rec["lot_number"],
        "base_rent_cents": rec["base_rent_cents"],
        "status": rec["status"],
        "current_lease_id": rec["current_lease_id"],
        "current_rent_cents": services.current_rent_cents(rec),
    })
    return out


def resident_out(rec):
    out = _common(rec)
    out.update({
        "community_id": rec["community_id"],
        "full_name": rec["full_name"],
        "household_size": rec["household_size"],
        "standing": rec["standing"],
        "arrears_cents": services.resident_arrears(rec["id"]),
    })
    return out


def lease_out(rec):
    out = _common(rec)
    out.update({
        "lot_id": rec["lot_id"],
        "resident_id": rec["resident_id"],
        "supersedes_lease_id": rec["supersedes_lease_id"],
        "start_date": rec["start_date"],
        "rent_cents_at_signing": rec["rent_cents_at_signing"],
        "status": rec["status"],
        "expected_lot_version": rec.get("expected_lot_version"),
    })
    return out


def rent_schedule_out(rec):
    out = _common(rec)
    out.update({
        "lot_id": rec["lot_id"],
        "prior_rent_cents": rec["prior_rent_cents"],
        "proposed_rent_cents": rec["proposed_rent_cents"],
        "new_rent_cents": rec["new_rent_cents"],
        "effective_date": rec["effective_date"],
        "cap_applied": rec["cap_applied"],
        "status": rec["status"],
    })
    return out


def utility_bill_out(rec):
    out = _common(rec)
    out.update({
        "community_id": rec["community_id"],
        "utility_type": rec["utility_type"],
        "period_start": rec["period_start"],
        "period_end": rec["period_end"],
        "master_charge_cents": rec["master_charge_cents"],
        "apportioned_total_cents": rec["apportioned_total_cents"],
        "status": rec["status"],
    })
    return out


def utility_reading_out(rec):
    out = _record(rec)
    out.update({
        "utility_bill_id": rec["utility_bill_id"],
        "lot_id": rec["lot_id"],
        "metered_units": rec["metered_units"],
    })
    return out


def utility_charge_out(rec):
    out = _record(rec)
    out.update({
        "utility_bill_id": rec["utility_bill_id"],
        "lot_id": rec["lot_id"],
        "resident_id": rec["resident_id"],
        "amount_cents": rec["amount_cents"],
    })
    return out


def eviction_case_out(rec):
    out = _common(rec)
    out.update({
        "lease_id": rec["lease_id"],
        "reason": rec["reason"],
        "cure_deadline": rec["cure_deadline"],
        "status": rec["status"],
    })
    return out


def conversion_vote_out(rec):
    out = _common(rec)
    out.update({
        "community_id": rec["community_id"],
        "quorum_threshold_pct": rec["quorum_threshold_pct"],
        "yes_count": services.yes_count(rec["id"]),
        "eligible_lot_count": rec["eligible_lot_count"],
        "status": rec["status"],
    })
    return out


def conversion_ballot_out(rec):
    out = _record(rec)
    out.update({
        "conversion_vote_id": rec["conversion_vote_id"],
        "lot_id": rec["lot_id"],
        "choice": rec["choice"],
    })
    return out


def ledger_entry_out(rec):
    out = _record(rec)
    out.update({
        "lease_id": rec["lease_id"],
        "resident_id": rec["resident_id"],
        "entry_type": rec["entry_type"],
        "amount_cents": rec["amount_cents"],
    })
    return out
