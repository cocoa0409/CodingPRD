"""Premium auction: sale-order generation and ordering, strict lot opening,
bounded reoffer cycle, buyer credit exposure, the close-sold cascade,
immediate consistency, and add-on pledge rules (PRD §3.6, §3.7, §2.7).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_posture,
    api_client,
    build_show_state,
    close_passed,
    close_sold,
    create_buyer,
    generate_lots,
    get_buyer_invoice,
    get_disposition,
    get_entry,
    get_lot,
    list_dispositions,
    make_buyer_headers,
    no_sale_lot,
    open_lot,
    reoffer_lot,
    setup_sold_lot,
    standard_shown_entry,
    validate_error,
    validate_success,
    create_add_on_payload,
)

ADMIN = TEST_USERS["admin"]
AUCTIONEER = TEST_USERS["auctioneer"]


def _lots_by_number(gen):
    """Map lot_number -> lot for the lots named in a generate response."""
    lots = {}
    for lot_id in gen["lot_ids"]:
        lot = get_lot(lot_id)
        lots[lot["lot_number"]] = lot
    return lots


def _two_steer_lots(name):
    """Two SHOWN steers ranked 1 and 2 in one class; lots generated."""
    ctx = build_show_state(
        fair_overrides={"name": name},
        entries=[
            {"species": "MARKET_STEER", "tag_number": "S-001",
             "weight_lbs": 1200},
            {"species": "MARKET_STEER", "tag_number": "S-002",
             "weight_lbs": 1210},
        ],
        classes=[{"species": "MARKET_STEER", "class_code": "STEER-A",
                  "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                  "capacity": 5}],
        entry_class_map={0: 0, 1: 0},
        judges=[{"qualified_species": ["MARKET_STEER"]}],
        slots=[{"class_index": 0, "judge_index": 0}],
        placings=[{
            "slot_index": 0,
            "lines": [
                {"entry_index": 0, "rank": 1, "award": "NONE"},
                {"entry_index": 1, "rank": 2, "award": "NONE"},
            ],
        }],
        advance_to="AUCTION",
    )
    gen = generate_lots(ctx["fair"]["id"])
    return ctx, _lots_by_number(gen)


class TestLotGenerationAndOrdering:
    def test_lot_open_strictly_in_lot_number_order(self, api):
        """PRD §3.6: "Opening a lot moves it `QUEUED` → `OPEN`, and requires
        every lot of the fair with a smaller `lot_number` to be past `QUEUED`
        already; opening out of order is rejected with `ERR_INVALID_STATE`."
        PRD §3.6: "Eligible entries are ordered by award tier first —
        `GRAND_CHAMPION` before `RESERVE_CHAMPION` before `NONE` — then by
        their species' position in `species_sale_order`, then by `rank`
        ascending, then by the entry's `created_at` ascending; `id` never
        participates in the ordering."

        Design: Corner/calculations/lot_open_strictly_in_lot_number_order
        """
        ctx, lots = _two_steer_lots("Fair K5")
        assert set(lots.keys()) == {1, 2}

        early = api_client.open_lot(lots[2]["id"], AUCTIONEER)
        validate_error(early, ApiErrorId.ERR_INVALID_STATE)

        first = open_lot(lots[1]["id"])
        assert first["status"] == "OPEN"
        second = open_lot(lots[2]["id"])
        assert second["status"] == "OPEN"

    def test_lot_number_one_is_the_rank_one_entry(self, api):
        """PRD §3.6: "Eligible entries are ordered by award tier first —
        `GRAND_CHAMPION` before `RESERVE_CHAMPION` before `NONE` — then by
        their species' position in `species_sale_order`, then by `rank`
        ascending, then by the entry's `created_at` ascending; `id` never
        participates in the ordering."
        PRD §3.6: "The entry moves `SHOWN` → `SOLD`."

        Design: Corner/calculations/lot_open_strictly_in_lot_number_order
        """
        ctx, lots = _two_steer_lots("Fair K5-order")
        buyer = create_buyer(ctx["fair"]["id"], credit_limit_cents=1000000)
        open_lot(lots[1]["id"])
        close_sold(lots[1]["id"], buyer["id"], 1000)
        assert get_entry(ctx["entries"][0]["id"])["status"] == "SOLD", (
            "lot_number 1 covers the rank-1 entry (rank ascending)"
        )
        assert get_entry(ctx["entries"][1]["id"])["status"] == "SHOWN"

    def test_generate_lots_excludes_entries_beyond_sale_threshold(self, api):
        """PRD §3.6: "An entry is eligible for a lot when it is `SHOWN`, no
        lot already references it, its exhibitor is still `ACTIVE`, its health
        record is clean — no inspection of the entry has result `FAIL`, and
        the latest inspection by `created_at`, if any exists, is `PASS` — and
        it earned its way in: either its placing's `award` is not `NONE`, or
        its `rank` is at or under the species threshold in
        `sale_rank_threshold`, with the boundary inclusive."
        PRD §3.6: "Lots receive `lot_number` values gapless from 1 in that
        order, and the response returns the created `lot_ids` and a
        `lot_count`."

        Design: Corner/calculations/generate_lots_excludes_entries_beyond_sale_threshold
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair K6"},
            entries=[
                {"species": "MARKET_LAMB", "tag_number": f"L-00{i}",
                 "weight_lbs": 99 + i}
                for i in range(1, 5)
            ],
            classes=[{"species": "MARKET_LAMB", "class_code": "LAMB-A",
                      "weight_min_lbs": 90, "weight_max_lbs": 120,
                      "capacity": 5}],
            entry_class_map={0: 0, 1: 0, 2: 0, 3: 0},
            judges=[{"qualified_species": ["MARKET_LAMB"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            placings=[{
                "slot_index": 0,
                "lines": [
                    {"entry_index": i, "rank": i + 1, "award": "NONE"}
                    for i in range(4)
                ],
            }],
            advance_to="AUCTION",
        )
        # sale_rank_threshold[MARKET_LAMB] == 3 (fixture default).
        gen = generate_lots(ctx["fair"]["id"])
        assert gen["lot_count"] == 3, (
            "ranks 1..3 are eligible; rank 4 exceeds the threshold"
        )
        lots = _lots_by_number(gen)
        assert set(lots.keys()) == {1, 2, 3}, "lot numbers gapless from 1"

        buyer = create_buyer(ctx["fair"]["id"], credit_limit_cents=10000000)
        for number in (1, 2, 3):
            open_lot(lots[number]["id"])
            close_sold(lots[number]["id"], buyer["id"], 1000)
        for i in range(3):
            assert get_entry(ctx["entries"][i]["id"])["status"] == "SOLD"
        assert get_entry(ctx["entries"][3]["id"])["status"] == "SHOWN", (
            "the rank-4 lamb received no lot and was never sold"
        )

    def test_auction_order_champions_first_then_species_order(self, api):
        """PRD §3.6: "Eligible entries are ordered by award tier first —
        `GRAND_CHAMPION` before `RESERVE_CHAMPION` before `NONE` — then by
        their species' position in `species_sale_order`, then by `rank`
        ascending, then by the entry's `created_at` ascending; `id` never
        participates in the ordering."

        Design: Corner/calculations/auction_order_champions_first_then_species_order
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair K7"},
            entries=[
                {"species": "MARKET_STEER", "tag_number": "S-001",
                 "weight_lbs": 1200},
                {"species": "MARKET_SWINE", "tag_number": "P-001",
                 "weight_lbs": 260},
            ],
            classes=[
                {"species": "MARKET_STEER", "class_code": "STEER-A",
                 "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                 "capacity": 5},
                {"species": "MARKET_SWINE", "class_code": "SWINE-A",
                 "weight_min_lbs": 200, "weight_max_lbs": 300, "capacity": 5},
            ],
            entry_class_map={0: 0, 1: 1},
            judges=[{"qualified_species": ["MARKET_STEER", "MARKET_SWINE"]}],
            slots=[
                {"class_index": 0, "judge_index": 0, "ring_name": "MAIN",
                 "starts_at": "2026-07-10T09:00:00Z",
                 "ends_at": "2026-07-10T10:00:00Z"},
                {"class_index": 1, "judge_index": 0, "ring_name": "MAIN",
                 "starts_at": "2026-07-10T10:15:00Z",
                 "ends_at": "2026-07-10T11:00:00Z"},
            ],
            placings=[
                {"slot_index": 0,
                 "lines": [{"entry_index": 0, "rank": 1, "award": "NONE"}]},
                {"slot_index": 1,
                 "lines": [{"entry_index": 1, "rank": 1,
                            "award": "GRAND_CHAMPION"}]},
            ],
            advance_to="AUCTION",
        )
        gen = generate_lots(ctx["fair"]["id"])
        assert gen["lot_count"] == 2
        lots = _lots_by_number(gen)

        # Sell lot_number 1; the entry that turns SOLD reveals the ordering.
        buyer = create_buyer(ctx["fair"]["id"], credit_limit_cents=10000000)
        open_lot(lots[1]["id"])
        close_sold(lots[1]["id"], buyer["id"], 1000)
        assert get_entry(ctx["entries"][1]["id"])["status"] == "SOLD", (
            "lot 1 is the GRAND_CHAMPION swine: award tier dominates the "
            "species order (steer precedes swine)"
        )
        assert get_entry(ctx["entries"][0]["id"])["status"] == "SHOWN", (
            "the rank-1 NONE steer waits at lot 2"
        )


class TestReofferCycle:
    def _open_lot_context(self, name):
        ctx = standard_shown_entry(fair_overrides={"name": name},
                                   advance_to="AUCTION")
        gen = generate_lots(ctx["fair"]["id"])
        lot_id = gen["lot_ids"][0]
        open_lot(lot_id)
        return ctx, lot_id

    def test_lot_passed_reoffer_cycle_bounded(self, api):
        """PRD §3.6: "A passed lot may be reoffered, moving `PASSED` → `OPEN`
        and incrementing `reoffer_count` by one, but only while
        `reoffer_count` is below 2 — a third reoffer is rejected with
        `ERR_REOFFER_LIMIT_REACHED` (HTTP 409). Declaring no-sale moves a
        `PASSED` lot to `NO_SALE` and drops the entry `SHOWN` → `NOT_SOLD`."

        Design: Difficulty/non_linear_state_machine/lot_passed_reoffer_cycle_bounded
        """
        ctx, lot_id = self._open_lot_context("Fair R3B")

        close_passed(lot_id)
        first = reoffer_lot(lot_id)
        assert first["reoffer_count"] == 1
        close_passed(lot_id)
        second = reoffer_lot(lot_id)
        assert second["reoffer_count"] == 2
        close_passed(lot_id)

        third = api_client.reoffer_lot(lot_id, AUCTIONEER)
        validate_error(third, ApiErrorId.ERR_REOFFER_LIMIT_REACHED)
        assert get_lot(lot_id)["status"] == "PASSED"

        no_sale = no_sale_lot(lot_id)
        assert no_sale["status"] == "NO_SALE"
        assert get_entry(ctx["entries"][0]["id"])["status"] == "NOT_SOLD"

    def test_reoffer_and_no_sale_rejected_from_open(self, api):
        """PRD §2.7: "state validity for the requested transition, including
        terminal-state lockdown, non-adjacent posture advance, settlement and
        closure guards, reoffer from a non-`PASSED` lot, double issue or
        double void, and lots opened out of order (failure:
        `ERR_INVALID_STATE`)".
        PRD §3.6: "Declaring no-sale moves a `PASSED` lot to `NO_SALE` and
        drops the entry `SHOWN` → `NOT_SOLD`."

        Design: Difficulty/non_linear_state_machine/lot_passed_reoffer_cycle_bounded
        """
        ctx, lot_id = self._open_lot_context("Fair R3B-open")

        reoffer_open = api_client.reoffer_lot(lot_id, AUCTIONEER)
        validate_error(reoffer_open, ApiErrorId.ERR_INVALID_STATE)
        nosale_open = api_client.no_sale_lot(lot_id, AUCTIONEER)
        validate_error(nosale_open, ApiErrorId.ERR_INVALID_STATE)

        passed = close_passed(lot_id)
        assert passed["status"] == "PASSED"
        reoffered = reoffer_lot(lot_id)
        assert reoffered["status"] == "OPEN"
        assert reoffered["reoffer_count"] == 1


class TestBuyerCreditExposure:
    def test_buyer_credit_equality_passes_one_cent_over_fails(self, api):
        """PRD §3.6: "the buyer's committed total is the sum of
        `hammer_price_cents` across their `SOLD` lots that are not on a `PAID`
        invoice, plus the sum of `amount_cents` across their pledges in
        `PLEDGED` or `INVOICED` status; the committed total plus the new
        `hammer_price_cents` must not exceed the buyer's `credit_limit_cents`.
        The boundary is inclusive — equality passes — and one cent over is
        rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/calculations/buyer_credit_equality_passes_one_cent_over_fails
        """
        ctx, lots = _two_steer_lots("Fair K3")
        buyer = create_buyer(ctx["fair"]["id"], credit_limit_cents=100000)

        open_lot(lots[1]["id"])
        sold = close_sold(lots[1]["id"], buyer["id"], 100000)
        assert sold["status"] == "SOLD", "equality with the limit passes"

        open_lot(lots[2]["id"])
        resp = api_client.close_sold(lots[2]["id"], buyer["id"], 1, AUCTIONEER)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_lot(lots[2]["id"])["status"] == "OPEN", (
            "100000 committed + 1 exceeds the 100000 limit"
        )


class TestCloseSoldErrorPrecedence:
    def _queued_lot_with_tiny_credit_buyer(self, name):
        ctx = standard_shown_entry(fair_overrides={"name": name},
                                   advance_to="AUCTION")
        buyer = create_buyer(ctx["fair"]["id"], business_name="Tiny Credit LLC",
                             credit_limit_cents=10)
        gen = generate_lots(ctx["fair"]["id"])
        return ctx, gen["lot_ids"][0], buyer

    def test_close_sold_state_beats_credit_limit(self, api):
        """PRD §2.7: "Validation on every endpoint is priority-ordered, and
        the first failure wins — an earlier failure masks later ones."
        PRD §2.7: "state validity for the requested transition, including
        terminal-state lockdown, non-adjacent posture advance, settlement and
        closure guards, reoffer from a non-`PASSED` lot, double issue or
        double void, and lots opened out of order (failure:
        `ERR_INVALID_STATE`)".

        Design: Difficulty/priority_pair_validation_conflict/close_sold_state_beats_credit_limit
        """
        _ctx, lot_id, buyer = self._queued_lot_with_tiny_credit_buyer("Fair R5A")
        resp = api_client.close_sold(lot_id, buyer["id"], 999999, AUCTIONEER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        lot = get_lot(lot_id)
        assert lot["status"] == "QUEUED"
        assert lot["buyer_id"] is None
        assert lot["hammer_price_cents"] is None

    def test_close_sold_from_passed_also_state_before_credit(self, api):
        """PRD §2.7: "Validation on every endpoint is priority-ordered, and
        the first failure wins — an earlier failure masks later ones."
        PRD §2.7: "state validity for the requested transition, including
        terminal-state lockdown, non-adjacent posture advance, settlement and
        closure guards, reoffer from a non-`PASSED` lot, double issue or
        double void, and lots opened out of order (failure:
        `ERR_INVALID_STATE`)".

        Design: Difficulty/priority_pair_validation_conflict/close_sold_state_beats_credit_limit
        """
        _ctx, lot_id, buyer = self._queued_lot_with_tiny_credit_buyer(
            "Fair R5A-passed"
        )
        open_lot(lot_id)
        close_passed(lot_id)
        resp = api_client.close_sold(lot_id, buyer["id"], 999999, AUCTIONEER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_lot(lot_id)["status"] == "PASSED"


class TestCloseSoldCascade:
    def test_close_sold_cascade_entry_disposition_invoice(self, api):
        """PRD §3.6: "A successful hammer close fires a four-part cascade. The
        lot records `buyer_id` and `hammer_price_cents`, and its
        `provisional_payout_cents` is computed as the hammer price minus the
        commission — the hammer price multiplied by the fair's
        `commission_rate`, rounded half-up to whole cents — minus the flat
        `yardage_fee_cents`. The entry moves `SHOWN` → `SOLD`. The sale
        requires harvest: a new disposition order is auto-created for the
        entry with `disposition_type` `HARVEST` in `REQUESTED` status and
        `created_by_user_id` recorded as `SYSTEM`, and any of the entry's
        pending `RETURN` orders in `REQUESTED` or `APPROVED` status are
        rejected with `reject_reason` `SALE_REQUIRES_HARVEST`. Finally, the
        buyer's `DRAFT` invoice is upserted — created on the buyer's first
        hammer, reused thereafter — and the lot line is added, with the draft
        totals live-recomputed per §3.7."

        Design: Difficulty/transitive_cascade/close_sold_cascade_entry_disposition_invoice
        """
        ctx = setup_sold_lot(hammer_price_cents=50000)
        lot = ctx["lot"]
        assert lot["status"] == "SOLD"
        assert lot["buyer_id"] == ctx["buyer"]["id"]
        assert lot["hammer_price_cents"] == 50000
        assert lot["provisional_payout_cents"] == 46000, (
            "50000 - round_half_up(50000*0.05)=2500 - 1500 yardage"
        )

        assert get_entry(ctx["entries"][0]["id"])["status"] == "SOLD"

        dispositions = list_dispositions()
        assert len(dispositions) == 1
        auto_order = dispositions[0]
        assert auto_order["disposition_type"] == "HARVEST"
        assert auto_order["status"] == "REQUESTED"
        assert auto_order["created_by_user_id"] == "SYSTEM"

        invoice = get_buyer_invoice(ctx["buyer"]["id"])
        assert invoice["status"] == "DRAFT"
        assert invoice["total_due_cents"] == 51500, (
            "hammer 50000 + round_half_up(50000*0.03)=1500 buyer premium"
        )

    def test_close_sold_rejects_pending_return_orders(self, api):
        """PRD §3.6: "The sale requires harvest: a new disposition order is
        auto-created for the entry with `disposition_type` `HARVEST` in
        `REQUESTED` status and `created_by_user_id` recorded as `SYSTEM`, and
        any of the entry's pending `RETURN` orders in `REQUESTED` or
        `APPROVED` status are rejected with `reject_reason`
        `SALE_REQUIRES_HARVEST`."

        Design: Difficulty/transitive_cascade/close_sold_cascade_entry_disposition_invoice
        """
        from test_helpers import (
            approve_disposition,
            create_disposition,
            make_admin_headers,
            sign_affidavit,
        )
        ctx = standard_shown_entry(fair_overrides={"name": "Fair R4B-ret"},
                                   advance_to="SHOWING")
        entry_id = ctx["entries"][0]["id"]
        exhibitor = ctx["exhibitors"][0]
        sign_affidavit(entry_id, exhibitor)
        pending_return = create_disposition(
            entry_id, creator_headers=make_admin_headers("admin-a"),
            disposition_type="RETURN",
        )
        approve_disposition(pending_return["id"], approver_id="admin-b")

        advance_posture(ctx["fair"]["id"], "AUCTION")
        buyer = create_buyer(ctx["fair"]["id"], credit_limit_cents=200000)
        gen = generate_lots(ctx["fair"]["id"])
        lot_id = gen["lot_ids"][0]
        open_lot(lot_id)
        close_sold(lot_id, buyer["id"], 50000)

        rejected = get_disposition(pending_return["id"])
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason"] == "SALE_REQUIRES_HARVEST"

        dispositions = list_dispositions()
        harvest = [d for d in dispositions if d["disposition_type"] == "HARVEST"]
        assert len(harvest) == 1
        assert harvest[0]["created_by_user_id"] == "SYSTEM"
        assert harvest[0]["status"] == "REQUESTED"


class TestImmediateConsistency:
    def test_sale_side_effects_visible_immediately_in_same_response(self, api):
        """PRD §3.6: "A successful hammer close fires a four-part cascade. The
        lot records `buyer_id` and `hammer_price_cents`, and its
        `provisional_payout_cents` is computed as the hammer price minus the
        commission — the hammer price multiplied by the fair's
        `commission_rate`, rounded half-up to whole cents — minus the flat
        `yardage_fee_cents`. The entry moves `SHOWN` → `SOLD`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        Design: Corner/consistency_model/sale_side_effects_visible_immediately_in_same_response
        """
        ctx = standard_shown_entry(fair_overrides={"name": "Fair M1"},
                                   advance_to="AUCTION")
        buyer = create_buyer(ctx["fair"]["id"], credit_limit_cents=200000)
        gen = generate_lots(ctx["fair"]["id"])
        lot_id = gen["lot_ids"][0]
        open_lot(lot_id)

        resp = api_client.close_sold(lot_id, buyer["id"], 50000, AUCTIONEER)
        data = validate_success(resp, 200)
        assert data["status"] == "SOLD"
        assert data["buyer_id"] == buyer["id"]
        assert data["hammer_price_cents"] == 50000
        assert data["provisional_payout_cents"] == 46000

        entry = get_entry(ctx["entries"][0]["id"])
        assert entry["status"] == "SOLD", (
            "the follow-up read shows the sale with no delay"
        )


class TestAddOnPledges:
    def _sold_lot_context(self, name):
        return setup_sold_lot(fair_overrides={"name": name},
                              hammer_price_cents=50000)

    def test_addon_on_unsold_lot_returns_lot_not_sold(self, api):
        """PRD §3.7: "The lot must be `SOLD` and not yet swept into an
        `ISSUED` invoice, otherwise the pledge is rejected with
        `ERR_LOT_NOT_SOLD` (HTTP 409); that lot-eligibility check runs before
        the amount check, which requires `amount_cents` greater than zero
        (else `ERR_INVALID_AMOUNT`)."

        Design: Corner/validations/addon_on_unsold_lot_returns_lot_not_sold
        """
        ctx = standard_shown_entry(fair_overrides={"name": "Fair V14"},
                                   advance_to="AUCTION")
        buyer = create_buyer(ctx["fair"]["id"], business_name="Boosters Club",
                             credit_limit_cents=200000)
        gen = generate_lots(ctx["fair"]["id"])
        lot_id = gen["lot_ids"][0]
        open_lot(lot_id)

        resp = api_client.create_add_on(
            create_add_on_payload(lot_id, buyer["id"], amount_cents=5000),
            make_buyer_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_SOLD)

    def test_addon_zero_amount_returns_invalid_amount(self, api):
        """PRD §3.7: "The lot must be `SOLD` and not yet swept into an
        `ISSUED` invoice, otherwise the pledge is rejected with
        `ERR_LOT_NOT_SOLD` (HTTP 409); that lot-eligibility check runs before
        the amount check, which requires `amount_cents` greater than zero
        (else `ERR_INVALID_AMOUNT`)."

        Design: Corner/validations/addon_zero_amount_returns_invalid_amount
        """
        ctx = self._sold_lot_context("Fair V15")
        lot_id = ctx["lot"]["id"]
        buyer_id = ctx["buyer"]["id"]

        zero = api_client.create_add_on(
            create_add_on_payload(lot_id, buyer_id, amount_cents=0),
            make_buyer_headers(buyer_id),
        )
        validate_error(zero, ApiErrorId.ERR_INVALID_AMOUNT)

        one_cent = api_client.create_add_on(
            create_add_on_payload(lot_id, buyer_id, amount_cents=1),
            make_buyer_headers(buyer_id),
        )
        pledge = validate_success(one_cent, 201)
        assert pledge["status"] == "PLEDGED"
        assert pledge["amount_cents"] == 1

    def test_buyer_cannot_pledge_addon_for_another_buyer(self, api):
        """PRD §2.1: "When `X-User-Role` is `Buyer`, `X-User-ID` is the `id`
        of the acting Buyer record, and add-on pledges may be created or
        voided only with `buyer_id` equal to `X-User-ID`."
        PRD §2.1: "a caller whose role is not permitted for the endpoint, or
        who fails an entity-backed ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/buyer_cannot_pledge_addon_for_another_buyer
        """
        ctx = self._sold_lot_context("Fair B2")
        buyer_b = create_buyer(ctx["fair"]["id"], business_name="Boosters Club",
                               credit_limit_cents=100000)
        resp = api_client.create_add_on(
            create_add_on_payload(ctx["lot"]["id"], ctx["buyer"]["id"],
                                  amount_cents=5000),
            make_buyer_headers(buyer_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
