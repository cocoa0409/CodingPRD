"""Shared lookup / ordering helpers for the route modules."""
from db import store
from errors import ApiError

READ_ALL = ["CycleAdmin", "CommitteeMember", "CreditArbiter", "Partner", "AuditObserver"]


def find(collection, key, error_id):
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def find_cycle(cycle_id):
    return find(store.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")


def find_partner(partner_id):
    return find(store.partners, partner_id, "ERR_PARTNER_NOT_FOUND")


def find_matter(matter_id):
    return find(store.matters, matter_id, "ERR_MATTER_NOT_FOUND")


def find_allocation(allocation_id):
    return find(store.allocations, allocation_id, "ERR_ALLOCATION_NOT_FOUND")


def find_record(record_id):
    return find(store.records, record_id, "ERR_RECORD_NOT_FOUND")


def find_claim(claim_id):
    return find(store.claims, claim_id, "ERR_CLAIM_NOT_FOUND")


def find_assessment(assessment_id):
    return find(store.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")


def find_review(review_id):
    return find(store.reviews, review_id, "ERR_REVIEW_NOT_FOUND")


def find_ballot(ballot_id):
    return find(store.ballots, ballot_id, "ERR_BALLOT_NOT_FOUND")


def find_award(award_id):
    return find(store.awards, award_id, "ERR_AWARD_NOT_FOUND")


def find_payment(payment_id):
    return find(store.payments, payment_id, "ERR_PAYMENT_NOT_FOUND")


def find_transition(transition_id):
    return find(store.transitions, transition_id, "ERR_TRANSITION_NOT_FOUND")


def by_created(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def matches(row, filters):
    for key, value in filters.items():
        if value is None:
            continue
        if row.get(key) != value:
            return False
    return True


def filtered(rows, filters):
    return [r for r in rows if matches(r, filters)]
