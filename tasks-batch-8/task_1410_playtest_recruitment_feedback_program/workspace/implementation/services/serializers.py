"""Public serializers — strip internal bookkeeping keys from stored records."""

_INTERNAL_KEYS = {"_created_sort", "_seq"}

_ENTITY_FIELDS = {
    "participant": ["id", "email", "full_name", "age_years", "region_code",
                    "platform_tags", "verified_platform_tags", "status",
                    "no_show_strikes", "risk_score",
                    "created_at", "updated_at", "version"],
    "moderator": ["id", "display_name", "email", "status",
                  "created_at", "updated_at", "version"],
    "study": ["id", "title", "code", "min_age", "max_age", "allowed_regions",
              "required_platforms", "cohort_capacity", "incentive_budget_cents",
              "status", "enrolled_count", "budget_committed_cents",
              "budget_spent_cents", "created_at", "updated_at", "version"],
    "application": ["id", "study_id", "participant_id", "status",
                    "fit_score_provisional", "fit_score_final",
                    "pinned_nda_agreement_id", "info_request_note",
                    "decision_reason", "created_at", "updated_at", "version"],
    "nda_agreement": ["id", "study_id", "version_label", "body_text", "status",
                      "published_at", "created_at", "updated_at", "version"],
    "nda_signature": ["id", "agreement_id", "participant_id", "study_id",
                      "application_id", "status", "expires_at", "signed_at",
                      "created_at", "updated_at", "version"],
    "build": ["id", "study_id", "build_label", "max_keys", "key_ttl_hours",
              "status", "released_at", "keys_active_count",
              "created_at", "updated_at", "version"],
    "access_key": ["id", "build_id", "participant_id", "key_code", "status",
                   "expires_at", "redeemed_at",
                   "created_at", "updated_at", "version"],
    "lab_station": ["id", "station_code", "location", "equipment_tags", "status",
                    "created_at", "updated_at", "version"],
    "session": ["id", "study_id", "mode", "station_id", "moderator_id",
                "starts_at", "ends_at", "seat_capacity", "seats_taken", "status",
                "created_at", "updated_at", "version"],
    "booking": ["id", "session_id", "participant_id", "status",
                "no_show_recorded_at", "created_at", "updated_at", "version"],
    "instrument": ["id", "study_id", "title", "questions", "pass_threshold",
                   "status", "created_at", "updated_at", "version"],
    "response": ["id", "instrument_id", "session_id", "participant_id",
                 "answers", "weighted_score", "score_pct", "passed", "status",
                 "submitted_at", "created_at", "updated_at", "version"],
    "ticket": ["id", "study_id", "session_id", "survey_response_id", "title",
               "severity", "reach_count", "reproducibility_pct",
               "priority_score", "priority_tier", "backlog_target", "status",
               "created_at", "updated_at", "version"],
    "payout": ["id", "study_id", "participant_id", "amount_provisional_cents",
               "amount_final_cents", "status", "created_by_user_id",
               "approved_by_user_id", "issued_by_user_id", "rejection_reason",
               "created_at", "updated_at", "version"],
    "breach_case": ["id", "participant_id", "study_id", "evidence_summary",
                    "severity", "reported_by_user_id", "reported_by_role",
                    "adjudicated_by_user_id", "sanction_type", "sanction_note",
                    "status", "created_at", "updated_at", "version"],
    # Append-only: id + created_at only, no updated_at / version
    "exposure_record": ["id", "participant_id", "build_id", "study_id",
                        "event_type", "recorded_at", "created_at"],
}


def public(rec, kind):
    fields = _ENTITY_FIELDS[kind]
    return {k: rec.get(k) for k in fields if k in rec or k in fields}
