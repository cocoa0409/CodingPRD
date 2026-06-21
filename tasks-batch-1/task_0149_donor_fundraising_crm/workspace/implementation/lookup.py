"""Existence lookups that raise ERR_NOT_FOUND (PRD §2.6) when an id does not
resolve. Used for path ids and body FKs, validated left-to-right."""

import db
import errors


def _get_or_404(store, entity_id):
    rec = store.get(entity_id)
    if rec is None:
        raise errors.not_found(f"Entity '{entity_id}' does not exist.")
    return rec


def household(entity_id):
    return _get_or_404(db.households, entity_id)


def donor(entity_id):
    return _get_or_404(db.donors, entity_id)


def employer(entity_id):
    return _get_or_404(db.employers, entity_id)


def campaign(entity_id):
    return _get_or_404(db.campaigns, entity_id)


def appeal(entity_id):
    return _get_or_404(db.appeals, entity_id)


def pledge(entity_id):
    return _get_or_404(db.pledges, entity_id)


def pledge_installment(entity_id):
    return _get_or_404(db.pledge_installments, entity_id)


def gift(entity_id):
    return _get_or_404(db.gifts, entity_id)


def soft_credit(entity_id):
    return _get_or_404(db.soft_credits, entity_id)


def match_claim(entity_id):
    return _get_or_404(db.match_claims, entity_id)


def planned_gift(entity_id):
    return _get_or_404(db.planned_gifts, entity_id)


def acknowledgement(entity_id):
    return _get_or_404(db.acknowledgements, entity_id)


def segment(entity_id):
    return _get_or_404(db.segments, entity_id)
