"""Shared route plumbing: the auth decorator and list-endpoint helpers."""
from functools import wraps

import envelope
import validation

ALL_ROLES = [
    "PlatformAdmin",
    "CaseManager",
    "CourierOps",
    "AgencyLiaison",
    "ComplianceOfficer",
    "Traveler",
]
READ_ROLES = ALL_ROLES
AUDIT_ROLES = ["PlatformAdmin", "CaseManager", "ComplianceOfficer", "Traveler"]
CONFIG_READ_ROLES = ["PlatformAdmin", "CaseManager"]


def endpoint(name, roles):
    """Rung 1 then rung 2, then hand a Ctx to the handler."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(**kwargs):
            ctx = validation.authenticate(name, roles)
            return fn(ctx, **kwargs)
        return wrapper
    return decorator


def listing(rows, serializer):
    limit, offset = validation.pagination()
    page, total = envelope.paginate(rows, limit, offset)
    return envelope.array_response([serializer(r) for r in page], limit, offset, total)


def created(data):
    return envelope.object_response(data, 201)


def ok(data):
    return envelope.object_response(data, 200)
