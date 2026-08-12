"""Entity -> API dict serializers. Internal helper fields ( *_dt ) are hidden."""


def _strip_internal(row, fields):
    out = {}
    for f in fields:
        if f in row and not f.endswith("_dt"):
            out[f] = row[f]
    return out


RECORD_FIELDS = ["id", "full_name", "primary_email", "class_year", "degree_code",
                 "status", "engagement_score", "engagement_tier", "giving_propensity",
                 "lifetime_giving_cents", "lost_since", "hard_bounce_flag",
                 "created_at", "updated_at", "version"]

CASE_FIELDS = ["id", "alumni_id", "lead_source", "lead_detail", "lead_confidence",
               "status", "reopened_count", "resolved_at",
               "created_at", "updated_at", "version"]

EVENT_FIELDS = ["id", "class_year", "title", "event_date", "milestone_year", "status",
                "posture", "committee_count", "committee_quorum_required",
                "total_revenue_cents", "created_at", "updated_at", "version"]

COMMITTEE_FIELDS = ["id", "event_id", "name", "chair_membership_id", "locked",
                    "created_at", "updated_at", "version"]

MEMBERSHIP_FIELDS = ["id", "committee_id", "alumni_id", "role", "status",
                     "invited_at", "ended_reason", "created_at", "updated_at", "version"]

TIER_FIELDS = ["id", "event_id", "name", "base_price_cents", "capacity", "sold_count",
               "sales_start", "sales_end", "early_bird_discount_pct",
               "created_at", "updated_at", "version"]

REGISTRATION_FIELDS = ["id", "event_id", "tier_id", "alumni_id", "payment_status",
                       "attendance_status", "quoted_price_cents", "final_price_cents",
                       "cancelled_reason", "created_at", "updated_at", "version"]

GROUP_FIELDS = ["id", "name", "kind", "status", "annual_budget_cents",
                "budget_committed_cents", "budget_spent_cents", "budget_remaining_cents",
                "created_at", "updated_at", "version"]

PROGRAM_FIELDS = ["id", "group_id", "title", "venue_slot_start", "venue_slot_end",
                  "budget_allocated_cents", "actual_spend_cents", "status", "leader_id",
                  "created_at", "updated_at", "version"]

PREFERENCE_FIELDS = ["id", "alumni_id", "channel", "opt_in", "suppressed",
                     "suppression_reason", "created_at", "updated_at", "version"]

CAMPAIGN_FIELDS = ["id", "event_id", "name", "goal_cents", "matching_multiplier_bps",
                   "pledged_total_cents", "fulfilled_total_cents",
                   "matched_credit_cents", "status",
                   "created_at", "updated_at", "version"]

PLEDGE_FIELDS = ["id", "campaign_id", "alumni_id", "amount_cents", "pledge_date",
                 "matched_credit_cents", "status",
                 "created_at", "updated_at", "version"]

PUBLICATION_FIELDS = ["id", "event_id", "title", "class_notes_body", "review_round",
                      "status", "created_at", "updated_at", "version"]


def serialize(row, fields):
    return _strip_internal(row, fields)
