"""Public serializers. Each returns a fresh dict so internal mutation cannot
leak through a cached response. Field sets follow SCAFFOLD §1.1 entities.
"""


def owner_view(o):
    return {
        "id": o["id"],
        "full_name": o["full_name"],
        "email": o["email"],
        "address_zip": o["address_zip"],
        "status": o["status"],
        "active_license_count": o["active_license_count"],
        "outstanding_penalty_cents": o["outstanding_penalty_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def pet_view(p):
    return {
        "id": p["id"],
        "owner_id": p["owner_id"],
        "name": p["name"],
        "species": p["species"],
        "breed": p["breed"],
        "is_altered": p["is_altered"],
        "birth_date": p["birth_date"],
        "is_dangerous": p["is_dangerous"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def vaccination_view(v):
    # immutable: id + created_at only (no updated_at / version) — PRD §2.4
    return {
        "id": v["id"],
        "pet_id": v["pet_id"],
        "vaccine_type": v["vaccine_type"],
        "administered_on": v["administered_on"],
        "expires_on": v["expires_on"],
        "vet_license_no": v["vet_license_no"],
        "created_at": v["created_at"],
    }


def kennel_view(k):
    return {
        "id": k["id"],
        "owner_id": k["owner_id"],
        "facility_name": k["facility_name"],
        "slot_capacity": k["slot_capacity"],
        "occupied_slots": k["occupied_slots"],
        "status": k["status"],
        "created_at": k["created_at"],
        "updated_at": k["updated_at"],
        "version": k["version"],
    }


def license_view(l):
    return {
        "id": l["id"],
        "owner_id": l["owner_id"],
        "pet_id": l["pet_id"],
        "kennel_id": l["kennel_id"],
        "license_kind": l["license_kind"],
        "term_years": l["term_years"],
        "vaccination_record_id": l["vaccination_record_id"],
        "status": l["status"],
        "provisional_fee_cents": l["provisional_fee_cents"],
        "final_fee_cents": l["final_fee_cents"],
        "late_penalty_cents": l["late_penalty_cents"],
        "penalty_paid": l["penalty_paid"],
        "issued_on": l["issued_on"],
        "expires_on": l["expires_on"],
        "tag_serial": l["tag_serial"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def tag_view(t):
    return {
        "id": t["id"],
        "license_id": t["license_id"],
        "serial": t["serial"],
        "status": t["status"],
        "issued_on": t["issued_on"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def case_view(c):
    return {
        "id": c["id"],
        "pet_id": c["pet_id"],
        "incident_summary": c["incident_summary"],
        "severity": c["severity"],
        "status": c["status"],
        "surcharge_cents": c["surcharge_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def report_view(r):
    return {
        "id": r["id"],
        "report_type": r["report_type"],
        "pet_id": r["pet_id"],
        "tag_serial_seen": r["tag_serial_seen"],
        "species": r["species"],
        "zip_seen": r["zip_seen"],
        "reported_at": r["reported_at"],
        "status": r["status"],
        "matched_report_id": r["matched_report_id"],
        "match_score": r["match_score"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def audit_view(a):
    # append-only: id + created_at only
    return {
        "id": a["id"],
        "subject_entity": a["subject_entity"],
        "subject_id": a["subject_id"],
        "action": a["action"],
        "actor_role": a["actor_role"],
        "created_at": a["created_at"],
    }
