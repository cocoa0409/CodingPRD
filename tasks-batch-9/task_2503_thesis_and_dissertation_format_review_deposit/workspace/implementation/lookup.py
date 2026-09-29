"""Stage 4/5 resolution helpers: every accessor reports its own 404 id."""

from db import db
from errors import fail


def _get(collection, row_id, error_id, label):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id, "%s '%s' was not found" % (label, row_id))
    return row


def get_term(term_id):
    return _get(db.terms, term_id, "ERR_TERM_NOT_FOUND", "Term")


def get_student(student_id):
    return _get(db.students, student_id, "ERR_STUDENT_NOT_FOUND", "Student")


def get_faculty(faculty_id):
    return _get(db.faculty_members, faculty_id, "ERR_FACULTY_NOT_FOUND", "FacultyMember")


def get_room(room_id):
    return _get(db.defense_rooms, room_id, "ERR_ROOM_NOT_FOUND", "DefenseRoom")


def get_thesis(thesis_id):
    return _get(db.theses, thesis_id, "ERR_THESIS_NOT_FOUND", "Thesis")


def get_committee(committee_id):
    return _get(db.committees, committee_id, "ERR_COMMITTEE_NOT_FOUND", "Committee")


def get_committee_member(member_id):
    return _get(
        db.committee_members,
        member_id,
        "ERR_COMMITTEE_MEMBER_NOT_FOUND",
        "CommitteeMember",
    )


def get_defense_event(event_id):
    return _get(db.defense_events, event_id, "ERR_DEFENSE_NOT_FOUND", "DefenseEvent")


def get_format_review(review_id):
    return _get(
        db.format_reviews, review_id, "ERR_FORMAT_REVIEW_NOT_FOUND", "FormatReview"
    )


def get_embargo_request(request_id):
    return _get(
        db.embargo_requests,
        request_id,
        "ERR_EMBARGO_REQUEST_NOT_FOUND",
        "EmbargoRequest",
    )


def get_permission_record(record_id):
    return _get(
        db.permission_records,
        record_id,
        "ERR_PERMISSION_RECORD_NOT_FOUND",
        "PermissionRecord",
    )


def get_screening(screening_id):
    return _get(
        db.integrity_screenings,
        screening_id,
        "ERR_SCREENING_NOT_FOUND",
        "IntegrityScreening",
    )


# ---------------------------------------------------------------- collections


def committee_of_thesis(thesis_id):
    for row in db.committees.values():
        if row["thesis_id"] == thesis_id:
            return row
    return None


def seats_of_committee(committee_id):
    return [
        row for row in db.committee_members.values() if row["committee_id"] == committee_id
    ]


def confirmed_seats(committee_id):
    return [
        row
        for row in seats_of_committee(committee_id)
        if row["status"] == "CONFIRMED"
    ]


def events_of_thesis(thesis_id):
    return [row for row in db.defense_events.values() if row["thesis_id"] == thesis_id]


def events_of_room(room_id):
    return [row for row in db.defense_events.values() if row["room_id"] == room_id]


def reviews_of_thesis(thesis_id):
    return [row for row in db.format_reviews.values() if row["thesis_id"] == thesis_id]


def embargoes_of_thesis(thesis_id):
    return [row for row in db.embargo_requests.values() if row["thesis_id"] == thesis_id]


def permissions_of_thesis(thesis_id):
    return [
        row for row in db.permission_records.values() if row["thesis_id"] == thesis_id
    ]


def screenings_of_thesis(thesis_id):
    return [
        row for row in db.integrity_screenings.values() if row["thesis_id"] == thesis_id
    ]


def deposits_of_thesis(thesis_id):
    return [
        row for row in db.repository_deposits.values() if row["thesis_id"] == thesis_id
    ]


def theses_of_student(student_id):
    return [row for row in db.theses.values() if row["student_id"] == student_id]


def theses_of_term(term_id):
    return [row for row in db.theses.values() if row["term_id"] == term_id]


def clearance_of_student(student_id):
    for row in db.graduation_clearances.values():
        if row["student_id"] == student_id:
            return row
    return None
