"""Domain logic: serializers, computed fields, cage capacity, per-diem billing,
productivity scoring, and logical-clock-driven transitions (PRD §2.4, §3).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, iso, now, new_rec

# ---------------------------------------------------------------------------
# Calculation constants (scaffold §1.3)
# ---------------------------------------------------------------------------
MOUSE_RATE = 125
RAT_PUP_RATE = 75
RAT_ADULT_RATE = 150
RAT_AGED_RATE = 210
RABBIT_RATE = 400
ZEBRAFISH_RATE = 40
FLAT_RATES = {"MOUSE": MOUSE_RATE, "RABBIT": RABBIT_RATE, "ZEBRAFISH": ZEBRAFISH_RATE}
PUP_AGE_DAYS = 21
AGED_AGE_DAYS = 365
SEMIANNUAL_DAYS = 180
TURNOVER_MINUTES = 30
LITTER_WEIGHT = Decimal("3")
PUP_WEIGHT = Decimal("0.5")
NONPROD_PENALTY = Decimal("0.05")
REQUIRED_COURSES = ("ANIMAL_HANDLING", "ASEPTIC_TECHNIQUE", "EUTHANASIA", "SPECIES_SPECIFIC")
SEVERE_GRADES = {"SEVERE", "MORBUND"}


def day_start(dt):
    """Midnight UTC of the calendar day containing dt."""
    dt = dt.astimezone(timezone.utc)
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def plus_years(dt, years):
    """Calendar-year addition (protocol 3-year expiry)."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + years, day=28)


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------

def budget_remaining(grant):
    """budget_total minus per-diem charges of POSTED billing runs (per_diem_billing)."""
    posted_ids = {
        r.id for r in STORE["billing_runs"].values() if r.state == "POSTED"
    }
    debited = sum(
        c.amount_cents
        for c in STORE["per_diem_charges"].values()
        if c.grant_id == grant.id and c.billing_run_id in posted_ids
    )
    return grant.budget_total_cents - debited


def animals_used_count(protocol):
    """Count of Animals on the protocol excluding only TRANSFERRED_OUT."""
    return sum(
        1
        for a in STORE["animals"].values()
        if a.protocol_id == protocol.id and a.status != "TRANSFERRED_OUT"
    )


def training_gate(personnel_id):
    """True iff every required course has a COMPLETED, unexpired enrollment."""
    for course in REQUIRED_COURSES:
        ok = any(
            e.personnel_id == personnel_id
            and e.course_code == course
            and e.state == "COMPLETED"
            and (e.expires_at is None or e.expires_at > now())
            for e in STORE["training_enrollments"].values()
        )
        if not ok:
            return False
    return True


def occ_health_gate(personnel_id):
    """True iff a CLEARED, unexpired occ-health enrollment exists."""
    return any(
        e.personnel_id == personnel_id
        and e.state == "CLEARED"
        and (e.expires_at is None or e.expires_at > now())
        for e in STORE["occ_health_enrollments"].values()
    )


def personnel_cleared(personnel_id):
    return training_gate(personnel_id) and occ_health_gate(personnel_id)


# ---------------------------------------------------------------------------
# Cage capacity (cage_capacity)
# ---------------------------------------------------------------------------

def pup_counts_toward_capacity(animal, at=None):
    """Nursing pups are exempt through their 21st day; on day 22 they count."""
    at = at or now()
    return (at - animal.date_of_birth) > timedelta(days=PUP_AGE_DAYS)


def effective_occupancy(cage_id):
    """ALIVE adults (litter_id null) + ALIVE pups older than 21 days."""
    n = 0
    for a in STORE["animals"].values():
        if a.cage_id != cage_id or a.status != "ALIVE":
            continue
        if a.litter_id is None:
            n += 1
        elif pup_counts_toward_capacity(a):
            n += 1
    return n


def animal_counts_toward_capacity(animal):
    """Would adding this (ALIVE) animal consume one capacity slot right now?"""
    if animal.litter_id is None:
        return True
    return pup_counts_toward_capacity(animal)


