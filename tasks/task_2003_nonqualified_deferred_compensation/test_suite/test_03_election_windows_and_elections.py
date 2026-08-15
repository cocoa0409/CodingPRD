"""Election windows and deferral elections: overlap geometry, window gates,
deadlines, locking/expiry, caps, and list filters.

PRD §3.2 (Election Windows and Deferral Elections), §2.10 (interval semantics).
"""
from test_helpers import (
    TEST_USERS,
    add_fund,
    add_window,
    advance_clock,
    create_active_plan,
    create_election,
    create_election_window_payload,
    create_plan,
    enroll_participant,
    get_election,
    get_election_window,
    get_plan,
    make_participant_headers,
    plan_version,
    setup_plan_fund_window,
    submit_election,
    validate_error,
    validate_paginated,
    validate_success,
)

PS = TEST_USERS["plan_sponsor_headers"]
BA = TEST_USERS["benefits_admin_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestWindowOverlap:
    def test_window_overlap_touching_conflicts_disjoint_accepted(self, api):
        """PRD §2.10: "Election windows of the same plan use **closed-interval**
        semantics: two windows conflict unless one closes strictly before the
        other opens. Windows that merely touch — one window's close date equal
        to another's open date — do conflict, and the second window's creation
        is rejected with `ERR_WINDOW_OVERLAP`."

        Window A [2026-10-01, 2026-12-31]; a touching window opening 2026-12-31
        conflicts, while a window opening 2027-01-01 is accepted.

        Design: Difficulty/resource_temporal_overlap/window_overlap_closed_interval_touching_conflict
        """
        plan = create_active_plan(name="Plan WO", distribution_events_allowed=["SEPARATION"])
        window_a = add_window(plan["id"], plan_year=2027,
                              general_open_date="2026-10-01", general_close_date="2026-12-31")
        assert window_a["status"] == "SCHEDULED"

        touching = api.create_election_window(create_election_window_payload(
            plan["id"], plan_version(plan["id"]), plan_year=2028,
            general_open_date="2026-12-31", general_close_date="2027-12-31"), PS)
        validate_error(touching, "ERR_WINDOW_OVERLAP", expected_status=409)

        disjoint = validate_success(api.create_election_window(create_election_window_payload(
            plan["id"], plan_version(plan["id"]), plan_year=2028,
            general_open_date="2027-01-01", general_close_date="2027-12-31"), PS), 201)
        assert disjoint["status"] == "SCHEDULED"

        rows, meta = validate_paginated(api.list_election_windows(PS, params={"plan_id": plan["id"]}))
        assert meta["total_count"] == 2
        assert {w["id"] for w in rows} == {window_a["id"], disjoint["id"]}

    def test_window_overlap_strict_overlap_and_cross_plan_independence(self, api):
        """PRD §2.10: "Election windows of the same plan use **closed-interval**
        semantics: two windows conflict unless one closes strictly before the
        other opens."

        A window strictly inside window A's interval conflicts; an identical
        date range on a DIFFERENT plan does not (the rule is per-plan).

        Design: Difficulty/resource_temporal_overlap/window_overlap_closed_interval_touching_conflict
        """
        plan_a = create_active_plan(name="Plan WO-A", distribution_events_allowed=["SEPARATION"])
        add_window(plan_a["id"], plan_year=2027,
                   general_open_date="2026-10-01", general_close_date="2026-12-31")
        plan_b = create_active_plan(name="Plan WO-B", distribution_events_allowed=["SEPARATION"])

        inside = api.create_election_window(create_election_window_payload(
            plan_a["id"], plan_version(plan_a["id"]), plan_year=2027,
            general_open_date="2026-11-01", general_close_date="2026-12-15"), PS)
        validate_error(inside, "ERR_WINDOW_OVERLAP", expected_status=409)

        other_plan = validate_success(api.create_election_window(create_election_window_payload(
            plan_b["id"], plan_version(plan_b["id"]), plan_year=2027,
            general_open_date="2026-10-01", general_close_date="2026-12-31"), PS), 201)
        assert other_plan["plan_id"] == plan_b["id"]


class TestElectionWindowGate:
    def test_election_create_gated_by_window_open(self, api):
        """PRD §3.2: "A `GENERAL` election may only be created while its window
        is `OPEN` (`ERR_WINDOW_NOT_OPEN`)."
        PRD §3.2: "When the logical clock date reaches `general_open_date`, the
        sweep moves the window from `SCHEDULED` to `OPEN`".

        Design: Difficulty/cross_entity_state_dependency/election_create_gated_by_window_open
        """
        ctx = setup_plan_fund_window(
            plan_overrides={"name": "Plan GW", "distribution_events_allowed": ["SEPARATION"]})
        participant = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-GW")
        assert ctx["window"]["status"] == "SCHEDULED"

        blocked = api.create_deferral_election({
            "participant_id": participant["id"],
            "election_window_id": ctx["window"]["id"],
            "election_type": "GENERAL",
            "deferral_percent_bp": 5000,
            "notional_fund_id": ctx["fund"]["id"],
        }, make_participant_headers(participant["id"]))
        validate_error(blocked, "ERR_WINDOW_NOT_OPEN", expected_status=409)

        advance_clock("2026-10-01T00:00:00Z")
        assert get_election_window(ctx["window"]["id"])["status"] == "OPEN"

        election = validate_success(api.create_deferral_election({
            "participant_id": participant["id"],
            "election_window_id": ctx["window"]["id"],
            "election_type": "GENERAL",
            "deferral_percent_bp": 5000,
            "notional_fund_id": ctx["fund"]["id"],
        }, make_participant_headers(participant["id"])), 201)
        assert election["status"] == "DRAFT"

    def test_election_create_gated_by_window_closed(self, api):
        """PRD §3.2: "A `GENERAL` election may only be created while its window
        is `OPEN` (`ERR_WINDOW_NOT_OPEN`)."
        PRD §3.2: "when the clock date passes `general_close_date`, the sweep
        moves it from `OPEN` to its terminal `CLOSED` state."

        Design: Difficulty/cross_entity_state_dependency/election_create_gated_by_window_open
        """
        ctx = setup_plan_fund_window(
            plan_overrides={"name": "Plan GC", "distribution_events_allowed": ["SEPARATION"]})
        participant = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-GC")

        advance_clock("2027-01-01T00:00:00Z")  # past general_close_date 2026-12-31
        assert get_election_window(ctx["window"]["id"])["status"] == "CLOSED"

        blocked = api.create_deferral_election({
            "participant_id": participant["id"],
            "election_window_id": ctx["window"]["id"],
            "election_type": "GENERAL",
            "deferral_percent_bp": 5000,
            "notional_fund_id": ctx["fund"]["id"],
        }, make_participant_headers(participant["id"]))
        validate_error(blocked, "ERR_WINDOW_NOT_OPEN", expected_status=409)


class TestWindowCloseAndLock:
    def test_window_close_locks_submitted_and_expires_draft(self, api):
        """PRD §3.2: "Closing is consequential for elections: every `GENERAL`
        deferral election referencing the window that is still in `DRAFT` is
        expired to `EXPIRED`, and every such election in `SUBMITTED` is locked —
        moved to `LOCKED` with `locked_at` stamped at the clock timestamp,
        irrevocable from that instant."

        Design: Corner/state_machines/window_close_locks_submitted_and_expires_draft
        """
        ctx = setup_plan_fund_window(
            plan_overrides={"name": "Plan WC", "distribution_events_allowed": ["SEPARATION"]})
        p1 = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-W1")
        p2 = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-W2")

        advance_clock("2026-10-15T00:00:00Z")
        e1 = create_election(p1["id"], ctx["window"]["id"], ctx["fund"]["id"],
                             deferral_percent_bp=5000)
        submit_election(e1["id"], p1["id"])
        e2 = create_election(p2["id"], ctx["window"]["id"], ctx["fund"]["id"],
                             deferral_percent_bp=2500)
        assert get_election(e2["id"])["status"] == "DRAFT"

        advance_clock("2027-01-01T00:00:00Z")  # closes the window
        window = get_election_window(ctx["window"]["id"])
        assert window["status"] == "CLOSED"

        e1_after = get_election(e1["id"])
        assert e1_after["status"] == "LOCKED"
        assert e1_after["locked_at"] is not None
        assert str(e1_after["locked_at"]).startswith("2027-01-01T00:00:00"), (
            "locked_at is stamped at the clock timestamp"
        )
        assert get_election(e2["id"])["status"] == "EXPIRED"

    def test_election_void_after_lock_rejected(self, api):
        """PRD §3.2: "An election that has not yet locked may be retracted:
        voiding moves an election from `DRAFT` or `SUBMITTED` to `VOIDED`, and
        any attempt to void from a later state is rejected with
        `ERR_ELECTION_NOT_MODIFIABLE`."

        Design: Corner/state_machines/election_void_after_lock_rejected
        """
        ctx = setup_plan_fund_window(
            plan_overrides={"name": "Plan VL", "distribution_events_allowed": ["SEPARATION"]})
        participant = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-VL")
        advance_clock("2026-10-15T00:00:00Z")
        election = create_election(participant["id"], ctx["window"]["id"], ctx["fund"]["id"])
        submit_election(election["id"], participant["id"])
        advance_clock("2027-01-01T00:00:00Z")  # LOCKED

        res = api.void_election(election["id"], make_participant_headers(participant["id"]))
        validate_error(res, "ERR_ELECTION_NOT_MODIFIABLE", expected_status=409)

        after = get_election(election["id"])
        assert after["status"] == "LOCKED"
        assert str(after["locked_at"]).startswith("2027-01-01T00:00:00")


class TestNewlyEligibleDeadline:
    def _ne_window_setup(self, api):
        ctx = setup_plan_fund_window(
            plan_overrides={"name": "Plan ED", "distribution_events_allowed": ["SEPARATION"]},
            window_overrides={"plan_year": 2026, "general_open_date": "2025-10-01",
                              "general_close_date": "2025-12-31"})
        return ctx

    def test_newly_eligible_deadline_inclusive_and_prorated_cap(self, api):
        """PRD §3.2: "A `NEWLY_ELIGIBLE` election may be created and submitted no
        later than thirty days after the participant's `initial_eligibility_date`,
        inclusive of that thirtieth day (`ERR_ELECTION_DEADLINE_PASSED`)."
        PRD §3.2: "For a `NEWLY_ELIGIBLE` election the cap is prorated to the
        remaining days of the plan year in a pinned two-step order: first count
        the remaining days as the number of days from the submission date through
        December 31 of the window's `plan_year`, inclusive of both ends (that is,
        the difference in days plus one); then round down the prorated
        compensation — `annual_compensation_cents` multiplied by those remaining
        days and divided by 365; and only then round down the product of that
        prorated compensation and `deferral_percent_bp` divided by 10000."

        P1 (eligibility 2026-07-02, deadline 2026-08-01 == startup clock) may
        create+submit at the boundary: cap = floor(floor(30000000*153/365) *
        5000/10000) = 6287671. P2 (eligibility 2026-06-30, deadline 2026-07-30)
        is already late at the startup clock.

        Design: Difficulty/boundary_precision_check/election_submit_deadline_inclusive_timestamp
        """
        ctx = self._ne_window_setup(api)
        p1 = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-P1",
                                hire_date="2024-01-02", initial_eligibility_date="2026-07-02")
        p2 = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-P2",
                                hire_date="2024-01-02", initial_eligibility_date="2026-06-30")

        e1 = validate_success(api.create_deferral_election({
            "participant_id": p1["id"], "election_window_id": ctx["window"]["id"],
            "election_type": "NEWLY_ELIGIBLE", "deferral_percent_bp": 5000,
            "notional_fund_id": ctx["fund"]["id"],
        }, make_participant_headers(p1["id"])), 201)
        submitted = validate_success(
            api.submit_election(e1["id"], make_participant_headers(p1["id"])), 200)
        assert submitted["status"] == "SUBMITTED", "deadline date 2026-08-01 is inclusive"
        assert submitted["elected_cap_cents"] == 6287671, (
            "floor(30000000*153/365)=12575342 prorated comp, then floor(*5000/10000)"
        )

        blocked = api.create_deferral_election({
            "participant_id": p2["id"], "election_window_id": ctx["window"]["id"],
            "election_type": "NEWLY_ELIGIBLE", "deferral_percent_bp": 5000,
            "notional_fund_id": ctx["fund"]["id"],
        }, make_participant_headers(p2["id"]))
        validate_error(blocked, "ERR_ELECTION_DEADLINE_PASSED", expected_status=422)

        rows, meta = validate_paginated(
            api.list_deferral_elections(BA, params={"participant_id": p2["id"]}))
        assert meta["total_count"] == 0, "rejected creation leaves no election row"

    def test_newly_eligible_prorated_cap_second_data_point(self, api):
        """PRD §3.2: "For a `NEWLY_ELIGIBLE` election the cap is prorated to the
        remaining days of the plan year in a pinned two-step order: first count
        the remaining days as the number of days from the submission date through
        December 31 of the window's `plan_year`, inclusive of both ends (that is,
        the difference in days plus one); then round down the prorated
        compensation — `annual_compensation_cents` multiplied by those remaining
        days and divided by 365; and only then round down the product of that
        prorated compensation and `deferral_percent_bp` divided by 10000."

        At submission date 2026-08-02 the remaining-days count is 152, so the
        cap is floor(floor(30000000*152/365) * 5000/10000) = 6246575 — the
        pinned order at a second point of the same formula.

        Design: Difficulty/boundary_precision_check/election_submit_deadline_inclusive_timestamp
        """
        ctx = self._ne_window_setup(api)
        p3 = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-P3",
                                hire_date="2024-01-02", initial_eligibility_date="2026-07-03")
        e3 = validate_success(api.create_deferral_election({
            "participant_id": p3["id"], "election_window_id": ctx["window"]["id"],
            "election_type": "NEWLY_ELIGIBLE", "deferral_percent_bp": 5000,
            "notional_fund_id": ctx["fund"]["id"],
        }, make_participant_headers(p3["id"])), 201)

        advance_clock("2026-08-02T00:00:00Z")  # deadline (2026-07-03 + 30d), inclusive
        submitted = validate_success(
            api.submit_election(e3["id"], make_participant_headers(p3["id"])), 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["elected_cap_cents"] == 6246575, (
            "floor(30000000*152/365)=12493150, then floor(*5000/10000)=6246575"
        )


class TestPerformanceElectionCutoff:
    def test_performance_election_six_month_cutoff(self, api):
        """PRD §3.2: "A `PERFORMANCE` election may be created and submitted no
        later than six calendar months before the window's
        `performance_period_end`, inclusive of that boundary date
        (`ERR_PERFORMANCE_ELECTION_TOO_LATE`)."
        PRD §3.2: "For `GENERAL` and `PERFORMANCE` elections the cap is the
        participant's `annual_compensation_cents` multiplied by
        `deferral_percent_bp` and divided by 10000, rounded down to a whole
        cent."

        Performance period 2027-01-01..2028-01-01 -> cutoff 2027-07-01:
        create+submit on the cutoff succeed (cap 7500000, unprorated branch);
        one day later creation is rejected. The period is chosen as a 365-day
        difference so it satisfies the "span at least 365 days" rule under any
        interval-semantics reading, and the cutoff lands on the 1st so no
        month-end clamping convention is exercised.

        Design: Corner/validations/performance_election_six_month_cutoff
        """
        ctx = setup_plan_fund_window(
            plan_overrides={"name": "Plan PF", "distribution_events_allowed": ["SEPARATION"]},
            window_overrides={"performance_period_start": "2027-01-01",
                              "performance_period_end": "2028-01-01"})
        p1 = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-PF1")
        p2 = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-PF2")

        advance_clock("2027-07-01T12:00:00Z")  # exactly the six-month cutoff
        e1 = validate_success(api.create_deferral_election({
            "participant_id": p1["id"], "election_window_id": ctx["window"]["id"],
            "election_type": "PERFORMANCE", "deferral_percent_bp": 2500,
            "notional_fund_id": ctx["fund"]["id"],
        }, make_participant_headers(p1["id"])), 201)
        submitted = validate_success(
            api.submit_election(e1["id"], make_participant_headers(p1["id"])), 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["elected_cap_cents"] == 7500000, (
            "floor(30000000*2500/10000); PERFORMANCE uses the unprorated branch"
        )

        advance_clock("2027-07-02T00:00:00Z")
        blocked = api.create_deferral_election({
            "participant_id": p2["id"], "election_window_id": ctx["window"]["id"],
            "election_type": "PERFORMANCE", "deferral_percent_bp": 2500,
            "notional_fund_id": ctx["fund"]["id"],
        }, make_participant_headers(p2["id"]))
        validate_error(blocked, "ERR_PERFORMANCE_ELECTION_TOO_LATE", expected_status=422)


class TestStateBeatsTemporalOnSubmit:
    def test_state_error_beats_temporal_error_on_locked_submit(self, api):
        """PRD §2.8: "Every request passes through a single ordered validation
        pipeline, and the order is observable when several violations coincide."
        PRD §2.8 stage 7 (state gates) names "election modifiability
        (`ERR_ELECTION_NOT_MODIFIABLE`)" ahead of stage 9 (temporal deadlines)
        naming "Election deadlines (`ERR_ELECTION_DEADLINE_PASSED`,
        `ERR_PERFORMANCE_ELECTION_TOO_LATE`)".
        PRD §3.2: "Only a `DRAFT` election may be submitted — any other source
        state is rejected with `ERR_ELECTION_NOT_MODIFIABLE`".

        After the window closes the election is LOCKED (state violation for
        submit) AND the general deadline has passed (temporal violation); the
        state gate wins.

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_temporal_error_on_locked_submit
        """
        ctx = setup_plan_fund_window(
            plan_overrides={"name": "Plan PP", "distribution_events_allowed": ["SEPARATION"]})
        participant = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-PP")
        advance_clock("2026-10-15T00:00:00Z")
        election = create_election(participant["id"], ctx["window"]["id"], ctx["fund"]["id"])
        submit_election(election["id"], participant["id"])
        advance_clock("2027-01-01T00:00:00Z")  # LOCKED + deadline passed

        res = api.submit_election(election["id"], make_participant_headers(participant["id"]))
        validate_error(res, "ERR_ELECTION_NOT_MODIFIABLE", expected_status=409)
        assert get_election(election["id"])["status"] == "LOCKED", "election unchanged"

    def test_state_error_beats_temporal_error_on_expired_submit(self, api):
        """PRD §3.2: "Elections still sitting in `DRAFT` when their type-specific
        deadline passes are instead expired to `EXPIRED` by the sweep."
        PRD §3.2: "Only a `DRAFT` election may be submitted — any other source
        state is rejected with `ERR_ELECTION_NOT_MODIFIABLE`".

        The same priority pair on the other branch: a DRAFT election is swept
        to EXPIRED at the deadline, so the late submit reports the state error,
        not ERR_ELECTION_DEADLINE_PASSED.

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_temporal_error_on_locked_submit
        """
        ctx = setup_plan_fund_window(
            plan_overrides={"name": "Plan PP2", "distribution_events_allowed": ["SEPARATION"]})
        participant = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-PP2")
        advance_clock("2026-10-15T00:00:00Z")
        election = create_election(participant["id"], ctx["window"]["id"], ctx["fund"]["id"])
        advance_clock("2027-01-01T00:00:00Z")  # DRAFT -> EXPIRED sweep

        assert get_election(election["id"])["status"] == "EXPIRED"
        res = api.submit_election(election["id"], make_participant_headers(participant["id"]))
        validate_error(res, "ERR_ELECTION_NOT_MODIFIABLE", expected_status=409)
        assert get_election(election["id"])["status"] == "EXPIRED"


class TestElectionListFilters:
    def test_elections_list_filter_by_participant(self, api):
        """PRD §3.2: "The election list view accepts `participant_id`,
        `election_window_id`, `notional_fund_id`, and `plan_id` as optional
        filters."

        Design: Corner/endpoints/elections_list_filter_by_participant
        """
        ctx = setup_plan_fund_window(
            plan_overrides={"name": "Plan LF", "distribution_events_allowed": ["SEPARATION"]})
        p1 = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-L1")
        p2 = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-L2")
        advance_clock("2026-10-15T00:00:00Z")
        e1 = create_election(p1["id"], ctx["window"]["id"], ctx["fund"]["id"],
                             deferral_percent_bp=5000)
        e2 = create_election(p2["id"], ctx["window"]["id"], ctx["fund"]["id"],
                             deferral_percent_bp=2500)

        rows, meta = validate_paginated(
            api.list_deferral_elections(BA, params={"participant_id": p1["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == e1["id"]

        rows, meta = validate_paginated(
            api.list_deferral_elections(BA, params={"participant_id": p2["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == e2["id"]

        rows, meta = validate_paginated(
            api.list_deferral_elections(BA, params={"election_window_id": ctx["window"]["id"]}))
        assert meta["total_count"] == 2
        assert {r["id"] for r in rows} == {e1["id"], e2["id"]}
