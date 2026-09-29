"""Dual-variant money and cadence calculations.

Three calculations in this platform carry more than one variant, and the variant
is selected by a field on the request rather than by the caller: the return
settlement rounding granularity is selected by the return `reason`, and the
auto-reorder cadence supply figure is selected by `cadence_basis`. Each test
below pins one variant against its sibling on byte-identical physical inputs, so
an implementation that collapses the variants into a single formula is caught.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CO_ALPHA_HEADERS,
    create_auto_reorder_schedule_payload,
    create_return_request_payload,
    make_customer_headers,
    new_auto_reorder_schedule,
    new_return_request,
    setup_shipped_order,
    setup_verified_prescription,
    validate_success,
)

# Every scenario below sells the same SKU: a 3200-cent box of 30 daily-disposable
# lenses, so the per-box value and the lenses-per-box divisor are both pinned and
# the proration arithmetic is fully determined by the return payload.


def _shipped_six_box_order():
    """A SHIPPED six-box order (3 right eye, 3 left eye) on an upload-verified
    prescription. `subtotal_cents` is 19200 and shipping is free, so
    `total_cents` is 19200 and the torn-lens cap sits well clear of the figures
    under test."""
    return setup_shipped_order(boxes_od=3, boxes_os=3)


def _shipped_two_box_order():
    """A SHIPPED two-box order, whose `total_cents` is 6400."""
    return setup_shipped_order(boxes_od=1, boxes_os=1)


def _open_return(api, scenario, **overrides):
    """Open a return request as the owning patient and validate the 201."""
    payload = create_return_request_payload(
        scenario["order"]["id"], scenario["customer"]["id"], **overrides
    )
    response = api.create_return_request(
        payload, make_customer_headers(scenario["customer"]["id"])
    )
    return validate_success(response, 201)


# Three opened boxes, each with 7 of its 30 lenses already worn, so 23 lenses
# remain unused in every one of them. The same physical return is priced by both
# prorating variants below.
THREE_OPENED_BOXES_SEVEN_USED = {
    "unopened_boxes": 0,
    "opened_box_used_counts": [7, 7, 7],
}


class TestReturnSettlementRoundingGranularity:
    """`PRESCRIPTION_CHANGE` rounds each opened box, `WRONG_PARAMETER` rounds the
    pooled residue once, and the two answers differ by a cent."""

    def test_prescription_change_return_rounds_each_opened_box_independently(self, api):
        """PRD §3.8: "`PRESCRIPTION_CHANGE` selects `PER_BOX_ROUNDED`,
        `WRONG_PARAMETER` selects `POOLED_ROUNDED`, and `TORN_LENS` selects
        `NO_PRORATION`."
        PRD §3.8: "Under `PER_BOX_ROUNDED`, each opened box is valued
        independently as the per-box value multiplied by the unused lenses in
        that box divided by the lenses per box, **rounded half up to a whole cent
        for that box**, and those per-box amounts are then added together."
        PRD §3.8: "For both prorating variants, `settlement_cents` is the
        unopened component plus the opened component."

        Design: Difficulty/dual_variant_calc/return_settlement_per_box_versus_pooled_rounding
        """
        scenario = _shipped_six_box_order()

        data = _open_return(
            api,
            scenario,
            reason="PRESCRIPTION_CHANGE",
            **THREE_OPENED_BOXES_SEVEN_USED,
        )

        assert data["settlement_mode"] == "PER_BOX_ROUNDED"
        assert data["settlement_cents"] == 7359

    def test_wrong_parameter_return_pools_the_residue_before_rounding_once(self, api):
        """PRD §3.8: "`PRESCRIPTION_CHANGE` selects `PER_BOX_ROUNDED`,
        `WRONG_PARAMETER` selects `POOLED_ROUNDED`, and `TORN_LENS` selects
        `NO_PRORATION`."
        PRD §3.8: "Under `POOLED_ROUNDED`, the unused lenses across all opened
        boxes are added together first, that total is multiplied by the per-box
        value and divided by the lenses per box **exactly**, and the single
        resulting amount is rounded half up to a whole cent once."
        PRD §3.8: "For both prorating variants, `settlement_cents` is the
        unopened component plus the opened component."

        Design: Difficulty/dual_variant_calc/return_settlement_per_box_versus_pooled_rounding
        """
        scenario = _shipped_six_box_order()

        data = _open_return(
            api,
            scenario,
            reason="WRONG_PARAMETER",
            **THREE_OPENED_BOXES_SEVEN_USED,
        )

        assert data["settlement_mode"] == "POOLED_ROUNDED"
        assert data["settlement_cents"] == 7360

    def test_per_box_and_pooled_variants_diverge_by_one_cent_on_identical_boxes(
        self, api
    ):
        """PRD §3.8: "The two variants differ only in where the rounding happens,
        and that difference is enough to shift the same physical return by a
        cent:"
        PRD §3.8: "The channel is `STORE_CREDIT` when `reason` is `TORN_LENS` and
        `CASH_REFUND` for the other two reasons — a torn lens is a replacement
        matter, not a refund matter."
        PRD §3.8: "Creating the return computes `settlement_mode` together with a
        **preview** of `settlement_cents` and `settlement_channel` without moving
        any money."

        Design: Difficulty/dual_variant_calc/return_settlement_per_box_versus_pooled_rounding
        """
        scenario = _shipped_six_box_order()
        order_id = scenario["order"]["id"]

        per_box = new_return_request(
            order_id,
            scenario["customer"]["id"],
            reason="PRESCRIPTION_CHANGE",
            **THREE_OPENED_BOXES_SEVEN_USED,
        )

        pooled = _open_return(
            api,
            scenario,
            reason="WRONG_PARAMETER",
            **THREE_OPENED_BOXES_SEVEN_USED,
        )

        assert pooled["settlement_mode"] == "POOLED_ROUNDED"
        assert pooled["settlement_cents"] == 7360

        # The per-box row is unchanged by the second, byte-identical return.
        reread = validate_success(
            api.get_return_request(per_box["id"], CO_ALPHA_HEADERS)
        )
        assert reread["settlement_mode"] == "PER_BOX_ROUNDED"
        assert reread["settlement_cents"] == 7359
        assert pooled["settlement_cents"] - reread["settlement_cents"] == 1

        # Both reasons refund cash, and neither row has moved money yet.
        for row in (reread, pooled):
            assert row["settlement_channel"] == "CASH_REFUND"
            assert row["status"] == "SUBMITTED"

        order = validate_success(api.get_order(order_id, ADMIN_HEADERS))
        assert order["subtotal_cents"] == 19200
        assert order["shipping_cents"] == 0
        assert order["total_cents"] == 19200


class TestAutoReorderCadenceBasis:
    """`NOMINAL` derives the supply from the wear schedule and the box size;
    `USAGE_ADJUSTED` derives it from the patient's reported box life."""

    def test_nominal_cadence_derives_supply_from_wear_schedule_and_box_size(self, api):
        """PRD §3.7: "The `cadence_basis` selects between two variants and
        defaults to `NOMINAL`; choosing `USAGE_ADJUSTED` requires the customer to
        supply `observed_days_per_box`, the number of days a box actually lasts
        them."
        PRD §3.7: "First establish how many days one lens covers, from the
        product's `wear_schedule`: one day for `DAILY_DISPOSABLE`, fourteen days
        for `BIWEEKLY`, thirty days for `MONTHLY`."
        PRD §3.7: "Under the `NOMINAL` variant, the supply this run represents is
        `boxes_per_run` multiplied by the product's `lenses_per_box` multiplied by
        the days one lens covers."
        PRD §3.7: "`cadence_days` is then that supply figure reduced by a fixed
        reorder lead time of five days, but never allowed below a floor of
        fourteen days — so a schedule whose raw supply is sixteen days lands on
        the floor rather than on eleven."
        PRD §3.7: "`next_run_at` is the `anchor_date` advanced by `cadence_days`,
        at 08:00 UTC on that date."

        Design: Difficulty/dual_variant_calc/auto_reorder_cadence_nominal_versus_usage_adjusted
        """
        scenario = setup_verified_prescription()

        payload = create_auto_reorder_schedule_payload(
            scenario["customer"]["id"],
            scenario["prescription"]["id"],
            scenario["product"]["id"],
            boxes_per_run=3,
            anchor_date="2026-09-08",
            cadence_basis="NOMINAL",
        )
        data = validate_success(
            api.create_auto_reorder_schedule(
                payload, make_customer_headers(scenario["customer"]["id"])
            ),
            201,
        )

        assert data["cadence_basis"] == "NOMINAL"
        assert data["cadence_days"] == 85
        assert data["next_run_at"] == "2026-12-02T08:00:00.000Z"

    def test_usage_adjusted_cadence_derives_supply_from_observed_days_per_box(
        self, api
    ):
        """PRD §3.7: "The `cadence_basis` selects between two variants and
        defaults to `NOMINAL`; choosing `USAGE_ADJUSTED` requires the customer to
        supply `observed_days_per_box`, the number of days a box actually lasts
        them."
        PRD §3.7: "Under the `USAGE_ADJUSTED` variant, the supply is instead
        `boxes_per_run` multiplied by the reported `observed_days_per_box`,
        ignoring the wear schedule entirely."
        PRD §3.7: "`cadence_days` is then that supply figure reduced by a fixed
        reorder lead time of five days, but never allowed below a floor of
        fourteen days — so a schedule whose raw supply is sixteen days lands on
        the floor rather than on eleven."
        PRD §3.7: "`next_run_at` is the `anchor_date` advanced by `cadence_days`,
        at 08:00 UTC on that date."

        Design: Difficulty/dual_variant_calc/auto_reorder_cadence_nominal_versus_usage_adjusted
        """
        scenario = setup_verified_prescription()

        payload = create_auto_reorder_schedule_payload(
            scenario["customer"]["id"],
            scenario["prescription"]["id"],
            scenario["product"]["id"],
            boxes_per_run=1,
            anchor_date="2026-09-14",
            cadence_basis="USAGE_ADJUSTED",
            observed_days_per_box=40,
        )
        data = validate_success(
            api.create_auto_reorder_schedule(
                payload, make_customer_headers(scenario["customer"]["id"])
            ),
            201,
        )

        assert data["cadence_basis"] == "USAGE_ADJUSTED"
        assert data["cadence_days"] == 35
        assert data["next_run_at"] == "2026-10-19T08:00:00.000Z"

    def test_both_cadence_bases_coexist_on_one_prescription(self, api):
        """PRD §3.7: "Under the `NOMINAL` variant, the supply this run represents
        is `boxes_per_run` multiplied by the product's `lenses_per_box` multiplied
        by the days one lens covers."
        PRD §3.7: "Under the `USAGE_ADJUSTED` variant, the supply is instead
        `boxes_per_run` multiplied by the reported `observed_days_per_box`,
        ignoring the wear schedule entirely."
        PRD §3.7: "Creating a schedule increments the customer's
        `active_schedule_count` and recomputes `auto_reorder_enabled`."
        PRD §2.7: "`auto_reorder_enabled` is true exactly when
        `active_schedule_count` is greater than zero and `open_hold_count` is
        zero, and false in every other case."

        Design: Difficulty/dual_variant_calc/auto_reorder_cadence_nominal_versus_usage_adjusted
        """
        scenario = setup_verified_prescription()
        customer_id = scenario["customer"]["id"]
        customer_headers = make_customer_headers(customer_id)

        nominal = new_auto_reorder_schedule(
            customer_id,
            scenario["prescription"]["id"],
            scenario["product"]["id"],
            boxes_per_run=3,
            anchor_date="2026-09-08",
            cadence_basis="NOMINAL",
        )

        usage_payload = create_auto_reorder_schedule_payload(
            customer_id,
            scenario["prescription"]["id"],
            scenario["product"]["id"],
            boxes_per_run=1,
            anchor_date="2026-09-14",
            cadence_basis="USAGE_ADJUSTED",
            observed_days_per_box=40,
        )
        usage = validate_success(
            api.create_auto_reorder_schedule(usage_payload, customer_headers), 201
        )

        assert usage["cadence_days"] == 35
        assert usage["next_run_at"] == "2026-10-19T08:00:00.000Z"

        # The nominal schedule keeps its own cadence: 3 boxes x 30 daily lenses.
        reread = validate_success(
            api.get_auto_reorder_schedule(nominal["id"], customer_headers)
        )
        assert reread["cadence_days"] == 85
        assert reread["next_run_at"] == "2026-12-02T08:00:00.000Z"

        customer = validate_success(api.get_customer(customer_id, customer_headers))
        assert customer["active_schedule_count"] == 2
        assert customer["auto_reorder_enabled"] is True


