"""Derived state, cascades and selectors (PRD 2.10, 2.11, 3.2-3.9)."""

import calc
from errors import ApiError
from store import db, order_key


# --------------------------------------------------------------- collections
def station_of_shift(shift):
    return db.stations.get(shift["station_id"])


def apparatus_of_station(station_id):
    return [a for a in db.apparatus.values() if a["station_id"] == station_id]


def open_companies(shift):
    closed = set(shift.get("closed_apparatus_ids") or [])
    units = [
        a
        for a in apparatus_of_station(shift["station_id"])
        if a["status"] == "IN_SERVICE" and a["id"] not in closed
    ]
    units.sort(key=lambda a: (a["closure_priority"],) + order_key(a))
    return units


def assignments_of_shift(shift_id, statuses=None):
    items = [a for a in db.shift_assignments.values() if a["duty_shift_id"] == shift_id]
    if statuses is not None:
        items = [a for a in items if a["status"] in statuses]
    items.sort(key=order_key)
    return items


def vacancies_of_shift(shift_id, statuses=None):
    items = [v for v in db.vacancies.values() if v["duty_shift_id"] == shift_id]
    if statuses is not None:
        items = [v for v in items if v["status"] in statuses]
    items.sort(key=order_key)
    return items


def offers_of_shift(shift_id, statuses=None):
    out = []
    for offer in db.overtime_offers.values():
        vacancy = db.vacancies.get(offer["vacancy_id"])
        if vacancy is None or vacancy["duty_shift_id"] != shift_id:
            continue
        if statuses is not None and offer["status"] not in statuses:
            continue
        out.append(offer)
    out.sort(key=order_key)
    return out


def leave_requests_of_shift(shift_id, statuses=None):
    items = [l for l in db.leave_requests.values() if l["duty_shift_id"] == shift_id]
    if statuses is not None:
        items = [l for l in items if l["status"] in statuses]
    items.sort(key=order_key)
    return items


def assignments_of_member(firefighter_id, statuses=None):
    items = [
        a for a in db.shift_assignments.values() if a["firefighter_id"] == firefighter_id
    ]
    if statuses is not None:
        items = [a for a in items if a["status"] in statuses]
    items.sort(key=order_key)
    return items


# -------------------------------------------------------------- work periods
def covering_work_period(firefighter_id, shift_date):
    target = calc.date_str(shift_date)
    best = None
    for wp in db.work_periods.values():
        if wp["firefighter_id"] != firefighter_id:
            continue
        if wp["period_start_date"] <= target <= wp["period_end_date"]:
            if best is None or order_key(wp) < order_key(best):
                best = wp
    return best


def create_work_period(firefighter_id, start_date):
    start = calc.to_date(start_date)
    end = calc.add_days(start, calc.FLSA_PERIOD_DAYS - 1)
    wp = db.new(
        {
            "firefighter_id": firefighter_id,
            "period_start_date": calc.date_str(start),
            "period_end_date": calc.date_str(end),
            "flsa_threshold_hours": calc.FLSA_THRESHOLD_HOURS,
            "adjusted_scheduled_hours": 0,
            "adjusted_worked_hours": 0,
            "scheduled_hours": 0,
            "worked_hours": 0,
            "leave_hours": 0,
            "projected_flsa_overtime_hours": 0,
            "final_flsa_overtime_hours": 0,
            "flsa_premium_cents": 0,
            "status": "OPEN",
        }
    )
    db.work_periods[wp["id"]] = wp
    return wp


def recompute_work_period(wp):
    """calculations.work_period_hour_ledger + flsa_work_period_overtime."""
    member = db.firefighters.get(wp["firefighter_id"])
    start = wp["period_start_date"]
    end = wp["period_end_date"]

    scheduled = 0.0
    worked = 0.0
    for asg in db.shift_assignments.values():
        if asg["firefighter_id"] != wp["firefighter_id"]:
            continue
        if asg["status"] not in ("SCHEDULED", "WORKED"):
            continue
        shift = db.duty_shifts.get(asg["duty_shift_id"])
        if shift is None:
            continue
        if not (start <= shift["shift_date"] <= end):
            continue
        scheduled += float(asg["scheduled_hours"] or 0)
        if asg["status"] == "WORKED":
            worked += float(asg["actual_hours"] or 0)

    leave = 0.0
    for leave_request in db.leave_requests.values():
        if leave_request["firefighter_id"] != wp["firefighter_id"]:
            continue
        if leave_request["status"] != "APPROVED":
            continue
        shift = db.duty_shifts.get(leave_request["duty_shift_id"])
        if shift is None:
            continue
        if not (start <= shift["shift_date"] <= end):
            continue
        leave += float(leave_request["requested_hours"] or 0)

    scheduled += float(wp["adjusted_scheduled_hours"] or 0)
    worked += float(wp["adjusted_worked_hours"] or 0)

    threshold = float(wp["flsa_threshold_hours"] or 0)
    projected = max(0.0, scheduled - threshold)
    final = max(0.0, worked - threshold)
    basis = projected if wp["status"] == "OPEN" else final
    rate = int(member["hourly_rate_cents"]) if member else 0
    premium = calc.flsa_premium_cents(basis, rate)

    changed = _apply(
        wp,
        {
            "scheduled_hours": calc.num(scheduled),
            "worked_hours": calc.num(worked),
            "leave_hours": calc.num(leave),
            "projected_flsa_overtime_hours": calc.num(projected),
            "final_flsa_overtime_hours": calc.num(final),
            "flsa_premium_cents": premium,
        },
    )
    if changed:
        db.touch(wp)
    return wp


