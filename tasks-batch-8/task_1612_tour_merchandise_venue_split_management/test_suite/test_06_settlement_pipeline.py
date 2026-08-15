"""Settlement pipeline: begin-reconciliation, reconcile, dispute/resolve
cycles, finalization gates, and the money math (commission, royalty,
licensing)."""
from test_helpers import (
    ACCT1,
    ACCT2,
    ApiErrorId,
    TM1,
    VENUE1,
    assert_settlement,
    assert_settlement_final_figures,
    begin_reconciliation,
    count_out_session,
    create_active_tour,
    create_product,
    create_seller,
    create_seller_session,
    create_show,
    create_show_product,
    dispute_payload,
    dispute_settlement,
    generate_allocations,
    get_settlement,
    get_show,
    get_success_data,
    make_seller_headers,
    open_show,
    reach_settlement,
    reconcile_settlement,
    record_sale,
    setup_selling_show,
    staff_session,
    validate_error,
    validate_paginated,
    verify_session,
)


def test_begin_reconciliation_with_open_session_rejected(api):
    """PRD §3.5: "Every seller session of the show must be `COUNTED_OUT` or
    `VERIFIED` — any straggler still `OPEN` fails the operation with
    `ERR_UNRESOLVED_SESSIONS`, and a show in any other status fails with
    `ERR_INVALID_SHOW_STATE`."
    PRD §3.5: "Beginning reconciliation moves the show from `OPEN` to
    `RECONCILING` and auto-creates the show's one and only settlement in
    `PROVISIONAL` status, recording its id on the show's `settlement_id`."

    Design: Corner/state_machines/begin_reconciliation_with_open_session_rejected
    """
    world = setup_selling_show(tour_name="SM7 Tour", city="Sonora",
                               venue_name="SM7 Hall",
                               show_date="2026-09-02T20:00:00Z", num_sellers=1)
    create_seller_session(world["show"]["id"], world["sellers"][0]["id"])

    resp = api.begin_reconciliation(world["show"]["id"], TM1)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_SESSIONS)

    show = get_show(world["show"]["id"])
    assert show["status"] == "OPEN"
    assert show["settlement_id"] is None, "no Settlement may be created"


def test_begin_reconciliation_creates_provisional_settlement(api):
    """PRD §3.5: "Beginning reconciliation moves the show from `OPEN` to
    `RECONCILING` and auto-creates the show's one and only settlement in
    `PROVISIONAL` status, recording its id on the show's `settlement_id`."
    PRD §3.5: "`provisional_gross_cents` measures what is physically in the
    drawers plus what the card processor saw: the sum over the show's sessions
    of each `counted_cash_cents` minus its `cash_float_cents`, plus the sum of
    `gross_cents` over the show's `ACTIVE` sale records tendered `CARD`."
    PRD §2.10: "A settlement, by contrast, must be reproducible, so at the
    moment a settlement is created it copies the tour's then-current terms into
    five pinned snapshot fields: `pinned_standard_rate_bps`,
    `pinned_tier_threshold_cents`, `pinned_tier_bonus_bps`,
    `pinned_licensed_flat_per_unit_cents`, and `pinned_licensed_rate_bps`."
    PRD §3.5: "Settlements can be listed filtered by `show_id` — since the
    relationship is one-to-one, such a filtered list has length zero or one."

    Design: Corner/endpoints/begin_reconciliation_creates_provisional_settlement
    """
    world = setup_selling_show(tour_name="EP3 Tour", city="Helena",
                               venue_name="EP3 Hall",
                               show_date="2026-09-15T20:00:00Z", num_sellers=1)
    session = staff_session(world, counted_cash_cents=5000, verify=False)
    assert session["status"] == "COUNTED_OUT"

    show = begin_reconciliation(world["show"]["id"])
    assert show["status"] == "RECONCILING"
    assert show["settlement_id"], "settlement_id must be recorded on the show"

    settlement = get_settlement(show["settlement_id"])
    assert_settlement(settlement)
    assert settlement["status"] == "PROVISIONAL"
    assert settlement["provisional_gross_cents"] == 0, (
        "drawer net 5000-5000 plus no card sales")
    assert settlement["venue_commission_provisional_cents"] == 0
    assert settlement["pinned_standard_rate_bps"] == 1000
    assert settlement["pinned_tier_threshold_cents"] == 500000
    assert settlement["pinned_tier_bonus_bps"] == 500
    assert settlement["pinned_licensed_flat_per_unit_cents"] == 500
    assert settlement["pinned_licensed_rate_bps"] == 2000

    rows, meta = validate_paginated(
        api.list_settlements(TM1, params={"show_id": show["id"]}))
    assert meta["total_count"] == 1 and len(rows) == 1, "1:1 with the show"
    assert rows[0]["id"] == settlement["id"]


