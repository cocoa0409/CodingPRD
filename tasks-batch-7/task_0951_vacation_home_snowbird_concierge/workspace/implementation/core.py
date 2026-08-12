"""Core primitives: constants, logical clock, in-memory store, errors, envelope."""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Global constants (SCAFFOLD global_constants)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

TRAVEL_ZONE_Z1_MAX_MILES = Decimal("10")
TRAVEL_ZONE_Z2_MAX_MILES = Decimal("25")
TRAVEL_ZONE_Z3_MAX_MILES = Decimal("60")
TRAVEL_SURCHARGE = {"Z1": 0, "Z2": 1500, "Z3": 3800}

VISIT_BASE_FEE_SCHEDULED_CENTS = 6500
VISIT_BASE_FEE_UNSCHEDULED_CENTS = 11000
OWNER_REQUEST_EXPEDITE_FEE_CENTS = 2500
AFTER_HOURS_START_HOUR_UTC = 22
AFTER_HOURS_END_HOUR_UTC = 6
AFTER_HOURS_MULTIPLIER = Decimal("1.35")

CYCLE_LENGTH_DAYS = 30
PRORATION_DAY_BASIS = 30
ENTITLEMENT_ROLLOVER_CAP_UNITS = 2
ENTITLEMENT_CONSUMING_TRIGGER_SOURCE = "SCHEDULED"
ENTITLEMENT_CONSUMING_VISIT_TYPES = ["ROUTINE_WATCH", "SEASONAL_CLOSE", "SEASONAL_OPEN"]

FREEZE_SETPOINT_DEFAULT_F = 55
FREEZE_TOLERANCE_BAND_F = Decimal("3")
FREEZE_RISK_WEIGHT_DELTA = Decimal("6.0")
FREEZE_RISK_DELTA_CAP = Decimal("60.0")
FREEZE_RISK_WEIGHT_WINTERIZATION = Decimal("25.0")
FREEZE_RISK_WEIGHT_VACANCY = Decimal("15.0")
FREEZE_RISK_SCORE_MAX = Decimal("100.0")
FREEZE_RISK_ELEVATED_THRESHOLD = Decimal("30.0")
FREEZE_RISK_CRITICAL_THRESHOLD = Decimal("60.0")

WINTERIZATION_REQUIRED_STEP_COUNT = 4
WINTERIZATION_REQUIRED_STEPS = ["WATER_SHUTOFF", "LINES_DRAINED", "THERMOSTAT_SET", "VALVE_TAGGED"]
WINTERIZATION_OPTIONAL_STEPS = ["ANTIFREEZE_ADDED"]
WINTERIZATION_MIN_THERMOSTAT_F = Decimal("50")

STORM_TIER_WATCH_MAX_HOURS = Decimal("48")
STORM_TIER_WARNING_MAX_HOURS = Decimal("24")
STORM_TIER_IMMINENT_MAX_HOURS = Decimal("6")
STORM_SWEEP_LEAD_HOURS = {"FORECAST": 48, "WATCH": 36, "WARNING": 18, "IMMINENT": 2}
STORM_ASSESSMENT_SLA_HOURS = 72
STORM_SURCHARGE_PCT = {"FORECAST": 0.0, "WATCH": 0.10, "WARNING": 0.20, "IMMINENT": 0.35}
STORM_GUARANTEE_CREDIT_CENTS = 15000
STORM_GUARANTEE_CREDIT_PCT = Decimal("0.50")
STORM_EMERGENCY_APPROVAL_CEILING_CENTS = 250000

WO_OWNER_APPROVAL_CEILING_CENTS = 50000
WO_MAX_DISPATCH_ATTEMPTS = 3
LABOUR_RATE_DEFAULT_CENTS_PER_HOUR = 8500
AUTO_DISPATCH_WINDOW_HOURS = 24
AUTO_STORM_WO_LABOUR_HOURS = 2.0
AUTO_STORM_WO_PARTS_CENTS = 25000

FINDING_SEVERITY_WEIGHT = {
    "LOW": Decimal("5.0"), "MEDIUM": Decimal("15.0"),
    "HIGH": Decimal("30.0"), "CRITICAL": Decimal("50.0"),
}
FINDING_RECHECK_WEIGHT = Decimal("8.0")
FINDING_RECHECK_CAP = Decimal("24.0")
FINDING_POSTURE_WEIGHT = {"NORMAL": Decimal("0.0"), "ELEVATED": Decimal("10.0"), "CRITICAL": Decimal("20.0")}
FINDING_SCORE_MAX = Decimal("100.0")

