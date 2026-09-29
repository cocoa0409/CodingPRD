"""Derived aggregates, pinned calculations and resource serialisation."""
from datetime import timedelta
from decimal import Decimal

import calc
import clock
import db
from util import num, round_half_up, round_half_up_1dp

ACTIVE_INVOICE_STATUSES = ("ISSUED", "PARTIALLY_PAID", "DELINQUENT")
LIVE_ENTRY_STATUSES = ("LINEUP_DECLARED", "SUBMITTED", "CONFIRMED")


def public(rec):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        out[key] = num(value) if isinstance(value, Decimal) else value
    return out


# --------------------------------------------------------------------------- #
# Member                                                                      #
# --------------------------------------------------------------------------- #
def dues_balance_cents(member_id):
    total = 0
    for inv in db.invoices.values():
        if inv["member_id"] == member_id and inv["status"] in ACTIVE_INVOICE_STATUSES:
            total += inv["assessed_cents"] - inv["paid_cents"]
    return total


def logged_session_count(member_id):
    count = 0
    for sess in db.sessions.values():
        if sess["status"] == "RETURNED" and member_id in (sess.get("athlete_member_ids") or []):
            count += 1
    return count


def boathouse_access_level(member):
    if member["membership_status"] in ("DUES_HOLD", "SUSPENDED", "WITHDRAWN"):
        return "NONE"
    return "FULL" if dues_balance_cents(member["id"]) == 0 else "SUPERVISED"


def swim_test_valid(member):
    passed = db.dt(member, "swim_test_passed_on")
    if passed is None:
        return False
    return (clock.now() - passed) <= timedelta(days=calc.SWIM_TEST_VALID_DAYS)


def coxswain_cert_valid(member):
    expiry = db.dt(member, "coxswain_cert_expires_at")
    return expiry is not None and expiry > clock.now()


def coach_cert_valid(member):
    expiry = db.dt(member, "coach_cert_expires_at")
    return expiry is not None and expiry > clock.now()


def launch_cert_valid(member):
    expiry = db.dt(member, "safety_launch_cert_expires_at")
    if expiry is None or expiry <= clock.now():
        return False
    return "LAUNCH_DRIVER" in (member.get("club_roles") or [])


def member_out(member):
    out = public(member)
    out["dues_balance_cents"] = dues_balance_cents(member["id"])
    out["logged_session_count"] = logged_session_count(member["id"])
    out["boathouse_access_level"] = boathouse_access_level(member)
    return out


# --------------------------------------------------------------------------- #
# DuesInvoice                                                                 #
# --------------------------------------------------------------------------- #
def dues_provisional_cents(member, billable_months, locker_requested):
    months = Decimal(billable_months)
    season = round_half_up(
        Decimal(calc.TIER_SEASON_FEE_CENTS[member["tier"]]) * months / Decimal(calc.SEASON_MONTHS))
    access = round_half_up(
        Decimal(calc.TIER_ACCESS_SURCHARGE_CENTS[member["tier"]]) * months / Decimal(calc.SEASON_MONTHS))
    locker = 0
    if locker_requested:
        locker = round_half_up(
            Decimal(calc.LOCKER_FEE_CENTS) * months / Decimal(calc.SEASON_MONTHS))
    return season + access + locker


def dues_trueup_cents(member):
    per_session = calc.PER_SESSION_RATE_CENTS * logged_session_count(member["id"])
    floor_component = round_half_up(
        Decimal(calc.TIER_SEASON_FEE_CENTS[member["tier"]]) * calc.TRUEUP_FLOOR_PCT)
    return max(per_session, floor_component) + calc.ADMIN_FEE_CENTS


def invoice_out(invoice):
    return public(invoice)


# --------------------------------------------------------------------------- #
# Shell / DamageReport                                                        #
# --------------------------------------------------------------------------- #
def report_severity_points(report):
    reported_at = db.dt(report, "reported_at")
    elapsed = clock.now() - reported_at
    age_days = elapsed.days
    if age_days < 0:
        age_days = 0
    periods = age_days // calc.DECAY_PERIOD_DAYS
    points = calc.SEVERITY_POINTS[report["severity"]] - calc.DECAY_POINTS_PER_PERIOD * periods
    return points if points > 0 else Decimal("0")


def condition_indices(shell_id):
    conservative = Decimal("0")
    optimistic = Decimal("0")
    for report in db.reports.values():
        if report["shell_id"] != shell_id:
            continue
        status = report["status"]
        if status in ("CONDEMNED", "CLOSED_NO_ACTION"):
            continue
        points = report_severity_points(report)
        if status == "VERIFIED":
            conservative += points * calc.VERIFIED_RESIDUAL_FACTOR
        elif status in ("REPORTED", "TRIAGED", "REPAIR_SCHEDULED"):
            conservative += points
            optimistic += points
    return (_clamp_index(calc.INDEX_CEILING - round_half_up(conservative)),
            _clamp_index(calc.INDEX_CEILING - round_half_up(optimistic)))


