"""Catering orders: per-line rounding, F&B accrual, cutoff gate, lifecycle."""
from test_helpers import (
    ESM, FIN, REP,
    ApiClient, ApiErrorId, EVENT_E1,
    make_account_holder_headers, set_clock, setup_active_agreement,
    validate_error, validate_success,
)

GOLD_SUITE = dict(suite_code="G-101", tier="GOLD", capacity_seats=20,
                  base_annual_fee_cents=12000000, f_b_minimum_cents=4000000)

PINNED_LINES = [
    {"item_code": "APP", "description": "Sliders", "quantity": 2,
     "unit_price_cents": 1250, "discount_pct": 0.10},
    {"item_code": "PLT", "description": "Carving station", "quantity": 1,
     "unit_price_cents": 4750},
    {"item_code": "DES", "description": "Dessert bites", "quantity": 5,
     "unit_price_cents": 640, "discount_pct": 0.25},
]
# Per line: round_half_up(2250*0.90)=2025, 4750, round_half_up(3200*0.75)=2400 -> 9400.

TRAP_LINES = [
    {"item_code": "WNG", "description": "Wings", "quantity": 3,
     "unit_price_cents": 999, "discount_pct": 0.15},
    {"item_code": "WNG2", "description": "Wings encore", "quantity": 3,
     "unit_price_cents": 999, "discount_pct": 0.15},
]
# Per line: round_half_up(2997*0.85) = 2547 each -> 5094; sum-then-round would give 5095.


def _setup(events_spec=None, clock="2026-08-20T00:00:00Z", suite_over=None):
    s = setup_active_agreement(num_seasons=1, events_spec=events_spec or [EVENT_E1],
                               suite_over=suite_over or GOLD_SUITE)
    set_clock(clock)
    return s


def _place(api: ApiClient, s, lines, guest_count=12, package_tier="PREMIUM"):
    return api.create_catering_order(
        {"event_id": s["events"][0]["id"], "suite_id": s["suite"]["id"],
         "agreement_id": s["agreement"]["id"], "package_tier": package_tier,
         "guest_count": guest_count, "lines": lines},
        make_account_holder_headers(s["account"]["id"]))


class TestCateringPerLineRounding:
    def test_subtotal_is_sum_of_per_line_rounded_amounts(self, api: ApiClient):
        """PRD §3.6: "Each line's amount is its `quantity` times its `unit_price_cents`
        times one minus its `discount_pct`, rounded half-up to a whole cent per line;
        `subtotal_cents` is the sum of those already-rounded line amounts."
        Design: Difficulty/combinatorial_formula/catering_total_per_line_then_sum_rounding
        """
        s = _setup()
        order = validate_success(_place(api, s, TRAP_LINES, guest_count=6,
                                        package_tier="STANDARD"), expected_status=201)
        assert order["subtotal_cents"] == 5094, (
            f"per-line 2547+2547 expected; sum-then-round would give 5095; got "
            f"{order['subtotal_cents']}")

    def test_service_fee_and_total_follow_the_rounded_subtotal(self, api: ApiClient):
        """PRD §3.6: "The `service_fee_cents` is eighteen percent of the subtotal,
        rounded half-up, and `total_cents` is the subtotal plus the service fee."
        Design: Difficulty/combinatorial_formula/catering_total_per_line_then_sum_rounding
        """
        s = _setup()
        order = validate_success(_place(api, s, TRAP_LINES, guest_count=6,
                                        package_tier="STANDARD"), expected_status=201)
        assert order["service_fee_cents"] == 917, "round_half_up(5094 * 0.18) = 917"
        assert order["total_cents"] == 6011


class TestFBAccrualNetOfServiceFee:
    def test_order_totals_fixture(self, api: ApiClient):
        """PRD §3.6: "The `service_fee_cents` is eighteen percent of the subtotal,
        rounded half-up, and `total_cents` is the subtotal plus the service fee."
        Design: Difficulty/dual_variant_calc/f_b_accrual_net_excludes_service_fee
        """
        s = _setup()
        order = validate_success(_place(api, s, PINNED_LINES), expected_status=201)
        assert order["subtotal_cents"] == 9400
        assert order["service_fee_cents"] == 1692
        assert order["total_cents"] == 11092

    def test_confirmed_order_accrues_net_subtotal_only(self, api: ApiClient):
        """PRD §3.5: "The accrual is net of the service fee: each of the agreement's
        catering orders on the season's events contributes its `subtotal_cents` while
        `CONFIRMED` or `FULFILLED`". PRD §3.6: "Confirming an agreement-context order
        feeds the minimum: the agreement's `f_b_accrued_cents_current_season` grows by
        the order's net accrual — its subtotal".
        Design: Difficulty/dual_variant_calc/f_b_accrual_net_excludes_service_fee
        """
        s = _setup()
        order = validate_success(_place(api, s, PINNED_LINES), expected_status=201)
        validate_success(api.set_catering_order_status(
            order["id"], {"target_status": "CONFIRMED"}, ESM))
        agreement = validate_success(api.get_agreement(s["agreement"]["id"], REP))
        assert agreement["f_b_accrued_cents_current_season"] == 9400, (
            f"net variant accrues subtotal 9400, not gross total 11092; got "
            f"{agreement['f_b_accrued_cents_current_season']}")


class TestCateringCutoffBoundary:
    def test_order_at_exact_cutoff_instant_passes(self, api: ApiClient):
        """PRD §3.6: "the clock must be at or before the event's `starts_at` minus the
        effective cutoff ... with anything strictly later rejected as
        `ERR_CATERING_CUTOFF_PASSED` and a call exactly at the cutoff admitted."
        Design: Difficulty/boundary_precision_check/catering_cutoff_exact_instant_passes_then_fails
        """
        s = _setup(clock="2026-09-07T17:00:00Z")  # exactly starts_at - 72h
        order = validate_success(_place(api, s, [{"item_code": "APP",
                                                  "description": "Sliders",
                                                  "quantity": 1,
                                                  "unit_price_cents": 1000}],
                                        guest_count=8, package_tier="STANDARD"),
                                 expected_status=201)
        assert order["status"] == "PLACED"

    def test_order_one_second_after_cutoff_fails(self, api: ApiClient):
        """PRD §3.6: "the clock must be at or before the event's `starts_at` minus the
        effective cutoff ... with anything strictly later rejected as
        `ERR_CATERING_CUTOFF_PASSED` and a call exactly at the cutoff admitted."
        Design: Difficulty/boundary_precision_check/catering_cutoff_exact_instant_passes_then_fails
        """
        s = _setup(clock="2026-09-07T17:00:01Z")  # one second past the cutoff
        resp = _place(api, s, [{"item_code": "APP", "description": "Sliders",
                                "quantity": 1, "unit_price_cents": 1000}],
                      guest_count=8, package_tier="STANDARD")
        validate_error(resp, ApiErrorId.ERR_CATERING_CUTOFF_PASSED)


class TestBodyBeforeCutoffPriority:
    def test_bad_body_and_past_cutoff_returns_constraint_error(self, api: ApiClient):
        """PRD §2.8: "Incoming requests are validated against a fixed sequence of
        gates; an earlier failure masks all later checks." (body well-formedness is
        gate 6; the catering cutoff is gate 10.) PRD §3.6: "a `guest_count` that must
        be positive and no greater than the suite's `capacity_seats`".
        Design: Difficulty/priority_pair_validation_conflict/place_order_bad_body_past_cutoff_returns_constraint_error
        """
        s = _setup(clock="2026-09-08T00:00:00Z")  # past the 2026-09-07T17:00Z cutoff
        resp = _place(api, s, [{"item_code": "APP", "description": "Sliders",
                                "quantity": 1, "unit_price_cents": 1000}],
                      guest_count=25, package_tier="STANDARD")  # 25 > capacity 20
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_valid_body_past_cutoff_returns_cutoff_error(self, api: ApiClient):
        """PRD §3.6: "the clock must be at or before the event's `starts_at` minus the
        effective cutoff — the event's own `catering_cutoff_hours` when set, otherwise
        the venue's `default_catering_cutoff_hours` — with anything strictly later
        rejected as `ERR_CATERING_CUTOFF_PASSED`".
        Design: Difficulty/priority_pair_validation_conflict/place_order_bad_body_past_cutoff_returns_constraint_error
        """
        s = _setup(clock="2026-09-08T00:00:00Z")
        resp = _place(api, s, [{"item_code": "APP", "description": "Sliders",
                                "quantity": 1, "unit_price_cents": 1000}],
                      guest_count=8, package_tier="STANDARD")
        validate_error(resp, ApiErrorId.ERR_CATERING_CUTOFF_PASSED)


class TestCrossEntityGuards:
    def test_confirm_blocked_when_agreement_suspended(self, api: ApiClient):
        """PRD §2.8: "(iii) the linked agreement must be `ACTIVE` for agreement-context
        catering placement or confirmation, agreement-context credential issue, and
        transfer approval, else `ERR_AGREEMENT_NOT_ACTIVE`".
        Design: Difficulty/cross_entity_state_dependency/catering_confirm_blocked_when_agreement_suspended
        """
        s = _setup()
        order = validate_success(_place(api, s, [{"item_code": "APP",
                                                  "description": "Sliders",
                                                  "quantity": 1,
                                                  "unit_price_cents": 1000}],
                                        guest_count=8, package_tier="STANDARD"),
                                 expected_status=201)
        # Manual account suspension cascades: agreement -> SUSPENDED (ADMINISTRATIVE).
        validate_success(api.set_account_status(
            s["account"]["id"], {"target_status": "SUSPENDED"},
            FIN))
        resp = api.set_catering_order_status(order["id"], {"target_status": "CONFIRMED"}, ESM)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_suspended_agreement_confirm_leaves_order_placed(self, api: ApiClient):
        """PRD §3.6: "Confirmation — moving `PLACED` to `CONFIRMED`, reserved to
        `EventServicesManager` and `StadiumAdmin` — repeats the placement gates: the
        event must still be `SCHEDULED`, the clock must still be at or before the
        cutoff, and the agreement or rental context must still be valid."
        Design: Difficulty/cross_entity_state_dependency/catering_confirm_blocked_when_agreement_suspended
        """
        s = _setup()
        order = validate_success(_place(api, s, [{"item_code": "APP",
                                                  "description": "Sliders",
                                                  "quantity": 1,
                                                  "unit_price_cents": 1000}],
                                        guest_count=8, package_tier="STANDARD"),
                                 expected_status=201)
        validate_success(api.set_account_status(
            s["account"]["id"], {"target_status": "SUSPENDED"},
            FIN))
        api.set_catering_order_status(order["id"], {"target_status": "CONFIRMED"}, ESM)
        after = validate_success(api.get_catering_order(order["id"], ESM))
        assert after["status"] == "PLACED", "a rejected confirm must leave the order untouched"

    def test_place_blocked_when_account_suspended(self, api: ApiClient):
        """PRD §2.8: "(i) the account must not be `SUSPENDED` for new commitments —
        agreement execution, placing a rental hold, placing a catering order, issuing
        a credential, or joining the waitlist — else `ERR_ACCOUNT_SUSPENDED`".
        Design: Corner/validations/catering_place_blocked_when_account_suspended
        """
        s = _setup()
        validate_success(api.set_account_status(
            s["account"]["id"], {"target_status": "SUSPENDED"},
            FIN))
        resp = _place(api, s, [{"item_code": "APP", "description": "Sliders",
                                "quantity": 1, "unit_price_cents": 1000}],
                      guest_count=8, package_tier="STANDARD")
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)


class TestFulfillmentGate:
    def test_fulfill_before_event_start_rejected(self, api: ApiClient):
        """PRD §3.6: "Fulfilment, moving `CONFIRMED` to `FULFILLED` under the same two
        roles, requires the clock to have reached the event's `starts_at` and is
        otherwise `ERR_INVALID_STATE_TRANSITION`."
        Design: Corner/state_machines/catering_fulfill_before_event_start_rejected
        """
        s = _setup()
        order = validate_success(_place(api, s, [{"item_code": "APP",
                                                  "description": "Sliders",
                                                  "quantity": 1,
                                                  "unit_price_cents": 1000}],
                                        guest_count=8, package_tier="STANDARD"),
                                 expected_status=201)
        validate_success(api.set_catering_order_status(
            order["id"], {"target_status": "CONFIRMED"}, ESM))
        set_clock("2026-09-10T16:00:00Z")  # one hour before the 17:00 start
        resp = api.set_catering_order_status(order["id"], {"target_status": "FULFILLED"}, ESM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert validate_success(api.get_catering_order(order["id"], ESM))["status"] == "CONFIRMED"


class TestAccrualConservation:
    def test_confirm_then_free_cancel_restores_accrual(self, api: ApiClient):
        """PRD §3.6: "A `CONFIRMED` order cancelled while the clock is still at or
        before the cutoff lands in `CANCELLED` and its accrual is removed from the
        agreement, so a confirm followed by a free cancel nets the accrual to zero."
        Design: Difficulty/compensating_invariant/catering_confirm_then_free_cancel_restores_accrual_exactly
        """
        s = _setup()
        holder = make_account_holder_headers(s["account"]["id"])
        ag_id = s["agreement"]["id"]
        assert validate_success(api.get_agreement(ag_id, REP))["f_b_accrued_cents_current_season"] == 0
        order = validate_success(_place(api, s, PINNED_LINES), expected_status=201)
        validate_success(api.set_catering_order_status(
            order["id"], {"target_status": "CONFIRMED"}, ESM))
        confirmed = validate_success(api.get_agreement(ag_id, REP))
        assert confirmed["f_b_accrued_cents_current_season"] == 9400
        validate_success(api.set_catering_order_status(
            order["id"], {"target_status": "CANCELLED"}, holder))
        restored = validate_success(api.get_agreement(ag_id, REP))
        assert restored["f_b_accrued_cents_current_season"] == 0, "exact conservation, zero drift"

    def test_free_cancel_before_cutoff_has_zero_fee(self, api: ApiClient):
        """PRD §3.6: "A `PLACED` order may be cancelled outright ... with no fee";
        "`cancel_fee_cents` itself is zero unless the order lands in `CANCELLED_LATE`".
        Design: Difficulty/compensating_invariant/catering_confirm_then_free_cancel_restores_accrual_exactly
        """
        s = _setup()
        holder = make_account_holder_headers(s["account"]["id"])
        order = validate_success(_place(api, s, PINNED_LINES), expected_status=201)
        validate_success(api.set_catering_order_status(
            order["id"], {"target_status": "CONFIRMED"}, ESM))
        cancelled = validate_success(api.set_catering_order_status(
            order["id"], {"target_status": "CANCELLED"}, holder))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_fee_cents"] == 0


class TestLateCancellation:
    def test_late_cancel_fee_and_accrual_switch(self, api: ApiClient):
        """PRD §3.6: "The same cancellation request arriving after the cutoff but
        before the event starts lands instead in `CANCELLED_LATE`: `cancel_fee_cents`
        becomes half the total, rounded half-up; the order's `accrual_cents` switches
        from its subtotal to its cancellation fee; and the agreement's
        `f_b_accrued_cents_current_season` adjusts by the difference between the fee
        and the former subtotal accrual."
        Design: Corner/calculations/catering_late_cancel_fee_and_accrual_switch
        """
        s = _setup()
        holder = make_account_holder_headers(s["account"]["id"])
        order = validate_success(_place(api, s, PINNED_LINES), expected_status=201)
        validate_success(api.set_catering_order_status(
            order["id"], {"target_status": "CONFIRMED"}, ESM))
        set_clock("2026-09-08T00:00:00Z")  # past cutoff 2026-09-07T17:00Z, before start
        cancelled = validate_success(api.set_catering_order_status(
            order["id"], {"target_status": "CANCELLED"}, holder))
        assert cancelled["status"] == "CANCELLED_LATE"
        assert cancelled["cancel_fee_cents"] == 5546, "round_half_up(0.5 * 11092)"
        assert cancelled["accrual_cents"] == 5546
        agreement = validate_success(api.get_agreement(s["agreement"]["id"], REP))
        assert agreement["f_b_accrued_cents_current_season"] == 5546, (
            "was 9400 while CONFIRMED; delta -3854 after the switch")


class TestAmendmentOcc:
    def test_occ_catering_amend_stale_version(self, api: ApiClient):
        """PRD §2.7: "Amending a catering order (`PATCH /api/catering-orders/{id}`)
        requires `expected_catering_order_version`, the client last observed `version`
        of the CateringOrder. Each successful amendment recomputes totals and bumps the
        order's `version` ... it is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        Design: Corner/cross_cutting_layers/occ_catering_amend_stale_version
        """
        s = _setup()
        holder = make_account_holder_headers(s["account"]["id"])
        order = validate_success(_place(api, s, [{"item_code": "APP",
                                                  "description": "Sliders",
                                                  "quantity": 1,
                                                  "unit_price_cents": 1000}],
                                        guest_count=8, package_tier="STANDARD"),
                                 expected_status=201)
        v1 = order["version"]
        amended = validate_success(api.amend_catering_order(
            order["id"], {"guest_count": 10, "expected_catering_order_version": v1}, holder))
        assert amended["guest_count"] == 10
        assert amended["version"] == v1 + 1
        stale = api.amend_catering_order(
            order["id"], {"guest_count": 12, "expected_catering_order_version": v1}, holder)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        final = validate_success(api.get_catering_order(order["id"], ESM))
        assert final["guest_count"] == 10


class TestImmediateConsistency:
    def test_create_response_carries_computed_fields_immediately(self, api: ApiClient):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." PRD §2.9: "no intermediate state is observable between a trigger and
        its cascaded effects."
        Design: Corner/consistency_model/create_responses_carry_computed_fields_immediately
        """
        s = _setup()
        resp = _place(api, s, TRAP_LINES, guest_count=6, package_tier="STANDARD")
        assert resp.status_code == 201
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        data = body["data"]
        assert data["subtotal_cents"] == 5094
        assert data["service_fee_cents"] == 917
        assert data["total_cents"] == 6011
        assert data["status"] == "PLACED"
