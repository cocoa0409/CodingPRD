"""Gates that live entirely in a second entity's state."""

from test_helpers import (
    ADMIN_HEADERS,
    EPA_HEADERS,
    ERR_ASSESSMENT_NOT_APPROVED,
    ERR_METHOD_NOT_DESIGNATED,
    PM_HEADERS,
    base_environment,
    canonical_environment,
    create_monitor,
    create_operating_site,
    create_reference_method,
    get_success_data,
    set_clock,
    submitted_change_request,
    validate_error,
    validate_success,
)


def _monitor_bound_to_a_not_yet_effective_method(api):
    env = base_environment(api)
    future_method = create_reference_method(
        api,
        env.pollutant_id,
        method_code="RFPS-0119-002",
        designation_type="FEM",
        effective_from="2027-01-01T00:00:00Z",
    )
    site = create_operating_site(api, env.network_id)
    env.site_id = site["id"]
    monitor = create_monitor(
        api, env.site_id, future_method["id"], installed_at="2026-01-04T00:00:00Z"
    )
    env.monitor_id = monitor["id"]
    env.future_method_id = future_method["id"]
    return env


def test_approval_is_refused_while_the_designation_is_still_in_the_future(api):
    """A method whose effective_from has not arrived cannot carry an approval.

    PRD 3.1: "Three operations consult the governing method's standing and demand that all
    three of the following hold: `designation_status` is either `DESIGNATED` or
    `CONDITIONAL`; `effective_from` is at or before the logical clock; and `withdrawn_on` is
    either null or strictly after the logical clock."

    Design: Difficulty/cross_entity_state_dependency/monitor_approval_requires_effective_method_designation
    """
    env = _monitor_bound_to_a_not_yet_effective_method(api)

    response = api.approve_monitor(
        env.monitor_id,
        {"approval_note": "Attempted before the designation takes effect"},
        EPA_HEADERS,
    )
    validate_error(response, ERR_METHOD_NOT_DESIGNATED, 422)
    assert env.read_monitor()["monitor_status"] == "PENDING_APPROVAL"


def test_the_same_approval_succeeds_once_the_clock_passes_effective_from(api):
    """No field on the instrument changed; only the clock moved past the designation.

    PRD 3.3: "Regional instrument approval advances `PENDING_APPROVAL → APPROVED` and
    confirms that the instrument implements a currently designated method."

    Design: Difficulty/cross_entity_state_dependency/monitor_approval_requires_effective_method_designation
    """
    env = _monitor_bound_to_a_not_yet_effective_method(api)
    api.approve_monitor(env.monitor_id, {}, EPA_HEADERS)

    set_clock(api, "2027-01-05T00:00:00Z")
    approved = validate_success(
        api.approve_monitor(
            env.monitor_id, {"approval_note": "Designation now effective"}, EPA_HEADERS
        )
    )
    assert approved["monitor_status"] == "APPROVED"

    method = get_success_data(api.get_reference_method(env.future_method_id, ADMIN_HEADERS))
    assert method["designation_status"] == "DESIGNATED"
    assert method["designation_change_count"] == 0


def _shutdown_request_over_an_unapproved_assessment(api):
    env = canonical_environment(api)
    assessment = get_success_data(
        api.create_assessment({"network_id": env.network_id, "cycle_year": 2026}, PM_HEADERS)
    )
    env.assessment_id = assessment["id"]
    get_success_data(api.submit_assessment(assessment["id"], {}, PM_HEADERS))
    submitted_change_request(env, "SHUTDOWN")
    return env


def test_approval_is_refused_while_the_cited_assessment_is_only_submitted(api):
    """A submitted-but-undecided assessment does not authorise a network change.

    PRD 3.9: "Then the referential gates, in priority order: the cited assessment must
    exist, have `status` `APPROVED` and belong to the same network as the target site, or
    the answer is `ERR_ASSESSMENT_NOT_APPROVED` (HTTP 422)"

    Design: Difficulty/cross_entity_state_dependency/site_change_request_approval_requires_approved_assessment
    """
    env = _shutdown_request_over_an_unapproved_assessment(api)

    response = api.decide_change_request(
        env.change_request_id,
        {"decision": "APPROVE", "decision_note": "Premature approval attempt"},
        EPA_HEADERS,
    )
    validate_error(response, ERR_ASSESSMENT_NOT_APPROVED, 422)

    request = get_success_data(api.get_change_request(env.change_request_id, PM_HEADERS))
    assert request["status"] == "SUBMITTED"
    assert env.read_site()["status"] == "OPERATING"
    assert env.read_monitor()["monitor_status"] == "OPERATING"


def test_approving_the_assessment_unlocks_the_identical_change_decision(api):
    """Only the second entity moved, and the same decision now fires its cascade.

    PRD 3.9: "`APPROVE` advances `SUBMITTED → APPROVED`, stamps `approved_at` from the
    logical clock and `approved_by_user_id` from the calling `X-User-ID`, and — critically
    — makes every change request citing this assessment eligible for approval."

    Design: Difficulty/cross_entity_state_dependency/site_change_request_approval_requires_approved_assessment
    """
    env = _shutdown_request_over_an_unapproved_assessment(api)
    api.decide_change_request(env.change_request_id, {"decision": "APPROVE"}, EPA_HEADERS)

    assessment = validate_success(
        api.decide_assessment(
            env.assessment_id,
            {"decision": "APPROVE", "decision_note": "Census and scoring accepted"},
            EPA_HEADERS,
        )
    )
    assert assessment["status"] == "APPROVED"
    assert env.read_network()["network_status"] == "ACTIVE"

    request = validate_success(
        api.decide_change_request(
            env.change_request_id,
            {"decision": "APPROVE", "decision_note": "Shutdown authorised"},
            EPA_HEADERS,
        )
    )
    assert request["status"] == "APPROVED"
    assert env.read_site()["status"] == "SHUTDOWN"
    assert env.read_monitor()["monitor_status"] == "DECOMMISSIONED"
