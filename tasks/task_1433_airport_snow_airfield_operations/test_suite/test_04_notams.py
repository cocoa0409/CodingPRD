"""NOTAM lifecycle: posture gates, closed-interval overlap, supersede cascade,
and the issue/rescind counter conservation."""
from test_helpers import (
    ApiErrorId,
    create_notam_payload,
    draft_notam,
    file_condition_report,
    get_surface,
    issue_notam,
    notam_action,
    record_friction_assessment,
    setup_event_with_surface,
    setup_issued_notam,
    setup_restricted_surface_with_friction,
    surface_action,
    validate_error,
    validate_success,
)


class TestIssueSurfaceGate:
    def test_notam_issue_requires_non_open_surface_rejected(
            self, api, ops_controller_headers):
        """PRD §3.6: "First, the referenced surface must be `RESTRICTED` or
        `CLOSED`; issuing against an `OPEN` surface is rejected with
        `ERR_INVALID_SURFACE_STATE`."

        Design: Difficulty/cross_entity_state_dependency/notam_issue_requires_non_open_surface
        """
        ctx = setup_event_with_surface(event_code="SNOW-N")
        notam = draft_notam(ctx["event"]["id"], ctx["surface"]["id"],
                            notam_type="RUNWAY_CLOSURE",
                            effective_from="2026-08-10T00:00:00Z",
                            effective_until="2026-08-11T00:00:00Z",
                            message="RWY 09L closure planned")
        resp = api.notam_action(notam["id"], {"action": "ISSUE"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_SURFACE_STATE, 409)

    def test_notam_issue_rejection_leaves_draft(
            self, api, ops_controller_headers):
        """PRD §3.6: "First, the referenced surface must be `RESTRICTED` or
        `CLOSED`; issuing against an `OPEN` surface is rejected with
        `ERR_INVALID_SURFACE_STATE`." and "A new NOTAM starts in `DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/notam_issue_requires_non_open_surface
        """
        ctx = setup_event_with_surface(event_code="SNOW-N")
        notam = draft_notam(ctx["event"]["id"], ctx["surface"]["id"],
                            notam_type="RUNWAY_CLOSURE",
                            effective_from="2026-08-10T00:00:00Z",
                            effective_until="2026-08-11T00:00:00Z",
                            message="RWY 09L closure planned")
        resp = api.notam_action(notam["id"], {"action": "ISSUE"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_SURFACE_STATE, 409)
        data = validate_success(api.get_notam(notam["id"],
                                              ops_controller_headers))
        assert data["status"] == "DRAFT"
        assert get_surface(ctx["surface"]["id"])["active_notam_count"] == 0


class TestRescindGuards:
    def test_notam_rescind_from_draft_rejected(self, api,
                                               ops_controller_headers):
        """PRD §3.6: "Attempting an action that does not match the NOTAM's
        current status — for example rescinding a `DRAFT` or issuing an
        already-`ISSUED` NOTAM — is rejected with
        `ERR_INVALID_NOTAM_STATE`."

        Design: Corner/state_machines/notam_rescind_from_draft_rejected
        """
        ctx = setup_event_with_surface(event_code="SNOW-C7")
        notam = draft_notam(ctx["event"]["id"], ctx["surface"]["id"],
                            notam_type="RUNWAY_CLOSURE",
                            effective_from="2026-08-10T00:00:00Z",
                            effective_until="2026-08-11T00:00:00Z",
                            message="planned closure")
        resp = api.notam_action(notam["id"], {"action": "RESCIND"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_NOTAM_STATE, 409)
        data = validate_success(api.get_notam(notam["id"],
                                              ops_controller_headers))
        assert data["status"] == "DRAFT"

    def test_notam_rescind_requires_open_surface_rejected(
            self, api, ops_controller_headers):
        """PRD §3.6: "Rescission is allowed from either `ISSUED` or
        `REISSUE_REQUIRED`, and in both cases requires the referenced surface
        to be `OPEN`; rescinding while the surface is `RESTRICTED` or `CLOSED`
        is rejected with `ERR_INVALID_SURFACE_STATE`."

        Design: Corner/state_machines/notam_rescind_requires_open_surface_rejected
        """
        ctx = setup_issued_notam(event_code="SNOW-C8")
        assert ctx["notam"]["status"] == "ISSUED"
        resp = api.notam_action(ctx["notam"]["id"], {"action": "RESCIND"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_SURFACE_STATE, 409)
        data = validate_success(api.get_notam(ctx["notam"]["id"],
                                              ops_controller_headers))
        assert data["status"] == "ISSUED"


class TestClosedIntervalOverlap:
    def _setup_touching_notams(self):
        """N1 ISSUED on [08-10T00:00Z, 08-10T06:00Z]; N2 drafted."""
        ctx = setup_event_with_surface(event_code="SNOW-P")
        event_id = ctx["event"]["id"]
        surface_id = ctx["surface"]["id"]
        surface_action(surface_id, "CLOSE", event_id)
        n1 = draft_notam(event_id, surface_id, notam_type="RUNWAY_CLOSURE",
                         effective_from="2026-08-10T00:00:00Z",
                         effective_until="2026-08-10T06:00:00Z",
                         message="RWY 09L closed AM")
        n1 = issue_notam(n1["id"])
        assert n1["status"] == "ISSUED"
        return ctx, n1

    def test_notam_window_closed_interval_touch_conflict(
            self, api, ops_controller_headers):
        """PRD §3.6: "the closed window `[effective_from, effective_until]`
        must share no instant with any other `ISSUED` NOTAM on the same
        surface with the same `notam_type` — and under closed-interval
        semantics, touching endpoints count as overlap. A conflict yields
        `ERR_NOTAM_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/notam_window_closed_interval_touch_conflict
        """
        ctx, n1 = self._setup_touching_notams()
        n2 = draft_notam(ctx["event"]["id"], ctx["surface"]["id"],
                         notam_type="RUNWAY_CLOSURE",
                         effective_from="2026-08-10T06:00:00Z",
                         effective_until="2026-08-10T12:00:00Z",
                         message="RWY 09L closed PM")
        resp = api.notam_action(n2["id"], {"action": "ISSUE"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_NOTAM_WINDOW_OVERLAP, 409)
        data = validate_success(api.get_notam(n2["id"],
                                              ops_controller_headers))
        assert data["status"] == "DRAFT"

    def test_notam_window_with_gap_is_allowed(
            self, api, ops_controller_headers):
        """PRD §3.6: "the closed window `[effective_from, effective_until]`
        must share no instant with any other `ISSUED` NOTAM on the same
        surface with the same `notam_type` — and under closed-interval
        semantics, touching endpoints count as overlap."

        Design: Difficulty/resource_temporal_overlap/notam_window_closed_interval_touch_conflict
        """
        ctx, n1 = self._setup_touching_notams()
        n3 = draft_notam(ctx["event"]["id"], ctx["surface"]["id"],
                         notam_type="RUNWAY_CLOSURE",
                         effective_from="2026-08-10T06:00:01Z",
                         effective_until="2026-08-10T12:00:00Z",
                         message="RWY 09L closed midday")
        resp = api.notam_action(n3["id"], {"action": "ISSUE"},
                                ops_controller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "ISSUED", (
            "a window starting one second after the issued window's end "
            f"shares no instant and must issue; got {data['status']}")


class TestSafetyGatePriorityConflict:
    def _setup_poor_friction_overlapping_draft(self):
        """N1 ISSUED (RUNWAY_CLOSURE); latest REPORTED braking POOR; N2 DRAFT
        (SURFACE_CONDITION, sourced from the POOR assessment)."""
        ctx = setup_event_with_surface(event_code="SNOW-J")
        event_id = ctx["event"]["id"]
        surface_id = ctx["surface"]["id"]
        closed = surface_action(surface_id, "CLOSE", event_id)
        record_friction_assessment(event_id, surface_id, mu_value=0.60,
                                   expected_surface_version=closed["version"])
        n1 = draft_notam(event_id, surface_id, notam_type="RUNWAY_CLOSURE",
                         effective_from="2026-08-10T00:00:00Z",
                         effective_until="2026-08-11T00:00:00Z",
                         message="RWY 09L closed")
        issue_notam(n1["id"])
        poor = record_friction_assessment(event_id, surface_id,
                                          mu_value=0.20)
        assert poor["braking_action"] == "POOR"
        n2 = draft_notam(event_id, surface_id, notam_type="SURFACE_CONDITION",
                         effective_from="2026-08-10T12:00:00Z",
                         effective_until="2026-08-12T00:00:00Z",
                         message="RWY 09L icy patches",
                         source_assessment_id=poor["id"])
        return ctx, n1, poor, n2

    def test_notam_issue_safety_error_beats_overlap_error(
            self, api, ops_controller_headers):
        """PRD §3.6: "Second, when `notam_type` is `SURFACE_CONDITION`, the
        latest `REPORTED` `FrictionAssessment` on the surface, if one exists,
        must have `braking_action` other than `POOR` or `NIL`; otherwise the
        issuance is rejected with `ERR_UNSAFE_NOTAM_CONDITION`."
        PRD §2.9: "The order is not stylistic — a caller hitting two
        violations must see the earlier one."

        Design: Difficulty/priority_pair_validation_conflict/notam_issue_safety_error_beats_overlap_error
        """
        ctx, n1, poor, n2 = self._setup_poor_friction_overlapping_draft()
        resp = api.notam_action(n2["id"], {"action": "ISSUE"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_UNSAFE_NOTAM_CONDITION, 409)

    def test_notam_issue_safety_rejection_leaves_draft_and_count(
            self, api, ops_controller_headers):
        """PRD §3.6: "otherwise the issuance is rejected with
        `ERR_UNSAFE_NOTAM_CONDITION`."
        PRD §3.6: "A successful issue adds `1` to the surface's
        `active_notam_count` and increments the NOTAM's `version`."

        Design: Difficulty/priority_pair_validation_conflict/notam_issue_safety_error_beats_overlap_error
        """
        ctx, n1, poor, n2 = self._setup_poor_friction_overlapping_draft()
        resp = api.notam_action(n2["id"], {"action": "ISSUE"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_UNSAFE_NOTAM_CONDITION, 409)
        data = validate_success(api.get_notam(n2["id"],
                                              ops_controller_headers))
        assert data["status"] == "DRAFT", "no partial issue may occur"
        assert get_surface(ctx["surface"]["id"])["active_notam_count"] == 1, (
            "only N1 remains counted after the rejected issue")


class TestSupersedeCascade:
    def _setup_issued_notam_sourced_from_report(self):
        """Report R1 filed; NOTAM N1 ISSUED sourced from R1."""
        ctx = setup_restricted_surface_with_friction(event_code="SNOW-G",
                                                     mu_value=0.60)
        r1 = file_condition_report(ctx["event"]["id"],
                                   ctx["surface"]["id"],
                                   contaminant_type="DRY_SNOW",
                                   coverage_pct=40, depth_inches=0.2)
        n1 = draft_notam(ctx["event"]["id"], ctx["surface"]["id"],
                         notam_type="SURFACE_CONDITION",
                         effective_from="2026-08-02T00:00:00Z",
                         effective_until="2026-08-03T00:00:00Z",
                         message="RWY 09L compacted snow",
                         source_report_id=r1["id"])
        n1 = issue_notam(n1["id"])
        assert n1["status"] == "ISSUED"
        assert get_surface(ctx["surface"]["id"])["active_notam_count"] == 1
        return ctx, r1, n1

    def test_report_supersede_flips_report_and_notam(
            self, api, ops_controller_headers):
        """PRD §3.4: "Filing a newer report for the same (`event_id`,
        `surface_id`) supersedes the prior `FILED` report: the older row's
        `status` becomes `SUPERSEDED`, its `superseded_by_id` is set to the
        newer report's `id`, every `ISSUED` `Notam` whose `source_report_id`
        names the superseded report flips to `REISSUE_REQUIRED`".

        Design: Difficulty/transitive_cascade/report_supersede_to_notam_reissue_cascade
        """
        ctx, r1, n1 = self._setup_issued_notam_sourced_from_report()
        r2 = file_condition_report(ctx["event"]["id"],
                                   ctx["surface"]["id"],
                                   contaminant_type="ICE", coverage_pct=60,
                                   depth_inches=0.5)
        old = validate_success(api.get_condition_report(
            r1["id"], ops_controller_headers))
        assert old["status"] == "SUPERSEDED"
        assert old["superseded_by_id"] == r2["id"], (
            "link 1: the superseded report must point at the newer report")
        flipped = validate_success(api.get_notam(n1["id"],
                                                 ops_controller_headers))
        assert flipped["status"] == "REISSUE_REQUIRED", (
            "link 2: the ISSUED NOTAM sourced from the superseded report "
            f"must flip to REISSUE_REQUIRED, got {flipped['status']}")

    def test_report_supersede_recomputes_active_notam_count(
            self, api, ops_controller_headers):
        """PRD §3.4: "each such flip recomputes the surface's
        `active_notam_count`."
        PRD §3.6: "that flip subtracts `1` from the surface's
        `active_notam_count` because `REISSUE_REQUIRED` rows are not counted."

        Design: Difficulty/transitive_cascade/report_supersede_to_notam_reissue_cascade
        """
        ctx, r1, n1 = self._setup_issued_notam_sourced_from_report()
        before = get_surface(ctx["surface"]["id"])
        assert before["active_notam_count"] == 1

        file_condition_report(ctx["event"]["id"], ctx["surface"]["id"],
                              contaminant_type="ICE", coverage_pct=60,
                              depth_inches=0.5)
        after = get_surface(ctx["surface"]["id"])
        assert after["active_notam_count"] == 0, (
            "link 3: the NOTAM flip must decrement the surface counter to 0, "
            f"got {after['active_notam_count']}")


class TestNotamCountConservation:
    def test_issue_increments_active_notam_count(self, api):
        """PRD §3.6: "A successful issue adds `1` to the surface's
        `active_notam_count` and increments the NOTAM's `version`."

        Design: Difficulty/compensating_invariant/notam_active_count_issue_rescind_conservation
        """
        ctx = setup_restricted_surface_with_friction(event_code="SNOW-R",
                                                     mu_value=0.60)
        notam = draft_notam(ctx["event"]["id"], ctx["surface"]["id"],
                            notam_type="SURFACE_CONDITION",
                            effective_from="2026-08-02T00:00:00Z",
                            effective_until="2026-08-03T00:00:00Z",
                            message="RWY 09L wet snow",
                            source_assessment_id=ctx["assessment"]["id"])
        baseline = get_surface(ctx["surface"]["id"])["active_notam_count"]
        issued = issue_notam(notam["id"])
        assert issued["status"] == "ISSUED"
        after = get_surface(ctx["surface"]["id"])
        assert after["active_notam_count"] == baseline + 1, (
            f"ISSUE must add exactly 1 ({baseline} -> "
            f"{after['active_notam_count']})")

    def test_rescind_compensates_issue_count(self, api):
        """PRD §3.6: "Rescinding from `ISSUED` subtracts `1` from
        `active_notam_count`; rescinding from `REISSUE_REQUIRED` does not
        change the count (the row was already not counted). Both paths move
        the NOTAM to `RESCINDED` and increment `version`."

        Design: Difficulty/compensating_invariant/notam_active_count_issue_rescind_conservation
        """
        ctx = setup_issued_notam(event_code="SNOW-R", mu_value=0.60)
        surface_id = ctx["surface"]["id"]
        assert get_surface(surface_id)["active_notam_count"] == 1

        # RESCIND requires the surface OPEN: RESTRICTED -> OPEN via CLEAR.
        surface_action(surface_id, "CLEAR", ctx["event"]["id"])
        rescinded = notam_action(ctx["notam"]["id"], "RESCIND")
        assert rescinded["status"] == "RESCINDED"
        after = get_surface(surface_id)
        assert after["active_notam_count"] == 0, (
            "RESCIND must compensate the ISSUE increment exactly, got "
            f"{after['active_notam_count']}")
