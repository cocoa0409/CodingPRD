"""Transaction booking and credit allocation: split rounding order, the
exact-sum invariant and its compensating cancel, booking guards, the double
cancel, listing filters, and immediate read-after-write."""
from test_helpers import (
    ApiErrorId,
    CANONICAL_CURVE_TIERS,
    TEST_USERS,
    assert_credit_entry,
    assert_sales_transaction,
    book_transaction,
    cancel_transaction,
    create_rep,
    get_assignment,
    get_only_credit_entry,
    list_credit_entries,
    setup_accepted_assignment,
    setup_assignment,
    setup_posted_credit,
    setup_program_with_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]


def _three_rep_scenario(api, prefix):
    """Program + PUBLISHED plan + three manager-less ACCEPTED reps."""
    sc = setup_program_with_plan(program_name=f"Prog {prefix}",
                                 plan_name=f"Plan {prefix}",
                                 curve_tiers=CANONICAL_CURVE_TIERS)
    reps, assignments = [], []
    for i in (1, 2, 3):
        rep = create_rep(sc["program"]["id"], f"{prefix} Rep{i}",
                         f"{prefix}-R{i}")
        asg = setup_assignment(sc["program"], sc["plan"], rep, accept=True)
        reps.append(rep)
        assignments.append(asg)
    return sc, reps, assignments


class TestCreditEntryShape:
    def test_direct_credit_computed_fields_on_post(self, api):
        """PRD §3.4: "Booking explodes the transaction into credit entries —
        one `DIRECT` entry per split — each recording its `transaction_id`, the
        credited rep's `assignment_id` and `rep_id`, a `credit_type` of
        `DIRECT`, and a computed `credit_amount_cents`."
        PRD §3.4: "When the assignment is `ACTIVE`, its `acceptance_status` is
        `ACCEPTED`, and the plan is `PUBLISHED`, the entry lands directly in
        `POSTED` with `posted_period_index` set to the program's current
        period; otherwise it parks in `PENDING` and waits for the acceptance
        cascade of §3.3."

        Design: Corner/entities/credit_entry_computed_fields_on_post
        """
        sc = setup_posted_credit(program_name="Prog CE", plan_name="Plan CE",
                                 rep_name="Rep CE", employee_ref="CE-R1",
                                 amount_cents=200000, external_ref="CE-T1")
        credit = sc["credit"]
        assert_credit_entry(credit)
        assert credit["credit_amount_cents"] == 200000
        assert credit["credit_type"] == "DIRECT"
        assert credit["status"] == "POSTED"
        assert credit["posted_period_index"] == 1
        assert credit.get("parent_credit_id") is None
        assert credit["assignment_id"] == sc["assignment"]["id"]
        assert credit["transaction_id"] == sc["transaction"]["id"]


