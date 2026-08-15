"""Backorders and branch posture: the confirm-to-freeze cascade, posture gating
on confirmation, the replenishment waterfall (ranking, exact grants, empty-lot
rejection), backorder state lockdown, lot-version OCC, and the unfreeze
compensation on cancel."""
from test_helpers import (
    ApiErrorId,
    MGR,
    branch_version,
    confirm_order,
    confirm_short_order,
    create_confirmed_order,
    get_order_lines,
    get_single_backorder,
    list_backorders,
    lot_version,
    make_account,
    make_branch,
    make_lot,
    make_order,
    make_product,
    order_line,
    seed_account_tier,
    setup_branch_account_product_lot,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

COUNTER = TEST_USERS["counter_rep_headers"]
WAREHOUSE = TEST_USERS["warehouse_lead_headers"]


class TestConfirmFreezeCascade:
    def test_confirm_short_backorder_freezes_branch(self, api):
        """PRD §3.4: "A line no single lot can cover goes short: `allocated_qty` stays zero, `backordered_qty` equals the full `qty`, and a backorder request is born per §3.7 — which may cascade the branch into `FROZEN`."
        PRD §2.7: "A branch is `FROZEN` when at least one product's open backorder load — the sum of `qty_open` across that branch's backorder requests in `OPEN` status for that product — reaches or exceeds the product's `shortage_freeze_threshold`; reaching the threshold exactly is enough to freeze."
        PRD §3.7: "When confirmation leaves a line short, the system births a backorder request in `OPEN` status: it references the `branch_id`, the short `order_line_id`, the `product_id` copied from the line, the `account_id` copied from the order, the original shortage as an immutable `qty_original`, the still-owed balance `qty_open`, and a `priority_rank` snapshotted at creation — 1 when the confirming order's `tier_at_confirm` was `PREMIER`, 2 for `ELITE`, 3 for `PRO`."

        Design: Difficulty/transitive_cascade/confirm_short_backorder_freezes_branch
        """
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"branch_code": "PHX-12", "hazmat_storage_certified": True},
            account_over={"account_number": "DLR-500"},
            product_over={
                "sku": "ACID-4X1", "product_family": "CHEMICAL",
                "hazmat_class": "CORROSIVE_8", "base_price_cents": 4000,
                "shortage_freeze_threshold": 10,
            },
            lot_over={"qty_on_hand": 3},
        )
        before = validate_success(api.get_branch(branch["id"], MGR))
        assert before["posture"] == "NORMAL"

        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 13)],
        )
        lines = get_order_lines(order["id"], api)
        # The only lot holds 3 < 13, so no single lot covers the line: the
        # whole line shorts (allocated_qty 0, backordered_qty == full qty).
        assert lines[0]["allocated_qty"] == 0
        assert lines[0]["backordered_qty"] == 13
        bo = get_single_backorder(branch["id"], product["id"], "OPEN", api)
        assert bo["qty_open"] == 13
        assert bo["qty_original"] == 13
        assert bo["priority_rank"] == 3, f"PRO account snapshots rank 3: {bo}"
        assert bo["status"] == "OPEN"

        # Open load 13 >= threshold 10 -> FROZEN through the backorder hop.
        branch_after = validate_success(api.get_branch(branch["id"], MGR))
        assert branch_after["posture"] == "FROZEN", (
            f"open backorder load 13 >= threshold 10 freezes the branch: {branch_after}"
        )

        # Posture now gates child operations: a second confirm is refused.
        order2 = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            requested_pickup_slot="2026-08-01T14:00:00Z",
            lines=[order_line(product["id"], 1)],
        )
        resp = api.confirm_order(
            order2["id"],
            {"expected_branch_version": branch_version(branch["id"], api)},
            COUNTER,
        )
        validate_error(resp, ApiErrorId.ERR_BRANCH_FROZEN)

    def test_confirm_shortfall_below_threshold_stays_normal(self, api):
        """PRD §2.7: "A branch is `FROZEN` when at least one product's open backorder load — the sum of `qty_open` across that branch's backorder requests in `OPEN` status for that product — reaches or exceeds the product's `shortage_freeze_threshold`; reaching the threshold exactly is enough to freeze."
        PRD §2.7: "Failing both, the branch is `NORMAL`."

        Design: Difficulty/transitive_cascade/confirm_short_backorder_freezes_branch
        """
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": True},
            product_over={
                "sku": "ACID-2X1", "product_family": "CHEMICAL",
                "hazmat_class": "CORROSIVE_8", "base_price_cents": 4000,
                "shortage_freeze_threshold": 10,
            },
            lot_over={"qty_on_hand": 1},
        )
        # Lot holds 1 < 9, so the whole line shorts: open load 9 sits one unit
        # below the threshold of 10.
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 9)],
        )
        bo = get_single_backorder(branch["id"], product["id"], "OPEN", api)
        assert bo["qty_open"] == 9
        branch_after = validate_success(api.get_branch(branch["id"], MGR))
        assert branch_after["posture"] == "NORMAL", (
            f"open load 9 is below threshold 10 — not frozen (floor default 0 "
            f"keeps CONSTRAINED off too): {branch_after}"
        )
        # And the branch keeps trading.
        order2 = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            requested_pickup_slot="2026-08-01T14:00:00Z",
            lines=[order_line(product["id"], 1)],
        )
        confirmed = confirm_order(order2["id"], branch["id"], api)
        assert confirmed["fulfillment_status"] == "CONFIRMED"


