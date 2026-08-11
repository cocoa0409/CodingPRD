"""Domain logic: serializers, fare math, driver eligibility/selector,
cascades, standing-ride occurrence generation."""

from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from core import (
    db, now, today, fmt_ts, fmt_date, stamp_new, touch, next_seq, new_id,
    ApiError,
)

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

FREE_CANCEL_NOTICE_MINUTES = 1440
LATE_CANCEL_NOTICE_MINUTES = 240
TRAVEL_BUFFER_MINUTES = 30
OFFER_TIMEOUT_MINUTES = 30
NO_SHOW_WAIT_MINUTES = 15
NO_SHOW_STRIKE_LIMIT = 3
NET_DAYS = 14
GENERATION_HORIZON_DAYS = 14
MAX_CREDIT_SHARE_BP = 5000

REQUIRED_DOC_TYPES = ("BACKGROUND_CHECK", "BONDING", "INSURANCE")
ASSIST_RANK = {"NONE": 0, "DOOR_TO_DOOR": 1, "DOOR_THROUGH_DOOR": 2}
LIVE_RIDE_STATUSES = ("ASSIGNED", "EN_ROUTE", "ARRIVED", "IN_SERVICE")
OPEN_RIDE_STATUSES = (
    "SCHEDULED", "DISPATCHING", "ASSIGNED", "EN_ROUTE", "ARRIVED", "IN_SERVICE",
)
OPEN_INVOICE_STATUSES = ("DRAFT", "ISSUED", "PARTIALLY_PAID")

WEEKDAY_MAP = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
}


def round_half_up_cents(numerator, denominator):
    """round_half_up(numerator / denominator) to whole cents -> int."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


def whole_minutes(delta):
    """Whole minutes of a timedelta, floored."""
    return int(delta.total_seconds() // 60)


# ----------------------------------------------------------------------------
# Rate card lookup and fare computation
# ----------------------------------------------------------------------------


def active_rate_card(service_class, on_date):
    """The ACTIVE card of service_class whose half-open window contains on_date."""
    for rc in db.rate_cards.values():
        if rc["service_class"] != service_class or rc["status"] != "ACTIVE":
            continue
        if rc["effective_from"] <= on_date < rc["effective_to"]:
            return rc
    return None


def any_rate_card_covering(service_class, on_date):
    """Fallback: latest-created card of the class covering on_date (any status)."""
    best = None
    for rc in db.rate_cards.values():
        if rc["service_class"] != service_class:
            continue
        if rc["effective_from"] <= on_date < rc["effective_to"]:
            if best is None or rc["_seq"] > best["_seq"]:
                best = rc
    return best


def compute_fare(card, minutes, miles, wait_minutes, pickup_dt, service_class):
    """Pinned fare formula. Returns (fare, minimum_adjustment, billable_wait)."""
    hourly_charge = round_half_up_cents(card["hourly_rate_cents"] * minutes, 60)
    mileage_charge = card["per_mile_cents"] * miles
    billable_wait = max(0, wait_minutes - card["included_wait_minutes"])
    wait_charge = billable_wait * card["wait_per_minute_cents"]
    subtotal = hourly_charge + mileage_charge + wait_charge
    pickup_minute_of_day = pickup_dt.hour * 60 + pickup_dt.minute
    if pickup_minute_of_day >= card["after_hours_start_minute"]:
        subtotal = round_half_up_cents(subtotal * card["after_hours_multiplier_bp"], 10000)
    floored = max(subtotal, card["minimum_charge_cents"])
    minimum_adjustment = floored - subtotal
    fare = floored
    if service_class == "WAV":
        fare += card["wav_surcharge_cents"]
    return fare, minimum_adjustment, billable_wait


def cancellation_fee(card, scheduled_pickup_at):
    """Tiered notice-based cancellation fee."""
    notice = whole_minutes(scheduled_pickup_at - now())
    if notice >= FREE_CANCEL_NOTICE_MINUTES:
        return 0
    if notice >= LATE_CANCEL_NOTICE_MINUTES:
        return round_half_up_cents(card["minimum_charge_cents"] * 50, 100)
    return card["minimum_charge_cents"]


# ----------------------------------------------------------------------------
# Driver compliance posture and load metrics
# ----------------------------------------------------------------------------


def posture_complete(driver_id, on_date):
    for doc_type in REQUIRED_DOC_TYPES:
        covered = False
        for doc in db.compliance_docs.values():
            if (
                doc["driver_id"] == driver_id
                and doc["doc_type"] == doc_type
                and doc["status"] == "APPROVED"
                and doc["valid_from"] <= on_date < doc["valid_until"]
            ):
                covered = True
                break
        if not covered:
            return False
    return True


def driver_current_load(driver_id):
    """Sum of estimated_duration_minutes over the driver's rides with pickup
    date == logical today and status in live set."""
    total = 0
    t = today()
    for ride in db.rides.values():
        if (
            ride["assigned_driver_id"] == driver_id
            and ride["scheduled_pickup_at"].date() == t
            and ride["status"] in LIVE_RIDE_STATUSES
        ):
            total += ride["estimated_duration_minutes"]
    return total


def driver_day_worked(driver_id):
    total = 0
    t = today()
    for ride in db.rides.values():
        if (
            ride["assigned_driver_id"] == driver_id
            and ride["scheduled_pickup_at"].date() == t
            and ride["status"] == "COMPLETED"
        ):
            total += ride["service_minutes"] or 0
    return total


def occupied_window(ride):
    start = ride["scheduled_pickup_at"] - timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    end = (
        ride["scheduled_pickup_at"]
        + timedelta(minutes=ride["estimated_duration_minutes"])
        + timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    )
    return start, end


def windows_conflict(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def driver_has_overlap(driver_id, candidate_ride, exclude_assignment_id=None):
    """Buffered-window conflict with the driver's live ACCEPTED assignments."""
    c_start, c_end = occupied_window(candidate_ride)
    for asg in db.assignments.values():
        if asg["driver_id"] != driver_id or asg["status"] != "ACCEPTED":
            continue
        if exclude_assignment_id is not None and asg["id"] == exclude_assignment_id:
            continue
        other = db.rides.get(asg["ride_id"])
        if other is None or other["status"] not in LIVE_RIDE_STATUSES:
            continue
        if other["id"] == candidate_ride["id"]:
            continue
        o_start, o_end = occupied_window(other)
        if windows_conflict(c_start, c_end, o_start, o_end):
            return True
    return False


