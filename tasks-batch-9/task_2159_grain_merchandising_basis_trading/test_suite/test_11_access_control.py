"""Segregation of duties across the six desk roles, and the authentication
check that precedes every authorisation decision."""

import pytest

from test_helpers import (
    CLEAN_LOAD,
    NO_AUTH_HEADERS,
    TEST_WEIGHT_TIERS,
    ApiErrorId,
    create_hedge_position_payload,
    create_trading_desk_payload,
    new_desk,
    read_contract,
    read_desk,
    read_ticket,
    setup_contract_scenario,
    setup_graded_ticket_scenario,
    validate_error,
    validate_paginated,
)
from test_helpers.test_users import TEST_USERS


ADMIN = TEST_USERS["desk_admin_headers"]
MERCH = TEST_USERS["merchandiser_headers"]
INSPECTOR = TEST_USERS["grain_inspector_headers"]


class TestRoleExclusivity:

    def test_a_merchandiser_cannot_open_a_hedge_position(self, api):
        """PRD §2.1: "A `Merchandiser` posts bids, strikes and rolls purchase
        contracts, and applies graded loads to contracts — but it may not cancel a
        contract it created itself, and it has no access to the futures book."
        PRD §2.1: "A `FuturesTrader` owns the board: opening positions, adding lots,
        marking them to market and liquidating them."
        PRD §2.8: "The acting role appears on the endpoint's authorised list —
        otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

        Design: Corner/rbac/merchandiser_cannot_open_a_hedge_position_returns_unauthorized
        """
        desk = new_desk(desk_code="CD46", name="Corner Desk 46")

        payload = create_hedge_position_payload(
            desk["id"], commodity_code="CORN", futures_month="2026-12",
            side="SHORT", lots_open=4, avg_entry_price_cents=448,
        )
        validate_error(api.create_hedge_position(payload, MERCH),
                       ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        _, meta = validate_paginated(api.list_hedge_positions(
            MERCH, params={"desk_id": desk["id"]}
        ))
        assert meta["total_count"] == 0
        assert read_desk(desk["id"])["margin_requirement_usd"] == pytest.approx(
            0, abs=0.01
        )

    def test_a_grain_inspector_cannot_apply_the_ticket_it_graded(self, api):
        """PRD §2.1: "A `GrainInspector` grades inbound loads and disposes of them
        by rejection or by reversal, but never applies a graded ticket to a
        contract: application is the `Merchandiser`'s act."
        PRD §3.8: "A graded ticket sits in limbo until someone decides what to do
        with it, and the three dispositions belong to two different roles.
        Application — the act that actually credits the contract — is the
        `Merchandiser`'s. Rejection and reversal are the `GrainInspector`'s."

        Design: Corner/rbac/grain_inspector_cannot_apply_a_ticket_returns_unauthorized
        """
        scenario = setup_graded_ticket_scenario(
            desk_code="CD47", desk_name="Corner Desk 47", lots_open=10,
            schedule_tiers=TEST_WEIGHT_TIERS,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
            ticket_overrides={"gross_bushels": 5000, **CLEAN_LOAD},
        )

        validate_error(api.apply_delivery_ticket(scenario["ticket"]["id"], INSPECTOR),
                       ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        assert read_ticket(scenario["ticket"]["id"])["status"] == "GRADED"
        assert read_contract(scenario["contract"]["id"])[
            "delivered_bushels"] == pytest.approx(0.00, abs=0.01)

    def test_a_desk_admin_cannot_cancel_a_purchase_contract(self, api):
        """PRD §2.1: "A `DeskAdmin` is a reference-data operator: it stands up
        trading desks, registers country elevators, drafts and activates quality
        discount schedules, and drives the server's logical clock. It never touches
        a bid, a contract, a hedge position or a delivery ticket."
        PRD §2.1: "A `RiskOfficer` polices exposure it cannot itself create — it
        publishes risk limits, wires variation margin to cure open calls, and
        terminates contracts by cancellation or by declaring default — but it may
        not post a bid, strike a contract or open a hedge."

        Design: Corner/rbac/desk_admin_cannot_cancel_a_contract_returns_unauthorized
        """
        scenario = setup_contract_scenario(
            desk_code="CD48", desk_name="Corner Desk 48", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
        )

        validate_error(api.cancel_purchase_contract(
            scenario["contract"]["id"],
            {"damages_method": "MARKET_LOSS",
             "cancellation_reason": "admin override attempt"},
            ADMIN,
        ), ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        contract = read_contract(scenario["contract"]["id"])
        assert contract["status"] == "ACTIVE"
        assert contract["damages_usd"] == pytest.approx(0, abs=0.01)


class TestAuthenticationPrecedesAuthorization:

    def test_a_request_with_no_role_header_is_unauthenticated(self, api):
        """PRD §2.1: "Every request to this API carries two headers: `X-User-ID`,
        identifying the operator making the call, and `X-User-Role`, naming the
        capacity in which they act. If either header is absent, or if `X-User-Role`
        is not one of the six roles enumerated below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are well-formed but the
        named role is not authorised for the operation being attempted, the
        rejection is `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.8: "Both headers present and `X-User-Role` one of the six declared
        roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
        """
        new_desk(desk_code="CD49", name="Corner Desk 49", credit_line_usd=250000.00)

        payload = create_trading_desk_payload(
            desk_code="CD50", name="Corner Desk 50", credit_line_usd=250000.00
        )
        resp = api.raw_post("/grain/trading-desks", payload, NO_AUTH_HEADERS)
        assert "X-User-Role" not in NO_AUTH_HEADERS
        assert "X-User-ID" not in NO_AUTH_HEADERS

        error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value

        _, meta = validate_paginated(api.list_trading_desks(ADMIN))
        assert meta["total_count"] == 1, (
            "the unauthenticated create must not have persisted a second desk"
        )
