"""Existence lookups and ownership checks.

Existence (priority 3) is checked before any state/business rule (PRD §2.8).
For entity-backed roles, ownership (priority 2, ERR_FORBIDDEN) is enforced once
the resource has been resolved.
"""

from flask import g

import errors
from db import db


def get_or_404(collection, resource_id):
    rec = collection.get(resource_id)
    if rec is None:
        raise errors.not_found()
    return rec


def fk_or_404(collection, resource_id):
    """Validate a foreign-key reference resolves; a missing FK is a 404 (PRD §2.8)."""
    rec = collection.get(resource_id)
    if rec is None:
        raise errors.not_found()
    return rec


# -----------------------------------------------------------------------------
# Ownership: entity-backed roles (PRD §2.1)
# -----------------------------------------------------------------------------

def family_of_patient(patient):
    return db.family_accounts.get(patient["family_account_id"])


def guardian_owns_family(family):
    """Guardian X-User-ID must equal the family's guardian_user_id."""
    return family is not None and family.get("guardian_user_id") == g.user_id


def require_guardian_owns_family(family):
    if g.user_role == "Guardian" and not guardian_owns_family(family):
        raise errors.forbidden()


def require_guardian_owns_patient(patient):
    if g.user_role == "Guardian":
        fam = family_of_patient(patient)
        if not guardian_owns_family(fam):
            raise errors.forbidden()


def require_guardian_owns_plan(plan):
    if g.user_role == "Guardian":
        pat = db.patients.get(plan["patient_id"])
        fam = family_of_patient(pat) if pat else None
        if not guardian_owns_family(fam):
            raise errors.forbidden()
