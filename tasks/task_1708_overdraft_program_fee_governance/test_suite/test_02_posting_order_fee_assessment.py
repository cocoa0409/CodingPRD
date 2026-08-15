"""Posting order and per-item fee assessment (PRD §2.7, §3.4): policy variant
divergence, cap/de-minimis interplay, working-vs-ledger balance separation,
and boundary precision."""
from test_helpers import (
    TUE,
    authorize,
    fund_account,
    get_account,
    get_transaction,
    list_fees,
    make_account,
    make_opted_in_account,
    make_program,
    open_batch,
    seal_batch,
    set_clock,
    settle_batch,
)

# Item clock instants shared by the ordering scenarios (PRD §2.4: the logical
# clock stamps authorized_date and created_at).
T0900 = "2026-08-04T09:00:00Z"
T0901 = "2026-08-04T09:01:00Z"
T0902 = "2026-08-04T09:02:00Z"
T0903 = "2026-08-04T09:03:00Z"
T0904 = "2026-08-04T09:04:00Z"
T0905 = "2026-08-04T09:05:00Z"


def _dual_policy_programs():
    """HIGH_TO_LOW and CHRONOLOGICAL programs, each with an opted-in account
    funded to 10000 and the same four one-time debits authorized on 2026-08-04,
    with the 2026-08-04 batch left OPEN in both programs."""
    prog_h = make_program(name="OD-H", posting_order_policy="HIGH_TO_LOW")
    prog_c = make_program(name="OD-C", posting_order_policy="CHRONOLOGICAL")
    acct_h, _ = make_opted_in_account(prog_h["id"], holder_name="Holder H")
    acct_c, _ = make_opted_in_account(prog_c["id"], holder_name="Holder C")
    fund_account(prog_h["id"], acct_h["id"], 10000, settle=False)
    fund_account(prog_c["id"], acct_c["id"], 10000, settle=False)
    batch_h = open_batch(prog_h["id"], TUE)
    batch_c = open_batch(prog_c["id"], TUE)
    for clock, amount in ((T0900, 1500), (T0901, 2000), (T0902, 3000),
                          (T0903, 6000)):
        set_clock(clock)
        authorize(acct_h["id"], "DEBIT_ONE_TIME", amount)
        authorize(acct_c["id"], "DEBIT_ONE_TIME", amount)
    return prog_h, prog_c, acct_h, acct_c, batch_h, batch_c


class TestPostingOrderVariantDivergence:
    def test_high_to_low_assesses_two_fees(self, api):
        """PRD §3.4: "then debits post according to the program's
        `posting_order_policy` — under `HIGH_TO_LOW`, largest `amount_cents`
        first with ties broken by earlier `authorized_date` and then earlier
        `created_at`".
        PRD §3.4: "The posting-order choice is not cosmetic: an identical input
        set can yield more fees under `HIGH_TO_LOW`, because large debits push
        the balance negative earlier".

        Design: Difficulty/dual_variant_calc/posting_order_high_to_low_vs_chronological_fee_count
        """
        _, _, acct_h, _, batch_h, _ = _dual_policy_programs()
        seal = seal_batch(batch_h["id"])
        # 6000->4000, 3000->1000, 2000->-1000 (fee), 1500->-2500 (fee)
        assert seal["fees_assessed_count"] == 2
        assert seal["fees_assessed_cents"] == 7000
        assert get_account(acct_h["id"])["ledger_balance_cents"] == -2500

    def test_chronological_assesses_one_fee_with_identical_ledger(self, api):
        """PRD §3.4: "whereas `CHRONOLOGICAL` lets a starting balance absorb
        small items first and can yield fewer fees."
        PRD §2.7: "The **ledger balance** is what is written back to the
        account when the seal completes: it equals the final working balance,
        because fees assessed during the seal are not debited until the batch
        later settles."

        Design: Difficulty/dual_variant_calc/posting_order_high_to_low_vs_chronological_fee_count
        """
        _, _, _, acct_c, _, batch_c = _dual_policy_programs()
        seal = seal_batch(batch_c["id"])
        # 1500->8500, 2000->6500, 3000->3500, 6000->-2500 (one fee)
        assert seal["fees_assessed_count"] == 1
        assert seal["fees_assessed_cents"] == 3500
        # Items-only ledger is identical across the two posting policies.
        assert get_account(acct_c["id"])["ledger_balance_cents"] == -2500


