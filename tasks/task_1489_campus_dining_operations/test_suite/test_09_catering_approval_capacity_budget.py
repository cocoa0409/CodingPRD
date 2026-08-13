"""Catering approval: slot capacity pools, the OCC guard on the department,
the critical-violation gate, the state-vs-fiscal priority pair, and the
budget-conservation invariant across the submit/reject/approve/cancel chain."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_order,
    assert_department_budget_conservation,
    create_approved_order,
    create_catering_order,
    create_department,
    create_hall,
    create_recipe,
    create_submitted_order,
    file_inspection,
    get_department,
    get_order,
    make_department_user_headers,
    menu_line,
    reject_order,
    submit_inspection,
    submit_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["dining_admin_headers"]
HALL_MANAGER = TEST_USERS["hall_manager_headers"]


def _setup_hall_recipe_dept(api, hall_name, budget=10000000, capacity=500,
                            dept_name="Bio", dept_code="BIO"):
    hall = create_hall(name=hall_name, service_model="RETAIL",
                       catering_kitchen_capacity=capacity)
    recipe = create_recipe(hall["id"], name="R", station="GRILL",
                           unit_cost_cents=800)
    dept = create_department(name=dept_name, code=dept_code, budget=budget)
    return hall, recipe, dept


class TestSlotCapacityExactFit:
    def _setup_full_pool(self, api):
        """Approves A (300 covers) and B (200 covers) into a 500-cover LUNCH
        pool; leaves C (1 cover) SUBMITTED for the same slot."""
        hall, recipe, dept = _setup_hall_recipe_dept(api, "Hall Cap")
        order_a = create_approved_order(
            hall["id"], dept["id"], "2026-09-05", "LUNCH", 300,
            [menu_line(recipe["id"], 250)])
        order_b = create_catering_order(
            hall["id"], dept["id"], "2026-09-05", "LUNCH", 200,
            [menu_line(recipe["id"], 200)])
        submit_order(order_b["id"], dept["id"])
        order_b = approve_order(order_b["id"], dept["id"])
        order_c = create_submitted_order(
            hall["id"], dept["id"], "2026-09-05", "LUNCH", 1,
            [menu_line(recipe["id"], 1)])
        return hall, dept, order_a, order_b, order_c

    def test_exact_fit_allowed(self, api):
        """PRD §3.8: "And the kitchen-capacity pool must hold: the sum of
        `guaranteed_covers` over all `APPROVED` orders at the same hall, on the
        same `event_date`, in the same `time_slot`, plus this order's own
        `guaranteed_covers`, must not exceed the hall's
        `catering_kitchen_capacity`, with equality allowed (else
        `ERR_CATERING_CAPACITY_EXCEEDED`)."

        Design: Difficulty/boundary_precision_check/catering_capacity_exact_fit_then_overflow
        """
        _hall, _dept, order_a, order_b, _c = self._setup_full_pool(api)
        assert get_order(order_a["id"])["approval_status"] == "APPROVED"
        assert get_order(order_b["id"])["approval_status"] == "APPROVED", (
            "300 + 200 == 500 capacity exactly is allowed")

    def test_one_cover_over_capacity_rejected(self, api):
        """PRD §3.8: "And the kitchen-capacity pool must hold: the sum of
        `guaranteed_covers` over all `APPROVED` orders at the same hall, on the
        same `event_date`, in the same `time_slot`, plus this order's own
        `guaranteed_covers`, must not exceed the hall's
        `catering_kitchen_capacity`, with equality allowed (else
        `ERR_CATERING_CAPACITY_EXCEEDED`)."

        Design: Difficulty/boundary_precision_check/catering_capacity_exact_fit_then_overflow
        """
        _hall, dept, _a, _b, order_c = self._setup_full_pool(api)
        dept_now = get_department(dept["id"])
        resp = api.approve_catering_order(
            order_c["id"],
            {"expected_department_version": dept_now["version"]},
            HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_CATERING_CAPACITY_EXCEEDED)
        assert get_order(order_c["id"])["approval_status"] == "SUBMITTED"
        dept_after = get_department(dept["id"])
        # The failed approval does not release the 50000-cent reservation made
        # at submit (A: 245000 committed, B: 196500 committed, C: 50000 reserved).
        assert dept_after["reserved_cents"] == 50000
        assert dept_after["committed_cents"] == 441500
        assert_department_budget_conservation(dept_after)


class TestSlotPoolIndependence:
    def _setup_slots(self, api):
        """L1 (500 covers LUNCH) APPROVED; D1 (500 covers DINNER) and L2
        (1 cover LUNCH) SUBMITTED for the same date."""
        hall, recipe, dept = _setup_hall_recipe_dept(api, "Hall OV3",
                                                     dept_name="Arts",
                                                     dept_code="ART")
        l1 = create_approved_order(
            hall["id"], dept["id"], "2026-09-10", "LUNCH", 500,
            [menu_line(recipe["id"], 400)])
        d1 = create_submitted_order(
            hall["id"], dept["id"], "2026-09-10", "DINNER", 500,
            [menu_line(recipe["id"], 400)])
        l2 = create_submitted_order(
            hall["id"], dept["id"], "2026-09-10", "LUNCH", 1,
            [menu_line(recipe["id"], 1)])
        return hall, dept, l1, d1, l2

    def test_different_slot_pool_is_independent(self, api):
        """PRD §3.8: "And the kitchen-capacity pool must hold: the sum of
        `guaranteed_covers` over all `APPROVED` orders at the same hall, on the
        same `event_date`, in the same `time_slot`, plus this order's own
        `guaranteed_covers`, must not exceed the hall's
        `catering_kitchen_capacity`, with equality allowed (else
        `ERR_CATERING_CAPACITY_EXCEEDED`)."

        Design: Difficulty/resource_temporal_overlap/catering_slot_aggregate_capacity_semantics
        """
        _hall, _dept, _l1, d1, _l2 = self._setup_slots(api)
        approved = approve_order(d1["id"], _dept["id"])
        assert approved["approval_status"] == "APPROVED", (
            "the DINNER slot pool is independent of the full LUNCH pool")

    def test_extra_cover_into_full_slot_rejected(self, api):
        """PRD §3.8: "And the kitchen-capacity pool must hold: the sum of
        `guaranteed_covers` over all `APPROVED` orders at the same hall, on the
        same `event_date`, in the same `time_slot`, plus this order's own
        `guaranteed_covers`, must not exceed the hall's
        `catering_kitchen_capacity`, with equality allowed (else
        `ERR_CATERING_CAPACITY_EXCEEDED`)."

        Design: Difficulty/resource_temporal_overlap/catering_slot_aggregate_capacity_semantics
        """
        _hall, dept, _l1, _d1, l2 = self._setup_slots(api)
        resp = api.approve_catering_order(
            l2["id"],
            {"expected_department_version": get_department(dept["id"])["version"]},
            HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_CATERING_CAPACITY_EXCEEDED)
        assert get_order(l2["id"])["approval_status"] == "SUBMITTED"


class TestBudgetConservationInvariant:
    def _setup_order(self, api):
        """Order quoted exactly 188000 (covers 200; food 150000 via R@800 x150
        plus R2@600 x50; 10 dietary plates), event far enough out for the 10%
        cancellation tier."""
        hall, recipe, dept = _setup_hall_recipe_dept(
            api, "Hall INV1", budget=1000000, capacity=10000,
            dept_name="Philosophy", dept_code="PHIL")
        recipe2 = create_recipe(hall["id"], name="R2", station="DELI",
                                unit_cost_cents=600)
        order = create_catering_order(
            hall["id"], dept["id"], "2026-09-01", "DINNER", 200,
            [menu_line(recipe["id"], 150), menu_line(recipe2["id"], 50)],
            dietary_plates=10)
        assert order["quoted_total_cents"] == 188000
        return hall, dept, order

    def test_submit_reject_is_a_perfect_compensating_pair(self, api):
        """PRD §3.8: "At every instant, the four buckets sum exactly back to the
        semester budget — the submit/reject pair and the approve/cancel-with-fee
        pair each conserve the total exactly."

        Design: Difficulty/compensating_invariant/department_budget_conservation
        """
        _hall, dept, order = self._setup_order(api)
        submit_order(order["id"], dept["id"])
        mid = get_department(dept["id"])
        assert mid["reserved_cents"] == 188000
        assert_department_budget_conservation(mid)

        reject_order(order["id"])
        after = get_department(dept["id"])
        assert after["reserved_cents"] == 0
        assert after["available_cents"] == 1000000, (
            "submit + reject leaves the ledger untouched")
        assert_department_budget_conservation(after)

    def test_approve_then_cancel_lands_fee_in_spent(self, api):
        """PRD §3.8: "Cancelling an `APPROVED` order whose fulfillment is `NONE`
        or `SCHEDULED` charges a cancellation fee: the fee is the quoted total
        times a fee rate, rounded half-up to whole cents, where the rate is
        1,000 basis points (ten percent) when the event's slot start is at least
        72 hours after the current logical time — exactly 72 hours qualifies —
        and 2,500 basis points (twenty-five percent) otherwise. The committed
        bucket releases the quoted total, the fee lands in `spent_cents`, and
        both versions increment."

        Design: Difficulty/compensating_invariant/department_budget_conservation
        """
        _hall, dept, order = self._setup_order(api)
        submit_order(order["id"], dept["id"])
        approve_order(order["id"], dept["id"])
        mid = get_department(dept["id"])
        assert mid["committed_cents"] == 188000
        assert mid["reserved_cents"] == 0
        assert mid["available_cents"] == 812000
        assert_department_budget_conservation(mid)

        cancelled = validate_success(api.cancel_catering_order(order["id"],
                                                               HALL_MANAGER))
        assert cancelled["cancellation_fee_cents"] == 18800, (
            "round_half_up(188000 * 1000/10000); the event is >= 72h out")
        end = get_department(dept["id"])
        assert end["spent_cents"] == 18800
        assert end["committed_cents"] == 0
        assert end["available_cents"] == 981200
        assert_department_budget_conservation(end)


class TestApproveOnApprovedOrderStateBeatsBudget:
    def _setup(self, api):
        """Order (quoted 156500) SUBMITTED then APPROVED; department available
        is now 43500 < 156500, so a second submit fails both the state tier and
        the fiscal tier."""
        hall, recipe, dept = _setup_hall_recipe_dept(
            api, "Hall P5a", budget=200000, capacity=10000,
            dept_name="Music", dept_code="MUS")
        order = create_catering_order(
            hall["id"], dept["id"], "2026-09-01", "DINNER", 200,
            [menu_line(recipe["id"], 150)], dietary_plates=20)
        assert order["quoted_total_cents"] == 156500, (
            "120000 * 1.15 = 138000; + 6000 dietary; + 12500 service")
        submit_order(order["id"], dept["id"])
        approve_order(order["id"], dept["id"])
        return dept, order

    def test_state_error_wins_over_fiscal_error(self, api):
        """PRD §2.7: "When several rules fail on the same request, the server
        does not report them all: it reports the failure from the **earliest
        tier** of a fixed ten-tier validation pipeline."
        PRD §2.7: "9. **Fiscal checks** — money is checked last among the
        business rules: catering submission requires sufficient departmental
        budget (`ERR_INSUFFICIENT_BUDGET`)."

        Design: Difficulty/priority_pair_validation_conflict/submit_approved_order_state_beats_budget
        """
        dept, order = self._setup(api)
        resp = api.submit_catering_order(
            order["id"], make_department_user_headers(dept["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, (
            "APPROVED is not a from-state for submit; the fiscal failure "
            "(available 43500 < quoted 156500) never surfaces")

    def test_failed_resubmit_moves_no_money(self, api):
        """PRD §3.8: "Approval moves the quoted total out of `reserved_cents`
        and into `committed_cents`, incrementing both versions."
        PRD §3.8: "At every instant, the four buckets sum exactly back to the
        semester budget — the submit/reject pair and the approve/cancel-with-fee
        pair each conserve the total exactly."

        Design: Difficulty/priority_pair_validation_conflict/submit_approved_order_state_beats_budget
        """
        dept, order = self._setup(api)
        before = get_department(dept["id"])
        assert before["reserved_cents"] == 0
        assert before["committed_cents"] == 156500

        api.submit_catering_order(order["id"],
                                  make_department_user_headers(dept["id"]))
        after = get_department(dept["id"])
        assert after["reserved_cents"] == 0
        assert after["committed_cents"] == 156500, (
            "the rejected re-submit changes no bucket")
        assert_department_budget_conservation(after)
        assert get_order(order["id"])["approval_status"] == "APPROVED"


class TestApproveBlockedByOpenCritical:
    def test_approve_rejected_with_critical_violation_open(self, api):
        """PRD §3.8: "No `CRITICAL` corrective action may be `OPEN` or
        `OVERDUE` on any inspection report at the order's hall (else
        `ERR_CRITICAL_VIOLATION_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/catering_approve_blocked_by_open_critical
        """
        hall, recipe, dept = _setup_hall_recipe_dept(
            api, "Hall XE3", budget=1000000, capacity=10000,
            dept_name="Chem", dept_code="CHEM")
        order = create_submitted_order(
            hall["id"], dept["id"], "2026-09-03", "DINNER", 100,
            [menu_line(recipe["id"], 90)])
        assert order["quoted_total_cents"] == 100000
        report = file_inspection(hall["id"], "2026-08-05",
                                 [{"code": "SAN-01", "severity": "CRITICAL"}])
        submit_inspection(report["id"])

        resp = api.approve_catering_order(
            order["id"],
            {"expected_department_version": get_department(dept["id"])["version"]},
            HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_CRITICAL_VIOLATION_OPEN)
        assert get_order(order["id"])["approval_status"] == "SUBMITTED"

    def test_failed_gate_moves_no_budget(self, api):
        """PRD §3.8: "Approval moves the quoted total out of `reserved_cents`
        and into `committed_cents`, incrementing both versions." A rejected
        approval performs no such movement.
        PRD §3.8: "At every instant, the four buckets sum exactly back to the
        semester budget — the submit/reject pair and the approve/cancel-with-fee
        pair each conserve the total exactly."

        Design: Difficulty/cross_entity_state_dependency/catering_approve_blocked_by_open_critical
        """
        hall, recipe, dept = _setup_hall_recipe_dept(
            api, "Hall XE3", budget=1000000, capacity=10000,
            dept_name="Chem", dept_code="CHEM")
        order = create_submitted_order(
            hall["id"], dept["id"], "2026-09-03", "DINNER", 100,
            [menu_line(recipe["id"], 90)])
        report = file_inspection(hall["id"], "2026-08-05",
                                 [{"code": "SAN-01", "severity": "CRITICAL"}])
        submit_inspection(report["id"])

        api.approve_catering_order(
            order["id"],
            {"expected_department_version": get_department(dept["id"])["version"]},
            HALL_MANAGER)
        after = get_department(dept["id"])
        assert after["reserved_cents"] == 100000, (
            "no bucket movement on the failed approval")
        assert after["committed_cents"] == 0
        assert_department_budget_conservation(after)


class TestApproveOccGuard:
    def test_stale_department_version_rejected_then_fresh_succeeds(self, api):
        """PRD §2.8: "Approving a catering order requires the request to carry
        `expected_department_version`, holding the `version` of the order's
        `Department` the approver last observed. If the department's current
        `version` does not match — because another approval or rejection has
        just moved funds between the department's reserved and committed
        buckets — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412)
        and must be re-issued against fresh figures."

        Design: Corner/cross_cutting_layers/occ_catering_approve_stale_version
        """
        hall, recipe, dept = _setup_hall_recipe_dept(
            api, "Hall L2", budget=500000, capacity=10000,
            dept_name="Dance", dept_code="DANC")
        stale_version = dept["version"]
        order = create_catering_order(
            hall["id"], dept["id"], "2026-09-22", "DINNER", 10,
            [menu_line(recipe["id"], 5)])
        submit_order(order["id"], dept["id"])
        mid = get_department(dept["id"])
        assert mid["version"] == stale_version + 1, (
            "the submit reservation bumped the department's version")

        resp = api.approve_catering_order(
            order["id"], {"expected_department_version": stale_version},
            HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_department(dept["id"])["version"]
        approved = validate_success(api.approve_catering_order(
            order["id"], {"expected_department_version": fresh_version},
            HALL_MANAGER))
        assert approved["approval_status"] == "APPROVED"
        assert get_department(dept["id"])["version"] == fresh_version + 1
