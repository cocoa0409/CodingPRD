"""Used-oil take-back: the two credit variants, the account ledger and its invariant."""

import pytest

from test_helpers import (
    CLOCK_BASE,
    CLOCK_BASE_ISO,
    ApiErrorId,
    TEST_USERS,
    add_order_line,
    apply_credit,
    assert_credit_ledger_conserved,
    assert_order_money_chain,
    confirm_order,
    create_customer,
    find_order_line,
    grant_takeback_credit,
    make_customer_headers,
    open_order,
    read_collection,
    read_customer,
    read_order,
    set_clock,
    setup_commercial_world,
    setup_order_with_credit_balance,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
QC = TEST_USERS["qc_technician_headers"]


def _assayed_collection(api, customer_id, volume=1200.0, water=6.5, sediment=3.0):
    collection = validate_success(
        api.create_takeback_collection(
            {"customer_id": customer_id, "scheduled_volume_l": volume}, SALES
        ),
        201,
    )
    validate_success(
        api.collect_takeback(collection["id"], {"collected_volume_l": volume}, SALES)
    )
    validate_success(
        api.assay_takeback(
            collection["id"], {"water_pct": water, "sediment_pct": sediment}, QC
        )
    )
    return collection


class TestCreditVariants:
    def test_tier_a_account_is_paid_the_flat_rate_even_after_an_assay(self, api):
        """PRD 3.9: "From `ASSAYED`, the variant is `FLAT_RATE` when the account's
        `contract_tier` is `TIER_A`, and `ASSAY_ADJUSTED` when the tier is `TIER_B` or
        `TIER_C`."
        PRD 3.9: "The `FLAT_RATE` variant pays a flat 18 cents per collected litre: multiply
        `collected_volume_l` by 18 and round half up to whole cents."
        PRD 3.9: "It ignores `water_pct` and `sediment_pct` entirely, so a dirty load is paid
        exactly as much as a clean one."
        PRD 3.9: "`takeback_credit_balance_cents` is always recomputed from scratch as the sum
        of `credit_cents` over that account's collections whose status is `CREDITED`, minus the
        sum of `takeback_credit_applied_cents` over that account's orders whose status is
        `CONFIRMED`, `HOLD` or `INVOICED`."

        Design: Difficulty/dual_variant_calc/takeback_credit_flat_rate_vs_assay_adjusted
        """
        set_clock(CLOCK_BASE)
        alpha = create_customer(
            name="Alpha Fleet",
            customer_type="FLEET",
            contract_tier="TIER_A",
            takeback_agreement_status="ACTIVE",
        )
        collection = _assayed_collection(api, alpha["id"])

        credited = validate_success(api.credit_takeback(collection["id"], SALES))
        assert credited["status"] == "CREDITED"
        assert credited["credit_variant"] == "FLAT_RATE"
        assert credited["credit_cents"] == 21600

        assert read_customer(alpha["id"])["takeback_credit_balance_cents"] == 21600

    def test_tier_b_account_is_paid_the_contamination_adjusted_rate(self, api):
        """PRD 3.9: "From `ASSAYED`, the variant is `FLAT_RATE` when the account's
        `contract_tier` is `TIER_A`, and `ASSAY_ADJUSTED` when the tier is `TIER_B` or
        `TIER_C`."
        PRD 3.9: "The `ASSAY_ADJUSTED` variant pays a higher headline 25 cents per litre but
        discounts for contamination: compute a net factor of one minus `water_pct` divided by
        one hundred minus `sediment_pct` divided by one hundred, multiply `collected_volume_l`
        by 25 and by that net factor, round half up to whole cents, and then take the greater of
        the result and zero so the credit is never negative."
        PRD 3.9: "The two variants can land either side of one another depending on how dirty
        the load was."

        Design: Difficulty/dual_variant_calc/takeback_credit_flat_rate_vs_assay_adjusted
        """
        set_clock(CLOCK_BASE)
        alpha = create_customer(
            name="Alpha Fleet",
            customer_type="FLEET",
            contract_tier="TIER_A",
            takeback_agreement_status="ACTIVE",
        )
        bravo = create_customer(
            name="Bravo Distribution",
            customer_type="DISTRIBUTOR",
            contract_tier="TIER_B",
            takeback_agreement_status="ACTIVE",
        )
        alpha_collection = _assayed_collection(api, alpha["id"])
        bravo_collection = _assayed_collection(api, bravo["id"])

        alpha_credited = validate_success(api.credit_takeback(alpha_collection["id"], SALES))
        bravo_credited = validate_success(api.credit_takeback(bravo_collection["id"], SALES))

        assert bravo_credited["credit_variant"] == "ASSAY_ADJUSTED"
        assert bravo_credited["credit_cents"] == 27150
        assert bravo_credited["credit_cents"] - alpha_credited["credit_cents"] == 5550

        assert read_customer(bravo["id"])["takeback_credit_balance_cents"] == 27150

    def test_crediting_straight_from_collected_takes_the_flat_branch(self, api):
        """PRD 3.9: "Granting the credit is a `SalesRep` action reachable from two originating
        states, and which one it comes from changes the arithmetic."
        PRD 3.9: "From `COLLECTED` — that is, with no assay on file — the variant is always
        `FLAT_RATE`."
        PRD 3.9: "The `FLAT_RATE` variant pays a flat 18 cents per collected litre: multiply
        `collected_volume_l` by 18 and round half up to whole cents."
        PRD 3.9: "Every recomputation — on a credit grant, on a credit draw, and on a void —
        also stamps the account's `version` upward by 1, and a grant or a draw additionally
        stamps `last_credit_event_at` from the logical clock."

        Design: Corner/calculations/takeback_flat_rate_variant_selected_when_credited_without_assay
        """
        set_clock(CLOCK_BASE)
        bravo = create_customer(
            name="Bravo Distribution",
            customer_type="DISTRIBUTOR",
            contract_tier="TIER_B",
            takeback_agreement_status="ACTIVE",
        )
        collection = validate_success(
            api.create_takeback_collection(
                {"customer_id": bravo["id"], "scheduled_volume_l": 1200.0}, SALES
            ),
            201,
        )
        validate_success(
            api.collect_takeback(collection["id"], {"collected_volume_l": 1200.0}, SALES)
        )

        credited = validate_success(api.credit_takeback(collection["id"], SALES))
        assert credited["status"] == "CREDITED"
        assert credited["credit_variant"] == "FLAT_RATE"
        assert credited["credit_cents"] == 21600
        assert credited["credit_cents"] != 27150

        account = read_customer(bravo["id"])
        assert account["takeback_credit_balance_cents"] == 21600
        assert account["last_credit_event_at"] == CLOCK_BASE_ISO

    def test_assay_above_the_contamination_cap_rejects_the_load_outright(self, api):
        """PRD 3.9: "Contamination is capped at a combined 25 percent: where `water_pct` plus
        `sediment_pct` is at most 25, the collection moves `COLLECTED → ASSAYED` and both
        figures are stored; where the sum exceeds 25, the collection moves
        `COLLECTED → REJECTED` instead, both figures are still stored, `reject_reason` is set to
        `CONTAMINATION_ABOVE_LIMIT`, `credit_cents` stays at 0 and `credit_variant` stays null."
        PRD 2.6: "10. Own-state legality — the target resource sits in a declared originating
        state for the requested transition; otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/takeback_assay_above_contamination_limit_rejects_collection
        """
        set_clock(CLOCK_BASE)
        bravo = create_customer(
            name="Bravo Distribution",
            customer_type="DISTRIBUTOR",
            contract_tier="TIER_B",
            takeback_agreement_status="ACTIVE",
        )
        collection = validate_success(
            api.create_takeback_collection(
                {"customer_id": bravo["id"], "scheduled_volume_l": 1200.0}, SALES
            ),
            201,
        )
        validate_success(
            api.collect_takeback(collection["id"], {"collected_volume_l": 1200.0}, SALES)
        )

        assayed = validate_success(
            api.assay_takeback(
                collection["id"], {"water_pct": 20.0, "sediment_pct": 6.0}, QC
            )
        )
        assert assayed["status"] == "REJECTED"
        assert assayed["reject_reason"] == "CONTAMINATION_ABOVE_LIMIT"
        assert assayed["credit_cents"] == 0
        assert assayed["credit_variant"] is None

        refused = api.credit_takeback(collection["id"], SALES)
        validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value, 409)
        assert read_customer(bravo["id"])["takeback_credit_balance_cents"] == 0


