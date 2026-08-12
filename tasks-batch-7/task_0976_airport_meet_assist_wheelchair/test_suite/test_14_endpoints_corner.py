"""Corner queue B — endpoints section instances."""
import pytest

from test_helpers import (
    get_success_data, validate_paginated,
    create_airport, create_terminal, create_segment,
    api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]


class TestListTerminals:
    def test_list_terminals_under_airport_returns_array(self, api):
        """PRD §2.2: "The `response_type` is either \"object\" for a single
        resource or \"array\" for a list of resources."
        PRD §4: GET /maa/airports/{id}/terminals lists terminals.

        Design: Corner/endpoints/list_terminals_under_airport_returns_array
        """
        airport = create_airport(iata_code="MCI", meet_buffer_minutes=15)
        create_terminal(airport["id"], code="B", requires_secure_escort=False)
        create_terminal(airport["id"], code="C", requires_secure_escort=True)
        resp = api_client.list_terminals(airport["id"], DISP)
        data, meta = validate_paginated(resp)
        assert len(data) == 2


class TestListSegmentsFilteredByTerminal:
    def test_list_segments_filtered_by_terminal(self, api):
        """PRD §4: GET /maa/airports/{id}/segments is "filterable by `direction`,
        `status`, `terminal_id`".

        Design: Corner/endpoints/list_segments_filtered_by_terminal
        """
        airport = create_airport(iata_code="OMA", meet_buffer_minutes=15)
        t1 = create_terminal(airport["id"], code="N", requires_secure_escort=False)
        t2 = create_terminal(airport["id"], code="S", requires_secure_escort=False)
        create_segment(airport["id"], t1["id"], flight_no="E1",
                       scheduled_utc="2026-06-16T10:00:00Z")
        create_segment(airport["id"], t1["id"], flight_no="E2",
                       scheduled_utc="2026-06-16T11:00:00Z")
        create_segment(airport["id"], t2["id"], flight_no="E3",
                       scheduled_utc="2026-06-16T12:00:00Z")
        resp = api_client.list_segments(
            airport["id"], DISP, params={"terminal_id": t1["id"]},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        for row in data:
            assert row["terminal_id"] == t1["id"]
