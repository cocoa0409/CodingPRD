"""Compensating actions: rescission restores the ledger, withdrawal the slot."""

from test_helpers import (
    ApiErrorId,
    FIFTY_MILLION_COST_LINES,
    adopt_amendment,
    api_client,
    create_drafting_request_payload,
    draft_amendment,
    file_drafting_request,
    read_agency,
    read_amendment,
    read_bill,
    read_drafter,
    read_drafting_request,
    read_member,
    read_note,
    read_session,
    refer_bill,
    report_referral,
    request_amendment,
    rescind_amendment_payload,
    set_clock,
    setup_certified_note,
    setup_introduced_bill,
    setup_world,
    validate_error,
    validate_success,
    withdraw_payload,
)

ADOPTION_CLOCK = "2026-10-06T00:00:00Z"


def _adopted_set_aside_on_a_constrained_session():
    """Reach the constrained threshold, then adopt a 750,000-cent floor amendment."""
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
            "name": "Dept of Transportation",
            "agency_code": "DOT",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=5,
        requested_sections_count=5,
        subject="Bridge rehabilitation program",
        summary="Create a bridge rehabilitation program.",
        target_code_chapter="Title 23",
        appropriation_requested_cents=40_000_000,
    )
    referral = refer_bill(world, bill)
    note = setup_certified_note(world, bill, lines=FIFTY_MILLION_COST_LINES)
    set_clock(ADOPTION_CLOCK)
    report_referral(world, referral, "FAVORABLE")
    amendment = request_amendment(
        world,
        bill,
        stage="FLOOR",
        summary="Add a rural bridge set-aside.",
        fiscal_impact_delta_cents=750_000,
        drafting_start_utc="2026-10-06T00:00:00Z",
        drafting_due_utc="2026-10-06T00:30:00Z",
    )
    drafted = draft_amendment(
        world,
        amendment,
        draft_text="On page 7, line 3, insert a rural set-aside subsection.",
    )
    adopt_amendment(world, drafted)
    return world, bill, note, drafted


def _rescind(world, amendment):
    return api_client.rescind_amendment(
        amendment["id"],
        rescind_amendment_payload(rescission_reason="Set-aside withdrawn on the floor."),
        world["clerk_headers"],
    )


def test_rescinding_an_adopted_amendment_restores_the_session_ledger_bit_identically():
    """PRD: "**The fiscal restoration on rescission is the compensating action the
    ledger depends on.**" and "Because the amount added back is the very same
    retained figure that was subtracted, an adopt-then-rescind round trip must
    leave `certified_fiscal_total_cents` bit-identical to its pre-adoption
    value."

    Design: Difficulty/compensating_invariant/rescinding_an_adopted_amendment_restores_the_session_certified_ledger_bit_identically
    """
    world, bill, note, drafted = _adopted_set_aside_on_a_constrained_session()
    assert read_session(world)["certified_fiscal_total_cents"] == 0

    validate_success(_rescind(world, drafted), 200)

    session = read_session(world)
    assert session["certified_fiscal_total_cents"] == 50_000_000
    assert session["fiscal_posture"] == "CONSTRAINED"

    restored = read_note(world, note["id"])
    assert restored["status"] == "CERTIFIED"
    assert restored["certified_total_cents"] == 50_000_000
    assert restored["reopened_by_amendment_id"] is None
    assert read_agency(world)["open_request_count"] == 0

    after = read_bill(world, bill["id"])
    assert after["fiscal_status"] == "NOTE_COMPLETE"
    assert after["legislative_status"] == "REPORTED"


def test_rescission_returns_the_amendment_to_drafted_without_rolling_back_the_round():
    """PRD: "The amendment returns from `ADOPTED` to `DRAFTED`, its
    `rescind_count` rises by one to record how often this has happened, and
    `adopted_utc` is cleared to null." and "The bill's `adopted_amendment_count`
    drops by one and its `fiscal_impact_delta_cents` is subtracted from the
    bill's `adopted_fiscal_delta_cents`." and "The attorney's
    `active_engagement_count` rises by one again, because a `DRAFTED` amendment
    re-enters the occupancy set."

    Design: Difficulty/compensating_invariant/rescinding_an_adopted_amendment_restores_the_session_certified_ledger_bit_identically
    """
    world, bill, note, drafted = _adopted_set_aside_on_a_constrained_session()

    _rescind(world, drafted)

    amendment = read_amendment(world, drafted["id"])
    assert amendment["status"] == "DRAFTED"
    assert amendment["adopted_utc"] is None
    assert amendment["rescind_count"] == 1
    assert amendment["fiscal_impact_delta_cents"] == 750_000

    after = read_bill(world, bill["id"])
    assert after["adopted_amendment_count"] == 0
    assert after["adopted_fiscal_delta_cents"] == 0

    # The pricing round is a historical record and is never wound back.
    assert read_note(world, note["id"])["revision_round"] == 1
    assert read_drafter(world)["active_engagement_count"] == 1


