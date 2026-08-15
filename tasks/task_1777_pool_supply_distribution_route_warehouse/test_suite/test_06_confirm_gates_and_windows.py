"""Order confirmation business gauntlet: hazmat storage licensing, hazmat
delivery license strictness, route-date windows (season-end boundary and
before-today), will-call authorization, and the pinned safety-before-fiscal
check ordering."""
from test_helpers import (
    ApiErrorId,
    MGR,
    branch_version,
    make_order,
    order_line,
    set_clock,
    setup_branch_account_product_lot,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

COUNTER = TEST_USERS["counter_rep_headers"]
ROUTE = TEST_USERS["route_dispatcher_headers"]
WAREHOUSE = TEST_USERS["warehouse_lead_headers"]


def _confirm_route_order(api, order_id, branch_id):
    """Confirm a ROUTE_DELIVERY draft against the branch's current version."""
    resp = api.confirm_order(
        order_id, {"expected_branch_version": branch_version(branch_id, api)}, ROUTE
    )
    return validate_success(resp, 200)


class TestRouteDateWindow:
    def test_route_date_season_window_day_boundary(self, api):
        """PRD §3.4: "Temporal third: a `route_date` before the logical today is always rejected, and when any line is hazmat the `route_date` must also fall no later than the branch's `peak_season_end` — `ERR_ROUTE_DATE_OUTSIDE_WINDOW` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/route_date_season_window_day_boundary
        """
        set_clock("2026-09-01T00:00:00Z", api)
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={
                "branch_code": "PHX-12", "hazmat_storage_certified": True,
                "peak_season_start": "04-01", "peak_season_end": "09-30",
            },
            account_over={
                "account_number": "DLR-901",
                "hazmat_delivery_license_expiry": "2027-01-01",
            },
            product_over={
                "sku": "ACID-M", "product_family": "CHEMICAL",
                "hazmat_class": "CORROSIVE_8", "base_price_cents": 4000,
            },
            lot_over={"qty_on_hand": 100},
        )
        # route_date == peak_season_end (09-30): the end day is inclusive.
        o_ok = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="ROUTE_DELIVERY", route_date="2026-09-30",
            lines=[order_line(product["id"], 1)],
        )
        confirmed = _confirm_route_order(api, o_ok["id"], branch["id"])
        assert confirmed["fulfillment_status"] == "CONFIRMED", (
            f"route_date on the peak-season end day is accepted: {confirmed}"
        )

        # One day later, the hazmat route falls outside the window.
        o_bad = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="ROUTE_DELIVERY", route_date="2026-10-01",
            lines=[order_line(product["id"], 1)],
        )
        resp = api.confirm_order(
            o_bad["id"],
            {"expected_branch_version": branch_version(branch["id"], api)},
            ROUTE,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_DATE_OUTSIDE_WINDOW)

    def test_route_date_before_today_rejected(self, api):
        """PRD §3.4: "Temporal third: a `route_date` before the logical today is always rejected, and when any line is hazmat the `route_date` must also fall no later than the branch's `peak_season_end` — `ERR_ROUTE_DATE_OUTSIDE_WINDOW` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/route_date_season_window_day_boundary
        """
        set_clock("2026-09-01T00:00:00Z", api)
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            product_over={"sku": "ROPE-30", "product_family": "PARTS", "base_price_cents": 700},
            lot_over={"qty_on_hand": 20},
        )
        order = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="ROUTE_DELIVERY", route_date="2026-08-15",
            lines=[order_line(product["id"], 1)],
        )
        resp = api.confirm_order(
            order["id"],
            {"expected_branch_version": branch_version(branch["id"], api)},
            ROUTE,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_DATE_OUTSIDE_WINDOW)
        order = validate_success(api.get_order(order["id"], MGR))
        assert order["fulfillment_status"] == "DRAFT"


