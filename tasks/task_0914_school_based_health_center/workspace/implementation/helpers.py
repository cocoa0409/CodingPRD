"""Shared lookups and list plumbing used by the route modules."""

import clock
import config
import envelope
import store
from services import serialize


def list_response(rows, op):
    payload, total = serialize.paginate(rows, op.limit, op.offset)
    return envelope.listing(payload, op.limit, op.offset, total)


def sorted_rows(collection, predicate=None):
    rows = store.all_rows(collection)
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    return rows


def filter_eq(rows, args, mapping):
    """Apply ``?field=value`` filters; an unknown value simply matches nothing."""
    for param, field in mapping.items():
        if param in args:
            wanted = args.get(param)
            rows = [r for r in rows if str(r.get(field)) == wanted]
    return rows


# --------------------------------------------------------------------------
# Consent lookups (PRD 3.4)
# --------------------------------------------------------------------------
def consent_is_usable(consent):
    if consent["status"] != "ACTIVE":
        return False
    expires = clock.parse_datetime(consent["expires_at"])
    return clock.now_dt() <= expires


def find_usable_consent(student_id, category):
    """Newest usable consent of a category; supersede keeps at most one ACTIVE."""
    candidates = [
        c
        for c in store.all_rows("consents")
        if c["student_id"] == student_id and c["category"] == category and consent_is_usable(c)
    ]
    if not candidates:
        return None
    return candidates[-1]


def required_consent_category(visit_type, confidential_service_requested):
    if visit_type == "ACUTE":
        return "CONFIDENTIAL_SERVICES" if confidential_service_requested else "GENERAL_TREATMENT"
    if visit_type == "BEHAVIORAL":
        return "BEHAVIORAL_HEALTH"
    if visit_type == "DENTAL":
        return "DENTAL"
    return "GENERAL_TREATMENT"  # SPORTS_PHYSICAL


# --------------------------------------------------------------------------
# Enrollment lookups (PRD 3.3)
# --------------------------------------------------------------------------
def active_enrollment(student_id, school_id=None, school_year=None):
    for enrollment in store.all_rows("enrollments"):
        if enrollment["student_id"] != student_id or enrollment["status"] != "ACTIVE":
            continue
        if school_id is not None and enrollment["school_id"] != school_id:
            continue
        if school_year is not None and enrollment["school_year"] != school_year:
            continue
        return enrollment
    return None


def school_year_of_enrollment(enrollment):
    if enrollment is None:
        return clock.current_school_year()
    return enrollment["school_year"]


def school_is_active(school):
    return school["program_status"] == "ACTIVE"


def visit_of(visit_id):
    return store.get("visits", visit_id)


def student_of(student_id):
    return store.get("students", student_id)


def fee_for(service_category):
    return config.FEE_SCHEDULE[service_category]
