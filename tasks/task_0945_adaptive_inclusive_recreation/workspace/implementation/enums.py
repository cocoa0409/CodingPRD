"""Declared enumeration members.

PRD rung 23 pins the closed set of fields that route to ERR_INVALID_ENUM:
income_band, mobility_profile, guardianship_status, relationship, support_tier,
consent_type, activity_type, risk_tier, pricing_mode, rounding_policy,
waitlist_policy, the members of required_consent_types and
required_certification_types, certification_type, assignment_role, item_kind,
disposition, return_condition, position_type, fare_mode, source_kind,
award_mode, mastery_mode, outcome, on_full and target_status.  "No other field
routes here."
"""

INCOME_BANDS = ("BAND_A", "BAND_B", "BAND_C", "BAND_D")
MOBILITY_PROFILES = ("WHEELCHAIR", "AMBULATORY")
GUARDIANSHIP_STATUSES = ("SELF", "GUARDIAN_REQUIRED", "CONSERVATORSHIP")
RELATIONSHIPS = ("PARENT", "GUARDIAN", "SIBLING", "OTHER")
SUPPORT_TIERS = ("INDEPENDENT", "INTERMITTENT", "SUBSTANTIAL", "ONE_TO_ONE")
CONSENT_TYPES = (
    "MEDIA_RELEASE",
    "EMERGENCY_MEDICAL",
    "BEHAVIOR_SUPPORT_PLAN",
    "MEDICATION_ADMIN",
)
ACTIVITY_TYPES = ("AQUATICS", "FITNESS", "ARTS", "SPORTS", "COMMUNITY_OUTING")
RISK_TIERS = ("LOW", "MODERATE", "HIGH")
PRICING_MODES = ("PER_SESSION", "SERIES_FLAT")
ROUNDING_POLICIES = ("ROUND_PER_LINE", "ROUND_ON_TOTAL")
WAITLIST_POLICIES = ("FIFO", "EQUITY_WEIGHTED")
CERTIFICATION_TYPES = ("ADAPTIVE_AQUATICS", "BEHAVIOR_SUPPORT", "MEDICATION_ADMIN", "CPR")
ASSIGNMENT_ROLES = ("LEAD", "GROUP", "ONE_TO_ONE")
ITEM_KINDS = ("SERIALIZED", "POOLED")
DISPOSITIONS = ("PASS", "FAIL", "RETIRE")
RETURN_CONDITIONS = ("GOOD", "DAMAGED")
POSITION_TYPES = ("ACCESSIBLE", "AMBULATORY")
FARE_MODES = ("FLAT", "ZONE_MILEAGE")
SOURCE_KINDS = ("RESTRICTED_GRANT", "GENERAL_FUND")
AWARD_MODES = ("NEED_PCT", "FLAT_CAP")
MASTERY_MODES = ("N_OF_M", "CONSECUTIVE")
OUTCOMES = ("ATTENDED", "NO_SHOW")
ON_FULL = ("ERROR", "WAITLIST", "DENY")
PERIOD_STATUSES = ("OPEN", "RESTRICTED", "FROZEN", "CLOSING", "CLOSED")
PARTICIPANT_STATUSES = ("INTAKE", "ACTIVE", "INACTIVE", "EXITED")

# --- role sets -------------------------------------------------------------
STAFF_ROLES = (
    "ProgramAdmin",
    "IntakeCoordinator",
    "ActivityLead",
    "FundingOfficer",
    "TransportDispatcher",
)
ALL_ROLES = STAFF_ROLES + ("CaregiverUser",)