class TestReconcileRequiresAllSessionsVerified:
    def _world_one_verified_one_counted_out(self, api):
        world = setup_selling_show(
            tour_name="CE2 Tour", city="Salinas", venue_name="CE2 Hall",
            show_date="2026-08-24T20:00:00Z", price_cents=2000, total_units=100,
            num_sellers=2,
            product_overrides={"sku": "CE2-CAP", "name": "Cap",
                               "base_price_cents": 2000,
                               "initial_stock_by_size": {"OS": 500}})
        staff_session(world, seller_index=0, sales=[(5, "CASH")],
                      counted_cash_cents=15000, verify=True, verify_by_index=1)
        staff_session(world, seller_index=1, sales=[(3, "CASH")],
                      counted_cash_cents=11000, verify=False)
        return world

    def test_reconcile_with_counted_out_session_rejected(self, api):
        """PRD §3.5: "Reconciling requires the settlement to be `PROVISIONAL`
        (otherwise `ERR_INVALID_SETTLEMENT_STATE`) and every session of the show
        to be `VERIFIED` (otherwise `ERR_UNRESOLVED_SESSIONS` — note the
        stricter gate than at begin-reconciliation)."
        PRD §3.5: "Every seller session of the show must be `COUNTED_OUT` or
        `VERIFIED` — any straggler still `OPEN` fails the operation with
        `ERR_UNRESOLVED_SESSIONS`, and a show in any other status fails with
        `ERR_INVALID_SHOW_STATE`."

        Design: Difficulty/cross_entity_state_dependency/reconcile_requires_all_sessions_verified
        """
        world = self._world_one_verified_one_counted_out(api)
        settlement = reach_settlement(world, "PROVISIONAL")

        resp = api.reconcile_settlement(settlement["id"], ACCT1)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_SESSIONS)
        assert get_settlement(settlement["id"])["status"] == "PROVISIONAL", (
            "COUNTED_OUT was enough to begin reconciliation but not to reconcile")

    def test_reconcile_succeeds_once_all_verified(self, api):
        """PRD §3.5: "Reconciling requires the settlement to be `PROVISIONAL`
        (otherwise `ERR_INVALID_SETTLEMENT_STATE`) and every session of the show
        to be `VERIFIED` (otherwise `ERR_UNRESOLVED_SESSIONS` — note the
        stricter gate than at begin-reconciliation)."
        PRD §3.5: "Reconcile moves the settlement to `RECONCILED` and replaces
        the provisional view with register truth: `final_gross_cents` is the sum
        of `gross_cents` over the show's `ACTIVE` sale records across both
        tenders, with `VOIDED` records excluded; `venue_commission_final_cents`
        applies the same commission formula to that final base;
        `net_to_tour_cents` is `final_gross_cents` minus
        `venue_commission_final_cents`, an exact subtraction."

        Design: Difficulty/cross_entity_state_dependency/reconcile_requires_all_sessions_verified
        """
        world = self._world_one_verified_one_counted_out(api)
        settlement = reach_settlement(world, "PROVISIONAL")

        verify_session(world["sessions"][1]["id"],
                       make_seller_headers(world["sellers"][0]["id"]))
        reconciled = reconcile_settlement(settlement["id"], ACCT1)
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["final_gross_cents"] == 16000, "10000 + 6000 cash"
        assert_settlement_final_figures(reconciled)


