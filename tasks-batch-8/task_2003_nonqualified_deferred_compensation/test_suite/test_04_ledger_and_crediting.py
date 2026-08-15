"""Ledger dual balances, append-only entry shape, notional crediting, reversal.

PRD §2.4 (append-only ledger), §3.3 (accounts, ledger, crediting), §3.2 (caps).
"""
from test_helpers import (
    TEST_USERS,
    add_fund,
    add_window,
    advance_clock,
    assert_ledger_entry,
    create_active_plan,
    create_crediting_run_payload,
    create_election,
    enroll_participant,
    get_account,
    get_election,
    get_statement,
    list_ledger_entries,
    open_account,
    plan_version,
    post_deferral,
    setup_funded_account,
    setup_plan_fund_window,
    settle_account,
    submit_election,
    validate_error,
    validate_success,
)

BA = TEST_USERS["benefits_admin_headers"]


def _post_run(api, plan_id, period_start, period_end, index_rates=None):
    payload = create_crediting_run_payload(
        plan_id, plan_version(plan_id), period_start=period_start, period_end=period_end)
    if index_rates is not None:
        payload["index_rates"] = index_rates
    return api.create_crediting_run(payload, BA)


class TestDualBalanceVariants:
    def test_balance_settled_vs_provisional_divergence(self, api):
        """PRD §3.3: "The `settled_balance_cents` sums `amount_cents` over the
        account's `POSTED` entries only; it is the fiscally authoritative figure
        used for distribution checks, the vesting base, and the account-closed
        transition. The `provisional_balance_cents` sums both `POSTED` and
        `PENDING` entries; it feeds statement display and the deferral-cap
        machinery, so the two balances diverge whenever unconfirmed payroll
        entries exist."
        PRD §3.3: "An account statement view exposes this machinery directly:
        `settled_balance_cents`, `provisional_balance_cents`,
        `vested_balance_cents`, the current `vested_bp`, the
        `pending_entries_count` and `posted_entries_count`, and the lifetime
        `total_deferred_cents` and `total_distributed_cents`."

        One PENDING deferral credit of 100000 makes the two variants diverge by
        exactly 100000 on identical ledger data.

        Design: Difficulty/dual_variant_calc/balance_settled_vs_provisional_divergence
        """
        ctx = setup_funded_account(100000, settle=False,
                                   plan_overrides={"name": "Plan DV"})
        statement = get_statement(ctx["account"]["id"])
        assert statement["settled_balance_cents"] == 0
        assert statement["provisional_balance_cents"] == 100000
        assert statement["pending_entries_count"] == 1
        assert statement["posted_entries_count"] == 0
        assert statement["provisional_balance_cents"] - statement["settled_balance_cents"] == 100000

    def test_settle_entries_closes_balance_divergence(self, api):
        """PRD §3.3: "The payroll-confirmation act by a `BenefitsAdministrator`
        flips all of an account's `PENDING` entries to `POSTED` in one step,
        recomputes the settled and vested balances, and bumps the account's
        `version`"

        After settle-entries, both variants count the same entry and the
        divergence closes: settled == provisional == 100000.

        Design: Difficulty/dual_variant_calc/balance_settled_vs_provisional_divergence
        """
        ctx = setup_funded_account(100000, settle=False,
                                   plan_overrides={"name": "Plan DV2"})
        settled_account = settle_account(ctx["account"]["id"])
        assert settled_account["settled_balance_cents"] == 100000

        statement = get_statement(ctx["account"]["id"])
        assert statement["settled_balance_cents"] == 100000
        assert statement["provisional_balance_cents"] == 100000
        assert statement["pending_entries_count"] == 0
        assert statement["posted_entries_count"] == 1