def _clamp_index(value):
    if value < 0:
        return 0
    if value > calc.INDEX_CEILING:
        return calc.INDEX_CEILING
    return value


def shell_out(shell):
    out = public(shell)
    conservative, optimistic = condition_indices(shell["id"])
    out["condition_index_conservative"] = conservative
    out["condition_index_optimistic"] = optimistic
    return out


def report_out(report):
    out = public(report)
    out["severity_points"] = num(report_severity_points(report))
    return out


# --------------------------------------------------------------------------- #
# WaterConditionReading / WaterSession                                        #
# --------------------------------------------------------------------------- #
def evaluate_posture(air_temp_c, water_temp_c, wind_speed_kt, visibility_m, traffic_pattern):
    cold = (water_temp_c < calc.COLD_WATER_TEMP_C
            or (water_temp_c + air_temp_c) <= calc.COMBINED_TEMP_SUM_C)
    if wind_speed_kt >= calc.WIND_CLOSE_KT or visibility_m <= calc.VIS_CLOSE_M:
        posture = "CLOSED"
    elif (wind_speed_kt >= calc.WIND_RESTRICT_KT
          or visibility_m <= calc.VIS_RESTRICT_M
          or cold
          or traffic_pattern == "NARROW_CHANNEL"):
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    return cold, posture


def required_launch_count(session, reading):
    base = 0
    if session["session_kind"] == "LEARN_TO_ROW":
        base += 1
    if reading["cold_water_flag"]:
        base += 1
    if reading["posture"] == "RESTRICTED":
        base += 1
    return min(base, calc.MAX_LAUNCHES_PER_SESSION)


def assigned_launch_count(session):
    return sum(1 for field in ("primary_launch_driver_member_id",
                               "secondary_launch_driver_member_id")
               if session.get(field) is not None)


def session_member_ids(session):
    ids = []
    for field in ("coach_member_id", "coxswain_member_id",
                  "primary_launch_driver_member_id", "secondary_launch_driver_member_id"):
        if session.get(field):
            ids.append(session[field])
    ids.extend(session.get("athlete_member_ids") or [])
    return ids


def reading_out(reading):
    return public(reading)


def session_out(session):
    out = public(session)
    out["assigned_launch_count"] = assigned_launch_count(session)
    return out


# --------------------------------------------------------------------------- #
# Regatta / RegattaEntry / LineupSeat                                         #
# --------------------------------------------------------------------------- #
def net_fee_cents(regatta_id):
    total = 0
    for entry in db.entries.values():
        if entry["regatta_id"] != regatta_id:
            continue
        if entry["status"] not in ("SUBMITTED", "CONFIRMED", "RACED", "SCRATCHED"):
            continue
        total += entry["total_fee_cents"] - (entry["refund_cents"] or 0)
    return total


def deposit_held_cents(regatta_id):
    heat_ids = {h["id"] for h in db.heats.values() if h["regatta_id"] == regatta_id}
    total = 0
    for protest in db.protests.values():
        if protest["heat_id"] not in heat_ids:
            continue
        if protest["deposit_refunded"]:
            continue
        if protest["status"] == "WITHDRAWN":
            continue
        total += protest["deposit_cents"]
    return total


def regatta_out(regatta):
    out = public(regatta)
    out["net_fee_cents"] = net_fee_cents(regatta["id"])
    out["deposit_held_cents"] = deposit_held_cents(regatta["id"])
    return out


def entry_fee(entry, regatta, submitted_at):
    boat_class = entry["boat_class"]
    base = calc.CLASS_ENTRY_FEE_CENTS[boat_class]
    levy = 0
    if regatta["venue_kind"] == "AWAY":
        levy = calc.AWAY_TRANSPORT_LEVY_CENTS_PER_RACK_UNIT * calc.CLASS_SLOT_UNITS[boat_class]
    subtotal = base + levy
    pct = (calc.LATE_FEE_PCT_HIGH if subtotal >= calc.LATE_TIER_THRESHOLD_CENTS
           else calc.LATE_FEE_PCT_LOW)
    late = 0
    deadline = db.dt(regatta, "entry_deadline_at")
    if submitted_at > deadline:
        late = round_half_up(Decimal(subtotal) * pct)
    return base, levy, late, subtotal + late


