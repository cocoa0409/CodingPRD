"""In-memory data store + logical clock. Store starts empty on every boot."""
from datetime import datetime, timezone

# Logical clock — server startup default is exactly 2026-05-01T00:00:00Z.
# It never falls back to wall-clock time once set.
_logical_now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# Monotonic insertion sequence for stable created_at ordering on ties.
_seq = 0


def now():
    return _logical_now


def set_now(dt):
    global _logical_now
    _logical_now = dt


def next_seq():
    global _seq
    _seq += 1
    return _seq


# Entity stores — plain dicts keyed by id. No seeding, ever.
analysts = {}
customers = {}
accounts = {}
transactions = {}
scenarios = {}
thresholds = {}
alerts = {}
cases = {}
sars = {}
reviews = {}      # ContinuingReview
inquiries = {}    # LawEnforcementInquiry
shares = {}       # InfoShareRequest (314(b))
decisions = {}    # AccountDecision
qa_reviews = {}   # QAReview
