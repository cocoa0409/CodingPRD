"""Cascades whose later hops are caused by earlier hops rather than by the request."""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    TEST_DEFAULTS,
    computed_settlement_state,
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
    post_results,
    record_inspection,
    rogueing_declaration_payload,
    rogueing_verification_payload,
    set_clock,
    sign_contract_payload,
    validate_success,
)

ROGUEING_OFF_TYPE_PLANTS = 21
FAILING_GERMINATION_PCT = 80.0


def _one_round_used_state(api):
    """Contract A carrying one verified rogueing round, plus a sibling contract left in DRAFT."""
    variety = make_variety(api)
    grower = make_grower(api)

    field_a = make_production_field(
        api, grower["id"], field_code="F-A", acres=320.0, isolation_distance_m=250.0
    )
    make_field_history_record(api, field_a["id"])
    field_b = make_production_field(
        api, grower["id"], field_code="F-B", acres=200.0, isolation_distance_m=250.0
    )
    make_field_history_record(api, field_b["id"])

    contract_a = get_success_data(
        api.create_production_contract(
            create_production_contract_payload(grower["id"], variety["id"], field_a["id"]),
            make_program_admin_headers(),
        )
    )
    contract_b = get_success_data(
        api.create_production_contract(
            create_production_contract_payload(
                grower["id"],
                variety["id"],
                field_b["id"],
                contracted_acres=150.0,
                advance_total_cents=400000,
            ),
            make_program_admin_headers(),
        )
    )
    get_success_data(api.offer_production_contract(contract_a["id"], {}, make_program_admin_headers()))
    get_success_data(
        api.sign_production_contract(
            contract_a["id"], sign_contract_payload(), make_grower_headers(grower["id"])
        )
    )
    set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])

    first = record_inspection(
        api, contract_a["id"], inspector_user_id="fo-1", off_type_plants=ROGUEING_OFF_TYPE_PLANTS
    )
    validate_success(
        api.declare_rogueing(
            first["id"],
            rogueing_declaration_payload(rogueing_plants_removed=9, rogueing_declared_on="2026-08-20"),
            make_grower_headers(grower["id"]),
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
    return {"variety": variety, "grower": grower, "contract": contract_a, "sibling": contract_b}


class TestRogueingOrderCascadeFlagsGrowerAndMarksSiblingContracts:
    def test_second_rogueing_order_drives_the_contract_and_the_flag_counter(self, api):
        """The outcome moves the contract, and the contract entering that state moves the counter.

        PRD: "On the second hop, because the contract entered one of those two conditions, the
        grower's `compliance_flag_count` increments by 1 and the grower's `version` increments
        by 1."

        Design: Difficulty/transitive_cascade/rogueing_order_cascade_flags_grower_and_marks_sibling_contracts
        """
        state = _one_round_used_state(api)

        second = record_inspection(
            api,
            state["contract"]["id"],
            inspector_user_id="fo-1",
            off_type_plants=ROGUEING_OFF_TYPE_PLANTS,
        )
        assert second["outcome"] == "ROGUEING_ORDERED"

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "ROGUEING_REQUIRED"
        assert contract["rogueing_rounds_used"] == 2

        grower = get_success_data(api.get_grower(state["grower"]["id"], make_program_admin_headers()))
        assert grower["compliance_flag_count"] == 2

    def test_degraded_standing_stamps_the_sibling_draft_contract(self, api):
        """The counter reaching the watch threshold is what flags the grower's other contracts.

        PRD: "On the fourth hop, because the grower's standing became `WATCH` or `SUSPENDED`,
        every *other* production contract of that same grower whose status is `DRAFT` or
        `OFFERED` has `requires_field_officer_review` set to true and its `version` incremented
        by 1, processed in `created_at` ascending order."

        Design: Difficulty/transitive_cascade/rogueing_order_cascade_flags_grower_and_marks_sibling_contracts
        """
        state = _one_round_used_state(api)
        record_inspection(
            api,
            state["contract"]["id"],
            inspector_user_id="fo-1",
            off_type_plants=ROGUEING_OFF_TYPE_PLANTS,
        )

        headers = make_program_admin_headers()
        grower = get_success_data(api.get_grower(state["grower"]["id"], headers))
        assert grower["status"] == "WATCH"

        sibling = get_success_data(api.get_production_contract(state["sibling"]["id"], headers))
        assert sibling["requires_field_officer_review"] is True
        assert sibling["status"] == "DRAFT"

        contract = get_success_data(api.get_production_contract(state["contract"]["id"], headers))
        assert contract["requires_field_officer_review"] is False


class TestSampleFailCascadeVoidsTagsAndSupersedesSettlement:
    def test_failing_retest_fails_the_lot_and_voids_its_issued_tag(self, api):
        """The verdict flips the lot, and the lot failing is what voids the tag.

        PRD: "On the third hop, because the lot became `FAILED`, every certification tag on that
        lot whose status is `ISSUED` is moved to `VOIDED` in `created_at` ascending order with
        `void_reason` set to `RETEST_FAILURE`, and the lot's `tagged_bag_count` is driven to 0."

        Design: Difficulty/transitive_cascade/sample_fail_cascade_voids_tags_and_supersedes_settlement
        """
        state = computed_settlement_state(api)
        lot_id = state["seed_lot"]["id"]

        retest = draw_sample(api, lot_id, sample_kind="RETEST")
        resulted = post_results(api, retest["id"], germination_pct=FAILING_GERMINATION_PCT)
        assert resulted["result"] == "FAIL"

        headers = make_program_admin_headers()
        lot = get_success_data(api.get_seed_lot(lot_id, headers))
        assert lot["certification_status"] == "FAILED"
        assert lot["disposition"] == "DOWNGRADE_TO_COMMERCIAL"
        assert lot["adjusted_price_per_unit_cents"] is None
        assert lot["tagged_bag_count"] == 0
        assert lot["bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]

        tag = get_success_data(api.get_certification_tag(state["tag"]["id"], headers))
        assert tag["status"] == "VOIDED"
        assert tag["void_reason"] == "RETEST_FAILURE"

    def test_dropped_bag_count_reconciles_the_contract_and_supersedes_the_settlement(self, api):
        """The roll-up is recomputed, and the changed total withdraws the computed settlement.

        PRD: "On the fifth hop, because the contract's certified unit total changed, every
        settlement of that contract whose status is `COMPUTED` has its `quality_hold` set to true
        and its status moved to `SUPERSEDED`, processed in `created_at` ascending order — the
        quality hold is set *before* the status moves, so the superseded settlement records why
        it was withdrawn."

        Design: Difficulty/transitive_cascade/sample_fail_cascade_voids_tags_and_supersedes_settlement
        """
        state = computed_settlement_state(api)
        assert state["settlement"]["net_payable_cents"] == GOLDEN_FIGURES["NET_PAYABLE_CENTS"]

        retest = draw_sample(api, state["seed_lot"]["id"], sample_kind="RETEST")
        post_results(api, retest["id"], germination_pct=FAILING_GERMINATION_PCT)

        headers = make_program_admin_headers()
        contract = get_success_data(api.get_production_contract(state["contract"]["id"], headers))
        assert contract["certified_units_total"] == pytest.approx(0.0, abs=0.01)
        assert contract["advance_outstanding_cents"] == TEST_DEFAULTS["ADVANCE_TOTAL_CENTS"]

        settlement = get_success_data(api.get_settlement(state["settlement"]["id"], headers))
        assert settlement["quality_hold"] is True
        assert settlement["status"] == "SUPERSEDED"
        assert settlement["net_payable_cents"] == GOLDEN_FIGURES["NET_PAYABLE_CENTS"]
        assert settlement["gross_payable_cents"] == GOLDEN_FIGURES["GROSS_PAYABLE_CENTS"]
