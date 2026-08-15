"""Combinatorial formula instances: route capacity mobilization conditional and
salvage per-class round-then-sum ordering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_stop,
    api_client,
    attest_pole_nameplate,
    create_account,
    create_active_program,
    create_batch,
    create_crew,
    create_district,
    create_pole,
    create_route,
    dispatch_and_complete,
    find_salvage_item_for_pole,
    get_batch,
    get_pole,
    get_route,
    list_work_orders_for_route,
    release_route,
    set_clock,
    setup_cleared_pole,
    setup_program_district_crew,
    setup_released_route,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]

# Module-level alias used by class-level setup helpers; the `api` pytest
# fixture returns this same shared client object.
api = api_client


def _add_stops(route_id, pole_ids, difficulty="COMPLEX"):
    for i, pole_id in enumerate(pole_ids):
        add_stop(route_id, pole_id, i + 1, difficulty_class=difficulty)


class TestRouteCapacityMobilizationShiftsFailurePoint:
    def test_traffic_control_route_rejects_eleventh_complex_stop(self, api):
        """PRD section 3.3: "The add is rejected with ERR_ROUTE_CAPACITY_EXCEEDED
        when the required shifts exceed the window days, or when the stop count
        including the candidate divided by the required shifts, rounded up,
        exceeds the crew's base_stops_per_shift. Both checks use post-add
        values"; "mobilization is 60 minutes per shift when the route requires
        traffic control and 30 otherwise; a shift holds 480 minutes."

        Design: Difficulty/combinatorial_formula/route_capacity_mobilization_shifts_failure_point
        """
        program, district, crew = setup_program_district_crew(zone="ARTERIAL")
        poles = [setup_cleared_pole(program, district, crew, pole_number=f"P{i:02d}",
                                    ownership_type="UTILITY_OWNED", nameplate_wattage=250)
                 for i in range(1, 12)]
        # traffic_control_required -> 420 workable min/shift; 10 x 120 = 1200 -> ceil(1200/420)=3 <= 3
        route = create_route(district["id"], crew["id"], start="2026-08-03", end="2026-08-05",
                             traffic_control_required=True)
        _add_stops(route["id"], [p["id"] for p in poles[:10]])
        mid = get_route(route["id"])
        assert mid["stop_count"] == 10 and mid["required_shifts"] == 3

        # 11th stop: W=1320 -> ceil(1320/420)=4 shifts > 3 window days
        resp = api.add_stop(route["id"],
                            {"pole_id": poles[10]["id"], "sequence_number": 11,
                             "difficulty_class": "COMPLEX"}, PM)
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED, expected_status=422)
        after = get_route(route["id"])
        assert after["stop_count"] == 10 and after["required_shifts"] == 3
        assert get_pole(poles[10]["id"])["status"] == "AUDIT_CLEARED"

    def test_plain_route_accepts_eleventh_rejects_twelfth(self, api):
        """PRD section 3.3: "mobilization is 60 minutes per shift when the route
        requires traffic control and 30 otherwise" and "The add is rejected with
        ERR_ROUTE_CAPACITY_EXCEEDED when the required shifts exceed the window
        days".

        Design: Difficulty/combinatorial_formula/route_capacity_mobilization_shifts_failure_point
        """
        program, district, crew = setup_program_district_crew(zone="ARTERIAL")
        poles = [setup_cleared_pole(program, district, crew, pole_number=f"P{i:02d}",
                                    ownership_type="UTILITY_OWNED", nameplate_wattage=250)
                 for i in range(1, 13)]
        # no traffic control -> 450 min/shift; 11 x 120 = 1320 -> ceil(1320/450)=3 <= 3,
        # stop-rate ceil(11/3)=4 <= 6: the 11th fits
        route = create_route(district["id"], crew["id"], start="2026-08-03", end="2026-08-05",
                             traffic_control_required=False)
        _add_stops(route["id"], [p["id"] for p in poles[:11]])
        mid = get_route(route["id"])
        assert mid["stop_count"] == 11 and mid["required_shifts"] == 3

        # 12th: W=1440 -> ceil(1440/450)=4 shifts > 3 window days
        resp = api.add_stop(route["id"],
                            {"pole_id": poles[11]["id"], "sequence_number": 12,
                             "difficulty_class": "COMPLEX"}, PM)
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED, expected_status=422)
        after = get_route(route["id"])
        assert after["stop_count"] == 11 and after["required_shifts"] == 3
        assert get_pole(poles[11]["id"])["status"] == "AUDIT_CLEARED"


class TestSalvagePerClassRoundThenSumOrder:
    def _setup_manifested_batch(self, contaminated=False):
        """Three poles (COBRA_HEAD, POST_TOP, FLOOD) converted; items batched at
        50.5 / 105.5 / 50.5 lb, mercury false; batch sealed. Returns batch id."""
        program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
        classes = ["COBRA_HEAD", "POST_TOP", "FLOOD"]
        poles = [setup_cleared_pole(program, district, crew, pole_number=f"S-{i:02d}",
                                    ownership_type="UTILITY_OWNED", nameplate_wattage=250,
                                    fixture_class=classes[i])
                 for i in range(3)]
        route, stops, wos = setup_released_route(
            program, district, crew, poles, start="2026-08-02", end="2026-08-02")
        set_clock("2026-08-02T10:00:00Z")
        for wo in wos:
            dispatch_and_complete(wo["id"], crew["id"], wattage=90, cct=2700,
                                  shielding="FULL_CUTOFF")
        items = [find_salvage_item_for_pole(p["id"]) for p in poles]
        batch = create_batch(program["id"], batch_label="BATCH-1")
        for item, weight in zip(items, (50.5, 105.5, 50.5)):
            resp = api.add_salvage_item(
                batch["id"],
                {"salvage_item_id": item["id"], "weight_lbs": weight, "mercury_flag": False},
                PM,
            )
            assert resp.status_code == 200, f"Setup failed: add item -> {resp.text}"
        resp = api.seal_salvage_batch(batch["id"], {"contaminated_flag": contaminated}, CO)
        assert resp.status_code == 200, f"Setup failed: seal -> {resp.text}"
        return batch["id"]

    def test_settlement_rounds_per_class_then_sums(self, api):
        """PRD section 3.7: "for each fixture class, sum the batch's weight_lbs in
        that class, multiply by the class price per pound — 85 cents for
        COBRA_HEAD, 95 for FLOOD, 70 for POST_TOP, 110 for DECORATIVE — round
        half-up, subtract 300 cents for each mercury-flagged item of the class,
        and floor the class value at zero. The subtotal is the sum of the four
        already-rounded class values — round per class, then sum, never the
        reverse. ... Finally subtract the 4500-cent transport fee and floor at
        zero".

        Design: Difficulty/combinatorial_formula/salvage_per_class_round_then_sum_order
        """
        batch_id = self._setup_manifested_batch()
        resp = api.manifest_salvage_batch(batch_id, CO)
        batch = validate_success(resp)
        # rhu(50.5*85)=4293, rhu(105.5*70)=7385, rhu(50.5*95)=4798 -> 16476 - 4500 = 11976
        assert batch["settlement_value_cents"] == 11976, (
            f"expected 11976 (per-class round-then-sum), got {batch['settlement_value_cents']}"
        )
        # The forbidden sum-then-round order would yield 16475 - 4500 = 11975
        assert batch["settlement_value_cents"] != 11975

    def test_manifest_mints_code_and_aggregates(self, api):
        """PRD section 3.7: "Manifesting requires SEALED (ERR_BATCH_NOT_SEALED)
        and every item weighed — any weight_lbs still zero fails with
        ERR_UNWEIGHED_ITEMS — then mints manifest_code as the prefix MF- followed
        by the batch label and computes the settlement value".
        PRD section 3.7: "Adding binds the item's batch_id, records the
        declarations, and recomputes the batch's item_count and total_weight_lbs,
        the latter carried to one decimal."

        Design: Difficulty/combinatorial_formula/salvage_per_class_round_then_sum_order
        """
        batch_id = self._setup_manifested_batch()
        resp = api.manifest_salvage_batch(batch_id, CO)
        batch = validate_success(resp)
        assert batch["status"] == "MANIFESTED"
        assert batch["manifest_code"] == "MF-BATCH-1"
        assert batch["item_count"] == 3
        assert batch["total_weight_lbs"] == 206.5
