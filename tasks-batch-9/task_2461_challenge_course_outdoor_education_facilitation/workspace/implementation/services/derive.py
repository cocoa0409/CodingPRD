"""Derived values: posture, counters, forecasts, readiness, certification
currency, screening and supervision arithmetic."""
from datetime import timedelta
from decimal import Decimal

from db import store, clock_date, clock_now, touch, by_created_at
from validation import add_years, add_months, add_days, fmt_date, ceil_div
from services import constants as C


# ---------------------------------------------------------------- collections

def elements_of_course(course_id):
    return by_created_at([e for e in store.elements.values() if e["course_id"] == course_id])


def facilitators_of_course(course_id):
    return by_created_at([f for f in store.facilitators.values() if f["course_id"] == course_id])


def equipment_of_course(course_id):
    return by_created_at([e for e in store.belay_equipment.values() if e["course_id"] == course_id])


def equipment_of_element(element_id):
    return by_created_at(
        [e for e in store.belay_equipment.values() if e["assigned_element_id"] == element_id]
    )


def bookings_of_course(course_id):
    return by_created_at([b for b in store.bookings.values() if b["course_id"] == course_id])


def bookings_of_client(client_id):
    return by_created_at([b for b in store.bookings.values() if b["group_client_id"] == client_id])


def blocks_of_booking(booking_id):
    rows = [b for b in store.program_blocks.values() if b["booking_id"] == booking_id]
    return sorted(rows, key=lambda b: (b["sequence_index"], b["created_at"], b["_seq"]))


def blocks_of_element(element_id):
    rows = [b for b in store.program_blocks.values() if b["element_id"] == element_id]
    return sorted(rows, key=lambda b: (b["sequence_index"], b["created_at"], b["_seq"]))


def participants_of_booking(booking_id):
    return by_created_at([p for p in store.participants.values() if p["booking_id"] == booking_id])


def assignments_of_block(block_id):
    return by_created_at(
        [a for a in store.block_assignments.values() if a["program_block_id"] == block_id]
    )


def assignments_of_facilitator(facilitator_id):
    return by_created_at(
        [a for a in store.block_assignments.values() if a["facilitator_id"] == facilitator_id]
    )


def training_of_facilitator(facilitator_id):
    return by_created_at(
        [t for t in store.training_records.values() if t["facilitator_id"] == facilitator_id]
    )


def inspections_of_element(element_id):
    return by_created_at(
        [i for i in store.professional_inspections.values() if i["element_id"] == element_id]
    )


def logs_of_element(element_id):
    return by_created_at(
        [l for l in store.operational_logs.values() if l["element_id"] == element_id]
    )


def observations_of_course(course_id):
    return by_created_at(
        [o for o in store.weather_observations.values() if o["course_id"] == course_id]
    )


def incidents_of_course(course_id):
    return by_created_at([i for i in store.incidents.values() if i["course_id"] == course_id])


def incidents_of_element(element_id):
    return by_created_at([i for i in store.incidents.values() if i["element_id"] == element_id])


# ------------------------------------------------------- certification currency

def rescue_drill_last_passed_on(facilitator):
    dates = [
        t["completed_on"]
        for t in training_of_facilitator(facilitator["id"])
        if t["kind"] == "RESCUE_DRILL"
    ]
    return max(dates) if dates else None


def refresher_hours_24mo(facilitator):
    today = clock_date()
    window_start = today - timedelta(days=C.REFRESHER_WINDOW_DAYS)
    total = Decimal("0")
    for t in training_of_facilitator(facilitator["id"]):
        if t["kind"] not in ("REFRESHER", "RECERTIFICATION"):
            continue
        if t["completed_on"] < window_start:
            continue
        total += Decimal(str(t["hours"]))
    if total == total.to_integral_value():
        return int(total)
    return float(total)


def derive_cert_status(facilitator):
    """Ordered first-match walk (PRD 3.2)."""
    today = clock_date()
    if facilitator["cert_expires_on"] < today:
        return "LAPSED"
    drill = rescue_drill_last_passed_on(facilitator)
    if drill is None:
        return "PROBATION"
    if (today - drill).days > C.RESCUE_DRILL_VALID_DAYS:
        return "PROBATION"
    if Decimal(str(refresher_hours_24mo(facilitator))) < Decimal(C.REFRESHER_HOURS_REQUIRED):
        return "PROBATION"
    return "ACTIVE"


