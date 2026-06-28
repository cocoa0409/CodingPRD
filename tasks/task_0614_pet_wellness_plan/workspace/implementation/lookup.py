"""Path-resource existence resolution (PRD §2.6, §2.9).

Path identifiers are resolved left to right; the first identifier that does not
resolve raises ERR_NOT_FOUND. Body foreign keys raise ERR_REFERENCE_NOT_FOUND
separately.
"""
from errors import err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND
from db import db


def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return rec


def get_membership_or_404(mid):
    return get_or_404(db.memberships, mid)


def get_plan_or_ref_404(plan_id):
    rec = db.plans.get(plan_id)
    if rec is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "Referenced plan does not exist")
    return rec


def get_clinic_or_ref_404(clinic_id):
    rec = db.clinics.get(clinic_id)
    if rec is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "Referenced clinic does not exist")
    return rec


def get_account_or_ref_404(account_id):
    rec = db.member_accounts.get(account_id)
    if rec is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "Referenced member account does not exist")
    return rec
