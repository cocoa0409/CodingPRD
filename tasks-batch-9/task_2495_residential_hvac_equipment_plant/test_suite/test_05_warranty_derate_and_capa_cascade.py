"""Warranty claims rescoring a platform, the derate table that cuts a supplier
lot, and the cascade that takes reserved kits back."""

import pytest

from test_helpers import (
    assert_effective_units_truncated,
    assert_instant_equals,
    assert_order_dimensions,
    assert_supplier_corrective_action,
    assert_supply_conservation,
    assert_warranty_claim,
    create_build_order_payload,
    file_claim,
    find_open_corrective_action,
    open_corrective_action_via_third_claim,
    read_order,
    read_platform,
    read_supply,
    setup_platform_two_claims_below_threshold,
    setup_warranty_capa_cascade_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestControlBoardDerateBand:
    """The worst rate band halves a control-board lot instead of stopping it."""

    def test_control_board_claim_in_the_top_band_cuts_the_pool_by_fifty_percent(
        self, api, supply_planner_headers
    ):
        """A rate of 10.00 or above: COMPRESSOR is cut 100 percent,
        CONTROL_BOARD is cut 50 percent. This table is likewise not the product
        of a component factor and a band factor.

        Design: Difficulty/combinatorial_formula/derate_matrix_control_board_band_10_plus_yields_50_not_100
        """
        scenario = setup_platform_two_claims_below_threshold(quantity_units=20)
        board_claim = file_claim(
            scenario["platform"]["id"],
            18200,
            failure_code="CONTROL_BOARD_FAULT",
            component_type="CONTROL_BOARD",
            supplier_lot_code="LOT-CTL-77",
        )
        assert_warranty_claim(board_claim)

        action = find_open_corrective_action(scenario["control_board"]["id"])
        assert_supplier_corrective_action(action)
        assert action["component_type"] == "CONTROL_BOARD"
        assert action["derate_pct"] == 50, (
            f"a control board is only ever halved, got {action['derate_pct']}"
        )
        assert float(action["trigger_claim_rate_pct"]) == pytest.approx(15.00, abs=0.005)
        assert action["cited_claim_count"] == 1, "only the board claim is swept in"
        assert action["warranty_claim_id"] == board_claim["id"]
        assert action["resolution"] is None
        assert action["closed_at"] is None

        pool = read_supply(scenario["control_board"]["id"])
        assert pool["status"] == "DERATED"
        assert pool["derate_pct"] == 50
        assert pool["effective_allocatable_units"] == 50
        assert pool["available_units"] == 50
        assert_effective_units_truncated(pool)
        assert_supply_conservation(pool)

    def test_three_claims_over_twenty_units_force_the_design_change_posture(
        self, api, warranty_analyst_headers
    ):
        """Once both gates are cleared the bands are evaluated from the top
        down: a rolling_claim_rate_pct of 10.00 or more yields
        DESIGN_CHANGE_REQUIRED; otherwise a rate of 5.00 or more yields
        CAPA_REQUIRED; otherwise OK.

        Design: Difficulty/combinatorial_formula/derate_matrix_control_board_band_10_plus_yields_50_not_100
        """
        scenario = setup_platform_two_claims_below_threshold(quantity_units=20)
        assert scenario["platform"]["warranty_posture"] == "OK", (
            "two claims are below the three-claim gate"
        )

        board_claim = file_claim(
            scenario["platform"]["id"],
            18200,
            failure_code="CONTROL_BOARD_FAULT",
            component_type="CONTROL_BOARD",
            supplier_lot_code="LOT-CTL-77",
        )

        platform = read_platform(scenario["platform"]["id"])
        assert platform["units_built_released"] == 20
        assert float(platform["rolling_claim_rate_pct"]) == pytest.approx(
            15.00, abs=0.005
        ), "three claims over twenty built units is 15.00 percent"
        assert platform["warranty_posture"] == "DESIGN_CHANGE_REQUIRED"

        claims, meta = validate_paginated(
            api.list_warranty_claims(
                warranty_analyst_headers, params={"platform_id": platform["id"]}
            )
        )
        assert meta["total_count"] == 3
        by_id = {row["id"]: row for row in claims}
        assert by_id[board_claim["id"]]["status"] == "LINKED_TO_CAPA"
        for earlier in scenario["claims"]:
            assert by_id[earlier["id"]]["status"] == "OPEN", (
                "a compressor claim is not swept into a control-board action"
            )

    def test_the_compressor_pool_of_the_same_platform_is_left_alone(
        self, api, supply_planner_headers
    ):
        """A compressor is a long-lead, single-source part, so a severe field
        rate stops the lot outright; a control board is second-sourced, so even
        the worst band only halves it, and the control-board column is flat at 25
        percent across the two lower bands while the compressor column is not.

        Design: Difficulty/combinatorial_formula/derate_matrix_control_board_band_10_plus_yields_50_not_100
        """
        scenario = setup_platform_two_claims_below_threshold(quantity_units=20)
        file_claim(
            scenario["platform"]["id"],
            18200,
            failure_code="CONTROL_BOARD_FAULT",
            component_type="CONTROL_BOARD",
            supplier_lot_code="LOT-CTL-77",
        )

        compressor = read_supply(scenario["compressor"]["id"])
        assert compressor["status"] == "ACTIVE"
        assert compressor["derate_pct"] == 0
        assert compressor["effective_allocatable_units"] == 100
        assert compressor["available_units"] == 100
        assert_supply_conservation(compressor)

        _, meta = validate_paginated(
            api.list_supply_corrective_actions(
                scenario["compressor"]["id"], supply_planner_headers
            )
        )
        assert meta["total_count"] == 0, (
            "the blamed component decides which pool is cut"
        )


class TestFivePercentThreshold:
    """Exactly five percent is on the corrective-action side of the line."""

    def test_rate_of_exactly_five_percent_yields_the_capa_posture(self, api):
        """The rolling_claim_rate_pct is then 100 multiplied by
        counted_claim_count, divided by denominator_units, rounded to two decimal
        places, and it is stored on the platform. Both thresholds are inclusive
        against the two-decimal rate, so exactly 5.00 percent is CAPA_REQUIRED
        while 4.99 percent is OK.

        Design: Difficulty/boundary_precision_check/claim_rate_of_exactly_five_percent_trips_capa_threshold
        """
        scenario = setup_platform_two_claims_below_threshold(quantity_units=60)
        open_corrective_action_via_third_claim(scenario["platform"]["id"], 40200)

        platform = read_platform(scenario["platform"]["id"])
        assert platform["units_built_released"] == 60
        assert float(platform["rolling_claim_rate_pct"]) == pytest.approx(
            5.00, abs=0.005
        ), "three claims over sixty built units is exactly 5.00 percent"
        assert platform["warranty_posture"] == "CAPA_REQUIRED"

    def test_the_lowest_band_cuts_a_compressor_lot_by_a_quarter(self, api):
        """A rate from 5.00 up to but not including 7.50: COMPRESSOR is cut 25
        percent, CONTROL_BOARD is cut 25 percent. Take the percentage that
        survives, which is 100 minus derate_pct, multiply the committed total by
        it, divide by 100, and truncate downward to a whole unit — a 25 percent
        cut of 101 units therefore leaves 75, not 75.75.

        Design: Difficulty/boundary_precision_check/claim_rate_of_exactly_five_percent_trips_capa_threshold
        """
        scenario = setup_platform_two_claims_below_threshold(quantity_units=60)
        third_claim = open_corrective_action_via_third_claim(
            scenario["platform"]["id"], 40200
        )

        action = find_open_corrective_action(scenario["compressor"]["id"])
        assert action["component_type"] == "COMPRESSOR"
        assert action["derate_pct"] == 25
        assert float(action["trigger_claim_rate_pct"]) == pytest.approx(5.00, abs=0.005)
        assert action["cited_claim_count"] == 3, (
            "all three claims of that lot are swept in"
        )
        assert action["warranty_claim_id"] == third_claim["id"]

        pool = read_supply(scenario["compressor"]["id"])
        assert pool["status"] == "DERATED"
        assert pool["derate_pct"] == 25
        assert pool["total_allocatable_units"] == 100
        assert pool["effective_allocatable_units"] == 75, (
            "a quarter cut of 100 committed units leaves 75 drawable"
        )
        assert pool["available_units"] == 75
        assert_effective_units_truncated(pool)

    def test_capa_posture_still_admits_a_new_build_lot(
        self, api, production_planner_headers
    ):
        """The two non-OK postures do different work: DESIGN_CHANGE_REQUIRED
        blocks the creation of any new build lot for that platform, as §3.8
        describes, while CAPA_REQUIRED does not block builds but does arm the
        supplier cascade below.

        Design: Difficulty/boundary_precision_check/claim_rate_of_exactly_five_percent_trips_capa_threshold
        """
        scenario = setup_platform_two_claims_below_threshold(quantity_units=60)
        open_corrective_action_via_third_claim(scenario["platform"]["id"], 40200)
        assert read_platform(scenario["platform"]["id"])["warranty_posture"] == (
            "CAPA_REQUIRED"
        )

        response = api.create_build_order(
            create_build_order_payload(scenario["platform"]["id"], quantity_units=10),
            production_planner_headers,
        )
        lot = validate_success(response, 201)
        assert lot["status"] == "DRAFT"
        assert lot["quantity_units"] == 10

    def test_shipped_basis_read_reports_a_different_rate_and_the_stored_posture(
        self, api, warranty_analyst_headers
    ):
        """It accepts an optional basis parameter of BUILT_BASIS or
        SHIPPED_BASIS, defaulting to BUILT_BASIS, and returns the platform_id,
        the basis it evaluated, the counted_claim_count, the denominator_units
        that basis produced — units_built_released or 1 under the built basis,
        units_shipped_total or 1 under the shipped basis — the resulting
        rolling_claim_rate_pct, and the warranty_posture. The posture is always
        the one the stored built basis produces, whichever basis was requested for
        the rate, and the read stores nothing and increments no version.

        Design: Difficulty/boundary_precision_check/claim_rate_of_exactly_five_percent_trips_capa_threshold
        """
        scenario = setup_platform_two_claims_below_threshold(quantity_units=60)
        open_corrective_action_via_third_claim(scenario["platform"]["id"], 40200)
        platform_id = scenario["platform"]["id"]

        analysis = validate_success(
            api.get_platform_warranty_analysis(
                platform_id, warranty_analyst_headers, params={"basis": "SHIPPED_BASIS"}
            )
        )
        assert analysis["platform_id"] == platform_id
        assert analysis["basis"] == "SHIPPED_BASIS"
        assert analysis["counted_claim_count"] == 3
        assert analysis["denominator_units"] == 1, (
            "nothing has shipped, so the floor of one unit applies"
        )
        assert float(analysis["rolling_claim_rate_pct"]) == pytest.approx(
            300.00, abs=0.005
        )
        assert analysis["warranty_posture"] == "CAPA_REQUIRED", (
            "the posture is the one the stored built basis produced"
        )

        platform = read_platform(platform_id)
        assert float(platform["rolling_claim_rate_pct"]) == pytest.approx(
            5.00, abs=0.005
        ), "the shipped-basis read never writes to the platform"
        assert platform["units_shipped_total"] == 0


class TestCapaCascadeRevokesKits:
    """Four hops from a filed claim to an unallocated distributor order."""

    def test_the_claim_rescores_the_platform_and_stops_the_compressor_lot(self, api):
        """Filing then triggers a four-hop cascade. The size of the cut is read
        from a second two-dimensional table, keyed by the claim's component_type
        and by which band the platform's rolling_claim_rate_pct falls into.

        Design: Difficulty/transitive_cascade/warranty_capa_cascade_revokes_allocation_kit_in_four_hops
        """
        scenario = setup_warranty_capa_cascade_scenario()
        third_claim = open_corrective_action_via_third_claim(
            scenario["platform"]["id"], 44100
        )
        assert_instant_equals(
            third_claim["filed_at"], "2026-08-01T00:00:00Z", "filed_at"
        )

        platform = read_platform(scenario["platform"]["id"])
        assert float(platform["rolling_claim_rate_pct"]) == pytest.approx(
            15.00, abs=0.005
        )
        assert platform["warranty_posture"] == "DESIGN_CHANGE_REQUIRED"

        action = find_open_corrective_action(scenario["compressor"]["id"])
        assert action["derate_pct"] == 100, "the top band stops a compressor lot"
        assert action["cited_claim_count"] == 3
        assert action["warranty_claim_id"] == third_claim["id"]
        assert float(action["trigger_claim_rate_pct"]) == pytest.approx(15.00, abs=0.005)

        pool = read_supply(scenario["compressor"]["id"])
        assert pool["status"] == "DERATED"
        assert pool["effective_allocatable_units"] == 0
        assert_supply_conservation(pool)

    def test_revocations_reach_the_kit_sibling_and_the_order_dimension(
        self, api, supply_planner_headers
    ):
        """Allocation lines on that pool whose status is RESERVED are revoked in
        descending created_at order — newest first — until available_units is
        back at zero or above, each revocation dragging its kit siblings with it
        exactly as §3.5 describes.

        Design: Difficulty/transitive_cascade/warranty_capa_cascade_revokes_allocation_kit_in_four_hops
        """
        scenario = setup_warranty_capa_cascade_scenario()
        order_id = scenario["order"]["id"]
        assert_order_dimensions(scenario["order"], "FULLY_ALLOCATED", "PENDING")
        assert scenario["order"]["allocated_units"] == 40

        open_corrective_action_via_third_claim(scenario["platform"]["id"], 44100)

        lines, lines_meta = validate_paginated(
            api.list_order_allocation_lines(order_id, supply_planner_headers)
        )
        assert lines_meta["total_count"] == 2
        for line in lines:
            assert line["status"] == "REVOKED", (
                "half a kit is worth nothing, so both lines go"
            )

        board_pool = read_supply(scenario["control_board"]["id"])
        assert board_pool["status"] == "ACTIVE"
        assert board_pool["reserved_units"] == 0
        assert board_pool["available_units"] == 100
        assert_supply_conservation(board_pool)

        compressor_pool = read_supply(scenario["compressor"]["id"])
        assert compressor_pool["reserved_units"] == 0
        assert compressor_pool["available_units"] == 0
        assert_supply_conservation(compressor_pool)

        order = read_order(order_id)
        assert_order_dimensions(order, "UNALLOCATED", "PENDING")
        assert order["allocated_units"] == 0
        assert order["staged_at"] is None, "the fulfillment dimension is untouched"

    def test_every_cited_claim_is_linked_and_new_lots_are_blocked(
        self, api, warranty_analyst_headers, production_planner_headers
    ):
        """Every claim of the same platform, component_type, and
        supplier_lot_code whose status is OPEN moves OPEN → LINKED_TO_CAPA with
        its version incremented, and cited_claim_count is exactly the count of
        claims of that same platform, component type, and supplier lot whose
        status is OPEN or LINKED_TO_CAPA. Its warranty_posture must not be
        DESIGN_CHANGE_REQUIRED, otherwise the lot is refused with
        ERR_WARRANTY_POSTURE_BLOCKED.

        Design: Difficulty/transitive_cascade/warranty_capa_cascade_revokes_allocation_kit_in_four_hops
        """
        scenario = setup_warranty_capa_cascade_scenario()
        open_corrective_action_via_third_claim(scenario["platform"]["id"], 44100)

        claims, meta = validate_paginated(
            api.list_warranty_claims(
                warranty_analyst_headers,
                params={"platform_id": scenario["platform"]["id"]},
            )
        )
        assert meta["total_count"] == 3
        for claim in claims:
            assert claim["status"] == "LINKED_TO_CAPA"

        refused = api.create_build_order(
            create_build_order_payload(scenario["platform"]["id"], quantity_units=10),
            production_planner_headers,
        )
        validate_error(refused, "ERR_WARRANTY_POSTURE_BLOCKED", 409)

        _, lots_meta = validate_paginated(
            api.list_build_orders(
                production_planner_headers,
                params={"platform_id": scenario["platform"]["id"]},
            )
        )
        assert lots_meta["total_count"] == 1, "the refused lot was never created"