class TestPostureGate:
    def test_order_confirm_gated_by_branch_posture(self, api):
        """PRD §3.4: "Posture fifth: a `FROZEN` branch refuses confirmation with `ERR_BRANCH_FROZEN` (HTTP 409), while `CONSTRAINED` branches keep trading."
        PRD §3.7: "Branch posture is recomputed once after the sweep — falling back below a product's `shortage_freeze_threshold` may unfreeze the branch."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_branch_posture
        """
        branch = make_branch(api, hazmat_storage_certified=False)
        account = make_account(api, account_number="DLR-800")
        pa = make_product(
            api, sku="CHLOR-G", product_family="CHEMICAL", base_price_cents=3000,
            shortage_freeze_threshold=5,
        )
        pb = make_product(api, sku="NET-STD", product_family="PARTS", base_price_cents=1500)
        lot_a = make_lot(api, branch_id=branch["id"], product_id=pa["id"], qty_on_hand=0)
        make_lot(api, branch_id=branch["id"], product_id=pb["id"], qty_on_hand=50)

        _o1, bo = confirm_short_order(
            api, branch_id=branch["id"], account_id=account["id"],
            product_id=pa["id"], qty=5,
        )
        branch_frozen = validate_success(api.get_branch(branch["id"], MGR))
        assert branch_frozen["posture"] == "FROZEN"

        # A DRAFT order on an in-stock product still cannot confirm while FROZEN.
        o2 = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            requested_pickup_slot="2026-08-01T14:00:00Z",
            lines=[order_line(pb["id"], 1)],
        )
        resp = api.confirm_order(
            o2["id"], {"expected_branch_version": branch_version(branch["id"], api)}, COUNTER
        )
        validate_error(resp, ApiErrorId.ERR_BRANCH_FROZEN)

        # Replenishment fires the sweep: the OPEN backorder drains and closes,
        # and posture recomputes back to NORMAL.
        validate_success(api.replenish_stock_lot(lot_a["id"], {"add_qty": 5}, WAREHOUSE), 200)
        bo_after = validate_success(api.get_backorder_request(bo["id"], WAREHOUSE))
        assert bo_after["status"] == "CLOSED", f"sweep drained the backorder: {bo_after}"
        branch_after = validate_success(api.get_branch(branch["id"], MGR))
        assert branch_after["posture"] == "NORMAL", (
            f"falling below the threshold unfreezes the branch: {branch_after}"
        )
        confirmed = confirm_order(o2["id"], branch["id"], api)
        assert confirmed["fulfillment_status"] == "CONFIRMED"

    def test_constrained_branch_still_confirms(self, api):
        """PRD §2.7: "Failing that, a branch is `CONSTRAINED` when at least one product whose `low_stock_floor` is greater than zero shows total available units at or below that floor, where total available units means the sum over the branch's lots of that product of physical units on hand minus both reservation buckets; sitting exactly at the floor is constrained."
        PRD §3.4: "Posture fifth: a `FROZEN` branch refuses confirmation with `ERR_BRANCH_FROZEN` (HTTP 409), while `CONSTRAINED` branches keep trading."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_branch_posture
        """
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            product_over={
                "sku": "SKIM-NET", "product_family": "PARTS", "base_price_cents": 900,
                "low_stock_floor": 10,
            },
            lot_over={"qty_on_hand": 10},
        )
        branch_mid = validate_success(api.get_branch(branch["id"], MGR))
        assert branch_mid["posture"] == "CONSTRAINED", (
            f"available 10 sits exactly at floor 10: {branch_mid}"
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 1)],
        )
        assert order["fulfillment_status"] == "CONFIRMED", (
            "CONSTRAINED branches keep trading"
        )


