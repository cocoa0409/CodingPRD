"""Which rejection wins, and what happens exactly on a threshold.

Two conflicting failures in one request must resolve to the identifier the
precedence ladder names, and a value sitting exactly on a stated boundary must
land on the side the PRD says it lands on.
"""

import pytest

from test_helpers import (
    CANONICAL_SNAPSHOTS,
    ApiErrorId,
    add_assessment,
    add_claim,
    add_sibling_vehicle,
    adjudicate,
    adjudicate_payload,
    assert_reman_stock,
    assert_settlement_waterfall,
    claim_payload,
    list_claims,
    read_claim,
    read_pack,
    read_program,
    setup_base_world,
    stock_reman_packs,
    validate_error,
    validate_success,
)

# A vehicle just inside the first retention tier: 48 elapsed months and 41,800
# miles select the 80.00 % row, which a 82.50 % retention figure fails.
EARLY_TIER_IN_SERVICE_DATE = "2022-08-01"
EARLY_TIER_SNAPSHOTS = [
    ("2026-07-20T00:00:00Z", 41000, 65.000),
    ("2026-07-22T00:00:00Z", 41200, 66.000),
    ("2026-07-24T00:00:00Z", 41400, 66.000),
    ("2026-07-26T00:00:00Z", 41600, 66.000),
    ("2026-07-28T00:00:00Z", 41800, 67.000),
]


def _window_around(mid_capacity: float):
    """The canonical five-row window with the middle three set to one value.

    The trimmed mean discards the 55.000 and 57.000 bookends, so the assessment's
    `estimated_capacity_kwh` comes back as exactly `mid_capacity`.
    """
    return [
        ("2026-07-20T00:00:00Z", 71000, 55.000),
        ("2026-07-22T00:00:00Z", 71200, mid_capacity),
        ("2026-07-24T00:00:00Z", 71400, mid_capacity),
        ("2026-07-26T00:00:00Z", 71600, mid_capacity),
        ("2026-07-28T00:00:00Z", 71800, 57.000),
    ]


