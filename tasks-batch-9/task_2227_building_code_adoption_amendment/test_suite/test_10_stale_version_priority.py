"""Concurrency outranking state on an analysis filing."""
from test_helpers import (
    ApiErrorId,
    fixtures,
    validate_error,
    validate_paginated,
    make_council_admin_headers,
)


def _rejected_proposal_world(api):
    """A proposal rejected at screening, leaving the analyst holding the version
    captured when the proposal was created."""
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")
    fixtures.submit_proposal(api, world)
    fixtures.screen_proposal(api, world, decision="REJECT")
    return world


def test_01_a_stale_version_outranks_the_forbidding_review_status(api):
    """"A stale expected version on a proposal whose `review_status` *also*
    forbids filing an analysis is reported as `ERR_STALE_PROPOSAL_VERSION`
    (priority 10), not as the state error (priority 11)." Screening incremented
    the proposal's `version`, so the version the analyst captured at creation no
    longer matches and "the request is rejected with `ERR_STALE_PROPOSAL_VERSION`
    (HTTP 412)".

    Design: Difficulty/priority_pair_validation_conflict/stale_proposal_version_outranks_rejected_proposal_state
    """
    world = _rejected_proposal_world(api)

    response = fixtures.submit_cost_benefit_analysis(
        api, world, expected_version=world["proposal_version_at_create"]
    )
    error = validate_error(response, ApiErrorId.ERR_STALE_PROPOSAL_VERSION, 412)
    assert error["error_id"] != ApiErrorId.ERR_PROPOSAL_STATE_INVALID


def test_02_the_refused_filing_creates_no_analysis_row(api):
    """"No analysis row is created" on a stale filing, and the rejection at
    screening had already moved `review_status` `SUBMITTED` → `REJECTED` while it
    "leaves `analysis_status` at `NOT_STARTED`".

    Design: Difficulty/priority_pair_validation_conflict/stale_proposal_version_outranks_rejected_proposal_state
    """
    world = _rejected_proposal_world(api)

    fixtures.submit_cost_benefit_analysis(
        api, world, expected_version=world["proposal_version_at_create"]
    )

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["review_status"] == "REJECTED"
    assert proposal["analysis_status"] == "NOT_STARTED"

    _, meta = validate_paginated(
        api.list_proposal_impact_analyses(
            world["proposal_id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 0
