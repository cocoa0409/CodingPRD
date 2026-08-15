"""Violation recording, windowed points, threshold cascades, and dismissal."""
from test_helpers import (
    BO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_violation,
    get_badge,
    grant_escort_privilege,
    make_auditor_headers,
    make_security_manager_headers,
    record_violation,
    set_clock,
    setup_issued_badge,
    sustain_violation,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPointsAssignment:

    def test_violation_points_assigned_from_type_constants(self):
        """PRD section 3.8: "The server assigns `points` from the type —
        `FAILURE_TO_DISPLAY` is worth 3 points, `ESCORT_VIOLATION` 6 points,
        `UNAUTHORIZED_AREA` 6 points, and `SECURITY_BREACH` 12 points — stamps
        `recorded_by` with the acting officer, and opens the record in
        `RECORDED` status."

        Design: Corner/calculations/violation_points_assigned_from_type_constants
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B601")
        badge_id = ctx["badge"]["id"]

        expected = [("FAILURE_TO_DISPLAY", 3), ("ESCORT_VIOLATION", 6),
                    ("UNAUTHORIZED_AREA", 6), ("SECURITY_BREACH", 12)]
        for vtype, points in expected:
            data = record_violation(badge_id, vtype,
                                    occurred_at="2026-08-02T00:00:00Z")
            assert_violation(data)
            assert data["points"] == points, f"{vtype} must assign {points}"
            assert data["status"] == "RECORDED"

        assert get_badge(badge_id)["status"] == "ACTIVE", \
            "no points are active until sustain"


class TestRollingWindow:

    def test_violation_window_excludes_exactly_24_months_old(self):
        """PRD section 3.8: "the sum of points across all `SUSTAINED`
        violations attached to badges of the same applicant whose
        `occurred_at` falls strictly within the trailing twenty-four months —
        a violation exactly twenty-four months old is excluded."

        Design: Corner/calculations/violation_window_excludes_exactly_24_months_old
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B701")
        badge_id = ctx["badge"]["id"]

        v_old = record_violation(badge_id, "FAILURE_TO_DISPLAY",
                                 occurred_at="2024-08-10T00:00:00Z")
        sustain_violation(v_old["id"])
        assert get_badge(badge_id)["status"] == "ACTIVE", \
            "3 points at the 2026-08-01 clock: below the threshold"

        set_clock("2026-08-10T00:00:00Z")
        v1 = record_violation(badge_id, "ESCORT_VIOLATION",
                              occurred_at="2026-08-05T00:00:00Z")
        sustain_violation(v1["id"])

        assert get_badge(badge_id)["status"] == "ACTIVE", (
            "at 2026-08-10 the window floor is 2024-08-10 and v_old occurred "
            "exactly at the floor, so it is excluded; 6 points < 12 leaves "
            "the badge ACTIVE")


class TestThresholdBoundary:

    def _badge_at_nine_points(self):
        ctx = setup_issued_badge(sponsor_code="TH", sponsor_name="TransHub",
                                 badge_class="SIDA", badge_number="B901",
                                 full_name="Ruth Senn",
                                 government_id_number="G9201",
                                 date_of_birth="1988-04-22")
        badge_id = ctx["badge"]["id"]
        v1 = record_violation(badge_id, "FAILURE_TO_DISPLAY",
                              occurred_at="2026-08-02T00:00:00Z")
        sustain_violation(v1["id"])
        v2 = record_violation(badge_id, "ESCORT_VIOLATION",
                              occurred_at="2026-08-03T00:00:00Z")
        sustain_violation(v2["id"])
        return ctx, badge_id

    def test_violation_points_below_threshold_leave_badge_active(self):
        """PRD section 3.8: "Exactly 12 points suspends; 11 points leaves the
        badge untouched."

        Design: Difficulty/boundary_precision_check/violation_points_threshold_exactly_12_suspends
        """
        _, badge_id = self._badge_at_nine_points()
        assert get_badge(badge_id)["status"] == "ACTIVE", \
            "9 accumulated points stay below the threshold"

    def test_violation_points_threshold_exactly_12_suspends(self):
        """PRD section 3.8: "Otherwise, at 12 points or more, an `ACTIVE`
        badge is suspended under the `VIOLATION_POINTS` reason with
        `suspended_by` set to the sustaining manager and `suspended_until`
        tiered by severity: a total from 12 through 17 points suspends for
        seven days, while a total from 18 through 23 points suspends for
        thirty days. Exactly 12 points suspends; 11 points leaves the badge
        untouched."

        Design: Difficulty/boundary_precision_check/violation_points_threshold_exactly_12_suspends
        """
        _, badge_id = self._badge_at_nine_points()
        v3 = record_violation(badge_id, "FAILURE_TO_DISPLAY",
                              occurred_at="2026-08-04T00:00:00Z")
        sustain_violation(v3["id"])

        badge = get_badge(badge_id)
        assert badge["status"] == "SUSPENDED", "12 >= 12 crosses the threshold"
        assert badge["suspended_until"] == "2026-08-08T00:00:00Z", \
            "the 12-17 tier suspends for seven days from the 2026-08-01 sustain"


class TestSustainCascade:

    def _badge_with_escort_and_nine_points(self):
        ctx = setup_issued_badge(sponsor_code="VC", sponsor_name="VectorCatering",
                                 badge_class="SIDA", badge_number="B601",
                                 full_name="Liam Mays",
                                 government_id_number="G7001",
                                 date_of_birth="1990-09-09")
        badge = ctx["badge"]
        ep1 = grant_escort_privilege(badge["id"], badge["version"],
                                     max_escortees=3, manager_id="mgr-1")
        v1 = record_violation(badge["id"], "ESCORT_VIOLATION",
                              occurred_at="2026-08-02T00:00:00Z")
        sustain_violation(v1["id"])
        assert get_badge(badge["id"])["status"] == "ACTIVE"
        return ctx, ep1

    def test_sustain_cascade_suspends_badge_and_revokes_escort(self):
        """PRD section 3.8: "The recomputed total drives a threshold cascade
        against the badge the violation was recorded on. At 24 points or more,
        an `ACTIVE` or `SUSPENDED` badge is revoked outright, following the
        same deactivation bookkeeping and escort-revocation chain as a manual
        revocation. Otherwise, at 12 points or more, an `ACTIVE` badge is
        suspended under the `VIOLATION_POINTS` reason with `suspended_by` set
        to the sustaining manager and `suspended_until` tiered by severity".

        Design: Difficulty/transitive_cascade/violation_sustain_cascades_badge_suspend_escort_revoke
        """
        ctx, ep1 = self._badge_with_escort_and_nine_points()
        badge_id = ctx["badge"]["id"]

        v2 = record_violation(badge_id, "UNAUTHORIZED_AREA",
                              occurred_at="2026-08-03T00:00:00Z")
        sustained = sustain_violation(v2["id"])
        assert sustained["status"] == "SUSTAINED", \
            "link 1: the violation itself moves to SUSTAINED"

        badge = get_badge(badge_id)
        assert badge["status"] == "SUSPENDED", "link 2: 6 + 6 == 12 >= 12"
        assert badge["suspension_reason"] == "VIOLATION_POINTS"
        assert badge["suspended_until"] == "2026-08-08T00:00:00Z"
        assert badge["suspended_by"] == "mgr-1"

        lst, _ = validate_paginated(
            api_client.list_escort_privileges(badge_id, BO))
        assert lst[0]["id"] == ep1["id"]
        assert lst[0]["status"] == "REVOKED", "link 3: the escort chain fires"
        assert lst[0]["revoked_reason"] == "BADGE_SUSPENDED"

    def test_sustain_cascade_tier_fields_on_badge(self):
        """PRD section 3.5: "The same transition fires automatically, with
        `suspension_reason` set to `VIOLATION_POINTS` and a computed
        `suspended_until`, when sustained violation points cross the threshold
        described in §3.8. Any suspension — manual, points-driven, or the
        sponsor cascade of §3.7's neighbor workflow — immediately revokes the
        badge's `GRANTED` escort privilege with `revoked_reason` set to
        `BADGE_SUSPENDED`."

        Design: Difficulty/transitive_cascade/violation_sustain_cascades_badge_suspend_escort_revoke
        """
        ctx, ep1 = self._badge_with_escort_and_nine_points()
        badge_id = ctx["badge"]["id"]

        v2 = record_violation(badge_id, "UNAUTHORIZED_AREA",
                              occurred_at="2026-08-03T00:00:00Z")
        sustain_violation(v2["id"])

        badge = get_badge(badge_id)
        assert badge["status"] == "SUSPENDED"
        assert badge["suspension_reason"] == "VIOLATION_POINTS"
        assert badge["suspended_by"] == "mgr-1"
        assert badge["suspended_until"] == "2026-08-08T00:00:00Z", \
            "the 12-17 tier is now + 7 days"

        ep = validate_paginated(
            api_client.list_escort_privileges(badge_id, BO))[0][0]
        assert ep["status"] == "REVOKED"
        assert ep["revoked_reason"] == "BADGE_SUSPENDED"


class TestDismissalCompensation:

    def _suspended_at_twelve(self):
        ctx = setup_issued_badge(sponsor_code="PT", sponsor_name="PlaneTech",
                                 badge_class="SIDA", badge_number="B1501",
                                 full_name="Abby Cobb",
                                 government_id_number="G9801",
                                 date_of_birth="1992-02-03")
        badge_id = ctx["badge"]["id"]
        v1 = record_violation(badge_id, "FAILURE_TO_DISPLAY",
                              occurred_at="2026-08-02T00:00:00Z")
        sustain_violation(v1["id"])
        v2 = record_violation(badge_id, "ESCORT_VIOLATION",
                              occurred_at="2026-08-03T00:00:00Z")
        sustain_violation(v2["id"])
        return ctx, badge_id

    def test_sustain_dismiss_pair_conserves_windowed_points(self):
        """PRD section 3.8: "A `SecurityManager` may dismiss a violation in
        `RECORDED` or `SUSTAINED` status, subject to the segregation-of-duties
        rule of §2.9; the record moves to `DISMISSED` with `dismissed_by`
        stamped, and the holder's windowed points are recomputed with the
        dismissed violation's points removed."

        Design: Difficulty/compensating_invariant/sustain_dismiss_pair_conserves_windowed_points
        """
        _, badge_id = self._suspended_at_twelve()
        assert get_badge(badge_id)["status"] == "ACTIVE", "9 points: no cascade"

        v3 = record_violation(badge_id, "FAILURE_TO_DISPLAY",
                              occurred_at="2026-08-04T00:00:00Z")
        sustain_violation(v3["id"])
        assert get_badge(badge_id)["status"] == "SUSPENDED", \
            "the +3 sustain crossed 12"

        dismissed = api_client.dismiss_violation(
            v3["id"], make_security_manager_headers("mgr-2"))
        assert validate_success(dismissed)["status"] == "DISMISSED"

        lst, _ = validate_paginated(api_client.list_violations(badge_id, BO))
        assert [v["status"] for v in lst] == ["SUSTAINED", "SUSTAINED", "DISMISSED"], \
            "SUSTAINED points are back to 3 + 6 == 9, the pre-pair total"

    def test_dismissal_does_not_auto_reinstate_badge(self):
        """PRD section 3.8: "A badge already suspended or revoked by the
        threshold cascade is not automatically restored — reinstatement is a
        separate manual action with its own guards."

        Design: Difficulty/compensating_invariant/sustain_dismiss_pair_conserves_windowed_points
        """
        _, badge_id = self._suspended_at_twelve()
        v3 = record_violation(badge_id, "FAILURE_TO_DISPLAY",
                              occurred_at="2026-08-04T00:00:00Z")
        sustain_violation(v3["id"])
        assert get_badge(badge_id)["status"] == "SUSPENDED"

        validate_success(api_client.dismiss_violation(
            v3["id"], make_security_manager_headers("mgr-2")))

        assert get_badge(badge_id)["status"] == "SUSPENDED", \
            "dismissal reverses the points, not the cascade"


class TestViolationStateAndRoles:

    def test_dismiss_dismissed_violation_rejected(self):
        """PRD section 3.8: "A violation in any other state refuses the
        sustain with `ERR_VIOLATION_NOT_OPEN`."
        PRD section 2.6: "The target entity must be in the state the
        transition requires, failing with the corresponding state error such
        as ... `ERR_VIOLATION_NOT_OPEN`."

        Design: Corner/state_machines/dismiss_dismissed_violation_rejected
        """
        ctx = setup_issued_badge(badge_number="B401")
        v1 = record_violation(ctx["badge"]["id"], "FAILURE_TO_DISPLAY",
                              occurred_at="2026-08-02T00:00:00Z")
        first = api_client.dismiss_violation(
            v1["id"], make_security_manager_headers("mgr-1"))
        assert validate_success(first)["status"] == "DISMISSED"

        second = api_client.dismiss_violation(
            v1["id"], make_security_manager_headers("mgr-2"))
        validate_error(second, ApiErrorId.ERR_VIOLATION_NOT_OPEN)

    def test_dismiss_by_sustaining_manager_rejected(self):
        """PRD section 2.9: "Dismissing a violation obeys the same principle
        from the other side: dismissing a violation still in `RECORDED`
        status requires the caller to differ from the officer in
        `recorded_by`, while dismissing a violation already in `SUSTAINED`
        status requires the caller to differ from the manager in
        `sustained_by`. Either conflict is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/dismiss_by_sustaining_manager_rejected
        """
        ctx = setup_issued_badge(badge_number="B2301")
        v1 = record_violation(ctx["badge"]["id"], "FAILURE_TO_DISPLAY",
                              occurred_at="2026-08-02T00:00:00Z",
                              officer_id="off-1")
        sustain_violation(v1["id"], manager_id="mgr-1")

        resp = api_client.dismiss_violation(
            v1["id"], make_security_manager_headers("mgr-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        ok = api_client.dismiss_violation(
            v1["id"], make_security_manager_headers("mgr-2"))
        assert validate_success(ok)["status"] == "DISMISSED"

    def test_auditor_cannot_sustain_violation(self):
        """PRD section 4: the `POST /badging/violations/{id}/sustain` row
        lists only `SecurityManager` under Authorized Role(s).
        PRD section 2.6: "The caller's role must be one of the endpoint's
        allowed roles; otherwise `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/auditor_cannot_sustain_violation
        """
        ctx = setup_issued_badge(badge_number="B2101")
        v1 = record_violation(ctx["badge"]["id"], "FAILURE_TO_DISPLAY",
                              occurred_at="2026-08-02T00:00:00Z")
        resp = api_client.sustain_violation(v1["id"], make_auditor_headers("aud-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_sustain_violation_not_found_returns_404(self):
        """PRD section 2.6: "Path identifiers are validated left to right and
        body references must exist — each unknown resource yields its specific
        not-found error (`ERR_SPONSOR_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_BADGE_NOT_FOUND`,
        `ERR_ESCORT_PRIVILEGE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, or
        `ERR_AUDIT_CYCLE_NOT_FOUND`)".

        Design: Corner/entities/sustain_violation_not_found_returns_404
        """
        resp = api_client.sustain_violation(
            NON_EXISTENT_UUID, make_security_manager_headers("mgr-1"))
        validate_error(resp, ApiErrorId.ERR_VIOLATION_NOT_FOUND)
