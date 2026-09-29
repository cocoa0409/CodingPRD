"""Path-identifier and body foreign-key resolution (ladder rungs 4 and 5)."""

from db import db
from errors import not_found


def resolve(collection, ident, resource):
    record = collection.get(ident) if isinstance(ident, str) else None
    if record is None:
        not_found(resource)
    return record


def member(ident):
    return resolve(db.member_insurers, ident, "MemberInsurer")


def producer(ident):
    return resolve(db.producers, ident, "Producer")


def applicant(ident):
    return resolve(db.applicants, ident, "Applicant")


def cat_zone(ident):
    return resolve(db.cat_zones, ident, "CatastropheZone")


def prop(ident):
    return resolve(db.properties, ident, "Property")


def application(ident):
    return resolve(db.applications, ident, "Application")


def inspection(ident):
    return resolve(db.inspections, ident, "Inspection")


def requirement(ident):
    return resolve(db.requirements, ident, "ImprovementRequirement")


def rate_filing(ident):
    return resolve(db.rate_filings, ident, "RateFiling")


def policy(ident):
    return resolve(db.policies, ident, "Policy")


def takeout_offer(ident):
    return resolve(db.takeout_offers, ident, "TakeoutOffer")


def assessment_event(ident):
    return resolve(db.assessment_events, ident, "AssessmentEvent")


def assessment_allocation(ident):
    return resolve(db.assessment_allocations, ident, "AssessmentAllocation")
