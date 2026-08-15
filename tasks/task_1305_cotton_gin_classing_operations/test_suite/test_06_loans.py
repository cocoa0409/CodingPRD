"""CCC loan pledges: principal pinning, the pledge/release/re-pledge cycle,
interest day counting, the season cap, and receipt-state gating."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    bales_by_tag,
    class_bale,
    create_grade_schedule,
    create_grower,
    create_module,
    create_shift,
    create_warehouse,
    get_bale,
    get_grower,
    get_pledge,
    get_receipt,
    get_warehouse,
    gin_module,
    issue_receipt,
    list_ledger_entries,
    list_pledges_for_receipt,
    pledge_receipt,
    redeem_pledge,
    set_clock,
    setup_classed_bale,
    setup_ginned_bale,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["gin_operator_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestPledgeReleaseRepledgeCycle:
    def _setup(self):
        ctx = setup_classed_bale(membership_number="MB-401", legal_name="Cycle Farm",
                                 bale_tag="B-01", stand_label="STAND-F")
        warehouse = create_warehouse("WH-C", capacity_bales=5, dock_count=1)
        receipt = issue_receipt(ctx["bale"]["id"], warehouse["id"],
                                wm_user_id="wm-1")
        ctx["warehouse"] = warehouse
        ctx["receipt"] = receipt
        return ctx

    def test_pledge_pins_principal_and_same_day_redeem_releases(self, api):
        """PRD: "the pledge pins that row's `loan_rate_points`. Principal is
        the bale's `net_weight_lbs` multiplied by those loan-rate points,
        divided by 100, rounded half-up to whole cents, and stored as
        `principal_cents`."
        PRD: "the pledge day counts, the redemption day does not, and a
        same-day redemption accrues zero days and zero interest."
        PRD: "Redemption stamps `redeemed_date`, moves the pledge to terminal
        `REPAID`, flips the receipt to `RELEASED`"

        Design: Difficulty/non_linear_state_machine/receipt_pledge_release_repledge_cycle
        """
        ctx = self._setup()
        p1 = pledge_receipt(ctx["receipt"]["id"])
        # 500 lbs * 5450 points / 100 = 27250
        assert p1["principal_cents"] == 27250
        assert p1["loan_rate_points"] == 5450
        assert p1["status"] == "ACTIVE"
        assert p1["interest_cents"] == 0
        assert get_receipt(ctx["receipt"]["id"])["status"] == "PLEDGED"

        redeemed = redeem_pledge(p1["id"])
        assert redeemed["status"] == "REPAID"
        assert redeemed["interest_cents"] == 0, "same-day redemption accrues zero"
        assert get_receipt(ctx["receipt"]["id"])["status"] == "RELEASED", (
            "redemption releases the receipt — a cycle point, not terminal")

    def test_repledge_from_release_and_ledger_net(self, api):
        """PRD: "the pledge/release cycle may repeat, so a redeemed receipt can
        be re-pledged under identical guards and an identical cascade."
        PRD: "Pledging creates the `LoanPledge` `ACTIVE`, stamps `pledged_date`
        from the logical clock, initializes `interest_cents` to 0, flips the
        receipt to `PLEDGED` (incrementing the receipt's `version`), posts a
        `LedgerEntry` of type `LOAN_ADVANCE` for positive principal with a
        `memo` naming the receipt, and recomputes the grower's
        `credit_balance_cents`."
        PRD: "posts a `LOAN_REPAYMENT` ledger entry for the negative of
        principal plus interest, and recomputes the grower's balance."

        Design: Difficulty/non_linear_state_machine/receipt_pledge_release_repledge_cycle
        """
        ctx = self._setup()
        p1 = pledge_receipt(ctx["receipt"]["id"])
        redeem_pledge(p1["id"])
        p2 = pledge_receipt(ctx["receipt"]["id"])
        assert p2["status"] == "ACTIVE"
        assert p2["principal_cents"] == 27250
        assert get_receipt(ctx["receipt"]["id"])["status"] == "PLEDGED"

        entries = list_ledger_entries(grower_id=ctx["grower"]["id"])
        advances = [e["amount_cents"] for e in entries
                    if e["entry_type"] == "LOAN_ADVANCE"]
        repayments = [e["amount_cents"] for e in entries
                      if e["entry_type"] == "LOAN_REPAYMENT"]
        assert advances == [27250, 27250]
        assert repayments == [-27250]
        # ginning charge -5750 (one 500-lb bale) plus the loan cycle +27250
        grower = get_grower(ctx["grower"]["id"])
        assert grower["credit_balance_cents"] == -5750 + 27250 - 27250 + 27250


class TestInterestDayCount:
    def test_ten_day_interest_and_same_day_zero(self, api):
        """PRD: "Interest accrues simply at 0.01 percent of principal per
        calendar day, counted half-open from `pledged_date` to the
        logical-clock redemption date — the pledge day counts, the redemption
        day does not, and a same-day redemption accrues zero days and zero
        interest."
        PRD: "`interest_cents` is principal multiplied by the daily rate
        multiplied by the day count, rounded half-up to whole cents."

        Design: Corner/calculations/loan_interest_day_count_and_same_day_zero
        """
        ctx = setup_classed_bale(membership_number="MB-C34",
                                 legal_name="Interest Farm", bale_tag="B-IN1",
                                 stand_label="STAND-IN")
        warehouse = create_warehouse("WH-IN", capacity_bales=5, dock_count=1)
        receipt = issue_receipt(ctx["bale"]["id"], warehouse["id"],
                                wm_user_id="wm-1")
        p1 = pledge_receipt(receipt["id"])

        set_clock("2026-08-11T00:00:00Z")  # 10 days after the 2026-08-01 pledge
        redeemed = redeem_pledge(p1["id"])
        # 27250 * 0.0001 * 10 = 27.25 -> 27 (half-up)
        assert redeemed["interest_cents"] == 27

        p2 = pledge_receipt(receipt["id"])
        redeemed2 = redeem_pledge(p2["id"])
        assert redeemed2["interest_cents"] == 0, "same-day redemption accrues zero"

        entries = list_ledger_entries(grower_id=ctx["grower"]["id"])
        repayments = sorted(e["amount_cents"] for e in entries
                            if e["entry_type"] == "LOAN_REPAYMENT")
        assert repayments == [-27277, -27250]
        # ginning -5750, advances +27250 +27250, repayments -27277 -27250
        grower = get_grower(ctx["grower"]["id"])
        assert grower["credit_balance_cents"] == -5750 - 27, (
            "the grower bears exactly the ginning charge plus the interest")


class TestPledgeTerminalLockdown:
    def test_redeem_and_forfeit_after_repay_rejected(self, api):
        """PRD: "Redemption repays the loan. The pledge must be `ACTIVE` (else
        `ERR_PLEDGE_NOT_ACTIVE`, HTTP 409)."
        PRD: "Forfeiture hands the collateral to the CCC. The pledge must
        likewise be `ACTIVE` (else `ERR_PLEDGE_NOT_ACTIVE`)."

        Design: Corner/state_machines/pledge_redeem_and_forfeit_after_repay_rejected
        """
        ctx = setup_classed_bale(membership_number="MB-C19", legal_name="Repay Farm",
                                 bale_tag="B-RP1", stand_label="STAND-RP")
        warehouse = create_warehouse("WH-RP", capacity_bales=5, dock_count=1)
        receipt = issue_receipt(ctx["bale"]["id"], warehouse["id"],
                                wm_user_id="wm-1")
        pledge = pledge_receipt(receipt["id"])
        redeem_pledge(pledge["id"])

        e1 = api.redeem_loan_pledge(pledge["id"], ACCOUNTANT)
        validate_error(e1, ApiErrorId.ERR_PLEDGE_NOT_ACTIVE)
        e2 = api.forfeit_loan_pledge(pledge["id"], ACCOUNTANT)
        validate_error(e2, ApiErrorId.ERR_PLEDGE_NOT_ACTIVE)

        settled = get_pledge(pledge["id"])
        assert settled["status"] == "REPAID"
        assert settled["interest_cents"] == 0
        assert get_receipt(receipt["id"])["status"] == "RELEASED"


class TestPledgeGuards:
    def test_pledge_unclassed_bale_rejected(self, api):
        """PRD: "The bale must be `CLASSED` (else `ERR_BALE_NOT_CLASSED`,
        HTTP 409), because principal prices off the active grade"

        Design: Corner/validations/pledge_unclassed_bale_rejected
        """
        create_grade_schedule(grade_code="31-3", premium_discount_points=265,
                              loan_rate_points=5450)
        ctx = setup_ginned_bale(membership_number="MB-C50",
                                legal_name="Unclassed Farm", bale_tag="B-UC1",
                                stand_label="STAND-UC")
        warehouse = create_warehouse("WH-UC", capacity_bales=5, dock_count=1)
        receipt = issue_receipt(ctx["bale"]["id"], warehouse["id"],
                                wm_user_id="wm-1")

        resp = api.create_loan_pledge({"warehouse_receipt_id": receipt["id"]},
                                      ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_BALE_NOT_CLASSED)
        assert get_receipt(receipt["id"])["status"] == "ACTIVE"
        assert list_pledges_for_receipt(receipt["id"]) == []

    def test_pledge_gated_by_cancelled_receipt_state(self, api):
        """PRD: "The receipt must be in `ACTIVE` or `RELEASED` status (else
        `ERR_RECEIPT_NOT_ACTIVE`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/pledge_gated_by_receipt_state
        """
        ctx = setup_classed_bale(membership_number="MB-800", legal_name="Gate Farm",
                                 bale_tag="B-G1", stand_label="STAND-L")
        warehouse = create_warehouse("WH-G", capacity_bales=5, dock_count=1)
        receipt = issue_receipt(ctx["bale"]["id"], warehouse["id"],
                                wm_user_id="wm-1")
        validate_success(api.cancel_warehouse_receipt(receipt["id"],
                                                      TEST_USERS["warehouse_manager_headers"]))

        resp = api.create_loan_pledge({"warehouse_receipt_id": receipt["id"]},
                                      ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_RECEIPT_NOT_ACTIVE)
        assert get_receipt(receipt["id"])["status"] == "CANCELLED"

    def test_cancelled_receipt_creates_no_pledge_rows(self, api):
        """PRD: "The receipt must be in `ACTIVE` or `RELEASED` status (else
        `ERR_RECEIPT_NOT_ACTIVE`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/pledge_gated_by_receipt_state
        """
        ctx = setup_classed_bale(membership_number="MB-800", legal_name="Gate Farm",
                                 bale_tag="B-G1", stand_label="STAND-L")
        warehouse = create_warehouse("WH-G", capacity_bales=5, dock_count=1)
        receipt = issue_receipt(ctx["bale"]["id"], warehouse["id"],
                                wm_user_id="wm-1")
        validate_success(api.cancel_warehouse_receipt(receipt["id"],
                                                      TEST_USERS["warehouse_manager_headers"]))
        api.create_loan_pledge({"warehouse_receipt_id": receipt["id"]}, ACCOUNTANT)
        assert list_pledges_for_receipt(receipt["id"]) == [], (
            "no LoanPledge rows may exist for the rejected pledge")


class TestSeasonLoanCap:
    def _setup(self):
        """Three classed 500-lb bales, three ACTIVE receipts; r1 and r2 already
        pledged so the season ACTIVE principal is exactly 50,000,000 cents."""
        create_grade_schedule(grade_code="52-1", premium_discount_points=0,
                              loan_rate_points=5000000)
        grower = create_grower("MB-600", "Cap Farm")
        warehouse = create_warehouse("WH-P", capacity_bales=10, dock_count=1)
        shift = create_shift("2026", "STAND-I")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-C")
        gin_module(module["id"], shift["id"],
                   [("B-C1", 500), ("B-C2", 500), ("B-C3", 500)])
        bales = bales_by_tag(module["id"])
        receipts = {}
        for tag in ("B-C1", "B-C2", "B-C3"):
            bale = bales[tag]
            class_bale(bale["id"], bale["version"], grade_code="52-1",
                       micronaire=4.0, strength_gpt=28.0, staple_32nds=36,
                       result_date="2026-03-10T00:00:00Z")
            receipts[tag] = issue_receipt(bale["id"], warehouse["id"],
                                          wm_user_id="wm-1")
        # principal per bale: 500 * 5000000 / 100 = 25,000,000 cents
        pledge_receipt(receipts["B-C1"]["id"])
        pledge_receipt(receipts["B-C2"]["id"])
        return grower, warehouse, receipts

    def test_state_precondition_beats_loan_cap(self, api):
        """PRD: "Only then do state-gate checks run (the transition gates and
        the OCC version match), then contamination and moisture safety plus
        segregation of duties, then uniqueness and quota rules, then temporal
        window rules, then cross-entity coherence, and finally money caps and
        exact-amount rules. A request failing an earlier tier never surfaces a
        later tier's error."
        PRD: "The receipt must be in `ACTIVE` or `RELEASED` status (else
        `ERR_RECEIPT_NOT_ACTIVE`, HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/pledge_state_precondition_beats_loan_cap
        """
        _grower, _warehouse, receipts = self._setup()
        # re-pledging r1 (PLEDGED) would also breach the season cap
        resp = api.create_loan_pledge(
            {"warehouse_receipt_id": receipts["B-C1"]["id"]}, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_RECEIPT_NOT_ACTIVE)
        assert get_receipt(receipts["B-C1"]["id"])["status"] == "PLEDGED"

    def test_cap_exceeded_on_active_receipt(self, api):
        """PRD: "A season-level cap guards the co-op's exposure: the sum of
        `principal_cents` across the grower's `ACTIVE` pledges in this season,
        plus the new principal, must not exceed 50,000,000 cents, or the pledge
        fails with `ERR_LOAN_CAP_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/pledge_state_precondition_beats_loan_cap
        """
        _grower, _warehouse, receipts = self._setup()
        # r3 is ACTIVE: 50,000,000 + 25,000,000 > cap
        resp = api.create_loan_pledge(
            {"warehouse_receipt_id": receipts["B-C3"]["id"]}, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_LOAN_CAP_EXCEEDED)
        assert get_receipt(receipts["B-C3"]["id"])["status"] == "ACTIVE"
