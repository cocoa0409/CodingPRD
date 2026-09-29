"""Enum value tuples and status-dimension vocabularies for the program API.

Transcribed from the PRD so a test can name a legal value without repeating a
raw string literal, and so illegal-enum tests can assert against the real set.
"""

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------

ROLE_CSP_LEAD = "CspComplianceLead"
ROLE_ASSESSOR = "ThirdPartyAssessor"
ROLE_AGENCY_OFFICIAL = "AgencyAuthorizingOfficial"
ROLE_BOARD_REVIEWER = "ProgramBoardReviewer"

ALL_ROLES = (
    ROLE_CSP_LEAD,
    ROLE_ASSESSOR,
    ROLE_AGENCY_OFFICIAL,
    ROLE_BOARD_REVIEWER,
)

# ---------------------------------------------------------------------------
# Agency (PRD 3.1)
# ---------------------------------------------------------------------------

AGENCY_STATUSES = ("ACTIVE", "INACTIVE")

# ---------------------------------------------------------------------------
# CloudServiceOffering (PRD 3.2, 3.3, 3.7, 3.8, 3.9)
# ---------------------------------------------------------------------------

SERVICE_MODELS = ("IAAS", "PAAS", "SAAS")
DEPLOYMENT_MODELS = ("GOV_COMMUNITY", "PUBLIC", "HYBRID", "PRIVATE")
AUTHORIZATION_PATHS = ("AGENCY_SPONSORED", "PROGRAM_BOARD")

OFFERING_STATUSES = (
    "DRAFT",
    "CATEGORIZED",
    "PATH_SELECTED",
    "IN_ASSESSMENT",
    "PACKAGE_SUBMITTED",
    "AUTHORIZED",
    "CHANGE_UNDER_REVIEW",
    "SUSPENDED",
)

# ---------------------------------------------------------------------------
# DataCategory (PRD 3.2)
# ---------------------------------------------------------------------------

DATA_CATEGORY_STATUSES = ("DECLARED", "CONFIRMED", "WITHDRAWN")
DATA_CATEGORY_DECISIONS = ("CONFIRM", "WITHDRAW")

# ---------------------------------------------------------------------------
# ControlImplementation (PRD 3.4)
# ---------------------------------------------------------------------------

IMPLEMENTATION_STATUSES = (
    "IMPLEMENTED",
    "PARTIALLY_IMPLEMENTED",
    "PLANNED",
    "ALTERNATIVE_IMPLEMENTATION",
    "NOT_APPLICABLE",
)

#: Only these two count toward customer-responsibility-matrix coverage.
COVERAGE_COUNTING_STATUSES = ("IMPLEMENTED", "PARTIALLY_IMPLEMENTED")

# ---------------------------------------------------------------------------
# AssessmentEngagement and TestSlot (PRD 3.5)
# ---------------------------------------------------------------------------

ENGAGEMENT_STATUSES = (
    "DRAFT",
    "PLAN_SUBMITTED",
    "PLAN_APPROVED",
    "TESTING",
    "REPORT_DELIVERED",
    "VOIDED",
)

PLAN_DECISIONS = ("APPROVE", "REJECT")

TEST_SLOT_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")

#: Slot statuses that occupy their interval and their hours.
TEST_SLOT_ACTIVE_STATUSES = ("SCHEDULED", "COMPLETED")

# ---------------------------------------------------------------------------
# PoamItem (PRD 2.12, 3.6)
# ---------------------------------------------------------------------------

SEVERITIES = ("HIGH", "MODERATE", "LOW")
POAM_SOURCES = ("ASSESSMENT", "SCAN", "SELF_IDENTIFIED")

REMEDIATION_STATUSES = ("OPEN", "IN_REMEDIATION", "AWAITING_VERIFICATION", "CLOSED")
RISK_DISPOSITIONS = (
    "NONE",
    "DEVIATION_REQUESTED",
    "EXTENSION_GRANTED",
    "RISK_ACCEPTED",
    "FALSE_POSITIVE_ACCEPTED",
)

#: The population contributing to residual risk.
RISK_BEARING_REMEDIATION_STATUSES = ("OPEN", "IN_REMEDIATION", "AWAITING_VERIFICATION")

CLOSURE_REASONS = ("REMEDIATED", "FALSE_POSITIVE", "SUPERSEDED")

REMEDIATION_ACTIONS = ("START", "SUBMIT_EVIDENCE", "VERIFY_CLOSE", "REOPEN")