class TestVenueCommissionProvisionalVsFinal:
    def _world_with_variance_cash_and_card(self, api):
        world = setup_selling_show(tour_name="DV1 Tour", city="Austin",
                                   venue_name="DV1 Hall",
                                   show_date="2026-08-10T20:00:00Z",
                                   flat_commission_bps=1500, total_units=300,
                                   num_sellers=1)
        # 100 CASH + 100 CARD @ 4000; drawer counted 3000 under expected, so
        # the |3000| variance exceeds the 1000 tolerance: manager override.
        staff_session(world, seller_index=0,
                      sales=[(100, "CASH"), (100, "CARD")],
                      counted_cash_cents=402000, verify=True,
                      verify_headers=TM1, variance_override=True)
        return world

    def test_provisional_variant_uses_drawer_cash_plus_card(self, api):
        """PRD §3.5: "`provisional_gross_cents` measures what is physically in
        the drawers plus what the card processor saw: the sum over the show's
        sessions of each `counted_cash_cents` minus its `cash_float_cents`, plus
        the sum of `gross_cents` over the show's `ACTIVE` sale records tendered
        `CARD`. `venue_commission_provisional_cents` applies the show's
        commission formula to that provisional base."
        PRD §3.5: "A `FLAT` show's commission on any base is the base multiplied
        by `flat_commission_bps` and divided by 10000, rounded half up to a
        whole cent."

        Design: Difficulty/dual_variant_calc/venue_commission_provisional_vs_final
        """
        world = self._world_with_variance_cash_and_card(api)
        settlement = reach_settlement(world, "PROVISIONAL")

        assert settlement["provisional_gross_cents"] == 797000, (
            "drawer net 402000-5000 plus card 400000")
        assert settlement["venue_commission_provisional_cents"] == 119550, (
            "797000 x 1500 bps")

    def test_final_variant_uses_register_only(self, api):
        """PRD §3.5: "Reconcile moves the settlement to `RECONCILED` and
        replaces the provisional view with register truth: `final_gross_cents`
        is the sum of `gross_cents` over the show's `ACTIVE` sale records across
        both tenders, with `VOIDED` records excluded;
        `venue_commission_final_cents` applies the same commission formula to
        that final base; `net_to_tour_cents` is `final_gross_cents` minus
        `venue_commission_final_cents`, an exact subtraction."

        Design: Difficulty/dual_variant_calc/venue_commission_provisional_vs_final
        """
        world = self._world_with_variance_cash_and_card(api)
        settlement = reach_settlement(world, "RECONCILED")

        assert settlement["final_gross_cents"] == 800000, "register: 100 CASH + 100 CARD"
        assert settlement["venue_commission_final_cents"] == 120000
        assert settlement["net_to_tour_cents"] == 680000
        assert settlement["provisional_gross_cents"] == 797000, (
            "the provisional snapshot is not recomputed")
        assert settlement["venue_commission_provisional_cents"] == 119550
        assert (settlement["venue_commission_final_cents"]
                - settlement["venue_commission_provisional_cents"]) == 450, (
            "the -3000 cash variance x 1500 bps drives the 450-cent divergence")
        assert_settlement_final_figures(settlement)


