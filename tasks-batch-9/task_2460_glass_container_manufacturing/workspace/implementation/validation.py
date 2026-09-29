"""Field level validation, auth/RBAC gate and pagination (PRD 2.1, 2.3, 2.10)."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail

ROLES = (
    "PlantManager",
    "PlantScheduler",
    "BatchHouseTech",
    "MoldEngineer",
    "QualityEngineer",
    "WarehouseOperator",
    "CustomerRep",
)

COLORS = ("FLINT", "AMBER", "GREEN")
MOLD_FAMILIES = ("NNPB", "BLOW_BLOW", "PRESS_BLOW")
OWNERS = ("CUSTOMER", "PLANT")
PALLET_STANDARDS = ("EURO_1200x800", "GMA_1200x1000")
DEFECT_CLASSES = ("CRITICAL", "MAJOR", "MINOR")
DEFECT_CODES = (
    "CHECK_CRACK",
    "BIRDSWING",
    "THIN_WALL",
    "STONE",
    "BLISTER",
    "OVERPRESS",
    "SPLIT_FINISH",
)
ATTRIBUTIONS = ("UNDETERMINED", "PLANT", "CUSTOMER", "SHARED")

CAMPAIGN_STATUSES = ("PLANNED", "ACTIVE", "WIND_DOWN", "REBUILD_SCHEDULED", "CLOSED")
COLOR_CHANGE_STATUSES = ("SCHEDULED", "COMPLETED", "ABORTED")
MACHINE_STATUSES = ("IDLE", "RUNNING")
POSTURES = ("OPERATING", "RESTRICTED", "REBUILD_DUE", "COLD")
DESIGN_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "CHANGES_REQUESTED",
    "RISK_SIGNED",
    "APPROVED",
    "OBSOLETE",
)
PROGRAM_STATUSES = (
    "DRAFT",
    "RISK_ASSESSED",
    "PILOT",
    "ADOPTED",
    "SUSPENDED",
    "REJECTED",
    "SUPERSEDED",
)
MOLD_SET_STATUSES = ("AVAILABLE", "MOUNTED", "IN_REPAIR", "SCRAPPED")
JOB_STATUSES = ("SCHEDULED", "RUNNING", "COMPLETED", "ABORTED", "CANCELLED")
QUALITY_STATUSES = ("PENDING_INSPECTION", "RELEASED", "QUARANTINED", "SCRAPPED")
LOGISTICS_STATUSES = ("IN_AGING", "PALLETIZED", "SHIPPED", "RETURNED")
COMPLAINT_STATUSES = ("OPEN", "INVESTIGATING", "CREDIT_ISSUED", "REJECTED")


# --------------------------------------------------------------------------- #
# auth / rbac
# --------------------------------------------------------------------------- #
def authorize(*allowed_roles):
    """PRD 2.10 steps 1-3: authentication precedes authorisation."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        fail("ERR_MISSING_USER_ID")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# --------------------------------------------------------------------------- #
