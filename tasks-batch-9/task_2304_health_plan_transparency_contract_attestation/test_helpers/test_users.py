"""Pre-built request headers for each role.

Four roles carry an opaque identity, so a fixed operator identifier is enough.
``VendorContact`` is the one entity-backed role: its ``X-User-ID`` must be the
``id`` of the acting vendor row, so headers for it are always built from a
vendor id captured at runtime.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_EXTERNAL_AUDITOR,
    ROLE_PLAN_SPONSOR_ADMIN,
    ROLE_PLATFORM_OPERATOR,
    ROLE_VENDOR_CONTACT,
)

# ---------------------------------------------------------------------------
# Opaque operator identities
# ---------------------------------------------------------------------------

SPONSOR_ADMIN_USER_ID = "sponsor-admin-1"
OFFICER_USER_ID = "officer-1"
OFFICER_PREPARER_USER_ID = "officer-prep-1"
OFFICER_SIGNER_USER_ID = "officer-sign-1"
AUDITOR_USER_ID = "auditor-1"
DUAL_ROLE_USER_ID = "dual-1"
PLATFORM_OPERATOR_USER_ID = "platform-op-1"

#: An identity that is syntactically fine but resolves to no vendor row.
UNKNOWN_VENDOR_USER_ID = "ghost-vendor-9"


SPONSOR_ADMIN_HEADERS = build_user_headers(
    SPONSOR_ADMIN_USER_ID, ROLE_PLAN_SPONSOR_ADMIN
)
COMPLIANCE_OFFICER_HEADERS = build_user_headers(
    OFFICER_USER_ID, ROLE_COMPLIANCE_OFFICER
)
OFFICER_PREPARER_HEADERS = build_user_headers(
    OFFICER_PREPARER_USER_ID, ROLE_COMPLIANCE_OFFICER
)
OFFICER_SIGNER_HEADERS = build_user_headers(
    OFFICER_SIGNER_USER_ID, ROLE_COMPLIANCE_OFFICER
)
EXTERNAL_AUDITOR_HEADERS = build_user_headers(AUDITOR_USER_ID, ROLE_EXTERNAL_AUDITOR)
PLATFORM_OPERATOR_HEADERS = build_user_headers(
    PLATFORM_OPERATOR_USER_ID, ROLE_PLATFORM_OPERATOR
)

#: The same human identity acting as an auditor after touching the record as an
#: officer — used to exercise the segregation-of-duties anchor.
DUAL_ROLE_OFFICER_HEADERS = build_user_headers(
    DUAL_ROLE_USER_ID, ROLE_COMPLIANCE_OFFICER
)
DUAL_ROLE_AUDITOR_HEADERS = build_user_headers(
    DUAL_ROLE_USER_ID, ROLE_EXTERNAL_AUDITOR
)

TEST_USERS: dict[str, dict[str, str]] = {
    "sponsor_admin": SPONSOR_ADMIN_HEADERS,
    "compliance_officer": COMPLIANCE_OFFICER_HEADERS,
    "officer_preparer": OFFICER_PREPARER_HEADERS,
    "officer_signer": OFFICER_SIGNER_HEADERS,
    "external_auditor": EXTERNAL_AUDITOR_HEADERS,
    "platform_operator": PLATFORM_OPERATOR_HEADERS,
}


def make_vendor_contact_headers(vendor_id: str) -> dict[str, str]:
    """Headers for a ``VendorContact`` acting as the vendor row ``vendor_id``.

    The PRD requires that "When ``X-User-Role`` is ``VendorContact``,
    ``X-User-ID`` is the ``id`` of the acting ``Vendor`` row", so callers must
    thread the real vendor identifier through rather than reusing a constant.
    """
    return build_user_headers(vendor_id, ROLE_VENDOR_CONTACT)


def make_officer_headers(user_id: str) -> dict[str, str]:
    """Headers for an arbitrary ``ComplianceOfficer`` identity."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_auditor_headers(user_id: str) -> dict[str, str]:
    """Headers for an arbitrary ``ExternalAuditor`` identity."""
    return build_user_headers(user_id, ROLE_EXTERNAL_AUDITOR)


def make_sponsor_admin_headers(user_id: str) -> dict[str, str]:
    """Headers for an arbitrary ``PlanSponsorAdmin`` identity."""
    return build_user_headers(user_id, ROLE_PLAN_SPONSOR_ADMIN)


def make_platform_operator_headers(user_id: str) -> dict[str, str]:
    """Headers for an arbitrary ``PlatformOperator`` identity."""
    return build_user_headers(user_id, ROLE_PLATFORM_OPERATOR)


def headers_with_role(user_id: str, role: str) -> dict[str, str]:
    """Arbitrary identity/role pairing, for role-matrix sweeps."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> dict[str, str]:
    """Headers whose ``X-User-ID`` is present but empty."""
    return build_user_headers("", role)
