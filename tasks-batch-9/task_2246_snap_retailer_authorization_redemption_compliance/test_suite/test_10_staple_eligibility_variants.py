"""The two staple-stock assessment variants disagreeing on identical inventory.

The desk variant counts breadth first and depth only in aggregate; the on-site
variant counts only varieties that are stocked three deep. One fourteen-line
inventory therefore passes at the desk and fails at the store.
"""
from test_helpers import (
    INV_DIVERGENT,
    assert_fields,
    assert_inspector_minutes,
    pending_visit_application,
    refresh_application,
    refresh_inspector,
    refresh_visit,
    submit_findings,
)


def test_desk_variety_first_passes_where_onsite_depth_first_fails():
    """The desk assessment and the on-site assessment read the same fourteen
    inventory lines and reach opposite verdicts.

    The specification pins both variants: "The category qualifies when it holds
    at least 3 distinct varieties and its aggregate unit count is at least 9."
    for DESK_VARIETY_FIRST, while ONSITE_DEPTH_FIRST counts only varieties
    holding at least three units, so "three varieties of two units each qualify
    the category at the desk and fail it at the store". Five two-deep FRUIT_VEG
    varieties give ten aggregate units and four desk-qualifying categories, but
    no deep variety at all, so only three categories survive on site.

    Design: Difficulty/dual_variant_calc/staple_criterion_a_desk_variety_first_vs_onsite_depth_first_divergence
    """
    context = pending_visit_application(inventory_lines=INV_DIVERGENT)

    application = refresh_application(context.application_id)
    assert_fields(
        application,
        {
            "desk_qualifying_categories": 4,
            "desk_perishable_categories": 3,
            "desk_criterion_pass": True,
        },
        "application desk figures",
    )

    submit_findings(
        context.visit,
        context.inspector,
        observed_inventory_lines=INV_DIVERGENT,
        observed_staple_shelf_linear_feet=30,
    )

    visit = refresh_visit(context.visit_id)
    assert_fields(
        visit,
        {
            "verified_qualifying_categories": 3,
            "verified_perishable_categories": 2,
            "verified_criterion_a_pass": False,
            "depth_of_stock_pass": True,
            "shelf_discrepancy_bps": 0,
            "status": "FINDINGS_SUBMITTED",
        },
        "visit findings",
    )


def test_onsite_failure_holds_the_application_and_frees_the_inspector():
    """The on-site shortfall is not merely reported: it moves the application to
    PENDING_DOCUMENTS with a staple-stock hold reason, consumes a deficiency
    cycle, and returns the inspector's committed minutes.

    Because the visit is over, the specification's minute conservation applies:
    an inspector's `committed_minutes` is the sum of the `window_minutes` of its
    SCHEDULED and IN_PROGRESS visits, so a visit that has reached
    FINDINGS_SUBMITTED contributes nothing.

    Design: Difficulty/dual_variant_calc/staple_criterion_a_desk_variety_first_vs_onsite_depth_first_divergence
    """
    context = pending_visit_application(inventory_lines=INV_DIVERGENT)
    assert_inspector_minutes(refresh_inspector(context.inspector_id), 120)

    submit_findings(
        context.visit,
        context.inspector,
        observed_inventory_lines=INV_DIVERGENT,
        observed_staple_shelf_linear_feet=30,
    )

    application = refresh_application(context.application_id)
    assert_fields(
        application,
        {
            "status": "PENDING_DOCUMENTS",
            "hold_reason_code": "STAPLE_STOCK_INSUFFICIENT",
            "deficiency_cycle_count": 1,
            "verified_criterion_pass": False,
        },
        "held application",
    )
    assert_inspector_minutes(refresh_inspector(context.inspector_id), 0)
