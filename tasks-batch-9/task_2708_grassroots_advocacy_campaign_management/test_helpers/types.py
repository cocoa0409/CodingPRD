"""Domain vocabulary for the grassroots advocacy campaign API test suite.

Every literal here is quoted from the PRD contract: enum members, state names,
role names and channel names. Tests import from this module instead of
repeating bare strings so that a contract-level rename is a one-line change.
"""

from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------
# Roles (PRD "Roles and access")
# --------------------------------------------------------------------------

ROLE_CAMPAIGN_DIRECTOR = "CampaignDirector"
ROLE_FIELD_ORGANIZER = "FieldOrganizer"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_MESSAGE_STRATEGIST = "MessageStrategist"
ROLE_PARTNER_DELEGATE = "PartnerDelegate"
ROLE_SUPPORTER = "Supporter"

ALL_ROLES = [
    ROLE_CAMPAIGN_DIRECTOR,
    ROLE_FIELD_ORGANIZER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_MESSAGE_STRATEGIST,
    ROLE_PARTNER_DELEGATE,
    ROLE_SUPPORTER,
]

# Roles whose X-User-ID must be the id of a row the caller owns.
ENTITY_BACKED_ROLES = [ROLE_PARTNER_DELEGATE, ROLE_SUPPORTER]


# --------------------------------------------------------------------------
# Campaign
# --------------------------------------------------------------------------

CAMPAIGN_DRAFT = "DRAFT"
CAMPAIGN_ACTIVE = "ACTIVE"
CAMPAIGN_CLOSED = "CLOSED"

POSTURE_OPEN = "OPEN"
POSTURE_RESTRICTED = "RESTRICTED"
POSTURE_FROZEN = "FROZEN"

POSTURE_OVERRIDE_NONE = "NONE"
POSTURE_OVERRIDE_FORCE_OPEN = "FORCE_OPEN"
POSTURE_OVERRIDE_FORCE_FROZEN = "FORCE_FROZEN"

CHAMBER_HOUSE = "HOUSE"
CHAMBER_SENATE = "SENATE"
CHAMBER_BOTH = "BOTH"


# --------------------------------------------------------------------------
# Channels and channel-scoped consent
# --------------------------------------------------------------------------

CHANNEL_EMAIL = "EMAIL"
CHANNEL_SMS = "SMS"
CHANNEL_PHONE = "PHONE"

ALL_CHANNELS = [CHANNEL_EMAIL, CHANNEL_SMS, CHANNEL_PHONE]

# The wildcard accepted by the consent log in place of a single channel.
CHANNEL_ALL = "ALL"

CONSENT_GRANTED = "GRANTED"
CONSENT_REVOKED = "REVOKED"
CONSENT_NONE = "NONE"

CONSENT_ACTION_GRANT = "GRANT"
CONSENT_ACTION_REVOKE = "REVOKE"

LAWFUL_BASIS_EXPRESS_WRITTEN = "EXPRESS_WRITTEN"
LAWFUL_BASIS_OPT_IN_FORM = "OPT_IN_FORM"
LAWFUL_BASIS_EVENT_CARD = "EVENT_CARD"
LAWFUL_BASIS_VERBAL_RECORDED = "VERBAL_RECORDED"

ALL_LAWFUL_BASES = [
    LAWFUL_BASIS_EXPRESS_WRITTEN,
    LAWFUL_BASIS_OPT_IN_FORM,
    LAWFUL_BASIS_EVENT_CARD,
    LAWFUL_BASIS_VERBAL_RECORDED,
]


# --------------------------------------------------------------------------
# Supporter
# --------------------------------------------------------------------------

ACQUISITION_PETITION = "PETITION"
ACQUISITION_EVENT = "EVENT"
ACQUISITION_DIGITAL_AD = "DIGITAL_AD"
ACQUISITION_REFERRAL = "REFERRAL"


# --------------------------------------------------------------------------
# Milestone
# --------------------------------------------------------------------------

MILESTONE_COMMITTEE_HEARING = "COMMITTEE_HEARING"
MILESTONE_FLOOR_VOTE = "FLOOR_VOTE"
MILESTONE_RECESS = "RECESS"
MILESTONE_SIGNING = "SIGNING"

MILESTONE_SCHEDULED = "SCHEDULED"
MILESTONE_IN_WINDOW = "IN_WINDOW"
MILESTONE_PASSED = "PASSED"


