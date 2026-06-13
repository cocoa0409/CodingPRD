"""Public serialization of stored records.

Records are stored as plain dicts that already hold every public field plus the
common quartet (id, created_at, updated_at, version). We return shallow copies
so callers never mutate the store, applying live recomputes where the PRD
mandates a fresh recount on read (donor derived fields, bucket counts).
"""
import db
from services import domain


def serialize_center(center):
    return dict(center)


def serialize_donor(donor):
    domain.donor_view(donor)
    return dict(donor)


def serialize_deferral(deferral):
    return dict(deferral)


def serialize_slot(slot):
    return dict(slot)


def serialize_appointment(appt):
    return dict(appt)


def serialize_screening(s):
    return dict(s)


def serialize_donation(d):
    return dict(d)


def serialize_test_result(t):
    return dict(t)


def serialize_unit(u):
    return dict(u)


def serialize_reaction(r):
    return dict(r)


def serialize_recall(r):
    return dict(r)


def serialize_bucket(b):
    domain.bucket_view(b)
    return dict(b)
