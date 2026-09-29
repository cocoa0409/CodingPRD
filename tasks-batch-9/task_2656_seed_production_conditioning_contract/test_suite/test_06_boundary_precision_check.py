"""Values sitting exactly on a stated threshold, and the empty-set boundary."""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    TEST_DEFAULTS,
    assert_field_inspection,
    assert_instant_equals,
    assert_seed_lot,
    create_carryover_payload,
    create_production_contract_payload,
    create_settlement_payload,
    get_success_data,
    harvested_lot_state,
    issue_tag,
    make_conditioning_manager_headers,
    make_field_history_record,
    make_grower,
    make_grower_headers,
    make_production_field,
    make_program_admin_headers,
    make_settlement_accountant_headers,
    make_variety,
    passed_lot_state,
    read_contract_version,
    record_inspection,
    set_clock,
    sign_contract_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

AT_TOLERANCE_COUNTS = {
    "sampled_plants": 20000,
    "off_type_plants": 20,
    "restricted_weed_plants": 10,
    "diseased_plants": 400,
    "isolation_verified_m": 250.0,
}
ONE_PLANT_OVER = dict(AT_TOLERANCE_COUNTS, off_type_plants=21)


def _two_signed_contracts(api):
    """One grower with two registered fields, each carrying a signed contract."""
    variety = make_variety(api)
    grower = make_grower(api)
    contracts = []
    for field_code, acres, contracted_acres, advance in (
        ("F-A", 320.0, 300.0, 1200000),
        ("F-B", 200.0, 150.0, 400000),
    ):
        field = make_production_field(
            api, grower["id"], field_code=field_code, acres=acres, isolation_distance_m=250.0
        )
        make_field_history_record(api, field["id"])
        contract = get_success_data(
            api.create_production_contract(
                create_production_contract_payload(
                    grower["id"],
                    variety["id"],
                    field["id"],
                    contracted_acres=contracted_acres,
                    advance_total_cents=advance,
                ),
                make_program_admin_headers(),
            )
        )
        get_success_data(api.offer_production_contract(contract["id"], {}, make_program_admin_headers()))
        contracts.append(
            get_success_data(
                api.sign_production_contract(
                    contract["id"], sign_contract_payload(), make_grower_headers(grower["id"])
                )
            )
        )
    set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
    return variety, grower, contracts