VENDOR_MARKUP_PCT_MANAGED = Decimal("0.18")
VENDOR_MARKUP_PCT_PASS_THROUGH = Decimal("0.05")
VENDOR_MARKUP_VOLUME_RELIEF_PCT = Decimal("0.03")
VENDOR_MARKUP_VOLUME_TIER_BASE_CENTS = 100000
VENDOR_MARKUP_CAP_CENTS = 60000
VENDOR_MIN_RATING = Decimal("3.0")
FINDING_CATEGORY_TRADE_MAP = {
    "PLUMBING": "PLUMBING", "HVAC": "HVAC", "ELECTRICAL": "ELECTRICAL",
    "STRUCTURAL": "GENERAL", "SECURITY": "SECURITY", "PEST": "GENERAL",
    "LANDSCAPE": "LANDSCAPE", "OTHER": "GENERAL",
}

KEY_RETURN_WINDOW_HOURS_PHYSICAL = 48
KEY_RETURN_WINDOW_HOURS_LOCKBOX = 24
KEY_OVERDUE_GRACE_HOURS = 6
KEY_LOST_THRESHOLD_DAYS = 7
REKEY_FEE_CENTS = 32500

MAIL_HOLD_MAX_DAYS = 30
MAIL_HOLD_ABSOLUTE_MAX_DAYS = 60
MAIL_HOLD_EXTENSION_DAYS = 15
MAIL_HOLD_MAX_EXTENSIONS = 2
PACKAGE_OVERFLOW_THRESHOLD_COUNT = 6
MAIL_FORWARD_BASE_CENTS = 1800
MAIL_FORWARD_PER_ITEM_CENTS = 250
HOLD_EXTENSION_FEE_CENTS = 900

FALSE_ALARM_WINDOW_DAYS = 365
FALSE_ALARM_FEES = {1: 0, 2: 5000, 3: 15000, 4: 10000}
FALSE_ALARM_FEE_5_PLUS_CENTS = 25000

TURNOVER_OVERLAP_BUFFER_MINUTES = 90
TURNOVER_MAX_RECLEAN_ATTEMPTS = 2
TURNOVER_ABSORPTION_CREDIT_PCT = Decimal("0.50")

CADENCE_MIN_DAYS = 3
CADENCE_MAX_DAYS = 30
AWAY_PERIOD_MAX_DAYS = 240

TAX_RATE_PCT = Decimal("0.07")
LATE_FEE_PCT = Decimal("0.015")
DELINQUENCY_THRESHOLD_DAYS = 21

ROLES = ["PlatformAdmin", "Owner", "AccountManager", "Dispatcher",
         "FieldTech", "Vendor", "StormCoordinator", "Auditor"]

# ---------------------------------------------------------------------------
# Enum member sets (rung 61 closed routing list + entity enums)
# ---------------------------------------------------------------------------
VISIT_TYPES = ["ROUTINE_WATCH", "SEASONAL_CLOSE", "SEASONAL_OPEN", "TURNOVER_INSPECT",
               "STORM_SECURE", "STORM_ASSESS", "ALARM_RESPONSE"]
TRIGGER_SOURCES = ["SCHEDULED", "OWNER_REQUESTED", "ALARM_TRIGGERED", "STORM"]
DEFER_REASONS = ["TURNOVER_OVERLAP", "OWNER_IN_RESIDENCE", "WEATHER", "ACCESS_BLOCKED", "SUBSCRIPTION_PAUSED"]
SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
CATEGORIES = ["PLUMBING", "HVAC", "ELECTRICAL", "STRUCTURAL", "SECURITY", "PEST", "LANDSCAPE", "OTHER"]
INCIDENT_TYPES = ["ALARM_INTRUSION", "ALARM_SMOKE", "FREEZE_ALARM", "WATER_LEAK", "VANDALISM", "UNAUTHORIZED_ACCESS"]
ALARM_CLASS_TYPES = ["ALARM_INTRUSION", "ALARM_SMOKE", "FREEZE_ALARM", "UNAUTHORIZED_ACCESS"]
FORCED_VISIT_INCIDENT_TYPES = ["ALARM_INTRUSION", "ALARM_SMOKE", "FREEZE_ALARM"]
KEY_TYPES = ["PHYSICAL", "LOCKBOX"]
LINE_TYPES = ["SUBSCRIPTION_FEE", "VISIT_OVERAGE", "TRAVEL_SURCHARGE", "WORK_ORDER", "FALSE_ALARM_FEE",
              "MAIL_DISPOSITION", "REKEY_FEE", "ENTITLEMENT_OFFSET", "GUARANTEE_CREDIT"]