class TestBookingGuards:
    def test_split_total_below_10000_rejected(self, api):
        """PRD §3.4: "first the `split_bps` values — each a positive integer —
        must total exactly ten thousand basis points
        (`ERR_SPLIT_TOTAL_INVALID`); the `external_ref` uniqueness is enforced;
        then every rep named in the splits must hold an assignment with
        lifecycle `status` equal to `ACTIVE` in this program
        (`ERR_SPLIT_REP_INELIGIBLE`)."

        Design: Corner/validations/transaction_split_total_9999_rejected
        """
        sc = setup_accepted_assignment(program_name="Prog SP",
                                       plan_name="Plan SP", rep_name="Rep SP",
                                       employee_ref="SP-R1", accept=False)
        resp = api.create_transaction(
            {"program_id": sc["program"]["id"], "external_ref": "SP-T1",
             "amount_cents": 200000, "transaction_date": "2026-02-01",
             "splits": [{"rep_id": sc["rep"]["id"], "split_bps": 9999}]},
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_SPLIT_TOTAL_INVALID, 422)

    def test_split_rep_without_active_assignment_rejected(self, api):
        """PRD §3.4: "first the `split_bps` values — each a positive integer —
        must total exactly ten thousand basis points
        (`ERR_SPLIT_TOTAL_INVALID`); the `external_ref` uniqueness is enforced;
        then every rep named in the splits must hold an assignment with
        lifecycle `status` equal to `ACTIVE` in this program
        (`ERR_SPLIT_REP_INELIGIBLE`)."

        Design: Corner/validations/split_rep_without_assignment_rejected
        """
        sc = setup_program_with_plan(program_name="Prog SR",
                                     plan_name="Plan SR")
        rep = create_rep(sc["program"]["id"], "Rep SR", "SR-R1")  # no assignment
        resp = api.create_transaction(
            {"program_id": sc["program"]["id"], "external_ref": "SR-T1",
             "amount_cents": 200000, "transaction_date": "2026-02-01",
             "splits": [{"rep_id": rep["id"], "split_bps": 10000}]},
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_SPLIT_REP_INELIGIBLE, 409)

    def test_duplicate_external_ref_after_cancel_rejected(self, api):
        """PRD §3.4: "The `external_ref` is the client-supplied idempotency
        anchor: it must be unique within the program **regardless of
        transaction status** — even a long-cancelled transaction's reference
        cannot be reused — and a collision is rejected with
        `ERR_DUPLICATE_TRANSACTION_REF`."

        Design: Corner/validations/duplicate_transaction_ref_after_cancel_rejected
        """
        sc = setup_posted_credit(program_name="Prog DX", plan_name="Plan DX",
                                 rep_name="Rep DX", employee_ref="DX-R1",
                                 amount_cents=200000, external_ref="DX-1")
        cancel_transaction(sc["transaction"]["id"])

        resp = api.create_transaction(
            {"program_id": sc["program"]["id"], "external_ref": "DX-1",
             "amount_cents": 300000, "transaction_date": "2026-02-02",
             "splits": [{"rep_id": sc["rep"]["id"], "split_bps": 10000}]},
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRANSACTION_REF, 409)


