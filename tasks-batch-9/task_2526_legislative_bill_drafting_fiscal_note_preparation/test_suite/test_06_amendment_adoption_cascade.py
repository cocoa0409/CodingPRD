"""Adoption of a fiscally material amendment cascades four levels."""

from test_helpers import (
    FIFTY_MILLION_COST_LINES,
    adopt_amendment,
    assert_amendment,
    assert_instant,
    assert_session_ledger_invariants,
    draft_amendment,
    read_agency,
    read_amendment,
    read_bill,
    read_note,
    read_session,
    refer_bill,
    report_referral,
    request_amendment,
    set_clock,
    setup_certified_note,
    setup_introduced_bill,
    setup_world,
)

ADOPTION_CLOCK = "2026-10-06T00:00:00Z"


def _constrained_session_with_reported_bill():
    """A bridge bill whose certified note puts the session exactly at the
    constrained threshold, reported FAVORABLE out of the fiscal committee."""
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
    return world, bill, note


def _adopt_rural_set_aside(world, bill):
    """Request, draft and adopt a floor amendment worth 750,000 cents."""
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
    return drafted, adopt_amendment(world, drafted)


def test_adoption_reopens_the_note_and_reverses_the_certified_ledger_posting():
    """PRD: "- **Level 1** sets the bill's `fiscal_status` to `NOTE_STALE`." and
    "- **Level 3**, caused by the note leaving `CERTIFIED`, subtracts that
    retained `certified_total_cents` from the session's
    `certified_fiscal_total_cents`."

    Design: Difficulty/transitive_cascade/amendment_adoption_cascades_four_levels_from_bill_fiscal_status_to_session_posture
    """
    world, bill, note = _constrained_session_with_reported_bill()
    before = read_session(world)
    assert before["certified_fiscal_total_cents"] == 50_000_000
    assert before["fiscal_posture"] == "CONSTRAINED"

    drafted, _adopted = _adopt_rural_set_aside(world, bill)

    assert read_bill(world, bill["id"])["fiscal_status"] == "NOTE_STALE"

    reopened = read_note(world, note["id"])
    assert reopened["status"] == "ROUTED"
    assert reopened["revision_round"] == 1
    assert reopened["reopened_by_amendment_id"] == drafted["id"]
    assert_instant(reopened["routed_utc"], ADOPTION_CLOCK)
    # A responsiveness score of 100 draws no extension: 21 days from re-routing.
    assert_instant(reopened["due_utc"], "2026-10-27T00:00:00Z")
    assert reopened["certified_total_cents"] == 50_000_000
    assert read_agency(world)["open_request_count"] == 1

    after = read_session(world)
    assert after["certified_fiscal_total_cents"] == 0
    assert_session_ledger_invariants(after)


def test_adoption_flips_the_session_posture_from_constrained_back_to_normal():
    """PRD: "- **Level 4**, caused by that ledger change, recomputes the
    session's `fiscal_posture` against `constrained_threshold_cents` — which can
    flip a session from `CONSTRAINED` back to `NORMAL` mid-stream." and "On
    success `adopted_utc` is stamped with the logical clock, the bill's
    `adopted_amendment_count` rises by one, the amendment's
    `fiscal_impact_delta_cents` is added to the bill's
    `adopted_fiscal_delta_cents`, and the attorney's `active_engagement_count`
    drops by one as the amendment leaves the occupancy set."

    Design: Difficulty/transitive_cascade/amendment_adoption_cascades_four_levels_from_bill_fiscal_status_to_session_posture
    """
    world, bill, _note = _constrained_session_with_reported_bill()
    assert read_session(world)["fiscal_posture"] == "CONSTRAINED"

    drafted, _adopted = _adopt_rural_set_aside(world, bill)

    assert read_session(world)["fiscal_posture"] == "NORMAL"

    after = read_bill(world, bill["id"])
    assert after["legislative_status"] == "REPORTED"
    assert after["adopted_amendment_count"] == 1
    assert after["adopted_fiscal_delta_cents"] == 750_000

    amendment = read_amendment(world, drafted["id"])
    assert_amendment(amendment)
    assert amendment["status"] == "ADOPTED"
    assert_instant(amendment["adopted_utc"], ADOPTION_CLOCK)
