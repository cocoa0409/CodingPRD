"""Temporary/emergency/disaster privileges: activation gates, window caps,
buffered overlap, and the parallel posture axis."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_temp_privilege,
    assert_temporary_privilege,
    create_member_record,
    create_member_with_active_grant,
    create_temp_privilege,
    refresh_grant,
    refresh_member,
    refresh_temp,
    set_clock,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
CHAIR = TEST_USERS["committee_chair_headers"]


def _qualified_sponsor(name="Dr. Sponsor", npdb="NPDB-SP"):
    """A member whose grant matured to ACTIVE — membership_status ACTIVE and
    privilege_posture FULL as required of a sponsor (PRD §3.7)."""
    return create_member_with_active_grant(name, npdb)


class TestActivationPriority:
    def test_temp_activate_sponsor_safety_beats_window_temporal(self, api):
        """PRD §3.7: "The sponsor must be qualified — a member whose
        `membership_status` is `ACTIVE` and whose `privilege_posture` is `FULL`
        (`ERR_SPONSOR_NOT_QUALIFIED`, 403)."
        PRD §2.9: "Every request is validated against a fixed priority ladder,
        and a request that fails an earlier rung is never evaluated against a
        later one — the first failing rung determines the error returned."

        One activation that violates both the sponsor safety gate (rung 7) and
        the 120-day window cap (rung 8) must surface the safety error.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_temp_activate
        """
        set_clock()
        recipient = create_member_record("Dr. T1", "NPDB-T1", "EMED")
        sponsor = create_member_record("Dr. T2", "NPDB-T2", "EMED")
        temp = create_temp_privilege(
            recipient["id"], sponsor["id"], "TEMPORARY", "EMED-GEN",
            "2026-08-02T00:00:00Z", "2027-02-01T00:00:00Z")

        resp = api.activate_temporary_privilege(temp["id"], CHAIR)
        validate_error(resp, ApiErrorId.ERR_SPONSOR_NOT_QUALIFIED, 403)
        assert refresh_temp(temp["id"])["temp_status"] == "PENDING_SPONSOR"

    def test_temp_activate_window_cap_violation_isolated(self, api):
        """PRD §3.7: "The window must fit its kind's cap: at most twenty-four
        hours for `EMERGENCY`, at most seventy-two hours for `DISASTER`, at most
        one hundred twenty days for `TEMPORARY` (`ERR_TEMP_WINDOW_TOO_LONG`)."

        With a qualified sponsor, the 183-day window alone fails the cap.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_temp_activate
        """
        sponsor = _qualified_sponsor("Dr. SponCap", "NPDB-SPC")
        recipient = create_member_record("Dr. RecipCap", "NPDB-RPC", "EMED")
        temp = create_temp_privilege(
            recipient["id"], sponsor["member"]["id"], "TEMPORARY", "EMED-GEN",
            "2026-08-02T00:00:00Z", "2027-02-01T00:00:00Z")

        resp = api.activate_temporary_privilege(temp["id"], CHAIR)
        validate_error(resp, ApiErrorId.ERR_TEMP_WINDOW_TOO_LONG, 409)
        assert refresh_temp(temp["id"])["temp_status"] == "PENDING_SPONSOR"


class TestWindowCapBoundary:
    def test_temp_window_exactly_120_days_activates(self, api):
        """PRD §3.7: "The window must fit its kind's cap: at most twenty-four
        hours for `EMERGENCY`, at most seventy-two hours for `DISASTER`, at most
        one hundred twenty days for `TEMPORARY` (`ERR_TEMP_WINDOW_TOO_LONG`)."

        [2026-09-01, 2026-12-30] spans exactly 120 days: at the cap, accepted.

        Design: Difficulty/boundary_precision_check/temp_window_cap_exactly_120_days_vs_over
        """
        sponsor = _qualified_sponsor("Dr. Sponsor3", "NPDB-SP3")
        recipient = create_member_record("Dr. Temp", "NPDB-TP1", "EMED")
        temp = create_temp_privilege(
            recipient["id"], sponsor["member"]["id"], "TEMPORARY", "EMED-GEN",
            "2026-09-01T00:00:00Z", "2026-12-30T00:00:00Z")

        activated = validate_success(
            api.activate_temporary_privilege(temp["id"], CHAIR))
        assert_temporary_privilege(activated)
        assert activated["temp_status"] == "ACTIVE"

    def test_temp_window_120_days_plus_one_second_rejected(self, api):
        """PRD §3.7: "The window must fit its kind's cap: at most twenty-four
        hours for `EMERGENCY`, at most seventy-two hours for `DISASTER`, at most
        one hundred twenty days for `TEMPORARY` (`ERR_TEMP_WINDOW_TOO_LONG`)."

        One second beyond the 120-day cap is over it.

        Design: Difficulty/boundary_precision_check/temp_window_cap_exactly_120_days_vs_over
        """
        sponsor = _qualified_sponsor("Dr. Sponsor3b", "NPDB-SP3B")
        recipient = create_member_record("Dr. TempB", "NPDB-TP1B", "EMED")
        temp = create_temp_privilege(
            recipient["id"], sponsor["member"]["id"], "TEMPORARY", "EMED-GEN",
            "2027-03-01T00:00:00Z", "2027-06-29T00:00:01Z")

        resp = api.activate_temporary_privilege(temp["id"], CHAIR)
        validate_error(resp, ApiErrorId.ERR_TEMP_WINDOW_TOO_LONG, 409)
        assert refresh_temp(temp["id"])["temp_status"] == "PENDING_SPONSOR"


class TestBufferedOverlap:
    def _sponsor_recipient_and_existing(self, suffix=""):
        sponsor = _qualified_sponsor(f"Dr. Sponsor4{suffix}",
                                     f"NPDB-SP4{suffix}")
        recipient = create_member_record(f"Dr. Overlap{suffix}",
                                         f"NPDB-O1{suffix}", "EMED")
        existing = create_temp_privilege(
            recipient["id"], sponsor["member"]["id"], "TEMPORARY", "EMED-GEN",
            "2026-09-10T00:00:00Z", "2026-09-12T00:00:00Z")
        activate_temp_privilege(existing["id"])
        return sponsor, recipient, existing

    def test_temp_overlap_one_day_adjacency_conflicts(self, api):
        """PRD §3.7: "Consequently, a candidate beginning exactly one day after
        an existing window ends still conflicts — it sits inside the buffer —
        while one beginning two days after does not."

        Design: Difficulty/resource_temporal_overlap/temp_privilege_closed_interval_with_buffer
        """
        _sponsor, recipient, _existing = self._sponsor_recipient_and_existing()
        candidate = create_temp_privilege(
            recipient["id"], _sponsor["member"]["id"], "TEMPORARY", "EMED-GEN",
            "2026-09-13T00:00:00Z", "2026-09-15T00:00:00Z")

        resp = api.activate_temporary_privilege(candidate["id"], CHAIR)
        validate_error(resp, ApiErrorId.ERR_TEMP_OVERLAP, 409)
        assert refresh_temp(candidate["id"])["temp_status"] == "PENDING_SPONSOR"

    def test_temp_overlap_two_day_gap_permitted(self, api):
        """PRD §3.7: "The overlap rule buffers the existing windows, never the
        candidate. For a candidate window from `window_start` to `window_end` and
        each existing `ACTIVE` temporary privilege of the same member, the
        existing window is extended by one day on both ends, and a conflict
        exists when the candidate's start falls on or before the buffered end
        and the buffered start falls on or before the candidate's end."

        Design: Difficulty/resource_temporal_overlap/temp_privilege_closed_interval_with_buffer
        """
        _sponsor, recipient, _existing = self._sponsor_recipient_and_existing(
            "Y")
        candidate = create_temp_privilege(
            recipient["id"], _sponsor["member"]["id"], "TEMPORARY", "EMED-GEN",
            "2026-09-14T00:00:00Z", "2026-09-16T00:00:00Z")

        activated = validate_success(
            api.activate_temporary_privilege(candidate["id"], CHAIR))
        assert activated["temp_status"] == "ACTIVE", (
            "A start two days after the existing window's end clears the "
            "one-day buffer")


class TestParallelAxes:
    def test_temp_activation_moves_posture_not_membership(self, api):
        """PRD §2.8: "A member's standing is tracked on two independent axes
        that evolve in parallel."
        PRD §3.7: "A successful activation moves the request to `ACTIVE` and
        recomputes the recipient's `privilege_posture` — a member whose posture
        was `NONE` rises to `EMERGENCY_ONLY`."

        Design: Difficulty/non_linear_state_machine/member_parallel_dimensions_membership_x_posture
        """
        sponsor = _qualified_sponsor("Dr. Sponsor", "NPDB-SP1")
        applicant = create_member_record("Dr. Applicant", "NPDB-A1", "EMED")
        assert applicant["membership_status"] == "APPLICANT"
        assert applicant["privilege_posture"] == "NONE"

        temp = create_temp_privilege(
            applicant["id"], sponsor["member"]["id"], "TEMPORARY", "EMED-GEN",
            "2026-08-05T00:00:00Z", "2026-09-05T00:00:00Z")
        validate_success(api.activate_temporary_privilege(temp["id"], CHAIR))

        member = refresh_member(applicant["id"])
        assert member["membership_status"] == "APPLICANT", (
            "Axis 1 (membership) does not move on temporary-privilege activation")
        assert member["privilege_posture"] == "EMERGENCY_ONLY", (
            "Axis 2 (posture) rises NONE -> EMERGENCY_ONLY")

    def test_sponsor_posture_full_after_fppe_maturation(self, api):
        """PRD §3.5: "When a grant's `fppe_cases_completed` reaches the
        `fppe_case_count` required by the specialty criteria for its line, the
        grant flips automatically `PROVISIONAL` → `ACTIVE`, and the member's
        `active_privilege_line_count` and `privilege_posture` are recomputed."
        PRD §3.7: "The sponsor must be qualified — a member whose
        `membership_status` is `ACTIVE` and whose `privilege_posture` is `FULL`
        (`ERR_SPONSOR_NOT_QUALIFIED`, 403)."

        The sponsor's posture reads FULL once its single grant has matured —
        proven by the sponsor gate accepting the activation below.

        Design: Difficulty/non_linear_state_machine/member_parallel_dimensions_membership_x_posture
        """
        sponsor = _qualified_sponsor("Dr. Sponsor2", "NPDB-SP2")
        assert refresh_grant(sponsor["grant"]["id"])["grant_status"] == "ACTIVE"

        recipient = create_member_record("Dr. Applicant2", "NPDB-A2", "EMED")
        temp = create_temp_privilege(
            recipient["id"], sponsor["member"]["id"], "TEMPORARY", "EMED-GEN",
            "2026-08-05T00:00:00Z", "2026-09-05T00:00:00Z")
        validate_success(api.activate_temporary_privilege(temp["id"], CHAIR))

        member = refresh_member(sponsor["member"]["id"])
        assert member["membership_status"] == "ACTIVE"
        assert member["privilege_posture"] == "FULL"


class TestEarlyTermination:
    def test_error_temp_terminate_non_active(self, api):
        """PRD §3.7: "The chair may instead terminate it early, `ACTIVE` →
        `TERMINATED_EARLY`, rejected from any other state with
        `ERR_TEMP_NOT_ACTIVE`."

        Design: Corner/errors/error_temp_terminate_non_active
        """
        set_clock()
        recipient = create_member_record("Dr. Recip", "NPDB-RC", "EMED")
        sponsor = create_member_record("Dr. Spon", "NPDB-SPN", "EMED")
        temp = create_temp_privilege(
            recipient["id"], sponsor["id"], "EMERGENCY", "EMED-GEN",
            "2026-08-02T00:00:00Z", "2026-08-02T23:00:00Z")

        resp = api.terminate_temporary_privilege(temp["id"], CHAIR)
        validate_error(resp, ApiErrorId.ERR_TEMP_NOT_ACTIVE, 409)
        assert refresh_temp(temp["id"])["temp_status"] == "PENDING_SPONSOR"
