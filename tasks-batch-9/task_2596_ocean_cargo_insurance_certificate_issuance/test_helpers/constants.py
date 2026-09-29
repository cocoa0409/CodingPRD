"""
Canonical request payloads, enum vocabularies and pre-computed expected values
for the Ocean Cargo Insurance API test suite.

The payload templates below describe one coherent book of business: an open
cover on consumer electronics, a classed 2015-built hull, and two green ports.
Every monetary expectation in the EXPECTED_* section was derived from the rules
the PRD states, so a test can assert the exact cents the API must produce.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
FREIGHT_BASES = ["PREPAID", "COLLECT"]
POLICY_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "CANCELLED"]
POLICY_WAR_STATUSES = ["ATTACHED", "TERMINATED", "REINSTATED"]
SUSCEPTIBILITY_RATINGS = ["S1", "S2", "S3", "S4"]
PACKAGING_CODES = ["STD", "EXPORT_CRATE", "IBC_LINED", "REEFER_SEALED"]
CLASSIFICATION_SOCIETIES = ["LR", "ABS", "DNV", "BV", "NK", "CCS", "UNCLASSED"]
VESSEL_STATUSES = ["PENDING_REVIEW", "APPROVED", "OVERAGE_SURCHARGED",
                   "BLOCKED", "GA_HOLD"]
WAR_RISK_TIERS = ["GREEN", "AMBER", "LISTED_AREA"]
SURVEYOR_STATUSES = ["ACTIVE", "SUSPENDED"]
VALUATION_BASES = ["CIF_PLUS_MARKUP", "DECLARED_VALUE"]
CERTIFICATE_STATUSES = ["DRAFT", "ISSUED", "SUPERSEDED", "CANCELLED",
                        "TRANSIT_ENDED", "CLAIMED"]
CERTIFICATE_WAR_STATUSES = ["PENDING", "ATTACHED", "TERMINATED",
                            "REINSTATED", "NOT_TAKEN"]
ACCUMULATION_SCOPES = ["VESSEL", "LOADING_PORT", "DISCHARGE_PORT"]
ACCUMULATION_STATUSES = ["ACTIVE", "RELEASED"]
RELEASE_REASONS = ["NONE", "CERTIFICATE_CANCELLED", "CERTIFICATE_SUPERSEDED",
                   "TRANSIT_ENDED", "DELIVERY_CONFIRMED"]
DECLARATION_STATUSES = ["OPEN", "SUBMITTED", "UNDER_AUDIT", "ADJUSTED", "ACCEPTED"]
LOSS_TYPES = ["PARTICULAR_AVERAGE", "GENERAL_AVERAGE", "SALVAGE_CHARGE",
              "TOTAL_LOSS", "SHORTAGE"]
PERILS = ["SEA_PERIL", "WET_DAMAGE", "JETTISON", "WAR", "STRIKES",
          "THEFT", "HANDLING"]
ADJUSTMENT_BASES = ["DEPRECIATION_PCT", "SALVAGE_SALE_PROCEEDS"]
SUBROGATION_STATUSES = ["NOT_STARTED", "NOTICE_SENT", "RECOVERED", "TIME_BARRED"]
CLAIM_STATUSES = ["OPENED", "SURVEY_ORDERED", "SURVEY_RECEIVED",
                  "DOCS_INCOMPLETE", "ADJUSTED", "SETTLED", "DENIED"]
DOCUMENT_TYPES = ["SURVEY_REPORT", "PACKING_LIST", "BILL_OF_LADING",
                  "COMMERCIAL_INVOICE", "CARRIER_CLAIM_LETTER", "PHOTO_SET"]
DOCUMENT_ORIGINS = ["ADJUSTER", "SURVEYOR"]
SURVEY_ORDER_STATUSES = ["APPOINTED", "ATTENDED", "REPORT_FILED", "CANCELLED"]
GA_EVENT_STATUSES = ["DECLARED", "SECURITY_COLLECTING", "SECURITY_COMPLETE",
                     "ADJUSTED"]
GA_POSTING_STATUSES = ["REQUIRED", "POSTED", "RELEASED"]

# The three documents an evidence log needs before a claim can be adjusted.
REQUIRED_CLAIM_DOCUMENTS = ["SURVEY_REPORT", "BILL_OF_LADING",
                            "CARRIER_CLAIM_LETTER"]

# ---------------------------------------------------------------------------
# Port payloads
# ---------------------------------------------------------------------------
PORT_SGSIN = {
    "unlocode": "SGSIN",
    "name": "Singapore",
    "country_code": "SG",
    "port_accumulation_limit_amount": 4000000,
    "storage_free_days": 30,
    "war_risk_tier": "GREEN",
}

PORT_NLRTM = {
    "unlocode": "NLRTM",
    "name": "Rotterdam",
    "country_code": "NL",
    "port_accumulation_limit_amount": 4000000,
    "storage_free_days": 30,
    "war_risk_tier": "GREEN",
}

PORT_USNYC = {
    "unlocode": "USNYC",
    "name": "New York",
    "country_code": "US",
    "port_accumulation_limit_amount": 4000000,
    "storage_free_days": 30,
    "war_risk_tier": "GREEN",
}

# ---------------------------------------------------------------------------
# Commodity class payload
# ---------------------------------------------------------------------------
COMMODITY_CLASS_ELECTRONICS = {
    "code": "CC-ELEC",
    "description": "Consumer electronics",
    "susceptibility_rating": "S3",
    "required_packaging_code": "EXPORT_CRATE",
    "rate_loading_pct": 0.35,
    "max_conveyance_share_pct": 0.80,
    "survey_required_above_amount": 500000,
}

# ---------------------------------------------------------------------------
# Vessel payloads
# ---------------------------------------------------------------------------
VESSEL_KITE = {
    "name": "MV Kite",
    "imo_number": "9100001",
    "year_built": 2015,
    "classification_society": "LR",
    "flag_code": "SG",
    "vessel_accumulation_limit_amount": 5000000,
}

VESSEL_OLD_SALT = {
    "name": "MV Old Salt",
    "imo_number": "9100002",
    "year_built": 1996,
    "classification_society": "LR",
    "flag_code": "PA",
    "vessel_accumulation_limit_amount": 5000000,
}

VESSEL_COMET = {
    "name": "MV Comet",
    "imo_number": "9100003",
    "year_built": 2018,
    "classification_society": "ABS",
    "flag_code": "SG",
    "vessel_accumulation_limit_amount": 5000000,
}

# ---------------------------------------------------------------------------
# Open cover payload
# ---------------------------------------------------------------------------
OPEN_POLICY_CANONICAL = {
    "policy_number": "OP-2596-A",
    "assured_name": "Kite Trading Pte",
    "inception_at": "2026-01-01T00:00:00Z",
    "expiry_at": "2027-01-01T00:00:00Z",
    "freight_basis": "PREPAID",
    "per_certificate_limit_amount": 2000000,
    "conveyance_limit_amount": 3000000,
    "annual_aggregate_limit_amount": 10000000,
    "premium_rate_per_mille": 3.500,
    "war_rate_per_mille": 0.600,
    "strikes_rate_per_mille": 0.255,
    "warehouse_to_warehouse": True,
    "markup_pct": 0.10,
    "deductible_amount": 2500,
}

# ---------------------------------------------------------------------------
# Certificate payloads (the foreign keys are filled in by the factories)
# ---------------------------------------------------------------------------
CERTIFICATE_CIF_SHIPMENT = {
    "certificate_number": "CERT-A",
    "valuation_basis": "CIF_PLUS_MARKUP",
    "packaging_code": "EXPORT_CRATE",
    "package_count": 120,
    "gross_weight_kg": 18000,
    "sailing_date": "2026-08-10T00:00:00Z",
    "discharge_date": "2026-09-05T00:00:00Z",
    "invoice_value": 1000000,
    "freight_amount": 45000,
    "duty_amount": 5000,
    "war_cover_requested": True,
    "strikes_cover_requested": True,
}

CERTIFICATE_DECLARED_SHIPMENT = {
    "certificate_number": "CERT-B",
    "valuation_basis": "DECLARED_VALUE",
    "packaging_code": "EXPORT_CRATE",
    "package_count": 120,
    "gross_weight_kg": 18000,
    "sailing_date": "2026-08-10T00:00:00Z",
    "discharge_date": "2026-09-05T00:00:00Z",
    "declared_value": 1050000,
    "war_cover_requested": True,
    "strikes_cover_requested": True,
}

# ---------------------------------------------------------------------------
# Surveyor payload
# ---------------------------------------------------------------------------
SURVEYOR_ROTTERDAM = {
    "name": "Rotterdam Marine Surveys BV",
    "panel_code": "PNL-NL-01",
    "certified_commodity_ratings": ["S2", "S3"],
    "travel_buffer_minutes": 45,
}

# ---------------------------------------------------------------------------
# General average payload
# ---------------------------------------------------------------------------
GA_EVENT_CANONICAL = {
    "voyage_sailing_date": "2026-08-10T00:00:00Z",
    "declaration_date": "2026-08-18T00:00:00Z",
    "average_adjuster_name": "Richards Hogg Lindley",
    "sacrifice_amount": 120000,
    "salvage_award_amount": 30000,
}

# ---------------------------------------------------------------------------
# Pre-computed expectations for the canonical book of business
# ---------------------------------------------------------------------------
# Valuation: 1000000.00 + 45000.00 + 5000.00, uplifted by the 10% markup.
EXPECTED_INSURED_VALUE_CIF = 1155000.00
# Valuation: the declared figure, taken as given.
EXPECTED_INSURED_VALUE_DECLARED = 1050000.00

# Rating: 3.500 per mille loaded by 35% for the commodity, no hull surcharge.
EXPECTED_EFFECTIVE_RATE = 4.7250
# Rating on an overage hull: 3.500 loaded by 35% and then by 25%.
EXPECTED_EFFECTIVE_RATE_OVERAGE = 5.9063

# Premium on the canonical CIF shipment.
EXPECTED_BASE_PREMIUM = 5457.38
EXPECTED_WAR_PREMIUM = 693.00
EXPECTED_STRIKES_PREMIUM = 294.53
EXPECTED_TOTAL_PREMIUM = 6444.91
# Premium on the same shipment carried by the overage hull.
EXPECTED_BASE_PREMIUM_OVERAGE = 6821.78
EXPECTED_TOTAL_PREMIUM_OVERAGE = 7809.31

# Premium on the 1050000.00 declared-value shipment.
EXPECTED_BASE_PREMIUM_DECLARED = 4961.25
EXPECTED_WAR_PREMIUM_DECLARED = 630.00
EXPECTED_STRIKES_PREMIUM_DECLARED = 267.75
EXPECTED_TOTAL_PREMIUM_DECLARED = 5859.00

# War and strikes returned when war cover falls away before delivery.
EXPECTED_WAR_STRIKES_RETURN = 987.53

# Transit: 30 free storage days after a 2026-09-05 discharge.
EXPECTED_TRANSIT_TERMINATION = "2026-10-05T00:00:00Z"

# Claim on the canonical CIF shipment, 12.5% damage, 2500.00 deductible.
EXPECTED_CLAIM_GROSS = 144375.00
EXPECTED_CLAIM_ADJUSTED_DEPRECIATION = 141875.00
EXPECTED_CLAIM_DEDUCTIBLE_APPLIED = 2500.00
# The same shipment adjusted on sale proceeds of 1050000.00 against a sound
# market value of 1200000.00.
EXPECTED_CLAIM_ADJUSTED_SALVAGE = 144062.50
EXPECTED_CLAIM_DEDUCTIBLE_APPLIED_SALVAGE = 312.50

# General average over contributors of 1155000.00 and 800000.00.
EXPECTED_GA_ADJUSTER_FEE = 7500.00
EXPECTED_GA_TOTAL_ALLOWANCE = 157500.00
EXPECTED_GA_TOTAL_CONTRIBUTORY_VALUE = 1955000.00
EXPECTED_GA_CONTRIBUTION_RATE = 0.080563
EXPECTED_GA_CONTRIBUTION_LARGEST = 93049.60
EXPECTED_GA_CONTRIBUTION_SMALLER = 64450.40
EXPECTED_GA_DEPOSIT_LARGEST = 18609.92
EXPECTED_GA_DEPOSIT_SMALLER = 12890.08
EXPECTED_GA_DEPOSIT_TOTAL = 31500.00
