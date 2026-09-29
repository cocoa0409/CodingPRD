"""Separation, vesting measurement and the forfeiture cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_forfeiture_event,
    assert_participant,
    assert_share_conservation,
    create_participant,
    create_plan,
    get_participant,
    get_plan,
    list_forfeiture_events,
    set_clock,
    setup_forfeited_participant,
    terminate_payload,
    terminate_participant,
    validate_error,
    validate_paginated,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _two_measurement_plans():
    """Two plans identical but for service_measurement_method, one participant each."""
    set_clock("2026-02-01T00:00:00Z", SPONSOR)
    plan_t = create_plan(plan_name="Measure-T", sponsor_name="Northgate Tooling Inc.",
                         service_measurement_method="TERMINATION_DATE_MEASURE")
    plan_y = create_plan(plan_name="Measure-Y", sponsor_name="Northgate Tooling Inc.",
                         service_measurement_method="PLAN_YEAR_END_MEASURE")
    person_t = create_participant(plan_t["id"], employee_number="E-201",
                                  date_of_birth="1985-06-10", hire_date="2021-03-01",
                                  eligible_compensation_cents=34_500_000)
    person_y = create_participant(plan_y["id"], employee_number="E-201",
                                  date_of_birth="1985-06-10", hire_date="2021-03-01",
                                  eligible_compensation_cents=34_500_000)
    return person_t, person_y


class TestServiceMeasurementVariants:
    def test_measurement_method_changes_service_years_and_vesting(self, api):
        """PRD 3.4: "The divergence is real and material: a participant hired on 2021-03-01
        and separating on 2026-01-15 has 1781 elapsed days under the termination-date method,
        which is 4 whole years and 60 percent vesting on the graded table, but 2131 elapsed
        days under the plan-year-end method, which is 5 whole years and 80 percent — a
        twenty-point difference on identical employment facts."
        PRD 3.4: "`years_of_service` is the plain count of calendar days from the `hire_date`
        to the measurement date, divided by a fixed 365 and floored to a whole year."

        Design: Difficulty/dual_variant_calc/vesting_measurement_termination_date_vs_plan_year_end
        """
        person_t, person_y = _two_measurement_plans()

        result_t = validate_success(api.terminate_participant(
            person_t["id"], terminate_payload("2026-01-15", "TERMINATION"), SPONSOR))
        result_y = validate_success(api.terminate_participant(
            person_y["id"], terminate_payload("2026-01-15", "TERMINATION"), SPONSOR))

        assert result_t["years_of_service"] == 4
        assert result_t["vested_percentage"] == 60
        assert result_y["years_of_service"] == 5
        assert result_y["vested_percentage"] == 80
        assert result_t["vested_percentage"] != result_y["vested_percentage"], (
            "the two measurement methods diverge on identical employment facts"
        )

    def test_both_measurement_variants_land_in_terminated_with_the_date_recorded(self, api):
        """PRD 3.4: "A separation for `TERMINATION` or for `DISABILITY` moves the participant
        from `ACTIVE` to `TERMINATED`."
        PRD 3.4: "Both fields are stored on the participant as `termination_date` and
        `termination_reason`, replacing the nulls they carried while active."
        PRD 3.4: "Under `TERMINATION_DATE_MEASURE`, service stops accruing on the separation
        date itself, so the measurement date is the `termination_date`. Under
        `PLAN_YEAR_END_MEASURE`, service accrues to the 31 December of the plan's current
        `plan_year`, so the measurement date is that year end."

        Design: Difficulty/dual_variant_calc/vesting_measurement_termination_date_vs_plan_year_end
        """
        person_t, person_y = _two_measurement_plans()
        terminate_participant(person_t["id"], "2026-01-15", "TERMINATION")
        terminate_participant(person_y["id"], "2026-01-15", "TERMINATION")

        after_t = get_participant(person_t["id"])
        after_y = get_participant(person_y["id"])
        assert_participant(after_t)
        assert_participant(after_y)
        assert after_t["status"] == "TERMINATED"
        assert after_y["status"] == "TERMINATED"
        assert after_t["termination_date"] == "2026-01-15"
        assert after_t["termination_reason"] == "TERMINATION"
        assert after_t["vested_shares"] == 0, "a zero share balance vests to zero shares"
        assert after_y["vested_shares"] == 0


class TestForfeitureCascade:
    def test_termination_books_a_forfeiture_and_moves_the_share_buckets(self, api):
        """PRD 3.4: "The second hop fires because the participant became `TERMINATED` while
        their measured `vested_percentage` is below 100: a forfeiture event is created,
        recording the `participant_id`, the `plan_id` for plan-scoped queries, the plan's
        `plan_year` as it stands at that moment, a `forfeited_shares` count equal to the
        participant's `allocated_shares` less their `vested_shares`, the
        `vested_percentage_at_forfeiture` and `years_of_service_at_forfeiture` that sized it,
        and `measurement_method_applied` recording which measurement variant produced those
        figures."
        PRD 3.4: "Immediately after the event is booked, both `allocated_shares` and
        `vested_shares` on the participant are set to the pre-forfeiture vested share count —
        this is the pinned exception to the generic vesting recomputation, because the unvested
        balance has physically left the account and the whole remainder is by definition
        vested, so the generic formula is not re-applied on top of that assignment."
        PRD 3.4: "The third hop follows from the second: because a forfeiture event now
        exists, the plan's `unallocated_forfeiture_shares` increases by the forfeited count
        and the plan's `allocated_shares_total` decreases by the same count."

        Design: Difficulty/transitive_cascade/termination_forfeiture_cascade_blocks_rollover_depth4
        """
        ctx = setup_forfeited_participant(
            plan_overrides={"forfeiture_sweep_threshold_shares": 100})
        participant = ctx["participant"]

        assert participant["status"] == "TERMINATED"
        assert participant["vested_percentage"] == 60
        assert participant["allocated_shares"] == 580
        assert participant["vested_shares"] == 580

        events = list_forfeiture_events(participant_id=participant["id"])
        assert len(events) == 1, "exactly one forfeiture event is booked by the separation"
        event = events[0]
        assert_forfeiture_event(event)
        assert event["forfeited_shares"] == 388
        assert event["vested_percentage_at_forfeiture"] == 60
        assert event["years_of_service_at_forfeiture"] == 4
        assert event["measurement_method_applied"] == "TERMINATION_DATE_MEASURE"
        assert event["status"] == "PENDING_REALLOCATION"
        assert event["reallocated_in_run_id"] is None
        assert event["plan_year"] == 2026

        plan = ctx["plan"]
        assert plan["unallocated_forfeiture_shares"] == 388
        assert plan["allocated_shares_total"] == 580
        assert plan["total_plan_shares"] == 968, (
            "the shares never left the trust, so total_plan_shares does not change"
        )
        assert_share_conservation(plan)

    def test_sweep_required_posture_blocks_the_year_rollover(self, api):
        """PRD 3.4: "The fourth hop follows from the third: with `unallocated_forfeiture_shares`
        now standing above the plan's `forfeiture_sweep_threshold_shares`, the plan's
        `forfeiture_posture` flips from `CLEAR` to `SWEEP_REQUIRED`. That posture is a hard
        block on the year rollover — the sponsor cannot advance the plan year while forfeited
        shares are waiting to be reallocated, and an attempt is refused with
        `ERR_FORFEITURE_SWEEP_REQUIRED`."

        Design: Difficulty/transitive_cascade/termination_forfeiture_cascade_blocks_rollover_depth4
        """
        ctx = setup_forfeited_participant(
            plan_overrides={"forfeiture_sweep_threshold_shares": 100})
        assert ctx["plan"]["forfeiture_posture"] == "SWEEP_REQUIRED"

        validate_error(api.rollover_plan(ctx["plan"]["id"], SPONSOR),
                       ApiErrorId.ERR_FORFEITURE_SWEEP_REQUIRED)

        plan = get_plan(ctx["plan"]["id"])
        assert plan["plan_year"] == 2026, "the refused rollover does not advance the plan year"
        assert plan["plan_status"] == "ALLOCATION_LOCKED"
        assert plan["forfeiture_posture"] == "SWEEP_REQUIRED"
        assert plan["total_plan_shares"] == 968
        assert_share_conservation(plan)

    def test_forfeiture_events_discoverable_only_through_reverse_lookup(self, api):
        """PRD 2.3: "Share allocations, forfeiture events, installments and participant
        statements are all created as cascade side effects rather than by a direct create
        call, so their list endpoints are the sole discovery channel for those rows."
        PRD 2.3: "Forfeiture event lists accept `participant_id`, `plan_id`,
        `reallocated_in_run_id` and `status`."

        Design: Corner/entities/forfeiture_events_discoverable_only_through_reverse_lookup
        """
        ctx = setup_forfeited_participant(plan_overrides={"plan_name": "Forfeit Lookup"})
        participant = ctx["participant"]

        rows, meta = validate_paginated(
            api.list_forfeiture_events(TRUSTEE, params={"participant_id": participant["id"]})
        )
        assert meta["total_count"] == 1 and len(rows) == 1
        forfeiture_id = rows[0]["id"]

        fetched = validate_success(api.get_forfeiture_event(forfeiture_id, TRUSTEE))
        assert fetched["participant_id"] == participant["id"]
        assert fetched["plan_id"] == ctx["plan"]["id"]
        assert fetched["forfeited_shares"] == 388
        assert fetched["plan_year"] == 2026
        assert fetched["status"] == "PENDING_REALLOCATION"
        assert fetched["reallocated_in_run_id"] is None

        _swept, swept_meta = validate_paginated(
            api.list_forfeiture_events(
                TRUSTEE, params={"reallocated_in_run_id": ctx["run"]["id"]})
        )
        assert swept_meta["total_count"] == 0, (
            "the event was booked after the run, so no run has swept it"
        )


class TestSeparationBranches:
    def test_retirement_branch_grants_full_vesting_and_creates_no_forfeiture(self, api):
        """PRD 3.4: "On the retirement branch, `vested_percentage` is forced to 100 and
        `vested_shares` is set equal to `allocated_shares`; no forfeiture event is created and
        the plan's `unallocated_forfeiture_shares` is left exactly where it was."
        PRD 3.4: "Three separation reasons override the table outright. A separation recorded
        as `RETIREMENT`, as `DEATH`, or as `DISABILITY` sets `vested_percentage` to 100
        regardless of what the service table produced."

        Design: Corner/state_machines/retirement_branch_grants_full_vesting_and_creates_no_forfeiture
        """
        ctx = setup_forfeited_participant(
            plan_overrides={"plan_name": "Retire Plan", "normal_retirement_age": 65},
            participant_overrides={"employee_number": "E-202", "date_of_birth": "1958-05-20"},
            termination_reason="RETIREMENT",
        )
        participant = ctx["participant"]

        assert participant["status"] == "RETIRED"
        assert participant["termination_reason"] == "RETIREMENT"
        assert participant["vested_percentage"] == 100
        assert participant["vested_shares"] == 968
        assert participant["allocated_shares"] == 968, "the retirement branch forfeits nothing"

        _rows, meta = validate_paginated(
            api.list_forfeiture_events(TRUSTEE, params={"participant_id": participant["id"]})
        )
        assert meta["total_count"] == 0, "no forfeiture event is created on the retirement branch"

        plan = ctx["plan"]
        assert plan["unallocated_forfeiture_shares"] == 0
        assert plan["forfeiture_posture"] == "CLEAR"
        assert plan["allocated_shares_total"] == 968

    def test_retirement_before_normal_retirement_age_rejected(self, api):
        """PRD 3.4: "A separation for `RETIREMENT` moves them from `ACTIVE` to `RETIRED`, and
        it carries an age gate: the participant's whole-year age on the `termination_date`
        must have reached the plan's `normal_retirement_age`, and a retirement recorded before
        that age is refused with `ERR_RETIREMENT_AGE_NOT_ATTAINED`."

        Design: Corner/state_machines/retirement_before_normal_retirement_age_rejected
        """
        set_clock("2026-02-01T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Young Retire", sponsor_name="Corner Corp",
                           normal_retirement_age=65)
        participant = create_participant(plan["id"], employee_number="E-003",
                                         date_of_birth="1990-02-14", hire_date="2019-03-15",
                                         eligible_compensation_cents=10_000_000)

        validate_error(
            api.terminate_participant(participant["id"],
                                      terminate_payload("2026-01-15", "RETIREMENT"), SPONSOR),
            ApiErrorId.ERR_RETIREMENT_AGE_NOT_ATTAINED,
        )
        refused = get_participant(participant["id"])
        assert refused["status"] == "ACTIVE", "the refused retirement leaves the owner active"
        assert refused["termination_date"] is None

        accepted = validate_success(api.terminate_participant(
            participant["id"], terminate_payload("2026-01-15", "TERMINATION"), SPONSOR))
        assert accepted["status"] == "TERMINATED", (
            "the same date is acceptable under a plain TERMINATION, which has no age gate"
        )

    def test_terminate_an_already_terminated_participant_returns_invalid_state(self, api):
        """PRD 3.4: "Separations are recorded by the `PlanSponsor` against a participant who
        is still `ACTIVE`, on a plan that is not frozen, by supplying a `termination_date` and
        a `termination_reason`."
        PRD 2.12: "Target state — the target resource is in a state from which the requested
        transition is declared, else `ERR_INVALID_STATE` (409). Applies to every action
        endpoint, including every repeat of an already-applied action."

        Design: Corner/state_machines/terminate_an_already_terminated_participant_returns_invalid_state
        """
        set_clock("2026-02-01T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Double Term", sponsor_name="Corner Corp")
        participant = create_participant(plan["id"], employee_number="E-204",
                                         date_of_birth="1985-06-10", hire_date="2021-03-01",
                                         eligible_compensation_cents=34_500_000)
        terminate_participant(participant["id"], "2026-01-15", "TERMINATION")

        validate_error(
            api.terminate_participant(participant["id"],
                                      terminate_payload("2026-01-20", "DEATH"), SPONSOR),
            ApiErrorId.ERR_INVALID_STATE,
        )
        after = get_participant(participant["id"])
        assert after["status"] == "TERMINATED", "the second separation is not applied"
        assert after["termination_date"] == "2026-01-15"
        assert after["termination_reason"] == "TERMINATION"