class TestCreditDrawGuards:
    def test_draw_against_an_empty_ledger_is_refused(self, api):
        """PRD 3.9: "And the order must be take-back linked with a positive balance on the
        account: a draw against an order whose `takeback_linked` is false, or against an account
        whose `takeback_credit_balance_cents` is 0, is refused with `ERR_NO_TAKEBACK_CREDIT`."
        PRD 3.9: "On registration `takeback_credit_balance_cents` is initialised to 0 and
        `last_credit_event_at` is null until the first credit event on the account."
        PRD 2.6: "37. Credit availability — the order is take-back linked and the account's
        credit balance is greater than zero; otherwise `ERR_NO_TAKEBACK_CREDIT` (422). Guards
        drawing take-back credit."

        Design: Corner/errors/apply_takeback_credit_with_zero_balance_returns_no_takeback_credit
        """
        world = setup_commercial_world(
            customer_overrides={
                "name": "Foxtrot Garages",
                "takeback_agreement_status": "ACTIVE",
            }
        )
        order = open_order(world["customer"]["id"], takeback_linked=True)
        add_order_line(order["id"], world["cfg_pail"]["id"], 37)
        confirm_order(order["id"])

        account = read_customer(world["customer"]["id"])
        assert account["takeback_credit_balance_cents"] == 0

        response = api.apply_takeback_credit(
            order["id"], {"expected_customer_version": account["version"]}, SALES
        )
        error = validate_error(response, ApiErrorId.ERR_NO_TAKEBACK_CREDIT.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_STALE_CUSTOMER_VERSION.value

        refreshed = read_order(order["id"])
        assert refreshed["takeback_credit_applied_cents"] == 0
        assert refreshed["total_cents"] == 400728

    def test_second_draw_carrying_the_pre_draw_account_version_is_rejected(self, api):
        """PRD 2.8: "Drawing used-oil credit against an order requires a non-optional
        `expected_customer_version` in the request body, carrying the client's last observed
        `version` of the order's buying account."
        PRD 2.8: "A customer may legitimately draw credit against more than one order, so
        applying credit to a second order is allowed on its own merits; but if the supplied value
        no longer equals that account's current `version`, the draw is rejected with
        `ERR_STALE_CUSTOMER_VERSION` and HTTP 412, because the caller's view of
        `takeback_credit_balance_cents` predates an earlier grant or draw-down and the amount it
        intends to apply is stale."
        PRD 3.9: "A successful draw runs steps four and five of the waterfall, writing
        `takeback_credit_applied_cents` and `total_cents`, then recomputes the account's
        `takeback_credit_balance_cents`, stamps `last_credit_event_at`, and advances both the
        account's and the order's `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_customer_version_rejects_second_credit_application
        """
        world = setup_order_with_credit_balance(lines=[("cfg_pail", 37)])
        second_order = open_order(world["customer"]["id"], takeback_linked=True)
        add_order_line(second_order["id"], world["cfg_pail"]["id"], 37)
        confirm_order(second_order["id"])

        observed_version = read_customer(world["customer"]["id"])["version"]

        first = validate_success(
            api.apply_takeback_credit(
                world["order"]["id"], {"expected_customer_version": observed_version}, SALES
            )
        )
        assert first["takeback_credit_applied_cents"] == 60109
        assert first["total_cents"] == 340619
        assert read_customer(world["customer"]["id"])["takeback_credit_balance_cents"] == 1297391

        stale = api.apply_takeback_credit(
            second_order["id"], {"expected_customer_version": observed_version}, SALES
        )
        validate_error(stale, ApiErrorId.ERR_STALE_CUSTOMER_VERSION.value, 412)

        untouched = read_order(second_order["id"])
        assert untouched["takeback_credit_applied_cents"] == 0
        assert untouched["total_cents"] == 400728
        assert read_customer(world["customer"]["id"])["takeback_credit_balance_cents"] == 1297391


class TestLedgerConservation:
    def test_voiding_an_order_returns_its_applied_credit_to_the_ledger(self, api):
        """PRD 2.9: "The second is **money**: for every account, granted take-back credit minus
        applied take-back credit is invariant."
        PRD 2.9: "Voiding an order zeroes that order's applied credit and drops it out of the
        applied sum, so an apply-then-void sequence restores `takeback_credit_balance_cents`
        exactly."
        PRD 3.8: "Where the order being voided was `CONFIRMED` or `HOLD`, the void is also the
        compensating action for a credit draw: `takeback_credit_applied_cents` is reset to 0,
        `total_cents` is recomputed as `pre_credit_total_cents`, the account's
        `takeback_credit_balance_cents` is recomputed, and the account's `version` is advanced by
        1."

        Design: Difficulty/compensating_invariant/order_void_conserves_customer_takeback_credit_ledger
        """
        world = setup_order_with_credit_balance()
        apply_credit(world)
        assert world["order"]["takeback_credit_applied_cents"] == 130090
        assert read_customer(world["customer"]["id"])["takeback_credit_balance_cents"] == 1227410

        voided = validate_success(
            api.void_order(world["order"]["id"], {"reason": "CUSTOMER_CANCELLED"}, SALES)
        )
        assert voided["status"] == "VOID"
        assert voided["takeback_credit_applied_cents"] == 0
        assert voided["pre_credit_total_cents"] == 867272
        assert voided["total_cents"] == 867272
        assert_order_money_chain(voided)

        assert read_customer(world["customer"]["id"])["takeback_credit_balance_cents"] == 1357500

    def test_voided_order_cancels_its_lines_and_leaves_the_grant_intact(self, api):
        """PRD 3.8: "Voiding is reachable from `DRAFT`, `CONFIRMED` and `HOLD`, always with a
        `reason`, and `VOID` is terminal."
        PRD 3.8: "Every line on the order in `OPEN` or `HOLD` moves to `CANCELLED`."
        PRD 3.9: "`takeback_credit_balance_cents` is always recomputed from scratch as the sum
        of `credit_cents` over that account's collections whose status is `CREDITED`, minus the
        sum of `takeback_credit_applied_cents` over that account's orders whose status is
        `CONFIRMED`, `HOLD` or `INVOICED`."
        PRD 3.9: "Collections in `SCHEDULED`, `COLLECTED`, `ASSAYED` or `REJECTED` contribute
        nothing to the first sum, and orders in `DRAFT` or `VOID` contribute nothing to the
        second."

        Design: Difficulty/compensating_invariant/order_void_conserves_customer_takeback_credit_ledger
        """
        world = setup_order_with_credit_balance()
        apply_credit(world)
        first_line, second_line = world["lines"]

        voided = validate_success(
            api.void_order(world["order"]["id"], {"reason": "CUSTOMER_CANCELLED"}, SALES)
        )

        assert find_order_line(world["order"]["id"], first_line["id"])["status"] == "CANCELLED"
        assert find_order_line(world["order"]["id"], second_line["id"])["status"] == "CANCELLED"

        collection = read_collection(world["collection"]["id"])
        assert collection["status"] == "CREDITED"
        assert collection["credit_cents"] == 1357500

        account = read_customer(world["customer"]["id"])
        assert_credit_ledger_conserved(account, [collection], [voided])
        assert account["takeback_credit_balance_cents"] == 1357500


class TestAccountScope:
    def test_a_buying_account_may_not_read_another_accounts_order(self, api):
        """PRD 2.1: "A caller acting as `Customer` may only read or write resources whose
        `customer_id` equals the caller's `X-User-ID`; any attempt to read another account,
        another account's orders or order lines, or another account's take-back collections, or
        to schedule a collection naming another account, is rejected with
        `ERR_CUSTOMER_SCOPE_VIOLATION` and HTTP 403."
        PRD 2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
        customer account, and ownership checks on any resource that references a customer account
        compare that resource's customer reference to `X-User-ID` directly."

        Design: Corner/errors/customer_role_cannot_read_another_accounts_order
        """
        set_clock(CLOCK_BASE)
        alpha = create_customer(
            name="Alpha Fleet",
            customer_type="FLEET",
            contract_tier="TIER_A",
            takeback_agreement_status="ACTIVE",
        )
        bravo = create_customer(
            name="Bravo Distribution",
            customer_type="DISTRIBUTOR",
            contract_tier="TIER_B",
            takeback_agreement_status="ACTIVE",
        )
        order = open_order(alpha["id"])

        intruder = api.get_order(order["id"], make_customer_headers(bravo["id"]))
        validate_error(intruder, ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION.value, 403)

        owner = validate_success(
            api.get_order(order["id"], make_customer_headers(alpha["id"]))
        )
        assert owner["id"] == order["id"]
        assert owner["customer_id"] == alpha["id"]