class TestTornLensNoProrationVariant:
    """`TORN_LENS` selects the third variant, which prices the torn lenses alone
    and pays store credit rather than cash."""

    def test_torn_lens_return_ignores_declared_box_residue(self, api):
        """PRD §3.8: "`PRESCRIPTION_CHANGE` selects `PER_BOX_ROUNDED`,
        `WRONG_PARAMETER` selects `POOLED_ROUNDED`, and `TORN_LENS` selects
        `NO_PRORATION`."
        PRD §3.8: "Under `NO_PRORATION`, no box residue is considered at all: the
        candidate figure is `torn_lens_count` multiplied by the per-box value,
        divided by the lenses per box and rounded half up to a whole cent, and
        `settlement_cents` is whichever is smaller — that candidate figure, or a
        cap equal to twenty percent of the order's `total_cents` with any fraction
        of a cent discarded downward."
        PRD §3.8: "The channel is `STORE_CREDIT` when `reason` is `TORN_LENS` and
        `CASH_REFUND` for the other two reasons — a torn lens is a replacement
        matter, not a refund matter."

        Design: Difficulty/dual_variant_calc/torn_lens_no_proration_variant_ignores_box_residue
        """
        scenario = _shipped_two_box_order()

        data = _open_return(
            api,
            scenario,
            reason="TORN_LENS",
            unopened_boxes=0,
            opened_box_used_counts=[7],
            torn_lens_count=7,
        )

        assert data["settlement_mode"] == "NO_PRORATION"
        assert data["settlement_cents"] == 747
        assert data["settlement_channel"] == "STORE_CREDIT"

        # The torn-lens candidate of 747 cents sits below the twenty-percent cap
        # on this 6400-cent order, so the cap does not bind and the candidate
        # figure survives untouched.
        order = validate_success(
            api.get_order(scenario["order"]["id"], ADMIN_HEADERS)
        )
        assert order["total_cents"] == 6400
        assert data["settlement_cents"] < order["total_cents"] * 20 // 100

    def test_torn_lens_and_prescription_change_price_the_same_box_differently(
        self, api
    ):
        """PRD §3.8: "It selects the `settlement_mode` — the rounding granularity
        variant — and it selects the `settlement_channel`."
        PRD §3.8: "Under `NO_PRORATION`, no box residue is considered at all: the
        candidate figure is `torn_lens_count` multiplied by the per-box value,
        divided by the lenses per box and rounded half up to a whole cent, and
        `settlement_cents` is whichever is smaller — that candidate figure, or a
        cap equal to twenty percent of the order's `total_cents` with any fraction
        of a cent discarded downward."
        PRD §3.8: "Under `PER_BOX_ROUNDED`, each opened box is valued
        independently as the per-box value multiplied by the unused lenses in
        that box divided by the lenses per box, **rounded half up to a whole cent
        for that box**, and those per-box amounts are then added together."

        Design: Difficulty/dual_variant_calc/torn_lens_no_proration_variant_ignores_box_residue
        """
        scenario = _shipped_two_box_order()

        # One opened box with 7 of its 30 lenses worn. Prorated, the 23 unused
        # lenses in that box are worth 2453 cents as a cash refund.
        prorated = new_return_request(
            scenario["order"]["id"],
            scenario["customer"]["id"],
            reason="PRESCRIPTION_CHANGE",
            unopened_boxes=0,
            opened_box_used_counts=[7],
        )
        assert prorated["settlement_mode"] == "PER_BOX_ROUNDED"
        assert prorated["settlement_cents"] == 2453
        assert prorated["settlement_channel"] == "CASH_REFUND"

        # The identical physical box declared under TORN_LENS is priced from the
        # torn lens count alone, and pays store credit instead.
        torn = _open_return(
            api,
            scenario,
            reason="TORN_LENS",
            unopened_boxes=0,
            opened_box_used_counts=[7],
            torn_lens_count=7,
        )

        assert torn["settlement_mode"] == "NO_PRORATION"
        assert torn["settlement_cents"] == 747
        assert torn["settlement_channel"] == "STORE_CREDIT"
        assert torn["settlement_cents"] != prorated["settlement_cents"]

    @pytest.mark.parametrize(
        "reason,expected_mode,expected_channel",
        [
            ("TORN_LENS", "NO_PRORATION", "STORE_CREDIT"),
            ("PRESCRIPTION_CHANGE", "PER_BOX_ROUNDED", "CASH_REFUND"),
            ("WRONG_PARAMETER", "POOLED_ROUNDED", "CASH_REFUND"),
        ],
    )
    def test_reason_selects_settlement_mode_and_channel(
        self, api, reason, expected_mode, expected_channel
    ):
        """PRD §3.8: "It selects the `settlement_mode` — the rounding granularity
        variant — and it selects the `settlement_channel`."
        PRD §3.8: "`PRESCRIPTION_CHANGE` selects `PER_BOX_ROUNDED`,
        `WRONG_PARAMETER` selects `POOLED_ROUNDED`, and `TORN_LENS` selects
        `NO_PRORATION`."
        PRD §3.8: "The channel is `STORE_CREDIT` when `reason` is `TORN_LENS` and
        `CASH_REFUND` for the other two reasons — a torn lens is a replacement
        matter, not a refund matter."

        Design: Difficulty/dual_variant_calc/torn_lens_no_proration_variant_ignores_box_residue
        """
        scenario = _shipped_two_box_order()

        overrides = {"unopened_boxes": 0, "opened_box_used_counts": [7]}
        if reason == "TORN_LENS":
            overrides["torn_lens_count"] = 7

        data = _open_return(api, scenario, reason=reason, **overrides)

        assert data["settlement_mode"] == expected_mode
        assert data["settlement_channel"] == expected_channel
