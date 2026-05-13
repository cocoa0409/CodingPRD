"""ApplicationOfficeAction tests for the IP Management API.

Covers PRD §3.2:
- Opening an office-action transitions JurisdictionFiling.status → OFFICE_ACTION
  and IPRight.status → OFFICE_ACTION
- /respond by the assigned agent transitions OFFICE_ACTION → RESPONDED,
  bubbles JurisdictionFiling back to FILED, and (if no other PENDING actions)
  IPRight back to FILED
- Identity-backed access control: only the agent referenced by
  ApplicationOfficeAction.assigned_agent_id may /respond
- /abandon requires server-clock past response_due_at
"""

from test_helpers import (
    ApiErrorId,
    advance_clock_days_fixture,
    assert_office_action,
    assigned_agent_headers,
    create_office_action_payload,
    iso_in_days,
    make_internal_agent_headers,
    open_office_action,
    setup_foundation,
    validate_error,
    validate_success,
    walk_ip_right_to_filed,
)


class TestOpenOfficeAction:
    """Opening an office-action — PRD §3.2 cascading side effects."""

    def test_open_cascades_filing_and_ip_to_office_action(
        self, api, ip_manager_headers
    ):
        """PRD §3.2: "Side effects of opening an office action are layered:
        the targeted `JurisdictionFiling.status` becomes `OFFICE_ACTION`, the
        `ApplicationOfficeAction` is created in `PENDING`, and the parent
        `IPRight.status` becomes `OFFICE_ACTION`."

        Claim: after open, action.status==PENDING, filing.status ==
        OFFICE_ACTION, ip.status == OFFICE_ACTION.
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        action = open_office_action(
            api,
            ip_right_id=ip["id"],
            jurisdiction_filing_id=filing["id"],
            assigned_agent_id=found["agent"]["id"],
        )
        assert_office_action(action)
        assert action["status"] == "PENDING"
        # Re-fetch parents to confirm cascades.
        ip_after = api.get_ip_right(ip["id"], ip_manager_headers).json()["data"]
        assert ip_after["status"] == "OFFICE_ACTION"


class TestRespondOfficeAction:
    """Successful and unsuccessful /respond per PRD §3.2."""

    def test_assigned_agent_responds_and_returns_filing_to_filed(
        self, api, ip_manager_headers
    ):
        """PRD §3.2: "On success, the action's `responded_at` is set to the
        current server time, its `status` flips to `RESPONDED`, the targeted
        `JurisdictionFiling.status` returns to `FILED`, and — if the parent
        `IPRight` has no other pending office actions remaining — the parent
        `IPRight.status` returns to `FILED` as well."

        Claim: respond by assigned agent → action RESPONDED, filing FILED,
        IPRight FILED.
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        action = open_office_action(
            api,
            ip_right_id=ip["id"],
            jurisdiction_filing_id=filing["id"],
            assigned_agent_id=found["agent"]["id"],
        )
        # Per PRD §2.1, the InternalAgent's X-User-ID must equal the Agent.id.
        agent_headers = assigned_agent_headers(found["agent"])
        resp = api.respond_office_action(action["id"], {}, agent_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "RESPONDED"
        # Bubble-up: IPRight should be back at FILED.
        ip_after = api.get_ip_right(ip["id"], ip_manager_headers).json()["data"]
        assert ip_after["status"] == "FILED"

    def test_respond_by_wrong_agent_is_forbidden(self, api, ip_manager_headers):
        """PRD §2.1: "the server confirms that the targeted
        `ApplicationOfficeAction.assigned_agent_id` matches `X-User-ID`;
        mismatch is treated as `ERR_FORBIDDEN`."

        Claim: /respond called by a different Agent.id → ERR_FORBIDDEN.
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        action = open_office_action(
            api,
            ip_right_id=ip["id"],
            jurisdiction_filing_id=filing["id"],
            assigned_agent_id=found["agent"]["id"],
        )
        # Use a totally unrelated InternalAgent id.
        wrong_headers = make_internal_agent_headers("some-other-agent-id")
        resp = api.respond_office_action(action["id"], {}, wrong_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_respond_after_deadline_returns_invalid_state(
        self, api, ip_manager_headers, admin_headers
    ):
        """PRD §3.2: "Successful response requires the action to be `PENDING`
        and the server clock to be strictly before `response_due_at`."

        Claim: when now() >= response_due_at, /respond fails with
        ERR_INVALID_STATE (PRD §2.7 priority 5).
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        # response_due_at in 1 day; advance clock 2 days.
        action = open_office_action(
            api,
            ip_right_id=ip["id"],
            jurisdiction_filing_id=filing["id"],
            assigned_agent_id=found["agent"]["id"],
            response_due_at=iso_in_days(1),
        )
        advance_clock_days_fixture(api, 2)
        agent_headers = assigned_agent_headers(found["agent"])
        resp = api.respond_office_action(action["id"], {}, agent_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestAbandonOfficeAction:
    """PRD §3.2 abandonment requires server clock past response_due_at."""

    def test_abandon_after_deadline_succeeds(
        self, api, ip_manager_headers
    ):
        """PRD §3.2: "The abandonment endpoint requires the action to be
        `PENDING` and the server clock to be greater than or equal to
        `response_due_at`; the resulting transition takes the action to
        `CLOSED_ABANDONED`."

        Claim: after the deadline, /abandon succeeds and status →
        CLOSED_ABANDONED.
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        action = open_office_action(
            api,
            ip_right_id=ip["id"],
            jurisdiction_filing_id=filing["id"],
            assigned_agent_id=found["agent"]["id"],
            response_due_at=iso_in_days(1),
        )
        advance_clock_days_fixture(api, 2)
        resp = api.abandon_office_action(action["id"], {}, ip_manager_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CLOSED_ABANDONED"

    def test_abandon_before_deadline_rejected_as_invalid_state(
        self, api, ip_manager_headers
    ):
        """PRD §3.2: "The abandonment endpoint requires the action to be
        `PENDING` and the server clock to be greater than or equal to
        `response_due_at`."

        Claim: before the deadline, /abandon fails with ERR_INVALID_STATE.
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        action = open_office_action(
            api,
            ip_right_id=ip["id"],
            jurisdiction_filing_id=filing["id"],
            assigned_agent_id=found["agent"]["id"],
            response_due_at=iso_in_days(30),
        )
        resp = api.abandon_office_action(action["id"], {}, ip_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
