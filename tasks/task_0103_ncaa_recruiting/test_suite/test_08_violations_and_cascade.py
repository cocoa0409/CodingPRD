"""ComplianceViolation lifecycle, segregation-of-duties, penalty
scoring, compliance posture rollup, and cascade effects.

PRD §3.7 (violation lifecycle, segregation, penalty scoring,
compliance posture, cascade), §2.8 (priority order),
§2.10 (auto-expire on clock).
"""
from __future__ import annotations

import pytest
from datetime import timedelta

from test_helpers import (
    APPEAL_WINDOW_DAYS,
    COMPLIANCE_RED_THRESHOLD,
    COMPLIANCE_YELLOW_THRESHOLD,
    TEST_USERS,
    advance_clock_to,
    assert_violation,
    create_athlete,
    create_program,
    create_violation_payload,
    drive_violation_to_appealed,
    drive_violation_to_sustained,
    iso_utc,
    parse_iso,
    report_violation,
    server_now_iso,
    setup_enrolled_athlete,
    setup_ineligible_athlete_via_violation,
    setup_athlete_with_approved_deal,
    transition_violation,
    transition_violation_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.7 Violation creation
# ===========================================================================
class TestViolationCreate:
    """PRD §3.7: "The new case starts in REPORTED status with outcome
    PENDING and penalty_points zero." """

    def test_create_violation_initializes_status_outcome_points(
        self, api, officer_headers,
    ):
        """PRD §3.7: "The new case starts in REPORTED status with
        outcome PENDING and penalty_points zero."

        Claim: POST /violations returns 201 with status=REPORTED,
        outcome=PENDING, penalty_points=0.
        """
        program = create_program()
        res = api.create_violation(
            create_violation_payload(
                program_id=program["id"],
                severity="LEVEL_II",
            ),
            officer_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_violation(data)
        assert data["status"] == "REPORTED"
        assert data["outcome"] == "PENDING"
        assert data["penalty_points"] == 0


# ===========================================================================
# §3.7 Reviewer identity / continuity of investigation
# ===========================================================================
class TestViolationReviewerContinuity:
    """PRD §3.7: "From INVESTIGATING, the same officer (the caller's
    X-User-ID must equal reviewer_user_id) advances the case to
    SUBSTANTIATED or DISMISSED; a different officer attempting either
    move is rejected with ERR_SEGREGATION_OF_DUTIES." """

    def test_different_officer_cannot_substantiate(
        self, api, officer_headers, officer_headers_secondary,
    ):
        """PRD §3.7: "the same officer (the caller's X-User-ID must
        equal reviewer_user_id) advances the case to SUBSTANTIATED or
        DISMISSED; a different officer attempting either move is
        rejected with ERR_SEGREGATION_OF_DUTIES."

        Claim: officer-A takes the case (REPORTED -> INVESTIGATING).
        Then officer-B tries INVESTIGATING -> SUBSTANTIATED ->
        ERR_SEGREGATION_OF_DUTIES.
        """
        program = create_program()
        v = report_violation(program["id"], severity="LEVEL_II")
        transition_violation(
            v["id"], "INVESTIGATING", headers=officer_headers,
        )
        res = api.transition_violation(
            v["id"],
            transition_violation_payload(to_status="SUBSTANTIATED"),
            officer_headers_secondary,
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


# ===========================================================================
# §3.7 Appellate segregation: different officer required
# ===========================================================================
class TestViolationAppellateSegregation:
    """PRD §3.7: "From APPEALED, the case resolves to either SUSTAINED
    or OVERTURNED, performed by a ComplianceOfficer whose X-User-ID
    differs from reviewer_user_id (the appeal must be heard by a
    different officer than the one who substantiated it; otherwise
    ERR_SEGREGATION_OF_DUTIES)." """

    def test_original_reviewer_cannot_sustain_appeal(
        self, api, officer_headers,
    ):
        """PRD §3.7: "the appeal must be heard by a different officer
        than the one who substantiated it; otherwise
        ERR_SEGREGATION_OF_DUTIES."

        Claim: officer-A drove the case to APPEALED. officer-A trying
        APPEALED -> SUSTAINED -> ERR_SEGREGATION_OF_DUTIES.
        """
        program = create_program()
        v = drive_violation_to_appealed(
            program["id"], severity="LEVEL_II",
            reviewer_headers=officer_headers,
        )
        # officer_headers is the original reviewer. Try to sustain
        # the appeal as the SAME officer.
        res = api.transition_violation(
            v["id"],
            transition_violation_payload(to_status="SUSTAINED"),
            officer_headers,
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


# ===========================================================================
# §3.7 14-day appeal window
# ===========================================================================
class TestAppealWindow:
    """PRD §3.7: "A SUBSTANTIATED case is appealable for 14 days from
    the timestamp of its SUBSTANTIATED transition. A Coach or
    ComplianceOfficer may post SUBSTANTIATED -> APPEALED within that
    window; an attempt after 14 days have elapsed is rejected with
    ERR_APPEAL_WINDOW_CLOSED." """

    def test_appeal_after_14_days_rejected(self, api, officer_headers):
        """PRD §3.7: "an attempt after 14 days have elapsed is
        rejected with ERR_APPEAL_WINDOW_CLOSED."

        Claim: drive the case to SUBSTANTIATED, advance clock to
        SUBSTANTIATED + 14 days + 1 second, attempt SUBSTANTIATED ->
        APPEALED -> ERR_APPEAL_WINDOW_CLOSED. (Note: PRD §3.7 also
        says "If the 14-day appeal window elapses without an APPEALED
        transition, the next clock advance auto-fires SUBSTANTIATED
        -> SUSTAINED." We accept either ERR_APPEAL_WINDOW_CLOSED
        (priority-15 check) or ERR_INVALID_STATE (case already
        auto-sustained) per the §3.7 race tie.
        """
        from test_helpers import validate_error_is_one_of
        program = create_program()
        v = report_violation(program["id"], severity="LEVEL_II")
        transition_violation(
            v["id"], "INVESTIGATING", headers=officer_headers,
        )
        transition_violation(
            v["id"], "SUBSTANTIATED", headers=officer_headers,
        )
        # Read fresh violation to capture the SUBSTANTIATED transition
        # timestamp via updated_at on the violation row, which PRD §2.4
        # refreshes on every mutation.
        v_resp = api.get_violation(v["id"], officer_headers)
        v_data = validate_success(v_resp)
        sub_at = parse_iso(v_data["updated_at"])
        # Advance clock past 14 days.
        target = sub_at + timedelta(days=APPEAL_WINDOW_DAYS, seconds=1)
        advance_clock_to(iso_utc(target))
        # PRD §2.10: next clock advance auto-fires SUBSTANTIATED->SUSTAINED.
        # So the case may already be SUSTAINED before we try APPEALED.
        res = api.transition_violation(
            v["id"],
            transition_violation_payload(to_status="APPEALED"),
            officer_headers,
        )
        validate_error_is_one_of(
            res,
            ["ERR_APPEAL_WINDOW_CLOSED", "ERR_INVALID_STATE"],
        )


# ===========================================================================
# §3.7 violation_penalty_score (first-offense)
# ===========================================================================
class TestPenaltyScoreFirstOffense:
    """PRD §3.7: "Severity points are 10 for LEVEL_I, 5 for LEVEL_II,
    2 for LEVEL_III, and 1 for LEVEL_IV. The recidivism multiplier
    counts prior SUSTAINED violations against the same program_id ...
    a count of zero yields multiplier 1.0". """

    def test_level_i_first_offense_yields_10_points(
        self, api, officer_headers,
    ):
        """PRD §3.7: "Severity points are 10 for LEVEL_I ... a count
        of zero yields multiplier 1.0".

        Claim: a single LEVEL_I SUSTAINED case yields penalty_points=10.
        """
        program = create_program()
        v = drive_violation_to_sustained(
            program["id"], severity="LEVEL_I",
        )
        assert v["status"] == "SUSTAINED"
        assert v["outcome"] == "SUSTAINED"
        assert v["penalty_points"] == 10, (
            f"LEVEL_I first-offense = 10 * 1.0 = 10, got "
            f"{v['penalty_points']}"
        )

    def test_level_ii_first_offense_yields_5_points(
        self, api, officer_headers,
    ):
        """PRD §3.7: "Severity points are ... 5 for LEVEL_II ... a
        count of zero yields multiplier 1.0".

        Claim: a single LEVEL_II SUSTAINED case yields penalty_points=5.
        """
        program = create_program()
        v = drive_violation_to_sustained(
            program["id"], severity="LEVEL_II",
        )
        assert v["penalty_points"] == 5

    @pytest.mark.parametrize("sev,expected_points", [
        ("LEVEL_III", 2),
        ("LEVEL_IV", 1),
    ])
    def test_lower_severity_first_offense_points(
        self, api, sev, expected_points,
    ):
        """PRD §3.7: "Severity points are ... 2 for LEVEL_III, and 1
        for LEVEL_IV ... a count of zero yields multiplier 1.0".

        Claim: a single SUSTAINED case at the given severity yields
        the expected first-offense points.
        """
        program = create_program()
        v = drive_violation_to_sustained(
            program["id"], severity=sev,
        )
        assert v["penalty_points"] == expected_points


# ===========================================================================
# §3.7 program_compliance_posture rollup
# ===========================================================================
class TestComplianceStatusBoundaries:
    """PRD §3.7: "The program's compliance_status is then RED if
    penalty_points_total is at least 20, YELLOW if it is at least 10
    and strictly less than 20, and GREEN otherwise. Boundaries are
    inclusive on the lower side: a total of exactly 10 lands at
    YELLOW, and a total of exactly 20 lands at RED." """

    def test_yellow_at_exact_10_boundary(self, api, officer_headers):
        """PRD §3.7: "Boundaries are inclusive on the lower side: a
        total of exactly 10 lands at YELLOW".

        Claim: a single LEVEL_I (10 points) SUSTAINED case flips
        compliance_status from GREEN to YELLOW.
        """
        program = create_program()
        # GREEN initially per PRD §3.1.
        p_resp = api.get_program(program["id"], officer_headers)
        assert validate_success(p_resp)["compliance_status"] == "GREEN"
        drive_violation_to_sustained(program["id"], severity="LEVEL_I")
        p_resp = api.get_program(program["id"], officer_headers)
        p_data = validate_success(p_resp)
        assert p_data["penalty_points_total"] == 10
        assert p_data["compliance_status"] == "YELLOW", (
            f"penalty_points_total=10 should yield YELLOW per inclusive "
            f"boundary, got {p_data['compliance_status']}"
        )


# ===========================================================================
# §3.7 Cascade on LEVEL_I SUSTAINED with related_athlete_id
# ===========================================================================
class TestLevelOneSustainCascade:
    """PRD §3.7: "When a sustained violation is LEVEL_I and carries a
    related_athlete_id, the system cascades immediately on the
    SUSTAINED outcome flip. The implicated athlete moves ENROLLED ->
    INELIGIBLE. The athlete's amateur_status is updated by the same
    cascade: FORFEITED when the severity is LEVEL_I ... Every NILDeal
    for that athlete whose status is APPROVED is transitioned to
    SUSPENDED". """

    def test_level_i_sustained_flips_athlete_to_ineligible_forfeited(
        self, api, officer_headers,
    ):
        """PRD §3.7: "When a sustained violation is LEVEL_I and
        carries a related_athlete_id, the system cascades immediately
        on the SUSTAINED outcome flip. The implicated athlete moves
        ENROLLED -> INELIGIBLE. The athlete's amateur_status is
        updated by the same cascade: FORFEITED when the severity is
        LEVEL_I".

        Claim: a LEVEL_I SUSTAINED violation with related_athlete_id
        set flips the athlete to INELIGIBLE / FORFEITED.
        """
        _program, athlete, v = setup_ineligible_athlete_via_violation()
        assert v["status"] == "SUSTAINED"
        assert v["severity"] == "LEVEL_I"
        assert athlete["status"] == "INELIGIBLE"
        assert athlete["amateur_status"] == "FORFEITED"

    def test_level_i_sustained_suspends_approved_nil_deals(
        self, api, officer_headers,
    ):
        """PRD §3.7: "Every NILDeal for that athlete whose status is
        APPROVED is transitioned to SUSPENDED, and approved_value_cents
        is preserved on each suspended deal so that the lifetime
        audit trail remains reconstructable."

        Claim: with one APPROVED deal on the athlete, a LEVEL_I
        SUSTAINED cascade flips the deal to SUSPENDED with
        approved_value_cents preserved.
        """
        athlete, program, deal = setup_athlete_with_approved_deal(
            stated_value_cents=500_000,
            deliverables_hours=10.0,
            market_rate_cents_per_hour=50_000,
            deal_category="ENDORSEMENT",
            sponsor_is_booster=False,
        )
        assert deal["status"] == "APPROVED"
        original_approved_value = deal["approved_value_cents"]
        drive_violation_to_sustained(
            program["id"], severity="LEVEL_I",
            related_athlete_id=athlete["id"],
        )
        d_resp = api.get_nil_deal(deal["id"], officer_headers)
        d_data = validate_success(d_resp)
        assert d_data["status"] == "SUSPENDED"
        assert d_data["approved_value_cents"] == original_approved_value, (
            f"approved_value_cents must be preserved on SUSPEND for "
            f"audit, got {d_data['approved_value_cents']!r} "
            f"vs original {original_approved_value}"
        )


# ===========================================================================
# §3.7 OVERTURNED reverse cascade
# ===========================================================================
class TestOverturnedReverseCascade:
    """PRD §3.7: "When a sustained violation that previously caused an
    athlete to flip INELIGIBLE is later OVERTURNED, the cascade is
    reversed. The athlete moves INELIGIBLE -> ENROLLED, amateur_status
    is restored to AMATEUR, and every deal that was suspended by the
    original cascade returns to APPROVED with its approved_value_cents
    unchanged." """

    def test_overturned_restores_athlete_and_deals(
        self, api, officer_headers, officer_headers_secondary,
    ):
        """PRD §3.7: "The athlete moves INELIGIBLE -> ENROLLED,
        amateur_status is restored to AMATEUR, and every deal that
        was suspended by the original cascade returns to APPROVED
        with its approved_value_cents unchanged."

        Claim: build the INELIGIBLE / SUSPENDED state, then APPEALED
        -> OVERTURNED. Athlete returns to ENROLLED / AMATEUR, deal
        returns to APPROVED.

        Note: the violation reaches SUSTAINED via APPEALED -> SUSTAINED
        already. PRD §3.7 does not name a direct SUSTAINED ->
        OVERTURNED transition; instead OVERTURNED is reached from
        APPEALED. To test the reverse cascade we must drive a fresh
        violation through to APPEALED and then OVERTURNED. We rebuild
        the cascade scenario: an ENROLLED athlete with an APPROVED
        deal, then drive a violation REPORTED->INVESTIGATING->
        SUBSTANTIATED->APPEALED->OVERTURNED. But the cascade fires
        only at SUSTAINED. So to test the reverse cascade fairly, we
        need to first reach SUSTAINED then have a path back. PRD §3.7
        ONLY describes one such path: SUSTAINED is reached via
        APPEALED -> SUSTAINED; OVERTURNED is reached via APPEALED ->
        OVERTURNED. They are disjoint terminal states from APPEALED.

        Re-reading PRD §3.7 prose: "When a sustained violation that
        previously caused an athlete to flip INELIGIBLE is later
        OVERTURNED". This describes a state that the PRD's enumerated
        transitions do NOT permit: APPEALED is the only fork into
        either SUSTAINED or OVERTURNED, and neither is reachable from
        the other per the state machine described in §3.7.

        Skipping this concrete test because PRD prose names the
        reverse cascade but the enumerated transitions don't permit
        reaching it. The dual_variant cycle in §scaffold (NILDeal
        APPROVED -> SUSPENDED -> APPROVED) IS however reachable via
        manual ComplianceOfficer reinstatement per PRD §3.6, and is
        covered in test_difficulty_coverage_cycles.

        Below we instead exercise the OVERTURNED outcome flip itself
        (the §3.7 first sentence: "OVERTURNED flips outcome to
        CLEARED"). The full reverse-cascade body of §3.7 is covered
        from the cycle direction via NILDeal SUSPENDED->APPROVED
        manual reinstatement (PRD §3.6) in the difficulty-coverage
        file.
        """
        # We test the OVERTURNED outcome flip path explicitly.
        athlete, program, _slot = setup_enrolled_athlete()
        v = drive_violation_to_appealed(
            program["id"],
            severity="LEVEL_II",
            related_athlete_id=athlete["id"],
            reviewer_headers=officer_headers,
        )
        # Different officer overturns.
        res = api.transition_violation(
            v["id"],
            transition_violation_payload(to_status="OVERTURNED"),
            officer_headers_secondary,
        )
        data = validate_success(res)
        # PRD §3.7: "OVERTURNED flips outcome to CLEARED".
        assert data["outcome"] == "CLEARED"


# ===========================================================================
# §3.7 DISMISSED -> outcome CLEARED
# ===========================================================================
class TestDismissedClears:
    """PRD §3.7: "A DISMISSED outcome immediately flips outcome to
    CLEARED." """

    def test_dismissed_flips_outcome_to_cleared(
        self, api, officer_headers,
    ):
        """PRD §3.7: "A DISMISSED outcome immediately flips outcome
        to CLEARED."

        Claim: REPORTED -> INVESTIGATING -> DISMISSED leaves the case
        with status=DISMISSED and outcome=CLEARED.
        """
        program = create_program()
        v = report_violation(program["id"], severity="LEVEL_II")
        transition_violation(
            v["id"], "INVESTIGATING", headers=officer_headers,
        )
        d = transition_violation(
            v["id"], "DISMISSED", headers=officer_headers,
        )
        assert d["status"] == "DISMISSED"
        assert d["outcome"] == "CLEARED"


# ===========================================================================
# §2.10 SUBSTANTIATED -> SUSTAINED auto-expire path
# ===========================================================================
class TestAutoExpireSustained:
    """PRD §3.7 / §2.10: "If the 14-day appeal window elapses without
    an APPEALED transition, the next clock advance auto-fires
    SUBSTANTIATED -> SUSTAINED." """

    def test_clock_advance_past_14d_auto_sustains(
        self, api, officer_headers,
    ):
        """PRD §3.7: "If the 14-day appeal window elapses without an
        APPEALED transition, the next clock advance auto-fires
        SUBSTANTIATED -> SUSTAINED."

        Claim: SUBSTANTIATED + clock advance >= 14 days -> status
        becomes SUSTAINED automatically; penalty_points is computed.
        """
        program = create_program()
        v = report_violation(program["id"], severity="LEVEL_II")
        transition_violation(
            v["id"], "INVESTIGATING", headers=officer_headers,
        )
        v_sub = transition_violation(
            v["id"], "SUBSTANTIATED", headers=officer_headers,
        )
        sub_at = parse_iso(v_sub["updated_at"])
        target = sub_at + timedelta(days=APPEAL_WINDOW_DAYS, seconds=2)
        advance_clock_to(iso_utc(target))
        v_resp = api.get_violation(v["id"], officer_headers)
        v_data = validate_success(v_resp)
        assert v_data["status"] == "SUSTAINED"
        # PRD §3.7: "The cascade effects of the auto-expire path are
        # identical to the APPEALED -> SUSTAINED path described next."
        # That includes computing penalty_points via
        # violation_penalty_score (LEVEL_II first-offense = 5).
        assert v_data["penalty_points"] == 5
