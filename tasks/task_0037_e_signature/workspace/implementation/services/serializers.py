"""Serializers convert in-memory dict rows to API JSON responses.

Field order tries to match the PRD-described shape.
"""

from clock import iso


def serialize_template(t: dict) -> dict:
    return {
        "id": t["id"],
        "name": t["name"],
        "category": t["category"],
        "owner_org_id": t["owner_org_id"],
        "permission_scope": t["permission_scope"],
        "latest_version_number": t["latest_version_number"],
        "published_version_number": t["published_version_number"],
        "status": t["status"],
        "version": t["version"],
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
    }


def serialize_template_version(v: dict) -> dict:
    return {
        "id": v["id"],
        "template_id": v["template_id"],
        "version_number": v["version_number"],
        "document_blob_sha256": v["document_blob_sha256"],
        "page_count": v["page_count"],
        "variable_fields": v["variable_fields"],
        "signature_positions": v["signature_positions"],
        "status": v["status"],
        "version": v["version"],
        "created_at": iso(v["created_at"]),
        "updated_at": iso(v["updated_at"]),
    }


def serialize_contract(c: dict) -> dict:
    return {
        "id": c["id"],
        "template_version_id": c["template_version_id"],
        "initiator_user_id": c["initiator_user_id"],
        "initiator_org_id": c["initiator_org_id"],
        "title": c["title"],
        "variable_values": c["variable_values"],
        "status": c["status"],
        "expires_at": iso(c["expires_at"]),
        "activated_at": iso(c.get("activated_at")),
        "completed_at": iso(c.get("completed_at")),
        "voided_at": iso(c.get("voided_at")),
        "void_reason": c.get("void_reason"),
        "reinitiated_from_contract_id": c.get("reinitiated_from_contract_id"),
        "document_fingerprint_sha256": c.get("document_fingerprint_sha256"),
        "signing_progress_percent": c.get("signing_progress_percent", 0.00),
        "evidence_strength_score": c.get("evidence_strength_score", 0.00),
        "evidence_tier": c.get("evidence_tier", "BRONZE"),
        "version": c["version"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
    }


def serialize_signing_step(s: dict) -> dict:
    return {
        "id": s["id"],
        "contract_id": s["contract_id"],
        "step_index": s["step_index"],
        "mode": s["mode"],
        "branch_condition": s.get("branch_condition"),
        "status": s["status"],
        "activated_at": iso(s.get("activated_at")),
        "completed_at": iso(s.get("completed_at")),
        "version": s["version"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
    }


def serialize_signing_party(p: dict) -> dict:
    return {
        "id": p["id"],
        "signing_step_id": p["signing_step_id"],
        "contract_id": p["contract_id"],
        "role_key": p["role_key"],
        "signer_type": p["signer_type"],
        "signer_user_id": p["signer_user_id"],
        "signer_org_id": p.get("signer_org_id"),
        "delegation_authorization_id": p.get("delegation_authorization_id"),
        "required_auth_factors": p["required_auth_factors"],
        "status": p["status"],
        "signed_at": iso(p.get("signed_at")),
        "timestamp_token_id": p.get("timestamp_token_id"),
        "identity_verification_id": p.get("identity_verification_id"),
        "version": p["version"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
    }


def serialize_identity_verification(iv: dict) -> dict:
    return {
        "id": iv["id"],
        "subject_user_id": iv["subject_user_id"],
        "contract_id": iv.get("contract_id"),
        "signing_party_id": iv.get("signing_party_id"),
        "factors_attempted": iv["factors_attempted"],
        "factors_passed": iv["factors_passed"],
        "real_name_match": iv["real_name_match"],
        "org_binding_verified": iv["org_binding_verified"],
        "identity_strength": iv["identity_strength"],
        "result": iv["result"],
        "archived_at": iso(iv["archived_at"]),
        "created_at": iso(iv["created_at"]),
    }


def serialize_timestamp_token(t: dict) -> dict:
    return {
        "id": t["id"],
        "contract_id": t["contract_id"],
        "signing_party_id": t["signing_party_id"],
        "server_anchor_at": iso(t["server_anchor_at"]),
        "tsa_anchor_at": iso(t["tsa_anchor_at"]),
        "tsa_provider": t["tsa_provider"],
        "tsa_token_value": t["tsa_token_value"],
        "hash_signed": t["hash_signed"],
        "drift_seconds": t["drift_seconds"],
        "verification_status": t["verification_status"],
        "created_at": iso(t["created_at"]),
    }


def serialize_evidence_package(e: dict) -> dict:
    return {
        "id": e["id"],
        "contract_id": e["contract_id"],
        "status": e["status"],
        "package_sha256": e.get("package_sha256"),
        "notary_provider": e["notary_provider"],
        "notary_reference": e.get("notary_reference"),
        "sealed_at": iso(e.get("sealed_at")),
        "exported_at": iso(e.get("exported_at")),
        "version": e["version"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
    }


def serialize_reminder_rule(r: dict) -> dict:
    return {
        "id": r["id"],
        "contract_id": r["contract_id"],
        "interval_hours": r["interval_hours"],
        "channels": r["channels"],
        "escalation_after_misses": r["escalation_after_misses"],
        "enabled": r["enabled"],
        "last_fired_at": iso(r.get("last_fired_at")),
        "misses_count": r["misses_count"],
        "version": r["version"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
    }


def serialize_reminder_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "reminder_rule_id": e["reminder_rule_id"],
        "contract_id": e["contract_id"],
        "fired_at": iso(e["fired_at"]),
        "channels_used": e["channels_used"],
        "escalated": e["escalated"],
        "idempotency_key": e["idempotency_key"],
        "created_at": iso(e["created_at"]),
    }


def serialize_audit_log(a: dict) -> dict:
    return {
        "id": a["id"],
        "contract_id": a.get("contract_id"),
        "template_id": a.get("template_id"),
        "actor_user_id": a["actor_user_id"],
        "actor_role": a["actor_role"],
        "action": a["action"],
        "payload_sha256": a["payload_sha256"],
        "prev_log_sha256": a.get("prev_log_sha256"),
        "occurred_at": iso(a["occurred_at"]),
        "created_at": iso(a["created_at"]),
    }
