"""The fiscal dimension of a bill cycles while its legislative dimension holds."""

from test_helpers import (
    STANDARD_COST_LINES,
    adopt_amendment,
    append_cost_estimates,
    assert_bill,
    assert_session_ledger_invariants,
    certify_note,
    draft_amendment,
    read_bill,
    read_note,
    read_session,
    refer_bill,
    report_referral,
    request_amendment,
    set_clock,
    setup_introduced_bill,
    setup_submitted_note,
    setup_world,
    submit_note,
)

REPORT_CLOCK = "2026-10-06T00:00:00Z"


def _reported_bill_with_certified_note():
    """A severance-tax bill reported FAVORABLE with a certified fiscal note."""
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
            "name": "Dept of Revenue",
            "agency_code": "DOR",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=4,
        requested_sections_count=4,
        subject="Severance tax rebasing",
        summary="Rebase the severance tax schedule.",
        target_code_chapter="Title 39",
        appropriation_requested_cents=12_000_000,
    )
    referral = refer_bill(world, bill)
    submitted = setup_submitted_note(world, bill, lines=STANDARD_COST_LINES)
    note = certify_note(world, submitted, certification_note="Round 0 accepted.")
    set_clock(REPORT_CLOCK)
    report_referral(world, referral, "FAVORABLE")
    return world, bill, note


def _fiscally_material_floor_amendment(world, bill):
    """Request and draft a floor amendment carrying a non-zero fiscal delta."""
    amendment = request_amendment(
        world,
        bill,
        stage="FLOOR",
        summary="Add a compliance grant line.",
        fiscal_impact_delta_cents=500_000,
        drafting_start_utc="2026-10-06T00:00:00Z",
        drafting_due_utc="2026-10-06T00:30:00Z",
    )
    return draft_amendment(
        world,
        amendment,
        draft_text="On page 4, line 12, insert a new subsection (d).",
    )


def test_adoption_moves_the_fiscal_dimension_to_note_stale_leaving_reported_untouched():
    """PRD: "A bill's two state dimensions advance **independently on the same
    row**." and "A bill at `NOTE_COMPLETE` moves to `NOTE_STALE`, and that is
    the head of a **four-level cascade**:" and "Crucially the note **retains**
    its `certified_total_cents` and its `certified_utc` so that a rescission can
    restore them exactly."

    Design: Difficulty/non_linear_state_machine/bill_fiscal_status_cycles_note_complete_stale_complete_while_legislative_status_holds_reported
    """
    world, bill, note = _reported_bill_with_certified_note()
    before = read_bill(world, bill["id"])
    assert before["legislative_status"] == "REPORTED"
    assert before["fiscal_status"] == "NOTE_COMPLETE"

    drafted = _fiscally_material_floor_amendment(world, bill)
    adopt_amendment(world, drafted)

    after = read_bill(world, bill["id"])
    assert_bill(after)
    assert after["fiscal_status"] == "NOTE_STALE"
    # The legislative dimension stands still across the whole fiscal round trip.
    assert after["legislative_status"] == "REPORTED"

    reopened = read_note(world, note["id"])
    assert reopened["status"] == "ROUTED"
    assert reopened["revision_round"] == 1
    assert reopened["reopened_by_amendment_id"] == drafted["id"]
    assert reopened["certified_total_cents"] == 26_568_000

    session = read_session(world)
    assert session["certified_fiscal_total_cents"] == 0
    assert session["fiscal_posture"] == "NORMAL"
    assert_session_ledger_invariants(session)


def test_recertifying_the_reopened_note_returns_the_bill_to_note_complete_still_reported():
    """PRD: "`fiscal_status` runs among `NOT_REQUIRED`, `NOTE_PENDING`,
    `NOTE_STALE` and `NOTE_COMPLETE` and has no terminal value at all — a bill
    can cycle through the fiscal dimension repeatedly while its legislative
    dimension stands still, and vice versa." and "A stale note can also be
    closed the ordinary way: re-submitting and re-certifying the re-opened note
    moves the bill's `fiscal_status` from `NOTE_STALE` to `NOTE_COMPLETE`, adds
    the freshly computed `certified_total_cents` to the session ledger, and
    clears `reopened_by_amendment_id`."

    Design: Difficulty/non_linear_state_machine/bill_fiscal_status_cycles_note_complete_stale_complete_while_legislative_status_holds_reported
    """
    world, bill, note = _reported_bill_with_certified_note()
    drafted = _fiscally_material_floor_amendment(world, bill)
    adopt_amendment(world, drafted)

    reopened = read_note(world, note["id"])
    append_cost_estimates(world, reopened, STANDARD_COST_LINES)
    resubmitted = submit_note(world, reopened)
    recertified = certify_note(world, resubmitted, certification_note="Round 1 accepted.")

    assert recertified["status"] == "CERTIFIED"
    assert recertified["revision_round"] == 1
    assert recertified["reopened_by_amendment_id"] is None
    assert recertified["certified_total_cents"] == 26_568_000

    after = read_bill(world, bill["id"])
    assert after["fiscal_status"] == "NOTE_COMPLETE"
    assert after["legislative_status"] == "REPORTED"
    assert after["adopted_amendment_count"] == 1
    assert after["adopted_fiscal_delta_cents"] == 500_000

    session = read_session(world)
    assert session["certified_fiscal_total_cents"] == 26_568_000
    assert session["fiscal_posture"] == "NORMAL"
