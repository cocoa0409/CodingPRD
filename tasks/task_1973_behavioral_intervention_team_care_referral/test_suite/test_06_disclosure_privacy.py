"""Cross-office disclosure grants: IMMINENT auto-grants, overlap windows,
privacy-gated case reads, expiry sweeps.

PRD §2.7 (privacy partitioning), §3.2 (IMMINENT auto-grant exception), and
§3.7 (grant lifecycle and window rules).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    request_grant,
    score_case,
    set_clock,
    setup_approved_grant,
    setup_case_in_intake,
    setup_staff_group,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestImminentAutoDisclosureGrants:
    def test_crossing_into_imminent_auto_approves_two_safety_grants(self, api):
        """PRD §3.2: "When an `INITIAL` scoring lands at `IMMINENT`, or when a
        `REASSESSMENT` crosses into `IMMINENT` from any lower tier, the system
        creates two disclosure grants with no human in the loop: one to
        `COUNSELING_CENTER` and one to `CAMPUS_SAFETY`, each with `scope`
        `SAFETY_MINIMUM`, each created directly in `APPROVED` status with
        `auto_approved` set to true, `requested_by` and `approved_by` left
        null, the window opening at the moment of creation, and `expires_at`
        exactly 72 hours later."

        Design: Difficulty/transitive_cascade/imminent_tier_auto_disclosure_grants
        """
        ctx = setup_staff_group()
        setup_case_in_intake(ctx, external_ref="S6002", category="BEHAVIORAL_THREAT")
        first = score_case(ctx, ctx["case_id"], mode="INITIAL",
                           harm_to_self=25, harm_to_others=17,
                           academic_disruption=2, substance_involvement=0,
                           rationale="high")
        assert first["tier"] == "HIGH"
        grants_before, meta_before = validate_paginated(
            api.list_disclosure_grants(ctx["chair_headers"], params={"case_id": ctx["case_id"]})
        )
        assert meta_before["total_count"] == 0
        second = score_case(ctx, ctx["case_id"], mode="REASSESSMENT",
                            harm_to_self=25, harm_to_others=25,
                            academic_disruption=25, substance_involvement=25,
                            rationale="imminent danger")
        # 0.6*100 + 0.4*60.0 = 84.0 -> crossing INTO IMMINENT.
        assert second["score"] == pytest.approx(84.0, abs=1e-9)
        assert second["tier"] == "IMMINENT"
        grants, meta = validate_paginated(
            api.list_disclosure_grants(ctx["chair_headers"], params={"case_id": ctx["case_id"]})
        )
        assert meta["total_count"] == 2
        for g in grants:
            assert g["status"] == "APPROVED"
            assert g["scope"] == "SAFETY_MINIMUM"
            assert g["auto_approved"] is True
            assert g["requested_by"] is None
            assert g["approved_by"] is None
        assert {g["to_office"] for g in grants} == {"COUNSELING_CENTER", "CAMPUS_SAFETY"}

    def test_continuation_at_imminent_creates_no_new_grants(self, api):
        """PRD §3.2: "If the case's previous tier was already `IMMINENT`, a
        reassessment that keeps it there creates no new grants — the exception
        fires on the crossing, not on the continuation."

        Design: Difficulty/transitive_cascade/imminent_tier_auto_disclosure_grants
        """
        ctx = setup_staff_group()
        setup_case_in_intake(ctx, external_ref="S6002B", category="BEHAVIORAL_THREAT")
        first = score_case(ctx, ctx["case_id"], mode="INITIAL",
                           harm_to_self=25, harm_to_others=25,
                           academic_disruption=20, substance_involvement=0,
                           rationale="imminent")
        # 4*(8.75+8.75+3.0) = 82.0 -> IMMINENT on INITIAL; two auto-grants.
        assert first["tier"] == "IMMINENT"
        grants, meta = validate_paginated(
            api.list_disclosure_grants(ctx["chair_headers"], params={"case_id": ctx["case_id"]})
        )
        assert meta["total_count"] == 2
        second = score_case(ctx, ctx["case_id"], mode="REASSESSMENT",
                            harm_to_self=25, harm_to_others=25,
                            academic_disruption=25, substance_involvement=25,
                            rationale="still imminent")
        assert second["tier"] == "IMMINENT"
        grants_after, meta_after = validate_paginated(
            api.list_disclosure_grants(ctx["chair_headers"], params={"case_id": ctx["case_id"]})
        )
        assert meta_after["total_count"] == 2


class TestDisclosureWindowOverlap:
    def test_intersecting_window_rejected(self, api):
        """PRD §3.7: "The window is half-open — inclusive at `effective_from`,
        exclusive at `expires_at` — and two temporal rules guard it:
        `expires_at` must be later than `effective_from`
        (`ERR_DISCLOSURE_WINDOW_INVALID`, 400), and the requested window must
        not intersect any existing `REQUESTED` or `APPROVED` grant for the same
        `case_id` and `to_office` pair (`ERR_DISCLOSURE_WINDOW_OVERLAP`, 409)."

        Design: Difficulty/resource_temporal_overlap/disclosure_grant_half_open_overlap
        """
        ctx = setup_staff_group(privacy_officer=True)
        setup_case_in_intake(ctx, external_ref="S1001")
        setup_approved_grant(ctx, ctx["case_id"], to_office="RESIDENCE_LIFE",
                             scope="FULL_RECORD",
                             effective_from="2026-09-01T00:00:00Z",
                             expires_at="2026-10-01T00:00:00Z")
        resp = request_grant(ctx, ctx["case_id"], to_office="RESIDENCE_LIFE",
                             scope="FULL_RECORD",
                             effective_from="2026-09-15T00:00:00Z",
                             expires_at="2026-11-01T00:00:00Z", purpose="overlapping")
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_WINDOW_OVERLAP)

    def test_adjacent_window_at_expiry_boundary_allowed(self, api):
        """PRD §3.7: "The window is half-open — inclusive at `effective_from`,
        exclusive at `expires_at` — and two temporal rules guard it:
        `expires_at` must be later than `effective_from`
        (`ERR_DISCLOSURE_WINDOW_INVALID`, 400), and the requested window must
        not intersect any existing `REQUESTED` or `APPROVED` grant for the same
        `case_id` and `to_office` pair (`ERR_DISCLOSURE_WINDOW_OVERLAP`, 409)."

        Design: Difficulty/resource_temporal_overlap/disclosure_grant_half_open_overlap
        """
        ctx = setup_staff_group(privacy_officer=True)
        setup_case_in_intake(ctx, external_ref="S1001B")
        setup_approved_grant(ctx, ctx["case_id"], to_office="RESIDENCE_LIFE",
                             scope="FULL_RECORD",
                             effective_from="2026-09-01T00:00:00Z",
                             expires_at="2026-10-01T00:00:00Z")
        # new.effective_from == existing.expires_at does not intersect half-open.
        adjacent = validate_success(
            request_grant(ctx, ctx["case_id"], to_office="RESIDENCE_LIFE",
                          scope="SUMMARY_ONLY",
                          effective_from="2026-10-01T00:00:00Z",
                          expires_at="2026-11-01T00:00:00Z",
                          purpose="adjacent renewal"),
            expected_status=201,
        )
        assert adjacent["status"] == "REQUESTED"


class TestGrantWindowShapeVsOverlapPriority:
    def test_inverted_window_reports_shape_error_not_overlap(self, api):
        """PRD §2.10: "9. **Field and constraint checks** — rubric range,
        scoring-mode consistency, enum and required-field validity, non-empty
        `objectives`, evaluator distinct from orderer, disclosure and trend
        window sanity, non-empty re-entry `conditions`, closure eligibility,
        open-plan exclusion, and pending-petition exclusion; failures yield
        `ERR_RUBRIC_SCORE_OUT_OF_RANGE`, `ERR_SCORING_MODE_INVALID`,
        `ERR_VALIDATION`, `ERR_EVALUATOR_SAME_AS_ORDERER`,
        `ERR_DISCLOSURE_WINDOW_INVALID`, `ERR_TREND_WINDOW_INVALID`, or
        `ERR_CONDITIONS_REQUIRED` (all 400), or `ERR_CASE_NOT_CLOSABLE`,
        `ERR_OPEN_PLAN_EXISTS`, or `ERR_REENTRY_ALREADY_PENDING` (all 409)."
        PRD §2.10: "10. **Temporal windows** — the assessment due-window and
        slot-occupation rules and the disclosure overlap rule; failures yield
        `ERR_ASSESSMENT_DUE_WINDOW_VIOLATION` (422),
        `ERR_ASSESSMENT_ALREADY_PENDING` (409), or
        `ERR_DISCLOSURE_WINDOW_OVERLAP` (409)."

        Design: Difficulty/priority_pair_validation_conflict/grant_window_shape_vs_overlap_conflict
        """
        ctx = setup_staff_group(privacy_officer=True)
        setup_case_in_intake(ctx, external_ref="S7002")
        setup_approved_grant(ctx, ctx["case_id"], to_office="RESIDENCE_LIFE",
                             scope="FULL_RECORD",
                             effective_from="2026-09-01T00:00:00Z",
                             expires_at="2026-10-01T00:00:00Z")
        # expires_at < effective_from (shape invalid) AND raw values intersect
        # the existing grant's window (overlap); window-shape (rank 9) wins.
        resp = request_grant(ctx, ctx["case_id"], to_office="RESIDENCE_LIFE",
                             scope="FULL_RECORD",
                             effective_from="2026-09-15T00:00:00Z",
                             expires_at="2026-09-10T00:00:00Z",
                             purpose="inverted and overlapping")
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_WINDOW_INVALID)

    def test_valid_window_overlapping_reports_overlap_error(self, api):
        """PRD §2.10: "9. **Field and constraint checks** — rubric range,
        scoring-mode consistency, enum and required-field validity, non-empty
        `objectives`, evaluator distinct from orderer, disclosure and trend
        window sanity, non-empty re-entry `conditions`, closure eligibility,
        open-plan exclusion, and pending-petition exclusion; failures yield
        `ERR_RUBRIC_SCORE_OUT_OF_RANGE`, `ERR_SCORING_MODE_INVALID`,
        `ERR_VALIDATION`, `ERR_EVALUATOR_SAME_AS_ORDERER`,
        `ERR_DISCLOSURE_WINDOW_INVALID`, `ERR_TREND_WINDOW_INVALID`, or
        `ERR_CONDITIONS_REQUIRED` (all 400), or `ERR_CASE_NOT_CLOSABLE`,
        `ERR_OPEN_PLAN_EXISTS`, or `ERR_REENTRY_ALREADY_PENDING` (all 409)."
        PRD §2.10: "10. **Temporal windows** — the assessment due-window and
        slot-occupation rules and the disclosure overlap rule; failures yield
        `ERR_ASSESSMENT_DUE_WINDOW_VIOLATION` (422),
        `ERR_ASSESSMENT_ALREADY_PENDING` (409), or
        `ERR_DISCLOSURE_WINDOW_OVERLAP` (409)."

        Design: Difficulty/priority_pair_validation_conflict/grant_window_shape_vs_overlap_conflict
        """
        ctx = setup_staff_group(privacy_officer=True)
        setup_case_in_intake(ctx, external_ref="S7002B")
        setup_approved_grant(ctx, ctx["case_id"], to_office="RESIDENCE_LIFE",
                             scope="FULL_RECORD",
                             effective_from="2026-09-01T00:00:00Z",
                             expires_at="2026-10-01T00:00:00Z")
        # Shape-valid window that overlaps: rank 9 passes, rank 10 fires.
        resp = request_grant(ctx, ctx["case_id"], to_office="RESIDENCE_LIFE",
                             scope="FULL_RECORD",
                             effective_from="2026-09-15T00:00:00Z",
                             expires_at="2026-10-15T00:00:00Z",
                             purpose="valid shape but overlapping")
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_WINDOW_OVERLAP)


class TestPrivacyScope:
    def test_reporter_without_grant_denied_case_read(self, api):
        """PRD §2.7: "Anyone else authorized to attempt the read — including a
        `Reporter` — must hold an `APPROVED`, unexpired disclosure grant issued
        to their own office for that case: a grant whose `scope` is
        `FULL_RECORD` yields the full view, while `SUMMARY_ONLY` or
        `SAFETY_MINIMUM` yields the redacted view."
        PRD §2.7: "When no role-based path and no qualifying grant exists, the
        read is rejected with `ERR_PRIVACY_SCOPE_INSUFFICIENT` (HTTP 403)."

        Design: Corner/validations/privacy_scope_insufficient_without_grant
        """
        ctx = setup_staff_group()
        setup_case_in_intake(ctx, external_ref="S0017")
        resp = api.get_care_case(ctx["case_id"], ctx["rep_headers"])
        validate_error(resp, ApiErrorId.ERR_PRIVACY_SCOPE_INSUFFICIENT)

    def test_summary_only_grant_yields_redacted_five_field_view(self, api):
        """PRD §2.7: "The redacted view contains exactly five fields: `id`,
        `student_id`, `status`, `current_risk_tier`, and `current_risk_score`."
        PRD §2.7: "Anyone else authorized to attempt the read — including a
        `Reporter` — must hold an `APPROVED`, unexpired disclosure grant issued
        to their own office for that case: a grant whose `scope` is
        `FULL_RECORD` yields the full view, while `SUMMARY_ONLY` or
        `SAFETY_MINIMUM` yields the redacted view."

        Design: Corner/validations/summary_only_grant_yields_redacted_view
        """
        ctx = setup_staff_group(privacy_officer=True)
        setup_case_in_intake(ctx, external_ref="S0018")
        setup_approved_grant(ctx, ctx["case_id"], to_office="FACULTY_AFFAIRS",
                             scope="SUMMARY_ONLY",
                             effective_from="2026-08-01T00:00:00Z",
                             expires_at="2026-09-01T00:00:00Z")
        view = validate_success(api.get_care_case(ctx["case_id"], ctx["rep_headers"]))
        assert view["id"] == ctx["case_id"]
        assert view["status"] == "INTAKE"
        # Redacted view: exactly the five fields.
        assert set(view.keys()) == {
            "id", "student_id", "status", "current_risk_tier", "current_risk_score",
        }
        assert view["student_id"] == ctx["student"]["id"]
        assert view["current_risk_tier"] is None
        assert view["current_risk_score"] is None


class TestGrantRevokeRequiresApproved:
    def test_revoke_requested_grant_rejected(self, api):
        """PRD §3.7: "Revoking moves an `APPROVED` grant to `REVOKED` and
        requires `APPROVED` (`ERR_GRANT_NOT_APPROVED`)."

        Design: Corner/state_machines/grant_revoke_from_requested_rejected
        """
        ctx = setup_staff_group(privacy_officer=True)
        setup_case_in_intake(ctx, external_ref="S0011")
        grant = get_success_data(
            request_grant(ctx, ctx["case_id"], to_office="RESIDENCE_LIFE",
                          scope="SUMMARY_ONLY",
                          effective_from="2026-08-01T00:00:00Z",
                          expires_at="2026-09-01T00:00:00Z", purpose="housing")
        )
        assert grant["status"] == "REQUESTED"
        resp = api.revoke_disclosure_grant(grant["id"], ctx["po_headers"])
        validate_error(resp, ApiErrorId.ERR_GRANT_NOT_APPROVED)
        after = get_success_data(api.get_disclosure_grant(grant["id"], ctx["po_headers"]))
        assert after["status"] == "REQUESTED"


class TestGrantExpiryBlocksRead:
    def test_expiry_sweep_retires_grant_and_revokes_access(self, api):
        """PRD §3.7: "Finally, the clock sweep retires any `APPROVED` grant
        whose `expires_at` has been reached or passed into `EXPIRED`;
        `DENIED`, `REVOKED`, and `EXPIRED` are all terminal."
        PRD §2.7: "When no role-based path and no qualifying grant exists, the
        read is rejected with `ERR_PRIVACY_SCOPE_INSUFFICIENT` (HTTP 403)."

        Design: Corner/cross_cutting_layers/grant_expiry_sweep_blocks_read
        """
        ctx = setup_staff_group(privacy_officer=True)
        setup_case_in_intake(ctx, external_ref="S0037")
        grant = setup_approved_grant(ctx, ctx["case_id"], to_office="FACULTY_AFFAIRS",
                                     scope="FULL_RECORD",
                                     effective_from="2026-08-01T00:00:00Z",
                                     expires_at="2026-08-03T00:00:00Z")
        # Before expiry: FULL_RECORD yields the unredacted view.
        full = validate_success(api.get_care_case(ctx["case_id"], ctx["rep_headers"]))
        assert full["assigned_case_manager_id"] == ctx["cm"]["id"]
        # At exactly expires_at the half-open window has closed (>= boundary).
        set_clock(ctx, "2026-08-03T00:00:00Z")
        grant_after = get_success_data(
            api.get_disclosure_grant(grant["id"], ctx["po_headers"])
        )
        assert grant_after["status"] == "EXPIRED"
        denied = api.get_care_case(ctx["case_id"], ctx["rep_headers"])
        validate_error(denied, ApiErrorId.ERR_PRIVACY_SCOPE_INSUFFICIENT)
