"""Entity serializers: explicit field lists in scaffold order."""

COMMON = ("created_at", "updated_at", "version")

FIELDS = {
    "parties": ("id", "legal_name", "party_type", "state_code", "licence_number"),
    "laboratories": ("id", "lab_name", "certification_code", "concurrent_capacity"),
    "sites": ("id", "owner_party_id", "site_name", "county_code", "acreage",
              "intended_reuse", "institutional_control_committed",
              "planned_acquisition_date", "acquisition_status", "acquisition_date",
              "delineation_status", "cleanup_posture", "impaired_control_count"),
    "assessment_phases": ("id", "site_id", "consultant_party_id",
                          "supersedes_phase_id", "phase_type", "field_start_date",
                          "field_end_date", "aai_report_date",
                          "delineation_confidence", "delineation_complete",
                          "status", "review_round", "findings_count",
                          "max_exceedance_factor", "submitted_at",
                          "reviewed_by_user_id", "review_comment"),
    "contaminant_findings": ("id", "assessment_phase_id", "contaminant_code",
                             "media", "sample_location_code",
                             "max_concentration_ugl", "screening_level_ugl",
                             "delineated", "exceedance_factor"),
    "cleanup_goals": ("id", "site_id", "contaminant_code", "media",
                      "screening_level_ugl", "basis", "control_credit_type",
                      "contaminant_count_in_media", "goal_ugl",
                      "cumulative_cap_applied", "attainment_status",
                      "compliant_streak"),
    "liability_protections": ("id", "site_id", "inquiry_state", "obligation_state",
                              "bfpp_status", "aai_phase_id", "aai_report_date",
                              "aai_expires_on", "obligations_total_weight",
                              "current_weight", "satisfied_weight",
                              "at_risk_weight", "lapsed_weight", "compliance_pct"),
    "continuing_obligations": ("id", "liability_protection_id",
                               "obligation_category", "description", "due_date",
                               "recurrence_days", "imposed_by_user_id", "status",
                               "certified_at", "certification_count",
                               "prior_due_date"),
    "vcp_enrollments": ("id", "site_id", "program_track", "applicant_statement",
                        "status", "enrolled_on", "eligibility_decided_by_user_id",
                        "completion_requested_at", "reverted_completion_count"),
    "remedial_action_plans": ("id", "vcp_enrollment_id", "site_id",
                              "remedy_narrative", "basis_assessment_phase_id",
                              "years_to_construction_start", "cost_lines",
                              "direct_cost_cents", "escalation_cents",
                              "contingency_pct", "contingency_cents",
                              "oversight_cents", "total_estimate_cents",
                              "total_funding_need_cents", "status",
                              "technical_review_state", "public_comment_state",
                              "public_comment_count", "revision_round",
                              "pinned_cleanup_goal_versions",
                              "approved_by_user_id", "approved_at"),
    "cost_cap_policies": ("id", "remedial_action_plan_id", "insurer_party_id",
                          "policy_reference", "term_years",
                          "underwriting_estimate_cents", "attachment_point_cents",
                          "buffer_layer_cents", "limit_cents", "rate_applied",
                          "premium_cents", "status", "bound_at"),
    "site_controls": ("id", "site_id", "remedial_action_plan_id", "control_type",
                      "control_class", "sub_area_code", "coverage_from",
                      "coverage_to", "inspection_interval_days", "status",
                      "last_certified_on", "next_certification_due_on",
                      "impaired_since", "impairment_count"),
    "funding_awards": ("id", "site_id", "program_code", "funding_kind",
                       "program_priority", "max_award_cents", "max_share_pct",
                       "match_requirement_pct", "eligible_cost_categories",
                       "eligibility_documents", "status", "decided_by_user_id",
                       "allocated_cents"),
    "nfa_letters": ("id", "site_id", "vcp_enrollment_id", "requested_scope",
                    "status", "issued_on", "issued_by_user_id",
                    "controls_certified_count", "accepted_by_lender_user_id",
                    "lender_reference", "revocation_reason", "reissue_count"),
    "monitoring_events": ("id", "site_id", "laboratory_id", "cleanup_goal_id",
                          "site_control_id", "event_type", "monitoring_period_code",
                          "sample_date", "window_start", "window_end", "status",
                          "result_value_ugl", "result_status", "control_condition"),
}


def serializer(collection):
    fields = FIELDS[collection]
    include_common = collection != "contaminant_findings"

    def dump(row):
        out = {}
        for name in fields:
            out[name] = row.get(name)
        if include_common:
            for name in COMMON:
                out[name] = row.get(name)
        else:
            out["created_at"] = row.get("created_at")
        return out

    return dump


dump_party = serializer("parties")
dump_laboratory = serializer("laboratories")
dump_site = serializer("sites")
dump_phase = serializer("assessment_phases")
dump_finding = serializer("contaminant_findings")
dump_goal = serializer("cleanup_goals")
dump_protection = serializer("liability_protections")
dump_obligation = serializer("continuing_obligations")
dump_enrollment = serializer("vcp_enrollments")
dump_plan = serializer("remedial_action_plans")
dump_policy = serializer("cost_cap_policies")
dump_control = serializer("site_controls")
dump_award = serializer("funding_awards")
dump_letter = serializer("nfa_letters")
dump_event = serializer("monitoring_events")
