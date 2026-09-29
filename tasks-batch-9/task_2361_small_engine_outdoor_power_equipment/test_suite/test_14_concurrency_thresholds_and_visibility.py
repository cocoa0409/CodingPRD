"""Version guards, cumulative thresholds, re-basing and immediate visibility.

Every test builds its own state from an empty database through the documented
endpoints only.
"""

import pytest

from test_helpers import (
    HTTP_STATUS_CODES,
    ApiErrorId,
    api_client,
    assert_build_order_unit_conservation,
    assert_lot_piece_conservation,
    assert_version_advanced_by,
    build_allocatable_plant,
    build_and_release_unit,
    build_engine_platform,
    build_production_ready_plant,
    build_service_part,
    certify_family,
    complete_durability_run,
    create_durability_test_payload,
    create_parts_request_payload,
    hot_test_unit,
    plan_build_order,
    read_build_order,
    read_durability_run,
    read_family,
    read_lot,
    read_model,
    read_platform,
    read_service_part,
    record_line_audit,
    record_torque,
    release_build_order,
    run_allocations_payload,
    schedule_durability_run,
    schedule_line_audit,
    set_clock,
    stage_engine_unit,
    submit_family,
    validate_error,
    validate_paginated,
    validate_success,
)


def _expect_error(response, error_id: ApiErrorId) -> dict:
    """Assert the documented error identifier and its documented HTTP status."""
    return validate_error(
        response, error_id.value, HTTP_STATUS_CODES[error_id.value]
    )


class TestFamilyVersionGuard:
    """Scheduling a durability run proves the client saw the current family."""

    def test_stale_family_version_is_refused_then_accepted_after_a_fresh_read(
        self, family_with_platform, certification_engineer_headers
    ):
        """
        PRD §2.10: "A `POST /durability-tests` request must carry `expected_certification_family_version` — a non-optional input field — holding the client's last observed `version` of the target `CertificationFamily`."
        PRD §2.10: "Scheduling a new durability run supersedes the family's prior deterioration basis, so if the family's `version` has advanced since the client read it, the create is rejected with `ERR_STALE_FAMILY_VERSION` (HTTP 412), preventing the client from displacing a run it never observed."
        PRD §2.10: "Note that scheduling a run itself increments the family's `version` by 1, which is precisely why a client that schedules two runs back to back must re-read the family between them."
        PRD §3.2: "Three things then happen to the surrounding graph: the family advances to `DURABILITY_TESTING` (from `DRAFT` or from `AUDIT_HOLD`; a family already in `DURABILITY_TESTING` stays there and simply carries an additional scheduled run), the family's `version` increments by 1, and every platform of the family has its `certification_posture` recomputed, landing on `RESTRICTED`."
        PRD §3.2: "The window must not overlap any other run on the same platform whose status is `SCHEDULED` or `COMPLETED`; overlap is judged on the half-open interval, so two windows that merely touch at an endpoint — one ending exactly where the next begins — are both accepted, while any genuine overlap is refused with `ERR_PLATFORM_TEST_WINDOW_OVERLAP`."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_family_version_is_refused_then_retried_fresh
        """
        family_id = family_with_platform.family_id
        platform_id = family_with_platform.platform_id
        first_observed_version = read_family(family_id)["version"]

        first_run = validate_success(
            api_client.create_durability_test(
                create_durability_test_payload(
                    family_id, platform_id, first_observed_version
                ),
                certification_engineer_headers,
            ),
            201,
        )
        assert first_run["status"] == "SCHEDULED"

        after_first = read_family(family_id)
        assert_version_advanced_by(
            first_observed_version,
            after_first["version"],
            1,
            "CertificationFamily",
        )
        assert after_first["status"] == "DURABILITY_TESTING"
        assert read_platform(platform_id)["certification_posture"] == "RESTRICTED"

        refused = api_client.create_durability_test(
            create_durability_test_payload(
                family_id,
                platform_id,
                first_observed_version,
                scheduled_start_at="2026-08-24T09:00:00Z",
                scheduled_end_at="2026-09-14T09:00:00Z",
            ),
            certification_engineer_headers,
        )
        _expect_error(refused, ApiErrorId.ERR_STALE_FAMILY_VERSION)

        _, refused_meta = validate_paginated(
            api_client.list_durability_tests(
                certification_engineer_headers, {"limit": 10, "offset": 0}
            )
        )
        assert refused_meta["total_count"] == 1
        assert read_family(family_id)["version"] == after_first["version"]

        fresh_version = read_family(family_id)["version"]
        second_run = validate_success(
            api_client.create_durability_test(
                create_durability_test_payload(
                    family_id,
                    platform_id,
                    fresh_version,
                    scheduled_start_at="2026-08-24T09:00:00Z",
                    scheduled_end_at="2026-09-14T09:00:00Z",
                ),
                certification_engineer_headers,
            ),
            201,
        )
        assert second_run["status"] == "SCHEDULED"
        assert second_run["df_method"] == "MULTIPLICATIVE"

        final_family = read_family(family_id)
        assert_version_advanced_by(
            fresh_version, final_family["version"], 1, "CertificationFamily"
        )
        assert final_family["status"] == "DURABILITY_TESTING"
        assert read_platform(platform_id)["certification_posture"] == "RESTRICTED"

        _, final_meta = validate_paginated(
            api_client.list_durability_tests(
                certification_engineer_headers, {"limit": 10, "offset": 0}
            )
        )
        assert final_meta["total_count"] == 2


