"""Capital-credit retirements and payouts: FIFO/pro-rata payout math, budget
guard, stale-check rejection, cash vs unclaimed conservation (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_allocation_payload,
    create_retirement_payload,
    get_success_data,
    set_clock,
    setup_cooperative,
    setup_executed_retirement,
    setup_finalized_invoice,
    setup_member,
    setup_posted_allocation,
    setup_published_schedule,
    validate_error,
    validate_success,
)

REP = TEST_USERS["rep"]
DIRECTOR = TEST_USERS["board_director"]


def _member_with_balance(api, kwh, pool, name="A", district_id=1, fiscal_year=2025):
    """ACTIVE member with `pool` allocated via FLAT_PER_MEMBER after billing
    `kwh` in the fiscal year. Returns (coop, member)."""
    coop = setup_cooperative()
    setup_published_schedule(rate_class="RESIDENTIAL")
    member, location = setup_member(
        status="ACTIVE", member_overrides={"legal_name": name, "district_id": district_id})
    setup_finalized_invoice(
        location["id"], f"{fiscal_year}-12-01T00:00:00Z",
        f"{fiscal_year}-12-31T00:00:00Z", 0, kwh)
    setup_posted_allocation(coop, fiscal_year=fiscal_year, method="FLAT_PER_MEMBER",
                            margin_cents=pool)
    return coop, member


class TestFifoRetirement:
    def test_fifo_retirement_oldest_first_partial_last(self, api):
        """PRD §3.8: "Under `FIFO_OLDEST`, members are walked in order of their
        oldest unretired allocation vintage — the earliest allocation
        `fiscal_year` with remaining balance, ties broken by ascending member
        `created_at` — and each is paid up to their full balance until the
        target total is exhausted; the final member in the walk may be partially
        paid, and any remainder below one cent is dropped."

        Design: Corner/calculations/fifo_retirement_oldest_first_partial_last
        """
        coop = setup_cooperative()
        setup_published_schedule(rate_class="RESIDENTIAL")
        m_a, loc_a = setup_member(
            status="ACTIVE", member_overrides={"legal_name": "A", "district_id": 1})
        m_b, loc_b = setup_member(
            status="ACTIVE", member_overrides={"legal_name": "B", "district_id": 2})

        # FY2024: only A has billed usage, so A absorbs the full 10000 pool.
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2024, "margin_cents": 10000}, REP), 200)
        setup_finalized_invoice(
            loc_a["id"], "2024-11-01T00:00:00Z", "2024-12-01T00:00:00Z", 0, 100)
        alloc24 = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2024,
                method="PATRONAGE_WEIGHTED"),
            REP), 201)
        alloc24 = get_success_data(api.approve_allocation(alloc24["id"], DIRECTOR), 200)
        coop_now = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        alloc24 = get_success_data(api.post_allocation(
            alloc24["id"], {"expected_cooperative_version": coop_now["version"]}, REP), 200)

        # FY2025: only B has billed usage, so B absorbs the full 30000 pool.
        get_success_data(api.post_margin(
            coop["id"], {"fiscal_year": 2025, "margin_cents": 30000}, REP), 200)
        setup_finalized_invoice(
            loc_b["id"], "2025-06-01T00:00:00Z", "2025-07-01T00:00:00Z", 0, 300)
        alloc25 = get_success_data(api.create_allocation(
            create_allocation_payload(
                cooperative_id=coop["id"], fiscal_year=2025,
                method="PATRONAGE_WEIGHTED"),
            REP), 201)
        alloc25 = get_success_data(api.approve_allocation(alloc25["id"], DIRECTOR), 200)
        coop_now = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        alloc25 = get_success_data(api.post_allocation(
            alloc25["id"], {"expected_cooperative_version": coop_now["version"]}, REP), 200)

        # FIFO retirement of 15000: A (oldest vintage 2024) is paid in full
        # (10000), then B takes the remaining 5000 of the budget, partial.
        ret = get_success_data(api.create_retirement(
            create_retirement_payload(
                cooperative_id=coop["id"], method="FIFO_OLDEST",
                total_retire_cents=15000),
            REP), 201)
        ret = get_success_data(api.board_approve_retirement(ret["id"], DIRECTOR), 200)
        coop_now = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        ret = get_success_data(api.execute_retirement(
            ret["id"], {"expected_cooperative_version": coop_now["version"]}, REP), 200)
        assert ret["status"] == "EXECUTING"
        # Payouts are issued, not yet cashed: balances remain on the books until
        # cash or mark-unclaimed decrements them; the run's payout lines carry
        # the FIFO split.
        payouts = get_success_data(api.list_retirement_payouts(ret["id"], REP), 200)
        by_member = {p["member_id"]: p["payout_cents"] for p in payouts}
        assert by_member[m_a["id"]] == 10000
        assert by_member[m_b["id"]] == 5000


class TestRetirementGuards:
    def test_retirement_method_not_allowed_rejected(self, api):
        """PRD §3.8: "The proposed `method` must appear in the cooperative's
        `retirement_methods_allowed`, else `ERR_RETIREMENT_METHOD_NOT_ALLOWED`."

        Design: Corner/validations/retirement_method_not_allowed_rejected
        """
        coop = setup_cooperative(retirement_methods_allowed=["FIFO_OLDEST"])
        ret = get_success_data(api.create_retirement(
            create_retirement_payload(
                cooperative_id=coop["id"], method="PRO_RATA_PERCENTAGE",
                total_retire_cents=1000, pro_rata_pct=0.5),
            REP), 201)
        resp = api.board_approve_retirement(ret["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_RETIREMENT_METHOD_NOT_ALLOWED)

    def test_retirement_budget_exceeds_total_balances_rejected(self, api):
        """PRD §3.8: "Execution also requires that `total_retire_cents` not
        exceed the sum of `capital_credit_balance_cents` across all members,
        else `ERR_RETIREMENT_BUDGET_EXCEEDED`."

        Design: Corner/errors/retirement_budget_exceeds_total_balances_rejected
        """
        coop, member = _member_with_balance(api, kwh=100, pool=10000)
        ret = get_success_data(api.create_retirement(
            create_retirement_payload(
                cooperative_id=coop["id"], method="FIFO_OLDEST",
                total_retire_cents=99999),
            REP), 201)
        ret = get_success_data(api.board_approve_retirement(ret["id"], DIRECTOR), 200)
        coop_now = get_success_data(api.get_cooperative(coop["id"], REP), 200)
        resp = api.execute_retirement(
            ret["id"], {"expected_cooperative_version": coop_now["version"]}, REP)
        validate_error(resp, ApiErrorId.ERR_RETIREMENT_BUDGET_EXCEEDED)


class TestPayouts:
    def test_mark_unclaimed_conserves_member_credit(self, api):
        """PRD §3.8: "A member who cannot be reached has the payout marked
        unclaimed (`ISSUED → UNCLAIMED`), which moves the money rather than
        erasing it: `unclaimed_credit_cents` is incremented and
        `capital_credit_balance_cents` decremented by the same `payout_cents`."

        Design: Difficulty/compensating_invariant/payout_cash_and_unclaimed_conserve_member_credit
        """
        coop, member = _member_with_balance(api, kwh=100, pool=10000)
        ret, payouts = setup_executed_retirement(
            coop, method="PRO_RATA_PERCENTAGE", total_retire_cents=5000,
            pro_rata_pct=0.5)
        assert len(payouts) == 1
        payout = payouts[0]
        assert payout["payout_cents"] == 5000
        validate_success(api.mark_payout_unclaimed(payout["id"], REP), 200)
        after = get_success_data(api.get_member(member["id"], REP), 200)
        assert after["capital_credit_balance_cents"] == 5000
        assert after["unclaimed_credit_cents"] == 5000
        # Conservation: the two buckets together still equal the posted balance.
        assert after["capital_credit_balance_cents"] + after["unclaimed_credit_cents"] == 10000

    def test_cash_decrements_balance_without_unclaimed(self, api):
        """PRD §3.8: "A member who deposits the check has it marked cashed
        (`ISSUED → CASHED`) ... and the member's `capital_credit_balance_cents`
        is decremented by the payout amount."

        Design: Difficulty/compensating_invariant/payout_cash_and_unclaimed_conserve_member_credit
        """
        coop, member = _member_with_balance(api, kwh=100, pool=10000)
        ret, payouts = setup_executed_retirement(
            coop, method="PRO_RATA_PERCENTAGE", total_retire_cents=5000,
            pro_rata_pct=0.5)
        payout = payouts[0]
        cashed = validate_success(api.cash_payout(payout["id"], REP), 200)
        assert cashed["status"] == "CASHED"
        after = get_success_data(api.get_member(member["id"], REP), 200)
        assert after["capital_credit_balance_cents"] == 5000
        assert after["unclaimed_credit_cents"] == 0

    def test_payout_cash_after_deadline_rejected(self, api):
        """PRD §3.8: "A member who deposits the check has it marked cashed
        (`ISSUED → CASHED`) — allowed only while the logical clock reads
        strictly before the `claim_deadline`, with a stale check refused as
        `ERR_PAYOUT_STALE`" and §2.5: "Payouts still in `ISSUED` are explicitly
        not auto-transitioned by clock advancement".

        Design: Corner/validations/payout_cash_after_deadline_rejected
        """
        coop, member = _member_with_balance(api, kwh=100, pool=10000)
        set_clock("2026-08-01T00:00:00Z")
        ret, payouts = setup_executed_retirement(
            coop, method="PRO_RATA_PERCENTAGE", total_retire_cents=5000,
            pro_rata_pct=0.5)
        payout = payouts[0]
        assert payout["status"] == "ISSUED"
        # Advance the clock beyond claim_deadline (issued_at 2026-08 + 3 years).
        set_clock("2030-01-01T00:00:00Z")
        resp = api.cash_payout(payout["id"], REP)
        validate_error(resp, ApiErrorId.ERR_PAYOUT_STALE)
