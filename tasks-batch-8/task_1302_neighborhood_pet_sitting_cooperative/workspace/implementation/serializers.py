"""Entity serializers — exact public field sets per the entity table.
Internal bookkeeping fields (underscore-prefixed) are never serialized."""

from util import fmt_dt, num


def member_view(m):
    return {
        "id": m["id"],
        "display_name": m["display_name"],
        "email": m["email"],
        "address_block": m["address_block"],
        "phone": m["phone"],
        "vetting_status": m["vetting_status"],
        "mediator_flag": m["mediator_flag"],
        "credit_balance_hours": num(m["credit_balance_hours"]),
        "provisional_credit_hours": num(m["provisional_credit_hours"]),
        "reliability_score": m["reliability_score"],
        "suspension_reason": m["suspension_reason"],
        "removal_reason": m["removal_reason"],
        "accepted_liability_at": fmt_dt(m["accepted_liability_at"]),
        "co_op_joined_at": fmt_dt(m["co_op_joined_at"]),
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def reference_view(r):
    return {
        "id": r["id"],
        "subject_member_id": r["subject_member_id"],
        "referee_member_id": r["referee_member_id"],
        "relationship_years": r["relationship_years"],
        "attestation_text": r["attestation_text"],
        "reciprocal_reference_id": r["reciprocal_reference_id"],
        "status": r["status"],
        "decided_at": fmt_dt(r["decided_at"]),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def pet_view(p):
    return {
        "id": p["id"],
        "owner_member_id": p["owner_member_id"],
        "pet_name": p["pet_name"],
        "species": p["species"],
        "routine_notes": p["routine_notes"],
        "medical_notes": p["medical_notes"],
        "emergency_vet_name": p["emergency_vet_name"],
        "emergency_vet_phone": p["emergency_vet_phone"],
        "emergency_vet_address": p["emergency_vet_address"],
        "liability_waiver_accepted": p["liability_waiver_accepted"],
        "active": p["active"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def window_view(w):
    return {
        "id": w["id"],
        "name": w["name"],
        "window_start": fmt_dt(w["window_start"]),
        "window_end": fmt_dt(w["window_end"]),
        "demand_multiplier": num(w["demand_multiplier"]),
        "enabled": w["enabled"],
        "created_at": fmt_dt(w["created_at"]),
        "updated_at": fmt_dt(w["updated_at"]),
        "version": w["version"],
    }


def request_view(r):
    return {
        "id": r["id"],
        "owner_member_id": r["owner_member_id"],
        "pet_profile_id": r["pet_profile_id"],
        "start_at": fmt_dt(r["start_at"]),
        "end_at": fmt_dt(r["end_at"]),
        "instructions": r["instructions"],
        "credit_hours_offered": num(r["credit_hours_offered"]),
        "status": r["status"],
        "cancelled_reason": r["cancelled_reason"],
        "expires_at": fmt_dt(r["expires_at"]),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def claim_view(c):
    return {
        "id": c["id"],
        "sitting_request_id": c["sitting_request_id"],
        "claimer_member_id": c["claimer_member_id"],
        "message": c["message"],
        "status": c["status"],
        "decided_at": fmt_dt(c["decided_at"]),
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def assignment_view(a):
    return {
        "id": a["id"],
        "sitting_request_id": a["sitting_request_id"],
        "owner_member_id": a["owner_member_id"],
        "sitter_member_id": a["sitter_member_id"],
        "scheduled_start_at": fmt_dt(a["scheduled_start_at"]),
        "scheduled_end_at": fmt_dt(a["scheduled_end_at"]),
        "actual_start_at": fmt_dt(a["actual_start_at"]),
        "actual_end_at": fmt_dt(a["actual_end_at"]),
        "credit_hours_settled": (
            num(a["credit_hours_settled"])
            if a["credit_hours_settled"] is not None
            else None
        ),
        "status": a["status"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def handoff_view(h, reveal_code=True):
    return {
        "id": h["id"],
        "sitting_assignment_id": h["sitting_assignment_id"],
        "handoff_method": h["handoff_method"],
        "access_code_ciphertext": (
            h["access_code_ciphertext"] if reveal_code else None
        ),
        "handed_off_at": fmt_dt(h["handed_off_at"]),
        "returned_at": fmt_dt(h["returned_at"]),
        "status": h["status"],
        "created_at": fmt_dt(h["created_at"]),
        "updated_at": fmt_dt(h["updated_at"]),
        "version": h["version"],
    }


def entry_view(e):
    return {
        "id": e["id"],
        "sitting_assignment_id": e["sitting_assignment_id"],
        "actor_member_id": e["actor_member_id"],
        "event_type": e["event_type"],
        "occurred_at": fmt_dt(e["occurred_at"]),
        "notes": e["notes"],
        "created_at": fmt_dt(e["created_at"]),
    }


def incident_view(i):
    return {
        "id": i["id"],
        "sitting_assignment_id": i["sitting_assignment_id"],
        "reporter_member_id": i["reporter_member_id"],
        "severity": i["severity"],
        "description": i["description"],
        "vet_involved": i["vet_involved"],
        "at_fault_member_id": i["at_fault_member_id"],
        "status": i["status"],
        "created_at": fmt_dt(i["created_at"]),
        "updated_at": fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def dispute_view(d):
    return {
        "id": d["id"],
        "initiator_member_id": d["initiator_member_id"],
        "respondent_member_id": d["respondent_member_id"],
        "sitting_assignment_id": d["sitting_assignment_id"],
        "dispute_type": d["dispute_type"],
        "statement": d["statement"],
        "mediator_member_id": d["mediator_member_id"],
        "status": d["status"],
        "resolution_notes": d["resolution_notes"],
        "created_at": fmt_dt(d["created_at"]),
        "updated_at": fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def ledger_view(entry):
    return {
        "id": entry["id"],
        "member_id": entry["member_id"],
        "entry_type": entry["entry_type"],
        "delta_hours": num(entry["delta_hours"]),
        "sitting_assignment_id": entry["sitting_assignment_id"],
        "dispute_id": entry["dispute_id"],
        "memo": entry["memo"],
        "created_at": fmt_dt(entry["created_at"]),
    }
