"""Identity headers for the four declared roles.

Every request must carry `X-User-ID` and `X-User-Role`.

When `X-User-Role` is `OwnerAgent`, `X-User-ID` is the `id` of the acting `Owner`, so an
owner-agent header must always be built from a real created owner's identifier with
`make_owner_agent_headers(owner["id"])`. `TEST_USERS["owner_agent_headers"]` is a
placeholder identity that owns nothing and is only useful for probes that expect an
ownership refusal.

For `ContractAdministrator`, `HudFieldOffice` and `PhaAdministrator` the `X-User-ID` is an
opaque operator identifier never compared to any entity's `id`, so the shared constants
below are the correct thing to use for those roles.
"""
from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identifiers.
CONTRACT_ADMIN_USER_ID = "ca-reviewer-1"
CONTRACT_ADMIN_APPROVER_USER_ID = "ca-approver-1"
CONTRACT_ADMIN_SECOND_APPROVER_USER_ID = "ca-approver-2"
CONTRACT_ADMIN_READER_USER_ID = "ca-reader-1"
HUD_FIELD_OFFICE_USER_ID = "hud-fo-1"
HUD_FIELD_OFFICE_SECOND_USER_ID = "hud-fo-7"
HUD_FIELD_OFFICE_THIRD_USER_ID = "hud-field-1"
PHA_ADMIN_USER_ID = "pha-1"

PLACEHOLDER_OWNER_USER_ID = "00000000-0000-0000-0000-0000000000ff"


def make_owner_agent_headers(owner_id: str) -> dict[str, str]:
    """Headers for an `OwnerAgent` acting as the `Owner` whose `id` is `owner_id`."""
    return build_user_headers(owner_id, UserRole.OWNER_AGENT.value)


def make_contract_administrator_headers(user_id: str) -> dict[str, str]:
    """Headers for a `ContractAdministrator` operator."""
    return build_user_headers(user_id, UserRole.CONTRACT_ADMINISTRATOR.value)


def make_hud_field_office_headers(user_id: str) -> dict[str, str]:
    """Headers for a `HudFieldOffice` operator."""
    return build_user_headers(user_id, UserRole.HUD_FIELD_OFFICE.value)


def make_pha_administrator_headers(user_id: str) -> dict[str, str]:
    """Headers for a `PhaAdministrator` operator."""
    return build_user_headers(user_id, UserRole.PHA_ADMINISTRATOR.value)


def make_raw_headers(user_id: str | None, role: str | None) -> dict[str, str]:
    """Build headers with arbitrary or omitted values, for authentication probes."""
    headers: dict[str, str] = {}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers


TEST_USERS: dict[str, object] = {
    "owner_agent_headers": make_owner_agent_headers(PLACEHOLDER_OWNER_USER_ID),
    "contract_administrator_headers": make_contract_administrator_headers(
        CONTRACT_ADMIN_USER_ID
    ),
    "contract_administrator_approver_headers": make_contract_administrator_headers(
        CONTRACT_ADMIN_APPROVER_USER_ID
    ),
    "contract_administrator_second_approver_headers": make_contract_administrator_headers(
        CONTRACT_ADMIN_SECOND_APPROVER_USER_ID
    ),
    "contract_administrator_reader_headers": make_contract_administrator_headers(
        CONTRACT_ADMIN_READER_USER_ID
    ),
    "hud_field_office_headers": make_hud_field_office_headers(HUD_FIELD_OFFICE_USER_ID),
    "hud_field_office_second_headers": make_hud_field_office_headers(
        HUD_FIELD_OFFICE_SECOND_USER_ID
    ),
    "hud_field_office_third_headers": make_hud_field_office_headers(
        HUD_FIELD_OFFICE_THIRD_USER_ID
    ),
    "pha_administrator_headers": make_pha_administrator_headers(PHA_ADMIN_USER_ID),
    # Raw identifiers, for tests that need to assert an audit field records them.
    "contract_administrator_user_id": CONTRACT_ADMIN_USER_ID,
    "contract_administrator_approver_user_id": CONTRACT_ADMIN_APPROVER_USER_ID,
    "contract_administrator_second_approver_user_id": CONTRACT_ADMIN_SECOND_APPROVER_USER_ID,
    "contract_administrator_reader_user_id": CONTRACT_ADMIN_READER_USER_ID,
    "hud_field_office_user_id": HUD_FIELD_OFFICE_USER_ID,
    "hud_field_office_second_user_id": HUD_FIELD_OFFICE_SECOND_USER_ID,
    "hud_field_office_third_user_id": HUD_FIELD_OFFICE_THIRD_USER_ID,
    "pha_administrator_user_id": PHA_ADMIN_USER_ID,
}
