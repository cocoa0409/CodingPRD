"""State vocabularies, small value objects and instant arithmetic.

The service runs on a logical clock and every "now plus N days" computation is
exact — N times 86400 seconds with no calendar adjustment — so the helpers here
do the same arithmetic the tests need to predict a deadline.
"""

from collections import namedtuple
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# State vocabularies
# ---------------------------------------------------------------------------

SPEC_DRAFT = "DRAFT"
SPEC_RATIFIED = "RATIFIED"
SPEC_DEPRECATED = "DEPRECATED"
SPEC_RETIRED = "RETIRED"

MEMBER_REGISTERED = "REGISTERED"
MEMBER_IP_EXECUTED = "IP_EXECUTED"
MEMBER_TOOLS_GRANTED = "TOOLS_GRANTED"
MEMBER_TOOLS_REVOKED = "TOOLS_REVOKED"
MEMBER_IP_WITHDRAWN = "IP_WITHDRAWN"

LAB_PROVISIONAL = "PROVISIONAL"
LAB_AUTHORIZED = "AUTHORIZED"
LAB_SUSPENDED = "SUSPENDED"
LAB_REVOKED = "REVOKED"

SUB_DRAFT = "DRAFT"
SUB_SUBMITTED = "SUBMITTED"
SUB_IN_REVIEW = "IN_REVIEW"
SUB_RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
SUB_REVIEW_COMPLETE = "REVIEW_COMPLETE"
SUB_CERTIFIED = "CERTIFIED"
SUB_REJECTED = "REJECTED"
SUB_WITHDRAWN = "WITHDRAWN"

REVIEW_PENDING = "PENDING"
REVIEW_APPROVED = "APPROVED"
REVIEW_REJECTED = "REJECTED"
REVIEW_RETURNED = "RETURNED"

DAC_NOT_ISSUED = "NOT_ISSUED"
DAC_ISSUED = "ISSUED"
DAC_REVOKED = "REVOKED"

PLAN_DRAFT = "DRAFT"
PLAN_ISSUED = "ISSUED"
PLAN_IN_EXECUTION = "IN_EXECUTION"
PLAN_COMPLETE = "COMPLETE"
PLAN_VOIDED = "VOIDED"

VOIDED_SUPERSEDED = "SUPERSEDED_BY_NEW_PLAN"
VOIDED_SPEC_DEPRECATED = "SPECIFICATION_DEPRECATED"

SESSION_SCHEDULED = "SCHEDULED"
SESSION_IN_PROGRESS = "IN_PROGRESS"
SESSION_COMPLETE = "COMPLETE"
SESSION_CANCELLED = "CANCELLED"

PLUGFEST_REGISTRATION_OPEN = "REGISTRATION_OPEN"
PLUGFEST_LOCKED = "LOCKED"
PLUGFEST_CLOSED = "CLOSED"
PLUGFEST_CANCELLED = "CANCELLED"

PARTICIPATION_REGISTERED = "REGISTERED"
PARTICIPATION_PASSED = "PASSED"
PARTICIPATION_FAILED = "FAILED"
PARTICIPATION_NO_SHOW = "NO_SHOW"

PUB_UNPUBLISHED = "UNPUBLISHED"
PUB_PUBLISHED = "PUBLISHED"
PUB_SUPPRESSED = "SUPPRESSED"
PUB_WITHDRAWN = "WITHDRAWN"

COMPLIANCE_COMPLIANT = "COMPLIANT"
COMPLIANCE_UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
COMPLIANCE_REMEDIATED = "REMEDIATED"
COMPLIANCE_NONCOMPLIANT = "NONCOMPLIANT"

CASE_OPEN = "OPEN"
CASE_EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
CASE_REMEDIATION_ORDERED = "REMEDIATION_ORDERED"
CASE_REMEDIATED = "REMEDIATED"
CASE_WITHDRAWAL_ORDERED = "WITHDRAWAL_ORDERED"
CASE_CLOSED = "CLOSED"

RECERT_NONE = "NONE"
RECERT_DELTA = "DELTA"
RECERT_FULL = "FULL"
RECERT_REASON_SECURITY_CHANGE = "FIRMWARE_SECURITY_CHANGE"
RECERT_REASON_FEATURE_DELTA = "FIRMWARE_FEATURE_DELTA"
RECERT_REASON_SPEC_DEPRECATED = "SPECIFICATION_DEPRECATED"

# The live submission states that block a specification's retirement.
LIVE_SUBMISSION_STATES = [
    SUB_DRAFT,
    SUB_SUBMITTED,
    SUB_IN_REVIEW,
    SUB_RETURNED_FOR_INFO,
    SUB_REVIEW_COMPLETE,
]

# ---------------------------------------------------------------------------
# Small value objects
# ---------------------------------------------------------------------------

#: One feature set to seed into a draft specification.
FeatureSpec = namedtuple(
    "FeatureSpec",
    ["feature_code", "obligation", "test_case_count", "device_type",
     "security_relevant", "depends_on"],
)


def feature(
    feature_code,
    obligation="MANDATORY",
    test_case_count=10,
    device_type="LIGHTING",
    security_relevant=False,
    depends_on=None,
):
    """Declare one feature set for a specification builder."""
    return FeatureSpec(
        feature_code=feature_code,
        obligation=obligation,
        test_case_count=test_case_count,
        device_type=device_type,
        security_relevant=security_relevant,
        depends_on=depends_on,
    )


def result_line(feature_set_id, outcome="PASS", evidence_hash=None):
    """One entry of a session's ``result_lines`` append."""
    return {
        "feature_set_id": feature_set_id,
        "outcome": outcome,
        "evidence_hash": evidence_hash or "sha256:{}".format(feature_set_id[:16]),
    }


# ---------------------------------------------------------------------------
# Instant arithmetic
# ---------------------------------------------------------------------------

_FORMATS = ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ")


def parse_instant(value):
    """Parse an ISO 8601 UTC instant with or without fractional digits."""
    text = value.replace("+00:00", "Z")
    for fmt in _FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise AssertionError("cannot parse instant {!r}".format(value))


def format_instant(moment):
    """Render an instant in the compact ``...Z`` form the payloads use."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_days(value, days):
    """The instant ``days`` times 86400 seconds after ``value``."""
    return format_instant(parse_instant(value) + timedelta(seconds=days * 86400))


def plus_minutes(value, minutes):
    return format_instant(parse_instant(value) + timedelta(minutes=minutes))


def plus_seconds(value, seconds):
    return format_instant(parse_instant(value) + timedelta(seconds=seconds))


def minutes_between(start, end):
    """Whole minutes between two minute-aligned bounds."""
    delta = parse_instant(end) - parse_instant(start)
    return int(delta.total_seconds() // 60)


def calendar_date(value):
    """The UTC calendar date of an instant, as ``YYYY-MM-DD``."""
    return parse_instant(value).strftime("%Y-%m-%d")


def same_instant(left, right):
    """True when two renderings name the same instant."""
    return parse_instant(left) == parse_instant(right)