class TestTieredCommissionStraddlingBoundary:
    def _tiered_world(self, api):
        world = setup_selling_show(
            tour_name="CF1 Tour", city="Denver", venue_name="CF1 Arena",
            show_date="2026-08-12T20:00:00Z", commission_mode="TIERED",
            flat_commission_bps=None,
            commission_tiers=[{"up_to_cents": 500000, "rate_bps": 1000},
                              {"up_to_cents": None, "rate_bps": 2000}],
            total_units=300, num_sellers=2)
        staff_session(world, seller_index=0, sales=[(200, "CASH")],
                      counted_cash_cents=805000, verify=True, verify_by_index=1)
        return world

    def test_provisional_commission_straddles_tiers(self, api):
        """PRD §3.5: "A `TIERED` show applies its brackets marginally in
        ascending `up_to_cents` order: each bracket's portion is the amount of
        the base falling within that bracket — from the previous bracket's cap
        up to this bracket's cap, with the trailing null-capped bracket catching
        everything above the last numbered cap, and no bracket contributing less
        than zero — each bracket's commission is rounded half up to a whole cent
        first, and the bracket commissions are then summed."
        PRD §3.5: "`provisional_gross_cents` measures what is physically in the
        drawers plus what the card processor saw: the sum over the show's
        sessions of each `counted_cash_cents` minus its `cash_float_cents`, plus
        the sum of `gross_cents` over the show's `ACTIVE` sale records tendered
        `CARD`."

        Design: Difficulty/combinatorial_formula/tiered_commission_straddling_boundary
        """
        world = self._tiered_world(api)
        settlement = reach_settlement(world, "PROVISIONAL")

        assert settlement["provisional_gross_cents"] == 800000, (
            "drawer net 805000-5000, zero variance")
        assert settlement["venue_commission_provisional_cents"] == 110000, (
            "500000 x 1000 bps + 300000 x 2000 bps = 50000 + 60000")

    def test_final_figures_and_royalty_split(self, api):
        """PRD §3.5: "Reconcile moves the settlement to `RECONCILED` and
        replaces the provisional view with register truth: `final_gross_cents`
        is the sum of `gross_cents` over the show's `ACTIVE` sale records across
        both tenders, with `VOIDED` records excluded;
        `venue_commission_final_cents` applies the same commission formula to
        that final base; `net_to_tour_cents` is `final_gross_cents` minus
        `venue_commission_final_cents`, an exact subtraction."
        PRD §3.5: "The artist royalty is tiered-marginal: when the net is at or
        below `pinned_tier_threshold_cents`, `artist_royalty_cents` is the net
        multiplied by `pinned_standard_rate_bps` and divided by 10000, rounded
        half up; when the net exceeds the threshold, it is the threshold
        multiplied by the standard rate and divided by 10000, rounded half up,
        plus the excess above the threshold multiplied by the sum of
        `pinned_standard_rate_bps` and `pinned_tier_bonus_bps` and divided by
        10000, rounded half up — the two segments rounded separately and then
        summed, and at a net exactly equal to the threshold the bonus portion is
        zero because the bonus applies only to the amount strictly above it."

        Design: Difficulty/combinatorial_formula/tiered_commission_straddling_boundary
        """
        world = self._tiered_world(api)
        settlement = reach_settlement(world, "RECONCILED")

        assert settlement["final_gross_cents"] == 800000
        assert settlement["venue_commission_final_cents"] == 110000
        assert settlement["net_to_tour_cents"] == 690000
        assert settlement["artist_royalty_cents"] == 78500, (
            "500000 x 1000 bps + 190000 x 1500 bps = 50000 + 28500")
        assert settlement["licensing_cents"] == 0, "STANDARD product"
        assert settlement["company_share_cents"] == 611500
        assert_settlement_final_figures(settlement)