class TestBuildOrderVersionGuard:
    """An allocation run proves the client saw the current pool."""

    def test_stale_build_order_version_is_refused_then_accepted_after_a_fresh_read(
        self, canonical_clock, production_planner_headers
    ):
        """
        PRD §2.10: "A `POST /build-orders/{id}/allocations/run` request must carry `expected_build_order_version` — likewise non-optional — holding the client's last observed `version` of the target `BuildOrder`."
        PRD §2.10: "A fresh allocation run replaces the standing dealer and mass-retail split, so if the order's `version` has advanced since the client read it, the run is rejected with `ERR_STALE_BUILD_ORDER_VERSION` (HTTP 412), preventing a client acting on a stale pool size from discarding a split another writer already committed."
        PRD §2.10: "A successful allocation run increments the order's `version` by 1."
        PRD §3.8: "When it is 1, that single unit goes to whichever bucket had the larger fractional part, and when the two fractional parts are equal the unit goes to the **dealer** bucket."
        PRD §2.11: "On a build order, the released population is conserved across channels: `built_quantity` always equals `allocated_dealer_units` plus `allocated_mass_retail_units` plus `unallocated_units`."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_build_order_version_is_refused_then_retried_fresh
        """
        scenario = build_production_ready_plant()
        order = plan_build_order(
            scenario.model_id, scenario.line_id, planned_quantity=1
        )
        version_at_plan_time = order["version"]
        scenario.build_order = release_build_order(order["id"])
        build_and_release_unit(scenario, "SN-0001")

        live = read_build_order(order["id"])
        assert live["built_quantity"] == 1
        assert live["unallocated_units"] == 1
        assert live["allocation_status"] == "UNALLOCATED"
        assert live["version"] > version_at_plan_time

        _expect_error(
            api_client.run_build_order_allocations(
                order["id"],
                run_allocations_payload(version_at_plan_time),
                production_planner_headers,
            ),
            ApiErrorId.ERR_STALE_BUILD_ORDER_VERSION,
        )
        _expect_error(
            api_client.run_build_order_allocations(
                order["id"],
                run_allocations_payload(live["version"] - 1),
                production_planner_headers,
            ),
            ApiErrorId.ERR_STALE_BUILD_ORDER_VERSION,
        )

        between = read_build_order(order["id"])
        assert between["version"] == live["version"]
        assert between["allocated_dealer_units"] == 0
        assert between["allocated_mass_retail_units"] == 0
        assert between["unallocated_units"] == 1
        assert between["allocation_status"] == "UNALLOCATED"
        assert between["allocation_run_at"] is None

        allocated = validate_success(
            api_client.run_build_order_allocations(
                order["id"],
                run_allocations_payload(between["version"]),
                production_planner_headers,
            ),
            200,
        )
        assert allocated["allocated_dealer_units"] == 1
        assert allocated["allocated_mass_retail_units"] == 0
        assert allocated["unallocated_units"] == 0
        assert allocated["allocation_status"] == "ALLOCATED"
        assert allocated["allocation_run_at"] is not None
        assert_version_advanced_by(
            between["version"], allocated["version"], 1, "BuildOrder"
        )
        assert_build_order_unit_conservation(allocated)

        _expect_error(
            api_client.run_build_order_allocations(
                order["id"],
                run_allocations_payload(between["version"]),
                production_planner_headers,
            ),
            ApiErrorId.ERR_STALE_BUILD_ORDER_VERSION,
        )


