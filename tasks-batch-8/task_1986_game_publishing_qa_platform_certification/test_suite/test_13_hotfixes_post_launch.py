"""Post-launch hotfix process: declaration gates, embargo priority, the
expedited-cert happy path, the rolling S1 quota, and the double-rollback
auto-embargo (PRD §3.9, §3.1)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_title,
    assert_clock_instant,
    confirm_release_window,
    create_build,
    create_candidate_build,
    create_hotfix,
    create_hotfix_payload,
    create_ready_hotfix,
    create_title,
    expedite_hotfix,
    get_hotfix,
    get_release_window,
    get_title,
    set_clock,
    set_embargo,
    setup_launched_title,
    transition_hotfix,
    validate_error,
    validate_paginated,
    validate_success,
)

RM_HEADERS = TEST_USERS["release_manager_headers"]
PR_HEADERS = TEST_USERS["platform_reviewer_headers"]
READER_HEADERS = TEST_USERS["reader_headers"]


def _launched_title_with_fix_build(title_code, budget=1_000_000):
    """A LAUNCHED title plus a second CANDIDATE build (the fixing build)."""
    set_clock("2026-08-03T09:00:00Z")  # a Monday
    ctx = setup_launched_title(title_code=title_code,
                               cert_budget_total_cents=budget)
    fix_build = create_candidate_build(
        ctx["title"]["id"], "PS5", "1.0.1", patch_class="HOTFIX"
    )
    return ctx, fix_build


class TestHotfixDeclarationGates:
    def test_hotfix_requires_launched_title(self, api):
        """PRD §3.9: "A `ReleaseManager` declares one for a launched,
        non-embargoed title — `ERR_TITLE_NOT_LAUNCHED` when the title has not
        launched, `ERR_TITLE_UNDER_EMBARGO` while an embargo is active"

        Design: Corner/validations/hotfix_create_requires_launched_title
        """
        title = create_title(title_code="VAL-HNL", cert_budget_total_cents=500000)
        advance_title(title["id"], "IN_DEVELOPMENT")
        build = create_build(title["id"], "PS5", "1.0.1", patch_class="HOTFIX")
        resp = api.create_hotfix(
            create_hotfix_payload(title["id"], "PS5", build["id"], "S1",
                                  "premature hotfix"),
            RM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_TITLE_NOT_LAUNCHED)
        _rows, meta = validate_paginated(
            api.list_hotfixes(READER_HEADERS, params={"title_id": title["id"]})
        )
        assert meta["total_count"] == 0


class TestEmbargoPriority:
    def _setup_embargoed_title_and_foreign_build(self):
        """Title A LAUNCHED then embargoed; title B with its own build —
        so a hotfix on A referencing B's build arms both the embargo gate
        and the build-title mismatch gate."""
        ctx_a, _fix = _launched_title_with_fix_build("PRIO-SA")
        set_embargo(ctx_a["title"]["id"], True, "compliance audit hold")
        title_b = create_title(title_code="PRIO-SB",
                               cert_budget_total_cents=100000)
        build_b = create_build(title_b["id"], "PS5", "9.9.9")
        return ctx_a, build_b

    def test_embargo_error_beats_build_mismatch(self, api):
        """PRD §2.8: "6. **Embargo safety.** The title is not under a
        compliance embargo for the two operations the embargo gates —
        otherwise `ERR_TITLE_UNDER_EMBARGO` (HTTP 403)."
        PRD §2.8: "8. **Cross-entity referential consistency.** The
        referenced build belongs to the title and targets the right platform,
        a regression target is closed, and a consumed week starts on a Monday
        — otherwise `ERR_BUILD_TITLE_MISMATCH`, `ERR_BUILD_PLATFORM_MISMATCH`,
        `ERR_REGRESSION_TARGET_NOT_CLOSED`, or `ERR_WEEK_START_NOT_MONDAY`
        (all HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/hotfix_embargo_beats_build_mismatch
        """
        ctx_a, build_b = self._setup_embargoed_title_and_foreign_build()
        resp = api.create_hotfix(
            create_hotfix_payload(ctx_a["title"]["id"], "PS5", build_b["id"],
                                  "S1", "server outage on auth"),
            RM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_TITLE_UNDER_EMBARGO)

    def test_embargoed_create_creates_no_hotfix_row(self, api):
        """PRD §3.1: "While a title is embargoed, two operations are
        forbidden: submitting a submission package and declaring a hotfix —
        both are rejected with `ERR_TITLE_UNDER_EMBARGO` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/hotfix_embargo_beats_build_mismatch
        """
        ctx_a, build_b = self._setup_embargoed_title_and_foreign_build()
        resp = api.create_hotfix(
            create_hotfix_payload(ctx_a["title"]["id"], "PS5", build_b["id"],
                                  "S1", "server outage on auth"),
            RM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_TITLE_UNDER_EMBARGO)
        _rows, meta = validate_paginated(
            api.list_hotfixes(READER_HEADERS,
                              params={"title_id": ctx_a["title"]["id"]})
        )
        assert meta["total_count"] == 0


class TestExpeditedCert:
    def test_happy_path_charges_fee_and_consumes_window(self, api):
        """PRD §3.9: "And the budget must cover the flat expedited fee of
        50000 cents (`ERR_CERT_BUDGET_EXCEEDED`). Success charges that fee
        directly to the title's spent partition and stamps
        `expedited_cert_entered_at` from the logical clock — the quota's
        anchor. Deployment — `EXPEDITED_CERT` → `DEPLOYED` by the
        `ReleaseManager` — consumes the covering window."

        Design: Corner/state_machines/hotfix_happy_path_charges_fee_and_consumes_window
        """
        ctx, fix_build = _launched_title_with_fix_build("SM-HTX")
        window = confirm_release_window(
            ctx["title"]["id"], "PS5", "HOTFIX_DEPLOY",
            start_utc="2026-08-20T09:00:00Z", end_utc="2026-08-20T11:00:00Z",
        )
        # The only PS5 window in its ISO week: 2h x 5000 x 1.00 (LOW).
        assert window["fee_cents"] == 10000
        set_clock("2026-08-20T10:00:00Z")  # inside the window
        hotfix = create_ready_hotfix(ctx["title"]["id"], "PS5",
                                     fix_build["id"], "S1",
                                     "login servers down")
        hotfix = expedite_hotfix(hotfix["id"])
        assert hotfix["fee_cents"] == 50000
        # Stamped from the logical clock: the instant is pinned (§3.9); the
        # string representation is not (§2.5's millisecond format is scoped
        # to id/created_at/updated_at/version).
        assert_clock_instant(
            hotfix["expedited_cert_entered_at"], "2026-08-20T10:00:00Z"
        )
        hotfix = transition_hotfix(hotfix["id"], "DEPLOYED")
        assert hotfix["status"] == "DEPLOYED"
        assert get_release_window(window["id"])["status"] == "CONSUMED"
        # 40000 ESRB + 120000 package + 10000 window + 50000 hotfix.
        assert get_title(ctx["title"]["id"])["cert_budget_spent_cents"] == 220000

    def test_expedite_without_covering_window_rejected(self, api):
        """PRD §3.9: "A `CONFIRMED` `HOTFIX_DEPLOY` window for the title and
        platform must cover the current logical time — its start at or before
        now and its end strictly after now — otherwise
        `ERR_NO_HOTFIX_WINDOW`."

        Design: Corner/state_machines/hotfix_expedite_without_window_rejected
        """
        ctx, fix_build = _launched_title_with_fix_build("SM2-HNW")
        # S2 carries no quota pressure, so the window gate is what fires.
        hotfix = create_ready_hotfix(ctx["title"]["id"], "PS5",
                                     fix_build["id"], "S2",
                                     "friends-list desync")
        set_clock("2026-08-20T10:00:00Z")
        resp = api.transition_hotfix(
            hotfix["id"], {"to_status": "EXPEDITED_CERT"}, PR_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_NO_HOTFIX_WINDOW)
        after = get_hotfix(hotfix["id"])
        assert after["status"] == "READY_FOR_CERT"
        assert after["fee_cents"] is None


class TestRollingQuota:
    def test_third_s1_within_30_days_blocked_then_oldest_ages_out(self, api):
        """PRD §3.9: "For `S1` hotfixes, the rolling quota counts the title's
        `S1` hotfixes whose `expedited_cert_entered_at` falls within the
        rolling thirty-day window — half-open, so an entry exactly thirty
        days old is excluded while the most recent instant is included — and
        when that count is already two the transition is rejected with
        `ERR_HOTFIX_QUOTA_EXCEEDED`; `S2` hotfixes never count and are never
        blocked."

        Design: Corner/calculations/hotfix_quota_rolling_window_boundary
        """
        ctx, fix_build = _launched_title_with_fix_build("CL-QTA")
        for start, end in (
            ("2026-08-21T08:00:00Z", "2026-08-21T12:00:00Z"),
            ("2026-08-22T08:00:00Z", "2026-08-22T12:00:00Z"),
            ("2026-08-23T08:00:00Z", "2026-08-23T12:00:00Z"),
            ("2026-09-20T08:00:00Z", "2026-09-20T12:00:00Z"),
        ):
            confirm_release_window(ctx["title"]["id"], "PS5", "HOTFIX_DEPLOY",
                                   start_utc=start, end_utc=end)

        def _ready_and_expedite(summary, clock):
            hotfix = create_ready_hotfix(ctx["title"]["id"], "PS5",
                                         fix_build["id"], "S1", summary)
            set_clock(clock)
            return api.transition_hotfix(
                hotfix["id"], {"to_status": "EXPEDITED_CERT"}, PR_HEADERS
            )

        validate_success(_ready_and_expedite("incident one", "2026-08-21T09:30:00Z"))
        validate_success(_ready_and_expedite("incident two", "2026-08-22T09:30:00Z"))
        # Third expedite inside the same rolling window: count already 2.
        resp = _ready_and_expedite("incident three", "2026-08-23T09:30:00Z")
        validate_error(resp, ApiErrorId.ERR_HOTFIX_QUOTA_EXCEEDED)
        # At 2026-09-20T09:30 the first entry (2026-08-21T09:30) is exactly
        # thirty days old and falls out of the half-open window.
        ok = _ready_and_expedite("incident four", "2026-09-20T09:30:00Z")
        hotfix4 = validate_success(ok)
        assert hotfix4["status"] == "EXPEDITED_CERT"
        assert hotfix4["fee_cents"] == 50000
        # 40000 ESRB + 120000 package + 4 x 20000 windows + 3 x 50000 fees.
        assert get_title(ctx["title"]["id"])["cert_budget_spent_cents"] == 390000


class TestRollbackEmbargo:
    def test_second_rollback_auto_embargoes_title(self, api):
        """PRD §3.9: "Rolling back — `DEPLOYED` → `ROLLED_BACK` — increments
        the title's `hotfix_rollback_count`, and when that count reaches two
        the system sets `embargoed` true with `embargo_reason`
        `AUTO_ROLLBACK_THRESHOLD`, the contagion gate on future submissions
        and hotfixes described in §3.1."
        PRD §3.1: "While a title is embargoed, two operations are forbidden:
        submitting a submission package and declaring a hotfix — both are
        rejected with `ERR_TITLE_UNDER_EMBARGO` (HTTP 403)."

        Design: Corner/state_machines/double_rollback_auto_embargoes_title
        """
        ctx, fix_build = _launched_title_with_fix_build("SM2-RBK")
        confirm_release_window(
            ctx["title"]["id"], "PS5", "HOTFIX_DEPLOY",
            start_utc="2026-08-21T08:00:00Z", end_utc="2026-08-21T12:00:00Z",
        )
        confirm_release_window(
            ctx["title"]["id"], "PS5", "HOTFIX_DEPLOY",
            start_utc="2026-08-22T08:00:00Z", end_utc="2026-08-22T12:00:00Z",
        )

        def _deployed_s2_hotfix(summary, clock):
            hotfix = create_ready_hotfix(ctx["title"]["id"], "PS5",
                                         fix_build["id"], "S2", summary)
            set_clock(clock)
            expedite_hotfix(hotfix["id"])
            return transition_hotfix(hotfix["id"], "DEPLOYED")

        h1 = _deployed_s2_hotfix("crash on alt-tab", "2026-08-21T09:30:00Z")
        h2 = _deployed_s2_hotfix("avatar t-pose", "2026-08-22T09:30:00Z")
        transition_hotfix(h1["id"], "ROLLED_BACK")
        title = get_title(ctx["title"]["id"])
        assert title["hotfix_rollback_count"] == 1
        assert title["embargoed"] is False
        transition_hotfix(h2["id"], "ROLLED_BACK")
        title = get_title(ctx["title"]["id"])
        assert title["hotfix_rollback_count"] == 2
        assert title["embargoed"] is True
        assert title["embargo_reason"] == "AUTO_ROLLBACK_THRESHOLD"
        # The contagion gate bites immediately.
        resp = api.create_hotfix(
            create_hotfix_payload(ctx["title"]["id"], "PS5", fix_build["id"],
                                  "S2", "third incident blocked"),
            RM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_TITLE_UNDER_EMBARGO)