def test_royalty_exactly_at_threshold_earns_no_bonus(api):
    """PRD §3.5: "The artist royalty is tiered-marginal: when the net is at or
    below `pinned_tier_threshold_cents`, `artist_royalty_cents` is the net
    multiplied by `pinned_standard_rate_bps` and divided by 10000, rounded half
    up; when the net exceeds the threshold, it is the threshold multiplied by
    the standard rate and divided by 10000, rounded half up, plus the excess
    above the threshold multiplied by the sum of `pinned_standard_rate_bps` and
    `pinned_tier_bonus_bps` and divided by 10000, rounded half up — the two
    segments rounded separately and then summed, and at a net exactly equal to
    the threshold the bonus portion is zero because the bonus applies only to
    the amount strictly above it."

    Design: Corner/calculations/royalty_exactly_at_threshold_earns_no_bonus
    """
    world = setup_selling_show(
        tour_name="CA1 Tour", city="Barstow", venue_name="CA1 Hall",
        show_date="2026-09-03T20:00:00Z", flat_commission_bps=2000,
        price_cents=5000, total_units=300, num_sellers=2,
        product_overrides={"sku": "CA1-TEE", "name": "Tee",
                           "base_price_cents": 5000})
    staff_session(world, seller_index=0, sales=[(125, "CASH")],
                  counted_cash_cents=630000, verify=True, verify_by_index=1)
    settlement = reach_settlement(world, "RECONCILED")

    assert settlement["final_gross_cents"] == 625000
    assert settlement["venue_commission_final_cents"] == 125000, (
        "625000 x 2000 bps")
    assert settlement["net_to_tour_cents"] == 500000, "exactly the threshold"
    assert settlement["artist_royalty_cents"] == 50000, (
        "base tier only: the bonus segment is zero at equality")
    assert settlement["company_share_cents"] == 450000
    assert_settlement_final_figures(settlement)


def test_licensing_split_picks_max_per_product(api):
    """PRD §3.5: "Licensing is computed per `LICENSED` product sold at the show:
    for each such product, take the greater of
    `pinned_licensed_flat_per_unit_cents` multiplied by the product's total
    units sold there and the product's show gross multiplied by
    `pinned_licensed_rate_bps`, divided by 10000, and rounded half up;
    `licensing_cents` is the sum of those per-product maxima, and `STANDARD`
    products contribute nothing."

    Design: Corner/calculations/licensing_split_picks_max_per_product
    """
    tour = create_active_tour(name="CA2 Tour")
    show = create_show(tour["id"], city="Needles", venue_name="CA2 Hall",
                       show_date="2026-09-04T20:00:00Z")
    product_a = create_product(tour["id"], sku="CA2-LP", name="Vinyl LP",
                               royalty_treatment="LICENSED", base_price_cents=3000,
                               initial_stock_by_size={"OS": 200})
    product_b = create_product(tour["id"], sku="CA2-PIN", name="Pin Set",
                               royalty_treatment="LICENSED", base_price_cents=2000,
                               initial_stock_by_size={"OS": 200})
    create_show_product(show["id"], product_a["id"], 3000)
    create_show_product(show["id"], product_b["id"], 2000)
    alloc_a = generate_allocations(show["id"], product_a["id"], 50)[0]
    alloc_b = generate_allocations(show["id"], product_b["id"], 50)[0]
    seller_a = create_seller(tour["id"], display_name="Seller A", seller_code="CA2-A")
    seller_b = create_seller(tour["id"], display_name="Seller B", seller_code="CA2-B")
    open_show(show["id"])
    session = create_seller_session(show["id"], seller_a["id"], 5000)
    record_sale(session["id"], alloc_a["id"], 10, "CASH", seller_a["id"])
    record_sale(session["id"], alloc_b["id"], 10, "CASH", seller_a["id"])
    count_out_session(session["id"], 55000, seller_a["id"])
    verify_session(session["id"], make_seller_headers(seller_b["id"]))
    world = {"show": show}
    settlement = reach_settlement(world, "RECONCILED")

    assert settlement["final_gross_cents"] == 50000
    assert settlement["licensing_cents"] == 11000, (
        "A: max(500x10, 2000bps x 30000) = 6000 percentage arm; "
        "B: max(500x10, 2000bps x 20000) = 5000 flat arm")
    assert settlement["venue_commission_final_cents"] == 7500
    assert settlement["net_to_tour_cents"] == 42500
    assert settlement["artist_royalty_cents"] == 4250
    assert settlement["company_share_cents"] == 27250
    assert_settlement_final_figures(settlement)


