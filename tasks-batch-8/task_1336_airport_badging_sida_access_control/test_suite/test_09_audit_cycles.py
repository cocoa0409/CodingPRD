"""Annual audit cycles: provisional vs final rates, tiling, and freezing."""
import pytest

from test_helpers import (
    AUD,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_audit_cycle,
    close_audit_cycle,
    create_applicant,
    create_audit_cycle_payload,
    create_sponsor,
    get_audit_cycle,
    issue_badge,
    mark_returned,
    open_audit_cycle,
    revoke_badge,
    set_clock,
    setup_issued_badge,
    setup_ready_application,
    validate_error,
    validate_success,
)


class TestProvisionalVersusFinal:

    def _setup_two_badge_scope(self):
        """b1 (STERILE) revoked 2026-08-10 and returned 2026-08-12;
        b2 (SIDA) revoked 2026-08-20 and never returned; audit cycle OPEN over
        [2026-01-01, 2027-01-01); clock parked at 2026-08-20."""
        sponsor = create_sponsor(active_badge_quota=5)

        a1 = create_applicant(sponsor["id"], full_name="Ana Rios",
                              government_id_number="G1001")
        app1, _ = setup_ready_application(sponsor["id"], a1["id"],
                                          badge_class="STERILE")
        b1 = issue_badge(app1["id"], "B101")

        a2 = create_applicant(sponsor["id"], full_name="Ben Okafor",
                              date_of_birth="1988-05-02",
                              government_id_number="G1002")
        app2, _ = setup_ready_application(sponsor["id"], a2["id"],
                                          badge_class="SIDA")
        b2 = issue_badge(app2["id"], "B102")

        set_clock("2026-08-10T00:00:00Z")
        revoke_badge(b1["id"], reason="credential misuse")
        set_clock("2026-08-12T00:00:00Z")
        mark_returned(b1["id"])
        set_clock("2026-08-20T00:00:00Z")
        revoke_badge(b2["id"], reason="employment ended")

        cycle = open_audit_cycle("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
        return cycle

    def test_provisional_rate_counts_only_due_badges(self):
        """PRD section 3.9: "While a cycle is `OPEN`, reading it returns live
        provisional figures computed against the current logical clock. The
        provisional scope restricts the audit's badges to those whose
        `return_deadline` has been set and has already passed:
        `due_scoped_count` counts them, `due_accounted_count` counts how many
        of them now stand in `RETURNED` or `VOIDED` status, and
        `recovery_rate_provisional_pct` is the accounted share of the due
        scope expressed as a percentage, rounded half-up to two decimals — or
        null when nothing is due yet."

        Design: Difficulty/dual_variant_calc/audit_recovery_provisional_vs_final
        """
        cycle = self._setup_two_badge_scope()

        set_clock("2026-09-10T00:00:00Z", headers=AUD)
        live = get_audit_cycle(cycle["id"])
        assert live["due_scoped_count"] == 1, \
            "only b1's 2026-09-09 deadline has passed; b2's 2026-09-19 has not"
        assert live["due_accounted_count"] == 1
        assert live["recovery_rate_provisional_pct"] == pytest.approx(100.00), \
            "the provisional denominator counts only due badges"

    def test_final_rate_uses_full_scope_and_provisional_fields_null(self):
        """PRD section 3.9: "The frozen `scoped_count` counts every badge
        whose `deactivated_at` falls within the window; the frozen
        `accounted_count` counts how many of those stand in `RETURNED` or
        `VOIDED`".
        PRD section 3.9: "At close the provisional fields — `due_scoped_count`,
        `due_accounted_count`, and `recovery_rate_provisional_pct` — become
        null and stay null. Because the provisional denominator counts only
        badges past their thirty-day return deadline while the final
        denominator counts the entire deactivation scope, the two rates
        diverge whenever not-yet-due unreturned badges exist."
        PRD section 3.9: "The `outcome` is `COMPLIANT` when the frozen rate
        is at least 95.00 and `DEFICIENT` below that line."

        Design: Difficulty/dual_variant_calc/audit_recovery_provisional_vs_final
        """
        cycle = self._setup_two_badge_scope()

        set_clock("2026-09-10T00:00:00Z", headers=AUD)
        live = get_audit_cycle(cycle["id"])
        assert live["recovery_rate_provisional_pct"] == pytest.approx(100.00)

        set_clock("2026-09-20T00:00:00Z", headers=AUD)
        closed = close_audit_cycle(cycle["id"])
        assert_audit_cycle(closed)
        assert closed["scoped_count"] == 2
        assert closed["accounted_count"] == 1
        assert closed["recovery_rate_pct"] == pytest.approx(50.00), \
            "full-scope denominator diverges from the 100.00 provisional"
        assert closed["outcome"] == "DEFICIENT"
        assert closed["recovery_rate_provisional_pct"] is None
        assert closed["due_scoped_count"] is None
        assert closed["due_accounted_count"] is None


class TestAggregateThenRound:

    def _setup_three_badge_scope(self):
        """Three badges revoked 2027-03-01 (inside the audit window); only
        b1 returned; clock parked at 2027-04-01."""
        sponsor = create_sponsor(sponsor_code="AR", name="AirRetail",
                                 active_badge_quota=5)
        roster = [
            ("Gus Hale", "1990-11-11", "G4001", "STERILE", "B401"),
            ("Hana Ives", "1989-12-12", "G4002", "STERILE", "B402"),
            ("Ian Judd", "1987-01-01", "G4003", "SIDA", "B403"),
        ]
        badges = []
        for name, dob, gid, klass, number in roster:
            a = create_applicant(sponsor["id"], full_name=name,
                                 date_of_birth=dob, government_id_number=gid)
            app, _ = setup_ready_application(sponsor["id"], a["id"],
                                             badge_class=klass)
            badges.append(issue_badge(app["id"], number))

        set_clock("2027-03-01T00:00:00Z")
        for i, badge in enumerate(badges, start=1):
            revoke_badge(badge["id"], reason=f"term{i}")
        set_clock("2027-03-02T00:00:00Z")
        mark_returned(badges[0]["id"])
        set_clock("2027-04-01T00:00:00Z", headers=AUD)
        return sponsor, badges

    def test_overall_rate_is_aggregate_then_round(self):
        """PRD section 3.9: "The rounding order is pinned: the overall rate
        is aggregated over the full scope and then rounded, never computed as
        the mean of the rounded per-class rates, so the same scope data can
        yield an overall figure that no averaging of the per-class figures
        reproduces."

        Design: Difficulty/combinatorial_formula/audit_overall_rate_aggregate_then_round
        """
        self._setup_three_badge_scope()
        cycle = open_audit_cycle("2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z")
        closed = close_audit_cycle(cycle["id"])

        assert closed["scoped_count"] == 3
        assert closed["accounted_count"] == 1
        assert closed["recovery_rate_pct"] == pytest.approx(33.33), (
            "round(100 * 1/3, 2) half-up; the forbidden mean of rounded "
            "per-class rates would be 25.00")
        assert closed["outcome"] == "DEFICIENT"

    def test_per_class_rates_sorted_alphabetically(self):
        """PRD section 3.9: "The `per_class_rates` array carries one entry
        per badge class present in the scope, each entry giving that class's
        `badge_class`, `scoped`, `accounted`, and `rate_pct` rounded half-up
        to two decimals, sorted alphabetically by class — `AOA`, then `SIDA`,
        then `STERILE`."

        Design: Difficulty/combinatorial_formula/audit_overall_rate_aggregate_then_round
        """
        self._setup_three_badge_scope()
        cycle = open_audit_cycle("2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z")
        closed = close_audit_cycle(cycle["id"])

        per_class = closed["per_class_rates"]
        assert len(per_class) == 2
        assert per_class[0]["badge_class"] == "SIDA"
        assert per_class[0]["scoped"] == 1
        assert per_class[0]["accounted"] == 0
        assert per_class[0]["rate_pct"] == pytest.approx(0.00)
        assert per_class[1]["badge_class"] == "STERILE"
        assert per_class[1]["scoped"] == 2
        assert per_class[1]["accounted"] == 1
        assert per_class[1]["rate_pct"] == pytest.approx(50.00)


class TestEmptyAndProvisionalConventions:

    def test_audit_empty_scope_closes_compliant_100(self):
        """PRD section 3.9: "The `recovery_rate_pct` is the accounted share
        of the full scope rounded half-up to two decimals, or 100.00 when the
        scope is empty."
        PRD section 3.9: "The `outcome` is `COMPLIANT` when the frozen rate
        is at least 95.00 and `DEFICIENT` below that line."

        Design: Corner/calculations/audit_empty_scope_closes_compliant_100
        """
        cycle = open_audit_cycle("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
        closed = close_audit_cycle(cycle["id"])
        assert closed["scoped_count"] == 0
        assert closed["accounted_count"] == 0
        assert closed["recovery_rate_pct"] == pytest.approx(100.00)
        assert closed["outcome"] == "COMPLIANT"
        assert closed["per_class_rates"] == [], "no badge classes in scope"

    def test_provisional_rate_null_when_no_badges_due(self):
        """PRD section 3.9: "`recovery_rate_provisional_pct` is the accounted
        share of the due scope expressed as a percentage, rounded half-up to
        two decimals — or null when nothing is due yet."
        PRD section 3.9: "A fresh cycle opens in `OPEN` status with all
        close-computed fields null."

        Design: Corner/calculations/provisional_rate_null_when_no_badges_due
        """
        ctx = setup_issued_badge(badge_number="B501")
        set_clock("2026-08-10T00:00:00Z")
        revoke_badge(ctx["badge"]["id"])
        cycle = open_audit_cycle("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")

        live = get_audit_cycle(cycle["id"])
        assert live["due_scoped_count"] == 0, \
            "the 2026-09-09 deadline is after the 2026-08-10 clock"
        assert live["due_accounted_count"] == 0
        assert live["recovery_rate_provisional_pct"] is None, \
            "null-when-none-due convention"
        assert live["recovery_rate_pct"] is None, "frozen fields stay null while OPEN"


class TestAuditWindowTiling:

    def _first_cycle(self):
        return open_audit_cycle("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")

    def test_audit_window_overlap_and_gap_rejected_adjacency_accepted(self):
        """PRD section 3.9: "the new window must not overlap any existing
        cycle's window, else `ERR_AUDIT_WINDOW_OVERLAP`. Touching windows are
        permitted, and more than permitted: once any cycle exists, a new
        cycle's `window_start` must fall exactly on the latest cycle's
        `window_end`, so cycles tile contiguously with no gaps; a start later
        than that boundary is rejected with `ERR_AUDIT_WINDOW_GAP`, and the
        overlap check is evaluated before the gap check."

        Design: Difficulty/resource_temporal_overlap/audit_window_mandatory_adjacency_tiling
        """
        self._first_cycle()

        overlap = api_client.create_audit_cycle(
            create_audit_cycle_payload("2026-06-01T00:00:00Z",
                                       "2027-06-01T00:00:00Z"), AUD)
        validate_error(overlap, ApiErrorId.ERR_AUDIT_WINDOW_OVERLAP)

        gap = api_client.create_audit_cycle(
            create_audit_cycle_payload("2027-02-01T00:00:00Z",
                                       "2028-02-01T00:00:00Z"), AUD)
        validate_error(gap, ApiErrorId.ERR_AUDIT_WINDOW_GAP)

        adjacent = api_client.create_audit_cycle(
            create_audit_cycle_payload("2027-01-01T00:00:00Z",
                                       "2028-01-01T00:00:00Z"), AUD)
        data = validate_success(adjacent, expected_status=201)
        assert data["status"] == "OPEN"
        assert data["window_start"] == "2027-01-01T00:00:00Z"

    def test_audit_window_gap_requires_exact_tiling(self):
        """PRD section 3.9: "once any cycle exists, a new cycle's
        `window_start` must fall exactly on the latest cycle's `window_end`,
        so cycles tile contiguously with no gaps; a start later than that
        boundary is rejected with `ERR_AUDIT_WINDOW_GAP`, and the overlap
        check is evaluated before the gap check."

        Design: Difficulty/resource_temporal_overlap/audit_window_mandatory_adjacency_tiling
        """
        first = self._first_cycle()
        assert first["window_end"] == "2027-01-01T00:00:00Z"

        gap = api_client.create_audit_cycle(
            create_audit_cycle_payload("2027-06-01T00:00:00Z",
                                       "2028-06-01T00:00:00Z"), AUD)
        validate_error(gap, ApiErrorId.ERR_AUDIT_WINDOW_GAP)

        tiled = api_client.create_audit_cycle(
            create_audit_cycle_payload("2027-01-01T00:00:00Z",
                                       "2028-01-01T00:00:00Z"), AUD)
        assert validate_success(tiled, expected_status=201)["status"] == "OPEN"

    def test_audit_window_end_before_start_returns_invalid_request(self):
        """PRD section 3.9: "the window is the half-open interval from
        `window_start` up to but not including `window_end`, the end must be
        strictly after the start (else `ERR_INVALID_REQUEST`)".

        Design: Corner/validations/audit_window_end_before_start_returns_invalid_request
        """
        resp = api_client.create_audit_cycle(
            create_audit_cycle_payload("2027-01-01T00:00:00Z",
                                       "2026-01-01T00:00:00Z"), AUD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAuditCloseLifecycle:

    def test_close_closed_audit_rejected(self):
        """PRD section 3.9: "Closing the cycle, an `Auditor`-only action
        requiring the cycle to be `OPEN` (else `ERR_AUDIT_NOT_OPEN`), moves
        the cycle to its terminal `CLOSED` status and freezes the final
        figures."

        Design: Corner/state_machines/close_closed_audit_rejected
        """
        cycle = open_audit_cycle("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
        first = close_audit_cycle(cycle["id"])
        assert first["status"] == "CLOSED"
        assert first["recovery_rate_pct"] == pytest.approx(100.00), "empty scope"

        resp = api_client.close_audit_cycle(cycle["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_OPEN)

        reread = get_audit_cycle(cycle["id"])
        assert reread["recovery_rate_pct"] == first["recovery_rate_pct"], \
            "the frozen figures do not change"

    def test_close_audit_not_found_returns_404(self):
        """PRD section 2.6: "Path identifiers are validated left to right and
        body references must exist — each unknown resource yields its specific
        not-found error (`ERR_SPONSOR_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_BADGE_NOT_FOUND`,
        `ERR_ESCORT_PRIVILEGE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, or
        `ERR_AUDIT_CYCLE_NOT_FOUND`)".

        Design: Corner/entities/close_audit_not_found_returns_404
        """
        resp = api_client.close_audit_cycle(NON_EXISTENT_UUID, AUD)
        validate_error(resp, ApiErrorId.ERR_AUDIT_CYCLE_NOT_FOUND)
