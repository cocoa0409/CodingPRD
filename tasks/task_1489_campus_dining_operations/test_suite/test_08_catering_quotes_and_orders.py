"""Department ledger defaults, catering quote calculation (tiers and floor),
order creation/FK integrity, pagination, lead-time gates, invoice bounds,
payment ordering, resubmission, the suspended-hall gate, and immediate
read-after-write consistency."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_department,
    create_catering_order,
    create_department,
    create_department_payload,
    create_hall,
    create_recipe,
    get_department,
    get_order,
    invoice_order,
    make_department_user_headers,
    menu_line,
    reject_order,
    set_clock,
    submit_order,
    suspend_hall,
    validate_error,
    validate_paginated,
    validate_success,
    walk_order_to_fulfilled,
)

ADMIN = TEST_USERS["dining_admin_headers"]
HALL_MANAGER = TEST_USERS["hall_manager_headers"]


class TestDepartmentDefaults:
    def test_computed_buckets_ignore_client_input(self, api):
        """PRD §3.8: "Four computed buckets track the money: `reserved_cents`,
        `committed_cents`, `spent_cents`, and `available_cents` all start at 0
        except `available_cents`, which starts equal to the semester budget."

        Design: Corner/entities/department_computed_fields_input_ignored
        """
        payload = create_department_payload(name="Math", department_code="MATH",
                                            semester_budget_cents=250000)
        payload["reserved_cents"] = 999
        payload["available_cents"] = 5
        dept = validate_success(api.create_department(payload, ADMIN),
                                expected_status=201)
        assert_department(dept)
        assert dept["reserved_cents"] == 0
        assert dept["committed_cents"] == 0
        assert dept["spent_cents"] == 0
        assert dept["available_cents"] == 250000


class TestCateringQuote:
    def _setup(self, api, hall_name="Hall C2"):
        hall = create_hall(name=hall_name, service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept = create_department(name="Econ", code="ECON", budget=500000)
        return hall, recipe, dept

    def test_minimum_order_floor_applies_last(self, api):
        """PRD §3.8: "The `quoted_total_cents` is the marked-up food cost plus
        the dietary premium plus the service fee — except that if that sum falls
        below the 50,000-cent minimum order, the quote is raised to 50,000
        cents; the floor applies last."

        Design: Corner/calculations/catering_quote_minimum_order_floor
        """
        hall, recipe, dept = self._setup(api)
        order = create_catering_order(
            hall["id"], dept["id"], "2026-09-15", "BREAKFAST", 10,
            [menu_line(recipe["id"], 5)], dietary_plates=0)
        # raw = round_half_up(4000 * 1.40) + 0 + (7500 + 25 * 10) = 13350 < floor
        assert order["quoted_total_cents"] == 50000

    def test_tier_boundary_200_uses_large_rate(self, api):
        """PRD §3.8: "A markup rate is selected by the guaranteed headcount:
        1.40 when fewer than 50 covers, 1.25 when at least 50 but fewer than
        200, and 1.15 at 200 or more — so a party of exactly 50 takes the 1.25
        rate and a party of exactly 200 the 1.15 rate."

        Design: Difficulty/combinatorial_formula/catering_quote_tiered_markup_at_covers_boundary
        """
        hall, recipe, dept = self._setup(api, hall_name="Hall Q")
        recipe2 = create_recipe(hall["id"], name="R2", station="DELI",
                                unit_cost_cents=600)
        order = create_catering_order(
            hall["id"], dept["id"], "2026-09-15", "LUNCH", 200,
            [menu_line(recipe["id"], 150), menu_line(recipe2["id"], 50)],
            dietary_plates=10)
        # food = 150*800 + 50*600 = 150000; marked = round_half_up(150000*1.15)
        # = 172500; dietary = 3000; service = 7500 + 25*200 = 12500 -> 188000
        assert order["quoted_total_cents"] == 188000, (
            "covers == 200 selects the 1.15 tier; 1.25 would give 203000")
        assert order["approval_status"] == "DRAFT"
        assert order["fulfillment_status"] == "NONE"

    def test_one_cover_below_boundary_uses_medium_rate(self, api):
        """PRD §3.8: "A markup rate is selected by the guaranteed headcount:
        1.40 when fewer than 50 covers, 1.25 when at least 50 but fewer than
        200, and 1.15 at 200 or more — so a party of exactly 50 takes the 1.25
        rate and a party of exactly 200 the 1.15 rate."

        Design: Difficulty/combinatorial_formula/catering_quote_tiered_markup_at_covers_boundary
        """
        hall, recipe, dept = self._setup(api, hall_name="Hall Q")
        recipe2 = create_recipe(hall["id"], name="R2", station="DELI",
                                unit_cost_cents=600)
        order = create_catering_order(
            hall["id"], dept["id"], "2026-09-15", "LUNCH", 199,
            [menu_line(recipe["id"], 150), menu_line(recipe2["id"], 50)],
            dietary_plates=10)
        # food 150000 * 1.25 = 187500; dietary 3000; service 7500 + 25*199 =
        # 12475 -> 202975
        assert order["quoted_total_cents"] == 202975


class TestOrderCreationAndFkIntegrity:
    def test_revised_from_fk_must_resolve(self, api):
        """PRD §3.8: "An optional `revised_from_id` lets the order point back at
        a `REJECTED` order it revises."
        PRD §2.9: "For request bodies that carry several foreign keys, existence
        is then checked in the fields' declared input order: `dining_hall_id`
        before `menu_cycle_id` before `recipe_id`; `department_id` before
        `revised_from_id`; and so on."

        Design: Corner/entities/catering_order_revised_from_fk_integrity
        """
        hall, recipe, dept = self._setup_fk(api)
        order_a = create_catering_order(
            hall["id"], dept["id"], "2026-09-25", "DINNER", 10,
            [menu_line(recipe["id"], 5)])
        submit_order(order_a["id"], dept["id"])
        reject_order(order_a["id"])
        assert get_order(order_a["id"])["approval_status"] == "REJECTED"

        resp = api.create_catering_order(
            {"dining_hall_id": hall["id"], "department_id": dept["id"],
             "event_date": "2026-09-26", "time_slot": "DINNER",
             "guaranteed_covers": 10,
             "menu_lines": [menu_line(recipe["id"], 5)],
             "revised_from_id": NON_EXISTENT_UUID},
            make_department_user_headers(dept["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

        order_b = create_catering_order(
            hall["id"], dept["id"], "2026-09-26", "DINNER", 10,
            [menu_line(recipe["id"], 5)], revised_from_id=order_a["id"])
        assert order_b["revised_from_id"] == order_a["id"]

        data, _meta = validate_paginated(api.list_catering_orders(HALL_MANAGER))
        revising = [row for row in data
                    if row.get("revised_from_id") == order_a["id"]]
        assert len(revising) == 1 and revising[0]["id"] == order_b["id"]

    def _setup_fk(self, api):
        hall = create_hall(name="Hall FK", service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept = create_department(name="Geo", code="GEO", budget=1000000)
        return hall, recipe, dept


class TestPagination:
    def test_limit_offset_windowing(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10 when omitted, and accepts values from a minimum of 1
        to a maximum of 100. The `offset` parameter specifies how many items to
        skip and defaults to 0."
        PRD §2.3: "List responses carry four pagination fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/catering_orders_pagination_envelope
        """
        hall = create_hall(name="Hall PG", service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept = create_department(name="Hist", code="HIST", budget=1000000)
        for day in ("2026-09-20", "2026-09-21", "2026-09-22"):
            create_catering_order(hall["id"], dept["id"], day, "LUNCH", 10,
                                  [menu_line(recipe["id"], 5)])

        resp1 = api.list_catering_orders(HALL_MANAGER,
                                         params={"limit": 2, "offset": 0})
        body1 = resp1.json()
        assert body1["response_type"] == "array"
        page1, meta1 = validate_paginated(resp1)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_catering_orders(
            HALL_MANAGER, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestLeadTime:
    def test_exactly_48h_allowed_one_minute_less_rejected(self, api):
        """PRD §3.8: "the event's slot start must be at least 48 hours after the
        current logical time, with exactly 48 hours allowed (else
        `ERR_LEAD_TIME_VIOLATION`)". Slot starts: "slots start at fixed hours —
        breakfast at 07:00, lunch at 11:00, dinner at 17:00 — and the slot
        start drives both lead-time enforcement and the kitchen-capacity pool."

        Design: Corner/validations/catering_lead_time_exactly_48h
        """
        hall = create_hall(name="Hall V4", service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept = create_department(name="PoliSci", code="POLI", budget=500000)
        order_ok = create_catering_order(
            hall["id"], dept["id"], "2026-08-10", "DINNER", 10,
            [menu_line(recipe["id"], 5)])
        order_late = create_catering_order(
            hall["id"], dept["id"], "2026-08-10", "DINNER", 10,
            [menu_line(recipe["id"], 5)])

        # Event slot start is 2026-08-10T17:00Z; at 2026-08-08T17:00Z the lead
        # is exactly 48h00m — allowed.
        set_clock("2026-08-08T17:00:00Z")
        submitted = submit_order(order_ok["id"], dept["id"])
        assert submitted["approval_status"] == "SUBMITTED"

        # One minute later the remaining lead is 47h59m — rejected.
        set_clock("2026-08-08T17:01:00Z")
        resp = api.submit_catering_order(
            order_late["id"], make_department_user_headers(dept["id"]))
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_VIOLATION)
        assert get_order(order_late["id"])["approval_status"] == "DRAFT"

    def test_default_clock_governs_when_never_set(self, api):
        """PRD §2.4: "Before any client call, the logical clock reads exactly
        `2026-08-01T00:00:00Z`."
        PRD §3.8: "the event's slot start must be at least 48 hours after the
        current logical time, with exactly 48 hours allowed (else
        `ERR_LEAD_TIME_VIOLATION`)".

        Design: Corner/validations/default_clock_governs_lead_time
        """
        hall = create_hall(name="Hall V7", service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept = create_department(name="Ling", code="LING", budget=500000)
        too_soon = create_catering_order(
            hall["id"], dept["id"], "2026-08-02", "LUNCH", 10,
            [menu_line(recipe["id"], 5)])
        far_enough = create_catering_order(
            hall["id"], dept["id"], "2026-08-03", "DINNER", 10,
            [menu_line(recipe["id"], 5)])

        resp = api.submit_catering_order(
            too_soon["id"], make_department_user_headers(dept["id"]))
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_VIOLATION, )

        submitted = submit_order(far_enough["id"], dept["id"])
        assert submitted["approval_status"] == "SUBMITTED"


class TestInvoiceBoundsAndPaymentOrder:
    def _setup_fulfilled_order(self, api):
        """Order at the 50000-cent minimum floor, walked to FULFILLED."""
        hall = create_hall(name="Hall V5", service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept = create_department(name="Stats", code="STAT", budget=500000)
        order = walk_order_to_fulfilled(
            hall["id"], dept["id"], "2026-09-16", "LUNCH", 10,
            [menu_line(recipe["id"], 5)])
        assert order["quoted_total_cents"] == 50000
        return order

    def test_invoice_bounds_are_inclusive(self, api):
        """PRD §3.8: "The final total must land within a tolerance band around
        the frozen quote — at least the quoted total times 0.80 and at most the
        quoted total times 1.20, each bound computed by rounding half-up, with
        both bounds inclusive — otherwise `ERR_VALIDATION`."

        Design: Corner/validations/invoice_final_total_bounds
        """
        order = self._setup_fulfilled_order(api)
        resp = api.invoice_catering_order(
            order["id"], {"final_total_cents": 39500}, HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert get_order(order["id"])["fulfillment_status"] == "FULFILLED"

        invoiced = invoice_order(order["id"], 40000)
        assert invoiced["fulfillment_status"] == "INVOICED"
        assert invoiced["final_total_cents"] == 40000, (
            "exactly 80% of the 50000-cent quote is the inclusive lower bound")

    def test_pay_before_invoice_rejected(self, api):
        """PRD §3.8: "Payment (`INVOICED` → `PAID`) is a `DiningAdmin` act that
        settles the ledger: the quoted total leaves `committed_cents` and the
        final total lands in `spent_cents`, with both versions incrementing."
        PRD §2.7: "4. **State** — the target entity sits in one of the
        transition's from-states (`ERR_INVALID_STATE`), and the cross-entity
        state gates live at this same tier: `ERR_HALL_SUSPENDED` when an
        operation requires an `ACTIVE` hall, `ERR_CONTRACT_NOT_ACTIVE` when a
        statement operation requires an `ACTIVE` contract,
        `ERR_FORECAST_LOCKED_PERIOD` when a forecast operation requires a
        `SCHEDULED` period, `ERR_PENDING_WASTE_LOGS` when a period close finds
        unposted waste, and `ERR_INSPECTION_INCOMPLETE` when a report close
        finds unverified actions."

        Design: Corner/state_machines/catering_pay_before_invoice_rejected
        """
        hall = create_hall(name="Hall SM3", service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept = create_department(name="Anthro", code="ANTH", budget=1000000)
        order = walk_order_to_fulfilled(
            hall["id"], dept["id"], "2026-09-08", "DINNER", 100,
            [menu_line(recipe["id"], 90)])
        resp = api.pay_catering_order(order["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_order(order["id"])
        assert after["fulfillment_status"] == "FULFILLED"
        assert after["final_total_cents"] is None


class TestResubmitCycle:
    def test_rejected_order_resubmits_with_single_reservation(self, api):
        """PRD §3.8: "Submitting an order (from either `DRAFT` or `REJECTED` to
        `SUBMITTED`) runs the submission gauntlet in pipeline order: the hall
        must be `ACTIVE` (else `ERR_HALL_SUSPENDED`); the event's slot start
        must be at least 48 hours after the current logical time, with exactly
        48 hours allowed (else `ERR_LEAD_TIME_VIOLATION`); and the department's
        `available_cents` must cover the `quoted_total_cents`, with exact
        equality allowed (else `ERR_INSUFFICIENT_BUDGET`, HTTP 402)."
        PRD §3.8: "Rejection (`SUBMITTED` → `REJECTED`) accepts an optional
        `reason` and is the compensating action for submission: the quoted total
        comes back out of `reserved_cents`, and both versions increment."

        Design: Corner/state_machines/catering_resubmit_after_reject_cycle
        """
        hall = create_hall(name="Hall SM10", service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept = create_department(name="Soc", code="SOC", budget=500000)
        order = create_catering_order(
            hall["id"], dept["id"], "2026-09-12", "LUNCH", 10,
            [menu_line(recipe["id"], 5)])
        assert order["quoted_total_cents"] == 50000
        submit_order(order["id"], dept["id"])
        reject_order(order["id"])
        assert get_department(dept["id"])["reserved_cents"] == 0, (
            "the reject fully unwound the first reservation")

        resubmitted = submit_order(order["id"], dept["id"])
        assert resubmitted["approval_status"] == "SUBMITTED", (
            "REJECTED is not terminal")
        dept_after = get_department(dept["id"])
        assert dept_after["reserved_cents"] == 50000, "reserved exactly once"
        assert dept_after["available_cents"] == 450000


class TestSuspendedHallGate:
    def test_submit_on_suspended_hall_rejected(self, api):
        """PRD §3.8: "Submitting an order (from either `DRAFT` or `REJECTED` to
        `SUBMITTED`) runs the submission gauntlet in pipeline order: the hall
        must be `ACTIVE` (else `ERR_HALL_SUSPENDED`); the event's slot start
        must be at least 48 hours after the current logical time, with exactly
        48 hours allowed (else `ERR_LEAD_TIME_VIOLATION`); and the department's
        `available_cents` must cover the `quoted_total_cents`, with exact
        equality allowed (else `ERR_INSUFFICIENT_BUDGET`, HTTP 402)."

        Design: Corner/errors/catering_submit_on_suspended_hall_rejected
        """
        hall = create_hall(name="Hall E6", service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept = create_department(name="Music2", code="MUS2", budget=500000)
        order = create_catering_order(
            hall["id"], dept["id"], "2026-09-20", "DINNER", 10,
            [menu_line(recipe["id"], 5)])
        suspend_hall(hall["id"])

        resp = api.submit_catering_order(
            order["id"], make_department_user_headers(dept["id"]))
        validate_error(resp, ApiErrorId.ERR_HALL_SUSPENDED)
        assert get_order(order["id"])["approval_status"] == "DRAFT"
        dept_after = get_department(dept["id"])
        assert dept_after["reserved_cents"] == 0
        assert dept_after["available_cents"] == 500000


class TestImmediateConsistency:
    def test_submit_response_and_read_show_reservation(self, api):
        """PRD §3.8: "On success the quoted total moves into the department's
        `reserved_cents`, both the department's and the order's `version`
        increment."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_consistency_submit_then_read
        """
        hall = create_hall(name="Hall CM1", service_model="RETAIL",
                           catering_kitchen_capacity=10000)
        recipe = create_recipe(hall["id"], name="R", station="GRILL",
                               unit_cost_cents=800)
        dept = create_department(name="Film", code="FILM", budget=500000)
        order = create_catering_order(
            hall["id"], dept["id"], "2026-09-24", "LUNCH", 10,
            [menu_line(recipe["id"], 5)])
        assert order["quoted_total_cents"] == 50000

        submitted = submit_order(order["id"], dept["id"])
        assert submitted["approval_status"] == "SUBMITTED", (
            "the state change is visible in the submit response itself")

        dept_now = get_department(dept["id"])
        assert dept_now["reserved_cents"] == 50000
        assert dept_now["available_cents"] == 450000