def recompute_member_work_periods(firefighter_id):
    for wp in list(db.work_periods.values()):
        if wp["firefighter_id"] == firefighter_id:
            recompute_work_period(wp)


def scheduled_hours_of_covering_period(firefighter_id, shift_date):
    wp = covering_work_period(firefighter_id, shift_date)
    if wp is None:
        return 0.0, None
    return float(wp["scheduled_hours"] or 0), wp


# -------------------------------------------------------------------- helpers
def _apply(entity, updates):
    changed = False
    for key, value in updates.items():
        if entity.get(key) != value:
            entity[key] = value
            changed = True
    return changed


# ----------------------------------------------------------------- station
def recompute_station(station):
    """PRD 2.10: ot_committed_cents is an invariant, not a running tally."""
    committed = 0
    for offer in db.overtime_offers.values():
        if offer["status"] != "OFFERED":
            continue
        vacancy = db.vacancies.get(offer["vacancy_id"])
        if vacancy is None:
            continue
        shift = db.duty_shifts.get(vacancy["duty_shift_id"])
        if shift is None or shift["station_id"] != station["id"]:
            continue
        committed += int(offer["projected_cost_cents"] or 0)
    for asg in db.shift_assignments.values():
        if asg["status"] != "SCHEDULED":
            continue
        if asg["assignment_type"] not in ("OVERTIME", "HOLDOVER", "CALLBACK"):
            continue
        shift = db.duty_shifts.get(asg["duty_shift_id"])
        if shift is None or shift["station_id"] != station["id"]:
            continue
        committed += int(asg["projected_premium_cents"] or 0)

    posture = calc.budget_posture(
        station["ot_actual_cents"], committed, station["fiscal_ot_budget_cents"]
    )
    if _apply(station, {"ot_committed_cents": committed, "budget_posture": posture}):
        db.touch(station)
    return station


# ---------------------------------------------------------------- duty shift
def compute_required_staffing(shift):
    return sum(a["minimum_crew_size"] for a in open_companies(shift))


def compute_certification_gap(shift):
    scheduled = assignments_of_shift(shift["id"], ("SCHEDULED",))
    total = 0
    for company in open_companies(shift):
        needed = list(company.get("required_certifications") or [])
        held = [
            a["seat_certification"]
            for a in scheduled
            if a["apparatus_id"] == company["id"] and a["seat_certification"] != "NONE"
        ]
        total += len(calc.multiset_difference(needed, held))
    return total


def recompute_shift(shift, auto_transition=True):
    station = station_of_shift(shift)
    required = compute_required_staffing(shift)
    assigned = len(assignments_of_shift(shift["id"], ("SCHEDULED",)))
    gap = max(0, required - assigned)
    cert_gap = compute_certification_gap(shift)
    floor = max(
        int(station["minimum_staffing_floor"]) if station else 0,
        required - calc.LEAVE_FLOOR_SLACK,
    )
    open_count = len(vacancies_of_shift(shift["id"], ("OPEN", "OFFERING")))
    posture = calc.staffing_posture(gap, cert_gap)

    updates = {
        "required_staffing": required,
        "assigned_headcount": assigned,
        "staffing_gap": gap,
        "certification_gap_count": cert_gap,
        "leave_floor_headcount": floor,
        "open_vacancy_count": open_count,
        "staffing_posture": posture,
    }
    if auto_transition:
        if shift["status"] == "HIRING" and open_count == 0:
            updates["status"] = "STAFFED"
        elif shift["status"] == "STAFFED" and open_count >= 1:
            updates["status"] = "HIRING"

    if _apply(shift, updates):
        db.touch(shift)
    return shift


