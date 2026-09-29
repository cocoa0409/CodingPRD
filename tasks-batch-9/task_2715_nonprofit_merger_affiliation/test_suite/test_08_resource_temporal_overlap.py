"""Temporal-reservation tests for crew windows and exclusivity cooling-off.

An integration crew holds a half-open window and can occupy exactly one at a
time (PRD 3.8); an exclusivity window keeps constraining its party for thirty
calendar days after it is released, when the counterparty changes (PRD 3.3).
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CREW_WINDOW_CONFLICT, ERR_EXCLUSIVITY_COOLING_OFF
from test_helpers.assertions import assert_field
from test_helpers.test_users import INTEGRATION_MANAGER, make_strategy_officer_headers


def test_adjacent_crew_windows_are_both_accepted(api):
    """Two windows of one crew that meet at a single date are adjacent, not overlapping.

    PRD 3.8 states that "the crew window is half-open: planned_start_date is
    inside the window and planned_end_date is outside it", and that "because the
    interval is half-open, adjacency is not overlap - one task ending on the very
    day the next begins is allowed". A window of 2026-09-01 to 2026-09-08 and one
    of 2026-09-08 to 2026-09-15 therefore both stand for the same crew_code.

    Design: Difficulty/resource_temporal_overlap/crew_window_adjacency_allowed_but_one_day_straddle_rejected
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    assert_field(fx.read_deal(api, deal_id), "restricted_asset_posture", "NOT_ASSESSED")

    first = fx.create_task(
        api,
        deal_id,
        workstream="STAFFING",
        crew_code="CREW-STAFF1",
        title="Pay band mapping wave one",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-08",
    )
    second = fx.create_task(
        api,
        deal_id,
        workstream="STAFFING",
        crew_code="CREW-STAFF1",
        title="Pay band mapping wave two",
        planned_start_date="2026-09-08",
        planned_end_date="2026-09-15",
    )

    assert_field(first, "status", "PLANNED")
    assert_field(first, "planned_end_date", "2026-09-08")
    assert_field(second, "status", "PLANNED")
    assert_field(second, "planned_start_date", "2026-09-08")
    assert_field(second, "crew_code", "CREW-STAFF1")


def test_one_day_straddle_of_the_crew_seam_is_refused(api):
    """A window straddling the seam between two adjacent windows conflicts with the crew.

    PRD 3.8 states that "an integration crew can occupy exactly one window at a
    time, so a requested window that overlaps the window of any other task sharing
    the same crew_code whose status is not CANCELLED is refused with
    ERR_CREW_WINDOW_CONFLICT". A window of 2026-09-07 to 2026-09-09 contains
    2026-09-07, which lies inside the half-open [2026-09-01, 2026-09-08) window,
    and 2026-09-08, which lies inside [2026-09-08, 2026-09-15).

    Design: Difficulty/resource_temporal_overlap/crew_window_adjacency_allowed_but_one_day_straddle_rejected
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    fx.create_task(
        api,
        deal_id,
        workstream="STAFFING",
        crew_code="CREW-STAFF1",
        title="Pay band mapping wave one",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-08",
    )
    fx.create_task(
        api,
        deal_id,
        workstream="STAFFING",
        crew_code="CREW-STAFF1",
        title="Pay band mapping wave two",
        planned_start_date="2026-09-08",
        planned_end_date="2026-09-15",
    )

    response = api.create_integration_task(
        f.integration_task_payload(
            deal_id,
            workstream="STAFFING",
            crew_code="CREW-STAFF1",
            title="Pay band straddle",
            planned_start_date="2026-09-07",
            planned_end_date="2026-09-09",
        ),
        INTEGRATION_MANAGER,
    )
    validate_error(response, ERR_CREW_WINDOW_CONFLICT, 409)


def test_the_straddling_window_is_accepted_under_a_different_crew_code(api):
    """Crew capacity is scoped per crew_code, so the same straddling window stands for another crew.

    PRD 3.8 scopes the conflict to "any other task sharing the same crew_code",
    so the window that CREW-STAFF1 must refuse is available to CREW-SYS1: the
    reservation belongs to the crew rather than to the deal or to the calendar.

    Design: Difficulty/resource_temporal_overlap/crew_window_adjacency_allowed_but_one_day_straddle_rejected
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    fx.create_task(
        api,
        deal_id,
        workstream="STAFFING",
        crew_code="CREW-STAFF1",
        title="Pay band mapping wave one",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-08",
    )
    fx.create_task(
        api,
        deal_id,
        workstream="STAFFING",
        crew_code="CREW-STAFF1",
        title="Pay band mapping wave two",
        planned_start_date="2026-09-08",
        planned_end_date="2026-09-15",
    )
    validate_error(
        api.create_integration_task(
            f.integration_task_payload(
                deal_id,
                workstream="STAFFING",
                crew_code="CREW-STAFF1",
                title="Pay band straddle",
                planned_start_date="2026-09-07",
                planned_end_date="2026-09-09",
            ),
            INTEGRATION_MANAGER,
        ),
        ERR_CREW_WINDOW_CONFLICT,
        409,
    )

    other_crew = fx.create_task(
        api,
        deal_id,
        workstream="SYSTEMS",
        crew_code="CREW-SYS1",
        title="Donor CRM cutover",
        planned_start_date="2026-09-07",
        planned_end_date="2026-09-09",
    )
    assert_field(other_crew, "status", "PLANNED")
    assert_field(other_crew, "crew_code", "CREW-SYS1")
    assert_field(other_crew, "planned_start_date", "2026-09-07")
    assert_field(other_crew, "planned_end_date", "2026-09-09")


