"""Corner queue B — validations and rbac sections: duplicate/uniqueness errors,
field-range validation, temporal & cross-entity referential errors, role
denials, and segregation of duties.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    fixtures as fx,
    factories as F,
    test_users as U,
    ApiErrorId,
)


# ===========================================================================
# Corner/validations/duplicate_csat_survey_returns_duplicate_survey
# ===========================================================================
def test_second_survey_for_ticket_rejected_duplicate():
    """PRD §3.7: "Once a ticket is resolved, its requester may file exactly one
    satisfaction survey ... A second survey for the same ticket is rejected with
    ERR_DUPLICATE_SURVEY."

    Design: Corner/validations/duplicate_csat_survey_returns_duplicate_survey
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_resolved_ticket(
        default_priority="P3", requester_id="req-c12", agent_id="agent-c12"
    )
    validate_success(
        api_client.create_csat_survey(
            {"ticket_id": ticket["id"], "score": 4}, U.requester("req-c12")
        ),
        expected_status=201,
    )
    resp = api_client.create_csat_survey(
        {"ticket_id": ticket["id"], "score": 5}, U.requester("req-c12")
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SURVEY.value, expected_status=409)


# ===========================================================================
# Corner/validations/csat_score_out_of_range_returns_invalid_field_value
# ===========================================================================
def test_csat_score_out_of_range_rejected():
    """PRD §3.2: "a score outside the integer range 1 through 5 inclusive is
    rejected with ERR_INVALID_FIELD_VALUE."

    Design: Corner/validations/csat_score_out_of_range_returns_invalid_field_value
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_resolved_ticket(
        default_priority="P3", requester_id="req-c13", agent_id="agent-c13"
    )
    resp = api_client.create_csat_survey(
        {"ticket_id": ticket["id"], "score": 6}, U.requester("req-c13")
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_FIELD_VALUE.value, expected_status=422)


# ===========================================================================
# Corner/validations/duplicate_cab_vote_returns_duplicate_vote
# ===========================================================================
def test_same_member_voting_twice_rejected_duplicate():
    """PRD §3.5: "a given voter_user_id may vote at most once per change, with a
    second attempt rejected with ERR_DUPLICATE_VOTE."

    Design: Corner/validations/duplicate_cab_vote_returns_duplicate_vote
    """
    _, _, _, _, change = fx.setup_submitted_change(risk="MEDIUM", default_priority="P2",
                                                   manager_id="cm-c14")
    cr_id = change["id"]
    validate_success(
        api_client.cast_vote(
            cr_id,
            {"decision": "APPROVE", "expected_change_request_version": change["version"]},
            U.cab_member("cab-x"),
        ),
        expected_status=201,
    )
    after = validate_success(api_client.get_change_request(cr_id, U.cab_member("cab-x")))
    resp = api_client.cast_vote(
        cr_id,
        {"decision": "REJECT", "expected_change_request_version": after["version"]},
        U.cab_member("cab-x"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE.value, expected_status=409)


# ===========================================================================
# Corner/validations/reopen_after_window_returns_reopen_window_closed
# ===========================================================================
def test_reopen_past_window_rejected():
    """PRD §3.6: "an attempt past the window is rejected with
    ERR_REOPEN_WINDOW_CLOSED, and one against a ticket not in RESOLVED with
    ERR_INVALID_STATE."

    Design: Corner/validations/reopen_after_window_returns_reopen_window_closed
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_resolved_ticket(
        default_priority="P3", requester_id="req-c16", agent_id="agent-c16"
    )
    fx.advance_clock(1441)  # one minute past the 1440 window
    resp = api_client.reopen_ticket(ticket["id"], U.requester("req-c16"))
    validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_CLOSED.value, expected_status=409)


# ===========================================================================
# Corner/validations/asset_retire_with_open_incident_returns_referential_error
# ===========================================================================
def test_retire_asset_with_open_incident_rejected():
    """PRD §3.8: "a retire attempted while incidents remain open is rejected with
    ERR_ASSET_HAS_OPEN_INCIDENTS."

    Design: Corner/validations/asset_retire_with_open_incident_returns_referential_error
    """
    _, _, category = fx.setup_catalog(default_priority="P3")
    asset = fx.create_asset(asset_tag="AI-1", kind="SERVER")
    fx.open_ticket(category["id"], requester_id="req-c17",
                   ticket_overrides={"asset_id": asset["id"]})

    resp = api_client.retire_asset(asset["id"], U.platform_admin())
    validate_error(resp, ApiErrorId.ERR_ASSET_HAS_OPEN_INCIDENTS.value, expected_status=409)

    after = validate_success(api_client.get_asset(asset["id"], U.platform_admin()))
    assert after["open_incident_count"] == 1


# ===========================================================================
# Corner/rbac/requester_cannot_resolve_ticket_returns_forbidden
# ===========================================================================
def test_requester_resolving_ticket_forbidden():
    """PRD §2.1: "When the headers are present but the named role is not permitted
    to perform the requested operation, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."

    Design: Corner/rbac/requester_cannot_resolve_ticket_returns_forbidden
    """
    _, _, _, ticket = fx.setup_in_progress_ticket(
        default_priority="P3", requester_id="req-c18", agent_id="agent-c18"
    )
    resp = api_client.resolve_ticket(ticket["id"], U.requester("req-c18"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


# ===========================================================================
# Corner/rbac/agent_cannot_create_sla_policy_returns_forbidden
# ===========================================================================
def test_agent_creating_sla_policy_forbidden():
    """PRD §2.1: "A PlatformAdmin configures categories, SLA policies, assignment
    groups, and assets, and operates the test-driving clock."

    Design: Corner/rbac/agent_cannot_create_sla_policy_returns_forbidden
    """
    resp = api_client.create_sla_policy(F.create_sla_policy_payload(name="Sneaky"),
                                        U.agent("agent-c19"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


# ===========================================================================
# Corner/rbac/change_raiser_cannot_vote_on_own_change_returns_sod_violation
# ===========================================================================
def test_change_raiser_voting_on_own_change_sod_violation():
    """PRD §3.5: "the change's own raised_by_user_id may never vote on that change
    — an attempt is rejected with ERR_SOD_VIOLATION."

    Design: Corner/rbac/change_raiser_cannot_vote_on_own_change_returns_sod_violation
    """
    # The raiser 'dual-1' also acts as a CabMember (same opaque X-User-ID).
    _, _, category = fx.setup_catalog(default_priority="P2")
    ticket = fx.open_ticket(category["id"], requester_id="req-c20")
    change = fx.create_and_submit_change(ticket["id"], risk="MEDIUM", manager_id="dual-1")

    resp = api_client.cast_vote(
        change["id"],
        {"decision": "APPROVE", "expected_change_request_version": change["version"]},
        U.cab_member("dual-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value, expected_status=403)
