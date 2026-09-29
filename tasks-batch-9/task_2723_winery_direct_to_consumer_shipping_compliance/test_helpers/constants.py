"""Business constants and canonical reference payloads for the Winery DTC API.

Every value here is quoted from the PRD narrative (§2 and §3) so that tests never
carry magic numbers inline.
"""

API_PREFIX = "/dtc"

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_WINERY_OPERATOR = "WineryOperator"
ROLE_CONSUMER = "Consumer"
ROLE_CARRIER_AGENT = "CarrierAgent"

ALL_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_WINERY_OPERATOR,
    ROLE_CONSUMER,
    ROLE_CARRIER_AGENT,
]

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_CANONICAL = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Charge chain (PRD §3.5)
# ---------------------------------------------------------------------------
SHIPPING_BASE_CENTS = 1500
SHIPPING_PER_LITER_CENTS = 220
LITER_TIER_1_MAX_L = 9.000
LITER_TIER_2_MAX_L = 18.000
LITER_TIER_1_MULTIPLIER = 1.00
LITER_TIER_2_MULTIPLIER = 0.90
LITER_TIER_3_MULTIPLIER = 0.80
CLUB_SHIPPING_DISCOUNT_BPS = 2500
FEE_WAIVER_THRESHOLD_CENTS = 20000
COMPLIANCE_HANDLING_FEE_CENTS = 900

# Excise (PRD §3.5)
SMALL_PRODUCER_MAX_GALLONS = 250000
SMALL_PRODUCER_CREDIT_BPS = 1500
LARGE_FORMAT_ML_EXCLUSIVE_THRESHOLD = 1500

# Risk model (PRD §3.4)
RETURN_CREDIT_WEIGHT = 10
RETURN_CREDIT_CAP = 40
DENIAL_WEIGHT = 15
DENIAL_CAP = 30
UTILISATION_CAP = 30
RISK_SCORE_CAP = 100
ELEVATED_TIER_THRESHOLD = 50

# Rolling windows (PRD §3.4)
ROLLING_12_MONTHS_DAYS = 365
ROLLING_30_DAYS_DAYS = 30

# Renewal calendar (PRD §3.9)
DEFAULT_HORIZON_DAYS = 90
MIN_HORIZON_DAYS = 1
MAX_HORIZON_DAYS = 365
DEFAULT_RENEWAL_LEAD_DAYS = 60
DEFAULT_MIN_PURCHASER_AGE = 21

# Club run (PRD §3.8)
MISSED_RUN_SUSPEND_THRESHOLD = 2
HOLD_BUFFER_DAYS = 3

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Body-shape bounds (PRD §2.8)
MIN_BOTTLES = 1
ALLOWED_BOTTLE_ML = [375, 500, 750, 1000, 1500, 3000]
MIN_UNIT_PRICE_CENTS = 1
MIN_LINES = 1
MAX_LINES = 20
MIN_SALES_TAX_RATE_BPS = 0
MAX_SALES_TAX_RATE_BPS = 2000

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
WINERY_STATUSES = ["ACTIVE", "SUSPENDED"]
PER_CONSUMER_PERIODS = ["ROLLING_12_MONTHS", "CALENDAR_YEAR", "ROLLING_30_DAYS"]
REPORTING_FREQUENCIES = ["MONTHLY", "ANNUAL"]
PROHIBITED_ZIP_REASONS = [
    "DRY_COUNTY",
    "PROHIBITED_MUNICIPALITY",
    "PO_BOX_ONLY",
    "CARRIER_UNSERVED",
]
CARRIER_CODES = ["UPS", "FEDEX", "GSO"]
ENROLLMENT_STATUSES = ["PENDING", "APPROVED", "SUSPENDED"]
ID_VERIFICATION_METHODS = ["NONE", "DOCUMENT", "DATABASE"]
SCREENING_TIERS = ["STANDARD", "ELEVATED"]
PERMIT_TYPES = ["DIRECT_SHIPPER", "WINE_SHIPPER", "COMMON_CARRIER_ENDORSEMENT"]
PERMIT_STATUSES = ["PENDING", "ACTIVE", "RENEWAL_FILED", "EXPIRED", "REVOKED"]
CADENCES = ["MONTHLY", "QUARTERLY"]
SUBSCRIPTION_STATUSES = ["ACTIVE", "WEATHER_HELD", "SUSPENDED_COMPLIANCE"]
HOLD_REASONS = ["WEATHER_HEAT", "WEATHER_FREEZE", "CONSUMER_REQUEST"]
COMPLIANCE_STATUSES = [
    "DRAFT",
    "CLEARED",
    "REJECTED",
    "OVERRIDE_PENDING",
    "SUSPENDED_PERMIT",
]
FULFILLMENT_STATUSES = [
    "UNFULFILLED",
    "LABELED",
    "IN_TRANSIT",
    "DELIVERED",
    "RETURNED",
]
SHIPMENT_STATUSES = [
    "LABEL_CREATED",
    "IN_TRANSIT",
    "EXCEPTION",
    "DELIVERED",
    "RETURNED",
]
SHIPMENT_EXCEPTION_CODES = [
    "WEATHER",
    "ADDRESS_UNDELIVERABLE",
    "ADULT_SIGNATURE_UNAVAILABLE",
    "REFUSED",
]
SCAN_TYPES = ["PICKUP", "EXCEPTION", "REROUTE_ACCEPTED", "DELIVERED", "RETURN_TO_SENDER"]
EXCEPTION_STATUSES = ["OPEN", "APPROVED", "DENIED"]
LEDGER_EVENT_TYPES = ["SHIPMENT_ACCEPTED", "RETURN_CREDIT", "MANUAL_ADJUSTMENT"]
REMITTANCE_PERIOD_TYPES = ["MONTHLY", "ANNUAL"]
REMITTANCE_BASES = ["ACCRUAL_BASIS", "DELIVERY_BASIS"]
REMITTANCE_STATUSES = ["OPEN", "FILED", "REMITTED", "AMENDED"]
CALENDAR_STATUSES = ["OVERDUE", "FILED", "DUE", "SCHEDULED"]

