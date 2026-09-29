"""Resource serializers — exact field sets per entity (SCAFFOLD 1.1)."""

COMMON = ("created_at", "updated_at", "version")

OUTING_FIELDS = (
    "id", "name", "beneficiary_name", "format", "start_format", "scheduled_date",
    "rain_date", "wave_a_start", "wave_a_end", "wave_b_start", "wave_b_end",
    "field_capacity_teams", "prize_pool_cents", "play_status", "finance_status",
    "reopen_count", "postponed_from_date", "confirmed_player_slots",
    "checked_in_player_count", "waitlisted_registration_count",
    "reserved_asset_slot_count", "gross_revenue_cents", "refunded_cents",
    "course_charge_cents", "fnb_shortfall_cents", "insurance_cost_cents",
    "prize_cost_cents", "fulfillment_credit_cents", "direct_costs_cents",
    "net_proceeds_before_fee_cents", "admin_fee_pct", "admin_fee_cents",
    "net_proceeds_cents", "unclaimed_prize_cents",
    "receipted_deductible_total_cents", "proceeds_variant",
    "beneficiary_remittance_cents", "remittance_reference",
) + COMMON

CONTRACT_FIELDS = (
    "id", "outing_id", "course_name", "rate_per_player_cents",
    "guaranteed_player_count", "fnb_minimum_cents", "fnb_per_player_cents",
    "course_rating", "slope_rating", "par", "tee_interval_minutes",
    "cart_allowance_count", "rain_date_terms", "rain_date_credit_pct",
    "cancellation_notice_days", "status", "signed_at", "amendment_count",
    "rain_credit_cents", "settled_charge_cents",
) + COMMON

TIER_FIELDS = (
    "id", "outing_id", "code", "kind", "price_cents", "player_slots",
    "gsv_cents", "inventory_cap", "entitled_asset_type", "entitled_asset_count",
    "sold_count",
) + COMMON

REGISTRATION_FIELDS = (
    "id", "outing_id", "package_tier_id", "buyer_name", "buyer_email",
    "player_count", "status", "amount_paid_cents", "amount_refunded_cents",
    "late_cancel_fee_cents", "fulfillment_credit_cents",
    "entitled_asset_balance", "confirmed_at", "amendment_count",
    "recorded_by_user_id", "receipt_issued",
) + COMMON

PLAYER_FIELDS = (
    "id", "registration_id", "team_id", "full_name", "handicap_index",
    "amateur_status", "handicap_index_at_confirm", "effective_handicap_index",
    "course_handicap", "checked_in",
) + COMMON

TEAM_FIELDS = (
    "id", "outing_id", "team_name", "player_count", "team_playing_handicap",
    "handicap_variant", "gross_score", "gross_back_9", "gross_back_6",
    "gross_back_3", "gross_hole_18", "net_score", "net_back_9", "net_back_6",
    "net_back_3", "net_hole_18", "rank_position", "prize_eligible",
    "prize_award_cents", "score_posted_at", "wave", "starting_hole", "tee_time",
    "cart_number", "slot_occupancy_start", "slot_occupancy_end",
    "tee_assignment_count",
) + COMMON

ASSET_FIELDS = (
    "id", "outing_id", "asset_type", "label", "hole_number", "capacity",
    "exclusive", "list_price_cents", "fulfillment_due_at", "reserved_count",
    "committed_count", "fulfilled_count", "remaining_capacity", "status",
) + COMMON

ALLOCATION_FIELDS = (
    "id", "registration_id", "sponsorship_asset_id", "source",
    "service_window_start", "service_window_end", "status",
    "upsell_price_cents", "fulfillment_credit_cents", "waived_reason",
    "artwork_approved_by_user_id", "verified_by_user_id", "committed_at",
) + COMMON

CONTEST_FIELDS = (
    "id", "outing_id", "contest_type", "hole_number", "yardage",
    "prize_value_cents", "prize_form", "requires_insurance", "status",
    "insurance_status", "insurance_carrier", "insurance_premium_cents",
    "insurance_coverage_cap_cents", "insurance_min_yardage",
    "insurance_required_witness_count", "insurance_bound_at",
    "winner_player_id", "witness_count", "award_form", "awarded_value_cents",
    "insurance_recovery_cents", "contest_payout_cents", "claim_denial_reason",
) + COMMON

ITEM_FIELDS = (
    "id", "outing_id", "item_type", "description", "fmv_cents", "ask_cents",
    "buyer_registration_id", "bid_cents", "collected_cents", "status",
    "recorded_by_user_id", "sold_at", "void_count",
) + COMMON

RECEIPT_FIELDS = (
    "id", "outing_id", "receipt_kind", "registration_id", "fundraising_item_id",
    "reverses_receipt_id", "payment_cents", "gsv_cents",
    "deductible_amount_cents", "receipt_number", "issued_by_user_id",
    "issued_at", "created_at",
)

FIELDS_BY_KIND = {
    "Outing": OUTING_FIELDS,
    "CourseContract": CONTRACT_FIELDS,
    "PackageTier": TIER_FIELDS,
    "Registration": REGISTRATION_FIELDS,
    "Player": PLAYER_FIELDS,
    "Team": TEAM_FIELDS,
    "SponsorshipAsset": ASSET_FIELDS,
    "SponsorAllocation": ALLOCATION_FIELDS,
    "Contest": CONTEST_FIELDS,
    "FundraisingItem": ITEM_FIELDS,
    "CharitableReceipt": RECEIPT_FIELDS,
}


def dump(row):
    """Project a stored row onto its declared field set."""
    fields = FIELDS_BY_KIND[row["_kind"]]
    return dict((name, row.get(name)) for name in fields)


def proceeds_report(outing):
    body = dump(outing)
    body["outing_id"] = outing["id"]
    return body