# --------------------------------------------------------------------------
# Legislator
# --------------------------------------------------------------------------

STANCE_SUPPORT = "SUPPORT"
STANCE_LEAN_SUPPORT = "LEAN_SUPPORT"
STANCE_UNDECIDED = "UNDECIDED"
STANCE_LEAN_OPPOSE = "LEAN_OPPOSE"
STANCE_OPPOSE = "OPPOSE"

TIER_PRIMARY = "PRIMARY"
TIER_SECONDARY = "SECONDARY"
TIER_MONITOR = "MONITOR"


# --------------------------------------------------------------------------
# MessageVariant
# --------------------------------------------------------------------------

VARIANT_DRAFT = "DRAFT"
VARIANT_IN_REVIEW = "IN_REVIEW"
VARIANT_CHANGES_REQUESTED = "CHANGES_REQUESTED"
VARIANT_APPROVED = "APPROVED"
VARIANT_LOCKED = "LOCKED"
VARIANT_RETIRED = "RETIRED"

REVIEW_DECISION_APPROVE = "APPROVE"
REVIEW_DECISION_REQUEST_CHANGES = "REQUEST_CHANGES"

TEST_CELL_ECONOMIC_FRAME = "ECONOMIC_FRAME"
TEST_CELL_MORAL_FRAME = "MORAL_FRAME"
TEST_CELL_URGENCY_FRAME = "URGENCY_FRAME"


# --------------------------------------------------------------------------
# CoalitionPartner and PartnerEndorsement
# --------------------------------------------------------------------------

PARTNER_ACTIVE = "ACTIVE"
PARTNER_WITHDRAWN = "WITHDRAWN"

PARTNER_TIER_ANCHOR = "ANCHOR"
PARTNER_TIER_CORE = "CORE"
PARTNER_TIER_ALLY = "ALLY"

ENDORSEMENT_ACTIVE = "ACTIVE"
ENDORSEMENT_REVOKED = "REVOKED"


# --------------------------------------------------------------------------
# Activation (a "wave")
# --------------------------------------------------------------------------

APPROVAL_PENDING = "PENDING"
APPROVAL_CLEARED = "CLEARED"
APPROVAL_BLOCKED = "BLOCKED"

DELIVERY_SCHEDULED = "SCHEDULED"
DELIVERY_SENDING = "SENDING"
DELIVERY_SENT = "SENT"
DELIVERY_PARTIAL = "PARTIAL"
DELIVERY_ABORTED = "ABORTED"


# --------------------------------------------------------------------------
# ActionRecord
# --------------------------------------------------------------------------

# Records are created in RECORDED, but the creating request resolves that to
# MATCHED or UNMATCHED before it answers, so no caller ever reads it back.
ACTION_RECORDED = "RECORDED"
ACTION_MATCHED = "MATCHED"
ACTION_UNMATCHED = "UNMATCHED"
ACTION_ACKNOWLEDGED = "ACKNOWLEDGED"
ACTION_THANKED = "THANKED"
ACTION_DISPUTED = "DISPUTED"
ACTION_VOIDED = "VOIDED"

DISPUTE_OUTCOME_VOIDED = "VOIDED"
DISPUTE_OUTCOME_REINSTATED = "REINSTATED"


# --------------------------------------------------------------------------
# Spokesperson
# --------------------------------------------------------------------------

TRAINING_UNTRAINED = "UNTRAINED"
TRAINING_TRAINED = "TRAINED"
TRAINING_CERTIFIED = "CERTIFIED"

PUBLICATION_CONSENT_WITHHELD = "WITHHELD"
PUBLICATION_CONSENT_INTERNAL = "INTERNAL"
PUBLICATION_CONSENT_PUBLIC = "PUBLIC"


# --------------------------------------------------------------------------
# DistrictMeeting
# --------------------------------------------------------------------------

MEETING_REQUESTED = "REQUESTED"
MEETING_CONFIRMED = "CONFIRMED"
MEETING_DECLINED = "DECLINED"
MEETING_HELD = "HELD"
MEETING_NO_SHOW = "NO_SHOW"

MEETING_DECISION_CONFIRM = "CONFIRM"
MEETING_DECISION_DECLINE = "DECLINE"


# --------------------------------------------------------------------------
# Convenience type aliases
# --------------------------------------------------------------------------

Json = Dict[str, Any]
JsonList = List[Json]
Headers = Dict[str, str]
Maybe = Optional[Any]