BROADBAND_COMMON = {
    "requested_sections_count": 3,
    "target_code_chapter": "Title 40",
    "confidentiality": "PUBLIC",
    "priority_flag": True,
    "appropriation_requested_cents": 0,
}


def _member_out_of_priority_slots():
    """A senator with two priority slots has spent both of them."""
    world = setup_world(
        member_overrides={
            "full_name": "Rep Gamma",
            "chamber": "SENATE",
            "party": "IND",
            "priority_slots_total": 2,
        }
    )
    request_a = file_drafting_request(
        world,
        subject="Rural broadband easements",
        summary="Simplify broadband easements.",
        **BROADBAND_COMMON,
    )
    request_b = file_drafting_request(
        world,
        subject="Utility pole attachment rates",
        summary="Cap pole attachment rates.",
        **BROADBAND_COMMON,
    )
    return world, request_a, request_b


def _file_priority_request(world, subject, summary, requested_sections_count=3):
    return api_client.create_drafting_request(
        create_drafting_request_payload(
            world["session"]["id"],
            subject=subject,
            summary=summary,
            requested_sections_count=requested_sections_count,
            target_code_chapter="Title 40",
            confidentiality="PUBLIC",
            priority_flag=True,
            appropriation_requested_cents=0,
        ),
        world["member_headers"],
    )


def test_withdrawing_a_priority_request_returns_the_member_slot_ledger():
    """PRD: "Withdrawal is the domain's cleanest **compensating action**, and it
    has four effects." and "When `priority_flag` is true, `priority_slots_used`
    drops by one, returning the ledger to precisely the value it held before the
    request was filed."

    Design: Difficulty/compensating_invariant/withdrawing_a_priority_drafting_request_returns_the_member_slot_ledger_to_its_prior_count
    """
    world, request_a, request_b = _member_out_of_priority_slots()
    assert read_member(world)["priority_slots_used"] == 2
    probe = _file_priority_request(
        world,
        "Probe request that must be refused",
        "Confirms the member is out of priority slots.",
        requested_sections_count=1,
    )
    validate_error(probe, ApiErrorId.ERR_PRIORITY_SLOTS_EXHAUSTED.value, 409)

    withdrawn = validate_success(
        api_client.withdraw_drafting_request(
            request_b["id"],
            withdraw_payload(
                withdrawal_reason="Sponsor consolidated the measure into request A."
            ),
            world["member_headers"],
        ),
        200,
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["sla_due_utc"] is None
    # The row is retained rather than deleted.
    assert read_drafting_request(world, request_b["id"])["status"] == "WITHDRAWN"

    member = read_member(world)
    assert member["priority_slots_used"] == 1
    assert member["clarification_pending_count"] == 0
    assert member["intake_hold"] is False
    assert read_drafting_request(world, request_a["id"])["priority_flag"] is True


def test_the_returned_slot_admits_a_fresh_priority_request():
    """PRD: "`priority_slots_used` is defined as the count of that member's
    drafting requests, across every session, whose `priority_flag` is true and
    whose `status` is neither `WITHDRAWN` nor `LAPSED`; when a priority request is
    accepted, that count rises by one." and "Eight points are added when
    `priority_flag` is true, and nothing otherwise."

    Design: Difficulty/compensating_invariant/withdrawing_a_priority_drafting_request_returns_the_member_slot_ledger_to_its_prior_count
    """
    world, request_a, request_b = _member_out_of_priority_slots()
    api_client.withdraw_drafting_request(
        request_b["id"],
        withdraw_payload(
            withdrawal_reason="Sponsor consolidated the measure into request A."
        ),
        world["member_headers"],
    )

    accepted = validate_success(
        _file_priority_request(
            world,
            "Middle mile grant conditions",
            "Attach conditions to middle mile grants.",
        ),
        201,
    )

    assert accepted["status"] == "SUBMITTED"
    assert accepted["priority_flag"] is True
    # Twelve points for three declared sections plus eight for priority.
    assert accepted["intake_complexity_estimate"] == 20
    assert read_member(world)["priority_slots_used"] == 2
    assert read_drafting_request(world, request_a["id"])["status"] == "SUBMITTED"