def driver_eligible(driver, ride):
    """Full eligibility filter for the selector. Returns True/False."""
    if driver["status"] != "ACTIVE":
        return False
    if not posture_complete(driver["id"], ride["scheduled_pickup_at"].date()):
        return False
    if ride["requires_wav"] and driver["vehicle_class"] != "WAV":
        return False
    if ASSIST_RANK[driver["assist_certification"]] < ASSIST_RANK[ride["assist_level"]]:
        return False
    if driver["id"] in ride["excluded_driver_ids"]:
        return False
    if driver_has_overlap(driver["id"], ride):
        return False
    if (
        driver_current_load(driver["id"]) + ride["estimated_duration_minutes"]
        > driver["max_daily_service_minutes"]
    ):
        return False
    return True


def select_driver(ride):
    """Filter + rank eligible drivers; return best Driver record or None."""
    pool = [d for d in db.drivers.values() if driver_eligible(d, ride)]
    if not pool:
        return None
    pool.sort(
        key=lambda d: (
            0 if d["home_zone"] == ride["origin_zone"] else 1,
            driver_current_load(d["id"]),
            d["created_at"],
            d["_seq"],
        )
    )
    return pool[0]


# ----------------------------------------------------------------------------
# Ride events
# ----------------------------------------------------------------------------


def append_event(ride, event_type, actor_role, actor_user_id, note=None, occurred=None):
    ev = {
        "id": new_id(),
        "ride_id": ride["id"],
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "occurred_at": occurred if occurred is not None else now(),
        "note": note,
        "created_at": occurred if occurred is not None else now(),
        "_seq": next_seq(),
    }
    db.ride_events[ev["id"]] = ev
    return ev


# ----------------------------------------------------------------------------
# Cancellation / suspension cascades
# ----------------------------------------------------------------------------


def expire_offered_assignments_for_ride(ride):
    """OFFERED assignments of this ride -> EXPIRED (release_reason=RIDE_CANCELLED)."""
    for asg in db.assignments.values():
        if asg["ride_id"] == ride["id"] and asg["status"] == "OFFERED":
            asg["status"] = "EXPIRED"
            asg["release_reason"] = "RIDE_CANCELLED"
            touch(asg)


def release_accepted_assignment_for_ride(ride, release_reason):
    asg = accepted_assignment_for_ride(ride)
    if asg is not None:
        asg["status"] = "RELEASED"
        asg["release_reason"] = release_reason
        asg["responded_at"] = now()
        touch(asg)
    return asg


def accepted_assignment_for_ride(ride):
    for asg in db.assignments.values():
        if asg["ride_id"] == ride["id"] and asg["status"] == "ACCEPTED":
            return asg
    return None


def offered_assignment_for_ride(ride):
    for asg in db.assignments.values():
        if asg["ride_id"] == ride["id"] and asg["status"] == "OFFERED":
            return asg
    return None


def system_cancel_ride(ride, reason):
    """System-initiated cancel: fee-free."""
    if ride["status"] == "DISPATCHING":
        expire_offered_assignments_for_ride(ride)
    ride["status"] = "CANCELLED"
    ride["cancel_reason"] = reason
    ride["cancellation_fee_cents"] = 0
    ride["cancelled_by_role"] = "system"
    touch(ride)
    append_event(ride, "CANCELLED", "system", "system")


