"""The two version pins and the reconciliation of a derived roll-up over its source set."""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    SETTLEMENT_ACCOUNTANT_ID,
    TEST_DEFAULTS,
    assert_grower_settlement,
    assert_instant_equals,
    assert_seed_lot,
    create_carryover_payload,
    create_certification_tag_payload,
    create_settlement_payload,
    get_success_data,
    issue_tag,
    make_certification_agency_headers,
    make_conditioning_manager_headers,
    make_program_admin_headers,
    make_settlement_accountant_headers,
    passed_lot_state,
    read_contract_version,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    void_certification_tag_payload,
)

CARRYOVER_CLOCK = "2027-06-12T00:00:00Z"
CARRYOVER_SEASON_YEAR = 2027
VOID_REASON = "Tags printed with the wrong lot serial"
ZERO_UNITS = 0.0


class TestSettlementCreatePinsTheContractVersion:
    def test_a_contract_version_read_before_tagging_is_stale_once_the_tag_is_issued(self, api):
        """Tagging moves the version under the accountant's feet, so her pinned figure is refused.

        PRD: "A settlement computation request — `POST /seed-ops/settlements` — must carry
        `expected_contract_version` as a required, non-optional input field, holding the `version` of
        the target `ProductionContract` as the accountant last observed it."

        PRD: "If that value does not equal the contract's current `version`, the request is rejected
        with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

        PRD: "The lot's `final_clean_units` is added to the originating contract's
        `certified_units_total` and the contract's `version` increments by 1."

        PRD: "The settlement then records `line_count` as the number of lines folded in,
        `settled_units_total` as the sum of the lines' clean unit figures rounded half-up to two
        decimal places, `gross_payable_cents` as the sum of the already-rounded line gross amounts,
        and `conditioning_charges_cents` as the sum of the already-rounded line charges."

        PRD: "A computed settlement records the computing accountant's `X-User-ID` as
        `computed_by_user_id`, lands in `COMPUTED` status with `quality_hold` false, and carries
        `approved_by_user_id`, `dispute_reason` and `payment_reference` all null."

        PRD: "Computing a settlement also increments the contract's `version` by 1, which is what
        makes a second computation against a version the accountant has not re-read fail the version
        pin."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_version_on_settlement_create
        """
        state = passed_lot_state(api)
        contract_id = state["contract"]["id"]
        accountant = make_settlement_accountant_headers()
        stale_version = read_contract_version(api, contract_id)

        issue_tag(api, state["seed_lot"]["id"], state["sample"]["id"])

        response = api.create_settlement(
            create_settlement_payload(contract_id, stale_version), accountant
        )
        validate_error(response, "ERR_STALE_CONTRACT_VERSION", 412)

        _refused, refused_meta = validate_paginated(
            api.list_settlements(accountant, {"production_contract_id": contract_id})
        )
        assert refused_meta["total_count"] == 0

        current_version = read_contract_version(api, contract_id)
        assert current_version == stale_version + 1

        settlement = validate_success(
            api.create_settlement(
                create_settlement_payload(contract_id, current_version), accountant
            ),
            201,
        )
        assert_grower_settlement(settlement)
        assert settlement["status"] == "COMPUTED"
        assert settlement["computed_by_user_id"] == SETTLEMENT_ACCOUNTANT_ID
        assert settlement["quality_hold"] is False
        assert settlement["approved_by_user_id"] is None
        assert settlement["line_count"] == 1
        assert settlement["settled_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )
        assert settlement["gross_payable_cents"] == GOLDEN_FIGURES["GROSS_PAYABLE_CENTS"]
        assert settlement["conditioning_charges_cents"] == GOLDEN_FIGURES[
            "CONDITIONING_CHARGES_CENTS"
        ]

        _one, one_meta = validate_paginated(
            api.list_settlements(accountant, {"production_contract_id": contract_id})
        )
        assert one_meta["total_count"] == 1

        contract = get_success_data(
            api.get_production_contract(contract_id, make_program_admin_headers())
        )
        assert contract["status"] == "HARVESTED"
        assert contract["version"] == current_version + 1
        assert contract["certified_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )


class TestCarryoverPinsTheParentLotVersion:
    def test_a_lot_version_read_before_tagging_is_refused_even_with_the_retest_genuinely_due(
        self, api
    ):
        """The second pin guards a different parent, and it outranks the open retest window.

        PRD: "A carryover minting request — `POST /seed-ops/seed-lots/{seed_lot_id}/carryover` — must
        likewise carry `expected_seed_lot_version` as a required, non-optional input field, holding
        the `version` of the parent `SeedLot` as the manager last observed it."

        PRD: "A mismatch against the parent lot's current `version` is rejected with
        `ERR_STALE_LOT_VERSION` (HTTP 412)."

        PRD: "The supplied version must match the parent's current `version`, or the request is
        refused with `ERR_STALE_LOT_VERSION`."

        PRD: "The current logical clock instant must be strictly after the parent's
        `germination_valid_until`, or the request is refused with `ERR_RETEST_NOT_DUE`."

        PRD: "Its `parent_seed_lot_id` points at the parent, establishing the self-referential
        lineage that lets a lot be traced back through every season it survived."

        PRD: "Its `carryover_generation` is the parent's generation plus one."

        PRD: "Its `conditioning_status` is `BAGGED` — no conditioning run will ever be planned
        against it — and its `certification_status` is `RETEST_DUE`, which is the one certification
        state that exists purely to say "this seed is physically ready but its paperwork has
        expired"."

        PRD: "Its `gross_kg` and its `current_kg` both take the parent's `current_kg`, with
        `cumulative_shrink_kg` and `dockage_pct` starting at 0, so the conserved mass identity of
        §2.11 holds on the successor from birth."

        PRD: "The parent lot itself is left in place."

        PRD: "Its `certification_status` stays `TAGGED`, its tags stay `ISSUED`, and its
        `tagged_bag_count` is unchanged — the only thing minting a successor does to the parent is
        increment the parent's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_lot_version_on_carryover
        """
        state = passed_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        manager = make_conditioning_manager_headers()
        stale_version = get_success_data(api.get_seed_lot(lot_id, manager))["version"]

        tag = issue_tag(api, lot_id, state["sample"]["id"])
        set_clock(api, CARRYOVER_CLOCK)

        response = api.create_carryover(
            lot_id,
            create_carryover_payload(stale_version, next_season_year=CARRYOVER_SEASON_YEAR),
            manager,
        )
        error = validate_error(response, "ERR_STALE_LOT_VERSION", 412)
        assert error["error_id"] != "ERR_RETEST_NOT_DUE"

        _children, children_meta = validate_paginated(
            api.list_seed_lots(manager, {"parent_seed_lot_id": lot_id})
        )
        assert children_meta["total_count"] == 0

        parent = get_success_data(api.get_seed_lot(lot_id, manager))
        assert parent["certification_status"] == "TAGGED"
        assert parent["version"] == stale_version + 1
        assert_instant_equals(parent["germination_valid_until"], GOLDEN_FIGURES["GERMINATION_VALID_UNTIL"])

        successor = validate_success(
            api.create_carryover(
                lot_id,
                create_carryover_payload(
                    parent["version"], next_season_year=CARRYOVER_SEASON_YEAR
                ),
                manager,
            ),
            201,
        )
        assert_seed_lot(successor)
        assert successor["parent_seed_lot_id"] == lot_id
        assert successor["carryover_generation"] == 1
        assert successor["certification_status"] == "RETEST_DUE"
        assert successor["conditioning_status"] == "BAGGED"
        assert successor["season_year"] == CARRYOVER_SEASON_YEAR
        assert successor["gross_kg"] == pytest.approx(TEST_DEFAULTS["BAGGING_OUTPUT_KG"], abs=0.001)
        assert successor["current_kg"] == pytest.approx(
            TEST_DEFAULTS["BAGGING_OUTPUT_KG"], abs=0.001
        )
        assert successor["cumulative_shrink_kg"] == pytest.approx(0.0, abs=0.001)
        assert successor["tagged_bag_count"] == 0
        assert successor["germination_valid_until"] is None

        after = get_success_data(api.get_seed_lot(lot_id, manager))
        assert after["certification_status"] == "TAGGED"
        assert after["tagged_bag_count"] == TEST_DEFAULTS["TAG_BAG_COUNT"]
        assert after["version"] == parent["version"] + 1

        held = get_success_data(
            api.get_certification_tag(tag["id"], make_certification_agency_headers())
        )
        assert held["status"] == "ISSUED"


class TestCertifiedUnitsTotalIsReconciledAfterEverySourceChange:
    def test_the_contract_rollup_follows_the_tag_through_issue_void_and_reissue(self, api):
        """The roll-up is recomputed at each source change, not written once at the first tag.

        PRD: "Derived roll-up fields are reconciled rather than incrementally patched wherever the
        scaffold of the business rule is a sum over a filtered set."

        PRD: "A contract's certified unit total is a roll-up over that contract's lots whose
        certification status is `TAGGED`; a lot's tagged bag count is a roll-up over its issued tags;
        a field's history record count is a roll-up over its history records."

        PRD: "When a cascade invalidates a member of one of those sets, the roll-up is recomputed
        from the surviving members, not adjusted by guesswork."

        PRD: "Issuing a tag mints a deterministic `tag_serial` of the form
        `TAG-{season_year}-{6-digit issuance sequence}` — the lot's season year followed by a
        six-digit, zero-padded issuance sequence number — stamps `issued_at` with the current logical
        clock instant, and puts the tag in `ISSUED` status with `void_reason` null."

        PRD: "The tag's `bag_count` is added to the lot's `tagged_bag_count`, and the lot's
        certification status advances `PASSED → TAGGED`."

        PRD: "The lot's `final_clean_units` is added to the originating contract's
        `certified_units_total` and the contract's `version` increments by 1."

        PRD: "Voiding stores the reason, moves the tag `ISSUED → VOIDED`, and subtracts the tag's
        `bag_count` back out of the lot's `tagged_bag_count`, restoring the invariant that the lot's
        tagged bag count equals the sum of bag counts over its still-issued tags."

        PRD: "When that subtraction brings the lot's `tagged_bag_count` down to 0, the lot's
        certification status returns `TAGGED → PASSED` and the lot's `final_clean_units` is
        subtracted back out of the contract's `certified_units_total`."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_certified_units_total
        """
        state = passed_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        contract_id = state["contract"]["id"]
        agency = make_certification_agency_headers()
        manager = make_conditioning_manager_headers()
        admin = make_program_admin_headers()

        first_tag = validate_success(
            api.create_certification_tag(
                create_certification_tag_payload(lot_id, state["sample"]["id"]), agency
            ),
            201,
        )
        assert first_tag["status"] == "ISSUED"
        assert first_tag["void_reason"] is None

        tagged_lot = get_success_data(api.get_seed_lot(lot_id, manager))
        assert tagged_lot["tagged_bag_count"] == TEST_DEFAULTS["TAG_BAG_COUNT"]
        assert tagged_lot["certification_status"] == "TAGGED"
        tagged_contract = get_success_data(api.get_production_contract(contract_id, admin))
        assert tagged_contract["certified_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )

        voided = validate_success(
            api.void_certification_tag(
                first_tag["id"], void_certification_tag_payload(void_reason=VOID_REASON), agency
            ),
            200,
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == VOID_REASON

        untagged_lot = get_success_data(api.get_seed_lot(lot_id, manager))
        assert untagged_lot["tagged_bag_count"] == 0
        assert untagged_lot["certification_status"] == "PASSED"
        emptied_contract = get_success_data(api.get_production_contract(contract_id, admin))
        assert emptied_contract["certified_units_total"] == pytest.approx(ZERO_UNITS, abs=0.01)

        second_tag = validate_success(
            api.create_certification_tag(
                create_certification_tag_payload(lot_id, state["sample"]["id"]), agency
            ),
            201,
        )
        assert second_tag["status"] == "ISSUED"
        assert second_tag["tag_serial"] != first_tag["tag_serial"]

        retagged_lot = get_success_data(api.get_seed_lot(lot_id, manager))
        assert retagged_lot["tagged_bag_count"] == TEST_DEFAULTS["TAG_BAG_COUNT"]
        assert retagged_lot["certification_status"] == "TAGGED"
        restored_contract = get_success_data(api.get_production_contract(contract_id, admin))
        assert restored_contract["certified_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )

        tags, tags_meta = validate_paginated(
            api.list_certification_tags(agency, {"seed_lot_id": lot_id})
        )
        assert tags_meta["total_count"] == 2
        assert {tag["status"] for tag in tags} == {"ISSUED", "VOIDED"}
