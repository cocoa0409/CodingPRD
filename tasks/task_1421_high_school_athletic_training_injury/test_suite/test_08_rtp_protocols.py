"""The graduated return-to-play protocol (PRD §3.7): stage dwell, symptom
gates, physician review, regression cycles, clearance authority, and the
injury-version OCC anchor (PRD §2.7)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    advance_protocol,
    assert_instant_equals,
    begin_care,
    complete_referral,
    create_injury_for,
    create_referral_for,
    create_rtp_protocol,
    first_notification_for_athlete,
    list_notifications,
    make_nurse,
    make_physician,
    make_trainer,
    physician_headers,
    record_baseline,
    schedule_referral,
    set_clock,
    setup_athlete_with_rtp,
    setup_cleared_athlete,
    trainer_headers,
    validate_error,
    validate_success,
    walk_protocol_to_stage,
)


def _protocol(trainer, protocol_id):
    return validate_success(api_client.get_rtp_protocol(
        protocol_id, trainer_headers(trainer)))


def _injury(trainer, injury_id):
    return validate_success(api_client.get_injury(
        injury_id, trainer_headers(trainer)))


def _clearance(trainer, athlete_id):
    return validate_success(api_client.get_athlete_clearance(
        athlete_id, trainer_headers(trainer)))


class TestRegressCycle:
    """Difficulty instance rtp_regress_cycle_stage_reentry (two tests)."""

    def _setup_stage2(self):
        tr1 = make_trainer()
        nr1 = make_nurse()
        athlete, injury, protocol = setup_athlete_with_rtp(
            tr1, nr1, protocol_clock="2026-08-02T09:00:00Z",
            injury_overrides={"evaluated_at": "2026-08-02T08:30:00Z"})
        set_clock("2026-08-03T09:00:00Z")
        advanced = advance_protocol(protocol["id"], tr1)
        return tr1, athlete, injury, protocol, advanced

    def test_regress_resets_stage_and_restarts_dwell(self):
        """PRD §3.7: "the protocol — which must be `ACTIVE` — appends a
        `REGRESSED` history entry, returns `current_stage` to 1, resets
        `stage_entered_at`, and increments `recurrence_count` by one."

        Design: Difficulty/non_linear_state_machine/rtp_regress_cycle_stage_reentry
        """
        tr1, athlete, injury, protocol, advanced = self._setup_stage2()
        assert advanced["current_stage"] == 2

        regressed = validate_success(api_client.regress_rtp_protocol(
            protocol["id"], {"notes": "symptoms returned"},
            trainer_headers(tr1)))
        assert regressed["current_stage"] == 1, \
            "regression resets the protocol to stage 1"
        assert regressed["recurrence_count"] == 1
        assert_instant_equals(regressed["stage_entered_at"],
                              "2026-08-03T09:00:00Z",
                              "stage_entered_at after regress")

        # A fresh 24h dwell must elapse before the re-advance lands.
        set_clock("2026-08-04T09:00:00Z")
        re_advanced = advance_protocol(protocol["id"], tr1)
        assert re_advanced["current_stage"] == 2

    def test_stage_history_accumulates_exit_reasons_in_order(self):
        """PRD §3.7: "Progress through the six stages is journaled in
        `stage_history`, an append-only log in which every entry records the
        `stage`, its `entered_at` and `exited_at` instants, and the
        `exit_reason` — `ADVANCED`, `REGRESSED`, `CLEARED`, or `TERMINATED`."

        Design: Difficulty/non_linear_state_machine/rtp_regress_cycle_stage_reentry
        """
        tr1, athlete, injury, protocol, advanced = self._setup_stage2()
        validate_success(api_client.regress_rtp_protocol(
            protocol["id"], {"notes": "symptoms returned"},
            trainer_headers(tr1)))
        set_clock("2026-08-04T09:00:00Z")
        final = advance_protocol(protocol["id"], tr1)
        reasons = [entry["exit_reason"] for entry in final["stage_history"]]
        assert reasons == ["ADVANCED", "REGRESSED", "ADVANCED"], (
            f"stage history must journal ADVANCED/REGRESSED/ADVANCED in "
            f"order, got {reasons}")


class TestRegressCascade:
    """Difficulty instance rtp_regress_injury_posture_cascade (two tests)."""

    def _setup(self):
        tr1 = make_trainer()
        nr1 = make_nurse()
        athlete, injury, protocol = setup_athlete_with_rtp(
            tr1, nr1, protocol_clock="2026-08-02T09:00:00Z",
            injury_overrides={"body_region": "KNEE", "mechanism":
                              "cutting move",
                              "evaluated_at": "2026-08-02T08:30:00Z"},
            athlete_overrides={"guardian_user_id": "g-4002"})
        set_clock("2026-08-03T09:00:00Z")
        advance_protocol(protocol["id"], tr1)
        return tr1, athlete, injury, protocol

    def test_regress_drops_injury_to_under_care_and_recomputes_posture(self):
        """PRD §3.7: "The injury falls from `RTP_IN_PROGRESS` back to
        `UNDER_CARE`, the posture recompute that follows lands the athlete in
        `CLEARED_WITH_RESTRICTIONS`, and an `RTP_REGRESSION` guardian
        notification is queued."
        PRD §3.1: "`CLEARED_WITH_RESTRICTIONS` — the higher gates pass, but
        the athlete has an injury in `UNDER_CARE` or `RTP_IN_PROGRESS`, or
        the latest `VERIFIED` physical's outcome is
        `CLEARED_WITH_RESTRICTIONS`. Reasons include `INJURY_RESTRICTIONS`
        and/or `PHYSICAL_RESTRICTIONS`."

        Design: Difficulty/transitive_cascade/rtp_regress_injury_posture_cascade
        """
        tr1, athlete, injury, protocol = self._setup()
        validate_success(api_client.regress_rtp_protocol(
            protocol["id"], {}, trainer_headers(tr1)))
        assert _injury(tr1, injury["id"])["status"] == "UNDER_CARE", \
            "hop 1: the regression moves the injury back to treatment"
        clearance = _clearance(tr1, athlete["id"])
        assert clearance["participation_posture"] == \
            "CLEARED_WITH_RESTRICTIONS", "hop 2: posture follows the injury"
        assert "INJURY_RESTRICTIONS" in clearance["posture_reasons"]

    def test_regress_queues_guardian_notification(self):
        """PRD §3.8: "Guardian notifications are created by the system,
        never drafted by hand: ... `RTP_REGRESSION` when a protocol
        regresses".

        Design: Difficulty/transitive_cascade/rtp_regress_injury_posture_cascade
        """
        tr1, athlete, injury, protocol = self._setup()
        validate_success(api_client.regress_rtp_protocol(
            protocol["id"], {}, trainer_headers(tr1)))
        notification = first_notification_for_athlete(
            athlete["id"], tr1, notification_type="RTP_REGRESSION")
        assert notification["status"] == "QUEUED"


class TestStageDwellBoundary:
    """Difficulty instance rtp_dwell_exactly_24h_inclusive (two tests)."""

    def _setup(self):
        tr1 = make_trainer()
        nr1 = make_nurse()
        athlete, injury, protocol = setup_athlete_with_rtp(
            tr1, nr1, protocol_clock="2026-08-02T09:00:00Z",
            injury_overrides={"body_region": "LOWER_LEG",
                              "injury_type": "STRAIN",
                              "mechanism": "sprint pull",
                              "evaluated_at": "2026-08-02T08:30:00Z"},
            athlete_overrides={"primary_sport": "TRACK",
                               "team_level": "JV", "sex": "F"},
            baseline_overrides={"instrument": "SWAY", "memory_index": 97.0,
                                "reaction_time_ms": 240.0,
                                "balance_errors": 0})
        return tr1, protocol

    def test_advance_at_23h59m59s_rejected(self):
        """PRD §3.7: "The athlete must have dwelt in the current stage for at
        least twenty-four hours — exactly twenty-four hours qualifies,
        anything less draws `ERR_RTP_STAGE_DWELL_NOT_MET`."

        Design: Difficulty/boundary_precision_check/rtp_dwell_exactly_24h_inclusive
        """
        tr1, protocol = self._setup()
        set_clock("2026-08-03T08:59:59Z")
        resp = api_client.advance_rtp_protocol(
            protocol["id"], {"symptom_check_passed": True},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_RTP_STAGE_DWELL_NOT_MET)

    def test_advance_at_exactly_24h_succeeds_and_resets_dwell(self):
        """PRD §3.7: "A successful advance increments `current_stage`,
        resets `stage_entered_at` to now, and appends an `ADVANCED` history
        entry".

        Design: Difficulty/boundary_precision_check/rtp_dwell_exactly_24h_inclusive
        """
        tr1, protocol = self._setup()
        set_clock("2026-08-03T09:00:00Z")
        data = advance_protocol(protocol["id"], tr1)
        assert data["current_stage"] == 2, \
            "the inclusive boundary admits the advance at exactly 24h"
        assert_instant_equals(data["stage_entered_at"],
                              "2026-08-03T09:00:00Z",
                              "stage_entered_at resets on advance")


class TestAdvanceSafetyGates:

    def test_advance_with_symptoms_rejected(self):
        """PRD §3.7: "The athlete must be symptom-free: the request's
        `symptom_check_passed` must be true, and a false value is rejected
        with `ERR_SYMPTOMS_REPORTED` (HTTP 422)."

        Design: Corner/validations/rtp_advance_with_symptoms_rejected
        """
        tr1 = make_trainer()
        nr1 = make_nurse()
        athlete, injury, protocol = setup_athlete_with_rtp(
            tr1, nr1, protocol_clock="2026-08-02T09:00:00Z",
            injury_overrides={"body_region": "ARM_HAND",
                              "mechanism": "swing",
                              "evaluated_at": "2026-08-02T08:30:00Z"},
            athlete_overrides={"primary_sport": "BASEBALL"})
        set_clock("2026-08-03T09:00:00Z")  # dwell fully satisfied
        resp = api_client.advance_rtp_protocol(
            protocol["id"], {"symptom_check_passed": False},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_SYMPTOMS_REPORTED)

        after = _protocol(tr1, protocol["id"])
        assert after["current_stage"] == 1, "the rejection moves nothing"
        assert after["stage_history"] == []

    def test_advance_blocked_when_physical_expired(self):
        """PRD §3.7: "The athlete's posture must not be `INELIGIBLE` or
        `NOT_CLEARED` — a lapse in physical or baseline validity mid-protocol
        blocks advancement with `ERR_PHYSICAL_EXPIRED`."
        PRD §2.4: "Recorded and verified pre-participation physicals whose
        validity has run out move to `EXPIRED` — the boundary is inclusive,
        so a physical expires the moment the clock reaches its `expires_on`."

        Design: Corner/validations/rtp_advance_blocked_when_physical_expired
        """
        tr1 = make_trainer()
        nr1 = make_nurse()
        set_clock("2026-07-15T00:00:00Z")
        athlete, injury, protocol = setup_athlete_with_rtp(
            tr1, nr1,
            physical_overrides={"exam_date": "2025-07-01"},
            baseline_overrides={"test_date": "2026-07-10"},
            injury_overrides={"body_region": "KNEE", "mechanism": "cut",
                              "evaluated_at": "2026-07-14T10:00:00Z"})
        # exam 2025-07-01 + 13 months -> expires_on 2026-08-01T00:00:00Z.
        set_clock("2026-08-01T00:00:00Z")
        physicals = validate_success(api_client.list_physicals(
            trainer_headers(tr1), params={"athlete_id": athlete["id"]}))
        assert physicals[0]["status"] == "EXPIRED", \
            "the sweep fires at exactly expires_on (inclusive)"
        assert _clearance(tr1, athlete["id"])["participation_posture"] == \
            "INELIGIBLE"

        # State and dwell are both satisfied; the safety gate fires.
        resp = api_client.advance_rtp_protocol(
            protocol["id"], {"symptom_check_passed": True},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_PHYSICAL_EXPIRED)


class TestAdvancePriorityPair:
    """Difficulty instance rtp_advance_state_vs_safety_priority (two tests)."""

    def _setup_terminated_protocol_with_expired_physical(self):
        tr1 = make_trainer()
        nr1 = make_nurse()
        set_clock("2026-07-15T00:00:00Z")
        athlete, injury, protocol = setup_athlete_with_rtp(
            tr1, nr1,
            physical_overrides={"exam_date": "2025-07-01"},
            baseline_overrides={"test_date": "2026-07-10"},
            injury_overrides={"body_region": "KNEE", "mechanism": "twist",
                              "evaluated_at": "2026-07-14T10:00:00Z"})
        validate_success(api_client.terminate_rtp_protocol(
            protocol["id"], {"reason": "athlete relocated"},
            trainer_headers(tr1)))
        # The clock sweep at expires_on flips the physical and the posture.
        set_clock("2026-08-01T00:00:00Z")
        return tr1, athlete, protocol

    def test_terminated_protocol_and_expired_physical_yields_state_error(self):
        """PRD §3.7: "a trainer action with five gates, applied under the
        global ordering of §2.9 — state first, then the safety gates, then
        the temporal dwell."
        PRD §2.9: "When several business rules could reject the same request,
        the ordering that decides the surfaced error is: state before safety,
        safety before temporal, temporal before reference quality, and all of
        those before fiscal coverage."

        Design: Difficulty/priority_pair_validation_conflict/rtp_advance_state_vs_safety_priority
        """
        tr1, athlete, protocol = \
            self._setup_terminated_protocol_with_expired_physical()
        # Both violations are genuinely armed.
        physicals = validate_success(api_client.list_physicals(
            trainer_headers(tr1), params={"athlete_id": athlete["id"]}))
        assert physicals[0]["status"] == "EXPIRED"
        assert _clearance(tr1, athlete["id"])["participation_posture"] == \
            "INELIGIBLE"

        resp = api_client.advance_rtp_protocol(
            protocol["id"], {"symptom_check_passed": True},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.json()["data"]["error_id"] != "ERR_PHYSICAL_EXPIRED", \
            "the state violation must outrank the safety violation"

    def test_safety_violation_alone_would_fire_physical_expired(self):
        """PRD §3.7: "The athlete's posture must not be `INELIGIBLE` or
        `NOT_CLEARED` — a lapse in physical or baseline validity mid-protocol
        blocks advancement with `ERR_PHYSICAL_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/rtp_advance_state_vs_safety_priority
        """
        tr1 = make_trainer()
        nr1 = make_nurse()
        set_clock("2026-07-15T00:00:00Z")
        athlete, injury, protocol = setup_athlete_with_rtp(
            tr1, nr1,
            physical_overrides={"exam_date": "2025-07-01"},
            baseline_overrides={"test_date": "2026-07-10"},
            injury_overrides={"evaluated_at": "2026-07-14T10:00:00Z"})
        # Same expired-physical safety violation but the protocol is ACTIVE:
        # with no state violation present the safety error surfaces, proving
        # the pair test's first arm is load-bearing.
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.advance_rtp_protocol(
            protocol["id"], {"symptom_check_passed": True},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_PHYSICAL_EXPIRED)


class TestConcussionStageFiveGate:
    """Difficulty instance concussion_stage5_gated_by_referral_report."""

    def _setup_concussion_at_stage4(self):
        tr1 = make_trainer()
        nr1 = make_nurse()
        md = make_physician()
        athlete = setup_cleared_athlete(
            tr1, nr1, athlete_overrides={"sex": "F"})
        set_clock("2026-08-02T09:00:00Z")
        injury = create_injury_for(
            athlete["id"], tr1, body_region="HEAD_NECK",
            injury_type="CONCUSSION", severity="MODERATE",
            mechanism="heading collision",
            evaluated_at="2026-08-02T08:30:00Z",
            restricted_activities=["PRACTICE", "CONTACT"])
        record_baseline(athlete["id"], tr1, test_date="2026-08-02",
                        symptom_score=2, memory_index=92.0,
                        reaction_time_ms=260.0, balance_errors=2)
        injury = begin_care(injury["id"], tr1)
        protocol = create_rtp_protocol(injury, tr1)
        # Walk 1 -> 4 with one 24h dwell per stage.
        walk_protocol_to_stage(protocol["id"], tr1,
                               protocol["stage_entered_at"], 4)
        return tr1, md, athlete, injury, protocol

    def test_concussion_derives_physician_clearance_authority(self):
        """PRD §3.7: "derives `clearance_authority_required`: `PHYSICIAN`
        when the injury is a `CONCUSSION` or its severity is `SEVERE` or
        `CRITICAL`, otherwise `TRAINER`."

        Design: Difficulty/cross_entity_state_dependency/concussion_stage5_gated_by_referral_report
        """
        tr1, md, athlete, injury, protocol = \
            self._setup_concussion_at_stage4()
        assert protocol["clearance_authority_required"] == "PHYSICIAN"
        assert _protocol(tr1, protocol["id"])["current_stage"] == 4

    def test_advance_into_stage5_requires_physician_report(self):
        """PRD §3.7: "when the advance would carry a `CONCUSSION` protocol
        into stage 5, a `COMPLETED` or `CLOSED` referral for this injury
        carrying a `report_clearance` of `CLEARED_FULL` or
        `CLEARED_RESTRICTED` must exist, else
        `ERR_RTP_PHYSICIAN_REVIEW_REQUIRED`".

        Design: Difficulty/cross_entity_state_dependency/concussion_stage5_gated_by_referral_report
        """
        tr1, md, athlete, injury, protocol = \
            self._setup_concussion_at_stage4()
        protocol = _protocol(tr1, protocol["id"])
        set_clock("2026-08-06T09:00:00Z")  # 24h after entering stage 4
        resp = api_client.advance_rtp_protocol(
            protocol["id"], {"symptom_check_passed": True},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_RTP_PHYSICIAN_REVIEW_REQUIRED)

        referral = create_referral_for(injury["id"], md, tr1,
                                       reason="concussion clearance eval")
        schedule_referral(referral["id"], tr1, "2026-08-06T10:00:00Z")
        complete_referral(referral["id"], md,
                          report_diagnosis="concussion resolved",
                          report_clearance="CLEARED_FULL")
        data = advance_protocol(protocol["id"], tr1)
        assert data["current_stage"] == 5, \
            "the identical advance succeeds once the report is on file"


class TestRecurrenceTwoPhysicianReview:

    def test_second_recurrence_blocks_advance_until_report(self):
        """PRD §3.7: "the identical requirement applies to any injury type
        once the protocol's `recurrence_count` reaches two".
        PRD §3.1: "`MEDICAL_HOLD` — the physical and baseline gates pass, but
        the athlete has an injury in `OPEN` or `REFERRED`, or has an `ACTIVE`
        concussion-type return-to-play protocol whose `recurrence_count` has
        reached two without a `COMPLETED` or `CLOSED` physician referral
        carrying a `report_clearance` of `CLEARED_FULL` or
        `CLEARED_RESTRICTED`. Reasons include `ACUTE_INJURY_OPEN` and/or
        `PHYSICIAN_REVIEW_PENDING` as applicable."

        Design: Corner/calculations/recurrence_two_requires_physician_review
        """
        tr1 = make_trainer()
        nr1 = make_nurse()
        md = make_physician()
        athlete = setup_cleared_athlete(
            tr1, nr1, athlete_overrides={"sex": "F"})
        set_clock("2026-08-02T09:00:00Z")
        injury = create_injury_for(
            athlete["id"], tr1, body_region="HEAD_NECK",
            injury_type="CONCUSSION", severity="MODERATE",
            mechanism="collision", evaluated_at="2026-08-02T08:30:00Z",
            restricted_activities=["PRACTICE", "CONTACT"])
        record_baseline(athlete["id"], tr1, test_date="2026-08-02",
                        symptom_score=4, memory_index=90.0,
                        reaction_time_ms=270.0, balance_errors=3)
        injury = begin_care(injury["id"], tr1)
        protocol = create_rtp_protocol(injury, tr1)

        # Recurrence 1: advance then regress.
        set_clock("2026-08-03T09:00:00Z")
        advance_protocol(protocol["id"], tr1)
        set_clock("2026-08-03T10:00:00Z")
        reg1 = validate_success(api_client.regress_rtp_protocol(
            protocol["id"], {}, trainer_headers(tr1)))
        assert reg1["recurrence_count"] == 1

        # Recurrence 2: re-advance after a fresh dwell, then regress again.
        set_clock("2026-08-04T10:00:00Z")
        advance_protocol(protocol["id"], tr1)
        set_clock("2026-08-04T11:00:00Z")
        reg2 = validate_success(api_client.regress_rtp_protocol(
            protocol["id"], {}, trainer_headers(tr1)))
        assert reg2["recurrence_count"] == 2

        # Posture flips to MEDICAL_HOLD via the physician-review clause.
        clearance = _clearance(tr1, athlete["id"])
        assert clearance["participation_posture"] == "MEDICAL_HOLD"
        assert "PHYSICIAN_REVIEW_PENDING" in clearance["posture_reasons"]

        # The advance is blocked even though the 24h dwell is satisfied.
        set_clock("2026-08-05T11:00:00Z")
        resp = api_client.advance_rtp_protocol(
            protocol["id"], {"symptom_check_passed": True},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_RTP_PHYSICIAN_REVIEW_REQUIRED)

        # A completed physician report carrying a clearance unlocks it.
        referral = create_referral_for(injury["id"], md, tr1,
                                       reason="recurrent symptoms",
                                       urgency="URGENT")
        schedule_referral(referral["id"], tr1, "2026-08-05T12:00:00Z")
        complete_referral(referral["id"], md,
                          report_diagnosis="cleared with monitoring",
                          report_clearance="CLEARED_RESTRICTED")
        data = advance_protocol(protocol["id"], tr1)
        assert data["current_stage"] == 2


class TestClearanceAuthority:

    def test_trainer_clear_rejected_physician_clear_succeeds(self):
        """PRD §3.7: "when it is `PHYSICIAN`, only a `Physician` caller may
        clear — a trainer's attempt is rejected with
        `ERR_CLEARANCE_AUTHORITY_INSUFFICIENT` (HTTP 403); when it is
        `TRAINER`, either an `AthleticTrainer` or a `Physician` may clear."
        PRD §3.7: "Clearance stamps `cleared_by_staff_id` and `cleared_at`,
        appends a `CLEARED` history entry for stage 6, moves the protocol to
        `CLEARED`, moves the injury from `RTP_IN_PROGRESS` to `RESOLVED` with
        `resolved_at` set, recomputes the athlete's posture, and queues a
        `CLEARANCE_GRANTED` guardian notification."

        Design: Corner/validations/clearance_authority_trainer_rejected_physician_succeeds
        """
        tr1 = make_trainer()
        nr1 = make_nurse()
        md = make_physician()
        athlete = setup_cleared_athlete(
            tr1, nr1,
            athlete_overrides={"primary_sport": "FOOTBALL", "grade": 12})
        set_clock("2026-08-02T09:00:00Z")
        injury = create_injury_for(
            athlete["id"], tr1, body_region="HEAD_NECK",
            injury_type="CONCUSSION", severity="MODERATE",
            mechanism="helmet contact", evaluated_at="2026-08-02T08:30:00Z",
            restricted_activities=["PRACTICE", "CONTACT", "GAME"])
        record_baseline(athlete["id"], tr1, test_date="2026-08-02",
                        symptom_score=2, memory_index=93.0,
                        reaction_time_ms=260.0, balance_errors=2)
        injury = begin_care(injury["id"], tr1)
        protocol = create_rtp_protocol(injury, tr1)
        assert protocol["clearance_authority_required"] == "PHYSICIAN"

        # Walk 1 -> 4, file the physician report, then walk 4 -> 6.
        walk_protocol_to_stage(protocol["id"], tr1,
                               protocol["stage_entered_at"], 4)
        referral = create_referral_for(injury["id"], md, tr1,
                                       reason="stage-5 clearance eval")
        schedule_referral(referral["id"], tr1, "2026-08-05T10:00:00Z")
        complete_referral(referral["id"], md, report_diagnosis="recovered",
                          report_clearance="CLEARED_FULL")
        protocol = _protocol(tr1, protocol["id"])
        walk_protocol_to_stage(protocol["id"], tr1,
                               protocol["stage_entered_at"], 6)
        assert _protocol(tr1, protocol["id"])["current_stage"] == 6

        # Dwell into stage 6 satisfied; the trainer's clear is rejected.
        protocol = _protocol(tr1, protocol["id"])
        set_clock("2026-08-08T09:00:00Z")
        resp = api_client.clear_rtp_protocol(
            protocol["id"], {"clearance_notes": "trainer attempt"},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_AUTHORITY_INSUFFICIENT)

        cleared = validate_success(api_client.clear_rtp_protocol(
            protocol["id"], {"clearance_notes": "physician clearance"},
            physician_headers(md)))
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_by_staff_id"] == md["id"]

        assert _injury(tr1, injury["id"])["status"] == "RESOLVED", \
            "clearance cascades to the injury"
        assert _clearance(tr1, athlete["id"])["participation_posture"] == \
            "CLEARED"
        granted = [n for n in list_notifications(
            tr1, athlete_id=athlete["id"],
            notification_type="CLEARANCE_GRANTED", status="QUEUED")]
        assert granted, "a CLEARANCE_GRANTED notification is queued"


class TestProtocolOcc:
    """Corner instance occ_stale_version_on_rtp_supersede."""

    def test_stale_injury_version_rejected_then_supersede_succeeds(self):
        """PRD §2.7: "Creating a return-to-play protocol on an injury
        requires the request body to carry `expected_injury_version` equal to
        the injury's current `version`. If another writer has advanced the
        injury's version since the client last read it, the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "Because product semantics allow a fresh protocol to
        replace an abandoned one, activation supersedes: any previously
        `ACTIVE` protocol on the same injury moves to `TERMINATED` with a
        corresponding `stage_history` entry."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_rtp_supersede
        """
        tr1 = make_trainer()
        nr1 = make_nurse()
        athlete = setup_cleared_athlete(tr1, nr1)
        injury = create_injury_for(athlete["id"], tr1, body_region="KNEE",
                                   mechanism="cut")
        injury = begin_care(injury["id"], tr1)
        stale_version = injury["version"]
        p1 = create_rtp_protocol(injury, tr1)
        assert p1["status"] == "ACTIVE"

        # The first create bumped the injury version, so the stale
        # expectation is rejected.
        resp = api_client.create_rtp_protocol(
            injury["id"],
            {"protocol_type": "GRADUATED_6_STAGE",
             "expected_injury_version": stale_version},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        injury_now = _injury(tr1, injury["id"])
        assert injury_now["version"] == stale_version + 1
        assert injury_now["status"] == "RTP_IN_PROGRESS"

        # Re-reading and resubmitting legitimately supersedes P1.
        p2 = validate_success(api_client.create_rtp_protocol(
            injury["id"],
            {"protocol_type": "GRADUATED_6_STAGE",
             "expected_injury_version": injury_now["version"]},
            trainer_headers(tr1)), expected_status=201)
        assert p2["status"] == "ACTIVE"
        p1_after = _protocol(tr1, p1["id"])
        assert p1_after["status"] == "TERMINATED", \
            "the replacement supersedes the previously ACTIVE protocol"
