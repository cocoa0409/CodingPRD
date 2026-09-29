"""Auth headers, RBAC and the endpoint decorator (PRD 2.1, 2.10)."""

import functools

from flask import g, request

import db
import errors
import response
from errors import (ERR_FORBIDDEN_ROLE, ERR_NOT_RESOURCE_OWNER,
                    ERR_UNAUTHENTICATED, ApiError, fail)

GENERAL_MANAGER = "GeneralManager"
COMPTROLLER = "Comptroller"
SYNDICATION_COUNSEL = "SyndicationCounsel"
LEAD_PRODUCER = "LeadProducer"
INVESTOR = "Investor"

ALL_ROLES = (GENERAL_MANAGER, COMPTROLLER, SYNDICATION_COUNSEL,
             LEAD_PRODUCER, INVESTOR)
OPERATOR_ROLES = (GENERAL_MANAGER, COMPTROLLER, SYNDICATION_COUNSEL,
                  LEAD_PRODUCER)
MANAGEMENT_ROLES = (GENERAL_MANAGER, COMPTROLLER, LEAD_PRODUCER)


def user_id():
    return g.user_id


def user_role():
    return g.user_role


def is_investor():
    return g.user_role == INVESTOR


def _authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or uid == "" or role == "":
        fail(ERR_UNAUTHENTICATED)
    if role not in ALL_ROLES:
        fail(ERR_UNAUTHENTICATED)
    g.user_id = uid
    g.user_role = role


def require_owner(investor_id):
    """Global validation step 6 (PRD 2.1 / 2.10)."""
    if is_investor() and investor_id != user_id():
        fail(ERR_NOT_RESOURCE_OWNER)


def endpoint(roles):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            with db.LOCK:
                ctx = db.RequestContext()
                g.ctx = ctx
                try:
                    _authenticate()
                    if g.user_role not in roles:
                        fail(ERR_FORBIDDEN_ROLE)
                    result = fn(**kwargs)
                    ctx.commit()
                except ApiError as exc:
                    return response.error(exc.error_id, exc.message,
                                          exc.http_status)
                return result.build()
        return wrapper
    return decorator


def ctx():
    return g.ctx


# ------------------------------------------------------------ path resolution
def lookup(table, row_id, error_id):
    row = db.get(table, row_id)
    if row is None:
        fail(error_id)
    return row


def find_production(production_id):
    return lookup("productions", production_id,
                  errors.ERR_PRODUCTION_NOT_FOUND)


def find_theatre(theatre_id):
    return lookup("theatres", theatre_id, errors.ERR_THEATRE_NOT_FOUND)


def find_offering_document(doc_id):
    return lookup("offering_documents", doc_id,
                  errors.ERR_OFFERING_DOCUMENT_NOT_FOUND)


def find_investor(investor_id):
    return lookup("investors", investor_id, errors.ERR_INVESTOR_NOT_FOUND)
