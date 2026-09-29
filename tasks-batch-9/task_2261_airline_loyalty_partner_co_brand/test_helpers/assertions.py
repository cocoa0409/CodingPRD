"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

RECOGNITION_STATES = ["OPEN", "CLOSING", "LOCKED"]
BREAKAGE_POLICY_MODES = ["HISTORICAL_ATTRITION", "FORWARD_EXPECTATION"]
ISSUER_STATUSES = ["ACTIVE", "SUSPENDED"]
ISSUER_SUSPENSION_REASONS = ["NONE", "CAP_BREACH"]
AGREEMENT_STATUSES = [
    "DRAFT", "ISSUER_REVIEW", "COUNTERED", "RATIFIED", "ACTIVE", "EXPIRED",
    "TERMINATED",
]
FULFILLMENT_STATUSES = ["PENDING", "ISSUED", "REVERSED"]
SETTLEMENT_STATUSES = ["PENDING", "INVOICED", "SETTLED", "WRITTEN_OFF"]
HOME_REGIONS = ["AMER", "EMEA", "APAC"]
ELITE_TIERS = ["BASE", "SILVER", "GOLD", "PLATINUM"]
SECURITY_STATES = ["NORMAL", "WATCH", "FROZEN", "CLOSED"]
STATUS_MATCH_STATES = ["NONE", "TRIAL", "CONFIRMED", "LAPSED"]
QUALIFICATION_STATES = ["ACCUMULATING", "CLOSED", "RESTATED"]
TXN_TYPES = [
    "FLIGHT_EARN", "CARD_SPEND_EARN", "PARTNER_EARN", "REDEEM", "REVERSAL",
    "EXPIRY", "ADJUSTMENT",
]
EARN_CHANNELS = ["FLIGHT", "CARD_SPEND", "PARTNER"]
STACKING_MODES = ["EXCLUSIVE", "ADDITIVE", "MULTIPLICATIVE"]
CAMPAIGN_STATUSES = ["SCHEDULED", "LIVE", "ENDED", "CANCELLED"]
CABINS = ["ECONOMY", "PREMIUM", "BUSINESS", "FIRST"]
CAPACITY_CONTROL_STATES = ["OPEN", "CONSTRAINED", "CLOSED"]
FARE_CLASSES = ["SAVER", "FLEX"]
SURCHARGE_BANDS = ["SURCHARGE_LOW", "SURCHARGE_MID", "SURCHARGE_HIGH"]
BOOKING_STATUSES = ["HELD", "TICKETED", "CANCELLED", "REFUNDED", "EXPIRED"]
RECIPROCITY_MODES = ["FULL", "INBOUND_ONLY", "OUTBOUND_ONLY", "SUSPENDED"]
AWARD_PRICING_MODES = ["FIXED_CHART", "DISTANCE_BAND", "DYNAMIC_PASSTHROUGH"]
CHANGE_TYPES = [
    "EARN_STRUCTURE", "AWARD_PRICING", "ELITE_THRESHOLD", "EXPIRY_POLICY",
]
NOTICE_STATUSES = [
    "DRAFT", "ANNOUNCED", "IN_GRANDFATHER", "EFFECTIVE", "ROLLED_BACK",
]
CASE_TYPES = ["ACCOUNT_TAKEOVER", "MILE_BROKERING", "VELOCITY_ANOMALY"]
FRAUD_CASE_STATUSES = ["OPEN", "INVESTIGATING", "SUBSTANTIATED", "DISMISSED"]

#: Booking states that still hold a seat against the window.
SEAT_HOLDING_BOOKING_STATUSES = ["HELD"]
#: Booking states that have consumed a seat outright.
SEAT_CONFIRMED_BOOKING_STATUSES = ["TICKETED"]


def _assert_system_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert "_" not in data.get("id", "x_x"), f"{label}.id carries no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version is an integer starting at 1"
    )


