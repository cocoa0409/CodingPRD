"""Cross-cutting row lookups shared by the gates, the calculations and the engine."""

from store import db, parse_date, sort_rows


# --- simple parent walks ---------------------------------------------------

def program_of_session(session):
    return db.get("activity_programs", session["program_id"]) if session else None


def session_of_enrollment(enrollment):
    return db.get("program_sessions", enrollment["session_id"]) if enrollment else None


def participant_of_enrollment(enrollment):
    return db.get("participants", enrollment["participant_id"]) if enrollment else None


def program_of_enrollment(enrollment):
    return program_of_session(session_of_enrollment(enrollment))


def charge_of_enrollment(enrollment):
    if enrollment is None:
        return None
    for charge in sort_rows(db.rows("enrollment_charges")):
        if charge["enrollment_id"] == enrollment["id"]:
            return charge
    return None


def enrollment_of_charge(charge):
    return db.get("enrollments", charge["enrollment_id"]) if charge else None


def item_of_reservation(reservation):
    return db.get("equipment_items", reservation["equipment_item_id"]) if reservation else None


def enrollment_of_reservation(reservation):
    return db.get("enrollments", reservation["enrollment_id"]) if reservation else None


def run_of_booking(booking):
    return db.get("transport_runs", booking["transport_run_id"]) if booking else None


def enrollment_of_booking(booking):
    return db.get("enrollments", booking["enrollment_id"]) if booking else None


def source_of_award(award):
    return db.get("funding_sources", award["funding_source_id"]) if award else None


def enrollment_of_award(award):
    return db.get("enrollments", award["enrollment_id"]) if award else None


def period_of_source(source):
    return db.get("operating_periods", source["operating_period_id"]) if source else None


def participant_of_goal(goal):
    return db.get("participants", goal["participant_id"]) if goal else None


def goal_of_rating(rating):
    return db.get("goals", rating["goal_id"]) if rating else None


# --- child collections -----------------------------------------------------

def _children(table, key, value):
    return sort_rows([r for r in db.rows(table) if r.get(key) == value])


def enrollments_of_session(session):
    return _children("enrollments", "session_id", session["id"])


def enrollments_of_participant(participant):
    return _children("enrollments", "participant_id", participant["id"])


def assignments_of_session(session):
    return _children("staff_assignments", "session_id", session["id"])


def assignments_of_staff(staff_id):
    return _children("staff_assignments", "staff_member_id", staff_id)


def certifications_of_staff(staff_id):
    return _children("staff_certifications", "staff_member_id", staff_id)


def reservations_of_enrollment(enrollment):
    return _children("equipment_reservations", "enrollment_id", enrollment["id"])


def reservations_of_item(item):
    return _children("equipment_reservations", "equipment_item_id", item["id"])


def bookings_of_enrollment(enrollment):
    return _children("transport_bookings", "enrollment_id", enrollment["id"])


def bookings_of_run(run):
    return _children("transport_bookings", "transport_run_id", run["id"])


def runs_of_session(session):
    return _children("transport_runs", "session_id", session["id"])


def awards_of_enrollment(enrollment):
    return _children("scholarship_awards", "enrollment_id", enrollment["id"])


def awards_of_source(source):
    return _children("scholarship_awards", "funding_source_id", source["id"])


def sources_of_period(period):
    return _children("funding_sources", "operating_period_id", period["id"])


def assessments_of_participant(participant):
    return _children("support_assessments", "participant_id", participant["id"])


def consents_of_participant(participant):
    return _children("consents", "participant_id", participant["id"])


def caregivers_of_participant(participant):
    return _children("caregivers", "participant_id", participant["id"])


def goals_of_participant(participant):
    return _children("goals", "participant_id", participant["id"])


def ratings_of_goal(goal):
    return _children("goal_ratings", "goal_id", goal["id"])


def active_assessment(participant):
    for row in assessments_of_participant(participant):
        if row["status"] == "ACTIVE":
            return row
    return None


# --- the current operating period (PRD 2.5) --------------------------------

def current_period():
    """The row whose starts_on <= clock date <= ends_on; starts_on DESC, then
    created_at ASC; None when nothing qualifies."""
    today = db.clock_date
    candidates = []
    for period in db.rows("operating_periods"):
        starts = parse_date(period["starts_on"])
        ends = parse_date(period["ends_on"])
        if starts is None or ends is None:
            continue
        if starts <= today <= ends:
            candidates.append(period)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (_neg_date(r["starts_on"]), r["created_at"], r["_seq"]))
    return candidates[0]


def _neg_date(value):
    day = parse_date(value)
    return -day.toordinal() if day else 0
