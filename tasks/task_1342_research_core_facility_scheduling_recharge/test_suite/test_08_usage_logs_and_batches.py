"""Usage-log workflow, recharge-batch lifecycle, open-batch gating, and
grant fiscal capacity (PRD §3.6, §3.8, §3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, create_usage_log_payload, create_recharge_batch_payload,
    create_subsidy_application_payload, create_award_approval_payload,
    make_researcher_headers,
    setup_canonical_stack, create_user, create_approved_booking,
    create_booking_request, approve_booking, open_batch, finalize_batch,
    run_session_to_completed, create_and_validate_usage_log,
    set_clock, get_batch, get_grant, get_booking, find_entries,
    list_all_entries,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
STAFF2 = TEST_USERS["staff2_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _completed_booking(api, stack, start="2026-09-01T09:00:00Z",
                       end="2026-09-01T10:30:00Z",
                       actual_start="2026-09-01T09:00:00Z",
                       actual_end="2026-09-01T10:30:00Z"):
    b = create_approved_booking(stack, start_at=start, end_at=end)
    return run_session_to_completed(b, actual_start, actual_end)


class TestUsageWindow:
    def test_usage_window_invalid_both_branches(self, api):
        """PRD §3.8: "the observed window must be well-formed:
        `actual_end_at` strictly after `actual_start_at`, and `actual_end_at`
        no later than twenty-four hours after the booking's `end_at`
        (`ERR_USAGE_WINDOW_INVALID`)."

        Design: Corner/validations/usage_window_invalid_both_branches
        """
        stack = setup_canonical_stack()
        b1 = _completed_booking(api, stack)  # booking end 2026-09-01T10:30
        degenerate = api.create_usage_log(
            create_usage_log_payload(
                b1["id"], "2026-09-01T10:00:00Z", "2026-09-01T10:00:00Z"
            ),
            STAFF,
        )
        validate_error(degenerate, "ERR_USAGE_WINDOW_INVALID", expected_status=422)
        # booking.end + 24h is 2026-09-02T10:30; 11:00 exceeds it.
        beyond_cap = api.create_usage_log(
            create_usage_log_payload(
                b1["id"], "2026-09-01T09:00:00Z", "2026-09-02T11:00:00Z"
            ),
            STAFF,
        )
        validate_error(beyond_cap, "ERR_USAGE_WINDOW_INVALID", expected_status=422)
        logs = validate_success(api.list_usage_logs(STAFF), 200)
        assert [l for l in logs if l.get("booking_id") == b1["id"]] == [], (
            "no usage log may be persisted by rejected creates"
        )

    def test_usage_log_unique_per_booking(self, api):
        """PRD §3.8: "Exactly one usage log may exist per booking
        (`ERR_USAGE_LOG_EXISTS`)".

        Design: Corner/validations/usage_log_unique_per_booking
        """
        stack = setup_canonical_stack()
        b1 = _completed_booking(api, stack)
        validate_success(
            api.create_usage_log(
                create_usage_log_payload(
                    b1["id"], "2026-09-01T09:00:00Z", "2026-09-01T10:30:00Z"
                ),
                STAFF,
            ),
            201,
        )
        res = api.create_usage_log(
            create_usage_log_payload(
                b1["id"], "2026-09-01T09:00:00Z", "2026-09-01T10:00:00Z"
            ),
            STAFF,
        )
        validate_error(res, "ERR_USAGE_LOG_EXISTS", expected_status=409)

    def test_usage_log_edit_after_validate(self, api):
        """PRD §3.8: "A `DRAFT` log may be edited (its times and
        `consumable_fee_cents`) and then submitted" and "`VALIDATED` is
        terminal." PRD §2.9: "State-machine legality (`ERR_INVALID_STATE`):
        the target resource's current state must permit the requested
        transition".

        Design: Corner/state_machines/usage_log_edit_after_validate
        """
        stack = setup_canonical_stack()
        b1 = _completed_booking(
            api, stack, actual_start="2026-09-01T09:00:00Z",
            actual_end="2026-09-01T10:14:00Z",
        )
        open_batch(2026, 9)
        log = create_and_validate_usage_log(
            b1, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z"
        )
        assert log["status"] == "VALIDATED"
        res = api.edit_usage_log(log["id"], {"consumable_fee_cents": 999}, STAFF)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        after = validate_success(api.get_usage_log(log["id"], STAFF), 200)
        assert after["consumable_fee_cents"] == 0, "a rejected edit must not mutate"


class TestBatchGating:
    def test_validate_without_open_batch(self, api):
        """PRD §3.8: "Validation re-checks that the booking is `COMPLETED` and
        that an `OPEN` `RechargeBatch` exists (`ERR_BATCH_NOT_OPEN`)."

        Design: Corner/validations/validate_without_open_batch
        """
        stack = setup_canonical_stack()
        b1 = _completed_booking(api, stack)
        log = validate_success(
            api.create_usage_log(
                create_usage_log_payload(
                    b1["id"], "2026-09-01T09:00:00Z", "2026-09-01T10:30:00Z"
                ),
                STAFF,
            ),
            201,
        )
        validate_success(api.submit_usage_log(log["id"], STAFF), 200)
        res = api.validate_usage_log(log["id"], STAFF2)
        validate_error(res, "ERR_BATCH_NOT_OPEN", expected_status=409)
        after = validate_success(api.get_usage_log(log["id"], STAFF), 200)
        assert after["status"] == "SUBMITTED"
        assert list_all_entries() == [], "no entry may be created"
        grant = get_grant(stack["g1"]["id"])
        assert grant["budget_used_cents"] == 0, "grant ledger untouched"

    def test_duplicate_open_batch(self, api):
        """PRD §3.9: "the pair is unique, only one `OPEN` batch may exist at
        any time (`ERR_DUPLICATE_OPEN_BATCH`)".

        Design: Corner/validations/duplicate_open_batch
        """
        from test_helpers import open_fiscal_year
        open_fiscal_year(2026)
        open_batch(2026, 9)
        res = api.create_recharge_batch(
            create_recharge_batch_payload(period_year=2026, period_month=10),
            FINANCE,
        )
        validate_error(res, "ERR_DUPLICATE_OPEN_BATCH", expected_status=409)


class TestBatchTotals:
    def test_batch_totals_track_entries_while_open(self, api):
        """PRD §3.9: "While `OPEN`, the batch's totals — `entry_count`,
        `gross_amount_cents`, `subsidy_offset_cents`, `net_amount_cents` —
        track their entries incrementally: the count of entries posted to the
        batch and the sums of `amount_cents`, `subsidy_offset_cents`, and
        `net_amount_cents` over them."

        Design: Corner/calculations/batch_totals_track_entries_while_open
        """
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)
        b2 = create_approved_booking(
            stack, start_at="2026-09-02T09:00:00Z", end_at="2026-09-02T09:30:00Z"
        )
        batch = open_batch(2026, 9)
        c1 = run_session_to_completed(b1, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z")
        log1 = create_and_validate_usage_log(
            c1, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z"
        )
        c2 = run_session_to_completed(b2, "2026-09-02T09:00:00Z", "2026-09-02T09:30:00Z")
        log2 = create_and_validate_usage_log(
            c2, "2026-09-02T09:00:00Z", "2026-09-02T09:30:00Z"
        )
        after = get_batch(batch["id"])
        assert after["status"] == "OPEN"
        assert after["entry_count"] == 2
        assert after["gross_amount_cents"] == 21000, "15000 + 6000"
        assert after["net_amount_cents"] == 21000
        assert after["subsidy_offset_cents"] == 0
        entries = find_entries(batch_id=batch["id"])
        assert all(e["status"] == "PENDING" for e in entries), (
            "entries stay PENDING until finalization (PRD §3.9)"
        )


class TestTerminalLockdowns:
    def test_batch_finalize_twice_and_application_terminal(self, api):
        """PRD §3.9: "Finalization by a `FinanceOfficer` flips every `PENDING`
        entry in the batch to `BILLED`, freezes the four totals by recomputing
        them once — they are immutable thereafter". PRD §3.10: "Submitting — by
        the owning `Researcher`, from `DRAFT` or `REVISION_REQUESTED`". PRD
        §2.9: "State-machine legality (`ERR_INVALID_STATE`): the target
        resource's current state must permit the requested transition".

        Design: Corner/state_machines/batch_finalize_twice_and_application_terminal
        """
        from test_helpers import open_fiscal_year
        open_fiscal_year(2026)
        batch = open_batch(2026, 9)
        finalize_batch(batch["id"])
        u1 = create_user(is_pi=True)
        application = validate_success(
            api.create_subsidy_application(
                create_subsidy_application_payload(u1["id"]),
                make_researcher_headers(u1["id"]),
            ),
            201,
        )
        owner = make_researcher_headers(u1["id"])
        validate_success(api.submit_subsidy_application(application["id"], owner), 200)
        validate_success(api.review_subsidy_application(application["id"], FINANCE), 200)
        award = validate_success(
            api.approve_subsidy_application(
                application["id"], create_award_approval_payload(), FINANCE
            ),
            200,
        )

        res1 = api.finalize_recharge_batch(batch["id"], FINANCE)
        validate_error(res1, "ERR_INVALID_STATE", expected_status=409)
        res2 = api.submit_subsidy_application(application["id"], owner)
        validate_error(res2, "ERR_INVALID_STATE", expected_status=409)
        award_after = validate_success(api.get_subsidy_award(award["id"], FINANCE), 200)
        assert award_after["status"] == "ACTIVE"
        assert award_after["remaining_amount_cents"] == 5000


class TestEpochRouting:
    def test_ops_epoch_routes_penalty_to_open_batch(self, api):
        """PRD §3.7: "Whenever `penalty_cents` exceeds zero, a `PENALTY`
        `RechargeEntry` — with `amount_cents` equal to the penalty,
        `subsidy_offset_cents` zero, and `net_amount_cents` equal to the
        penalty — posts into the currently `OPEN` `RechargeBatch` (none open
        means `ERR_BATCH_NOT_OPEN`)". PRD §3.9: "Finalization deliberately does
        *not* open the next period's batch; the `FinanceOfficer` opens each
        period explicitly, which keeps fiscal-year close deterministic.
        Corrections after finalization never touch the frozen batch — they post
        as `ADJUSTMENT` entries into the *next* open batch."

        Design: Corner/cross_cutting_layers/ops_epoch_routes_penalty_to_open_batch
        """
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)
        b2 = create_approved_booking(
            stack, start_at="2026-09-03T09:00:00Z", end_at="2026-09-03T10:30:00Z"
        )
        bat9 = open_batch(2026, 9)
        c1 = run_session_to_completed(b1, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z")
        create_and_validate_usage_log(c1, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z")
        finalize_batch(bat9["id"])
        bat10 = open_batch(2026, 10)

        # 2026-09-02T12:00 is 21 h before b2's start: inside the 24 h window.
        set_clock("2026-09-02T12:00:00Z")
        owner = make_researcher_headers(stack["u1"]["id"])
        cancelled = validate_success(api.cancel_booking(b2["id"], owner), 200)
        assert cancelled["penalty_cents"] == 9000

        penalties = find_entries(booking_id=b2["id"], kind="PENALTY")
        assert len(penalties) == 1
        assert penalties[0]["batch_id"] == bat10["id"], (
            "the penalty posts to the currently OPEN epoch, not the finalized one"
        )
        assert penalties[0]["amount_cents"] == 9000
        bat9_after = get_batch(bat9["id"])
        assert bat9_after["status"] == "FINALIZED"
        assert bat9_after["entry_count"] == 1


class TestGrantFiscalCapacity:
    def _setup(self, api):
        """grantA totals exactly 15000; bookingA 75 minutes (estimate 15000)
        approved, completed with 75 actual minutes, log submitted. grantB
        16000 with bB1 approved (estimate 15000) and bB2 REQUESTED
        (estimate 6000)."""
        stack = setup_canonical_stack(with_grant=False)
        gA = validate_success(
            api.create_grant(
                {"grant_code": "NIH-A", "pi_user_id": stack["u1"]["id"],
                 "title": "Exact fit", "budget_total_cents": 15000,
                 "start_date": "2026-01-01", "end_date": "2026-12-31"},
                FINANCE,
            ),
            201,
        )
        gB = validate_success(
            api.create_grant(
                {"grant_code": "NIH-B", "pi_user_id": stack["u1"]["id"],
                 "title": "Overflow", "budget_total_cents": 16000,
                 "start_date": "2026-01-01", "end_date": "2026-12-31"},
                FINANCE,
            ),
            201,
        )
        bA = create_approved_booking(
            stack, start_at="2026-09-01T09:00:00Z", end_at="2026-09-01T10:15:00Z",
            grant=gA,
        )
        bB1 = create_approved_booking(
            stack, start_at="2026-09-02T09:00:00Z", end_at="2026-09-02T10:15:00Z",
            grant=gB,
        )
        bB2 = create_booking_request(
            stack, start_at="2026-09-03T09:00:00Z", end_at="2026-09-03T09:30:00Z",
            grant=gB,
        )
        open_batch(2026, 9)
        completedA = run_session_to_completed(
            bA, "2026-09-01T09:00:00Z", "2026-09-01T10:15:00Z"
        )
        logA = validate_success(
            api.create_usage_log(
                create_usage_log_payload(
                    completedA["id"], "2026-09-01T09:00:00Z", "2026-09-01T10:15:00Z"
                ),
                STAFF,
            ),
            201,
        )
        validate_success(api.submit_usage_log(logA["id"], STAFF), 200)
        return stack, gA, gB, bA, bB1, bB2, logA

    def test_exact_fit_validation_succeeds_and_exhausts(self, api):
        """PRD §3.8: "For an internal user, validation also requires the
        grant's `budget_available_cents` to be at least the entry's
        `net_amount_cents` (`ERR_GRANT_BUDGET_EXCEEDED`)." PRD §2.10:
        "otherwise `EXHAUSTED` when `budget_available_cents` is less than or
        equal to zero — exactly zero is exhausted — and otherwise `ACTIVE`."

        Design: Difficulty/boundary_precision_check/grant_budget_exact_fit_at_validation
        """
        stack, gA, gB, bA, bB1, bB2, logA = self._setup(api)
        validated = validate_success(api.validate_usage_log(logA["id"], STAFF2), 200)
        assert validated["usage_charge_cents"] == 15000, "75 billable min x 200"
        grant = get_grant(gA["id"])
        assert grant["budget_available_cents"] == 0
        assert grant["status"] == "EXHAUSTED", "exactly zero is exhausted"

    def test_one_cent_over_budget_at_approval_rejected(self, api):
        """PRD §3.6: "Second, fiscal capacity: for an internal booking, the
        grant's `budget_available_cents` must be at least the provisional
        estimate (`ERR_GRANT_BUDGET_EXCEEDED`)."

        Design: Difficulty/boundary_precision_check/grant_budget_exact_fit_at_validation
        """
        stack, gA, gB, bA, bB1, bB2, logA = self._setup(api)
        # bB1 already encumbers 15000 of grantB's 16000 -> 1000 available;
        # bB2's 30-minute estimate is 6000 cents > 1000.
        res = api.approve_booking(bB2["id"], STAFF)
        validate_error(res, "ERR_GRANT_BUDGET_EXCEEDED", expected_status=422)
        assert get_booking(bB2["id"])["status"] == "REQUESTED"