def _cap_de_minimis_scenario():
    """Account funded to 500 (funding batch settled, so the 2026-08-04 batch
    may itself settle per PRD §3.5's earlier-batch ordering rule); six one-time
    debits (600, 3000, 2000, 1500, 900, 500) authorized 09:00..09:05 on
    2026-08-04; batch left OPEN."""
    program = make_program(name="OD-A", max_daily_fees_count=5)
    account, _ = make_opted_in_account(program["id"], holder_name="Holder A")
    fund_account(program["id"], account["id"], 500, settle=True)
    batch = open_batch(program["id"], TUE)
    txns = {}
    for label, clock, amount in (("d1", T0900, 600), ("d2", T0901, 3000),
                                 ("d3", T0902, 2000), ("d4", T0903, 1500),
                                 ("d5", T0904, 900), ("d6", T0905, 500)):
        set_clock(clock)
        txns[label] = authorize(account["id"], "DEBIT_ONE_TIME", amount)
    return program, account, batch, txns


class TestFeeAssessmentCapDeMinimisInterplay:
    def test_exact_fit_cap_admission_and_cap_blocked_items_carry_no_fee(self, api):
        """PRD §3.4: "the fee cents assessed so far plus `fee_amount_cents`
        does not exceed `daily_fee_cap_cents` — an exact fit that lands
        precisely on the cap is permitted."
        PRD §3.4: "the magnitude of the now-negative working balance is
        strictly greater than `de_minimis_threshold_cents` — a balance exactly
        at the threshold yields no fee".
        PRD §3.4: "The fee ledger can be queried with optional `account_id`,
        `batch_id`, `transaction_id` (a filter returning an array of zero or
        one element), `status`, and `fee_type` filters."

        Design: Difficulty/combinatorial_formula/fee_assessment_cap_de_minimis_interplay
        """
        _, account, batch, txns = _cap_de_minimis_scenario()
        seal = seal_batch(batch["id"])
        # 600->-100 de minimis skip; 3000->-3100 fee; 2000->-5100 fee;
        # 1500->-6600 fee (exact fit 10500<=10500); 900/500 blocked by cap.
        assert seal["fees_assessed_count"] == 3
        assert seal["fees_assessed_cents"] == 10500
        assert list_fees(transaction_id=txns["d1"]["id"]) == [], (
            "de minimis item must carry no fee")
        assert list_fees(transaction_id=txns["d5"]["id"]) == [], (
            "cap-blocked item must carry no fee")
        assert list_fees(transaction_id=txns["d6"]["id"]) == [], (
            "cap-blocked item must carry no fee")

    def test_settle_debits_fees_and_counts_the_negative_day(self, api):
        """PRD §2.7: "it equals the final working balance, because fees
        assessed during the seal are not debited until the batch later
        settles."
        PRD §3.5: "An account whose post-fee ledger is negative has its
        `consecutive_negative_business_days` incremented".

        Design: Difficulty/combinatorial_formula/fee_assessment_cap_de_minimis_interplay
        """
        _, account, batch, _ = _cap_de_minimis_scenario()
        seal_batch(batch["id"])
        at_seal = get_account(account["id"])
        # Items only: 500-600-3000-2000-1500-900-500 = -8000.
        assert at_seal["ledger_balance_cents"] == -8000
        settle_batch(batch["id"])
        settled = get_account(account["id"])
        assert settled["ledger_balance_cents"] == -18500  # -8000 - 10500 fees
        assert settled["consecutive_negative_business_days"] == 1
        assert settled["status"] == "ACTIVE"


class TestSameBatchFeesNeverEnterWorkingBalance:
    def _setup(self):
        program = make_program(name="OD-C2", daily_fee_cap_cents=100000,
                               max_daily_fees_count=10)
        account, _ = make_opted_in_account(program["id"],
                                           holder_name="Holder C2")
        batch = open_batch(program["id"], "2026-08-03")
        set_clock("2026-08-03T09:00:00Z")
        authorize(account["id"], "DEBIT_ONE_TIME", 600)
        set_clock("2026-08-03T09:01:00Z")
        authorize(account["id"], "DEBIT_ONE_TIME", 100)
        return program, account, batch

    def test_seal_leaves_fees_out_of_the_ledger(self, api):
        """PRD §2.7: "any fee created by those checks does not modify the
        working balance, so it cannot influence the pay/return decision, the
        de minimis test, or the cap test of any later item in the same batch.
        The practical consequence is that same-batch fees never cascade into
        extra returns or extra fees."

        Design: Difficulty/combinatorial_formula/same_batch_fees_never_enter_working_balance
        """
        _, account, batch = self._setup()
        seal = seal_batch(batch["id"])
        assert seal["fees_assessed_count"] == 2
        assert seal["fees_assessed_cents"] == 7000
        # -700, not -7700: fees never entered the same-batch balance.
        assert get_account(account["id"])["ledger_balance_cents"] == -700

    def test_settle_debits_fees_and_stamps_posted_date(self, api):
        """PRD §3.5: "Settlement first moves every `ASSESSED` fee created by
        the seal to `POSTED`, stamping `posted_date` with the batch's business
        date and debiting each fee's amount from its account's
        `ledger_balance_cents`".

        Design: Difficulty/combinatorial_formula/same_batch_fees_never_enter_working_balance
        """
        _, account, batch = self._setup()
        seal_batch(batch["id"])
        settle_batch(batch["id"])
        settled = get_account(account["id"])
        assert settled["ledger_balance_cents"] == -7700  # fees debit at settle
        assert settled["consecutive_negative_business_days"] == 1
        fee = list_fees(account_id=account["id"])[0]
        assert fee["posted_date"] == "2026-08-03"


