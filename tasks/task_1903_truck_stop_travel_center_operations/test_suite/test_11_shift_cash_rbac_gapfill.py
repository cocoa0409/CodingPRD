"""Shift cash lifecycle gap-fill: validation pipeline ordering (auth before
existence), segregation of duties on shift close and payouts, drop/payout
fiscal bounds, register posture cascade across a payout, and the pinned
expected-then-deposit close arithmetic."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    build_user_headers,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.constants import TEST_CLOCK_ISO
from test_helpers.factories import (
    create_fuel_price_payload,
    create_store_sale_payload,
    create_work_order_payload,
    member_adjustment_payload,
    shift_close_payload,
    shift_drop_payload,
    shift_payout_payload,
    work_order_estimate_payload,
)
from test_helpers.fixtures import (
    CASH_1,
    FDL,
    GM,
    SM_1,
    SM_2,
    authorize_retail_sale,
    create_fleet,
    create_member,
    create_site,
    create_stock_item,
    create_technician,
    dispensing_complete,
    dispensing_start,
    finalize_sale,
    make_fleet_manager_headers,
    make_loyalty_member_headers,
    make_maintenance_tech_headers,
    pay_sale_cash,
    reload_shift,
    set_clock,
    setup_enrolled_member,
    setup_fuel_site,
    setup_shift_site,
)


class TestValidationPipelineOrdering:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD section 2.1: "A request with either header missing, or with a
        role string outside the declared set, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD section 2.10: "Authentication comes first: missing or unknown
        headers fail with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/validation_missing_auth_header_returns_401
        """
        resp = api.list_sites(None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_wrong_role_beats_missing_site(self, api):
        """PRD section 2.10: "Role authorization follows, then entity-backed
        identity scoping, both failing with `ERR_FORBIDDEN`; ... Existence
        checks follow: path identifiers are validated left to right ... and
        any miss is `ERR_NOT_FOUND` (HTTP 404)."
        PRD section 3.2 endpoint table: POST /sites/{id}/fuel-prices is a
        `FuelDeskLead` operation, so a Cashier is refused before the site's
        existence is consulted.

        Design: Corner/validations/validation_wrong_role_and_missing_site_returns_forbidden
        """
        site = create_site("Site V3")
        resp = api.create_fuel_price(
            NON_EXISTENT_UUID,
            create_fuel_price_payload(site["version"], "DIESEL", 385),
            CASH_1,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_unknown_site_segment_returns_not_found(self, api):
        """PRD section 2.10: "Existence checks follow: path identifiers are
        validated left to right, each child required to belong to the site or
        parent scope named in the path, and any miss is `ERR_NOT_FOUND`
        (HTTP 404)".

        Design: Corner/validations/validation_unknown_site_returns_not_found
        """
        resp = api.list_pumps(NON_EXISTENT_UUID, GM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestShiftStateGuards:
    def test_drop_on_closed_shift_rejected(self, api):
        """PRD section 2.8: "Any money-affecting operation — drops, payouts,
        cash payments of any kind, and close itself — requires its target
        shift to be `OPEN`; against a closed, reconciled, or locked shift the
        operation is rejected with `ERR_SHIFT_NOT_OPEN` (HTTP 409)."

        Design: Corner/errors/error_shift_not_open_after_close
        """
        ctx = setup_shift_site("Site R1")
        close = validate_success(
            api.shift_close(ctx.shift["id"], shift_close_payload(20000), SM_2)
        )
        assert close["status"] == "CLOSED"

        resp = api.shift_drop(
            ctx.shift["id"], shift_drop_payload(1000, {"1000": 1}), CASH_1
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_OPEN)

        drops = get_success_data(api.list_shift_cash_drops(ctx.shift["id"], SM_2))
        assert drops == [], "rejected drop must not persist a CashDrop row"

    def test_second_open_shift_on_register_rejected(self, api):
        """PRD section 3.8: "The register must have no other `OPEN` shift,
        else `ERR_REGISTER_NOT_AVAILABLE` (HTTP 409)."

        Design: Corner/errors/error_register_not_available_second_shift
        """
        ctx = setup_shift_site("Site R2")
        resp = api.create_shift(
            ctx.site["id"],
            {
                "register_id": ctx.register["id"],
                "cashier_user_id": "cash-2",
                "shift_label": "NIGHT",
            },
            SM_2,
        )
        validate_error(resp, ApiErrorId.ERR_REGISTER_NOT_AVAILABLE)
        assert reload_shift(ctx.shift["id"])["status"] == "OPEN"


class TestSegregationOfDuties:
    def test_close_by_opening_manager_rejected(self, api):
        """PRD section 2.1: "Segregation of duties is enforced on the shift
        cash lifecycle: the manager closing a shift must not be the manager
        who opened it, ... Any of these collisions is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/errors/error_segregation_close_by_opener
        """
        ctx = setup_shift_site("Site R10")
        resp = api.shift_close(
            ctx.shift["id"], shift_close_payload(20000), SM_1
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        closed = validate_success(
            api.shift_close(ctx.shift["id"], shift_close_payload(20000), SM_2)
        )
        assert closed["status"] == "CLOSED"

    def test_payout_by_owning_cashier_rejected(self, api):
        """PRD section 2.1: "the manager approving a payout must not be the
        cashier who owns that shift's drawer. Any of these collisions is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/errors/error_segregation_payout_by_cashier
        """
        ctx = setup_shift_site("Site R11")
        # A ShiftManager whose user id equals the shift's cashier_user_id.
        cashier_as_manager = build_user_headers("cash-1", "ShiftManager")
        resp = api.shift_payout(
            ctx.shift["id"],
            shift_payout_payload(5000, "manager covering till"),
            cashier_as_manager,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestRoleExclusiveOperations:
    def test_cashier_cannot_post_fuel_price(self, api):
        """PRD section 2.1: "`FuelDeskLead` — the fuel desk lead; posts
        retail fuel prices, takes pumps out of and back into service, and
        records bulk tank stick readings and deliveries."
        PRD section 2.1: "A request whose role is not in the endpoint's
        authorized set is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 3.2: "A successful posting recomputes the site's retail
        mirrors — each mirror reflects the currently effective `ACTIVE` price
        for its fuel, or null when none is in force".

        Design: Corner/rbac/rbac_cashier_cannot_post_fuel_price
        """
        site = create_site("Site RB1")
        # Post while the logical clock still reads its initial value so the
        # window's effective_from is not in the past (PRD 3.1); the clock is
        # advanced only after the price is in place.
        payload = create_fuel_price_payload(
            site["version"], "DIESEL", 385, effective_from="2026-08-01T00:00:00Z"
        )
        resp = api.create_fuel_price(site["id"], payload, CASH_1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        price = validate_success(
            api.create_fuel_price(site["id"], payload, FDL), 201
        )
        assert price["retail_cents_per_gallon"] == 385
        set_clock(TEST_CLOCK_ISO)
        site_now = validate_success(api.get_site(site["id"], FDL))
        assert site_now["diesel_retail_cents_per_gallon"] == 385

    def test_fleet_manager_scope_limited_to_own_fleet(self, api):
        """PRD section 2.1: "When `X-User-Role` is `FleetManager`, `X-User-ID`
        is the `id` of the acting `FleetAccount`; the caller may read only its
        own fleet subtree (its account, contracts, fuel sales, work orders,
        and linked loyalty members) and may approve an estimate only on a work
        order whose `fleet_account_id` equals `X-User-ID`. ... Violations of
        these entity-backed scoping rules are rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/rbac_fleet_manager_scope_limited
        """
        fleet_a = create_fleet("Fleet A", 5_000_000, "T1")
        fleet_b = create_fleet("Fleet B", 5_000_000, "T1")
        site = create_site("Site RB3")
        tech = create_technician(site["id"], "Tech One", 12500)
        wo = validate_success(
            api.create_work_order(
                site["id"],
                create_work_order_payload(
                    "TRK-1", "fleet work", fleet_account_id=fleet_a["id"]
                ),
                CASH_1,
            ),
            201,
        )
        validate_success(
            api.work_order_estimate(
                wo["id"],
                work_order_estimate_payload(1.0),
                make_maintenance_tech_headers(tech["id"]),
            )
        )

        fm_a = make_fleet_manager_headers(fleet_a["id"])
        resp = api.get_fleet_account(fleet_b["id"], fm_a)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        own = validate_success(api.get_fleet_account(fleet_a["id"], fm_a))
        assert own["name"] == "Fleet A"

        approved = validate_success(
            api.work_order_approve_estimate(wo["id"], fm_a)
        )
        assert approved["status"] == "APPROVED"

    def test_member_cannot_adjust_own_points(self, api):
        """PRD section 2.1: "`GeneralManager` — the site general manager; the
        superset role for site configuration, fleet and contract
        administration, points adjustments, discount-network governance,
        purchase-order approval, shift lock, and control of the logical
        clock."
        PRD section 2.9: "Manual adjustments created by a `GeneralManager`
        use the same machinery: a positive `points_delta` writes a normal
        lot, a negative `points_delta` claws back newest-first, and every
        adjustment carries a `reason`."
        PRD section 2.1: "A request whose role is not in the endpoint's
        authorized set is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_member_cannot_adjust_points
        """
        member = create_member(full_name="Driver A", email="a@x.com")
        resp = api.member_adjustment(
            member["id"],
            member_adjustment_payload(1000, "self serve"),
            make_loyalty_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestShiftFiscalBounds:
    def test_drop_denominations_must_sum_to_amount(self, api):
        """PRD section 3.8: "The owning cashier records a cash drop to the
        safe with an `amount_cents` and a `denominations` map from
        denomination cents to bill count; the map must sum exactly to the
        declared amount, else `ERR_DROP_MISMATCH` (HTTP 422)".

        Design: Corner/validations/validation_drop_denominations_mismatch
        """
        ctx = setup_shift_site("Site V7")
        resp = api.shift_drop(
            ctx.shift["id"],
            shift_drop_payload(4000, {"2000": 2, "100": 1}),
            CASH_1,
        )
        validate_error(resp, ApiErrorId.ERR_DROP_MISMATCH)
        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 20000

    def test_drop_exceeds_amount_above_float(self, api):
        """PRD section 3.8: "the amount may not exceed the shift's expected
        cash above its opening float — the drawer always keeps at least the
        float — else `ERR_DROP_EXCEEDS_EXPECTED` (HTTP 422)".

        Design: Corner/validations/validation_drop_exceeds_above_float
        """
        ctx = setup_shift_site("Site V8")
        # Fresh shift: expected equals the float, so even one cent is over.
        resp = api.shift_drop(
            ctx.shift["id"], shift_drop_payload(1, {"1": 1}), CASH_1
        )
        validate_error(resp, ApiErrorId.ERR_DROP_EXCEEDS_EXPECTED)

    def test_payout_exceeds_expected_rejected_exact_amount_succeeds(self, api):
        """PRD section 3.8: "a `ShiftManager` who is not the shift's cashier
        approves an `amount_cents` with a `reason`, the amount may not exceed
        the shift's full `expected_cash_cents` else
        `ERR_PAYOUT_EXCEEDS_EXPECTED` (HTTP 422), and approval decrements
        expected cash and recomputes posture".

        Design: Corner/validations/validation_payout_exceeds_expected
        """
        ctx = setup_shift_site("Site V9")
        resp = api.shift_payout(
            ctx.shift["id"], shift_payout_payload(20001, "too much"), SM_2
        )
        validate_error(resp, ApiErrorId.ERR_PAYOUT_EXCEEDS_EXPECTED)

        payout = validate_success(
            api.shift_payout(
                ctx.shift["id"], shift_payout_payload(20000, "exact"), SM_2
            ),
            201,
        )
        assert payout["expected_cash_cents"] == 0

    def test_close_variance_unapproved_then_approved(self, api):
        """PRD section 3.8: "The closer supplies the physical
        `counted_cash_cents`; when the absolute difference between counted and
        expected exceeds 500 cents, the close must explicitly carry
        `approve_variance` set true, else `ERR_COUNT_SHORTAGE_UNAPPROVED`
        (HTTP 422). A successful close ... writes the audit trail: a
        `ShiftReconciliation` capturing the expected figure at close, the
        counted figure, their signed `variance_cents` (positive meaning
        overage), a `resolution` of `BALANCED` when the variance is zero,
        `OVERAGE` when positive, or `SHORTAGE` when negative".

        Design: Corner/validations/validation_close_variance_unapproved_then_approved
        """
        ctx = setup_shift_site("Site V10")
        # variance -700, beyond the 500-cent tolerance: unapproved close fails.
        resp = api.shift_close(
            ctx.shift["id"], shift_close_payload(19300), SM_2
        )
        validate_error(resp, ApiErrorId.ERR_COUNT_SHORTAGE_UNAPPROVED)

        closed = validate_success(
            api.shift_close(
                ctx.shift["id"],
                shift_close_payload(19300, approve_variance=True),
                SM_2,
            )
        )
        assert closed["status"] == "CLOSED"

        recon = get_success_data(
            api.list_shift_reconciliations(ctx.shift["id"], SM_2)
        )
        assert recon[0]["variance_cents"] == -700
        assert recon[0]["resolution"] == "SHORTAGE"


class TestShiftCashArithmetic:
    def _setup_shift_with_cash_sales(self, site_name):
        """Fuel site + member seeded with 9000 points and an ACTIVE FleetPass
        enrollment; a paid CASH fuel sale (retail 385 c/gal, 200 points
        redeemed, 40.000 authorized / 38.000 dispensed -> 10450 cents) and a
        CASH store sale of 999 + 150 = 1149 cents on the open shift."""
        ctx = setup_fuel_site(site_name, diesel_cents=385)
        enrolled = setup_enrolled_member(points=9000)
        item_a = create_stock_item(
            ctx.site["id"], sku="SNACK-A", name="Snack A", category="RETAIL",
            unit_price_cents=999, reorder_point=5, initial_on_hand_quantity=50,
        )
        item_b = create_stock_item(
            ctx.site["id"], sku="DRINK-B", name="Drink B", category="RETAIL",
            unit_price_cents=150, reorder_point=5, initial_on_hand_quantity=50,
        )
        sale = authorize_retail_sale(
            ctx, member_id=enrolled.member["id"], redeem_points=200,
            max_gallons=40.0,
        )
        dispensing_start(sale["id"])
        dispensing_complete(sale["id"], 38.0)
        finalize_sale(sale["id"])
        pay_sale_cash(sale["id"])
        store_sale = validate_success(
            self._store_sale(api_client, ctx, item_a, item_b), 201
        )
        assert store_sale["total_cents"] == 1149
        return ctx

    @staticmethod
    def _store_sale(api, ctx, item_a, item_b):
        """Ring up the two-item CASH store sale (999 + 150) on the shift."""
        return api.create_store_sale(
            ctx.site["id"],
            create_store_sale_payload(
                ctx.shift["id"],
                [
                    {"stock_item_id": item_a["id"], "quantity": 1},
                    {"stock_item_id": item_b["id"], "quantity": 1},
                ],
                tender_type="CASH",
            ),
            CASH_1,
        )

    def test_expected_cash_then_deposit_order_at_close(self, api):
        """PRD section 2.8: "The evaluation order is pinned to remove any
        circular reading between the expected position and the bank deposit:
        first, expected cash equals the shift's `opening_float_cents`, plus
        every cash receipt attributed to the shift (cash fuel payments, cash
        store sales, cash parking check-in charges, cash service payments,
        cash scale settlements, and cash work-order collections), minus every
        approved payout, minus every posted cash drop, minus every cash refund
        attributed to the shift; second, at close only, the deposit total is
        the amount by which expected cash exceeds the opening float, floored
        at zero; third, the variance is the physical count minus the expected
        position, a positive value being an overage."

        Design: Difficulty/combinatorial_formula/shift_expected_then_deposit_order
        """
        ctx = self._setup_shift_with_cash_sales("Site E")
        # 20000 float + 10450 cash fuel = 30450; store sale adds 1149 more.
        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 31599

        payout = validate_success(
            api.shift_payout(
                ctx.shift["id"], shift_payout_payload(5000, "vendor payout"),
                SM_2,
            ),
            201,
        )
        assert payout["expected_cash_cents"] == 26599

        closed = validate_success(
            api.shift_close(ctx.shift["id"], shift_close_payload(26599), SM_2)
        )
        assert closed["status"] == "CLOSED"

        recon = get_success_data(
            api.list_shift_reconciliations(ctx.shift["id"], SM_2)
        )
        assert recon[0]["expected_cash_cents"] == 26599
        assert recon[0]["variance_cents"] == 0
        assert recon[0]["resolution"] == "BALANCED"
        # deposit = max(0, 26599 - 20000), derived FROM expected at close.
        assert recon[0]["deposit_total_cents"] == 6599

        deposits = get_success_data(
            api.list_shift_safe_deposits(ctx.shift["id"], SM_2)
        )
        assert deposits[0]["amount_cents"] == 6599

    def test_cash_conservation_across_posted_drop(self, api):
        """PRD section 2.8: "expected cash equals the shift's
        `opening_float_cents`, plus every cash receipt attributed to the shift
        ... minus every approved payout, minus every posted cash drop, minus
        every cash refund attributed to the shift".
        PRD section 3.8: "A posted drop is a `POSTED` `CashDrop` that
        decrements the shift's expected cash and recomputes posture." and
        "whenever that deposit total is greater than zero, a `SafeDeposit` in
        status `RECORDED` for the same amount".

        Design: Difficulty/compensating_invariant/shift_cash_conservation_across_drop
        """
        ctx = self._setup_shift_with_cash_sales("Site Q")
        validate_success(
            api.shift_payout(
                ctx.shift["id"], shift_payout_payload(5000, "vendor payout"),
                SM_2,
            ),
            201,
        )
        # 20000 + 10450 + 1149 - 5000 = 26599 ahead of the drop.
        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 26599

        # 3x2000 + 5x100 + 3x25 + 24x1 = 6599 == amount_cents.
        drop = validate_success(
            api.shift_drop(
                ctx.shift["id"],
                shift_drop_payload(
                    6599, {"2000": 3, "100": 5, "25": 3, "1": 24}
                ),
                CASH_1,
            ),
            201,
        )
        assert drop["status"] == "POSTED"

        # Conservation: 20000 + 6599 (drops) - 20000 (float) == 11599
        # (receipts) - 5000 (payouts) == 6599.
        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 20000

        closed = validate_success(
            api.shift_close(ctx.shift["id"], shift_close_payload(20000), SM_2)
        )
        assert closed["status"] == "CLOSED"

        recon = get_success_data(
            api.list_shift_reconciliations(ctx.shift["id"], SM_2)
        )
        assert recon[0]["variance_cents"] == 0
        # Expected cash sits exactly at the float: no deposit is recorded.
        assert recon[0]["deposit_total_cents"] == 0
        deposits = get_success_data(
            api.list_shift_safe_deposits(ctx.shift["id"], SM_2)
        )
        assert deposits == []

    def test_payout_flips_posture_then_blocks_close(self, api):
        """PRD section 2.8: "Posture is `NEEDS_DROP` when the open shift's
        expected cash exceeds five times the register's `float_cents`,
        `LOW_FLOAT` when expected cash has fallen below one times the float
        (the drawer holds less than its standard float), and `OK` otherwise."
        PRD section 3.8: "a payout may flip the register to `LOW_FLOAT`" and
        "Closing the shift ... requires the drawer to still hold at least the
        float: expected cash below `opening_float_cents` is rejected with
        `ERR_REMAINING_BELOW_FLOAT` (HTTP 422)."

        Design: Difficulty/transitive_cascade/payout_expected_posture_close_block
        """
        ctx = setup_fuel_site("Site H", diesel_cents=385)
        enrolled = setup_enrolled_member(points=9000)
        sale = authorize_retail_sale(
            ctx, member_id=enrolled.member["id"], redeem_points=200,
            max_gallons=40.0,
        )
        dispensing_start(sale["id"])
        dispensing_complete(sale["id"], 38.0)
        finalize_sale(sale["id"])
        pay_sale_cash(sale["id"])
        # Hop 0: 20000 float + 10450 cash fuel = 30450 expected -> OK.
        assert validate_success(
            api.get_register(ctx.register["id"], SM_2)
        )["posture"] == "OK"

        # Hop 1: payout mutates Shift.expected_cash_cents 30450 -> 5450.
        payout = validate_success(
            api.shift_payout(
                ctx.shift["id"],
                shift_payout_payload(25000, "armored car early pickup"),
                SM_2,
            ),
            201,
        )
        assert payout["expected_cash_cents"] == 5450

        # Hop 2: the shift mutation flips Register.posture OK -> LOW_FLOAT.
        assert validate_success(
            api.get_register(ctx.register["id"], SM_2)
        )["posture"] == "LOW_FLOAT"

        # Hop 3: expected 5450 < float 20000 blocks the close.
        resp = api.shift_close(
            ctx.shift["id"], shift_close_payload(5450), SM_2
        )
        validate_error(resp, ApiErrorId.ERR_REMAINING_BELOW_FLOAT)
        assert reload_shift(ctx.shift["id"])["status"] == "OPEN"
