"""The costing rule and the capital funding ledger: the provisional estimate versus
the final settlement, the after-hours multiplier over capped hours and tiered parts,
the minimum call-out floor, the contingency tier keyed on base cost, and the
commit/release conservation of a project's money.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_capital_funding_invariant,
    assert_capital_project,
    assert_work_order,
    capital_project_payload,
    create_building,
    create_work_order,
    make_facility_manager_headers,
    make_finance_controller_headers,
    propose_capital_project,
    read_capital_project,
    read_work_order,
    set_clock,
    setup_approved_project,
    setup_building_and_vendor,
    setup_work_order_pending_qa,
    validate_error,
    validate_success,
    work_order_payload,
)

FM = TEST_USERS["facility_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]


# ---------------------------------------------------------------------------
# The two costing variants
# ---------------------------------------------------------------------------
def test_provisional_estimate_reprices_from_standard_rate_to_vendor_rate(api):
    """PRD §3.4: "Where no vendor is attached to the order — at creation, and again
    after an offer has been declined — the rate is the standard 80.00 per hour. Where a
    vendor is attached — at dispatch creation, and at dispatch completion — the rate is
    that vendor's `hourly_rate`."
    PRD §3.4: "The **provisional** variant stops there: it uses `estimated_labor_hours`
    and `estimated_parts_cost` as its hours and parts, never deducts an SLA penalty (no
    SLA outcome exists yet), and writes the rounded gross into the order's
    `estimated_amount` — the figure that is held against the funding project's
    committed amount."
    PRD §3.5: "The order's `estimated_amount` is recomputed by the provisional variant,
    now using the vendor's real `hourly_rate` in place of the standard rate, and any
    funding project's `committed_amount` moves by the difference between the new
    estimate and the old one, with `remaining_amount` following."

    Design: Difficulty/dual_variant_calc/work_order_provisional_estimate_vs_final_settlement
    """
    ctx = setup_building_and_vendor(clock="2026-05-04T09:00:00Z")
    building, vendor = ctx["building"], ctx["vendor"]
    asset_free_order = create_work_order(
        building["id"], wo_type="CORRECTIVE", priority="P1",
        estimated_labor_hours=4, estimated_parts_cost=400.00, chargeable=True,
    )

    # At creation, no vendor is attached: 4h * 80.00 = 320.00 labour,
    # + 25% P1 surcharge = 80.00, + 400.00 * 1.15 parts = 460.00  ->  860.00
    assert asset_free_order["estimated_amount"] == pytest.approx(860.00, abs=0.01)

    version = asset_free_order["version"]
    dispatch = validate_success(
        api.create_dispatch(
            asset_free_order["id"],
            {"vendor_id": vendor["id"], "expected_work_order_version": version},
            FM,
        ),
        201,
    )
    assert dispatch["status"] == "OFFERED"

    # At dispatch, the vendor's rate replaces the standard one:
    # 4h * 100.00 = 400.00 labour, + 25% = 100.00, + 460.00 parts  ->  960.00
    reread = read_work_order(asset_free_order["id"])
    assert_work_order(reread)
    assert reread["estimated_amount"] == pytest.approx(960.00, abs=0.01)


def test_final_settlement_disagrees_with_provisional_estimate(api):
    """PRD §3.4: "The **final settlement** variant runs only when a dispatch completes.
    It uses the vendor-reported `actual_labor_hours` and `actual_parts_cost` as its
    hours and parts, always uses the vendor's `hourly_rate`, and then continues past
    the gross: the penalty is the gross multiplied by the dispatch's `penalty_pct`,
    rounded half up to 2 decimal places, and the order's `billable_amount` is the gross
    less that penalty, again rounded half up to 2 decimal places."
    PRD §3.4: "For identical work the two variants therefore disagree whenever the
    actuals differ from the estimates or whenever any SLA leg was breached."
    PRD §3.5: "The dispatch's `penalty_pct` is then the sum of 0.10 if the response leg
    was missed and 0.15 if the resolve leg was missed, capped at 0.25; if both legs
    were met it is 0."

    Design: Difficulty/dual_variant_calc/work_order_provisional_estimate_vs_final_settlement
    """
    ctx = setup_work_order_pending_qa(
        clock="2026-05-04T09:00:00Z",
        accept_clock="2026-05-04T09:30:00Z",
        complete_clock="2026-05-04T12:00:00Z",
        actual_labor_hours=6, actual_parts_cost=600.00,
        wo_overrides={
            "wo_type": "CORRECTIVE", "priority": "P1",
            "estimated_labor_hours": 4, "estimated_parts_cost": 400.00,
            "chargeable": True,
        },
    )
    work_order, dispatch = ctx["work_order"], ctx["dispatch"]
    assert_work_order(work_order)

    # Both SLA legs met (60-minute response window, 240-minute resolve window).
    assert dispatch["sla_response_met"] is True
    assert dispatch["sla_resolve_met"] is True
    assert dispatch["penalty_pct"] == pytest.approx(0, abs=0.001)

    # Final settlement on the vendor-reported actuals, priced off the work order's
    # dispatched_at (09:00 UTC, so no after-hours multiplier):
    # 6h * 100.00 = 600.00 labour, + 25% P1 = 150.00, + 600.00 * 1.10 = 660.00 parts.
    assert work_order["billable_amount"] == pytest.approx(1410.00, abs=0.01)
    assert work_order["estimated_amount"] == pytest.approx(960.00, abs=0.01)
    assert work_order["billable_amount"] != work_order["estimated_amount"], (
        "the two variants must not collapse onto the same figure"
    )
    assert work_order["status"] == "PENDING_QA"


def test_after_hours_multiplier_applies_to_capped_hours_and_top_parts_tier(api):
    """PRD §3.4: "The job counts as after-hours when the UTC hour of the reference
    instant is earlier than 8, or is 18 or later; a job whose reference instant falls
    anywhere from 08:00:00 to 17:59:59 UTC is not after-hours."
    PRD §3.4: "Take the labour hours in play and cap them at 12: any hours beyond the
    twelfth are simply not billed. Multiply the capped hours by the labour rate, and
    multiply that product by 1.5 if the job is after-hours, or leave it as it is if it
    is not; that is the labour component."
    PRD §3.4: "Add a priority surcharge on top of the labour component: 25 percent of
    it for a `P1` order, 10 percent for a `P2`, and nothing at all for a `P3` or a `P4`."
    PRD §3.4: "The parts markup is tiered on the parts figure itself: 15 percent when
    the parts figure is at most 500, 10 percent when it is above 500 but at most 2000,
    and 5 percent when it is above 2000."

    Design: Difficulty/combinatorial_formula/work_order_after_hours_multiplier_with_tiered_parts_markup
    """
    ctx = setup_building_and_vendor(clock="2026-05-04T19:00:00Z")
    building, vendor = ctx["building"], ctx["vendor"]
    work_order = create_work_order(
        building["id"], wo_type="CORRECTIVE", priority="P2",
        estimated_labor_hours=14, estimated_parts_cost=2500.00,
    )

    validate_success(
        api.create_dispatch(
            work_order["id"],
            {"vendor_id": vendor["id"],
             "expected_work_order_version": work_order["version"]},
            FM,
        ),
        201,
    )

    reread = read_work_order(work_order["id"])
    # Reference instant is the dispatch's 19:00 UTC — after hours.
    # Labour: min(14, 12) = 12 capped hours * 100.00 * 1.5 = 1800.00
    # P2 surcharge: 1800.00 * 0.10 = 180.00
    # Parts: 2500.00 is above 2000, so the 5% tier -> 2500.00 * 1.05 = 2625.00
    assert reread["estimated_amount"] == pytest.approx(4605.00, abs=0.01), (
        "hours beyond the twelfth are not billed, so 12 capped hours are multiplied "
        "by the 1.5 after-hours factor"
    )


def test_dispatch_advances_work_order_status_and_version(api):
    """PRD §3.5: "Dispatching an order sends it to a vendor and moves it
    `NEW → DISPATCHED`."
    PRD §3.5: "Dispatch creation increments the work order's `version` by 1 — which is
    precisely why the next dispatch attempt needs a freshly-read
    `expected_work_order_version`."

    Design: Difficulty/combinatorial_formula/work_order_after_hours_multiplier_with_tiered_parts_markup
    """
    ctx = setup_building_and_vendor(clock="2026-05-04T19:00:00Z")
    building, vendor = ctx["building"], ctx["vendor"]
    work_order = create_work_order(
        building["id"], wo_type="CORRECTIVE", priority="P2",
        estimated_labor_hours=14, estimated_parts_cost=2500.00,
    )
    version_at_create = work_order["version"]

    validate_success(
        api.create_dispatch(
            work_order["id"],
            {"vendor_id": vendor["id"],
             "expected_work_order_version": version_at_create},
            FM,
        ),
        201,
    )

    reread = read_work_order(work_order["id"])
    assert reread["status"] == "DISPATCHED"
    assert reread["version"] == version_at_create + 1


def test_minimum_callout_charge_floors_a_tiny_estimate(api):
    """PRD §3.4: "Sum the labour component, the surcharge, and the billed parts to get
    a gross figure — but never let the gross fall below the minimum call-out charge of
    150.00; if the sum is below that, the gross is 150.00."

    Design: Corner/calculations/min_callout_amount_floors_a_tiny_estimate
    """
    set_clock("2026-05-04T09:00:00Z")
    building = create_building()

    response = api.create_work_order(
        work_order_payload(building["id"], wo_type="CORRECTIVE", priority="P4",
                           estimated_labor_hours=0.5, estimated_parts_cost=0),
        FM,
    )
    data = validate_success(response, 201)
    assert_work_order(data)

    # 0.5h * 80.00 = 40.00 of labour, no P4 surcharge and no parts — below the floor.
    assert data["estimated_amount"] == pytest.approx(150.00, abs=0.01)


# ---------------------------------------------------------------------------
# The capital funding ledger
# ---------------------------------------------------------------------------
def test_contingency_tier_is_keyed_on_base_cost_not_the_derived_budget(api):
    """PRD §3.3: "First it selects a `contingency_pct` from the base cost alone: 0.10
    if `base_cost` is at most 100,000; otherwise 0.07 if it is at most 500,000;
    otherwise 0.05."
    PRD §3.3: "The lookup key is always the *base* cost and never the derived budget —
    the tiers may look circular, but they are not."
    PRD §3.3: "Second, `contingency_amount` is the base cost multiplied by that
    percentage, rounded half up to 2 decimal places. Third, `budget_amount` is the base
    cost plus the contingency amount, rounded half up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/capital_contingency_tier_keyed_on_base_cost_not_budget
    """
    building = create_building()

    response = api.create_capital_project(
        capital_project_payload(building["id"], title="Chiller replacement",
                                base_cost=95000.00),
        make_facility_manager_headers("fm-1"),
    )
    data = validate_success(response, 201)
    assert_capital_project(data)

    # 95000.00 sits under the 100,000 edge on the BASE, so the tier is 0.10 —
    # a budget-keyed lookup on the resulting 104500.00 would wrongly select 0.07.
    assert data["contingency_pct"] == pytest.approx(0.10, abs=0.0001)
    assert data["contingency_amount"] == pytest.approx(9500.00, abs=0.01)
    assert data["budget_amount"] == pytest.approx(104500.00, abs=0.01)
    assert data["budget_amount"] != pytest.approx(101650.00, abs=0.01)


def test_new_project_remaining_equals_budget_and_records_its_proposer(api):
    """PRD §3.3: "Fourth, `remaining_amount` is the budget amount less
    `committed_amount` less `spent_amount`, rounded half up to 2 decimal places; both
    of those start at zero on a new project, so a fresh project's remaining amount
    equals its budget. The project's `proposed_by_user_id` is recorded from the
    caller's `X-User-ID`."
    PRD §3.3: "The project starts in `PROPOSED`."

    Design: Difficulty/combinatorial_formula/capital_contingency_tier_keyed_on_base_cost_not_budget
    """
    building = create_building()

    response = api.create_capital_project(
        capital_project_payload(building["id"], title="Chiller replacement",
                                base_cost=95000.00),
        make_facility_manager_headers("fm-1"),
    )
    data = validate_success(response, 201)
    assert_capital_project(data)

    assert data["remaining_amount"] == pytest.approx(104500.00, abs=0.01)
    assert data["committed_amount"] == pytest.approx(0, abs=0.01)
    assert data["spent_amount"] == pytest.approx(0, abs=0.01)
    assert data["status"] == "PROPOSED"
    assert data["proposed_by_user_id"] == "fm-1"
    assert_capital_funding_invariant(data)


def test_funded_work_order_commits_its_estimate_and_pulls_project_in_flight(api):
    """PRD §3.3: "The first work order that names an `APPROVED` project as its funder
    pulls the project `APPROVED → IN_FLIGHT`, and the project's committed amount rises
    by that order's estimate."
    PRD §2.10: "The second is capital funding: for any capital project, `budget_amount`
    minus `committed_amount` minus `spent_amount` always equals `remaining_amount`, and
    every work order that draws on a project either eventually charges the project (on
    closure) or hands the money back (on cancellation, or on the estimate being
    revised)."

    Design: Difficulty/compensating_invariant/capital_funds_conserved_across_work_order_create_and_cancel
    """
    ctx = setup_approved_project(clock="2026-05-04T09:00:00Z", base_cost=1000.00)
    project = ctx["project"]
    assert project["budget_amount"] == pytest.approx(1100.00, abs=0.01)

    work_order = create_work_order(
        ctx["building"]["id"], wo_type="CORRECTIVE", priority="P3",
        estimated_labor_hours=5, estimated_parts_cost=0,
        funding_project_id=project["id"],
    )
    # 5h * 80.00 = 400.00, no P3 surcharge, no parts.
    assert work_order["estimated_amount"] == pytest.approx(400.00, abs=0.01)

    after = read_capital_project(project["id"])
    assert_capital_project(after)
    assert after["status"] == "IN_FLIGHT"
    assert after["committed_amount"] == pytest.approx(400.00, abs=0.01)
    assert after["remaining_amount"] == pytest.approx(700.00, abs=0.01)
    assert after["spent_amount"] == pytest.approx(0, abs=0.01)
    assert_capital_funding_invariant(after)


def test_cancelling_a_funded_order_releases_the_commitment_with_zero_drift(api):
    """PRD §3.6: "Cancellation is the compensating action for the funding invariant: if
    the order named a funding project, the project's `committed_amount` falls by the
    order's `estimated_amount` and its `remaining_amount` is restored to exactly its
    pre-creation value, while `spent_amount` is left untouched — the money was never
    spent."
    PRD §2.10: "The second is capital funding: for any capital project, `budget_amount`
    minus `committed_amount` minus `spent_amount` always equals `remaining_amount`, and
    every work order that draws on a project either eventually charges the project (on
    closure) or hands the money back (on cancellation, or on the estimate being
    revised)."

    Design: Difficulty/compensating_invariant/capital_funds_conserved_across_work_order_create_and_cancel
    """
    ctx = setup_approved_project(clock="2026-05-04T09:00:00Z", base_cost=1000.00)
    project = ctx["project"]
    work_order = create_work_order(
        ctx["building"]["id"], wo_type="CORRECTIVE", priority="P3",
        estimated_labor_hours=5, estimated_parts_cost=0,
        funding_project_id=project["id"],
    )

    cancelled = validate_success(api.cancel_work_order(work_order["id"], FM))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["estimated_amount"] == pytest.approx(400.00, abs=0.01), (
        "the released amount is exactly what was committed"
    )

    after = read_capital_project(project["id"])
    assert after["committed_amount"] == pytest.approx(0, abs=0.01)
    assert after["remaining_amount"] == pytest.approx(1100.00, abs=0.01)
    assert after["spent_amount"] == pytest.approx(0, abs=0.01)
    assert_capital_funding_invariant(after)


def test_work_order_naming_a_proposed_project_is_not_fundable(api):
    """PRD §3.3: "Either way, a shortfall is refused with `ERR_PROJECT_BUDGET_EXCEEDED`
    (HTTP 402), and a work order naming a project whose status is neither `APPROVED`
    nor `IN_FLIGHT` is refused earlier, with `ERR_PROJECT_NOT_FUNDABLE`."

    Design: Corner/validations/work_order_funded_by_unapproved_project_rejected
    """
    set_clock("2026-05-04T09:00:00Z")
    building = create_building()
    project = propose_capital_project(building["id"], proposer_id="fm-1",
                                      title="Lobby refit", base_cost=1000.00)
    assert project["status"] == "PROPOSED"

    response = api.create_work_order(
        work_order_payload(building["id"], wo_type="CORRECTIVE", priority="P3",
                           estimated_labor_hours=2, estimated_parts_cost=0,
                           funding_project_id=project["id"]),
        FM,
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FUNDABLE.value)
    assert response.status_code == 409

    after = read_capital_project(project["id"])
    assert after["status"] == "PROPOSED"
    assert after["committed_amount"] == pytest.approx(0, abs=0.01)
    assert after["remaining_amount"] == pytest.approx(1100.00, abs=0.01)


def test_work_order_exceeding_project_remaining_budget_is_refused(api):
    """PRD §3.3: "Nothing may over-draw the project. Whenever a work order names a
    `funding_project_id`, the project's remaining amount must cover the order's newly
    computed `estimated_amount`. At creation time that means the project's remaining
    amount must be at least the new estimate."
    PRD §3.3: "Either way, a shortfall is refused with `ERR_PROJECT_BUDGET_EXCEEDED`
    (HTTP 402), and a work order naming a project whose status is neither `APPROVED`
    nor `IN_FLIGHT` is refused earlier, with `ERR_PROJECT_NOT_FUNDABLE`."

    Design: Corner/validations/work_order_exceeding_project_remaining_budget_rejected
    """
    ctx = setup_approved_project(clock="2026-05-04T09:00:00Z", base_cost=1000.00)
    project = ctx["project"]

    first = create_work_order(
        ctx["building"]["id"], wo_type="CORRECTIVE", priority="P3",
        estimated_labor_hours=10, estimated_parts_cost=0,
        funding_project_id=project["id"],
    )
    # 10h * 80.00 = 800.00 committed against a 1100.00 budget, leaving 300.00.
    assert first["estimated_amount"] == pytest.approx(800.00, abs=0.01)
    assert read_capital_project(project["id"])["remaining_amount"] == pytest.approx(
        300.00, abs=0.01
    )

    response = api.create_work_order(
        work_order_payload(ctx["building"]["id"], wo_type="CORRECTIVE", priority="P3",
                           estimated_labor_hours=10, estimated_parts_cost=0,
                           funding_project_id=project["id"]),
        FM,
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_BUDGET_EXCEEDED.value)
    assert response.status_code == 402

    after = read_capital_project(project["id"])
    assert after["committed_amount"] == pytest.approx(800.00, abs=0.01), (
        "the refused order must not have moved the ledger"
    )
    assert after["status"] == "IN_FLIGHT"
    assert_capital_funding_invariant(after)
