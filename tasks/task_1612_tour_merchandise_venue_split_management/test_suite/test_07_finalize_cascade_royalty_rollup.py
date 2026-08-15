"""Finalization cascade, stale-snapshot remediation, the tour royalty rollup,
and show close-out."""
from test_helpers import (
    ACCT1,
    ACCT2,
    ApiErrorId,
    TM1,
    assert_allocation_conservation,
    closeout_payload,
    count_out_session,
    create_active_tour,
    create_product,
    create_seller,
    create_seller_session,
    create_show_product,
    finalize_settlement,
    generate_allocations,
    get_allocation,
    get_product,
    get_session,
    get_show,
    get_success_data,
    get_tour,
    make_seller_headers,
    open_show,
    patch_royalty_config,
    place_online_order,
    fulfill_online_order,
    reach_settlement,
    record_sale,
    setup_selling_show,
    staff_session,
    validate_error,
    verify_session,
)


def test_stale_royalty_config_blocks_finalize_until_rebase(api):
    """PRD §3.5: "The settlement must be `RECONCILED` (otherwise
    `ERR_SETTLEMENT_NOT_RECONCILED`); the finalizer's `X-User-ID` must differ
    from `reconciled_by_user_id` under §2.8 (otherwise
    `ERR_SEGREGATION_OF_DUTIES`); and the pinned royalty snapshot must equal the
    tour's current royalty configuration — if the tour's terms were patched
    after the snapshot was pinned, finalization fails with
    `ERR_STALE_ROYALTY_CONFIG`, and the remedy is to rebase first."
    PRD §3.5: "When the settlement is `RECONCILED` at rebase time,
    `artist_royalty_cents`, `licensing_cents`, and `company_share_cents` are
    immediately recomputed from the unchanged `final_gross_cents` and
    `venue_commission_final_cents` using the new snapshot; in `PROVISIONAL` or
    `DISPUTED` the re-pin alone suffices because the figures will be computed
    (or recomputed) at the next reconcile or resolve."

    Design: Corner/validations/stale_royalty_config_blocks_finalize_until_rebase
    """
    world = setup_selling_show(
        tour_name="VA7 Tour", city="Aberdeen", venue_name="VA7 Hall",
        show_date="2026-09-11T20:00:00Z", price_cents=2000, total_units=100,
        num_sellers=2,
        product_overrides={"sku": "VA7-CAP", "name": "Cap",
                           "base_price_cents": 2000,
                           "initial_stock_by_size": {"OS": 500}})
    staff_session(world, seller_index=0, sales=[(8, "CASH")],
                  counted_cash_cents=21000, verify=True, verify_by_index=1)
    settlement = reach_settlement(world, "RECONCILED")
    assert settlement["final_gross_cents"] == 16000
    assert settlement["net_to_tour_cents"] == 13600
    assert settlement["artist_royalty_cents"] == 1360

    # Patching the tour's terms after the snapshot was pinned makes it stale.
    tour_version = get_tour(world["tour"]["id"])["version"]
    patch_royalty_config(world["tour"]["id"], tour_version,
                         standard_rate_bps=2000)

    resp = api.finalize_settlement(settlement["id"], ACCT2)
    validate_error(resp, ApiErrorId.ERR_STALE_ROYALTY_CONFIG)

    rebased = get_success_data(api.rebase_royalty(settlement["id"], ACCT1))
    assert rebased["status"] == "RECONCILED", "rebase never changes status"
    assert rebased["pinned_standard_rate_bps"] == 2000
    assert rebased["final_gross_cents"] == 16000, "the register base is unchanged"
    assert rebased["venue_commission_final_cents"] == 2400
    assert rebased["artist_royalty_cents"] == 2720, "13600 x 2000 bps"
    assert rebased["company_share_cents"] == 10880

    finalized = finalize_settlement(settlement["id"], ACCT2)
    assert finalized["status"] == "FINALIZED"


