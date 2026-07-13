"""Core infrastructure: store, envelope, errors, helpers, calculations."""
import json
import os
import secrets
import string
import uuid
import math
import itertools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start; NO seeding)
# ---------------------------------------------------------------------------
DB = {
    "carriers": {},
    "permits": {},
    "route_segments": {},
    "structures": {},
    "bridge_analyses": {},
    "pilot_cars": {},
    "escort_assignments": {},
    "bonds": {},
    "violations": {},
    "travel_restrictions": {},
}

_seq_counter = itertools.count(1)

# Logical clock (default at startup, never falls back to wall clock)
DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"
STRUCTURE_CLEARANCE_BUFFER_MIN = 30

CLOCK = {"now": None}


def reset_clock():
    CLOCK["now"] = parse_dt(DEFAULT_CLOCK_UTC)


KNOWN_ROLES = {"Carrier", "PermitOfficer", "BridgeEngineer",
               "EnforcementOfficer", "DOTAdmin"}

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_STRUCTURE_NOT_FOUND": 404,
    "ERR_PILOT_CAR_NOT_FOUND": 404,
    "ERR_ROUTE_SEGMENT_NOT_FOUND": 404,
    "ERR_BRIDGE_ANALYSIS_NOT_FOUND": 404,
    "ERR_ESCORT_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_VIOLATION_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_DIMENSIONS": 422,
    "ERR_VALIDITY_WINDOW_INVALID": 422,
    "ERR_STALE_PERMIT_VERSION": 412,
    "ERR_INVALID_PERMIT_STATE": 409,
    "ERR_INVALID_ANALYSIS_STATE": 409,
    "ERR_INVALID_ESCORT_STATE": 409,
    "ERR_INVALID_VIOLATION_STATE": 409,
    "ERR_CARRIER_SUSPENDED": 403,
    "ERR_ROUTE_EMPTY": 422,
    "ERR_ANNUAL_SUPERLOAD_FORBIDDEN": 422,
    "ERR_BRIDGE_ANALYSIS_INCOMPLETE": 409,
    "ERR_BRIDGE_REJECTED": 409,
    "ERR_ESCORT_REQUIREMENT_UNMET": 409,
    "ERR_STRUCTURE_CLOSED": 409,
    "ERR_STRUCTURE_CAPACITY_EXCEEDED": 409,
    "ERR_PILOT_CAR_UNAVAILABLE": 409,
    "ERR_PILOT_CAR_DOUBLE_BOOKED": 409,
    "ERR_STRUCTURE_WINDOW_CONFLICT": 409,
    "ERR_TRAVEL_TIME_RESTRICTED": 409,
    "ERR_UNPAID_FEES": 402,
    "ERR_INSUFFICIENT_ESCROW": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------
def to_jsonable(v):
    if isinstance(v, Decimal):
        if v == v.to_integral_value():
            return int(v)
        return float(v)
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%S.") + f"{v.microsecond // 1000:03d}Z"
    if isinstance(v, dict):
        return {k: to_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    return v


def rand_request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alnum) for _ in range(20))


def meta_base():
    return {"api_request_id": rand_request_id(),
            "api_request_timestamp": now_iso()}


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_base(common_fields=True):
    rec = {"id": str(uuid.uuid4()),
           "created_at": now_iso(),
           "_seq": next(_seq_counter)}
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def round_half_up_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_decimal(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


# ---------------------------------------------------------------------------
# Calculation constants
# ---------------------------------------------------------------------------
LEGAL_WIDTH_IN = 102
LEGAL_HEIGHT_IN = 162
LEGAL_LENGTH_IN = 1020
LEGAL_OVERHANG_IN = 72
LEGAL_GROSS_LBS = 80000
SUPERLOAD_WIDTH_IN = 192
SUPERLOAD_HEIGHT_IN = 204
SUPERLOAD_LENGTH_IN = 1560
SUPERLOAD_WEIGHT_LBS = 200000

ESCORT_WIDTH_T1_IN = 120
ESCORT_WIDTH_T2_IN = 168
ESCORT_LENGTH_T1_IN = 960
ESCORT_LENGTH_T2_IN = 1440
ESCORT_HEIGHT_POLE_IN = 168
POLICE_WIDTH_IN = 192

BASE_FEE_CENTS = 1500
PER_MILE_RATE_CENTS = 25
OVERSIZE_SURCHARGE_CENTS = 3000
OVERWEIGHT_PER_KLB_CENTS = 1000
SUPERLOAD_SURCHARGE_CENTS = 50000
ANNUAL_BASE_FEE_CENTS = 40000

BOND_BASE_CENTS = 5000000
BOND_PER_KLB_CENTS = 100000

RATING_FACTORS = {
    "LFR": (Decimal("1.30"), Decimal("2.17")),
    "LRFR": (Decimal("1.25"), Decimal("1.75")),
}
CLEARED_MIN_RF = Decimal("1.00")
CONDITIONAL_MIN_RF = Decimal("0.90")

BASE_PENALTY = {
    "OVER_DIMENSION": 100000,
    "OFF_ROUTE": 150000,
    "OFF_SCHEDULE": 75000,
    "NO_ESCORT": 200000,
    "EXPIRED_PERMIT": 50000,
}
SEVERITY_MULT = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}
REPEAT_STEP = Decimal("0.5")


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def classify_load(p):
    oversize = (p["width_in"] > LEGAL_WIDTH_IN
                or p["height_in"] > LEGAL_HEIGHT_IN
                or p["length_in"] > LEGAL_LENGTH_IN
                or max(p["front_overhang_in"], p["rear_overhang_in"]) > LEGAL_OVERHANG_IN)
    overweight = p["gross_weight_lbs"] > LEGAL_GROSS_LBS
    superload = (p["width_in"] >= SUPERLOAD_WIDTH_IN
                 or p["height_in"] >= SUPERLOAD_HEIGHT_IN
                 or p["length_in"] >= SUPERLOAD_LENGTH_IN
                 or p["gross_weight_lbs"] >= SUPERLOAD_WEIGHT_LBS)
    if superload:
        return "SUPERLOAD"
    if oversize and overweight:
        return "OVERSIZE_OVERWEIGHT"
    if oversize:
        return "OVERSIZE"
    if overweight:
        return "OVERWEIGHT"
    return "LEGAL"