def suspend_client_cascade(client):
    """Cancel every SCHEDULED/DISPATCHING ride of this client, fee-free."""
    for ride in list(db.rides.values()):
        if ride["client_id"] != client["id"]:
            continue
        if ride["status"] in ("SCHEDULED", "DISPATCHING"):
            system_cancel_ride(ride, "CLIENT_SUSPENDED")


def driver_release_cascade(driver):
    """Release this driver's ACCEPTED assignments whose ride is ASSIGNED."""
    for asg in list(db.assignments.values()):
        if asg["driver_id"] != driver["id"] or asg["status"] != "ACCEPTED":
            continue
        ride = db.rides.get(asg["ride_id"])
        if ride is None or ride["status"] != "ASSIGNED":
            continue
        asg["status"] = "RELEASED"
        asg["release_reason"] = "DRIVER_SUSPENDED"
        asg["responded_at"] = now()
        touch(asg)
        ride["status"] = "DISPATCHING"
        ride["assigned_driver_id"] = None
        ride["dispatch_round"] += 1
        if driver["id"] not in ride["excluded_driver_ids"]:
            ride["excluded_driver_ids"].append(driver["id"])
        touch(ride)
        append_event(ride, "RELEASED", "system", "system")


# ----------------------------------------------------------------------------
# Standing ride occurrence generation
# ----------------------------------------------------------------------------


def cadence_dates(series, horizon_limited):
    """Cadence dates for generation or next-occurrence computation."""
    t = today()
    last = series["ends_on"]
    if horizon_limited:
        horizon_end = t + timedelta(days=GENERATION_HORIZON_DAYS)
        if horizon_end < last:
            last = horizon_end
    wd = WEEKDAY_MAP[series["weekday"]]
    d = t
    out = []
    while d <= last:
        if d >= series["starts_on"] and d.weekday() == wd:
            out.append(d)
        d += timedelta(days=1)
    return out


def next_occurrence(series):
    dates = cadence_dates(series, horizon_limited=False)
    return dates[0] if dates else None


def ride_exists_on(series_id, day):
    """A non-cancelled ride of this series already occupies the date."""
    for ride in db.rides.values():
        if (
            ride["standing_ride_id"] == series_id
            and ride["scheduled_pickup_at"].date() == day
            and ride["status"] != "CANCELLED"
        ):
            return True
    return False


def generate_occurrences(series, actor_role="system", actor_user_id="system"):
    """Create SCHEDULED rides inside the generation horizon. Returns new rides."""
    if series["status"] != "ACTIVE":
        return []
    client = db.clients.get(series["client_id"])
    if client is None or client["status"] != "ACTIVE":
        return []
    created = []
    for day in cadence_dates(series, horizon_limited=True):
        if ride_exists_on(series["id"], day):
            continue
        pickup = datetime(
            day.year, day.month, day.day, tzinfo=timezone.utc
        ) + timedelta(minutes=series["pickup_time_of_day_minutes"])
        ride = {
            "client_id": series["client_id"],
            "standing_ride_id": series["id"],
            "booked_by_family_member_id": series["booked_by_family_member_id"],
            "linked_return_ride_id": None,
            "kind": series["kind"],
            "origin_zone": series["origin_zone"],
            "scheduled_pickup_at": pickup,
            "estimated_duration_minutes": series["estimated_duration_minutes"],
            "estimated_distance_miles": series["estimated_distance_miles"],
            "requires_wav": client["mobility_aid"] == "POWER_WHEELCHAIR" if client else False,
            "status": "SCHEDULED",
            "dispatch_round": 0,
            "excluded_driver_ids": [],
            "assigned_driver_id": None,
            "en_route_at": None,
            "arrived_at": None,
            "wait_minutes": 0,
            "service_minutes": None,
            "actual_distance_miles": None,
            "quoted_fare_cents": None,
            "final_fare_cents": None,
            "cancellation_fee_cents": 0,
            "cancel_reason": None,
            "cancelled_by_role": None,
            "no_show_fee_cents": 0,
            "_open_wait_started_at": None,
            "_service_started_at": None,
            "_rate_card_id": None,
        }
        ride["service_class"] = "WAV" if ride["requires_wav"] else "STANDARD"
        ride["assist_level"] = client["assist_level_default"] if client else "DOOR_TO_DOOR"
        card = active_rate_card(ride["service_class"], day)
        if card is not None:
            ride["_rate_card_id"] = card["id"]
            fare, _min_adj, _bw = compute_fare(
                card,
                ride["estimated_duration_minutes"],
                ride["estimated_distance_miles"],
                0,
                pickup,
                ride["service_class"],
            )
            ride["quoted_fare_cents"] = fare
        stamp_new(ride)
        db.rides[ride["id"]] = ride
        append_event(ride, "CREATED", actor_role, actor_user_id)
        created.append(ride)
    return created