class TestFinalizeCascadeShowThenSessions:
    def _reconciled_two_session_world(self, api):
        world = setup_selling_show(
            tour_name="TC2 Tour", city="Provo", venue_name="TC2 Arena",
            show_date="2026-08-19T20:00:00Z", price_cents=2000, total_units=100,
            num_sellers=2,
            product_overrides={"sku": "TC2-CAP", "name": "Cap",
                               "base_price_cents": 2000,
                               "initial_stock_by_size": {"OS": 500}})
        staff_session(world, seller_index=0, sales=[(5, "CASH")],
                      counted_cash_cents=15000, verify=True, verify_by_index=1)
        staff_session(world, seller_index=1, sales=[(3, "CASH")],
                      counted_cash_cents=11000, verify=True, verify_by_index=0)
        settlement = reach_settlement(world, "RECONCILED")
        return world, settlement

    def test_finalize_settles_show_and_computes_figures(self, api):
        """PRD §3.5: "A successful finalize moves the settlement to `FINALIZED`
        and cascades outward: the parent show transitions from `RECONCILING` to
        `SETTLED`, and every `VERIFIED` session of the show locks, moving from
        `VERIFIED` to `LOCKED`."

        Design: Difficulty/transitive_cascade/finalize_cascade_show_then_sessions
        """
        world, settlement = self._reconciled_two_session_world(api)
        assert settlement["final_gross_cents"] == 16000
        assert settlement["venue_commission_final_cents"] == 2400
        assert settlement["artist_royalty_cents"] == 1360
        assert settlement["company_share_cents"] == 12240

        finalized = finalize_settlement(settlement["id"], ACCT2)
        assert finalized["status"] == "FINALIZED"
        assert get_show(world["show"]["id"])["status"] == "SETTLED", (
            "link 1: the parent show bubbles up to SETTLED")

    def test_finalize_locks_every_verified_session(self, api):
        """PRD §3.5: "A successful finalize moves the settlement to `FINALIZED`
        and cascades outward: the parent show transitions from `RECONCILING` to
        `SETTLED`, and every `VERIFIED` session of the show locks, moving from
        `VERIFIED` to `LOCKED`."

        Design: Difficulty/transitive_cascade/finalize_cascade_show_then_sessions
        """
        world, settlement = self._reconciled_two_session_world(api)
        session_a = world["sessions"][0]
        session_b = world["sessions"][1]
        assert session_a["status"] == "VERIFIED"
        assert session_b["status"] == "VERIFIED"

        finalize_settlement(settlement["id"], ACCT2)

        assert get_session(session_a["id"])["status"] == "LOCKED", (
            "link 2: sessions lock with no direct session call")
        assert get_session(session_b["id"])["status"] == "LOCKED"


def test_tour_royalty_rollup_counts_only_finalized_and_fulfilled(api):
    """PRD §3.1: "Reading a single tour reports `royalty_payable_cents`,
    computed on read as the sum of `artist_royalty_cents` plus
    `licensing_cents` over the tour's `FINALIZED` settlements, plus the sum of
    `artist_royalty_final_cents` plus `licensing_final_cents` over the tour's
    `FULFILLED` online orders; provisional, reconciled, or disputed settlements
    and placed or cancelled orders contribute nothing."

    Design: Corner/calculations/tour_royalty_rollup_counts_only_finalized_and_fulfilled
    """
    world = setup_selling_show(
        tour_name="CA4 Tour", city="Indio", venue_name="CA4 Hall",
        show_date="2026-09-06T20:00:00Z", price_cents=2000, total_units=100,
        num_sellers=2,
        product_overrides={"sku": "CA4-CAP", "name": "Cap",
                           "base_price_cents": 2000,
                           "initial_stock_by_size": {"OS": 500}})
    staff_session(world, seller_index=0, sales=[(8, "CASH")],
                  counted_cash_cents=21000, verify=True, verify_by_index=1)
    settlement = reach_settlement(world, "FINALIZED")
    assert settlement["artist_royalty_cents"] == 1360
    assert settlement["licensing_cents"] == 0

    poster = get_success_data(api.create_product(
        {"tour_id": world["tour"]["id"], "sku": "CA4-POSTER", "name": "Poster",
         "product_type": "REGULAR", "royalty_treatment": "STANDARD",
         "sized": False, "base_price_cents": 5000,
         "initial_stock_by_size": {"OS": 100}}, TM1))
    order_fulfilled = place_online_order(world["tour"]["id"], poster["id"], 2)
    fulfilled = fulfill_online_order(order_fulfilled["id"])
    assert fulfilled["artist_royalty_final_cents"] == 1000

    order_placed = place_online_order(world["tour"]["id"], poster["id"], 1)
    assert order_placed["status"] == "PLACED"
    assert order_placed["artist_royalty_provisional_cents"] == 500

    tour = get_tour(world["tour"]["id"])
    assert tour["royalty_payable_cents"] == 2360, (
        "1360 (FINALIZED settlement) + 1000 (FULFILLED order); "
        "the PLACED order contributes nothing")