class TestOffTypeRateExactlyAtTolerancePasses:
    def test_three_rates_exactly_at_their_tolerances_all_pass(self, api):
        """Purity, weed and disease each land exactly on the tolerance and the walk passes.

        PRD: "Each rate is compared only against the variety's own tolerance, and every one of
        those comparisons is strictly greater-than: a rate exactly equal to the tolerance passes."

        Design: Difficulty/boundary_precision_check/off_type_rate_exactly_at_tolerance_passes
        """
        _variety, _grower, contracts = _two_signed_contracts(api)

        inspection = record_inspection(
            api, contracts[0]["id"], inspector_user_id="fo-1", **AT_TOLERANCE_COUNTS
        )
        assert_field_inspection(inspection)

        assert inspection["off_type_rate_per_10000"] == pytest.approx(10.00, abs=0.01)
        assert inspection["weed_rate_per_10000"] == pytest.approx(5.00, abs=0.01)
        assert inspection["disease_incidence_pct"] == pytest.approx(2.00, abs=0.01)
        assert inspection["outcome"] == "PASSED"
        assert inspection["status"] == "RECORDED"

        contract = get_success_data(
            api.get_production_contract(contracts[0]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "INSPECTION_PASSED"

    def test_one_plant_past_the_tolerance_orders_rogueing(self, api):
        """A single extra off-type plant tips the rate over the tolerance and orders rogueing.

        PRD: "A **purity breach** exists when the off-type rate is strictly greater than the
        variety's `max_off_type_per_10000`; a **weed breach** exists when the weed rate is
        strictly greater than the variety's `max_restricted_weed_per_10000`."

        Design: Difficulty/boundary_precision_check/off_type_rate_exactly_at_tolerance_passes
        """
        _variety, grower, contracts = _two_signed_contracts(api)
        record_inspection(api, contracts[0]["id"], inspector_user_id="fo-1", **AT_TOLERANCE_COUNTS)

        breaching = record_inspection(
            api, contracts[1]["id"], inspector_user_id="fo-2", **ONE_PLANT_OVER
        )
        assert breaching["off_type_rate_per_10000"] == pytest.approx(10.50, abs=0.01)
        assert breaching["outcome"] == "ROGUEING_ORDERED"

        headers = make_program_admin_headers()
        second = get_success_data(api.get_production_contract(contracts[1]["id"], headers))
        assert second["status"] == "ROGUEING_REQUIRED"

        standing = get_success_data(api.get_grower(grower["id"], headers))
        assert standing["compliance_flag_count"] == 1
        assert standing["status"] == "GOOD_STANDING"


class TestTagIssuanceAtGerminationValidityInstant:
    def test_tagging_is_still_permitted_at_the_exact_validity_instant(self, api):
        """At the boundary instant equal to `germination_valid_until` a tag may still be issued.

        PRD: "The germination result must still be live: the current logical clock instant must
        be at or before the lot's `germination_valid_until`, and at the exact boundary instant
        tagging is still permitted; past it the request is refused with
        `ERR_GERMINATION_VALIDITY_EXPIRED`."

        Design: Difficulty/boundary_precision_check/tag_issuance_at_germination_validity_instant
        """
        state = passed_lot_state(api)
        assert_instant_equals(
            state["seed_lot"]["germination_valid_until"], GOLDEN_FIGURES["GERMINATION_VALID_UNTIL"]
        )

        set_clock(api, GOLDEN_FIGURES["GERMINATION_VALID_UNTIL"])
        tag = issue_tag(api, state["seed_lot"]["id"], state["sample"]["id"])
        assert tag["status"] == "ISSUED"

        lot = get_success_data(api.get_seed_lot(state["seed_lot"]["id"], make_conditioning_manager_headers()))
        assert lot["certification_status"] == "TAGGED"
        assert lot["tagged_bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]

    def test_carryover_is_not_yet_due_at_that_same_instant(self, api):
        """The two gates are exact complements: tagging is open while carryover is still closed.

        PRD: "The platform models this by requiring the parent lot's germination result to have
        *lapsed* before a successor may be minted, which makes the carryover gate and the
        tag-issuance gate exact complements of one another: at the precise boundary instant equal
        to the lot's `germination_valid_until`, tag issuance is still allowed and carryover is not
        yet due."

        Design: Difficulty/boundary_precision_check/tag_issuance_at_germination_validity_instant
        """
        state = passed_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        set_clock(api, GOLDEN_FIGURES["GERMINATION_VALID_UNTIL"])
        issue_tag(api, lot_id, state["sample"]["id"])

        tagged = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        too_early = api.create_carryover(
            lot_id,
            create_carryover_payload(tagged["version"], next_season_year=2027),
            make_conditioning_manager_headers(),
        )
        error = validate_error(too_early, "ERR_RETEST_NOT_DUE", 409)
        assert error["error_id"] != "ERR_STALE_LOT_VERSION"

        set_clock(api, "2027-06-12T00:00:00Z")
        child = validate_success(
            api.create_carryover(
                lot_id,
                create_carryover_payload(tagged["version"], next_season_year=2027),
                make_conditioning_manager_headers(),
            ),
            201,
        )
        assert_seed_lot(child)
        assert child["certification_status"] == "RETEST_DUE"
        assert child["conditioning_status"] == "BAGGED"
        assert child["carryover_generation"] == 1
        assert child["parent_seed_lot_id"] == lot_id
        assert child["season_year"] == 2027
        assert child["gross_kg"] == pytest.approx(TEST_DEFAULTS["BAGGING_OUTPUT_KG"], abs=0.01)

        parent = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert parent["certification_status"] == "TAGGED"


class TestSettlementWithEmptyLineSetRejected:
    def test_a_contract_with_no_tagged_lot_cannot_be_settled(self, api):
        """An empty line set is refused outright rather than settled at zero.

        PRD: "When the filter selects nothing at all, the request is refused with
        `ERR_NO_SETTLEABLE_LOTS` rather than being settled at zero."

        Design: Difficulty/boundary_precision_check/settlement_with_empty_line_set_rejected
        """
        state = harvested_lot_state(api)
        version = read_contract_version(api, state["contract"]["id"])

        response = api.create_settlement(
            create_settlement_payload(state["contract"]["id"], version),
            make_settlement_accountant_headers(),
        )
        validate_error(response, "ERR_NO_SETTLEABLE_LOTS", 422)

    def test_the_refused_computation_leaves_the_contract_and_lot_untouched(self, api):
        """No settlement is persisted and no money or unit total moves.

        PRD: "The rollup selects its lines by a narrow filter: every seed lot of that contract
        whose `certification_status` is `TAGGED` and whose `final_clean_units` is not null,
        ordered by `created_at` ascending with `lot_code` ascending as the tie-break."

        Design: Difficulty/boundary_precision_check/settlement_with_empty_line_set_rejected
        """
        state = harvested_lot_state(api)
        contract_id = state["contract"]["id"]
        version = read_contract_version(api, contract_id)
        api.create_settlement(
            create_settlement_payload(contract_id, version), make_settlement_accountant_headers()
        )

        settlements, meta = validate_paginated(
            api.list_settlements(make_settlement_accountant_headers(), {"production_contract_id": contract_id})
        )
        assert meta["total_count"] == 0
        assert settlements == []

        contract = get_success_data(api.get_production_contract(contract_id, make_program_admin_headers()))
        assert contract["status"] == "HARVESTED"
        assert contract["certified_units_total"] == pytest.approx(0.0, abs=0.01)
        assert contract["advance_outstanding_cents"] == TEST_DEFAULTS["ADVANCE_TOTAL_CENTS"]

        lot = get_success_data(api.get_seed_lot(state["seed_lot"]["id"], make_conditioning_manager_headers()))
        assert lot["conditioning_status"] == "RAW"
        assert lot["certification_status"] == "UNSAMPLED"
