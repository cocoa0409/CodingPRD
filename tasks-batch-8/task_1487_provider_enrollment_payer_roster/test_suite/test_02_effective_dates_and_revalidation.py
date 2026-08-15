"""Enrollment effective-date policy variants and the revalidation schedule
(Medicare month-end snap vs commercial plain sum) per PRD §3.3 and §3.7."""
from test_helpers import (
    ApiErrorId,
    assert_enrollment_record,
    assert_timestamp_second,
    create_approved_application,
    create_claim,
    create_draft_application,
    create_payer_config,
    create_submitted_application,
    find_record,
    get_claim,
    set_clock,
    setup_group_provider_payer,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["enrollment_specialist_headers"]
PAYER_REP = TEST_USERS["payer_representative_headers"]


class TestEffectiveDatePolicyVariants:
    def test_approval_date_vs_retro90_diverge_on_same_inputs(self, api):
        """PRD §3.3: "Under `APPROVAL_DATE`, the effective date is simply the
        calendar day of approval; the `requested_effective_date` is ignored
        entirely. Under `RETRO_90`, the effective date is the later of the
        requested effective date and the day ninety days before the approval
        day — so identical inputs yield an earlier effective date than the
        approval-date variant whenever the requested date precedes the approval
        day."

        Design: Difficulty/dual_variant_calc/effective_date_policy_divergence
        """
        _, provider, _, _ = setup_group_provider_payer()
        payer_a = create_payer_config(
            payer_code="PA", name="Payer A", effective_date_policy="APPROVAL_DATE",
        )
        payer_b = create_payer_config(
            payer_code="PB", name="Payer B", effective_date_policy="RETRO_90",
        )
        app_a = create_submitted_application(
            provider["id"], payer_a["id"], requested_effective_date="2026-08-15",
        )
        app_b = create_submitted_application(
            provider["id"], payer_b["id"], requested_effective_date="2026-08-15",
        )

        set_clock("2026-09-01T00:00:00Z")
        validate_success(api.approve_application(app_a["id"], PAYER_REP), 200)
        validate_success(api.approve_application(app_b["id"], PAYER_REP), 200)

        rec_a = find_record(provider_id=provider["id"], payer_id=payer_a["id"])
        rec_b = find_record(provider_id=provider["id"], payer_id=payer_b["id"])
        assert_enrollment_record(rec_a)
        assert_enrollment_record(rec_b)
        assert rec_a["effective_date"] == "2026-09-01", (
            "APPROVAL_DATE: effective date is the calendar day of approval"
        )
        # RETRO_90: max(2026-08-15, 2026-09-01 - 90d = 2026-06-03) = 2026-08-15.
        assert rec_b["effective_date"] == "2026-08-15"
        assert rec_a["effective_date"] != rec_b["effective_date"]

    def test_retro90_floor_binds_when_requested_date_is_older(self, api):
        """PRD §3.3: "Under `RETRO_90`, the effective date is the later of the
        requested effective date and the day ninety days before the approval
        day — so identical inputs yield an earlier effective date than the
        approval-date variant whenever the requested date precedes the approval
        day."

        Design: Difficulty/dual_variant_calc/effective_date_policy_divergence
        """
        _, provider, _, payer = setup_group_provider_payer(
            payer_overrides={"effective_date_policy": "RETRO_90"},
        )
        # Requested 2026-05-03 is the earliest date allowed at the startup
        # clock (2026-08-01 - 90 days); approval happens at 2026-09-01.
        app = create_submitted_application(
            provider["id"], payer["id"], requested_effective_date="2026-05-03",
        )
        set_clock("2026-09-01T00:00:00Z")
        validate_success(api.approve_application(app["id"], PAYER_REP), 200)

        record = find_record(source_application_id=app["id"])
        # max(2026-05-03, 2026-09-01 - 90d = 2026-06-03) = 2026-06-03.
        assert record["effective_date"] == "2026-06-03", (
            "the ninety-days-before-approval floor binds over the older request"
        )


class TestRevalidationSchedule:
    def test_medicare_month_end_snap_vs_commercial_plain_sum(self, api):
        """PRD §3.7: "The base due date is the calendar day of the last
        completed revalidation plus the interval; for a Medicare payer — one
        whose `is_medicare` flag is true — the due date then snaps to the last
        calendar day of the month containing that base, while commercial payers
        keep the base itself."
        PRD §3.7: "The `revalidation_window_start` sits sixty days before the
        `revalidation_due_date`."

        Design: Difficulty/combinatorial_formula/medicare_revalidation_month_end_snap
        """
        _, provider, _, _ = setup_group_provider_payer()
        payer_mcr = create_payer_config(
            payer_code="MCR", name="Medicare", is_medicare=True,
            revalidation_interval_days=1825,
        )
        payer_com = create_payer_config(
            payer_code="COM", name="Commercial", is_medicare=False,
            revalidation_interval_days=200,
        )
        app_mcr = create_submitted_application(
            provider["id"], payer_mcr["id"], requested_effective_date="2026-08-10",
        )
        app_com = create_submitted_application(
            provider["id"], payer_com["id"], requested_effective_date="2026-08-10",
        )
        set_clock("2026-08-10T00:00:00Z")
        validate_success(api.approve_application(app_mcr["id"], PAYER_REP), 200)
        validate_success(api.approve_application(app_com["id"], PAYER_REP), 200)

        rec_mcr = find_record(provider_id=provider["id"], payer_id=payer_mcr["id"])
        rec_com = find_record(provider_id=provider["id"], payer_id=payer_com["id"])
        # Medicare: base 2026-08-10 + 1825d = 2031-08-09 -> month-end snap.
        assert rec_mcr["revalidation_due_date"] == "2031-08-31"
        assert rec_mcr["revalidation_window_start"] == "2031-07-02"
        # Commercial: plain 2026-08-10 + 200d, no snap.
        assert rec_com["revalidation_due_date"] == "2027-02-26"
        assert rec_com["revalidation_window_start"] == "2026-12-28"

    def test_medicare_snap_moves_due_date_past_commercial_base(self, api):
        """PRD §3.7: "The base due date is the calendar day of the last
        completed revalidation plus the interval; for a Medicare payer — one
        whose `is_medicare` flag is true — the due date then snaps to the last
        calendar day of the month containing that base, while commercial payers
        keep the base itself."

        Design: Difficulty/combinatorial_formula/medicare_revalidation_month_end_snap
        """
        _, provider, _, _ = setup_group_provider_payer()
        payer_mcr = create_payer_config(
            payer_code="MCR2", name="Medicare 200", is_medicare=True,
            revalidation_interval_days=200,
        )
        payer_com = create_payer_config(
            payer_code="COM2", name="Commercial 200", is_medicare=False,
            revalidation_interval_days=200,
        )
        app_mcr = create_submitted_application(
            provider["id"], payer_mcr["id"], requested_effective_date="2026-08-10",
        )
        app_com = create_submitted_application(
            provider["id"], payer_com["id"], requested_effective_date="2026-08-10",
        )
        set_clock("2026-08-10T00:00:00Z")
        validate_success(api.approve_application(app_mcr["id"], PAYER_REP), 200)
        validate_success(api.approve_application(app_com["id"], PAYER_REP), 200)

        rec_mcr = find_record(provider_id=provider["id"], payer_id=payer_mcr["id"])
        rec_com = find_record(provider_id=provider["id"], payer_id=payer_com["id"])
        # Identical base 2027-02-26: Medicare snaps to month end, commercial
        # keeps the base — the snap strictly moves the due date here.
        assert rec_com["revalidation_due_date"] == "2027-02-26"
        assert rec_mcr["revalidation_due_date"] == "2027-02-28"
        assert rec_mcr["revalidation_window_start"] == "2026-12-30"


class TestRecordFieldsSetOnApproval:
    def test_record_inherits_scope_benefit_source_and_revalidation_baseline(self, api):
        """PRD §3.3: "The new record starts `ACTIVE`, records the application
        as its `source_application_id`, copies the application's
        `enrollment_scope`, and sets `benefit_assignment` to `GROUP` when the
        scope is `GROUP_LINK` (benefits reassigned to the practice group) and
        to `INDIVIDUAL` otherwise."
        PRD §3.3: "Its `last_revalidation_completed_at` is the approval
        instant, and `revalidation_due_date` and `revalidation_window_start`
        are computed per the schedule in §3.7."

        Design: Corner/entities/enrollment_record_fields_set_on_approval
        """
        _, provider, _, payer = setup_group_provider_payer()
        app = create_submitted_application(
            provider["id"], payer["id"], enrollment_scope="GROUP_LINK",
            requested_effective_date="2026-08-01",
        )
        validate_success(api.approve_application(app["id"], PAYER_REP), 200)

        record = find_record(source_application_id=app["id"])
        assert_enrollment_record(record)
        assert record["enrollment_scope"] == "GROUP_LINK"
        assert record["benefit_assignment"] == "GROUP"
        assert record["source_application_id"] == app["id"]
        assert record["source_roster_line_id"] is None
        assert record["status"] == "ACTIVE"
        # Approval happened at the startup clock 2026-08-01T00:00:00Z.
        assert_timestamp_second(
            record["last_revalidation_completed_at"], "2026-08-01T00:00:00"
        )


class TestRevalidationWindowCycle:
    def test_window_entry_and_revalidate_rebases_schedule(self, api):
        """PRD §3.7: "A record still within its window — the current date on or
        after `revalidation_window_start` but not past the due date — moves
        from `ACTIVE` to `PENDING_REVALIDATION`; a record already pending stays
        put until it is revalidated or lapses into deactivation."
        PRD §3.7: "A successful revalidation returns the record to `ACTIVE`,
        stamps `last_revalidation_completed_at` from the logical clock, and
        recomputes `revalidation_due_date` and `revalidation_window_start`
        from the new baseline — the `ACTIVE → PENDING_REVALIDATION → ACTIVE`
        cycle may repeat indefinitely."

        Design: Corner/state_machines/revalidation_window_cycle_completes
        """
        _, provider, _, payer = setup_group_provider_payer()
        app = create_submitted_application(
            provider["id"], payer["id"], requested_effective_date="2026-08-10",
        )
        set_clock("2026-08-10T00:00:00Z")
        validate_success(api.approve_application(app["id"], PAYER_REP), 200)
        record = find_record(source_application_id=app["id"])
        # Interval 200: due 2027-02-26, window opens 2026-12-28.
        assert record["revalidation_due_date"] == "2027-02-26"
        assert record["revalidation_window_start"] == "2026-12-28"

        set_clock("2027-01-15T00:00:00Z")  # inside [2026-12-28, 2027-02-26]
        mid = validate_success(api.get_enrollment_record(record["id"], SPECIALIST), 200)
        assert mid["status"] == "PENDING_REVALIDATION"

        after = validate_success(
            api.revalidate_enrollment_record(record["id"], SPECIALIST), 200
        )
        assert after["status"] == "ACTIVE"
        # Rebased from 2027-01-15 + 200 days.
        assert after["revalidation_due_date"] == "2027-08-03"
        assert after["revalidation_window_start"] == "2027-06-04"

    def test_revalidate_too_early_returns_not_due(self, api):
        """PRD §3.7: "Invoked on an `ACTIVE` record whose window has not opened
        it fails with `ERR_REVALIDATION_NOT_DUE`; invoked on a `DEACTIVATED` or
        `TERMINATED` record it fails with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/validations/revalidate_too_early_returns_not_due
        """
        _, provider, _, payer = setup_group_provider_payer()
        _, record = create_approved_application(provider["id"], payer["id"])
        assert record["status"] == "ACTIVE"

        res = api.revalidate_enrollment_record(record["id"], SPECIALIST)
        validate_error(res, ApiErrorId.ERR_REVALIDATION_NOT_DUE)


class TestMissedRevalidationDeadline:
    def test_deactivation_denies_held_claims_but_not_released(self, api):
        """PRD §3.7: "A record whose due date has passed — the current logical
        date strictly later than `revalidation_due_date` — is deactivated from
        either state, moving to `DEACTIVATED`, and the deactivation cascade
        denies every `HELD` claim of the provider–payer pair with
        `denial_reason` `ENROLLMENT_DEACTIVATED`."
        PRD §3.7: "Deactivation is deliberately not retroactive: `RELEASED`
        claims are left untouched and never recouped."

        Design: Corner/state_machines/missed_revalidation_deadline_deactivates_and_denies
        """
        _, provider, _, payer = setup_group_provider_payer()
        set_clock("2026-08-10T00:00:00Z")
        # Uncovered at intake (no record yet) -> HELD.
        c_old = create_claim(
            provider["id"], payer["id"], service_date="2026-08-05", amount_cents=3000,
        )
        assert c_old["status"] == "HELD"

        app = create_submitted_application(
            provider["id"], payer["id"], requested_effective_date="2026-08-10",
        )
        validate_success(api.approve_application(app["id"], PAYER_REP), 200)
        record = find_record(source_application_id=app["id"])
        assert record["revalidation_due_date"] == "2027-02-26"

        set_clock("2026-08-20T00:00:00Z")
        c_ok = create_claim(
            provider["id"], payer["id"], service_date="2026-08-12", amount_cents=4000,
        )
        assert c_ok["status"] == "RELEASED"

        set_clock("2027-02-27T00:00:00Z")  # one day past the due date
        record_after = validate_success(
            api.get_enrollment_record(record["id"], SPECIALIST), 200
        )
        assert record_after["status"] == "DEACTIVATED"

        old_after = get_claim(c_old["id"])
        assert old_after["status"] == "DENIED"
        assert old_after["denial_reason"] == "ENROLLMENT_DEACTIVATED"
        ok_after = get_claim(c_ok["id"])
        assert ok_after["status"] == "RELEASED", "deactivation is not retroactive"
