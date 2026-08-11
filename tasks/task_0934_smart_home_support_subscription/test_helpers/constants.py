"""Domain thresholds and reusable fixture inputs, all taken from the PRD."""

# Numeric constants the PRD states in prose.
THRESHOLDS = {
    "CLOCK_DEFAULT_UTC": "2026-05-01T00:00:00Z",
    "BILLING_CYCLE_DAYS": 30,
    "ACTIVATION_TOKEN_TTL_MINUTES": 1440,
    "ACTIVATION_MAX_ATTEMPTS": 3,
    "TRAVEL_BUFFER_MINUTES": 45,
    "VISIT_LATE_CANCEL_CUTOFF_HOURS": 24,
    "LATE_CANCEL_FEE_CENTS": 4500,
    "NO_SHOW_FEE_CENTS": 9000,
    "INSTALL_VISIT_FEE_CENTS": 12900,
    "ADDON_ORDER_MAX_LINES": 5,
    "BUNDLE_TIER_1_MIN_SUBTOTAL_CENTS": 20_000,
    "BUNDLE_TIER_1_PCT": 0.10,
    "BUNDLE_TIER_2_MIN_SUBTOTAL_CENTS": 50_000,
    "BUNDLE_TIER_2_PCT": 0.15,
    "PRORATION_MIN_DAYS": 5,
    "REMOTE_FAILURE_ESCALATION_THRESHOLD": 3,
    "FIRMWARE_MAX_RETRY_COUNT": 2,
    "FIRMWARE_DEFER_MAX_DAYS": 14,
    "DEFAULT_HALT_FAILURE_RATE_PCT": 0.20,
    "RMA_RETURN_WINDOW_DAYS": 14,
    "ADVANCE_REPLACEMENT_HOLD_PCT_OF_MSRP": 0.60,
    "ADVANCE_REPLACEMENT_MIN_WARRANTY_DAYS": 30,
    "REOPEN_WINDOW_HOURS": 168,
    "CSAT_SURVEY_WINDOW_HOURS": 72,
    "CSAT_LOW_SCORE_MAX": 2,
    "CSAT_BREACH_COMPOUNDED_PCT": 0.10,
    "CSAT_GOODWILL_PCT": 0.05,
    "CREDIT_CAP_PCT_OF_MONTHLY_FEE": 0.50,
    "SLA_AT_RISK_PCT": 0.80,
    "BREACH_MINOR_MAX_RATIO": 0.25,
    "BREACH_MAJOR_MAX_RATIO": 1.00,
    "BREACH_MINOR_PCT": 0.05,
    "BREACH_MAJOR_PCT": 0.15,
    "BREACH_SEVERE_PCT": 0.30,
    "BUSINESS_HOURS_START_MINUTE_OF_DAY": 540,
    "BUSINESS_HOURS_END_MINUTE_OF_DAY": 1020,
}

TEST_DEFAULTS = {
    "CLOCK": "2026-05-01T00:00:00Z",
    "REGION": "NWA",
    "OTHER_REGION": "SEB",
    "PURCHASE_DATE": "2026-04-01",
}


# ---------------------------------------------------------------------------
# Plan templates. Each mirrors the plan shapes the design index exercises.
# ---------------------------------------------------------------------------
PRO_PLAN = {
    "tier": "PRO",
    "monthly_fee_cents": 9999,
    "included_device_count": 2,
    "overage_fee_cents_per_device": 299,
    "coverage_mode": "TWENTY_FOUR_SEVEN",
    "first_response_minutes_p1": 30,
    "first_response_minutes_p2": 120,
    "first_response_minutes_p3": 480,
    "onsite_resolution_hours_p1": 24,
    "onsite_resolution_hours_p2": 48,
    "onsite_resolution_hours_p3": 96,
    "warranty_extension_months": 12,
    "included_install_credits": 3,
    "advance_replacement_eligible": True,
}

PLUS_PLAN = {
    "tier": "PLUS",
    "monthly_fee_cents": 4999,
    "included_device_count": 2,
    "overage_fee_cents_per_device": 399,
    "coverage_mode": "BUSINESS_HOURS",
    "first_response_minutes_p1": 120,
    "first_response_minutes_p2": 240,
    "first_response_minutes_p3": 720,
    "onsite_resolution_hours_p1": 48,
    "onsite_resolution_hours_p2": 72,
    "onsite_resolution_hours_p3": 168,
    "warranty_extension_months": 6,
    "included_install_credits": 1,
    "advance_replacement_eligible": False,
}

BASIC_PLAN = {
    "tier": "BASIC",
    "monthly_fee_cents": 1999,
    "included_device_count": 1,
    "overage_fee_cents_per_device": 499,
    "coverage_mode": "BUSINESS_HOURS",
    "first_response_minutes_p1": 240,
    "first_response_minutes_p2": 480,
    "first_response_minutes_p3": 1440,
    "onsite_resolution_hours_p1": 72,
    "onsite_resolution_hours_p2": 120,
    "onsite_resolution_hours_p3": 240,
    "warranty_extension_months": 0,
    "included_install_credits": 0,
    "advance_replacement_eligible": False,
}

PLAN_TEMPLATES = {"PRO": PRO_PLAN, "PLUS": PLUS_PLAN, "BASIC": BASIC_PLAN}


# ---------------------------------------------------------------------------
# Catalog templates.
# ---------------------------------------------------------------------------
HUB_MODEL = {
    "model_code": "HUB-X1",
    "display_name": "Hub X1",
    "device_class": "HUB",
    "serial_prefix": "HBX",
    "base_warranty_months": 24,
    "requires_install": True,
    "manufacturer_service_only": False,
    "msrp_cents": 24900,
    "current_firmware_version": "1.0.0",
}

CAMERA_MODEL = {
    "model_code": "CAM-A2",
    "display_name": "Cam A2",
    "device_class": "CAMERA",
    "serial_prefix": "CMA",
    "base_warranty_months": 12,
    "requires_install": False,
    "manufacturer_service_only": True,
    "msrp_cents": 12900,
    "current_firmware_version": "2.0.0",
}

SENSOR_MODEL = {
    "model_code": "SNS-B1",
    "display_name": "Sensor B1",
    "device_class": "SENSOR",
    "serial_prefix": "SNB",
    "base_warranty_months": 12,
    "requires_install": False,
    "manufacturer_service_only": False,
    "msrp_cents": 4900,
    "current_firmware_version": "1.2.0",
}

THERMOSTAT_MODEL = {
    "model_code": "THM-C1",
    "display_name": "Thermo C1",
    "device_class": "THERMOSTAT",
    "serial_prefix": "TMC",
    "base_warranty_months": 36,
    "requires_install": True,
    "manufacturer_service_only": False,
    "msrp_cents": 19000,
    "current_firmware_version": "3.0.0",
}

CATALOG_TEMPLATES = {
    "HUB": HUB_MODEL,
    "CAMERA": CAMERA_MODEL,
    "SENSOR": SENSOR_MODEL,
    "THERMOSTAT": THERMOSTAT_MODEL,
}
