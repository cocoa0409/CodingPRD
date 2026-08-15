"""Sales orders: per-line pricing with pinned rounding, the credit-limit gate,
exposure bookkeeping, and submission rules."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    make_customer_headers,
    create_sales_order_payload,
    create_species,
    create_draft_quote,
    create_and_publish_quote,
    create_customer,
    create_order_with_lines,
    submit_order,
    confirm_order,
    get_order,
    get_order_line,
    get_customer,
)

OM = TEST_USERS["operations_manager_headers"]


class TestOrderLinePricing:
    """Each line rounds to whole cents first; the order sums rounded lines."""

    def test_per_line_rounding_then_sum(self, api):
        """PRD §3.6: "Lines are priced in their creation order, earliest `created_at` first: each line locks its `unit_price_cents` from the selected quote, and its `line_total_cents` is the `requested_qty_kg` multiplied by the locked unit price, multiplied by one minus the customer's `discount_pct`, rounded half up to whole cents. The order's `total_cents` is the sum of the already-rounded line totals — the pinned rounding order of §2.5 forbids summing unrounded values."
        PRD §2.5: "Rounding order is pinned wherever a total aggregates per-line amounts: each line is rounded to whole cents first, and only then are the rounded line amounts summed. The alternative order — summing unrounded values and rounding once at the end — produces different cents and is forbidden."

        Design: Difficulty/combinatorial_formula/order_pricing_per_line_rounding_then_sum
        """
        species = create_species(species_code="HADDOCK")
        create_and_publish_quote(species["id"], grade="GRADE_A",
                                 price_per_kg_cents=999)
        customer = create_customer(business_name="Resto Group",
                                   credit_limit_cents=1000000, discount_pct=0.10)
        built = create_order_with_lines(
            customer["id"],
            [{"species_id": species["id"], "requested_qty_kg": 1.55},
             {"species_id": species["id"], "requested_qty_kg": 2.55}])
        submit_order(built["order"]["id"], customer["id"])
        order = confirm_order(built["order"]["id"])

        line1 = get_order_line(built["lines"][0]["id"])
        line2 = get_order_line(built["lines"][1]["id"])
        assert line1["line_total_cents"] == 1394, (
            "round_half_up(1.55 x 999 x 0.9) = round_half_up(1393.605)")
        assert line2["line_total_cents"] == 2293, (
            "round_half_up(2.55 x 999 x 0.9) = round_half_up(2292.705)")
        assert order["total_cents"] == 3687, (
            "Sum of rounded lines; the forbidden sum-then-round order gives 3686")
        assert line1["unit_price_cents"] == 999, "Unit price locks from the quote"

    def test_half_cent_lines_round_half_up_before_summing(self, api):
        """PRD §3.6: "Lines are priced in their creation order, earliest `created_at` first: each line locks its `unit_price_cents` from the selected quote, and its `line_total_cents` is the `requested_qty_kg` multiplied by the locked unit price, multiplied by one minus the customer's `discount_pct`, rounded half up to whole cents. The order's `total_cents` is the sum of the already-rounded line totals — the pinned rounding order of §2.5 forbids summing unrounded values."
        PRD §2.5: "All monetary values are stored and returned as integer cents. Whenever a calculation produces a fractional cent, the value is rounded half up to whole cents at the step the workflow specifies; intermediate values never accumulate hidden precision beyond that step."

        Design: Difficulty/combinatorial_formula/order_pricing_per_line_rounding_then_sum
        """
        species = create_species(species_code="HADDOCK")
        create_and_publish_quote(species["id"], grade="GRADE_A",
                                 price_per_kg_cents=999)
        customer = create_customer(credit_limit_cents=1000000)
        built = create_order_with_lines(
            customer["id"],
            [{"species_id": species["id"], "requested_qty_kg": 1.50},
             {"species_id": species["id"], "requested_qty_kg": 2.50}])
        submit_order(built["order"]["id"], customer["id"])
        order = confirm_order(built["order"]["id"])

        assert get_order_line(built["lines"][0]["id"])["line_total_cents"] == 1499, (
            "1498.5 rounds half up to 1499")
        assert get_order_line(built["lines"][1]["id"])["line_total_cents"] == 2498, (
            "2497.5 rounds half up to 2498")
        assert order["total_cents"] == 3997
        assert order["status"] == "CONFIRMED"
        assert order["confirmed_at"], "A successful confirmation stamps confirmed_at"


class TestCreditLimitBoundary:
    """The confirm-time credit gate: exposure + candidate total <= limit."""

    def test_exact_limit_passes_one_cent_over_fails(self, api):
        """PRD §3.6: "The credit gate then applies: the customer's current `credit_exposure_cents` plus the candidate order's `total_cents` must not exceed the customer's `credit_limit_cents`, and landing exactly on the limit is permitted; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (402)."
        PRD §3.6: "A customer's `credit_exposure_cents` is the sum of `total_cents` over that customer's orders in `CONFIRMED`, `FULFILLED`, or `INVOICED` status; orders in `DRAFT`, `SUBMITTED`, or `CANCELLED` are excluded."

        Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_passes
        """
        species = create_species(species_code="COD")
        create_and_publish_quote(species["id"], grade="GRADE_A",
                                 price_per_kg_cents=1200)
        customer = create_customer(credit_limit_cents=12000)

        order_a = create_order_with_lines(
            customer["id"],
            [{"species_id": species["id"], "requested_qty_kg": 10.00}])
        submit_order(order_a["order"]["id"], customer["id"])
        order_b = create_order_with_lines(
            customer["id"],
            [{"species_id": species["id"], "requested_qty_kg": 1.00}])
        submit_order(order_b["order"]["id"], customer["id"])

        confirmed = confirm_order(order_a["order"]["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["total_cents"] == 12000, "0 + 12000 <= 12000 passes exactly"
        assert get_customer(customer["id"])["credit_exposure_cents"] == 12000

        resp = api_client.confirm_sales_order(order_b["order"]["id"], OM)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_order(order_b["order"]["id"])["status"] == "SUBMITTED", (
            "12000 + 1200 > 12000: the rejected order stays SUBMITTED")

    def test_cancellation_frees_exposure_for_a_waiting_order(self, api):
        """PRD §3.6: "Exposure is recomputed at confirmation, at cancellation, and at substitution application, so the figure always reflects the live book."
        PRD §3.6: "The credit gate then applies: the customer's current `credit_exposure_cents` plus the candidate order's `total_cents` must not exceed the customer's `credit_limit_cents`, and landing exactly on the limit is permitted; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (402)."

        Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_passes
        """
        species = create_species(species_code="COD")
        create_and_publish_quote(species["id"], grade="GRADE_A",
                                 price_per_kg_cents=1200)
        customer = create_customer(credit_limit_cents=12000)

        order_a = create_order_with_lines(
            customer["id"],
            [{"species_id": species["id"], "requested_qty_kg": 10.00}])
        submit_order(order_a["order"]["id"], customer["id"])
        confirm_order(order_a["order"]["id"])

        order_b = create_order_with_lines(
            customer["id"],
            [{"species_id": species["id"], "requested_qty_kg": 1.00}])
        submit_order(order_b["order"]["id"], customer["id"])
        validate_error(api_client.confirm_sales_order(order_b["order"]["id"], OM),
                       ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

        get_success_data(api_client.cancel_sales_order(
            order_a["order"]["id"], make_customer_headers(customer["id"])))
        assert get_customer(customer["id"])["credit_exposure_cents"] == 0

        confirmed = validate_success(
            api_client.confirm_sales_order(order_b["order"]["id"], OM))
        assert confirmed["status"] == "CONFIRMED"
        assert get_customer(customer["id"])["credit_exposure_cents"] == 1200


class TestConfirmValidationPrecedence:
    """State (step 6) is evaluated before fiscal (step 10)."""

    def test_confirm_cancelled_order_reports_state_not_credit(self, api):
        """PRD §2.8: "Every request is validated in a fixed order, and the first failing check determines the error response. The ordering is part of the contract: a missing header surfaces before a permission failure, a stale version surfaces before an invalid-state failure, and a hold violation surfaces before a fiscal failure."
        PRD §2.8: "6. **State.** The target resource is in a valid from-state for the requested transition, else the machine-specific state error"
        PRD §3.6: "Confirmation is where pricing hardens, performed by an `OperationsManager` on a `SUBMITTED` order."

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_order_state_beats_credit
        """
        species = create_species(species_code="COD")
        create_and_publish_quote(species["id"], grade="GRADE_A",
                                 price_per_kg_cents=1200)
        # The would-be total (12000) also breaches the limit (10000), so both
        # the state check and the fiscal check fail; state must win.
        customer = create_customer(credit_limit_cents=10000)
        built = create_order_with_lines(
            customer["id"],
            [{"species_id": species["id"], "requested_qty_kg": 10.00}])
        submit_order(built["order"]["id"], customer["id"])
        get_success_data(api_client.cancel_sales_order(
            built["order"]["id"], make_customer_headers(customer["id"])))

        resp = api_client.confirm_sales_order(built["order"]["id"], OM)
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
        assert get_order(built["order"]["id"])["status"] == "CANCELLED"

    def test_confirm_draft_order_reports_state_not_credit(self, api):
        """PRD §2.8: "Every request is validated in a fixed order, and the first failing check determines the error response."
        PRD §2.8: "6. **State.** The target resource is in a valid from-state for the requested transition, else the machine-specific state error"
        PRD §3.6: "Confirmation is where pricing hardens, performed by an `OperationsManager` on a `SUBMITTED` order."

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_order_state_beats_credit
        """
        species = create_species(species_code="COD")
        create_and_publish_quote(species["id"], grade="GRADE_A",
                                 price_per_kg_cents=1200)
        customer = create_customer(credit_limit_cents=100)
        built = create_order_with_lines(
            customer["id"],
            [{"species_id": species["id"], "requested_qty_kg": 10.00}])

        resp = api_client.confirm_sales_order(built["order"]["id"], OM)
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
        assert get_order(built["order"]["id"])["status"] == "DRAFT"


def test_credit_exposure_includes_only_active_book_states(api):
    """PRD §3.6: "A customer's `credit_exposure_cents` is the sum of `total_cents` over that customer's orders in `CONFIRMED`, `FULFILLED`, or `INVOICED` status; orders in `DRAFT`, `SUBMITTED`, or `CANCELLED` are excluded. Exposure is recomputed at confirmation, at cancellation, and at substitution application, so the figure always reflects the live book."

    Design: Corner/calculations/calc_credit_exposure_state_filtering
    """
    species = create_species(species_code="COD")
    create_and_publish_quote(species["id"], grade="GRADE_A",
                             price_per_kg_cents=1200)
    customer = create_customer(credit_limit_cents=1000000)
    built = create_order_with_lines(
        customer["id"],
        [{"species_id": species["id"], "requested_qty_kg": 10.00}])
    submit_order(built["order"]["id"], customer["id"])
    assert get_customer(customer["id"])["credit_exposure_cents"] == 0, (
        "SUBMITTED is outside the exposure set")

    confirm_order(built["order"]["id"])
    assert get_customer(customer["id"])["credit_exposure_cents"] == 12000, (
        "CONFIRMED counts")

    get_success_data(api_client.cancel_sales_order(
        built["order"]["id"], make_customer_headers(customer["id"])))
    assert get_customer(customer["id"])["credit_exposure_cents"] == 0, (
        "CANCELLED drops out of the sum")


def test_confirm_without_published_quote_rejected(api):
    """PRD §3.6: "Every line must resolve a standing price through the selector of §3.2 for its species and requested grade as of the confirmation date; any unresolvable line rejects the confirmation with `ERR_QUOTE_NOT_PUBLISHED` (422)."
    PRD §3.2: "An empty candidate set surfaces `ERR_QUOTE_NOT_PUBLISHED` (422) at the point of use."

    Design: Corner/errors/err_quote_not_published_on_confirm
    """
    species = create_species(species_code="COD")
    create_draft_quote(species["id"], grade="GRADE_A", price_per_kg_cents=1200)
    customer = create_customer(credit_limit_cents=1000000)
    built = create_order_with_lines(
        customer["id"],
        [{"species_id": species["id"], "requested_qty_kg": 10.00}])
    submit_order(built["order"]["id"], customer["id"])

    resp = api_client.confirm_sales_order(built["order"]["id"], OM)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_PUBLISHED)
    order = get_order(built["order"]["id"])
    assert order["status"] == "SUBMITTED"
    assert order["total_cents"] == 0


def test_submit_empty_order_rejected(api):
    """PRD §3.6: "Submission is the buyer's own act: only the owning `Customer` may submit, moving a `DRAFT` order to `SUBMITTED`. An order in any other state draws `ERR_ORDER_INVALID_STATE`, a non-owner draws `ERR_OWNERSHIP_MISMATCH` (403), and an order with no lines at all draws `ERR_ORDER_EMPTY` (422)."

    Design: Corner/validations/val_order_submit_empty_rejected
    """
    customer = create_customer(credit_limit_cents=1000000)
    order = get_success_data(api_client.create_sales_order(
        create_sales_order_payload(customer_id=customer["id"]),
        make_customer_headers(customer["id"])))

    resp = api_client.submit_sales_order(
        order["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_EMPTY)
    assert get_order(order["id"])["status"] == "DRAFT"


def test_customer_cannot_confirm_own_order(api):
    """PRD §2.1: "A request whose role is valid but not permitted for the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: "POST | `/sales-orders/{id}/confirm` | Confirm an order: locks line prices from the standing published quotes, computes totals, enforces the credit limit | OperationsManager"

    Design: Corner/rbac/rbac_customer_cannot_confirm_order
    """
    species = create_species(species_code="COD")
    create_and_publish_quote(species["id"], grade="GRADE_A",
                             price_per_kg_cents=1200)
    customer = create_customer(credit_limit_cents=1000000)
    built = create_order_with_lines(
        customer["id"],
        [{"species_id": species["id"], "requested_qty_kg": 10.00}])
    submit_order(built["order"]["id"], customer["id"])

    resp = api_client.confirm_sales_order(
        built["order"]["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert get_order(built["order"]["id"])["status"] == "SUBMITTED"
