"""Derived state, serialization, recomputation and cascades.

Everything derived is recomputed in full from the rows that survive the request
(PRD section 2.9); nothing is adjusted incrementally.
"""
import calc
from store import db, mark, parse_day, parse_instant, public, sorted_rows

# ---------------------------------------------------------------------------
# Relationship walks
# ---------------------------------------------------------------------------
def sections_of_order(order_id):
    return sorted_rows([r for r in db.sections.values() if r["order_id"] == order_id])


def site_of_order(order_id):
    rows = sorted_rows([r for r in db.sites.values() if r["order_id"] == order_id])
    return rows[0] if rows else None


def set_jobs_of_order(order_id):
    return sorted_rows([r for r in db.set_jobs.values() if r["order_id"] == order_id])


def permits_of_section(section_id):
    return sorted_rows([r for r in db.permits.values() if r["section_id"] == section_id])


def legs_of_permit(permit_id):
    return sorted_rows([r for r in db.route_legs.values() if r["permit_id"] == permit_id])


def legs_of_hauler(hauler_id):
    return sorted_rows([r for r in db.route_legs.values() if r["hauler_id"] == hauler_id])


def assignments_of_leg(leg_id):
    return sorted_rows(
        [r for r in db.escort_assignments.values() if r["route_leg_id"] == leg_id]
    )


def assignments_of_crew(crew_id):
    return sorted_rows(
        [r for r in db.escort_assignments.values() if r["escort_crew_id"] == crew_id]
    )


def joints_of_job(set_job_id):
    return sorted_rows(
        [r for r in db.marriage_joints.values() if r["set_job_id"] == set_job_id]
    )


def certs_of_job(set_job_id):
    return sorted_rows(
        [r for r in db.anchor_certs.values() if r["set_job_id"] == set_job_id]
    )


def claims_of_order(order_id):
    return sorted_rows([r for r in db.claims.values() if r["order_id"] == order_id])


def order_of_section(section):
    return db.orders.get(section["order_id"]) if section else None


def section_of_permit(permit):
    return db.sections.get(permit["section_id"]) if permit else None


def order_of_permit(permit):
    return order_of_section(section_of_permit(permit))


def order_of_leg(leg):
    return order_of_permit(db.permits.get(leg["permit_id"])) if leg else None


def legs_of_order(order_id):
    out = []
    for leg in db.route_legs.values():
        order = order_of_leg(leg)
        if order is not None and order["id"] == order_id:
            out.append(leg)
    return sorted_rows(out)


# ---------------------------------------------------------------------------
# Derived scalar states
# ---------------------------------------------------------------------------
def set_crew_status(crew):
    """PRD 3.1: ACTIVE while license_expiry_date >= the logical current date."""
    expiry = parse_day(crew["license_expiry_date"])
    if expiry is None:
        return "ACTIVE"
    return "ACTIVE" if expiry >= db.clock_date() else "LICENSE_EXPIRED"


def endorsement_covers(endorsement_class, permit_class):
    ladder = {"STANDARD": 1, "OVERSIZE": 2, "SUPERLOAD": 3}
    return ladder.get(endorsement_class, 0) >= ladder.get(permit_class, 0)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def pub_plant(row):
    return public(row)


def pub_hauler(row):
    return public(row)


def pub_escort_crew(row):
    return public(row)


def pub_set_crew(row):
    out = public(row)
    out["status"] = set_crew_status(row)
    return out


def pub_order(row):
    return public(row)


def pub_section(row):
    return public(row)


def pub_site(row):
    return public(row)


def pub_permit(row):
    return public(row)


def pub_leg(row):
    return public(row)


def pub_assignment(row):
    return public(row)


def pub_set_job(row):
    return public(row)


def pub_joint(row):
    return public(row)


def pub_cert(row):
    return public(row)


def pub_claim(row):
    return public(row)


