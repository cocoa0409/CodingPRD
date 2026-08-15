"""Pre-built role headers for every role in the PRD.

All four roles are opaque (no entity-backed identity), so shared constants are
safe for general use. For Contractor-role and Owner-role writes the PRD binds
X-User-ID to the project's contractor_user_id / owner_user_id, so the
per-instance builders below take the user id explicitly.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    USER_OWNER,
    USER_CONTRACTOR,
    USER_ARCH_LEAD,
    USER_FIRM_ADMIN,
)

# Shared constants — safe for FirmAdmin / ArchitectCA (never compared against
# project fields) and for tests that do not exercise counterparty ownership.
TEST_USERS = {
    "firm_admin_headers": build_user_headers(USER_FIRM_ADMIN, "FirmAdmin"),
    "architect_headers": build_user_headers(USER_ARCH_LEAD, "ArchitectCA"),
    "contractor_headers": build_user_headers(USER_CONTRACTOR, "Contractor"),
    "owner_headers": build_user_headers(USER_OWNER, "Owner"),
}


def make_firm_admin_headers(user_id: str = USER_FIRM_ADMIN) -> dict:
    """FirmAdmin identity is opaque; any id authorizes the firm-admin operations."""
    return build_user_headers(user_id, "FirmAdmin")


def make_architect_headers(user_id: str = USER_ARCH_LEAD) -> dict:
    """ArchitectCA identity is recorded (e.g. certified_by_user_id) and compared
    against earlier actor identifiers by segregation-of-duties checks."""
    return build_user_headers(user_id, "ArchitectCA")


def make_contractor_headers(user_id: str) -> dict:
    """Contractor-role writes require X-User-ID == project.contractor_user_id.
    Pass the project's contractor_user_id for every ownership-gated call."""
    return build_user_headers(user_id, "Contractor")


def make_owner_headers(user_id: str) -> dict:
    """Owner-role writes require X-User-ID == project.owner_user_id.
    Pass the project's owner_user_id for every ownership-gated call."""
    return build_user_headers(user_id, "Owner")