class TestHazmatLicenseGate:
    def test_route_hazmat_license_expired_exactly_on_route_date(self, api):
        """PRD §3.4: "Delivery licensing second: hazmat lines on a `ROUTE_DELIVERY` order require the account's `hazmat_delivery_license_expiry` to fall strictly after the `route_date`, with an absent license treated as no authorization — `ERR_HAZMAT_LICENSE_EXPIRED` (HTTP 422)."

        Design: Corner/validations/route_hazmat_license_expired_exactly_on_route_date
        """
        set_clock("2026-06-01T00:00:00Z", api)
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"branch_code": "PHX-12", "hazmat_storage_certified": True},
            account_over={
                "account_number": "DLR-12",
                "hazmat_delivery_license_expiry": "2026-06-10",
            },
            product_over={
                "sku": "ACID-S", "product_family": "CHEMICAL",
                "hazmat_class": "OXIDIZER_5_1", "base_price_cents": 2000,
            },
            lot_over={"qty_on_hand": 5},
        )
        # License expiry == route_date fails: the rule is strictly-after.
        order = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="ROUTE_DELIVERY", route_date="2026-06-10",
            lines=[order_line(product["id"], 1)],
        )
        resp = api.confirm_order(
            order["id"],
            {"expected_branch_version": branch_version(branch["id"], api)},
            ROUTE,
        )
        validate_error(resp, ApiErrorId.ERR_HAZMAT_LICENSE_EXPIRED)
        order = validate_success(api.get_order(order["id"], MGR))
        assert order["fulfillment_status"] == "DRAFT"
        lot_after = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert lot_after["qty_reserved_route"] == 0, (
            f"rejected confirm creates no reservation: {lot_after}"
        )


class TestSafetyBeforeFiscalPriority:
    def test_credit_hold_blocks_confirm_fiscal_after_safety(self, api):
        """PRD §2.9: "Business rules come last, and where several apply to one endpoint their relative order is pinned in the workflow narratives: on order confirmation the hazmat storage-certification check precedes the hazmat license check, which precedes the route-date window check, which precedes the will-call authorization check, which precedes the frozen-posture check, which precedes the commitment-exhaustion check, which precedes account orderability."
        PRD §3.4: "Storage safety first: if any line's product is hazmat and the branch is not hazmat-storage certified, `ERR_BRANCH_NOT_HAZMAT_CERTIFIED` (HTTP 422)."
        PRD §3.4: "Fiscal standing last: a `SUSPENDED` account or one under `credit_hold` is `ERR_ACCOUNT_NOT_ORDERABLE` (HTTP 402)."

        Design: Corner/validations/credit_hold_blocks_confirm_fiscal_after_safety
        """
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"branch_code": "PHX-12", "hazmat_storage_certified": False},
            account_over={"account_number": "DLR-13", "credit_hold": True},
            product_over={
                "sku": "CHLOR-G25", "product_family": "CHEMICAL",
                "hazmat_class": "OXIDIZER_5_1", "base_price_cents": 4000,
            },
            lot_over={"qty_on_hand": 5},
        )
        # WILL_CALL channel keeps the license gate out of play; both the safety
        # check (uncertified branch) and the fiscal check (credit hold) fail.
        order = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="WILL_CALL", lines=[order_line(product["id"], 1)],
        )
        resp = api.confirm_order(
            order["id"],
            {"expected_branch_version": branch_version(branch["id"], api)},
            COUNTER,
        )
        validate_error(resp, ApiErrorId.ERR_BRANCH_NOT_HAZMAT_CERTIFIED)


class TestWillcallAuthorization:
    def test_willcall_unauthorized_account(self, api):
        """PRD §3.4: "Channel authorization fourth: a `WILL_CALL` order for an account whose `willcall_authorized` is false draws `ERR_WILLCALL_NOT_AUTHORIZED` (HTTP 422)."

        Design: Corner/validations/willcall_unauthorized_account
        """
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-14", "willcall_authorized": False},
            product_over={"sku": "POLE-8FT", "product_family": "PARTS", "base_price_cents": 1500},
            lot_over={"qty_on_hand": 5},
        )
        order = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="WILL_CALL", lines=[order_line(product["id"], 1)],
        )
        resp = api.confirm_order(
            order["id"],
            {"expected_branch_version": branch_version(branch["id"], api)},
            COUNTER,
        )
        validate_error(resp, ApiErrorId.ERR_WILLCALL_NOT_AUTHORIZED)
        order = validate_success(api.get_order(order["id"], MGR))
        assert order["fulfillment_status"] == "DRAFT"
