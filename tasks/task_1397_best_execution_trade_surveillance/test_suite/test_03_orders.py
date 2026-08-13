"""Client orders: request shape, conditional limit price, routing gates, and
execution window (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    make_active_arrangement,
    make_order,
    make_venue,
    setup_venue_with_active_arrangement,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

CA = TEST_USERS["compliance_admin_headers"]
OPS = TEST_USERS["ops_admin_headers"]


class TestOrderRequestShape:
    def test_create_limit_order_without_price_returns_422(self, api):
        """PRD §3.2: "The `limit_price_cents` field is conditional: it is
        required when `order_type` is `LIMIT` and forbidden for any other
        order type, and a violation in either direction reports
        `ERR_LIMIT_PRICE_REQUIRED` (HTTP 422) rather than a generic shape
        error."

        Design: Corner/entities/create_limit_order_without_price_returns_422
        """
        base = {
            "symbol": "ACME", "side": "BUY", "quantity": 10,
            "arrival_nbbo_bid_cents": 9990, "arrival_nbbo_ask_cents": 10010,
        }
        resp1 = api.create_order({**base, "client_ref": "L1", "order_type": "LIMIT"}, OPS)
        validate_error(resp1, ApiErrorId.ERR_LIMIT_PRICE_REQUIRED)
        resp2 = api.create_order(
            {**base, "client_ref": "L2", "order_type": "MARKET", "limit_price_cents": 10000}, OPS)
        validate_error(resp2, ApiErrorId.ERR_LIMIT_PRICE_REQUIRED)

    def test_create_order_with_invalid_enum_returns_400(self, api):
        """PRD §2.10: "then request shape — required fields, types, enum
        membership, positive quantities, and a legally named transition target
        (`ERR_INVALID_REQUEST`, with the conditional limit-price rule
        reporting `ERR_LIMIT_PRICE_REQUIRED` instead)". PRD §3.2:
        "`order_type` (`MARKET`, `LIMIT`, or `MARKET_ON_CLOSE`)".

        Design: Corner/entities/create_order_with_invalid_enum_returns_400
        """
        resp = api.create_order({
            "client_ref": "E1", "symbol": "ACME", "side": "BUY", "quantity": 10,
            "order_type": "ICEBERG",
            "arrival_nbbo_bid_cents": 9990, "arrival_nbbo_ask_cents": 10010,
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_order_nonpositive_quantity_returns_400(self, api):
        """PRD §3.2: "`quantity` in shares (which must be greater than zero)".
        PRD §2.10: "then request shape — required fields, types, enum
        membership, positive quantities, and a legally named transition target
        (`ERR_INVALID_REQUEST`, with the conditional limit-price rule
        reporting `ERR_LIMIT_PRICE_REQUIRED` instead)".

        Design: Corner/entities/create_order_nonpositive_quantity_returns_400
        """
        resp = api.create_order({
            "client_ref": "Z1", "symbol": "ACME", "side": "BUY", "quantity": 0,
            "order_type": "MARKET",
            "arrival_nbbo_bid_cents": 9990, "arrival_nbbo_ask_cents": 10010,
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_order_ask_not_above_bid_returns_400(self, api):
        """PRD §3.2: "the arrival quote as `arrival_nbbo_bid_cents` and
        `arrival_nbbo_ask_cents`, both integer cents with the bid greater than
        zero and the ask strictly greater than the bid." PRD §2.10: "then
        request shape — required fields, types, enum membership, positive
        quantities, and a legally named transition target
        (`ERR_INVALID_REQUEST`, with the conditional limit-price rule
        reporting `ERR_LIMIT_PRICE_REQUIRED` instead)".

        Design: Corner/entities/create_order_ask_not_above_bid_returns_400
        """
        resp = api.create_order({
            "client_ref": "NB1", "symbol": "ACME", "side": "BUY", "quantity": 10,
            "order_type": "MARKET",
            "arrival_nbbo_bid_cents": 10000, "arrival_nbbo_ask_cents": 10000,
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestOrderStateMachine:
    def test_order_execute_from_received_rejected(self, api):
        """PRD §3.2: "Execution moves an order from `ROUTED` to `EXECUTED`
        with the supplied `executed_price_cents` and `executed_at`."
        PRD §2.10: "then state admissibility of the requested transition
        including terminal lockdown (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/order_execute_from_received_rejected
        """
        order = validate_success(api.create_order({
            "client_ref": "S1", "symbol": "ACME", "side": "BUY", "quantity": 10,
            "order_type": "MARKET",
            "arrival_nbbo_bid_cents": 9990, "arrival_nbbo_ask_cents": 10010,
        }, OPS), expected_status=201)
        resp = api.order_transition(order["id"], {
            "to_status": "EXECUTED",
            "executed_price_cents": 10000,
            "executed_at": "2026-08-01T00:00:00Z",
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_executed_order_is_terminal(self, api):
        """PRD §3.2: "Executed and cancelled orders admit no further
        transitions." PRD §2.10: "Terminal states admit no further
        transitions anywhere in the system: executed or cancelled orders,
        terminated arrangements and employees, locked snapshots, superseded
        disclosures and policies, retired lexicon policies, completed or
        cancelled training assignments, denied, reconciled, or expired
        personal trades, expired restricted-list entries, and cleared or
        escalated communication items are all final."

        Design: Corner/state_machines/executed_order_is_terminal
        """
        set_clock("2026-08-10T14:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        order = make_order(
            arrangement_id=arrangement["id"], symbol="ACME", quantity=10,
            execute={"price_cents": 10000, "executed_at": "2026-08-10T14:00:00Z"},
        )
        assert order["status"] == "EXECUTED"
        resp = api.order_transition(order["id"], {"to_status": "CANCELLED"}, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_order_execute_with_future_timestamp_rejected(self, api):
        """PRD §3.2: "The execution timestamp must satisfy the execution
        window — no earlier than the order's `created_at` and no later than
        the logical now — or the transition is rejected with
        `ERR_EXECUTION_WINDOW_VIOLATION` (HTTP 422)."

        Design: Corner/errors/order_execute_with_future_timestamp_rejected
        """
        set_clock("2026-08-10T14:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        order = make_order(arrangement_id=arrangement["id"], symbol="ACME", quantity=10)
        assert order["status"] == "ROUTED"
        resp = api.order_transition(order["id"], {
            "to_status": "EXECUTED",
            "executed_price_cents": 10000,
            "executed_at": "2026-08-10T15:00:00Z",  # one hour beyond the logical now
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_EXECUTION_WINDOW_VIOLATION)


class TestRoutingWindowGate:
    def test_route_before_arrangement_window_opens_rejected(self, api):
        """PRD §3.2: "the window must still be open at the logical now —
        `effective_to` must lie in the future (otherwise
        `ERR_INVALID_WINDOW`)" for activation, while routing requires "the
        arrangement itself must be `ACTIVE` with the logical now inside its
        half-open window (`ERR_NO_ACTIVE_ARRANGEMENT`)".

        Design: Corner/validations/route_before_arrangement_window_opens_rejected
        """
        set_clock("2026-08-05T00:00:00Z")
        venue = make_venue(venue_code="NYSE")
        arrangement = make_active_arrangement(
            venue["id"],
            effective_from="2026-08-10T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        )
        assert arrangement["status"] == "ACTIVE", "activation only requires effective_to in the future"

        order = make_order(symbol="ACME", quantity=10)
        resp = api.order_transition(
            order["id"], {"to_status": "ROUTED", "arrangement_id": arrangement["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_ARRANGEMENT)
