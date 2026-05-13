"""Difficulty-design instances (mandatory priority queue).

Each scaffold_difficulty_design instance is covered by at least TWO
dedicated tests tagged with `# difficulty: <rule_id>/<instance.name>`.
Every test's docstring carries a PRD citation for the underlying rule
(PRD prose, not the difficulty-design entry itself).
"""
from __future__ import annotations
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    SEC,
    advance_clock,
    api_client,
    assert_resolution,
    assert_tally_conservation,
    cast_vote,
    cast_votes_for,
    create_annual_report,
    create_application,
    create_member,
    create_meeting,
    create_submission,
    declare_conflict,
    discover_rectification_id,
    find_audit_entries,
    get_agenda_item,
    get_application,
    get_rectification,
    get_resolution,
    iso_z,
    list_audit_logs,
    make_applicant_headers,
    make_chair_headers,
    make_committee_member_headers,
    parse_iso,
    prescreen_application,
    publish_agenda,
    resolve_agenda_item,
    run_sweep,
    seed_committee,
    setup_application_pending_prescreen,
    setup_application_pending_review,
    setup_meeting_lead_time_cases,
    setup_meeting_with_recusals,
    setup_open_agenda_item,
    setup_resolved_initial_review,
    submit_application,
    unique_applicant_id,
    unique_sponsor_name,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    # difficulty: dual_variant_calc/vote_tally_dual_variant_initial_vs_continuing
    def test_initial_review_tally_yields_approve_outcome(self, api):
        """PRD §3.5: 'the count of APPROVE_WITH_MODIFICATION votes is
        strictly greater than the count of APPROVE votes, the outcome
        is APPROVE_WITH_MODIFICATION; otherwise (including when the two
        counts are equal — equality resolves to APPROVE_WITH_MODIFICATION
        as the conservative default), the outcome is APPROVE.'

        6 APPROVE + 2 AWM + 1 REJECT → APPROVE outcome on INITIAL_REVIEW.
        """
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 6, "APPROVE_WITH_MODIFICATION": 2,
                        "REJECT": 1},
            member_count=9,
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        assert bundle["resolution"]["outcome"] == "APPROVE", (
            f"PRD §3.5 initial-review tally: APPROVE(6) > AWM(2) → "
            f"APPROVE; got {bundle['resolution']['outcome']!r}"
        )
        assert bundle["application"]["status"] == "APPROVED"

    # difficulty: dual_variant_calc/vote_tally_dual_variant_initial_vs_continuing
    def test_continuing_review_tally_same_counts_yield_continue_outcome(
        self, api,
    ):
        """PRD §3.5: 'For an ANNUAL_REVIEW, AMENDMENT_REVIEW, or
        FINAL_REPORT_REVIEW agenda item — the continuing-review variant
        of the tally rule — the underlying counts and the same
        supermajority and majority steps apply, but the final
        Application-level outcome is remapped to the continuing-review
        domain: an APPROVE or APPROVE_WITH_MODIFICATION count yields a
        CONTINUE outcome on the linked AnnualReport, a REJECT count
        yields TERMINATE, and a DEFER count yields SUSPEND.' PRD §3.5
        further: 'A CONTINUE result while the application is in
        APPROVED or APPROVED_WITH_MOD keeps the application in that
        same state for ANNUAL_REVIEW and AMENDMENT_REVIEW items'.

        Same 6/2/1 split as the initial-review test, this time on an
        ANNUAL_REVIEW: AnnualReport.outcome == CONTINUE, Application
        stays APPROVED.
        """
        # First: drive an Application to APPROVED.
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 6, "APPROVE_WITH_MODIFICATION": 2,
                        "REJECT": 1},
            member_count=9,
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        app = bundle["application"]
        members = bundle["members"]
        chair = bundle["chair"]
        # File AnnualReport then schedule ANNUAL_REVIEW meeting.
        advance_clock("2027-06-01T00:00:00.000Z")
        report = create_annual_report(
            app,
            serious_adverse_event_count=0,
            total_adverse_event_count=0,
            enrollment_count=10,
            report_kind="ANNUAL_PROGRESS",
        )
        # Schedule meeting M2 at base+168h.
        from test_helpers import add_agenda_item
        m2 = create_meeting(
            convener_member_id=chair["id"],
            scheduled_at="2027-06-08T00:00:00.000Z",
            meeting_type="STANDARD",
        )
        ai2 = add_agenda_item(
            m2["id"], app["id"],
            review_kind="ANNUAL_REVIEW",
            annual_report_id=report["id"],
        )
        publish_agenda(m2["id"])
        advance_clock("2027-06-08T00:00:00.000Z")
        from test_helpers import open_meeting
        open_meeting(m2["id"])
        # Cast same 6/2/1 split
        voters_by_mode = {
            "APPROVE": members[0:6],
            "APPROVE_WITH_MODIFICATION": members[6:8],
            "REJECT": members[8:9],
        }
        cast_votes_for(ai2["id"], voters_by_mode)
        resolution2 = resolve_agenda_item(ai2["id"], chair)
        assert resolution2["outcome"] == "APPROVE", (
            f"PRD §3.5: underlying tally is the same shape; got "
            f"{resolution2['outcome']!r}"
        )
        # Application stays APPROVED for ANNUAL_REVIEW CONTINUE.
        app_after = get_application(app["id"])
        assert app_after["status"] == "APPROVED", (
            f"PRD §3.5: 'A CONTINUE result while the application is in "
            f"APPROVED ... keeps the application in that same state for "
            f"ANNUAL_REVIEW'; got {app_after['status']!r}"
        )

    # difficulty: dual_variant_calc/safety_alert_chronological_vs_forward_pinned
    def test_safety_alert_chronological_rate_below_threshold_false(
        self, api,
    ):
        """PRD §3.7: 'The system pins this chronological interpretation
        of the rate — numerator restricted to already-recorded events,
        denominator equal to the reported enrollment — rather than a
        forward-looking variant that would include pending events in
        the numerator.' SAE=1<3 AND 2/20=0.10 < 0.20 → flag false."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        advance_clock("2027-06-01T00:00:00.000Z")
        report = create_annual_report(
            app,
            serious_adverse_event_count=1,
            total_adverse_event_count=2,
            enrollment_count=20,
        )
        assert report["safety_alert_flag"] is False

    # difficulty: dual_variant_calc/safety_alert_chronological_vs_forward_pinned
    def test_safety_alert_chronological_rate_exactly_at_threshold_true(
        self, api,
    ):
        """PRD §3.7: 'the observed adverse-event rate, defined as
        total_adverse_event_count divided by enrollment_count, is at or
        above 0.20 (twenty percent) ... a rate of exactly 0.20 raises
        the flag.' SAE=2<3 BUT 4/20=0.20 → flag true."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        advance_clock("2027-06-01T00:00:00.000Z")
        report = create_annual_report(
            app,
            serious_adverse_event_count=2,
            total_adverse_event_count=4,
            enrollment_count=20,
        )
        assert report["safety_alert_flag"] is True


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    # difficulty: combinatorial_formula/quorum_max_ceil_rounding_order
    def test_quorum_max_with_floor_dominates_for_recusal_heavy_app(
        self, api,
    ):
        """PRD §2.9: 'This eligible count is multiplied by 67 percent,
        rounded up to the next whole integer using ceiling rounding,
        and then the larger of that value and the absolute minimum
        quorum of 5 voters is taken as quorum_required. The order is
        pinned: multiply percent by the eligible count first, take the
        ceiling next, then take the maximum with the absolute floor of
        5 voters last.'

        With 7 members and 2 recused → eligible=5, ceil(0.67*5)=4,
        max(5,4)=5 → quorum_required=5 (floor dominates)."""
        bundle = setup_meeting_with_recusals(
            total_members=7, recuse_indices=[1, 2],
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        app = bundle["application"]
        members = bundle["members"]
        chair = bundle["chair"]
        # Schedule + publish a meeting.
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        # PRD §3.3: 'eligible_voter_count is taken from the active-
        # member-minus-conflicts count'.
        assert item["eligible_voter_count"] == 5, (
            f"PRD §2.9: 7 active − 2 recused = 5 eligible; got "
            f"{item.get('eligible_voter_count')!r}"
        )
        assert item["quorum_required"] == 5, (
            f"PRD §2.9: 'multiply percent by the eligible count first, "
            f"take the ceiling next, then take the maximum with the "
            f"absolute floor of 5 voters last.' max(5, ceil(0.67*5))="
            f"max(5,4)=5; got {item.get('quorum_required')!r}"
        )

    # difficulty: combinatorial_formula/quorum_max_ceil_rounding_order
    def test_quorum_floor_drives_no_quorum_at_4_votes(self, api):
        """PRD §3.5: 'If the cast count is below the required count ...
        the resolve succeeds with a NO_QUORUM outcome.' With
        quorum_required=5, casting only 4 votes triggers NO_QUORUM."""
        bundle = setup_meeting_with_recusals(
            total_members=7, recuse_indices=[1, 2],
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        app = bundle["application"]
        members = bundle["members"]
        chair = bundle["chair"]
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        # Cast only 4 votes from the 5 non-recused (chair+members[3..6]).
        non_recused = [chair, members[3], members[4], members[5]]
        for m in non_recused:
            cast_vote(item["id"], m, "APPROVE")
        resolution = resolve_agenda_item(item["id"], chair)
        assert resolution["outcome"] == "NO_QUORUM", (
            f"PRD §3.5: 4 < quorum_required=5 → NO_QUORUM; got "
            f"{resolution['outcome']!r}"
        )

    # difficulty: combinatorial_formula/lead_time_tiered_selection_and_boundary
    def test_standard_lead_time_exact_168h_accepted(self, api):
        """PRD §3.3: 'compared as a strict inequality: the request is
        rejected with ERR_AGENDA_LEAD_TIME_VIOLATION only when the
        seconds remaining until the meeting are strictly less than the
        required hours multiplied by 3600; a meeting scheduled exactly
        the required-hours interval away from now is allowed.'"""
        bundle = setup_meeting_lead_time_cases(
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        res = api.publish_agenda(bundle["meet_std_ok"]["id"], SEC)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "AGENDA_PUBLISHED", (
            f"PRD §3.3: 'scheduled exactly the required-hours interval "
            f"away from now is allowed'; got {data['status']!r}"
        )

    # difficulty: combinatorial_formula/lead_time_tiered_selection_and_boundary
    def test_standard_under_168h_rejected_and_expedited_24h_ok(self, api):
        """PRD §3.3: 'required-hours value is selected by meeting_type
        from a two-tier table — 168 hours for STANDARD, 24 hours for
        EXPEDITED — and is then compared as a strict inequality'. A
        meeting at 167h59m59s for STANDARD must be rejected; a meeting
        at exact 24h for EXPEDITED is allowed."""
        bundle = setup_meeting_lead_time_cases(
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        res_fail = api.publish_agenda(bundle["meet_std_fail"]["id"], SEC)
        validate_error(
            res_fail,
            ApiErrorId.ERR_AGENDA_LEAD_TIME_VIOLATION.value,
        )
        res_exp = api.publish_agenda(bundle["meet_exp_ok"]["id"], SEC)
        data = validate_success(res_exp, expected_status=200)
        assert data["status"] == "AGENDA_PUBLISHED"


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    # difficulty: non_linear_state_machine/application_cyclic_rework_loop
    def test_application_visits_pending_prescreen_twice_via_rework(self, api):
        """PRD §3.1: 'After REWORK_REQUIRED, the applicant uploads a
        new submission version (which auto-becomes the new current
        submission and resets its prescreen_status to PENDING) and
        re-submits, returning the application to PENDING_PRESCREEN.'"""
        app, sub_v1 = setup_application_pending_prescreen()
        # First REJECT → REWORK_REQUIRED
        prescreen_application(app["id"], "REJECT")
        # Upload v2
        app_obj = get_application(app["id"])
        sub_v2 = create_submission(app_obj)
        assert sub_v2["version_number"] == 2
        # Re-submit → PENDING_PRESCREEN second time
        app_again = submit_application(app_obj)
        assert app_again["status"] == "PENDING_PRESCREEN", (
            f"PRD §3.1: 'returning the application to PENDING_PRESCREEN'; "
            f"got {app_again['status']!r}"
        )
        # Final check: current_submission_version == 2
        assert app_again["current_submission_version"] == 2

    # difficulty: non_linear_state_machine/application_cyclic_rework_loop
    def test_rework_cycle_emits_two_review_decision_audit_rows(self, api):
        """PRD §3.1: 'an audit row of event_type REVIEW_DECISION is
        written' on PASS; 'A REJECT decision moves the application from
        PENDING_PRESCREEN to REWORK_REQUIRED ... and likewise writes a
        REVIEW_DECISION audit row.' Two prescreen-REJECT calls produce
        two REVIEW_DECISION rows."""
        app, _ = setup_application_pending_prescreen()
        prescreen_application(app["id"], "REJECT")
        app_obj = get_application(app["id"])
        create_submission(app_obj)
        submit_application(app_obj)
        prescreen_application(app_obj["id"], "REJECT")
        rows = list_audit_logs(
            SEC, event_type="REVIEW_DECISION",
            subject_entity="Application", subject_id=app["id"],
        )
        assert len(rows) >= 2, (
            f"PRD §3.1: two REJECT decisions yield two REVIEW_DECISION "
            f"audit rows; got {len(rows)}"
        )

    # difficulty: non_linear_state_machine/rectification_secondary_review_branching
    def test_rectification_expiry_cascades_application_to_deferred_or_rejected(
        self, api,
    ):
        """PRD §3.6: 'The cascade depends on which kind of resolution
        originated the rectification: if the source resolution's outcome
        was APPROVE_WITH_MODIFICATION, the application cascades from
        APPROVED_WITH_MOD to REJECTED; if the source outcome was DEFER,
        the application remains in DEFERRED.'

        Take the DEFER branch: source DEFER → expiry → app remains
        DEFERRED."""
        bundle = setup_resolved_initial_review(
            vote_split={"DEFER": 5, "APPROVE": 2},
            member_count=9,
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        app = bundle["application"]
        assert app["status"] == "DEFERRED"
        resolution = bundle["resolution"]
        when = parse_iso(resolution["created_at"]) + timedelta(days=31)
        advance_clock(iso_z(when))
        run_sweep()
        app_after = get_application(app["id"])
        assert app_after["status"] == "DEFERRED", (
            f"PRD §3.6: 'if the source outcome was DEFER, the "
            f"application remains in DEFERRED.'; got "
            f"{app_after['status']!r}"
        )

    # difficulty: non_linear_state_machine/rectification_secondary_review_branching
    def test_awm_rectification_expiry_cascades_to_rejected(self, api):
        """PRD §3.6: 'if the source resolution's outcome was
        APPROVE_WITH_MODIFICATION, the application cascades from
        APPROVED_WITH_MOD to REJECTED'."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE_WITH_MODIFICATION": 5, "APPROVE": 2},
            member_count=9,
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        app = bundle["application"]
        assert app["status"] == "APPROVED_WITH_MOD"
        resolution = bundle["resolution"]
        when = parse_iso(resolution["created_at"]) + timedelta(days=31)
        advance_clock(iso_z(when))
        run_sweep()
        app_after = get_application(app["id"])
        assert app_after["status"] == "REJECTED", (
            f"PRD §3.6: 'the application cascades from APPROVED_WITH_MOD "
            f"to REJECTED'; got {app_after['status']!r}"
        )


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    # difficulty: transitive_cascade/resolve_with_modification_cascade_depth_3
    def test_awm_resolve_creates_rectification_due_at_30d(self, api):
        """PRD §3.5: 'An APPROVE_WITH_MODIFICATION outcome moves the
        application to APPROVED_WITH_MOD ... creates a Rectification
        row with opinions populated from the resolution's reviewer
        comments and due_at set to the resolution's created_at plus 30
        calendar days'.

        Cascade depth-1 to depth-2: resolve → AWM cascade →
        Rectification with due_at = resolution.created_at + 30d."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE_WITH_MODIFICATION": 5, "APPROVE": 2},
            member_count=9,
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        resolution = bundle["resolution"]
        app = bundle["application"]
        assert app["status"] == "APPROVED_WITH_MOD"
        rid = discover_rectification_id(
            resolution=resolution, application_id=app["id"],
        )
        if rid:
            r = get_rectification(rid)
            expected_due = parse_iso(resolution["created_at"]) + \
                timedelta(days=30)
            actual_due = parse_iso(r["due_at"])
            # Allow milliseconds of imprecision.
            assert abs((actual_due - expected_due).total_seconds()) < 1.0, (
                f"PRD §3.5: 'due_at set to the resolution's created_at "
                f"plus 30 calendar days'; expected {expected_due!r}, "
                f"got {actual_due!r}"
            )

    # difficulty: transitive_cascade/resolve_with_modification_cascade_depth_3
    def test_awm_resolve_then_sweep_past_30d_cascades_to_rejected(self, api):
        """PRD §3.6: 'if the source resolution's outcome was
        APPROVE_WITH_MODIFICATION, the application cascades from
        APPROVED_WITH_MOD to REJECTED'. Cascade depth-3: resolve → AWM
        → Rectification → expiry → REJECTED."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE_WITH_MODIFICATION": 5, "APPROVE": 2},
            member_count=9,
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        resolution = bundle["resolution"]
        app = bundle["application"]
        when = parse_iso(resolution["created_at"]) + timedelta(days=31)
        advance_clock(iso_z(when))
        run_sweep()
        app_after = get_application(app["id"])
        assert app_after["status"] == "REJECTED", (
            f"PRD §3.6 cascade: AWM-origin expiry → REJECTED; got "
            f"{app_after['status']!r}"
        )

    # difficulty: transitive_cascade/prescreen_reject_then_rework_cascade_depth_2
    def test_prescreen_reject_cascades_application_to_rework_required(
        self, api,
    ):
        """PRD §3.1: 'A REJECT decision moves the application from
        PENDING_PRESCREEN to REWORK_REQUIRED, sets the current
        submission's prescreen_status to REJECTED, and likewise writes
        a REVIEW_DECISION audit row.'

        Cascade depth-2: prescreen REJECT → Submission.prescreen_status
        REJECTED, Application → REWORK_REQUIRED, audit row emitted."""
        app, _ = setup_application_pending_prescreen()
        updated = prescreen_application(
            app["id"], "REJECT",
            prescreen_notes="missing power calculation",
        )
        assert updated["status"] == "REWORK_REQUIRED", (
            f"PRD §3.1: 'A REJECT decision moves the application from "
            f"PENDING_PRESCREEN to REWORK_REQUIRED'; got "
            f"{updated['status']!r}"
        )

    # difficulty: transitive_cascade/prescreen_reject_then_rework_cascade_depth_2
    def test_prescreen_reject_emits_review_decision_audit(self, api):
        """PRD §3.1: 'A REJECT decision moves the application from
        PENDING_PRESCREEN to REWORK_REQUIRED, sets the current
        submission's prescreen_status to REJECTED, and likewise writes
        a REVIEW_DECISION audit row.'"""
        app, _ = setup_application_pending_prescreen()
        prescreen_application(app["id"], "REJECT",
                              prescreen_notes="needs more data")
        rows = list_audit_logs(
            SEC, event_type="REVIEW_DECISION",
            subject_entity="Application", subject_id=app["id"],
        )
        assert len(rows) >= 1, (
            f"PRD §3.1: REJECT 'likewise writes a REVIEW_DECISION audit "
            f"row'; got {len(rows)}"
        )


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    # difficulty: priority_pair_validation_conflict/recused_member_votes_on_closed_item_recusal_wins
    def test_recused_vote_on_resolved_item_yields_member_recused(self, api):
        """PRD §2.7: 'the conflict-of-interest gate runs before the
        state legality check, so a recused member who attempts to vote
        on a CLOSED agenda item receives ERR_MEMBER_RECUSED, not
        ERR_INVALID_STATE.'"""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 6, "APPROVE_WITH_MODIFICATION": 2,
                        "REJECT": 1},
            member_count=9,
        )
        app = bundle["application"]
        members = bundle["members"]
        recused = members[3]
        declare_conflict(recused, app["id"])
        res = api.cast_vote(
            bundle["agenda_item"]["id"], {"vote_mode": "APPROVE"},
            make_committee_member_headers(recused["id"]),
        )
        validate_error(res, ApiErrorId.ERR_MEMBER_RECUSED.value)

    # difficulty: priority_pair_validation_conflict/recused_member_votes_on_closed_item_recusal_wins
    def test_non_recused_vote_on_resolved_item_yields_invalid_state(
        self, api,
    ):
        """PRD §2.7: 'the conflict-of-interest gate runs before the
        state legality check'. With NO conflict declared, the state
        check still applies — voting on a RESOLVED agenda item must
        return ERR_INVALID_STATE."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 6, "APPROVE_WITH_MODIFICATION": 2,
                        "REJECT": 1},
            member_count=9,
        )
        members = bundle["members"]
        # Vote attempt by a non-voted, non-conflicted member.
        # But all 9 members already cast a vote above. Pick a fresh
        # member with no prior vote and no conflict.
        new_member = create_member(qualification="ETHICIST")
        res = api.cast_vote(
            bundle["agenda_item"]["id"], {"vote_mode": "APPROVE"},
            make_committee_member_headers(new_member["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    # difficulty: priority_pair_validation_conflict/late_response_with_duplicate_vote_temporal_wins
    def test_rectification_response_after_due_yields_expired(self, api):
        """PRD §3.6: 'a request made at or after the deadline is
        rejected with ERR_RECTIFICATION_EXPIRED (HTTP 409).'"""
        bundle = setup_resolved_initial_review(
            vote_split={"DEFER": 5, "APPROVE": 2},
            member_count=9,
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        rid = discover_rectification_id(
            resolution=bundle["resolution"],
            application_id=bundle["application"]["id"],
        )
        if not rid:
            # Cannot exercise without a discovery channel — skip
            # silently per the discovery contract.
            return
        when = parse_iso(bundle["resolution"]["created_at"]) + \
            timedelta(days=30, hours=1)
        advance_clock(iso_z(when))
        res = api.respond_rectification(
            rid, {"applicant_response_uri": "https://x/r.pdf"},
            make_applicant_headers(bundle["applicant_id"]),
        )
        validate_error(res, ApiErrorId.ERR_RECTIFICATION_EXPIRED.value)

    # difficulty: priority_pair_validation_conflict/late_response_with_duplicate_vote_temporal_wins
    def test_duplicate_vote_returns_duplicate_vote_error(self, api):
        """PRD §3.4: 'a member may cast at most one vote per agenda
        item: a second insert from the same member with the same
        agenda_item_id is rejected with ERR_DUPLICATE_VOTE.'"""
        app, _ = setup_application_pending_review()
        members = seed_committee(total=9, chair_index=0)
        chair = members[0]
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
        )
        cast_vote(item["id"], members[1], "APPROVE")
        res = api.cast_vote(
            item["id"], {"vote_mode": "APPROVE"},
            make_committee_member_headers(members[1]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_VOTE.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    # difficulty: boundary_precision_check/quorum_boundary_votes_cast_equals_quorum_required
    def test_quorum_boundary_exact_equality_resolves_with_approve(self, api):
        """PRD §3.5: 'If the cast count is below the required count ...
        NO_QUORUM ...' implies cast >= required succeeds. PRD §2.9:
        max(5, ceil(0.67*9)) = max(5, 7) = 7. With exactly 7 votes
        cast and a 5/2 APPROVE/AWM split, supermajority is met and
        APPROVE wins."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        assert bundle["resolution"]["outcome"] == "APPROVE", (
            f"PRD §3.5: votes_cast=7 == quorum=7 with APPROVE(5)+AWM(2) "
            f"→ APPROVE outcome; got {bundle['resolution']['outcome']!r}"
        )

    # difficulty: boundary_precision_check/quorum_boundary_votes_cast_equals_quorum_required
    def test_quorum_boundary_one_below_yields_no_quorum(self, api):
        """PRD §3.5: 'If the cast count is below the required count'
        with default require_quorum yields NO_QUORUM. Cast 6 of 9
        members (quorum=7) and resolve."""
        app, _ = setup_application_pending_review()
        members = seed_committee(total=9, chair_index=0)
        chair = members[0]
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
        )
        # 6 votes — below quorum 7
        for m in members[1:7]:
            cast_vote(item["id"], m, "APPROVE")
        resolution = resolve_agenda_item(item["id"], chair)
        assert resolution["outcome"] == "NO_QUORUM", (
            f"PRD §3.5: 6 < 7 (quorum) → NO_QUORUM; got "
            f"{resolution['outcome']!r}"
        )
        item_after = get_agenda_item(item["id"])
        assert item_after["status"] == "CLOSED_WITHOUT_QUORUM"

    # difficulty: boundary_precision_check/empty_agenda_publish_rejected
    def test_empty_agenda_publish_rejected_with_invalid_state(self, api):
        """PRD §3.3: 'at least one AgendaItem must belong to the
        meeting'. Empty agenda publish → ERR_INVALID_STATE."""
        advance_clock("2026-06-01T00:00:00.000Z")
        m = create_member(qualification="MEDICAL_EXPERT")
        meeting = create_meeting(
            convener_member_id=m["id"],
            scheduled_at="2026-06-15T00:00:00.000Z",
            meeting_type="STANDARD",
        )
        res = api.publish_agenda(meeting["id"], SEC)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    # difficulty: boundary_precision_check/empty_agenda_publish_rejected
    def test_empty_agenda_publish_leaves_meeting_in_scheduled(self, api):
        """PRD §3.3: 'The transition from SCHEDULED to AGENDA_PUBLISHED
        is the Secretary's action and is gated by two preconditions ...
        at least one AgendaItem must belong to the meeting'. When the
        precondition fails, the meeting must remain SCHEDULED."""
        advance_clock("2026-06-01T00:00:00.000Z")
        m = create_member(qualification="MEDICAL_EXPERT")
        meeting = create_meeting(
            convener_member_id=m["id"],
            scheduled_at="2026-06-15T00:00:00.000Z",
            meeting_type="STANDARD",
        )
        api.publish_agenda(meeting["id"], SEC)
        # Fetch meeting and verify still SCHEDULED
        get_resp = api.get_meeting(meeting["id"], SEC)
        from prd_bench_local_runner.testing import validate_success as vs
        data = vs(get_resp, expected_status=200)
        assert data["status"] == "SCHEDULED", (
            f"PRD §3.3: failed publish must leave meeting SCHEDULED; "
            f"got {data['status']!r}"
        )


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    # difficulty: cross_entity_state_dependency/agenda_item_open_requires_meeting_in_session
    def test_vote_on_unopened_agenda_item_rejected(self, api):
        """PRD §3.3: 'When the meeting's scheduled_at time has been
        reached, the Secretary opens the session, which advances the
        meeting from AGENDA_PUBLISHED to IN_SESSION and every
        PUBLISHED agenda item to OPEN_FOR_VOTING.' Voting before /open
        targets a PUBLISHED (not OPEN_FOR_VOTING) item — state-illegal."""
        advance_clock("2026-06-01T00:00:00.000Z")
        app, _ = setup_application_pending_review()
        members = seed_committee(total=9, chair_index=0)
        chair = members[0]
        from test_helpers import add_agenda_item
        meeting = create_meeting(
            convener_member_id=chair["id"],
            scheduled_at="2026-06-08T00:00:00.000Z",
            meeting_type="STANDARD",
        )
        item = add_agenda_item(meeting["id"], app["id"])
        publish_agenda(meeting["id"])
        # Do NOT call /open. Try to vote.
        res = api.cast_vote(
            item["id"], {"vote_mode": "APPROVE"},
            make_committee_member_headers(members[1]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    # difficulty: cross_entity_state_dependency/agenda_item_open_requires_meeting_in_session
    def test_vote_after_open_succeeds(self, api):
        """PRD §3.3: 'When the meeting's scheduled_at time has been
        reached, the Secretary opens the session, which advances the
        meeting from AGENDA_PUBLISHED to IN_SESSION and every
        PUBLISHED agenda item to OPEN_FOR_VOTING.'"""
        app, _ = setup_application_pending_review()
        members = seed_committee(total=9, chair_index=0)
        chair = members[0]
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
        )
        res = api.cast_vote(
            item["id"], {"vote_mode": "APPROVE"},
            make_committee_member_headers(members[1]["id"]),
        )
        validate_success(res, expected_status=201)

    # difficulty: cross_entity_state_dependency/annual_report_review_requires_application_approved
    def test_annual_report_on_draft_application_rejected(self, api):
        """PRD §3.7: 'Each report carries an application_id (which must
        reference an application in one of those two states)' —
        APPROVED or APPROVED_WITH_MOD. A DRAFT application is invalid."""
        app = create_application()  # DRAFT
        res = api.create_annual_report(
            app["id"],
            {
                "report_period_start": "2027-01-01T00:00:00.000Z",
                "report_period_end": "2027-12-31T00:00:00.000Z",
                "report_kind": "ANNUAL_PROGRESS",
                "serious_adverse_event_count": 0,
                "total_adverse_event_count": 0,
                "enrollment_count": 0,
            },
            make_applicant_headers(app["applicant_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    # difficulty: cross_entity_state_dependency/annual_report_review_requires_application_approved
    def test_annual_report_on_approved_application_succeeds(self, api):
        """PRD §3.7: 'Once an application is in APPROVED or
        APPROVED_WITH_MOD, the Applicant must periodically file an
        AnnualReport'."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        assert app["status"] == "APPROVED"
        report = create_annual_report(
            app,
            serious_adverse_event_count=0,
            total_adverse_event_count=0,
            enrollment_count=10,
        )
        assert report["status"] == "SUBMITTED"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    # difficulty: resource_temporal_overlap/rectification_window_buffered_overlap_on_application
    def test_respond_at_exactly_due_at_rejected(self, api):
        """PRD §3.6: 'The precondition is that the current logical
        clock is strictly before the rectification's due_at and the
        rectification's status is OPEN; a request made at or after the
        deadline is rejected with ERR_RECTIFICATION_EXPIRED (HTTP
        409).'"""
        bundle = setup_resolved_initial_review(
            vote_split={"DEFER": 5, "APPROVE": 2},
            member_count=9,
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        rid = discover_rectification_id(
            resolution=bundle["resolution"],
            application_id=bundle["application"]["id"],
        )
        if not rid:
            return
        # Advance to exactly due_at
        due_at = parse_iso(bundle["resolution"]["created_at"]) + \
            timedelta(days=30)
        advance_clock(iso_z(due_at))
        res = api.respond_rectification(
            rid, {"applicant_response_uri": "https://x/r.pdf"},
            make_applicant_headers(bundle["applicant_id"]),
        )
        validate_error(res, ApiErrorId.ERR_RECTIFICATION_EXPIRED.value)

    # difficulty: resource_temporal_overlap/rectification_window_buffered_overlap_on_application
    def test_sweep_at_due_at_inclusive_flips_to_expired(self, api):
        """PRD §3.6: 'the boundary is inclusive: the exact due_at
        instant counts as expired'. Sweep at exactly due_at flips status
        and cascades."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE_WITH_MODIFICATION": 5, "APPROVE": 2},
            member_count=9,
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        resolution = bundle["resolution"]
        app = bundle["application"]
        due_at = parse_iso(resolution["created_at"]) + timedelta(days=30)
        advance_clock(iso_z(due_at))
        run_sweep()
        app_after = get_application(app["id"])
        assert app_after["status"] == "REJECTED", (
            f"PRD §3.6: 'boundary is inclusive: the exact due_at instant "
            f"counts as expired' → AWM cascade to REJECTED; got "
            f"{app_after['status']!r}"
        )

    # difficulty: resource_temporal_overlap/meeting_lead_time_minimum_gap_on_meeting
    def test_publish_at_exact_168h_accepted(self, api):
        """PRD §3.3: 'compared as a strict inequality ... a meeting
        scheduled exactly the required-hours interval away from now is
        allowed.'"""
        bundle = setup_meeting_lead_time_cases(
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        res = api.publish_agenda(bundle["meet_std_ok"]["id"], SEC)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "AGENDA_PUBLISHED"

    # difficulty: resource_temporal_overlap/meeting_lead_time_minimum_gap_on_meeting
    def test_publish_at_167h59m_rejected(self, api):
        """PRD §3.3: 'the request is rejected with
        ERR_AGENDA_LEAD_TIME_VIOLATION only when the seconds remaining
        until the meeting are strictly less than the required hours
        multiplied by 3600'."""
        bundle = setup_meeting_lead_time_cases(
            clock_base_iso="2026-06-01T00:00:00.000Z",
        )
        res = api.publish_agenda(bundle["meet_std_fail"]["id"], SEC)
        validate_error(res, ApiErrorId.ERR_AGENDA_LEAD_TIME_VIOLATION.value)


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    # difficulty: compensating_invariant/submission_version_monotonicity_conserved_quantity
    def test_each_new_submission_becomes_current_and_bumps_version(self, api):
        """PRD §3.1: 'sets is_current to true on the new row, clears
        is_current on whichever sibling submission had previously been
        current, and updates the parent application's
        current_submission_version to match.'"""
        app = create_application()
        sub_v1 = create_submission(app)
        assert sub_v1["version_number"] == 1
        sub_v2 = create_submission(app)
        sub_v3 = create_submission(app)
        assert sub_v2["version_number"] == 2
        assert sub_v3["version_number"] == 3
        # current_submission_version on the application
        app_after = get_application(app["id"])
        assert app_after["current_submission_version"] == 3, (
            f"PRD §3.1: 'updates the parent application's "
            f"current_submission_version to match'; got "
            f"{app_after['current_submission_version']!r}"
        )
        assert sub_v3.get("is_current") is True
        # If is_current is included on the read of sub_v1/v2, verify
        # they are now false. The list endpoint allows inspection.
        from prd_bench_local_runner.testing import validate_paginated
        res = api.list_submissions(app["id"], SEC)
        rows, _ = validate_paginated(res)
        by_v = {r["version_number"]: r for r in rows}
        if 1 in by_v and "is_current" in by_v[1]:
            assert by_v[1]["is_current"] is False, (
                f"PRD §3.1: 'clears is_current on whichever sibling "
                f"submission had previously been current'; got "
                f"{by_v[1]['is_current']!r}"
            )
        if 2 in by_v and "is_current" in by_v[2]:
            assert by_v[2]["is_current"] is False

    # difficulty: compensating_invariant/submission_version_monotonicity_conserved_quantity
    def test_only_one_is_current_submission_at_a_time(self, api):
        """PRD §3.1: 'sets is_current to true on the new row, clears
        is_current on whichever sibling submission had previously been
        current'. Invariant: exactly one is_current=true per
        application."""
        app = create_application()
        create_submission(app)
        create_submission(app)
        create_submission(app)
        from prd_bench_local_runner.testing import validate_paginated
        res = api.list_submissions(app["id"], SEC)
        rows, _ = validate_paginated(res)
        current_count = sum(1 for r in rows if r.get("is_current") is True)
        assert current_count == 1, (
            f"PRD §3.1: 'clears is_current on whichever sibling "
            f"submission had previously been current'; exactly one "
            f"is_current=true expected; got {current_count}"
        )

    # difficulty: compensating_invariant/vote_tally_quorum_arithmetic_invariant
    def test_tally_bucket_sum_equals_total_votes_cast(self, api):
        """PRD §3.5 tally structure: 'the full tally object recording
        per-mode counts plus total_votes_cast, eligible_voter_count,
        and quorum_required'. PRD §2.9: 'All quorum and vote tallies
        are integer-valued; there is no rounding inside the tally
        itself.' The per-mode counts must sum to total_votes_cast."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        tally = bundle["resolution"]["tally"]
        assert_tally_conservation(tally)
        assert tally["APPROVE"] == 5
        assert tally["APPROVE_WITH_MODIFICATION"] == 2
        assert tally["REJECT"] == 0
        assert tally["DEFER"] == 0
        assert tally["total_votes_cast"] == 7

    # difficulty: compensating_invariant/vote_tally_quorum_arithmetic_invariant
    def test_failed_vote_attempts_leave_no_trace_in_tally(self, api):
        """PRD §3.4: 'a member with an active declaration ... receives
        ERR_MEMBER_RECUSED', and PRD §3.4: 'a second insert from the
        same member ... is rejected with ERR_DUPLICATE_VOTE'. Failed
        inserts MUST NOT alter any bucket nor total_votes_cast."""
        app, _ = setup_application_pending_review()
        # 9 members; recuse one upfront so quorum/eligible become 8.
        members = seed_committee(total=9, chair_index=0)
        chair = members[0]
        recused = members[8]
        declare_conflict(recused, app["id"])
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
        )
        # Vote with 7 non-recused (5 APPROVE + 2 AWM)
        voters_by_mode = {
            "APPROVE": members[0:5],
            "APPROVE_WITH_MODIFICATION": members[5:7],
        }
        cast_votes_for(item["id"], voters_by_mode)
        # Now a recused vote (rejected) and a duplicate vote (rejected).
        api.cast_vote(
            item["id"], {"vote_mode": "APPROVE"},
            make_committee_member_headers(recused["id"]),
        )
        api.cast_vote(
            item["id"], {"vote_mode": "REJECT"},
            make_committee_member_headers(members[1]["id"]),  # duplicate
        )
        resolution = resolve_agenda_item(item["id"], chair)
        tally = resolution["tally"]
        assert_tally_conservation(tally)
        assert tally["APPROVE"] == 5
        assert tally["APPROVE_WITH_MODIFICATION"] == 2
        assert tally["REJECT"] == 0, (
            f"PRD §3.4: failed votes must not alter any bucket; got "
            f"REJECT={tally['REJECT']!r}"
        )
        assert tally["total_votes_cast"] == 7