class TestDeMinimisExactThresholdBoundary:
    def _setup(self):
        program = make_program(name="OD-D", daily_fee_cap_cents=100000,
                               max_daily_fees_count=10)
        account, _ = make_opted_in_account(program["id"], holder_name="Holder D")
        fund_account(program["id"], account["id"], 10000, settle=False)
        batch = open_batch(program["id"], TUE)
        set_clock(T0900)
        big = authorize(account["id"], "DEBIT_ONE_TIME", 10500)   # -> exactly -500
        set_clock(T0901)
        tiny = authorize(account["id"], "DEBIT_ONE_TIME", 1)      # -> -501
        return account, batch, big, tiny

    def test_balance_exactly_at_threshold_yields_no_fee(self, api):
        """PRD §3.4: "the magnitude of the now-negative working balance is
        strictly greater than `de_minimis_threshold_cents` — a balance exactly
        at the threshold yields no fee".

        Design: Difficulty/boundary_precision_check/de_minimis_exact_threshold_boundary
        """
        account, batch, big, _ = self._setup()
        seal_batch(batch["id"])
        assert list_fees(transaction_id=big["id"]) == [], (
            "magnitude exactly == threshold must yield no fee")

    def test_one_cent_beyond_threshold_yields_a_fee(self, api):
        """PRD §3.4: "An `OVERDRAFT` fee is assessed only when all four hold:
        the program is `ACTIVE`; the magnitude of the now-negative working
        balance is strictly greater than `de_minimis_threshold_cents`".
        PRD §3.4: "When the test passes, the system creates an **OverdraftFee**
        of `fee_type` `OVERDRAFT` in `ASSESSED` status with `amount_cents`
        equal to the program's `fee_amount_cents`".

        Design: Difficulty/boundary_precision_check/de_minimis_exact_threshold_boundary
        """
        account, batch, _, tiny = self._setup()
        seal = seal_batch(batch["id"])
        assert seal["fees_assessed_count"] == 1
        assert seal["fees_assessed_cents"] == 3500
        tiny_fees = list_fees(transaction_id=tiny["id"])
        assert len(tiny_fees) == 1
        assert tiny_fees[0]["amount_cents"] == 3500
        assert get_account(account["id"])["ledger_balance_cents"] == -501


class TestSealAssignsPostingSequenceCreditsFirst:
    def test_credits_post_first_with_one_based_sequence(self, api):
        """PRD §3.4: "Items are ordered deterministically: all `CREDIT_DEPOSIT`
        items post first, ordered by `authorized_date` earliest first with ties
        broken by earlier `created_at`; then debits post according to the
        program's `posting_order_policy`".
        PRD §3.4: "Each swept item receives a per-account, one-based
        `posting_sequence`, along with its `batch_id` and a `posted_date` equal
        to the batch's business date."

        Design: Corner/state_machines/seal_assigns_posting_sequence_credits_first
        """
        program = make_program(name="OD-SM9")
        # No election needed: this scenario never overdraws, so the
        # pay-or-return decision is never exercised.
        account = make_account(program["id"], holder_name="H SM9")
        batch = open_batch(program["id"], "2026-08-03")
        set_clock("2026-08-03T09:00:00Z")
        debit1 = authorize(account["id"], "DEBIT_ONE_TIME", 2000)
        set_clock("2026-08-03T09:01:00Z")
        credit = authorize(account["id"], "CREDIT_DEPOSIT", 5000)
        set_clock("2026-08-03T09:02:00Z")
        debit2 = authorize(account["id"], "DEBIT_ONE_TIME", 1000)

        seal = seal_batch(batch["id"])
        assert seal["items_posted_count"] == 3

        credit_after = get_transaction(credit["id"])
        debit1_after = get_transaction(debit1["id"])
        debit2_after = get_transaction(debit2["id"])
        assert credit_after["posting_sequence"] == 1
        assert debit1_after["posting_sequence"] == 2
        assert debit2_after["posting_sequence"] == 3
        assert credit_after["batch_id"] == batch["id"]
        assert credit_after["posted_date"] == "2026-08-03"
        assert credit_after["status"] == "POSTED"
        assert debit1_after["status"] == "POSTED"
        # 0 + 5000 - 2000 - 1000; the early debit never overdraws.
        assert get_account(account["id"])["ledger_balance_cents"] == 2000