class TestCancel:
    def test_double_cancel_rejected_and_reversal_once(self, api):
        """PRD §3.5: "Cancellation requires the transaction to still be
        `BOOKED`; a repeat attempt on an already-`CANCELLED` transaction is
        rejected with `ERR_TRANSACTION_ALREADY_CANCELLED`."
        PRD §3.5: "Reversing a `POSTED` entry whose `posted_period_index` is
        the current open period decrements its assignment's
        `current_period_earned_cents` by the entry's amount; posted entries
        from earlier periods cannot exist, because period close has already
        locked them."

        Design: Corner/state_machines/transaction_double_cancel_rejected
        """
        sc = setup_posted_credit(program_name="Prog DC", plan_name="Plan DC",
                                 rep_name="Rep DC", employee_ref="DC-R1",
                                 amount_cents=200000, external_ref="DC-T1")
        cancel_transaction(sc["transaction"]["id"])
        assert (get_assignment(sc["assignment"]["id"])
                ["current_period_earned_cents"] == 0)

        resp = api.cancel_transaction(sc["transaction"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_ALREADY_CANCELLED, 409)
        assert (get_assignment(sc["assignment"]["id"])
                ["current_period_earned_cents"] == 0), (
            "the reversal is applied exactly once"
        )


class TestListing:
    def test_transactions_list_status_filter(self, api):
        """PRD §3.4: "Transactions may be listed with `program_id` and `status`
        filters."
        PRD §3.4: "A booked transaction is born in `BOOKED` status, with
        `booked_period_index` snapshotting the program's open period at
        creation"

        Design: Corner/endpoints/transactions_list_status_filter
        """
        sc = setup_accepted_assignment(program_name="Prog LF",
                                       plan_name="Plan LF", rep_name="Rep LF",
                                       employee_ref="LF-R1")
        t1 = book_transaction(sc["program"]["id"], "LF-T1", 100000,
                              [{"rep_id": sc["rep"]["id"], "split_bps": 10000}])
        t2 = book_transaction(sc["program"]["id"], "LF-T2", 150000,
                              [{"rep_id": sc["rep"]["id"], "split_bps": 10000}],
                              transaction_date="2026-02-02")
        cancel_transaction(t1["id"])

        cancelled, _ = validate_paginated(api.list_transactions(
            ADMIN, params={"program_id": sc["program"]["id"],
                           "status": "CANCELLED"}))
        assert [t["id"] for t in cancelled] == [t1["id"]]

        booked, _ = validate_paginated(api.list_transactions(
            ADMIN, params={"program_id": sc["program"]["id"],
                           "status": "BOOKED"}))
        assert [t["id"] for t in booked] == [t2["id"]]
        assert_sales_transaction(booked[0])
        assert booked[0]["booked_period_index"] == 1


class TestSplitRounding:
    def test_split_rounding_per_split_half_up_first(self, api):
        """PRD §3.4: "Allocation follows a deterministic rounding contract: for
        each split in request array order, the raw share is `amount_cents`
        multiplied by the split's `split_bps` and divided by ten thousand, and
        the split's credit is that raw share rounded half up to a whole cent —
        per-split rounding first, before any summation."

        100001 cents split 3333/3333/3334: the two 3333-bps splits each round
        half up from 33330.3333 to 33330.

        Design: Difficulty/combinatorial_formula/split_rounding_remainder_allocation
        """
        sc, reps, _ = _three_rep_scenario(api, "S")
        txn = book_transaction(
            sc["program"]["id"], "S-T1", 100001,
            [{"rep_id": reps[0]["id"], "split_bps": 3333},
             {"rep_id": reps[1]["id"], "split_bps": 3333},
             {"rep_id": reps[2]["id"], "split_bps": 3334}])

        c1 = get_only_credit_entry(transaction_id=txn["id"],
                                   rep_id=reps[0]["id"])
        c2 = get_only_credit_entry(transaction_id=txn["id"],
                                   rep_id=reps[1]["id"])
        # round_half_up(100001 * 3333 / 10000) = round_half_up(33330.3333)
        assert c1["credit_amount_cents"] == 33330
        assert c2["credit_amount_cents"] == 33330

    def test_split_remainder_reconciled_to_largest_split(self, api):
        """PRD §3.4: "The remainder, the transaction amount minus the sum of
        the rounded credits, may be positive or negative; when it is nonzero,
        the entire remainder is added to (or, when negative, subtracted from)
        the split with the largest `split_bps`, with ties broken in favor of
        the lowest array index."
        PRD §3.4: "The invariant is exact: the `DIRECT` credits of a
        transaction always sum to `amount_cents` to the cent."

        100001 split 3333/3333/3334: per-split rounding gives
        33330+33330+33340 = 100000, so the +1 remainder lands on the largest
        split (3334): 33341.

        Design: Difficulty/combinatorial_formula/split_rounding_remainder_allocation
        """
        sc, reps, _ = _three_rep_scenario(api, "S2")
        txn = book_transaction(
            sc["program"]["id"], "S2-T1", 100001,
            [{"rep_id": reps[0]["id"], "split_bps": 3333},
             {"rep_id": reps[1]["id"], "split_bps": 3333},
             {"rep_id": reps[2]["id"], "split_bps": 3334}])

        amounts = [get_only_credit_entry(transaction_id=txn["id"],
                                         rep_id=r["id"])["credit_amount_cents"]
                   for r in reps]
        assert amounts == [33330, 33330, 33341]
        assert sum(amounts) == 100001 == txn["amount_cents"], (
            "DIRECT credits conserve the transaction amount exactly"
        )

    def test_split_tie_negative_remainder_to_lowest_index(self, api):
        """PRD §3.4: "The remainder, the transaction amount minus the sum of
        the rounded credits, may be positive or negative; when it is nonzero,
        the entire remainder is added to (or, when negative, subtracted from)
        the split with the largest `split_bps`, with ties broken in favor of
        the lowest array index."

        99999 split 5000/5000 rounds each half up to 50000 (sum 100000), so
        the -1 remainder is subtracted from the tied split at the lowest array
        index: 49999 / 50000.

        Design: Corner/calculations/split_negative_remainder_goes_to_lowest_index_on_tie
        """
        sc = setup_program_with_plan(program_name="Prog NR", plan_name="Plan NR")
        rep1 = create_rep(sc["program"]["id"], "NR Rep1", "NR-R1")
        rep2 = create_rep(sc["program"]["id"], "NR Rep2", "NR-R2")
        setup_assignment(sc["program"], sc["plan"], rep1, accept=True)
        setup_assignment(sc["program"], sc["plan"], rep2, accept=True)

        txn = book_transaction(
            sc["program"]["id"], "NR-T1", 99999,
            [{"rep_id": rep1["id"], "split_bps": 5000},
             {"rep_id": rep2["id"], "split_bps": 5000}])
        c1 = get_only_credit_entry(transaction_id=txn["id"], rep_id=rep1["id"])
        c2 = get_only_credit_entry(transaction_id=txn["id"], rep_id=rep2["id"])
        assert c1["credit_amount_cents"] == 49999
        assert c2["credit_amount_cents"] == 50000
        assert c1["credit_amount_cents"] + c2["credit_amount_cents"] == 99999


class TestCreditMassConservation:
    def test_direct_credits_sum_exactly_to_amount(self, api):
        """PRD §3.4: "The invariant is exact: the `DIRECT` credits of a
        transaction always sum to `amount_cents` to the cent."

        Design: Difficulty/compensating_invariant/credit_allocation_conservation
        """
        sc, reps, _ = _three_rep_scenario(api, "M")
        txn = book_transaction(
            sc["program"]["id"], "M-T1", 100001,
            [{"rep_id": reps[0]["id"], "split_bps": 3333},
             {"rep_id": reps[1]["id"], "split_bps": 3333},
             {"rep_id": reps[2]["id"], "split_bps": 3334}])
        credits = list_credit_entries(transaction_id=txn["id"])
        posted = [c for c in credits if c["status"] == "POSTED"]
        assert len(posted) == 3
        assert sum(c["credit_amount_cents"] for c in posted) == 100001, (
            "no cent is created or lost in allocation"
        )

    def test_cancel_preserves_credit_mass_as_reversed(self, api):
        """PRD §3.5: "Cancellation is a deep reversal: every credit entry of
        the transaction in `PENDING`, `POSTED`, or `LOCKED` moves to
        `REVERSED`, roll-up children included — reversing any entry likewise
        reverses its own `ROLLUP` children still in `PENDING` or `POSTED`
        under the same rules."

        Design: Difficulty/compensating_invariant/credit_allocation_conservation
        """
        sc, reps, _ = _three_rep_scenario(api, "M2")
        txn = book_transaction(
            sc["program"]["id"], "M2-T1", 100001,
            [{"rep_id": reps[0]["id"], "split_bps": 3333},
             {"rep_id": reps[1]["id"], "split_bps": 3333},
             {"rep_id": reps[2]["id"], "split_bps": 3334}])
        cancel_transaction(txn["id"])

        credits = list_credit_entries(transaction_id=txn["id"])
        assert len(credits) == 3
        assert all(c["status"] == "REVERSED" for c in credits)
        live_mass = sum(c["credit_amount_cents"] for c in credits
                        if c["status"] != "REVERSED")
        assert live_mass == 0, "the compensating cancel zeroes the live mass"
        historical = sum(c["credit_amount_cents"] for c in credits)
        assert historical == 100001, (
            "the REVERSED rows still record the original allocation"
        )


class TestImmediateConsistency:
    def test_read_after_write_immediate_consistency(self, api):
        """PRD §3.4: "Two live indicators on each assignment are recomputed on
        every credit change. `current_attainment_bps` converts the
        mode-filtered earned amount into basis points: the earned amount
        multiplied by ten thousand and divided by `quota_cents`, the quotient
        rounded down to a whole number with fractions discarded, and zero
        whenever the earned amount is zero or negative."
        PRD §3.4: "The assignment's `current_period_earned_cents` increases by
        the credit amount, raw, for both credit types."

        Design: Corner/consistency_model/immediate_read_after_write
        """
        sc = setup_accepted_assignment(program_name="Prog IC",
                                       plan_name="Plan IC", rep_name="Rep IC",
                                       employee_ref="IC-R1")
        resp = api.create_transaction(
            {"program_id": sc["program"]["id"], "external_ref": "IC-T1",
             "amount_cents": 200000, "transaction_date": "2026-02-01",
             "splits": [{"rep_id": sc["rep"]["id"], "split_bps": 10000}]},
            ANALYST)
        transaction = validate_success(resp, 201)
        assert transaction["status"] == "BOOKED"

        assignment = get_assignment(sc["assignment"]["id"])
        assert assignment["current_period_earned_cents"] == 200000
        assert assignment["current_attainment_bps"] == 2000
        # Flat 10% curve: provisional estimate is the gross-curve figure.
        assert assignment["provisional_period_payout_cents"] == 20000
