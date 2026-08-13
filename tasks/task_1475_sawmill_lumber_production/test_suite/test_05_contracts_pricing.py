"""Contract lifecycle, spot pricing formula, OCC amendment, and ops-run expiry."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    publish_price_list, create_contract, create_active_contract, place_order,
    get_contract, set_clock, run_ops_checkpoint,
    create_sales_order_payload, amend_sales_contract_payload,
    make_sales_rep_headers, make_mill_manager_headers,
)


class TestSpotPricing:
    def test_spot_price_length_16_with_top_volume_discount(self, api):
        """PRD Section 3.7: "The quote then applies a length multiplier to the row's base price: 0.96 for `RL`, 0.95 for length 8, 0.97 for length 10, 1.00 for length 12, and 1.08 for length 16."
        PRD Section 3.7: "A volume discount follows: 5 percent off when `volume_mbf` is at least 50, otherwise 2 percent off when it is at least 10, otherwise no discount."

        Design: Difficulty/combinatorial_formula/spot_price_length_tier_volume_discount
        """
        publish_price_list()  # base 60000 effective 2026-07-01
        order = place_order(customer_name="Bridgeline Homes", length_spec=16, volume_mbf=60)
        assert order["pricing_mode"] == "SPOT"
        assert order["status"] == "PLACED"
        # round(60000 * 1.08) = 64800; 60 >= 50 -> 5% -> round(64800 * 0.95) = 61560
        assert order["unit_price_cents"] == 61560, (
            f"two-step rounding: 64800 then 61560, got {order['unit_price_cents']}"
        )

    def test_spot_price_length_8_below_discount_threshold(self, api):
        """PRD Section 3.7: "The pinned `unit_price_cents` is computed in two rounding steps, and the order of the steps is part of the contract: first multiply the base price by the length multiplier and round half-up to whole cents, then multiply that rounded figure by one minus the discount and round half-up to whole cents again."

        Design: Difficulty/combinatorial_formula/spot_price_length_tier_volume_discount
        """
        publish_price_list()
        order = place_order(customer_name="Bridgeline Homes", length_spec=8, volume_mbf=5)
        # round(60000 * 0.95) = 57000; volume 5 < 10 -> no discount
        assert order["unit_price_cents"] == 57000, (
            f"no volume discount below 10 mbf, got {order['unit_price_cents']}"
        )

    def test_volume_discount_boundary_exactly_10(self, api):
        """PRD Section 3.7: "A volume discount follows: 5 percent off when `volume_mbf` is at least 50, otherwise 2 percent off when it is at least 10, otherwise no discount."

        Design: Corner/calculations/volume_discount_boundary_exactly_10
        """
        publish_price_list()
        at_tier = place_order(customer_name="B1", length_spec=12, volume_mbf=10)
        # round(60000 * 1.00) = 60000; 10 >= 10 -> 2% -> round(60000 * 0.98) = 58800
        assert at_tier["unit_price_cents"] == 58800, (
            f"10 mbf qualifies for the 2 percent bracket, got {at_tier['unit_price_cents']}"
        )
        below_tier = place_order(customer_name="B2", length_spec=12, volume_mbf=9.999)
        assert below_tier["unit_price_cents"] == 60000, (
            f"9.999 mbf earns no discount, got {below_tier['unit_price_cents']}"
        )

    def test_spot_order_without_price_list_returns_no_price_list(self, api):
        """PRD Section 3.7: "An empty pool — no effective row for that species and grade — rejects the placement with `ERR_NO_PRICE_LIST` (HTTP 422)."

        Design: Corner/validations/spot_order_without_price_list_returns_no_price_list
        """
        res = api.create_sales_order(
            create_sales_order_payload(species="HEMLOCK_FIR", volume_mbf=5),
            make_sales_rep_headers(),
        )
        validate_error(res, ApiErrorId.ERR_NO_PRICE_LIST)


class TestContractPlacementGuards:
    def test_order_against_draft_contract_rejected(self, api):
        """PRD Section 3.7: "The referenced contract must be `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409) — orders against `DRAFT`, `CLOSED`, or `EXPIRED` contracts are all refused here, and the same refusal applies when allocation would touch a non-active contract."

        Design: Difficulty/cross_entity_state_dependency/order_placement_gated_on_contract_active
        """
        contract = create_contract()  # stays DRAFT
        res = api.create_sales_order(
            create_sales_order_payload(contract_id=contract["id"], volume_mbf=5),
            make_sales_rep_headers(),
        )
        validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    def test_rejected_placement_records_no_drawdown(self, api):
        """PRD Section 3.7: "A contract's `reserved_mbf` is the sum of `volume_mbf` over its orders in `PLACED` or `ALLOCATED`, and its `remaining_mbf` is `committed_mbf` minus `reserved_mbf`; placing the order immediately adds its `volume_mbf` to that reservation."

        Design: Difficulty/cross_entity_state_dependency/order_placement_gated_on_contract_active
        """
        contract = create_contract()
        res = api.create_sales_order(
            create_sales_order_payload(contract_id=contract["id"], volume_mbf=5),
            make_sales_rep_headers(),
        )
        validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
        after = get_contract(contract["id"])
        assert after["reserved_mbf"] == 0, f"no reservation on a refused order, got {after['reserved_mbf']}"
        assert after["status"] == "DRAFT"

    def test_contract_volume_exceeded_on_placement(self, api):
        """PRD Section 3.7: "And the order's `volume_mbf` must not exceed the contract's `remaining_mbf`, otherwise `ERR_CONTRACT_VOLUME_EXCEEDED`."

        Design: Corner/validations/contract_volume_exceeded_on_placement
        """
        contract = create_active_contract(committed_mbf=5)
        res = api.create_sales_order(
            create_sales_order_payload(contract_id=contract["id"], volume_mbf=6),
            make_sales_rep_headers(),
        )
        validate_error(res, ApiErrorId.ERR_CONTRACT_VOLUME_EXCEEDED)
        assert get_contract(contract["id"])["reserved_mbf"] == 0


class TestContractAmendmentOcc:
    def test_amend_with_observed_version_succeeds(self, api):
        """PRD Section 3.7: "The amendment request must carry `expected_contract_version` equal to the contract's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD Section 3.7: "A successful amendment increments `version`, which is exactly the mechanism that makes the next stale writer detectable."

        Design: Corner/complexity_layers/contract_amend_occ_conflict_and_success
        """
        contract = create_contract()
        cv = contract["version"]
        amended = validate_success(api.amend_sales_contract(
            contract["id"],
            amend_sales_contract_payload(cv, contract_price_per_mbf_cents=56000),
            make_mill_manager_headers(),
        ), 200)
        assert amended["version"] == cv + 1, (
            f"amendment increments version: {cv} -> {amended['version']}"
        )
        assert amended["contract_price_per_mbf_cents"] == 56000

    def test_amend_replay_with_stale_version_rejected(self, api):
        """PRD Section 2.7: "If the contract's current `version` has advanced beyond that value — because another amendment or a lifecycle transition landed in the meantime — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently overwriting contract terms it never saw."

        Design: Corner/complexity_layers/contract_amend_occ_conflict_and_success
        """
        contract = create_contract()
        cv = contract["version"]
        validate_success(api.amend_sales_contract(
            contract["id"],
            amend_sales_contract_payload(cv, contract_price_per_mbf_cents=56000),
            make_mill_manager_headers(),
        ), 200)
        stale = api.amend_sales_contract(
            contract["id"],
            amend_sales_contract_payload(cv, contract_price_per_mbf_cents=57000),
            make_mill_manager_headers(),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        after = get_contract(contract["id"])
        assert after["contract_price_per_mbf_cents"] == 56000, (
            f"rejected amendment did not apply, got {after['contract_price_per_mbf_cents']}"
        )


class TestOpsCheckpointExpiry:
    def test_ops_run_expires_contract_past_end_date(self, api):
        """PRD Section 3.9: "First, contract expiry: every contract still `ACTIVE` whose `end_date` falls before the current logical date flips to `EXPIRED` and increments its `version`."
        PRD Section 3.9: "The checkpoint responds with the list of contracts it expired and the list of loads whose degrade it refreshed — the `expired_contract_ids` and `degraded_load_ids` arrays — and returns 200."

        Design: Corner/complexity_layers/ops_run_expires_contract_past_end_date
        """
        contract = create_active_contract(end_date="2026-08-10")
        set_clock("2026-08-11T00:00:00Z")
        data = run_ops_checkpoint()
        assert contract["id"] in data["expired_contract_ids"], (
            f"checkpoint reports the expired contract, got {data['expired_contract_ids']}"
        )
        after = get_contract(contract["id"])
        assert after["status"] == "EXPIRED", f"got {after['status']}"
