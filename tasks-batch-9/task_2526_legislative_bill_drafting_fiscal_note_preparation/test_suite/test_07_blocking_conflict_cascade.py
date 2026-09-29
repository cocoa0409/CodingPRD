"""A blocking finding in DRAFTING cascades from counters to the member hold."""

from test_helpers import (
    assert_member_hold_invariants,
    assert_statutory_conflict,
    file_statutory_conflict,
    read_drafter,
    read_drafting_request,
    read_member,
    setup_request_in_drafting,
    setup_world,
)


def _two_requests_one_already_bounced():
    """The same member has two researched files; the first is already bounced."""
    world = setup_world(
        member_overrides={"priority_slots_total": 2},
        drafter_overrides={"max_concurrent_engagements": 2},
    )
    request_a = setup_request_in_drafting(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Records retention overhaul",
        summary="Overhaul agency records retention.",
        target_code_chapter="Title 44",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-10T00:00:00Z",
    )
    request_b = setup_request_in_drafting(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Notary commission reform",
        summary="Reform notary commissioning.",
        target_code_chapter="Title 45",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-03T00:00:00Z",
        engagement_end_utc="2026-09-11T00:00:00Z",
    )
    file_statutory_conflict(
        world,
        request_a,
        severity="BLOCKING",
        code_citation="44-3-102(b)",
        conflict_type="REPEALS_ACTIVE",
    )
    return world, request_a, request_b


def test_second_blocking_finding_bounces_the_file_and_puts_the_member_on_hold():
    """PRD: "Beyond that, a `BLOCKING` finding recorded **while the request is
    already in `DRAFTING`** triggers a three-level cascade that bounces the file
    back to the sponsor." and "At the second level, caused by the status leaving
    `DRAFTING` for `RETURNED_FOR_CLARIFICATION`, three further things happen:
    `sla_due_utc` is cleared to null, the assigned attorney's
    `active_engagement_count` is recomputed downward by one as the request leaves
    the occupancy set, and the sponsoring member's `clarification_pending_count`
    rises by one." and "At the third level, caused by that member's
    `clarification_pending_count` reaching two, the member's `intake_hold`
    becomes true — which is what blocks their next drafting request with
    `ERR_MEMBER_INTAKE_HOLD`."

    Design: Difficulty/transitive_cascade/blocking_conflict_cascades_three_levels_from_conflict_counters_to_member_intake_hold
    """
    world, _request_a, request_b = _two_requests_one_already_bounced()

    conflict = file_statutory_conflict(
        world,
        request_b,
        severity="BLOCKING",
        code_citation="45-17-204",
        conflict_type="AMENDS_SAME_SECTION",
    )

    assert_statutory_conflict(conflict)
    assert conflict["resolution_status"] == "OPEN"
    assert conflict["drafting_request_id"] == request_b["id"]

    bounced = read_drafting_request(world, request_b["id"])
    assert bounced["blocking_conflict_count"] == 1
    assert bounced["open_blocking_conflict_count"] == 1
    assert bounced["advisory_conflict_count"] == 0
    assert bounced["status"] == "RETURNED_FOR_CLARIFICATION"
    assert bounced["sla_due_utc"] is None

    # Both files have left the occupancy set, one after the other.
    assert read_drafter(world)["active_engagement_count"] == 0

    member = read_member(world)
    assert member["clarification_pending_count"] == 2
    assert member["intake_hold"] is True
    assert_member_hold_invariants(member)


def test_the_cascade_leaves_the_complexity_score_and_the_priority_ledger_untouched():
    """PRD: "Statutory research concludes when the assigned attorney reports what
    the code actually requires." and "On success, `revision_round` rises by one,
    recording how many clarification loops the file has completed;
    `actual_complexity_score` is recomputed, and because the conflict counters
    have grown it necessarily rises; `sla_due_utc` is recomputed from the current
    logical clock rather than from the original research instant; the attorney's
    `active_engagement_count` rises by one as the interval is re-acquired; and
    the member's `clarification_pending_count` falls by one with `intake_hold`
    recomputed."

    Design: Difficulty/transitive_cascade/blocking_conflict_cascades_three_levels_from_conflict_counters_to_member_intake_hold
    """
    world, _request_a, request_b = _two_requests_one_already_bounced()
    assert read_drafting_request(world, request_b["id"])["actual_complexity_score"] == 12

    file_statutory_conflict(
        world,
        request_b,
        severity="BLOCKING",
        code_citation="45-17-204",
        conflict_type="AMENDS_SAME_SECTION",
    )

    bounced = read_drafting_request(world, request_b["id"])
    # Four points for each of three affected sections, and nothing else: the
    # score is only recomputed when research completes or the sponsor answers.
    assert bounced["actual_complexity_score"] == 12
    assert bounced["revision_round"] == 0
    # Neither file declared priority_flag, so no slot was ever consumed.
    assert read_member(world)["priority_slots_used"] == 0
