"""In-memory data store."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Return current UTC time as ISO 8601 with exactly 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


# ---- stores keyed by id ----
shelters = {}
animals = {}
vaccination_records = {}
adopters = {}
adoption_applications = {}
home_visits = {}
boarding_reservations = {}
boarding_matches = {}
fee_invoices = {}
compliance_holds = {}
fee_schedules = {}
