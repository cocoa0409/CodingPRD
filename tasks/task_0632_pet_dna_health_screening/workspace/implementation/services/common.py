"""Shared lookup and ownership helpers used across route modules."""
from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER, ERR_PURGE_IN_PROGRESS,
)
from serializers import _account_purge_pending


def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return rec


def require_account_owner(account_id, user_id, role):
    """ERR_NOT_RESOURCE_OWNER: Account actor must own the targeted resource.
    PlatformAdmin/LabTechnician are not subject to account-ownership checks."""
    if role == "Account" and account_id != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Acting account does not own this resource")


def assert_not_purge_pending(account_id):
    """ERR_PURGE_IN_PROGRESS: no mutation while a DELETE DataRequest is in
    {GRACE, PURGING} for this account."""
    if _account_purge_pending(account_id):
        raise err(ERR_PURGE_IN_PROGRESS, "A deletion request is in progress for this account")