def create_vacancy(shift, apparatus_id, driver, driver_source_id,
                   required_certification, seat_index):
    vacancy = db.new(
        {
            "duty_shift_id": shift["id"],
            "apparatus_id": apparatus_id,
            "filled_by_assignment_id": None,
            "driver": driver,
            "driver_source_id": driver_source_id,
            "required_certification": required_certification or "NONE",
            "seat_index": seat_index,
            "status": "OPEN",
        }
    )
    db.vacancies[vacancy["id"]] = vacancy
    return vacancy


def next_seat_index(shift_id, apparatus_id):
    existing = [
        v
        for v in db.vacancies.values()
        if v["duty_shift_id"] == shift_id and v["apparatus_id"] == apparatus_id
    ]
    return len(existing) + 1


def generate_vacancies(shift):
    """calculations.vacancy_generation (PRD 3.2)."""
    scheduled = assignments_of_shift(shift["id"], ("SCHEDULED",))
    created = 0
    for company in open_companies(shift):
        on_company = [a for a in scheduled if a["apparatus_id"] == company["id"]]
        filled = len(on_company)
        open_seats = max(0, int(company["minimum_crew_size"]) - filled)
        held = [
            a["seat_certification"] for a in on_company if a["seat_certification"] != "NONE"
        ]
        unmet = sorted(
            calc.multiset_difference(list(company.get("required_certifications") or []), held)
        )
        for seat_index in range(1, open_seats + 1):
            required_certification = (
                unmet[seat_index - 1] if seat_index <= len(unmet) else "NONE"
            )
            create_vacancy(
                shift, company["id"], "VACANT_POSITION", None, required_certification,
                seat_index,
            )
            created += 1
    return created


# ------------------------------------------------------------------- offers
def rescind_offer(offer):
    """PRD 3.7: the department withdrew, so the member is charged nothing."""
    offer["status"] = "RESCINDED"
    db.touch(offer)
    member = db.firefighters.get(offer["firefighter_id"])
    if member is not None:
        member["pending_offer_count"] = max(0, int(member["pending_offer_count"]) - 1)
        db.touch(member)


def charge_pass(offer, new_status):
    """Shared decline / expiry consequences (PRD 3.7)."""
    offer["status"] = new_status
    db.touch(offer)
    member = db.firefighters.get(offer["firefighter_id"])
    if member is not None:
        member["voluntary_ot_hours_charged"] = calc.num(
            float(member["voluntary_ot_hours_charged"] or 0)
            + float(offer["offer_hours"] or 0)
        )
        member["ot_pass_count"] = int(member["ot_pass_count"]) + 1
        member["pending_offer_count"] = max(0, int(member["pending_offer_count"]) - 1)
        if member["ot_pass_count"] >= calc.OT_PASS_LIMIT:
            member["roster_standing"] = "PASSED"
        db.touch(member)
    vacancy = db.vacancies.get(offer["vacancy_id"])
    if vacancy is not None and vacancy["status"] == "OFFERING":
        vacancy["status"] = "OPEN"
        db.touch(vacancy)


def cancel_vacancy_and_rescind(vacancy, new_status):
    vacancy["status"] = new_status
    db.touch(vacancy)
    for offer in offers_of_vacancy(vacancy["id"]):
        if offer["status"] == "OFFERED":
            rescind_offer(offer)


def offers_of_vacancy(vacancy_id):
    items = [o for o in db.overtime_offers.values() if o["vacancy_id"] == vacancy_id]
    items.sort(key=order_key)
    return items


# ------------------------------------------------------- interval / capacity
def member_intervals(firefighter_id, exclude_assignment_id=None):
    intervals = []
    for asg in assignments_of_member(firefighter_id, ("SCHEDULED",)):
        if exclude_assignment_id is not None and asg["id"] == exclude_assignment_id:
            continue
        shift = db.duty_shifts.get(asg["duty_shift_id"])
        if shift is None:
            continue
        intervals.append(calc.interval_for(shift["shift_date"], asg["scheduled_hours"]))
    return intervals


def check_double_booking(firefighter_id, prospective, exclude_assignment_id=None):
    for existing in member_intervals(firefighter_id, exclude_assignment_id):
        if calc.intervals_overlap(existing, prospective):
            raise ApiError("ERR_DOUBLE_BOOKED_SHIFT")


def continuous_duty(firefighter_id, prospective, exclude_assignment_id=None):
    hours = calc.merged_block_hours(
        member_intervals(firefighter_id, exclude_assignment_id), prospective
    )
    return hours, hours > calc.CONTINUOUS_DUTY_FATIGUE_HOURS


def check_rest_period(firefighter_id, prospective, exclude_assignment_id=None):
    hours, fatigue = continuous_duty(firefighter_id, prospective, exclude_assignment_id)
    if hours > calc.CONTINUOUS_DUTY_MAX_HOURS:
        raise ApiError("ERR_REST_PERIOD_VIOLATION")
    return hours, fatigue


