"""fetch-or-404 helpers for each collection (existence checks, PRD §2.5)."""
from db import store
from errors import err, ERR_NOT_FOUND


def _get(collection, _id):
    obj = collection.get(_id)
    if obj is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return obj


def test_center(_id):
    return _get(store.test_centers, _id)


def test_session(_id):
    return _get(store.test_sessions, _id)


def candidate(_id):
    return _get(store.candidates, _id)


def registration(_id):
    return _get(store.registrations, _id)


def accommodation_request(_id):
    return _get(store.accommodation_requests, _id)


def standby_entry(_id):
    return _get(store.standby_entries, _id)


def score_report(_id):
    return _get(store.score_reports, _id)


def score_send(_id):
    return _get(store.score_sends, _id)


def clep_claim(_id):
    return _get(store.clep_claims, _id)


def id_verification(_id):
    return _get(store.id_verifications, _id)
