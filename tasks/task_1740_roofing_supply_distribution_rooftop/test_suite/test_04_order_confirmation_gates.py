"""Order confirmation gates: state priority, credit, lots, OCC, ownership,
and CONFIRMED-order cancellation releasing reservations."""
from test_helpers import (
    TEST_USERS,
    confirm_order,
    convert_to_order,
    create_quoted_takeoff,
    get_success_data,
    make_account,
    make_branch,
    make_contractor_headers,
    make_job,
    make_lot,
    make_product,
    schedule_delivery,
    setup_order_scenario,
    validate_error,
    validate_success,
    ApiErrorId,
)

SALES = TEST_USERS["sales_rep_headers"]
CREDIT = TEST_USERS["credit_analyst_headers"]
WAREHOUSE = TEST_USERS["warehouse_clerk_headers"]


class TestStateBeatsCreditOnConfirm:
    def _confirmed_order_with_tight_credit(self, credit_limit):
        branch = make_branch("BR-V1")
        product = make_product("SH-V1", price=2000)
        make_lot(branch["id"], product["id"], on_hand=500)
        account = make_account(credit_limit=credit_limit, name="Tiny Credit")
        job = make_job(account["id"])
        takeoff = create_quoted_takeoff(job["id"], product["id"], 10.0, 0, 0)
        order = convert_to_order(takeoff["id"], branch["id"], account["id"])
        confirm_order(order["id"], account["id"])
        return account, order

    def test_reconfirm_of_confirmed_order_surfaces_state_error(self, api):
        """PRD §2.11: "Incoming requests are checked against a fixed priority
        cascade, and a higher-priority failure always surfaces before a
        lower-priority one is evaluated."
        PRD §3.4: "The order must be in `QUOTED` (otherwise
        `ERR_ORDER_NOT_QUOTED`), and a contractor acting on another
        contractor's order is `ERR_FORBIDDEN`."

        The order is already CONFIRMED and its 60000-cent total would also
        exceed the remaining credit (100000 limit, 60000 already held): the
        priority-4 state check surfaces ERR_ORDER_NOT_QUOTED, not the
        priority-11 fiscal error.

        Design: Difficulty/priority_pair_validation_conflict/confirm_wrong_state_vs_credit_exceeded_state_wins
        """
        account, order = self._confirmed_order_with_tight_credit(100_000)
        account = get_success_data(
            api.get_contractor_account(account["id"], CREDIT))
        resp = api.confirm_order(order["id"], account["version"],
                                 make_contractor_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_QUOTED)

    def test_reconfirm_with_ample_credit_also_surfaces_state_error(self, api):
        """PRD §2.11: "Fourth, the target entity is checked to be in the state
        the requested transition requires (priority 4) — these rejections
        carry the state-specific codes of §5 such as `ERR_ORDER_NOT_QUOTED` or
        `ERR_DELIVERY_NOT_SCHEDULED`."
        PRD §3.4: "The order must be in `QUOTED` (otherwise
        `ERR_ORDER_NOT_QUOTED`), and a contractor acting on another
        contractor's order is `ERR_FORBIDDEN`."

        Control arm: with ample credit the second confirm still fails on
        state, isolating the state check from the fiscal one.

        Design: Difficulty/priority_pair_validation_conflict/confirm_wrong_state_vs_credit_exceeded_state_wins
        """
        account, order = self._confirmed_order_with_tight_credit(
            100_000_000)
        account = get_success_data(
            api.get_contractor_account(account["id"], CREDIT))
        resp = api.confirm_order(order["id"], account["version"],
                                 make_contractor_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_QUOTED)


