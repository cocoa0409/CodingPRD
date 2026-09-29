"""All derived figures of the domain (PRD §2.9, §3.2-§3.9).

Money is whole cents, percentages and power figures carry two decimals,
`session_energy_kwh` three, durations are whole minutes floored (the expedite
discount alone rounds up).  Shares inside the interoperability score and the
uptime percentage stay exact rationals until a single half-up rounding.
"""
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import clock
import db

# --------------------------------------------------------------------- constants
FAULT_BASE_MINUTES = {"CRITICAL": 240, "MAJOR": 720, "MINOR": 2880, "INFORMATIONAL": 10080}
POWER_CLASS_FACTOR = {
    "DCFC_350": Fraction(1, 2),
    "DCFC_150": Fraction(3, 4),
    "L2_19": Fraction(1, 1),
}
CORRIDOR_TIGHTEN_MINUTES = 60
REGULATORY_FLOOR_MINUTES = 120
REGULATORY_CAP_MINUTES = 4320

W_CONTACTLESS = Fraction(40, 100)
W_PLUG_AND_CHARGE = Fraction(20, 100)
W_PRICE_DISPLAY = Fraction(20, 100)
W_ROAMING = Fraction(20, 100)
COMMISSION_MIN_SCORE = Decimal("90.00")
ROAMING_COMPLIANT_VERSIONS = ("V2_2_1", "V2_3_0")

LABOR_MINUTES_BY_PART_CLASS = {
    "DISPENSER": 480,
    "POWER_MODULE": 300,
    "CABLE_ASSEMBLY": 180,
    "PAYMENT_TERMINAL": 120,
}
LABOR_MINUTES_DEFAULT = 120
EXPEDITE_TRIGGER_MINUTES = 2880
EXPEDITE_FACTOR = Fraction(1, 2)

WITHHOLD_TIERS = (
    (Decimal("97.00"), Decimal("0.00")),
    (Decimal("95.00"), Decimal("0.10")),
    (Decimal("90.00"), Decimal("0.25")),
    (Decimal("0.00"), Decimal("1.00")),
)
UPTIME_PCT_MAX = Decimal("100.00")
MIN_REPORTING_PERIOD_MINUTES = 10080

TECH_CERT_RANK = {"L2": 1, "DCFC_BASIC": 2, "DCFC_HV": 3}
REQUIRED_CERT_RANK = {"L2_19": 1, "DCFC_150": 2, "DCFC_350": 3}

OPEN_OUTAGE_STATES = ("DETECTED", "CLASSIFIED", "DISPATCHED", "EXCLUSION_REVIEW")
LIVE_DISPATCH_STATES = ("CREATED", "EN_ROUTE", "ON_SITE", "PARTS_HOLD")
BILLABLE_OUTAGE_STATES = (
    "DETECTED", "CLASSIFIED", "DISPATCHED", "RESOLVED", "VERIFIED", "EXCLUSION_REVIEW",
)


