"""Explicit per-entity output projections.

Records carry private bookkeeping keys (a monotonic sequence number, parsed
datetimes, settlement stamps). Serialising through explicit field lists keeps
those out of every response body.
"""

from decimal import Decimal

_COMMON = ("id", "created_at", "updated_at", "version")
_APPEND_ONLY = ("id", "created_at")

FIELDS = {
    "owner": ("display_name", "email", "payout_state_code", "status",
              "owner_penalty_points", "payout_balance_cents", "listed_listing_count"),
    "renter": ("display_name", "email", "date_of_birth", "license_state_code",
               "wallet_credit_cents", "renter_penalty_points", "driving_record_points",
               "driving_record_status", "towing_verified_tier"),
    "listing": ("owner_id", "nickname", "vehicle_class", "requires_towing", "gvwr_lbs",
                "length_ft", "base_nightly_rate_cents", "included_miles_per_night",
                "mileage_overage_rate_cents_per_mile", "included_generator_hours_per_night",
                "generator_overage_rate_cents_per_hour", "min_renter_age",
                "delivery_offered", "delivery_base_fee_cents", "delivery_per_mile_cents",
                "listing_status", "insurance_status", "inspection_photo_zone_count",
                "completed_night_count", "last_reconciled_at", "suspend_reason",
                "decision_note"),
    "vehicle_document": ("listing_id", "doc_type", "zone", "expires_on", "image_ref",
                         "verification_status", "superseded"),
    "renter_qualification": ("renter_id", "check_type", "result", "violation_points",
                             "checked_at", "expires_on"),
    "protection_plan": ("tier", "daily_premium_cents", "premium_pct_of_base_bp",
                        "deductible_cents", "coverage_ceiling_cents", "excluded_causes",
                        "eligible_vehicle_classes"),
    "cancellation_policy": ("tier", "full_refund_hours_before", "partial_refund_pct_bp",
                            "renter_cancel_penalty_points", "owner_cancel_penalty_points",
                            "owner_cancel_fee_bp"),
    "pricing_season": ("season_code", "start_month_day", "end_month_day", "multiplier_bp"),
    "campground": ("name", "state_code", "max_rig_length_ft", "daily_dropoff_capacity",
                   "dropoff_buffer_minutes", "status", "scheduled_assignment_count"),
    "booking": ("listing_id", "renter_id", "protection_plan_id", "cancellation_policy_id",
                "start_date", "end_date", "delivery_option", "declared_miles",
                "declared_generator_hours", "nights", "trip_status", "settlement_status",
                "renter_age_years_at_start", "renter_record_points_snapshot",
                "towing_verified_tier", "base_subtotal_cents", "premium_cents",
                "delivery_fee_cents", "loyalty_tier", "loyalty_discount_cents",
                "service_fee_cents", "estimated_overage_cents", "quoted_total_cents",
                "hold_amount_cents", "final_overage_cents", "trip_total_overage_cents",
                "late_return_fee_cents", "final_total_cents", "balance_due_cents",
                "refund_cents", "info_round_count", "cancel_reason", "reversal_reason"),
    "delivery_assignment": ("booking_id", "campground_id", "window_start", "window_end",
                            "distance_miles", "setup_fee_cents", "delivery_fee_cents",
                            "status", "dropoff_date", "promoted_from_waitlist",
                            "void_reason"),
    "meter_reading": ("booking_id", "reading_type", "odometer_miles", "generator_hours",
                      "recorded_at"),
    "trip_photo": ("booking_id", "phase", "zone", "damage_flagged", "image_ref"),
    "damage_claim": ("booking_id", "cause_code", "damage_zone", "claimed_amount_cents",
                     "description", "status", "comparison_verdict", "pre_photo_count",
                     "post_photo_count", "info_rounds_used", "gross_amount_cents",
                     "renter_charge_cents", "plan_paid_cents", "owner_payout_cents",
                     "override_amount_cents", "override_reason", "info_request_note",
                     "response_note", "withdraw_reason"),
    "ledger_entry": ("booking_id", "party", "entry_type", "amount_cents",
                     "reversal_of_entry_id", "memo"),
}

_VERSIONLESS = ("renter_qualification", "meter_reading", "trip_photo", "ledger_entry")


def _clean(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def dump(kind, record):
    if record is None:
        return None
    keys = (_APPEND_ONLY if kind in _VERSIONLESS else _COMMON) + FIELDS[kind]
    return {key: _clean(record.get(key)) for key in keys}


def dump_all(kind, records):
    return [dump(kind, record) for record in records]
