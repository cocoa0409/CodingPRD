"""In-memory data store. All state lives in module-level dicts keyed by id.
The store starts empty on every boot -- nothing is seeded or preloaded."""

import uuid
from datetime import datetime, timezone

# ----------------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------------
_DEFAULT_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_now = _DEFAULT_NOW


def get_now():
    return _now


def set_now(value):
    global _now
    _now = value


def now_iso():
    """Current logical clock as ISO 8601 UTC with 3 fractional digits (Z)."""
    return iso_z(_now)


def iso_z(dt):
    """Format a datetime as ISO 8601 UTC with millisecond precision and Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


# ----------------------------------------------------------------------------
# Entity stores (all start empty)
# ----------------------------------------------------------------------------
customers = {}
home_assessments = {}
product_models = {}          # keyed by id; lookup by model_code via index
product_models_by_code = {}  # model_code -> id
equipment_units = {}
equipment_by_serial = {}     # serial_number -> id
quotes = {}
funding_applications = {}
agreements = {}
install_jobs = {}
service_plans = {}
warranty_claims = {}
removal_jobs = {}
audit_events = {}
