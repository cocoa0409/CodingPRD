"""Derived-field recomputation (PRD 2.9).

Every derived figure is a definition over primitives rather than a running
counter, so it is re-derived on every read as well as on every write.  That
makes the cascade chains of PRD 2.9 exact by construction: a stay that stops
consuming beds instantly changes the agreement, the school and the season.
"""
from calc import housing_bed_night_capacity, installment_due_dates
from store import clock_date, db, parse_date

PLAN_OPEN_STATUSES = ("ACTIVE", "DELINQUENT")
SEASON_CHARGED_STATUSES = ("CONTRACTED", "ON_TOUR", "WITHDRAWN")


# --------------------------------------------------------------------------
# payment plans
# --------------------------------------------------------------------------
def plan_payments(plan_id):
    return [p for p in db.payments.values() if p["payment_plan_id"] == plan_id]


def posted_plan_payments(plan_id):
    return [p for p in plan_payments(plan_id) if p["status"] == "POSTED"]


def plan_installment_amounts(plan):
    base = plan["installment_base_cents"]
    remainder = plan["installment_remainder_cents"]
    count = plan["installment_count"]
    return [base + 1 if i < remainder else base for i in range(count)]


def plan_principal_paid(plan):
    return sum(p["allocated_to_principal_cents"] for p in posted_plan_payments(plan["id"]))


def plan_late_fee_paid(plan):
    return sum(p["allocated_to_late_fee_cents"] for p in posted_plan_payments(plan["id"]))


def plan_installments_due_count(plan):
    """Installments whose due date falls on or before the logical-clock date,
    capped at installment_count."""
    today = clock_date()
    first_due = plan["_first_due_date"]
    count = 0
    for due in installment_due_dates(first_due, plan["installment_count"]):
        if due <= today:
            count += 1
    return count


def plan_figures(plan):
    """The four clock-sensitive figures plus the two paid buckets."""
    principal_paid = plan_principal_paid(plan)
    late_fee_paid = plan_late_fee_paid(plan)
    due_count = plan_installments_due_count(plan)
    amounts = plan_installment_amounts(plan)
    due_amount = sum(amounts[:due_count])
    arrears = due_amount - principal_paid
    if arrears < 0:
        arrears = 0
    outstanding = (
        plan["financed_total_cents"] - principal_paid
        + plan["late_fee_accrued_cents"] - late_fee_paid
    )
    return {
        "principal_paid_cents": principal_paid,
        "late_fee_paid_cents": late_fee_paid,
        "installments_due_count": due_count,
        "due_amount_cents": due_amount,
        "arrears_cents": arrears,
        "outstanding_cents": outstanding,
    }


def plan_total_outstanding(plan):
    """The obligation a payment may not exceed (PRD 3.3)."""
    figures = plan_figures(plan)
    return figures["outstanding_cents"]


# --------------------------------------------------------------------------
# members
# --------------------------------------------------------------------------
def member_plans(member_id):
    return [p for p in db.plans.values() if p["member_id"] == member_id]


def member_paid_cents(member):
    """Re-summed over principal allocations of POSTED payments only; late-fee
    allocations are excluded from this figure entirely."""
    total = 0
    for plan in member_plans(member["id"]):
        total += plan_principal_paid(plan)
    return total


def member_figures(member):
    paid = member_paid_cents(member)
    charged = member["tuition_charged_cents"]
    return {
        "tuition_paid_cents": paid,
        "tuition_balance_cents": max(charged - paid, 0),
        "refund_due_cents": max(paid - charged, 0),
    }


# --------------------------------------------------------------------------
# facility agreements / housing / host schools
# --------------------------------------------------------------------------
def agreement_nights(agreement):
    """end_date is EXCLUSIVE, so nights is simply end - start."""
    return agreement["_nights"]


def agreement_assignments(agreement_id):
    return [h for h in db.housing.values() if h["facility_agreement_id"] == agreement_id]


def active_agreement_assignments(agreement_id):
    return [h for h in agreement_assignments(agreement_id) if h["status"] == "ACTIVE"]


def agreement_figures(agreement):
    """Occupancy is re-summed over active stays.  An unsigned agreement bills
    nothing; a cancelled one bills nothing at all but keeps the minimum-bed
    floor visible on billable_bed_nights when it had been signed."""
    occupied = sum(h["nights"] for h in active_agreement_assignments(agreement["id"]))
    status = agreement["status"]
    if status == "SIGNED":
        billable_nights, billable_cents = housing_bed_night_capacity(
            occupied,
            agreement["minimum_billable_beds"],
            agreement_nights(agreement),
            agreement["effective_nightly_rate_cents"],
        )
    elif status == "CANCELLED" and agreement.get("_was_signed"):
        floor_nights = agreement["minimum_billable_beds"] * agreement_nights(agreement)
        billable_nights = max(floor_nights, 0)
        billable_cents = 0
    else:
        billable_nights = 0
        billable_cents = 0
    return {
        "occupied_bed_nights": occupied,
        "billable_bed_nights": billable_nights,
        "billable_cents": billable_cents,
    }


def school_agreements(school_id):
    return [a for a in db.agreements.values() if a["host_school_id"] == school_id]


def school_bookings(school_id):
    return [b for b in db.bookings.values() if b["host_school_id"] == school_id]


def school_figures(school):
    booked = len([b for b in school_bookings(school["id"])
                  if b["status"] in ("HELD", "CONFIRMED")])
    reserved = 0
    for agreement in school_agreements(school["id"]):
        reserved += sum(h["nights"] for h in active_agreement_assignments(agreement["id"]))
    return {"booked_block_count": booked, "reserved_bed_nights": reserved}


# --------------------------------------------------------------------------
# volunteers
# --------------------------------------------------------------------------
def volunteer_shifts(volunteer_id):
    return [s for s in db.staff.values() if s["volunteer_id"] == volunteer_id]


def volunteer_assignment_count(volunteer):
    return len([s for s in volunteer_shifts(volunteer["id"]) if s["status"] == "APPROVED"])


# --------------------------------------------------------------------------
# seasons
# --------------------------------------------------------------------------
def season_members(season_id):
    return [m for m in db.members.values() if m["season_id"] == season_id]


def season_stops(season_id):
    return [s for s in db.stops.values() if s["season_id"] == season_id]


def season_figures(season):
    season_id = season["id"]
    members = season_members(season_id)
    member_ids = set(m["id"] for m in members)

    charged = sum(m["tuition_charged_cents"] for m in members
                  if m["membership_status"] in SEASON_CHARGED_STATUSES)

    plan_ids = set(p["id"] for p in db.plans.values() if p["member_id"] in member_ids)
    collected = 0
    late_fees = 0
    for payment in db.payments.values():
        if payment["status"] != "POSTED":
            continue
        if payment["payment_plan_id"] not in plan_ids:
            continue
        collected += payment["allocated_to_principal_cents"]
        late_fees += payment["allocated_to_late_fee_cents"]

    housing_cost = 0
    for agreement in db.agreements.values():
        if agreement["season_id"] == season_id and agreement["status"] == "SIGNED":
            housing_cost += agreement_figures(agreement)["billable_cents"]

    stop_ids = set(s["id"] for s in season_stops(season_id))
    revenue = 0
    for settlement in db.settlements.values():
        if settlement["status"] == "FINALIZED" and settlement["tour_stop_id"] in stop_ids:
            revenue += settlement["final_net_cents"] or 0

    return {
        "tuition_charged_cents": charged,
        "tuition_collected_cents": collected,
        "late_fee_collected_cents": late_fees,
        "housing_cost_cents": housing_cost,
        "tour_revenue_cents": revenue,
    }