def compute_escort_requirement(p):
    w = p["width_in"]
    ln = p["length_in"]
    h = p["height_in"]
    g = p["gross_weight_lbs"]
    width_comp = 0 if w <= ESCORT_WIDTH_T1_IN else (1 if w <= ESCORT_WIDTH_T2_IN else 2)
    length_comp = 0 if ln <= ESCORT_LENGTH_T1_IN else (1 if ln <= ESCORT_LENGTH_T2_IN else 2)
    height_comp = 1 if h > ESCORT_HEIGHT_POLE_IN else 0
    police_comp = 1 if (w > POLICE_WIDTH_IN or g >= SUPERLOAD_WEIGHT_LBS) else 0
    return max(width_comp, length_comp) + height_comp + police_comp


def compute_permit_fee(p, segments):
    classification = p["classification"]
    oversize_surcharge = (OVERSIZE_SURCHARGE_CENTS
                          if classification in ("OVERSIZE", "OVERSIZE_OVERWEIGHT", "SUPERLOAD")
                          else 0)
    g = p["gross_weight_lbs"]
    if g > LEGAL_GROSS_LBS:
        over_klb = math.ceil((g - LEGAL_GROSS_LBS) / 1000)
        overweight_surcharge = over_klb * OVERWEIGHT_PER_KLB_CENTS
    else:
        overweight_surcharge = 0
    superload_surcharge = SUPERLOAD_SURCHARGE_CENTS if classification == "SUPERLOAD" else 0

    if p["permit_type"] == "SINGLE_TRIP":
        mileage_total = 0
        for seg in sorted(segments, key=lambda s: s["sequence_index"]):
            per = round_half_up_int(to_decimal(seg["miles"]) * PER_MILE_RATE_CENTS)
            mileage_total += per
        return (BASE_FEE_CENTS + mileage_total + oversize_surcharge
                + overweight_surcharge + superload_surcharge)
    # ANNUAL: flat base, no mileage, no superload surcharge
    return ANNUAL_BASE_FEE_CENTS + oversize_surcharge + overweight_surcharge


def compute_bond_amount(p):
    g = p["gross_weight_lbs"]
    over_klb = math.ceil((g - SUPERLOAD_WEIGHT_LBS) / 1000)
    if over_klb < 0:
        over_klb = 0
    return BOND_BASE_CENTS + over_klb * BOND_PER_KLB_CENTS


def compute_rating_factor(structure, permit, method):
    dead_factor, live_factor = RATING_FACTORS[method]
    live_load = to_decimal(permit["gross_weight_lbs"]) / Decimal(2000)
    numerator = (to_decimal(structure["rated_capacity_tonnage"])
                 - dead_factor * to_decimal(structure["dead_load_tonnage"]))
    denominator = live_factor * live_load
    rf = (numerator / denominator).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return rf


def compute_violation_penalty(carrier_id, violation_type, severity):
    prior_upheld = sum(1 for v in DB["violations"].values()
                       if v["carrier_id"] == carrier_id and v["status"] == "UPHELD")
    base = BASE_PENALTY[violation_type]
    sev = SEVERITY_MULT[severity]
    repeat_mult = Decimal(1) + REPEAT_STEP * Decimal(prior_upheld)
    penalty = Decimal(base * sev) * repeat_mult
    return round_half_up_int(penalty)


# ---------------------------------------------------------------------------
# Computed / derived fields
# ---------------------------------------------------------------------------
def carrier_active_bond(carrier_id):
    return sum(b["amount_cents"] for b in DB["bonds"].values()
               if _bond_carrier_id(b) == carrier_id and b["status"] == "ACTIVE")


def _bond_carrier_id(bond):
    permit = DB["permits"].get(bond["permit_id"])
    return permit["carrier_id"] if permit else None


def carrier_upheld_count(carrier_id):
    return sum(1 for v in DB["violations"].values()
               if v["carrier_id"] == carrier_id and v["status"] == "UPHELD")


def carrier_standing(carrier_id):
    c = carrier_upheld_count(carrier_id)
    if c >= 5:
        return "SUSPENDED"
    if c >= 3:
        return "PROBATION"
    return "GOOD_STANDING"


def structure_available(structure):
    return to_decimal(structure["rated_capacity_tonnage"]) - to_decimal(structure["committed_tonnage"])


def structure_posture(structure):
    available = structure_available(structure)
    rated = to_decimal(structure["rated_capacity_tonnage"])
    if available <= 0:
        return "CLOSED"
    if rated > 0 and (available / rated) >= Decimal("0.5"):
        return "OPEN"
    return "RESTRICTED"
