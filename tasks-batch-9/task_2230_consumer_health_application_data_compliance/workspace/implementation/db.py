"""In-memory store. No seeding, no preloading -- every table starts empty."""

import uuid
from decimal import Decimal

import clock

TABLES = (
    "app_products",
    "applicability_assessments",
    "data_elements",
    "processing_purposes",
    "element_purpose_mappings",
    "consumers",
    "consent_records",
    "privacy_policy_versions",
    "consumer_requests",
    "deletion_tasks",
    "vendors",
    "geofence_zones",
    "geofence_campaigns",
    "breach_incidents",
    "security_risk_assessments",
)


class Store(object):
    def __init__(self):
        self._seq = 0
        for name in TABLES:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq

    def reset(self):
        self._seq = 0
        for name in TABLES:
            getattr(self, name).clear()


db = Store()


def new_row(table, fields):
    """Insert a fresh row carrying the common envelope fields."""
    stamp = clock.now()
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = db.next_seq()
    getattr(db, table)[row["id"]] = row
    return row


def touch(row):
    """Advance updated_at to the logical now and bump the version counter."""
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1
    return row


def set_fields(row, **fields):
    """Assign fields then touch. Returns True when anything actually moved."""
    changed = False
    for key, value in fields.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def sort_key(row):
    return (row["created_at"], row["_seq"])


def sort_rows(rows):
    return sorted(rows, key=sort_key)


def rows_of(table):
    return sort_rows(list(getattr(db, table).values()))


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(db, table).get(row_id)


def _clean(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        return dict((k, _clean(v)) for k, v in value.items())
    return value


DATE_FIELDS = (
    "compliance_deadline_date",
    "effective_from",
    "effective_to",
)


def serialize(row):
    """Project a stored row into its JSON representation."""
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if hasattr(value, "isoformat") and hasattr(value, "hour"):
            out[key] = clock.fmt(value)
        elif hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        else:
            out[key] = _clean(value)
    return out


def serialize_all(rows):
    return [serialize(r) for r in rows]
