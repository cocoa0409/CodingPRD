"""The retirement cascade, project bundling, and refresh-health FCI band
boundaries."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_project_bundle,
    create_asset_system,
    create_deficiency,
    create_draft_plan,
    create_facility,
    create_project_bundle_payload,
    create_scenario,
    get_capital_plan,
    get_facility,
    list_line_items,
    remediate_to_corrected,
    run_scenario,
    setup_facility_with_system,
    setup_system_with_deficiency,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CONSULTANT, MANAGER, PLANNER


class TestRetirementCascade:
    def test_retire_cascades_to_line_item_and_plan_total(self, api):
        """PRD §3.8: "Retirement moves the system to the terminal `RETIRED`
        state, recomputes the facility's `current_replacement_value_cents`
        (which now excludes the retired system) and
        `facility_condition_index`, and sweeps the plan layer: any line item
        that references a deficiency of the retired system, has
        `funding_status` of `FUNDED`, and belongs to a plan still in `DRAFT`
        is moved to `REMOVED`, after which that plan's
        `total_programmed_cents` is recomputed."
        PRD §2.4: "When a facility has no live systems — that is, when the
        current replacement value is zero — the index is defined as 0 rather
        than being undefined."

        Design: Difficulty/transitive_cascade/retire_system_cascades_to_line_item_and_plan_total
        """
        facility = create_facility()
        sys1 = create_asset_system(
            facility["id"], system_category="ROOF", name="Roof A",
            install_year=2005, design_life_years=25,
            replacement_cost_cents=500000000, condition_rating=3)
        sys2 = create_asset_system(
            facility["id"], system_category="INTERIOR", name="Finishes",
            install_year=2015, design_life_years=15,
            replacement_cost_cents=300000000, condition_rating=4)
        deficiency = create_deficiency(
            sys1["id"], description="Membrane failure",
            cost_estimate_cents=10000000, severity=3, urgency=3,
            recommended_year=2027)
        plan = create_draft_plan(facility["id"], title="P", start_year=2027,
                                 horizon_years=2)
        scenario = create_scenario(plan["id"], name="Flat",
                                   annual_budget_cents=50000000,
                                   escalation_rate=0.0)
        run_scenario(scenario["id"])
        plan_mid = get_capital_plan(plan["id"])
        assert plan_mid["total_programmed_cents"] == 10000000

        # Correct the finding so the retire precondition passes.
        remediate_to_corrected(deficiency["id"])

        retired = validate_success(api.retire_asset_system(sys1["id"],
                                                           MANAGER))
        assert retired["status"] == "RETIRED"

        items = list_line_items(plan["id"])
        assert len(items) == 1
        assert items[0]["deficiency_id"] == deficiency["id"]
        assert items[0]["funding_status"] == "REMOVED", (
            "link 1: retire moves the DRAFT plan's FUNDED item to REMOVED")

        plan_after = get_capital_plan(plan["id"])
        assert plan_after["total_programmed_cents"] == 0, (
            "link 2: the item removal recomputes the plan total")

        facility_after = get_facility(facility["id"])
        assert facility_after["current_replacement_value_cents"] == 300000000, (
            "RETIRED systems are excluded from the CRV; only S2 remains")
        assert facility_after["backlog_cost_cents"] == 0
        assert facility_after["facility_condition_index"] == pytest.approx(
            0.0, abs=1e-9)

    def test_retire_leaves_items_on_non_draft_plans_untouched(self, api):
        """PRD §3.8: "any line item that references a deficiency of the
        retired system, has `funding_status` of `FUNDED`, and belongs to a
        plan still in `DRAFT` is moved to `REMOVED`, after which that plan's
        `total_programmed_cents` is recomputed."

        Design: Difficulty/transitive_cascade/retire_system_cascades_to_line_item_and_plan_total
        """
        facility, system = setup_facility_with_system(
            {"system_category": "ROOF", "name": "Roof A", "install_year": 2005,
             "design_life_years": 25, "replacement_cost_cents": 500000000,
             "condition_rating": 3})
        deficiency = create_deficiency(
            system["id"], description="Membrane failure",
            cost_estimate_cents=10000000, severity=3, urgency=3,
            recommended_year=2027)
        plan = create_draft_plan(facility["id"], title="P", start_year=2027,
                                 horizon_years=2)
        scenario = create_scenario(plan["id"], name="Flat",
                                   annual_budget_cents=50000000,
                                   escalation_rate=0.0)
        run_scenario(scenario["id"])
        remediate_to_corrected(deficiency["id"])
        submitted = submit_plan(plan["id"])
        assert submitted["status"] == "SUBMITTED"

        retired = validate_success(api.retire_asset_system(system["id"],
                                                           MANAGER))
        assert retired["status"] == "RETIRED"

        items = list_line_items(plan["id"])
        assert len(items) == 1
        assert items[0]["funding_status"] == "FUNDED", (
            "the cascade reaches only plans still in DRAFT; a SUBMITTED "
            "plan's funded items are untouched")
        assert get_capital_plan(
            plan["id"])["total_programmed_cents"] == 10000000
        assert get_facility(
            facility["id"])["current_replacement_value_cents"] == 0


class TestProjectBundling:
    def test_attach_recomputes_bundled_cost(self, api):
        """PRD §3.8: "The attachment sets the item's `project_bundle_id` —
        which is otherwise null for unbundled work — and recomputes the
        bundle's `bundled_cost_cents` as the sum of `escalated_cost_cents`
        over the line items attached to it that remain `FUNDED`."
        PRD §3.8: "its `bundled_cost_cents` starts at 0."

        Design: Corner/endpoints/project_bundle_attach_recomputes_bundled_cost
        """
        facility, system = setup_facility_with_system(
            {"system_category": "ROOF", "name": "R", "install_year": 2005,
             "design_life_years": 25, "replacement_cost_cents": 300000000,
             "condition_rating": 3})
        d1 = create_deficiency(system["id"], description="d1",
                               cost_estimate_cents=10000000, severity=4,
                               urgency=4, recommended_year=2027)
        d2 = create_deficiency(system["id"], description="d2",
                               cost_estimate_cents=5000000, severity=2,
                               urgency=2, recommended_year=2027)
        plan = create_draft_plan(facility["id"], title="P", start_year=2027,
                                 horizon_years=1)
        scenario = create_scenario(plan["id"], name="S",
                                   annual_budget_cents=100000000,
                                   escalation_rate=0.0)
        run_scenario(scenario["id"])
        funded, _meta = validate_paginated(api.list_line_items(
            PLANNER, {"capital_plan_id": plan["id"],
                      "funding_status": "FUNDED"}))
        assert len(funded) == 2

        bundle = validate_success(api.create_project_bundle(
            create_project_bundle_payload(plan["id"], name="Phase 1 Roof",
                                          phase_number=1),
            PLANNER), 201)
        assert_project_bundle(bundle)
        assert bundle["bundled_cost_cents"] == 0

        for item in funded:
            assert item["project_bundle_id"] is None, "unbundled before attach"
            validate_success(api.attach_line_item(
                bundle["id"], {"plan_line_item_id": item["id"]}, PLANNER))

        after = validate_success(api.get_project_bundle(bundle["id"], PLANNER))
        assert after["bundled_cost_cents"] == 15000000, (
            "10000000 + 5000000 over the attached FUNDED items")
        for item in funded:
            refreshed = validate_success(api.get_line_item(item["id"],
                                                           PLANNER))
            assert refreshed["project_bundle_id"] == bundle["id"]

    def test_attach_line_item_from_other_plan_rejected(self, api):
        """PRD §3.8: "Two constraints guard the operation: the attached item
        must belong to the same capital plan as the bundle — cross-plan
        attachment is an `ERR_REFERENTIAL_CONFLICT`"

        Design: Corner/endpoints/attach_line_item_from_other_plan_rejected
        """
        facility, system = setup_facility_with_system(
            {"system_category": "ROOF", "name": "R", "install_year": 2005,
             "design_life_years": 25, "replacement_cost_cents": 300000000,
             "condition_rating": 3})
        create_deficiency(system["id"], description="d1",
                          cost_estimate_cents=10000000, severity=4, urgency=4,
                          recommended_year=2027)
        plan1 = create_draft_plan(facility["id"], title="P1", start_year=2027,
                                  horizon_years=1)
        plan2 = create_draft_plan(facility["id"], title="P2", start_year=2028,
                                  horizon_years=1)
        scenario = create_scenario(plan1["id"], name="S",
                                   annual_budget_cents=100000000,
                                   escalation_rate=0.0)
        run_scenario(scenario["id"])
        items_p1 = list_line_items(plan1["id"])
        assert len(items_p1) == 1

        bundle = validate_success(api.create_project_bundle(
            create_project_bundle_payload(plan2["id"], name="B2 bundle",
                                          phase_number=1),
            PLANNER), 201)
        resp = api.attach_line_item(
            bundle["id"], {"plan_line_item_id": items_p1[0]["id"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_CONFLICT)
        assert validate_success(api.get_line_item(
            items_p1[0]["id"], PLANNER))["project_bundle_id"] is None


class TestRefreshHealthThresholds:
    def test_fci_exactly_at_watch_threshold_reports_watch(self, api):
        """PRD §3.9: "otherwise the stored four-decimal facility condition
        index is compared against two bands — an index of at least 0.10
        reports `CRITICAL`, an index of at least 0.05 reports `WATCH`, and
        anything below reports `GOOD`. A value exactly at a band threshold
        enters the worse band, because both comparisons are inclusive."

        Design: Difficulty/boundary_precision_check/fci_watch_threshold_exact_inclusion
        """
        _facility, _system, _deficiency = setup_system_with_deficiency(
            {"description": "Resurface", "cost_estimate_cents": 50000000,
             "severity": 2, "urgency": 2, "recommended_year": 2028},
            {"system_category": "SITE", "name": "Parking Lot",
             "install_year": 2018, "design_life_years": 20,
             "replacement_cost_cents": 1000000000, "condition_rating": 5})
        facility = get_facility(_facility["id"])
        # 50000000 / 1000000000 = 0.05 -> 0.0500 at 4dp.
        assert facility["facility_condition_index"] == pytest.approx(
            0.05, abs=1e-9)

        health = validate_success(api.get_refresh_health(_facility["id"],
                                                         CONSULTANT))
        assert health["health"] == "WATCH", (
            "0.0500 >= 0.05 enters WATCH; a strict-> comparison would "
            "wrongly report GOOD")
        assert health["stale_systems"] == 0
        assert health["total_systems"] == 1

    def test_just_below_watch_and_at_critical_thresholds(self, api):
        """PRD §3.9: "an index of at least 0.10 reports `CRITICAL`, an index
        of at least 0.05 reports `WATCH`, and anything below reports `GOOD`.
        A value exactly at a band threshold enters the worse band, because
        both comparisons are inclusive."

        Design: Difficulty/boundary_precision_check/fci_watch_threshold_exact_inclusion
        """
        # Facility 1: FCI 0.0499 -> below the WATCH band.
        f1, s1 = setup_facility_with_system(
            {"system_category": "SITE", "name": "Lot", "install_year": 2018,
             "design_life_years": 20, "replacement_cost_cents": 1000000000,
             "condition_rating": 5})
        create_deficiency(s1["id"], description="minor",
                          cost_estimate_cents=49900000, severity=2, urgency=2,
                          recommended_year=2028)
        f1 = get_facility(f1["id"])
        assert f1["facility_condition_index"] == pytest.approx(0.0499,
                                                               abs=1e-9)
        health1 = validate_success(api.get_refresh_health(f1["id"],
                                                          CONSULTANT))
        assert health1["health"] == "GOOD"

        # Facility 2: FCI exactly 0.1000 -> CRITICAL (inclusive).
        f2, s2 = setup_facility_with_system(
            {"system_category": "SITE", "name": "Lot", "install_year": 2018,
             "design_life_years": 20, "replacement_cost_cents": 1000000000,
             "condition_rating": 5})
        create_deficiency(s2["id"], description="major",
                          cost_estimate_cents=100000000, severity=3,
                          urgency=3, recommended_year=2028)
        f2 = get_facility(f2["id"])
        assert f2["facility_condition_index"] == pytest.approx(0.10,
                                                               abs=1e-9)
        health2 = validate_success(api.get_refresh_health(f2["id"],
                                                          CONSULTANT))
        assert health2["health"] == "CRITICAL"