# --------------------------------------------------------------------- rounding
def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q3(value):
    return Decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def q0(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_fraction(frac, places):
    """Exact half-up rounding of a Fraction to `places` decimals."""
    scale = 10 ** places
    scaled = Fraction(frac) * scale
    whole = math.floor(scaled + Fraction(1, 2))
    return Decimal(whole) / Decimal(scale)


def floor_minutes_between(start, end):
    return int((end - start).total_seconds() // 60)


# ---------------------------------------------------------- station derived data
def station_ports(station_id):
    return db.ports_of_station(station_id)


def non_retired_ports(station_id):
    return [p for p in station_ports(station_id) if p["service_state"] != "RETIRED"]


def scored_ports(station_id):
    return [p for p in station_ports(station_id)
            if p["service_state"] in ("IN_SERVICE", "OUT_OF_SERVICE")]


def commissioned_port_count(station_id):
    return len(non_retired_ports(station_id))


def out_of_service_port_count(station_id):
    return len([p for p in station_ports(station_id) if p["service_state"] == "OUT_OF_SERVICE"])


def installed_power_kw(station_id):
    total = Decimal("0")
    for port in non_retired_ports(station_id):
        total += port["rated_power_kw"]
    return q2(total)


def payment_interoperability_score(station_id):
    scored = scored_ports(station_id)
    n = len(scored)
    if n == 0:
        return Decimal("0.00")
    contactless = sum(1 for p in scored if p["contactless_enabled"])
    pnc = sum(1 for p in scored if p["plug_and_charge_enabled"])
    display = sum(1 for p in scored if p["price_display_verified"])
    roaming = sum(1 for p in scored
                  if p["terminal_certification_status"] == "CERTIFIED"
                  and p["roaming_ocpi_version"] in ROAMING_COMPLIANT_VERSIONS)
    weighted = (W_CONTACTLESS * Fraction(contactless, n)
                + W_PLUG_AND_CHARGE * Fraction(pnc, n)
                + W_PRICE_DISPLAY * Fraction(display, n)
                + W_ROAMING * Fraction(roaming, n))
    return round_half_up_fraction(weighted * 100, 2)


def station_downtime_ledger(station_id):
    port_ids = {p["id"] for p in station_ports(station_id)}
    gross = 0
    excluded = 0
    for outage in db.outages.values():
        if outage["port_id"] not in port_ids:
            continue
        if outage["cleared_at"] is None:
            continue
        minutes = floor_minutes_between(outage["detected_at"], outage["cleared_at"])
        gross += minutes
        if outage["state"] == "EXCLUDED":
            excluded += minutes
    return gross, excluded, gross - excluded


def refund_liability_cents(station_id):
    total = 0
    for complaint in db.complaints.values():
        if complaint["station_id"] != station_id:
            continue
        if complaint["refund_state"] == "SETTLED" and complaint["refund_amount_cents"]:
            total += complaint["refund_amount_cents"]
    return total


def host_site_station_count(host_site_id):
    return len([s for s in db.stations.values()
                if s["host_site_id"] == host_site_id and s["status"] != "DECOMMISSIONED"])


# ------------------------------------------------------------- spare part figures
def reserved_qty(part_id):
    return sum(r["qty"] for r in db.reservations.values()
               if r["spare_part_id"] == part_id and r["state"] == "RESERVED")


def backordered_qty(part_id):
    return sum(r["qty"] for r in db.reservations.values()
               if r["spare_part_id"] == part_id and r["state"] == "BACKORDERED")


def consumed_qty_lifetime(part_id):
    return sum(r["qty"] for r in db.reservations.values()
               if r["spare_part_id"] == part_id and r["state"] == "CONSUMED")


def unencumbered_qty(part):
    return part["on_hand_qty"] - reserved_qty(part["id"])


# ------------------------------------------------------------- uptime percentage
def uptime_figures(report, variant):
    """Returns the five figures of PRD §3.7 under the requested methodology.

    `uptime_pct` comes back as None when the variant's denominator is zero; the
    caller turns that into ERR_NO_REPORTABLE_PORT_MINUTES.
    """
    period_start = report["period_start"]
    period_end = report["period_end"]
    period_minutes = floor_minutes_between(period_start, period_end)

    eligible = [p for p in db.ports_of_station(report["station_id"])
                if p["created_at"] <= period_start
                and p["service_state"] in ("IN_SERVICE", "OUT_OF_SERVICE")]
    eligible_ids = {p["id"] for p in eligible}
    eligible_port_count = len(eligible)
    total_port_minutes = eligible_port_count * period_minutes

    excluded_minutes = 0
    billable_minutes = 0
    for outage in db.outages.values():
        if outage["port_id"] not in eligible_ids:
            continue
        if not outage["detected_at"] < period_end:
            continue
        cleared_at = outage["cleared_at"]
        if cleared_at is not None and not cleared_at > period_start:
            continue
        ov_start = max(outage["detected_at"], period_start)
        ov_end = min(cleared_at if cleared_at is not None else period_end, period_end)
        overlap = max(0, floor_minutes_between(ov_start, ov_end))
        if outage["state"] == "EXCLUDED":
            excluded_minutes += overlap
        else:
            billable_minutes += overlap

    t = total_port_minutes
    e = excluded_minutes
    d = billable_minutes
    denominator = t if variant == "PROVISIONAL" else t - e
    uptime_pct = None
    if denominator > 0:
        uptime_pct = round_half_up_fraction(Fraction(100 * (t - e - d), denominator), 2)

    return {
        "eligible_port_count": eligible_port_count,
        "total_port_minutes": total_port_minutes,
        "excluded_minutes": excluded_minutes,
        "billable_downtime_minutes": billable_minutes,
        "uptime_pct": uptime_pct,
        "denominator": denominator,
    }


def attributed_outages(report):
    """The outage rows the report's period attributes, used by the finalisation
    guard on pending exclusion reviews."""
    period_start = report["period_start"]
    period_end = report["period_end"]
    eligible_ids = {p["id"] for p in db.ports_of_station(report["station_id"])
                    if p["created_at"] <= period_start
                    and p["service_state"] in ("IN_SERVICE", "OUT_OF_SERVICE")}
    result = []
    for outage in db.outages.values():
        if outage["port_id"] not in eligible_ids:
            continue
        if not outage["detected_at"] < period_end:
            continue
        cleared_at = outage["cleared_at"]
        if cleared_at is not None and not cleared_at > period_start:
            continue
        result.append(outage)
    return result


# ------------------------------------------------------------- response deadline
def dispatch_response_deadline(outage, station, host_site):
    base = FAULT_BASE_MINUTES[outage["fault_class"]]
    scaled = math.floor(base * POWER_CLASS_FACTOR[station["power_class"]])
    tightened = scaled - (CORRIDOR_TIGHTEN_MINUTES if station["corridor_designated"] else 0)
    bounded = min(REGULATORY_CAP_MINUTES, max(REGULATORY_FLOOR_MINUTES, tightened))
    naive = outage["detected_at"] + timedelta(minutes=bounded)

    if host_site["access_hours_mode"] == "TWENTY_FOUR_SEVEN":
        return naive

    open_minute = host_site["access_open_minute"]
    close_minute = host_site["access_close_minute"]
    minute_of_day = naive.hour * 60 + naive.minute
    if open_minute <= minute_of_day < close_minute:
        return naive
    day = datetime(naive.year, naive.month, naive.day, tzinfo=timezone.utc)
    if minute_of_day < open_minute:
        return day + timedelta(minutes=open_minute)
    return day + timedelta(days=1, minutes=open_minute)


# ------------------------------------------------------------ parts-hold promise
def parts_hold_promise(dispatch):
    held = [r for r in db.reservations_of_dispatch(dispatch["id"])
            if r["state"] in ("RESERVED", "BACKORDERED")]

    waits = []
    labors = []
    for reservation in held:
        part = db.spare_parts.get(reservation["spare_part_id"])
        lead_days = part["lead_time_days"] if part else 0
        waits.append(lead_days * 1440 if reservation["state"] == "BACKORDERED" else 0)
        part_class = part["part_class"] if part else None
        labors.append(LABOR_MINUTES_BY_PART_CLASS.get(part_class, LABOR_MINUTES_DEFAULT))

    parts_wait_raw = max(waits) if waits else 0
    labor_minutes = max(labors) if labors else LABOR_MINUTES_DEFAULT
    pre_expedite = parts_wait_raw + labor_minutes
    expedite_eligible = pre_expedite > EXPEDITE_TRIGGER_MINUTES
    if expedite_eligible:
        parts_wait_final = math.ceil(Fraction(parts_wait_raw) * EXPEDITE_FACTOR)
    else:
        parts_wait_final = parts_wait_raw
    total_hold_minutes = parts_wait_final + labor_minutes
    return total_hold_minutes, clock.now() + timedelta(minutes=total_hold_minutes)


# ------------------------------------------------------------------ claim money
def effective_uptime_pct(report_uptime_pct, credit_pp):
    base = Decimal(report_uptime_pct if report_uptime_pct is not None else 0)
    credit = Decimal(credit_pp if credit_pp is not None else 0)
    return min(UPTIME_PCT_MAX, q2(base + credit))


def withhold_rate_for(effective_pct):
    for threshold, rate in WITHHOLD_TIERS:
        if effective_pct >= threshold:
            return rate
    return Decimal("1.00")


def withheld_amount_cents(line_items, rate):
    total = 0
    for item in line_items:
        total += q0(Decimal(item["amount_cents"]) * Decimal(rate))
    return total


# ---------------------------------------------------------------- refund amounts
def energy_component_cents(complaint):
    product = Decimal(complaint["session_energy_kwh"]) * Decimal(
        complaint["session_price_per_kwh_cents"])
    return q0(product)


def outage_overlaps_session(outage, complaint):
    o_start = outage["detected_at"]
    o_end = outage["cleared_at"]
    s_start = complaint["session_started_at"]
    s_end = complaint["session_ended_at"]
    if o_end is None:
        return o_start < s_end
    return o_start < s_end and s_start < o_end


def session_refund_amount(complaint, basis):
    charged = complaint["session_charged_cents"]
    if basis == "FULL_SESSION_GOODWILL":
        return charged
    energy = energy_component_cents(complaint)
    return max(0, charged - energy - complaint["session_idle_fee_cents"])


# ------------------------------------------------------------------- misc guards
def station_of_port(port):
    return db.stations.get(port["station_id"])


def station_is_serviceable(station):
    return station is not None and station["status"] in ("OPERATIONAL", "SUSPENDED")


def technician_covers(cert_class, power_class):
    return TECH_CERT_RANK.get(cert_class, 0) >= REQUIRED_CERT_RANK.get(power_class, 0)