class TestSettlementDisputeReconcileCycle:
    def _reconciled_world(self, api):
        world = setup_selling_show(tour_name="NL1 Tour", city="Fresno",
                                   venue_name="NL1 Hall",
                                   show_date="2026-08-16T20:00:00Z",
                                   total_units=300, num_sellers=2)
        staff_session(world, seller_index=0, sales=[(100, "CASH")],
                      counted_cash_cents=405000, verify=True, verify_by_index=1)
        settlement = reach_settlement(world, "RECONCILED")
        assert settlement["final_gross_cents"] == 400000
        assert settlement["venue_commission_final_cents"] == 60000
        return world, settlement

    def test_dispute_records_reason_and_moves_to_disputed(self, api):
        """PRD §3.5: "A `VenueRep` or `TourManager` may dispute it — the
        settlement must be `RECONCILED`, otherwise
        `ERR_SETTLEMENT_NOT_RECONCILED` — supplying a `reason` that is recorded
        on `dispute_reason`, moving the settlement to `DISPUTED`."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_reconcile_cycle_recomputes
        """
        _world, settlement = self._reconciled_world(api)

        disputed = dispute_settlement(
            settlement["id"], "Venue contests a misrecorded cash drop",
            headers=VENUE1)
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "Venue contests a misrecorded cash drop"

    def test_resolve_recomputes_from_current_register(self, api):
        """PRD §3.5: "An `Accountant` then resolves the dispute, moving it back
        from `DISPUTED` to `RECONCILED` (a settlement in any other status fails
        with `ERR_INVALID_SETTLEMENT_STATE`); resolution recomputes every final,
        royalty, licensing, and company figure from the current register state,
        so audit voids recorded during the dispute flow into the numbers, and
        `reconciled_by_user_id` is updated to the resolving accountant."
        PRD §3.8: "An `Accountant` performs the audit void once the money is
        under review: the parent show must be `RECONCILING` and its settlement
        `PROVISIONAL` or `DISPUTED`, so an audit void attempted after
        reconciliation has produced final figures fails with
        `ERR_INVALID_SETTLEMENT_STATE`."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_reconcile_cycle_recomputes
        """
        world, settlement = self._reconciled_world(api)
        dispute_settlement(settlement["id"],
                           "Venue contests a misrecorded cash drop",
                           headers=VENUE1)

        sale = world["sale_records"][0]
        voided = get_success_data(api.void_sale_record(
            sale["id"], {"void_reason": "audit: duplicate register entry"},
            ACCT1))
        assert voided["status"] == "VOIDED", "audit void succeeds during DISPUTED"

        resolved = get_success_data(api.resolve_settlement(settlement["id"], ACCT1))
        assert resolved["status"] == "RECONCILED", "the cycle closes"
        assert resolved["final_gross_cents"] == 0, (
            "the voided sale is excluded from the register")
        assert resolved["venue_commission_final_cents"] == 0
        assert resolved["artist_royalty_cents"] == 0
        assert resolved["company_share_cents"] == 0
        assert resolved["provisional_gross_cents"] == 400000, (
            "the provisional snapshot is never recomputed")
        assert_settlement_final_figures(resolved)


def _finalized_world(api, tour_name="SM3 Tour", city="Madera",
                     venue_name="SM3 Hall", show_date="2026-08-31T20:00:00Z"):
    world = setup_selling_show(
        tour_name=tour_name, city=city, venue_name=venue_name,
        show_date=show_date, price_cents=2000, total_units=100, num_sellers=2,
        product_overrides={"sku": f"{tour_name[:2]}-CAP", "name": "Cap",
                           "base_price_cents": 2000,
                           "initial_stock_by_size": {"OS": 500}})
    staff_session(world, seller_index=0, sales=[(8, "CASH")],
                  counted_cash_cents=21000, verify=True, verify_by_index=1)
    reach_settlement(world, "FINALIZED")
    return world


