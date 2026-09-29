"""Entity lookups, parent walks and derived aggregates."""

from decimal import Decimal

from db import db
from errors import ApiError
from services.calc import floor_int, round_half_up

TERMINAL_APPLICATION_STATUSES = (
    "NOT_SELECTED",
    "WITHDRAWN",
    "LAPSED",
    "CLOSED_RECORDED",
)


def _fetch(collection, key, error_id, label):
    if not isinstance(key, str) or not key:
        raise ApiError(error_id, "%s not found" % label)
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id, "%s not found" % label)
    return row


def get_program(key):
    return _fetch(db.programs, key, "ERR_PROGRAM_NOT_FOUND", "preservation program")


def get_round(key):
    return _fetch(db.rounds, key, "ERR_ROUND_NOT_FOUND", "funding round")


def get_landowner(key):
    return _fetch(db.landowners, key, "ERR_LANDOWNER_NOT_FOUND", "landowner")


def get_parcel(key):
    return _fetch(db.parcels, key, "ERR_PARCEL_NOT_FOUND", "parcel")


def get_application(key):
    return _fetch(db.applications, key, "ERR_APPLICATION_NOT_FOUND", "application")


def get_appraisal(key):
    return _fetch(db.appraisals, key, "ERR_APPRAISAL_NOT_FOUND", "appraisal")


def get_funding_source(key):
    return _fetch(db.funding_sources, key, "ERR_SOURCE_NOT_FOUND", "funding source")


def get_commitment(key):
    return _fetch(db.funding_commitments, key, "ERR_COMMITMENT_NOT_FOUND", "funding commitment")


def get_requirement(key):
    return _fetch(db.closing_requirements, key, "ERR_REQUIREMENT_NOT_FOUND", "closing requirement")


def get_easement(key):
    return _fetch(db.easements, key, "ERR_EASEMENT_NOT_FOUND", "easement")


def get_visit(key):
    return _fetch(db.monitoring_visits, key, "ERR_VISIT_NOT_FOUND", "monitoring visit")


def get_violation(key):
    return _fetch(db.violations, key, "ERR_VIOLATION_NOT_FOUND", "violation")


def get_amendment(key):
    return _fetch(db.amendments, key, "ERR_AMENDMENT_NOT_FOUND", "amendment")


# ---- parent walks --------------------------------------------------------
def program_of_round(rnd):
    return db.programs[rnd["program_id"]]


def round_of_application(app):
    return db.rounds[app["funding_round_id"]]


def program_of_application(app):
    return program_of_round(round_of_application(app))


def program_of_easement(easement):
    return program_of_application(db.applications[easement["application_id"]])


def parcel_of_application(app):
    return db.parcels[app["parcel_id"]]


# ---- child collections ---------------------------------------------------
def applications_of_round(round_id):
    return [a for a in db.applications.values() if a["funding_round_id"] == round_id]


def negotiation_rounds_of(application_id):
    return [n for n in db.negotiation_rounds.values() if n["application_id"] == application_id]


def appraisals_of(application_id):
    return [a for a in db.appraisals.values() if a["application_id"] == application_id]


def commitments_of_application(application_id):
    return [
        c
        for c in db.funding_commitments.values()
        if c["application_id"] == application_id
    ]


def commitments_of_source(source_id):
    return [
        c
        for c in db.funding_commitments.values()
        if c["funding_source_id"] == source_id
    ]


def requirements_of(application_id):
    return [
        r
        for r in db.closing_requirements.values()
        if r["application_id"] == application_id
    ]


def visits_of(easement_id):
    return [v for v in db.monitoring_visits.values() if v["easement_id"] == easement_id]


def violations_of(easement_id):
    return [v for v in db.violations.values() if v["easement_id"] == easement_id]


def violations_of_visit(visit_id):
    return [v for v in db.violations.values() if v.get("monitoring_visit_id") == visit_id]


def amendments_of(easement_id):
    return [a for a in db.amendments.values() if a["easement_id"] == easement_id]


def easement_of_application(application_id):
    for e in db.easements.values():
        if e["application_id"] == application_id:
            return e
    return None


# ---- derived aggregates --------------------------------------------------
def source_committed_cents(source_id):
    return sum(
        c["amount_cents"]
        for c in commitments_of_source(source_id)
        if c["status"] in ("OBLIGATED", "DISBURSED")
    )


def source_reserved_cents(source_id):
    return sum(
        c["amount_cents"]
        for c in commitments_of_source(source_id)
        if c["status"] == "RESERVED"
    )


def source_disbursed_cents(source_id):
    return sum(
        c["amount_cents"]
        for c in commitments_of_source(source_id)
        if c["status"] == "DISBURSED"
    )


def source_available_cents(source):
    """authorized_cents - committed_cents; RESERVED money is not netted."""
    return int(source["authorized_cents"]) - source_committed_cents(source["id"])


def source_fully_obligated_threshold(source):
    return floor_int(
        Decimal(int(source["authorized_cents"])) * source["fully_obligated_threshold_pct"]
    )


def round_application_count(round_id):
    return len(applications_of_round(round_id))


def round_selected_count(round_id):
    return sum(
        1
        for a in applications_of_round(round_id)
        if a["status"] not in ("RECEIVED", "NOT_SELECTED", "WITHDRAWN")
    )


def application_negotiation_round_count(application_id):
    return sum(
        1
        for n in negotiation_rounds_of(application_id)
        if n["kind"] == "OFFER"
    )


def application_requirement_total(application_id):
    return len(requirements_of(application_id))


def application_requirement_satisfied_count(application_id):
    return sum(
        1
        for r in requirements_of(application_id)
        if r["status"] in ("SATISFIED", "WAIVED")
    )


def easement_open_violation_count(easement_id):
    return sum(
        1
        for v in violations_of(easement_id)
        if v["status"] in ("OPEN", "CURE_PLAN_ACCEPTED", "ESCALATED")
    )


def easement_pending_amendment_count(easement_id):
    # PRD 3.8: "pending_amendment_count counts amendments in UNDER_REVIEW" --
    # a suspension therefore recomputes the counter downward.
    return sum(1 for a in amendments_of(easement_id) if a["status"] == "UNDER_REVIEW")


def easement_amendment_count(easement_id):
    return sum(1 for a in amendments_of(easement_id) if a["status"] == "APPROVED")


def program_total_preserved_acres(program_id):
    total = Decimal(0)
    for e in db.easements.values():
        if e["status"] not in ("RECORDED", "AMENDED"):
            continue
        app = db.applications.get(e["application_id"])
        if app is None:
            continue
        rnd = db.rounds.get(app["funding_round_id"])
        if rnd is None or rnd["program_id"] != program_id:
            continue
        total += e["protected_acres"]
    return round_half_up(total, 2)
