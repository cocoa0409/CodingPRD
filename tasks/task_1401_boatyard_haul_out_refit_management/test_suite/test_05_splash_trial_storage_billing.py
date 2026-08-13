"""Splash gating, sea trials, storage accrual variants, and the ledger."""
from test_helpers import (
    ApiErrorId,
    approve_work_order,
    complete_work_order,
    create_lift_slot_payload,
    create_refit_job,
    create_submitted_job,
    create_vessel,
    create_vessel_with_insurance,
    get_job,
    get_statement,
    list_ledger_entries,
    post_ledger_entry,
    run_daily_close,
    set_clock,
    setup_job_awaiting_trial,
    setup_job_on_hard,
    setup_job_ready_for_splash,
    setup_two_jobs_different_billing_modes,
    start_work_order,
    create_work_order,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, api_client, assert_statement

SW = TEST_USERS["service_writer_headers"]
YM = TEST_USERS["yard_manager_headers"]
AC = TEST_USERS["accountant_headers"]


class TestSplashBookingGates:

    def _work_in_progress_job(self):
        """Job hauled and one work order started (job WORK_IN_PROGRESS)."""
        ctx = setup_job_on_hard(vessel_name="MV Priority")
        owner_id = ctx["vessel"]["owner_user_id"]
        wo = create_work_order(ctx["job"]["id"], type="MECHANICAL",
                               description="Engine", quoted_hours=10,
                               quoted_rate_cents=8000, quoted_parts_cents=5000)
        approve_work_order(wo["id"], owner_id)
        start_work_order(wo["id"])
        ctx["work_order"] = wo
        return ctx

    def test_state_gate_beats_deposit_shortfall(self):
        """PRD section 2.9: "State legality comes seventh — a wrong
        from-state yields `ERR_INVALID_STATE`, an entity already in a
        terminal state yields `ERR_ALREADY_TERMINAL`, and a splash booking
        against a job that is not ready yields
        `ERR_JOB_NOT_READY_FOR_SPLASH`. Only after all seven generic gates
        pass do the business rules of Section 3 apply, in the order each
        workflow narrative states them."
        PRD section 3.10: "Before a splash slot may be booked, the job must
        be `READY_FOR_SPLASH` (else `ERR_JOB_NOT_READY_FOR_SPLASH`) and the
        deposit gate must pass."

        Design: Difficulty/priority_pair_validation_conflict/splash_booking_state_beats_deposit_fiscal
        """
        ctx = self._work_in_progress_job()
        assert get_job(ctx["job"]["id"])["status"] == "WORK_IN_PROGRESS"
        # No deposits posted: the fiscal gate would also fail.
        resp = api_client.create_lift_slot(
            create_lift_slot_payload(
                ctx["job"]["id"], kind="SPLASH",
                scheduled_start="2026-08-20T08:00:00Z",
                scheduled_end="2026-08-20T09:00:00Z",
                vessel_displacement_tons=20),
            YM)
        validate_error(resp, ApiErrorId.ERR_JOB_NOT_READY_FOR_SPLASH)

    def test_state_gate_fires_alone_when_deposit_satisfied(self):
        """PRD section 3.10: "Before a splash slot may be booked, the job
        must be `READY_FOR_SPLASH` (else `ERR_JOB_NOT_READY_FOR_SPLASH`) and
        the deposit gate must pass."

        Design: Difficulty/priority_pair_validation_conflict/splash_booking_state_beats_deposit_fiscal
        """
        ctx = self._work_in_progress_job()
        # Satisfy the deposit requirement (0.25 x 85000) so only the state
        # gate can fail.
        post_ledger_entry(ctx["job"]["id"], kind="DEPOSIT",
                          amount_cents=21250)
        resp = api_client.create_lift_slot(
            create_lift_slot_payload(
                ctx["job"]["id"], kind="SPLASH",
                scheduled_start="2026-08-20T08:00:00Z",
                scheduled_end="2026-08-20T09:00:00Z",
                vessel_displacement_tons=20),
            YM)
        validate_error(resp, ApiErrorId.ERR_JOB_NOT_READY_FOR_SPLASH)

    def test_deposit_boundary_exact_25_percent(self):
        """PRD section 3.10: "The requirement is satisfied when posted
        deposits are at least the required amount; the boundary is inclusive,
        so deposits exactly equal to the requirement pass. Booking a splash
        while short is rejected with `ERR_DEPOSIT_SHORTFALL`."

        Design: Corner/calculations/deposit_boundary_exact_25_percent
        """
        ctx = setup_job_ready_for_splash(vessel_name="MV Dep",
                                         deposit_cents=None)
        # Required: round_half_up(0.25 x 85000) = 21250.
        post_ledger_entry(ctx["job"]["id"], kind="DEPOSIT",
                          amount_cents=21249)
        short = api_client.create_lift_slot(
            create_lift_slot_payload(
                ctx["job"]["id"], kind="SPLASH",
                scheduled_start="2026-08-20T08:00:00Z",
                scheduled_end="2026-08-20T09:00:00Z",
                vessel_displacement_tons=20),
            YM)
        validate_error(short, ApiErrorId.ERR_DEPOSIT_SHORTFALL)

        post_ledger_entry(ctx["job"]["id"], kind="DEPOSIT", amount_cents=1)
        booked = api_client.create_lift_slot(
            create_lift_slot_payload(
                ctx["job"]["id"], kind="SPLASH",
                scheduled_start="2026-08-20T08:00:00Z",
                scheduled_end="2026-08-20T09:00:00Z",
                vessel_displacement_tons=20),
            YM)
        data = validate_success(booked, expected_status=201)
        assert data["status"] == "BOOKED", \
            "deposits exactly equal to the requirement satisfy the gate"


class TestSeaTrialFailCycle:

    def test_sea_trial_fail_returns_job_to_work_in_progress(self):
        """PRD section 3.10: "A `FAIL` outcome requires
        `failed_work_order_id` referencing one of the job's work orders that
        is currently `COMPLETE`; a reference to a work order in any other
        state is rejected with `ERR_INVALID_STATE`. On failure the job
        returns to `WORK_IN_PROGRESS` and the referenced work order becomes
        `CHANGE_REQUESTED` — hop two of the sea-trial-fail cascade —
        re-entering the change-order cycle of §3.5."

        Design: Difficulty/non_linear_state_machine/job_sea_trial_fail_full_cycle
        """
        ctx = setup_job_awaiting_trial(vessel_name="MV Trial")
        assert ctx["job"]["status"] == "AWAITING_TRIAL"

        failed = validate_success(api_client.record_sea_trial(
            ctx["job"]["id"],
            {"outcome": "FAIL",
             "failed_work_order_id": ctx["work_order"]["id"],
             "notes": "Vibration at cruise RPM"},
            YM))
        assert failed["status"] == "WORK_IN_PROGRESS"

    def test_failed_work_order_cycle_returns_job_to_ready_for_splash(self):
        """PRD section 3.10: "Readiness for splash is a computed job
        property, re-evaluated on every work-order completion and every hold
        release. A job becomes `READY_FOR_SPLASH` — from either `ON_HARD` or
        `WORK_IN_PROGRESS` — when three conditions hold simultaneously: at
        least one of the job's work orders is `COMPLETE`; every work order of
        the job is in `COMPLETE` or `CANCELLED`; and the job's
        `open_hold_count` is zero."

        Design: Difficulty/non_linear_state_machine/job_sea_trial_fail_full_cycle
        """
        ctx = setup_job_awaiting_trial(vessel_name="MV Trial2")
        owner_id = ctx["vessel"]["owner_user_id"]
        wo_id = ctx["work_order"]["id"]
        validate_success(api_client.record_sea_trial(
            ctx["job"]["id"],
            {"outcome": "FAIL", "failed_work_order_id": wo_id},
            YM))
        from test_helpers import get_work_order
        assert get_work_order(wo_id)["status"] == "CHANGE_REQUESTED"

        validate_success(api_client.requote_work_order(
            wo_id,
            {"quoted_hours": 12, "quoted_rate_cents": 8000,
             "quoted_parts_cents": 9000},
            SW))
        approve_work_order(wo_id, owner_id)
        start_work_order(wo_id)
        complete_work_order(wo_id)
        assert get_job(ctx["job"]["id"])["status"] == "READY_FOR_SPLASH", \
            "the fail loop re-traverses to READY_FOR_SPLASH"


class TestSeaTrialFailCascade:

    def _awaiting_trial_with_labor_charge(self):
        return setup_job_awaiting_trial(
            vessel_name="MV Cascade",
            labor_lines=[{"worker_type": "YARD_CREW", "hours": 5,
                          "rate_cents": 8000}])

    def test_sea_trial_fail_reopens_complete_work_order(self):
        """PRD section 3.10: "On failure the job returns to
        `WORK_IN_PROGRESS` and the referenced work order becomes
        `CHANGE_REQUESTED` — hop two of the sea-trial-fail cascade —
        re-entering the change-order cycle of §3.5."

        Design: Difficulty/transitive_cascade/sea_trial_fail_cascade_reopens_work
        """
        ctx = self._awaiting_trial_with_labor_charge()
        failed = validate_success(api_client.record_sea_trial(
            ctx["job"]["id"],
            {"outcome": "FAIL",
             "failed_work_order_id": ctx["work_order"]["id"]},
            YM))
        assert failed["status"] == "WORK_IN_PROGRESS", "hop 1"
        from test_helpers import get_work_order
        assert get_work_order(
            ctx["work_order"]["id"])["status"] == "CHANGE_REQUESTED", "hop 2"

    def test_sea_trial_fail_keeps_posted_labor_charge(self):
        """PRD section 2.8: "Voiding is the sole compensation mechanism: an
        `Accountant` may void a posted entry, moving it from `POSTED` to
        `VOIDED`, after which it contributes nothing to the balance or to
        statement aggregates."
        PRD section 3.10: "On failure the job returns to `WORK_IN_PROGRESS`
        and the referenced work order becomes `CHANGE_REQUESTED` — hop two of
        the sea-trial-fail cascade — re-entering the change-order cycle of
        §3.5."

        Design: Difficulty/transitive_cascade/sea_trial_fail_cascade_reopens_work
        """
        ctx = self._awaiting_trial_with_labor_charge()
        # 5h x 8000c = 40000 posted at completion.
        validate_success(api_client.record_sea_trial(
            ctx["job"]["id"],
            {"outcome": "FAIL",
             "failed_work_order_id": ctx["work_order"]["id"]},
            YM))
        charges = list_ledger_entries(ctx["job"]["id"],
                                      params={"kind": "CHARGE"})
        assert len(charges) == 1
        assert charges[0]["status"] == "POSTED", \
            "the fail cascade does not void the posted LABOR charge"
        assert charges[0]["amount_cents"] == 40000


class TestStorageAccrual:

    def test_daily_variant_accrues_marginal_tiers(self):
        """PRD section 3.11: "Under the `DAILY` billing variant, each accrued
        date posts one ledger entry of kind `CHARGE`, category `STORAGE`. The
        per-day charge is the vessel's `loa_ft` multiplied by a marginal tier
        rate in cents per foot and by a winter multiplier, rounded half-up to
        whole cents per day — per-day rounding is pinned, never
        sum-then-round. The tier rate is 50 cents per foot for lay-day
        indexes 1 through 7, 65 cents per foot for indexes 8 through 30, and
        85 cents per foot for index 31 and beyond."

        Design: Difficulty/dual_variant_calc/storage_daily_vs_monthly_divergence
        """
        ctx_a, _ctx_b, _close = setup_two_jobs_different_billing_modes()
        statement = get_statement(ctx_a["job"]["id"])
        assert_statement(statement)
        assert statement["lay_days"] == 10, \
            "2026-08-02 through 2026-08-11 inclusive is 10 lay days"
        # 7 days x (40 x 50) + 3 days x (40 x 65) = 14000 + 7800
        assert statement["storage_charges_cents"] == 21800

    def test_monthly_variant_posts_flat_block(self):
        """PRD section 3.11: "Under the `MONTHLY_CONTRACT` variant, storage
        posts in flat 30-day blocks: when the accrued date's lay-day index,
        reduced by one, is an exact multiple of 30 — that is, lay days 1, 31,
        61, and so on — one ledger entry of kind `CHARGE`, category `STORAGE`
        posts for the vessel's `loa_ft` multiplied by 1400 cents per foot,
        rounded half-up. All other accrued dates post nothing."
        PRD section 3.11: "The two variants intentionally diverge: identical
        lay days produce different totals, with short stays cheaper under
        daily accrual than under a monthly block."

        Design: Difficulty/dual_variant_calc/storage_daily_vs_monthly_divergence
        """
        ctx_a, ctx_b, _close = setup_two_jobs_different_billing_modes()
        stmt_a = get_statement(ctx_a["job"]["id"])
        stmt_b = get_statement(ctx_b["job"]["id"])
        assert stmt_b["lay_days"] == 10
        # One 30-day block: 40 x 1400
        assert stmt_b["storage_charges_cents"] == 56000
        assert stmt_a["storage_charges_cents"] != \
            stmt_b["storage_charges_cents"], \
            "identical lay days diverge between the two billing variants"

    def test_winter_tier_per_day_rounding(self):
        """PRD section 3.11: "The winter multiplier is 0.85 when the accrued
        date's month-and-day falls within November 1 through March 31,
        inclusive, and 1.0 otherwise."
        PRD section 2.7: "Every monetary multiplication is rounded half-up to
        zero decimal places, and the rounding point is pinned per rule:
        quoted totals round the labor product only, before adding the parts
        allowance; labor lines round each line individually before any
        summation — never sum-then-round; daily storage rounds each calendar
        day's charge individually before any accumulation."

        Design: Difficulty/combinatorial_formula/storage_winter_tier_per_day_rounding
        """
        ctx = setup_job_on_hard(
            vessel_name="SV Winter", owner_user_id="owner-1", loa_ft=37,
            beam_ft=12, hull_type="SAIL", displacement_tons=15,
            billing_mode="DAILY", row_code="W", total_stands=8,
            stands_used=3, haul_date="2026-11-01", stand_end_date="2026-12-15",
            clock_init="2026-10-28T09:00:00Z")
        set_clock("2026-11-07T12:00:00Z")
        run_daily_close()

        statement = get_statement(ctx["job"]["id"])
        assert statement["lay_days"] == 7, \
            "2026-11-01 through 2026-11-07 inclusive is 7 lay days"
        # 7 x round_half_up(37 x 50 x 0.85) = 7 x 1573
        assert statement["storage_charges_cents"] == 11011
        assert statement["storage_charges_cents"] != 11008, \
            "per-day rounding is pinned; sum-then-round would give 11008"

    def test_winter_per_day_rounding_visible_per_ledger_entry(self):
        """PRD section 3.11: "Under the `DAILY` billing variant, each accrued
        date posts one ledger entry of kind `CHARGE`, category `STORAGE`. The
        per-day charge is the vessel's `loa_ft` multiplied by a marginal tier
        rate in cents per foot and by a winter multiplier, rounded half-up to
        whole cents per day — per-day rounding is pinned, never
        sum-then-round."
        PRD section 3.11: "The winter multiplier is 0.85 when the accrued
        date's month-and-day falls within November 1 through March 31,
        inclusive, and 1.0 otherwise."

        Design: Difficulty/combinatorial_formula/storage_winter_tier_per_day_rounding
        """
        ctx = setup_job_on_hard(
            vessel_name="SV Winter2", owner_user_id="owner-1", loa_ft=37,
            beam_ft=12, hull_type="SAIL", displacement_tons=15,
            billing_mode="DAILY", row_code="W", total_stands=8,
            stands_used=3, haul_date="2026-11-01", stand_end_date="2026-12-15",
            clock_init="2026-10-28T09:00:00Z")
        set_clock("2026-11-07T12:00:00Z")
        close = run_daily_close()
        assert close["storage_entries_posted"] == 7, \
            "one CHARGE/STORAGE entry per accrued date"

        charges = list_ledger_entries(ctx["job"]["id"],
                                      params={"kind": "CHARGE"})
        assert len(charges) == 7
        for entry in charges:
            assert entry["category"] == "STORAGE"
            # round_half_up(37 x 50 x 0.85) = round_half_up(1572.5) = 1573
            assert entry["amount_cents"] == 1573, \
                "each winter tier-1 day is rounded half-up individually"

    def test_storage_tier_boundary_day8_uses_tier2(self):
        """PRD section 3.11: "The tier rate is 50 cents per foot for lay-day
        indexes 1 through 7, 65 cents per foot for indexes 8 through 30, and
        85 cents per foot for index 31 and beyond."
        PRD section 3.11: "Each accrued date carries a one-based lay-day
        index: the job's current `lay_days` plus the date's offset within the
        sweep. After the sweep, `lay_days` increases by the number of accrued
        dates and `last_accrual_date` becomes the current date."

        Design: Corner/calculations/storage_tier_boundary_day8_uses_tier2
        """
        ctx = setup_job_on_hard(vessel_name="MV Tier", row_code="TB",
                                total_stands=8, stands_used=3)
        set_clock("2026-08-08T12:00:00Z")
        close1 = run_daily_close()
        assert close1["storage_entries_posted"] == 7
        stmt7 = get_statement(ctx["job"]["id"])
        assert stmt7["storage_charges_cents"] == 14000, \
            "7 x (40 x 50), all tier 1"

        set_clock("2026-08-09T12:00:00Z")
        close2 = run_daily_close()
        assert close2["storage_entries_posted"] == 1, \
            "only lay-day index 8 accrues on the second close"
        stmt8 = get_statement(ctx["job"]["id"])
        assert stmt8["lay_days"] == 8
        # 14000 + 40 x 65 (tier 2) = 14000 + 2600
        assert stmt8["storage_charges_cents"] == 16600

    def test_monthly_block_second_block_at_day31(self):
        """PRD section 3.11: "Under the `MONTHLY_CONTRACT` variant, storage
        posts in flat 30-day blocks: when the accrued date's lay-day index,
        reduced by one, is an exact multiple of 30 — that is, lay days 1, 31,
        61, and so on — one ledger entry of kind `CHARGE`, category `STORAGE`
        posts for the vessel's `loa_ft` multiplied by 1400 cents per foot,
        rounded half-up. All other accrued dates post nothing."

        Design: Corner/calculations/monthly_block_second_block_at_day31
        """
        ctx = setup_job_on_hard(
            vessel_name="MV Block", hull_type="SAIL",
            billing_mode="MONTHLY_CONTRACT", row_code="MB", total_stands=8,
            stands_used=3)
        set_clock("2026-09-01T12:00:00Z")
        close = run_daily_close()
        assert close["storage_entries_posted"] == 2, \
            "blocks post on lay-day indexes 1 and 31 only"

        statement = get_statement(ctx["job"]["id"])
        assert statement["lay_days"] == 31, \
            "2026-08-02 through 2026-09-01 inclusive is 31 lay days"
        # 2 x (40 x 1400)
        assert statement["storage_charges_cents"] == 112000

    def test_daily_close_idempotent_same_day(self):
        """PRD section 3.11: "A job whose `last_accrual_date` already equals
        the current date is skipped, so a same-day re-run of the close
        accrues nothing; the close is idempotent."

        Design: Corner/endpoints/daily_close_idempotent_same_day
        """
        ctx = setup_job_on_hard(vessel_name="MV Idem", row_code="ID",
                                total_stands=6, stands_used=3)
        set_clock("2026-08-05T12:00:00Z")
        close1 = run_daily_close()
        assert close1["storage_entries_posted"] == 4, \
            "lay days 2026-08-02 through 2026-08-05 accrue 4 entries"
        store1 = get_statement(ctx["job"]["id"])["storage_charges_cents"]
        assert store1 == 8000, "4 x (40 x 50)"

        close2 = run_daily_close()
        assert close2["storage_entries_posted"] == 0
        store2 = get_statement(ctx["job"]["id"])["storage_charges_cents"]
        assert store2 == 8000, "the same-day re-run accrues nothing"


class TestLedgerConservation:

    def _job_with_labor_charge(self):
        """WORK_IN_PROGRESS -> one completed work order with a 40000-cent
        POSTED LABOR charge; job settles in READY_FOR_SPLASH."""
        return setup_job_ready_for_splash(
            vessel_name="MV Ledger",
            labor_lines=[{"worker_type": "YARD_CREW", "hours": 5,
                          "rate_cents": 8000}],
            deposit_cents=None)

    def test_deposit_moves_balance(self):
        """PRD section 2.8: "The job's `balance_cents` is the sum of
        `amount_cents` over all `POSTED` entries of kind `CHARGE`, minus the
        sum of `amount_cents` over all `POSTED` entries of kind `PAYMENT`,
        `CREDIT`, or `DEPOSIT`."

        Design: Difficulty/compensating_invariant/ledger_post_void_conserves_balance
        """
        ctx = self._job_with_labor_charge()
        before = get_statement(ctx["job"]["id"])
        assert before["balance_cents"] == 40000

        post_ledger_entry(ctx["job"]["id"], kind="DEPOSIT",
                          amount_cents=21250)
        mid = get_statement(ctx["job"]["id"])
        assert mid["balance_cents"] == 18750, \
            "40000 charge minus 21250 deposit"

    def test_void_restores_balance(self):
        """PRD section 2.8: "Posting then voiding the same entry leaves the
        balance unchanged."
        PRD section 2.8: "Voiding is the sole compensation mechanism: an
        `Accountant` may void a posted entry, moving it from `POSTED` to
        `VOIDED`, after which it contributes nothing to the balance or to
        statement aggregates."

        Design: Difficulty/compensating_invariant/ledger_post_void_conserves_balance
        """
        ctx = self._job_with_labor_charge()
        before = get_statement(ctx["job"]["id"])["balance_cents"]
        assert before == 40000

        entry = post_ledger_entry(ctx["job"]["id"], kind="DEPOSIT",
                                  amount_cents=21250)
        voided = validate_success(
            api_client.void_ledger_entry(entry["id"], AC))
        assert voided["status"] == "VOIDED"
        after = get_statement(ctx["job"]["id"])["balance_cents"]
        assert after == before, \
            "post + void composes to the identity on balance_cents"

    def test_charge_kind_via_api_rejected(self):
        """PRD section 2.8: "Through the API an `Accountant` may post entries
        of kind `PAYMENT`, `CREDIT`, or `DEPOSIT`; the kind `CHARGE` is
        system-created only and is rejected from API input with
        `ERR_VALIDATION`."

        Design: Corner/validations/charge_kind_via_api_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        vessel, _c = create_vessel_with_insurance(
            name="MV Chg", owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="POWER", displacement_tons=10, policy_no="POL-C3")
        job = create_submitted_job(vessel["id"])

        resp = api_client.create_ledger_entry(
            {"job_id": job["id"], "kind": "CHARGE", "amount_cents": 100},
            AC)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
