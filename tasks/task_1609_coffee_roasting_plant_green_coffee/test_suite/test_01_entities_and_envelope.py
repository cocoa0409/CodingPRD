"""Entity creation, system-managed fields, enum validation, and envelope shape."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_counterparty,
    create_counterparty_payload,
    create_ptbf_contract,
    create_fixed_contract,
    create_counterparty,
    is_iso8601_timestamp,
    is_valid_uuid,
    record_price_fix,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

TRADER = TEST_USERS["trader_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


class TestCounterpartyCreation:
    def test_create_counterparty_with_all_required_fields_returns_201(self, api):
        """PRD §3.1: "A `Trader` registers one by supplying a `counterparty_ref`
        (the external supplier or importer reference code), a `legal_name`, a
        `counterparty_kind` of `SUPPLIER`, `IMPORTER`, or `CUSTOMER`, and a
        `credit_limit_usd` bounding the open exposure the house will tolerate.
        A new counterparty arrives with `counterparty_status` `ACTIVE` and
        `open_exposure_usd` zero."

        Design: Corner/entities/create_counterparty_with_all_required_fields_returns_201
        """
        set_clock()
        resp = api.create_counterparty(
            create_counterparty_payload(
                counterparty_ref="SUP-NEW", legal_name="New Supplier",
                counterparty_kind="SUPPLIER", credit_limit_usd=100000,
            ),
            TRADER,
        )
        data = validate_success(resp, 201)
        assert_counterparty(data)
        assert is_valid_uuid(data["id"])
        assert data["counterparty_status"] == "ACTIVE"
        assert data["open_exposure_usd"] == 0
        assert data["version"] == 1

    def test_create_counterparty_missing_credit_limit_returns_invalid_request(
            self, api):
        """PRD §2.8: "Structural request validation — required fields present,
        unknown fields rejected, enum values within their declared sets, and
        numeric ranges respected (for example `advance_rate_pct` between 0 and
        1, `moisture_pct` between 0 and 100, attribute scores within 0–10 in
        0.25 steps) — shares this same post-concurrency priority ordering and
        is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A `Trader` registers one by supplying a `counterparty_ref`
        (the external supplier or importer reference code), a `legal_name`, a
        `counterparty_kind` of `SUPPLIER`, `IMPORTER`, or `CUSTOMER`, and a
        `credit_limit_usd` bounding the open exposure the house will tolerate."

        Design: Corner/entities/create_counterparty_missing_credit_limit_returns_invalid_request
        """
        set_clock()
        payload = {
            "counterparty_ref": "SUP-MISS",
            "legal_name": "Missing Field",
            "counterparty_kind": "SUPPLIER",
        }
        resp = api.create_counterparty(payload, TRADER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestSystemFields:
    def test_entity_system_fields_id_created_at_updated_at_present(self, api):
        """PRD §2.4: "Every resource carries a standard set of system-managed
        properties: `id` (string): a server-minted UUID with no type prefix.
        `created_at` (string): an ISO 8601 UTC timestamp with three fractional
        digits recording when the resource was created. `updated_at` (string):
        an ISO 8601 UTC timestamp refreshed on every modification. `version`
        (integer): starts at its initial value on creation and increments by
        exactly 1 on every mutation of the resource — including system-driven
        mutations such as cascades, recomputations, and automatic state
        transitions, not only client-initiated writes."
        PRD §2.11: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z; until an operator sets it, the clock returns
        precisely this default and never falls back to wall-clock time."

        Design: Corner/entities/entity_system_fields_id_created_at_updated_at_present
        """
        set_clock()
        resp = api.create_counterparty(
            create_counterparty_payload(
                counterparty_ref="SUP-SYS", legal_name="Sys Fields",
                counterparty_kind="SUPPLIER", credit_limit_usd=1000,
            ),
            TRADER,
        )
        data = validate_success(resp, 201)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        # Server logical clock is set to the default startup instant.
        assert data["created_at"] == "2026-08-01T00:00:00Z"
        assert data["updated_at"] == "2026-08-01T00:00:00Z"
        assert data["version"] == 1

    def test_price_fix_event_is_append_only(self, api):
        """PRD §2.4: "One entity is the exception. A price-fix event is an
        append-only ledger entry: it carries `id` and `created_at`, and both
        `updated_at` and `version` are absent. It is never modified after
        recording; its `fixed_at` timestamp and `fixed_by_trader_id` are
        immutable."

        Design: Corner/entities/price_fix_event_is_append_only
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-IMM")
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-IMM",
                                         total_lbs=5000, differential=0.25)
        fix = record_price_fix(contract["id"], 1000, 1.80,
                                contract["version"])
        # List the contract's price-fix events and check shape.
        fixes, _meta = validate_paginated(
            api.list_price_fixes(contract["id"], TRADER))
        assert len(fixes) == 1
        fix0 = fixes[0]
        assert fix0["id"] == fix["id"]
        assert is_valid_uuid(fix0["id"])
        assert is_iso8601_timestamp(fix0["created_at"])
        assert "version" not in fix0, (
            "price-fix events must not expose a version field"
        )
        assert "updated_at" not in fix0, (
            "price-fix events must not expose updated_at"
        )
        assert fix0["fix_lbs"] == 1000


