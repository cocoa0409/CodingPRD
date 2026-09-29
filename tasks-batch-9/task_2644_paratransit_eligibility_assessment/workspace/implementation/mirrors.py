"""PRD 2.10 — derived mirrors and conserved quantities maintained by side effects.

Every mirror written here belongs to a record other than the one the request
addresses, so each write carries its own updated_at refresh and version
increment (PRD 2.4).
"""

import lookups
from store import db, plus_days, touch

TERM_DAYS = {
    "UNCONDITIONAL": 1825,
    "CONDITIONAL": 1095,
    "TEMPORARY": 180,
    "INELIGIBLE": 0,
}

SLOT_OCCUPYING_ATTENDANCE = ("SCHEDULED", "ATTENDED")


def term_days_for(category):
    return TERM_DAYS[category]


def expires_at_for(category, effective_date):
    """PRD 3.6: effective_date advanced by term_days; null for INELIGIBLE."""
    if category == "INELIGIBLE":
        return None
    return plus_days(effective_date, TERM_DAYS[category])


# ---------------------------------------------------------------------------
# AssessmentSlot.booked_count / status
# ---------------------------------------------------------------------------

def recompute_slot(slot_rec):
    """booked_count counts assessments whose attendance_status is SCHEDULED or
    ATTENDED; status is FULL exactly when booked_count equals capacity."""
    count = len(
        [
            a
            for a in db.assessments.values()
            if a["slot_id"] == slot_rec["id"]
            and a["attendance_status"] in SLOT_OCCUPYING_ATTENDANCE
        ]
    )
    status = "FULL" if count == slot_rec["capacity"] else "OPEN"
    if count != slot_rec["booked_count"] or status != slot_rec["status"]:
        slot_rec["booked_count"] = count
        slot_rec["status"] = status
        touch(slot_rec)
    return slot_rec


# ---------------------------------------------------------------------------
# Vehicle lane counters
# ---------------------------------------------------------------------------

def recompute_vehicle(vehicle_rec):
    """Both counters are conserved: a booking leaving RESERVED by any route
    releases exactly the one lane it consumed."""
    wheelchair = 0
    ambulatory = 0
    for b in db.bookings.values():
        if b["vehicle_id"] != vehicle_rec["id"] or b["status"] != "RESERVED":
            continue
        if b["requires_wheelchair_position"]:
            wheelchair += 1
        else:
            ambulatory += 1
    if (
        wheelchair != vehicle_rec["open_wheelchair_reservations"]
        or ambulatory != vehicle_rec["open_ambulatory_reservations"]
    ):
        vehicle_rec["open_wheelchair_reservations"] = wheelchair
        vehicle_rec["open_ambulatory_reservations"] = ambulatory
        touch(vehicle_rec)
    return vehicle_rec


# ---------------------------------------------------------------------------
# Applicant eligibility mirrors
# ---------------------------------------------------------------------------

def set_eligibility(applicant_rec, status, category, determination_id):
    applicant_rec["current_eligibility_status"] = status
    applicant_rec["eligibility_category"] = category
    applicant_rec["active_determination_id"] = determination_id
    touch(applicant_rec)
    return applicant_rec


def set_eligibility_status(applicant_rec, status):
    applicant_rec["current_eligibility_status"] = status
    touch(applicant_rec)
    return applicant_rec


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------

def withdraw_referrals_for_lapse(applicant_id):
    """PRD 3.6 hop 3: every referral in REFERRED or ENROLLED moves to WITHDRAWN
    with withdrawal_reason ELIGIBILITY_LAPSED."""
    withdrawn = 0
    for ref in lookups.ordered_referrals(applicant_id):
        if ref["status"] in ("REFERRED", "ENROLLED"):
            ref["status"] = "WITHDRAWN"
            ref["withdrawal_reason"] = "ELIGIBILITY_LAPSED"
            touch(ref)
            withdrawn += 1
    return withdrawn


def supersede_visitor_records(applicant_id):
    """PRD 3.10: issuing any determination freezes every ACTIVE visitor record."""
    for rec in lookups.visitor_records_of(applicant_id):
        if rec["status"] == "ACTIVE":
            rec["status"] = "SUPERSEDED_BY_LOCAL"
            touch(rec)


def sync_determination_competency(applicant_id):
    """PRD 3.7: when the rider's flag flips true, the mirror on the rider's
    determination that is still in ISSUED flips true as well."""
    for det in lookups.determinations_of_applicant(applicant_id):
        if det["status"] == "ISSUED" and not det["fixed_route_competency_confirmed"]:
            det["fixed_route_competency_confirmed"] = True
            touch(det)