class TestWaterfallAllocation:
    def test_waterfall_zero_available_empty_grant(self, api):
        """PRD §3.7: "The backorder must be `OPEN` (`ERR_BACKORDER_NOT_OPEN`, HTTP 409), and the target lot must have at least one unit of `qty_available` — a completely empty lot draws `ERR_LOT_EMPTY` (HTTP 422), though per §2.8 a stale lot version is reported first when both conditions hold."

        Design: Difficulty/boundary_precision_check/waterfall_zero_available_empty_grant
        """
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-701"},
            product_over={
                "sku": "FILTER-CART", "product_family": "PARTS",
                "base_price_cents": 4500, "shortage_freeze_threshold": 1000,
            },
            lot_over={"lot_code": "L-EMPTY", "qty_on_hand": 0},
        )
        _order, bo = confirm_short_order(
            api, branch_id=branch["id"], account_id=account["id"],
            product_id=product["id"], qty=5,
        )
        version_before = lot_version(lot["id"], api)
        resp = api.allocate_backorder(
            bo["id"],
            {"lot_id": lot["id"], "expected_stock_lot_version": version_before},
            WAREHOUSE,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_EMPTY)
        bo_after = validate_success(api.get_backorder_request(bo["id"], WAREHOUSE))
        assert bo_after["qty_open"] == 5 and bo_after["status"] == "OPEN", (
            f"empty grant rejected — nothing moved: {bo_after}"
        )
        lot_after = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert lot_after["qty_available"] == 0
        assert lot_after["version"] == version_before, (
            f"rejected allocation must not mutate the lot: {lot_after}"
        )

    def test_waterfall_sweep_exact_grant_leaves_second_untouched(self, api):
        """PRD §3.7: "The sweep walks the ranked candidates, granting each the smaller of its `qty_open` and the lot's remaining `qty_available`, reserving the grant in the bucket matching the parent order's channel, decrementing `qty_open`, and stopping when availability is exhausted."
        PRD §3.7: "A candidate drained to zero becomes `CLOSED`; one still owed units remains `ALLOCATED` with its residual."

        Design: Difficulty/boundary_precision_check/waterfall_zero_available_empty_grant
        """
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            product_over={
                "sku": "GRID-Q", "product_family": "PARTS", "base_price_cents": 800,
                "shortage_freeze_threshold": 1000,
            },
            lot_over={"qty_on_hand": 0},
        )
        # Two OPEN backorders, same product, same rank (PRO) — created_at order.
        _o1, bo1 = confirm_short_order(
            api, branch_id=branch["id"], account_id=account["id"],
            product_id=product["id"], qty=4,
        )
        o2 = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            requested_pickup_slot="2026-08-01T14:00:00Z",
            lines=[order_line(product["id"], 2)],
        )
        confirm_order(o2["id"], branch["id"], api)
        bos = list_backorders(api, branch_id=branch["id"], product_id=product["id"],
                              status="OPEN")
        assert len(bos) == 2
        bo2 = next(b for b in bos if b["id"] != bo1["id"])

        # Replenish exactly enough for the first-ranked backorder only.
        validate_success(api.replenish_stock_lot(lot["id"], {"add_qty": 4}, WAREHOUSE), 200)
        bo1_after = validate_success(api.get_backorder_request(bo1["id"], WAREHOUSE))
        bo2_after = validate_success(api.get_backorder_request(bo2["id"], WAREHOUSE))
        assert bo1_after["status"] == "CLOSED" and bo1_after["qty_open"] == 0
        assert bo2_after["status"] == "OPEN" and bo2_after["qty_open"] == 2, (
            f"the sweep stops when availability is exhausted: {bo2_after}"
        )
        lot_after = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert lot_after["qty_available"] == 0
        assert lot_after["qty_reserved_willcall"] == 4

    def test_backorder_waterfall_priority_order_premier_first(self, api):
        """PRD §3.7: "Candidates are ranked by `priority_rank` ascending, ties broken by `created_at` ascending; the UUID `id` must never be used as a ranking key."
        PRD §3.7: "When confirmation leaves a line short, the system births a backorder request in `OPEN` status: it references the `branch_id`, the short `order_line_id`, the `product_id` copied from the line, the `account_id` copied from the order, the original shortage as an immutable `qty_original`, the still-owed balance `qty_open`, and a `priority_rank` snapshotted at creation — 1 when the confirming order's `tier_at_confirm` was `PREMIER`, 2 for `ELITE`, 3 for `PRO`."
        PRD §3.7: "That snapshot is a ratchet: a backorder's place in line never moves even if the account's live tier changes afterward."

        Design: Corner/calculations/backorder_waterfall_priority_order_premier_first
        """
        branch = make_branch(api, hazmat_storage_certified=False)
        a_pro = make_account(api, account_number="DLR-9PRO")
        a_pre = make_account(api, account_number="DLR-9PRE")
        seed_account_tier(a_pre["id"], branch["id"], "PREMIER", api)
        product = make_product(
            api, sku="GRID-V", product_family="PARTS", base_price_cents=1500,
            shortage_freeze_threshold=1000,
        )
        lot = make_lot(api, branch_id=branch["id"], product_id=product["id"], qty_on_hand=0)

        # PRO's backorder is created FIRST (qty 3)...
        _o_pro, bo_pro = confirm_short_order(
            api, branch_id=branch["id"], account_id=a_pro["id"],
            product_id=product["id"], qty=3,
        )
        # ...PREMIER's second (qty 2), yet ranks ahead. Two OPEN backorders for
        # the same (branch, product) now legitimately coexist, so fetch neither
        # via the single-backorder helper; confirm directly.
        o_pre = make_order(
            api, branch_id=branch["id"], account_id=a_pre["id"],
            requested_pickup_slot="2026-08-01T14:00:00Z",
            lines=[order_line(product["id"], 2)],
        )
        confirm_order(o_pre["id"], branch["id"], api)

        validate_success(api.replenish_stock_lot(lot["id"], {"add_qty": 3}, WAREHOUSE), 200)
        pre_rows = list_backorders(api, branch_id=branch["id"], account_id=a_pre["id"])
        pro_rows = list_backorders(api, branch_id=branch["id"], account_id=a_pro["id"])
        bo_pre = next(b for b in pre_rows if b["product_id"] == product["id"])
        bo_pro_after = next(b for b in pro_rows if b["product_id"] == product["id"])
        assert bo_pre["priority_rank"] == 1
        assert bo_pre["status"] == "CLOSED" and bo_pre["qty_open"] == 0, (
            f"rank 1 (PREMIER) is fully granted before the earlier-created PRO "
            f"backorder: {bo_pre}"
        )
        assert bo_pro_after["priority_rank"] == 3
        assert bo_pro_after["status"] == "ALLOCATED", (
            f"residual keeps the PRO backorder ALLOCATED: {bo_pro_after}"
        )
        assert bo_pro_after["qty_open"] == 2, f"granted 1 of 3: {bo_pro_after}"
        lot_after = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert lot_after["qty_available"] == 0
        assert lot_after["qty_reserved_willcall"] == 3


