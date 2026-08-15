"""Injury care continuum and physician referrals (PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    begin_care,
    complete_referral,
    create_athlete_as_trainer,
    create_injury_for,
    create_referral_for,
    create_rtp_protocol,
    make_nurse,
    make_physician,
    make_trainer,
    record_baseline,
    schedule_referral,
    set_clock,
    setup_athlete_with_rtp,
    setup_cleared_athlete,
    trainer_headers,
    validate_error,
    validate_success,
)


def _posture(trainer, athlete_id):
    return validate_success(api_client.get_athlete_clearance(
        athlete_id, trainer_headers(trainer)))["participation_posture"]


class TestInjuryLifecycle:

    def test_reopen_cycle_close_window_and_terminal_lockdown(self):
        """PRD §3.5: "If symptoms recur, a trainer **reopens** the injury —
        supplying a free-text `reason` — moving it from `RESOLVED` back to
        `OPEN`, clearing `resolved_at` to null, and recomputing the posture
        back into hold territory."
        PRD §3.5: "the trainer **closes** the injury once the clock has
        reached thirty days past `resolved_at`; the boundary is inclusive,
        and an earlier attempt is rejected with `ERR_CLOSE_WINDOW_NOT_MET`.
        `CLOSED` is terminal".

        Design: Corner/state_machines/injury_reopen_cycle_and_close_window
        """
        tr1 = make_trainer()
        athlete = create_athlete_as_trainer(tr1, primary_sport="BASKETBALL",
                                            team_level="JV",
                                            guardian_email=None)
        injury = create_injury_for(athlete["id"], tr1)
        assert injury["status"] == "OPEN"
        begin_care(injury["id"], tr1)

        resolved = validate_success(api_client.resolve_injury(
            injury["id"], trainer_headers(tr1)))
        assert resolved["status"] == "RESOLVED"
        # resolved_at is stamped with the (default) logical clock.
        assert_instant_equals(resolved["resolved_at"],
                              "2026-08-01T00:00:00Z", "resolved_at")

        reopened = validate_success(api_client.reopen_injury(
            injury["id"], {"reason": "pain returned"},
            trainer_headers(tr1)))
        assert reopened["status"] == "OPEN"
        assert reopened["resolved_at"] is None, "reopen clears resolved_at"

        begin_care(injury["id"], tr1)
        validate_success(api_client.resolve_injury(injury["id"],
                                                   trainer_headers(tr1)))
        # Same-day close attempt: thirty days have not elapsed.
        resp = api_client.close_injury(injury["id"], trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_CLOSE_WINDOW_NOT_MET)

        # resolved_at 2026-08-01T00:00:00Z + 30 days = 2026-08-31T00:00:00Z,
        # inclusive boundary.
        set_clock("2026-08-31T00:00:00Z")
        closed = validate_success(api_client.close_injury(
            injury["id"], trainer_headers(tr1)))
        assert closed["status"] == "CLOSED"

        resp = api_client.reopen_injury(injury["id"], {"reason": "too late"},
                                        trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_resolve_blocked_while_protocol_active(self):
        """PRD §3.5: "resolution is refused while an `ACTIVE` return-to-play
        protocol still exists for the injury (the refusal is
        `ERR_INVALID_STATE`; the protocol must first be cleared or terminated
        per §3.7)."

        Design: Corner/state_machines/injury_resolve_blocked_with_active_protocol_rejected
        """
        tr1 = make_trainer()
        nr1 = make_nurse()
        athlete, injury, protocol = setup_athlete_with_rtp(
            tr1, nr1,
            injury_overrides={"body_region": "KNEE", "mechanism": "cut"})
        assert protocol["status"] == "ACTIVE"

        resp = api_client.resolve_injury(injury["id"], trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        injury_after = validate_success(api_client.get_injury(
            injury["id"], trainer_headers(tr1)))
        assert injury_after["status"] == "RTP_IN_PROGRESS", \
            "the rejected resolve leaves the injury unchanged"

    def test_reopen_reference_requires_closed_prior(self):
        """PRD §3.5: "supplying `reopen_of_id` links the new evaluation to a
        prior injury, which must be `CLOSED` and must belong to the same
        athlete — anything else is rejected with
        `ERR_REFERENCED_INJURY_NOT_CLOSED`."
        PRD §3.5: "A plain first injury carries `recurrence_count` zero; a
        recurrence carries the referenced injury's `recurrence_count` plus
        one."

        Design: Corner/errors/reopen_reference_requires_closed_prior
        """
        tr1 = make_trainer()
        athlete = create_athlete_as_trainer(tr1, primary_sport="FOOTBALL")
        first = create_injury_for(athlete["id"], tr1, body_region="KNEE",
                                  severity="MODERATE", mechanism="cut")

        # The prior injury is still OPEN: the reference is rejected.
        resp = api_client.create_injury(
            {
                "athlete_id": athlete["id"],
                "body_region": "KNEE",
                "injury_type": "SPRAIN",
                "severity": "MODERATE",
                "mechanism": "recurrence attempt",
                "evaluated_at": "2026-07-31T12:00:00Z",
                "reopen_of_id": first["id"],
            },
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_REFERENCED_INJURY_NOT_CLOSED)

        # Drive the prior injury to CLOSED (resolve + thirty-day window).
        begin_care(first["id"], tr1)
        validate_success(api_client.resolve_injury(first["id"],
                                                   trainer_headers(tr1)))
        set_clock("2026-08-31T00:00:00Z")
        closed = validate_success(api_client.close_injury(
            first["id"], trainer_headers(tr1)))
        assert closed["status"] == "CLOSED"

        recurrence = validate_success(api_client.create_injury(
            {
                "athlete_id": athlete["id"],
                "body_region": "KNEE",
                "injury_type": "SPRAIN",
                "severity": "MODERATE",
                "mechanism": "true recurrence",
                "evaluated_at": "2026-08-30T09:00:00Z",
                "reopen_of_id": first["id"],
            },
            trainer_headers(tr1)), expected_status=201)
        assert recurrence["status"] == "OPEN"
        assert recurrence["recurrence_count"] == 1, \
            "inherits the predecessor's recurrence_count plus one"


class TestReferralLifecycle:

    def test_addendum_cycle_overwrites_report(self):
        """PRD §3.6: "A completed report can be questioned: the trainer
        requests an addendum, supplying the `question` to be answered, which
        moves the referral from `COMPLETED` to `ADDENDUM_REQUESTED`."
        PRD §3.6: "The physician's next completion — allowed from `SCHEDULED`
        or `ADDENDUM_REQUESTED`, subject to the same ownership rule — files
        the amended report: the report fields are overwritten, `reported_at`
        is refreshed, and the same cascades as a fresh completion apply."
        PRD §3.6: "computes its `due_by` from the creation timestamp:
        fourteen days out for `ROUTINE`, three days for `URGENT`, one day for
        `EMERGENT`."

        Design: Corner/state_machines/referral_addendum_cycle
        """
        tr1 = make_trainer()
        md = make_physician()
        athlete = create_athlete_as_trainer(tr1, sex="F",
                                            primary_sport="SOFTBALL")
        injury = create_injury_for(athlete["id"], tr1, body_region="SHOULDER",
                                   severity="MODERATE", mechanism="throwing")
        referral = create_referral_for(injury["id"], md, tr1,
                                       reason="rotator eval", urgency="URGENT")
        # Created at the default clock 2026-08-01T00:00:00Z + 3 days.
        assert_instant_equals(referral["due_by"], "2026-08-04T00:00:00Z",
                              "due_by URGENT")
        schedule_referral(referral["id"], tr1, "2026-08-02T10:00:00Z")

        completed = complete_referral(referral["id"], md,
                                      report_diagnosis="strain grade 1",
                                      report_clearance="CLEARED_RESTRICTED")
        assert completed["status"] == "COMPLETED"
        assert completed["report_diagnosis"] == "strain grade 1"

        addendum = validate_success(api_client.request_addendum_referral(
            referral["id"], {"question": "clarify contact restrictions"},
            trainer_headers(tr1)))
        assert addendum["status"] == "ADDENDUM_REQUESTED"

        amended = complete_referral(referral["id"], md,
                                    report_diagnosis="strain grade 1 - resolved",
                                    report_clearance="CLEARED_FULL")
        assert amended["status"] == "COMPLETED"
        assert amended["report_diagnosis"] == "strain grade 1 - resolved"
        assert amended["report_clearance"] == "CLEARED_FULL", \
            "the amended report overwrites the prior fields"


class TestReferralDueBoundary:
    """Difficulty instance referral_due_boundary_exclusive (two tests)."""

    def _setup_routine_referral(self):
        tr1 = make_trainer()
        md = make_physician()
        athlete = create_athlete_as_trainer(tr1, grade=10,
                                            primary_sport="BASEBALL",
                                            team_level="JV")
        injury = create_injury_for(athlete["id"], tr1, body_region="SHOULDER",
                                   severity="MODERATE", mechanism="throwing",
                                   restricted_activities=["PRACTICE", "GAME"])
        referral = create_referral_for(injury["id"], md, tr1,
                                       reason="shoulder eval")
        return tr1, referral

    def test_due_by_exactly_still_actionable(self):
        """PRD §3.6: "the clock sweep expires any referral still in
        `REQUESTED` or `SCHEDULED` once the clock is strictly later than
        `due_by` — at exactly `due_by` the referral remains actionable —
        moving it to `EXPIRED`."

        Design: Difficulty/boundary_precision_check/referral_due_boundary_exclusive
        """
        tr1, referral = self._setup_routine_referral()
        # ROUTINE: created at the 2026-08-01T00:00:00Z default clock + 14d.
        assert_instant_equals(referral["due_by"], "2026-08-15T00:00:00Z",
                              "due_by ROUTINE")
        set_clock("2026-08-15T00:00:00Z")
        data = validate_success(api_client.schedule_referral(
            referral["id"], {"appointment_at": "2026-08-15T10:00:00Z"},
            trainer_headers(tr1)))
        assert data["status"] == "SCHEDULED", \
            "the exclusive boundary leaves the referral actionable at due_by"

    def test_one_second_past_due_by_expires(self):
        """PRD §2.4: "Physician referrals still waiting in `REQUESTED` or
        `SCHEDULED` move to `EXPIRED` once the clock is strictly later than
        `due_by` — at the exact `due_by` instant the referral is still
        actionable."

        Design: Difficulty/boundary_precision_check/referral_due_boundary_exclusive
        """
        tr1, referral = self._setup_routine_referral()
        set_clock("2026-08-15T00:00:00Z")
        validate_success(api_client.schedule_referral(
            referral["id"], {"appointment_at": "2026-08-15T10:00:00Z"},
            trainer_headers(tr1)))
        set_clock("2026-08-15T00:00:01Z")
        expired = validate_success(api_client.get_referral(
            referral["id"], trainer_headers(tr1)))
        assert expired["status"] == "EXPIRED", \
            "one second past due_by the sweep expires the referral"
        resp = api_client.schedule_referral(
            referral["id"], {"appointment_at": "2026-08-16T10:00:00Z"},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestNotClearanceCascade:
    """Difficulty instance referral_not_cleared_three_hop_cascade."""

    def _setup_concussion_rtp_referred(self):
        """Concussion injury with an ACTIVE protocol and a SCHEDULED
        referral; the post-injury replacement baseline keeps the baseline
        gate satisfied."""
        tr1 = make_trainer()
        nr1 = make_nurse()
        md = make_physician()
        athlete = setup_cleared_athlete(
            tr1, nr1, athlete_overrides={"sex": "F"})
        set_clock("2026-08-02T09:00:00Z")
        injury = create_injury_for(
            athlete["id"], tr1, body_region="HEAD_NECK",
            injury_type="CONCUSSION", severity="MODERATE",
            mechanism="head-to-head collision",
            evaluated_at="2026-08-02T08:30:00Z",
            restricted_activities=["PRACTICE", "CONTACT"])
        # The concussion supersedes the CURRENT baseline (PRD §3.5); record
        # a fresh baseline so the baseline gate passes again.
        record_baseline(athlete["id"], tr1, test_date="2026-08-02",
                        instrument="IMPACT", symptom_score=3,
                        memory_index=90.0, reaction_time_ms=265.0,
                        balance_errors=2)
        injury = begin_care(injury["id"], tr1)
        protocol = create_rtp_protocol(injury, tr1)
        referral = create_referral_for(injury["id"], md, tr1,
                                       reason="concussion specialist eval")
        schedule_referral(referral["id"], tr1, "2026-08-03T10:00:00Z")
        return tr1, md, athlete, injury, protocol, referral

    def test_not_cleared_report_terminates_protocol(self):
        """PRD §3.6: "When `report_clearance` is `NOT_CLEARED` and an
        `ACTIVE` return-to-play protocol exists for the injury, the protocol
        moves to `TERMINATED` as a direct consequence of the report; that
        termination drops the injury from `RTP_IN_PROGRESS` back to
        `UNDER_CARE`; and the injury change recomputes the athlete's posture
        — three hops from one physician signature."

        Design: Difficulty/transitive_cascade/referral_not_cleared_three_hop_cascade
        """
        tr1, md, athlete, injury, protocol, referral = \
            self._setup_concussion_rtp_referred()
        completed = complete_referral(
            referral["id"], md,
            report_diagnosis="concussion - persistent symptoms",
            report_clearance="NOT_CLEARED")
        assert completed["status"] == "COMPLETED"

        protocol_after = validate_success(api_client.get_rtp_protocol(
            protocol["id"], trainer_headers(tr1)))
        assert protocol_after["status"] == "TERMINATED", \
            "hop 1: the report terminates the ACTIVE protocol"

    def test_cascade_reaches_injury_and_posture(self):
        """PRD §3.6: "that termination drops the injury from
        `RTP_IN_PROGRESS` back to `UNDER_CARE`; and the injury change
        recomputes the athlete's posture — three hops from one physician
        signature."
        PRD §3.1: "`CLEARED_WITH_RESTRICTIONS` — the higher gates pass, but
        the athlete has an injury in `UNDER_CARE` or `RTP_IN_PROGRESS`".

        Design: Difficulty/transitive_cascade/referral_not_cleared_three_hop_cascade
        """
        tr1, md, athlete, injury, protocol, referral = \
            self._setup_concussion_rtp_referred()
        complete_referral(referral["id"], md,
                          report_diagnosis="concussion - persistent symptoms",
                          report_clearance="NOT_CLEARED")
        injury_after = validate_success(api_client.get_injury(
            injury["id"], trainer_headers(tr1)))
        assert injury_after["status"] == "UNDER_CARE", \
            "hop 2: the protocol termination drops the injury back"
        assert _posture(tr1, athlete["id"]) == "CLEARED_WITH_RESTRICTIONS", \
            "hop 3: the injury change recomputes the posture"
