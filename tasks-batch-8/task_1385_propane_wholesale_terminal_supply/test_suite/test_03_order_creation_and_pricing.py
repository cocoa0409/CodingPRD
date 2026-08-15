"""Order creation: posture fast paths, the delivered-price engine (bands,
premia, freight floor, rounding, provisional/final variants), and the
creation-time gates."""
from test_helpers import (
    CREDIT_MANAGER,
    DISPATCHER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_dealer_contract,
    api_client,
    assert_delivery_order,
    base_order_fixture,
    base_terminal_fixture,
    create_dealer,
    create_dealer_contract,
    create_order,
    create_terminal,
    create_zone,
    curtail_terminal,
    get_success_data,
    load_order,
    publish_index,
    schedule_order,
    set_clock,
    stock_terminal,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import make_dealer_user_headers


class TestCreationPostureFastPath:

    def test_order_initial_state_allocated_in_normal_posture(self):
        """PRD section 3.4: "At a `NORMAL` terminal, creation is a fast path:
        the order is allocated immediately, `fulfillment_status` becomes
        `ALLOCATED`, `allocated_gal` equals `requested_gal`, and
        `provisional_total_cents` is stamped at once."

        Design: Corner/state_machines/order_initial_state_allocated_in_normal_posture
        """
        ctx = base_order_fixture(name="T-M1")
        resp = api_client.create_delivery_order(
            {"dealer_contract_id": ctx["dealer_contract"]["id"],
             "terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": ctx["zone"]["id"], "requested_gal": 5_000},
            make_dealer_user_headers(ctx["dealer"]["id"]),
        )
        order = validate_success(resp, expected_status=201)
        assert_delivery_order(order)
        assert order["fulfillment_status"] == "ALLOCATED"
        assert order["allocated_gal"] == 5_000
        assert order["invoice_status"] == "NOT_READY"
        assert isinstance(order["provisional_total_cents"], int), \
            "the provisional is stamped at creation on the fast path"

    def test_order_initial_state_requested_when_curtailed(self):
        """PRD section 3.4: "At a `CURTAILED` terminal there is no allocation
        check at creation: the order lands in `REQUESTED` with `allocated_gal`
        null and `provisional_total_cents` null, waiting for an allocation run."

        Design: Corner/state_machines/order_initial_state_requested_when_curtailed
        """
        ctx = base_order_fixture(name="T-M2")
        curtail_terminal(ctx["terminal"]["id"], severity="WATCH")

        resp = api_client.create_delivery_order(
            {"dealer_contract_id": ctx["dealer_contract"]["id"],
             "terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": ctx["zone"]["id"], "requested_gal": 5_000},
            make_dealer_user_headers(ctx["dealer"]["id"]),
        )
        order = validate_success(resp, expected_status=201)
        assert_delivery_order(order)
        assert order["fulfillment_status"] == "REQUESTED"
        assert order["allocated_gal"] is None
        assert order["provisional_total_cents"] is None


class TestDeliveredPriceEngine:

    def test_spot_order_pricing_includes_spot_premium(self):
        """PRD section 3.4: "Omitting the contract produces a `SPOT` order
        priced at the index plus a spot premium of 40 cents per gallon."
        PRD section 3.5: "For a `SPOT` order, the product segment is the
        volume times the sum of the resolved index price, the 40-cent-per-
        gallon spot premium, and any applicable watch surcharge, converted
        from millicents to cents with half-up rounding."

        Design: Corner/calculations/spot_order_pricing_includes_spot_premium
        """
        ctx = base_terminal_fixture(name="T-L4", truck_count=0)
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")
        dealer = create_dealer(legal_name="Dealer L4")

        order = create_order(dealer["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 10_000)
        assert_delivery_order(order)
        assert order["pricing_mode"] == "SPOT"
        # rhu(10000 * (95000 + 40000) / 1000) + max(150000, 80000)
        assert order["provisional_total_cents"] == 1_500_000, (
            f"1350000 product + 150000 freight; got "
            f"{order['provisional_total_cents']}")

    def test_freight_minimum_applied(self):
        """PRD section 3.5: "The freight segment is the greater of the zone's
        `min_freight_cents` and the volume times the zone's
        `freight_mc_per_gal` converted to cents with half-up rounding."

        Design: Corner/calculations/freight_minimum_applied
        """
        ctx = base_order_fixture(name="T-L1")
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 5_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        # rhu(5000*90000/1000)=450000 product + max(150000, rhu(40000)) freight
        assert order["provisional_total_cents"] == 600_000, (
            f"the 150000-cent zone minimum beats the computed 40000; got "
            f"{order['provisional_total_cents']}")

    def test_rounding_half_up_per_segment_boundary(self):
        """PRD section 2.7: "All delivered-price computation rounds half-up to
        integer cents, and the rounding is applied per segment: the in-band
        product segment, the overage product segment, the freight segment, and
        the winter-surcharge segment are each rounded half-up to integer cents
        individually, and only then summed."

        Design: Corner/calculations/rounding_half_up_per_segment_boundary
        """
        ctx = base_order_fixture(name="T-L2", fixed_price_mc_per_gal=50_500)
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 1_001,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        # rhu(1001*50500/1000) = rhu(50550.5) = 50551 (round half UP);
        # freight max(150000, rhu(8008)) = 150000.
        assert order["provisional_total_cents"] == 200_551, (
            "an exact .5-cent segment must round up to 50551, not to even; "
            f"got {order['provisional_total_cents']}")

    def test_provisional_priced_at_creation_date_index(self):
        """PRD section 3.5: "The provisional variant is computed at order
        creation, re-stamped on every entry into `ALLOCATED`, and re-stamped on
        every `ALLOCATED` or `SCHEDULED` order whenever the terminal's posture
        flips; its reference date is the current logical-clock date and its
        winter leg uses the terminal's current posture."
        PRD section 3.5: "Resolving the index for a reference date means
        finding the publication for that index whose `effective_date` is the
        greatest one on or before the reference date"

        Design: Difficulty/dual_variant_calc/index_order_provisional_vs_final_diverge
        """
        ctx = base_order_fixture(name="T-D1", pricing_mode="INDEX")
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")

        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 10_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        # Created 2026-08-01: rhu(10000*95000/1000)=950000 + 150000 freight.
        assert order["provisional_total_cents"] == 1_100_000, (
            f"creation-date index 95000 governs the provisional; got "
            f"{order['provisional_total_cents']}")

        # A future-dated publication does not move the stamped provisional.
        publish_index(price_mc_per_gal=98_000, effective_date="2026-08-10")
        reread = get_success_data(api_client.get_delivery_order(order["id"],
                                                                DISPATCHER))
        assert reread["provisional_total_cents"] == 1_100_000

    def test_final_priced_at_load_date_index_diverges(self):
        """PRD section 3.5: "The final variant is computed exactly once, at the
        moment a `SCHEDULED` order is loaded; its reference date is the
        calendar date of `planned_load_start`, its winter leg uses the posture
        at the load transition, and the `volume_drawn_gal` used for banding is
        the value before this load's draw is applied."

        Design: Difficulty/dual_variant_calc/index_order_provisional_vs_final_diverge
        """
        ctx = base_order_fixture(name="T-D1", pricing_mode="INDEX")
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 10_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        publish_index(price_mc_per_gal=98_000, effective_date="2026-08-10")

        schedule_order(order["id"], ctx["trucks"][0]["id"],
                       "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
        load_order(order["id"])

        done = get_success_data(api_client.get_delivery_order(order["id"],
                                                              DISPATCHER))
        # Final ref date 2026-08-10 resolves 98000: 980000 + 150000.
        assert done["final_total_cents"] == 1_130_000, (
            f"the load-date index governs the final; got "
            f"{done['final_total_cents']}")
        assert done["provisional_total_cents"] == 1_100_000
        assert done["final_total_cents"] != done["provisional_total_cents"], \
            "the same order yields different provisional and final totals"

    def test_delivered_price_tiered_band_overage_min_freight(self):
        """PRD section 3.5: "For a contract order, the volume splits:
        `in_band_gal` is the smaller of the priced volume and the remaining
        committed band (the greater of zero and `volume_committed_gal` minus
        `volume_drawn_gal`), and `over_gal` is the rest."
        PRD section 3.5: "Overage gallons always price at the index plus an
        overage premium of 25 cents per gallon, plus the watch surcharge when
        applicable."

        Design: Difficulty/combinatorial_formula/delivered_price_tiered_band_overage_min_freight
        """
        ctx = base_order_fixture(name="T-C1", volume_committed_gal=12_000)
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")
        dealer, contract = ctx["dealer"], ctx["dealer_contract"]

        order1 = create_order(dealer["id"], ctx["terminal"]["id"],
                              ctx["zone"]["id"], 9_500,
                              dealer_contract_id=contract["id"])
        schedule_order(order1["id"], ctx["trucks"][0]["id"])
        load_order(order1["id"])

        # 9500 of the 12000 band drawn; the next 10000-gal order straddles:
        # 2500 in-band @ 90000 + 7500 overage @ (95000+25000) + freight floor.
        order2 = create_order(dealer["id"], ctx["terminal"]["id"],
                              ctx["zone"]["id"], 10_000,
                              dealer_contract_id=contract["id"])
        assert order2["fulfillment_status"] == "ALLOCATED"
        # rhu(2500*90000/1000)=225000 + rhu(7500*120000/1000)=900000 + 150000
        assert order2["provisional_total_cents"] == 1_275_000, (
            f"225000 in-band + 900000 overage + 150000 freight; got "
            f"{order2['provisional_total_cents']}")

    def test_load_draws_only_in_band_gallons(self):
        """PRD section 3.6: "adds the in-band gallons — the smaller of
        `allocated_gal` and the remaining committed band — to the contract's
        `volume_drawn_gal`; overage gallons are never added to the band draw."

        Design: Difficulty/combinatorial_formula/delivered_price_tiered_band_overage_min_freight
        """
        ctx = base_order_fixture(name="T-C1", volume_committed_gal=12_000)
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")
        dealer, contract = ctx["dealer"], ctx["dealer_contract"]

        order1 = create_order(dealer["id"], ctx["terminal"]["id"],
                              ctx["zone"]["id"], 9_500,
                              dealer_contract_id=contract["id"])
        schedule_order(order1["id"], ctx["trucks"][0]["id"])
        load_order(order1["id"])

        loaded = get_success_data(api_client.get_delivery_order(order1["id"],
                                                                DISPATCHER))
        # FIXED in-band final: rhu(9500*90000/1000)=855000 + 150000 freight.
        assert loaded["final_total_cents"] == 1_005_000, (
            f"855000 product + 150000 freight; got "
            f"{loaded['final_total_cents']}")

        contract_after = get_success_data(
            api_client.get_dealer_contract(contract["id"], CREDIT_MANAGER))
        assert contract_after["volume_drawn_gal"] == 9_500, (
            f"only the 9500 in-band gallons draw the band; got "
            f"{contract_after['volume_drawn_gal']}")


class TestImmediateConsistency:

    def test_immediate_consistency_create_response_carries_computed_fields(self):
        """PRD section 3.4: "At a `NORMAL` terminal, creation is a fast path:
        the order is allocated immediately, `fulfillment_status` becomes
        `ALLOCATED`, `allocated_gal` equals `requested_gal`, and
        `provisional_total_cents` is stamped at once."

        Design: Corner/consistency_model/immediate_consistency_create_response_carries_computed_fields
        """
        ctx = base_order_fixture(name="T-K9")
        resp = api_client.create_delivery_order(
            {"dealer_contract_id": ctx["dealer_contract"]["id"],
             "terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": ctx["zone"]["id"], "requested_gal": 9_000},
            make_dealer_user_headers(ctx["dealer"]["id"]),
        )
        order = validate_success(resp, expected_status=201)
        assert_delivery_order(order)
        # rhu(9000*90000/1000)=810000 + 150000 freight, all in one response.
        assert order["fulfillment_status"] == "ALLOCATED"
        assert order["allocated_gal"] == 9_000
        assert order["provisional_total_cents"] == 960_000


class TestCreationGates:

    def test_volume_below_minimum_rejected(self):
        """PRD section 3.4: "The request names the `terminal_id`, the
        `freight_zone_id` of the destination, a `requested_gal` of at least
        1000 gallons (anything less, or a non-integer, is rejected with
        `ERR_VOLUME_INVALID`), and optionally a `dealer_contract_id`."

        Design: Corner/validations/volume_below_minimum_rejected
        """
        term = create_terminal(name="T-V4")
        dealer = create_dealer(legal_name="Dealer V4")
        zone = create_zone(term["id"], zone_code="Z1")
        resp = api_client.create_delivery_order(
            {"terminal_id": term["id"], "freight_zone_id": zone["id"],
             "requested_gal": 500},
            make_dealer_user_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOLUME_INVALID)

    def test_body_fk_not_found_returns_referenced_not_found(self):
        """PRD section 2.9: "Fifth, body foreign keys — such as
        `dealer_contract_id`, `terminal_id`, `freight_zone_id`, `truck_id`,
        `supply_contract_id`, and `dealer_id` — must resolve to existing
        entities, else `ERR_REFERENCED_NOT_FOUND` (HTTP 422)."

        Design: Corner/validations/body_fk_not_found_returns_referenced_not_found
        """
        ctx = base_order_fixture(name="T-V3", truck_count=0)
        resp = api_client.create_delivery_order(
            {"dealer_contract_id": ctx["dealer_contract"]["id"],
             "terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": NON_EXISTENT_UUID, "requested_gal": 5_000},
            make_dealer_user_headers(ctx["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND)

    def test_no_index_published_rejected(self):
        """PRD section 3.5: "Index resolution inside pricing is lazy: it
        happens only when an index-exposed gallon exists — any gallon of a
        `SPOT` order, the band gallons of an `INDEX` contract, or the overage
        gallons of a `FIXED` contract. When such a gallon exists and no
        publication is effective on the reference date, the operation fails
        with `ERR_NO_INDEX_PUBLISHED`."

        Design: Corner/validations/no_index_published_rejected
        """
        ctx = base_terminal_fixture(name="T-V12", truck_count=0)
        dealer = create_dealer(legal_name="Dealer V12")
        # No publications exist anywhere: the SPOT order is index-exposed.
        resp = api_client.create_delivery_order(
            {"terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": ctx["zone"]["id"], "requested_gal": 5_000},
            make_dealer_user_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_INDEX_PUBLISHED)

    def test_order_create_requires_contract_active_draft(self):
        """PRD section 3.4: "in that case the contract must belong to the
        calling dealer (`ERR_CONTRACT_DEALER_MISMATCH`), must be anchored at
        the order's terminal (`ERR_CONTRACT_TERMINAL_MISMATCH`), must be
        `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`), and the creation date must fall
        inside the contract window (`ERR_OUTSIDE_CONTRACT_WINDOW`)."

        Design: Difficulty/cross_entity_state_dependency/order_create_requires_contract_active
        """
        ctx = base_terminal_fixture(name="T-X1", truck_count=0)
        dealer = create_dealer(legal_name="Dealer X1")
        contract = create_dealer_contract(dealer["id"], ctx["terminal"]["id"])
        assert contract["status"] == "DRAFT", "setup check: never activated"

        resp = api_client.create_delivery_order(
            {"dealer_contract_id": contract["id"],
             "terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": ctx["zone"]["id"], "requested_gal": 5_000},
            make_dealer_user_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

        orders, meta = validate_paginated(
            api_client.list_delivery_orders(
                CREDIT_MANAGER, params={"dealer_id": dealer["id"]}))
        assert meta["total_count"] == 0, "a rejected creation adds no order row"

    def test_order_create_requires_contract_active_cancelled(self):
        """PRD section 3.4: "must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`)" —
        a CANCELLED contract is no more ACTIVE than a DRAFT one.
        PRD section 3.3: "Cancelling a contract from `DRAFT` or `ACTIVE`
        performs the same order cascade; orders already `LOADED` or
        `DELIVERED` and any open invoices are unaffected."

        Design: Difficulty/cross_entity_state_dependency/order_create_requires_contract_active
        """
        ctx = base_order_fixture(name="T-X1C", truck_count=0)
        contract = ctx["dealer_contract"]
        api_client.cancel_dealer_contract(contract["id"], CREDIT_MANAGER)
        cancelled = get_success_data(
            api_client.get_dealer_contract(contract["id"], CREDIT_MANAGER))
        assert cancelled["status"] == "CANCELLED"

        resp = api_client.create_delivery_order(
            {"dealer_contract_id": contract["id"],
             "terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": ctx["zone"]["id"], "requested_gal": 5_000},
            make_dealer_user_headers(ctx["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    def test_contract_terminal_mismatch_rejected(self):
        """PRD section 3.4: "must be anchored at the order's terminal
        (`ERR_CONTRACT_TERMINAL_MISMATCH`)"

        Design: Corner/validations/contract_terminal_mismatch_rejected
        """
        ta = create_terminal(name="T-V9A")
        tb = create_terminal(name="T-V9B", region_code="MW",
                             storage_capacity_gal=500_000,
                             reserve_floor_gal=20_000,
                             winter_reserve_floor_gal=60_000,
                             rack_bay_count=1)
        set_clock()
        stock_terminal(tb["id"], volume_gal=100_000,
                       contracted_volume_gal=300_000)
        zb = create_zone(tb["id"], zone_code="ZB")
        dealer = create_dealer(legal_name="Dealer V9")
        contract = create_dealer_contract(dealer["id"], ta["id"])
        activate_dealer_contract(contract["id"], dealer["id"])

        resp = api_client.create_delivery_order(
            {"dealer_contract_id": contract["id"], "terminal_id": tb["id"],
             "freight_zone_id": zb["id"], "requested_gal": 5_000},
            make_dealer_user_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_TERMINAL_MISMATCH)

    def test_contract_dealer_mismatch_rejected(self):
        """PRD section 3.4: "in that case the contract must belong to the
        calling dealer (`ERR_CONTRACT_DEALER_MISMATCH`)"

        Design: Corner/validations/contract_dealer_mismatch_rejected
        """
        ctx = base_order_fixture(name="T-V10", truck_count=0,
                                 dealer_name="Dealer V10A")
        other = create_dealer(legal_name="Dealer V10B")

        resp = api_client.create_delivery_order(
            {"dealer_contract_id": ctx["dealer_contract"]["id"],
             "terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": ctx["zone"]["id"], "requested_gal": 5_000},
            make_dealer_user_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_DEALER_MISMATCH)

    def test_zone_terminal_mismatch_rejected(self):
        """PRD section 3.1: "A zone belongs to exactly one terminal, and an
        order naming a zone owned by a different terminal than its own is
        rejected with `ERR_ZONE_TERMINAL_MISMATCH`."

        Design: Corner/validations/zone_terminal_mismatch_rejected
        """
        ctx = base_terminal_fixture(name="T-V14A", truck_count=0)
        tb = create_terminal(name="T-V14B", region_code="MW",
                             storage_capacity_gal=500_000,
                             reserve_floor_gal=20_000,
                             winter_reserve_floor_gal=60_000,
                             rack_bay_count=1)
        zb = create_zone(tb["id"], zone_code="ZB")
        dealer = create_dealer(legal_name="Dealer V14")

        resp = api_client.create_delivery_order(
            {"terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": zb["id"], "requested_gal": 5_000},
            make_dealer_user_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_TERMINAL_MISMATCH)


class TestSupplyAndCreditGates:

    def test_atp_exact_gallon_boundary_accepted(self):
        """PRD section 3.4: "The fast path requires `requested_gal` to be no
        greater than the terminal's `available_to_promise_gal` — exactly equal
        succeeds, one gallon over fails with `ERR_INSUFFICIENT_SUPPLY`."

        Design: Difficulty/boundary_precision_check/atp_exact_gallon_boundary
        """
        ctx = base_order_fixture(name="T-B2", truck_count=0,
                                 volume_committed_gal=400_000)
        # ATP = 400000 on hand - 50000 summer floor - 0 reserved = 350000.
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 350_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        assert order["fulfillment_status"] == "ALLOCATED", \
            "requested_gal == ATP exactly must succeed"
        assert order["allocated_gal"] == 350_000

    def test_atp_one_gallon_step_over_rejected(self):
        """PRD section 3.4: "The fast path requires `requested_gal` to be no
        greater than the terminal's `available_to_promise_gal` — exactly equal
        succeeds, one gallon over fails with `ERR_INSUFFICIENT_SUPPLY`."

        Design: Difficulty/boundary_precision_check/atp_exact_gallon_boundary
        """
        ctx = base_order_fixture(name="T-B2", truck_count=0,
                                 volume_committed_gal=400_000)
        create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                     ctx["zone"]["id"], 350_000,
                     dealer_contract_id=ctx["dealer_contract"]["id"])
        # ATP is now 0; the smallest legal request (1000 gal) is one step over.
        resp = api_client.create_delivery_order(
            {"dealer_contract_id": ctx["dealer_contract"]["id"],
             "terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": ctx["zone"]["id"], "requested_gal": 1_000},
            make_dealer_user_headers(ctx["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SUPPLY)

    def test_credit_gate_excludes_candidate_from_status(self):
        """PRD section 3.4: "First, `committed_before` is computed: the
        dealer's committed exposure excluding the candidate order. Second, the
        threshold ladder of section 3.3 maps `committed_before` to a
        `status_before`; a `SUSPENDED` dealer is rejected here with
        `ERR_DEALER_SUSPENDED` and never reaches pricing. Third, if
        `status_before` is `WATCH`, a watch surcharge of 15 cents per gallon
        applies to index-exposed gallons; otherwise the surcharge is zero."

        Design: Difficulty/combinatorial_formula/credit_gate_circular_eval_order
        """
        ctx = base_order_fixture(name="T-C3", truck_count=0,
                                 credit_limit_cents=5_700_000,
                                 pricing_mode="INDEX")
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")
        dealer, contract = ctx["dealer"], ctx["dealer_contract"]

        # 45000*95000/1000=4275000 + max(150000, 360000)=360000 -> 4635000,
        # i.e. 81.3% of the 5700000 limit: WATCH for the next order.
        create_order(dealer["id"], ctx["terminal"]["id"], ctx["zone"]["id"],
                     45_000, dealer_contract_id=contract["id"])

        order2 = create_order(dealer["id"], ctx["terminal"]["id"],
                              ctx["zone"]["id"], 5_000,
                              dealer_contract_id=contract["id"])
        # status_before (excluding this candidate) is WATCH, so the 15000 mc
        # surcharge applies: rhu(5000*(95000+15000)/1000)=550000 + 150000.
        assert order2["provisional_total_cents"] == 700_000, (
            "the watch surcharge is included because status was evaluated "
            f"excluding the candidate; got {order2['provisional_total_cents']}")

    def test_credit_gate_committed_and_status_after(self):
        """PRD section 3.3: "The `committed_exposure_cents` is the
        forward-looking view used by credit decisions: the `fee_balance_cents`,
        plus the ledger exposure, plus the sum of `final_total_cents` over the
        dealer's `LOADED` orders, plus the sum of `provisional_total_cents`
        over the dealer's `ALLOCATED` and `SCHEDULED` orders."
        PRD section 3.3: "Otherwise, when five times the committed exposure
        reaches or exceeds four times the credit limit — an exposure of exactly
        eighty percent crosses the line — the dealer is `WATCH`."

        Design: Difficulty/combinatorial_formula/credit_gate_circular_eval_order
        """
        ctx = base_order_fixture(name="T-C3", truck_count=0,
                                 credit_limit_cents=5_700_000,
                                 pricing_mode="INDEX")
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")
        dealer, contract = ctx["dealer"], ctx["dealer_contract"]

        create_order(dealer["id"], ctx["terminal"]["id"], ctx["zone"]["id"],
                     45_000, dealer_contract_id=contract["id"])
        create_order(dealer["id"], ctx["terminal"]["id"], ctx["zone"]["id"],
                     5_000, dealer_contract_id=contract["id"])

        dealer_after = get_success_data(api_client.get_dealer(dealer["id"],
                                                              CREDIT_MANAGER))
        # 4635000 + 700000 = 5335000, below the 5700000 limit.
        assert dealer_after["committed_exposure_cents"] == 5_335_000
        # 5335000 * 5 = 26675000 >= 5700000 * 4 = 22800000 -> WATCH.
        assert dealer_after["credit_status"] == "WATCH"


class TestValidationLayerPrecedence:

    def test_state_beats_fiscal_on_order_create(self):
        """PRD section 2.9: "Every request passes through validation layers in
        a fixed order, so that an earlier failure masks later ones
        deterministically." and "Eighth, cross-entity state gates such as
        contract-active, dealer-not-suspended, truck-available,
        terminal-curtailed, and no-other-active-cold-snap." precede "Eleventh
        and last, fiscal gates: the credit gate at order creation, the
        overpayment cap at payment posting, and index availability for
        index-exposed gallons."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_create
        """
        ctx = base_terminal_fixture(name="T-P1", truck_count=0)
        dealer = create_dealer(legal_name="Dealer P1", credit_limit_cents=100_000)
        contract = create_dealer_contract(dealer["id"], ctx["terminal"]["id"])
        # Contract DRAFT (state failure) AND 600000 provisional > 100000 limit
        # (fiscal failure): the earlier state gate must mask the fiscal one.
        resp = api_client.create_delivery_order(
            {"dealer_contract_id": contract["id"],
             "terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": ctx["zone"]["id"], "requested_gal": 5_000},
            make_dealer_user_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    def test_fiscal_gate_surfaces_once_state_fixed(self):
        """PRD section 3.4: "Fifth, the gate itself: if `committed_before` plus
        the order's provisional total exceeds `credit_limit_cents`, creation is
        rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_create
        """
        ctx = base_terminal_fixture(name="T-P1", truck_count=0)
        dealer = create_dealer(legal_name="Dealer P1", credit_limit_cents=100_000)
        contract = create_dealer_contract(dealer["id"], ctx["terminal"]["id"])
        activate_dealer_contract(contract["id"], dealer["id"])
        # State gate now passes; the same request reaches the fiscal gate:
        # committed_before 0 + provisional 600000 > 100000.
        resp = api_client.create_delivery_order(
            {"dealer_contract_id": contract["id"],
             "terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": ctx["zone"]["id"], "requested_gal": 5_000},
            make_dealer_user_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