GROSS_SERVICE_LINE_TYPES = ["SUBSCRIPTION_FEE", "VISIT_OVERAGE", "TRAVEL_SURCHARGE", "WORK_ORDER",
                            "FALSE_ALARM_FEE", "MAIL_DISPOSITION", "REKEY_FEE"]
NEGATIVE_LINE_TYPES = ["ENTITLEMENT_OFFSET", "GUARANTEE_CREDIT"]
TIERS = ["BASIC", "STANDARD", "PREMIUM"]
ROLLOVER_POLICIES = ["EXPIRE", "CARRY_CAPPED"]
BILLING_MODES = ["MANAGED", "PASS_THROUGH"]
TRADES = ["PLUMBING", "HVAC", "ELECTRICAL", "GENERAL", "SECURITY", "LOCKSMITH", "LANDSCAPE"]
WORK_TYPES = ["REPAIR", "REKEY", "WINTERIZE_FIX", "STORM_MITIGATION", "CLEANING"]
DAMAGE_LEVELS = ["NONE", "MINOR", "MODERATE", "SEVERE"]
REOPEN_REASONS = ["FREEZE_ALARM", "SPRING_OPEN", "RENTAL_TURNOVER", "INSPECTION_FAIL"]
NOTIFICATION_PREFERENCES = ["EMAIL", "SMS", "BOTH"]
OCCUPANCY_STATES = ["VACANT", "OWNER_IN_RESIDENCE", "RENTAL_OCCUPIED", "CONTRACTOR_ONSITE"]
SEASONAL_STATES = ["OPEN", "CLOSING", "WINTERIZED", "OPENING"]
SEASONAL_ACTIONS = ["BEGIN_CLOSE", "ABORT_CLOSE", "COMPLETE_WINTERIZATION", "BEGIN_OPEN", "COMPLETE_OPEN"]
TURNOVER_STATUSES = ["BOOKED", "CHECKOUT", "CLEANING", "INSPECTION", "READY", "CHECKIN", "CANCELLED"]
STORM_EVENT_STATUSES = ["FORECAST", "WATCH", "WARNING", "IMMINENT", "LANDFALL", "ALL_CLEAR", "CLOSED"]
REVOKE_REASONS = ["OPERATOR", "WINDOW_ELAPSED"]
WINTERIZATION_STEP_CODES = WINTERIZATION_REQUIRED_STEPS + WINTERIZATION_OPTIONAL_STEPS + ["ALL_REQUIRED"]

