"""Time, decay, and possession arithmetic (PRD §2.4-2.6, SCAFFOLD Table 3).

All activity arithmetic uses Decimal. The exact decay variant rounds half-up to
3 decimals once at the end; the tabular variant rounds the per-minute factor to
6 decimals and rounds each minute step to 3 decimals.
"""

import math
import re
from datetime import datetime, timedelta, timezone

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ERR_VALIDATION, raise_error

Q3 = Decimal("0.001")
Q6 = Decimal("0.000001")

ISO_NO_FRAC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_dt(value, field):
    """Parse an ISO 8601 datetime to a naive UTC datetime."""
    if not isinstance(value, str):
        raise_error(ERR_VALIDATION, f"Field '{field}' must be an ISO 8601 datetime string")
    s = value
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise_error(ERR_VALIDATION, f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def iso_z(dt):
    """Format a naive UTC datetime as ...Z with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def system_ts():
    """System-stamped instant: no-fraction form when the clock has no fraction."""
    now = get_now()
    if now.microsecond == 0:
        return now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso_z(now)


def get_now():
    return parse_dt(db.current_utc_iso, "current_utc")


def minutes_between(t_from, t_to):
    """Whole minutes between two instants, fractional seconds truncated (PRD §2.4)."""
    total = (t_to - t_from).total_seconds() / 60.0
    return int(total)  # truncates toward zero; exact for minute-aligned values


def dfrac(value):
    """Convert a JSON numeric input to Decimal via str() (exact).

    Accepts Decimal passthrough and numeric strings (for server-stored values
    that may have been serialized)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise_error(ERR_VALIDATION, "Expected a numeric value")
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            raise_error(ERR_VALIDATION, "Expected a numeric value")
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Decay correction (PRD §2.5)
# ---------------------------------------------------------------------------

def decay_exact(a_ref, t_reference, t_target, half_life_minutes):
    """Exact exponential variant: A_ref * 0.5**(delta_min/HL), rounded once, 3dp."""
    delta_min = minutes_between(t_reference, t_target)
    hl = float(half_life_minutes)
    factor = 0.5 ** (delta_min / hl)
    result = Decimal(str(float(a_ref) * factor)).quantize(Q3, rounding=ROUND_HALF_UP)
    return result


def decay_tabular(a_ref, t_reference, t_target, half_life_minutes):
    """Tabular minute-step variant: per-minute factor rounded to 6dp; each step
    multiplied/divided and rounded half-up to 3dp (PRD §2.5)."""
    delta_min = minutes_between(t_reference, t_target)
    hl = float(half_life_minutes)
    df = Decimal(str(0.5 ** (1.0 / hl))).quantize(Q6, rounding=ROUND_HALF_UP)
    a = Decimal(str(a_ref)) if not isinstance(a_ref, Decimal) else a_ref
    steps = abs(delta_min)
    if delta_min >= 0:
        for _ in range(steps):
            a = (a * df).quantize(Q3, rounding=ROUND_HALF_UP)
    else:
        for _ in range(steps):
            a = (a / df).quantize(Q3, rounding=ROUND_HALF_UP)
    return a


def required_activity_at_preparation(order, isotope, now):
    """Required draw activity at preparation (PRD §3.4 / SCAFFOLD calc)."""
    dt_min = minutes_between(now, order["administration_scheduled_at_dt"])
    if dt_min < 0:
        dt_min = 0
    hl = float(isotope["half_life_minutes"])
    if hl < 120:
        overage = Decimal("1.10")
    elif hl <= 1440:
        overage = Decimal("1.05")
    else:
        overage = Decimal("1.00")
    raw = float(order["prescribed_activity_mbq"]) * (2.0 ** (dt_min / hl))
    raw_d = Decimal(str(raw)) * overage
    return raw_d.quantize(Q3, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# License / isotope-condition lookups
# ---------------------------------------------------------------------------

def get_order_license(order):
    au = db.authorized_users.get(order["authorized_user_id"])
    if au is None:
        return None
    return db.licenses.get(au["license_id"])


def find_license_for_isotope(isotope_product_id):
    """The single license whose isotope_conditions include this isotope."""
    for lic in db.licenses.values():
        for cond in lic["isotope_conditions"]:
            if cond.get("isotope_product_id") == isotope_product_id:
                return lic
    return None


def matching_condition(license_obj, isotope_product_id):
    for cond in license_obj["isotope_conditions"]:
        if cond.get("isotope_product_id") == isotope_product_id:
            return cond
    return None


# ---------------------------------------------------------------------------
# Waste container current activity (PRD §3.7)
# ---------------------------------------------------------------------------

def container_current_activity(container, now):
    isotope = db.isotope_products.get(container["isotope_product_id"])
    hl = isotope["half_life_minutes"]
    if container["status"] == "FILLING":
        total = Decimal("0")
        for vial in db.dose_vials.values():
            if vial.get("waste_container_id") == container["id"] and vial["status"] == "DISPOSED":
                total += decay_exact(vial["residual_activity_mbq"], vial["disposed_at_dt"], now, hl)
        return total.quantize(Q3, rounding=ROUND_HALF_UP)
    if container["status"] == "SEALED":
        delta_min = minutes_between(container["sealed_at_dt"], now)
        factor = 0.5 ** (delta_min / float(hl))
        return (Decimal(str(float(container["intake_activity_mbq"]) * factor))).quantize(Q3, rounding=ROUND_HALF_UP)
    # CLEARED: exits the ledger; report decayed-to-zero-equivalent (not counted)
    return Decimal("0.000")


# ---------------------------------------------------------------------------
# Possession ledger (PRD §2.6)
# ---------------------------------------------------------------------------

def compute_possession(license_obj, now):
    conditioned = {c.get("isotope_product_id") for c in license_obj["isotope_conditions"]}
    total = Decimal("0")

    # Vials in CALIBRATED or QUARANTINED whose order traces to this license.
    for vial in db.dose_vials.values():
        if vial["status"] not in ("CALIBRATED", "QUARANTINED"):
            continue
        order = db.dose_orders.get(vial["order_id"])
        if order is None:
            continue
        au = db.authorized_users.get(order["authorized_user_id"])
        if au is None or au["license_id"] != license_obj["id"]:
            continue
        if order["isotope_product_id"] not in conditioned:
            continue
        isotope = db.isotope_products[order["isotope_product_id"]]
        total += decay_exact(vial["measured_activity_mbq"], vial["calibrated_at_dt"], now,
                             isotope["half_life_minutes"])

    # Deliveries in SCHEDULED whose isotope is conditioned on this license.
    for dlv in db.isotope_deliveries.values():
        if dlv["status"] != "SCHEDULED":
            continue
        if dlv["isotope_product_id"] not in conditioned:
            continue
        isotope = db.isotope_products[dlv["isotope_product_id"]]
        total += decay_exact(dlv["reference_activity_mbq"], dlv["reference_time_at_dt"], now,
                             isotope["half_life_minutes"])

    # Waste containers in FILLING or SEALED whose isotope is conditioned.
    for cont in db.waste_containers.values():
        if cont["status"] not in ("FILLING", "SEALED"):
            continue
        if cont["isotope_product_id"] not in conditioned:
            continue
        total += container_current_activity(cont, now).quantize(Q3, rounding=ROUND_HALF_UP)

    return total.quantize(Q3, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Common entity plumbing
# ---------------------------------------------------------------------------

def stamp_new(entity, append_only=False):
    """Set id-independent system fields on creation."""
    ts = system_ts()
    entity["created_at"] = ts
    if not append_only:
        entity["updated_at"] = ts
        entity["version"] = 1


def touch(entity):
    entity["updated_at"] = system_ts()
    entity["version"] += 1


def public_num(value):
    """Serialize a Decimal (or number) as a JSON float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
