"""The two complexity scores on a drafting request are structurally different."""

from test_helpers import (
    assert_drafting_request,
    assert_instant,
    complete_research,
    file_statutory_conflict,
    read_drafting_request,
    setup_request_in_research,
    setup_world,
)

CONFIDENTIAL_PRIORITY_REQUEST = {
    "subject": "Confidential tax restructuring",
    "summary": "Restructure the franchise tax.",
    "requested_sections_count": 6,
    "target_code_chapter": "Title 39",
    "confidentiality": "CONFIDENTIAL",
    "priority_flag": True,
    "appropriation_requested_cents": 12_000_000,
}


def _request_with_three_findings():
    """Research a confidential priority request that collects two advisory and
    one blocking finding while it is still in RESEARCH."""
    world = setup_world(
        member_overrides={"priority_slots_total": 2},
        drafter_overrides={"max_concurrent_engagements": 2},
        counsel_overrides={"max_concurrent_engagements": 2},
    )
    request = setup_request_in_research(
        world,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-30T00:00:00Z",
        **CONFIDENTIAL_PRIORITY_REQUEST,
    )
    file_statutory_conflict(
        world,
        request,
        severity="ADVISORY",
        code_citation="39-22-104",
        conflict_type="STYLE_VIOLATION",
    )
    file_statutory_conflict(
        world,
        request,
        severity="ADVISORY",
        code_citation="39-22-105",
        conflict_type="DUPLICATE_ENACTMENT",
    )
    file_statutory_conflict(
        world,
        request,
        severity="BLOCKING",
        code_citation="39-22-301",
        conflict_type="AMENDS_SAME_SECTION",
    )
    return world, request


def test_actual_complexity_score_reprices_the_footprint_without_the_appropriation_band():
    """PRD: "It is the sum of five terms: four points for each section in
    `affected_sections_count`; three points for each of the request's advisory
    conflicts as counted by `advisory_conflict_count`; nine points for each of
    its blocking conflicts as counted by `blocking_conflict_count`; twelve
    points when `confidentiality` is `CONFIDENTIAL`; and eight points when
    `priority_flag` is true." and "Continuing the earlier example, if research
    on that confidential priority request finds nine affected sections, two
    advisory conflicts and one blocking conflict, the `actual_complexity_score`
    is thirty-six for sections, six for the advisory findings, nine for the
    blocking finding, twelve for confidentiality and eight for priority,
    totalling 71 — against an `intake_complexity_estimate` of 59 for the same
    row."

    Design: Difficulty/dual_variant_calc/drafting_complexity_intake_estimate_vs_post_research_actual_diverge
    """
    world, request = _request_with_three_findings()

    drafting = complete_research(world, request, affected_sections_count=9)

    assert_drafting_request(drafting)
    assert drafting["status"] == "DRAFTING"
    assert drafting["affected_sections_count"] == 9
    assert drafting["advisory_conflict_count"] == 2
    assert drafting["blocking_conflict_count"] == 1
    # 36 + 6 + 9 + 12 + 8, with no appropriation tier bonus in this variant.
    assert drafting["actual_complexity_score"] == 71
    assert drafting["intake_complexity_estimate"] == 59
    assert drafting["actual_complexity_score"] != drafting["intake_complexity_estimate"]


def test_intake_estimate_is_frozen_and_the_service_target_follows_the_actual_score():
    """PRD: "At intake the system freezes the member's own view of how hard the
    work will be into `intake_complexity_estimate`, and this value is never
    recomputed afterwards." and "A score of 71 on a priority request, for
    instance, produces a base of 426 hours, clamped to the 240-hour ceiling,
    halved to 120 hours by priority, left unmultiplied when the clock has not
    yet reached the pressure window, and added to the research completion
    instant as a flat five days."

    Design: Difficulty/dual_variant_calc/drafting_complexity_intake_estimate_vs_post_research_actual_diverge
    """
    world, request = _request_with_three_findings()
    # 24 for six declared sections, 12 confidential, 8 priority, 15 for the top
    # appropriation band: the member's own view of the work, frozen at filing.
    assert request["intake_complexity_estimate"] == 59
    assert request["actual_complexity_score"] is None

    complete_research(world, request, affected_sections_count=9)
    after = read_drafting_request(world, request["id"])

    assert after["intake_complexity_estimate"] == 59
    assert after["actual_complexity_score"] == 71
    assert_instant(after["research_completed_utc"], "2026-09-01T00:00:00Z")
    # 71 * 6 = 426 hours, clamped to 240, halved by priority to a flat 5 days.
    assert_instant(after["sla_due_utc"], "2026-09-06T00:00:00Z")