def _released_window_then_a_deal_with_a_new_counterparty(api):
    """Withdraw the A-B letter, leaving a RELEASED window, then open a screened A-C deal.

    The A-B letter runs 2026-08-01 for 60 days, so PRD 3.3's "exclusivity_start_date
    advanced by exclusivity_days minus one calendar day" ends it on 2026-09-29, and
    withdrawal "sets exclusivity_status to RELEASED, freeing the parties from the
    window and starting the cooling-off clock".
    """
    ctx = fx.setup_deal_loi_negotiation(api)
    officer_a = make_strategy_officer_headers(ctx["org_a"]["id"])
    assert_field(ctx["loi"], "exclusivity_end_date", "2026-09-29")

    ctx["loi"] = validate_success(
        api.withdraw_letter_of_intent(ctx["loi"]["id"], f.withdraw_payload(), officer_a)
    )
    assert_field(ctx["loi"], "status", "WITHDRAWN")
    assert_field(ctx["loi"], "exclusivity_status", "RELEASED")

    ctx["org_c"] = fx.create_organization(api, fx.ORG_C)
    deal2 = validate_success(
        api.create_restructuring(
            f.restructuring_payload(ctx["org_a"]["id"], ctx["org_c"]["id"]), officer_a
        ),
        201,
    )
    validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(deal2["id"], "SCREENING"), officer_a
        ),
        201,
    )
    ctx["deal2"] = fx.read_deal(api, deal2["id"])
    assert_field(ctx["deal2"], "status", "RATIONALE_BUILT")
    return ctx, officer_a


def test_cooling_off_refuses_a_start_exactly_thirty_days_after_the_released_window(api):
    """A new counterparty's window may not start on the thirtieth day after the released one.

    PRD 3.3 requires that "where the most recent RELEASED or EXPIRED window of a
    party involved a different counterparty than the one now proposed, the new
    exclusivity_start_date must fall strictly more than thirty calendar days after
    that window's exclusivity_end_date, and a start date inside those thirty days
    answers ERR_EXCLUSIVITY_COOLING_OFF". The released window ended 2026-09-29, and
    2026-10-29 is exactly the thirtieth day after it, so the strictly-more-than
    test fails.

    Design: Difficulty/resource_temporal_overlap/exclusivity_cooling_off_window_boundary_for_a_different_counterparty
    """
    ctx, officer_a = _released_window_then_a_deal_with_a_new_counterparty(api)
    deal2_id = ctx["deal2"]["id"]

    response = api.create_letter_of_intent(
        f.letter_of_intent_payload(
            deal2_id,
            fx.deal_version(api, deal2_id),
            exclusivity_days=30,
            exclusivity_start_date="2026-10-29",
        ),
        officer_a,
    )
    validate_error(response, ERR_EXCLUSIVITY_COOLING_OFF, 409)


