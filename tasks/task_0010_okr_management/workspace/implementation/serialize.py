"""Serialization helpers — strip internal-only fields and shape for response."""

# All entities are stored as dicts with all fields already present.
# Serialization is mostly identity, but we may want to strip internals.
# In this implementation we have no internals beyond stored fields, so identity copy is fine.


def s_department(d):
    return {k: d[k] for k in ("id", "code", "name", "parent_department_id",
                              "created_at", "updated_at", "version")}


def s_user(u):
    return {k: u[k] for k in ("id", "email", "full_name", "department_id",
                              "manager_id", "role_type", "status",
                              "created_at", "updated_at", "version")}


def s_cycle(c):
    return {k: c[k] for k in ("id", "cycle_code", "year", "quarter",
                              "start_date", "end_date", "status",
                              "completion_rate",
                              "created_at", "updated_at", "version")}


def s_objective(o):
    keys = ("id", "cycle_id", "parent_objective_id", "level", "department_id",
            "owner_user_id", "title", "description", "weight", "confidential",
            "status", "progress", "final_score", "stale_warning_count",
            "kr_count", "child_count",
            "created_at", "updated_at", "version")
    return {k: o.get(k) for k in keys}


def s_kr(k):
    keys = ("id", "objective_id", "title", "measurement_type",
            "start_value", "target_value", "current_value",
            "milestones", "weight", "score", "status",
            "last_update_at", "stale",
            "created_at", "updated_at", "version")
    return {kk: k.get(kk) for kk in keys}


def s_progress(p):
    keys = ("id", "key_result_id", "update_type", "new_value",
            "milestone_index", "milestone_completed", "comment",
            "actor_user_id", "score_at_update", "created_at")
    return {k: p.get(k) for k in keys}


def s_link(l):
    keys = ("id", "upstream_objective_id", "downstream_objective_id",
            "dependency_type", "declared_by_user_id", "status",
            "accepted_at", "rejection_reason",
            "forward_impact_score", "backward_impact_score",
            "created_at", "updated_at", "version")
    return {k: l.get(k) for k in keys}


def s_co_ownership(c):
    keys = ("id", "objective_id", "co_owner_user_id", "contribution_weight",
            "status", "created_at", "updated_at", "version")
    return {k: c.get(k) for k in keys}


def s_review(r):
    keys = ("id", "objective_id", "cycle_id", "status",
            "self_score", "self_submitted_at",
            "manager_score", "manager_submitted_at",
            "calibration_score", "calibration_adjusted_at",
            "final_score", "revision_count", "locked_at",
            "created_at", "updated_at", "version")
    return {k: r.get(k) for k in keys}


def s_grant(g):
    keys = ("id", "objective_id", "user_id", "granted_by_user_id",
            "status", "created_at", "updated_at", "version")
    return {k: g.get(k) for k in keys}


def s_audit(a):
    keys = ("id", "entity_type", "entity_id", "action",
            "actor_user_id", "actor_role",
            "before_value", "after_value", "api_request_id", "created_at")
    return {k: a.get(k) for k in keys}


def s_event(e):
    keys = ("id", "source_system", "external_event_id", "event_type",
            "payload", "received_at", "processing_status", "processed_at",
            "side_effect_summary", "created_at")
    return {k: e.get(k) for k in keys}