def refresh_cert_status(facilitator):
    """Re-derives cert_status; bumps the facilitator's version when it moves."""
    new_status = derive_cert_status(facilitator)
    if new_status != facilitator["cert_status"]:
        facilitator["cert_status"] = new_status
        touch(facilitator)
        return True
    return False


def rescue_current(facilitator):
    drill = rescue_drill_last_passed_on(facilitator)
    if drill is None:
        return False
    return (clock_date() - drill).days <= C.RESCUE_DRILL_VALID_DAYS


# ------------------------------------------------------------- element forecast

def recompute_element_forecast(element):
    """Two-variant retirement forecast (PRD 3.1)."""
    today = clock_date()
    installed_on = element["installed_on"]
    calendar_date = add_years(installed_on, element["design_life_years"])
    element["calendar_life_forecast_date"] = calendar_date

    days = (today - installed_on).days
    if days < 1:
        days = 1
    cumulative = element["cumulative_cycle_count"]
    remaining = element["cycle_life_limit"] - cumulative

    if remaining <= 0:
        usage_date = today
    elif cumulative == 0:
        # No history to project from: the calendar date stands alone.
        usage_date = None
    else:
        projected_days = ceil_div(remaining * days, cumulative)
        usage_date = add_days(today, projected_days)

    element["usage_life_forecast_date"] = usage_date

    if usage_date is None:
        element["retirement_forecast_date"] = calendar_date
        element["retirement_basis"] = "CALENDAR"
    else:
        if calendar_date <= usage_date:
            element["retirement_forecast_date"] = calendar_date
            element["retirement_basis"] = "CALENDAR"
        else:
            element["retirement_forecast_date"] = usage_date
            element["retirement_basis"] = "USAGE"


# ----------------------------------------------------------- equipment forecast

def recompute_equipment_forecast(item):
    kind = item["equipment_kind"]
    mfg_date = add_years(item["manufactured_on"], C.MFG_SHELF_LIFE_YEARS[kind])
    item["mfg_life_forecast_date"] = mfg_date
    if item["first_use_on"] is None:
        service_date = None
    else:
        service_date = add_years(item["first_use_on"], C.SERVICE_LIFE_YEARS[kind])
    item["service_life_forecast_date"] = service_date

    if service_date is None:
        item["retirement_forecast_date"] = mfg_date
    else:
        item["retirement_forecast_date"] = min(mfg_date, service_date)

    if item["usage_cycles"] >= item["max_cycles"]:
        item["retirement_basis"] = "CYCLE"
    elif service_date is None:
        item["retirement_basis"] = "MANUFACTURE"
    elif mfg_date <= service_date:
        item["retirement_basis"] = "MANUFACTURE"
    else:
        item["retirement_basis"] = "SERVICE"


def equipment_date_basis(item):
    """MANUFACTURE or SERVICE — whichever date won, ignoring the cycle clause."""
    service_date = item["service_life_forecast_date"]
    if service_date is None:
        return "MANUFACTURE"
    if item["mfg_life_forecast_date"] <= service_date:
        return "MANUFACTURE"
    return "SERVICE"


def equipment_viable(item):
    today = clock_date()
    return item["retirement_forecast_date"] > today and item["usage_cycles"] < item["max_cycles"]


# --------------------------------------------------------------- belay readiness

def belay_ready(element):
    required = element["required_belay_set_count"]
    rigged = equipment_of_element(element["id"])
    for item in rigged:
        if item["status"] == "QUARANTINED":
            return False
    usable = 0
    for item in rigged:
        if item["status"] != "IN_SERVICE":
            continue
        if not equipment_viable(item):
            continue
        usable += 1
    return usable >= required


# ------------------------------------------------------------- element rollups

def latest_inspection_outcome(element):
    disposed = [i for i in inspections_of_element(element["id"]) if i["status"] == "DISPOSED"]
    if not disposed:
        return "NONE"
    disposed.sort(key=lambda i: (i["performed_on"], i["created_at"], i["_seq"]), reverse=True)
    return disposed[0]["outcome"]


def newest_log(element_id):
    logs = logs_of_element(element_id)
    if not logs:
        return None
    logs.sort(key=lambda l: (l["log_date"], l["created_at"], l["_seq"]), reverse=True)
    return logs[0]


def last_clear_log_date(element_id):
    logs = [l for l in logs_of_element(element_id) if l["result"] == "CLEAR"]
    if not logs:
        return None
    logs.sort(key=lambda l: (l["log_date"], l["created_at"], l["_seq"]), reverse=True)
    return logs[0]["log_date"]


