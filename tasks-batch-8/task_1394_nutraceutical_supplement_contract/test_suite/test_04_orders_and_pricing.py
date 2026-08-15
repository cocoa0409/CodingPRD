"""Order placement, tiered pricing, MOQ gate, scheduling, cancellation, aggregates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_manufacturing_order,
    create_customer,
    create_raw_material,
    create_and_approve_formula,
    get_customer,
    get_order,
    make_brandrep_headers,
    make_catalog,
    place_order,
    schedule_order,
    setup_batch_at_stage,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import WINDOW_DAY1

PLANNER = TEST_USERS["production_planner_headers"]
QA = TEST_USERS["qa_manager_headers"]


class TestOrderOwnership:
    def test_brandrep_placing_for_other_customer_rejected(self, api):
        """PRD §2.1: "ownership checks compare the `customer_id` stored on a
        manufacturing order (or supplied in a placement payload) against
        `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/validations/brandrep_order_for_other_customer_rejected
        """
        cust_a = create_customer("AcmeA")
        cust_b = create_customer("AcmeB")
        material = create_raw_material("VitC", "NONE")
        formula = create_and_approve_formula(cust_b["id"], material["id"])

        resp = api.create_manufacturing_order(
            {"customer_id": cust_b["id"], "formula_id": formula["id"],
             "ordered_qty": 1000},
            make_brandrep_headers(cust_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert resp.status_code == 403


class TestTieredPricing:
    TIERS = [
        {"min_qty": 1000, "unit_price_cents": 120},
        {"min_qty": 5000, "unit_price_cents": 100},
        {"min_qty": 20000, "unit_price_cents": 85},
    ]

    def test_tier_lower_bounds_inclusive_at_breakpoints(self, api):
        """PRD §3.3: "Among the formula's `price_tiers`, the system selects the tier
        with the greatest `min_qty` that is less than or equal to the ordered
        quantity — tier lower bounds are inclusive, and the tier-set validation from
        §3.1 guarantees the `min_qty` values are unique".

        Design: Difficulty/combinatorial_formula/tiered_pricing_flat_rate_tier_selection
        """
        ctx = make_catalog(price_tiers=[dict(t) for t in self.TIERS])
        cust_id = ctx["customer"]["id"]
        f_id = ctx["formula"]["id"]

        below = place_order(cust_id, f_id, 4999)
        assert_manufacturing_order(below)
        assert below["unit_price_cents"] == 120, (
            "greatest min_qty <= 4999 is 1000, so the 120-cent tier applies"
        )
        assert below["total_price_cents"] == 4999 * 120  # 599880

        at_break = place_order(cust_id, f_id, 5000)
        assert at_break["unit_price_cents"] == 100, (
            "breakpoint 5000 is inclusive, so the 100-cent tier applies"
        )
        assert at_break["total_price_cents"] == 5000 * 100  # 500000

    def test_flat_rate_applies_selected_tier_to_every_unit(self, api):
        """PRD §3.3: "that single tier's `unit_price_cents` applies to every unit
        ordered, not merely to units within the tier band; the marginal alternative
        reading is deliberately not used."
        PRD §3.3: "The order's `unit_price_cents` is the selected tier rate and its
        `total_price_cents` is the ordered quantity multiplied by that rate, an
        exact integer number of cents."

        Design: Difficulty/combinatorial_formula/tiered_pricing_flat_rate_tier_selection
        """
        ctx = make_catalog(price_tiers=[dict(t) for t in self.TIERS])
        order = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 20000)
        assert order["unit_price_cents"] == 85
        # Flat rate: 20000 x 85 = 1700000, NOT the marginal blend
        # 4999*120 + 15000*100 + 1*85 = 2099865.
        assert order["total_price_cents"] == 1700000
        assert order["total_price_cents"] != 2099865, (
            "the marginal blend reading is deliberately not used"
        )


class TestMinimumOrderBoundary:
    def test_order_below_minimum_quantity_rejected(self, api):
        """PRD §3.3: "the ordered quantity must be at least the formula's
        `min_order_qty` — equality is allowed — or the placement is rejected with
        `ERR_BELOW_MINIMUM_ORDER` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/moq_exact_boundary
        """
        ctx = make_catalog()
        resp = api.create_manufacturing_order(
            {"customer_id": ctx["customer"]["id"],
             "formula_id": ctx["formula"]["id"], "ordered_qty": 999},
            make_brandrep_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BELOW_MINIMUM_ORDER)
        assert resp.status_code == 422

    def test_order_at_exact_minimum_quantity_accepted(self, api):
        """PRD §3.3: "the ordered quantity must be at least the formula's
        `min_order_qty` — equality is allowed — or the placement is rejected with
        `ERR_BELOW_MINIMUM_ORDER` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/moq_exact_boundary
        """
        ctx = make_catalog()
        resp = api.create_manufacturing_order(
            {"customer_id": ctx["customer"]["id"],
             "formula_id": ctx["formula"]["id"], "ordered_qty": 1000},
            make_brandrep_headers(ctx["customer"]["id"]),
        )
        data = validate_success(resp, 201)
        assert data["unit_price_cents"] == 120
        assert data["total_price_cents"] == 1000 * 120  # 120000
        assert data["status"] == "PLACED"


class TestScheduling:
    def test_inverted_window_rejected_as_invalid_request(self, api):
        """PRD §3.3: "a window whose start is not strictly before its end is
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/schedule_inverted_window_returns_invalid_request
        """
        ctx = make_catalog()
        mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        resp = api.schedule_manufacturing_order(
            mo["id"],
            {"production_line_id": ctx["line"]["id"],
             "planned_start": "2026-09-01T16:00:00Z",
             "planned_end": "2026-09-01T08:00:00Z"},
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_overlapping_window_rejected_on_same_line(self, api):
        """PRD §3.3: "The window must not intersect the window of any
        non-`CANCELLED` batch already on that line: windows are half-open intervals,
        so a new batch whose `planned_start` equals an existing batch's
        `planned_end` (or vice versa) is lawful adjacency, while any genuine
        intersection is rejected with `ERR_LINE_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/line_window_overlap_half_open
        """
        ctx = make_catalog()
        mo1 = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        schedule_order(mo1["id"], ctx["line"]["id"],
                       "2026-09-01T08:00:00Z", "2026-09-01T16:00:00Z")

        mo2 = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        resp = api.schedule_manufacturing_order(
            mo2["id"],
            {"production_line_id": ctx["line"]["id"],
             "planned_start": "2026-09-01T12:00:00Z",
             "planned_end": "2026-09-01T20:00:00Z"},
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_SCHEDULE_CONFLICT)
        assert resp.status_code == 409
        assert get_order(mo2["id"])["status"] == "PLACED"

    def test_adjacent_window_allowed_half_open(self, api):
        """PRD §3.3: "windows are half-open intervals, so a new batch whose
        `planned_start` equals an existing batch's `planned_end` (or vice versa) is
        lawful adjacency, while any genuine intersection is rejected with
        `ERR_LINE_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/line_window_overlap_half_open
        """
        ctx = make_catalog()
        mo1 = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        schedule_order(mo1["id"], ctx["line"]["id"],
                       "2026-09-01T08:00:00Z", "2026-09-01T16:00:00Z")

        mo3 = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        resp = api.schedule_manufacturing_order(
            mo3["id"],
            {"production_line_id": ctx["line"]["id"],
             "planned_start": "2026-09-01T16:00:00Z",
             "planned_end": "2026-09-01T23:00:00Z"},
            PLANNER,
        )
        batch = validate_success(resp, 201)
        assert batch["production_status"] == "CREATED"
        assert batch["quality_status"] == "PENDING_QC"

    def test_schedule_creates_batch_discoverable_via_filtered_list(self, api):
        """PRD §3.3: "A successful scheduling creates the Batch — addressed back to
        its order via `mo_id`, stamped with the `production_line_id`, the planned
        window, and a `theoretical_units` snapshot of the formula's
        `batch_size_units` — in `CREATED` / `PENDING_QC` posture, and advances the
        order from `PLACED` to `SCHEDULED`."

        Design: Corner/endpoints/schedule_creates_batch_discoverable_via_filtered_list
        """
        ctx = make_catalog()
        mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        resp = api.schedule_manufacturing_order(
            mo["id"],
            {"production_line_id": ctx["line"]["id"],
             "planned_start": WINDOW_DAY1[0], "planned_end": WINDOW_DAY1[1]},
            PLANNER,
        )
        batch = validate_success(resp, 201)
        assert batch["mo_id"] == mo["id"]
        assert batch["theoretical_units"] == 10000
        assert batch["production_status"] == "CREATED"
        assert batch["quality_status"] == "PENDING_QC"

        found, meta = validate_paginated(
            api.list_batches(QA, params={"mo_id": mo["id"]})
        )
        assert meta["total_count"] == 1
        assert found[0]["id"] == batch["id"]
        assert get_order(mo["id"])["status"] == "SCHEDULED"

    def test_schedule_already_scheduled_order_rejected(self, api):
        """PRD §3.3: "A `ProductionPlanner` schedules a `PLACED` order
        (`ERR_ORDER_STATE` otherwise)".

        Design: Corner/state_machines/order_schedule_twice_rejected
        """
        ctx = make_catalog()
        mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        schedule_order(mo["id"], ctx["line"]["id"])

        resp = api.schedule_manufacturing_order(
            mo["id"],
            {"production_line_id": ctx["line"]["id"],
             "planned_start": "2026-09-03T08:00:00Z",
             "planned_end": "2026-09-03T16:00:00Z"},
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_STATE)
        assert resp.status_code == 409

        batches, meta = validate_paginated(
            api.list_batches(QA, params={"mo_id": mo["id"]})
        )
        assert meta["total_count"] == 1, (
            "a rejected second schedule must not create another batch"
        )
        assert batches[0]["mo_id"] == mo["id"]


class TestCancellation:
    def test_cancel_in_production_order_rejected(self, api):
        """PRD §3.3: "A `BrandRep` may cancel an order whose status is `PLACED` or
        `SCHEDULED` — anything further along is rejected with `ERR_ORDER_STATE`".

        Design: Corner/state_machines/order_cancel_after_in_production_rejected
        """
        ctx = setup_batch_at_stage("IN_PROCESS")
        resp = api.cancel_manufacturing_order(
            ctx["mo"]["id"], {}, make_brandrep_headers(ctx["customer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_STATE)
        assert resp.status_code == 409
        assert get_order(ctx["mo"]["id"])["status"] == "IN_PRODUCTION"


class TestCustomerCommitmentInvariant:
    def test_placement_raises_committed_value_and_open_count(self, api):
        """PRD §3.3: "the new order enters `PLACED` status while the customer's
        `committed_order_value_cents` rises by `total_price_cents` and its
        `open_order_count` rises by one."

        Design: Difficulty/compensating_invariant/customer_commitment_conserved_on_place_and_cancel
        """
        ctx = make_catalog()
        order = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 2000)
        assert order["total_price_cents"] == 2000 * 120  # 240000

        customer = get_customer(ctx["customer"]["id"])
        assert customer["committed_order_value_cents"] == 240000
        assert customer["open_order_count"] == 1
        assert customer["lifetime_receipts_cents"] == 0

    def test_cancel_restores_commitment_to_zero(self, api):
        """PRD §3.3: "Cancellation moves the order to `CANCELLED`, decrements the
        customer's `open_order_count` by one, and subtracts the order's
        `total_price_cents` from `committed_order_value_cents`."
        PRD §2.12: "at all times `committed_order_value_cents` plus
        `lifetime_receipts_cents` equals the sum of `total_price_cents` over all of
        the customer's non-`CANCELLED` orders."

        Design: Difficulty/compensating_invariant/customer_commitment_conserved_on_place_and_cancel
        """
        ctx = make_catalog()
        order = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 2000)
        assert order["total_price_cents"] == 240000

        cancel_resp = api.cancel_manufacturing_order(
            order["id"], {}, make_brandrep_headers(ctx["customer"]["id"])
        )
        cancelled = validate_success(cancel_resp, 200)
        assert cancelled["status"] == "CANCELLED"

        customer = get_customer(ctx["customer"]["id"])
        assert customer["committed_order_value_cents"] == 0
        assert customer["open_order_count"] == 0
        assert customer["lifetime_receipts_cents"] == 0, (
            "commitment invariant: committed + lifetime == sum over non-CANCELLED"
        )
