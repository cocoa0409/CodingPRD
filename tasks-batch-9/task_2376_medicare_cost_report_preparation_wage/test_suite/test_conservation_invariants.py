"""Compensating operations return the conserved quantities to their exact
pre-create values: mapped direct cost in cents, and rotation FTE days."""

from test_helpers import (
    DEFAULT_CLOCK,
    assert_direct_cost_conserved,
    assert_fte_equals,
    assert_instant_equals,
    assert_money_equals,
    validate_success,
)
from test_helpers.fixtures import (
    create_reclassification,
    create_rotation,
    read_cost_center,
    read_cost_report,
    read_gme_summary,
    reverse_workpaper_entry,
    setup_resident_with_rotation,
    setup_three_center_report,
    void_rotation,
)
from test_helpers.factories import workpaper_leg


def _three_legged_reclassification(api, scenario):
    return create_reclassification(
        api,
        scenario,
        [
            workpaper_leg(scenario["cc_ag"], -30000000),
            workpaper_leg(scenario["cc_routine"], 20000000),
            workpaper_leg(scenario["cc_ancillary"], 10000000),
        ],
        code="A6-4",
        description="Move administration effort to nursing and surgery",
    )


def _centers(api, scenario):
    return [
        read_cost_center(api, scenario, scenario["cc_ag"]),
        read_cost_center(api, scenario, scenario["cc_routine"]),
        read_cost_center(api, scenario, scenario["cc_ancillary"]),
    ]


def test_a_reclassification_moves_cost_without_creating_any(api):
    """Shifting 30000000 out of administration into two receivers leaves the sum
    of post-reclassification cost at 420000000.

    PRD 3.3: "Summing `post_reclass_direct_cost_cents` across the report's cost centers always equals summing `amount_cents` across the report's `MAPPED` trial balance lines, and that equality survives every reclassification create and every reversal precisely because reclassification legs are required to net to zero."

    Design: Difficulty/compensating_invariant/reclassification_reversal_conserves_mapped_direct_cost_in_cents
    """
    scenario = setup_three_center_report(api)
    assert_direct_cost_conserved(_centers(api, scenario), 420000000)
    assert_money_equals(
        read_cost_report(api, scenario)["total_direct_cost_cents"],
        420000000,
        "total_direct_cost_cents",
    )

    _three_legged_reclassification(api, scenario)

    ag, routine, ancillary = _centers(api, scenario)
    assert_money_equals(
        ag["reclassified_amount_cents"], -30000000, "reclassified_amount_cents"
    )
    assert_money_equals(
        ag["post_reclass_direct_cost_cents"], 70000000, "00100 post_reclass"
    )
    assert_money_equals(
        routine["post_reclass_direct_cost_cents"], 220000000, "03000 post_reclass"
    )
    assert_money_equals(
        ancillary["post_reclass_direct_cost_cents"], 130000000, "05000 post_reclass"
    )
    assert_direct_cost_conserved([ag, routine, ancillary], 420000000)
    assert_money_equals(
        read_cost_report(api, scenario)["total_direct_cost_cents"],
        420000000,
        "total_direct_cost_cents",
    )


def test_reversing_the_entry_restores_every_cent(api):
    """The reversal returns all three centers to 100000000 / 200000000 / 120000000
    with no residual cent anywhere.

    PRD 3.3: "Creating an entry and then reversing it must return every affected figure to its exact pre-create value."

    Design: Difficulty/compensating_invariant/reclassification_reversal_conserves_mapped_direct_cost_in_cents
    """
    scenario = setup_three_center_report(api)
    _three_legged_reclassification(api, scenario)

    reversed_entry = reverse_workpaper_entry(api, scenario)
    assert reversed_entry["status"] == "REVERSED"
    assert_instant_equals(reversed_entry["reversed_at"], DEFAULT_CLOCK, "reversed_at")

    ag, routine, ancillary = _centers(api, scenario)
    assert_money_equals(ag["reclassified_amount_cents"], 0, "reclassified_amount_cents")
    assert_money_equals(
        ag["post_reclass_direct_cost_cents"], 100000000, "00100 post_reclass"
    )
    assert_money_equals(
        routine["post_reclass_direct_cost_cents"], 200000000, "03000 post_reclass"
    )
    assert_money_equals(
        ancillary["post_reclass_direct_cost_cents"], 120000000, "05000 post_reclass"
    )
    assert_money_equals(ag["direct_cost_cents"], 100000000, "00100 direct_cost_cents")
    assert_money_equals(
        routine["direct_cost_cents"], 200000000, "03000 direct_cost_cents"
    )
    assert_money_equals(
        ancillary["direct_cost_cents"], 120000000, "05000 direct_cost_cents"
    )
    assert_direct_cost_conserved([ag, routine, ancillary], 420000000)
    assert_money_equals(
        read_cost_report(api, scenario)["total_direct_cost_cents"],
        420000000,
        "total_direct_cost_cents",
    )