OVERRIDABLE_RULES = [
    "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED",
    "ERR_WINERY_VOLUME_LIMIT_EXCEEDED",
    "ERR_ELEVATED_RISK_REVIEW_REQUIRED",
]

# ---------------------------------------------------------------------------
# Canonical reference data used by the shared fixtures
# ---------------------------------------------------------------------------
WINERY_ESTATE_1 = {
    "name": "Estate 1",
    "ttb_permit_number": "TTB-1001",
    "home_state_code": "CA",
    "annual_production_gallons": 120000,
}

WINERY_ESTATE_2 = {
    "name": "Estate 2",
    "ttb_permit_number": "TTB-2002",
    "home_state_code": "OR",
    "annual_production_gallons": 120000,
}

# A winery one gallon past the small-producer ceiling of 250000 gallons.
WINERY_LARGE_PRODUCER = {
    "name": "Estate Large",
    "ttb_permit_number": "TTB-3003",
    "home_state_code": "CA",
    "annual_production_gallons": 250001,
}

STATE_RULE_TX = {
    "state_code": "TX",
    "allows_dtc": True,
    "per_consumer_limit_liters": 27.000,
    "per_consumer_period": "ROLLING_12_MONTHS",
    "per_winery_annual_limit_liters": 5000.000,
    "excise_rate_per_liter_cents": 55,
    "large_format_surcharge_cents_per_liter": 20,
    "excise_cap_cents_per_shipment": 100000,
    "sales_tax_rate_bps": 825,
    "tax_on_shipping": True,
    "excise_in_tax_base": False,
    "adult_signature_required": True,
    "requires_carrier_program": True,
    "reporting_frequency": "MONTHLY",
    "zero_filing_required": True,
    "min_purchaser_age": 21,
    "renewal_lead_days": 45,
}

STATE_RULE_NM = {
    "state_code": "NM",
    "allows_dtc": True,
    "per_consumer_limit_liters": 9.000,
    "per_consumer_period": "ROLLING_30_DAYS",
    "per_winery_annual_limit_liters": 100.000,
    "excise_rate_per_liter_cents": 120,
    "large_format_surcharge_cents_per_liter": 20,
    "excise_cap_cents_per_shipment": 300,
    "sales_tax_rate_bps": 0,
    "tax_on_shipping": False,
    "excise_in_tax_base": False,
    "adult_signature_required": True,
    "requires_carrier_program": False,
    "reporting_frequency": "ANNUAL",
    "zero_filing_required": False,
    "min_purchaser_age": 21,
    "renewal_lead_days": 45,
}

CONSUMER_ADA = {
    "full_name": "Ada Buyer",
    "email": "ada@example.com",
    "birthdate": "1985-04-02",
    "address_line": "12 Vine St",
    "city": "Austin",
    "state_code": "TX",
    "zip_code": "78701",
}

CONSUMER_BEN = {
    "full_name": "Ben Buyer",
    "email": "ben@example.com",
    "birthdate": "1980-01-15",
    "address_line": "44 Oak Ave",
    "city": "Austin",
    "state_code": "TX",
    "zip_code": "78701",
}

CARRIER_PROGRAM_GSO_TX = {
    "carrier_code": "GSO",
    "program_name": "Wine Shipper TX",
    "states_served": ["TX"],
    "requires_enrollment": True,
    "adult_signature_service_code": "AS21",
}

# A program that cannot offer an age-verified adult-signature service at all.
CARRIER_PROGRAM_NO_SIGNATURE = {
    "carrier_code": "UPS",
    "program_name": "Ground Only TX",
    "states_served": ["TX"],
    "requires_enrollment": True,
    "adult_signature_service_code": None,
}

PERMIT_TX_2026 = {
    "state_code": "TX",
    "permit_number": "TX-DTC-1",
    "permit_type": "DIRECT_SHIPPER",
    "effective_date": "2026-01-01",
    "expiration_date": "2026-12-31",
}

# The canonical order body: 6 x 750 ml at 4200 cents, i.e. 4.500 L.
CANONICAL_LINE = {
    "sku": "CAB-750",
    "bottle_ml": 750,
    "bottles": 6,
    "unit_price_cents": 4200,
}

CANONICAL_SHIP_TO = {
    "ship_to_address_line": "12 Vine St",
    "ship_to_state_code": "TX",
    "ship_to_zip": "78701",
}

# Frozen money for the canonical 4.500 L TX order (PRD §3.5 worked chain).
CANONICAL_ORDER_TOTAL_LITERS = 4.500
CANONICAL_ORDER_SUBTOTAL_CENTS = 25200
CANONICAL_ORDER_SHIPPING_CENTS = 2490
CANONICAL_ORDER_EXCISE_CENTS = 211
CANONICAL_ORDER_SALES_TAX_CENTS = 2284
CANONICAL_ORDER_TOTAL_CENTS = 30185
