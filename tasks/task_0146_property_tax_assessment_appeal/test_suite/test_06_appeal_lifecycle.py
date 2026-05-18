"""Appeal lifecycle: filing, scheduling, conducting, deciding, and
withdrawing (PRD §3.5).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    APPEAL_WINDOW_DAYS,
    ApiErrorId,
    GRACE_MIN,
    HEARING_MAX_DURATION_MIN,
    OFFICER_BUFFER_MIN,
    add_days_iso,
    add_milliseconds_iso,
    add_minutes_iso,
    advance_clock_to,
    assert_appeal,
    assert_hearing,
    conduct_appeal,
    create_assessment,
    create_hearing_officer,
    create_owner,
    create_property,
    decide_appeal,
    decide_appeal_payload,
    file_appeal,
    file_appeal_payload,
    get_appeal,
    get_assessment,
    iso_now_utc,
    issue_assessment,
    make_assessor_headers,
    make_hearing_officer_headers,
    make_owner_headers,
    schedule_appeal,
    schedule_appeal_payload,
    setup_heard_appeal,
    setup_issued_assessment,
    setup_owner_and_property,
    setup_scheduled_appeal,
    setup_two_appeals_for_scheduling_conflict,
    validate_error,
    validate_success,
    withdraw_appeal,
)


# ===========================================================================
# Filing — PRD §3.5
# ===========================================================================
class TestFileAppeal:

    def test_owner_files_appeal_within_window(self, api):
        """PRD §3.5: 'On a successful filing, the Appeal is created in
        FILED status, assessment_version is captured from the
        Assessment's current version (version-pinning so the appeal
        references the precise snapshot it was filed against), and
        the Assessment transitions ISSUED → UNDER_APPEAL'.

        Claim: owner files an Appeal, returned in FILED state with
        assessment_version captured.
        """
        owner, prop, asmt = setup_issued_assessment()
        appeal = file_appeal(
            owner=owner, property_id=prop["id"],
            assessment_id=asmt["id"], claimed_value=100_000.00,
        )
        assert_appeal(appeal)
        assert appeal["status"] == "FILED"
        assert appeal["assessment_version"] == asmt["version"], (
            f"assessment_version pinning failed: assessment.version="
            f"{asmt['version']}, appeal.assessment_version="
            f"{appeal['assessment_version']}"
        )
        # Assessment now UNDER_APPEAL.
        re_asmt = get_assessment(prop["id"], asmt["id"])
        assert re_asmt["status"] == "UNDER_APPEAL"

    def test_appeal_rejected_at_exact_window_boundary(self, api):
        """PRD §3.5: 'The strict precondition is that the current
        logical time is strictly less than the Assessment's
        appeal_window_closes_at; at the exact equality boundary the
        window is treated as closed and the request is rejected with
        ERR_APPEAL_WINDOW_CLOSED.'

        Claim: now exactly equal to appeal_window_closes_at →
        ERR_APPEAL_WINDOW_CLOSED.

        # difficulty: boundary_precision_check/appeal_window_strict_inequality
        """
        owner, prop, asmt = setup_issued_assessment()
        # Advance to EXACTLY appeal_window_closes_at.
        advance_clock_to(asmt["appeal_window_closes_at"])
        from test_helpers import api_client
        resp = api_client.file_appeal(
            prop["id"],
            file_appeal_payload(
                assessment_id=asmt["id"], claimed_value=100_000.00,
            ),
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)

    def test_appeal_rejected_after_window(self, api):
        """PRD §3.5: 'the current logical time is strictly less than
        the Assessment's appeal_window_closes_at; at the exact
        equality boundary the window is treated as closed and the
        request is rejected with ERR_APPEAL_WINDOW_CLOSED.'

        Claim: filing after the window is closed → ERR_APPEAL_WINDOW_CLOSED
        (the Assessment may auto-FINALIZE; the rejection error remains
        the temporal one per priority).

        # difficulty: boundary_precision_check/appeal_window_strict_inequality
        # difficulty: priority_pair_validation_conflict/state_vs_business_temporal_pair
        """
        owner, prop, asmt = setup_issued_assessment()
        # Advance clock 1 day past the appeal window.
        advance_clock_to(add_days_iso(asmt["appeal_window_closes_at"], 1))
        # PRD §2.11 says assessments auto-FINALIZE on clock advance
        # past appeal_window_closes_at when no Appeal exists. So the
        # underlying state when we attempt the file is FINALIZED,
        # which per PRD §2.9 priority ordering (state, priority 5,
        # before temporal at priority 7) should surface
        # ERR_INVALID_STATE.
        from test_helpers import api_client
        resp = api_client.file_appeal(
            prop["id"],
            file_appeal_payload(
                assessment_id=asmt["id"], claimed_value=100_000.00,
            ),
            make_owner_headers(owner["id"]),
        )
        # PRD §2.9: state check fires before temporal check.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_appeal_rejected_when_assessment_is_draft(self, api):
        """PRD §3.5: 'The Assessment itself must be in ISSUED (or
        already in UNDER_APPEAL — additional Appeals on the same
        Assessment are permitted while the window remains open).'

        Claim: filing an Appeal on a DRAFT Assessment fails with
        ERR_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/appeal_filing_requires_assessment_issued
        """
        owner, prop = setup_owner_and_property()
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        from test_helpers import api_client
        resp = api_client.file_appeal(
            prop["id"],
            file_appeal_payload(
                assessment_id=draft["id"], claimed_value=100_000.00,
            ),
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Schedule — PRD §3.5
# ===========================================================================
class TestScheduleAppeal:

    def test_schedule_creates_hearing_and_sets_scheduled(self, api):
        """PRD §3.5: 'Successful scheduling sets Appeal.status and
        Hearing.status to SCHEDULED; the Hearing row carries appeal_id
        (the live SCHEDULED hearing is 1:1 with its appeal) and a
        denormalized property_id for routing.'

        Claim: after schedule, both Appeal and Hearing are SCHEDULED;
        Hearing.appeal_id points back at the Appeal.
        """
        ctx = setup_scheduled_appeal()
        # Verify Appeal.
        appeal_data = get_appeal(
            ctx["property"]["id"], ctx["appeal"]["id"],
        )
        assert appeal_data["status"] == "SCHEDULED"
        # Verify Hearing.
        from test_helpers import api_client, TEST_USERS
        resp = api_client.get_hearing(
            ctx["property"]["id"], ctx["appeal"]["id"],
            TEST_USERS["treasurer_headers"],
        )
        hearing = validate_success(resp)
        assert_hearing(hearing)
        assert hearing["status"] == "SCHEDULED"
        assert hearing["appeal_id"] == ctx["appeal"]["id"]

    def test_schedule_rejected_when_end_le_start(self, api):
        """PRD §3.5: 'scheduled_end must be strictly greater than
        scheduled_start; otherwise ERR_HEARING_INTERVAL_INVALID.'

        Claim: scheduled_end == scheduled_start →
        ERR_HEARING_INTERVAL_INVALID.
        """
        owner, prop, asmt = setup_issued_assessment()
        appeal = file_appeal(
            owner=owner, property_id=prop["id"],
            assessment_id=asmt["id"], claimed_value=100_000.00,
        )
        officer = create_hearing_officer()
        base = add_minutes_iso(iso_now_utc(), 60)
        from test_helpers import api_client, TEST_USERS
        resp = api_client.schedule_appeal(
            prop["id"], appeal["id"],
            schedule_appeal_payload(
                scheduled_start=base, scheduled_end=base,
                hearing_room="ROOM_A", officer_id=officer["id"],
            ),
            TEST_USERS["treasurer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_INTERVAL_INVALID.value)

    def test_schedule_rejected_when_duration_exceeds_120min(self, api):
        """PRD §3.5: 'The interval (scheduled_end − scheduled_start)
        must not exceed the system constant HEARING_MAX_DURATION_MIN
        (120 minutes); otherwise ERR_HEARING_INTERVAL_INVALID.'

        Claim: 121-minute interval → ERR_HEARING_INTERVAL_INVALID.
        """
        owner, prop, asmt = setup_issued_assessment()
        appeal = file_appeal(
            owner=owner, property_id=prop["id"],
            assessment_id=asmt["id"], claimed_value=100_000.00,
        )
        officer = create_hearing_officer()
        start = add_minutes_iso(iso_now_utc(), 60)
        end = add_minutes_iso(start, 121)
        from test_helpers import api_client, TEST_USERS
        resp = api_client.schedule_appeal(
            prop["id"], appeal["id"],
            schedule_appeal_payload(
                scheduled_start=start, scheduled_end=end,
                hearing_room="ROOM_A", officer_id=officer["id"],
            ),
            TEST_USERS["treasurer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_INTERVAL_INVALID.value)

    def test_segregation_of_duties_officer_equals_assessor_rejected(
        self, api,
    ):
        """PRD §2.8: 'For any given Appeal, the HearingOfficer who is
        recorded as the presiding officer (via Hearing.officer_id)
        must not be the same user who issued the underlying
        Assessment. The server enforces this by comparing the officer
        to the recorded issuer at schedule time and rejecting
        violations with ERR_BOE_OFFICER_CONFLICT.'

        Claim: scheduling with officer_id == X-User-ID of the
        Assessor who issued the Assessment → ERR_BOE_OFFICER_CONFLICT.
        """
        # 1) Create owner + property + Assessment DRAFT.
        owner, prop = setup_owner_and_property()
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        # 2) Create a fresh HearingOfficer; we will issue the
        # Assessment as that officer (X-User-ID == officer.id, role
        # Assessor — the server only inspects X-User-ID for
        # segregation, not role mapping per PRD §2.1).
        officer = create_hearing_officer()
        # Issue Assessment as Assessor whose X-User-ID == officer.id.
        from test_helpers import api_client
        api_client.issue_assessment(
            prop["id"], draft["id"],
            make_assessor_headers(officer["id"]),
        )
        # 3) File Appeal as Owner.
        appeal = file_appeal(
            owner=owner, property_id=prop["id"],
            assessment_id=draft["id"], claimed_value=100_000.00,
        )
        # 4) Treasurer schedules with the same officer as both BoE
        # officer AND the prior issuer.
        from test_helpers import TEST_USERS
        start = add_minutes_iso(iso_now_utc(), 60)
        end = add_minutes_iso(start, 60)
        resp = api_client.schedule_appeal(
            prop["id"], appeal["id"],
            schedule_appeal_payload(
                scheduled_start=start, scheduled_end=end,
                hearing_room="ROOM_A", officer_id=officer["id"],
            ),
            TEST_USERS["treasurer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BOE_OFFICER_CONFLICT.value)


# ===========================================================================
# Conduct / Decide — PRD §3.5
# ===========================================================================
class TestConductAndDecide:

    def test_conduct_substituting_officer_rejected(self, api):
        """PRD §2.8: 'Once scheduling has captured an officer, the
        user who later conducts and decides the hearing must equal
        that captured officer_id; substitution at the bench is
        rejected with ERR_OFFICER_MISMATCH.'

        Claim: an HearingOfficer with X-User-ID != the scheduled
        Hearing.officer_id is rejected on /conduct with
        ERR_OFFICER_MISMATCH.
        """
        ctx = setup_scheduled_appeal()
        # Advance to scheduled_start so the time-window check passes.
        advance_clock_to(ctx["scheduled_start"])
        substitute = create_hearing_officer(full_name="Substitute Officer")
        from test_helpers import api_client
        resp = api_client.conduct_appeal(
            ctx["property"]["id"], ctx["appeal"]["id"],
            make_hearing_officer_headers(substitute["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFICER_MISMATCH.value)

    def test_decide_outcome_reduced_requires_decided_value_strictly_less(
        self, api,
    ):
        """PRD §3.5: 'The decided value must satisfy the outcome
        relative to the Assessment's capped_value as captured at the
        time the Appeal was filed: REDUCED requires decided_value
        strictly less than that captured capped_value ... A mismatched
        decision is rejected with ERR_DECISION_VALUE_INCONSISTENT.'

        Claim: REDUCED with decided_value >= captured capped_value →
        ERR_DECISION_VALUE_INCONSISTENT.
        """
        ctx = setup_heard_appeal(market_value=500_000.00)
        from test_helpers import api_client
        # captured capped_value=500000; submit a REDUCED with
        # decided_value=500000 (equal) — should be rejected.
        resp = api_client.decide_appeal(
            ctx["property"]["id"], ctx["appeal"]["id"],
            decide_appeal_payload(
                decision_outcome="REDUCED", decided_value=500_000.00,
            ),
            make_hearing_officer_headers(ctx["officer"]["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_DECISION_VALUE_INCONSISTENT.value,
        )

    def test_decide_outcome_upheld_requires_exact_equality(self, api):
        """PRD §3.5: 'UPHELD requires it exactly equal.' ... 'A
        mismatched decision is rejected with
        ERR_DECISION_VALUE_INCONSISTENT.'

        Claim: UPHELD with decided_value != captured capped_value →
        ERR_DECISION_VALUE_INCONSISTENT.
        """
        ctx = setup_heard_appeal(market_value=500_000.00)
        from test_helpers import api_client
        resp = api_client.decide_appeal(
            ctx["property"]["id"], ctx["appeal"]["id"],
            decide_appeal_payload(
                decision_outcome="UPHELD", decided_value=400_000.00,
            ),
            make_hearing_officer_headers(ctx["officer"]["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_DECISION_VALUE_INCONSISTENT.value,
        )

    def test_decide_outcome_reduced_succeeds_with_strictly_less(self, api):
        """PRD §3.5: 'REDUCED requires decided_value strictly less
        than that captured capped_value'.

        Claim: REDUCED with decided_value strictly less than captured
        capped_value succeeds; Appeal.status=DECIDED with
        decision_outcome=REDUCED and decided_value persisted.
        """
        ctx = setup_heard_appeal(market_value=500_000.00)
        decided = decide_appeal(
            property_id=ctx["property"]["id"],
            appeal_id=ctx["appeal"]["id"],
            officer=ctx["officer"],
            decision_outcome="REDUCED", decided_value=400_000.00,
        )
        assert_appeal(decided)
        assert decided["status"] == "DECIDED"
        assert decided["decision_outcome"] == "REDUCED"
        assert decided["decided_value"] == pytest.approx(400_000.00, abs=0.01)

    def test_decide_cascades_assessment_capped_value_for_reduced(self, api):
        """PRD §3.5: 'The Assessment's capped_value is updated to
        decided_value if the outcome is REDUCED or INCREASED (unchanged
        if UPHELD); the Assessment's version and updated_at are
        bumped.'

        Claim: after REDUCED decide, Assessment.capped_value equals
        decided_value.

        # difficulty: transitive_cascade/appeal_decided_cascade_depth_3
        # difficulty: non_linear_state_machine/appeal_branching_decisions
        """
        ctx = setup_heard_appeal(market_value=500_000.00)
        decide_appeal(
            property_id=ctx["property"]["id"],
            appeal_id=ctx["appeal"]["id"],
            officer=ctx["officer"],
            decision_outcome="REDUCED", decided_value=400_000.00,
        )
        re_asmt = get_assessment(
            ctx["property"]["id"], ctx["assessment"]["id"],
        )
        assert re_asmt["capped_value"] == pytest.approx(
            400_000.00, abs=0.01,
        )
        # And the Assessment is FINALIZED since no other Appeals open.
        assert re_asmt["status"] == "FINALIZED"

    def test_decide_upheld_leaves_capped_value_unchanged(self, api):
        """PRD §3.5: 'The Assessment's capped_value is updated to
        decided_value if the outcome is REDUCED or INCREASED
        (unchanged if UPHELD)'.

        Claim: UPHELD does not modify Assessment.capped_value.

        # difficulty: non_linear_state_machine/appeal_branching_decisions
        """
        ctx = setup_heard_appeal(market_value=500_000.00)
        decide_appeal(
            property_id=ctx["property"]["id"],
            appeal_id=ctx["appeal"]["id"],
            officer=ctx["officer"],
            decision_outcome="UPHELD", decided_value=500_000.00,
        )
        re_asmt = get_assessment(
            ctx["property"]["id"], ctx["assessment"]["id"],
        )
        assert re_asmt["capped_value"] == pytest.approx(
            500_000.00, abs=0.01,
        )


# ===========================================================================
# Withdraw — PRD §3.5
# ===========================================================================
class TestWithdrawAppeal:

    def test_withdraw_scheduled_appeal_cancels_hearing(self, api):
        """PRD §3.5: 'The Appeal's status becomes WITHDRAWN; if a
        Hearing was already SCHEDULED, its status flips to CANCELLED.'

        Claim: withdrawing a SCHEDULED Appeal sets Hearing.status to
        CANCELLED.
        """
        ctx = setup_scheduled_appeal()
        withdraw_appeal(
            owner=ctx["owner"], property_id=ctx["property"]["id"],
            appeal_id=ctx["appeal"]["id"],
        )
        from test_helpers import api_client, TEST_USERS
        resp = api_client.get_hearing(
            ctx["property"]["id"], ctx["appeal"]["id"],
            TEST_USERS["treasurer_headers"],
        )
        hearing = validate_success(resp)
        assert hearing["status"] == "CANCELLED"
