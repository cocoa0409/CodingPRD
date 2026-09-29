"""Cascades, plan re-evaluation, withdrawal machinery and the billing sweep."""
import calc
import derive
from store import clock_date, clock_iso, db, fmt_date, sorted_records, touch


# --------------------------------------------------------------------------
# plan status re-evaluation (PRD 3.3)
# --------------------------------------------------------------------------
def reevaluate_plan_after_payment(plan):
    """Branches checked in the PRD's order: settled first, then cure."""
    figures = derive.plan_figures(plan)
    if plan["status"] not in ("ACTIVE", "DELINQUENT"):
        return
    settled = (
        figures["arrears_cents"] == 0
        and figures["principal_paid_cents"] == plan["financed_total_cents"]
        and figures["late_fee_paid_cents"] == plan["late_fee_accrued_cents"]
    )
    if settled:
        plan["status"] = "SETTLED"
        touch(plan)
        return
    if figures["arrears_cents"] == 0 and plan["status"] == "DELINQUENT":
        plan["status"] = "ACTIVE"
        touch(plan)


def reevaluate_plan_after_reversal(plan):
    """A plan already SETTLED is never re-opened."""
    if plan["status"] != "ACTIVE":
        return
    figures = derive.plan_figures(plan)
    if figures["arrears_cents"] > 0:
        plan["status"] = "DELINQUENT"
        touch(plan)


# --------------------------------------------------------------------------
# housing chain (PRD 2.9)
# --------------------------------------------------------------------------
def release_assignment(assignment, reason, bump_agreement=True):
    """Every derived housing figure is a live definition, so releasing a stay
    is the whole housing chain: agreement occupancy and billing, the school's
    reserved bed-nights and the season's housing cost all move with it."""
    assignment["status"] = "RELEASED"
    assignment["released_reason"] = reason
    touch(assignment)
    if bump_agreement:
        agreement = db.agreements.get(assignment["facility_agreement_id"])
        if agreement is not None:
            touch(agreement)


def release_member_assignments(member_id, reason):
    released = []
    for assignment in sorted_records(db.housing):
        if assignment["member_id"] == member_id and assignment["status"] == "ACTIVE":
            release_assignment(assignment, reason)
            released.append(assignment)
    return released


def release_booking(booking, reason):
    """The school's booked_block_count is derived over HELD/CONFIRMED blocks,
    so it decrements as a consequence of this status move."""
    booking["status"] = "RELEASED"
    booking["released_reason"] = reason
    touch(booking)


# --------------------------------------------------------------------------
# withdrawal machinery (PRD 3.5)
# --------------------------------------------------------------------------
def close_member_plans_on_withdrawal(member):
    for plan in sorted_records(db.plans):
        if plan["member_id"] != member["id"]:
            continue
        if plan["status"] not in ("ACTIVE", "DELINQUENT"):
            continue
        figures = derive.plan_figures(plan)
        if figures["outstanding_cents"] <= 0:
            plan["status"] = "SETTLED"
        else:
            plan["status"] = "CLOSED_WITH_BALANCE"
        touch(plan)


def strike_withdrawal_obligation(member, season, withdrawal_date_raw, withdrawal_date):
    """Runs the obligation calculation and lets it REPLACE the charged figure."""
    obligation, basis = calc.member_withdrawal_obligation(
        member["tuition_charged_cents"],
        withdrawal_date,
        season["_spring_training_start_date"],
        season["_tour_departure_date"],
    )
    member["withdrawal_date"] = withdrawal_date_raw
    member["withdrawal_obligation_cents"] = obligation
    member["withdrawal_obligation_basis"] = basis
    member["tuition_charged_cents"] = obligation
    member["membership_status"] = "WITHDRAWN"
    touch(member)
    close_member_plans_on_withdrawal(member)
    release_member_assignments(member["id"], "MEMBER_WITHDRAWN")


# --------------------------------------------------------------------------
# facility-agreement cancellation (PRD 3.6)
# --------------------------------------------------------------------------
def cancel_agreement(agreement, cancel_reason):
    """Out of DRAFT, SUBMITTED and COUNTERED the cancellation is inert beyond
    storing the reason.  Out of SIGNED it is a demolition."""
    was_signed = agreement["status"] == "SIGNED"
    agreement["status"] = "CANCELLED"
    agreement["cancel_reason"] = cancel_reason
    if was_signed:
        agreement["_was_signed"] = True
        for assignment in sorted_records(db.housing):
            if (assignment["facility_agreement_id"] == agreement["id"]
                    and assignment["status"] == "ACTIVE"):
                release_assignment(assignment, "AGREEMENT_CANCELLED",
                                   bump_agreement=False)
        for booking in sorted_records(db.bookings):
            if (booking["facility_agreement_id"] == agreement["id"]
                    and booking["status"] in ("HELD", "CONFIRMED")):
                release_booking(booking, "AGREEMENT_CANCELLED")
    touch(agreement)


