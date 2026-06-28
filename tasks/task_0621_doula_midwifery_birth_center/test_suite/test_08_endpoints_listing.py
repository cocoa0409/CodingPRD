"""Filtered listing and conditional-action endpoints (queue B: Corner / endpoints).
"""
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, fixtures,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["center_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


# ---- list_episodes_filtered_by_client ----
def test_list_episodes_filtered_by_client(api):
    """PRD §2.3: "The meta object of a list response carries the pagination fields limit,
    offset, total_count, and has_more."
    PRD §4: endpoint "GET | /birth-center/episodes | List episodes" filterable by
    client_id (Section 4 routing table).

    Design: Corner/endpoints/list_episodes_filtered_by_client
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    client_id = ctx["client"]["id"]

    resp = api.list_episodes(INTAKE, params={"client_id": client_id})
    data, meta = validate_paginated(resp)
    ids = [e["id"] for e in data]
    assert ep_id in ids, "filtered list contains the client's episode"
    assert all(e["client_id"] == client_id for e in data), "only that client's episodes"
    assert "total_count" in meta and "has_more" in meta


# ---- room_close_blocks_confirm ----
def test_room_close_blocks_confirm(api):
    """PRD §3.5: "A CenterAdmin confirms a held booking, moving status from HELD to
    CONFIRMED, which requires the room's status to be OPEN."

    Design: Corner/endpoints/room_close_blocks_confirm
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    room = fixtures.create_room(turnover_minutes=0)
    booking = fixtures.create_booking(ep_id, room["id"], room["version"])
    validate_success(api.close_room(room["id"], ADMIN))

    resp = api.confirm_booking(booking["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
