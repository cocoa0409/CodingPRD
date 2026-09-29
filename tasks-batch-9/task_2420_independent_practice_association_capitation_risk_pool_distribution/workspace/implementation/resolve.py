"""Resource-specific path/body resolution (PRD 2.7, checks 4 and 5)."""

import db
from errors import fail


def _get(store, identifier, error_id):
    entity = store.get(identifier) if isinstance(identifier, str) else None
    if entity is None:
        fail(error_id)
    return entity


def agreement(identifier):
    return _get(db.agreements, identifier, "ERR_AGREEMENT_NOT_FOUND")


def physician(identifier):
    return _get(db.physicians, identifier, "ERR_PHYSICIAN_NOT_FOUND")


def enrollee(identifier):
    return _get(db.enrollees, identifier, "ERR_ENROLLEE_NOT_FOUND")


def assignment(identifier):
    return _get(db.assignments, identifier, "ERR_ASSIGNMENT_NOT_FOUND")


def enrollment_file(identifier):
    return _get(db.files, identifier, "ERR_ENROLLMENT_FILE_NOT_FOUND")


def remittance(identifier):
    return _get(db.remittances, identifier, "ERR_REMITTANCE_NOT_FOUND")


def pool(identifier):
    return _get(db.pools, identifier, "ERR_RISK_POOL_NOT_FOUND")


def claim(identifier):
    return _get(db.claims, identifier, "ERR_CLAIM_NOT_FOUND")


def recovery(identifier):
    return _get(db.recoveries, identifier, "ERR_RECOVERY_NOT_FOUND")


def scorecard(identifier):
    return _get(db.scorecards, identifier, "ERR_SCORECARD_NOT_FOUND")


def distribution(identifier):
    return _get(db.distributions, identifier, "ERR_DISTRIBUTION_NOT_FOUND")