def scratch_refund(entry, regatta):
    now = clock.now()
    if now <= db.dt(regatta, "entry_deadline_at"):
        pct = calc.REFUND_PCT_FULL
    elif now <= db.dt(regatta, "scratch_deadline_at"):
        pct = calc.REFUND_PCT_PARTIAL
    else:
        pct = calc.REFUND_PCT_NONE
    load_id = entry.get("trailer_load_id")
    levy_refundable = True
    if load_id is not None:
        load = db.trailers.get(load_id)
        levy_refundable = load is not None and load["status"] == "OPEN"
    refund = round_half_up(Decimal(entry["base_fee_cents"]) * pct)
    refund += round_half_up(Decimal(entry["late_fee_cents"]) * pct)
    if levy_refundable:
        refund += round_half_up(Decimal(entry["transport_levy_cents"]) * pct)
    return refund


def seat_eligibility(member, seat_role):
    if not swim_test_valid(member):
        return "BLOCKED_SAFETY"
    if seat_role == "COXSWAIN" and not coxswain_cert_valid(member):
        return "BLOCKED_CERT"
    if dues_balance_cents(member["id"]) != 0:
        return "BLOCKED_DUES"
    return "ELIGIBLE"


def entry_seats(entry_id):
    return db.ordered(db.seats, lambda s: s["regatta_entry_id"] == entry_id)


def coxswain_deadweight(weighed_kg, seat_role):
    if seat_role != "COXSWAIN":
        return Decimal("0")
    remainder = calc.MIN_COXSWAIN_WEIGHT_KG - weighed_kg
    if remainder < 0:
        remainder = Decimal("0")
    return round_half_up_1dp(remainder)


def entry_out(entry):
    return public(entry)


def seat_out(seat):
    return public(seat)


# --------------------------------------------------------------------------- #
# Heat / RaceLane                                                             #
# --------------------------------------------------------------------------- #
def heat_lanes(heat_id):
    return db.ordered(db.lanes, lambda l: l["heat_id"] == heat_id)


def occupied_lane_count(heat_id):
    return sum(1 for lane in db.lanes.values()
               if lane["heat_id"] == heat_id and lane["lane_status"] != "VOIDED")


def heat_out(heat):
    out = public(heat)
    occupied = occupied_lane_count(heat["id"])
    out["occupied_lane_count"] = occupied
    out["free_lane_count"] = heat["lane_count"] - occupied
    return out


def lane_out(lane):
    return public(lane)


def preference_lanes(lane_count):
    return [n for n in calc.LANE_PREFERENCE_ORDER if n <= lane_count]


def recompute_places(heat_id):
    """1-based finish rank over PROVISIONAL and OFFICIAL lanes of the heat."""
    ranked = [l for l in heat_lanes(heat_id)
              if l["lane_status"] in ("PROVISIONAL", "OFFICIAL") and l["elapsed_seconds"] is not None]
    ranked.sort(key=lambda l: (l["elapsed_seconds"], l["_created_at"], l["_seq"]))
    changed = []
    for index, lane in enumerate(ranked, start=1):
        if lane["place"] != index:
            lane["place"] = index
            changed.append(lane)
    return changed


# --------------------------------------------------------------------------- #
# Protest / TrailerLoad                                                       #
# --------------------------------------------------------------------------- #
def protest_out(protest):
    return public(protest)


def rack_units_used(load_id):
    total = 0
    for entry in db.entries.values():
        if entry.get("trailer_load_id") != load_id:
            continue
        if entry["status"] not in ("SUBMITTED", "CONFIRMED", "RACED"):
            continue
        total += calc.CLASS_SLOT_UNITS[entry["boat_class"]]
    return total


def trailer_out(load):
    out = public(load)
    capacity = load["rack_tier_count"] * load["rack_units_per_tier"]
    used = rack_units_used(load["id"])
    out["rack_unit_capacity"] = capacity
    out["rack_units_used"] = used
    out["rack_units_free"] = capacity - used
    return out


def rack_allocate(load, entry):
    """Waterfall placement; returns (tier, position) or None."""
    boat_class = entry["boat_class"]
    units = calc.CLASS_SLOT_UNITS[boat_class]
    max_tier = min(calc.CLASS_MAX_TIER[boat_class], load["rack_tier_count"])
    per_tier = load["rack_units_per_tier"]
    occupied = {}
    for other in db.entries.values():
        if other["id"] == entry["id"]:
            continue
        if other.get("trailer_load_id") != load["id"]:
            continue
        if other["status"] not in ("SUBMITTED", "CONFIRMED", "RACED"):
            continue
        if other.get("rack_tier") is None or other.get("rack_position") is None:
            continue
        span = calc.CLASS_SLOT_UNITS[other["boat_class"]]
        for pos in range(other["rack_position"], other["rack_position"] + span):
            occupied.setdefault(other["rack_tier"], set()).add(pos)
    for tier in range(1, max_tier + 1):
        taken = occupied.get(tier, set())
        for start in range(1, per_tier - units + 2):
            if all((start + offset) not in taken for offset in range(units)):
                return tier, start
    return None
