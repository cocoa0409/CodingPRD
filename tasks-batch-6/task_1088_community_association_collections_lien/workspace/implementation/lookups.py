"""Entity resolution (existence -> ERR_NOT_FOUND) and AssociationManager read scoping."""
import store as S
from web import ApiError


def _get(coll, rid):
    if not isinstance(rid, str):
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    ent = coll.get(rid)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return ent


def get_association(rid):
    return _get(S.associations, rid)


def get_account(rid):
    return _get(S.accounts, rid)


def get_assessment(rid):
    return _get(S.assessments, rid)


def get_payment(rid):
    return _get(S.payments, rid)


def get_notice(rid):
    return _get(S.notices, rid)


def get_plan(rid):
    return _get(S.plans, rid)


def get_lien(rid):
    return _get(S.liens, rid)


def get_referral(rid):
    return _get(S.referrals, rid)


def get_bankruptcy(rid):
    return _get(S.bankruptcies, rid)


def get_remittance(rid):
    return _get(S.remittances, rid)


# --------------------------------------------------------------------------
# read scoping for AssociationManager
# --------------------------------------------------------------------------
def scope_association(role, uid, association_id):
    if role == "AssociationManager" and association_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "AssociationManager scope violation")


def scope_account(role, uid, account):
    scope_association(role, uid, account["association_id"])


def scope_child_by_account(role, uid, account_id):
    if role != "AssociationManager":
        return
    assoc_id = S.association_of_account(account_id)
    if assoc_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "AssociationManager scope violation")
