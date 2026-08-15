"""Procurement money rules: per-line rounding, spend positions, fiscal gate,
segregation of duties, and the approve/cancel conservation invariant."""
from test_helpers import (
    ApiErrorId,
    PINNED_LINES,
    PINNED_LINES_TOTAL_CENTS,
    TEST_USERS,
    approve_order,
    create_order,
    get_event,
    get_order,
    setup_matched_scenario,
    submit_order,
    validate_error,
    validate_success,
)

CEM = TEST_USERS["cem_headers"]
PO = TEST_USERS["procurement_officer_headers"]
PO_AS_CREATOR = TEST_USERS["procurement_officer_creator_headers"]  # X-User-ID cem-1


class TestPerLineRounding:
    def test_order_total_uses_per_line_rounding(self, api):
        """PRD §3.5: "At creation the server computes `order_total_cents` and freezes it: each line's extended cost is its `quantity` multiplied by its `unit_cost_cents` and by one plus the 8.75% tax rate, rounded half-up to whole cents, and the order total is the sum of those per-line rounded amounts. Rounding each line first and then summing is mandatory — summing the unrounded line products and rounding once at the end produces different cents and is not permitted."

        Design: Difficulty/combinatorial_formula/procurement_total_per_line_rounding_order_pinned
        """
        sc = setup_matched_scenario(event_name="Day D", open_registration=False)
        # round_half_up(3 x 999 x 1.0875) = 3259; round_half_up(7 x 149 x 1.0875) = 1134
        resp = api.create_procurement_order(
            {
                "event_id": sc["event"]["id"],
                "project_id": sc["project"]["id"],
                "lines": PINNED_LINES,
            },
            CEM,
        )
        data = validate_success(resp, 201)
        assert data["order_total_cents"] == PINNED_LINES_TOTAL_CENTS, (
            f"per-line rounding gives 4393 (3259 + 1134); "
            f"sum-then-round would give 4394 — got {data['order_total_cents']}"
        )

    def test_order_created_in_draft_with_creator_recorded(self, api):
        """PRD §3.5: "The new order starts in `DRAFT` status, with `created_by_user_id` recorded from the caller's `X-User-ID` and `rejection_reason` null."

        Design: Difficulty/combinatorial_formula/procurement_total_per_line_rounding_order_pinned
        """
        sc = setup_matched_scenario(event_name="Day D2", open_registration=False)
        resp = api.create_procurement_order(
            {
                "event_id": sc["event"]["id"],
                "project_id": sc["project"]["id"],
                "lines": PINNED_LINES,
            },
            CEM,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
        assert data["created_by_user_id"] == "cem-1"
        assert data["rejection_reason"] is None


class TestBudgetConservation:
    def _setup_order(self):
        sc = setup_matched_scenario(
            event_name="Day Q", budget_cents=100000, open_registration=False
        )
        order = create_order(sc["event"]["id"], sc["project"]["id"], lines=PINNED_LINES)
        return sc, order

    def test_submit_then_approve_move_spend_positions(self, api):
        """PRD §2.8: "`projected_spend_cents` is the forward-looking pipeline: the sum of `order_total_cents` over the event's procurement orders in `SUBMITTED`, `APPROVED`, or `RECEIVED` status, plus the sum of `total_cost_cents` over its meal plans in `ORDERED` or `FULFILLED` status, plus the sum of `cost_cents` over its transport manifests in `BOOKED`, `CONFIRMED`, or `COMPLETED` status."
        PRD §2.8: "`available_budget_cents` is the event's `budget_cents` minus its `projected_spend_cents` — the conservative availability figure, since it treats the whole pipeline as spent."

        Design: Difficulty/compensating_invariant/budget_approve_cancel_conservation
        """
        sc, order = self._setup_order()
        event_id = sc["event"]["id"]

        submit_order(order["id"])
        event = get_event(event_id)
        assert event["projected_spend_cents"] == 4393
        assert event["committed_spend_cents"] == 0
        assert event["available_budget_cents"] == 100000 - 4393

        approve_order(order["id"])
        event = get_event(event_id)
        assert event["committed_spend_cents"] == 4393
        assert event["projected_spend_cents"] == 4393

    def test_cancel_after_approve_restores_budget_exactly(self, api, cem_headers):
        """PRD §3.5: "Cancellation is available from `DRAFT`, `SUBMITTED`, or `APPROVED` and moves the order to `CANCELLED` with a budget reversal; `RECEIVED` orders are terminal and cannot be cancelled."
        PRD §2.8: "Both positions start at zero on a new event."

        Design: Difficulty/compensating_invariant/budget_approve_cancel_conservation
        """
        sc, order = self._setup_order()
        event_id = sc["event"]["id"]
        submit_order(order["id"])
        approve_order(order["id"])

        # The compensating action must restore the conserved quantity exactly
        validate_success(api.cancel_order(order["id"], cem_headers), 200)
        event = get_event(event_id)
        assert event["projected_spend_cents"] == 0
        assert event["committed_spend_cents"] == 0
        assert event["available_budget_cents"] == event["budget_cents"] == 100000


class TestApproveValidationPriority:
    def test_order_approve_state_error_precedes_budget_error(self, api):
        """PRD §2.6: "The practical consequence: a confirm request that would fail both the waiver gate and the capacity gate surfaces `ERR_WAIVER_NOT_SIGNED`, because safety gates (step 7) precede capacity (step 11); an order approval that would breach the budget surfaces `ERR_BUDGET_WOULD_EXCEED` only after auth, existence, state, and every other check has passed, because the fiscal gate is evaluated last."

        Design: Difficulty/priority_pair_validation_conflict/order_approve_state_error_precedes_budget_error
        """
        sc = setup_matched_scenario(
            event_name="Day I", budget_cents=1000, open_registration=False
        )
        # DRAFT order (never submitted) whose total (4393) exceeds the budget (1000):
        # violates BOTH the from-state guard and the fiscal gate; state must win.
        order = create_order(sc["event"]["id"], sc["project"]["id"], lines=PINNED_LINES)

        resp = api.approve_order(order["id"], PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_TRANSITION)

    def test_state_priority_rejection_leaves_order_and_spend_untouched(self, api):
        """PRD §2.6: "an order approval that would breach the budget surfaces `ERR_BUDGET_WOULD_EXCEED` only after auth, existence, state, and every other check has passed, because the fiscal gate is evaluated last."
        PRD §2.8: "`projected_spend_cents` is the forward-looking pipeline: the sum of `order_total_cents` over the event's procurement orders in `SUBMITTED`, `APPROVED`, or `RECEIVED` status, plus the sum of `total_cost_cents` over its meal plans in `ORDERED` or `FULFILLED` status, plus the sum of `cost_cents` over its transport manifests in `BOOKED`, `CONFIRMED`, or `COMPLETED` status."

        Design: Difficulty/priority_pair_validation_conflict/order_approve_state_error_precedes_budget_error
        """
        sc = setup_matched_scenario(
            event_name="Day I2", budget_cents=1000, open_registration=False
        )
        order = create_order(sc["event"]["id"], sc["project"]["id"], lines=PINNED_LINES)

        api.approve_order(order["id"], PO)
        assert get_order(order["id"])["status"] == "DRAFT"
        # A DRAFT order never entered the projected position
        assert get_event(sc["event"]["id"])["projected_spend_cents"] == 0


class TestFiscalGate:
    def test_order_approve_over_budget_returns_402(self, api, any_headers):
        """PRD §3.5: "Approval additionally requires the event to be in `PLANNING`, `REGISTRATION_OPEN`, or `REGISTRATION_LOCKED` (`ERR_EVENT_STATE_FORBIDS_WRITE`) and passes through the fiscal gate last: the event's `projected_spend_cents` — which already includes this order, since it is `SUBMITTED` — must not exceed the event's `budget_cents`, otherwise the approval is rejected with `ERR_BUDGET_WOULD_EXCEED` (HTTP 402)."

        Design: Corner/validations/order_approve_over_budget_returns_402
        """
        sc = setup_matched_scenario(
            event_name="Day 32", budget_cents=1000, open_registration=False
        )
        order = create_order(sc["event"]["id"], sc["project"]["id"], lines=PINNED_LINES)
        submit_order(order["id"])

        resp = api.approve_order(order["id"], PO)
        validate_error(resp, ApiErrorId.ERR_BUDGET_WOULD_EXCEED)
        assert resp.status_code == 402
        # The SUBMITTED order stays in projected spend: 1000 - 4393 = -3393
        assert get_event(sc["event"]["id"])["available_budget_cents"] == -3393
        assert get_order(order["id"])["status"] == "SUBMITTED"


class TestSegregationOfDuties:
    def test_procurement_officer_cannot_create_orders(self, api):
        """PRD §2.1: "an authenticated caller whose role is not in an endpoint's list, or who fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4 endpoint table: "| POST | `/procurement-orders` | Create a supply/tool order (`event_id`, `project_id`, `lines`); computes the per-line-tax total; starts `DRAFT` | CommunityEngagementManager |"

        Design: Corner/rbac/procurement_officer_cannot_create_orders
        """
        sc = setup_matched_scenario(event_name="Day 45", open_registration=False)
        resp = api.create_procurement_order(
            {
                "event_id": sc["event"]["id"],
                "project_id": sc["project"]["id"],
                "lines": [{"item_name": "Gloves", "quantity": 1, "unit_cost_cents": 100}],
            },
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_segregation_of_duties_creator_cannot_approve(self, api):
        """PRD §3.5: "Approval and rejection belong exclusively to a `ProcurementOfficer`, and segregation of duties is enforced on both: the caller's `X-User-ID` must differ from the order's `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/segregation_of_duties_creator_cannot_approve
        """
        sc = setup_matched_scenario(event_name="Day 46", open_registration=False)
        order = create_order(
            sc["event"]["id"],
            sc["project"]["id"],
            lines=[{"item_name": "Gloves", "quantity": 1, "unit_cost_cents": 100}],
        )
        submit_order(order["id"])

        # Same operator handle that created the order, acting as ProcurementOfficer
        denied = api.approve_order(order["id"], PO_AS_CREATOR)
        validate_error(denied, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

        # A different officer approves
        ok = api.approve_order(order["id"], PO)
        assert validate_success(ok, 200)["status"] == "APPROVED"
