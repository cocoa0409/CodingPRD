"""Domain constants: thresholds, weights, tiers and enumeration orders from the PRD."""

# The logical clock's startup value.
STARTUP_CLOCK = "2026-08-01T00:00:00Z"

# Design-score factor weights and rating multipliers.
FACTOR_WEIGHTS = {
    "SUBJECT_MATTER": 30,
    "VISUAL_CONTENT": 20,
    "CHILD_CELEBRITIES": 15,
    "LANGUAGE": 10,
    "MUSIC_AUDIO": 10,
    "ADVERTISING_PLACEMENT": 10,
    "INTERACTIVE_DESIGN": 5,
}

RATING_MULTIPLIERS = {
    "ABSENT": 0.00,
    "INCIDENTAL": 0.25,
    "MODERATE": 0.60,
    "STRONG": 1.00,
}

# Determination thresholds (all inclusive).
THRESHOLDS = {
    "DESIGN_MIXED_THRESHOLD": 0.45,
    "DESIGN_PRIMARY_THRESHOLD": 0.75,
    "AUDIENCE_PRIMARY_THRESHOLD": 0.4000,
    "AUDIENCE_MIXED_THRESHOLD": 0.2000,
    "AUDIENCE_DESIGN_ESCALATION_THRESHOLD": 0.65,
    "EXPOSURE_RESTRICT_THRESHOLD": 40,
    "EXPOSURE_FREEZE_THRESHOLD": 80,
    "MAX_ASSURANCE_TIER": 3,
}

# Per-integration base exposure weights, doubled when a persistent identifier is collected.
INTEGRATION_TYPE_POINTS = {
    "BEHAVIORAL_AD_NETWORK": 40,
    "SOCIAL_PLUGIN": 25,
    "ANALYTICS": 15,
    "CONTEXTUAL_AD_NETWORK": 5,
    "CDN": 0,
}

# Assurance tier of each intended use, and of each consent/verification method.
USE_TIER = {
    "PARTICIPATION_CORE": 1,
    "INTERNAL_OPERATIONS": 1,
    "CONTESTS_PRIZES": 2,
    "PERSONALIZED_ADVERTISING": 3,
    "THIRD_PARTY_DISCLOSURE": 3,
    "PUBLIC_POSTING": 3,
}

METHOD_TIER = {
    "EMAIL_PLUS": 1,
    "SCHOOL_AUTHORIZATION": 1,
    "KNOWLEDGE_BASED_AUTH": 2,
    "SIGNED_FORM_RETURN": 2,
    "PHONE_CALL_TRAINED_PERSONNEL": 2,
    "CREDIT_CARD_TRANSACTION": 3,
    "GOVT_ID_MATCH": 3,
    "VIDEO_CONFERENCE_REVIEW": 3,
}

# Mapping from a collection purpose onto the intended use the parent must have consented to.
PURPOSE_USE_MAP = {
    "PARTICIPATION_CORE": "PARTICIPATION_CORE",
    "INTERNAL_OPERATIONS": "INTERNAL_OPERATIONS",
    "SUPPORT": "INTERNAL_OPERATIONS",
    "CONTESTS": "CONTESTS_PRIZES",
    "PERSONALIZED_ADS": "PERSONALIZED_ADVERTISING",
}

# Disposal methods admissible per data element.
ALLOWED_DISPOSAL_METHODS = {
    "PERSISTENT_IDENTIFIER": ["CRYPTO_ERASE", "OVERWRITE", "ANONYMIZE"],
    "GEOLOCATION_PRECISE": ["CRYPTO_ERASE", "OVERWRITE"],
    "PHOTO_VIDEO_AUDIO": ["CRYPTO_ERASE", "PHYSICAL_DESTRUCTION"],
    "VOICE_RECORDING": ["CRYPTO_ERASE", "PHYSICAL_DESTRUCTION"],
    "FULL_NAME": ["CRYPTO_ERASE", "OVERWRITE"],
    "EMAIL": ["CRYPTO_ERASE", "OVERWRITE"],
    "SCREEN_NAME": ["CRYPTO_ERASE", "OVERWRITE", "ANONYMIZE"],
    "PHONE": ["CRYPTO_ERASE", "OVERWRITE"],
    "POSTAL_ADDRESS": ["CRYPTO_ERASE", "OVERWRITE", "PHYSICAL_DESTRUCTION"],
    "SCHOOL_NAME": ["CRYPTO_ERASE", "OVERWRITE", "ANONYMIZE"],
}

# The seven required notice content sections, in canonical order.
REQUIRED_CONTENT_KEYS = [
    "OPERATOR_IDENTITY_CONTACT",
    "ELEMENTS_COLLECTED",
    "USE_PURPOSES",
    "THIRD_PARTY_DISCLOSURE",
    "PARENTAL_RIGHTS",
    "NO_CONDITIONING_OF_PARTICIPATION",
    "RETENTION_AND_DISPOSAL",
]

# Fixed order of the neutrality violation codes.
NEUTRALITY_CODE_ORDER = [
    "PREFILLED_AGE",
    "RETRY_ALLOWED",
    "OUTCOME_NOT_PERSISTED",
    "UNVERIFIED_INHERIT",
]

# Bounded-loop caps and windows.
DOMAIN_LIMITS = {
    "CONSENT_VERIFICATION_WINDOW_DAYS": 14,
    "MAX_VERIFICATION_ATTEMPTS": 3,
    "MAX_REMEDIATION_ROUNDS": 2,
    "MAX_SCREEN_REVISION_ROUNDS": 2,
}

# Safe harbor program defaults.
PROGRAM_DEFAULTS = {
    "annual_assessment_required": True,
    "assessment_validity_days": 365,
    "assessment_grace_days": 30,
}

# Pagination contract.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Values used repeatedly by tests as arbitrary-but-fixed inputs.
TEST_DEFAULTS = {
    "SERVICE_CATEGORY": "GAME",
    "SUBJECT_MATTER_CODE": "FAMILY_MIXED",
    "OPERATOR_ORGANIZATION": "Test Media",
    "DELIVERY_CHANNEL": "EMAIL",
    "ACTIVITY_CODE": "CLUB",
    "SCHEDULE_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "SCHEDULE_EFFECTIVE_TO": "2026-12-31T00:00:00Z",
}
