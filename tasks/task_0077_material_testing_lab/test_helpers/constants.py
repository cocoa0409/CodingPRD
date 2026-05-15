"""Domain thresholds and defaults derived from PRD calculations and tables."""
from __future__ import annotations


# Pricing table (PRD §3.10).
BASE_FEE_CENTS: dict = {
    "COMPRESSION_STRENGTH": 20000,
    "TENSILE_STRENGTH": 25000,
    "COMPACTION_DENSITY": 18000,
    "MARSHALL_STABILITY": 30000,
    "SETTING_TIME": 15000,
}

# Method-to-material coupling (PRD §3.3).
METHOD_TO_CATEGORY: dict = {
    "COMPRESSION_STRENGTH": "CONCRETE",
    "TENSILE_STRENGTH": "STEEL_REBAR",
    "COMPACTION_DENSITY": "SOIL",
    "MARSHALL_STABILITY": "ASPHALT",
    "SETTING_TIME": "CEMENT",
}

MATERIAL_TO_METHOD: dict = {v: k for k, v in METHOD_TO_CATEGORY.items()}

# Test-result expected bands (PRD §3.6).
RESULT_BAND: dict = {
    "COMPRESSION_STRENGTH": (20.0, 60.0),
    "TENSILE_STRENGTH": (400.0, 600.0),
    "COMPACTION_DENSITY": (1.9, 2.6),
    "MARSHALL_STABILITY": (7.5, 18.0),
    "SETTING_TIME": (45.0, 600.0),
}

# Material short codes for sample_code derivation (PRD §3.2).
MATERIAL3_PREFIX: dict = {
    "CONCRETE": "CON",
    "STEEL_REBAR": "STE",
    "SOIL": "SOI",
    "ASPHALT": "ASP",
    "CEMENT": "CEM",
}

# Money / percentage constants (PRD §3.10).
URGENT_SURCHARGE_RATE = 0.50
REFUND_RATE_ON_ABNORMAL_AFTER_RETEST = 0.30
PACKAGE_THRESHOLD_COUNT = 5
PACKAGE_DISCOUNT_RATE = 0.10

# Qualification posture window (PRD §3.5).
EXPIRING_WINDOW_DAYS = 30

# Tester workload default cap (PRD §3.5).
DEFAULT_MAX_CONCURRENT_TASKS = 5

# Report archive window (PRD §3.9).
REPORT_ARCHIVE_DAYS = 30

# Retest cap (PRD §3.7).
RETEST_LIMIT = 1


# Test default scratch values used by factories.
TEST_DEFAULTS: dict = {
    "CLIENT_NAME": "Acme Construction",
    "CONTACT_EMAIL": "acme@example.test",
    "SOURCE_PROJECT": "Tower A",
    "TESTER_NAME": "Tester Alpha",
    "REVIEWER_NAME": "Reviewer Beta",
    "SIGNATORY_NAME": "Signatory Gamma",
    "INSTRUMENT_ASSET_CODE_PREFIX": "UTM-",
    "SIGNATURE_CERT_ID": "CERT-001",
    # default specifications keyed by material so calculator yields valid area
    "SPEC_CONCRETE_CUBE_150MM": "C30 cube 150mm",
    "SPEC_STEEL_REBAR": "HRB400 D16",
    "SPEC_SOIL": "Sample plug",
    "SPEC_ASPHALT": "Marshall briquette",
    "SPEC_CEMENT": "OPC 42.5",
}


__all__ = [
    "BASE_FEE_CENTS",
    "METHOD_TO_CATEGORY",
    "MATERIAL_TO_METHOD",
    "RESULT_BAND",
    "MATERIAL3_PREFIX",
    "URGENT_SURCHARGE_RATE",
    "REFUND_RATE_ON_ABNORMAL_AFTER_RETEST",
    "PACKAGE_THRESHOLD_COUNT",
    "PACKAGE_DISCOUNT_RATE",
    "EXPIRING_WINDOW_DAYS",
    "DEFAULT_MAX_CONCURRENT_TASKS",
    "REPORT_ARCHIVE_DAYS",
    "RETEST_LIMIT",
    "TEST_DEFAULTS",
]
