"""Season closeout and validation priority: the close-season cascade that
settles programs and commitments, the open-orders guard, and the pinned
precedence of state preconditions over posture/OCC on order confirmation."""
from test_helpers import (
    ApiErrorId,
    MGR,
    branch_version,
    complete_order_fully,
    confirm_order,
    confirm_short_order,
    create_confirmed_order,
    make_account,
    make_branch,
    make_commitment,
    make_lot,
    make_open_program_with_commitment,
    make_order,
    make_product,
    order_line,
    set_clock,
    setup_branch_account_product_lot,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

COUNTER = TEST_USERS["counter_rep_headers"]


class TestSeasonCloseout:
    def test_close_season_cascade_commitments_settle(self, api):
        """PRD §3.9: "Closing moves the branch from `OPEN` to `CLOSED_SEASON`, cascades every `OPEN` seasonal program of the branch to `CLOSED` — settling each program's commitments exactly as a manual close would, short commitments to `DEFAULTED` and fully consumed ones to `FULFILLED` — and increments the branch's `version` by one."
        PRD §3.3: "Either way the branch's `seasonal_pool_units` — defined as the sum of `committed_units` over `COMMITTED` commitments across the branch's programs — is recomputed: the superseded units leave the pool, the new units enter it, and a defaulted commitment likewise leaves the pool."

        Design: Difficulty/transitive_cascade/close_season_cascade_commitments_settle
        """
        set_clock("2026-01-10T00:00:00Z", api)
        branch = make_branch(api, branch_code="PHX-12", hazmat_storage_certified=True)
        a1 = make_account(api, account_number="DLR-501")
        a2 = make_account(api, account_number="DLR-502")
        product = make_product(
            api, sku="TAB-1IN", product_family="CHEMICAL", base_price_cents=1000
        )
        make_lot(api, branch_id=branch["id"], product_id=product["id"], qty_on_hand=10000)
        program, c1 = make_open_program_with_commitment(
            branch["id"], a1["id"], 100, api,
            program_name="EB-2026", early_buy_discount_pct=10, pool_cap_units=10000,
        )
        c2 = make_commitment(program["id"], a2["id"], 100, api=api)

        # Fully consume c1 through an order driven all the way to COMPLETED so
        # no lingering CONFIRMED/PICKED_LOADED order blocks close-season.
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=a1["id"],
            requested_pickup_slot="2026-01-10T15:00:00Z",
            commitment_id=c1["id"],
            lines=[order_line(product["id"], 100)],
        )
        c1_mid = validate_success(api.get_seasonal_commitment(c1["id"], MGR))
        assert c1_mid["status"] == "FULFILLED" and c1_mid["consumed_units"] == 100
        complete_order_fully(order["id"], "WILL_CALL", api)

        resp = api.close_branch_season(branch["id"], MGR)
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED_SEASON"
        program_after = validate_success(api.get_seasonal_program(program["id"], MGR))
        assert program_after["status"] == "CLOSED", (
            f"close-season cascades OPEN programs to CLOSED: {program_after}"
        )
        c1_after = validate_success(api.get_seasonal_commitment(c1["id"], MGR))
        assert c1_after["status"] == "FULFILLED", (
            f"fully consumed commitment settles FULFILLED: {c1_after}"
        )
        c2_after = validate_success(api.get_seasonal_commitment(c2["id"], MGR))
        assert c2_after["status"] == "DEFAULTED", (
            f"short commitment (0 of 100 consumed) settles DEFAULTED: {c2_after}"
        )
        assert closed["seasonal_pool_units"] == 0, (
            f"both commitments left the COMMITTED pool: {closed}"
        )

    def test_program_close_settles_commitments_directly(self, api):
        """PRD §3.3: "Closing an `OPEN` program (attempts on anything else draw `ERR_PROGRAM_NOT_OPEN`, HTTP 409) settles its book: each commitment still `COMMITTED` whose `consumed_units` have reached its `committed_units` becomes `FULFILLED`, while each one still short becomes `DEFAULTED`."

        Design: Difficulty/transitive_cascade/close_season_cascade_commitments_settle
        """
        set_clock("2026-01-10T00:00:00Z", api)
        branch = make_branch(api, hazmat_storage_certified=True)
        a1 = make_account(api, account_number="DLR-511")
        a2 = make_account(api, account_number="DLR-512")
        product = make_product(
            api, sku="TAB-2IN", product_family="CHEMICAL", base_price_cents=800
        )
        make_lot(api, branch_id=branch["id"], product_id=product["id"], qty_on_hand=100)
        program, c1 = make_open_program_with_commitment(
            branch["id"], a1["id"], 5, api, pool_cap_units=1000
        )
        c2 = make_commitment(program["id"], a2["id"], 7, api=api)
        create_confirmed_order(
            api, branch_id=branch["id"], account_id=a1["id"],
            requested_pickup_slot="2026-01-10T15:00:00Z",
            commitment_id=c1["id"],
            lines=[order_line(product["id"], 5)],
        )

        resp = api.close_seasonal_program(program["id"], MGR)
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED"
        c1_after = validate_success(api.get_seasonal_commitment(c1["id"], MGR))
        c2_after = validate_success(api.get_seasonal_commitment(c2["id"], MGR))
        assert c1_after["status"] == "FULFILLED"
        assert c2_after["status"] == "DEFAULTED"

    def test_close_season_blocked_by_open_orders(self, api):
        """PRD §3.9: "A `BranchManager` closes the branch's season only when no order of the branch remains in fulfillment `CONFIRMED` or `PICKED_LOADED` (`ERR_BRANCH_ORDERS_OPEN`, HTTP 409) and no backorder request of the branch remains `OPEN` or `ALLOCATED` (`ERR_BRANCH_BACKORDERS_OPEN`, HTTP 409)."

        Design: Corner/endpoints/close_season_blocked_by_open_orders
        """
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-17"},
            product_over={"sku": "BRUSH-18", "product_family": "PARTS", "base_price_cents": 1200},
            lot_over={"qty_on_hand": 5},
        )
        create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 1)],
        )
        resp = api.close_branch_season(branch["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_BRANCH_ORDERS_OPEN)
        branch_after = validate_success(api.get_branch(branch["id"], MGR))
        assert branch_after["status"] == "OPEN", (
            f"blocked close leaves the branch OPEN: {branch_after}"
        )


class TestStateBeforeBusinessPriority:
    def test_confirm_cancelled_order_on_frozen_branch_reports_state_error(self, api):
        """PRD §2.8: "Evaluation precedence on confirmation is pinned: authentication, then ownership, then existence, then the order's state preconditions (such as the draft check), then this version check, then the business checks of §2.9 in their pinned order. A confirm that violates a state precondition reports the state error even when the supplied branch version is also stale."
        PRD §3.4: "The order must be in fulfillment `DRAFT` (`ERR_ORDER_NOT_DRAFT`, HTTP 409) and its branch still `OPEN` (`ERR_BRANCH_CLOSED`, HTTP 409) before any business check runs."
        PRD §3.4: "Posture fifth: a `FROZEN` branch refuses confirmation with `ERR_BRANCH_FROZEN` (HTTP 409), while `CONSTRAINED` branches keep trading."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_posture_confirm_cancelled_on_frozen_branch
        """
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"branch_code": "PHX-12", "hazmat_storage_certified": True},
            account_over={"account_number": "DLR-600"},
            product_over={
                "sku": "ACID-8", "product_family": "CHEMICAL",
                "hazmat_class": "CORROSIVE_8", "base_price_cents": 4000,
                "shortage_freeze_threshold": 1,
            },
            lot_over={"qty_on_hand": 0},
        )
        # o1 freezes the branch, then is cancelled (posture drops back).
        o1, _bo1 = confirm_short_order(
            api, branch_id=branch["id"], account_id=account["id"],
            product_id=product["id"], qty=5,
        )
        validate_success(api.cancel_order(o1["id"], MGR), 200)
        stale_version = branch_version(branch["id"], api)

        # o2 freezes the branch again.
        o2 = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            requested_pickup_slot="2026-08-01T14:00:00Z",
            lines=[order_line(product["id"], 5)],
        )
        confirm_order(o2["id"], branch["id"], api)
        branch_frozen = validate_success(api.get_branch(branch["id"], MGR))
        assert branch_frozen["posture"] == "FROZEN"

        # o1 is CANCELLED (state violation) on a FROZEN branch (posture
        # violation) with a stale branch version (OCC violation): the state
        # error is reported first.
        resp = api.confirm_order(
            o1["id"], {"expected_branch_version": stale_version}, COUNTER
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DRAFT)

    def test_reconfirm_confirmed_order_on_frozen_branch_reports_state_error(self, api):
        """PRD §2.8: "Evaluation precedence on confirmation is pinned: authentication, then ownership, then existence, then the order's state preconditions (such as the draft check), then this version check, then the business checks of §2.9 in their pinned order. A confirm that violates a state precondition reports the state error even when the supplied branch version is also stale."
        PRD §3.4: "The order must be in fulfillment `DRAFT` (`ERR_ORDER_NOT_DRAFT`, HTTP 409) and its branch still `OPEN` (`ERR_BRANCH_CLOSED`, HTTP 409) before any business check runs."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_posture_confirm_cancelled_on_frozen_branch
        """
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": True},
            product_over={
                "sku": "ACID-9", "product_family": "CHEMICAL",
                "hazmat_class": "CORROSIVE_8", "base_price_cents": 4000,
                "shortage_freeze_threshold": 1,
            },
            lot_over={"qty_on_hand": 0},
        )
        # o1's own shortfall froze the branch; o1 itself is CONFIRMED.
        o1, _bo1 = confirm_short_order(
            api, branch_id=branch["id"], account_id=account["id"],
            product_id=product["id"], qty=2,
        )
        branch_frozen = validate_success(api.get_branch(branch["id"], MGR))
        assert branch_frozen["posture"] == "FROZEN"

        resp = api.confirm_order(
            o1["id"], {"expected_branch_version": branch_version(branch["id"], api)},
            COUNTER,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DRAFT)
        order = validate_success(api.get_order(o1["id"], MGR))
        assert order["fulfillment_status"] == "CONFIRMED"
