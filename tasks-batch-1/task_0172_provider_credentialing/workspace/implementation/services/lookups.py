"""Existence lookups that raise ERR_NOT_FOUND when missing."""
from db import store
from errors import err


def get_or_404(collection_attr, rid):
    rec = getattr(store, collection_attr).get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found.")
    return rec


def get_org(rid):
    return get_or_404("orgs", rid)


def get_provider(rid):
    return get_or_404("providers", rid)


def get_payer(rid):
    return get_or_404("payers", rid)


def get_sanctions_source(rid):
    return get_or_404("sanctions_sources", rid)


def get_credential_item(rid):
    return get_or_404("credential_items", rid)


def get_verification_request(rid):
    return get_or_404("verification_requests", rid)


def get_sanctions_screening(rid):
    return get_or_404("sanctions_screenings", rid)


def get_credentialing_file(rid):
    return get_or_404("credentialing_files", rid)


def get_peer_reviewer(rid):
    return get_or_404("peer_reviewers", rid)


def get_vote(rid):
    return get_or_404("peer_review_votes", rid)


def get_enrollment(rid):
    return get_or_404("payer_enrollments", rid)
