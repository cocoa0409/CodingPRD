"""Classing: quality band edges, reclass supersede, schedule coverage,
OCC on Bale.version, parallel state dimensions, and the DRAFT-settlement
recompute cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    bales_by_tag,
    class_bale,
    create_classing_result_payload,
    create_grade_schedule,
    create_grower,
    create_module,
    create_settlement_for_grower,
    create_shift,
    create_warehouse,
    get_bale,
    get_settlement,
    gin_module,
    issue_receipt,
    list_classing_results,
    setup_classed_bale,
    setup_ginned_bale,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["gin_operator_headers"]
CLERK = TEST_USERS["classing_clerk_headers"]


def _band_scenario():
    """One module with six 500-lb bales under a zero-point 21-2 schedule."""
    create_grade_schedule(grade_code="21-2", premium_discount_points=0,
                          loan_rate_points=5200)
    grower = create_grower("MB-C35", "Band Farm")
    shift = create_shift("2026", "STAND-BD")
    module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-BD")
    gin_module(module["id"], shift["id"],
               [(f"B-BD{i}", 500) for i in range(1, 7)])
    return grower, shift, module, bales_by_tag(module["id"])


class TestQualityBandEdges:
    def test_band_edges(self, api):
        """PRD: "Micronaire between 3.7 and 4.2 inclusive earns a premium of 25
        points; micronaire outside that premium band but still within the
        acceptable range of 3.5 to 4.9 inclusive earns 0; anything outside the
        acceptable range costs 50 points. Strength of at least 29.0 grams per
        tex adds 15 points; strength of 26.0 or below subtracts 30 points;
        anything between contributes 0."
        PRD: "The bale's `adjustment_cents` is the bale's `net_weight_lbs`
        multiplied by the total quality points, divided by 100, and rounded
        half-up to whole cents — a signed value, since discounts run negative."

        Design: Corner/calculations/quality_band_edges
        """
        _g, _s, _m, bales = _band_scenario()
        cases = [
            # (tag, micronaire, strength, expected_points, expected_cents on 500 lbs)
            ("B-BD1", 3.7, 28.0, 25, 125),     # premium-band low edge
            ("B-BD2", 3.6, 28.0, 0, 0),        # acceptable only
            ("B-BD3", 3.4, 28.0, -50, -250),   # outside acceptable
            ("B-BD4", 4.4, 29.0, 15, 75),      # strength bonus edge
            ("B-BD5", 4.4, 26.0, -30, -150),   # strength penalty edge
            ("B-BD6", 4.4, 26.1, 0, 0),        # between the strength bands
        ]
        for tag, mic, strength, points, cents in cases:
            bale = bales[tag]
            result = validate_success(api.create_classing_result(
                bale["id"],
                create_classing_result_payload(
                    bale["version"], grade_code="21-2", micronaire=mic,
                    strength_gpt=strength, staple_32nds=35,
                    result_date="2026-03-10T00:00:00Z"),
                CLERK), expected_status=201)
            assert result["quality_points"] == points, (
                f"{tag}: expected {points} points, got {result['quality_points']}")
            assert result["adjustment_cents"] == cents, (
                f"{tag}: expected {cents} cents, got {result['adjustment_cents']}")


class TestClassingCoverageAndOcc:
    def test_result_date_without_covering_schedule_rejected(self, api):
        """PRD: "Because windows do not overlap, at most one schedule covers
        any given date for a grade; when classing or pledging finds no covering
        row, the write fails with `ERR_NO_ACTIVE_GRADE_SCHEDULE` (HTTP 422)."

        Design: Corner/validations/classing_date_without_covering_schedule_rejected
        """
        create_grade_schedule(grade_code="41-4", premium_discount_points=-110,
                              loan_rate_points=5200,
                              effective_from="2026-01-01T00:00:00Z",
                              effective_to="2026-07-01T00:00:00Z")
        ctx = setup_ginned_bale(membership_number="MB-C44",
                                legal_name="Window Farm", bale_tag="B-WN1",
                                stand_label="STAND-WN")
        bale = ctx["bale"]
        resp = api.create_classing_result(
            bale["id"],
            create_classing_result_payload(
                bale["version"], grade_code="41-4", micronaire=4.0,
                strength_gpt=28.0, staple_32nds=35,
                result_date="2026-08-15T00:00:00Z"),
            CLERK)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_GRADE_SCHEDULE)
        assert get_bale(bale["id"])["classing_status"] == "UNCLASSED"
        assert list_classing_results(bale["id"]) == []

    def test_occ_stale_bale_version_rejected(self, api):
        """PRD: "Recording a classing result against a bale requires the
        request to carry `expected_bale_version` equal to the bale's current
        `version`. If the bale's version has advanced since the client last
        read it, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_classing_stale_version_rejected
        """
        create_grade_schedule(grade_code="31-3", premium_discount_points=265,
                              loan_rate_points=5450)
        ctx = setup_ginned_bale(membership_number="MB-C80", legal_name="OCC Farm",
                                bale_tag="B-OC1", stand_label="STAND-OC")
        bale = ctx["bale"]
        observed = bale["version"]
        first = validate_success(api.create_classing_result(
            bale["id"],
            create_classing_result_payload(
                observed, grade_code="31-3", micronaire=4.0, strength_gpt=28.0,
                staple_32nds=36, result_date="2026-03-10T00:00:00Z"),
            CLERK), expected_status=201)
        assert first["status"] == "ACTIVE"

        replay = api.create_classing_result(
            bale["id"],
            create_classing_result_payload(
                observed, grade_code="31-3", micronaire=4.2, strength_gpt=28.0,
                staple_32nds=36, result_date="2026-03-11T00:00:00Z"),
            CLERK)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        results = list_classing_results(bale["id"])
        assert len(results) == 1, "no supersede occurred from the stale write"
        assert results[0]["id"] == first["id"]
        assert results[0]["status"] == "ACTIVE"


class TestClassingResultListing:
    def test_list_contains_active_and_superseded(self, api):
        """PRD: "The new result is created `ACTIVE`, and at most one result per
        bale is ever `ACTIVE`."
        PRD: "The prior `ACTIVE` result flips to terminal `SUPERSEDED`
        (incrementing the prior result's `version`)"
        PRD: "The bale recomputes its `active_grade_code`, `quality_points`,
        and `adjustment_cents` from the active result"

        Design: Corner/entities/classing_results_list_contains_active_and_superseded
        """
        ctx = setup_classed_bale(membership_number="MB-C04",
                                 legal_name="List Farm", bale_tag="B-CL1",
                                 stand_label="STAND-CL", micronaire=4.0,
                                 strength_gpt=28.0)
        bale = ctx["bale"]
        cr1 = ctx["classing_result"]
        cr2 = class_bale(bale["id"], bale["version"], grade_code="31-3",
                         micronaire=4.1, strength_gpt=28.5, staple_32nds=36,
                         result_date="2026-03-20T00:00:00Z")

        results = list_classing_results(bale["id"])
        assert len(results) == 2
        by_id = {r["id"]: r for r in results}
        assert by_id[cr1["id"]]["status"] == "SUPERSEDED"
        assert by_id[cr2["id"]]["status"] == "ACTIVE"

        refreshed = get_bale(bale["id"])
        assert refreshed["classing_status"] == "CLASSED"
        # mic 4.1 -> +25 premium; str 28.5 -> 0; schedule +265 -> 290
        assert refreshed["quality_points"] == 290


class TestParallelDimensions:
    def _setup(self):
        create_grade_schedule(grade_code="41-4", premium_discount_points=-110,
                              loan_rate_points=5200,
                              effective_from="2026-01-01T00:00:00Z",
                              effective_to="2026-07-01T00:00:00Z")
        create_grade_schedule(grade_code="31-3", premium_discount_points=265,
                              loan_rate_points=5450)
        grower = create_grower("MB-400", "Parallel Farm")
        warehouse = create_warehouse("WH-1", capacity_bales=10, dock_count=1)
        shift = create_shift("2026", "STAND-E")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-B")
        gin_module(module["id"], shift["id"], [("B-01", 480)])
        bale = bales_by_tag(module["id"])["B-01"]
        return grower, warehouse, bale

    def test_classing_moves_while_custody_stays_on_floor(self, api):
        """PRD: "The new result is created `ACTIVE`, and at most one result per
        bale is ever `ACTIVE`."
        PRD: "The bale recomputes its `active_grade_code`, `quality_points`,
        and `adjustment_cents` from the active result (these read null while
        the bale is `UNCLASSED`), its `classing_status` flips to `CLASSED`, and
        its `version` increments."
        PRD: "a `Bale` instead carries the two parallel dimensions
        `classing_status` and `custody_status`."

        Design: Difficulty/non_linear_state_machine/bale_parallel_dimensions_evolve_independently
        """
        _grower, _warehouse, bale = self._setup()
        v0 = bale["version"]
        result = class_bale(bale["id"], v0, grade_code="41-4", micronaire=4.5,
                            strength_gpt=30.0, staple_32nds=35,
                            result_date="2026-03-10T00:00:00Z")
        # -110 schedule + 0 mic (4.5 acceptable) + 15 strength = -95
        assert result["quality_points"] == -95
        assert result["adjustment_cents"] == -456  # 480 * -95 / 100

        refreshed = get_bale(bale["id"])
        assert refreshed["classing_status"] == "CLASSED"
        assert refreshed["custody_status"] == "ON_GIN_FLOOR", (
            "classing moved while custody stayed on the gin floor")
        assert refreshed["version"] == v0 + 1

    def test_custody_and_reclass_self_loop(self, api):
        """PRD: "The bale's `custody_status` flips to `WAREHOUSED`, the
        warehouse's `stored_bale_count` increases by one"
        PRD: "A reclass is the same operation run against an already-`CLASSED`
        bale — a `CLASSED → CLASSED` self-loop that supersedes rather than
        edits."
        PRD: "a `version` integer that increments by exactly 1 on every
        mutation of that resource"

        Design: Difficulty/non_linear_state_machine/bale_parallel_dimensions_evolve_independently
        """
        _grower, warehouse, bale = self._setup()
        class_bale(bale["id"], bale["version"], grade_code="41-4", micronaire=4.5,
                   strength_gpt=30.0, staple_32nds=35,
                   result_date="2026-03-10T00:00:00Z")
        v1 = get_bale(bale["id"])["version"]

        issue_receipt(bale["id"], warehouse["id"], wm_user_id="wm-1")
        after_receipt = get_bale(bale["id"])
        assert after_receipt["custody_status"] == "WAREHOUSED"
        assert after_receipt["classing_status"] == "CLASSED", (
            "custody moved without disturbing the classing dimension")
        assert after_receipt["version"] == v1 + 1

        result2 = class_bale(bale["id"], after_receipt["version"],
                             grade_code="31-3", micronaire=3.9, strength_gpt=27.0,
                             staple_32nds=36, result_date="2026-03-15T00:00:00Z")
        # 265 schedule + 25 mic (3.9 premium) + 0 strength = 290
        assert result2["quality_points"] == 290
        assert result2["adjustment_cents"] == 1392  # 480 * 290 / 100

        final = get_bale(bale["id"])
        assert final["classing_status"] == "CLASSED"
        assert final["custody_status"] == "WAREHOUSED"
        assert final["active_grade_code"] == "31-3"
        assert final["quality_points"] == 290
        assert final["adjustment_cents"] == 1392
        assert final["version"] == after_receipt["version"] + 1


class TestReclassSettlementCascade:
    def _setup(self):
        """Grower with a 480-lb bale classed 41-4 (-456) and a DRAFT
        settlement created after classing."""
        create_grade_schedule(grade_code="41-4", premium_discount_points=-110,
                              loan_rate_points=5200,
                              effective_from="2026-01-01T00:00:00Z",
                              effective_to="2026-07-01T00:00:00Z")
        create_grade_schedule(grade_code="31-3", premium_discount_points=265,
                              loan_rate_points=5450)
        grower = create_grower("MB-501", "Reclass Farm")
        shift = create_shift("2026", "STAND-H")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-R")
        gin_module(module["id"], shift["id"], [("B-R1", 480)])
        bale = bales_by_tag(module["id"])["B-R1"]
        cr1 = class_bale(bale["id"], bale["version"], grade_code="41-4",
                         micronaire=4.5, strength_gpt=30.0, staple_32nds=35,
                         result_date="2026-03-10T00:00:00Z")
        settlement = create_settlement_for_grower(grower["id"], "2026")
        return grower, bale, cr1, settlement

    def test_reclass_recomputes_draft_settlement(self, api):
        """PRD: "Because quality feeds settlement, every `DRAFT` settlement for
        the bale's grower and season is then recomputed per the settlement
        rules of §3.8."
        PRD: "Second, `quality_adjustment_cents` sums the `adjustment_cents` of
        each season bale's `ACTIVE` classing result, with unclassed bales
        contributing 0."

        Design: Difficulty/transitive_cascade/reclass_cascade_recomputes_draft_settlement
        """
        grower, bale, _cr1, settlement = self._setup()
        before = get_settlement(settlement["id"])
        # lint 480*60 = 28800; quality -456; seed estimate 5500*25 = 137500;
        # ginning -(480*11.5) = -5520; patronage 0.2*5520 = 1104
        assert before["quality_adjustment_cents"] == -456
        assert before["net_payable_cents"] == 161428

        refreshed = get_bale(bale["id"])
        class_bale(bale["id"], refreshed["version"], grade_code="31-3",
                   micronaire=3.9, strength_gpt=27.0, staple_32nds=36,
                   result_date="2026-03-15T00:00:00Z")

        after = get_settlement(settlement["id"])
        assert after["status"] == "DRAFT"
        assert after["quality_adjustment_cents"] == 1392
        assert after["net_payable_cents"] == 163276, (
            "settlement delta equals the bale adjustment delta exactly (+1848)")

    def test_reclass_supersedes_prior_result_and_recomputes_bale(self, api):
        """PRD: "The prior `ACTIVE` result flips to terminal `SUPERSEDED`
        (incrementing the prior result's `version`), the new result is created
        `ACTIVE` with its own pinned snapshot under the same OCC and
        schedule-coverage guards, the bale's classing fields recompute from the
        new snapshot"

        Design: Difficulty/transitive_cascade/reclass_cascade_recomputes_draft_settlement
        """
        _grower, bale, cr1, _settlement = self._setup()
        refreshed = get_bale(bale["id"])
        cr2 = class_bale(bale["id"], refreshed["version"], grade_code="31-3",
                         micronaire=3.9, strength_gpt=27.0, staple_32nds=36,
                         result_date="2026-03-15T00:00:00Z")

        results = list_classing_results(bale["id"])
        assert len(results) == 2
        by_id = {r["id"]: r for r in results}
        assert by_id[cr1["id"]]["status"] == "SUPERSEDED"
        assert by_id[cr2["id"]]["status"] == "ACTIVE"

        rebale = get_bale(bale["id"])
        assert rebale["quality_points"] == 290
        assert rebale["adjustment_cents"] == 1392
        assert rebale["active_grade_code"] == "31-3"