def daily_inspection_satisfied(element_id):
    """A CLEAR log dated on the clock date, with no later log that is not CLEAR."""
    today = clock_date()
    logs = logs_of_element(element_id)
    logs.sort(key=lambda l: (l["log_date"], l["created_at"], l["_seq"]))
    clear_today = None
    for log in logs:
        if log["log_date"] == today and log["result"] == "CLEAR":
            clear_today = log
    if clear_today is None:
        return False
    key = (clear_today["log_date"], clear_today["created_at"], clear_today["_seq"])
    for log in logs:
        if (log["log_date"], log["created_at"], log["_seq"]) > key and log["result"] != "CLEAR":
            return False
    return True


# ---------------------------------------------------------------- course rollups

def latest_observation(course_id):
    rows = observations_of_course(course_id)
    if not rows:
        return None
    rows.sort(key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]), reverse=True)
    return rows[0]


def latest_wind_speed_kph(course_id):
    obs = latest_observation(course_id)
    return obs["wind_speed_kph"] if obs else C.DEFAULT_LATEST_WIND_KPH


def latest_air_temp_c(course_id):
    obs = latest_observation(course_id)
    return obs["air_temp_c"] if obs else C.DEFAULT_LATEST_TEMP_C


def latest_lightning_distance_km(course_id):
    obs = latest_observation(course_id)
    return obs["lightning_distance_km"] if obs else None


def latest_observation_at(course_id):
    obs = latest_observation(course_id)
    return obs["observed_at"] if obs else None


def restricted_element_count(course_id):
    return len([e for e in elements_of_course(course_id) if e["status"] == "RESTRICTED"])


def out_of_service_element_count(course_id):
    return len([e for e in elements_of_course(course_id) if e["status"] == "OUT_OF_SERVICE"])


def quarantined_equipment_count(course_id):
    return len([e for e in equipment_of_course(course_id) if e["status"] == "QUARANTINED"])


def rescue_ready_facilitator_count(course_id):
    return len([f for f in facilitators_of_course(course_id) if f["cert_status"] == "ACTIVE"])


def rescue_readiness_ok(course):
    if rescue_ready_facilitator_count(course["id"]) < C.RESCUE_READY_MINIMUM:
        return False
    return course["ems_response_minutes"] <= C.EMS_MAX_MINUTES


def course_next_professional_inspection_due_on(course_id):
    dates = [
        e["next_professional_inspection_due_on"]
        for e in elements_of_course(course_id)
        if e["status"] != "RETIRED" and e["next_professional_inspection_due_on"] is not None
    ]
    return min(dates) if dates else None


def at_risk_booking_count(course_id):
    return len([
        b for b in bookings_of_course(course_id)
        if b["status"] in ("AT_RISK", "WEATHER_HOLD")
    ])


def has_open_serious_incident(course_id):
    for incident in incidents_of_course(course_id):
        if incident["severity"] == "SERIOUS" and incident["status"] == "UNDER_REVIEW":
            return True
    return False


# ------------------------------------------------------------------- posture

def derive_posture(course):
    """The ordered ten-clause first-match walk of PRD 2.5."""
    now = clock_now()
    today = clock_date()
    course_id = course["id"]

    hold = course["lightning_hold_until"]
    if hold is not None and hold > now:
        return "CLOSED", "LIGHTNING_STOP"

    wind = latest_wind_speed_kph(course_id)
    if wind >= C.WIND_STOP_KPH:
        return "CLOSED", "WIND_STOP"

    temp = latest_air_temp_c(course_id)
    if temp <= C.TEMP_STOP_C:
        return "CLOSED", "COLD_STOP"

    due = course_next_professional_inspection_due_on(course_id)
    if due is not None and due < today:
        return "CLOSED", "INSPECTION_OVERDUE"

    if not rescue_readiness_ok(course):
        return "CLOSED", "RESCUE_READINESS"

    if has_open_serious_incident(course_id):
        return "RESTRICTED", "SERIOUS_INCIDENT"

    if restricted_element_count(course_id) > 0 or out_of_service_element_count(course_id) > 0:
        return "RESTRICTED", "ELEMENT_RESTRICTED"

    lightning = latest_lightning_distance_km(course_id)
    if lightning is not None and C.LIGHTNING_STOP_KM < lightning <= C.LIGHTNING_WATCH_KM:
        return "RESTRICTED", "LIGHTNING_WATCH"

    if C.WIND_WATCH_KPH <= wind < C.WIND_STOP_KPH:
        return "RESTRICTED", "WIND_WATCH"

    return "OPEN", "NONE"