# --------------------------------------------------------------------------
# tour-stop cancellation (PRD 3.7 / 3.8)
# --------------------------------------------------------------------------
def cancel_stop(stop, cancel_reason):
    stop["status"] = "CANCELLED"
    stop["cancel_reason"] = cancel_reason
    for booking in sorted_records(db.bookings):
        if booking["tour_stop_id"] == stop["id"] and booking["status"] in ("HELD", "CONFIRMED"):
            release_booking(booking, "STOP_CANCELLED")
    for shift in sorted_records(db.staff):
        if shift["tour_stop_id"] != stop["id"]:
            continue
        if shift["status"] not in ("PROPOSED", "ACCEPTED", "APPROVED"):
            continue
        shift["status"] = "RELEASED"
        shift["released_reason"] = "STOP_CANCELLED"
        touch(shift)
    touch(stop)


# --------------------------------------------------------------------------
# the billing sweep (PRD 3.4) -- five jobs in one pass
# --------------------------------------------------------------------------
def run_billing_cycle(season):
    season["billing_epoch"] = season["billing_epoch"] + 1
    member_ids = set(m["id"] for m in derive.season_members(season["id"]))

    # Job one: late-fee assessment and the delinquency escalation.
    for plan in sorted_records(db.plans):
        if plan["member_id"] not in member_ids:
            continue
        if plan["status"] not in ("ACTIVE", "DELINQUENT"):
            continue
        arrears = derive.plan_figures(plan)["arrears_cents"]
        if arrears == 0:
            if plan["status"] == "DELINQUENT":
                plan["status"] = "ACTIVE"
                touch(plan)
            continue
        fee = calc.late_fee_assessment(arrears)
        strikes_before = plan["delinquency_strikes"]
        plan["late_fee_accrued_cents"] = plan["late_fee_accrued_cents"] + fee
        plan["delinquency_strikes"] = strikes_before + 1
        if plan["status"] == "ACTIVE":
            plan["status"] = "DELINQUENT"
        elif strikes_before >= 2:
            plan["status"] = "CLOSED_WITH_BALANCE"
        touch(plan)
        if plan["status"] == "CLOSED_WITH_BALANCE":
            member = db.members.get(plan["member_id"])
            if member is not None and member["membership_status"] == "CONTRACTED":
                today = clock_date()
                strike_withdrawal_obligation(member, season, fmt_date(today), today)

    # Job two: roster promotion.
    if clock_date() >= season["_tour_departure_date"]:
        for member in sorted_records(db.members):
            if member["season_id"] != season["id"]:
                continue
            if member["membership_status"] != "CONTRACTED":
                continue
            if member["medical_status"] != "CLEARED":
                continue
            blocked = any(
                p["status"] == "CLOSED_WITH_BALANCE"
                for p in derive.member_plans(member["id"])
            )
            if blocked:
                continue
            member["membership_status"] = "ON_TOUR"
            touch(member)

    # Job three: screening expiry.
    now = db.clock
    for volunteer in sorted_records(db.volunteers):
        if volunteer["screening_status"] != "CLEARED":
            continue
        expires = volunteer.get("_screening_expires_on")
        if expires is None or not (expires < clock_date()):
            continue
        volunteer["screening_status"] = "EXPIRED"
        for shift in sorted_records(db.staff):
            if shift["volunteer_id"] != volunteer["id"]:
                continue
            if shift["status"] not in ("PROPOSED", "ACCEPTED", "APPROVED"):
                continue
            if not (shift["_shift_end_at"] > now):
                continue
            shift["status"] = "RELEASED"
            shift["released_reason"] = "SCREENING_EXPIRED"
            touch(shift)
        touch(volunteer)

    # Job four: ledger rollups are live definitions (PRD 2.9) and need no work.

    # Job five: ledger closure -- vacuously true for a season with no stops.
    stops = derive.season_stops(season["id"])
    stop_ids = set(s["id"] for s in stops)
    closed = all(s["status"] in ("COMPLETED", "CANCELLED") for s in stops)
    settled = all(
        s["status"] == "FINALIZED"
        for s in db.settlements.values()
        if s["tour_stop_id"] in stop_ids
    )
    if closed and settled:
        season["ledger_status"] = "RECONCILED"

    touch(season)