class TestStateLockBeatsLiabilityCap:
    """The fiscal ceiling is checked last, so it can never mask a state failure."""

    def test_re_adjudicating_a_decided_claim_reports_the_state_lock_not_the_cap(self, api):
        """A second decision on the same claim is a state error, not a money error.

        PRD 3.5: "The fiscal ceiling is checked last, after every safety,
        referential and constraint check has passed, so that no money rule can mask
        a safety failure."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_lock_precedes_liability_cap_on_double_adjudication
        """
        world = setup_base_world(
            api,
            program_overrides={"liability_cap_cents": 400000},
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        add_assessment(api, world, module_fault_positions=[3, 7])
        add_claim(api, world)
        decided = adjudicate(api, world, "MODULE_REPLACEMENT")
        assert decided["remedy_cost_cents"] == 363092
        assert decided["oem_total_cents"] == 370592
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 370592

        # A second 370,592 would breach the 400,000 ceiling, but the claim's own
        # state is examined first.
        validate_error(
            api.adjudicate_claim(
                world["claim_id"],
                adjudicate_payload("MODULE_REPLACEMENT"),
                world["adjudicator_headers"],
            ),
            ApiErrorId.ERR_CLAIM_NOT_ADJUDICABLE.value,
            expected_status=409,
        )

        assert read_claim(api, world["claim_id"])["adjudication_status"] == "APPROVED_MODULE"
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 370592

    def test_a_second_submitted_claim_is_the_one_that_hits_the_ceiling(self, api):
        """With the state check satisfied, the money rule fires and books nothing.

        PRD 3.5: "If the program's current `accrued_liability_cents` plus this
        claim's computed `oem_total_cents` would exceed the program's
        `liability_cap_cents`, the adjudication is refused with
        `ERR_LIABILITY_CAP_EXCEEDED`; landing exactly on the cap is permitted."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_lock_precedes_liability_cap_on_double_adjudication
        """
        first = setup_base_world(
            api,
            program_overrides={"liability_cap_cents": 400000},
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        second = add_sibling_vehicle(
            api,
            first,
            vin="5YJ3E1EA7KF000002",
            serial_number="PK-C002",
            snapshots=CANONICAL_SNAPSHOTS,
            snapshot_overrides={"coolant_temp_c": 20.0},
        )

        add_assessment(api, first, module_fault_positions=[3, 7])
        add_claim(api, first)
        adjudicate(api, first, "MODULE_REPLACEMENT")

        add_assessment(api, second, module_fault_positions=[3, 7])
        pending = add_claim(api, second)
        assert pending["adjudication_status"] == "SUBMITTED"

        validate_error(
            api.adjudicate_claim(
                second["claim_id"],
                adjudicate_payload("MODULE_REPLACEMENT"),
                second["adjudicator_headers"],
            ),
            ApiErrorId.ERR_LIABILITY_CAP_EXCEEDED.value,
            expected_status=409,
        )

        refused = read_claim(api, second["claim_id"])
        assert refused["adjudication_status"] == "SUBMITTED"
        assert refused["remedy_cost_cents"] is None
        assert refused["oem_total_cents"] is None

        assert read_program(api, first["program_id"])["accrued_liability_cents"] == 370592


class TestAssessmentMismatchBeatsRetention:
    """A cross-entity mismatch is reported before any retention comparison."""

    def test_filing_for_the_wrong_vehicle_reports_the_mismatch_not_the_retention(self, api):
        """One assessment, two candidate vehicles, and two different refusals.

        PRD 3.4: "The backing assessment must describe the same vehicle as the
        claim, or the filing is refused with `ERR_ASSESSMENT_VEHICLE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/assessment_vehicle_mismatch_precedes_retention_threshold_on_claim_filing
        """
        untelemetered = setup_base_world(api, snapshots=None)
        diagnosed = add_sibling_vehicle(
            api,
            untelemetered,
            vin="5YJ3E1EA7KF000002",
            serial_number="PK-C002",
            vehicle_overrides={"in_service_date": EARLY_TIER_IN_SERVICE_DATE},
            snapshots=EARLY_TIER_SNAPSHOTS,
            snapshot_overrides={"coolant_temp_c": 20.0},
        )

        assessment = add_assessment(api, diagnosed, module_fault_positions=[5])
        assert assessment["elapsed_months"] == 48
        assert assessment["assessed_odometer_miles"] == 41800
        assert assessment["estimated_capacity_kwh"] == pytest.approx(66.000, abs=0.001)
        assert assessment["retention_pct"] == pytest.approx(82.50, abs=0.01)
        assert assessment["coverage_position"] == "IN_COVERAGE"
        assert assessment["applicable_min_retention_pct"] == pytest.approx(80.00, abs=0.01)
        assert assessment["qualifies_for_claim"] is False

        # The retention figure would also fail, but the vehicle mismatch is reported.
        validate_error(
            api.create_claim(
                claim_payload(
                    untelemetered["vehicle_id"],
                    untelemetered["center_id"],
                    assessment["id"],
                    untelemetered["technician_id"],
                ),
                untelemetered["tech_headers"],
            ),
            ApiErrorId.ERR_ASSESSMENT_VEHICLE_MISMATCH.value,
            # PRD 5 catalogues `ERR_ASSESSMENT_VEHICLE_MISMATCH` as HTTP 422.
            expected_status=422,
        )

        # Filed against the right vehicle, the retention rule is what refuses it.
        validate_error(
            api.create_claim(
                claim_payload(
                    diagnosed["vehicle_id"],
                    diagnosed["center_id"],
                    assessment["id"],
                    diagnosed["technician_id"],
                ),
                diagnosed["tech_headers"],
            ),
            ApiErrorId.ERR_RETENTION_ABOVE_THRESHOLD.value,
            expected_status=409,
        )

        rows, meta = list_claims(api)
        assert meta["total_count"] == 0
        assert rows == []


class TestRetentionExactlyAtThreshold:
    """Retention exactly at the applicable floor qualifies; one hundredth above does not."""

    @pytest.mark.parametrize(
        "mid_capacity, expected_retention, expected_qualifies",
        [
            (55.992, 69.99, True),
            (56.000, 70.00, True),
            (56.008, 70.01, False),
        ],
    )
    def test_qualification_turns_on_the_hundredth_of_a_point(
        self, api, mid_capacity, expected_retention, expected_qualifies
    ):
        """69.99 and 70.00 qualify against a 70.00 floor; 70.01 does not.

        PRD 3.3: "`qualifies_for_claim` is true when `diagnostic_validity` is
        `VALID`, `coverage_position` is either `IN_COVERAGE` or `GOODWILL_BAND`, and
        `retention_pct` is at or below `applicable_min_retention_pct` — retention
        exactly at the threshold qualifies."

        Design: Difficulty/boundary_precision_check/retention_exactly_at_tier_threshold_qualifies_on_claim_filing
        """
        world = setup_base_world(
            api,
            snapshots=_window_around(mid_capacity),
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        assessment = add_assessment(api, world, module_fault_positions=[2])

        assert assessment["diagnostic_validity"] == "VALID"
        assert assessment["estimated_capacity_kwh"] == pytest.approx(mid_capacity, abs=0.001)
        assert assessment["nominal_basis_kwh"] == pytest.approx(80.000, abs=0.001)
        assert assessment["retention_pct"] == pytest.approx(expected_retention, abs=0.01)
        assert assessment["coverage_position"] == "IN_COVERAGE"
        assert assessment["applicable_min_retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert assessment["qualifies_for_claim"] is expected_qualifies

    def test_only_the_vehicle_above_the_floor_is_refused_at_filing(self, api):
        """Two filings are accepted and the third is refused on retention alone.

        PRD 3.4: "an assessment whose `retention_pct` is strictly above its
        `applicable_min_retention_pct` is refused with
        `ERR_RETENTION_ABOVE_THRESHOLD` (retention exactly at the threshold
        qualifies)."

        Design: Difficulty/boundary_precision_check/retention_exactly_at_tier_threshold_qualifies_on_claim_filing
        """
        low = setup_base_world(
            api,
            snapshots=_window_around(55.992),
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        edge = add_sibling_vehicle(
            api,
            low,
            vin="5YJ3E1EA7KF000002",
            serial_number="PK-C002",
            snapshots=_window_around(56.000),
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        high = add_sibling_vehicle(
            api,
            low,
            vin="5YJ3E1EA7KF000003",
            serial_number="PK-C003",
            snapshots=_window_around(56.008),
            snapshot_overrides={"coolant_temp_c": 20.0},
        )

        for world in (low, edge, high):
            add_assessment(api, world, module_fault_positions=[2])

        low_claim = validate_success(
            api.create_claim(
                claim_payload(
                    low["vehicle_id"],
                    low["center_id"],
                    low["assessment_id"],
                    low["technician_id"],
                ),
                low["tech_headers"],
            ),
            expected_status=201,
        )
        assert low_claim["adjudication_status"] == "SUBMITTED"

        edge_claim = validate_success(
            api.create_claim(
                claim_payload(
                    edge["vehicle_id"],
                    edge["center_id"],
                    edge["assessment_id"],
                    edge["technician_id"],
                ),
                edge["tech_headers"],
            ),
            expected_status=201,
        )
        assert edge_claim["adjudication_status"] == "SUBMITTED"
        assert edge_claim["recommended_remedy"] == "MODULE_REPLACEMENT"
        assert edge_claim["recommendation_basis"] == "MODULE_FAULT"

        validate_error(
            api.create_claim(
                claim_payload(
                    high["vehicle_id"],
                    high["center_id"],
                    high["assessment_id"],
                    high["technician_id"],
                ),
                high["tech_headers"],
            ),
            ApiErrorId.ERR_RETENTION_ABOVE_THRESHOLD.value,
            expected_status=409,
        )

        rows, meta = list_claims(api, vehicle_id=high["vehicle_id"])
        assert meta["total_count"] == 0
        assert rows == []
        assert list_claims(api)[1]["total_count"] == 2


class TestRemanRefurbSohBoundary:
    """The selector's refurb floor accepts the boundary value and rejects a hundredth below."""

    def test_a_pack_one_hundredth_below_the_floor_is_invisible_to_the_selector(self, api):
        """84.99 % against an 85.00 % floor leaves the pool empty.

        PRD 3.5: "its `refurb_soh_pct` is at or above the program's
        `reman_min_soh_pct`, with the boundary value accepted." And: "If the
        remanufactured pool is empty, the program's `allow_new_pack_substitution`
        decides what happens. When it is false, the adjudication is refused with
        `ERR_NO_REMAN_PACK_AVAILABLE`."

        Design: Difficulty/boundary_precision_check/reman_pack_refurb_soh_exactly_at_minimum_is_selectable_on_adjudicate
        """
        world = setup_base_world(
            api,
            program_overrides={
                "reman_min_soh_pct": 85.00,
                "allow_new_pack_substitution": False,
            },
            center_overrides={"hv_certification_level": "L3", "has_pack_lift": True},
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        below = stock_reman_packs(
            api, [{"serial_number": "PK-R8499", "refurb_soh_pct": 84.99}]
        )[0]
        assert_reman_stock(read_program(api, world["program_id"]), 1, "AVAILABLE")

        add_assessment(api, world, module_fault_positions=[1, 2, 3, 4, 5])
        claim = add_claim(api, world)
        assert claim["recommended_remedy"] == "PACK_REPLACEMENT"
        assert claim["recommendation_basis"] == "MODULE_ALLOWANCE"

        validate_error(
            api.adjudicate_claim(
                world["claim_id"],
                adjudicate_payload("PACK_REPLACEMENT"),
                world["adjudicator_headers"],
            ),
            ApiErrorId.ERR_NO_REMAN_PACK_AVAILABLE.value,
            expected_status=409,
        )

        assert read_claim(api, world["claim_id"])["adjudication_status"] == "SUBMITTED"
        assert read_pack(api, below["id"])["status"] == "STOCK"
        assert_reman_stock(read_program(api, world["program_id"]), 1, "AVAILABLE")

    def test_a_pack_exactly_at_the_floor_is_selected_over_the_one_below_it(self, api):
        """85.00 % is selectable, and reserving it prices the pack remedy at 1,040,497.

        PRD 3.5: "its `refurb_soh_pct` is at or above the program's
        `reman_min_soh_pct`, with the boundary value accepted."

        Design: Difficulty/boundary_precision_check/reman_pack_refurb_soh_exactly_at_minimum_is_selectable_on_adjudicate
        """
        world = setup_base_world(
            api,
            program_overrides={
                "reman_min_soh_pct": 85.00,
                "allow_new_pack_substitution": False,
            },
            center_overrides={"hv_certification_level": "L3", "has_pack_lift": True},
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        below = stock_reman_packs(
            api, [{"serial_number": "PK-R8499", "refurb_soh_pct": 84.99}]
        )[0]
        at_floor = stock_reman_packs(
            api, [{"serial_number": "PK-R8500", "refurb_soh_pct": 85.00}]
        )[0]
        assert_reman_stock(read_program(api, world["program_id"]), 2, "AVAILABLE")

        add_assessment(api, world, module_fault_positions=[1, 2, 3, 4, 5])
        add_claim(api, world)
        decided = adjudicate(api, world, "PACK_REPLACEMENT")
        assert_settlement_waterfall(decided)

        assert decided["adjudication_status"] == "APPROVED_PACK"
        assert decided["replacement_pack_id"] == at_floor["id"]
        assert read_pack(api, at_floor["id"])["status"] == "RESERVED"
        assert read_pack(api, below["id"])["status"] == "STOCK"
        assert_reman_stock(read_program(api, world["program_id"]), 1, "AVAILABLE")

        # 890,000 reman parts + 119,165 labour + 19,332 UN3480 freight + 12,000.
        assert decided["remedy_cost_cents"] == 1040497
        assert decided["settlement_variant"] == "FULL_COVERAGE"
        assert decided["owner_share_cents"] == 0
        assert decided["oem_share_cents"] == 1040497
        assert decided["admin_fee_cents"] == 15000
        assert decided["oem_total_cents"] == 1055497