def check_seat_capacity(shift_id, apparatus):
    riding = len(
        [
            a
            for a in assignments_of_shift(shift_id, ("SCHEDULED",))
            if a["apparatus_id"] == apparatus["id"]
        ]
    )
    capacity = int(apparatus["minimum_crew_size"]) + calc.MAX_OVERSTAFF_SEATS
    if riding + 1 > capacity:
        raise ApiError("ERR_APPARATUS_SEAT_CAPACITY_EXCEEDED")


def check_flsa_cap(firefighter_id, shift_date, hours):
    current, wp = scheduled_hours_of_covering_period(firefighter_id, shift_date)
    if current + float(hours) > calc.FLSA_MAX_PERIOD_HOURS:
        raise ApiError("ERR_FLSA_WORK_PERIOD_CAP_EXCEEDED")
    return wp


# ------------------------------------------------------- hiring order (3.6)
def resolve_roster(shift, wanted_type, required_certification):
    candidates = [
        r
        for r in db.hiring_rosters.values()
        if r["station_id"] == shift["station_id"] and r["roster_type"] == wanted_type
    ]
    scoped = [r for r in candidates if r["certification_scope"] == required_certification]
    if scoped:
        scoped.sort(key=order_key)
        return scoped[0]
    general = [r for r in candidates if r["certification_scope"] == "NONE"]
    if general:
        general.sort(key=order_key)
        return general[0]
    return None


def select_candidate(shift, vacancy, hiring_mode, payable_hours):
    """calculations.hiring_order_selector (PRD 3.6)."""
    required_certification = vacancy["required_certification"]
    shift_date = shift["shift_date"]
    on_duty = calc.platoon_on_duty(shift_date)

    base = []
    for member in db.firefighters.values():
        if member["station_id"] != shift["station_id"]:
            continue
        if member["employment_status"] != "ACTIVE":
            continue
        if required_certification != "NONE" and required_certification not in (
            member.get("certifications") or []
        ):
            continue
        if any(
            a["duty_shift_id"] == shift["id"]
            for a in assignments_of_member(member["id"], ("SCHEDULED",))
        ):
            continue
        if any(
            l["duty_shift_id"] == shift["id"] and l["status"] == "APPROVED"
            for l in db.leave_requests.values()
            if l["firefighter_id"] == member["id"]
        ):
            continue
        if int(member["pending_offer_count"]) != 0:
            continue
        current, _wp = scheduled_hours_of_covering_period(member["id"], shift_date)
        if current + float(payable_hours) > calc.FLSA_MAX_PERIOD_HOURS:
            continue
        base.append(member)

    if hiring_mode == "VOLUNTARY":
        pool = [
            m
            for m in base
            if m["roster_standing"] == "AVAILABLE" and not calc.is_kelly_day(m, shift_date)
        ]
        pool.sort(
            key=lambda m: (
                float(m["voluntary_ot_hours_charged"] or 0),
                int(m["seniority_rank"]),
            )
            + order_key(m)
        )
    elif hiring_mode == "CALLBACK":
        pool = [
            m
            for m in base
            if m["roster_standing"] == "AVAILABLE" and m["platoon"] != on_duty
        ]
        pool.sort(
            key=lambda m: (int(m["callback_count"]), int(m["seniority_rank"])) + order_key(m)
        )
    else:  # MANDATORY_HOLDOVER
        outgoing = calc.platoon_on_duty(calc.add_days(shift_date, -1))
        pool = [
            m
            for m in base
            if m["roster_standing"] != "UNAVAILABLE" and m["platoon"] == outgoing
        ]
        pool.sort(
            key=lambda m: (int(m["mandatory_holdover_count"]), -int(m["seniority_rank"]))
            + order_key(m)
        )

    if not pool:
        return None
    return pool[0]


# ------------------------------------------------- company closure selector
def select_closure_company(shift):
    closed = set(shift.get("closed_apparatus_ids") or [])
    pool = [
        a
        for a in apparatus_of_station(shift["station_id"])
        if a["status"] == "IN_SERVICE"
        and not a["closure_exempt"]
        and a["id"] not in closed
    ]
    if not pool:
        return None
    pool.sort(
        key=lambda a: (-int(a["closure_priority"]), -int(a["minimum_crew_size"]))
        + order_key(a)
    )
    return pool[0]


# -------------------------------------------------------------- lookups (404)
def require(collection, key, error_id):
    entity = collection.get(key)
    if entity is None:
        raise ApiError(error_id)
    return entity


def require_active_shift(shift):
    if shift["status"] not in ("HIRING", "STAFFED"):
        raise ApiError("ERR_SHIFT_NOT_HIRING")
    return shift