def test_settlement_dispute_after_finalize_rejected(api):
    """PRD §3.5: "A `VenueRep` or `TourManager` may dispute it — the settlement
    must be `RECONCILED`, otherwise `ERR_SETTLEMENT_NOT_RECONCILED` — supplying
    a `reason` that is recorded on `dispute_reason`, moving the settlement to
    `DISPUTED`."
    PRD §3.5: "An `Accountant` may rebase while the settlement is `PROVISIONAL`,
    `DISPUTED`, or `RECONCILED`; rebasing a `FINALIZED` settlement is rejected
    with `ERR_INVALID_SETTLEMENT_STATE`."

    Design: Corner/state_machines/settlement_dispute_after_finalize_rejected
    """
    world = _finalized_world(api)
    settlement_id = world["settlement"]["id"]

    resp = api.dispute_settlement(settlement_id, dispute_payload("too late"),
                                  VENUE1)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_RECONCILED)

    resp2 = api.rebase_royalty(settlement_id, ACCT1)
    validate_error(resp2, ApiErrorId.ERR_INVALID_SETTLEMENT_STATE)

    assert get_settlement(settlement_id)["status"] == "FINALIZED"


def test_venue_rep_cannot_reconcile(api):
    """PRD §2.1: "A caller whose authenticated role is not in an endpoint's
    authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | /merch/settlements/{id}/reconcile | Transition the
    settlement `PROVISIONAL` → `RECONCILED`; requires all sessions `VERIFIED`;
    computes register-based final figures against the pinned snapshot |
    Accountant |"

    Design: Corner/rbac/venue_rep_cannot_reconcile
    """
    world = setup_selling_show(tour_name="RB3 Tour", city="Casper",
                               venue_name="RB3 Hall",
                               show_date="2026-09-19T20:00:00Z", num_sellers=1)
    staff_session(world, counted_cash_cents=5000, verify=False)
    settlement = reach_settlement(world, "PROVISIONAL")

    resp = api.reconcile_settlement(settlement["id"], VENUE1)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_settlement(settlement["id"])["status"] == "PROVISIONAL"


def test_finalize_by_same_accountant_rejected_sod(api):
    """PRD §3.5: "The settlement must be `RECONCILED` (otherwise
    `ERR_SETTLEMENT_NOT_RECONCILED`); the finalizer's `X-User-ID` must differ
    from `reconciled_by_user_id` under §2.8 (otherwise
    `ERR_SEGREGATION_OF_DUTIES`); and the pinned royalty snapshot must equal the
    tour's current royalty configuration — if the tour's terms were patched
    after the snapshot was pinned, finalization fails with
    `ERR_STALE_ROYALTY_CONFIG`, and the remedy is to rebase first."
    PRD §2.8: "The same `X-User-ID` may not stand on both sides of any pair: the
    verifier of a seller session must differ from that session's seller; the
    finalizer of a settlement must differ from the accountant recorded in the
    settlement's `reconciled_by_user_id`; and the receiver of a shipment must
    differ from the user recorded in `dispatched_by_user_id`. Violating any of
    the three is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/finalize_by_same_accountant_rejected_sod
    """
    world = setup_selling_show(
        tour_name="VA5 Tour", city="Huron", venue_name="VA5 Hall",
        show_date="2026-09-10T20:00:00Z", price_cents=2000, total_units=100,
        num_sellers=2,
        product_overrides={"sku": "VA5-CAP", "name": "Cap",
                           "base_price_cents": 2000,
                           "initial_stock_by_size": {"OS": 500}})
    staff_session(world, seller_index=0, sales=[(8, "CASH")],
                  counted_cash_cents=21000, verify=True, verify_by_index=1)
    settlement = reach_settlement(world, "RECONCILED")

    resp = api.finalize_settlement(settlement["id"], ACCT1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    finalized = get_success_data(api.finalize_settlement(settlement["id"], ACCT2))
    assert finalized["status"] == "FINALIZED"
