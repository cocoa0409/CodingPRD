"""Serialization of entities to response payloads, including derived fields.

Derived (computed) fields are recomputed at read time from the canonical store
state per scaffold 1.3 aggregations and the entity table.
"""
from db import db
import calculations as calc


# ----------------------------------------------------------------------------
# Studio derived fields (kit ledger + compliance posture)
# ----------------------------------------------------------------------------
def studio_kit_consumed(studio_id):
    """Count appointments scoped to this studio (via technician.studio_id) whose
    kit_consumed is true and lifecycle in IN_PROCEDURE/HEALING/COMPLETED."""
    count = 0
    for appt in db.appointments.values():
        tech = db.technicians.get(appt.get("technician_id"))
        if not tech or tech.get("studio_id") != studio_id:
            continue
        if appt.get("kit_consumed") and appt.get("lifecycle_status") in ("IN_PROCEDURE", "HEALING", "COMPLETED"):
            count += 1
    return count


def studio_kit_available(studio):
    consumed = studio_kit_consumed(studio["id"])
    return max(0, studio["sterile_kit_total"] - consumed)


def studio_has_active_tech(studio_id):
    for tech in db.technicians.values():
        if tech.get("studio_id") == studio_id and tech.get("license_status") == "LICENSE_ACTIVE":
            return True
    return False


def compliance_posture(studio):
    """PRD 2.10: OPEN when >=1 LICENSE_ACTIVE tech AND >=1 kit available;
    RESTRICTED when no kit available but a licensed tech exists;
    FROZEN when no LICENSE_ACTIVE technician."""
    available = studio_kit_available(studio)
    has_active = studio_has_active_tech(studio["id"])
    if not has_active:
        return "FROZEN"
    if available == 0:
        return "RESTRICTED"
    return "OPEN"


def serialize_studio(studio):
    consumed = studio_kit_consumed(studio["id"])
    available = max(0, studio["sterile_kit_total"] - consumed)
    return {
        "id": studio["id"],
        "name": studio["name"],
        "state_code": studio["state_code"],
        "min_client_age": studio["min_client_age"],
        "sterile_kit_total": studio["sterile_kit_total"],
        "sterile_kit_consumed": consumed,
        "sterile_kit_available": available,
        "compliance_posture": compliance_posture(studio),
        "created_at": studio["created_at"],
        "updated_at": studio["updated_at"],
        "version": studio["version"],
    }


def serialize_technician(tech):
    return {
        "id": tech["id"],
        "studio_id": tech["studio_id"],
        "full_name": tech["full_name"],
        "license_number": tech["license_number"],
        "bbp_cert_expiry": tech["bbp_cert_expiry"],
        "license_expiry": tech["license_expiry"],
        "license_status": tech["license_status"],
        "created_at": tech["created_at"],
        "updated_at": tech["updated_at"],
        "version": tech["version"],
    }


# ----------------------------------------------------------------------------
# Client derived fields
# ----------------------------------------------------------------------------
def client_no_show_strikes(client_id):
    return sum(
        1 for a in db.appointments.values()
        if a.get("client_id") == client_id and a.get("lifecycle_status") == "NO_SHOW"
    )


def client_status(strikes):
    return "BLOCKED" if strikes >= calc.NO_SHOW_BLOCK_THRESHOLD else "ACTIVE"


def client_risk(client):
    score = calc.client_risk_score(
        client["medical_flag_count"],
        client["prior_adverse_reactions"],
        client["skin_sensitivity_self"],
        client["skin_sensitivity_observed"],
    )
    return score, calc.risk_band(score)


def serialize_client(client):
    score, band = client_risk(client)
    strikes = client_no_show_strikes(client["id"])
    return {
        "id": client["id"],
        "studio_id": client["studio_id"],
        "full_name": client["full_name"],
        "date_of_birth": client["date_of_birth"],
        "medical_flag_count": client["medical_flag_count"],
        "prior_adverse_reactions": client["prior_adverse_reactions"],
        "skin_sensitivity_self": client["skin_sensitivity_self"],
        "skin_sensitivity_observed": client["skin_sensitivity_observed"],
        "risk_score": score,
        "risk_band": band,
        "medical_cleared": client["medical_cleared"],
        "no_show_strikes": strikes,
        "client_status": client_status(strikes),
        "created_at": client["created_at"],
        "updated_at": client["updated_at"],
        "version": client["version"],
    }


def serialize_consent(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "client_id": rec["client_id"],
        "consent_type": rec["consent_type"],
        "age_verified": rec["age_verified"],
        "signed_by_name": rec["signed_by_name"],
    }


