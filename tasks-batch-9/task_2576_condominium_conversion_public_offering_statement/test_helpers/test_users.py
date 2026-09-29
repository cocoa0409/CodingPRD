"""Role header builders.

Every request carries `X-User-ID` and `X-User-Role`. Seven of the nine roles
take an opaque `X-User-ID` of the caller's choosing, so a module-level constant
is safe for them. `TenantOccupant` and `Purchaser` are entity-backed: the PRD
requires their `X-User-ID` to be the id of the TenantHousehold / the
PurchaseAgreement they are acting for, so those two builders take the acting
entity's own id as a mandatory parameter and never fall back to a constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    ENGINEER_USER_ID,
    ESCROW_USER_ID,
    LENDER_USER_ID,
    PEER_USER_ID,
    REGULATOR_USER_ID,
    ROLE_CONVERTER_SPONSOR,
    ROLE_ESCROW_AGENT,
    ROLE_LENDER_UNDERWRITER,
    ROLE_LICENSED_ENGINEER,
    ROLE_PEER_REVIEW_ENGINEER,
    ROLE_PLATFORM_ADMIN,
    ROLE_PURCHASER,
    ROLE_STATE_REGULATOR,
    ROLE_TENANT_OCCUPANT,
    SPONSOR_USER_ID,
)
from .types import Headers


# --- the seven opaque-identity roles ----------------------------------------
def sponsor_headers(user_id: str = SPONSOR_USER_ID) -> Headers:
    return build_user_headers(user_id, ROLE_CONVERTER_SPONSOR)


def engineer_headers(user_id: str = ENGINEER_USER_ID) -> Headers:
    return build_user_headers(user_id, ROLE_LICENSED_ENGINEER)


def peer_headers(user_id: str = PEER_USER_ID) -> Headers:
    return build_user_headers(user_id, ROLE_PEER_REVIEW_ENGINEER)


def regulator_headers(user_id: str = REGULATOR_USER_ID) -> Headers:
    return build_user_headers(user_id, ROLE_STATE_REGULATOR)


def escrow_headers(user_id: str = ESCROW_USER_ID) -> Headers:
    return build_user_headers(user_id, ROLE_ESCROW_AGENT)


def lender_headers(user_id: str = LENDER_USER_ID) -> Headers:
    return build_user_headers(user_id, ROLE_LENDER_UNDERWRITER)


def admin_headers(user_id: str = ADMIN_USER_ID) -> Headers:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


# --- the two entity-backed roles --------------------------------------------
def tenant_headers(tenant_household_id: str) -> Headers:
    """Headers for a TenantOccupant acting as one TenantHousehold.

    `tenant_household_id` must be that household's own `id`; there is
    deliberately no default, because a shared identity would make a household
    act on a row it does not own.
    """
    if not tenant_household_id:
        raise ValueError("TenantOccupant headers require the household's own id")
    return build_user_headers(tenant_household_id, ROLE_TENANT_OCCUPANT)


def purchaser_headers(purchase_agreement_id: str) -> Headers:
    """Headers for a Purchaser acting as one PurchaseAgreement.

    `purchase_agreement_id` must be that agreement's own `id`; there is
    deliberately no default.
    """
    if not purchase_agreement_id:
        raise ValueError("Purchaser headers require the agreement's own id")
    return build_user_headers(purchase_agreement_id, ROLE_PURCHASER)


def unbound_role_headers(role: str, user_id: str) -> Headers:
    """Headers for a role/identity pair used only in pre-entity denial probes.

    Some authorization checks are decided before any entity is consulted, so
    the test needs a role header with an identity that is not tied to a row.
    """
    return build_user_headers(user_id, role)


def headers_without_auth() -> Headers:
    """A request that omits both auth headers entirely."""
    return {"Content-Type": "application/json"}


ROLE_HEADERS = {
    ROLE_CONVERTER_SPONSOR: sponsor_headers,
    ROLE_LICENSED_ENGINEER: engineer_headers,
    ROLE_PEER_REVIEW_ENGINEER: peer_headers,
    ROLE_STATE_REGULATOR: regulator_headers,
    ROLE_ESCROW_AGENT: escrow_headers,
    ROLE_LENDER_UNDERWRITER: lender_headers,
    ROLE_PLATFORM_ADMIN: admin_headers,
    ROLE_TENANT_OCCUPANT: tenant_headers,
    ROLE_PURCHASER: purchaser_headers,
}