# Terminal states per state machine (SCAFFOLD 1.2)
TERMINAL_STATES = {
    "subscription": ["CANCELLED"],
    "billing_cycle": ["CLOSED"],
    "visit": ["COMPLETED", "CONVERTED", "ABORTED"],
    "finding": ["DISMISSED"],
    "work_order": ["INVOICED", "VOID"],
    "vendor_assignment": ["DECLINED", "FINISHED", "WITHDRAWN"],
    "vendor": [],
    "key_issuance": ["RETURNED", "RETURNED_LATE", "REKEY_ORDERED"],
    "access_grant": ["EXPIRED", "REVOKED", "INVALIDATED"],
    "winterization_record": [],
    "rental_turnover": ["CHECKIN", "CANCELLED"],
    "mail_hold": ["RELEASED", "FORWARDED"],
    "security_incident": ["RESOLVED", "FALSE_ALARM"],
    "storm_event": ["CLOSED"],
    "storm_response": ["CLOSED"],
    "invoice": ["PAID", "VOID"],
    "invoice_line": [],
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401, "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403, "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_ASSIGNED_VENDOR": 403, "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_WORK_ORDER_PIPELINE_MISMATCH": 403,
    "ERR_RESOURCE_NOT_FOUND": 404, "ERR_OWNER_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404, "ERR_SERVICE_PLAN_NOT_FOUND": 404,
    "ERR_TEMPLATE_NOT_FOUND": 404, "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404, "ERR_LINKED_RESOURCE_NOT_FOUND": 404,
    "ERR_STALE_FINDING_VERSION": 412, "ERR_STALE_SUBSCRIPTION_VERSION": 412,
    "ERR_STALE_KEY_ASSET_VERSION": 412, "ERR_STALE_STORM_RESPONSE_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409, "ERR_ALREADY_TERMINAL": 409,
    "ERR_VISIT_NOT_ARRIVED": 409, "ERR_PARENT_VISIT_NOT_COMPLETED": 409,
    "ERR_NO_RECHECK_VISIT": 409, "ERR_FINDING_HAS_LIVE_WORK_ORDER": 409,
    "ERR_SEVERITY_TOO_HIGH_TO_MONITOR": 409, "ERR_DISPATCH_ATTEMPTS_EXHAUSTED": 409,
    "ERR_RECLEAN_ATTEMPTS_EXHAUSTED": 409, "ERR_HOLD_EXTENSIONS_EXHAUSTED": 409,
    "ERR_STORM_NOT_ALL_CLEAR": 409, "ERR_STORM_RESPONSES_OPEN": 409,
    "ERR_INVOICE_ALREADY_PAID": 409, "ERR_CYCLE_HAS_LIVE_VISIT": 409,
    "ERR_PLAN_RETIRED": 409, "ERR_SUBSCRIPTION_CANCELLED": 409,
    "ERR_VISIT_IN_FLIGHT": 409, "ERR_APPROVAL_REQUIRED": 409,
    "ERR_STORM_CEILING_EXCEEDED": 409, "ERR_ISSUANCE_NOT_OVERDUE": 409,
    "ERR_LOST_THRESHOLD_NOT_MET": 409, "ERR_STEP_ALREADY_RECORDED": 409,
    "ERR_TURNOVER_STAGE_INVALID": 409, "ERR_NO_TURNOVER_OVERLAP": 409,
    "ERR_PACKAGES_OUTSTANDING": 409, "ERR_MAIL_HOLD_NOT_STARTED": 409,
    "ERR_INCIDENT_NOT_ALARM_CLASS": 409, "ERR_SEVERITY_TOO_LOW_TO_ESCALATE": 409,
    "ERR_STORM_REGION_MISMATCH": 409, "ERR_INVOICE_NOT_DRAFT": 409,
    "ERR_LINE_ALREADY_VOID": 409, "ERR_VISIT_TYPE_NOT_COVERED": 409,
    "ERR_SEASONAL_STATE_FORBIDS_VISIT": 409, "ERR_TURNOVER_IN_FLIGHT": 409,
    "ERR_WINTERIZATION_INCOMPLETE": 409, "ERR_KEY_CUSTODY_BLOCKS_OPEN": 409,
    "ERR_NO_SEASONAL_OPEN_VISIT": 409, "ERR_PROPERTY_HAS_OPEN_STORM_HOLD": 409,
    "ERR_OCCUPANCY_FORBIDS_VISIT": 409, "ERR_RENTAL_NOT_ENROLLED": 409,
    "ERR_SEASONAL_STATE_FORBIDS_OCCUPANCY": 409, "ERR_VENDOR_NOT_ELIGIBLE": 409,
    "ERR_VENDOR_COI_EXPIRED": 409, "ERR_VENDOR_LICENSE_EXPIRED": 409,
    "ERR_VENDOR_NOT_EMERGENCY_CAPABLE": 409, "ERR_NO_ELIGIBLE_VENDOR": 409,
    "ERR_VENDOR_WINDOW_CONFLICT": 409, "ERR_VENDOR_RATING_BELOW_FLOOR": 409,
    "ERR_VENDOR_KEY_OVERDUE": 409, "ERR_KEY_COPIES_UNAVAILABLE": 409,
    "ERR_KEY_REKEY_PENDING": 409, "ERR_ACCESS_CAPACITY_EXCEEDED": 409,
    "ERR_ACCESS_GRANT_INVALID": 409, "ERR_GRANT_WINDOW_NOT_OPEN": 409,
    "ERR_NO_ACTIVE_SUBSCRIPTION": 409, "ERR_PROPERTY_OUT_OF_AREA": 409,
    "ERR_NO_OPEN_CYCLE": 409, "ERR_NOT_YET_DELINQUENT": 409,
    "ERR_BALANCE_STILL_OUTSTANDING": 409, "ERR_INVOICE_HAS_NO_LINES": 409,
    "ERR_PAYMENT_AMOUNT_INVALID": 409, "ERR_ENTITLEMENT_EXHAUSTED": 409,
    "ERR_MISSING_REQUIRED_FIELD": 400, "ERR_INVALID_FIELD_TYPE": 400,
    "ERR_INVALID_ENUM_VALUE": 400, "ERR_VALUE_OUT_OF_RANGE": 400,
    "ERR_CHECKLIST_MISMATCH": 400, "ERR_INTERVAL_MALFORMED": 400,
    "ERR_TURNOVER_WINDOW_OVERLAP": 409, "ERR_HOLD_TOO_LONG": 400,
    "ERR_AWAY_PERIOD_INVALID": 400, "ERR_TEMPLATE_TYPE_MISMATCH": 400,
    "ERR_UNIQUENESS_VIOLATION": 409, "ERR_LINE_SIGN_INVALID": 400,
    "ERR_WINTERIZATION_STEP_INVALID": 400, "ERR_THERMOSTAT_BELOW_MINIMUM": 400,
    "ERR_FORWARDING_ADDRESS_MISSING": 400, "ERR_LANDFALL_ETA_IN_PAST": 400,
    "ERR_PAGINATION_INVALID": 400, "ERR_CLOCK_REGRESSION": 400,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Datetime handling
# ---------------------------------------------------------------------------
UTC = timezone.utc


def parse_iso(value):
    """Strict ISO-8601 instant parser.

    Accepts YYYY-MM-DDTHH:MM[:SS[.ffffff]] followed by a mandatory zone
    designator ('Z', '+HH:MM', '-HH:MM', '+HHMM', '-HHMM').  A space separator
    or a missing zone designator is rejected.  Returns an aware UTC datetime,
    or None when the input is not a parseable instant.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or "T" not in s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        body, zone = s[:-1], "+00:00"
    else:
        # find the zone designator after the time part
        idx = max(s.rfind("+"), s.rfind("-"))
        if idx <= 10:  # no offset after the date portion
            return None
        body, zone = s[:idx], s[idx:]
        if len(zone) == 5 and ":" not in zone:
            zone = zone[:3] + ":" + zone[3:]
        if len(zone) != 6 or zone[3] != ":":
            return None
    try:
        dt = datetime.fromisoformat(body + zone)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(UTC)


def fmt_iso(dt):
    """Canonical rendering: ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        parsed = parse_iso(dt)
        if parsed is None:
            return dt
        dt = parsed
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# Money / rounding helpers  (round half away from zero)
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half away from zero to `places` decimals."""
    d = D(value)
    q = Decimal(1).scaleb(-places)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(rhu(value, 0))


def rhu1(value):
    return float(rhu(value, 1))


# ---------------------------------------------------------------------------
# In-memory store (no persistence of any kind; wiped on every process start)
# ---------------------------------------------------------------------------
COLLECTIONS = [
    "owners", "properties", "service_plans", "subscriptions", "billing_cycles",
    "away_periods", "checklist_templates", "visits", "findings", "vendors",
    "work_orders", "vendor_assignments", "key_assets", "key_issuances",
    "access_grants", "winterization_records", "rental_turnovers", "mail_holds",
    "security_incidents", "storm_events", "storm_responses", "invoices",
    "invoice_lines",
]


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.data = {name: {} for name in COLLECTIONS}
        self.seq = 0
        self.clock = parse_iso(CLOCK_DEFAULT_UTC)

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def rows(collection):
    """Every row of a collection in ascending (created_at, insertion) order."""
    return sorted(db.data[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return db.data[collection].get(row_id)


def new_row(collection, **fields):
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["created_at"] = now()
    row["updated_at"] = now()
    row["version"] = 1
    row["_seq"] = db.next_seq()
    row["_collection"] = collection
    db.data[collection][row["id"]] = row
    created = getattr(g, "created_rows", None)
    if created is None:
        created = set()
        g.created_rows = created
    created.add(row["id"])
    return row


def touch(row):
    """One version increment per mutated row per request (PRD 2.4)."""
    if row is None:
        return row
    created = getattr(g, "created_rows", None) or set()
    if row["id"] in created:
        row["updated_at"] = now()
        return row
    touched = getattr(g, "touched_rows", None)
    if touched is None:
        touched = set()
        g.touched_rows = touched
    row["updated_at"] = now()
    if row["id"] not in touched:
        touched.add(row["id"])
        row["version"] += 1
    return row


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_timestamp()}


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), ERROR_STATUS.get(error_id, 400)