#: Which role owns which remediation action (PRD 3.6).
REMEDIATION_ACTIONS_BY_LEAD = ("START", "SUBMIT_EVIDENCE")
REMEDIATION_ACTIONS_BY_ASSESSOR = ("VERIFY_CLOSE", "REOPEN")

POAM_RISK_TIERS = ("NONE", "LOW", "MODERATE", "ELEVATED")

# ---------------------------------------------------------------------------
# DeviationRequest (PRD 3.6)
# ---------------------------------------------------------------------------

DEVIATION_KINDS = ("OPERATIONAL_REQUIREMENT", "FALSE_POSITIVE", "RISK_ADJUSTMENT")
DEVIATION_STATUSES = ("SUBMITTED", "BOARD_REVIEW", "AGENCY_REVIEW", "APPROVED", "DENIED")
REVIEW_QUEUES = ("BOARD", "AGENCY")
DEVIATION_DECISIONS = ("APPROVE", "DENY")

#: Deviation statuses that block a VERIFY_CLOSE.
DEVIATION_PENDING_STATUSES = ("SUBMITTED", "BOARD_REVIEW", "AGENCY_REVIEW")

# ---------------------------------------------------------------------------
# AuthorizationPackage (PRD 3.7)
# ---------------------------------------------------------------------------

PACKAGE_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "REVISION_REQUESTED",
    "AUTHORIZED",
    "REJECTED",
    "SUPERSEDED",
)

#: Package statuses counted by an offering's open_package_count.
PACKAGE_OPEN_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED")

PACKAGE_DECISIONS = ("AUTHORIZE", "REJECT")

# ---------------------------------------------------------------------------
# Authorization (PRD 2.12, 3.7)
# ---------------------------------------------------------------------------

AUTHORIZATION_STATUSES = ("AUTHORIZED", "SUSPENDED", "REVOKED", "EXPIRED")
MONITORING_POSTURES = ("ACTIVE", "AT_RISK", "ESCALATED")

# ---------------------------------------------------------------------------
# MonitoringPeriod and ScanSubmission (PRD 3.8)
# ---------------------------------------------------------------------------

MONITORING_PERIOD_STATUSES = ("OPEN", "CLOSED_COMPLIANT", "CLOSED_DEFICIENT")
SCAN_SUBMISSION_STATUSES = ("ACCEPTED", "LATE_ACCEPTED", "REJECTED")

#: Submission statuses that contribute to covered_scan_types.
SCAN_COVERING_STATUSES = ("ACCEPTED", "LATE_ACCEPTED")

# ---------------------------------------------------------------------------
# SignificantChangeRequest (PRD 3.9)
# ---------------------------------------------------------------------------

CHANGE_KINDS = ("BOUNDARY_CHANGE", "NEW_SERVICE", "TECH_REFRESH")
CHANGE_REQUEST_STATUSES = ("SUBMITTED", "APPROVED", "DENIED")

#: Change-request statuses whose windows still block a new window.
CHANGE_BLOCKING_STATUSES = ("SUBMITTED", "APPROVED")

CHANGE_DECISIONS = ("APPROVE", "DENY")

# ---------------------------------------------------------------------------
# ReuseGrant (PRD 3.9)
# ---------------------------------------------------------------------------

REUSE_ACCESS_STATES = (
    "REQUESTED",
    "PACKAGE_ACCESS_GRANTED",
    "INCREMENTAL_REVIEW",
    "REUSE_ACCEPTED",
    "NOTICE_ISSUED",
    "REVOKED",
)

#: Access states that let a grantee agency read the authorization package,
#: and that receive a notice on a deficient period close.
PACKAGE_READ_GRANTING_STATES = (
    "PACKAGE_ACCESS_GRANTED",
    "INCREMENTAL_REVIEW",
    "REUSE_ACCEPTED",
    "NOTICE_ISSUED",
)
NOTICE_ELIGIBLE_STATES = (
    "PACKAGE_ACCESS_GRANTED",
    "INCREMENTAL_REVIEW",
    "REUSE_ACCEPTED",
)

INCREMENTAL_REVIEW_DECISIONS = ("MORE_INFO", "ACCEPT")

# ---------------------------------------------------------------------------
# Audit-field shapes (PRD 2.4)
# ---------------------------------------------------------------------------

#: Resource types that carry only `id` and `created_at`.
IDENTITY_ONLY_RESOURCES = ("ControlBaseline", "ScanSubmission")

AUDIT_TRIPLET_FIELDS = ("created_at", "updated_at", "version")