# ---------------------------------------------------------------------------
# Order posture (PRD 2.8) -- ordered, first-match-wins ladder of five bands
# ---------------------------------------------------------------------------
SECTION_HOLD_STATES = ("PERMIT_REVOKED_HOLD", "DAMAGED_HOLD")


def derive_posture(order):
    order_id = order["id"]
    jobs = set_jobs_of_order(order_id)

    # Band 1 -- CLOSED
    if jobs:
        live = [j for j in jobs if j["progress_status"] != "SUPERSEDED"]
        if all(j["progress_status"] == "CLOSED" for j in live):
            return "CLOSED"

    # Band 2 -- TRANSPORT_BLOCKED
    for section in sections_of_order(order_id):
        if section["transit_status"] in SECTION_HOLD_STATES:
            return "TRANSPORT_BLOCKED"
    for leg in legs_of_order(order_id):
        if leg["status"] == "HAULER_HOLD":
            return "TRANSPORT_BLOCKED"

    # Band 3 -- SET_IN_PROGRESS
    for job in jobs:
        if job["progress_status"] in ("DISPATCHED", "SET_COMPLETE"):
            return "SET_IN_PROGRESS"

    # Band 4 -- SITE_BLOCKED
    site = site_of_order(order_id)
    if site is not None and site["readiness_status"] in (
        "READINESS_PENDING",
        "READINESS_FAILED",
    ):
        for job in jobs:
            if job["progress_status"] == "SCHEDULED":
                return "SITE_BLOCKED"

    # Band 5 -- OPEN
    return "OPEN"


def recompute_posture(order):
    if order is None:
        return
    posture = derive_posture(order)
    if order["posture"] != posture:
        order["posture"] = posture
        mark(order)


# ---------------------------------------------------------------------------
# Escort minute ledger (PRD 3.5) -- full recompute, never incremental
# ---------------------------------------------------------------------------
def recompute_crew_minutes(crew):
    """Recompute one crew's reserved_minutes and status; the crew is an affected
    row of the calling cascade, so its version rises."""
    if crew is None:
        return
    total = 0
    for row in assignments_of_crew(crew["id"]):
        if row["status"] == "RESERVED":
            total += int(row["reserved_minutes"])
    crew["reserved_minutes"] = total
    crew["status"] = (
        "OVERBOOKED" if total > int(crew["max_reserved_minutes"]) else "AVAILABLE"
    )
    mark(crew)