class TestLedgerShapeAndConsistency:
    def test_ledger_entry_has_no_version_field_immutable(self, api):
        """PRD §2.4: "An account ledger entry carries `id` and `created_at`
        only; both `updated_at` and `version` are absent, because the ledger is
        append-only."
        PRD §3.3: "An entry's `entry_status` is `PENDING` or `POSTED`: deferral
        credits enter the ledger as `PENDING` — payroll intent not yet confirmed
        — while every other entry type enters directly as `POSTED`."

        Design: Corner/entities/ledger_entry_has_no_version_field_immutable
        """
        ctx = setup_funded_account(100000, settle=False,
                                   plan_overrides={"name": "Plan LE"})
        entries = list_ledger_entries(election_id=ctx["election"]["id"])
        assert len(entries) == 1
        entry = entries[0]
        assert_ledger_entry(entry)  # pins the absent updated_at/version keys
        assert entry["entry_type"] == "DEFERRAL_CREDIT"
        assert entry["entry_status"] == "PENDING"
        assert entry["amount_cents"] == 100000
        assert entry["account_id"] == ctx["account"]["id"]

    def test_immediate_visibility_after_mutation(self, api):
        """PRD §3.3: "Two balance variants are derived from this ledger on every
        mutation and every read."
        PRD §3.2: "An accepted posting creates a ledger entry of type
        `DEFERRAL_CREDIT` in `PENDING` status, carrying the election's
        `notional_fund_id` as its fund reference and the election as its source".

        The post-deferral response, a follow-up GET in the same logical instant,
        and the settle-entries response itself all carry the recomputed balances
        — no read-after-write lag.

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        ctx = setup_funded_account(100000, settle=False,
                                   plan_overrides={"name": "Plan IM"})
        assert ctx["entry"]["entry_status"] == "PENDING"

        account = get_account(ctx["account"]["id"])
        assert account["provisional_balance_cents"] == 100000
        assert account["settled_balance_cents"] == 0

        settled = settle_account(ctx["account"]["id"])
        assert settled["settled_balance_cents"] == 100000, (
            "settle response carries the recomputed settled balance"
        )


class TestNotionalCrediting:
    def test_crediting_round_per_entry_then_sum(self, api):
        """PRD §3.3: "The raw gain is the fund-specific settled balance
        multiplied by the rate in basis points, multiplied by `days_in_period`,
        and divided by the product of 10000 and 365. That raw figure is rounded
        half-up to whole cents **per entry**, and only then are the per-entry
        gains summed into the run's `total_gain_cents`; the reverse order —
        summing raw fractional gains and rounding once — is forbidden because
        the two orders diverge by whole cents on identical inputs."

        Two funds each holding 33333 settled cents at 500 bp for 31 days yield
        raw 141.5514 per entry; the pinned per-entry order gives 142+142 = 284
        while the forbidden sum-then-round order would give 283.

        Design: Difficulty/combinatorial_formula/crediting_round_per_entry_then_sum
        """
        plan = create_active_plan(name="Plan CR", distribution_events_allowed=["SEPARATION"],
                                  vesting_cliff_years=3)
        fund1 = add_fund(plan["id"], ticker="FA")
        fund2 = add_fund(plan["id"], ticker="FB")
        window1 = add_window(plan["id"], plan_year=2027,
                             general_open_date="2026-10-01", general_close_date="2026-12-31")
        window2 = add_window(plan["id"], plan_year=2028,
                             general_open_date="2027-10-01", general_close_date="2027-12-31")
        participant = enroll_participant(plan["id"], employee_ref="EMP-CR")
        account = open_account(participant["id"], plan["id"])

        advance_clock("2026-10-15T00:00:00Z")
        e1 = create_election(participant["id"], window1["id"], fund1["id"])
        submit_election(e1["id"], participant["id"])
        advance_clock("2027-01-01T00:00:00Z")  # e1 LOCKED
        post_deferral(e1["id"], 33333)
        settle_account(account["id"])

        advance_clock("2027-10-15T00:00:00Z")  # window2 OPEN
        e2 = create_election(participant["id"], window2["id"], fund2["id"])
        submit_election(e2["id"], participant["id"])
        advance_clock("2028-01-01T00:00:00Z")  # e2 LOCKED
        post_deferral(e2["id"], 33333)
        settle_account(account["id"])

        run = validate_success(_post_run(api, plan["id"], "2028-03-01", "2028-04-01"), 201)
        assert run["days_in_period"] == 31
        assert run["total_gain_cents"] == 284, (
            "round_half_up(33333*500*31/3650000) = 142 per entry; 142+142"
        )

        entries = list_ledger_entries(crediting_run_id=run["id"])
        gains = [e for e in entries if e["entry_type"] == "CREDITING_GAIN"]
        assert len(gains) == 2
        assert sorted(e["amount_cents"] for e in gains) == [142, 142]
        assert {e["fund_id"] for e in gains} == {fund1["id"], fund2["id"]}

        assert get_account(account["id"])["settled_balance_cents"] == 66950, (
            "33333+33333+284"
        )

    def test_crediting_gain_round_half_up_at_exact_half_cent(self, api):
        """PRD §3.3: "That raw figure is rounded half-up to whole cents **per
        entry**, and only then are the per-entry gains summed into the run's
        `total_gain_cents`".
        PRD §2.5: "Crediting gains and the income-inclusion interest and tax
        components are rounded half-up to whole cents."

        A settled balance of 250 cents at 100 bp for 73 days yields raw gain
        exactly 0.5 cents; half-up rounding posts a 1-cent gain entry.

        Design: Difficulty/combinatorial_formula/crediting_round_per_entry_then_sum
        """
        ctx = setup_funded_account(250, plan_overrides={"name": "Plan RHU"},
                                   fund_overrides={"annual_rate_bp": 100},
                                   participant_overrides={"employee_ref": "EMP-RHU"})
        run = validate_success(_post_run(api, ctx["plan"]["id"], "2027-06-01", "2027-08-13"), 201)
        assert run["days_in_period"] == 73
        assert run["total_gain_cents"] == 1, "round_half_up(250*100*73/3650000) = round_half_up(0.5) = 1"

        entries = list_ledger_entries(crediting_run_id=run["id"])
        gains = [e for e in entries if e["entry_type"] == "CREDITING_GAIN"]
        assert len(gains) == 1 and gains[0]["amount_cents"] == 1
        assert get_account(ctx["account"]["id"])["settled_balance_cents"] == 251

    def test_crediting_index_fund_requires_rate_and_uses_it(self, api):
        """PRD §3.3: "requires every `ACTIVE` `INDEX_LINKED` fund of the plan to
        appear in `index_rates` — an omission is rejected with
        `ERR_INDEX_RATE_MISSING`."
        PRD §3.3: "for an `INDEX_LINKED` fund it is the rate supplied for that
        fund in the run's `index_rates`."

        Omitting the rate fails; supplying 300 bp credits
        round_half_up(100000*300*31/3650000) = 255 cents.

        Design: Corner/calculations/crediting_index_fund_requires_rate_and_uses_it
        """
        ctx = setup_funded_account(
            100000, plan_overrides={"name": "Plan IX"},
            fund_overrides={"ticker": "IDX", "crediting_mode": "INDEX_LINKED",
                            "annual_rate_bp": 0},
            participant_overrides={"employee_ref": "EMP-IX"})

        missing = _post_run(api, ctx["plan"]["id"], "2028-03-01", "2028-04-01")
        validate_error(missing, "ERR_INDEX_RATE_MISSING", expected_status=422)

        run = validate_success(_post_run(
            api, ctx["plan"]["id"], "2028-03-01", "2028-04-01",
            index_rates=[{"fund_id": ctx["fund"]["id"], "annual_rate_bp": 300}]), 201)
        assert run["days_in_period"] == 31
        assert run["total_gain_cents"] == 255, "round_half_up(100000*300*31/3650000)"
        assert get_account(ctx["account"]["id"])["settled_balance_cents"] == 100255

    def test_crediting_skips_pending_entries_basis(self, api):
        """PRD §3.3: "Within an account, each notional fund in which the account
        holds a positive settled balance — the sum of `POSTED` entries bearing
        that fund, replayed as of run creation — earns a gain."

        An account whose 100000 cents are entirely PENDING has a zero settled
        basis and receives zero gain entries.

        Design: Corner/calculations/crediting_skips_pending_entries_basis
        """
        ctx = setup_funded_account(100000, settle=False,
                                   plan_overrides={"name": "Plan PB"},
                                   participant_overrides={"employee_ref": "EMP-PB"})
        run = validate_success(_post_run(api, ctx["plan"]["id"], "2027-02-01", "2027-03-01"), 201)
        assert run["total_gain_cents"] == 0, "PENDING entries are excluded from the basis"
        assert list_ledger_entries(crediting_run_id=run["id"]) == []

        statement = get_statement(ctx["account"]["id"])
        assert statement["settled_balance_cents"] == 0
        assert statement["provisional_balance_cents"] == 100000


class TestCreditingReversal:
    def test_crediting_reversal_restores_settled_balance(self, api):
        """PRD §3.3: "Reversal posts, for every `CREDITING_GAIN` of the run, a
        compensating `CREDITING_REVERSAL` entry of exactly the negated amount
        against the same account, fund, and run, then recomputes balances —
        which return exactly to their pre-run values, a compensating invariant
        the system guarantees — and moves the run to `REVERSED`."

        Settled walks 33333 -> 33475 -> 33333 with zero drift.

        Design: Difficulty/compensating_invariant/crediting_reversal_restores_settled_balance
        """
        ctx = setup_funded_account(33333, plan_overrides={"name": "Plan RI"},
                                   participant_overrides={"employee_ref": "EMP-RI"})
        assert get_account(ctx["account"]["id"])["settled_balance_cents"] == 33333

        run = validate_success(_post_run(api, ctx["plan"]["id"], "2028-03-01", "2028-04-01"), 201)
        assert run["total_gain_cents"] == 142
        assert get_account(ctx["account"]["id"])["settled_balance_cents"] == 33475

        reversed_run = validate_success(api.reverse_crediting_run(run["id"], BA), 200)
        assert reversed_run["status"] == "REVERSED"
        assert get_account(ctx["account"]["id"])["settled_balance_cents"] == 33333, (
            "settled_after_reverse == settled_before_run, zero drift"
        )

        entries = list_ledger_entries(crediting_run_id=run["id"])
        signed = sorted(e["amount_cents"] for e in entries)
        assert signed == [-142, 142], "gain + compensating reversal sum to zero"
        by_type = {e["entry_type"]: e["amount_cents"] for e in entries}
        assert by_type["CREDITING_GAIN"] == 142
        assert by_type["CREDITING_REVERSAL"] == -142

    def test_reversing_latest_of_two_runs_restores_intermediate_balance(self, api):
        """PRD §3.3: "then recomputes balances — which return exactly to their
        pre-run values, a compensating invariant the system guarantees".

        With two runs posted, reversing the latest (R2) returns the settled
        balance to its post-R1 value exactly: 33333 ->(+142 R1) 33475
        ->(+138 R2) 33613 ->(reverse R2) 33475.

        Design: Difficulty/compensating_invariant/crediting_reversal_restores_settled_balance
        """
        ctx = setup_funded_account(33333, plan_overrides={"name": "Plan RI2"},
                                   participant_overrides={"employee_ref": "EMP-RI2"})
        run1 = validate_success(_post_run(api, ctx["plan"]["id"], "2028-03-01", "2028-04-01"), 201)
        assert run1["total_gain_cents"] == 142
        assert get_account(ctx["account"]["id"])["settled_balance_cents"] == 33475

        run2 = validate_success(_post_run(api, ctx["plan"]["id"], "2028-04-01", "2028-05-01"), 201)
        assert run2["total_gain_cents"] == 138, "round_half_up(33475*500*30/3650000)"
        assert get_account(ctx["account"]["id"])["settled_balance_cents"] == 33613

        reversed_run2 = validate_success(api.reverse_crediting_run(run2["id"], BA), 200)
        assert reversed_run2["status"] == "REVERSED"
        assert get_account(ctx["account"]["id"])["settled_balance_cents"] == 33475, (
            "balance returns exactly to the post-R1 value"
        )

        still_posted = validate_success(api.get_crediting_run(run1["id"], BA), 200)
        assert still_posted["status"] == "POSTED"


class TestCreditingPeriodOverlap:
    def test_crediting_period_half_open_adjacency_allowed(self, api):
        """PRD §2.10: "Crediting runs of the same plan use **half-open**
        semantics over the interval from `period_start` inclusive to
        `period_end` exclusive: two runs conflict when one's start falls before
        the other's end while its own end falls after the other's start.
        Back-to-back runs, where one run's `period_end` equals the next run's
        `period_start`, are explicitly allowed. An overlapping new run is
        rejected with `ERR_CREDITING_PERIOD_OVERLAP`."

        Run2 starting exactly at run1's period_end is adjacency (accepted);
        run3 strictly inside run1 is rejected.

        Design: Difficulty/resource_temporal_overlap/crediting_period_half_open_adjacency_allowed
        """
        plan = create_active_plan(name="Plan CO", distribution_events_allowed=["SEPARATION"])
        run1 = validate_success(_post_run(api, plan["id"], "2027-01-01", "2027-02-01"), 201)
        assert run1["total_gain_cents"] == 0, "no funded accounts; run still posts"
        assert run1["status"] == "POSTED"

        run2 = validate_success(_post_run(api, plan["id"], "2027-02-01", "2027-03-01"), 201)
        assert run2["status"] == "POSTED", "adjacency is not overlap under half-open semantics"

        inside = _post_run(api, plan["id"], "2027-01-15", "2027-01-20")
        validate_error(inside, "ERR_CREDITING_PERIOD_OVERLAP", expected_status=409)

    def test_crediting_overlap_ignores_reversed_run(self, api):
        """PRD §3.3: "Creation is concurrency-guarded by `expected_plan_version`
        per §2.7, rejects periods overlapping an existing `POSTED` run of the
        same plan under the half-open rule of §2.10
        (`ERR_CREDITING_PERIOD_OVERLAP`)".

        Only an existing POSTED run blocks a new period: once run1 is REVERSED,
        the same interval may be posted again.

        Design: Difficulty/resource_temporal_overlap/crediting_period_half_open_adjacency_allowed
        """
        plan = create_active_plan(name="Plan CO2", distribution_events_allowed=["SEPARATION"])
        run1 = validate_success(_post_run(api, plan["id"], "2027-01-01", "2027-02-01"), 201)
        reversed_run1 = validate_success(api.reverse_crediting_run(run1["id"], BA), 200)
        assert reversed_run1["status"] == "REVERSED"

        rerun = validate_success(_post_run(api, plan["id"], "2027-01-01", "2027-02-01"), 201)
        assert rerun["status"] == "POSTED", "a REVERSED run is not an existing POSTED run"

    def test_crediting_reverse_not_latest_then_reverse_twice(self, api):
        """PRD §3.3: "the run must be `POSTED` (`ERR_CREDITING_RUN_STATE_INVALID`)
        and must be the plan's most recent `POSTED` run, ranked by greatest
        `period_end` with ties broken toward the later-created run
        (`ERR_CREDITING_RUN_NOT_LATEST`)."

        Design: Corner/errors/crediting_reverse_not_latest_then_reverse_twice
        """
        plan = create_active_plan(name="Plan RN", distribution_events_allowed=["SEPARATION"])
        run1 = validate_success(_post_run(api, plan["id"], "2027-01-01", "2027-02-01"), 201)
        run2 = validate_success(_post_run(api, plan["id"], "2027-02-01", "2027-03-01"), 201)

        not_latest = api.reverse_crediting_run(run1["id"], BA)
        validate_error(not_latest, "ERR_CREDITING_RUN_NOT_LATEST", expected_status=409)

        reversed_run2 = validate_success(api.reverse_crediting_run(run2["id"], BA), 200)
        assert reversed_run2["status"] == "REVERSED"

        twice = api.reverse_crediting_run(run2["id"], BA)
        validate_error(twice, "ERR_CREDITING_RUN_STATE_INVALID", expected_status=409)


class TestDeferralCap:
    def test_deferral_cap_exact_application_and_overflow(self, api):
        """PRD §3.2: "For `GENERAL` and `PERFORMANCE` elections the cap is the
        participant's `annual_compensation_cents` multiplied by
        `deferral_percent_bp` and divided by 10000, rounded down to a whole
        cent."
        PRD §3.2: "Fiscally, the posting may not push the election's cumulative
        `posted_cents` above its `elected_cap_cents` — the new amount plus the
        running total must remain within the cap, else the posting is rejected
        with `ERR_DEFERRAL_CAP_EXCEEDED`."
        PRD §3.2: "when that running total reaches the cap exactly, moves the
        election from `LOCKED` to its terminal `APPLIED` state."

        Cap = floor(30000000*5000/10000) = 15000000. Postings of 14999999 then
        1 reach the cap exactly (APPLIED); a posting of 2 when only 1 remains
        is rejected and posts nothing.

        Design: Corner/calculations/deferral_cap_exact_application_and_overflow
        """
        ctx = setup_plan_fund_window(
            plan_overrides={"name": "Plan DC", "distribution_events_allowed": ["SEPARATION"]})
        participant = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-DC")
        account = open_account(participant["id"], ctx["plan"]["id"])
        advance_clock("2026-10-15T00:00:00Z")
        election = create_election(participant["id"], ctx["window"]["id"], ctx["fund"]["id"])
        submitted = submit_election(election["id"], participant["id"])
        assert submitted["elected_cap_cents"] == 15000000

        advance_clock("2027-01-01T00:00:00Z")  # LOCKED
        post_deferral(election["id"], 14999999)

        over = api.post_deferral(election["id"], {
            "amount_cents": 2,
            "service_period_start": "2027-02-01",
            "service_period_end": "2027-02-28",
        }, BA)
        validate_error(over, "ERR_DEFERRAL_CAP_EXCEEDED", expected_status=402)
        assert get_election(election["id"])["posted_cents"] == 14999999, "nothing posted"

        post_deferral(election["id"], 1, service_period_start="2027-02-01",
                      service_period_end="2027-02-28")
        final = get_election(election["id"])
        assert final["posted_cents"] == 15000000
        assert final["status"] == "APPLIED", "exact-cap posting flips LOCKED -> APPLIED"
        assert get_account(account["id"])["provisional_balance_cents"] == 15000000
