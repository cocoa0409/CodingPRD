"""Typed aliases for the payload and entity shapes used across the suite.

These are documentation-grade hints only: the API is exercised over HTTP and the
responses arrive as plain dicts.
"""

from typing import Any, Dict, List, Optional, Tuple

# --- Generic aliases -------------------------------------------------------

Headers = Dict[str, str]
Payload = Dict[str, Any]
Entity = Dict[str, Any]
EntityList = List[Entity]
PaginatedResult = Tuple[EntityList, Dict[str, Any]]

# --- Domain vocabularies (PRD sections 3.1 - 3.9) --------------------------

BodyType = str            # COUNCIL | PLANNING_COMMISSION | BOARD_OF_ADJUSTMENT
MeetingType = str         # REGULAR | SPECIAL | EMERGENCY | WORKSHOP
MeetingStatus = str       # SCHEDULED | NOTICED | IN_SESSION | ADJOURNED | CANCELLED
VenueStatus = str         # AVAILABLE | CLOSED
PacketStatus = str        # DRAFT | POSTED | SUPERSEDED | WITHDRAWN
ItemType = str            # CONSENT | PUBLIC_HEARING | ... | REPORT
MotionType = str          # ORDINANCE_ADOPTION | ... | PROCEDURAL
MajorityRule = str        # SIMPLE | TWO_THIRDS | FOUR_FIFTHS | UNANIMOUS_CONSENT
MotionStatus = str        # SECONDED | TALLIED | WITHDRAWN
MotionOutcome = str       # PENDING | PASSED | FAILED | TIE_BROKEN_PASSED | TIE_BROKEN_FAILED
MinutesStatus = str       # DRAFT | SUBMITTED | APPROVED | CORRECTION_PENDING
InstrumentClass = str     # ORDINANCE | RESOLUTION
OrdinanceCategory = str   # GENERAL | ZONING | CODE_AMENDMENT | EMERGENCY
InstrumentStatus = str    # INTRODUCED | ... | EFFECTIVE | FAILED
NoticeType = str          # ORDINANCE_SUMMARY | ORDINANCE_FULL_TEXT | MEETING_AGENDA | ...
NoticeStatus = str        # DRAFT | ORDERED | PUBLISHED | VOID
CycleStatus = str         # OPEN | LOCKED | CERTIFIED
SubmissionStatus = str    # PENDING | IN_REVIEW | CONFLICT_HELD | ACCEPTED | REJECTED | WITHDRAWN
SubmissionOrigin = str    # CLIENT | CASCADE
SubmissionAction = str    # ADD | AMEND | REPEAL
ResolutionBasis = str     # LATER_ADOPTION_WINS | SPECIFIC_OVER_GENERAL | MANUAL_OVERRIDE
FulfillmentStatus = str   # RECEIVED | UNDER_REVIEW | ... | CLOSED | WITHDRAWN
FeeStatus = str           # NOT_ASSESSED | ASSESSED | DEPOSIT_HELD | PAID | WAIVED | REFUNDED
FeeVariant = str          # ACTUAL_COST | FLAT_SCHEDULE
DeliveryMedium = str      # PAPER | ELECTRONIC
Disposition = str         # FULL_RELEASE | PARTIAL_RELEASE | DENIAL
RetentionTrigger = str    # CREATION | FISCAL_YEAR_END | REQUEST_CLOSURE
LegalHoldStatus = str     # NONE | LITIGATION_HOLD | AUDIT_HOLD
BatchStatus = str         # PROPOSED | CERTIFIED | RESCINDED

# --- Composite fixture shapes ---------------------------------------------

FeeLine = Dict[str, Any]        # { page_count, staff_minutes, delivery_medium }
FeeLines = List[FeeLine]
PublicationDates = List[str]
ExemptionClaims = List[str]

OptionalStr = Optional[str]
OptionalInt = Optional[int]