def test_first_day_past_the_cooling_off_period_is_accepted(api):
    """The thirty-first day is the first legal start for a different counterparty.

    PRD 3.3 makes the cooling-off test strict, so the first admissible
    exclusivity_start_date after a window ending 2026-09-29 is 2026-10-30. The
    letter then lands as PRD 3.3 describes - "status ISSUED, exclusivity_status
    ACTIVE" - with exclusivity_end_date "exclusivity_start_date advanced by
    exclusivity_days minus one calendar day", which for 30 days is 2026-11-28, and
    the first letter of a deal "advances it RATIONALE_BUILT -> LOI_NEGOTIATION".

    Design: Difficulty/resource_temporal_overlap/exclusivity_cooling_off_window_boundary_for_a_different_counterparty
    """
    ctx, officer_a = _released_window_then_a_deal_with_a_new_counterparty(api)
    deal2_id = ctx["deal2"]["id"]

    validate_error(
        api.create_letter_of_intent(
            f.letter_of_intent_payload(
                deal2_id,
                fx.deal_version(api, deal2_id),
                exclusivity_days=30,
                exclusivity_start_date="2026-10-29",
            ),
            officer_a,
        ),
        ERR_EXCLUSIVITY_COOLING_OFF,
        409,
    )

    letter = validate_success(
        api.create_letter_of_intent(
            f.letter_of_intent_payload(
                deal2_id,
                fx.deal_version(api, deal2_id),
                exclusivity_days=30,
                exclusivity_start_date="2026-10-30",
            ),
            officer_a,
        ),
        201,
    )

    assert_field(letter, "exclusivity_start_date", "2026-10-30")
    assert_field(letter, "exclusivity_end_date", "2026-11-28")
    assert_field(letter, "exclusivity_status", "ACTIVE")
    assert_field(letter, "status", "ISSUED")
    assert_field(fx.read_deal(api, deal2_id), "status", "LOI_NEGOTIATION")


def test_a_repeat_window_with_the_same_counterparty_is_exempt_from_cooling_off(api):
    """The same two parties may resume immediately inside the thirty-day period.

    PRD 3.3 states that "a repeat window with the same counterparty is exempt from
    the cooling-off period entirely - parties are allowed to resume talks with each
    other immediately, just not to shop the deal". The A-B window was released on
    2026-09-29, so a fresh A-B letter starting 2026-10-29 sits squarely inside the
    thirty days that would refuse a different counterparty and must still be
    accepted.

    Design: Difficulty/resource_temporal_overlap/exclusivity_cooling_off_window_boundary_for_a_different_counterparty
    """
    ctx = fx.setup_deal_loi_negotiation(api)
    officer_a = make_strategy_officer_headers(ctx["org_a"]["id"])
    deal_id = ctx["deal"]["id"]
    assert_field(ctx["loi"], "exclusivity_end_date", "2026-09-29")

    withdrawn = validate_success(
        api.withdraw_letter_of_intent(ctx["loi"]["id"], f.withdraw_payload(), officer_a)
    )
    assert_field(withdrawn, "exclusivity_status", "RELEASED")

    letter = validate_success(
        api.create_letter_of_intent(
            f.letter_of_intent_payload(
                deal_id,
                fx.deal_version(api, deal_id),
                exclusivity_days=30,
                exclusivity_start_date="2026-10-29",
            ),
            officer_a,
        ),
        201,
    )

    assert_field(letter, "exclusivity_start_date", "2026-10-29")
    assert_field(letter, "exclusivity_end_date", "2026-11-27")
    assert_field(letter, "exclusivity_status", "ACTIVE")
    assert_field(letter, "status", "ISSUED")
