"""Route-level helpers shared by every blueprint."""

import derive
from envelope import ok, ok_list
from store import ordered
from validate import pagination

READ_ROLES_ALL = (
    "SystemOperator",
    "PrivacyOfficer",
    "ComplianceApprover",
    "VendorManager",
    "HRAdministrator",
)


def respond(serializer, rec, status=200):
    """Recompute every derived field, then serialize."""
    derive.refresh_all()
    return ok(serializer(rec), status)


def respond_raw(data, status=200):
    derive.refresh_all()
    return ok(data, status)


def respond_list(rows, serializer):
    derive.refresh_all()
    limit, offset = pagination()
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)
