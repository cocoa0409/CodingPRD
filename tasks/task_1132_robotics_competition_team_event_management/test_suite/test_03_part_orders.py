"""Part-order branching, terminal lockdown, stop-build deadline, and the
default logical clock (PRD §3.3, §2.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_to_build_season,
    create_part_order_payload,
    make_team_lead_headers,
    set_clock,
    setup_confirmed_teams,
    validate_error,
    validate_success,
    api_client,
)

RO = TEST_USERS["registration_officer_headers"]
PO = TEST_USERS["procurement_officer_headers"]


def _submitted_order(ctx, **order_overrides):
    """BUILD_SEASON event + one CONFIRMED team + one SUBMITTED PartOrder."""
    event_id = ctx["event"]["id"]
    entry = ctx["teams"][0]
    team_id = entry["team"]["id"]
    lead = make_team_lead_headers(entry["mentor"]["id"])
    order = validate_success(
        api_client.create_part_order(
            event_id, team_id, create_part_order_payload(**order_overrides), lead,
        ),
        expected_status=201,
    )
    assert order["status"] == "DRAFT"
    assert order["order_total_cents"] == order["quantity"] * order["unit_cost_cents"]
    order = validate_success(api_client.submit_part_order(event_id, team_id, order["id"], lead))
    assert order["status"] == "SUBMITTED"
    return order, team_id, lead


class TestPartOrderBranching:
    def test_rejected_is_terminal(self):
        """PRD §3.3: "Rejection moves `SUBMITTED → REJECTED` with no additional
        preconditions." and "`RECEIVED`, `REJECTED`, and `CANCELLED` are
        terminal; mutating an order already in a terminal state is rejected
        with `ERR_ALREADY_TERMINAL`."

        Design: Difficulty/non_linear_state_machine/part_order_branching_with_revert_and_reject
        """
        ctx = setup_confirmed_teams(num_teams=2)
        advance_to_build_season(ctx, stop_build_at="2026-06-01T00:00:00Z")
        order, team_id, lead = _submitted_order(ctx)
        rejected = validate_success(
            api_client.reject_part_order(ctx["event"]["id"], team_id, order["id"], PO)
        )
        assert rejected["status"] == "REJECTED"
        resp = api_client.approve_part_order(ctx["event"]["id"], team_id, order["id"], PO)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_cancelled_from_submitted_is_terminal(self):
        """PRD §3.3: "Cancellation is permitted from `DRAFT` and from
        `SUBMITTED`, both landing in `CANCELLED`." and "mutating an order
        already in a terminal state is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Difficulty/non_linear_state_machine/part_order_branching_with_revert_and_reject
        """
        ctx = setup_confirmed_teams(num_teams=2)
        advance_to_build_season(ctx, stop_build_at="2026-06-01T00:00:00Z")
        order, team_id, lead = _submitted_order(ctx)
        cancelled = validate_success(
            api_client.cancel_part_order(ctx["event"]["id"], team_id, order["id"], lead)
        )
        assert cancelled["status"] == "CANCELLED"
        resp = api_client.submit_part_order(ctx["event"]["id"], team_id, order["id"], lead)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestStopBuildDeadline:
    def test_submit_after_stop_build_rejected(self):
        """PRD §3.3: "the current logical clock must be at or before the
        `scheduled_at` of the `STOP_BUILD` milestone (otherwise
        `ERR_STOP_BUILD_PASSED`, HTTP 422)".

        Design: Corner/validations/part_order_submit_after_stop_build_returns_error
        """
        ctx = setup_confirmed_teams(num_teams=2)
        advance_to_build_season(ctx, stop_build_at="2026-06-01T00:00:00Z")
        set_clock("2026-06-02T00:00:00Z")  # one day past the deadline
        event_id = ctx["event"]["id"]
        entry = ctx["teams"][0]
        team_id = entry["team"]["id"]
        lead = make_team_lead_headers(entry["mentor"]["id"])
        order = validate_success(
            api_client.create_part_order(event_id, team_id, create_part_order_payload(), lead),
            expected_status=201,
        )
        resp = api_client.submit_part_order(event_id, team_id, order["id"], lead)
        validate_error(resp, ApiErrorId.ERR_STOP_BUILD_PASSED)

    def test_default_clock_permits_submit_at_exact_stop_build(self):
        """PRD §2.9: "The clock defaults to `2026-05-01T00:00:00Z` if it has
        never been set." PRD §3.3: submission is permitted when the clock is
        "at or before the `scheduled_at` of the `STOP_BUILD` milestone" — so
        with STOP_BUILD scheduled exactly at the stated default instant and no
        clock call ever made, submission must succeed.

        Design: Corner/endpoints/clock_default_is_2026_05_01
        """
        ctx = setup_confirmed_teams(num_teams=2)
        advance_to_build_season(ctx, stop_build_at="2026-05-01T00:00:00Z")
        event_id = ctx["event"]["id"]
        entry = ctx["teams"][0]
        team_id = entry["team"]["id"]
        lead = make_team_lead_headers(entry["mentor"]["id"])
        order = validate_success(
            api_client.create_part_order(event_id, team_id, create_part_order_payload(), lead),
            expected_status=201,
        )
        submitted = validate_success(
            api_client.submit_part_order(event_id, team_id, order["id"], lead)
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] is not None


class TestPartOrderRbac:
    def test_teamlead_cannot_approve_part_order(self):
        """PRD §2.1: "the server checks that the named role is on the
        endpoint's permitted-role list; if not, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4: part-order approve is
        authorized for `ProcurementOfficer` only.

        Design: Corner/rbac/teamlead_cannot_approve_own_part_order
        """
        ctx = setup_confirmed_teams(num_teams=2)
        advance_to_build_season(ctx, stop_build_at="2026-06-01T00:00:00Z")
        order, team_id, lead = _submitted_order(ctx)
        resp = api_client.approve_part_order(ctx["event"]["id"], team_id, order["id"], lead)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