class TestCumulativeAuditFailureThreshold:
    """The second failure is the one that suspends the family for good."""

    def test_second_audit_failure_suspends_the_family_and_freezes_its_platforms(
        self, canonical_clock, certification_engineer_headers
    ):
        """
        PRD §3.8: "Its `cumulative_audit_failures` rises by 1."
        PRD §3.8: "If the resulting count is still below 2, the family moves to `AUDIT_HOLD` and its `audit_hold_at` is stamped from the clock."
        PRD §3.8: "If the resulting count reaches 2, the family instead moves to the terminal `SUSPENDED`."
        PRD §3.8: "Every engine platform of that family has its `certification_posture` recomputed by the projection of §2.7, landing on `RESTRICTED` for an `AUDIT_HOLD` family and on the terminal `FROZEN` for a `SUSPENDED` one."
        PRD §3.8: "Every product model sitting on those platforms whose `status` is `RELEASED` moves to `SUSPENDED`, which blocks new build orders against it."
        PRD §3.8: "Every build order of those models whose status is `PLANNED`, `RELEASED` or `IN_PRODUCTION` moves to `HELD`, with its prior status captured in `status_before_hold` and `held_reason` set to `FAMILY_AUDIT_HOLD`."
        PRD §3.8: "When the family went to `SUSPENDED` instead, the sweep additionally picks up orders that were already `HELD`, and `held_reason` is set to `FAMILY_SUSPENDED`."
        PRD §3.8: "For every order newly moved to `HELD`, `allocated_dealer_units` and `allocated_mass_retail_units` are reset to 0, `unallocated_units` is set to the full `built_quantity`, and `allocation_status` returns to `UNALLOCATED` — the standing channel position is torn up because the goods can no longer be shipped."
        PRD §3.8: "Otherwise, when a rate breach holds, the audit is `FAILED` with `failure_reason` `FAILURE_RATE_EXCEEDED`."
        PRD §3.1: "Any operation attempted against a family whose status does not admit it — and every operation on a `SUSPENDED` family — is refused with `ERR_FAMILY_STATE_INVALID`."

        Design: Corner/cross_cutting_complexity_layers/family_suspension_at_the_cumulative_audit_failure_threshold
        """
        scenario = build_allocatable_plant(released_units=2)
        order = scenario.refresh_build_order()
        assert order["status"] == "IN_PRODUCTION"
        assert order["built_quantity"] == 2

        first_audit = schedule_line_audit(order["id"], "2026-09-14")
        first_result = record_line_audit(
            first_audit["id"],
            units_tested=2,
            units_failed=2,
            max_measured_emission_g_per_kwh=5.60,
        )
        assert first_result["status"] == "FAILED"
        assert first_result["failure_reason"] == "FAILURE_RATE_EXCEEDED"
        assert first_result["failure_rate"] == pytest.approx(1.0000, abs=0.01)

        held_family = read_family(scenario.family_id)
        assert held_family["status"] == "AUDIT_HOLD"
        assert held_family["cumulative_audit_failures"] == 1
        assert held_family["audit_hold_at"] is not None
        assert read_platform(scenario.platform_id)["certification_posture"] == "RESTRICTED"
        assert read_model(scenario.model_id)["status"] == "SUSPENDED"

        held_order = read_build_order(order["id"])
        assert held_order["status"] == "HELD"
        assert held_order["held_reason"] == "FAMILY_AUDIT_HOLD"
        assert held_order["status_before_hold"] == "IN_PRODUCTION"
        assert held_order["allocated_dealer_units"] == 0
        assert held_order["allocated_mass_retail_units"] == 0
        assert held_order["unallocated_units"] == 2
        assert held_order["allocation_status"] == "UNALLOCATED"
        assert_build_order_unit_conservation(held_order)

        second_audit = schedule_line_audit(order["id"], "2026-09-21")
        assert second_audit["required_sample_size"] == 2
        second_result = record_line_audit(
            second_audit["id"],
            units_tested=2,
            units_failed=1,
            max_measured_emission_g_per_kwh=5.60,
        )
        assert second_result["status"] == "FAILED"
        assert second_result["failure_reason"] == "FAILURE_RATE_EXCEEDED"
        assert second_result["failure_rate"] == pytest.approx(0.5000, abs=0.01)

        suspended_family = read_family(scenario.family_id)
        assert suspended_family["status"] == "SUSPENDED"
        assert suspended_family["cumulative_audit_failures"] == 2
        assert read_platform(scenario.platform_id)["certification_posture"] == "FROZEN"
        assert read_model(scenario.model_id)["status"] == "SUSPENDED"

        suspended_order = read_build_order(order["id"])
        assert suspended_order["status"] == "HELD"
        assert suspended_order["held_reason"] == "FAMILY_SUSPENDED"

        _expect_error(
            api_client.create_durability_test(
                create_durability_test_payload(
                    scenario.family_id,
                    scenario.platform_id,
                    suspended_family["version"],
                    scheduled_start_at="2026-09-28T09:00:00Z",
                    scheduled_end_at="2026-10-19T09:00:00Z",
                ),
                certification_engineer_headers,
            ),
            ApiErrorId.ERR_FAMILY_STATE_INVALID,
        )


