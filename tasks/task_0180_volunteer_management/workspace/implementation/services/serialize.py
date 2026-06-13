"""Entity serialization — each entity exposes exactly its scaffold field set
plus the common system fields. Internal bookkeeping keys (prefixed with '_')
are never emitted.
"""

# Per-entity ordered field list (excluding the common system fields). The
# common fields id/created_at[/updated_at/version] are emitted by serialize().
_FIELDS = {
    "organizations": [
        "name", "reliability_suspension_threshold", "no_show_strike_limit",
        "status",
    ],
    "volunteers": [
        "organization_id", "full_name", "email", "status", "bg_check_tier",
        "lifetime_no_show_count", "total_verified_hours", "reliability_score",
        "milestone_tier",
    ],
    "background_checks": [
        "volunteer_id", "requested_tier", "status", "cleared_at", "valid_until",
        "validity_days",
    ],
    "skills": ["organization_id", "code", "label"],
    "volunteer_skills": ["volunteer_id", "skill_id", "proficiency"],
    "waiver_templates": ["organization_id", "code", "revision"],
    "waiver_acceptances": ["volunteer_id", "waiver_template_id", "accepted_revision"],
    "training_modules": ["organization_id", "code", "valid_days"],
    "training_completions": [
        "volunteer_id", "training_module_id", "completed_at", "expires_at",
    ],
    "opportunities": [
        "organization_id", "title", "publication_status", "staffing_status",
        "required_bg_tier", "required_skill_ids", "required_waiver_template_id",
        "required_training_module_id", "is_group_event",
    ],
    "shifts": [
        "opportunity_id", "starts_at", "ends_at", "capacity", "reserved_count",
        "status", "group_reserved_seats",
    ],
    "signups": [
        "shift_id", "volunteer_id", "corporate_group_id", "status",
        "logged_hours", "verified_hours", "provisional_hours",
    ],
    "corporate_groups": [
        "opportunity_id", "sponsor_name", "requested_seats", "target_shift_id",
        "status", "allocated_seat_count",
    ],
}

# Append-only entities carry only id + created_at (PRD §2.4).
_APPEND_ONLY = {"volunteer_skills", "waiver_acceptances", "training_completions"}


def serialize(collection, rec):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    for f in _FIELDS[collection]:
        out[f] = rec.get(f)
    if collection not in _APPEND_ONLY:
        out["updated_at"] = rec.get("updated_at")
        out["version"] = rec.get("version")
    return out


def serialize_list(collection, recs):
    return [serialize(collection, r) for r in recs]