def recompute_cage(cage, always_bump=True):
    """Recompute cage lifecycle status from effective occupancy (PRD §3.4).

    eff > capacity          -> OVER_CAPACITY
    eff == 0                -> EMPTY
    else                    -> OCCUPIED (protocol suspension forces OVER_CAPACITY)
    """
    if cage.status == "DECOMMISSIONED":
        return
    eff = effective_occupancy(cage.id)
    proto = STORE["protocols"].get(cage.protocol_id)
    suspended = proto is not None and proto.status == "SUSPENDED"
    if eff == 0:
        new_status = "EMPTY"
    elif eff > cage.capacity_adults or suspended:
        new_status = "OVER_CAPACITY"
    else:
        new_status = "OCCUPIED"
    changed = new_status != cage.status
    if changed:
        if new_status == "OCCUPIED" and cage.status == "EMPTY":
            cage.occupied_since = now()
        if new_status == "EMPTY":
            cage.occupied_since = None
        cage.status = new_status
    if changed or always_bump:
        cage.touch()


# ---------------------------------------------------------------------------
# Animal placement history (for per-diem occupancy reconstruction)
# ---------------------------------------------------------------------------

def open_placement(animal, cage_id):
    animal.placements.append({"cage_id": cage_id, "start": now(), "end": None})


def close_placement(animal):
    cur = animal.placements[-1]
    if cur["end"] is None:
        cur["end"] = now()


def animal_present_in_cage_on_day(animal, cage_id, d0):
    """Placement intersects calendar day [d0, d0+1)."""
    d1 = d0 + timedelta(days=1)
    for p in animal.placements:
        if p["cage_id"] != cage_id:
            continue
        if p["start"] < d1 and (p["end"] is None or p["end"] > d0):
            return True
    return False


def animal_excluded_final(animal, d0):
    """FINAL variant: exclude animals RETIRED/EUTHANIZED/TRANSFERRED_OUT on or
    after their status-change date from the day's headcount."""
    if animal.status in ("RETIRED", "EUTHANIZED", "TRANSFERRED_OUT"):
        sc = animal.status_changed_at
        if sc is not None and day_start(sc) <= d0:
            return True
    return False


def rat_tier_on_day(animal, d0):
    age = d0 - animal.date_of_birth
    if age < timedelta(days=PUP_AGE_DAYS):
        return RAT_PUP_RATE
    if age > timedelta(days=AGED_AGE_DAYS):
        return RAT_AGED_RATE
    return RAT_ADULT_RATE


def census_confirms_occupancy(cage_id, d0):
    """A reconciled census (discrepancy == 0) confirms occupancy for the day."""
    for c in STORE["census_records"].values():
        if (
            c.cage_id == cage_id
            and day_start(c.census_date) == d0
            and c.discrepancy == 0
            and c.physical_count >= 1
        ):
            return True
    return False


