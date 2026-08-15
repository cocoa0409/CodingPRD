"""Shared helpers: timestamps, rounding, ids, enums, body validation, pagination."""

import re
import uuid
from datetime import datetime, timezone

from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_ENUM


# ---------------------------------------------------------------------------
# Enum member sets (from SCAFFOLD entity field constraints)
# ---------------------------------------------------------------------------
NETWORKS = ("VISA", "MASTERCARD")
RISK_TIERS = ("STANDARD", "HIGH_RISK")
RESERVE_MODES = ("FIXED_TIER", "EXPOSURE_BASED")
MERCHANT_STATUSES = ("ACTIVE", "SUSPENDED")
RULE_CATEGORIES = ("FRAUD", "AUTHORIZATION", "PROCESSING_ERROR", "CONSUMER_DISPUTE")
TRANSACTION_STATUSES = ("SETTLED", "REFUNDED", "CHARGED_BACK")
CASE_STATUSES = (
    "RECEIVED", "MERCHANT_NOTIFIED", "REPRESENTED", "DECIDED_WON", "DECIDED_LOST",
    "MERCHANT_ACCEPTED", "PRE_ARBITRATION", "EXPIRED", "REVERSED",
)
OPEN_CASE_STATUSES = ("RECEIVED", "MERCHANT_NOTIFIED", "REPRESENTED", "PRE_ARBITRATION")
FUNDS_STATUSES = ("MERCHANT_DEBITED", "FUNDS_RETURNED", "DEBIT_FINAL", "NOT_DEBITED")
EVIDENCE_TYPES = (
    "RECEIPT", "AVS_MATCH", "CVV_MATCH", "DELIVERY_PROOF", "SIGNED_AGREEMENT",
    "REFUND_PROOF", "PRIOR_TXN_HISTORY", "IP_DEVICE_LOG", "CARDHOLDER_COMMUNICATION",
)
EVIDENCE_STATUSES = ("DRAFT", "ATTACHED", "WITHDRAWN")
REPRESENTMENT_STATUSES = (
    "ASSEMBLED", "SUBMITTED", "WON", "PARTIAL_WON", "LOST", "RETURNED_FOR_CURE", "SUPERSEDED",
)
FEE_KINDS = ("CHARGEBACK_FEE", "PROGRAM_FINE", "ARBITRATION_FEE")
FEE_STATUSES = ("ASSESSED", "SETTLED", "WAIVED")
PROGRAM_CODES = ("VDMP_STANDARD", "VDMP_EXCESSIVE", "ECM", "HECM")
ENROLLMENT_STATUSES = ("ACTIVE", "REMEDIATION", "EXITED")
ROOT_CAUSE_CODES = ("FRAUD_GAP", "FULFILLMENT_GAP", "CUSTOMER_SERVICE_GAP", "POLICY_GAP")
PLAN_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "RETURNED")
ALERT_TYPES = ("FRAUD_ALERT", "DISPUTE_ALERT", "REFUND_OPPORTUNITY")
ALERT_STATUSES = ("OPEN", "ACTIONED_REFUND", "DISMISSED", "EXPIRED")
MODULE_CODES = ("CHARGEBACK_BASICS", "EVIDENCE_BEST_PRACTICE", "FRAUD_PREVENTION")
ASSIGNMENT_STATUSES = ("ASSIGNED", "COMPLETED")
NETWORK_OUTCOMES = ("WON", "PARTIAL_WON", "LOST", "RETURNED_FOR_CURE")
PRE_ARB_DECISIONS = ("WON", "LOST")
PLAN_REVIEW_DECISIONS = ("APPROVE", "RETURN")
ALERT_ACTIONS = ("REFUND", "DISMISS")

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

ALERT_RESPONSE_HOURS = 72
MAX_CURES = 1
ZERO_DENOMINATOR_SENTINEL_BPS = 100000
EXPOSURE_MULTIPLIER = 2


