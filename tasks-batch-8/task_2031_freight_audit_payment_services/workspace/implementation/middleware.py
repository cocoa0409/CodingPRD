"""Auth header extraction, role authorization, and entity-backed scope checks."""

from flask import request

import db
from db import STORE
from errors import ApiError, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, \
    ERR_FORBIDDEN_FOR_ROLE, ERR_NOT_FOUND, ERR_CLIENT_NOT_ACTIVE

ROLES = {
    "FapAdmin",
    "AuditAnalyst",
    "FinanceController",
    "TreasuryApprover",
    "CarrierRep",
    "ClientViewer",
    "System",
}

READ_ROLES = {"FapAdmin", "AuditAnalyst", "FinanceController",
              "TreasuryApprover", "CarrierRep", "ClientViewer"}


def authenticate():
    """Stage 1: identity headers present and well-formed."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not isinstance(uid, str) or not uid.strip():
        raise ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
                       "X-User-ID header missing or malformed")
    if role is None or role not in ROLES:
        raise ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
                       "X-User-Role header missing or malformed")
    return uid.strip(), role


def require_roles(role, allowed):
    """Stage 2 (role half): the role must be permitted on the endpoint."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, 403,
                       "Role %s is not permitted for this endpoint" % role)


def entity_scope(kind, obj):
    """Resolve the (client_id, carrier_id) ownership scope of any resource.

    carrier_id is None when the resource has no carrier association.
    """
    if obj is None:
        return None, None
    if kind == "client":
        return obj["id"], None
    if kind == "carrier":
        return obj["client_id"], obj["id"]
    if kind == "contract":
        return obj["client_id"], obj["carrier_id"]
    if kind == "shipment":
        return obj["client_id"], obj["carrier_id"]
    if kind == "invoice":
        return obj["client_id"], obj["carrier_id"]
    if kind == "line":
        inv = STORE.invoices.get(obj["invoice_id"])
        return entity_scope("invoice", inv)
    if kind == "exception":
        inv = STORE.invoices.get(obj["invoice_id"])
        return obj["client_id"], (inv["carrier_id"] if inv else None)
    if kind == "gl_account":
        return obj["client_id"], None
    if kind == "allocation":
        line = STORE.lines.get(obj["invoice_line_id"])
        return entity_scope("line", line)
    if kind == "run":
        return obj["client_id"], None
    if kind == "run_item":
        inv = STORE.invoices.get(obj["invoice_id"])
        return entity_scope("invoice", inv)
    if kind == "advice":
        run = STORE.runs.get(obj["payment_run_id"])
        return (run["client_id"] if run else None), obj["carrier_id"]
    if kind == "fx_rate":
        return obj["client_id"], None
    if kind == "claim":
        inv = STORE.invoices.get(obj["invoice_id"])
        return obj["client_id"], (inv["carrier_id"] if inv else None)
    if kind == "export":
        return obj["client_id"], None
    return None, None


def _not_found():
    return ApiError(ERR_NOT_FOUND, 404, "Referenced resource does not exist")


def guard_read_scope(role, uid, kind, obj):
    """Entity-backed roles reading outside their scope get ERR_NOT_FOUND."""
    if obj is None:
        raise _not_found()
    cid, car = entity_scope(kind, obj)
    if role == "ClientViewer" and cid != uid:
        raise _not_found()
    if role == "CarrierRep" and car is not None and car != uid:
        raise _not_found()
    return obj


def in_read_scope(role, uid, kind, obj):
    cid, car = entity_scope(kind, obj)
    if role == "ClientViewer" and cid != uid:
        return False
    if role == "CarrierRep" and car is not None and car != uid:
        return False
    return True


def guard_mutation_scope(role, uid, kind, obj):
    """Entity-backed roles mutating outside their scope get ERR_FORBIDDEN_FOR_ROLE."""
    if role == "CarrierRep":
        cid, car = entity_scope(kind, obj)
        if car is not None and car != uid:
            raise ApiError(ERR_FORBIDDEN_FOR_ROLE, 403,
                           "Carrier representative acting outside own carrier scope")
    elif role == "ClientViewer":
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, 403,
                       "ClientViewer is read-only")


def require_client_active(client):
    """Stage 5: business mutations require the owning client to be ACTIVE."""
    if client is None or client["status"] != "ACTIVE":
        raise ApiError(ERR_CLIENT_NOT_ACTIVE, 409,
                       "Business mutation attempted while client not ACTIVE")


def resolve(table, entity_id):
    """Stage 3: path identifier existence."""
    obj = table.get(entity_id)
    if obj is None:
        raise _not_found()
    return obj
