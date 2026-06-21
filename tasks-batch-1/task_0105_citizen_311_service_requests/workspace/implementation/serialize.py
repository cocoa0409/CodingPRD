"""Convert internal entity records into API output dicts.

Each entity exposes exactly the fields declared in SCAFFOLD 1.1, plus the
common system fields. Internal-only keys (prefixed with '_') are stripped.
"""

# Full-common-field entities carry id, created_at, updated_at, version.
_COMMON = ["id", "created_at", "updated_at", "version"]
# Append-only audit entities carry only id, created_at.
_AUDIT = ["id", "created_at"]

_FIELDS = {
    "category": _COMMON + [
        "name", "code", "default_priority", "default_department_id",
        "requires_geolocation", "active",
    ],
    "jurisdiction": _COMMON + [
        "name", "min_lat", "max_lat", "min_lng", "max_lng",
        "override_department_id",
    ],
    "department": _COMMON + [
        "name", "open_work_order_count", "backlog_threshold", "congested",
    ],
    "sla_policy": _COMMON + [
        "category_id", "priority", "resolution_sla_hours",
        "escalation_tier1_hours", "escalation_tier2_hours",
    ],
    "citizen": _COMMON + ["email", "full_name", "notify_channel"],
    "agent": _COMMON + ["department_id", "full_name", "is_supervisor"],
    "service_request": _COMMON + [
        "citizen_id", "category_id", "description", "lat", "lng",
        "priority", "requested_priority", "jurisdiction_id", "department_id",
        "cluster_id", "status", "sla_deadline_at", "routed_at", "resolved_at",
        "sla_breached", "reopen_count",
    ],
    "cluster": _COMMON + [
        "category_id", "canonical_request_id", "center_lat", "center_lng",
        "member_count", "status",
    ],
    "work_order": _COMMON + [
        "request_id", "department_id", "assigned_agent_id", "status",
        "completion_note",
    ],
    "escalation": _AUDIT + [
        "request_id", "tier", "reason", "status", "resolved_by_role",
    ],
    "notification": _AUDIT + [
        "request_id", "channel", "from_status", "to_status", "message",
    ],
    "survey": _COMMON + ["request_id", "status", "score", "comment"],
    "window": _COMMON + [
        "window_type", "department_id", "jurisdiction_id", "starts_at",
        "ends_at",
    ],
}


def view(kind, record):
    if record is None:
        return None
    fields = _FIELDS[kind]
    return {f: record.get(f) for f in fields}


def view_list(kind, records):
    return [view(kind, r) for r in records]
