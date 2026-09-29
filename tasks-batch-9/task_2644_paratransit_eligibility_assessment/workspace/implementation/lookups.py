"""PRD 2.5 stages 6-8 — path/body existence and parentage resolution."""

from errors import ApiError
from store import db


def _get(table, key, error_id):
    if not isinstance(key, str) or key not in table:
        raise ApiError(error_id)
    return table[key]


def applicant(applicant_id):
    return _get(db.applicants, applicant_id, "ERR_APPLICANT_NOT_FOUND")


def application(application_id):
    return _get(db.applications, application_id, "ERR_APPLICATION_NOT_FOUND")


def verification(verification_id):
    return _get(db.verifications, verification_id, "ERR_VERIFICATION_NOT_FOUND")


def slot(slot_id):
    return _get(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")


def assessment(assessment_id):
    return _get(db.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")


def vehicle(vehicle_id):
    return _get(db.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")


def booking(booking_id):
    return _get(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")


def determination(determination_id):
    return _get(db.determinations, determination_id, "ERR_DETERMINATION_NOT_FOUND")


def appeal(appeal_id):
    return _get(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")


def trip_event(trip_event_id):
    return _get(db.trip_events, trip_event_id, "ERR_TRIP_EVENT_NOT_FOUND")


def proceeding(proceeding_id):
    return _get(db.proceedings, proceeding_id, "ERR_PROCEEDING_NOT_FOUND")


def referral(referral_id):
    return _get(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")


def visitor_record(record_id):
    return _get(db.visitor_records, record_id, "ERR_VISITOR_RECORD_NOT_FOUND")


def verification_under(app_rec, verification_id):
    """PRD 2.5 stage 8: a verification whose application_id differs from the
    application named in the path is ERR_VERIFICATION_NOT_FOUND (404)."""
    ver = verification(verification_id)
    if ver["application_id"] != app_rec["id"]:
        raise ApiError("ERR_VERIFICATION_NOT_FOUND")
    return ver


# ---------------------------------------------------------------------------
# collection helpers
# ---------------------------------------------------------------------------

def applications_of(applicant_id):
    return [a for a in db.applications.values() if a["applicant_id"] == applicant_id]


def verifications_of(application_id):
    return [v for v in db.verifications.values() if v["application_id"] == application_id]


def assessments_of_application(application_id):
    return [a for a in db.assessments.values() if a["application_id"] == application_id]


def assessments_on_slot(slot_id):
    return [a for a in db.assessments.values() if a["slot_id"] == slot_id]


def bookings_of_assessment(assessment_id):
    return [b for b in db.bookings.values() if b["assessment_id"] == assessment_id]


def bookings_of_vehicle(vehicle_id):
    return [b for b in db.bookings.values() if b["vehicle_id"] == vehicle_id]


def determinations_of_applicant(applicant_id):
    return [d for d in db.determinations.values() if d["applicant_id"] == applicant_id]


def determinations_of_application(application_id):
    return [d for d in db.determinations.values() if d["application_id"] == application_id]


def conditions_of(determination_id):
    return [c for c in db.trip_conditions.values() if c["determination_id"] == determination_id]


def appeals_of_determination(determination_id):
    return [a for a in db.appeals.values() if a["determination_id"] == determination_id]


def trip_events_of(applicant_id):
    return [e for e in db.trip_events.values() if e["applicant_id"] == applicant_id]


def proceedings_of(applicant_id):
    return [p for p in db.proceedings.values() if p["applicant_id"] == applicant_id]


def referrals_of(applicant_id):
    return [r for r in db.referrals.values() if r["applicant_id"] == applicant_id]


def visitor_records_of(applicant_id):
    return [v for v in db.visitor_records.values() if v["applicant_id"] == applicant_id]


def issued_determination_of(applicant_id):
    """PRD 2.4: the authoritative way to discover a rider's governing grant."""
    for det in determinations_of_applicant(applicant_id):
        if det["status"] == "ISSUED":
            return det
    return None


def appeal_owner_applicant_id(appeal_rec):
    det = db.determinations.get(appeal_rec["determination_id"])
    return None if det is None else det["applicant_id"]


def ordered_referrals(applicant_id):
    from store import ordered
    return ordered(referrals_of(applicant_id))
