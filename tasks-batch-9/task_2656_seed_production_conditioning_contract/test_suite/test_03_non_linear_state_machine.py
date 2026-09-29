"""Shapes that are not a straight line: a cycle, two parallel axes and a three-way fork."""

from __future__ import annotations

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    assert_field_inspection,
    assert_grower,
    assert_production_contract,
    assert_seed_lot,
    bagged_lot_state,
    create_production_contract_payload,
    draw_sample,
    get_success_data,
    make_field_history_record,
    make_field_officer_headers,
    make_grower,
    make_grower_headers,
    make_production_field,
    make_program_admin_headers,
    make_variety,
    planted_contract_state,
    record_inspection,
    rogueing_declaration_payload,
    rogueing_verification_payload,
    set_clock,
    sign_contract_payload,
    validate_success,
)

ROGUEING_OFF_TYPE_PLANTS = 21
FAILING_OFF_TYPE_PLANTS = 80


def _signed_contract(api, variety, grower, field, **overrides):
    """Draft, offer and sign one contract against an already registered field."""
    contract = get_success_data(
        api.create_production_contract(
            create_production_contract_payload(grower["id"], variety["id"], field["id"], **overrides),
            make_program_admin_headers(),
        )
    )
    get_success_data(api.offer_production_contract(contract["id"], {}, make_program_admin_headers()))
    return get_success_data(
        api.sign_production_contract(
            contract["id"], sign_contract_payload(), make_grower_headers(grower["id"])
        )
    )


class TestContractRogueingCycleReturnsToPlanted:
    def test_verified_rogueing_returns_the_contract_to_planted(self, api):
        """The declaration and verification pair close the loop back onto PLANTED.

        PRD: "This edge is what closes the cyclic `PLANTED → ROGUEING_REQUIRED → PLANTED` loop
        that lets a field be given a second chance."

        Design: Difficulty/non_linear_state_machine/contract_rogueing_cycle_returns_to_planted
        """
        state = planted_contract_state(api)
        set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
        grower_id = state["grower"]["id"]

        inspection = record_inspection(
            api,
            state["contract"]["id"],
            inspector_user_id="fo-1",
            off_type_plants=ROGUEING_OFF_TYPE_PLANTS,
        )
        assert_field_inspection(inspection)
        assert inspection["off_type_rate_per_10000"] == pytest.approx(10.50, abs=0.01)
        assert inspection["outcome"] == "ROGUEING_ORDERED"
        assert inspection["status"] == "RECORDED"

        ordered = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert ordered["status"] == "ROGUEING_REQUIRED"
        assert ordered["rogueing_rounds_used"] == 1

        declared = validate_success(
            api.declare_rogueing(
                inspection["id"],
                rogueing_declaration_payload(rogueing_plants_removed=9, rogueing_declared_on="2026-08-20"),
                make_grower_headers(grower_id),
            ),
            200,
        )
        assert declared["status"] == "ROGUEING_DECLARED"

        verified = validate_success(
            api.verify_rogueing(
                inspection["id"],
                rogueing_verification_payload(verified_remaining_off_type_plants=15),
                make_field_officer_headers("fo-2"),
            ),
            200,
        )
        assert verified["status"] == "ROGUEING_VERIFIED"
        assert verified["rogueing_verified_by_user_id"] == "fo-2"
        assert verified["outcome"] == "ROGUEING_ORDERED"

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert_production_contract(contract)
        assert contract["status"] == "PLANTED"
        assert contract["rogueing_rounds_used"] == 1
        assert contract["inspection_round"] == 1

    def test_second_round_after_the_cycle_passes_and_the_flag_is_never_cleared(self, api):
        """A second walk is admissible after the cycle, and the raised flag stays raised.

        PRD: "Both thresholds are inclusive, the counter is monotonically increasing, and it is
        never decremented — a rogueing round that is later verified successfully does not clear
        the flag it raised."

        Design: Difficulty/non_linear_state_machine/contract_rogueing_cycle_returns_to_planted
        """
        state = planted_contract_state(api)
        set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
        grower_id = state["grower"]["id"]
        contract_id = state["contract"]["id"]

        first = record_inspection(
            api, contract_id, inspector_user_id="fo-1", off_type_plants=ROGUEING_OFF_TYPE_PLANTS
        )
        validate_success(
            api.declare_rogueing(
                first["id"],
                rogueing_declaration_payload(rogueing_plants_removed=9, rogueing_declared_on="2026-08-20"),
                make_grower_headers(grower_id),
            ),
            200,
        )
        validate_success(
            api.verify_rogueing(
                first["id"],
                rogueing_verification_payload(verified_remaining_off_type_plants=15),
                make_field_officer_headers("fo-2"),
            ),
            200,
        )

        second = record_inspection(api, contract_id, inspector_user_id="fo-1")
        assert second["off_type_rate_per_10000"] == pytest.approx(6.00, abs=0.01)
        assert second["outcome"] == "PASSED"
        assert second["inspection_round"] == 2

        contract = get_success_data(api.get_production_contract(contract_id, make_program_admin_headers()))
        assert contract["status"] == "INSPECTION_PASSED"
        assert contract["inspection_round"] == 2
        assert contract["rogueing_rounds_used"] == 1

        grower = get_success_data(api.get_grower(grower_id, make_program_admin_headers()))
        assert_grower(grower)
        assert grower["compliance_flag_count"] == 1
        assert grower["status"] == "GOOD_STANDING"


