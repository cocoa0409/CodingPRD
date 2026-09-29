"""Authentication, authorization (PRD §2.1) and ownership enforcement (§2.11 #7)."""

from functools import wraps

from flask import g, request

import db
import errors
from errors import fail

ROLES = ("BureauAdmin", "BookingAgent", "Speaker", "Client")

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def authenticate(allowed_roles):
    """Ladder bands 1 and 2."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in ROLES:
        fail(errors.ERR_UNAUTHENTICATED)
    if allowed_roles is not None and role not in allowed_roles:
        fail(errors.ERR_UNAUTHORIZED)
    g.user_id = user_id
    g.role = role


def roles(*allowed):
    """Route decorator running the authentication / authorization bands."""

    allowed_roles = tuple(allowed) if allowed else None

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(allowed_roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# --- path / body lookups (ladder bands 3 and 6) -----------------------------

def _get(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id)
    return row


def get_speaker(sid):
    return _get(db.speakers, sid, errors.ERR_SPEAKER_NOT_FOUND)


def get_client(cid):
    return _get(db.clients, cid, errors.ERR_CLIENT_NOT_FOUND)


def get_inquiry(iid):
    return _get(db.inquiries, iid, errors.ERR_INQUIRY_NOT_FOUND)


def get_proposal(pid):
    return _get(db.proposals, pid, errors.ERR_PROPOSAL_NOT_FOUND)


def get_option(oid):
    return _get(db.options, oid, errors.ERR_OPTION_NOT_FOUND)


def get_engagement(eid):
    return _get(db.engagements, eid, errors.ERR_ENGAGEMENT_NOT_FOUND)


def get_contract(cid):
    return _get(db.contracts, cid, errors.ERR_CONTRACT_NOT_FOUND)


def get_hold(hid):
    return _get(db.holds, hid, errors.ERR_HOLD_NOT_FOUND)


def get_expense(xid):
    return _get(db.expenses, xid, errors.ERR_TRAVEL_EXPENSE_NOT_FOUND)


def get_invoice(iid):
    return _get(db.invoices, iid, errors.ERR_INVOICE_NOT_FOUND)


def get_remittance(rid):
    return _get(db.remittances, rid, errors.ERR_REMITTANCE_NOT_FOUND)


def get_claim(cid):
    return _get(db.claims, cid, errors.ERR_CLAIM_NOT_FOUND)


def get_grant(gid):
    return _get(db.grants, gid, errors.ERR_GRANT_NOT_FOUND)


def get_feedback(fid):
    return _get(db.feedbacks, fid, errors.ERR_FEEDBACK_NOT_FOUND)


# --- relationship helpers ---------------------------------------------------

def inquiry_of_proposal(proposal):
    return db.inquiries[proposal["inquiry_id"]]


def inquiry_of_engagement(engagement):
    return db.inquiries[engagement["inquiry_id"]]


def client_of_engagement(engagement):
    return db.clients[inquiry_of_engagement(engagement)["client_id"]]


def speaker_of_engagement(engagement):
    return db.speakers[engagement["speaker_id"]]


# --- ownership (ladder band 7) ----------------------------------------------

def _deny():
    fail(errors.ERR_NOT_RESOURCE_OWNER)


def own_inquiry(inquiry):
    if g.role == "Client":
        if inquiry["client_id"] != g.user_id:
            _deny()
    elif g.role == "BookingAgent":
        if inquiry.get("owning_agent_user_id") != g.user_id:
            _deny()


def own_proposal(proposal):
    own_inquiry(inquiry_of_proposal(proposal))


def own_engagement(engagement):
    if g.role == "Speaker":
        if engagement["speaker_id"] != g.user_id:
            _deny()
    elif g.role == "Client":
        if inquiry_of_engagement(engagement)["client_id"] != g.user_id:
            _deny()
    elif g.role == "BookingAgent":
        if engagement.get("owning_agent_user_id") != g.user_id:
            _deny()


def own_contract(contract):
    own_engagement(db.engagements[contract["engagement_id"]])


def own_expense(expense):
    own_engagement(db.engagements[expense["engagement_id"]])


def own_invoice(invoice):
    if g.role == "Client":
        if invoice["client_id"] != g.user_id:
            _deny()
    elif g.role == "Speaker":
        _deny()
    elif g.role == "BookingAgent":
        own_engagement(db.engagements[invoice["engagement_id"]])
