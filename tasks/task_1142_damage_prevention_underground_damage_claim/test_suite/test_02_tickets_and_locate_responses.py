"""Locate ticket windows, renewal, expiry sweep, and locate responses (PRD §3.2, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_locate_ticket,
    create_excavator,
    create_locator,
    create_locate_response_payload,
    create_locate_ticket_payload,
    create_ticket,
    get_success_data,
    make_excavator_headers,
    make_locator_headers,
    make_manager_headers,
    set_clock,
    validate_error,
    validate_success,
)


class TestTicketCreation:
    def test_locate_ticket_initial_state_open(self, api):
        """PRD §3.2: "A successful create initializes `status` to `OPEN`, `renewal_count`
        to 0, and mints a `ticket_number`."

        Design: Corner/state_machines/locate_ticket_initial_state_open
        """
        excavator = create_excavator()
        payload = create_locate_ticket_payload(
            excavator_id=excavator["id"], dig_site_address="8 Eighth St",
            work_start_at="2026-06-01T08:00:00Z", work_end_at="2026-06-01T17:00:00Z",
        )
        resp = api.create_locate_ticket(payload, make_excavator_headers(excavator["id"]))
        data = validate_success(resp, expected_status=201)
        assert_locate_ticket(data)
        assert data["status"] == "OPEN"
        assert data["renewal_count"] == 0
        assert len(data["ticket_number"]) > 0

    def test_ticket_window_invalid_rejected(self, api):
        """PRD §3.2: "`work_end_at` must be strictly after `work_start_at` (otherwise
        `ERR_TICKET_WINDOW_INVALID`, HTTP 422)."

        Design: Corner/errors/ticket_window_invalid_rejected
        """
        excavator = create_excavator()
        payload = create_locate_ticket_payload(
            excavator_id=excavator["id"], dig_site_address="30 Omicron St",
            work_start_at="2026-06-01T08:00:00Z", work_end_at="2026-06-01T08:00:00Z",
        )
        resp = api.create_locate_ticket(payload, make_excavator_headers(excavator["id"]))
        validate_error(resp, ApiErrorId.ERR_TICKET_WINDOW_INVALID, expected_status=422)


class TestTicketWindowOverlap:
    def test_ticket_windows_adjacent_touching_allowed(self, api):
        """PRD §3.2: "an overlapping window is rejected with `ERR_TICKET_WINDOW_CONFLICT`
        (HTTP 409), while two windows that merely touch at a boundary are permitted."
        The dig window is the half-open interval `[work_start_at, work_end_at)`, so a
        ticket starting exactly at the prior ticket's end does not overlap.

        Design: Difficulty/resource_temporal_overlap/ticket_windows_half_open_adjacency_allowed
        """
        excavator = create_excavator()
        headers = make_excavator_headers(excavator["id"])
        ticket_a = create_ticket(
            excavator["id"], "5 Oak Ave", "2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z",
        )
        assert ticket_a["status"] == "OPEN"
        payload_b = create_locate_ticket_payload(
            excavator_id=excavator["id"], dig_site_address="5 Oak Ave",
            work_start_at="2026-06-01T12:00:00Z", work_end_at="2026-06-01T14:00:00Z",
        )
        resp_b = api.create_locate_ticket(payload_b, headers)
        ticket_b = validate_success(resp_b, expected_status=201)
        assert ticket_b["status"] == "OPEN", "boundary-touching ticket must be permitted"

    def test_ticket_windows_straddling_conflict(self, api):
        """PRD §3.2: "Two `OPEN` tickets for the same `(excavator_id, dig_site_address)`
        pair must not overlap; an overlapping window is rejected with
        `ERR_TICKET_WINDOW_CONFLICT` (HTTP 409)"

        Design: Difficulty/resource_temporal_overlap/ticket_windows_half_open_adjacency_allowed
        """
        excavator = create_excavator()
        headers = make_excavator_headers(excavator["id"])
        create_ticket(excavator["id"], "5 Oak Ave", "2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z")
        payload_c = create_locate_ticket_payload(
            excavator_id=excavator["id"], dig_site_address="5 Oak Ave",
            work_start_at="2026-06-01T11:00:00Z", work_end_at="2026-06-01T13:00:00Z",
        )
        resp_c = api.create_locate_ticket(payload_c, headers)
        validate_error(resp_c, ApiErrorId.ERR_TICKET_WINDOW_CONFLICT, expected_status=409)


class TestTicketExpiryAndRenewal:
    def test_renew_expired_ticket_rejected(self, api):
        """PRD §3.2: "Renewing a ticket that has already moved out of `OPEN` is rejected
        with `ERR_INVALID_STATE` (HTTP 409)." The clock sweep moves an `OPEN` ticket
        whose `work_end_at` has passed to `EXPIRED` (PRD §2.5).

        Design: Corner/state_machines/renew_expired_ticket_rejected
        """
        excavator = create_excavator()
        ticket = create_ticket(
            excavator["id"], "6 Sixth St", "2026-05-01T08:00:00Z", "2026-05-01T17:00:00Z",
        )
        set_clock("2026-05-02T00:00:00Z")
        resp = api.renew_locate_ticket(
            ticket["id"], {"new_work_end_at": "2026-05-03T17:00:00Z"},
            make_excavator_headers(excavator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        ticket_after = get_success_data(api.get_locate_ticket(ticket["id"], make_manager_headers()))
        assert ticket_after["status"] == "EXPIRED"


class TestLocateResponses:
    def test_response_on_expired_ticket_rejected(self, api):
        """PRD §3.2: "Submitting against a ticket whose `status` is `EXPIRED` is rejected
        with `ERR_TICKET_EXPIRED` (HTTP 409)"

        Design: Corner/errors/response_on_expired_ticket_rejected
        """
        excavator = create_excavator()
        locator = create_locator()
        ticket = create_ticket(
            excavator["id"], "31 Pi St", "2026-05-01T08:00:00Z", "2026-05-01T17:00:00Z",
        )
        set_clock("2026-05-02T00:00:00Z")
        payload = create_locate_response_payload(
            locate_ticket_id=ticket["id"], locator_id=locator["id"],
            response_code="MARKED", marks_completed_at="2026-05-01T07:00:00Z",
        )
        resp = api.create_locate_response(payload, make_locator_headers(locator["id"]))
        validate_error(resp, ApiErrorId.ERR_TICKET_EXPIRED, expected_status=409)
        ticket_after = get_success_data(api.get_locate_ticket(ticket["id"], make_manager_headers()))
        assert ticket_after["status"] == "EXPIRED"

    def test_suspended_locator_response_rejected(self, api):
        """PRD §3.1: "a suspended locator cannot submit marking responses (the submission
        is rejected with `ERR_LOCATOR_INACTIVE`, HTTP 409)."

        Design: Corner/errors/suspended_locator_response_rejected
        """
        excavator = create_excavator()
        locator = create_locator()
        get_success_data(api.suspend_locator(locator["id"], make_manager_headers()))
        ticket = create_ticket(
            excavator["id"], "33 Sigma St", "2026-06-01T08:00:00Z", "2026-06-01T17:00:00Z",
        )
        payload = create_locate_response_payload(
            locate_ticket_id=ticket["id"], locator_id=locator["id"],
            response_code="MARKED", marks_completed_at="2026-06-01T07:00:00Z",
        )
        resp = api.create_locate_response(payload, make_locator_headers(locator["id"]))
        validate_error(resp, ApiErrorId.ERR_LOCATOR_INACTIVE, expected_status=409)
        ticket_after = get_success_data(api.get_locate_ticket(ticket["id"], make_manager_headers()))
        assert ticket_after["status"] == "OPEN"
