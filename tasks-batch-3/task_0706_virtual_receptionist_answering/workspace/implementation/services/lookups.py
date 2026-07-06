"""Existence lookups and ownership checks (PRD §2.1, §2.7, §2.8).

Existence is validated left-to-right; first unresolved id => ERR_NOT_FOUND.
Ownership: AccountOwner X-User-ID == resource.account_id;
Receptionist X-User-ID == Call.answered_by_receptionist_id where it applies.
"""
import errors
from db import db
from middleware import ROLE_OWNER, ROLE_RECEPTIONIST


def find_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Referenced resource does not exist")
    return rec


def require_account_owner(account_id, user_id, role):
    """ERR_NOT_RESOURCE_OWNER when an AccountOwner targets another account's
    resource (priority 4). PlatformAdmin/Receptionist are not account-scoped."""
    if role == ROLE_OWNER and account_id != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "AccountOwner may only act on its own account's resources")


def require_call_receptionist(call, user_id, role):
    """For receptionist-owned call operations, the acting Receptionist must be
    the one who answered (PRD §2.1)."""
    if role == ROLE_RECEPTIONIST and call["answered_by_receptionist_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Only the answering receptionist may act on this call")
