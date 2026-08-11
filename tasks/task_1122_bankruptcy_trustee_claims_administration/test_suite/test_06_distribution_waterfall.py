"""Distribution plans and the priority waterfall: pro-rata rounding, secured
cap and deficiency spill, cascades, dividend voiding, OCC on confirm."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_sale_payload, file_claim_payload,
    make_creditor_headers, create_creditor, create_asset, file_claim,
    get_case, get_case_version, set_clock, review_claim, allow_claim,
    review_and_allow_claim, object_to_claim, create_judgment_action,
    file_fee_application, propose_plan, confirm_plan, get_plan_dividends,
    dividend_for_claim, setup_case_in_claims_administration,
    setup_case_in_liquidation, setup_case_in_distribution,
)

TRUSTEE = TEST_USERS["trustee_headers"]
CLERK = TEST_USERS["clerk_headers"]
COURT = TEST_USERS["court_headers"]


def _drive_sale_and_distribution(ctx, hammer, costs=0):
    """From LIQUIDATION: mark the ctx asset, sell it, consummate, DISTRIBUTION."""
    case_id = ctx["case"]["id"]
    asset_id = ctx["asset"]["id"]
    get_success_data(api_client.mark_asset_for_sale(asset_id, TRUSTEE))
    sale = get_success_data(api_client.create_sale(
        case_id, create_sale_payload(asset_id=asset_id,
                                     hammer_price_cents=hammer,
                                     sale_costs_cents=costs), TRUSTEE))
    get_success_data(api_client.approve_sale(sale["id"], COURT))
    set_clock("2026-06-04T00:00:00Z")
    get_success_data(api_client.consummate_sale(sale["id"], TRUSTEE))
    get_success_data(api_client.begin_distribution(case_id, TRUSTEE))
    return sale


class TestProrataRemainder:
    def _three_claim_case(self):
        """DISTRIBUTION with three ALLOWED GENERAL_UNSECURED claims of 100,000
        cents each (claim_numbers 1,2,3 in filing order) and estate cash of
        exactly 100,000."""
        ctx = setup_case_in_claims_administration(case_number="26-10004",
                                                  objection_window_days=1,
                                                  scheduled_value_cents=150000)
        case_id = ctx["case"]["id"]
        cred_id = ctx["creditor"]["id"]
        claims = [
            file_claim(case_id, cred_id, received_at="2026-02-01T00:00:00Z"),
            file_claim(case_id, cred_id, received_at="2026-02-02T00:00:00Z"),
            file_claim(case_id, cred_id, received_at="2026-02-03T00:00:00Z"),
        ]
        for c in claims:
            review_and_allow_claim(c["id"])
        set_clock("2026-06-02T00:00:00Z")
        get_success_data(api_client.begin_liquidation(case_id, TRUSTEE))
        _drive_sale_and_distribution(ctx, hammer=100000)
        plan = propose_plan(case_id)
        confirm_plan(plan["id"], case_id)
        return ctx, claims, plan

    def test_floor_per_claim_then_remainder_to_last(self, api):
        """PRD §3.6: "otherwise each claim's dividend is its allowed amount
        multiplied by the class grant and divided by the class need, floored to
        whole cents — for every claim except the last one in the class's
        ordering, which is pinned by `claim_number` ascending and never by
        `id`; that last claim receives the class grant minus the sum of the
        previously computed dividends, so the class total matches the grant
        exactly."

        Three claims of 100,000 sharing a 100,000 grant: 33,333 / 33,333 /
        33,334.

        Design: Difficulty/combinatorial_formula/waterfall_prorata_floor_then_remainder_to_last_claim
        """
        ctx, claims, plan = self._three_claim_case()
        amounts = sorted(
            (dividend_for_claim(plan["id"], c["id"])[0]["amount_cents"]
             for c in claims))
        assert amounts == [33333, 33333, 33334]
        assert sum(amounts) == 100000, "class total matches the grant exactly"

    def test_remainder_goes_to_highest_claim_number(self, api):
        """PRD §3.6: "otherwise each claim's dividend is its allowed amount
        multiplied by the class grant and divided by the class need, floored to
        whole cents — for every claim except the last one in the class's
        ordering, which is pinned by `claim_number` ascending and never by
        `id`; that last claim receives the class grant minus the sum of the
        previously computed dividends, so the class total matches the grant
        exactly."

        Design: Difficulty/combinatorial_formula/waterfall_prorata_floor_then_remainder_to_last_claim
        """
        ctx, claims, plan = self._three_claim_case()
        by_number = sorted(
            ((validate_success(api.get_claim(c["id"], TRUSTEE))["claim_number"],
              dividend_for_claim(plan["id"], c["id"])[0]["amount_cents"])
             for c in claims))
        assert by_number[0][1] == 33333
        assert by_number[1][1] == 33333
        assert by_number[2][1] == 33334, \
            "the last claim by claim_number ascending receives the remainder"


class TestSecuredCapAndDeficiencySpill:
    def test_waterfall_secured_cap_and_deficiency_spill(self, api):
        """PRD §3.6: "each class's need is the sum of `allowed_amount_cents`
        over its `ALLOWED` claims — except that a secured claim's need is
        capped at the `realized_proceeds_cents` of its securing asset, and any
        unsecured deficiency spills into `GENERAL_UNSECURED` as a deficiency
        share on the same claim, so the claim participates in both classes
        with split amounts — and each class's grant is the lesser of its need
        and the remaining pool, with the pool reduced by each grant in turn."

        SECURED 500,000 capped at realized 300,000; deficiency 200,000 spills
        into GENERAL_UNSECURED beside a 300,000 general claim; cash 400,000
        (300,000 net sale + 100,000 judgment recovery).

        Design: Corner/calculations/waterfall_secured_cap_and_deficiency_spill
        """
        ctx = setup_case_in_claims_administration(case_number="26-20016",
                                                  objection_window_days=1,
                                                  scheduled_value_cents=350000)
        case_id = ctx["case"]["id"]
        cred_id = ctx["creditor"]["id"]
        asset_id = ctx["asset"]["id"]
        cl_sec = file_claim(case_id, cred_id, filed_amount_cents=500000,
                            priority_class="SECURED", secured_by_asset_id=asset_id)
        cl_gu = file_claim(case_id, cred_id, received_at="2026-02-01T01:00:00Z",
                           filed_amount_cents=300000)
        review_and_allow_claim(cl_sec["id"])
        review_and_allow_claim(cl_gu["id"])
        # Recovery contributes the second 100,000 of estate cash.
        create_judgment_action(case_id, cred_id, transfer_amount_cents=100000,
                               demand_amount_cents=100000)
        set_clock("2026-06-02T00:00:00Z")
        get_success_data(api_client.begin_liquidation(case_id, TRUSTEE))
        _drive_sale_and_distribution(ctx, hammer=400000, costs=100000)

        plan = propose_plan(case_id)
        confirm_plan(plan["id"], case_id)

        allocations = api_client.list_plan_allocations(plan["id"], TRUSTEE).json()["data"]
        by_class = {a["priority_class"]: a["allocated_cents"] for a in allocations}
        assert by_class["SECURED"] == 300000, "secured grant capped at realized proceeds"
        assert by_class["GENERAL_UNSECURED"] == 100000

        sec_amounts = sorted(d["amount_cents"]
                             for d in dividend_for_claim(plan["id"], cl_sec["id"]))
        assert sec_amounts == [40000, 300000], \
            "the secured claim participates in both classes with split amounts"
        gu_amounts = [d["amount_cents"]
                      for d in dividend_for_claim(plan["id"], cl_gu["id"])]
        assert gu_amounts == [60000], "remainder-to-last inside the class"
        assert sum(sec_amounts) + sum(gu_amounts) == 400000


class TestSettlePartialCascade:
    def _objected_case_in_liquidation(self):
        """LIQUIDATION: claim X OBJECTED (proposed 0), claim Y ALLOWED at
        100,000, and a consummated sale netting 150,000."""
        ctx = setup_case_in_claims_administration(case_number="26-10007",
                                                  objection_window_days=1,
                                                  scheduled_value_cents=200000)
        case_id = ctx["case"]["id"]
        cred_id = ctx["creditor"]["id"]
        claim_x = file_claim(case_id, cred_id, filed_amount_cents=500000)
        claim_y = file_claim(case_id, cred_id,
                             received_at="2026-02-01T01:00:00Z",
                             filed_amount_cents=100000)
        review_claim(claim_x["id"])
        obj = object_to_claim(claim_x["id"], proposed_allowed_amount_cents=0)
        review_and_allow_claim(claim_y["id"])
        set_clock("2026-06-02T00:00:00Z")
        get_success_data(api_client.begin_liquidation(case_id, TRUSTEE))
        get_success_data(api_client.mark_asset_for_sale(ctx["asset"]["id"], TRUSTEE))
        sale = get_success_data(api_client.create_sale(
            case_id, create_sale_payload(asset_id=ctx["asset"]["id"],
                                         hammer_price_cents=150000,
                                         sale_costs_cents=0), TRUSTEE))
        get_success_data(api_client.approve_sale(sale["id"], COURT))
        set_clock("2026-06-04T00:00:00Z")
        get_success_data(api_client.consummate_sale(sale["id"], TRUSTEE))
        return ctx, claim_x, claim_y, obj

    def test_settle_partial_reallows_and_updates_register_total(self, api):
        """PRD §3.3: "a `PARTIAL` outcome resolves it as `ALLOWED` at the
        supplied `settled_amount_cents` and `settled_priority_class`."
        PRD §3.3: "Where the settlement changes the claim's class,
        `allowed_claims_total_cents` reflects the new amount only, never a
        stale residue under the old class."

        Design: Difficulty/transitive_cascade/objection_settle_partial_cascade
        """
        ctx, claim_x, claim_y, obj = self._objected_case_in_liquidation()
        validate_success(api.settle_objection(
            obj["id"],
            {"outcome": "PARTIAL", "settled_amount_cents": 50000,
             "settled_priority_class": "GENERAL_UNSECURED"},
            TRUSTEE))
        claim_x_after = validate_success(api.get_claim(claim_x["id"], TRUSTEE))
        assert claim_x_after["status"] == "ALLOWED"
        assert claim_x_after["allowed_amount_cents"] == 50000
        assert get_case(ctx["case"]["id"])["allowed_claims_total_cents"] == 150000

    def test_settle_partial_cascades_into_plan_pool_and_dividends(self, api):
        """PRD §3.6: "The `distributable_cents` is the case's
        `estate_cash_on_hand_cents` minus the total reserve across classes
        minus the approved amounts of any fee applications approved but not yet
        paid; a pool that is not strictly positive is rejected with
        `ERR_NO_FUNDS_TO_DISTRIBUTE`."
        PRD §3.6: "if a class's grant equals its need, every claim in the class
        receives its full `allowed_amount_cents`"

        Design: Difficulty/transitive_cascade/objection_settle_partial_cascade
        """
        ctx, claim_x, claim_y, obj = self._objected_case_in_liquidation()
        case_id = ctx["case"]["id"]
        validate_success(api.settle_objection(
            obj["id"],
            {"outcome": "PARTIAL", "settled_amount_cents": 50000,
             "settled_priority_class": "GENERAL_UNSECURED"},
            TRUSTEE))
        get_success_data(api.begin_distribution(case_id, TRUSTEE))
        plan = propose_plan(case_id)
        assert plan["distributable_cents"] == 150000
        confirm_plan(plan["id"], case_id)
        dx = dividend_for_claim(plan["id"], claim_x["id"])
        dy = dividend_for_claim(plan["id"], claim_y["id"])
        assert [d["amount_cents"] for d in dx] == [50000]
        assert [d["amount_cents"] for d in dy] == [100000]


class TestConsummationCascade:
    def _approved_sale_ctx(self):
        """LIQUIDATION with an APPROVED sale (net 400,000) whose objection
        window has elapsed; all claims allowed."""
        ctx = setup_case_in_liquidation(case_number="26-10008",
                                        objection_window_days=1,
                                        scheduled_value_cents=700000)
        case_id = ctx["case"]["id"]
        asset_id = ctx["asset"]["id"]
        get_success_data(api_client.mark_asset_for_sale(asset_id, TRUSTEE))
        sale = get_success_data(api_client.create_sale(
            case_id, create_sale_payload(asset_id=asset_id,
                                         hammer_price_cents=400000,
                                         sale_costs_cents=0), TRUSTEE))
        get_success_data(api_client.approve_sale(sale["id"], COURT))
        set_clock("2026-06-04T00:00:00Z")
        return ctx, sale

    def test_consummate_sells_asset_and_stamps_realized_proceeds(self, api):
        """PRD §3.4: "Consummating an `APPROVED` sale flips its
        `proceeds_status` to `POSTED` and its status to `CONSUMMATED`, credits
        `net_proceeds_cents` into `estate_cash_on_hand_cents`, and moves the
        asset to `SOLD` with its `realized_proceeds_cents` set to the sale's
        net proceeds."

        Design: Difficulty/transitive_cascade/sale_consummation_cascade_into_case_posture
        """
        ctx, sale = self._approved_sale_ctx()
        consummated = validate_success(api.consummate_sale(sale["id"], TRUSTEE))
        assert consummated["status"] == "CONSUMMATED"
        assert consummated["proceeds_status"] == "POSTED"
        asset = validate_success(api.get_asset(ctx["asset"]["id"], TRUSTEE))
        assert asset["status"] == "SOLD"
        assert asset["realized_proceeds_cents"] == 400000
        assert get_case(ctx["case"]["id"])["estate_cash_on_hand_cents"] == 400000

    def test_consummation_unblocks_distribution_posture(self, api):
        """PRD §3.4: "Beginning distribution moves the case from `LIQUIDATION`
        to `DISTRIBUTION` and requires no asset still in `MARKED_FOR_SALE` or
        `IN_AUCTION` (else `ERR_ASSETS_PENDING_SALE`), no claim still
        `OBJECTED` (else `ERR_OBJECTIONS_PENDING`), and a strictly positive
        `estate_cash_on_hand_cents` (else `ERR_NO_FUNDS_TO_DISTRIBUTE`)."

        Design: Difficulty/transitive_cascade/sale_consummation_cascade_into_case_posture
        """
        ctx, sale = self._approved_sale_ctx()
        validate_success(api.consummate_sale(sale["id"], TRUSTEE))
        case = validate_success(api.begin_distribution(ctx["case"]["id"], TRUSTEE))
        assert case["status"] == "DISTRIBUTION"


class TestDividendVoid:
    def test_dividend_void_leaves_unclaimed_funds(self, api):
        """PRD §3.6: "Voiding a `COMPUTED` dividend — for a check never claimed
        — flips it to `VOIDED` and leaves its amount in the estate as unclaimed
        funds."
        PRD §3.6: "the first posting moves the plan automatically from
        `CONFIRMED` to `EXECUTING`, and when every dividend of the plan is
        `POSTED` or `VOIDED` and the paid total equals the allocated amount
        less the voided remainder, the plan becomes `FULLY_DISTRIBUTED`."
        PRD §3.6: "When the case's last active plan reaches `FULLY_DISTRIBUTED`
        — meaning no other plan of the case remains in `PROPOSED`, `CONFIRMED`,
        or `EXECUTING` — the case moves automatically from `DISTRIBUTION` into
        the `FINAL_REPORT` posture, and any estate cash still on hand is
        definitionally unclaimed funds."

        Design: Corner/endpoints/dividend_void_leaves_unclaimed_funds
        """
        ctx = setup_case_in_claims_administration(case_number="26-20031",
                                                  objection_window_days=1,
                                                  scheduled_value_cents=150000)
        case_id = ctx["case"]["id"]
        cred_id = ctx["creditor"]["id"]
        cl1 = file_claim(case_id, cred_id, filed_amount_cents=60000)
        cl2 = file_claim(case_id, cred_id,
                         received_at="2026-02-01T01:00:00Z",
                         filed_amount_cents=40000)
        review_and_allow_claim(cl1["id"])
        review_and_allow_claim(cl2["id"])
        set_clock("2026-06-02T00:00:00Z")
        get_success_data(api_client.begin_liquidation(case_id, TRUSTEE))
        _drive_sale_and_distribution(ctx, hammer=100000)
        plan = propose_plan(case_id)
        confirm_plan(plan["id"], case_id)

        d1 = dividend_for_claim(plan["id"], cl1["id"])[0]
        d2 = dividend_for_claim(plan["id"], cl2["id"])[0]
        validate_success(api.void_dividend(d2["id"], TRUSTEE))
        validate_success(api.post_dividend(d1["id"], TRUSTEE))

        plan_after = validate_success(api.get_plan(plan["id"], TRUSTEE))
        assert plan_after["status"] == "FULLY_DISTRIBUTED"
        case_after = get_case(case_id)
        assert case_after["estate_cash_on_hand_cents"] == 40000, \
            "the voided dividend's amount remains as unclaimed funds"
        assert case_after["status"] == "FINAL_REPORT"


class TestPlanConfirmOcc:
    def test_occ_stale_case_version_on_plan_confirm(self, api):
        """PRD §2.9: "If the case's current `version` has advanced beyond that
        value — because a sale was consummated, a claim was allowed, a dividend
        was posted, or any other mutation bumped it — the request is rejected
        with `ERR_STALE_CASE_VERSION` (HTTP 412)."
        PRD §3.6: "Confirming a plan requires the case to be in `DISTRIBUTION`
        (else `ERR_CASE_NOT_IN_DISTRIBUTION`), requires that no other plan of
        the case be `CONFIRMED` or `EXECUTING` (else `ERR_PLAN_ALREADY_ACTIVE`),
        and carries the optimistic-concurrency guard of §2.9 — the request must
        present an `expected_case_version` matching the case's current
        `version`, and a mismatch is rejected with `ERR_STALE_CASE_VERSION`
        (HTTP 412)."

        Design: Corner/endpoints/occ_stale_case_version_on_plan_confirm
        """
        ctx = setup_case_in_distribution(case_number="26-20030")
        case_id = ctx["case"]["id"]
        plan = propose_plan(case_id)
        observed = get_case_version(case_id)

        # An intervening fee filing advances the case version.
        file_fee_application(case_id, applicant_role="COUNSEL",
                             requested_amount_cents=10000)

        resp = api.confirm_plan(plan["id"], observed, COURT)
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)

        fresh = get_case_version(case_id)
        confirmed = validate_success(api.confirm_plan(plan["id"], fresh, COURT))
        assert confirmed["status"] == "CONFIRMED"
