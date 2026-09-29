"""Acting principals.

Five of the six roles carry an opaque operator identifier that the server never
compares against any stored row, so a module-level constant is safe for them.
A ``SupplierUser`` is different: its ``X-User-ID`` is the id of the acting
supplier, so its headers must be built per supplier with
:func:`supplier_user_headers`.
"""
from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers

# ------------------------------------------------------- opaque operator principals
PLATFORM_ADMIN_USER_ID = "admin-001"
COMMERCIAL_MANAGER_USER_ID = "cm-001"
COMPLIANCE_OFFICER_USER_ID = "co-001"
PARITY_ANALYST_USER_ID = "pa-001"
BOOKING_AGENT_USER_ID = "ba-001"

PLATFORM_ADMIN = build_user_headers("admin-001", "PlatformAdmin")
PLATFORM_ADMIN_ALT = build_user_headers("admin-002", "PlatformAdmin")

COMMERCIAL_MANAGER = build_user_headers("cm-001", "CommercialManager")
COMMERCIAL_MANAGER_ALT = build_user_headers("cm-002", "CommercialManager")

COMPLIANCE_OFFICER = build_user_headers("co-001", "ComplianceOfficer")
COMPLIANCE_OFFICER_ALT = build_user_headers("co-002", "ComplianceOfficer")

PARITY_ANALYST = build_user_headers("pa-001", "ParityAnalyst")
PARITY_ANALYST_ALT = build_user_headers("pa-002", "ParityAnalyst")

BOOKING_AGENT = build_user_headers("ba-001", "BookingAgent")
BOOKING_AGENT_ALT = build_user_headers("ba-002", "BookingAgent")

# A dual-hatted operator: the same opaque identifier acting under two roles, which
# is what the segregation-of-duties comparisons are written against.
DUAL_HAT_USER_ID = "dual-001"
DUAL_HAT_COMMERCIAL_MANAGER = build_user_headers(DUAL_HAT_USER_ID, "CommercialManager")
DUAL_HAT_COMPLIANCE_OFFICER = build_user_headers(DUAL_HAT_USER_ID, "ComplianceOfficer")
DUAL_HAT_BOOKING_AGENT = build_user_headers(DUAL_HAT_USER_ID, "BookingAgent")


def supplier_user_headers(supplier_id: str) -> Headers:
    """Headers for the ``SupplierUser`` that owns ``supplier_id``."""
    return build_user_headers(supplier_id, "SupplierUser")


def role_headers(role: str, user_id: str = "op-001") -> Headers:
    """Headers for an arbitrary role name, including undeclared ones."""
    return build_user_headers(user_id, role)


def headers_for_each_role(supplier_id: str) -> dict:
    """Every declared role, with the supplier-backed identity threaded correctly."""
    return {
        "PlatformAdmin": PLATFORM_ADMIN,
        "CommercialManager": COMMERCIAL_MANAGER,
        "ComplianceOfficer": COMPLIANCE_OFFICER,
        "ParityAnalyst": PARITY_ANALYST,
        "SupplierUser": supplier_user_headers(supplier_id),
        "BookingAgent": BOOKING_AGENT,
    }
