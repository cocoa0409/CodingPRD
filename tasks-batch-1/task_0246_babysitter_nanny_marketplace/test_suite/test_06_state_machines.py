"""Interview fork-join branching, background-check adjudication transitions
(CLEAR side effects, CONSIDER re-run loop, terminal lockdown), invalid session
transitions, declined-booking terminal lockdown, and the two OCC stale-version
guards.

Translates the non_linear_state_machine interview instance, corner
state_machines instances, and the cross_cutting OCC instances.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    set_clock, create_family, create_caregiver, create_cleared_available_caregiver,
    create_open_posting, offer_booking, confirm_booking, first_session,
    open_backup_request, clear_background_check,
    make_family_headers, make_caregiver_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


class TestInterviewForkJoin:
    """non_linear_state_machine / interview_branching_forkjoin_scheduled_to_three_outcomes."""

    def _trial_booked_interview(self, suffix):
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=10000, num_children=1,
                            required_tier="BASIC", email=f"fork-{suffix}@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email=f"forkcg-{suffix}@x.com")
        posting = create_open_posting(fam["id"], care_type="RECURRING",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        interview = get_success_data(api_client.create_interview(
            {"job_posting_id": posting["id"], "family_id": fam["id"],
             "caregiver_id": cg["id"], "scheduled_start": "2026-03-10T15:00:00Z",
             "scheduled_end": "2026-03-10T16:00:00Z", "kind": "TRIAL"},
            make_family_headers(fam["id"])))
        get_success_data(api_client.decide_interview(
            interview["id"], {"outcome": "TRIAL_BOOKED"}, make_family_headers(fam["id"])))
        return fam, interview

    def test_trial_booked_then_passed(self, api):
        """PRD §3.3: "From `SCHEDULED`, a decision can fork three ways: to
        `PASSED`, to `FAILED`, or — only when the interview's `kind` is `TRIAL` —
        to `TRIAL_BOOKED`. An interview already in `TRIAL_BOOKED` can subsequently
        be decided to either `PASSED` or `FAILED`."

        SCHEDULED → TRIAL_BOOKED → PASSED.

        Design: Difficulty/non_linear_state_machine/interview_branching_forkjoin_scheduled_to_three_outcomes
        """
        fam, interview = self._trial_booked_interview("a")
        decided = validate_success(api.decide_interview(
            interview["id"], {"outcome": "PASSED"}, make_family_headers(fam["id"])), 200)
        assert decided["status"] == "PASSED"

    def test_trial_booked_is_intermediate_state(self, api):
        """PRD §3.3: "to `TRIAL_BOOKED` ... An interview already in `TRIAL_BOOKED`
        can subsequently be decided to either `PASSED` or `FAILED`."

        Confirms the interview is parked in TRIAL_BOOKED before the join.

        Design: Difficulty/non_linear_state_machine/interview_branching_forkjoin_scheduled_to_three_outcomes
        """
        fam, interview = self._trial_booked_interview("b")
        current = validate_success(api.get_interview(interview["id"], ADMIN), 200)
        assert current["status"] == "TRIAL_BOOKED"
        decided = validate_success(api.decide_interview(
            interview["id"], {"outcome": "FAILED"}, make_family_headers(fam["id"])), 200)
        assert decided["status"] == "FAILED"


class TestBackgroundCheckTransitions:
    """Corner state_machines: CLEAR side effect, CONSIDER re-run, terminal lockdown."""

    def test_clear_adjudication_sets_tier_and_status(self, api):
        """PRD §3.2: "A decision of CLEAR moves the check to `CLEAR` (a terminal
        outcome): it stamps `cleared_at` with the current clock, sets the
        caregiver's `verification_status` to `CLEAR`, and raises the caregiver's
        `background_check_tier` to the greater of its current value and the
        check's `requested_tier` under the tier order".

        STANDARD check cleared → caregiver verification CLEAR, tier STANDARD.

        Design: Corner/state_machines/clear_adjudication_sets_caregiver_tier_and_status
        """
        set_clock("2026-03-01T00:00:00Z")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="ela@x.com")
        bc = get_success_data(api.create_background_check(
            {"caregiver_id": cg["id"], "requested_tier": "STANDARD"}, ADMIN))
        api.start_background_check(bc["id"], ADMIN)
        check = validate_success(api.adjudicate_background_check(
            bc["id"], {"decision": "CLEAR"}, ADMIN), 200)
        assert check["status"] == "CLEAR"
        caregiver = validate_success(api.get_caregiver(cg["id"], ADMIN), 200)
        assert caregiver["verification_status"] == "CLEAR"
        assert caregiver["background_check_tier"] == "STANDARD"

    def test_consider_then_rerun_reverts_to_in_progress(self, api):
        """PRD §3.2: "A decision of CONSIDER moves the check to the non-terminal
        `CONSIDER` state and sets `verification_status` to `CONSIDER`; from there
        the platform may re-run the check, which transitions `CONSIDER` back to
        `IN_PROGRESS` and resets `verification_status` to `PENDING`, forming a
        review-and-rerun loop."

        Design: Corner/state_machines/consider_then_rerun_revert_loop_to_in_progress
        """
        set_clock("2026-03-01T00:00:00Z")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="fox@x.com")
        bc = get_success_data(api.create_background_check(
            {"caregiver_id": cg["id"], "requested_tier": "BASIC"}, ADMIN))
        api.start_background_check(bc["id"], ADMIN)
        get_success_data(api.adjudicate_background_check(
            bc["id"], {"decision": "CONSIDER"}, ADMIN))
        rerun = validate_success(api.start_background_check(bc["id"], ADMIN), 200)
        assert rerun["status"] == "IN_PROGRESS"
        caregiver = validate_success(api.get_caregiver(cg["id"], ADMIN), 200)
        assert caregiver["verification_status"] == "PENDING"

    def test_clear_check_is_terminal(self, api):
        """PRD §3.2: "A decision of CLEAR moves the check to `CLEAR` (a terminal
        outcome) ... Each adjudication transition is rejected with
        `ERR_INVALID_STATE` if the check is not in the state the decision
        requires."

        Re-adjudicating a CLEAR (terminal) check → ERR_INVALID_STATE.

        Design: Corner/state_machines/clear_check_is_terminal_no_further_adjudication
        """
        set_clock("2026-03-01T00:00:00Z")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="gem@x.com")
        bc = get_success_data(api.create_background_check(
            {"caregiver_id": cg["id"], "requested_tier": "BASIC"}, ADMIN))
        api.start_background_check(bc["id"], ADMIN)
        get_success_data(api.adjudicate_background_check(
            bc["id"], {"decision": "CLEAR"}, ADMIN))
        res = api.adjudicate_background_check(bc["id"], {"decision": "FLAGGED"}, ADMIN)
        validate_error(res, "ERR_INVALID_STATE")


class TestInvalidTransitions:
    """Corner state_machines: declined booking terminal, clock-out from SCHEDULED."""

    def test_decline_already_declined_booking_rejected(self, api):
        """PRD §3.4: "At any point while the booking is in `OFFERED` or
        `COUNTERED`, the caregiver may decline it outright, moving it to the
        terminal `DECLINED` state."
        PRD §2.10: "For a state-changing endpoint, the target's eligibility for
        the requested transition comes fourth (`ERR_INVALID_STATE`)."

        Second decline of a DECLINED (terminal) booking → ERR_INVALID_STATE.

        Design: Corner/state_machines/decline_booking_from_declined_returns_invalid_state
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=50000, num_children=1,
                            required_tier="BASIC", email="dl@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="dlcg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-20T08:00:00Z",
                                scheduled_end="2026-03-20T12:00:00Z")
        get_success_data(api.decline_booking(booking["id"], make_caregiver_headers(cg["id"])))
        res = api.decline_booking(booking["id"], make_caregiver_headers(cg["id"]))
        validate_error(res, "ERR_INVALID_STATE")

    def test_clock_out_scheduled_session_rejected(self, api):
        """PRD §3.7: "The caregiver later clocks out an `IN_PROGRESS` session,
        which moves it to `COMPLETED`."
        PRD §2.10: "For a state-changing endpoint, the target's eligibility for
        the requested transition comes fourth (`ERR_INVALID_STATE`)."

        Clock-out on a never-clocked-in (SCHEDULED) session → ERR_INVALID_STATE.

        Design: Corner/state_machines/clockout_from_scheduled_session_returns_invalid_state
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100000, num_children=1,
                            required_tier="BASIC", email="cs@x.com")
        cg = create_cleared_available_caregiver(tier="BASIC", email="cscg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-20T08:00:00Z",
                                scheduled_end="2026-03-20T12:00:00Z")
        booking = confirm_booking(booking["id"], cg["id"])
        session = first_session(booking["id"])
        res = api.clock_out(session["id"], make_caregiver_headers(cg["id"]))
        validate_error(res, "ERR_INVALID_STATE")


class TestOccStaleVersion:
    """Corner cross_cutting: OCC stale-version on backup match and booking counter."""

    def test_stale_version_on_backup_match_rejected(self, api):
        """PRD §2.8: "When the platform matches a caregiver to a backup care
        request, the request must carry `expected_backuprequest_version` holding
        the `version` of the target `BackupCareRequest` that the client last
        observed. A backup request may be matched at most once; if its `version`
        has advanced since the client last read it, the match is rejected with
        `ERR_STALE_VERSION` (HTTP 412)".

        A second match carrying the original (pre-match) version is rejected. Per
        PRD §2.10 the eligibility-state check (`ERR_INVALID_STATE`, priority 4)
        precedes the stale-version check (`ERR_STALE_VERSION`, priority 5); and
        because matching is the only version-bumping write on a BackupCareRequest
        and it moves the request OPEN→MATCHED, any advanced version is necessarily
        also a non-OPEN (non-matchable) state. A faithful implementer therefore
        surfaces either error — both are PRD-permitted for this construction.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_backup_match
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=50000, num_children=1,
                            required_tier="BASIC", email="oc@x.com")
        cg = create_cleared_available_caregiver(tier="BASIC", email="occg@x.com")
        req = open_backup_request(fam["id"], needed_start="2026-03-05T08:00:00Z",
                                  needed_end="2026-03-05T12:00:00Z",
                                  required_tier="BASIC", max_rate_cents=3000)
        stale_v = req["version"]
        get_success_data(api.match_backup_request(
            req["id"], {"expected_backuprequest_version": stale_v}, ADMIN))
        res = api.match_backup_request(
            req["id"], {"expected_backuprequest_version": stale_v}, ADMIN)
        validate_error_is_one_of(res, ["ERR_STALE_VERSION", "ERR_INVALID_STATE"])

    def test_stale_version_on_booking_counter_rejected(self, api):
        """PRD §2.8: "When a counter-offer is posted against a booking, the request
        must carry `expected_booking_version` holding the `version` of the target
        `Booking` that the client last observed. If another writer has advanced
        the booking's `version` since the client read it, the counter is rejected
        with `ERR_STALE_VERSION` (HTTP 412) rather than overwriting the latest
        round".

        A counter carrying the original version after a first counter advanced it
        → 412 ERR_STALE_VERSION.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_booking_counter
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100000, num_children=1,
                            required_tier="BASIC", email="ocb@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="ocbcg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-20T08:00:00Z",
                                scheduled_end="2026-03-20T12:00:00Z")
        v0 = booking["version"]
        get_success_data(api.counter_booking(
            booking["id"], {"agreed_rate_cents": 2500, "expected_booking_version": v0},
            make_caregiver_headers(cg["id"])))
        res = api.counter_booking(
            booking["id"], {"agreed_rate_cents": 2300, "expected_booking_version": v0},
            make_family_headers(fam["id"]))
        validate_error(res, "ERR_STALE_VERSION")
