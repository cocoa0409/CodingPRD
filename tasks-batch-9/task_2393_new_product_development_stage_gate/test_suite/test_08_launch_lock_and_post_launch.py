"""The supersede cascade under a locked launch, and the two post-launch attainment bases."""
import pytest

from test_helpers import (
    assert_attainment_decision,
    assert_post_launch_period,
    create_formulation,
    deliverable_by_type,
    post_launch_period_payload,
    project_deliverables,
    read_formulation,
    read_project,
    read_window,
    setup_launch_locked_with_regulatory_clearance,
    setup_launched_project,
    validate_success,
)

REVISION_B = {"spec_summary": "Citrus wipe substrate rev B", "unit_cost_usd": 3.3000}


def _supersede_under_a_locked_launch():
    """A launch-locked household project whose current revision is then superseded."""
    ctx = setup_launch_locked_with_regulatory_clearance()
    assert ctx["project"]["commercial_status"] == "LAUNCH_LOCKED"
    ctx["revision_b"] = create_formulation(ctx["project"]["id"], **REVISION_B)
    return ctx


def test_superseding_a_revision_invalidates_the_label_that_cleared_it(
    api, portfolio_admin_headers
):
    """One accepted write retires revision A and voids its approved artwork.

    PRD: "Level two: any label approval describing the superseded revision whose `status` is
    `APPROVED` or `CONDITIONAL` moves to `INVALIDATED` — both statuses take that path
    identically."

    Design: Difficulty/transitive_cascade/formulation_supersede_four_level_lock_slip_cascade
    """
    ctx = _supersede_under_a_locked_launch()

    revision_a = read_formulation(ctx["formulation"]["id"])
    revision_b = read_formulation(ctx["revision_b"]["id"])
    label = validate_success(
        api.get_label_approval(ctx["label_approval"]["id"], portfolio_admin_headers)
    )

    assert revision_a["status"] == "SUPERSEDED"
    assert revision_a["revision"] == 1
    assert revision_b["status"] == "DRAFT"
    assert revision_b["revision"] == 2
    assert label["status"] == "INVALIDATED"


def test_the_cascade_drives_regulatory_clearance_back_to_pending(api):
    """The clearance item reopens with no evidence while the readiness items stand.

    PRD: "Level three: because the label that cleared it is gone, the project's
    `REGULATORY_CLEARANCE` checklist item moves `APPROVED → PENDING` with `evidence_url`
    cleared, which is why `APPROVED` is not a terminal checklist status."

    Design: Difficulty/transitive_cascade/formulation_supersede_four_level_lock_slip_cascade
    """
    ctx = _supersede_under_a_locked_launch()

    clearance = deliverable_by_type(ctx["project"]["id"], "REGULATORY_CLEARANCE",
                                    gate_id=ctx["gate2"]["id"])
    readiness = [
        item for item in project_deliverables(ctx["project"]["id"])
        if item["deliverable_type"] in ("MANUFACTURING_READINESS", "SALES_SELL_IN_PLAN")
    ]

    assert clearance["status"] == "PENDING"
    assert clearance["evidence_url"] is None
    assert len(readiness) == 2
    assert all(item["status"] == "APPROVED" for item in readiness), (
        "only the regulatory clearance reopens; the readiness evidence is untouched"
    )


def test_the_locked_launch_date_slips_when_the_revision_underneath_it_is_replaced(api):
    """The lock is released: LOCK_SLIPPED with no date and no window.

    PRD: "Level four: if the project's `commercial_status` was `LAUNCH_LOCKED` and the
    superseded revision carried that `APPROVED` or `CONDITIONAL` label, the launch lock slips —
    `commercial_status` moves `LAUNCH_LOCKED → LOCK_SLIPPED`, `launch_date` and
    `shelf_reset_window_id` are cleared to null, and `launch_readiness_pct` is recomputed."

    Design: Difficulty/transitive_cascade/formulation_supersede_four_level_lock_slip_cascade
    """
    ctx = _supersede_under_a_locked_launch()

    project = read_project(ctx["project"]["id"])

    assert project["commercial_status"] == "LOCK_SLIPPED"
    assert project["launch_date"] is None
    assert project["shelf_reset_window_id"] is None
    assert project["launch_readiness_pct"] == pytest.approx(100.00, abs=0.01), (
        "the recomputation finds both required readiness items still approved"
    )
    assert project["dev_status"] == "LAUNCH_READY", (
        "the cascade moves the commercial track only"
    )


def test_the_cascade_leaves_the_retailer_slot_and_the_spent_budget_alone(
    api, portfolio_admin_headers
):
    """A completed run and a passed study keep their money; the presentation keeps its slot.

    PRD: "Level one: its pilot runs in `SCHEDULED` or `RUNNING` move to `CANCELLED`, releasing
    their `committed_cost_usd`, and its studies still `ACTIVE` move `ACTIVE → ABANDONED`,
    likewise releasing theirs."

    Design: Difficulty/transitive_cascade/formulation_supersede_four_level_lock_slip_cascade
    """
    ctx = _supersede_under_a_locked_launch()

    presentation = validate_success(
        api.get_sell_in_presentation(ctx["presentation"]["id"], portfolio_admin_headers)
    )
    run = validate_success(api.get_pilot_run(ctx["pilot_run"]["id"], portfolio_admin_headers))
    study = validate_success(
        api.get_shelf_life_study(ctx["shelf_life_study"]["id"], portfolio_admin_headers)
    )
    project = read_project(ctx["project"]["id"])

    assert run["status"] == "COMPLETED"
    assert study["status"] == "PASSED"
    assert project["development_budget_committed_usd"] == pytest.approx(100000.00, abs=0.01), (
        "neither the completed run nor the passed study is released by the supersede"
    )
    assert presentation["status"] == "ACCEPTED"
    assert read_window(ctx["window"]["id"])["booked_slot_count"] == 1
    assert project["authorized_acv_pct"] == pytest.approx(32.50, abs=0.01)


