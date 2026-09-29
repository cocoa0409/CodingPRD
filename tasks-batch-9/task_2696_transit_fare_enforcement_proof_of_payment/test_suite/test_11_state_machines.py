"""
Lifecycle behaviour: declared initial states, the guarded forward transitions,
the side effect a contest carries with it, and the refusals that meet an
undeclared transition, a terminal record and a replayed call.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import (
    ERR_INVALID_DEPLOYMENT_STATE,
    ERR_INVALID_ZONE_STATE,
    ERR_SAMPLE_SIZE_INADEQUATE,
    ERR_SIGNAGE_BELOW_THRESHOLD,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_rate_equals,
    assert_versioned_record,
    ids_of,
)
from test_helpers.constants import (
    ADJUDICATION_CONTESTED,
    DECISION_PENDING,
    DEPLOYMENT_STATUS_ACTIVE,
    DEPLOYMENT_STATUS_PLANNED,
    HEARING_STATUS_SCHEDULED,
    OUTCOME_PENDING,
    SETTLEMENT_OUTSTANDING,
    VALIDATION_NO_PROOF,
    ZONE_STATUS_PENDING_SIGNAGE,
    ZONE_STATUS_REVOKED,
)
from test_helpers.fixtures import OBSERVATION_AT, WINDOW_START
from test_helpers.test_users import PLANNER_HEADERS, make_rider_headers

HEARING_AT = "2026-08-19T09:00:00Z"


def test_a_planned_deployment_and_a_new_encounter_open_in_their_declared_states(api):
    """
    A planned deployment opens in `status` `PLANNED` with `achieved_sample_count`
    at 0, `voided_encounter_count` at 0 and `sample_adequacy_ratio` at 0.0.  A
    new encounter opens with `outcome` `PENDING`.

    Design: Corner/state_machines/deployment_and_encounter_start_in_their_declared_initial_states
    """
    env = fixtures.build_environment(api)

    deployment = fixtures.plan_deployment(api, env["line"]["id"], env["zone"]["id"])
    assert deployment["status"] == DEPLOYMENT_STATUS_PLANNED
    assert deployment["achieved_sample_count"] == 0
    assert deployment["voided_encounter_count"] == 0
    assert_rate_equals(
        deployment["sample_adequacy_ratio"], 0.0000, "deployment.sample_adequacy_ratio"
    )
    assert_versioned_record(deployment, 1, "deployment")
    assert deployment["measured_evasion_rate_bps"] is None
    assert deployment["enforcement_cost_cents"] is None

    fixtures.move_clock(api, WINDOW_START)
    get_success_data(api.activate_deployment(deployment["id"], PLANNER_HEADERS))
    fixtures.move_clock(api, OBSERVATION_AT)

    encounter = fixtures.build_pending_encounter(api, env, deployment)
    assert encounter["outcome"] == OUTCOME_PENDING
    assert encounter["validation_result"] == VALIDATION_NO_PROOF


def test_activation_moves_a_planned_deployment_to_active_at_window_start(api):
    """
    Activation moves `status` from `PLANNED` to `ACTIVE` and is the moment
    enforcement authority actually attaches.

    Design: Corner/state_machines/deployment_activates_from_planned_once_clock_reaches_window_start
    """
    env = fixtures.build_environment(api)
    deployment = fixtures.plan_deployment(api, env["line"]["id"], env["zone"]["id"])

    fixtures.move_clock(api, WINDOW_START)
    activated = validate_success(api.activate_deployment(deployment["id"], PLANNER_HEADERS))

    assert activated["status"] == DEPLOYMENT_STATUS_ACTIVE
    assert activated["version"] == 2

    rows, meta = validate_paginated(
        api.list_deployments(PLANNER_HEADERS, {"status": DEPLOYMENT_STATUS_ACTIVE})
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [deployment["id"]]


def test_designating_a_zone_with_no_audit_on_file_fails_the_signage_clause(api):
    """
    Designating a zone moves `designation_status` from `PENDING_SIGNAGE` to
    `DESIGNATED`, and requires both that at least one signage audit exists for
    the zone and that `signage_compliance_pct` is at least 0.9000; a zone that
    fails either condition is refused with `ERR_SIGNAGE_BELOW_THRESHOLD`.

    Design: Corner/state_machines/designate_without_any_signage_audit_returns_signage_below_threshold
    """
    env = fixtures.build_environment(
        api,
        designate=False,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )
    zone_id = env["zone"]["id"]
    pending = get_success_data(api.submit_zone_for_signage(zone_id, PLANNER_HEADERS))
    assert pending["designation_status"] == ZONE_STATUS_PENDING_SIGNAGE
    assert pending["version"] == 2

    validate_error(
        api.designate_zone(zone_id, PLANNER_HEADERS), ERR_SIGNAGE_BELOW_THRESHOLD, 409
    )

    after = fixtures.read_zone(api, zone_id)
    assert after["designation_status"] == ZONE_STATUS_PENDING_SIGNAGE
    assert not after.get("designated_at")
    assert_rate_equals(after["signage_compliance_pct"], 0.0000, "zone.signage_compliance_pct")
    assert after["version"] == 2


def test_contesting_a_citation_schedules_the_hearing_fourteen_days_out(api):
    """
    A successful contest moves the citation `ISSUED → CONTESTED`, increments its
    `version` by 1, and creates the administrative hearing that will decide it.
    ... opens in `status` `SCHEDULED` with `decision` `PENDING`, and has
    `scheduled_for` set to the logical clock plus 14 days.

    Design: Corner/state_machines/contest_schedules_a_hearing_fourteen_days_out_as_a_side_effect
    """
    chain = fixtures.build_citation_chain(api)
    citation = chain["citation"]
    rider = chain["rider"]

    hearing = get_success_data(
        api.contest_citation(citation["id"], make_rider_headers(rider["id"]))
    )

    assert hearing["status"] == HEARING_STATUS_SCHEDULED
    assert hearing["decision"] == DECISION_PENDING
    assert_instant_equals(hearing["scheduled_for"], HEARING_AT, "hearing.scheduled_for")
    assert hearing["citation_id"] == citation["id"]
    assert hearing["requested_by_rider_id"] == rider["id"]
    assert not hearing.get("hearing_officer_user_id")
    assert not hearing.get("decided_at")

    contested = fixtures.read_citation(api, citation["id"])
    assert contested["adjudication_status"] == ADJUDICATION_CONTESTED
    assert contested["version"] == 2
    assert contested["settlement_status"] == SETTLEMENT_OUTSTANDING

    rows, meta = validate_paginated(
        api.list_hearings(PLANNER_HEADERS, {"citation_id": citation["id"]})
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [hearing["id"]]


def test_closing_a_deployment_that_never_activated_is_a_state_refusal(api):
    """
    A close request against a deployment whose `status` is not `ACTIVE` is
    refused with `ERR_INVALID_DEPLOYMENT_STATE`.

    Design: Corner/state_machines/close_on_a_planned_deployment_is_not_a_declared_transition
    """
    env = fixtures.build_environment(api)
    deployment = fixtures.plan_deployment(api, env["line"]["id"], env["zone"]["id"])
    assert_rate_equals(
        deployment["sample_adequacy_ratio"], 0.0000, "deployment.sample_adequacy_ratio"
    )

    response = api.close_deployment(deployment["id"], PLANNER_HEADERS)
    validate_error(response, ERR_INVALID_DEPLOYMENT_STATE, 409)
    assert response.json()["data"]["error_id"] != ERR_SAMPLE_SIZE_INADEQUATE

    after = fixtures.read_deployment(api, deployment["id"])
    assert after["status"] == DEPLOYMENT_STATUS_PLANNED
    assert after["version"] == 1


def test_a_revoked_zone_refuses_every_further_zone_transition(api):
    """
    As is any attempt to submit a zone whose current status is neither `DRAFT`
    nor `SUSPENDED`.  The `SUSPENDED` arm is the system's recovery path: a
    suspended zone re-enters the signage queue by the same operation.

    Design: Corner/state_machines/revoked_zone_cannot_be_resubmitted_for_signage
    """
    env = fixtures.build_environment(api)
    zone_id = env["zone"]["id"]
    revoked = get_success_data(api.revoke_zone(zone_id, PLANNER_HEADERS))
    assert revoked["designation_status"] == ZONE_STATUS_REVOKED
    version_after_revoke = revoked["version"]

    validate_error(
        api.submit_zone_for_signage(zone_id, PLANNER_HEADERS), ERR_INVALID_ZONE_STATE, 409
    )
    validate_error(api.suspend_zone(zone_id, PLANNER_HEADERS), ERR_INVALID_ZONE_STATE, 409)
    validate_error(api.revoke_zone(zone_id, PLANNER_HEADERS), ERR_INVALID_ZONE_STATE, 409)

    after = fixtures.read_zone(api, zone_id)
    assert after["designation_status"] == ZONE_STATUS_REVOKED
    assert after["version"] == version_after_revoke


def test_activation_is_not_idempotent_and_the_replay_is_refused(api):
    """
    A deployment whose `status` is not `PLANNED`, or whose window has not yet
    begun, is refused with `ERR_INVALID_DEPLOYMENT_STATE`.

    Design: Corner/state_machines/activating_the_same_deployment_twice_is_rejected_on_the_second_call
    """
    env = fixtures.build_environment(api)
    deployment = fixtures.build_active_deployment(api, env, observe_at=None)
    assert deployment["status"] == DEPLOYMENT_STATUS_ACTIVE
    assert deployment["version"] == 2

    validate_error(
        api.activate_deployment(deployment["id"], PLANNER_HEADERS),
        ERR_INVALID_DEPLOYMENT_STATE,
        409,
    )

    after = fixtures.read_deployment(api, deployment["id"])
    assert after["status"] == DEPLOYMENT_STATUS_ACTIVE
    assert after["version"] == 2