# ----------------------------------------------------------------------------
# Billing hold / overdue AR
# ----------------------------------------------------------------------------


def overdue_ar_cents(client_id):
    t = today()
    total = 0
    for inv in db.invoices.values():
        if inv["client_id"] != client_id:
            continue
        if inv["issuance_status"] not in ("ISSUED", "PARTIALLY_PAID"):
            continue
        if inv["due_date"] < t:
            total += inv["total_due_cents"] - inv["paid_cents"]
    return total


def billing_hold_active(client):
    return overdue_ar_cents(client["id"]) >= client["billing_hold_limit_cents"]


# ----------------------------------------------------------------------------
# Serializers (strip internal fields, format timestamps)
# ----------------------------------------------------------------------------


def _base(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        out[k] = v
    return out


def ser_client(c):
    out = _base(c)
    out["created_at"] = fmt_ts(c["created_at"])
    out["updated_at"] = fmt_ts(c["updated_at"])
    return out


def ser_family_member(m):
    out = _base(m)
    out["created_at"] = fmt_ts(m["created_at"])
    out["updated_at"] = fmt_ts(m["updated_at"])
    return out


def ser_driver(d):
    out = _base(d)
    out["current_load_minutes"] = driver_current_load(d["id"])
    out["day_worked_minutes"] = driver_day_worked(d["id"])
    out["created_at"] = fmt_ts(d["created_at"])
    out["updated_at"] = fmt_ts(d["updated_at"])
    return out


def ser_compliance_doc(doc):
    out = _base(doc)
    out["valid_from"] = fmt_date(doc["valid_from"])
    out["valid_until"] = fmt_date(doc["valid_until"])
    out["created_at"] = fmt_ts(doc["created_at"])
    out["updated_at"] = fmt_ts(doc["updated_at"])
    return out


def ser_rate_card(rc):
    out = _base(rc)
    out["effective_from"] = fmt_date(rc["effective_from"])
    out["effective_to"] = fmt_date(rc["effective_to"])
    out["created_at"] = fmt_ts(rc["created_at"])
    out["updated_at"] = fmt_ts(rc["updated_at"])
    return out


def ser_standing_ride(s):
    out = _base(s)
    out["starts_on"] = fmt_date(s["starts_on"])
    out["ends_on"] = fmt_date(s["ends_on"])
    out["next_occurrence_date"] = fmt_date(next_occurrence(s))
    out["created_at"] = fmt_ts(s["created_at"])
    out["updated_at"] = fmt_ts(s["updated_at"])
    return out


def ser_ride(r):
    out = _base(r)
    out["scheduled_pickup_at"] = fmt_ts(r["scheduled_pickup_at"])
    out["en_route_at"] = fmt_ts(r["en_route_at"])
    out["arrived_at"] = fmt_ts(r["arrived_at"])
    out["excluded_driver_ids"] = list(r["excluded_driver_ids"])
    out["created_at"] = fmt_ts(r["created_at"])
    out["updated_at"] = fmt_ts(r["updated_at"])
    return out


def ser_assignment(a):
    out = _base(a)
    out["offered_at"] = fmt_ts(a["offered_at"])
    out["offer_expires_at"] = fmt_ts(a["offer_expires_at"])
    out["responded_at"] = fmt_ts(a["responded_at"])
    out["created_at"] = fmt_ts(a["created_at"])
    out["updated_at"] = fmt_ts(a["updated_at"])
    return out


def ser_ride_event(ev):
    return {
        "id": ev["id"],
        "ride_id": ev["ride_id"],
        "event_type": ev["event_type"],
        "actor_role": ev["actor_role"],
        "actor_user_id": ev["actor_user_id"],
        "occurred_at": fmt_ts(ev["occurred_at"]),
        "note": ev["note"],
        "created_at": fmt_ts(ev["created_at"]),
    }


def ser_invoice(inv):
    out = _base(inv)
    out["period_start"] = fmt_date(inv["period_start"])
    out["period_end"] = fmt_date(inv["period_end"])
    out["due_date"] = fmt_date(inv["due_date"])
    out["created_at"] = fmt_ts(inv["created_at"])
    out["updated_at"] = fmt_ts(inv["updated_at"])
    return out


def ser_invoice_line(line):
    out = _base(line)
    out["created_at"] = fmt_ts(line["created_at"])
    out["updated_at"] = fmt_ts(line["updated_at"])
    return out


def ser_payment(p):
    out = _base(p)
    out["applications"] = [dict(a) for a in p["applications"]]
    out["created_at"] = fmt_ts(p["created_at"])
    out["updated_at"] = fmt_ts(p["updated_at"])
    return out
