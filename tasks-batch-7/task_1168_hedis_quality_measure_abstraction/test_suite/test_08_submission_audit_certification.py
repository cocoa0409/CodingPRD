"""Submission, audit engagement, and director certification.

Covers the pinned submit precondition order, the certification reopen cycle, the
certification aggregate gate, engagement windows and auditor overlap, and the
default logical clock.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    compute_rate,
    create_active_spec,
    create_and_open_season,
    create_certify_payload,
    create_engagement_payload,
    create_finding_payload,
    create_run,
    create_season,
    get_run,
    get_season,
    identify_population,
    list_engagement_findings,
    make_quality_analyst_headers,
    make_quality_director_headers,
    register_enrolled_member,
    set_clock,
    setup_engagement,
    setup_submitted_run,
    validate_error,
    validate_success,
    get_success_data,
)

ADMIN = TEST_USERS["quality_admin_headers"]
ANALYST = TEST_USERS["quality_analyst_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

QA1 = make_quality_analyst_headers("qa-1")
DIR1 = make_quality_director_headers("dir-1")


def _draft_season_computed_run(api):
    """Season left in DRAFT; spec activated (legal in DRAFT); one member; run
    advanced to RATE_COMPUTED."""
    season = create_season(api, approved_supplemental_sources=["LAB_FEED"])
    spec = create_active_spec(api, season["id"], hedis_measure_code="CBP")
    register_enrolled_member(api, "M01", gender="M")
    run = identify_population(api, create_run(api, season["id"], spec["id"])["id"])
    run = compute_rate(api, run["id"])
    return season, spec, run


class TestSubmitSeasonGate:
    def test_submit_rejected_while_season_draft(self, api):
        """The same RATE_COMPUTED run is rejected while its season is DRAFT: the
        season-state guard, not the run's own state, blocks the transition.

        PRD §3.8: "Three preconditions apply in a pinned order: the run must be
        `RATE_COMPUTED`, else `ERR_RUN_NOT_SUBMITTABLE` — this check is evaluated
        before the season-state and deadline checks; the run's season must be `OPEN`,
        else `ERR_SEASON_NOT_OPEN`; and the logical clock's current instant must be at
        or before the season's `submission_deadline`, else
        `ERR_SUBMISSION_DEADLINE_PASSED` — evaluated after the run-state and
        season-state checks."

        Design: Difficulty/cross_entity_state_dependency/submit_gated_on_season_open
        """
        season, _spec, run = _draft_season_computed_run(api)
        assert run["reporting_status"] == "RATE_COMPUTED"
        resp = api.submit_run(run["id"], QA1)
        validate_error(resp, ApiErrorId.ERR_SEASON_NOT_OPEN)

    def test_submit_accepted_once_season_open(self, api):
        """After the season opens, the identical submit succeeds and stamps the
        caller as submitted_by_user_id.

        PRD §3.8: "the run's season must be `OPEN`, else `ERR_SEASON_NOT_OPEN`"
        PRD §3.8: "On success the run records the caller as `submitted_by_user_id`, a
        `HYBRID` run's sample moves from `FINALIZED` to the terminal `LOCKED`
        (incrementing the sample's `version`), and the run's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/submit_gated_on_season_open
        """
        season, _spec, run = _draft_season_computed_run(api)
        validate_success(api.open_season(season["id"], ADMIN))
        submitted = validate_success(api.submit_run(run["id"], QA1))
        assert submitted["reporting_status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == "qa-1"


class TestSubmitPreconditionOrder:
    def _deadline_pair(self, api):
        """Season with a deadline already before the default logical clock
        (2026-05-01); run1 left POPULATED (state violation armed), run2 advanced to
        RATE_COMPUTED (only the deadline violation armed)."""
        season = create_and_open_season(
            api,
            submission_deadline="2026-04-01T00:00:00Z",
            admin_data_cutoff="2026-03-01T00:00:00Z",
            approved_supplemental_sources=["LAB_FEED"],
        )
        spec1 = create_active_spec(api, season["id"], hedis_measure_code="D1")
        spec2 = create_active_spec(api, season["id"], hedis_measure_code="D2")
        register_enrolled_member(api, "M1", gender="F")
        run1 = identify_population(api, create_run(api, season["id"], spec1["id"])["id"])
        run2 = identify_population(api, create_run(api, season["id"], spec2["id"])["id"])
        run2 = compute_rate(api, run2["id"])
        return season, run1, run2

    def test_submit_state_error_masks_deadline(self, api):
        """On a submit where the run is not RATE_COMPUTED and the deadline has
        passed, the state error wins.

        PRD §3.8: "the run must be `RATE_COMPUTED`, else `ERR_RUN_NOT_SUBMITTABLE` —
        this check is evaluated before the season-state and deadline checks"
        PRD §2.9: "a submission from a non-`RATE_COMPUTED` run surfaces
        `ERR_RUN_NOT_SUBMITTABLE` even when the season is also closed"

        Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_deadline_temporal
        """
        season, run1, run2 = self._deadline_pair(api)
        assert get_season(api, season["id"])["status"] == "OPEN", (
            "the default clock was never advanced, so the season never auto-closed"
        )
        assert run2["reporting_status"] == "RATE_COMPUTED"
        resp = api.submit_run(run1["id"], QA1)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_SUBMITTABLE)

    def test_submit_deadline_error_after_state_passes(self, api):
        """With the run RATE_COMPUTED and the season OPEN, the temporal check fires:
        the default clock (2026-05-01) sits past the 2026-04-01 deadline.

        PRD §3.8: "the logical clock's current instant must be at or before the
        season's `submission_deadline`, else `ERR_SUBMISSION_DEADLINE_PASSED` —
        evaluated after the run-state and season-state checks."
        PRD §2.5: "At startup the clock reads exactly 2026-05-01T00:00:00Z, and it
        never falls back to wall-clock time thereafter."

        Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_deadline_temporal
        """
        _season, _run1, run2 = self._deadline_pair(api)
        resp = api.submit_run(run2["id"], QA1)
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_DEADLINE_PASSED)


class TestCertificationReopenCycle:
    def _fail_first_pass(self, api):
        """Submitted run -> engagement IN_REVIEW -> completed FAIL -> AUDIT_FAILED
        with the auto-minted CRITICAL finding; certify FAILED; reopen."""
        scenario = setup_submitted_run(api, member_refs=("M01",), analyst_id="qa-1")
        eng1 = setup_engagement(api, scenario["season"]["id"], scenario["run"]["id"])
        eng1 = get_success_data(api.begin_review(eng1["id"], AUDITOR))
        return scenario, eng1

    def test_audit_fail_certify_failed_reopen_resets(self, api):
        """A FAIL completion moves the audit dimension to AUDIT_FAILED and
        auto-mints an OPEN CRITICAL finding; the FAILED certification branch needs
        no audit pass; reopen returns the run to POPULATED and resets the audit
        dimension independently.

        PRD §3.8: "A `FAIL` moves it to `AUDIT_FAILED` and additionally auto-mints an
        audit finding with `severity` `CRITICAL`, status `OPEN`, and the summary text
        \"AUDIT_OUTCOME_FAIL\", linked to this engagement."
        PRD §3.8: "The `FAILED` branch instead moves the run to
        `CERTIFICATION_FAILED`, incrementing its `version`, with no season-side
        effects."
        PRD §3.8: "Reopening moves the run from `CERTIFICATION_FAILED` back to
        `POPULATED`: the audit dimension resets, `audit_status` returning to
        `UNAUDITED`"

        Design: Difficulty/non_linear_state_machine/measure_run_certification_reopen_cycle
        """
        scenario, eng1 = self._fail_first_pass(api)
        run_id = scenario["run"]["id"]
        assert scenario["run"]["denominator_count"] == 1
        get_success_data(
            api.complete_engagement(eng1["id"], {"outcome": "FAIL"}, AUDITOR)
        )
        run_mid = get_run(api, run_id)
        assert run_mid["audit_status"] == "AUDIT_FAILED"
        findings, _ = list_engagement_findings(api, eng1["id"])
        assert findings[0]["severity"] == "CRITICAL"
        assert findings[0]["status"] == "OPEN"
        assert findings[0]["summary"] == "AUDIT_OUTCOME_FAIL"
        failed = validate_success(api.certify_run(run_id, create_certify_payload("FAILED"), DIR1))
        assert failed["reporting_status"] == "CERTIFICATION_FAILED"
        reopened = validate_success(api.reopen_run(run_id, QA1))
        assert reopened["reporting_status"] == "POPULATED"
        assert reopened["audit_status"] == "UNAUDITED", (
            "reopen resets the parallel audit dimension independently of reporting"
        )

    def test_second_pass_certifies_and_increments_season_counter(self, api):
        """After reopen, the loop closes: recompute, resubmit, re-review (PASS),
        resolve the stale finding, certify CERTIFIED — and the season's
        certified_run_count increments.

        PRD §3.8: "A successful certification records the director as
        `certified_by_user_id` and fires a two-link cascade: the season's
        `certified_run_count` increments by 1, and the moment that counter equals the
        total number of measure runs of the season, the season auto-transitions from
        `OPEN` to `SUBMISSION_CLOSED`."
        PRD §3.8: "because the intervals are half-open, adjacent windows where one
        engagement's end equals the next's start do not overlap and are permitted."
        PRD §3.8: "the engagement's run must be `SUBMITTED`, and the run's
        `audit_status` must be `UNAUDITED` or `AUDIT_FAILED` — the latter admitting
        re-review after a failed audit"

        Design: Difficulty/non_linear_state_machine/measure_run_certification_reopen_cycle
        """
        scenario, eng1 = self._fail_first_pass(api)
        run_id = scenario["run"]["id"]
        season_id = scenario["season"]["id"]
        get_success_data(api.complete_engagement(eng1["id"], {"outcome": "FAIL"}, AUDITOR))
        findings, _ = list_engagement_findings(api, eng1["id"])
        finding_id = findings[0]["id"]
        validate_success(api.certify_run(run_id, create_certify_payload("FAILED"), DIR1))
        validate_success(api.reopen_run(run_id, QA1))
        compute_rate(api, run_id, user_id="qa-1")
        validate_success(api.submit_run(run_id, QA1))
        eng2 = setup_engagement(
            api, season_id, run_id,
            window_start="2026-07-01T00:00:00Z", window_end="2026-08-01T00:00:00Z",
        )
        set_clock(api, "2026-07-02T00:00:00Z")
        get_success_data(api.begin_review(eng2["id"], AUDITOR))
        validate_success(api.resolve_finding(finding_id, AUDITOR))
        get_success_data(api.complete_engagement(eng2["id"], {"outcome": "PASS"}, AUDITOR))
        certified = validate_success(
            api.certify_run(run_id, create_certify_payload("CERTIFIED"), DIR1)
        )
        assert certified["reporting_status"] == "CERTIFIED"
        assert certified["audit_status"] == "AUDIT_PASSED"
        assert certified["certified_by_user_id"] == "dir-1"
        season = get_season(api, season_id)
        assert season["certified_run_count"] == 1, (
            "the certify cascade incremented the season counter"
        )


class TestCertificationGate:
    def test_certify_blocked_by_open_critical_finding(self, api):
        """Certification is an aggregate gate: AUDIT_PASSED alone is insufficient
        while an OPEN CRITICAL finding is linked to the run through an engagement;
        resolving it unblocks certification.

        PRD §3.8: "The `CERTIFIED` branch adds two further requirements, both
        surfacing as `ERR_RUN_NOT_CERTIFIABLE`: the run's `audit_status` must be
        `AUDIT_PASSED`, and no audit finding with `severity` `CRITICAL` and status
        `OPEN` may be linked to the run through any engagement's `measure_run_id`."

        Design: Corner/validations/certify_blocked_by_open_critical_finding
        """
        set_clock(api, "2026-04-15T00:00:00Z")
        scenario = setup_submitted_run(api, member_refs=("M1",), analyst_id="qa-1")
        run_id = scenario["run"]["id"]
        season_id = scenario["season"]["id"]
        eng1 = setup_engagement(
            api, season_id, run_id,
            window_start="2026-04-01T00:00:00Z", window_end="2026-05-01T00:00:00Z",
        )
        get_success_data(api.begin_review(eng1["id"], AUDITOR))
        get_success_data(api.complete_engagement(eng1["id"], {"outcome": "FAIL"}, AUDITOR))
        findings, _ = list_engagement_findings(api, eng1["id"])
        assert findings[0]["status"] == "OPEN"
        assert findings[0]["severity"] == "CRITICAL"
        eng2 = setup_engagement(
            api, season_id, run_id,
            window_start="2026-05-01T00:00:00Z", window_end="2026-06-01T00:00:00Z",
        )
        set_clock(api, "2026-05-15T00:00:00Z")
        get_success_data(api.begin_review(eng2["id"], AUDITOR))
        get_success_data(api.complete_engagement(eng2["id"], {"outcome": "PASS"}, AUDITOR))
        assert get_run(api, run_id)["audit_status"] == "AUDIT_PASSED"
        resp = api.certify_run(run_id, create_certify_payload("CERTIFIED"), DIR1)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_CERTIFIABLE)
        validate_success(api.resolve_finding(findings[0]["id"], AUDITOR))
        certified = validate_success(
            api.certify_run(run_id, create_certify_payload("CERTIFIED"), DIR1)
        )
        assert certified["reporting_status"] == "CERTIFIED"

    def test_sod_submitter_certify_returns_403(self, api):
        """The analyst who submitted the run may not certify it; the SoD check
        fires before the certifiability gate (the run is also UNAUDITED here).

        PRD §2.8: "Second, a run may never be certified by the analyst who submitted
        it: the certifier's `X-User-ID` must differ from the run's
        `submitted_by_user_id`, and a violation is rejected with
        `ERR_SOD_SUBMITTER_CERTIFY`."
        PRD §2.9: "8. **Segregation of duties.** The over-read self-review check
        returns `ERR_SOD_SELF_OVERREAD` (HTTP 403) and the submitter-certifier check
        returns `ERR_SOD_SUBMITTER_CERTIFY` (HTTP 403)"

        Design: Corner/validations/sod_submitter_certify_returns_403
        """
        scenario = setup_submitted_run(
            api, member_refs=("M1",), analyst_id="qa-1",
            season_overrides={"approved_supplemental_sources": []},
        )
        assert scenario["run"]["submitted_by_user_id"] == "qa-1"
        resp = api.certify_run(
            scenario["run"]["id"],
            create_certify_payload("CERTIFIED"),
            make_quality_director_headers("qa-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_SUBMITTER_CERTIFY)


class TestEngagementWindows:
    def test_begin_review_outside_window_returns_422(self, api):
        """begin-review is temporal-gated by the engagement's half-open window: the
        default clock 2026-05-01 is outside [2026-01-01, 2026-02-01).

        PRD §3.8: "The logical clock must currently sit inside the half-open window —
        at or after `window_start` and strictly before `window_end` — else
        `ERR_OUTSIDE_ENGAGEMENT_WINDOW`."

        Design: Corner/validations/begin_review_outside_window_returns_422
        """
        scenario = setup_submitted_run(
            api, member_refs=("M1",), analyst_id="qa-1",
            season_overrides={"approved_supplemental_sources": []},
        )
        engagement = setup_engagement(
            api, scenario["season"]["id"], scenario["run"]["id"],
            window_start="2026-01-01T00:00:00Z", window_end="2026-02-01T00:00:00Z",
        )
        resp = api.begin_review(engagement["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_ENGAGEMENT_WINDOW)

    def test_engagement_window_invalid_returns_422(self, api):
        """An empty (equal-endpoint) engagement window is rejected at creation.

        PRD §3.8: "The window is **half-open**: it includes `window_start` and
        excludes `window_end`, and creating an engagement whose `window_end` is not
        strictly after `window_start` is rejected with
        `ERR_ENGAGEMENT_WINDOW_INVALID`."

        Design: Corner/validations/engagement_window_invalid_returns_422
        """
        season = create_season(api, approved_supplemental_sources=[])
        spec = create_active_spec(api, season["id"], hedis_measure_code="CBP")
        run = create_run(api, season["id"], spec["id"])
        resp = api.create_engagement(
            create_engagement_payload(
                season["id"], run["id"],
                window_start="2026-05-01T00:00:00Z", window_end="2026-05-01T00:00:00Z",
            ),
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_WINDOW_INVALID)

    def test_engagement_complete_from_scheduled_rejected(self, api):
        """Complete requires IN_REVIEW; a SCHEDULED engagement cannot be completed.

        PRD §3.8: "Completing the review moves the engagement from `IN_REVIEW` to the
        terminal `COMPLETED` with an `outcome` of `PASS` or `FAIL`, recorded on the
        engagement."

        Design: Corner/state_machines/engagement_complete_from_scheduled_rejected
        """
        season = create_season(api, approved_supplemental_sources=[])
        spec = create_active_spec(api, season["id"], hedis_measure_code="CBP")
        run = create_run(api, season["id"], spec["id"])
        engagement = setup_engagement(api, season["id"], run["id"])
        assert engagement["status"] == "SCHEDULED"
        resp = api.complete_engagement(engagement["id"], {"outcome": "PASS"}, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_auditor_halfopen_adjacency_accepted_interior_rejected(self, api):
        """Half-open auditor windows: an engagement whose window_start equals the
        existing window's window_end is adjacency, not overlap; a strictly interior
        window is rejected.

        PRD §3.8: "One auditor may not hold overlapping engagements: a new window is
        rejected with `ERR_AUDITOR_WINDOW_OVERLAP` when its start falls strictly
        before an existing engagement's end while its end falls strictly after that
        engagement's start — and because the intervals are half-open, adjacent windows
        where one engagement's end equals the next's start do not overlap and are
        permitted."

        Design: Difficulty/resource_temporal_overlap/auditor_engagement_halfopen_adjacency
        """
        season = create_season(api, approved_supplemental_sources=[])
        spec = create_active_spec(api, season["id"], hedis_measure_code="CBP")
        run = create_run(api, season["id"], spec["id"])
        first = validate_success(
            api.create_engagement(
                create_engagement_payload(
                    season["id"], run["id"],
                    window_start="2026-04-01T00:00:00Z", window_end="2026-05-01T00:00:00Z",
                ),
                AUDITOR,
            ),
            201,
        )
        assert first["status"] == "SCHEDULED"
        adjacent = api.create_engagement(
            create_engagement_payload(
                season["id"], run["id"],
                window_start="2026-05-01T00:00:00Z", window_end="2026-06-01T00:00:00Z",
            ),
            AUDITOR,
        )
        validate_success(adjacent, 201)
        interior = api.create_engagement(
            create_engagement_payload(
                season["id"], run["id"],
                window_start="2026-04-15T00:00:00Z", window_end="2026-04-20T00:00:00Z",
            ),
            AUDITOR,
        )
        validate_error(interior, ApiErrorId.ERR_AUDITOR_WINDOW_OVERLAP)

    def test_same_window_under_different_auditor_accepted(self, api):
        """The overlap resource is the auditor: an identical window held by another
        auditor is accepted.

        PRD §3.8: "One auditor may not hold overlapping engagements: a new window is
        rejected with `ERR_AUDITOR_WINDOW_OVERLAP` when its start falls strictly
        before an existing engagement's end while its end falls strictly after that
        engagement's start"
        PRD §3.8: "Audit engagements are scheduled by an `Auditor` supplying
        `season_id`, `measure_run_id`, `auditor_user_id`, `window_start`, and
        `window_end`."

        Design: Difficulty/resource_temporal_overlap/auditor_engagement_halfopen_adjacency
        """
        season = create_season(api, approved_supplemental_sources=[])
        spec = create_active_spec(api, season["id"], hedis_measure_code="CBP")
        run = create_run(api, season["id"], spec["id"])
        validate_success(
            api.create_engagement(
                create_engagement_payload(
                    season["id"], run["id"], auditor_user_id="aud-1",
                    window_start="2026-04-01T00:00:00Z", window_end="2026-05-01T00:00:00Z",
                ),
                AUDITOR,
            ),
            201,
        )
        other = api.create_engagement(
            create_engagement_payload(
                season["id"], run["id"], auditor_user_id="aud-2",
                window_start="2026-04-01T00:00:00Z", window_end="2026-05-01T00:00:00Z",
            ),
            AUDITOR,
        )
        validate_success(other, 201)


class TestFindings:
    def test_finding_resolve_terminal_lockdown(self, api):
        """OPEN -> RESOLVED is one-way; resolving an already-RESOLVED finding is
        rejected.

        PRD §3.8: "Beyond the automatic one, an `Auditor` files findings on an
        engagement by supplying `engagement_id`, a `severity` of `CRITICAL`, `MAJOR`,
        or `MINOR`, and a free-text `summary`; findings start `OPEN` and are resolved
        by moving them to the terminal `RESOLVED`, incrementing the finding's
        `version`."

        Design: Corner/state_machines/finding_resolve_terminal_lockdown
        """
        season = create_season(api, approved_supplemental_sources=[])
        spec = create_active_spec(api, season["id"], hedis_measure_code="CBP")
        run = create_run(api, season["id"], spec["id"])
        engagement = setup_engagement(api, season["id"], run["id"])
        finding = validate_success(
            api.create_finding(
                create_finding_payload(engagement["id"], "MINOR", "documentation nit"),
                AUDITOR,
            ),
            201,
        )
        resolved = validate_success(api.resolve_finding(finding["id"], AUDITOR))
        assert resolved["status"] == "RESOLVED"
        resp = api.resolve_finding(finding["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDefaultClock:
    def test_default_logical_clock_accepts_predeadline_submit(self, api):
        """Without any clock call the logical clock is exactly
        2026-05-01T00:00:00Z: a season with deadline 2026-06-15 accepts a submit.

        PRD §2.5: "At startup the clock reads exactly 2026-05-01T00:00:00Z, and it
        never falls back to wall-clock time thereafter."
        PRD §2.5: "Run submissions, by contrast, are accepted at or before the
        deadline instant — a submission whose logical-clock time equals the season's
        `submission_deadline` exactly is still on time."

        Design: Corner/cross_cutting_complexity_layers/default_logical_clock_accepts_predeadline_submit
        """
        scenario = setup_submitted_run(api, member_refs=("M1",), analyst_id="qa-1")
        assert scenario["run"]["reporting_status"] == "SUBMITTED"
