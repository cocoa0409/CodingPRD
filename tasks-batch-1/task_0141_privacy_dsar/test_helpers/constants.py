"""Domain thresholds — numeric constants from the PRD's deadline, ack-window,
and erasure-risk computations."""

from datetime import datetime, timedelta, timezone

# Statutory deadline base/extension windows (calendar days), by jurisdiction.
DEADLINE_DAYS = {
    "GDPR_BASE_DAYS": 30,
    "GDPR_EXTENSION_DAYS": 60,
    "CCPA_BASE_DAYS": 45,
    "CCPA_EXTENSION_DAYS": 45,
}

# Processor acknowledgement SLA default (hours).
DEFAULT_SLA_ACK_HOURS = 72

# Erasure-risk per-category sensitivity weights.
CATEGORY_WEIGHT = {
    "HEALTH": 5,
    "FINANCIAL": 4,
    "IDENTITY": 3,
    "CONTACT": 2,
    "BEHAVIORAL": 1,
}

# Identity verification attempt cap (resubmit refused at 3).
MAX_IDENTITY_ATTEMPTS = 3

# A reference instant used by many fixtures as received_at when the test does
# not drive the clock itself. PRD §2.6: the server clock defaults to real
# wall-clock time until a test sets it explicitly. Fixtures that build a request
# and then perform deadline-gated actions (verify-identity, complete-discovery,
# dispatch-fulfillment) without first calling set_clock must therefore anchor
# received_at to a recent past instant so the computed deadline (received_at +
# 30/45 calendar days) still lies in the future relative to "now" — otherwise the
# PRD-faithful implementation correctly refuses those actions with
# ERR_DEADLINE_PASSED. Anchoring two days before now keeps both the GDPR (30-day)
# and CCPA (45-day) deadlines comfortably ahead of the default wall clock.
DEFAULT_RECEIVED_AT = (
    (datetime.now(timezone.utc) - timedelta(days=2))
    .replace(hour=9, minute=0, second=0, microsecond=0)
    .strftime("%Y-%m-%dT%H:%M:%SZ")
)
