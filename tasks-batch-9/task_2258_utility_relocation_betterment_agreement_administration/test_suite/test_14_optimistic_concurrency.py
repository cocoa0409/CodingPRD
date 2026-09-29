"""The two version-guarded writes, each defending work the caller never saw."""
from test_helpers import (
    CANON_ESTIMATE_STATE_SHARE_CENTS,
    OFFICER_USER_ID,
    agreement_payload,
    make_agreement_officer_headers,
    make_utility_coordinator_headers,
    make_utility_owner_rep_headers,
    plan_payload,
    read_conflict,
    read_plan,
    start_plan_review,
    validate_error,
    validate_paginated,
    validate_success,
    world_determination_issued,
    world_permit_granted,
)

REVISED_TERMS = {
    "estimated_cost_cents": 39_000_000,
    "replacement_in_kind_cost_cents": 32_000_000,
    "proposed_capacity_ratio": 1.20,
    "work_days": 11,
}


def test_a_stale_conflict_version_stops_a_plan_that_would_retire_an_unseen_one(api):
    """PRD 2.7: "If that value does not equal the conflict's current `version`, the
    submittal is rejected with `ERR_STALE_VERSION` (412). The guard exists because a
    newly created plan supersedes every earlier non-superseded plan on the same
    conflict; a submittal made on a stale view of the conflict would silently retire a
    plan revision the submitter never saw."

    Design: Corner/cross_cutting_complexity_layers/a_stale_conflict_version_stops_a_plan_submittal_that_would_have_superseded_an_unseen_revision
    """
    world = world_determination_issued(api)
    rep = make_utility_owner_rep_headers(world["owner_id"])
    stale_version = read_conflict(api, world["conflict_id"])["version"]

    first = validate_success(
        api.create_relocation_plan(
            plan_payload(world["conflict_id"], stale_version), rep
        ),
        201,
    )
    assert first["status"] == "SUBMITTED"

    after_first = read_conflict(api, world["conflict_id"])
    assert after_first["version"] == stale_version + 1
    assert after_first["status"] == "RESPONSIBILITY_SET"

    stale_body = plan_payload(world["conflict_id"], stale_version, **REVISED_TERMS)
    validate_error(
        api.create_relocation_plan(stale_body, rep), "ERR_STALE_VERSION", 412
    )

    assert read_plan(api, first["id"])["status"] == "SUBMITTED"
    rows, meta = validate_paginated(
        api.list_conflict_relocation_plans(
            world["conflict_id"], make_utility_coordinator_headers()
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert read_conflict(api, world["conflict_id"])["version"] == stale_version + 1

    refreshed = plan_payload(
        world["conflict_id"], stale_version + 1, **REVISED_TERMS
    )
    second = validate_success(api.create_relocation_plan(refreshed, rep), 201)
    assert second["status"] == "SUBMITTED"
    assert second["estimated_cost_cents"] == 39_000_000
    assert read_plan(api, first["id"])["status"] == "SUPERSEDED"
    assert read_conflict(api, world["conflict_id"])["version"] == stale_version + 2


def test_a_stale_plan_version_stops_an_agreement_drafted_on_unreviewed_terms(api):
    """PRD 2.7: "If that value does not equal the plan's current `version`, the draft is
    rejected with `ERR_STALE_VERSION` (412). The guard exists because drafting a new
    agreement voids any earlier agreement on the same plan that is still in `DRAFT` or
    `PENDING_OWNER_SIGNATURE`; a stale view of the plan would retire cost terms the
    drafter never reviewed."

    Design: Corner/cross_cutting_complexity_layers/a_stale_plan_version_stops_an_agreement_draft_that_would_have_voided_an_unseen_one
    """
    world = world_permit_granted(api)
    coordinator = make_utility_coordinator_headers()
    officer = make_agreement_officer_headers(OFFICER_USER_ID)

    under_review = start_plan_review(api, world["plan_id"], coordinator)
    assert under_review["status"] == "UNDER_REVIEW"
    stale_version = validate_success(
        api.get_relocation_plan(world["plan_id"], officer)
    )["version"]

    approved = validate_success(api.approve_plan(world["plan_id"], coordinator))
    assert approved["status"] == "APPROVED"
    assert approved["version"] == stale_version + 1

    validate_error(
        api.create_agreement(
            agreement_payload(world["plan_id"], stale_version, 44_000_000), officer
        ),
        "ERR_STALE_VERSION",
        412,
    )
    _, meta = validate_paginated(
        api.list_agreements(officer, {"plan_id": world["plan_id"]})
    )
    assert meta["total_count"] == 0
    assert read_plan(api, world["plan_id"])["version"] == stale_version + 1

    validate_error(
        api.create_agreement(
            agreement_payload(world["plan_id"], stale_version + 1, 44_000_000), officer
        ),
        "ERR_NOT_TO_EXCEED_TOO_LOW",
        422,
    )

    drafted = validate_success(
        api.create_agreement(
            agreement_payload(world["plan_id"], stale_version + 1, 45_000_000), officer
        ),
        201,
    )
    assert drafted["execution_status"] == "DRAFT"
    assert drafted["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS
