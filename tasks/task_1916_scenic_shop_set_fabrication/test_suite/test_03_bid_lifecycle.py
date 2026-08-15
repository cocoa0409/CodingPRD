"""Bid lifecycle: submission, negotiation cycle, accept, reject, withdraw,
expiration, epoch, takeoff lock."""
import pytest

from test_helpers import (
    ADMIN,
    EST,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_bid,
    assert_production,
    create_rom_bid,
    get_success_data,
    make_client_pm_headers,
    set_clock,
    setup_accepted_production,
    setup_basic_scenario,
    setup_design_package,
    setup_second_package,
    setup_shop,
    submit_bid,
    accept_bid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBidNegotiationCycle:
    def test_counter_revise_loop_increments_round_and_price(self, api):
        """PRD §3.3: "An estimator may then revise a `COUNTERED` bid, supplying
        `revised_price_cents`: the bid's `price_cents` is replaced by the
        revised value, `round_no` increments by 1, `valid_until` is recomputed
        as the logical clock at revision plus `validity_days`, and the bid
        returns to `SUBMITTED` — the negotiation cycle."

        Design: Difficulty/non_linear_state_machine/bid_counter_revise_cycle_increments_round
        """
        shop, client, pkg = setup_basic_scenario()
        bid = create_rom_bid(client["id"], pkg["id"], estimated_crew_hours=100)
        submit_bid(bid["id"])
        # Two full counter/revise loops
        api.counter_bid(bid["id"], {"counter_price_cents": 700000},
                        make_client_pm_headers(client["id"]))
        api.revise_bid(bid["id"], {"revised_price_cents": 850000}, EST)
        api.counter_bid(bid["id"], {"counter_price_cents": 800000},
                        make_client_pm_headers(client["id"]))
        api.revise_bid(bid["id"], {"revised_price_cents": 825000}, EST)
        after = get_success_data(api.get_bid(bid["id"], EST))
        assert after["round_no"] == 3  # 1 + 2 revises
        assert after["price_cents"] == 825000
        assert after["status"] == "SUBMITTED"

    def test_negotiation_loop_then_accept_propagates_price(self, api):
        """PRD §3.3: "Acceptance spawns a `Production` in `SCHEDULED` status:
        ... `current_price_cents` starts at the accepted bid's `price_cents`."

        Design: Difficulty/non_linear_state_machine/bid_counter_revise_cycle_increments_round
        """
        shop, client, pkg = setup_basic_scenario()
        bid = create_rom_bid(client["id"], pkg["id"], estimated_crew_hours=100)
        submit_bid(bid["id"])
        api.counter_bid(bid["id"], {"counter_price_cents": 700000},
                        make_client_pm_headers(client["id"]))
        api.revise_bid(bid["id"], {"revised_price_cents": 825000}, EST)
        accepted = accept_bid(bid["id"], client["id"])
        assert accepted["status"] == "ACCEPTED"
        prod = get_success_data(api.get_production(accepted["production_id"], EST))
        assert prod["current_price_cents"] == 825000


class TestBidSubmitIdempotency:
    def test_second_submit_returns_invalid_state(self, api):
        """PRD §3.3: "the bid must currently be `DRAFT` (otherwise
        `ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/bid_submit_twice_returns_invalid_state
        """
        shop, client, pkg = setup_basic_scenario()
        bid = create_rom_bid(client["id"], pkg["id"])
        submit_resp = api.submit_bid(bid["id"], EST)
        first = validate_success(submit_resp)
        first_valid_until = first["valid_until"]
        # Second submit on a now-SUBMITTED bid
        err_resp = api.submit_bid(bid["id"], EST)
        validate_error(err_resp, ApiErrorId.ERR_INVALID_STATE, 409)
        # No side effects refire: valid_until unchanged
        after = get_success_data(api.get_bid(bid["id"], EST))
        assert after["status"] == "SUBMITTED"
        assert after["valid_until"] == first_valid_until


class TestBidTerminalStates:
    def test_accept_after_reject_returns_invalid_state(self, api):
        """PRD §2.6: "the target entity must be in a state from which the
        requested transition exists; terminal entities reject all further
        actions (failures: `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/accept_rejected_bid_returns_invalid_state
        """
        shop, client, pkg = setup_basic_scenario()
        bid = create_rom_bid(client["id"], pkg["id"])
        submit_bid(bid["id"])
        api.reject_bid(bid["id"], make_client_pm_headers(client["id"]))
        resp = api.accept_bid(bid["id"], make_client_pm_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(api.get_bid(bid["id"], EST))
        assert after["status"] == "REJECTED"
        assert after.get("production_id") is None

    def test_withdraw_countered_bid_then_counter_fails(self, api):
        """PRD §3.3: "an estimator may withdraw a bid from `DRAFT`,
        `SUBMITTED`, or `COUNTERED` into `WITHDRAWN`; any other starting state
        for these actions is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/withdraw_countered_bid_is_valid_and_terminal
        """
        shop, client, pkg = setup_basic_scenario()
        bid = create_rom_bid(client["id"], pkg["id"])
        submit_bid(bid["id"])
        api.counter_bid(bid["id"], {"counter_price_cents": 700000},
                        make_client_pm_headers(client["id"]))
        resp = api.withdraw_bid(bid["id"], EST)
        withdrawn = validate_success(resp)
        assert withdrawn["status"] == "WITHDRAWN"
        # Counter after withdraw fails
        err = api.counter_bid(bid["id"], {"counter_price_cents": 800000},
                              make_client_pm_headers(client["id"]))
        validate_error(err, ApiErrorId.ERR_INVALID_STATE, 409)


class TestBidStaleDrawingRevision:
    def test_superseded_package_submit_returns_stale_revision(self, api):
        """PRD §3.3: "the design package must still be `CURRENT` and the bid's
        `pinned_drawing_revision` must still equal the package's
        `drawing_revision` (otherwise `ERR_STALE_DRAWING_REVISION`, HTTP 409 —
        this is where a superseded drawing first bites)."

        Design: Corner/errors/superseded_package_submit_returns_stale_revision
        """
        shop, client, pkg = setup_basic_scenario()
        bid = create_rom_bid(client["id"], pkg["id"])
        # Re-upload supersedes pkg revision 1 -> 2
        setup_design_package(client["id"], show_title="Hamlet")
        resp = api.submit_bid(bid["id"], EST)
        validate_error(resp, ApiErrorId.ERR_STALE_DRAWING_REVISION, 409)
        after = get_success_data(api.get_bid(bid["id"], EST))
        assert after["status"] == "DRAFT"


class TestBidExpiryAndEpoch:
    def test_accept_after_valid_until_returns_bid_expired(self, api):
        """PRD §3.3: "not past its `valid_until` against the logical clock
        (else `ERR_BID_EXPIRED`, HTTP 409)."

        Design: Corner/errors/accept_after_valid_until_returns_bid_expired
        """
        shop, client, pkg = setup_basic_scenario()
        bid = create_rom_bid(client["id"], pkg["id"], validity_days=5)
        submit_bid(bid["id"])
        # Default clock 2026-08-01; validity 5 -> valid_until 2026-08-06.
        # Advance clock past it.
        set_clock("2026-08-07T00:00:00Z")
        resp = api.accept_bid(bid["id"], make_client_pm_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_EXPIRED, 409)
        after = get_success_data(api.get_bid(bid["id"], EST))
        assert after["status"] == "SUBMITTED"

    def test_run_epoch_expires_stale_bid_and_bumps_index(self, api):
        """PRD §3.7: "Running an epoch increments the shop's `epoch_index` by
        1, expires every `SUBMITTED` bid of the shop whose `valid_until` has
        fallen behind the logical clock into `EXPIRED`, and recomputes the
        shop's capacity posture."

        Design: Corner/errors/run_epoch_expires_stale_bid_and_bumps_index
        """
        shop, client, pkg_a = setup_basic_scenario()
        pkg_b = setup_second_package(client["id"], venue="Rialto")
        bid_1 = create_rom_bid(client["id"], pkg_a["id"], validity_days=5,
                               estimated_crew_hours=100)
        submit_bid(bid_1["id"])
        bid_2 = create_rom_bid(client["id"], pkg_b["id"], validity_days=30,
                               estimated_crew_hours=80, floor_area_sqft=80,
                               build_start_at="2026-10-01T00:00:00Z")
        submit_bid(bid_2["id"])
        set_clock("2026-08-07T00:00:00Z")
        api.run_epoch(shop["id"], ADMIN)
        shop_after = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_after["epoch_index"] == 1
        b1 = get_success_data(api.get_bid(bid_1["id"], EST))
        b2 = get_success_data(api.get_bid(bid_2["id"], EST))
        assert b1["status"] == "EXPIRED"
        assert b2["status"] == "SUBMITTED"


class TestBidAcceptanceCascade:
    def test_acceptance_spawns_production_with_correct_fields(self, api):
        """PRD §3.3: "Acceptance spawns a `Production` in `SCHEDULED` status:
        its `shop_id` is the client's shop; `bid_id`, `client_id`,
        `show_title`, `build_start_at`, and `bays_required` are copied from
        the bid and its package; `load_in_deadline_at` is the package's
        `load_in_at`; `strike_at` is the package's `strike_at`;
        `committed_crew_hours` is the takeoff's `labor_hours_est` for a
        `DETAILED` bid or the bid's `estimated_crew_hours` for a `ROM` bid;
        `applied_drawing_revision` is the bid's `pinned_drawing_revision`;
        `required_review_scopes` is `STRUCTURAL` alone, or `STRUCTURAL` plus
        `AUTOMATION` when the bid's `has_automation_scope` is true; and
        `current_price_cents` starts at the accepted bid's `price_cents`."

        Design: Difficulty/transitive_cascade/bid_acceptance_cascade_spawns_production_reviews_and_posture
        """
        shop, client, pkg = setup_basic_scenario()
        bid = create_rom_bid(client["id"], pkg["id"],
                             has_automation_scope=True, estimated_crew_hours=400)
        submit_bid(bid["id"])
        accepted = accept_bid(bid["id"], client["id"])
        assert accepted["status"] == "ACCEPTED"
        assert accepted.get("production_id")
        prod = get_success_data(api.get_production(accepted["production_id"], EST))
        assert_production(prod)
        assert prod["status"] == "SCHEDULED"
        assert prod["current_price_cents"] == 900000  # 100 * 9000 ROM
        assert prod["committed_crew_hours"] == 400
        assert prod["applied_drawing_revision"] == 1
        assert sorted(prod["required_review_scopes"]) == ["AUTOMATION", "STRUCTURAL"]
        assert prod["bid_id"] == bid["id"]
        assert prod["client_id"] == client["id"]
        assert prod["shop_id"] == shop["id"]

    def test_acceptance_drives_shop_to_saturated_and_gates_next_submit(self, api):
        """PRD §2.7: "Posture gates commercial activity: bid submission and
        bid acceptance are both rejected with `ERR_SHOP_SATURATED` while the
        shop is `SATURATED`."

        Design: Difficulty/transitive_cascade/bid_acceptance_cascade_spawns_production_reviews_and_posture
        """
        shop, client, pkg_a = setup_basic_scenario()
        pkg_b = setup_second_package(client["id"], show_title="Macbeth",
                                     load_in_at="2026-10-24T00:00:00Z",
                                     strike_at="2026-11-07T00:00:00Z")
        bid_a = create_rom_bid(client["id"], pkg_a["id"], estimated_crew_hours=400,
                               has_automation_scope=True)
        submit_bid(bid_a["id"])
        bid_b = create_rom_bid(client["id"], pkg_b["id"], estimated_crew_hours=100,
                               build_start_at="2026-10-01T00:00:00Z",
                               validity_days=60)
        # Accept bid A -> shop committed 400/400 = 10000bp -> SATURATED
        accept_bid(bid_a["id"], client["id"])
        shop_now = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_now["committed_crew_hours"] == 400
        assert shop_now["capacity_ratio_bp"] == 10000
        assert shop_now["posture"] == "SATURATED"
        # Submit bid B now fails
        resp = api.submit_bid(bid_b["id"], EST)
        validate_error(resp, ApiErrorId.ERR_SHOP_SATURATED, 409)
        # Client outstanding reflects the new production's price
        client_now = get_success_data(api.get_client(client["id"], ADMIN))
        assert client_now["outstanding_cents"] == 900000


class TestBidListFiltering:
    def test_bid_list_combines_client_and_status_filters(self, api):
        """PRD §4 endpoint table: "List bids (filterable by `client_id`,
        `design_package_id`, `takeoff_id`, `production_id`, `status`)."

        Design: Corner/endpoints/bid_list_combines_client_and_status_filters
        """
        shop = setup_shop()
        client_a = get_success_data(api.create_client(
            {"shop_id": shop["id"], "company_name": "Alpha Productions",
             "contact_email": "a@x.example", "credit_limit_cents": 100000000},
            ADMIN,
        ))
        client_b = get_success_data(api.create_client(
            {"shop_id": shop["id"], "company_name": "Bravo Productions",
             "contact_email": "b@x.example", "credit_limit_cents": 100000000},
            ADMIN,
        ))
        pkg_a = setup_design_package(client_a["id"], show_title="Hamlet")
        pkg_b = setup_design_package(client_b["id"], show_title="Macbeth",
                                     venue="Rialto")
        # Two DRAFT bids on alpha, one SUBMITTED on bravo
        create_rom_bid(client_a["id"], pkg_a["id"])
        create_rom_bid(client_a["id"], pkg_a["id"], floor_area_sqft=120,
                       complexity_class="C_COMPLEX", has_automation_scope=True,
                       bays_required=2, estimated_crew_hours=150)
        bid_b = create_rom_bid(client_b["id"], pkg_b["id"], floor_area_sqft=80,
                               complexity_class="B_STANDARD", estimated_crew_hours=80)
        submit_bid(bid_b["id"])

        data, meta = validate_paginated(api.list_bids(
            EST, params={"client_id": client_a["id"], "status": "DRAFT"},
        ))
        assert meta["total_count"] == 2
        assert all(row["client_id"] == client_a["id"] and row["status"] == "DRAFT"
                   for row in data)

        data_b, meta_b = validate_paginated(api.list_bids(
            EST, params={"client_id": client_b["id"], "status": "SUBMITTED"},
        ))
        assert meta_b["total_count"] == 1
        assert data_b[0]["id"] == bid_b["id"]


class TestBidValidationErrors:
    def test_create_bid_missing_pricing_variant_returns_400(self, api):
        """PRD §3.2: "omitting a universally required field, passing an
        unknown field, supplying an invalid enum value, giving a non-positive
        quantity, or giving a window or deadline whose end does not strictly
        follow its start anywhere in the system — is rejected with
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_bid_missing_required_pricing_variant_returns_400
        """
        shop, client, pkg = setup_basic_scenario()
        resp = api.create_bid(
            {
                "client_id": client["id"], "design_package_id": pkg["id"],
                "has_automation_scope": False, "bays_required": 1,
                "build_start_at": "2026-09-01T00:00:00Z", "validity_days": 30,
                "floor_area_sqft": 100, "complexity_class": "A_SIMPLE",
                "estimated_crew_hours": 100,
            },
            EST,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)
        # The bid is not persisted
        data, meta = validate_paginated(api.list_bids(
            EST, params={"client_id": client["id"]},
        ))
        assert meta["total_count"] == 0

    def test_create_bid_with_computed_price_field_rejected(self, api):
        """PRD §2.10: "a bid's `price_cents` ... are all computed values;
        clients never supply them."  PRD §3.2: "passing an unknown field ... is
        rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/bid_create_extra_price_field_rejected
        """
        shop, client, pkg = setup_basic_scenario()
        resp = api.create_bid(
            {
                "client_id": client["id"], "design_package_id": pkg["id"],
                "pricing_variant": "ROM", "has_automation_scope": False,
                "bays_required": 1, "build_start_at": "2026-09-01T00:00:00Z",
                "validity_days": 30, "floor_area_sqft": 100,
                "complexity_class": "A_SIMPLE", "estimated_crew_hours": 100,
                "price_cents": 1,
            },
            EST,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_get_nonexistent_bid_returns_404(self, api):
        """PRD §2.6 priority 3: "every path identifier and every
        body-referenced identifier ... must resolve to an existing resource;
        the first unresolvable identifier rejects the request with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_bid_returns_not_found
        """
        setup_shop()
        resp = api.get_bid(NON_EXISTENT_UUID, EST)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestBidAcceptImmediateConsistency:
    def test_accept_response_immediately_reflects_spawned_production(self, api):
        """PRD §3.3: "Acceptance spawns a `Production` in `SCHEDULED` status"
        and "The bid's `production_id` is set to the new production".

        Design: Corner/consistency_model/accept_response_immediately_reflects_spawned_production
        """
        shop, client, pkg = setup_basic_scenario()
        bid = create_rom_bid(client["id"], pkg["id"], estimated_crew_hours=100)
        submit_bid(bid["id"])
        accept_resp = api.accept_bid(bid["id"], make_client_pm_headers(client["id"]))
        accepted = validate_success(accept_resp)
        assert accepted["status"] == "ACCEPTED"
        assert accepted.get("production_id")
        prod = get_success_data(api.get_production(accepted["production_id"], EST))
        assert prod["status"] == "SCHEDULED"
        assert prod["current_price_cents"] == 900000
        assert prod["bid_id"] == bid["id"]