def escort_window_conflict(crew, candidate_start, candidate_end, skip_id=None):
    """PRD 3.5: half-open windows, both sides inflated by buffer_minutes, two
    strict comparisons."""
    from datetime import timedelta

    buffer_delta = timedelta(minutes=int(crew["buffer_minutes"]))
    for row in assignments_of_crew(crew["id"]):
        if row["status"] != "RESERVED":
            continue
        if skip_id is not None and row["id"] == skip_id:
            continue
        other_start = parse_instant(row["window_start"])
        other_end = parse_instant(row["window_end"])
        if candidate_start < other_end + buffer_delta and other_start < (
            candidate_end + buffer_delta
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Chargeback ledger (PRD 3.9) -- full recompute of all three balance families
# ---------------------------------------------------------------------------
def network_chargeback_total():
    total = 0
    for plant in db.plants.values():
        total += int(plant["chargeback_balance_cents"])
    for hauler in db.haulers.values():
        total += int(hauler["chargeback_balance_cents"])
    for crew in db.set_crews.values():
        total += int(crew["chargeback_balance_cents"])
    return total


def _adjudicated_claims():
    return [r for r in db.claims.values() if r["status"] == "ADJUDICATED"]


def refresh_chargebacks():
    """Recompute every party balance, refresh statuses, cascade hauler holds and
    return the orders whose posture must be re-derived."""
    settled = _adjudicated_claims()
    affected_orders = {}

    for plant in db.plants.values():
        balance = 0
        for claim in settled:
            order = db.orders.get(claim["order_id"])
            if order is not None and order["plant_id"] == plant["id"]:
                balance += int(claim["plant_charge_cents"])
        status = (
            "PROBATION"
            if balance >= calc.PLANT_PROBATION_THRESHOLD_CENTS
            else "ACTIVE"
        )
        if balance != plant["chargeback_balance_cents"] or status != plant["status"]:
            plant["chargeback_balance_cents"] = balance
            plant["status"] = status
            mark(plant)

    for crew in db.set_crews.values():
        balance = 0
        for claim in settled:
            if claim["set_crew_id"] == crew["id"]:
                balance += int(claim["installer_charge_cents"])
        if balance != crew["chargeback_balance_cents"]:
            crew["chargeback_balance_cents"] = balance
            mark(crew)

    for hauler in db.haulers.values():
        balance = 0
        for claim in settled:
            if claim["hauler_id"] == hauler["id"]:
                balance += int(claim["hauler_charge_cents"])
        status = (
            "SUSPENDED"
            if balance >= calc.HAULER_SUSPENSION_THRESHOLD_CENTS
            else "ACTIVE"
        )
        was = hauler["status"]
        if balance != hauler["chargeback_balance_cents"] or status != was:
            hauler["chargeback_balance_cents"] = balance
            hauler["status"] = status
            mark(hauler)
        if status == "SUSPENDED" and was != "SUSPENDED":
            for leg in legs_of_hauler(hauler["id"]):
                if leg["status"] == "SCHEDULED":
                    leg["status"] = "HAULER_HOLD"
                    mark(leg)
                    order = order_of_leg(leg)
                    if order is not None:
                        affected_orders[order["id"]] = order
        elif status == "ACTIVE" and was == "SUSPENDED":
            for leg in legs_of_hauler(hauler["id"]):
                if leg["status"] == "HAULER_HOLD":
                    leg["status"] = "SCHEDULED"
                    mark(leg)
                    order = order_of_leg(leg)
                    if order is not None:
                        affected_orders[order["id"]] = order

    return affected_orders


def blocking_claims_for_section(section_id):
    """Claims that still hold the floor: blocks_set and not yet settled."""
    live = ("SUBMITTED", "UNDER_REVIEW", "DISPUTED")
    return [
        r
        for r in db.claims.values()
        if r["section_id"] == section_id and r["blocks_set"] and r["status"] in live
    ]


def release_damaged_section(section):
    """PRD 3.9: DAMAGED_HOLD -> DELIVERED once no blocking claim remains."""
    if section is None or section["transit_status"] != "DAMAGED_HOLD":
        return False
    if blocking_claims_for_section(section["id"]):
        return False
    section["transit_status"] = "DELIVERED"
    mark(section)
    return True


# ---------------------------------------------------------------------------
# Permit evaluation (PRD 3.4) -- PROVISIONAL and FINAL variants
# ---------------------------------------------------------------------------
FINAL_LEG_STATES = ("SCHEDULED", "IN_TRANSIT", "ARRIVED")


def provisional_evaluation(permit, section):
    """Declared dimensions plus planned_leg_count."""
    matrix = calc.escort_requirement_matrix(
        section["declared_width_in"],
        section["declared_height_in"],
        permit["state_code"],
        bool(permit["night_move"]),
        int(permit["planned_leg_count"]),
    )
    fee = calc.permit_fee_assessment(
        section["declared_width_in"],
        section["declared_height_in"],
        int(permit["planned_leg_count"]),
        matrix["escort_count_required"],
        matrix["permit_class"],
    )
    return matrix, fee


def final_leg_count(permit_id):
    return len(
        [leg for leg in legs_of_permit(permit_id) if leg["status"] in FINAL_LEG_STATES]
    )


def final_evaluation(permit, section):
    """Measured dimensions where present, and the permit's actual leg count."""
    width = section["measured_width_in"]
    if width is None:
        width = section["declared_width_in"]
    height = section["measured_height_in"]
    if height is None:
        height = section["declared_height_in"]
    legs = final_leg_count(permit["id"])
    matrix = calc.escort_requirement_matrix(
        width, height, permit["state_code"], bool(permit["night_move"]), legs
    )
    fee = calc.permit_fee_assessment(
        width, height, legs, matrix["escort_count_required"], matrix["permit_class"]
    )
    return matrix, fee


def issue_escort_counts(permit_id):
    """Reserved coverage across the permit's SCHEDULED / IN_TRANSIT legs."""
    escorts = 0
    pilot_cars = 0
    for leg in legs_of_permit(permit_id):
        if leg["status"] not in ("SCHEDULED", "IN_TRANSIT"):
            continue
        for row in assignments_of_leg(leg["id"]):
            if row["status"] != "RESERVED":
                continue
            if row["role"] == "ESCORT":
                escorts += 1
            elif row["role"] == "PILOT_CAR":
                pilot_cars += 1
    return escorts, pilot_cars


def section_has_issued_permit(section_id):
    return any(p["status"] == "ISSUED" for p in permits_of_section(section_id))


# ---------------------------------------------------------------------------
# Set-crew day capacity (PRD 3.6) -- inclusive both ends, aggregate per day
# ---------------------------------------------------------------------------
DAY_LOAD_STATES = ("SCHEDULED", "DISPATCHED", "SET_COMPLETE")


def day_capacity_exceeded(crew, start_day, end_day):
    """The per-day committed count is piecewise constant and only ever rises at
    an existing job's start date, so the maximum over the candidate's inclusive
    range is attained at the candidate's start or at one of those starts."""
    occupied = []
    for job in db.set_jobs.values():
        if job["set_crew_id"] != crew["id"]:
            continue
        if job["progress_status"] not in DAY_LOAD_STATES:
            continue
        job_start = parse_day(job["scheduled_start_date"])
        job_end = parse_day(job["scheduled_end_date"])
        if job_start is None or job_end is None:
            continue
        if job_end < start_day or job_start > end_day:
            continue
        occupied.append((job_start, job_end))

    probes = {start_day}
    for job_start, _job_end in occupied:
        if start_day <= job_start <= end_day:
            probes.add(job_start)

    capacity = int(crew["daily_capacity"])
    for probe in probes:
        count = 0
        for job_start, job_end in occupied:
            if job_start <= probe <= job_end:
                count += 1
        if count + 1 > capacity:
            return True
    return False


# ---------------------------------------------------------------------------
# Invoice assembly (PRD 3.8)
# ---------------------------------------------------------------------------
def assemble_invoice(job):
    return calc.installation_invoice_total(
        int(job["labor_base_cents"]),
        int(job["skirting_fee_cents"]),
        int(job["steps_fee_cents"]),
        int(job["crossover_fee_cents"]),
    )


# ---------------------------------------------------------------------------
# Order roll-up (PRD 2.11)
# ---------------------------------------------------------------------------
OPEN_CLAIM_STATES = ("SUBMITTED", "UNDER_REVIEW", "DISPUTED")


def order_summary(order):
    order_id = order["id"]
    sections = sections_of_order(order_id)
    site = site_of_order(order_id)
    issued = 0
    for section in sections:
        for permit in permits_of_section(section["id"]):
            if permit["status"] == "ISSUED":
                issued += 1
    open_claims = len(
        [c for c in claims_of_order(order_id) if c["status"] in OPEN_CLAIM_STATES]
    )
    return {
        "order_id": order_id,
        "posture": order["posture"],
        "section_count_declared": int(order["section_count"]),
        "section_count_actual": len(sections),
        "sections_delivered_count": len(
            [s for s in sections if s["transit_status"] == "DELIVERED"]
        ),
        "sections_on_hold_count": len(
            [s for s in sections if s["transit_status"] in SECTION_HOLD_STATES]
        ),
        "site_readiness_status": site["readiness_status"] if site else None,
        "issued_permit_count": issued,
        "open_claim_count": open_claims,
        "network_chargeback_cents": network_chargeback_total(),
        "invoice_total_cents": order["invoice_total_cents"],
    }
