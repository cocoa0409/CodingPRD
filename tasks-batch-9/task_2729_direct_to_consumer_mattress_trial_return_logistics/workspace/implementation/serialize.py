"""Resource representations."""
from util import iso

DATETIME_FIELDS = frozenset((
    "created_at", "updated_at", "trial_block_until", "delivered_at",
    "break_in_ends_at", "trial_ends_at", "requested_at", "picked_up_at",
    "window_start_at", "window_end_at", "slot_start_at", "slot_end_at",
    "closed_at", "released_at", "voided_at", "reported_at", "submitted_at",
    "resolved_at", "recorded_at",
))

COMMON = ("created_at", "updated_at", "version")

CUSTOMER = ("id", "email", "full_name", "household_hash", "status",
            "lifetime_trial_count", "completed_return_count",
            "abuse_score_rolling", "abuse_score_lifetime", "trial_block_until",
            "signal_count") + COMMON

MATTRESS_MODEL = ("id", "sku", "name", "firmness", "size", "list_price_cents",
                  "break_in_nights", "trial_nights",
                  "indentation_warranty_threshold_mm", "warranty_years",
                  "donation_eligible") + COMMON

PROMOTION_BUNDLE = ("id", "code", "accessory_retail_cents", "percent_off_bps",
                    "gift_card_cents", "unwind_policy",
                    "requires_accessory_return") + COMMON

RETAIL_PARTNER = ("id", "name", "region_code", "commission_bps",
                  "price_match_policy", "attribution_window_days",
                  "status") + COMMON

DISPOSITION_PARTNER = ("id", "name", "partner_type", "region_code",
                       "daily_intake_capacity_units",
                       "accepts_condition_grades", "soil_policy",
                       "priority_rank", "recycle_fee_cents_per_unit",
                       "status") + COMMON

TRIAL_ORDER = ("id", "customer_id", "model_id", "bundle_id",
               "retail_partner_id", "exchanged_from_order_id", "channel",
               "gross_price_cents", "bundle_discount_cents",
               "paid_amount_cents", "fulfillment_status", "trial_status",
               "delivered_at", "break_in_ends_at", "trial_ends_at",
               "nights_slept", "exchange_chain_depth",
               "goodwill_credit_cents", "price_match_credit_cents",
               "refunded_total_cents", "outstanding_refundable_cents",
               "retained_amount_cents") + COMMON

RETURN_CASE = ("id", "order_id", "reason_code", "requested_at",
               "logistics_status", "financial_status", "picked_up_at",
               "nights_used", "condition_grade", "soil_flag",
               "accessory_returned", "disposition",
               "proration_deduction_cents", "bundle_unwind_cents",
               "damage_offset_cents", "provisional_refund_cents",
               "final_refund_cents") + COMMON

PICKUP_ROUTE = ("id", "region_code", "route_date", "window_start_at",
                "window_end_at", "buffer_minutes", "capacity_units",
                "booked_units", "available_units", "status") + COMMON

PICKUP_APPOINTMENT = ("id", "route_id", "return_case_id", "slot_start_at",
                      "slot_end_at", "units", "status", "closed_at") + COMMON

DISPOSITION_ASSIGNMENT = ("id", "return_case_id", "partner_id", "intake_date",
                          "disposition_type", "units", "fee_cents",
                          "fallback_applied", "status") + COMMON

REFUND_AUTHORIZATION = ("id", "return_case_id", "order_id",
                        "supersedes_refund_id", "gross_refundable_cents",
                        "proration_deduction_cents", "bundle_unwind_cents",
                        "damage_offset_cents", "net_refund_cents",
                        "authorized_by_user_id", "released_by_user_id",
                        "released_at", "voided_at", "void_reason",
                        "status") + COMMON

COMFORT_EXCHANGE = ("id", "original_order_id", "target_model_id",
                    "replacement_order_id", "sequence_number",
                    "raw_price_difference_cents", "exchange_fee_cents",
                    "tier_credit_cents", "price_difference_cents",
                    "settlement_direction", "status", "decline_note") + COMMON

QUALITY_CLAIM = ("id", "order_id", "claim_type", "photo_evidence_count",
                 "measurement_method", "measured_indentation_mm",
                 "reported_at", "evidence_round_count", "ownership_years",
                 "coverage_bps", "credit_cents", "resolution", "status",
                 "approved_by_user_id", "settled_by_user_id") + COMMON

ATTRIBUTION_CLAIM = ("id", "partner_id", "order_id", "claim_type",
                     "competitor_price_cents", "evidence_url_count",
                     "submitted_at", "revision_round_count",
                     "commission_cents", "price_match_credit_cents", "status",
                     "resolved_at") + COMMON

# TrialAbuseSignal is the one resource without updated_at / version.
ABUSE_SIGNAL = ("id", "customer_id", "signal_type", "recorded_at", "weight",
                "source_note", "created_at")


def dump(record, fields):
    out = {}
    for name in fields:
        value = record.get(name)
        if name in DATETIME_FIELDS:
            value = iso(value)
        elif isinstance(value, list):
            value = list(value)
        out[name] = value
    return out


def dump_many(records, fields):
    return [dump(r, fields) for r in records]