# ---------------------------------------------------------------------------
# Timestamps: ISO 8601 UTC with three fractional digits (PRD 2.4)
# ---------------------------------------------------------------------------
def iso3(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def month_of(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m")


# ---------------------------------------------------------------------------
# Rounding: integer round-half-up via Decimal (PRD 2.6); never float for money
# ---------------------------------------------------------------------------
def rhu(numer, denom=1):
    """round_half_up(numer / denom) to an integer."""
    return int((Decimal(int(numer)) / Decimal(int(denom))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Request body extraction with deferred payload-shape errors (PRD 2.9:
# payload-shape validation ranks last, priority 11).
# ---------------------------------------------------------------------------
class Body:
    def __init__(self, data):
        self.d = data if isinstance(data, dict) else {}
        self.err = None  # (error_id, message), first recorded wins

    def _fail(self, pair, message):
        if self.err is None:
            self.err = (pair, message)

    def raise_pending(self):
        if self.err is not None:
            pair, message = self.err
            raise ApiError(pair[1], pair[0], message)

    def present(self, name):
        return name in self.d and self.d[name] is not None

    def req_str(self, name):
        v = self.d.get(name)
        if not isinstance(v, str) or not v:
            self._fail(ERR_INVALID_REQUEST, "Field '%s' is required and must be a non-empty string" % name)
            return None
        return v

    def opt_str(self, name):
        if name not in self.d or self.d[name] is None:
            return None
        v = self.d[name]
        if not isinstance(v, str):
            self._fail(ERR_INVALID_REQUEST, "Field '%s' must be a string" % name)
            return None
        return v

    def req_int(self, name, minv=None, maxv=None):
        v = self.d.get(name)
        if not is_int(v):
            self._fail(ERR_INVALID_REQUEST, "Field '%s' is required and must be an integer" % name)
            return None
        if minv is not None and v < minv:
            self._fail(ERR_INVALID_REQUEST, "Field '%s' must be >= %s" % (name, minv))
            return None
        if maxv is not None and v > maxv:
            self._fail(ERR_INVALID_REQUEST, "Field '%s' must be <= %s" % (name, maxv))
            return None
        return v

    def opt_int(self, name, minv=None, maxv=None):
        if name not in self.d or self.d[name] is None:
            return None
        v = self.d[name]
        if not is_int(v):
            self._fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer" % name)
            return None
        if minv is not None and v < minv:
            self._fail(ERR_INVALID_REQUEST, "Field '%s' must be >= %s" % (name, minv))
            return None
        if maxv is not None and v > maxv:
            self._fail(ERR_INVALID_REQUEST, "Field '%s' must be <= %s" % (name, maxv))
            return None
        return v

    def req_enum(self, name, members):
        if name not in self.d or self.d[name] is None:
            self._fail(ERR_INVALID_REQUEST, "Field '%s' is required" % name)
            return None
        v = self.d[name]
        if not isinstance(v, str) or v not in members:
            self._fail(ERR_INVALID_ENUM, "Field '%s' must be one of %s" % (name, ", ".join(members)))
            return None
        return v

    def opt_enum(self, name, members, default=None):
        if name not in self.d or self.d[name] is None:
            return default
        v = self.d[name]
        if not isinstance(v, str) or v not in members:
            self._fail(ERR_INVALID_ENUM, "Field '%s' must be one of %s" % (name, ", ".join(members)))
            return None
        return v

    def req_dt(self, name):
        v = self.d.get(name)
        if v is None:
            self._fail(ERR_INVALID_REQUEST, "Field '%s' is required" % name)
            return None
        try:
            return parse_iso(v)
        except (ValueError, TypeError):
            self._fail(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 UTC instant" % name)
            return None

    def opt_dt(self, name):
        if name not in self.d or self.d[name] is None:
            return None
        try:
            return parse_iso(self.d[name])
        except (ValueError, TypeError):
            self._fail(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 UTC instant" % name)
            return None

    def req_list(self, name, min_len=None):
        v = self.d.get(name)
        if not isinstance(v, list):
            self._fail(ERR_INVALID_REQUEST, "Field '%s' is required and must be an array" % name)
            return None
        if min_len is not None and len(v) < min_len:
            self._fail(ERR_INVALID_REQUEST, "Field '%s' must contain at least %d item(s)" % (name, min_len))
            return None
        return v

    def req_enum_list(self, name, members, min_len=None):
        v = self.req_list(name, min_len=min_len)
        if v is None:
            return None
        for item in v:
            if not isinstance(item, str) or item not in members:
                self._fail(ERR_INVALID_ENUM, "Field '%s' entries must be one of %s" % (name, ", ".join(members)))
                return None
        return v

    def req_str_list(self, name, min_len=None):
        v = self.req_list(name, min_len=min_len)
        if v is None:
            return None
        for item in v:
            if not isinstance(item, str):
                self._fail(ERR_INVALID_REQUEST, "Field '%s' entries must be strings" % name)
                return None
        return v

    def req_month(self, name):
        v = self.d.get(name)
        if not isinstance(v, str) or not MONTH_RE.match(v):
            self._fail(ERR_INVALID_REQUEST, "Field '%s' must be a calendar month in YYYY-MM format" % name)
            return None
        return v


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0
# ---------------------------------------------------------------------------
def pagination_params(args):
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise ApiError(400, "ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(400, "ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise ApiError(400, "ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer")
        if offset < 0:
            raise ApiError(400, "ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0")
    return limit, offset


def filter_enum(args, name, members):
    """Validate an enum-typed list filter; None when absent."""
    v = args.get(name)
    if v is None:
        return None
    if v not in members:
        raise ApiError(400, "ERR_INVALID_ENUM", "Query parameter '%s' must be one of %s" % (name, ", ".join(members)))
    return v
