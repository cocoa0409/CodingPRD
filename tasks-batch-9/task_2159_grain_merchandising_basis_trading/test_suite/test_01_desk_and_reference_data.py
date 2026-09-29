"""Standing up the desk: registration, elevators, discount schedules and
risk limits, plus the pagination and not-found envelopes that govern reads."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_WEIGHT_TIERS,
    TEST_WEIGHT_TIERS_DEAR,
    UNKNOWN_UUID,
    assert_desk_credit_invariants,
    assert_elevator_location,
    assert_trading_desk,
    create_risk_limit_payload,
    create_trading_desk_payload,
    is_valid_uuid,
    new_desk,
    new_location,
    new_risk_limit,
    new_schedule,
    read_desk,
    read_risk_limit,
    read_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


ADMIN = TEST_USERS["desk_admin_headers"]
RISK = TEST_USERS["risk_officer_headers"]
MERCH = TEST_USERS["merchandiser_headers"]
INSPECTOR = TEST_USERS["grain_inspector_headers"]


class TestDeskRegistration:

    def test_registered_desk_starts_at_version_one_with_normal_posture(self, api):
        """PRD §2.4: "Most resources additionally carry `updated_at` — the same
        format, refreshed on every mutation of the row — and `version`, an integer
        that begins at 1 when the row is created and increments by exactly 1 on
        every mutation."
        PRD §3.1: "The desk comes into existence with `posture` `NORMAL` and every
        derived figure — `margin_requirement_usd`, `open_margin_call_usd`,
        `credit_utilization`, `committed_hedge_lots`, `open_bushel_commitment`,
        `unpriced_bushels`, `realized_hedge_pnl_usd` — at zero, and
        `available_credit_usd` equal to the full credit line."

        Design: Corner/entities/create_trading_desk_returns_system_minted_id_and_version_one
        """
        payload = create_trading_desk_payload(
            desk_code="CD01", name="Corner Desk 1", credit_line_usd=250000.00
        )
        created = validate_success(api.create_trading_desk(payload, ADMIN), 201)

        desk = validate_success(api.get_trading_desk(created["id"], ADMIN), 200)
        assert_trading_desk(desk)

        assert is_valid_uuid(desk["id"]), (
            f"desk id must be a bare UUID with no type prefix, got {desk['id']}"
        )
        assert desk["version"] == 1, f"Expected version 1, got {desk['version']}"
        assert desk["posture"] == "NORMAL"
        assert desk["margin_requirement_usd"] == pytest.approx(0, abs=0.01)
        assert desk["open_margin_call_usd"] == pytest.approx(0, abs=0.01)
        assert desk["available_credit_usd"] == pytest.approx(250000.00, abs=0.01)
        assert desk["credit_utilization"] == pytest.approx(0, abs=0.0001)
        assert desk["committed_hedge_lots"] == 0
        assert desk["open_bushel_commitment"] == pytest.approx(0, abs=0.01)
        assert desk["unpriced_bushels"] == pytest.approx(0, abs=0.01)
        assert desk["realized_hedge_pnl_usd"] == pytest.approx(0, abs=0.01)
        assert_desk_credit_invariants(desk)

    def test_reading_an_unknown_desk_id_returns_trading_desk_not_found(self, api):
        """PRD §2.8: "Every id embedded in the URL path resolves to a stored row,
        checked left to right. The code names the missing entity:
        `ERR_TRADING_DESK_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`,
        `ERR_DISCOUNT_SCHEDULE_NOT_FOUND`, `ERR_RISK_LIMIT_NOT_FOUND`,
        `ERR_RAIL_FLEET_NOT_FOUND`, `ERR_BID_NOT_FOUND`,
        `ERR_HEDGE_POSITION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_PRICING_ORDER_NOT_FOUND`, `ERR_MARGIN_CALL_NOT_FOUND`,
        `ERR_DELIVERY_TICKET_NOT_FOUND` or `ERR_FREIGHT_BOOKING_NOT_FOUND`, each at
        HTTP 404."

        Design: Corner/entities/get_trading_desk_with_unknown_id_returns_not_found
        """
        new_desk(desk_code="CD02", name="Corner Desk 2", credit_line_usd=250000.00)

        resp = api.get_trading_desk(UNKNOWN_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_TRADING_DESK_NOT_FOUND.value, 404)

        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)

    def test_unknown_path_ids_answer_with_the_named_entity_not_found_code(self, api):
        """PRD §2.8: "Every id embedded in the URL path resolves to a stored row,
        checked left to right. The code names the missing entity:
        `ERR_TRADING_DESK_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`,
        `ERR_DISCOUNT_SCHEDULE_NOT_FOUND`, `ERR_RISK_LIMIT_NOT_FOUND`,
        `ERR_RAIL_FLEET_NOT_FOUND`, `ERR_BID_NOT_FOUND`,
        `ERR_HEDGE_POSITION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_PRICING_ORDER_NOT_FOUND`, `ERR_MARGIN_CALL_NOT_FOUND`,
        `ERR_DELIVERY_TICKET_NOT_FOUND` or `ERR_FREIGHT_BOOKING_NOT_FOUND`, each at
        HTTP 404."

        Design: Corner/errors/unknown_path_ids_return_entity_specific_not_found_errors
        """
        new_desk(desk_code="CD55", name="Corner Desk 55", credit_line_usd=250000.00)

        cases = [
            (api.get_discount_schedule(UNKNOWN_UUID, ADMIN),
             ApiErrorId.ERR_DISCOUNT_SCHEDULE_NOT_FOUND.value),
            (api.get_risk_limit(UNKNOWN_UUID, RISK),
             ApiErrorId.ERR_RISK_LIMIT_NOT_FOUND.value),
            (api.get_pricing_order(UNKNOWN_UUID, MERCH),
             ApiErrorId.ERR_PRICING_ORDER_NOT_FOUND.value),
            (api.get_delivery_ticket(UNKNOWN_UUID, INSPECTOR),
             ApiErrorId.ERR_DELIVERY_TICKET_NOT_FOUND.value),
        ]
        for resp, expected_error in cases:
            validate_error(resp, expected_error, 404)
            assert resp.json()["response_type"] == "error"


class TestElevatorRegistration:

    def test_omitting_intake_capacity_is_an_invalid_request(self, api):
        """PRD §2.8: "Required fields are present, enum values are members of their
        declared sets, numbers respect their declared ranges, dates parse as
        `YYYY-MM-DD` and datetimes as ISO 8601 UTC — otherwise
        `ERR_INVALID_REQUEST` (400). Applies to every write endpoint."
        PRD §3.1: "Registering one, again a `DeskAdmin` act, takes the owning
        `desk_id`, a `location_code` unique across all elevators, a `name`, and an
        `intake_capacity_bushels` greater than zero."

        Design: Corner/entities/create_elevator_location_missing_required_field_returns_invalid_request
        """
        desk = new_desk(desk_code="CD04", name="Corner Desk 4",
                        credit_line_usd=250000.00)

        payload = {"desk_id": desk["id"], "location_code": "E1", "name": "One"}
        validate_error(
            api.create_elevator_location(payload, ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST.value, 400,
        )

        rows, meta = validate_paginated(
            api.list_elevator_locations(ADMIN, params={"desk_id": desk["id"]})
        )
        assert meta["total_count"] == 0, "the rejected create must not persist a row"
        assert rows == []

    def test_rail_served_defaults_to_false_when_omitted(self, api):
        """PRD §3.1: "The optional `rail_served` flag says whether the elevator has
        a rail spur; it defaults to false when omitted, and an elevator without a
        spur can never host a rail booking."
        PRD §3.1: "A fresh elevator's `committed_intake_bushels` — the running total
        of bushels on `ACTIVE` purchase contracts written at that elevator — starts
        at zero."

        Design: Corner/entities/create_elevator_location_defaults_rail_served_to_false
        """
        desk = new_desk(desk_code="CD05", name="Corner Desk 5",
                        credit_line_usd=250000.00)

        payload = {
            "desk_id": desk["id"], "location_code": "E1", "name": "One",
            "intake_capacity_bushels": 100000,
        }
        location = validate_success(api.create_elevator_location(payload, ADMIN), 201)
        assert_elevator_location(location)

        assert location["rail_served"] is False, (
            f"rail_served must default to false, got {location['rail_served']}"
        )
        assert location["committed_intake_bushels"] == pytest.approx(0, abs=0.01)
        assert location["version"] == 1

    def test_elevator_list_pages_with_total_count_and_has_more(self, api):
        """PRD §2.3: "For list responses, the `meta` object carries `limit`,
        `offset`, `total_count` and `has_more`, where `total_count` is the number of
        rows matching the filters before pagination is applied and `has_more` is
        true when rows remain beyond the current page."

        Design: Corner/entities/list_elevator_locations_paginates_with_total_count_and_has_more
        """
        desk = new_desk(desk_code="CD03", name="Corner Desk 3",
                        credit_line_usd=250000.00)
        new_location(desk["id"], location_code="E1", name="One",
                     intake_capacity_bushels=100000, rail_served=True)
        for code, name in (("E2", "Two"), ("E3", "Three")):
            payload = {"desk_id": desk["id"], "location_code": code, "name": name,
                       "intake_capacity_bushels": 100000}
            validate_success(api.create_elevator_location(payload, ADMIN), 201)

        first_resp = api.list_elevator_locations(
            ADMIN, params={"desk_id": desk["id"], "limit": 2, "offset": 0}
        )
        page_one, meta_one = validate_paginated(first_resp)
        assert len(page_one) == 2, f"Expected 2 rows on page one, got {len(page_one)}"
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert first_resp.json()["response_type"] == "array"

        second_resp = api.list_elevator_locations(
            ADMIN, params={"desk_id": desk["id"], "limit": 2, "offset": 2}
        )
        page_two, meta_two = validate_paginated(second_resp)
        assert len(page_two) == 1, f"Expected 1 row on page two, got {len(page_two)}"
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert second_resp.json()["response_type"] == "array"

    def test_pagination_limit_above_one_hundred_is_rejected_not_clamped(self, api):
        """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted,
        may not be smaller than 1, and may not be larger than 100. `offset` controls
        the starting position: it defaults to 0 and may not be negative. A value
        outside these bounds is a malformed request and is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/endpoints/pagination_limit_above_the_declared_max_returns_invalid_request
        """
        desk = new_desk(desk_code="CD44", name="Corner Desk 44",
                        credit_line_usd=250000.00)
        new_location(desk["id"], location_code="E1", name="One",
                     intake_capacity_bushels=100000, rail_served=True)

        validate_error(
            api.list_elevator_locations(
                ADMIN, params={"desk_id": desk["id"], "limit": 200}
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value, 400,
        )

        rows, meta = validate_paginated(api.list_elevator_locations(
            ADMIN, params={"desk_id": desk["id"], "limit": 100}
        ))
        assert meta["total_count"] == 1
        assert len(rows) == 1


class TestDiscountScheduleActivation:

    def test_activating_a_second_schedule_supersedes_the_incumbent(self, api):
        """PRD §3.1: "On success the schedule moves `DRAFT → ACTIVE`, and every
        other schedule for the same `commodity_code` that was sitting in `ACTIVE`
        moves `ACTIVE → SUPERSEDED` in the same operation."

        Design: Corner/state_machines/activating_a_second_discount_schedule_supersedes_the_first
        """
        first = new_schedule(
            activate=True, commodity_code="CORN",
            effective_from="2026-07-01T00:00:00Z",
            tiers=[dict(t) for t in TEST_WEIGHT_TIERS],
        )
        second = new_schedule(
            activate=False, commodity_code="CORN",
            effective_from="2026-07-15T00:00:00Z",
            tiers=[dict(t) for t in TEST_WEIGHT_TIERS_DEAR],
        )

        activated = validate_success(
            api.activate_discount_schedule(second["id"], ADMIN), 200
        )
        assert activated["status"] == "ACTIVE"
        assert read_schedule(first["id"])["status"] == "SUPERSEDED", (
            "the prior ACTIVE CORN schedule must move to SUPERSEDED"
        )

        _, meta = validate_paginated(api.list_discount_schedules(
            ADMIN, params={"commodity_code": "CORN", "status": "ACTIVE"}
        ))
        assert meta["total_count"] == 1, (
            "exactly one ACTIVE schedule may exist per commodity"
        )


class TestRiskLimitPublication:

    def test_stale_expected_desk_version_is_refused_with_precondition_failed(self, api):
        """PRD §2.7: "Its request body must carry `expected_desk_version` — a
        required field, never optional — holding the `version` of the target
        `TradingDesk` as the client last observed it. If that value does not equal
        the desk's current `version`, the request is rejected with
        `ERR_STALE_DESK_VERSION` (HTTP 412)."
        PRD §2.7: "A successful create increments the desk's `version` by 1, which
        by construction invalidates every other client's stale expectation."

        Design: Corner/cross_cutting_layers/risk_limit_create_with_stale_desk_version_returns_412
        """
        desk = new_desk(desk_code="CD51", name="Corner Desk 51")
        observed_version = desk["version"]

        first = new_risk_limit(
            desk["id"], expected_desk_version=observed_version,
            commodity_code="CORN", max_unpriced_bushels=100000, max_net_short_lots=40,
        )

        stale = create_risk_limit_payload(
            desk["id"], observed_version, commodity_code="CORN",
            max_unpriced_bushels=200000, max_net_short_lots=60,
        )
        validate_error(
            api.create_risk_limit(stale, RISK),
            ApiErrorId.ERR_STALE_DESK_VERSION.value, 412,
        )

        survivor = read_risk_limit(first["id"])
        assert survivor["status"] == "ACTIVE"
        assert survivor["max_unpriced_bushels"] == 100000, (
            "the stale write must not have retired or replaced the standing limit"
        )
        _, meta = validate_paginated(
            api.list_risk_limits(RISK, params={"desk_id": desk["id"]})
        )
        assert meta["total_count"] == 1

    def test_publishing_a_new_limit_supersedes_the_prior_active_one(self, api):
        """PRD §3.1: "Publication moves any prior limit for the same desk and
        commodity from `ACTIVE` to `SUPERSEDED`, leaves the incoming row as the
        single `ACTIVE` limit for that pairing, and increments the desk's `version`
        by one."

        Design: Corner/cross_cutting_layers/new_risk_limit_supersedes_the_prior_active_limit
        """
        desk = new_desk(desk_code="CD53", name="Corner Desk 53")
        first = new_risk_limit(
            desk["id"], expected_desk_version=desk["version"], commodity_code="CORN",
            max_unpriced_bushels=100000, max_net_short_lots=40,
        )

        refreshed_version = read_desk(desk["id"])["version"]
        payload = create_risk_limit_payload(
            desk["id"], refreshed_version, commodity_code="CORN",
            max_unpriced_bushels=250000, max_net_short_lots=80,
        )
        second = validate_success(api.create_risk_limit(payload, RISK), 201)

        assert second["status"] == "ACTIVE"
        assert read_risk_limit(first["id"])["status"] == "SUPERSEDED"

        _, meta = validate_paginated(api.list_risk_limits(
            RISK, params={"desk_id": desk["id"], "status": "ACTIVE"}
        ))
        assert meta["total_count"] == 1

        assert read_desk(desk["id"])["version"] > refreshed_version, (
            "a successful publication increments the desk's version by one"
        )