class TestFamilyBasisReBasing:
    """The family's stored basis follows the most recently completed run."""

    def test_family_basis_re_bases_to_the_latest_completed_run(
        self, family_with_platform
    ):
        """
        PRD §3.2: "Because a family can carry several scheduled runs, two clarifications matter: the family reaches `DURABILITY_COMPLETE` on the *first* completion, and the family's stored deterioration figures always come from the *most recently completed* run of that family, ordered by `completed_at` descending and, for ties, by `created_at` descending, with runs still in `SCHEDULED` excluded from consideration entirely."
        PRD §3.2: "Under `MULTIPLICATIVE`, the deterioration factor is 1 plus the quantity (the raw factor minus 1) multiplied by the scaling factor."
        PRD §3.2: "Under `MULTIPLICATIVE`, the certified emission is the family's `declared_baseline_emission_g_per_kwh` multiplied by the rounded deterioration factor."
        PRD §3.2: "The compliance margin is the family's `family_emission_limit_g_per_kwh` minus the rounded certified emission, divided by that same `family_emission_limit_g_per_kwh`, multiplied by 100, and rounded half up to 2 decimal places."
        PRD §3.2: "The three results are written to the family as `deterioration_factor`, `certified_emission_g_per_kwh` and `compliance_margin_pct`, and the family advances to `DURABILITY_COMPLETE`."
        PRD §3.2: "The run's `extrapolated` flag is set true exactly when `accumulated_hours` is strictly less than the family's `durability_hours`, and false otherwise."

        Design: Corner/cross_cutting_complexity_layers/family_basis_re_bases_to_the_latest_completed_durability_run
        """
        family_id = family_with_platform.family_id
        first_platform_id = family_with_platform.platform_id
        second_platform = build_engine_platform(
            family_id, platform_code="210SS", displacement_cc=210
        )

        first_run = schedule_durability_run(family_id, first_platform_id)
        second_run = schedule_durability_run(family_id, second_platform["id"])

        completed_first = complete_durability_run(
            first_run["id"], accumulated_hours=500, final_emission_g_per_kwh=6.40
        )
        assert completed_first["status"] == "COMPLETED"
        assert completed_first["extrapolated"] is False
        assert completed_first["computed_deterioration_factor"] == pytest.approx(
            1.2800, abs=0.01
        )

        after_first = read_family(family_id)
        assert after_first["status"] == "DURABILITY_COMPLETE"
        assert after_first["deterioration_factor"] == pytest.approx(1.2800, abs=0.01)
        assert after_first["certified_emission_g_per_kwh"] == pytest.approx(
            5.12, abs=0.01
        )
        assert after_first["compliance_margin_pct"] == pytest.approx(36.00, abs=0.01)

        set_clock("2026-08-04T08:00:00Z")
        completed_second = complete_durability_run(
            second_run["id"], accumulated_hours=500, final_emission_g_per_kwh=7.20
        )
        assert completed_second["computed_deterioration_factor"] == pytest.approx(
            1.4400, abs=0.01
        )

        after_second = read_family(family_id)
        assert after_second["status"] == "DURABILITY_COMPLETE"
        assert after_second["deterioration_factor"] == pytest.approx(1.4400, abs=0.01)
        assert after_second["certified_emission_g_per_kwh"] == pytest.approx(
            5.76, abs=0.01
        )
        assert after_second["compliance_margin_pct"] == pytest.approx(28.00, abs=0.01)

        untouched = read_durability_run(first_run["id"])
        assert untouched["computed_deterioration_factor"] == pytest.approx(
            1.2800, abs=0.01
        )

        submit_family(family_id)
        certified = certify_family(family_id)
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_emission_g_per_kwh"] == pytest.approx(5.76, abs=0.01)
        assert certified["compliance_margin_pct"] == pytest.approx(28.00, abs=0.01)


