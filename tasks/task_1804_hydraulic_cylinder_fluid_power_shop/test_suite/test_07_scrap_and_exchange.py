"""Scrap path, exchange-pool lifecycle, and core-credit variants (PRD §3.8)."""
from test_helpers import (
    ADVISOR,
    INSPECTOR,
    ApiErrorId,
    close_work_order,
    create_exchange_unit,
    create_exchange_unit_payload,
    create_shop,
    get_success_data,
    make_customer_headers,
    setup_exchange_fulfilled,
    setup_exchange_selected,
    setup_exchange_settled,
    setup_quote_sent,
    validate_error,
    validate_paginated,
    validate_success,
)


def _pool_count(api) -> int:
    _data, meta = validate_paginated(
        api.list_exchange_units(ADVISOR, params={"status": "IN_POOL", "limit": 100})
    )
    return meta["total_count"]


class TestScrapPath:
    def test_complete_scrap_without_authorization_rejected(self, api):
        """PRD §3.8: "Completing the scrap is then a `ShopAdmin` or
        `ServiceAdvisor` action that records a `disposal_method`; attempted
        before the customer's authorization it is rejected with
        `ERR_SCRAP_NOT_AUTHORIZED`, and on success the work order moves to the
        terminal `SCRAPPED` state and the cylinder cascades from `ACTIVE` to
        `RETIRED`."

        Design: Corner/state_machines/complete_scrap_without_authorization_rejected
        """
        sc = setup_quote_sent(rod_needed=False, honing_passes=0, estimated_labor_hours=1.0)
        resp = api.complete_scrap(
            sc.work_order["id"], {"disposal_method": "certified recycler"}, ADVISOR
        )
        validate_error(resp, ApiErrorId.ERR_SCRAP_NOT_AUTHORIZED)
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "QUOTE_SENT"

    def test_scrap_path_cascades_and_terminal_lockdown(self, api):
        """PRD §3.8: "Authorizing scrap — available to the owning `Customer`
        while the work order is in `QUOTE_SENT` or `REVISION_REQUESTED`
        (`ERR_NOT_OWNER` for anyone else) — moves the work order to
        `SCRAP_AUTHORIZED`; when the decision comes from `QUOTE_SENT`, the `SENT`
        quote moves to `REJECTED_SCRAP`."
        PRD §3.8: "on success the work order moves to the terminal `SCRAPPED`
        state and the cylinder cascades from `ACTIVE` to `RETIRED`."
        PRD §2.7: "A resource sitting in a terminal state — `CLOSED`, `SCRAPPED`,
        or `CANCELLED` for a work order; `APPROVED`, `EXPIRED`, `SUPERSEDED`, or
        `REJECTED_SCRAP` for a quote; `CONSUMED` or `RELEASED` for a reservation;
        `PASSED`, `FAILED`, `VOIDED`, or `CANCELLED` for a pressure test;
        `REVOKED` for a certificate; `SETTLED` for an exchange unit; `DEPLETED`
        for an inventory item; `COMPLETED` or `CANCELLED` for a field service
        job; `RETIRED` or `EXCHANGED` for a cylinder — rejects every further
        transition with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/scrap_path_cascades_and_terminal_lockdown
        """
        sc = setup_quote_sent(rod_needed=False, honing_passes=0,
                              estimated_labor_hours=3.0)
        authorized = validate_success(
            api.authorize_scrap(
                sc.work_order["id"], make_customer_headers(sc.customer["id"])
            )
        )
        assert authorized["status"] == "SCRAP_AUTHORIZED"
        quote = get_success_data(api.get_quote(sc.quote["id"], ADVISOR))
        assert quote["status"] == "REJECTED_SCRAP"
        scrapped = validate_success(
            api.complete_scrap(
                sc.work_order["id"], {"disposal_method": "certified recycler"}, ADVISOR
            )
        )
        assert scrapped["status"] == "SCRAPPED"
        cylinder = get_success_data(api.get_cylinder(sc.cylinder["id"], ADVISOR))
        assert cylinder["status"] == "RETIRED"
        resp = api.cancel_work_order(sc.work_order["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestExchangeUnitPool:
    def test_exchange_unit_created_in_pool(self, api):
        """PRD §3.8: "A new unit starts `IN_POOL` with `work_order_id`,
        `provisional_credit_cents`, `condition`, `completeness`, and
        `final_credit_cents` all null."

        Design: Corner/entities/exchange_unit_created_in_pool
        """
        create_shop()
        unit = create_exchange_unit()
        assert unit["status"] == "IN_POOL"
        assert unit["work_order_id"] is None
        assert unit["provisional_credit_cents"] is None
        assert unit["condition"] is None
        assert unit["completeness"] is None
        assert unit["final_credit_cents"] is None

    def test_select_exchange_spec_mismatch_rejected(self, api):
        """PRD §3.8: "The unit must be `IN_POOL` — otherwise
        `ERR_UNIT_NOT_IN_POOL` — and its `bore_mm`, `stroke_mm`,
        `rod_diameter_mm`, and `pressure_class` must each exactly equal the
        cylinder's, otherwise `ERR_SPEC_MISMATCH`."

        Design: Corner/validations/select_exchange_spec_mismatch_rejected
        """
        sc = setup_quote_sent(rod_needed=False, honing_passes=0, estimated_labor_hours=1.0)
        unit = create_exchange_unit(bore_mm=100)  # cylinder bore is 80
        resp = api.select_exchange(
            sc.work_order["id"],
            {"exchange_unit_id": unit["id"]},
            make_customer_headers(sc.customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SPEC_MISMATCH)
        unit_after = get_success_data(api.get_exchange_unit(unit["id"], ADVISOR))
        assert unit_after["status"] == "IN_POOL"
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "QUOTE_SENT"

    def test_receive_core_before_fulfill_rejected(self, api):
        """PRD §3.8: "A `ShopAdmin` or `ServiceAdvisor` logs its arrival, moving
        the deal from `FULFILLED` to `CORE_RECEIVED`; attempting to receive a
        core before fulfilment is rejected with `ERR_EXCHANGE_NOT_FULFILLED`."

        Design: Corner/validations/receive_core_before_fulfill_rejected
        """
        sc = setup_exchange_selected()
        resp = api.receive_core(sc.unit["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_EXCHANGE_NOT_FULFILLED)
        unit = get_success_data(api.get_exchange_unit(sc.unit["id"], ADVISOR))
        assert unit["status"] == "RESERVED"


class TestCoreCreditVariants:
    def test_provisional_credit_assumes_good_complete_at_fulfill(self, api):
        """PRD §3.8: "Fulfilment moves the unit to `FULFILLED`, computes its
        `provisional_credit_cents` under the provisional core-credit variant —
        which assumes the returned core will grade `GOOD` and `COMPLETE` —
        cascades the cylinder from `ACTIVE` to `EXCHANGED`, and moves the work
        order from `EXCHANGE_SELECTED` to `EXCHANGE_FULFILLED`."
        PRD §3.8: "The credit is the lesser of the two, never below zero."

        Design: Difficulty/dual_variant_calc/exchange_core_credit_provisional_vs_final
        """
        sc = setup_exchange_selected()
        fulfilled = validate_success(api.fulfill_exchange_unit(sc.unit["id"], ADVISOR))
        assert fulfilled["status"] == "FULFILLED"
        # min(cap = round_half_down(250000 x 0.30) = 75000, 40000 x 1.0 x 1.0).
        assert fulfilled["provisional_credit_cents"] == 40000
        cylinder = get_success_data(api.get_cylinder(sc.cylinder["id"], ADVISOR))
        assert cylinder["status"] == "EXCHANGED"
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "EXCHANGE_FULFILLED"

    def test_final_credit_diverges_after_grading(self, api):
        """PRD §3.8: "The provisional variant at fulfilment assumes `GOOD` and
        `COMPLETE`; the final variant at grading uses the inspected values and
        may diverge arbitrarily from the provisional figure."
        PRD §3.8: "The condition factor is 1.0 for `GOOD`, 0.6 for `WORN`, 0.25
        for `DAMAGED`, and 0.0 for `SCRAP`; the completeness factor is 1.0 for
        `COMPLETE` and 0.5 for `MISSING_PARTS`."

        Design: Difficulty/dual_variant_calc/exchange_core_credit_provisional_vs_final
        """
        sc = setup_exchange_settled(condition="WORN", completeness="COMPLETE")
        # Final: 40000 x 0.6 x 1.0 = 24000, diverging from provisional 40000.
        assert sc.unit["status"] == "SETTLED"
        assert sc.unit["final_credit_cents"] == 24000
        assert sc.unit["provisional_credit_cents"] == 40000
        assert sc.unit["final_credit_cents"] != sc.unit["provisional_credit_cents"]


class TestReserveReleaseCycle:
    def test_release_returns_unit_to_pool_with_fields_cleared(self, api):
        """PRD §3.8: "a `ShopAdmin` or `ServiceAdvisor` releases a `RESERVED`
        unit back to `IN_POOL`, clearing its `work_order_id` and
        `provisional_credit_cents`, while the linked work order remains
        `EXCHANGE_SELECTED` and may select another unit — the reserve-release
        cycle `IN_POOL` → `RESERVED` → `IN_POOL`."

        Design: Difficulty/non_linear_state_machine/exchange_unit_reserve_release_cycle
        """
        sc = setup_exchange_selected()
        assert sc.unit["status"] == "RESERVED"
        released = validate_success(api.release_exchange_unit(sc.unit["id"], ADVISOR))
        assert released["status"] == "IN_POOL"
        assert released["work_order_id"] is None
        assert released["provisional_credit_cents"] is None
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "EXCHANGE_SELECTED"

    def test_released_unit_can_be_reserved_again(self, api):
        """PRD §3.8: "a `ShopAdmin` or `ServiceAdvisor` releases a `RESERVED`
        unit back to `IN_POOL`, clearing its `work_order_id` and
        `provisional_credit_cents`, while the linked work order remains
        `EXCHANGE_SELECTED` and may select another unit — the reserve-release
        cycle `IN_POOL` → `RESERVED` → `IN_POOL`."

        Design: Difficulty/non_linear_state_machine/exchange_unit_reserve_release_cycle
        """
        sc = setup_exchange_selected()
        second = create_exchange_unit(unit_price_cents=260000)
        validate_success(api.release_exchange_unit(sc.unit["id"], ADVISOR))
        # The work order remains EXCHANGE_SELECTED and may select another unit.
        wo = validate_success(
            api.select_exchange(
                sc.work_order["id"],
                {"exchange_unit_id": second["id"]},
                make_customer_headers(sc.customer["id"]),
            )
        )
        assert wo["status"] == "EXCHANGE_SELECTED"
        second_after = get_success_data(api.get_exchange_unit(second["id"], ADVISOR))
        assert second_after["status"] == "RESERVED"
        assert second_after["work_order_id"] == sc.work_order["id"]


class TestPoolCountConservation:
    def test_reserve_decrements_pool_count(self, api):
        """PRD §3.8: "Selection supersedes the `SENT` quote, moves the unit from
        `IN_POOL` to `RESERVED` with its `work_order_id` set to this work order,
        and moves the work order to `EXCHANGE_SELECTED`."
        PRD §3.8: "The pool can be listed with filters on `status`,
        `work_order_id`, and `bore_mm`."

        Design: Difficulty/compensating_invariant/exchange_pool_count_conservation_reserve_release
        """
        sc = setup_quote_sent(rod_needed=False, honing_passes=0, estimated_labor_hours=1.0)
        unit1 = create_exchange_unit()
        create_exchange_unit(unit_price_cents=260000)
        assert _pool_count(api) == 2
        validate_success(
            api.select_exchange(
                sc.work_order["id"],
                {"exchange_unit_id": unit1["id"]},
                make_customer_headers(sc.customer["id"]),
            )
        )
        assert _pool_count(api) == 1

    def test_release_restores_pool_count_and_clears_deal_fields(self, api):
        """PRD §3.8: "a `ShopAdmin` or `ServiceAdvisor` releases a `RESERVED`
        unit back to `IN_POOL`, clearing its `work_order_id` and
        `provisional_credit_cents`, while the linked work order remains
        `EXCHANGE_SELECTED` and may select another unit — the reserve-release
        cycle `IN_POOL` → `RESERVED` → `IN_POOL`."

        Design: Difficulty/compensating_invariant/exchange_pool_count_conservation_reserve_release
        """
        sc = setup_quote_sent(rod_needed=False, honing_passes=0, estimated_labor_hours=1.0)
        unit1 = create_exchange_unit()
        create_exchange_unit(unit_price_cents=260000)
        validate_success(
            api.select_exchange(
                sc.work_order["id"],
                {"exchange_unit_id": unit1["id"]},
                make_customer_headers(sc.customer["id"]),
            )
        )
        assert _pool_count(api) == 1
        validate_success(api.release_exchange_unit(unit1["id"], ADVISOR))
        assert _pool_count(api) == 2
        unit1_after = get_success_data(api.get_exchange_unit(unit1["id"], ADVISOR))
        assert unit1_after["work_order_id"] is None
        assert unit1_after["provisional_credit_cents"] is None


class TestScrapCoreSettlement:
    def test_scrap_core_zero_credit_and_disposal_fee_on_close(self, api):
        """PRD §3.8: "A core graded `SCRAP` earns zero credit and instead adds a
        `core_disposal_fee_cents` charge (7500 by default) at the work order's
        close."
        PRD §3.8: "The invoice is the unit's `unit_price_cents` minus its
        `final_credit_cents`, plus the `core_disposal_fee_cents` when the core's
        `condition` is `SCRAP`; `core_credit_applied_cents` records the
        `final_credit_cents` actually applied, and the customer's
        `ytd_spend_cents` again increases by `invoice_total_cents`."

        Design: Corner/calculations/scrap_core_zero_credit_and_disposal_fee_on_close
        """
        sc = setup_exchange_settled(condition="SCRAP", completeness="MISSING_PARTS")
        assert sc.unit["final_credit_cents"] == 0
        closed = close_work_order(sc.work_order, 0)
        assert closed["status"] == "CLOSED"
        # 250000 - 0 + 7500 disposal fee.
        assert closed["invoice_total_cents"] == 257500
        assert closed["core_credit_applied_cents"] == 0
