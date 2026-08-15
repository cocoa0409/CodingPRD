"""Entity serializers (dict -> API representation)."""
from clock import to_iso


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def donor_out(d):
    out = _common(d)
    out["donor_reference_code"] = d["donor_reference_code"]
    out["status"] = d["status"]
    return out


def consent_out(c):
    out = _common(c)
    out.update({
        "donor_id": c["donor_id"],
        "permitted_uses": list(c["permitted_uses"]),
        "excluded_uses": list(c["excluded_uses"]),
        "allow_reidentification": c["allow_reidentification"],
        "effective_from": to_iso(c["effective_from"]),
        "status": c["status"],
        "withdrawal_requested_at": to_iso(c["withdrawal_requested_at"]),
        "grace_deadline": to_iso(c["grace_deadline"]),
        "supersedes_consent_id": c["supersedes_consent_id"],
    })
    return out


def kit_out(k):
    out = _common(k)
    out.update({
        "kit_type": k["kit_type"],
        "donor_id": k["donor_id"],
        "expires_at": to_iso(k["expires_at"]),
        "status": k["status"],
        "distributed_at": to_iso(k["distributed_at"]),
        "returned_at": to_iso(k["returned_at"]),
    })
    return out


def custody_event_out(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "kit_id": e["kit_id"],
        "event_type": e["event_type"],
        "actor_user_id": e["actor_user_id"],
        "location": e["location"],
        "note": e["note"],
    }


def specimen_out(s):
    out = _common(s)
    out.update({
        "donor_id": s["donor_id"],
        "kit_id": s["kit_id"],
        "consent_record_id": s["consent_record_id"],
        "storage_slot_id": s["storage_slot_id"],
        "specimen_type": s["specimen_type"],
        "collected_at": to_iso(s["collected_at"]),
        "initial_volume_ml": s["initial_volume_ml"],
        "residual_volume_ml": s["residual_volume_ml"],
        "committed_volume_book_ml": s["committed_volume_book_ml"],
        "committed_volume_physical_ml": s["committed_volume_physical_ml"],
        "lifecycle_status": s["lifecycle_status"],
        "viability_status": s["viability_status"],
    })
    return out


def aliquot_out(a):
    out = _common(a)
    out.update({
        "specimen_id": a["specimen_id"],
        "storage_slot_id": a["storage_slot_id"],
        "initial_volume_ml": a["initial_volume_ml"],
        "remaining_volume_ml": a["remaining_volume_ml"],
        "status": a["status"],
        "reserved_for_request_id": a["reserved_for_request_id"],
    })
    return out


def storage_unit_out(u):
    out = _common(u)
    out.update({
        "unit_code": u["unit_code"],
        "setpoint_c": u["setpoint_c"],
        "warn_threshold_c": u["warn_threshold_c"],
        "fail_threshold_c": u["fail_threshold_c"],
        "posture": u["posture"],
        "peak_excursion_c": u["peak_excursion_c"],
        "cumulative_degree_minutes": u["cumulative_degree_minutes"],
    })
    return out


def temperature_reading_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "storage_unit_id": r["storage_unit_id"],
        "recorded_at": to_iso(r["recorded_at"]),
        "temp_c": r["temp_c"],
    }


def slot_out(s):
    out = _common(s)
    out.update({
        "storage_unit_id": s["storage_unit_id"],
        "slot_code": s["slot_code"],
        "capacity_ml": s["capacity_ml"],
        "status": s["status"],
    })
    return out


def reservation_out(r):
    out = _common(r)
    out.update({
        "storage_slot_id": r["storage_slot_id"],
        "starts_at": to_iso(r["starts_at"]),
        "ends_at": to_iso(r["ends_at"]),
        "purpose": r["purpose"],
        "status": r["status"],
    })
    return out


def request_out(r):
    out = _common(r)
    out.update({
        "requester_user_id": r["requester_user_id"],
        "title": r["title"],
        "required_uses": list(r["required_uses"]),
        "specimen_type": r["specimen_type"],
        "volume_needed_ml": r["volume_needed_ml"],
        "sharing_agreement_id": r["sharing_agreement_id"],
        "status": r["status"],
        "revision_round": r["revision_round"],
        "votes_for": r["votes_for"],
        "votes_against": r["votes_against"],
        "charged_volume_ml": r["charged_volume_ml"],
        "fulfilled_volume_ml": r["fulfilled_volume_ml"],
        "handling_fee_cents": r["handling_fee_cents"],
        "recall_required": r["recall_required"],
    })
    return out


def vote_out(v):
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "sample_request_id": v["sample_request_id"],
        "reviewer_user_id": v["reviewer_user_id"],
        "decision": v["decision"],
        "rationale": v["rationale"],
        "round": v["round"],
    }


def agreement_out(a):
    out = _common(a)
    out.update({
        "recipient_institution": a["recipient_institution"],
        "scope_uses": list(a["scope_uses"]),
        "total_committed_volume_ml": a["total_committed_volume_ml"],
        "remaining_volume_ml": a["remaining_volume_ml"],
        "reserved_volume_ml": a["reserved_volume_ml"],
        "fulfilled_volume_ml": a["fulfilled_volume_ml"],
        "effective_from": to_iso(a["effective_from"]),
        "effective_to": to_iso(a["effective_to"]),
        "status": a["status"],
    })
    return out


def key_out(k):
    out = _common(k)
    out.update({
        "specimen_id": k["specimen_id"],
        "key_code": k["key_code"],
        "holder_user_id": k["holder_user_id"],
        "status": k["status"],
        "reveal_count": k["reveal_count"],
    })
    return out


def grant_out(g):
    out = _common(g)
    out.update({
        "deidentification_key_id": g["deidentification_key_id"],
        "grantee_user_id": g["grantee_user_id"],
        "starts_at": to_iso(g["starts_at"]),
        "ends_at": to_iso(g["ends_at"]),
        "purpose": g["purpose"],
        "status": g["status"],
    })
    return out


def destruction_order_out(o):
    out = _common(o)
    out.update({
        "specimen_id": o["specimen_id"],
        "consent_record_id": o["consent_record_id"],
        "reason": o["reason"],
        "created_by_user_id": o["created_by_user_id"],
        "confirmed_by_user_id": o["confirmed_by_user_id"],
        "status": o["status"],
        "due_at": to_iso(o["due_at"]),
        "completed_late": o["completed_late"],
    })
    return out