class TestBackorderStateAndOcc:
    def test_backorder_terminal_lockdown(self, api):
        """PRD §3.7: "The backorder must be `OPEN` (`ERR_BACKORDER_NOT_OPEN`, HTTP 409), and the target lot must have at least one unit of `qty_available` — a completely empty lot draws `ERR_LOT_EMPTY` (HTTP 422), though per §2.8 a stale lot version is reported first when both conditions hold."
        PRD §3.7: "A `BranchManager` may also cancel an `OPEN` backorder outright — again `ERR_BACKORDER_NOT_OPEN` guards the state — moving it to `CANCELLED` with a posture recompute."

        Design: Corner/state_machines/backorder_terminal_lockdown
        """
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-5"},
            product_over={
                "sku": "SKIM-B", "product_family": "PARTS", "base_price_cents": 2000,
                "shortage_freeze_threshold": 1000,
            },
            lot_over={"qty_on_hand": 0},
        )
        _order, bo = confirm_short_order(
            api, branch_id=branch["id"], account_id=account["id"],
            product_id=product["id"], qty=4,
        )
        validate_success(api.cancel_backorder(bo["id"], MGR), 200)

        resp = api.allocate_backorder(
            bo["id"],
            {"lot_id": lot["id"], "expected_stock_lot_version": lot_version(lot["id"], api)},
            WAREHOUSE,
        )
        validate_error(resp, ApiErrorId.ERR_BACKORDER_NOT_OPEN)
        resp = api.cancel_backorder(bo["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_BACKORDER_NOT_OPEN)
        bo_after = validate_success(api.get_backorder_request(bo["id"], WAREHOUSE))
        assert bo_after["status"] == "CANCELLED"

    def test_occ_stale_lot_version_on_manual_allocate(self, api):
        """PRD §2.8: "**Manual backorder allocation** requires a non-optional `expected_stock_lot_version` carrying the client's last observed `version` of the target stock lot. A mismatch is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). Precedence is pinned: authentication, then existence, then the backorder's open-state check, then the version check, then the quantity check — so a stale version is reported even when the lot is empty at the same moment."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_lot_version_on_manual_allocate
        """
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-23"},
            product_over={
                "sku": "SEAL-2", "product_family": "PARTS", "base_price_cents": 600,
                "shortage_freeze_threshold": 1000,
            },
            lot_over={"qty_on_hand": 0},
        )
        # BO1 takes the whole first replenishment; the lot ends empty again.
        _o1, bo1 = confirm_short_order(
            api, branch_id=branch["id"], account_id=account["id"],
            product_id=product["id"], qty=4,
        )
        stale = lot_version(lot["id"], api)
        validate_success(api.replenish_stock_lot(lot["id"], {"add_qty": 4}, WAREHOUSE), 200)
        bo1_after = validate_success(api.get_backorder_request(bo1["id"], WAREHOUSE))
        assert bo1_after["status"] == "CLOSED"

        # A second short order leaves BO2 OPEN while the lot sits empty.
        o2 = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            requested_pickup_slot="2026-08-01T14:00:00Z",
            lines=[order_line(product["id"], 2)],
        )
        confirm_order(o2["id"], branch["id"], api)
        bo2 = get_single_backorder(branch["id"], product["id"], "OPEN", api)
        lot_now = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert lot_now["qty_available"] == 0
        assert lot_now["version"] != stale

        resp = api.allocate_backorder(
            bo2["id"], {"lot_id": lot["id"], "expected_stock_lot_version": stale},
            WAREHOUSE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION)
        bo2_after = validate_success(api.get_backorder_request(bo2["id"], WAREHOUSE))
        assert bo2_after["status"] == "OPEN" and bo2_after["qty_open"] == 2, (
            f"stale version rejected before the quantity check: {bo2_after}"
        )
        lot_after = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert lot_after["qty_available"] == 0, "no partial grant slipped through"

    def test_cascade_order_cancel_unfreezes_branch(self, api):
        """PRD §3.6: "The compensating act releases every line's lot reservation by its `allocated_qty`, cancels the order's `OPEN` backorder requests, and recomputes branch posture, which may drop the branch out of `FROZEN` into `CONSTRAINED` or `NORMAL`."
        PRD §2.7: "Each branch derives a `posture` of `NORMAL`, `CONSTRAINED`, or `FROZEN`, recomputed after every order confirmation, order cancellation, backorder allocation, backorder closure or cancellation, and lot replenishment."

        Design: Corner/cross_cutting_complexity_layers/cascade_order_cancel_unfreezes_branch
        """
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-25"},
            product_over={
                "sku": "CHLOR-P", "product_family": "CHEMICAL", "base_price_cents": 2500,
                "shortage_freeze_threshold": 5,
            },
            lot_over={"qty_on_hand": 0},
        )
        order, bo = confirm_short_order(
            api, branch_id=branch["id"], account_id=account["id"],
            product_id=product["id"], qty=5,
        )
        frozen = validate_success(api.get_branch(branch["id"], MGR))
        assert frozen["posture"] == "FROZEN", "5 open units reach threshold 5"

        validate_success(api.cancel_order(order["id"], MGR), 200)
        after = validate_success(api.get_branch(branch["id"], MGR))
        assert after["posture"] == "NORMAL", (
            f"cancel cascaded: backorder cancelled, posture recomputed: {after}"
        )
        bo_after = validate_success(api.get_backorder_request(bo["id"], WAREHOUSE))
        assert bo_after["status"] == "CANCELLED"