class TestConfirmFiscalAndLotGates:
    def test_confirm_rejected_when_total_exceeds_credit(self, api):
        """PRD §3.4: "Credit is then checked: `credit_available_cents` must
        cover the order's `total_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`."
        PRD §3.5: "Scheduling against a `QUOTED` order is deliberately allowed
        so that the delivery fee accrues into the order total before the
        confirmation credit check prices it in."

        30 bundles * 2000 = 60000 plus a ground fee of 8500 accrued
        pre-confirm: total 68500 > 65000 limit.

        Design: Corner/validations/credit_limit_exceeded_on_confirm
        """
        branch = make_branch("BR-VL3")
        product = make_product("SH-VL3", price=2000)
        make_lot(branch["id"], product["id"], on_hand=200)
        account = make_account(credit_limit=65_000, name="Poor Credit")
        job = make_job(account["id"])
        takeoff = create_quoted_takeoff(job["id"], product["id"], 10.0, 0, 0)
        order = convert_to_order(takeoff["id"], branch["id"], account["id"])
        schedule_delivery(order["id"], branch["id"], slot_date="2026-08-16",
                          equipment_type="GROUND")
        account = get_success_data(
            api.get_contractor_account(account["id"], CREDIT))
        resp = api.confirm_order(order["id"], account["version"],
                                 make_contractor_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    def test_confirm_rejected_when_no_lot_can_cover_line(self, api):
        """PRD §3.4: "Every order line must find, at the order's branch, an
        inventory lot holding the same product with `available_bundles` of at
        least the line's `quantity_bundles`; if any line cannot be satisfied,
        confirmation fails with `ERR_LOT_UNAVAILABLE`."

        The lot holds 10 bundles; the line needs 30.

        Design: Corner/validations/lot_unavailable_when_insufficient_available
        """
        branch = make_branch("BR-VL4")
        product = make_product("SH-VL4", price=2000)
        make_lot(branch["id"], product["id"], on_hand=10)
        account = make_account(name="NoStock Co")
        job = make_job(account["id"])
        takeoff = create_quoted_takeoff(job["id"], product["id"], 10.0, 0, 0)
        order = convert_to_order(takeoff["id"], branch["id"], account["id"])
        account = get_success_data(
            api.get_contractor_account(account["id"], CREDIT))
        resp = api.confirm_order(order["id"], account["version"],
                                 make_contractor_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_UNAVAILABLE)


class TestConfirmOptimisticConcurrency:
    def test_confirm_with_stale_account_version_rejected(self, api):
        """PRD §2.10: "If that value does not match the account's current
        `version` — because, for instance, another confirmed order has
        legitimately consumed credit and advanced the account version since
        the client last read it — the confirmation is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from committing
        against a credit position it has not observed."

        The version captured at account creation is stale after a
        suspend/reinstate cycle advanced it.

        Design: Corner/cross_cutting_layers/occ_confirm_stale_account_version_rejected
        """
        branch = make_branch("BR-CC1")
        product = make_product("SH-CC1", price=2000)
        make_lot(branch["id"], product["id"], on_hand=100)
        account = make_account(name="CC1 Co")
        stale_version = account["version"]
        job = make_job(account["id"])
        takeoff = create_quoted_takeoff(job["id"], product["id"], 5.0, 0, 0)
        order = convert_to_order(takeoff["id"], branch["id"], account["id"])
        get_success_data(api.suspend_account(account["id"], CREDIT))
        get_success_data(api.reinstate_account(account["id"], CREDIT))
        resp = api.confirm_order(order["id"], stale_version,
                                 make_contractor_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestConfirmOwnership:
    def test_contractor_cannot_confirm_other_contractors_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `Contractor`, `X-User-ID` is the
        `id` of the acting ContractorAccount; ownership checks on any resource
        that references a ContractorAccount compare the resource's foreign-key
        field to `X-User-ID` — for example the `contractor_account_id` carried
        by a JobAccount or an Allocation, or the account reached through an
        order's `job_account_id`."
        PRD §3.4: "Confirmation is the pivot of the whole system, performed by
        the owning `Contractor`."

        Design: Corner/rbac/contractor_cannot_touch_other_contractors_job
        """
        branch = make_branch("BR-RB3")
        product = make_product("SH-RB3", price=2000)
        make_lot(branch["id"], product["id"], on_hand=100)
        account_a = make_account(name="A Co")
        account_b = make_account(name="B Co")
        job_b = make_job(account_b["id"], job_name="Job RB3")
        takeoff = create_quoted_takeoff(job_b["id"], product["id"], 5.0, 0, 0)
        order = convert_to_order(takeoff["id"], branch["id"], account_b["id"])
        account_a = get_success_data(
            api.get_contractor_account(account_a["id"], CREDIT))
        resp = api.confirm_order(order["id"], account_a["version"],
                                 make_contractor_headers(account_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestConfirmedOrderCancellation:
    def test_cancel_releases_lot_reservation_and_credit_hold(self, api):
        """PRD §3.4: "Once `CONFIRMED`, cancellation becomes a `SalesRep`
        operation, permitted only when no delivery for the order is
        `SCHEDULED` or `EN_ROUTE` (an active delivery draws
        `ERR_ACTIVE_DELIVERY_EXISTS`); cancelling then releases each line's
        reservation by subtracting its quantity from its lot's
        `reserved_bundles`, subtracts the `total_cents` from the account's
        `pending_delivery_hold_cents`, and — when the order was surge-linked —
        subtracts the line quantities from the allocation's `consumed_bundles`
        and recomputes the allocation status."

        30 bundles reserved on confirm; after cancel the lot's
        reserved_bundles returns to 0 and the hold is released.

        Design: Corner/state_machines/order_cancel_releases_lot_reservation
        """
        ctx = setup_order_scenario(branch_code="BR-SM5", sku="SH-SM5",
                                   roof_squares=10.0, on_hand=100,
                                   lot_code="LOT-SM5", company_name="SM5 Co")
        lot_id = ctx["lot"]["id"]
        lot = get_success_data(api.get_inventory_lot(lot_id, WAREHOUSE))
        assert lot["reserved_bundles"] == 30

        cancelled = validate_success(api.cancel_order(ctx["order"]["id"],
                                                      SALES))
        assert cancelled["status"] == "CANCELLED"
        lot = get_success_data(api.get_inventory_lot(lot_id, WAREHOUSE))
        assert lot["reserved_bundles"] == 0
        account = get_success_data(
            api.get_contractor_account(ctx["account"]["id"], CREDIT))
        assert account["pending_delivery_hold_cents"] == 0
