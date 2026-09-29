"""Per-entity serialisers.

Field lists follow SCAFFOLD 1.1 exactly.  Twelve of the thirteen resources
carry id/created_at/updated_at/version; CalibrationSubmission carries only
id/created_at (PRD 2.4).
"""

COMMON = ("id", "created_at", "updated_at", "version")
IMMUTABLE = ("id", "created_at")

FIELDS = {
    "forms": ("name", "version_label", "status", "min_compliance_item_score",
              "auto_fail_policy", "behavior_weight_total",
              "compliance_behavior_count", "guidance_version", "activated_at",
              "retired_at"),
    "behaviors": ("form_id", "code", "label", "weight_pct",
                  "compliance_critical", "auto_fail_on_violation", "max_points",
                  "allows_not_applicable", "guidance_text", "guidance_version"),
    "agents": ("external_ref", "full_name", "team_code", "hire_date",
               "quality_index_rolling", "quality_index_period",
               "open_compliance_findings", "consecutive_passing_evaluations",
               "coaching_state", "recognition_points"),
    "evaluators": ("full_name", "max_open_assignments", "calibration_status",
                   "last_deviation_pct", "open_assignment_count"),
    "interactions": ("agent_id", "channel", "started_at", "ended_at",
                     "duration_seconds", "required_disclosures",
                     "captured_disclosures", "recording_consent_status",
                     "customer_flagged", "csat_score",
                     "repeat_contact_within_72h", "compliance_hold",
                     "sampled_count"),
    "scans": ("interaction_id", "silence_pct", "sentiment_delta",
              "flagged_categories", "risk_score", "priority_tier", "status"),
    "plans": ("form_id", "period_start", "period_end",
              "per_agent_target_volume", "source_mix", "status",
              "pinned_form_guidance_version", "selections_count",
              "excluded_count", "targeted_reserved_count",
              "targeted_reserve_by_agent", "agent_volume_attainment"),
    "selections": ("plan_id", "interaction_id", "agent_id",
                   "assigned_evaluator_id", "source", "status",
                   "review_window_start", "review_window_end",
                   "exclusion_reason"),
    "evaluations": ("selection_id", "evaluator_id", "form_id", "agent_id",
                    "pinned_guidance_version", "item_scores", "weighted_score",
                    "raw_weighted_score", "adjusted_weighted_score",
                    "auto_fail_triggered", "compliance_result",
                    "review_status", "feedback_status", "submitted_at",
                    "feedback_delivered_at", "agreement"),
    "sessions": ("form_id", "interaction_id", "scheduled_start",
                 "scheduled_end", "benchmark_item_scores",
                 "benchmark_weighted_score", "status", "participant_count",
                 "variance_pct", "mean_abs_deviation",
                 "guidance_updates_applied"),
    "submissions": ("session_id", "evaluator_id", "item_scores",
                    "weighted_score", "deviation_pct", "alignment"),
    "disputes": ("evaluation_id", "agent_id", "reviewer_evaluator_id",
                 "disputed_behavior_codes", "rationale", "adjusted_item_scores",
                 "outcome_note", "status", "round_count"),
    "coaching_plans": ("agent_id", "source_evaluation_id",
                       "assigned_supervisor_id", "target_score", "deficit_pct",
                       "escalation_tier", "required_session_count",
                       "completed_session_count", "due_at", "status",
                       "escalation_note"),
}


def view(row):
    """Public representation of one stored row."""
    kind = row["_kind"]
    header = IMMUTABLE if kind == "submissions" else COMMON
    out = {}
    for key in header:
        out[key] = row.get(key)
    for key in FIELDS[kind]:
        out[key] = row.get(key)
    return out


def views(items):
    return [view(row) for row in items]