class TestImmediateVisibilityOfDerivedFields:
    """Derived values are readable from the response of the write that set them."""

    def test_every_derived_field_is_visible_in_the_same_response(
        self, canonical_clock, quality_engineer_headers, channel_partner_headers
    ):
        """
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.7: "The unit's `hot_test_emission_threshold` is derived from the certified emission of the family owning its platform, multiplied by a factor and rounded half up to 2 decimal places."
        PRD §3.7: "For an ordinary unit the factor is 1.10, allowing a ten percent production allowance above the certified value."
        PRD §3.7: "The `build_state` advances `ASSEMBLED → HOT_TESTED` either way, and `conformance_state` becomes `CONFORMING` when both comparisons hold and `NONCONFORMING` when either fails."
        PRD §3.7: "The unit reaches the terminal `RELEASED` build state with `released_at` stamped from the clock, the order's `built_quantity` rises by 1 while `staged_quantity` falls by 1, and the unit joins the order's allocation pool."
        PRD §3.7: "When the release brings `built_quantity` up to the order's `planned_quantity`, the order transitions `IN_PRODUCTION → COMPLETED` in the same request; a `COMPLETED` order accepts no further units, though allocation runs remain permitted on it."
        PRD §2.11: "On a component lot, the pieces released to the line are conserved: `accepted_qty` always equals `consumed_qty` plus `remaining_qty`."
        PRD §3.9: "The request is minted in `BACKORDERED` and settles within the very same call when stock allows: if the part's `on_hand_qty` is at least `requested_quantity`, the request becomes `FILLED`, its `shipped_from_part_id` is set to the part it was requested from, and the part's `on_hand_qty` is reduced by `requested_quantity`."
        PRD §3.9: "That last point is worth stressing: a part with no requests at all has no fill rate, not a fill rate of 0.00."
        PRD §3.9: "Otherwise it is the served count divided by the total, multiplied by 100, rounded half up to 2 decimal places."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response
        """
        scenario = build_production_ready_plant()
        order = plan_build_order(
            scenario.model_id, scenario.line_id, planned_quantity=1
        )
        scenario.build_order = release_build_order(order["id"])

        unit = stage_engine_unit(scenario, "SN-0001")
        assert unit["build_state"] == "STAGED"
        assert unit["conformance_state"] == "PENDING"
        assert unit["deviation_sourced"] is False

        torqued = record_torque(unit["id"])
        assert torqued["build_state"] == "ASSEMBLED"
        assert torqued["out_of_spec_fastener_count"] == 0
        assert torqued["conformance_state"] == "PENDING"

        hot_tested = hot_test_unit(unit["id"])
        assert hot_tested["build_state"] == "HOT_TESTED"
        assert hot_tested["conformance_state"] == "CONFORMING"
        assert hot_tested["hot_test_emission_threshold"] == pytest.approx(
            5.63, abs=0.01
        )

        released = validate_success(
            api_client.release_engine_unit(unit["id"], quality_engineer_headers), 200
        )
        assert released["build_state"] == "RELEASED"
        assert released["conformance_state"] == "CONFORMING"
        assert released["released_at"] is not None

        completed_order = read_build_order(order["id"])
        assert completed_order["status"] == "COMPLETED"
        assert completed_order["built_quantity"] == 1
        assert completed_order["staged_quantity"] == 0
        assert completed_order["unallocated_units"] == 1
        assert_build_order_unit_conservation(completed_order)

        carburetor_lot = read_lot(scenario.carburetor_lot_id)
        assert carburetor_lot["accepted_qty"] == 800
        assert carburetor_lot["consumed_qty"] == 1
        assert carburetor_lot["remaining_qty"] == 799
        assert_lot_piece_conservation(carburetor_lot)

        part = build_service_part(scenario.platform_id, on_hand_qty=1)
        assert part["fill_rate_pct"] is None

        request = validate_success(
            api_client.create_parts_request(
                create_parts_request_payload(part["id"]), channel_partner_headers
            ),
            201,
        )
        assert request["status"] == "FILLED"
        assert request["shipped_from_part_id"] == part["id"]
        assert request["promised_ship_date"] == "2026-08-05"

        refreshed_part = read_service_part(part["id"])
        assert refreshed_part["on_hand_qty"] == 0
        assert refreshed_part["filled_request_count"] == 1
        assert refreshed_part["backordered_request_count"] == 0
        assert refreshed_part["fill_rate_pct"] == pytest.approx(100.00, abs=0.01)