def test_the_two_attainment_bases_coincide_in_the_first_period(api, portfolio_admin_headers):
    """Period 1 stores 88.76 on both bases and puts the project into a fix.

    PRD: "At period 1 the two coincide by construction."

    Design: Difficulty/dual_variant_calc/post_launch_attainment_basis_divergence
    """
    ctx = setup_launched_project(category="HOUSEHOLD", project_type="LINE_EXTENSION")

    period = validate_success(
        api.create_post_launch_period(
            ctx["project"]["id"],
            post_launch_period_payload(1, actual_units=34000,
                                       actual_net_revenue_usd=190000.00,
                                       actual_gross_margin_usd=62000.00,
                                       attainment_basis="CUMULATIVE"),
            portfolio_admin_headers,
        ),
        201,
    )

    assert_post_launch_period(period)
    assert period["plan_units_per_period"] == pytest.approx(38304.00, abs=0.01), (
        "153216 annual units divided by the four periods in a year"
    )
    assert period["attainment_cumulative_pct"] == pytest.approx(88.76, abs=0.01)
    assert period["attainment_trailing_pct"] == pytest.approx(88.76, abs=0.01)
    assert period["attainment_pct"] == pytest.approx(88.76, abs=0.01)
    assert period["decision"] == "FIX"
    assert_attainment_decision(period)
    assert read_project(ctx["project"]["id"])["dev_status"] == "IN_MARKET_FIX"


def test_the_second_period_stores_both_bases_and_they_diverge(api, portfolio_admin_headers):
    """A weak quarter reads 78.32 cumulatively and 67.88 on the trailing basis.

    PRD: "Both attainment figures are then computed and **both are always stored**, whichever
    basis was reported."

    Design: Difficulty/dual_variant_calc/post_launch_attainment_basis_divergence
    """
    ctx = setup_launched_project(category="HOUSEHOLD", project_type="LINE_EXTENSION")
    validate_success(
        api.create_post_launch_period(
            ctx["project"]["id"],
            post_launch_period_payload(1, actual_units=34000,
                                       actual_net_revenue_usd=190000.00,
                                       actual_gross_margin_usd=62000.00,
                                       attainment_basis="CUMULATIVE"),
            portfolio_admin_headers,
        ),
        201,
    )

    second = validate_success(
        api.create_post_launch_period(
            ctx["project"]["id"],
            post_launch_period_payload(2, actual_units=26000,
                                       actual_net_revenue_usd=141000.00,
                                       actual_gross_margin_usd=44000.00,
                                       attainment_basis="TRAILING"),
            portfolio_admin_headers,
        ),
        201,
    )

    assert second["attainment_cumulative_pct"] == pytest.approx(78.32, abs=0.01), (
        "60000 units against two periods of plan"
    )
    assert second["attainment_trailing_pct"] == pytest.approx(67.88, abs=0.01), (
        "26000 units against a single period of plan"
    )
    assert second["attainment_pct"] == pytest.approx(67.88, abs=0.01)
    assert second["attainment_basis"] == "TRAILING"


def test_the_trailing_basis_reaches_the_harsher_verdict_on_the_same_numbers(
    api, portfolio_admin_headers
):
    """The stored cumulative figure would have been a fix; the reported basis discontinues.

    PRD: "The cumulative basis averages every period to date, so a weak quarter is cushioned by
    earlier strength; the trailing basis reacts immediately to the period just reported and can
    therefore reach a harsher verdict than the cumulative basis on identical inputs."

    Design: Difficulty/dual_variant_calc/post_launch_attainment_basis_divergence
    """
    ctx = setup_launched_project(category="HOUSEHOLD", project_type="LINE_EXTENSION")
    validate_success(
        api.create_post_launch_period(
            ctx["project"]["id"],
            post_launch_period_payload(1, actual_units=34000,
                                       actual_net_revenue_usd=190000.00,
                                       actual_gross_margin_usd=62000.00,
                                       attainment_basis="CUMULATIVE"),
            portfolio_admin_headers,
        ),
        201,
    )

    second = validate_success(
        api.create_post_launch_period(
            ctx["project"]["id"],
            post_launch_period_payload(2, actual_units=26000,
                                       actual_net_revenue_usd=141000.00,
                                       actual_gross_margin_usd=44000.00,
                                       attainment_basis="TRAILING"),
            portfolio_admin_headers,
        ),
        201,
    )

    assert second["attainment_cumulative_pct"] >= 70.00, (
        "judged cumulatively the quarter would still have been a fix"
    )
    assert second["attainment_pct"] < 70.00
    assert second["decision"] == "DISCONTINUE"
    assert_attainment_decision(second)
    project = read_project(ctx["project"]["id"])
    assert project["dev_status"] == "DISCONTINUED"
    assert project["post_launch_decision"] == "DISCONTINUE"
