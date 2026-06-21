"""Entity -> JSON serialization (PRD §2.4).

Common fields:
  - Every entity has `id` (UUID, no prefix) and `created_at` (ISO 8601, 3 frac digits).
  - Most entities additionally carry `updated_at` and an integer `version`.
  - Two lightweight, immutable entities carry ONLY `id` + `created_at`:
    `Certificate` and `Attestation` (no `updated_at`, no `version`).

Computed cycle fields (earned hours, carryover, reminder) are recomputed and
serialized live; reminder_status in particular is re-derived against the current
clock on every read and never persisted stale.
"""

from util import iso_millis
import services.cycle as cycle_service


def _common(record):
    out = {
        "id": record["id"],
        "created_at": iso_millis(record["created_at"]),
        "updated_at": iso_millis(record["updated_at"]),
        "version": record["version"],
    }
    return out


def _lightweight(record):
    return {
        "id": record["id"],
        "created_at": iso_millis(record["created_at"]),
    }


def license_board(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "jurisdiction_code": r["jurisdiction_code"],
        "credit_unit": r["credit_unit"],
        "cycle_length_months": r["cycle_length_months"],
        "total_required_hours": r["total_required_hours"],
        "carryover_cap_hours": r["carryover_cap_hours"],
        "audit_cooldown_days": r["audit_cooldown_days"],
        "reminder_lead_days": r["reminder_lead_days"],
    })
    return out


def credit_requirement(r):
    out = _common(r)
    out.update({
        "board_id": r["board_id"],
        "category": r["category"],
        "min_hours": r["min_hours"],
    })
    return out


def provider(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "board_id": r["board_id"],
        "status": r["status"],
        "accredited_from": iso_millis(r["accredited_from"]),
        "accredited_until": iso_millis(r["accredited_until"]),
    })
    return out


def course(r):
    out = _common(r)
    out.update({
        "provider_id": r["provider_id"],
        "title": r["title"],
        "category": r["category"],
        "credit_hours": r["credit_hours"],
        "status": r["status"],
    })
    return out


def licensee(r):
    out = _common(r)
    out.update({
        "full_name": r["full_name"],
        "home_board_id": r["home_board_id"],
        "license_number": r["license_number"],
        "audit_risk_score": r["audit_risk_score"],
    })
    return out


def renewal_cycle(r):
    # Recompute reminder_status live against the current clock (PRD §3.3).
    reminder_status = cycle_service.compute_reminder_status(r)
    out = _common(r)
    out.update({
        "licensee_id": r["licensee_id"],
        "board_id": r["board_id"],
        "cycle_start": iso_millis(r["cycle_start"]),
        "cycle_end": iso_millis(r["cycle_end"]),
        "status": r["status"],
        "carryover_in_hours": r["carryover_in_hours"],
        "carryover_out_hours": r["carryover_out_hours"],
        "provisional_earned_hours": r["provisional_earned_hours"],
        "final_earned_hours": r["final_earned_hours"],
        "reciprocity_hours": r["reciprocity_hours"],
        "reminder_status": reminder_status,
    })
    return out


def completion(r):
    out = _common(r)
    out.update({
        "licensee_id": r["licensee_id"],
        "course_id": r["course_id"],
        "cycle_id": r["cycle_id"],
        "completed_at": iso_millis(r["completed_at"]),
        "awarded_hours": r["awarded_hours"],
        "category": r["category"],
        "status": r["status"],
        "is_late": r["is_late"],
    })
    return out


def certificate(r):
    out = _lightweight(r)
    out.update({
        "cycle_id": r["cycle_id"],
        "serial_number": r["serial_number"],
        "total_hours_certified": r["total_hours_certified"],
        "issued_at": iso_millis(r["issued_at"]),
    })
    return out


def audit(r):
    out = _common(r)
    out.update({
        "cycle_id": r["cycle_id"],
        "licensee_id": r["licensee_id"],
        "initiated_by_user_id": r["initiated_by_user_id"],
        "decided_by_user_id": r["decided_by_user_id"],
        "status": r["status"],
        "initiated_at": iso_millis(r["initiated_at"]),
        "closed_at": iso_millis(r["closed_at"]),
    })
    return out


def attestation(r):
    out = _lightweight(r)
    out.update({
        "audit_id": r["audit_id"],
        "statement": r["statement"],
        "attested_hours": r["attested_hours"],
    })
    return out


def reciprocity_grant(r):
    out = _common(r)
    out.update({
        "licensee_id": r["licensee_id"],
        "target_cycle_id": r["target_cycle_id"],
        "source_jurisdiction_code": r["source_jurisdiction_code"],
        "category": r["category"],
        "credit_hours": r["credit_hours"],
        "status": r["status"],
    })
    return out
