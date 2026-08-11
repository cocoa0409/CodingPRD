"""Fair lifecycle: creation defaults, posture machine, settlement/closure
guards, response envelope, and basic existence errors (PRD §2.2, §2.5, §3.1).
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_posture,
    api_client,
    assert_fair,
    create_buyer,
    create_exhibitor,
    create_fair,
    create_verified_entry,
    generate_lots,
    get_buyer_invoice,
    get_fair,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    issue_invoice,
    post_payment,
    setup_sold_lot,
    standard_shown_entry,
    validate_error,
    weigh_entry,
)

ADMIN = TEST_USERS["admin"]


class TestFairCreation:
    def test_fair_created_with_defaults_and_setup_posture(self, api):
        """PRD §3.1: "A newly created fair starts in `posture` `SETUP` with
        `available_premium_pool_cents` equal to `premium_budget_cents` — the
        full purse is uncommitted."
        PRD §3.1: "the large-class configuration, where
        `large_class_min_entries` defaults to 8 and `large_class_bonus_rate`
        defaults to 0.10 when omitted."

        Design: Corner/entities/fair_created_with_defaults_and_setup_posture
        """
        fair = create_fair(name="Fair C1")
        assert_fair(fair)
        assert fair["posture"] == "SETUP", (
            f"new fair posture must be SETUP, got {fair['posture']}"
        )
        assert fair["available_premium_pool_cents"] == fair["premium_budget_cents"] == 100000
        assert fair["large_class_min_entries"] == 8
        assert fair["large_class_bonus_rate"] == 0.10
        fetched = get_fair(fair["id"])
        assert fetched["posture"] == "SETUP"
        assert fetched["available_premium_pool_cents"] == 100000

    def test_bidder_number_computed_in_created_at_order(self, api):
        """PRD §3.1: "the server assigns a `bidder_number` automatically — the
        letter B followed by a zero-padded three-digit sequence number, handed
        out per fair in `created_at` ascending order."

        Design: Corner/entities/bidder_number_computed_in_created_at_order
        """
        fair = create_fair(name="Fair C5")
        buyer_1 = create_buyer(fair["id"], business_name="Alpha Meats")
        buyer_2 = create_buyer(fair["id"], business_name="Beta Foods")
        assert buyer_1["bidder_number"] == "B-001"
        assert buyer_2["bidder_number"] == "B-002"


class TestResponseEnvelope:
    def test_response_envelope_success_and_error_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        fair = create_fair(name="Fair E1")
        resp = api_client.create_exhibitor(
            {"fair_id": fair["id"], "full_name": "Ann A", "organization": "FFA"},
            ADMIN,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert is_valid_uuid(body["data"]["id"])

        err_resp = api_client.get_exhibitor(NON_EXISTENT_UUID, ADMIN)
        assert err_resp.status_code == 404
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"]
        assert set(err_body["meta"].keys()) == {
            "api_request_id", "api_request_timestamp",
        }

    def test_get_nonexistent_exhibitor_returns_not_found(self, api):
        """PRD §2.7: "existence of every referenced resource, validated
        left-to-right along the path identifiers first and then the body
        foreign keys (failure: `ERR_NOT_FOUND`)".

        Design: Corner/entities/get_nonexistent_exhibitor_returns_not_found
        """
        resp = api_client.get_exhibitor(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestFairPostureMachine:
    def test_fair_advance_skipping_steps_returns_invalid_state(self, api):
        """PRD §2.5: "A `FairBoardAdmin` advances the posture by naming the
        desired next posture in `to_posture`; the advance is strictly one step
        — skipping a posture or naming an earlier one is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/fair_advance_skipping_steps_returns_invalid_state
        """
        fair = create_fair(name="Fair S1")
        resp = api_client.advance_posture(fair["id"], "WEIGH_IN", ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_fair(fair["id"])["posture"] == "SETUP"

    def test_fair_reopen_entries_cycle_then_blocked_after_weigh(self, api):
        """PRD §2.5: "The sole backward edge in the lifecycle is reopening
        entries, which moves `ENTRIES_LOCKED` → `ENTRIES_OPEN` and is permitted
        only while no weigh ticket in `ACTIVE` status exists for any entry of
        the fair; otherwise the reopen is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/fair_reopen_entries_cycle_then_blocked_after_weigh
        """
        fair = create_fair(name="Fair S2")
        advance_posture(fair["id"], "ENTRIES_OPEN")
        exhibitor = create_exhibitor(fair["id"])
        entry = create_verified_entry(fair["id"], exhibitor, tag_number="S-001")
        advance_posture(fair["id"], "ENTRIES_LOCKED")

        reopened = get_success_data(api_client.reopen_entries(fair["id"], ADMIN))
        assert reopened["posture"] == "ENTRIES_OPEN", (
            "first reopen (no ACTIVE weigh ticket) must succeed"
        )

        advance_posture(fair["id"], "ENTRIES_LOCKED")
        advance_posture(fair["id"], "WEIGH_IN")
        weigh_entry(entry["id"], 1200)

        resp = api_client.reopen_entries(fair["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_fair(fair["id"])["posture"] == "WEIGH_IN"

    def test_fair_settlement_blocked_with_open_lots(self, api):
        """PRD §2.5: "Advancing `AUCTION` → `SETTLEMENT` requires every auction
        lot of the fair to be in a terminal state — `SOLD` or `NO_SALE`."
        PRD §2.5: "A guard failure is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/fair_settlement_blocked_with_open_lots
        """
        ctx = standard_shown_entry(advance_to="AUCTION")
        fair_id = ctx["fair"]["id"]
        gen = generate_lots(fair_id)
        assert gen["lot_count"] == 1  # lot exists and is QUEUED

        resp = api_client.advance_posture(fair_id, "SETTLEMENT", ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_fair(fair_id)["posture"] == "AUCTION"

    def test_fair_close_blocked_until_invoices_paid(self, api):
        """PRD §2.5: "Advancing `SETTLEMENT` → `CLOSED` requires every invoice
        of the fair to be `PAID`, every premium award to be `PAID` or
        `FORFEITED`, and every disposition order to be `COMPLETED` or
        `REJECTED`. A guard failure is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/fair_close_blocked_until_invoices_paid
        """
        ctx = setup_sold_lot(hammer_price_cents=50000, advance_to_settlement=True)
        fair_id = ctx["fair"]["id"]
        invoice = get_buyer_invoice(ctx["buyer"]["id"])
        invoice = issue_invoice(invoice["id"])
        assert invoice["total_due_cents"] == 51500

        first = api_client.advance_posture(fair_id, "CLOSED", ADMIN)
        validate_error(first, ApiErrorId.ERR_INVALID_STATE)
        assert get_fair(fair_id)["posture"] == "SETTLEMENT"

        paid = post_payment(invoice["id"], 51500)
        assert paid["status"] == "PAID"

        # Premium award still ACCRUED and the auto-created HARVEST disposition
        # still REQUESTED, so the closure guard keeps failing.
        second = api_client.advance_posture(fair_id, "CLOSED", ADMIN)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)
        assert get_fair(fair_id)["posture"] == "SETTLEMENT"