def serialize_patch_test(pt):
    return {
        "id": pt["id"],
        "client_id": pt["client_id"],
        "applied_at": pt["applied_at"],
        "read_at": pt["read_at"],
        "status": pt["status"],
        "reaction_grade": pt["reaction_grade"],
        "result": pt["result"],
        "created_at": pt["created_at"],
        "updated_at": pt["updated_at"],
        "version": pt["version"],
    }


def serialize_color_formula(cf):
    return {
        "id": cf["id"],
        "studio_id": cf["studio_id"],
        "name": cf["name"],
        "procedure_type": cf["procedure_type"],
        "pigment_count": cf["pigment_count"],
        "created_at": cf["created_at"],
        "updated_at": cf["updated_at"],
        "version": cf["version"],
    }


# ----------------------------------------------------------------------------
# Appointment derived money fields
# ----------------------------------------------------------------------------
def appointment_deposit_paid(appointment_id):
    """sum(CHARGE) - sum(REFUND); FORFEIT does not reduce deposit_paid_cents."""
    total = 0
    for t in db.deposit_transactions.values():
        if t.get("appointment_id") != appointment_id:
            continue
        if t["txn_type"] == "CHARGE":
            total += t["amount_cents"]
        elif t["txn_type"] == "REFUND":
            total -= t["amount_cents"]
    return total


def appointment_balance_due(appt, deposit_paid):
    if appt["payment_status"] == "PAID_IN_FULL":
        return 0
    # AWAITING_DEPOSIT, DEPOSIT_PAID, BALANCE_DUE
    if appt["payment_status"] == "REFUNDED":
        # not specified to compute; keep canonical stored when present
        return appt["session_price_cents"] - deposit_paid
    return appt["session_price_cents"] - deposit_paid


def serialize_appointment(appt):
    deposit_paid = appointment_deposit_paid(appt["id"])
    balance_due = appointment_balance_due(appt, deposit_paid)
    return {
        "id": appt["id"],
        "client_id": appt["client_id"],
        "technician_id": appt["technician_id"],
        "color_formula_id": appt["color_formula_id"],
        "patch_test_id": appt["patch_test_id"],
        "procedure_type": appt["procedure_type"],
        "appointment_kind": appt["appointment_kind"],
        "is_corrective": appt["is_corrective"],
        "scheduled_start": appt["scheduled_start"],
        "lifecycle_status": appt["lifecycle_status"],
        "payment_status": appt["payment_status"],
        "session_price_cents": appt["session_price_cents"],
        "deposit_required_cents": appt["deposit_required_cents"],
        "deposit_paid_cents": deposit_paid,
        "balance_due_cents": balance_due,
        "kit_consumed": appt["kit_consumed"],
        "healing_outcome": appt["healing_outcome"],
        "completed_at": appt["completed_at"],
        "parent_appointment_id": appt["parent_appointment_id"],
        "package_order_id": appt["package_order_id"],
        "created_at": appt["created_at"],
        "updated_at": appt["updated_at"],
        "version": appt["version"],
    }


def package_remaining_sessions(pkg):
    """included_sessions minus count of TOUCH_UP appointments referencing this
    package not in CANCELLED/VOIDED."""
    drawn = sum(
        1 for a in db.appointments.values()
        if a.get("package_order_id") == pkg["id"]
        and a.get("appointment_kind") == "TOUCH_UP"
        and a.get("lifecycle_status") not in ("CANCELLED", "VOIDED")
    )
    return pkg["included_sessions"] - drawn


def serialize_package(pkg):
    return {
        "id": pkg["id"],
        "client_id": pkg["client_id"],
        "source_appointment_id": pkg["source_appointment_id"],
        "included_sessions": pkg["included_sessions"],
        "remaining_sessions": package_remaining_sessions(pkg),
        "pricing_mode": pkg["pricing_mode"],
        "package_price_cents": pkg["package_price_cents"],
        "status": pkg["status"],
        "created_at": pkg["created_at"],
        "updated_at": pkg["updated_at"],
        "version": pkg["version"],
    }


def serialize_deposit_txn(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "appointment_id": t["appointment_id"],
        "txn_type": t["txn_type"],
        "amount_cents": t["amount_cents"],
    }


def serialize_healing_log(h):
    return {
        "id": h["id"],
        "created_at": h["created_at"],
        "appointment_id": h["appointment_id"],
        "day_offset": h["day_offset"],
        "outcome_flag": h["outcome_flag"],
        "notes": h["notes"],
    }


def serialize_redo_request(r):
    return {
        "id": r["id"],
        "appointment_id": r["appointment_id"],
        "reason": r["reason"],
        "status": r["status"],
        "redo_appointment_id": r["redo_appointment_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
