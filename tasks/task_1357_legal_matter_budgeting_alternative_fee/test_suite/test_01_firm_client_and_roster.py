"""Firm creation, timekeeper roster, client intake, list envelope, auth."""
import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_client,
    add_matter,
    add_timekeeper,
    api_client,
    assert_client,
    assert_firm,
    assert_timekeeper,
    create_client_payload,
    create_firm_payload,
    create_timekeeper_payload,
    setup_firm,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFirmCreation:

    def test_firm_creation_populates_fiscal_counters(self):
        """PRD section 3.1: "A `FirmAdmin` creates it with a display `name`
        and the `fiscal_year_start_month` that anchors its fiscal calendar;
        the new firm starts life with `current_period_index` at 0 and
        `closed_through_period_index` at -1, meaning no period has yet been
        closed."

        Design: Corner/entities/firm_creation_required_fields
        """
        resp = api_client.create_firm(
            create_firm_payload(name="Acme Law", fiscal_year_start_month=7),
            ADMIN)
        firm = validate_success(resp, 201)
        assert_firm(firm)
        assert firm["name"] == "Acme Law"
        assert firm["fiscal_year_start_month"] == 7
        assert firm["current_period_index"] == 0, (
            f"new firm must start at period 0, got "
            f"{firm['current_period_index']}")
        assert firm["closed_through_period_index"] == -1, (
            f"new firm must have no closed period, got "
            f"{firm['closed_through_period_index']}")

    def test_firm_creation_missing_fiscal_month_rejected(self):
        """PRD section 3.1: "A `FirmAdmin` creates it with a display `name`
        and the `fiscal_year_start_month` that anchors its fiscal calendar".
        Omitting one of those required inputs is a malformed request, and the
        only 400-series input error identifier the API defines is
        `ERR_INVALID_REQUEST` (PRD section 5).

        Design: Corner/entities/firm_creation_missing_required_returns_invalid_request
        """
        resp = api_client.create_firm({"name": "NoMonth"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRosterAndClients:

    def test_timekeeper_created_active(self):
        """PRD section 3.1: "New timekeepers arrive in `ACTIVE` status;
        `INACTIVE` is the roster's other status value."

        Design: Corner/entities/timekeeper_default_status_active
        """
        firm = setup_firm()
        resp = api_client.create_timekeeper(
            firm["id"],
            create_timekeeper_payload(full_name="Alice", bar_number="B100",
                                      role_title="ASSOCIATE",
                                      standard_rate_cents=30000),
            ADMIN)
        tk = validate_success(resp, 201)
        assert_timekeeper(tk)
        assert tk["status"] == "ACTIVE", (
            f"new timekeeper must be ACTIVE, got {tk['status']}")

    def test_client_accrual_reporting_defaults_false(self):
        """PRD section 3.1: "Two optional flags govern the client's accrual
        obligations: `accrual_reporting_required`, defaulting to false,
        records whether the client mandates periodic accrual reports, and
        `accrual_reporting_cadence_periods`, defaulting to 1, records every
        how many fiscal periods a report must reach the client — a value of
        1 means every period, that is, monthly."

        Design: Corner/entities/client_default_accrual_not_required
        """
        firm = setup_firm()
        resp = api_client.create_client(
            firm["id"],
            create_client_payload(display_name="C1", client_number="C1"),
            ADMIN)
        client = validate_success(resp, 201)
        assert_client(client)
        assert client["accrual_reporting_required"] is False, (
            "accrual_reporting_required must default to false when omitted")

    def test_list_timekeepers_pagination_envelope(self):
        """PRD section 2.3: "Paginated list responses carry `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope."
        PRD section 2.3: "`limit` specifies the maximum number of items to
        return; it defaults to 10, with a minimum of 1 and a maximum of
        100."

        Design: Corner/entities/list_endpoint_pagination_envelope
        """
        firm = setup_firm()
        add_timekeeper(firm["id"], full_name="P1", bar_number="B001")
        add_timekeeper(firm["id"], full_name="P2", bar_number="B002")

        resp = api_client.list_timekeepers(
            ADMIN, params={"firm_id": firm["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, (
            f"limit=1 must return at most one item, got {len(data)}")
        assert meta["limit"] == 1

    def test_get_matter_not_found_returns_404(self):
        """PRD section 2.11: "Requests that address nested resources are
        validated left to right along the path: the system confirms the firm
        first, then each successive identifier, and rejects the request with
        `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
        exist within the enclosing scope, without examining later
        identifiers."

        Design: Corner/entities/entity_not_found_returns_404
        """
        setup_firm()
        resp = api_client.get_matter(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_client_close_blocked_with_open_matter(self):
        """PRD section 3.1: "Closing is permitted only once every matter
        belonging to the client has reached `CLOSED`; otherwise the request
        is rejected with `ERR_CLIENT_HAS_OPEN_MATTERS`."

        Design: Corner/state_machines/client_close_blocked_by_open_matters
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        add_matter(firm["id"], client["id"], tk["id"])

        resp = api_client.close_client(firm["id"], client["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLIENT_HAS_OPEN_MATTERS)


class TestUserContextGuards:

    def test_timekeeper_cannot_advance_period(self):
        """PRD section 2.1: "A request whose role is not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."
        PRD section 4: "| POST | `/firms/{firmId}/advance_period` | Advance
        fiscal period; triggers auto-transitions, snapshot updates, collar
        true-up scheduling | FirmAdmin |"

        Design: Corner/validations/wrong_role_returns_forbidden
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        resp = api_client.advance_period(
            firm["id"],
            {"X-User-ID": tk["id"], "X-User-Role": "Timekeeper",
             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_missing_user_context_headers_rejected(self):
        """PRD section 2.1: "A request missing either header, or presenting
        a malformed value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_invalid
        """
        firm = setup_firm()
        resp = api_client.get_firm(
            firm["id"], {"Content-Type": "application/json"})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
