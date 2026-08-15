"""Build lifecycle and retest loop, bug intake/triage/lifecycle, the blocker
counter, triage SLA breach boundary, and the three-hop blocker cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_budget_invariant,
    close_bug_fully,
    create_bug,
    create_bug_payload,
    create_build,
    create_build_payload,
    create_release_window,
    create_title,
    get_build,
    get_bug,
    get_package,
    get_release_window,
    get_title,
    ops_run,
    set_clock,
    setup_submittable_package,
    submit_package,
    transition_build,
    transition_bug,
    triage_bug,
    validate_error,
    validate_paginated,
    validate_success,
)

QA_HEADERS = TEST_USERS["qa_lead_headers"]


class TestBuildUniqueness:
    def test_build_version_unique_per_title_and_platform(self, api,
                                                         qa_lead_headers):
        """PRD §3.4: "A `QALead` registers each **build** against a title and
        platform, giving a `version_string` that must be unique for that
        title-and-platform pair (`ERR_DUPLICATE_BUILD_VERSION`)"

        Design: Corner/entities/build_duplicate_version_rejected
        """
        title = create_title(title_code="ENT-T6", platform_codes=["PS5", "PC"],
                             cert_budget_total_cents=1000)
        validate_success(
            api.create_build(
                create_build_payload(title["id"], "PS5", "1.0.0"),
                qa_lead_headers,
            ),
            expected_status=201,
        )
        resp = api.create_build(
            create_build_payload(title["id"], "PS5", "1.0.0"), qa_lead_headers
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BUILD_VERSION)
        validate_success(
            api.create_build(
                create_build_payload(title["id"], "PC", "1.0.0"),
                qa_lead_headers,
            ),
            expected_status=201,
        )


class TestBugIntake:
    def test_bug_with_unknown_severity_enum_rejected(self, api, qa_lead_headers):
        """PRD §3.4: "a `severity` of `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`,
        or `TRIVIAL`"
        PRD §2.8: "Malformed requests — a missing required field, an unknown
        enum value, a wrong-typed value, an out-of-range scalar, or a window
        whose end is not strictly after its start — are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400) at the point the malformation is
        detected."

        Design: Corner/entities/bug_invalid_severity_enum_rejected
        """
        title = create_title(title_code="ENT-T4", cert_budget_total_cents=1000)
        build = create_build(title["id"], "PS5", "1.0.0")
        resp = api.create_bug(
            create_bug_payload(title["id"], build["id"], severity="COSMIC",
                               category="GAMEPLAY"),
            qa_lead_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _rows, meta = validate_paginated(
            api.list_bugs(qa_lead_headers, params={"title_id": title["id"]})
        )
        assert meta["total_count"] == 0

    def test_regression_target_must_be_closed_first(self, api):
        """PRD §3.4: "`regression_of_id` — also null when omitted — links the
        report to an earlier bug of the same title that is `RESOLVED`,
        `VERIFIED`, or `CLOSED` at creation; a target in any other state is
        rejected with `ERR_REGRESSION_TARGET_NOT_CLOSED`. The computed
        `is_regression` flag is true exactly when a regression link is
        present."

        Design: Corner/validations/regression_target_must_be_closed_first
        """
        title = create_title(title_code="VAL-REG", cert_budget_total_cents=1000)
        build = create_build(title["id"], "PS5", "1.0.0")
        transition_build(build["id"], "IN_TEST")
        g1 = create_bug(title["id"], build["id"], severity="MAJOR",
                        category="GAMEPLAY")
        resp = api.create_bug(
            create_bug_payload(title["id"], build["id"], severity="MAJOR",
                               category="GAMEPLAY",
                               regression_of_id=g1["id"]),
            QA_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_REGRESSION_TARGET_NOT_CLOSED)
        close_bug_fully(g1["id"], severity="MAJOR")
        g2 = create_bug(title["id"], build["id"], severity="MAJOR",
                        category="GAMEPLAY", regression_of_id=g1["id"])
        assert g2["is_regression"] is True


class TestOpenBlockerCounter:
    def test_blocker_counter_tracks_bug_lifecycle(self, api):
        """PRD §3.1: "Promotion from `CERT_APPROVED` to `LAUNCHED` requires
        the title's `open_blocker_count` — the number of its own bug reports
        with severity `BLOCKER` sitting in `OPEN`, `TRIAGED`, `IN_PROGRESS`,
        or `REOPENED` — to be zero; otherwise `ERR_OPEN_BLOCKERS_EXIST`."
        PRD §3.4: "Two terminal dispositions exist short of a fix: `TRIAGED`
        or `IN_PROGRESS` may move to `WONT_FIX`, and `TRIAGED` may move to
        `DUPLICATE`; both require a `resolution` note (`ERR_INVALID_REQUEST`
        when absent), and both recompute the blocker count."

        Design: Corner/entities/open_blocker_counter_reconciles_with_bug_lifecycle
        """
        title = create_title(title_code="ENT-T8", cert_budget_total_cents=1000)
        build = create_build(title["id"], "PS5", "1.0.0")
        transition_build(build["id"], "IN_TEST")
        bug = create_bug(title["id"], build["id"], severity="BLOCKER",
                         category="AUDIO")
        assert get_title(title["id"])["open_blocker_count"] == 1
        triage_bug(bug["id"], "BLOCKER")
        transition_bug(bug["id"], "WONT_FIX",
                       resolution="platform limitation accepted")
        assert get_title(title["id"])["open_blocker_count"] == 0


class TestBuildLifecycle:
    def test_retest_loop_and_candidate_promote_gate(self, api):
        """PRD §3.4: "A `QALead` moves `RECEIVED` → `IN_TEST`, and a failed
        build can re-enter testing — `TEST_FAILED` → `IN_TEST` is the retest
        loop."
        PRD §3.4: "Promotion `TEST_PASSED` → `CANDIDATE` is allowed only when
        no bug report on this build carries severity `BLOCKER` in `OPEN`,
        `TRIAGED`, `IN_PROGRESS`, or `REOPENED` — otherwise
        `ERR_OPEN_BLOCKERS_EXIST`."

        Design: Corner/state_machines/build_retest_loop_and_promote_gate
        """
        title = create_title(title_code="SM-BLD", cert_budget_total_cents=1000)
        build = create_build(title["id"], "PS5", "1.0.0")
        transition_build(build["id"], "IN_TEST")
        transition_build(build["id"], "TEST_FAILED")
        build = transition_build(build["id"], "IN_TEST")
        assert build["status"] == "IN_TEST"
        bug = create_bug(title["id"], build["id"], severity="BLOCKER",
                         category="GAMEPLAY")
        transition_build(build["id"], "TEST_PASSED")
        resp = api.transition_build(
            build["id"], {"to_status": "CANDIDATE"},
            QA_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_BLOCKERS_EXIST)
        close_bug_fully(bug["id"], severity="BLOCKER")
        build = transition_build(build["id"], "CANDIDATE")
        assert build["status"] == "CANDIDATE"


class TestBugLifecycle:
    def test_closed_bug_rejects_reopen(self, api):
        """PRD §3.4: "From `TRIAGED` — and from `REOPENED`, since a reopened
        bug re-enters the work stream — work advances to `IN_PROGRESS`, then
        `RESOLVED`, then `VERIFIED`, and finally the terminal `CLOSED`."
        PRD §2.8: "**State legality.** The target entity is in a legal
        from-state for the requested transition — otherwise
        `ERR_INVALID_STATE` (or `ERR_PACKAGE_NOT_ASSEMBLING` for package
        submission)."

        Design: Corner/state_machines/bug_terminal_closed_rejects_reopen
        """
        title = create_title(title_code="SM-TRM", cert_budget_total_cents=1000)
        build = create_build(title["id"], "PS5", "1.0.0")
        bug = create_bug(title["id"], build["id"], severity="MINOR",
                         category="AUDIO")
        close_bug_fully(bug["id"], severity="MINOR")
        resp = api.transition_bug(
            bug["id"], {"to_status": "REOPENED"},
            QA_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_bug(bug["id"])
        assert after["status"] == "CLOSED"
        assert after["reopened_count"] == 0

    def test_reopen_cycle_twice_increments_reopened_count(self, api):
        """PRD §3.4: "A bug in `RESOLVED` or `VERIFIED` can be reopened: the
        transition increments `reopened_count`, applies an optional severity
        re-triage first — the effective severity is the payload's `severity`
        when present, otherwise the current one — and recomputes the title's
        blocker count."

        Design: Difficulty/non_linear_state_machine/bug_report_reopen_cycle
        """
        title = create_title(title_code="CYC-BUG", cert_budget_total_cents=500000)
        build = create_build(title["id"], "PS5", "1.0.0")
        transition_build(build["id"], "IN_TEST")
        bug = create_bug(title["id"], build["id"], severity="MAJOR",
                         category="GAMEPLAY")
        triage_bug(bug["id"], "MAJOR")
        # First full loop: ... -> VERIFIED -> REOPENED.
        transition_bug(bug["id"], "IN_PROGRESS")
        transition_bug(bug["id"], "RESOLVED")
        transition_bug(bug["id"], "VERIFIED")
        bug = transition_bug(bug["id"], "REOPENED")
        assert bug["reopened_count"] == 1
        # Second loop re-enters the work stream from REOPENED.
        transition_bug(bug["id"], "IN_PROGRESS")
        transition_bug(bug["id"], "RESOLVED")
        bug = transition_bug(bug["id"], "REOPENED")
        assert bug["reopened_count"] == 2
        assert bug["status"] == "REOPENED"

    def test_reopen_cycle_keeps_blocker_count_zero_for_major(self, api):
        """PRD §3.1: "Promotion from `CERT_APPROVED` to `LAUNCHED` requires
        the title's `open_blocker_count` — the number of its own bug reports
        with severity `BLOCKER` sitting in `OPEN`, `TRIAGED`, `IN_PROGRESS`,
        or `REOPENED` — to be zero; otherwise `ERR_OPEN_BLOCKERS_EXIST`."

        Design: Difficulty/non_linear_state_machine/bug_report_reopen_cycle
        """
        title = create_title(title_code="CYC-BUG", cert_budget_total_cents=500000)
        build = create_build(title["id"], "PS5", "1.0.0")
        transition_build(build["id"], "IN_TEST")
        bug = create_bug(title["id"], build["id"], severity="MAJOR",
                         category="GAMEPLAY")
        assert get_title(title["id"])["open_blocker_count"] == 0
        triage_bug(bug["id"], "MAJOR")
        transition_bug(bug["id"], "IN_PROGRESS")
        transition_bug(bug["id"], "RESOLVED")
        transition_bug(bug["id"], "VERIFIED")
        transition_bug(bug["id"], "REOPENED")
        transition_bug(bug["id"], "IN_PROGRESS")
        transition_bug(bug["id"], "RESOLVED")
        transition_bug(bug["id"], "REOPENED")
        assert get_title(title["id"])["open_blocker_count"] == 0


class TestBugListing:
    def test_bug_list_filters_compose(self, api, reader_headers):
        """PRD §3.4: "The bug list filters by `title_id`, `build_id`,
        `severity`, `status`, `found_by_vendor_id`, and `regression_of_id`."

        Design: Corner/endpoints/bugs_list_filter_combination
        """
        title = create_title(title_code="EP-FLT", cert_budget_total_cents=1000)
        build = create_build(title["id"], "PS5", "1.0.0")
        transition_build(build["id"], "IN_TEST")
        g1 = create_bug(title["id"], build["id"], severity="MAJOR",
                        category="AUDIO")
        triage_bug(g1["id"], "MAJOR")
        create_bug(title["id"], build["id"], severity="MAJOR",
                   category="GAMEPLAY")
        create_bug(title["id"], build["id"], severity="BLOCKER",
                   category="NETWORK")
        _rows, meta = validate_paginated(
            api.list_bugs(reader_headers,
                          params={"title_id": title["id"], "severity": "MAJOR"})
        )
        assert meta["total_count"] == 2
        _rows, meta = validate_paginated(
            api.list_bugs(reader_headers,
                          params={"title_id": title["id"], "severity": "MAJOR",
                                  "status": "OPEN"})
        )
        assert meta["total_count"] == 1


class TestTriageSlaBreach:
    def test_sla_breach_boundary_is_strictly_greater(self, api):
        """PRD §3.4: "A bug breaches when the logical clock reads strictly
        later than its `created_at` plus the allowance; a bug sitting exactly
        at that boundary instant has not breached."
        PRD §3.4: "each severity carries a triage allowance — 24 hours for
        `BLOCKER`, 72 for `CRITICAL`, 168 for `MAJOR`, and 720 for `MINOR`,
        while `TRIVIAL` carries no SLA and never breaches."

        Design: Corner/calculations/sla_breach_strictly_greater_boundary
        """
        set_clock("2026-08-03T00:00:00Z")
        title = create_title(title_code="CL-SLA", cert_budget_total_cents=1000)
        build = create_build(title["id"], "PS5", "1.0.0")
        transition_build(build["id"], "IN_TEST")
        bug = create_bug(title["id"], build["id"], severity="BLOCKER",
                         category="PERFORMANCE")
        # Exactly created_at + 24h: not yet breached.
        set_clock("2026-08-04T00:00:00Z")
        ops_run()
        assert get_bug(bug["id"])["sla_breached"] is False
        # One second past the boundary: breached.
        set_clock("2026-08-04T00:00:01Z")
        ops_run()
        assert get_bug(bug["id"])["sla_breached"] is True


class TestBlockerReopenCascade:
    def _setup_submitted_package_window_and_verified_bug(self):
        """Submitted package (fee 120000 in escrow, Monday submit), a RESERVED
        LAUNCH window, and a VERIFIED MAJOR bug on the CANDIDATE build."""
        set_clock("2026-08-03T09:00:00Z")
        ctx = setup_submittable_package(title_code="CASC-BLK",
                                        cert_budget_total_cents=1_000_000)
        set_clock("2026-08-03T10:00:00Z")  # a Monday
        ctx["package"] = submit_package(ctx["package"]["id"])
        window = create_release_window(
            ctx["title"]["id"], "PS5", "LAUNCH",
            start_utc="2026-08-10T09:00:00Z", end_utc="2026-08-10T17:00:00Z",
        )
        bug = create_bug(ctx["title"]["id"], ctx["build"]["id"],
                         severity="MAJOR", category="GRAPHICS")
        triage_bug(bug["id"], "MAJOR")
        transition_bug(bug["id"], "IN_PROGRESS")
        transition_bug(bug["id"], "RESOLVED")
        transition_bug(bug["id"], "VERIFIED")
        return ctx, window, bug

    def test_reopen_with_blocker_demotes_build_withdraws_package_releases_window(
            self, api):
        """PRD §3.4: "Whenever a blocker enters the open set against a
        `CANDIDATE` build — created with severity `BLOCKER`, triaged up to
        `BLOCKER`, or reopened with an effective severity of `BLOCKER` — hop
        one demotes the build `CANDIDATE` → `IN_TEST`. Hop two then withdraws
        every submission package referencing that build that sits in
        `ASSEMBLING`, `SUBMITTED`, or `IN_REVIEW`: each moves to `WITHDRAWN`
        with `withdrawn_cause` recorded as `SYSTEM_BUILD_INVALIDATED`"
        PRD §3.4: "Hop three, which fires only for these system-caused
        withdrawals, releases the title's launch windows: every `LAUNCH`-kind
        release window of the same title and platform in `RESERVED` or
        `CONFIRMED` moves to `RELEASED`, and a confirmed window's fee is not
        refunded."

        Design: Difficulty/transitive_cascade/blocker_reopen_cascade_build_package_window
        """
        ctx, window, bug = (
            self._setup_submitted_package_window_and_verified_bug()
        )
        transition_bug(bug["id"], "REOPENED", severity="BLOCKER")
        assert get_build(ctx["build"]["id"])["status"] == "IN_TEST"
        package = get_package(ctx["package"]["id"])
        assert package["status"] == "WITHDRAWN"
        assert package["withdrawn_cause"] == "SYSTEM_BUILD_INVALIDATED"
        assert get_release_window(window["id"])["status"] == "RELEASED"

    def test_reopen_cascade_refunds_escrow_and_recomputes_counters(self, api):
        """PRD §3.4: "each withdrawn package that had a fee in escrow moves
        that fee from the title's escrow back to available."
        PRD §3.4: "the transition increments `reopened_count`, applies an
        optional severity re-triage first — the effective severity is the
        payload's `severity` when present, otherwise the current one — and
        recomputes the title's blocker count."

        Design: Difficulty/transitive_cascade/blocker_reopen_cascade_build_package_window
        """
        ctx, _window, bug = (
            self._setup_submitted_package_window_and_verified_bug()
        )
        bug = transition_bug(bug["id"], "REOPENED", severity="BLOCKER")
        assert bug["reopened_count"] == 1
        title = get_title(ctx["title"]["id"])
        assert title["open_blocker_count"] == 1
        assert title["cert_budget_escrow_cents"] == 0
        # 1000000 total minus the 40000 ESRB filing fee already spent.
        assert title["cert_budget_available_cents"] == 960000
        assert_budget_invariant(title)