class TestCreditsPostBeforeDebits:
    def test_later_credit_still_posts_first(self, api):
        """PRD §3.4: "Items are ordered deterministically: all `CREDIT_DEPOSIT`
        items post first, ordered by `authorized_date` earliest first with ties
        broken by earlier `created_at`; then debits post according to the
        program's `posting_order_policy`".

        Design: Corner/calculations/credits_post_before_debits_despite_later_authorization
        """
        program = make_program(name="OD-CAL1")
        account = make_account(program["id"], holder_name="H CAL1")
        batch = open_batch(program["id"], "2026-08-03")
        set_clock("2026-08-03T09:00:00Z")
        debit = authorize(account["id"], "DEBIT_ONE_TIME", 2000)
        set_clock("2026-08-03T09:01:00Z")
        credit = authorize(account["id"], "CREDIT_DEPOSIT", 5000)

        seal = seal_batch(batch["id"])
        assert seal["fees_assessed_count"] == 0
        assert seal["items_returned_count"] == 0
        assert get_transaction(credit["id"])["posting_sequence"] == 1
        debit_after = get_transaction(debit["id"])
        assert debit_after["posting_sequence"] == 2
        assert debit_after["status"] == "POSTED"
        assert get_account(account["id"])["ledger_balance_cents"] == 3000


class TestHighToLowAmountTieBreak:
    def test_equal_amount_debits_break_tie_by_earlier_authorization(self, api):
        """PRD §3.4: "under `HIGH_TO_LOW`, largest `amount_cents` first with
        ties broken by earlier `authorized_date` and then earlier `created_at`".
        PRD §3.4: "Ties are never broken by identifier."

        Design: Corner/calculations/high_to_low_amount_tie_break_authorized_at
        """
        program = make_program(name="OD-CAL2",
                               posting_order_policy="HIGH_TO_LOW")
        account, _ = make_opted_in_account(program["id"], holder_name="H CAL2")
        batch = open_batch(program["id"], "2026-08-03")
        set_clock("2026-08-03T09:00:00Z")
        txn_a = authorize(account["id"], "DEBIT_ONE_TIME", 2000)
        set_clock("2026-08-03T09:01:00Z")
        txn_b = authorize(account["id"], "DEBIT_ONE_TIME", 2000)

        seal = seal_batch(batch["id"])
        assert get_transaction(txn_a["id"])["posting_sequence"] == 1
        assert get_transaction(txn_b["id"])["posting_sequence"] == 2
        # -2000 and -4000, both magnitudes > 500.
        assert seal["fees_assessed_count"] == 2


class TestSealEmptyBatchZeroCounters:
    def test_empty_seal_and_settle_leave_counters_and_accounts_untouched(self, api):
        """PRD §3.4: "A new batch is `OPEN` with all four counters —
        `items_posted_count`, `items_returned_count`, `fees_assessed_count`,
        `fees_assessed_cents` — at zero."
        PRD §3.5: "the sustained-overdraft day count runs for every `ACTIVE`
        or `RESTRICTED` account of the batch's program — including accounts
        with no activity in this batch".

        Design: Corner/endpoints/seal_empty_batch_zero_counters
        """
        program = make_program(name="OD-EP3")
        account = make_account(program["id"], holder_name="H EP3")
        batch = open_batch(program["id"], "2026-08-03")

        seal = seal_batch(batch["id"])
        assert seal["status"] == "SEALED"
        assert seal["items_posted_count"] == 0
        assert seal["items_returned_count"] == 0
        assert seal["fees_assessed_count"] == 0
        assert seal["fees_assessed_cents"] == 0

        settled = settle_batch(batch["id"])
        assert settled["status"] == "SETTLED"
        account_after = get_account(account["id"])
        assert account_after["ledger_balance_cents"] == 0
        assert account_after["consecutive_negative_business_days"] == 0
