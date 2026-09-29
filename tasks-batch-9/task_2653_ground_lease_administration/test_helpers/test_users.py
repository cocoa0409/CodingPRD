"""
Acting principals for every role in PRD.md §2.1.

Five of the six roles are opaque: their `X-User-ID` is any stable string. The
sixth is entity-backed — the PRD states that for a `GroundTenant` "the
`X-User-ID` is the identifier of the acting `Lessee`", so every GroundTenant
call must be made with the real `Lessee.id` created during setup. Never use a
placeholder there; a bogus tenant identity turns every tenant-authored setup
call into a refusal and cascades as a fixture failure.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ARBITRATOR,
    ROLE_ASSET_MANAGER,
    ROLE_GROUND_TENANT,
    ROLE_LEASE_ACCOUNTANT,
    ROLE_LESSOR_ADMIN,
    ROLE_MORTGAGEE_AGENT,
    USER_ACCOUNTANT_1,
    USER_ARBITRATOR_NEUTRAL,
    USER_ASSET_MANAGER_1,
    USER_LESSOR_ADMIN,
)


def make_lessor_admin_headers(user_id=USER_LESSOR_ADMIN):
    return build_user_headers(user_id, ROLE_LESSOR_ADMIN)


def make_asset_manager_headers(user_id=USER_ASSET_MANAGER_1):
    return build_user_headers(user_id, ROLE_ASSET_MANAGER)


def make_accountant_headers(user_id=USER_ACCOUNTANT_1):
    return build_user_headers(user_id, ROLE_LEASE_ACCOUNTANT)


def make_arbitrator_headers(user_id=USER_ARBITRATOR_NEUTRAL):
    return build_user_headers(user_id, ROLE_ARBITRATOR)


def make_ground_tenant_headers(lessee_id):
    """GroundTenant identity is entity-backed: X-User-ID is the Lessee.id."""
    return build_user_headers(lessee_id, ROLE_GROUND_TENANT)


def make_mortgagee_agent_headers(mortgage_id):
    """The design recipes act as a MortgageeAgent under the mortgage's own id."""
    return build_user_headers(mortgage_id, ROLE_MORTGAGEE_AGENT)


def make_headers_for_role(role, user_id):
    return build_user_headers(user_id, role)


# Shared header dicts for the five opaque roles.
LESSOR_ADMIN = make_lessor_admin_headers()
ASSET_MANAGER = make_asset_manager_headers()
ACCOUNTANT = make_accountant_headers()
ARBITRATOR = make_arbitrator_headers()
