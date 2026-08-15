"""Program change notices (PRD §3.7): disclosure windows (half-open),
activation gating, withdrawal, supersession, and program-scoped optimistic
concurrency (§2.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_same_instant,
    create_notice,
    get_notice,
    get_program,
    make_issued_notice,
    make_program,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COMPLIANCE


class TestNoticeWindowsHalfOpenAdjacency:
    def _setup(self):
        """Notice N1 (FEE_AMOUNT -> '3600') issued at 2026-08-03T09:00:00Z:
        window [2026-08-03T09:00:00Z, 2026-09-02T09:00:00Z). Notice N2
        (FEE_AMOUNT -> '3700') left DRAFT."""
        program = make_program(name="OD-N", posting_order_policy="HIGH_TO_LOW")
        n1 = make_issued_notice(program["id"], "2026-08-03T09:00:00Z",
                                new_value="3600")
        assert_same_instant(n1["effective_at"], "2026-09-02T09:00:00Z",
                            "notice.effective_at")
        n2 = create_notice(program["id"], new_value="3700")
        return program, n1, n2

    def test_issue_one_second_before_window_end_overlaps(self, api):
        """PRD §3.7: "Issuance is refused — with `ERR_NOTICE_WINDOW_OVERLAP` —
        if any other notice for the same program and parameter is already
        `ISSUED` with a window that would overlap the new one."

        Design: Difficulty/resource_temporal_overlap/notice_windows_half_open_adjacency
        """
        _, n1, n2 = self._setup()
        # One second inside N1's half-open window.
        set_clock("2026-09-02T08:59:59Z")
        resp = api.issue_notice(n2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_OVERLAP)
        assert get_notice(n2["id"])["status"] == "DRAFT"
        assert_same_instant(n1["effective_at"], "2026-09-02T09:00:00Z",
                            "notice.effective_at")

    def test_issue_exactly_at_prior_effective_at_is_permitted(self, api):
        """PRD §3.7: "Each window is the half-open interval that includes its
        `sent_at` instant and runs up to but does not include its
        `effective_at` instant, so a new issue whose `sent_at` coincides
        exactly with the prior notice's `effective_at` does not overlap and is
        permitted."
        PRD §3.7: "`sent_at` is stamped from the logical clock and
        `effective_at` is computed as `sent_at` plus the program's
        `notice_window_days` calendar days."

        Design: Difficulty/resource_temporal_overlap/notice_windows_half_open_adjacency
        """
        _, _, n2 = self._setup()
        set_clock("2026-09-02T09:00:00Z")
        issued = validate_success(api.issue_notice(n2["id"], ADMIN))
        assert issued["status"] == "ISSUED"
        assert_same_instant(issued["sent_at"], "2026-09-02T09:00:00Z",
                            "notice.sent_at")
        assert_same_instant(issued["effective_at"], "2026-10-02T09:00:00Z",
                            "notice.effective_at")


class TestNoticeActivateSuspendedBeatsWindowError:
    def _setup(self):
        """Notice issued at 2026-08-03T09:00:00Z (effective_at
        2026-09-02T09:00:00Z); program then suspended with the clock still
        inside the window."""
        program = make_program(name="OD-P2",
                               posting_order_policy="HIGH_TO_LOW")
        notice = make_issued_notice(program["id"], "2026-08-03T09:00:00Z",
                                    new_value="3600")
        suspended = validate_success(
            api_client.suspend_program(program["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        return program, notice

    def test_suspended_program_error_wins_over_window_error(self, api):
        """PRD §2.10: "eighth, program posture and disclosure compliance
        (`ERR_PROGRAM_SUSPENDED`, `ERR_STALE_DISCLOSURE_VERSION`); ninth, the
        time-window rules covering notice windows, report periods, business
        days, settle ordering, reversal windows, and offer expiry".
        PRD §2.10: "Validation on any request executes in a fixed precedence
        order, and a failure at an earlier tier masks every later check."

        Design: Difficulty/priority_pair_validation_conflict/notice_activate_suspended_program_beats_window_error
        """
        _, notice = self._setup()
        resp = api.activate_notice(notice["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_SUSPENDED)

    def test_failed_activation_applies_nothing(self, api):
        """PRD §3.7: "Activation requires the program to be `ACTIVE` — a
        suspended program refuses activation with `ERR_PROGRAM_SUSPENDED` — and
        requires the logical clock to have reached `effective_at`; an early
        attempt is rejected with `ERR_NOTICE_WINDOW_NOT_ELAPSED`."
        PRD §3.7: "A successful activation moves the notice from `ISSUED` to
        `EFFECTIVE`, writes the `new_value` into the mapped program field, and
        increments the program's `version`."

        Design: Difficulty/priority_pair_validation_conflict/notice_activate_suspended_program_beats_window_error
        """
        program, notice = self._setup()
        assert_same_instant(notice["effective_at"], "2026-09-02T09:00:00Z",
                            "notice.effective_at")
        validate_error(api.activate_notice(notice["id"], COMPLIANCE),
                       ApiErrorId.ERR_PROGRAM_SUSPENDED)
        # The activation did not apply: notice stays ISSUED, program unchanged.
        assert get_notice(notice["id"])["status"] == "ISSUED"
        assert get_program(program["id"])["fee_amount_cents"] == 3500


class TestWithdrawEffectiveNoticeRejected:
    def test_activation_applies_value_and_effective_cannot_withdraw(self, api):
        """PRD §3.7: "A successful activation moves the notice from `ISSUED` to
        `EFFECTIVE`, writes the `new_value` into the mapped program field, and
        increments the program's `version`."
        PRD §3.7: "Withdrawal, a `ProgramAdmin` action, abandons a notice
        before it bites: a `DRAFT` notice may be withdrawn at any time, and an
        `ISSUED` notice may be withdrawn only while the clock has not yet
        reached its `effective_at` — an already-effective notice cannot be
        withdrawn."

        Design: Corner/state_machines/withdraw_effective_notice_returns_invalid_state
        """
        program = make_program(name="OD-SM6")
        notice = make_issued_notice(program["id"], "2026-08-03T09:00:00Z",
                                    new_value="3600")
        set_clock("2026-09-02T09:00:00Z")
        activated = validate_success(
            api.activate_notice(notice["id"], COMPLIANCE))
        assert activated["status"] == "EFFECTIVE"

        program_after = get_program(program["id"])
        assert program_after["fee_amount_cents"] == 3600
        assert program_after["version"] == 3  # create bumped to 2, activate to 3

        resp = api.withdraw_notice(notice["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestNoticeActivateBeforeWindowRejected:
    def test_early_activation_fails_and_notice_stays_issued(self, api):
        """PRD §3.7: "Activation requires the program to be `ACTIVE` — a
        suspended program refuses activation with `ERR_PROGRAM_SUSPENDED` — and
        requires the logical clock to have reached `effective_at`; an early
        attempt is rejected with `ERR_NOTICE_WINDOW_NOT_ELAPSED`."

        Design: Corner/validations/notice_activate_before_window_rejected
        """
        program = make_program(name="OD-V18")
        notice = make_issued_notice(program["id"], "2026-08-03T09:00:00Z",
                                    new_value="3600")
        set_clock("2026-08-20T00:00:00Z")
        resp = api.activate_notice(notice["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_NOT_ELAPSED)
        assert get_notice(notice["id"])["status"] == "ISSUED"


class TestOccNoticeCreateStaleProgramVersion:
    def test_stale_version_rejected_fresh_create_supersedes_draft(self, api):
        """PRD §2.8: "Creating a program-change notice requires the request to
        carry `expected_program_version`, holding the `version` of the target
        program as the client last observed it; if the program's current
        `version` no longer matches — because another writer has since created
        a notice (legitimately superseding a draft on the same parameter) or a
        notice activation has repriced the program — the creation is rejected
        with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)".
        PRD §3.7: "Creation snapshots the current value of the mapped field
        into `old_value`, births the notice in `DRAFT` status, supersedes any
        existing `DRAFT` notice for the same program and parameter — the older
        draft moves to `SUPERSEDED` — and increments the program's `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_notice_create_stale_program_version
        """
        program = make_program(name="OD-OCC1")
        observed_version = program["version"]
        n1 = create_notice(program["id"], new_value="3600")
        assert n1["status"] == "DRAFT"

        stale = api.create_notice(
            {"program_id": program["id"], "parameter": "FEE_AMOUNT",
             "new_value": "3700", "expected_program_version": observed_version},
            ADMIN)
        validate_error(stale, ApiErrorId.ERR_STALE_PROGRAM_VERSION)

        fresh_version = get_program(program["id"])["version"]
        assert fresh_version == 2
        n2 = validate_success(api.create_notice(
            {"program_id": program["id"], "parameter": "FEE_AMOUNT",
             "new_value": "3700", "expected_program_version": fresh_version},
            ADMIN), 201)
        assert n2["status"] == "DRAFT"
        # The fresh create supersedes the older DRAFT on the same parameter.
        assert get_notice(n1["id"])["status"] == "SUPERSEDED"
