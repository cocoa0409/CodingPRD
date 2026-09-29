"""Explicit output field ordering for every entity (PRD 2.4 / SCAFFOLD entities)."""

COMMON = ("created_at", "updated_at", "version")

FIELDS = {
    "Licensee": ("id", "legal_name", "contact_email", "home_country_code", "status",
                 "vendor_compliance_certified", "compliance_risk_index",
                 "risk_index_as_of_quarter", "outstanding_recovery_cents",
                 "agreement_count", "suspension_reason") + COMMON,

    "ProductCategory": ("id", "category_code", "display_name", "base_royalty_rate_bps",
                        "tier_schedule", "closeout_rate_bps", "closeout_cap_pct_bps",
                        "closeout_hard_limit_bps", "deduction_cap_pct_bps",
                        "deduction_hard_limit_bps", "exclusivity_allowed",
                        "minimum_guarantee_floor_cents", "advance_floor_bps_of_mg",
                        "mark_usage_class", "central_licensing_default") + COMMON,

    "Club": ("id", "club_code", "market_name", "revenue_share_units", "status",
             "lifetime_distributed_cents") + COMMON,

    "Player": ("id", "full_name", "club_id", "group_licensing_opt_in",
               "individual_grant_category_ids", "status") + COMMON,

    "MarkRight": ("id", "mark_code", "owner_type", "club_id", "player_id", "usage_class",
                  "royalty_share_bps", "status", "status_reason", "withdrawn_at") + COMMON,

    "LicenseAgreement": ("id", "licensee_id", "category_id", "exclusivity_mode",
                         "minimum_guarantee_cents", "required_advance_cents",
                         "advance_paid_cents", "unrecouped_advance_cents",
                         "recouped_advance_cents", "term_start_date", "term_end_date",
                         "central_licensing_flag", "contract_status", "compliance_posture",
                         "posture_as_of_quarter", "cumulative_royalty_cents",
                         "contract_year_start_quarter", "mg_accrued_shortfall_cents",
                         "mg_final_shortfall_cents", "approved_sku_count",
                         "authorized_channel_count", "distribution_ready",
                         "countersigned_by", "suspension_reason",
                         "termination_reason") + COMMON,

    "TerritoryGrant": ("id", "agreement_id", "territory_code", "channel_class",
                       "effective_from", "effective_to", "status",
                       "exclusivity_mode_snapshot") + COMMON,

    "ProductSubmission": ("id", "agreement_id", "product_name", "sku_class", "mark_ids",
                          "retail_price_cents", "sample_required", "status",
                          "revision_round", "review_hold", "defect_codes",
                          "approved_mark_snapshot", "mark_snapshot_stale",
                          "approved_by_user_id", "approved_at", "revocation_reason",
                          "rejection_reason") + COMMON,

    "SampleReview": ("id", "submission_id", "verdict", "sample_round", "defect_codes",
                     "conditions", "reviewer_user_id", "occurrence_quarter", "created_at"),

    "RetailerAuthorization": ("id", "licensee_id", "retailer_name", "channel_class",
                              "sku_classes", "authorized_from", "authorized_to",
                              "closeout_allowed", "status", "suspension_reason",
                              "suspended_at", "approved_by_user_id") + COMMON,

    "RoyaltyReport": ("id", "agreement_id", "period_quarter", "channel_lines", "status",
                      "net_regular_total_cents", "closeout_eligible_total_cents",
                      "applied_tier_rate_bps", "royalty_due_cents",
                      "recoupment_applied_cents", "cash_due_pre_fee_cents", "late_days",
                      "late_filing_interest_cents", "admin_fee_cents",
                      "total_payable_cents", "filed_at", "return_count", "return_reason",
                      "accepted_by_user_id", "accepted_at", "adjusted_royalty_due_cents",
                      "audit_engagement_id", "distribution_run_id") + COMMON,

    "AuditEngagement": ("id", "agreement_id", "scope_quarters", "status",
                        "opened_by_user_id", "opened_quarter", "audited_quarters",
                        "recomputed_royalty_cents", "reported_royalty_cents",
                        "underreported_royalty_cents", "underreport_rate_bps",
                        "cost_shift_applied", "audit_cost_recovery_cents", "interest_cents",
                        "recovery_assessed_cents", "findings_issued_by_user_id",
                        "findings_quarter", "findings_round", "dispute_note",
                        "settlement_basis", "settled_amount_cents",
                        "settled_by_user_id") + COMMON,

    "EnforcementAction": ("id", "venue_type", "venue_reference", "target_name",
                          "suspected_licensee_id", "estimated_units",
                          "estimated_retail_cents", "seized_units", "seizure_authority",
                          "status", "occurrence_quarter", "disposition", "recovered_cents",
                          "dismissal_reason") + COMMON,

    "DistributionRun": ("id", "period_quarter", "league_admin_rate_bps", "status",
                        "projected_pool_cents", "pool_gross_cents", "league_admin_cents",
                        "player_pool_cents", "club_pool_cents", "report_count",
                        "locked_at", "distributed_at") + COMMON,

    "ClubDistribution": ("id", "run_id", "club_id", "club_code",
                         "revenue_share_units_snapshot", "equal_component_cents",
                         "weighted_component_cents", "remainder_cent_applied",
                         "amount_cents", "created_at"),
}


def dump(kind, row):
    fields = FIELDS[kind]
    return {name: row.get(name) for name in fields}


def dump_all(kind, rows):
    return [dump(kind, row) for row in rows]
