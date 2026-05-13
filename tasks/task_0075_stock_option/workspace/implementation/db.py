"""In-memory data store with UUID generation and timestamp management."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def utc_now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# Tables keyed by id
DB = {
    "option_plans": {},          # plan_id -> OptionPlan dict
    "grant_batches": {},
    "grantees": {},
    "grants": {},
    "exercise_windows": {},
    "corporate_events": {},
    "exercise_price_versions": {},
    "exercise_applications": {},
    "vesting_records": {},
    "tax_events": {},
    "departure_records": {},
    "audit_log": {},
}


def reset():
    for k in DB:
        DB[k] = {}
