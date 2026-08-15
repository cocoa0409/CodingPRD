"""Onboarding entities: pagination envelope, referential existence, settlement
gates on customer/account close, dormant reactivation, unfreeze gating, and
beneficiary retirement gating."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_account,
    assert_customer,
    create_customer,
    create_wire,
    confirm_fraud_hold,
    create_approved_wire,
    place_fraud_hold,
    setup_wire_room,
    submit_wire,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["wire_ops_admin_headers"]
OPERATOR = TEST_USERS["wire_operator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestCustomerListingPagination:
    def test_list_customers_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, accepts a minimum of 1 and a maximum of 100. The
        `offset` parameter specifies how many items to skip and defaults to 0."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns
        resources sorted by creation timestamp in ascending order."

        Two customers exist; paging with limit=1 returns one per page with
        total_count == 2 and has_more flipping from true to false.

        Design: Corner/entities/list_customers_pagination_envelope
        """
        first = create_customer(legal_name="Page One", risk_rating="LOW")
        second = create_customer(
            legal_name="Page Two", risk_rating="HIGH", high_risk_jurisdiction=True)

        resp1 = api.list_customers(AUDITOR, params={"limit": 1, "offset": 0})
        page1, meta1 = validate_paginated(resp1)
        assert resp1.json()["response_type"] == "array"
        assert isinstance(resp1.json()["meta"]["api_request_id"], str)
        assert isinstance(resp1.json()["meta"]["api_request_timestamp"], str)
        assert len(page1) == 1, f"page 1 must carry exactly 1 customer, got {len(page1)}"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        assert page1[0]["id"] == first["id"], "creation order ascending"

        page2, meta2 = validate_paginated(
            api.list_customers(AUDITOR, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1, f"page 2 must carry exactly 1 customer, got {len(page2)}"
        assert page2[0]["id"] == second["id"]
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False


class TestBeneficiaryReferentialExistence:
    def test_beneficiary_with_unknown_customer_returns_not_found(self, api):
        """PRD §2.8: "(3) existence of every path identifier, validated
        left-to-right, and of every body-supplied foreign reference such as
        `ordering_account_id`, `beneficiary_id`, `wire_id`, or
        `investigation_id` — `ERR_NOT_FOUND`"

        A beneficiary registered against a non-existent customer_id is
        rejected with ERR_NOT_FOUND (404).

        Design: Corner/entities/beneficiary_with_unknown_customer_returns_not_found
        """
        resp = api.create_beneficiary(
            {
                "customer_id": NON_EXISTENT_UUID,
                "name": "Ghost Ben",
                "bank_name": "GhostBank",
                "account_number": "B-G001",
                "country_code": "US",
            },
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAccountSettlementGate:
    def test_account_close_blocked_by_open_wire(self, api):
        """PRD §3.1: "Closing an account requires `ACTIVE` status, requires
        that no non-terminal wire reference the account, and requires
        `daily_reserved_cents` to be zero; violations are
        `ERR_ACCOUNT_NOT_SETTLED`."

        A PENDING_APPROVAL wire blocks the close; cancelling it settles the
        account and the retry succeeds.

        Design: Corner/state_machines/account_close_blocked_by_open_wire
        """
        room = setup_wire_room(business_date="2026-09-10")
        account = room["account"]
        wire = create_wire(account["id"], room["beneficiary"]["id"], 100000)
        submit_wire(wire["id"], "2026-09-10")

        resp = api_client.close_account(account["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_SETTLED)

        validate_success(api_client.cancel_wire(wire["id"], OPERATOR), 200)
        closed = validate_success(api_client.close_account(account["id"], ADMIN), 200)
        assert_account(closed)
        assert closed["status"] == "CLOSED"


class TestCustomerSettlementGate:
    def test_customer_close_blocked_by_open_wire(self, api):
        """PRD §3.1: "Closing a customer requires `ACTIVE` status and requires
        that no wire in a non-terminal processing status exist on any of the
        customer's accounts; the rejection code is `ERR_CUSTOMER_NOT_SETTLED`."

        A PENDING_APPROVAL wire blocks the close; rejecting it settles the
        customer and the retry succeeds.

        Design: Corner/state_machines/customer_close_blocked_by_open_wire
        """
        room = setup_wire_room(business_date="2026-09-11")
        customer = room["customer"]
        wire = create_wire(
            room["account"]["id"], room["beneficiary"]["id"], 100000)
        submit_wire(wire["id"], "2026-09-11")

        resp = api_client.close_customer(customer["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_SETTLED)

        validate_success(api_client.reject_wire(
            wire["id"], {"reason": "settle"}, TEST_USERS["wire_approver_headers"]), 200)
        closed = validate_success(api_client.close_customer(customer["id"], ADMIN), 200)
        assert_customer(closed)
        assert closed["status"] == "CLOSED"


class TestDormantAccountReactivation:
    def test_dormant_account_reactivates_on_execution(self, api):
        """PRD §3.1: "a dormant account reactivates to `ACTIVE` automatically
        the first time one of its wires reaches `EXECUTED`."
        PRD §3.5: "On success the wire reaches `EXECUTED`: `executed_at` is
        stamped, the reservation converts into the released tally, a `DORMANT`
        ordering account reactivates to `ACTIVE`"

        The account goes DORMANT with the wire in flight (APPROVED); the
        release executes and flips the account back to ACTIVE.

        Design: Corner/state_machines/dormant_account_reactivates_on_execution
        """
        room = setup_wire_room(business_date="2026-09-07")
        account = room["account"]
        wire = create_approved_wire(
            account["id"], room["beneficiary"]["id"], "2026-09-07", 100000)

        dormant = validate_success(
            api_client.mark_account_dormant(account["id"], ADMIN), 200)
        assert dormant["status"] == "DORMANT"

        released = validate_success(api_client.release_wire(
            wire["id"], {"expected_wire_version": wire["version"]}, OPERATOR), 200)
        assert released["status"] == "EXECUTED"

        account_after = validate_success(api_client.get_account(account["id"], ADMIN), 200)
        assert_account(account_after)
        assert account_after["status"] == "ACTIVE", (
            f"DORMANT account must reactivate on execution, got {account_after['status']}")


class TestUnfreezeGatedByOpenFraudHold:
    def test_unfreeze_blocked_by_open_fraud_hold(self, api):
        """PRD §3.1: "Unfreezing requires the customer to be `FROZEN` and
        requires that no `OPEN` fraud hold remain on any wire ordered by any
        account of the customer — otherwise the request is rejected with
        `ERR_CUSTOMER_STILL_FROZEN`."

        Unfreeze fails while the hold is OPEN; after a LEGITIMATE customer
        confirmation clears the hold, the same unfreeze succeeds.

        Design: Corner/validations/unfreeze_blocked_by_open_fraud_hold
        """
        room = setup_wire_room(business_date="2026-09-18")
        customer = room["customer"]
        wire = create_approved_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-09-18", 100000)
        hold = place_fraud_hold(wire["id"], reason_code="MULE_SUSPECT",
                                note="mule pattern")
        validate_success(api_client.freeze_customer(customer["id"], ADMIN), 200)

        resp = api_client.unfreeze_customer(customer["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_STILL_FROZEN)

        cleared = confirm_fraud_hold(hold["id"], confirmation="LEGITIMATE")
        assert cleared["status"] == "CLEARED"

        unfrozen = validate_success(api_client.unfreeze_customer(customer["id"], ADMIN), 200)
        assert_customer(unfrozen)
        assert unfrozen["status"] == "ACTIVE"
        assert unfrozen["frozen_at"] is None


class TestBeneficiaryRetireGate:
    def test_beneficiary_retire_rejected_while_wire_pending(self, api):
        """PRD §3.1: "Retiring a beneficiary moves it from `ACTIVE` to its
        terminal `RETIRED` status; it requires `ACTIVE` status and that no
        wire in a non-terminal status reference it, else
        `ERR_BENEFICIARY_IN_USE`."

        Retire is rejected while a PENDING_APPROVAL wire references the
        beneficiary; once the wire is CANCELLED (terminal), the same retire
        succeeds.

        Design: Difficulty/cross_entity_state_dependency/beneficiary_retire_gated_by_open_wire
        """
        room = setup_wire_room(business_date="2026-08-17")
        beneficiary = room["beneficiary"]
        wire = create_wire(room["account"]["id"], beneficiary["id"], 200000)
        submit_wire(wire["id"], "2026-08-17")

        resp = api_client.retire_beneficiary(beneficiary["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_BENEFICIARY_IN_USE)

        validate_success(api_client.cancel_wire(wire["id"], OPERATOR), 200)
        retired = validate_success(
            api_client.retire_beneficiary(beneficiary["id"], OPERATOR), 200)
        assert retired["status"] == "RETIRED"

    def test_beneficiary_retire_blocked_from_initiated_until_terminal(self, api):
        """PRD §3.1: "Retiring a beneficiary moves it from `ACTIVE` to its
        terminal `RETIRED` status; it requires `ACTIVE` status and that no
        wire in a non-terminal status reference it, else
        `ERR_BENEFICIARY_IN_USE`."

        The gate holds for every non-terminal wire state: an INITIATED wire
        blocks the retire, a PENDING_APPROVAL wire still blocks it, and only
        the terminal REJECTED (after rejection) lets the retire through.

        Design: Difficulty/cross_entity_state_dependency/beneficiary_retire_gated_by_open_wire
        """
        room = setup_wire_room(business_date="2026-08-17")
        beneficiary = room["beneficiary"]
        wire = create_wire(room["account"]["id"], beneficiary["id"], 200000)

        resp_init = api_client.retire_beneficiary(beneficiary["id"], OPERATOR)
        validate_error(resp_init, ApiErrorId.ERR_BENEFICIARY_IN_USE)

        submit_wire(wire["id"], "2026-08-17")
        resp_pending = api_client.retire_beneficiary(beneficiary["id"], OPERATOR)
        validate_error(resp_pending, ApiErrorId.ERR_BENEFICIARY_IN_USE)

        validate_success(api_client.reject_wire(
            wire["id"], {"reason": "not needed"},
            TEST_USERS["wire_approver_headers"]), 200)
        retired = validate_success(
            api_client.retire_beneficiary(beneficiary["id"], OPERATOR), 200)
        assert retired["status"] == "RETIRED"
