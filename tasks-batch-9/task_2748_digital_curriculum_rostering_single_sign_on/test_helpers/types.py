"""
Domain enumerations for the Digital Curriculum Rostering & Single Sign-On API.

Every value below is a literal enum member declared by the PRD. Tests import
these instead of hard-coding strings so that a typo becomes an ImportError
rather than a silent assertion mismatch.
"""


class GradeBand:
    """School.grade_band / members of VendorApp.grade_band_scope."""

    ELEMENTARY = "ELEMENTARY"
    MIDDLE = "MIDDLE"
    HIGH = "HIGH"
    ALL = ["ELEMENTARY", "MIDDLE", "HIGH"]


class SchoolStatus:
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class TermState:
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    ROLLED_OVER = "ROLLED_OVER"


class EmploymentStatus:
    ACTIVE = "ACTIVE"
    SEPARATED = "SEPARATED"


class EnrollmentState:
    """Student.enrollment_state."""

    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    MERGED_DUPLICATE = "MERGED_DUPLICATE"


class Subject:
    MATH = "MATH"
    ELA = "ELA"
    SCIENCE = "SCIENCE"
    SOCIAL_STUDIES = "SOCIAL_STUDIES"
    ELECTIVE = "ELECTIVE"


class SectionStatus:
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    CANCELLED = "CANCELLED"


class RosterHealth:
    OK = "OK"
    UNMATCHED_TEACHER = "UNMATCHED_TEACHER"


class MeetingDay:
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    ALL = ["MON", "TUE", "WED", "THU", "FRI"]
    MWF = ["MON", "WED", "FRI"]
    TR = ["TUE", "THU"]


class RosterStatus:
    """Enrollment.roster_status."""

    PENDING_ADD = "PENDING_ADD"
    ACTIVE = "ACTIVE"
    PENDING_DROP = "PENDING_DROP"
    DROPPED = "DROPPED"


class AddDropClass:
    IN_WINDOW = "IN_WINDOW"
    LATE_ADD = "LATE_ADD"


class EnrollmentSource:
    SIS_EXTRACT = "SIS_EXTRACT"
    MANUAL = "MANUAL"


class RosteringStandard:
    ONEROSTER_CSV_1P1 = "ONEROSTER_CSV_1P1"
    ONEROSTER_REST_1P2 = "ONEROSTER_REST_1P2"
    VENDOR_NATIVE_JSON = "VENDOR_NATIVE_JSON"


class IdentifierStrategy:
    SIS_ID = "SIS_ID"
    EMAIL_LOCALPART = "EMAIL_LOCALPART"
    STATE_ID = "STATE_ID"


class NameFormat:
    LAST_FIRST = "LAST_FIRST"
    FIRST_LAST = "FIRST_LAST"


class SeatModel:
    PER_STUDENT = "PER_STUDENT"
    PER_STUDENT_AND_TEACHER = "PER_STUDENT_AND_TEACHER"


class AllocationPolicy:
    PROPORTIONAL_HEADCOUNT = "PROPORTIONAL_HEADCOUNT"
    FIXED_BUILDING_BLOCKS = "FIXED_BUILDING_BLOCKS"


class OveragePolicy:
    BLOCK = "BLOCK"
    POOL_FALLBACK = "POOL_FALLBACK"


class UnmatchedTeacherPolicy:
    HOLD_RUN = "HOLD_RUN"
    SKIP_SECTION = "SKIP_SECTION"


class VendorAppStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RenewalRecommendation:
    RENEW = "RENEW"
    RENEGOTIATE = "RENEGOTIATE"
    DROP = "DROP"


class SyncHealth:
    OK = "OK"
    BLOCKED = "BLOCKED"


class SubjectType:
    """AppAccount.subject_type."""

    STUDENT = "STUDENT"
    TEACHER = "TEACHER"


class SeatStatus:
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class IdentityStatus:
    PENDING_PROVISION = "PENDING_PROVISION"
    PROVISIONED = "PROVISIONED"
    SUSPENDED = "SUSPENDED"
    DEPROVISIONED = "DEPROVISIONED"


class PasswordState:
    TEMP_SET = "TEMP_SET"
    USER_SET = "USER_SET"
    EXPIRED = "EXPIRED"
    LOCKED = "LOCKED"


class RunType:
    FULL = "FULL"
    DELTA = "DELTA"
    ROLLOVER = "ROLLOVER"


class SyncRunState:
    EXTRACTED = "EXTRACTED"
    TRANSFORMED = "TRANSFORMED"
    HELD = "HELD"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ErrorCategory:
    UNMATCHED_TEACHER = "UNMATCHED_TEACHER"
    DUPLICATE_STUDENT = "DUPLICATE_STUDENT"
    MISSING_GRADE_BAND = "MISSING_GRADE_BAND"
    SEAT_SHORTFALL = "SEAT_SHORTFALL"


class ErrorSeverity:
    BLOCKING = "BLOCKING"
    ADVISORY = "ADVISORY"


class ErrorQueueItemStatus:
    OPEN = "OPEN"
    RESOLVED_MATCHED = "RESOLVED_MATCHED"
    RESOLVED_MERGED = "RESOLVED_MERGED"
    DISMISSED = "DISMISSED"


class RenewalBasis:
    """Query value for GET /rostering/vendor-apps/{id}/renewal-summary."""

    FINAL = "final"
    PROVISIONAL = "provisional"
