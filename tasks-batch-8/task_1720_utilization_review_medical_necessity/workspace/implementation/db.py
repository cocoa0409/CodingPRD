"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Logical-clock timestamp: ISO 8601 UTC with three fractional digits."""
    from services.clock import logical_now
    dt = logical_now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Entity stores — keyed by id, all empty at startup
payers = {}
physicians = {}
utilization_cases = {}
admission_reviews = {}
authorization_requests = {}
concurrent_reviews = {}
peer_to_peer_conferences = {}
condition_code_44_requests = {}
avoidable_days = {}
escalation_cases = {}
denial_cases = {}
appeal_cases = {}
audit_events = {}