class TestSeedLotParallelAxesIndependence:
    def test_conditioning_ladder_leaves_the_certification_axis_untouched(self, api):
        """Three completed runs walk the conditioning axis and never move the certification axis.

        PRD: "Every conditioning transition leaves the certification axis untouched, and every
        certification transition leaves the conditioning axis untouched."

        Design: Difficulty/non_linear_state_machine/seed_lot_parallel_axes_independence
        """
        state = bagged_lot_state(api)
        lot = state["seed_lot"]
        assert_seed_lot(lot)

        assert lot["conditioning_status"] == "BAGGED"
        assert lot["certification_status"] == "UNSAMPLED"
        assert lot["germination_pct"] is None
        assert lot["purity_pct"] is None
        assert lot["adjusted_price_per_unit_cents"] is None

    def test_sampling_moves_only_the_certification_axis(self, api):
        """Drawing a sample advances certification while conditioning stays exactly where it was.

        PRD: "Drawing a sample records the drawing operator's `X-User-ID` as `sampler_user_id`,
        puts the sample in `PENDING` result state with `germination_pct`, `purity_pct`,
        `inert_pct`, `weed_seed_count_per_kg`, `tested_at` and `germination_valid_until` all
        null, moves the lot's certification status to `SAMPLED` while leaving its conditioning
        status exactly where it was, and increments the lot's `version` by 1."

        Design: Difficulty/non_linear_state_machine/seed_lot_parallel_axes_independence
        """
        state = bagged_lot_state(api)
        lot_id = state["seed_lot"]["id"]

        sample = draw_sample(api, lot_id)
        assert sample["result"] == "PENDING"

        lot = get_success_data(api.get_seed_lot(lot_id, make_program_admin_headers()))
        assert lot["certification_status"] == "SAMPLED"
        assert lot["conditioning_status"] == "BAGGED"
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["BAGGING_OUTPUT_KG"], abs=0.01)
        assert lot["bag_count"] == 1380
        assert lot["germination_pct"] is None
        assert lot["adjusted_price_per_unit_cents"] is None

        bagging_run = get_success_data(
            api.get_conditioning_run(state["bagging_run"]["id"], make_program_admin_headers())
        )
        assert bagging_run["status"] == "COMPLETED"


def _three_sibling_contracts(api):
    """One grower with three registered fields and three signed contracts."""
    variety = make_variety(api)
    grower = make_grower(api)
    contracts = []
    for field_code in ("F-A", "F-B", "F-C"):
        field = make_production_field(
            api, grower["id"], field_code=field_code, acres=320.0, isolation_distance_m=250.0
        )
        make_field_history_record(api, field["id"])
        contracts.append(_signed_contract(api, variety, grower, field))
    set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
    return variety, grower, contracts


class TestInspectionForkThreeOutcomeBranches:
    def test_one_endpoint_forks_into_three_outcomes(self, api):
        """The same count sheet endpoint yields PASSED, ROGUEING_ORDERED and FAILED.

        PRD: "The three outcome branches have deliberately disjoint side-effect sets, and all
        three are reachable from the single act of recording a count sheet."

        Design: Difficulty/non_linear_state_machine/inspection_fork_three_outcome_branches
        """
        _variety, _grower, contracts = _three_sibling_contracts(api)
        passing, rogueing, failing = contracts

        first = record_inspection(api, passing["id"], inspector_user_id="fo-1")
        second = record_inspection(
            api, rogueing["id"], inspector_user_id="fo-1", off_type_plants=ROGUEING_OFF_TYPE_PLANTS
        )
        third = record_inspection(
            api, failing["id"], inspector_user_id="fo-2", off_type_plants=FAILING_OFF_TYPE_PLANTS
        )

        assert first["outcome"] == "PASSED"
        assert first["status"] == "RECORDED"
        assert second["off_type_rate_per_10000"] == pytest.approx(10.50, abs=0.01)
        assert second["outcome"] == "ROGUEING_ORDERED"
        assert second["status"] == "RECORDED"
        assert third["off_type_rate_per_10000"] == pytest.approx(40.00, abs=0.01)
        assert third["outcome"] == "FAILED"
        assert third["status"] == "CLOSED"

    def test_the_three_branches_leave_three_different_contract_states(self, api):
        """Each branch lands its contract in a different status and moves standing once each.

        PRD: "On the `FAILED` branch the contract moves `PLANTED → REJECTED`, the contract's
        `inspection_round` increments by 1, the grower-standing cascade runs, the inspection
        moves directly to `CLOSED`, and the contract's `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/inspection_fork_three_outcome_branches
        """
        _variety, grower, contracts = _three_sibling_contracts(api)
        passing, rogueing, failing = contracts

        record_inspection(api, passing["id"], inspector_user_id="fo-1")
        record_inspection(
            api, rogueing["id"], inspector_user_id="fo-1", off_type_plants=ROGUEING_OFF_TYPE_PLANTS
        )
        record_inspection(
            api, failing["id"], inspector_user_id="fo-2", off_type_plants=FAILING_OFF_TYPE_PLANTS
        )

        headers = make_program_admin_headers()
        passed_contract = get_success_data(api.get_production_contract(passing["id"], headers))
        rogueing_contract = get_success_data(api.get_production_contract(rogueing["id"], headers))
        failed_contract = get_success_data(api.get_production_contract(failing["id"], headers))

        assert passed_contract["status"] == "INSPECTION_PASSED"
        assert passed_contract["rogueing_rounds_used"] == 0
        assert rogueing_contract["status"] == "ROGUEING_REQUIRED"
        assert rogueing_contract["rogueing_rounds_used"] == 1
        assert failed_contract["status"] == "REJECTED"

        assert passed_contract["requires_field_officer_review"] is False
        assert rogueing_contract["requires_field_officer_review"] is False

        standing = get_success_data(api.get_grower(grower["id"], headers))
        assert standing["compliance_flag_count"] == 2
        assert standing["status"] == "WATCH"
