"""A fiscal note cycles through revision rounds and is re-opened by adoption."""

from test_helpers import (
    STANDARD_COST_LINES,
    adopt_amendment,
    append_cost_estimates,
    assert_agency_responsiveness_invariants,
    assert_fiscal_note_request,
    assert_instant,
    certify_note,
    draft_amendment,
    read_agency,
    read_bill,
    read_note,
    read_referral,
    read_session,
    refer_bill,
    request_amendment,
    return_note,
    route_fiscal_note,
    setup_introduced_bill,
    setup_world,
    submit_note,
)


def _clinic_bill_with_open_referral():
    """A community-clinic bill referred to the fiscal committee and left there."""
    world = setup_world(
        with_committee=True,
        with_agency=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
        agency_overrides={
            "name": "Dept of Health",
            "agency_code": "DOH",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Community clinic staffing",
        summary="Fund community clinic staffing.",
        target_code_chapter="Title 26",
        appropriation_requested_cents=9_000_000,
    )
    referral = refer_bill(world, bill)
    return world, bill, referral


def _note_certified_at_round_one(world, bill):
    """Submit, take one return for revision, resubmit and certify the note."""
    note = route_fiscal_note(world, bill, methodology="INCREMENTAL_COST")
    append_cost_estimates(world, note, STANDARD_COST_LINES)
    submitted = submit_note(world, note, submission_note="Round 0 submission.")
    returned = return_note(
        world, submitted, return_reason="Restate the FY2028 personnel assumption."
    )
    append_cost_estimates(world, returned, STANDARD_COST_LINES)
    resubmitted = submit_note(world, returned, submission_note="Round 1 resubmission.")
    return returned, certify_note(world, resubmitted, certification_note="Round 1 accepted.")


def test_returned_note_cycles_back_through_submitted_to_certified_bumping_the_round():
    """PRD: "The note moves from `SUBMITTED` to `RETURNED_FOR_REVISION` and its
    `revision_round` rises by one, which flips `included_in_certification` to
    false on every cost estimate line of the prior round and drops them out of
    every total — the analyst must file a fresh set." and "The agency's
    `open_request_count` is deliberately left unchanged, because the note is
    still open work on that agency's desk."

    Design: Difficulty/non_linear_state_machine/fiscal_note_cycles_submitted_returned_submitted_certified_then_reopened_to_routed
    """
    world, bill, _referral = _clinic_bill_with_open_referral()
    note = route_fiscal_note(world, bill, methodology="INCREMENTAL_COST")
    append_cost_estimates(world, note, STANDARD_COST_LINES)
    submitted = submit_note(world, note, submission_note="Round 0 submission.")
    assert submitted["status"] == "SUBMITTED"
    assert submitted["revision_round"] == 0

    returned = return_note(
        world, submitted, return_reason="Restate the FY2028 personnel assumption."
    )
    assert_fiscal_note_request(returned)
    assert returned["status"] == "RETURNED_FOR_REVISION"
    assert returned["revision_round"] == 1
    mid_agency = read_agency(world)
    assert mid_agency["revision_count"] == 1
    assert mid_agency["late_submission_count"] == 0
    assert mid_agency["responsiveness_score"] == 95
    assert mid_agency["open_request_count"] == 1
    assert_agency_responsiveness_invariants(mid_agency)

    append_cost_estimates(world, returned, STANDARD_COST_LINES)
    resubmitted = submit_note(world, returned, submission_note="Round 1 resubmission.")
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["certified_total_cents"] == 26_568_000
    assert resubmitted["late_submission"] is False

    certified = certify_note(world, resubmitted, certification_note="Round 1 accepted.")
    assert certified["status"] == "CERTIFIED"
    assert certified["revision_round"] == 1
    assert read_agency(world)["open_request_count"] == 0
    assert read_bill(world, bill["id"])["fiscal_status"] == "NOTE_COMPLETE"


def test_adopting_a_committee_amendment_reopens_the_certified_note_to_routed_at_round_two():
    """PRD: "**Level 2**, caused by the fiscal status becoming `NOTE_STALE`,
    re-opens the pricing exercise. The bill's fiscal note request in `CERTIFIED`
    moves back to `ROUTED`; its `revision_round` rises by one;
    `reopened_by_amendment_id` is set to the adopted amendment's identifier;
    `routed_utc` is re-stamped with the logical clock; `due_utc` is recomputed
    from the agency's current responsiveness band; and the agency's
    `open_request_count` rises by one." and "The total grant in whole days is
    added to `routed_utc` to produce `due_utc`, preserving `routed_utc`'s
    time-of-day exactly."

    Design: Difficulty/non_linear_state_machine/fiscal_note_cycles_submitted_returned_submitted_certified_then_reopened_to_routed
    """
    world, bill, referral = _clinic_bill_with_open_referral()
    _returned, certified = _note_certified_at_round_one(world, bill)

    amendment = request_amendment(
        world,
        bill,
        stage="COMMITTEE",
        committee_referral_id=referral["id"],
        summary="Add an outreach coordinator.",
        fiscal_impact_delta_cents=250_000,
        drafting_start_utc="2026-09-01T00:00:00Z",
        drafting_due_utc="2026-09-01T04:00:00Z",
    )
    drafted = draft_amendment(
        world, amendment, draft_text="On page 3, line 5, insert an outreach coordinator."
    )
    adopt_amendment(world, drafted)

    reopened = read_note(world, certified["id"])
    assert reopened["status"] == "ROUTED"
    # One return bumped the round to 1; the re-opening bumps it again.
    assert reopened["revision_round"] == 2
    assert reopened["reopened_by_amendment_id"] == drafted["id"]
    assert reopened["certified_total_cents"] == 26_568_000
    assert reopened["certified_utc"] is not None
    # A responsiveness score of 95 draws no extension: 21 days from 2026-09-01.
    assert_instant(reopened["due_utc"], "2026-09-22T00:00:00Z")

    agency = read_agency(world)
    assert agency["revision_count"] == 1
    assert agency["late_submission_count"] == 0
    assert agency["responsiveness_score"] == 95
    assert agency["open_request_count"] == 1

    after = read_bill(world, bill["id"])
    assert after["fiscal_status"] == "NOTE_STALE"
    assert after["legislative_status"] == "REFERRED"
    assert read_session(world)["certified_fiscal_total_cents"] == 0
    assert read_referral(world, referral["id"])["status"] == "IN_COMMITTEE"