# timestamps
# --------------------------------------------------------------------------- #
def parse_datetime(raw):
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# field specs
# --------------------------------------------------------------------------- #
class Field(object):
    def __init__(
        self,
        name,
        kind,
        required=True,
        choices=None,
        gt=None,
        ge=None,
        lt=None,
        le=None,
        decimals=None,
        min_len=None,
        max_len=None,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.choices = choices
        self.gt = gt
        self.ge = ge
        self.lt = lt
        self.le = le
        self.decimals = decimals
        self.min_len = min_len
        self.max_len = max_len

    def coerce(self, raw):
        name = self.name
        if self.kind == "string":
            if not isinstance(raw, str):
                fail("ERR_VALIDATION", "%s must be a string." % name)
            if self.min_len is not None and len(raw) < self.min_len:
                fail("ERR_VALIDATION", "%s is shorter than %d characters." % (name, self.min_len))
            if self.max_len is not None and len(raw) > self.max_len:
                fail("ERR_VALIDATION", "%s is longer than %d characters." % (name, self.max_len))
            return raw
        if self.kind == "enum":
            if not isinstance(raw, str) or raw not in self.choices:
                fail("ERR_VALIDATION", "%s must be one of %s." % (name, ", ".join(self.choices)))
            return raw
        if self.kind == "boolean":
            if not isinstance(raw, bool):
                fail("ERR_VALIDATION", "%s must be a boolean." % name)
            return raw
        if self.kind == "integer":
            if isinstance(raw, bool) or not isinstance(raw, int):
                fail("ERR_VALIDATION", "%s must be an integer." % name)
            self._range(Decimal(raw))
            return raw
        if self.kind == "number":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                fail("ERR_VALIDATION", "%s must be a number." % name)
            try:
                value = Decimal(str(raw))
            except InvalidOperation:
                fail("ERR_VALIDATION", "%s must be a number." % name)
            if not value.is_finite():
                fail("ERR_VALIDATION", "%s must be a finite number." % name)
            if self.decimals is not None:
                exponent = value.normalize().as_tuple().exponent
                if exponent < -self.decimals:
                    fail(
                        "ERR_VALIDATION",
                        "%s must carry at most %d decimal places." % (name, self.decimals),
                    )
            self._range(value)
            return value
        if self.kind == "datetime":
            value = parse_datetime(raw)
            if value is None:
                fail("ERR_VALIDATION", "%s must be an ISO 8601 timestamp." % name)
            return value
        raise AssertionError("unknown field kind %s" % self.kind)

    def _range(self, value):
        name = self.name
        if self.gt is not None and not value > Decimal(str(self.gt)):
            fail("ERR_VALIDATION", "%s must be greater than %s." % (name, self.gt))
        if self.ge is not None and not value >= Decimal(str(self.ge)):
            fail("ERR_VALIDATION", "%s must be at least %s." % (name, self.ge))
        if self.lt is not None and not value < Decimal(str(self.lt)):
            fail("ERR_VALIDATION", "%s must be less than %s." % (name, self.lt))
        if self.le is not None and not value <= Decimal(str(self.le)):
            fail("ERR_VALIDATION", "%s must be at most %s." % (name, self.le))


def Str(name, required=True, min_len=1, max_len=32):
    return Field(name, "string", required=required, min_len=min_len, max_len=max_len)


def Text(name, required=False, max_len=None):
    return Field(name, "string", required=required, min_len=None, max_len=max_len)


def Num(name, required=True, gt=None, ge=None, lt=None, le=None, decimals=2):
    return Field(name, "number", required=required, gt=gt, ge=ge, lt=lt, le=le, decimals=decimals)


def Int(name, required=True, ge=None, le=None):
    return Field(name, "integer", required=required, ge=ge, le=le)


def Enum(name, choices, required=True):
    return Field(name, "enum", required=required, choices=choices)


def Ts(name, required=True):
    return Field(name, "datetime", required=required)


def Id(name, required=True):
    return Field(name, "string", required=required, min_len=1, max_len=200)


def body():
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return raw


def validate_body(fields):
    """PRD 2.10 step 4 -- each field inspected in isolation."""
    data = body()
    out = {}
    for field in fields:
        if field.name not in data or data[field.name] is None:
            if field.required:
                fail("ERR_VALIDATION", "%s is required." % field.name)
            out[field.name] = None
            continue
        out[field.name] = field.coerce(data[field.name])
    return out


# --------------------------------------------------------------------------- #
# query parameters
# --------------------------------------------------------------------------- #
def pagination():
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def _query_int(name, default, low, high):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw.strip())
    except (ValueError, AttributeError):
        fail("ERR_VALIDATION", "%s must be an integer." % name)
    if low is not None and value < low:
        fail("ERR_VALIDATION", "%s must be at least %d." % (name, low))
    if high is not None and value > high:
        fail("ERR_VALIDATION", "%s must be at most %d." % (name, high))
    return value


def query_enum(name, choices):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in choices:
        fail("ERR_VALIDATION", "%s must be one of %s." % (name, ", ".join(choices)))
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_VALIDATION", "%s must be a boolean." % name)


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def paginate(records, limit, offset):
    total = len(records)
    page = records[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