def test_voiding_a_rotation_gives_back_exactly_its_fte_days(api):
    """A 15.5000 FTE-day rotation created and then voided leaves the resident and
    the report back at 110.4000.

    PRD 3.6: "It advances the assignment to the terminal `VOID` state, sets its `fte_days` to 0.0000, decrements the resident's `assigned_fte_days` by the assignment's pre-void `fte_days`, decrements the report's `unweighted_fte_days_total` by the same figure, and recomputes the report's full-time-equivalent outputs."

    Design: Difficulty/compensating_invariant/rotation_void_conserves_resident_fte_days
    """
    scenario = setup_resident_with_rotation(api)
    resident_id = scenario["resident_id"]
    base_rotation_id = scenario["base_rotation_id"]

    before = validate_success(api.get_resident(resident_id, scenario["analyst"]))
    assert_fte_equals(before["assigned_fte_days"], 110.4000, "assigned_fte_days")
    assert_fte_equals(
        read_cost_report(api, scenario)["unweighted_fte_days_total"],
        110.4000,
        "unweighted_fte_days_total",
    )

    extra = create_rotation(
        api,
        scenario,
        start_date="2026-01-01",
        end_date="2026-02-01",
        fte_fraction=0.5000,
    )
    assert extra["overlap_days"] == 31
    assert_fte_equals(extra["fte_days"], 15.5000, "extra fte_days")
    mid_resident = validate_success(api.get_resident(resident_id, scenario["analyst"]))
    assert_fte_equals(mid_resident["assigned_fte_days"], 125.9000, "assigned_fte_days")
    assert_fte_equals(
        read_cost_report(api, scenario)["unweighted_fte_days_total"],
        125.9000,
        "unweighted_fte_days_total",
    )

    voided = void_rotation(api, scenario, extra["id"])
    assert voided["status"] == "VOID"
    assert_fte_equals(voided["fte_days"], 0.0000, "voided fte_days")
    assert voided["overlap_days"] == 31

    after = validate_success(api.get_resident(resident_id, scenario["analyst"]))
    assert_fte_equals(after["assigned_fte_days"], 110.4000, "assigned_fte_days")
    assert_fte_equals(
        read_cost_report(api, scenario)["unweighted_fte_days_total"],
        110.4000,
        "unweighted_fte_days_total",
    )

    base = validate_success(
        api.get_rotation_assignment(base_rotation_id, scenario["analyst"])
    )
    assert base["status"] == "ACTIVE"
    assert_fte_equals(base["fte_days"], 110.4000, "base fte_days")


def test_the_gme_summary_returns_to_its_pre_create_figures(api):
    """Every derived full-time-equivalent output travels 0.30 to 0.34 and back to
    0.30 across the create and its void.

    PRD 3.6: "The report's `rolling_average_fte` is this report's `capped_unweighted_fte` plus the `capped_unweighted_fte` of each prior period, divided by one plus the number of prior periods found, rounded half up to two decimal places."

    Design: Difficulty/compensating_invariant/rotation_void_conserves_resident_fte_days
    """
    scenario = setup_resident_with_rotation(api)

    before = read_gme_summary(api, scenario)
    assert before["period_days"] == 365
    assert before["prior_period_count"] == 0
    assert before["unweighted_fte_total"] == 0.30
    assert before["capped_unweighted_fte"] == 0.30
    assert before["weighted_fte_total"] == 0.30
    assert before["rolling_average_fte"] == 0.30

    extra = create_rotation(
        api,
        scenario,
        start_date="2026-01-01",
        end_date="2026-02-01",
        fte_fraction=0.5000,
    )
    during = read_gme_summary(api, scenario)
    assert during["unweighted_fte_total"] == 0.34
    assert during["rolling_average_fte"] == 0.34

    void_rotation(api, scenario, extra["id"])

    after = read_gme_summary(api, scenario)
    assert after["unweighted_fte_total"] == 0.30
    assert after["capped_unweighted_fte"] == 0.30
    assert after["weighted_fte_total"] == 0.30
    assert after["rolling_average_fte"] == 0.30
    assert after["prior_period_count"] == 0
