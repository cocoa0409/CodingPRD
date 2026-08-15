"""EPCIS event capture and the serialized case/unit state machine: event
sequencing, lot freshness, event-time admissibility, hash chaining, and the
case-units sub-resource listing."""
from test_helpers import (
    ApiErrorId,
    CaseStatus,
    UnitStatus,
    assert_epcis_event,
    create_case,
    create_case_with_units,
    create_customer,
    create_epcis_event_payload,
    create_product,
    create_supplier,
    get_case,
    get_unit,
    set_clock,
    setup_case_with_counterparties,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEventSequencing:
    def test_receive_case_before_ship_rejected(self, api, warehouse_operator_headers):
        """PRD §3.3: "A `RECEIVE` event requires the case to be `SHIPPED`
        (otherwise `ERR_CASE_NOT_IN_TRANSIT`) and moves the case and its units
        `SHIPPED` → `RECEIVED`."

        A RECEIVE against a still-COMMISSIONED case is rejected.

        Design: Corner/state_machines/receive_case_before_ship_rejected
        """
        set_clock()
        _p, case, _units, supplier, recipient = setup_case_with_counterparties(num_units=0)

        payload = create_epcis_event_payload(
            case["id"], supplier["id"], recipient["id"],
            event_type="RECEIVE", event_time="2026-07-31T01:00:00Z",
        )
        resp = api.create_epcis_event(payload, warehouse_operator_headers)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_TRANSIT)
        assert get_case(case["id"])["case_status"] == CaseStatus.COMMISSIONED.value


class TestShipThenReceiveChain:
    def test_ship_then_receive_transitions_and_hash_chain(
        self, api, warehouse_operator_headers
    ):
        """PRD §3.3: "on success the case moves `COMMISSIONED` → `SHIPPED`,
        every one of its units moves `COMMISSIONED` → `SHIPPED`, and the case's
        `version` increments. A `RECEIVE` event requires the case to be
        `SHIPPED` (otherwise `ERR_CASE_NOT_IN_TRANSIT`) and moves the case and
        its units `SHIPPED` → `RECEIVED`."
        PRD §3.3: "The first event recorded for a case carries an empty string.
        Thereafter the system locates the previous event for the same case —
        the one with the greatest `event_time`, ties broken by the greatest
        `recorded_at` — and computes a hex SHA-256-style digest over the
        concatenation of that previous event's `txn_history_hash`, the current
        `event_type`, and the current `event_time` rendered as an ISO 8601
        string."

        Design: Corner/state_machines/epcis_ship_then_receive_happy_path_and_hash_chain
        """
        set_clock("2026-08-01T03:00:00Z")
        _p, case, units, supplier, recipient = setup_case_with_counterparties(num_units=1)
        unit = units[0]

        ship_payload = create_epcis_event_payload(
            case["id"], supplier["id"], recipient["id"],
            event_type="SHIP", event_time="2026-08-01T01:00:00Z",
        )
        ev1 = validate_success(
            api.create_epcis_event(ship_payload, warehouse_operator_headers),
            expected_status=201,
        )
        assert_epcis_event(ev1)
        # SHIP is the first event recorded for this case: genesis hash is empty.
        assert ev1["txn_history_hash"] == ""

        recv_payload = create_epcis_event_payload(
            case["id"], supplier["id"], recipient["id"],
            event_type="RECEIVE", event_time="2026-08-01T02:00:00Z",
        )
        ev2 = validate_success(
            api.create_epcis_event(recv_payload, warehouse_operator_headers),
            expected_status=201,
        )
        assert_epcis_event(ev2)
        # The second event chains the first: non-empty and distinct.
        assert ev2["txn_history_hash"] != ""
        assert ev2["txn_history_hash"] != ev1["txn_history_hash"]

        assert get_case(case["id"])["case_status"] == CaseStatus.RECEIVED.value
        assert get_unit(unit["id"])["unit_status"] == UnitStatus.RECEIVED.value


class TestEventFreshness:
    def test_epcis_event_time_in_future_rejected(self, api, warehouse_operator_headers):
        """PRD §3.3: "An `event_time` later than the current logical clock is
        rejected with `ERR_EVENT_TIME_IN_FUTURE` (HTTP 422), and that freshness
        check is evaluated before event sequencing."

        Design: Corner/validations/epcis_event_time_in_future_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        _p, case, _u, supplier, recipient = setup_case_with_counterparties(num_units=0)

        payload = create_epcis_event_payload(
            case["id"], supplier["id"], recipient["id"],
            event_type="SHIP", event_time="2026-08-02T00:00:00Z",
        )
        resp = api.create_epcis_event(payload, warehouse_operator_headers)
        validate_error(resp, ApiErrorId.ERR_EVENT_TIME_IN_FUTURE)
        assert get_case(case["id"])["case_status"] == CaseStatus.COMMISSIONED.value

    def test_expired_case_ship_rejected(self, api, warehouse_operator_headers):
        """PRD §3.3: "A `SHIP` event requires the case to be `COMMISSIONED`
        (otherwise `ERR_CASE_NOT_SHIPPABLE`) and its `expiry_date` to be
        strictly after the current logical clock (otherwise
        `ERR_PRODUCT_EXPIRED`, HTTP 422)".

        An expiry equal to the current clock is not strictly after it.

        Design: Corner/validations/expired_case_ship_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        product = create_product()
        case = create_case(product["id"], expiry_date="2026-08-01T00:00:00Z")
        supplier = create_supplier(name="SupEX")
        recipient = create_customer(name="RecEX", credit_limit_cents=0)

        payload = create_epcis_event_payload(
            case["id"], supplier["id"], recipient["id"],
            event_type="SHIP", event_time="2026-08-01T00:00:00Z",
        )
        resp = api.create_epcis_event(payload, warehouse_operator_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_EXPIRED)
        assert get_case(case["id"])["case_status"] == CaseStatus.COMMISSIONED.value


class TestCaseUnitsSubResource:
    def test_case_units_listing_returns_aggregated_units(
        self, api, warehouse_operator_headers
    ):
        """PRD §3.3: "Units are then aggregated into the case: commissioning a
        unit takes its `sni` — a Serialized Numeric Identifier combining GTIN
        and serial, unique across all units — and the parent `case_id` that
        binds the unit into the case's aggregation tree".
        PRD §4: GET /wholesale/serialized-cases/{caseId}/units — "List units
        aggregated under a case".

        Design: Corner/endpoints/sub_resource_units_listing
        """
        product = create_product()
        case, _units = create_case_with_units(product["id"], num_units=2)

        resp = api.list_case_units(case["id"], warehouse_operator_headers)
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"case has exactly 2 units, got {len(data)}"
        assert meta["total_count"] == 2
        for unit in data:
            assert unit["case_id"] == case["id"], (
                f"sub-resource listing must return only units of the case; "
                f"got case_id {unit['case_id']}"
            )
            assert unit["unit_status"] == UnitStatus.COMMISSIONED.value