def compute_charge_for_cage(cage, period_start, period_end, variant):
    """Per-diem billing (PROVISIONAL cage-day model / FINAL reconciled model).

    Returns dict(cage_days, rate_cents, amount_cents) or None when the cage
    accrued no billable days in the period.
    """
    occupants = [a for a in STORE["animals"].values()]
    cage_days = 0
    amount = 0
    rates_seen = []
    d0 = day_start(period_start)
    end = day_start(period_end)
    while d0 < end:
        if variant == "PROVISIONAL":
            todays = [
                a
                for a in occupants
                if animal_present_in_cage_on_day(a, cage.id, d0)
            ]
        else:  # FINAL
            todays = [
                a
                for a in occupants
                if animal_present_in_cage_on_day(a, cage.id, d0)
                and not animal_excluded_final(a, d0)
            ]
            if todays and not census_confirms_occupancy(cage.id, d0):
                todays = []
        if todays:
            cage_days += 1
            if cage.species == "RAT":
                daily = max(rat_tier_on_day(a, d0) for a in todays)
            else:
                daily = FLAT_RATES[cage.species]
            # integer cents per day (round-half-up is identity on integers)
            daily = int(
                Decimal(daily).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
            rates_seen.append(daily)
            amount += daily
        d0 += timedelta(days=1)
    if cage_days == 0:
        return None
    rate_cents = max(rates_seen) if rates_seen else FLAT_RATES.get(cage.species, 0)
    return {"cage_days": cage_days, "rate_cents": rate_cents, "amount_cents": amount}


# ---------------------------------------------------------------------------
# Breeding productivity (breeding_productivity)
# ---------------------------------------------------------------------------

def productivity(cage):
    litters = [
        l
        for l in STORE["litters"].values()
        if l.cage_id == cage.id and l.state in ("WEANED", "CLOSED")
    ]
    weaned_litters = len(litters)
    weaned_pups = sum(l.weaned_count for l in litters)

    nonproductive_days = 0
    if cage.occupied_since is not None:
        cage_litters = [l for l in STORE["litters"].values() if l.cage_id == cage.id]
        d = day_start(cage.occupied_since)
        last = day_start(now())
        while d <= last:
            d1 = d + timedelta(days=1)
            covered = any(
                l.born_on < d1 and (l.closed_at is None or l.closed_at > d)
                for l in cage_litters
            )
            if not covered:
                nonproductive_days += 1
            d = d1

    raw = (
        LITTER_WEIGHT * weaned_litters
        + PUP_WEIGHT * weaned_pups
        - NONPROD_PENALTY * nonproductive_days
    )
    score = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if score < 0:
        score = Decimal("0.00")
    return {
        "cage_id": cage.id,
        "score": float(score),
        "weaned_litters": weaned_litters,
        "weaned_pups": weaned_pups,
        "nonproductive_days": nonproductive_days,
    }


# ---------------------------------------------------------------------------
# Protocol suspension cascade (shared by suspend + deviation impose-suspension)
# ---------------------------------------------------------------------------

def suspend_protocol_cascade(protocol):
    """APPROVED -> SUSPENDED with cage/adverse-event cascades (PRD §3.8)."""
    if protocol.status != "APPROVED":
        return
    protocol.status = "SUSPENDED"
    protocol.touch()
    for cage in STORE["cages"].values():
        if cage.protocol_id == protocol.id and cage.status == "OCCUPIED":
            cage.status = "OVER_CAPACITY"
            cage.touch()
    for ev in STORE["adverse_events"].values():
        if ev.protocol_id == protocol.id and ev.state in ("OPEN", "UNDER_TREATMENT"):
            ev.state = "ESCALATED"
            ev.touch()


def file_deviation_from_escalation(event):
    """deviation_escalation cascade: SEVERE/MORBUND auto-files SERIOUS deviation."""
    new_rec(
        "deviations",
        protocol_id=event.protocol_id,
        reported_by_personnel_id=event.reported_by_personnel_id,
        description=(
            "Auto-filed SERIOUS deviation from escalation of adverse event "
            f"{event.id}"
        ),
        seriousness="SERIOUS",
        state="REPORTED",
    )


# ---------------------------------------------------------------------------
# Logical-clock-driven transitions (PRD §2.4)
# ---------------------------------------------------------------------------

def apply_clock_transitions():
    t = now()
    # Protocol expiry: APPROVED -> EXPIRED when clock reaches expires_at.
    for p in STORE["protocols"].values():
        if p.status == "APPROVED" and p.expires_at is not None and t >= p.expires_at:
            p.status = "EXPIRED"
            p.touch()
    # Training enrolment expiry: COMPLETED -> EXPIRED.
    for e in STORE["training_enrollments"].values():
        if e.state == "COMPLETED" and e.expires_at is not None and t >= e.expires_at:
            e.state = "EXPIRED"
            e.touch()
    # Occ-health clearance expiry: CLEARED -> EXPIRED.
    for e in STORE["occ_health_enrollments"].values():
        if e.state == "CLEARED" and e.expires_at is not None and t >= e.expires_at:
            e.state = "EXPIRED"
            e.touch()
    # Inspection lapse: SCHEDULED -> LAPSED once the clock passes due_by.
    for i in STORE["inspections"].values():
        if i.state == "SCHEDULED" and i.due_by is not None and t > i.due_by:
            i.state = "LAPSED"
            i.touch()
    # Adverse-event auto-escalation on 72h deadline breach.
    for ev in STORE["adverse_events"].values():
        if ev.state == "UNDER_TREATMENT" and t > ev.reported_at + timedelta(hours=72):
            ev.state = "ESCALATED"
            ev.touch()
            if ev.severity in SEVERE_GRADES:
                file_deviation_from_escalation(ev)
    # Pup aging may push cages over capacity (daily clock tick).
    for cage in STORE["cages"].values():
        recompute_cage(cage, always_bump=False)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(r):
    return {
        "id": r.id,
        "created_at": iso(r.created_dt),
        "updated_at": iso(r.updated_dt),
        "version": r.version,
    }


def ser_investigator(r):
    d = _common(r)
    d.update(
        full_name=r.full_name, email=r.email, department=r.department, status=r.status
    )
    return d


def ser_grant(r):
    d = _common(r)
    d.update(
        grant_number=r.grant_number,
        investigator_id=r.investigator_id,
        budget_total_cents=r.budget_total_cents,
        budget_remaining_cents=budget_remaining(r),
        expires_on=iso(r.expires_on),
    )
    return d


def ser_personnel(r):
    d = _common(r)
    d.update(
        full_name=r.full_name,
        email=r.email,
        role_on_protocols=r.role_on_protocols,
        training_completed=training_gate(r.id),
        occ_health_cleared=occ_health_gate(r.id),
        status=r.status,
    )
    return d


def ser_training_enrollment(r):
    d = _common(r)
    d.update(
        personnel_id=r.personnel_id,
        course_code=r.course_code,
        state=r.state,
        completed_at=iso(r.completed_at),
        expires_at=iso(r.expires_at),
    )
    return d


def ser_occ_health_enrollment(r):
    d = _common(r)
    d.update(
        personnel_id=r.personnel_id,
        state=r.state,
        cleared_at=iso(r.cleared_at),
        expires_at=iso(r.expires_at),
    )
    return d


def ser_protocol(r):
    d = _common(r)
    d.update(
        protocol_number=r.protocol_number,
        investigator_id=r.investigator_id,
        grant_id=r.grant_id,
        title=r.title,
        species=r.species,
        max_animals_justified=r.max_animals_justified,
        pain_category=r.pain_category,
        review_path=r.review_path,
        status=r.status,
        approved_at=iso(r.approved_at),
        expires_at=iso(r.expires_at),
        animals_used_count=animals_used_count(r),
    )
    return d


def ser_protocol_reviewer(r):
    d = _common(r)
    d.update(
        protocol_id=r.protocol_id,
        reviewer_name=r.reviewer_name,
        reviewer_kind=r.reviewer_kind,
        decision=r.decision,
    )
    return d


def ser_cage(r):
    d = _common(r)
    d.update(
        cage_barcode=r.cage_barcode,
        room_code=r.room_code,
        species=r.species,
        cage_kind=r.cage_kind,
        capacity_adults=r.capacity_adults,
        status=r.status,
        protocol_id=r.protocol_id,
    )
    return d


def ser_animal(r):
    d = _common(r)
    d.update(
        animal_tag=r.animal_tag,
        cage_id=r.cage_id,
        protocol_id=r.protocol_id,
        species=r.species,
        date_of_birth=iso(r.date_of_birth),
        sex=r.sex,
        status=r.status,
        litter_id=r.litter_id,
    )
    return d


def ser_litter(r):
    d = _common(r)
    d.update(
        cage_id=r.cage_id,
        protocol_id=r.protocol_id,
        born_on=iso(r.born_on),
        pup_count=r.pup_count,
        weaned_count=r.weaned_count,
        state=r.state,
    )
    return d


def ser_census_record(r):
    d = _common(r)
    d.update(
        cage_id=r.cage_id,
        census_date=iso(r.census_date),
        physical_count=r.physical_count,
        system_count=r.system_count,
        discrepancy=r.discrepancy,
    )
    return d


def ser_billing_run(r):
    d = _common(r)
    d.update(
        period_start=iso(r.period_start),
        period_end=iso(r.period_end),
        state=r.state,
        hold_reason=r.hold_reason,
    )
    return d


def ser_charge(r):
    d = _common(r)
    d.update(
        billing_run_id=r.billing_run_id,
        cage_id=r.cage_id,
        protocol_id=r.protocol_id,
        grant_id=r.grant_id,
        cage_days=r.cage_days,
        rate_cents=r.rate_cents,
        amount_cents=r.amount_cents,
        variant=r.variant,
    )
    return d


def ser_inspection(r):
    d = _common(r)
    d.update(
        inspection_kind=r.inspection_kind,
        scheduled_for=iso(r.scheduled_for),
        due_by=iso(r.due_by),
        completed_at=iso(r.completed_at),
        state=r.state,
        deficiency_count=r.deficiency_count,
    )
    return d


def ser_adverse_event(r):
    d = _common(r)
    d.update(
        protocol_id=r.protocol_id,
        animal_id=r.animal_id,
        reported_by_personnel_id=r.reported_by_personnel_id,
        severity=r.severity,
        description=r.description,
        state=r.state,
        reported_at=iso(r.reported_at),
        resolved_at=iso(r.resolved_at),
    )
    return d


def ser_deviation(r):
    d = _common(r)
    d.update(
        protocol_id=r.protocol_id,
        reported_by_personnel_id=r.reported_by_personnel_id,
        description=r.description,
        seriousness=r.seriousness,
        state=r.state,
    )
    return d


def ser_room_booking(r):
    d = _common(r)
    d.update(
        room_code=r.room_code,
        protocol_id=r.protocol_id,
        booked_by_personnel_id=r.booked_by_personnel_id,
        start_at=iso(r.start_at),
        end_at=iso(r.end_at),
        state=r.state,
    )
    return d
