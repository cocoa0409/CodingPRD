"""Role headers for every role the PRD defines (PRD §2.1).

Every request carries `X-User-ID` and the role header. `StoreOperator`,
`ChannelPartner` and `CourierNetworkAgent` act on behalf of a specific persisted
entity, so their headers must be built per instance with the acting entity's
`id`: the PRD states that when an entity-backed role omits its scope header the
server falls back to interpreting `X-User-ID` as the acting entity's `id`, and
these builders therefore set both the scope header and `X-User-ID` to that id.

`PlatformAdmin` and `SettlementAnalyst` are not entity-backed, so their shared
constants below are the canonical form. The two analyst identities exist because
segregation of duties compares recorded identities, not roles.
"""
from prd_bench_local_runner.testing import build_user_headers

ADMIN_USER_ID = "admin-1"
ANALYST_ONE_USER_ID = "analyst-1"
ANALYST_TWO_USER_ID = "analyst-2"

TEST_USERS = {
    # Not entity-backed — the shared constant is the canonical form.
    "admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "analyst_headers": build_user_headers(ANALYST_ONE_USER_ID, "SettlementAnalyst"),
    "second_analyst_headers": build_user_headers(ANALYST_TWO_USER_ID, "SettlementAnalyst"),
    # Entity-backed — these fallbacks are for tests that do not exercise
    # ownership (missing-body-field, unknown-identifier, role-rejection tests).
    "store_operator_headers": build_user_headers("store-operator-1", "StoreOperator"),
    "channel_partner_headers": build_user_headers("channel-partner-1", "ChannelPartner"),
    "courier_agent_headers": build_user_headers("courier-agent-1", "CourierNetworkAgent"),
}


def make_store_operator_headers(store_id: str) -> dict:
    """Headers for the operator of the given `Store`."""
    headers = build_user_headers(store_id, "StoreOperator")
    headers["X-Store-ID"] = store_id
    return headers


def make_channel_partner_headers(channel_id: str) -> dict:
    """Headers for the partner of the given `Channel`."""
    headers = build_user_headers(channel_id, "ChannelPartner")
    headers["X-Channel-ID"] = channel_id
    return headers


def make_courier_agent_headers(courier_network_id: str) -> dict:
    """Headers for the agent of the given `CourierNetwork`."""
    headers = build_user_headers(courier_network_id, "CourierNetworkAgent")
    headers["X-Courier-Network-ID"] = courier_network_id
    return headers


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    """Headers for a platform administrator with an explicit operator identity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_analyst_headers(user_id: str = ANALYST_ONE_USER_ID) -> dict:
    """Headers for a settlement analyst with an explicit operator identity."""
    return build_user_headers(user_id, "SettlementAnalyst")


def make_raw_role_headers(user_id: str, role: str) -> dict:
    """Headers carrying an arbitrary role string, including unrecognized ones."""
    return build_user_headers(user_id, role)


def make_headers_without_role(user_id: str) -> dict:
    """Headers that omit the role header entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_without_user_id(role: str) -> dict:
    """Headers that omit `X-User-ID` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