def recompute_posture(course, bump_version=True):
    posture, reason = derive_posture(course)
    changed = posture != course["posture"] or reason != course["posture_reason"]
    course["posture"] = posture
    course["posture_reason"] = reason
    if bump_version or changed:
        touch(course)
    return changed


# ------------------------------------------------------------------ participants

def age_years(participant, booking):
    birth = participant["birth_date"]
    on = booking["program_date"]
    years = on.year - birth.year
    if (on.month, on.day) < (birth.month, birth.day):
        years -= 1
    return years


def is_minor(participant, booking):
    return age_years(participant, booking) < C.ADULT_AGE_YEARS


def screening_status(participant, booking):
    """Ordered first-match walk (PRD 3.6)."""
    if not participant["agreement_signed"]:
        return "BLOCKED"
    if participant["health_form_status"] == "MISSING":
        return "BLOCKED"
    if is_minor(participant, booking) and not participant["guardian_signature_provided"]:
        return "BLOCKED"
    if participant["health_form_status"] == "FLAGGED" and not participant["medical_clearance_granted"]:
        return "CONDITIONAL"
    return "ELIGIBLE"


def roster_status(booking):
    people = participants_of_booking(booking["id"])
    if not people:
        return "INCOMPLETE"
    statuses = [screening_status(p, booking) for p in people]
    if any(s in ("BLOCKED", "CONDITIONAL") for s in statuses):
        return "BLOCKED"
    if not any(not p["is_chaperone"] for p in people):
        return "INCOMPLETE"
    return "READY"


def required_chaperone_count(booking):
    minors = [
        p for p in participants_of_booking(booking["id"])
        if not p["is_chaperone"] and is_minor(p, booking)
    ]
    return ceil_div(len(minors), C.CHAPERONE_RATIO_MINORS)


def billable_head_count(booking):
    return len([p for p in participants_of_booking(booking["id"]) if not p["is_chaperone"]])


def eligible_participants(booking):
    return [p for p in participants_of_booking(booking["id"])
            if screening_status(p, booking) == "ELIGIBLE"]


def active_head_count(booking):
    """Eligible non-chaperone heads — the supervision sizing base."""
    return len([p for p in eligible_participants(booking) if not p["is_chaperone"]])


# ------------------------------------------------------------------ block rollups

def block_count(booking_id):
    return len(blocks_of_booking(booking_id))


def blocked_block_count(booking_id):
    return len([b for b in blocks_of_booking(booking_id) if b["status"] == "BLOCKED_UNSAFE"])


def assigned_facilitator_count(block_id):
    return len(assignments_of_block(block_id))


def required_facilitator_count(block):
    """Maximum over the ratio dimension, the phase floor and the type floor."""
    booking = store.bookings.get(block["booking_id"])
    heads = active_head_count(booking) if booking else 0
    element = store.elements.get(block["element_id"]) if block["element_id"] else None

    if element is None:
        ratio_dimension = 0
    else:
        ratio_dimension = ceil_div(heads, C.RATIO_BY_ELEMENT_TYPE[element["element_type"]])

    phase_floor = C.MIN_FACILITATORS_BY_PHASE[block["phase"]]

    if element is not None and element["element_type"] in C.HIGH_RISK_ELEMENT_TYPES:
        type_floor = C.HIGH_RISK_TYPE_FLOOR
    else:
        type_floor = 0

    return max(ratio_dimension, phase_floor, type_floor)


def block_supervision_capacity(block_id):
    total = 0
    for assignment in assignments_of_block(block_id):
        facilitator = store.facilitators.get(assignment["facilitator_id"])
        if facilitator is None:
            continue
        total += C.SUPERVISION_CAPACITY_BY_LEVEL[facilitator["certification_level"]]
    return total


def required_cert_level_for_block(block):
    if not block["element_id"]:
        return "LEVEL_1"
    element = store.elements.get(block["element_id"])
    if element is None:
        return "LEVEL_1"
    return C.REQUIRED_CERT_LEVEL_BY_ELEMENT_TYPE[element["element_type"]]


# ------------------------------------------------------------------ client ledger

def late_cancellation_count(client_id):
    count = 0
    for booking in bookings_of_client(client_id):
        if booking["status"] != "CANCELLED":
            continue
        if booking["cancellation_variant"] != "CLIENT_INITIATED":
            continue
        notice = booking["notice_days_at_cancel"]
        if notice is not None and notice < 14:
            count += 1
    return count