def _assert_append_only_fields(data: dict, label: str):
    """For the two append-only rows: ``id`` and ``created_at`` only."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert "_" not in data.get("id", "x_x"), f"{label}.id carries no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "version" not in data, f"{label} is append-only and carries no version"
    assert "updated_at" not in data, f"{label} is append-only and is never updated"


def assert_loyalty_program(data: dict):
    _assert_system_fields(data, "LoyaltyProgram")
    assert data["revenue_recognition_state"] in RECOGNITION_STATES
    assert data["breakage_policy_mode"] in BREAKAGE_POLICY_MODES
    assert 0 <= data["saver_share_default_bps"] <= 10000
    assert data["outstanding_miles"] >= 0
    assert data["deferred_revenue_cents"] >= 0
    assert 0 <= data["last_breakage_rate_bps"] <= 10000
    assert data["lifetime_breakage_income_cents"] >= 0
    assert len(data["current_period"]) == 7 and data["current_period"][4] == "-"


def assert_co_brand_issuer(data: dict):
    _assert_system_fields(data, "CoBrandIssuer")
    assert data["status"] in ISSUER_STATUSES
    assert data["suspension_reason"] in ISSUER_SUSPENSION_REASONS
    assert data["annual_mile_purchase_cap_miles"] >= 1
    assert data["aggregate_committed_miles"] >= 0
    assert is_valid_uuid(data["program_id"])


def assert_mile_sale_agreement(data: dict):
    _assert_system_fields(data, "MileSaleAgreement")
    assert data["status"] in AGREEMENT_STATUSES
    assert is_valid_uuid(data["issuer_id"])
    assert data["term_end_date"] > data["term_start_date"]
    assert data["committed_volume_miles"] >= 1
    assert data["negotiation_round"] >= 1
    assert data["drawn_miles"] >= 0
    assert data["prepayment_balance_miles"] >= 0
    assert isinstance(data["tier_schedule"], list) and data["tier_schedule"]
    for entry in data["tier_schedule"]:
        assert entry["threshold_miles"] >= 0
        assert entry["price_per_mile_centicents"] >= 1


def assert_mile_purchase_order(data: dict):
    _assert_system_fields(data, "MilePurchaseOrder")
    assert data["fulfillment_status"] in FULFILLMENT_STATUSES
    assert data["settlement_status"] in SETTLEMENT_STATUSES
    assert is_valid_uuid(data["agreement_id"])
    assert data["order_miles"] >= 1
    assert data["drawn_miles_before"] >= 0
    assert data["provisional_tier_price_centicents"] >= 0
    assert data["gross_amount_cents"] >= 0


def assert_member_account(data: dict):
    _assert_system_fields(data, "MemberAccount")
    assert data["home_region"] in HOME_REGIONS
    assert data["elite_tier"] in ELITE_TIERS
    assert data["security_state"] in SECURITY_STATES
    assert data["status_match_state"] in STATUS_MATCH_STATES
    assert data["qualification_state"] in QUALIFICATION_STATES
    assert data["status_match_tier"] is None or data["status_match_tier"] in ELITE_TIERS
    assert data["awarded_tier_at_close"] is None or (
        data["awarded_tier_at_close"] in ELITE_TIERS
    )
    assert data["mile_balance"] >= 0
    assert data["lifetime_miles"] >= 0
    assert 0 <= data["risk_score"] <= 100
    assert data["qualifying_miles_ytd"] >= 0
    assert data["qualifying_segments_ytd"] >= 0
    assert data["qualifying_spend_cents_ytd"] >= 0
    assert 0 <= data["rollover_carried_in"] <= 40000
    assert 0 <= data["rollover_carried_out"] <= 40000


def assert_mile_transaction(data: dict):
    _assert_append_only_fields(data, "MileTransaction")
    assert data["txn_type"] in TXN_TYPES
    assert is_valid_uuid(data["member_id"])
    assert data["elite_tier_at_earn"] in ELITE_TIERS
    assert data["stacking_mode_applied"] is None or (
        data["stacking_mode_applied"] in STACKING_MODES
    )
    assert data["tier_bonus_miles"] >= 0
    assert data["bonus_miles"] >= 0
    assert data["qualifying_miles_credited"] >= 0
    assert data["promo_multiplier_bps"] >= 0
    assert data["segments"] >= 0
    assert data["qualifying_spend_cents"] >= 0
    assert len(data["posted_period"]) == 7 and data["posted_period"][4] == "-"


def assert_promotion_campaign(data: dict):
    _assert_system_fields(data, "PromotionCampaign")
    assert data["status"] in CAMPAIGN_STATUSES
    assert data["earn_channel"] in EARN_CHANNELS
    assert data["stacking_mode"] in STACKING_MODES
    assert 10000 <= data["multiplier_bps"] <= 50000
    assert data["bonus_cap_miles"] is None or data["bonus_cap_miles"] >= 0
    assert data["accrued_bonus_miles"] >= 0
    assert data["window_end"] > data["window_start"]


def assert_award_inventory_window(data: dict):
    _assert_system_fields(data, "AwardInventoryWindow")
    assert data["cabin"] in CABINS
    assert data["capacity_control_state"] in CAPACITY_CONTROL_STATES
    assert data["authorized_seats"] >= 1
    assert 0 <= data["saver_seat_share_bps"] <= 10000
    assert data["seats_held"] >= 0
    assert data["seats_confirmed"] >= 0
    assert data["saver_seats_consumed"] >= 0
    assert 0 <= data["load_factor_bps"] <= 10000
    assert data["demand_multiplier_bps"] >= 0
    assert data["window_end_date"] >= data["window_start_date"]


def assert_award_booking(data: dict):
    _assert_system_fields(data, "AwardBooking")
    assert data["status"] in BOOKING_STATUSES
    assert data["fare_class"] in FARE_CLASSES
    assert data["surcharge_band"] in SURCHARGE_BANDS
    assert 1 <= data["seats"] <= 9
    assert data["chart_miles_per_seat"] >= 1
    assert data["demand_multiplier_bps_applied"] >= 0
    assert data["partner_uplift_bps_applied"] >= 0
    assert data["elite_discount_bps_applied"] >= 0
    assert data["quoted_miles"] >= 0
    assert data["cash_surcharge_cents"] >= 0
    assert data["partner_settlement_cents"] >= 0
    assert isinstance(data["partner_settled"], bool)
    assert is_iso8601_timestamp(data["hold_expires_at"])


def assert_partner_airline(data: dict):
    _assert_system_fields(data, "PartnerAirline")
    assert data["reciprocity_mode"] in RECIPROCITY_MODES
    assert data["award_pricing_mode"] in AWARD_PRICING_MODES
    assert len(data["iata_code"]) == 2
    assert data["settlement_rate_centicents_per_mile"] >= 1
    assert data["settled_booking_count"] >= 0
    assert data["last_settlement_run_at"] is None or (
        is_iso8601_timestamp(data["last_settlement_run_at"])
    )


def assert_program_change_notice(data: dict):
    _assert_system_fields(data, "ProgramChangeNotice")
    assert data["status"] in NOTICE_STATUSES
    assert data["change_type"] in CHANGE_TYPES
    assert is_iso8601_timestamp(data["effective_at"])
    assert data["grandfather_until"] is None or (
        is_iso8601_timestamp(data["grandfather_until"])
    )
    assert data["grandfathered_tier_floor"] is None or (
        data["grandfathered_tier_floor"] in ELITE_TIERS
    )
    assert data["announced_at"] is None or is_iso8601_timestamp(data["announced_at"])
    assert data["notice_days"] >= 0
    assert data["exposed_member_count"] >= 0
    assert 0 <= data["member_reaction_index"] <= 100


def assert_fraud_case(data: dict):
    _assert_system_fields(data, "FraudCase")
    assert data["status"] in FRAUD_CASE_STATUSES
    assert data["case_type"] in CASE_TYPES
    assert is_valid_uuid(data["member_id"])
    assert data["login_geo_velocity"] >= 0
    assert data["redemption_velocity_24h"] >= 0
    assert data["brokering_pattern_hits"] >= 0
    assert data["dormancy_days"] >= 0
    assert 0 <= data["detection_score"] <= 100
    assert isinstance(data["freeze_applied"], bool)
    assert data["clawback_miles"] >= 0
    assert data["opened_by_user_id"]


def assert_deferred_revenue_posting(data: dict):
    _assert_append_only_fields(data, "DeferredRevenuePosting")
    assert is_valid_uuid(data["program_id"])
    assert data["method_applied"] in BREAKAGE_POLICY_MODES
    assert data["method"] is None or data["method"] in BREAKAGE_POLICY_MODES
    assert len(data["period"]) == 7 and data["period"][4] == "-"
    assert data["outstanding_miles_snapshot"] >= 0
    assert data["expired_miles_trailing"] >= 0
    assert data["redeemed_miles_trailing"] >= 0
    assert data["issued_miles_trailing"] >= 0
    assert 0 <= data["breakage_rate_bps"] <= 3500
    assert data["deferred_balance_before_cents"] >= 0
    assert data["breakage_income_cents"] >= 0
    assert data["deferred_balance_after_cents"] >= 0


def assert_epoch_report(data: dict):
    for counter in (
        "holds_expired", "campaigns_launched", "campaigns_ended",
        "status_matches_lapsed", "notices_advanced", "agreements_expired",
        "windows_recomputed",
    ):
        assert data[counter] >= 0, f"epoch report counter {counter} is non-negative"
    assert is_iso8601_timestamp(data["epoch_at"])