class TestEnums:
    def test_enum_out_of_set_rejected(self, api):
        """PRD §2.8: "Structural request validation — required fields present,
        unknown fields rejected, enum values within their declared sets, and
        numeric ranges respected (for example `advance_rate_pct` between 0 and
        1, `moisture_pct` between 0 and 100, attribute scores within 0–10 in
        0.25 steps) — shares this same post-concurrency priority ordering and
        is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "a `counterparty_kind` of `SUPPLIER`, `IMPORTER`, or
        `CUSTOMER`"

        Design: Corner/entities/enum_out_of_set_rejected
        """
        set_clock()
        resp = api.create_counterparty(
            create_counterparty_payload(
                counterparty_ref="SUP-ENUM", legal_name="Enum Violator",
                counterparty_kind="BROKER", credit_limit_usd=1000,
            ),
            TRADER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFound:
    def test_not_found_on_bogus_id(self, api):
        """PRD §2.8: "Then existence: every identifier in the URL path must
        resolve to an existing resource, validated strictly left to right so
        the first unresolvable identifier produces `ERR_NOT_FOUND` (HTTP 404)
        before later segments are even examined; identifiers referenced in
        the request body are likewise checked for existence with the same
        error."

        Design: Corner/entities/not_found_on_bogus_id
        """
        set_clock()
        resp = api.get_counterparty(NON_EXISTENT_UUID, TRADER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestComputedFields:
    def test_contract_fixed_outright_initializes_pricing_fields(self, api):
        """PRD §3.1: "an outright contract moves immediately to
        `NOT_APPLICABLE`, with `fixed_lbs_accum` set to `total_lbs`,
        `unpriced_lbs` zero, `weighted_avg_fixed_futures_usd` left null
        (there is no futures leg), and `priced_notional_usd` computed as
        `total_lbs` times the outright price, rounded half-up to 2 decimals."

        Design: Corner/entities/contract_fixed_outright_initializes_pricing_fields
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-FO")
        contract = create_fixed_contract(
            supplier["id"], contract_ref="C-FO", total_lbs=5000,
            fixed_price=2.50,
        )
        assert contract["pricing_status"] == "NOT_APPLICABLE"
        assert contract["fixed_lbs_accum"] == 5000
        assert contract["unpriced_lbs"] == 0
        assert contract["weighted_avg_fixed_futures_usd"] is None
        assert contract["priced_notional_usd"] == 12500.00

    def test_green_lot_available_lbs_computed_not_input(self, api):
        """PRD §3.4: "The lot's `landed_cost_usd_per_lb` is fixed at this
        moment per the dual-basis rule of §2.7, and its `available_lbs` is
        derived as its `received_lbs` minus any `ACTIVE` roast allocations
        against it minus any pounds pledged under active financing reserves."
        PRD §3.4: "Receipt moves the shipment to `RECEIVED`, flips its
        `qc_status` from `NOT_REQUIRED` to `PENDING_CUP`, and creates exactly
        one green lot child in `QUARANTINE` carrying the received mass and
        intake measurements."

        Design: Corner/entities/green_lot_available_lbs_computed_not_input
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-CMP")
        contract = create_fixed_contract(
            supplier["id"], contract_ref="C-CMP", total_lbs=1000,
            fixed_price=2.00,
        )
        shipment = validate_success(api.create_shipment(
            contract["id"],
            {"shipment_ref": "SH-CMP", "planned_lbs": 1000,
             "scheduled_arrival": "2026-09-01T00:00:00Z"},
            TEST_USERS["logistics_headers"],
        ), 201)
        validate_success(api.depart_shipment(shipment["id"],
                                              TEST_USERS["logistics_headers"]))
        validate_success(api.arrive_shipment(shipment["id"],
                                              TEST_USERS["logistics_headers"]))
        validate_success(api.receive_shipment(
            shipment["id"],
            {"received_lbs": 1000, "lot_code": "L-CMP", "moisture_pct": 11,
             "warehouse_location": "WH-A"},
            WAREHOUSE,
        ))
        lots, _meta = validate_paginated(
            api.list_green_lots(WAREHOUSE, params={"shipment_id": shipment["id"]}))
        assert len(lots) == 1
        assert lots[0]["received_lbs"] == 1000
        assert lots[0]["available_lbs"] == 1000, (
            "available_lbs is system-computed from received_lbs initially"
        )
