"""Rotation generation: deterministic selector tie-breaks and empty-pool
shortfall gap creation."""
from test_helpers import (
    assert_coverage_gap,
    create_draft_program,
    create_staff_physician,
    generate_program,
    get_slot_for_date,
    list_assignments,
    list_gaps,
    list_slots,
    TEST_USERS,
)


def test_generation_selector_tiebreak_prefers_earliest_created_physician(api):
    """PRD §3.1: "The slot goes to the physician with the lowest prospective
    total points including tentative assignments; ties break toward the lowest
    prospective undesirable points — the weekend-and-holiday portion of the
    total — and then toward the earliest physician `created_at`."
    PRD §3.1: "each tentative assignment immediately counts toward later slots
    in the same run."

    Two zero-point physicians tie on total and undesirable points, so the
    earlier-created physician wins the first slot; the run projection then
    penalizes that physician's new 1.0 points, sending the second slot to the
    later-created physician.

    Design: Corner/calculations/generation_selector_tiebreak_prefers_earliest_created_physician
    """
    program = create_draft_program(
        name="Cards Tiebreak", period_start="2026-09-08", period_end="2026-09-09"
    )
    p_early = create_staff_physician("Dr Early")
    p_late = create_staff_physician("Dr Late")
    assert p_early["created_at"] <= p_late["created_at"]
    generate_program(program["id"])

    slot1 = get_slot_for_date(program["id"], "2026-09-08")
    slot2 = get_slot_for_date(program["id"], "2026-09-09")

    a1 = list_assignments(slot_id=slot1["id"])
    assert len(a1) == 1
    assert a1[0]["physician_id"] == p_early["id"], (
        "zero-point tie must break toward the earliest created_at"
    )
    assert a1[0]["origin"] == "GENERATED"

    a2 = list_assignments(slot_id=slot2["id"])
    assert len(a2) == 1
    assert a2[0]["physician_id"] == p_late["id"], (
        "the first tentative assignment's 1.0 points must count against the "
        "earlier physician for the next slot in the same run"
    )


def test_generation_empty_pool_creates_shortfall_gaps(api):
    """PRD §3.1: "every slot whose pool is empty stays OPEN and opens a
    CoverageGap with `reason` GENERATION_SHORTFALL."

    Design: Corner/calculations/generation_empty_pool_creates_shortfall_gaps
    """
    program = create_draft_program(
        name="Cards Empty", period_start="2026-09-08", period_end="2026-09-09"
    )
    generated = generate_program(program["id"])
    assert generated["status"] == "GENERATED"

    slots = list_slots(program["id"])
    assert len(slots) == 2
    assert all(s["status"] == "OPEN" for s in slots)

    gaps = list_gaps(program["id"])
    assert len(gaps) == 2
    for gap in gaps:
        assert_coverage_gap(gap)
        assert gap["reason"] == "GENERATION_SHORTFALL"
        assert gap["status"] == "OPEN"
        assert gap["resolved_by_assignment_id"] is None
