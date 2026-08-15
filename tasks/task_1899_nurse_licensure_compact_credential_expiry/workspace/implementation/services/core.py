"""Entity persistence helpers: creation, mutation stamps, serialization."""

import db
from util import new_uuid, now_iso

# Declared serialized fields per entity (scaffold Table 1.1 + common fields).
# PrivilegeEvaluation is append-only: id + created_at only (no updated_at/version).
FIELDS = {
    "nurses": ["full_name", "email", "primary_state_of_residence", "employment_type",
               "hire_date", "status", "credential_posture", "multistate_privilege_status",
               "practice_scope", "open_encumbrance_count"],
    "licenses": ["nurse_id", "state_code", "license_number", "license_class",
                 "multistate_flag", "issued_on", "expires_on", "status",
                 "created_by_user_id", "verified_by_user_id"],
    "psvs": ["license_id", "channel", "status", "requested_by_user_id",
             "resolved_by_user_id", "verified_on", "valid_through", "discrepancy_note"],
    "certifications": ["nurse_id", "cert_type", "issuing_body", "obtained_on",
                       "expires_on", "status"],
    "disciplines": ["nurse_id", "license_id", "scope", "action_type", "effective_on",
                    "status", "reported_by_user_id", "acknowledged_by_user_id",
                    "adjudicated_by_user_id", "resolution_note"],
    "packets": ["nurse_id", "target_unit_id", "status", "readiness_score",
                "created_by_user_id", "reviewed_by_user_id", "rejection_reason"],
    "packet_items": ["packet_id", "item_type", "critical", "weight", "status",
                     "evidence_ref", "submitted_by_user_id", "source_credential_id"],
    "requirements": ["code", "name", "validity_months", "window_mode", "mandatory",
                     "applies_to"],
    "completions": ["nurse_id", "requirement_id", "completed_on", "expires_on",
                    "status", "source", "session_booking_id"],
    "units": ["name", "required_cert_types", "scheduled_hours_total",
              "active_assignment_count"],
    "shifts": ["nurse_id", "unit_id", "starts_at", "ends_at", "hours", "status",
               "was_clear_at_start", "cancel_reason"],
    "sessions": ["requirement_id", "title", "starts_at", "ends_at", "capacity",
                 "booked_count"],
    "bookings": ["session_id", "nurse_id", "attended", "completion_id"],
    "evaluations": ["nurse_id", "trigger_reason", "resulting_status",
                    "resulting_scope", "home_license_id"],
    "audit_runs": ["window_start", "window_end", "per_unit_sample_size", "status",
                   "sampled_nurse_ids", "point_in_time_rate", "shift_incidence_rate",
                   "projected_deficiency_count", "created_by_user_id"],
    "audit_findings": ["audit_run_id", "nurse_id", "finding_type", "detail", "status"],
}

APPEND_ONLY = {"evaluations"}


def create_entity(store, fields):
    now = now_iso()
    entity = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    entity.update(fields)
    if store in APPEND_ONLY:
        entity.pop("updated_at", None)
        entity.pop("version", None)
    db.STORES[store][entity["id"]] = entity
    return entity


def touch(entity):
    """Refresh updated_at and increment version on every mutation of the row."""
    entity["updated_at"] = now_iso()
    if "version" in entity:
        entity["version"] += 1


def serialize(store, entity):
    out = {"id": entity["id"], "created_at": entity["created_at"]}
    if store not in APPEND_ONLY:
        out["updated_at"] = entity["updated_at"]
        out["version"] = entity["version"]
    for field in FIELDS[store]:
        out[field] = entity.get(field)
    return out


def get_or_404(store, entity_id, error_id, message):
    entity = db.STORES[store].get(entity_id)
    if entity is None:
        from errors import ApiError
        raise ApiError(error_id, message, 404)
    return entity


def all_entities(store):
    """Creation order == insertion order (dict) == _seq order."""
    return list(db.STORES[store].values())