class TestCloseoutCascade:
    def _settled_world(self, api):
        world = setup_selling_show(tour_name="TC1 Tour", city="Reno",
                                   venue_name="TC1 Hall",
                                   show_date="2026-08-18T20:00:00Z",
                                   total_units=300, num_sellers=2)
        staff_session(world, seller_index=0, sales=[(50, "CASH")],
                      counted_cash_cents=205000, verify=True, verify_by_index=1)
        reach_settlement(world, "FINALIZED")
        return world

    def test_closeout_applies_lines_and_restocks_warehouse(self, api):
        """PRD §3.6: "Close-out writes the residue onto every lined allocation:
        `quantity_returned` and `quantity_liquidated` come from the lines, and
        `quantity_shrunk` takes whatever remains — the on-hand units neither
        returned nor liquidated — so that afterwards a strict conservation
        invariant holds per allocation: `quantity_allocated` equals
        `quantity_sold` plus `quantity_returned` plus `quantity_liquidated` plus
        `quantity_shrunk`."
        PRD §3.6: "Returned units flow back into the product's
        `warehouse_stock_by_size` per size, as described in §3.3."

        Design: Difficulty/transitive_cascade/closeout_cascade_allocation_show_tour
        """
        world = self._settled_world(api)
        allocation_id = world["allocation"]["id"]

        get_success_data(api.close_out_show(
            world["show"]["id"],
            closeout_payload(
                [{"allocation_id": allocation_id, "action": "RETURN",
                  "quantity": 200},
                 {"allocation_id": allocation_id, "action": "LIQUIDATE",
                  "quantity": 50}],
                actual_proceeds_cents=25000, handling_fee_cents=5000),
            TM1))

        allocation = get_allocation(allocation_id)
        assert allocation["quantity_returned"] == 200
        assert allocation["quantity_liquidated"] == 50
        assert allocation["quantity_shrunk"] == 0
        assert_allocation_conservation(allocation)

        product = get_product(world["product"]["id"])
        assert product["warehouse_stock_by_size"]["OS"] == 1200, (
            "1000 initial + 200 returned")

    def test_closeout_closes_show_and_auto_closes_tour(self, api):
        """PRD §3.6: "The show records `closeout_credit_cents` as
        `actual_proceeds_cents` minus `handling_fee_cents` and moves from
        `SETTLED` to `CLOSED`. If that close-out removed the tour's last
        non-terminal show — no other show remains outside `CLOSED` or
        `CANCELLED` — the tour automatically follows, transitioning from
        `ACTIVE` to `CLOSED` without any manual close call."

        Design: Difficulty/transitive_cascade/closeout_cascade_allocation_show_tour
        """
        world = self._settled_world(api)
        assert get_show(world["show"]["id"])["status"] == "SETTLED"

        closed = get_success_data(api.close_out_show(
            world["show"]["id"],
            closeout_payload(
                [{"allocation_id": world["allocation"]["id"],
                  "action": "RETURN", "quantity": 200},
                 {"allocation_id": world["allocation"]["id"],
                  "action": "LIQUIDATE", "quantity": 50}],
                actual_proceeds_cents=25000, handling_fee_cents=5000),
            TM1))
        assert closed["status"] == "CLOSED"
        assert closed["closeout_credit_cents"] == 20000, "25000 - 5000"

        assert get_tour(world["tour"]["id"])["status"] == "CLOSED", (
            "the last non-terminal show closing auto-closes the tour")


def test_closeout_requires_complete_lines(api):
    """PRD §3.6: "The tour manager submits `lines` covering the show's
    allocations: every allocation row whose `quantity_on_hand` is positive must
    appear in the lines exactly once, and an omitted row fails with
    `ERR_CLOSEOUT_INCOMPLETE`."

    Design: Corner/endpoints/closeout_requires_complete_lines
    """
    tour = create_active_tour(name="EP4 Tour")
    show = get_success_data(api.create_show(
        {"tour_id": tour["id"], "city": "Bozeman", "venue_name": "EP4 Hall",
         "show_date": "2026-09-16T20:00:00Z", "commission_mode": "FLAT",
         "flat_commission_bps": 1500}, TM1))
    p1 = create_product(tour["id"], sku="EP4-TEE", name="Tee",
                        base_price_cents=4000, initial_stock_by_size={"OS": 500})
    p2 = create_product(tour["id"], sku="EP4-HAT", name="Hat",
                        base_price_cents=3000, initial_stock_by_size={"OS": 500})
    create_show_product(show["id"], p1["id"], 4000)
    create_show_product(show["id"], p2["id"], 3000)
    a1 = generate_allocations(show["id"], p1["id"], 50)[0]
    a2 = generate_allocations(show["id"], p2["id"], 50)[0]
    seller_a = create_seller(tour["id"], display_name="Seller A", seller_code="EP4-A")
    seller_b = create_seller(tour["id"], display_name="Seller B", seller_code="EP4-B")
    open_show(show["id"])
    session = create_seller_session(show["id"], seller_a["id"], 5000)
    record_sale(session["id"], a1["id"], 5, "CASH", seller_a["id"])
    count_out_session(session["id"], 25000, seller_a["id"])
    verify_session(session["id"], make_seller_headers(seller_b["id"]))
    reach_settlement({"show": show}, "FINALIZED")

    resp = api.close_out_show(
        show["id"],
        closeout_payload(
            [{"allocation_id": a1["id"], "action": "RETURN", "quantity": 45}],
            actual_proceeds_cents=0, handling_fee_cents=0),
        TM1)
    validate_error(resp, ApiErrorId.ERR_CLOSEOUT_INCOMPLETE)

    show_after = get_show(show["id"])
    assert show_after["status"] == "SETTLED", "the show is unchanged"
    allocation2 = get_allocation(a2["id"])
    assert allocation2["quantity_returned"] == 0
    assert allocation2["quantity_liquidated"] == 0
    assert allocation2["quantity_on_hand"] == 50
