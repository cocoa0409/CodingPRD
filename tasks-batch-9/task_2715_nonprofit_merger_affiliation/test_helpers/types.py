"""Type aliases and enumerated literal sets for the API under test.

These mirror the entity field vocabularies stated in the PRD narratives.
"""

from typing import Any, Dict, List

Json = Dict[str, Any]
JsonList = List[Json]
Headers = Dict[str, str]

# --- Organization (PRD 3.1) ---
AFFILIATION_ROLES = [
    "INDEPENDENT",
    "SURVIVOR",
    "DISSOLVED",
    "DIVESTED",
    "PARENT",
    "SUBSIDIARY",
    "MSA_PROVIDER",
    "MSA_CLIENT",
]

# --- Restructuring (PRD 3.2, 3.5, 3.9) ---
DEAL_STATUSES = [
    "EXPLORATORY",
    "RATIONALE_BUILT",
    "LOI_NEGOTIATION",
    "DILIGENCE",
    "DILIGENCE_CLOSED",
    "STRUCTURE_SELECTED",
    "BOARD_APPROVAL",
    "REGULATORY_REVIEW",
    "INTEGRATION",
    "CONSUMMATED",
    "ABANDONED",
]
RESTRICTED_ASSET_POSTURES = [
    "NOT_ASSESSED",
    "RESTRICTED_PENDING",
    "BLOCKED",
    "CLEARED",
]

# --- AlignmentAssessment (PRD 3.2) ---
COMPOSITE_RATINGS = ["STRONG", "MODERATE", "WEAK", "NOT_VIABLE"]

# --- LetterOfIntent (PRD 3.3) ---
LETTER_STATUSES = [
    "ISSUED",
    "COUNTERED",
    "EXECUTED",
    "WITHDRAWN",
    "LAPSED",
    "SUPERSEDED",
]
EXCLUSIVITY_STATUSES = ["ACTIVE", "EXPIRED", "RELEASED"]

# --- DiligenceRequest (PRD 3.4) ---
DILIGENCE_STATUSES = ["OPEN", "RESPONDED", "ESCALATED", "CLEARED", "WAIVED"]

# --- RestrictedFund (PRD 3.6) ---
FUND_STATUSES = [
    "HELD",
    "CONSENT_SOUGHT",
    "CONSENT_GRANTED",
    "CONSENT_DENIED",
    "PETITION_FILED",
    "MODIFIED",
    "TRANSFERRED",
    "RETAINED",
]

# --- BoardApproval (PRD 3.5) ---
APPROVAL_STATUSES = ["RECORDED", "CERTIFIED", "RESCINDED", "SUPERSEDED", "FAILED"]

# --- AGFiling (PRD 3.7) ---
FILING_STATUSES = ["SUBMITTED", "APPROVED", "OBJECTED", "DEEMED_APPROVED"]

# --- IntegrationTask (PRD 3.8) ---
TASK_STATUSES = ["PLANNED", "HELD", "IN_PROGRESS", "COMPLETE", "CANCELLED"]
TASK_WORKSTREAMS = [
    "STAFFING",
    "SYSTEMS",
    "BRANDING",
    "PROGRAM_CONTINUITY",
]

# --- Program (PRD 3.1, 3.8) ---
PROGRAM_CONTINUITY_STATUSES = [
    "ACTIVE",
    "PLANNED_TRANSFER",
    "PLANNED_SUNSET",
    "TRANSFERRED",
    "SUNSET",
]

# --- common field sets (PRD 2.4) ---
FULL_COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]
CREATE_ONLY_COMMON_FIELDS = ["id", "created_at"]
