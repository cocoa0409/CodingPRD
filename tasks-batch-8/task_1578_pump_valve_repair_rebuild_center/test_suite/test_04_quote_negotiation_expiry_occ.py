"""Quote negotiation: revision fork side effects, OCC on quote creation,
lazy expiry boundaries, and the credit-limit gate."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_ro_in_quote_in_progress,
    api_client,
    assert_instant_equals,
    assert_quote,
    create_customer,
    create_part,
    create_quote_for_ro,
    create_quote_payload,
    get_quote,
    get_repair_order,
    get_success_data,
    get_window,
    issue_quote,
    issue_quote_for,
    make_customer_headers,
    set_clock,
    setup_issued_quote_shop,
    setup_quote_in_progress_shop,
    validate_error,
    validate_paginated,
    validate_success,
)

SM = TEST_USERS["service_manager_headers"]


class TestNegotiationFork:
    def test_revision_approve_and_decline_branches_diverge(self, api):
        """PRD §3.5: "the first quote is `revision` 1 with `supersedes_quote_id` null, and each subsequent creation increments the counter, marks every prior non-terminal quote for that order — any quote in `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` — as `SUPERSEDED`, and points `supersedes_quote_id` at the immediately prior non-terminal revision."
        PRD §3.6: "An approved quote cascades in three links: the repair order moves `QUOTE_IN_PROGRESS` → `AUTHORIZED`; the quote's `capacity_window_id` is copied onto the order; and the order's `estimated_bay_hours` are added to the window's `bay_hours_reserved`, recomputing `window_posture`, which may flip `NORMAL` → `SURGE` or `SURGE` → `FULL`."
        PRD §3.6: "Declining moves it `ISSUED` → `DECLINED` and cascades the repair order `QUOTE_IN_PROGRESS` → `CANCELLED`, carrying the cancellation's own side effects — notably the release of any pool reservation (§3.9)."

        Design: Difficulty/non_linear_state_machine/quote_negotiation_fork_divergent_side_effects
        """
        shop = setup_quote_in_progress_shop(ro_over={"estimated_bay_hours": 40})
        cust_headers = make_customer_headers(shop["customer"]["id"])

        # Revision branch: q1 ISSUED -> REVISION_REQUESTED, then q2 supersedes it.
        q1 = issue_quote_for(shop, quote_over={"labor_hours": 4})
        revised = get_success_data(api_client.request_quote_revision(q1["id"], cust_headers))
        assert revised["status"] == "REVISION_REQUESTED"
        q2 = create_quote_for_ro(shop["ro"]["id"], shop["window"]["id"], labor_hours=3)
        assert q2["revision"] == 2
        assert q2["supersedes_quote_id"] == q1["id"]
        assert get_quote(q1["id"])["status"] == "SUPERSEDED"
        q2 = issue_quote(q2["id"])

        # Decline branch on a second order: q3 ISSUED -> DECLINED.
        ro2 = add_ro_in_quote_in_progress(shop, ro_over={"estimated_bay_hours": 30})
        q3 = create_quote_for_ro(ro2["id"], shop["window"]["id"], labor_hours=3)
        q3 = issue_quote(q3["id"])

        # Approve the revision winner; decline the other order's quote.
        approved = get_success_data(api_client.approve_quote(q2["id"], cust_headers))
        assert approved["status"] == "APPROVED"
        ro1_after = get_repair_order(shop["ro"]["id"])
        assert ro1_after["status"] == "AUTHORIZED"
        assert ro1_after["capacity_window_id"] == shop["window"]["id"]

        declined = get_success_data(api_client.decline_quote(q3["id"], cust_headers))
        assert declined["status"] == "DECLINED"
        assert get_repair_order(ro2["id"])["status"] == "CANCELLED"

        window = get_window(shop["window"]["id"])
        assert window["bay_hours_reserved"] == 40, (
            "only the approved branch reserved hours; the declined branch reserved nothing"
        )

    def test_draft_quote_superseded_and_revision_request_has_no_effects(self, api):
        """PRD §3.5: "the first quote is `revision` 1 with `supersedes_quote_id` null, and each subsequent creation increments the counter, marks every prior non-terminal quote for that order — any quote in `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` — as `SUPERSEDED`, and points `supersedes_quote_id` at the immediately prior non-terminal revision."
        PRD §3.6: "Requesting a revision moves the quote `ISSUED` → `REVISION_REQUESTED` with no further effects."

        Design: Difficulty/non_linear_state_machine/quote_negotiation_fork_divergent_side_effects
        """
        shop = setup_quote_in_progress_shop()
        cust_headers = make_customer_headers(shop["customer"]["id"])

        # q1 never leaves DRAFT before q2 is composed: DRAFT -> SUPERSEDED.
        q1 = create_quote_for_ro(shop["ro"]["id"], shop["window"]["id"], labor_hours=1)
        assert q1["revision"] == 1 and q1["supersedes_quote_id"] is None
        ro_version_after_q1 = get_repair_order(shop["ro"]["id"])["version"]
        q2 = create_quote_for_ro(shop["ro"]["id"], shop["window"]["id"], labor_hours=2)
        assert q2["revision"] == 2
        assert q2["supersedes_quote_id"] == q1["id"]
        assert get_quote(q1["id"])["status"] == "SUPERSEDED"

        # ISSUED -> REVISION_REQUESTED has no further effects: the order does not
        # move and the window reserves nothing.
        q2 = issue_quote(q2["id"])
        ro_version_before = get_repair_order(shop["ro"]["id"])["version"]
        revised = get_success_data(api_client.request_quote_revision(q2["id"], cust_headers))
        assert revised["status"] == "REVISION_REQUESTED"
        ro_after = get_repair_order(shop["ro"]["id"])
        assert ro_after["status"] == "QUOTE_IN_PROGRESS"
        assert ro_after["version"] == ro_version_before, "no further effects on the order"
        assert get_window(shop["window"]["id"])["bay_hours_reserved"] == 0
        assert ro_version_after_q1 + 1 == ro_version_before, (
            "only the second quote creation advanced the order's version"
        )


class TestOptimisticConcurrency:
    def test_stale_version_rejected_then_refetched_retry_supersedes(self, api):
        """PRD §2.7: "If that value does not match the repair order's current `version` — most commonly because a prior successful quote creation legitimately superseded the client's base revision and advanced the order's version — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no quote is created."
        PRD §3.5: "Creating a quote increments the repair order's `version` by one, which is precisely what invalidates a stale `expected_repair_order_version` on the next attempt."
        PRD §3.5: "the first quote is `revision` 1 with `supersedes_quote_id` null, and each subsequent creation increments the counter, marks every prior non-terminal quote for that order — any quote in `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` — as `SUPERSEDED`, and points `supersedes_quote_id` at the immediately prior non-terminal revision."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_quote_create_supersede
        """
        shop = setup_quote_in_progress_shop()
        stale_version = shop["ro"]["version"]

        q1 = create_quote_for_ro(shop["ro"]["id"], shop["window"]["id"],
                                 expected_version=stale_version, labor_hours=1)
        assert_quote(q1)
        assert q1["revision"] == 1
        bumped = get_repair_order(shop["ro"]["id"])
        assert bumped["version"] == stale_version + 1, "creation mutates the order"

        # Replay with the pre-creation version: stale.
        stale_retry = api_client.create_quote(
            create_quote_payload(shop["ro"]["id"], shop["window"]["id"],
                                 stale_version, labor_hours=2),
            SM)
        validate_error(stale_retry, ApiErrorId.ERR_STALE_VERSION)
        data, meta = validate_paginated(api_client.list_quotes(
            SM, params={"repair_order_id": shop["ro"]["id"]}))
        assert meta["total_count"] == 1, "no quote is created on a stale write"

        # Refetch and retry: succeeds and supersedes the first revision.
        fresh_version = get_repair_order(shop["ro"]["id"])["version"]
        q2 = validate_success(api_client.create_quote(
            create_quote_payload(shop["ro"]["id"], shop["window"]["id"],
                                 fresh_version, labor_hours=2),
            SM), 201)
        assert q2["revision"] == 2
        assert q2["supersedes_quote_id"] == q1["id"]
        assert get_quote(q1["id"])["status"] == "SUPERSEDED"


class TestLazyExpiry:
    def test_approve_expired_and_over_credit_quote_surfaces_expiry(self, api):
        """PRD §3.6: "Approval evaluates its gates in validation-priority order — the lazy-expiry check first, then the window-capacity and pool-unit constraints, and the credit check last, so an over-credit quote on an over-capacity window surfaces the capacity error."
        PRD §3.6: "Once `ISSUED`, the quote belongs to the customer to answer, and time works against it: any read or action on an `ISSUED` quote when the logical clock has reached or passed `expires_at` first transitions the quote to `EXPIRED`, and the requested action is rejected with `ERR_QUOTE_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/quote_approve_expiry_vs_credit_priority_conflict
        """
        # Credit limit 1000 with a quote total of 80000 (4h @ 20000, no parts).
        shop = setup_issued_quote_shop(
            customer_over={"credit_limit_cents": 1000},
            quote_over={"labor_hours": 4, "labor_rate_cents": 20000})
        assert shop["quote"]["total_cents"] == 80000

        # Advance past expiry (issued at the 2026-08-01 default, valid 14 days).
        set_clock("2026-08-20T00:00:00Z")

        resp = api_client.approve_quote(
            shop["quote"]["id"], make_customer_headers(shop["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)
        assert get_quote(shop["quote"]["id"])["status"] == "EXPIRED"
        assert get_repair_order(shop["ro"]["id"])["status"] == "QUOTE_IN_PROGRESS"

    def test_all_customer_answers_rejected_after_expiry(self, api):
        """PRD §3.6: "Once `ISSUED`, the quote belongs to the customer to answer, and time works against it: any read or action on an `ISSUED` quote when the logical clock has reached or passed `expires_at` first transitions the quote to `EXPIRED`, and the requested action is rejected with `ERR_QUOTE_EXPIRED`."
        PRD §3.6: "Both customer answers are subject to the same lazy expiry as approval."

        Design: Difficulty/priority_pair_validation_conflict/quote_approve_expiry_vs_credit_priority_conflict
        """
        shop = setup_issued_quote_shop()
        cust = make_customer_headers(shop["customer"]["id"])
        # Three more issued quotes on three more orders of the same customer.
        quotes = [shop["quote"]]
        for _ in range(3):
            ro = add_ro_in_quote_in_progress(shop)
            quotes.append(issue_quote_for(shop, ro=ro))

        set_clock("2026-08-20T00:00:00Z")

        validate_error(api_client.approve_quote(quotes[0]["id"], cust),
                       ApiErrorId.ERR_QUOTE_EXPIRED)
        validate_error(api_client.approve_quote(quotes[1]["id"], cust),
                       ApiErrorId.ERR_QUOTE_EXPIRED)
        validate_error(api_client.request_quote_revision(quotes[2]["id"], cust),
                       ApiErrorId.ERR_QUOTE_EXPIRED)
        validate_error(api_client.decline_quote(quotes[3]["id"], cust),
                       ApiErrorId.ERR_QUOTE_EXPIRED)
        for q in quotes:
            assert get_quote(q["id"])["status"] == "EXPIRED"

    def test_expiry_boundary_at_exact_second(self, api):
        """PRD §3.6: "Once `ISSUED`, the quote belongs to the customer to answer, and time works against it: any read or action on an `ISSUED` quote when the logical clock has reached or passed `expires_at` first transitions the quote to `EXPIRED`, and the requested action is rejected with `ERR_QUOTE_EXPIRED`."

        Design: Corner/validations/quote_expiry_boundary_exact_second
        """
        shop1 = setup_issued_quote_shop()
        shop2 = setup_issued_quote_shop()
        # Both quotes issued at the default 2026-08-01T00:00:00Z, so
        # expires_at lands on the 2026-08-15T00:00:00Z instant for each.
        assert_instant_equals(shop1["quote"]["expires_at"], "2026-08-15T00:00:00Z")
        assert_instant_equals(shop2["quote"]["expires_at"], "2026-08-15T00:00:00Z")

        # One second before expiry: approval succeeds.
        set_clock("2026-08-14T23:59:59Z")
        ok = get_success_data(api_client.approve_quote(
            shop1["quote"]["id"], make_customer_headers(shop1["customer"]["id"])))
        assert ok["status"] == "APPROVED"

        # At exactly expires_at: reached-or-passed is inclusive — expired.
        set_clock("2026-08-15T00:00:00Z")
        resp = api_client.approve_quote(
            shop2["quote"]["id"], make_customer_headers(shop2["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)
        assert get_quote(shop2["quote"]["id"])["status"] == "EXPIRED"

    def test_approve_after_lazy_expiry_read_returns_invalid_state(self, api):
        """PRD §3.6: "Once `ISSUED`, the quote belongs to the customer to answer, and time works against it: any read or action on an `ISSUED` quote when the logical clock has reached or passed `expires_at` first transitions the quote to `EXPIRED`, and the requested action is rejected with `ERR_QUOTE_EXPIRED`."
        PRD §3.5: "A quote's full status vocabulary is `DRAFT`, `ISSUED`, `REVISION_REQUESTED`, `APPROVED`, `DECLINED`, `EXPIRED`, `SUPERSEDED`, and `CANCELLED`, the last five terminal."
        PRD §2.6: "5. **State validity** — the target entity must be in a valid from-state for the requested transition, terminal states are locked, and the quote-creation version check must match (`ERR_INVALID_STATE`, HTTP 409; the version mismatch carries `ERR_STALE_VERSION`, HTTP 412, on quote creation)."

        Design: Corner/state_machines/approve_expired_quote_terminal_lockdown
        """
        shop = setup_issued_quote_shop()
        set_clock("2026-08-20T00:00:00Z")

        # A read applies lazy expiry. The first read races the transition; the
        # second read observes the settled (terminal) EXPIRED state.
        api_client.get_quote(shop["quote"]["id"], SM)
        settled = get_quote(shop["quote"]["id"])
        assert settled["status"] == "EXPIRED", "lazy expiry transitioned the quote"

        # Approve on an EXPIRED quote is a from-state error, not an expiry error.
        resp = api_client.approve_quote(
            shop["quote"]["id"], make_customer_headers(shop["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_nonexistent_quote_returns_not_found(self, api):
        """PRD §2.6: "4. **Existence** — path-referenced and body-referenced resources must exist, validated left to right (`ERR_NOT_FOUND`, HTTP 404)."

        Design: Corner/validations/approve_nonexistent_quote_returns_not_found
        """
        customer = create_customer(name="Abilene", account_number="AB-350",
                                   credit_limit_cents=99999999, warranty_terms_days=365)
        resp = api_client.approve_quote(NON_EXISTENT_UUID,
                                        make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCreditLimitGate:
    def test_credit_limit_equality_allowed_one_cent_over_rejected(self, api):
        """PRD §3.6: "Finally, `total_cents` must not exceed the customer's `credit_limit_cents` — equality is allowed — else approval is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/quote_approve_credit_limit_equality_boundary
        """
        lines_part1 = create_part(part_number="IMPELLER-9", description="Impeller",
                                  unit_price_cents=15000)
        lines_part2 = create_part(part_number="SEAL-9", description="Seal",
                                  unit_price_cents=7500)
        lines = [
            {"part_id": lines_part1["id"], "quantity": 2, "unit_price_cents": 15000},
            {"part_id": lines_part2["id"], "quantity": 1, "unit_price_cents": 7500},
        ]
        quote_over = {"labor_hours": 4, "labor_rate_cents": 20000, "part_lines": lines}

        # Customer 1: credit exactly equals the total (117500).
        shop1 = setup_issued_quote_shop(
            customer_over={"credit_limit_cents": 117500}, quote_over=quote_over)
        assert shop1["quote"]["total_cents"] == 117500
        approved = get_success_data(api_client.approve_quote(
            shop1["quote"]["id"], make_customer_headers(shop1["customer"]["id"])))
        assert approved["status"] == "APPROVED"
        assert get_repair_order(shop1["ro"]["id"])["status"] == "AUTHORIZED"

        # Customer 2: one cent short (117499).
        shop2 = setup_issued_quote_shop(
            customer_over={"credit_limit_cents": 117499}, quote_over=quote_over)
        assert shop2["quote"]["total_cents"] == 117500
        resp = api_client.approve_quote(
            shop2["quote"]["id"], make_customer_headers(shop2["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_quote(shop2["quote"]["id"])["status"] == "ISSUED"
        assert get_repair_order(shop2["ro"]["id"])["status"] == "QUOTE_IN_PROGRESS"

    def test_credit_boundary_on_labor_only_quote(self, api):
        """PRD §3.6: "Finally, `total_cents` must not exceed the customer's `credit_limit_cents` — equality is allowed — else approval is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/quote_approve_credit_limit_equality_boundary
        """
        # Labor-only total: 1h @ 1000 cents = 1000; window NORMAL keeps x1.00.
        shop_ok = setup_issued_quote_shop(
            customer_over={"credit_limit_cents": 1000},
            quote_over={"labor_hours": 1, "labor_rate_cents": 1000})
        assert shop_ok["quote"]["total_cents"] == 1000
        approved = get_success_data(api_client.approve_quote(
            shop_ok["quote"]["id"], make_customer_headers(shop_ok["customer"]["id"])))
        assert approved["status"] == "APPROVED"

        shop_short = setup_issued_quote_shop(
            customer_over={"credit_limit_cents": 999},
            quote_over={"labor_hours": 1, "labor_rate_cents": 1000})
        assert shop_short["quote"]["total_cents"] == 1000
        resp = api_client.approve_quote(
            shop_short["quote"]["id"],
            make_customer_headers(shop_short["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_quote(shop_short["quote"]["id"])["status"] == "ISSUED"
