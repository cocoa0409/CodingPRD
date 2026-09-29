"""Optimistic concurrency on a version that a cascade has already moved, and the
read-your-write guarantee the derived ledgers carry."""
from test_helpers import (
    ApiErrorId,
    fixtures,
    get_success_data,
    make_council_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_FILING = {
    "code_section": "C403.2.2",
    "local_text": "Riverbend also requires duct leakage testing on every system.",
    "stringency_direction": "MORE_STRINGENT",
    "justification": "Local commissioning practice.",
}


def test_01_a_second_filing_replaying_the_pre_acceptance_version_is_refused(api):
    """"Filing increments the target jurisdiction's `version` by one", and
    accepting "increments the jurisdiction's `effective_local_amendment_count` by
    one along with the jurisdiction's `version`". A second filing that replays the
    value read before either write therefore fails the precondition that "if that
    value does not equal the jurisdiction's current `version`, the request is
    rejected with `ERR_STALE_JURISDICTION_VERSION` (HTTP 412)", which is exactly
    why "a jurisdiction's filing set legitimately changes whenever another of its
    filings is accepted, so the section-uniqueness decision has to be made against
    a current read".

    Design: Corner/cross-cutting complexity layers/local_amendment_with_a_stale_jurisdiction_version_is_rejected
    """
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)
    stale_version = fixtures.read_jurisdiction(api, world["riverbend_id"])["version"]

    fixtures.add_local_amendment(api, world)
    get_success_data(fixtures.review_local_amendment(api, world, "START_REVIEW"))
    accepted = get_success_data(fixtures.review_local_amendment(api, world, "ACCEPT"))
    assert accepted["status"] == "FILED_EFFECTIVE"

    response = fixtures.file_local_amendment(
        api,
        world,
        expected_jurisdiction_version=stale_version,
        **SECOND_FILING,
    )
    validate_error(response, ApiErrorId.ERR_STALE_JURISDICTION_VERSION, 412)

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["effective_local_amendment_count"] == 1
    assert riverbend["version"] > stale_version

    _, meta = validate_paginated(
        api.list_jurisdiction_local_amendments(
            world["riverbend_id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 1


def test_02_the_cycle_ledger_is_current_on_the_read_that_follows_the_vote(api):
    """The derived aggregates are "exact at every instant — never reconciled after
    the fact, never eventually consistent", so the approving ballot both returns
    the `APPROVED` outcome and "synchronises the cycle ledger" in the same call:
    "the proposal's `statewide_incremental_cost_cents` is added to the cycle's
    `approved_incremental_cost_cents`, its `affected_permit_count` is added to the
    cycle's `approved_permit_backlog_count`, and the cycle's
    `approved_proposal_count` increases by one." The very next read shows the
    certified 143,002,800 cents and 2,410 permits with no second write.

    Design: Corner/consistency model/the_vote_response_already_carries_the_updated_cycle_ledger
    """
    world = fixtures.setup_convened_hearing(api)

    before = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert before["approved_proposal_count"] == 0
    assert before["approved_incremental_cost_cents"] == 0
    assert before["approved_permit_backlog_count"] == 0

    vote = validate_success(fixtures.record_vote(api, world), 201)
    assert vote["outcome"] == "APPROVED"
    assert vote["outcome_reason"] == "MAJORITY_APPROVED"
    assert vote["yes_count"] == 4
    assert vote["no_count"] == 2

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["review_status"] == "APPROVED"
    assert proposal["statewide_incremental_cost_cents"] == 143002800
    assert proposal["affected_permit_count"] == 2410

    after = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert after["approved_proposal_count"] == 1
    assert after["approved_incremental_cost_cents"] == 143002800
    assert after["approved_permit_backlog_count"] == 2410
    assert after["status"] == "DELIBERATION"
