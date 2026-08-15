"""Termination claims: window projection, lazy clock-derived statuses, notice
deadlines, the terminated-work safety gate, and the rights-reversion cascade."""
from test_helpers import (
    ApiErrorId,
    create_split_set,
    create_split_set_payload,
    create_termination_claim,
    create_work,
    create_writer,
    effectuate_termination,
    get_work,
    list_split_lines,
    make_writer_headers,
    publisher_split_line,
    set_clock,
    submit_split_set,
    validate_error,
    validate_success,
    writer_split_line,
)
from test_helpers.fixtures import ADMIN, COPYRIGHT

GRANT_1990 = "1990-06-15T00:00:00Z"


class TestWindowProjection:
    def test_termination_window_dates_projected(self, api):
        """PRD §3.10: "At creation the server projects the statutory calendar from the work's `grant_date` using whole-calendar-year arithmetic that preserves month and day (a February 29 date clamps to February 28 when the target year is not a leap year): `window_open_date` is the grant date plus 35 calendar years, `window_close_date` is the grant date plus 40 calendar years, `notice_earliest_date` is the intended effective date minus 10 calendar years, and `notice_latest_date` is the intended effective date minus 2 calendar years."
        PRD §2.5: "A TerminationClaim in `TRACKING` behaves as `NOTICE_WINDOW_OPEN` once the logical clock reaches or passes its `window_open_date`"

        Design: Corner/calculations/termination_window_dates_projected
        """
        work = create_work(title="Window Song", grant_date=GRANT_1990)
        claim = create_termination_claim(work["id"], "2028-06-15T00:00:00Z")

        assert claim["window_open_date"].startswith("2025-06-15"), (
            f"grant + 35y, got {claim['window_open_date']}")
        assert claim["window_close_date"].startswith("2030-06-15"), (
            f"grant + 40y, got {claim['window_close_date']}")
        assert claim["notice_earliest_date"].startswith("2018-06-15"), (
            f"effective - 10y, got {claim['notice_earliest_date']}")
        assert claim["notice_latest_date"].startswith("2026-06-15"), (
            f"effective - 2y, got {claim['notice_latest_date']}")
        # The default logical clock (2026-08-01) is past the window open.
        assert claim["status"] == "NOTICE_WINDOW_OPEN"


class TestLazyStatuses:
    def test_termination_claim_lapsed_via_clock(self, api):
        """PRD §2.5: "a claim that has never reached `NOTICE_FILED` behaves as `LAPSED` once the logical clock passes its `window_close_date`."

        Design: Corner/state_machines/termination_claim_lapsed_via_clock
        """
        work = create_work(title="Lapsed Song", grant_date=GRANT_1990)
        claim = create_termination_claim(work["id"], "2028-06-15T00:00:00Z")

        set_clock("2030-06-16T00:00:00Z")
        after = validate_success(api.get_termination_claim(claim["id"], ADMIN))
        assert after["status"] == "LAPSED", (
            "never filed and now (2030-06-16) past window_close (2030-06-15)")

    def test_file_notice_before_window_rejected(self, api):
        """PRD §3.10: "Filing the notice — a `CopyrightSpecialist` action carrying the `notice_ref` — is permitted only in that derived window: attempting it while the derived status is still `TRACKING` because the window has not opened is rejected with `ERR_TERMINATION_WINDOW_NOT_OPEN`, while attempting it after the logical clock has passed `notice_latest_date` is rejected with `ERR_NOTICE_DEADLINE_PASSED`; the filing moment must lie within the inclusive notice window from `notice_earliest_date` through `notice_latest_date`."

        Design: Corner/state_machines/termination_claim_file_notice_before_window_rejected
        """
        work = create_work(title="Future Song",
                           grant_date="2000-01-01T00:00:00Z")
        claim = create_termination_claim(work["id"], "2036-01-01T00:00:00Z")
        # Default clock 2026-08-01 < window_open 2035-01-01.
        assert claim["status"] == "TRACKING"

        resp = api.file_notice(claim["id"], "N-EARLY", COPYRIGHT)
        validate_error(resp, ApiErrorId.ERR_TERMINATION_WINDOW_NOT_OPEN)

    def test_notice_deadline_passed_with_default_clock(self, api):
        """PRD §2.5: "Before any operator sets it, the logical clock reads exactly 2026-08-01T00:00:00Z."
        PRD §3.10: "attempting it after the logical clock has passed `notice_latest_date` is rejected with `ERR_NOTICE_DEADLINE_PASSED`; the filing moment must lie within the inclusive notice window from `notice_earliest_date` through `notice_latest_date`."

        Design: Corner/validations/notice_deadline_passed_with_default_clock
        """
        work = create_work(title="Late Notice Song", grant_date=GRANT_1990)
        # notice_latest_date = 2028-06-15 - 2y = 2026-06-15, already passed at
        # the default clock 2026-08-01 (window is open, so the state gate
        # passes and the deadline gate fires).
        claim = create_termination_claim(work["id"], "2028-06-15T00:00:00Z")
        assert claim["status"] == "NOTICE_WINDOW_OPEN"

        resp = api.file_notice(claim["id"], "N-LATE", COPYRIGHT)
        validate_error(resp, ApiErrorId.ERR_NOTICE_DEADLINE_PASSED)

    def test_effective_date_outside_window_rejected(self, api):
        """PRD §3.10: "The intended effective date must fall strictly after `window_open_date` and on or before `window_close_date`; otherwise creation is rejected with `ERR_EFFECTIVE_DATE_OUTSIDE_WINDOW`."

        Design: Corner/validations/effective_date_outside_window_rejected
        """
        work = create_work(title="Bad Window Song", grant_date=GRANT_1990)
        # window_open is 2025-06-15; 2024-01-01 is strictly before it.
        resp = api.create_termination_claim(
            {"work_id": work["id"], "statute_basis": "SEC_203",
             "intended_effective_date": "2024-01-01T00:00:00Z"},
            COPYRIGHT)
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_OUTSIDE_WINDOW)


class TestTerminatedWorkSafetyGate:
    def test_terminated_work_safety_beats_split_sum_constraint(self, api):
        """PRD §2.8: "When a request violates several rules at once, validation tiers are evaluated in a fixed order so the returned error is deterministic:"
        PRD §2.8: "6. **Rights and compliance gates** — no split-set creation or submission and no registration submission against a `TERMINATED` work; termination effective dates inside their statutory window; notice filed inside its filing window; distribution approval segregated from calculation, else `ERR_WORK_RIGHTS_TERMINATED`, `ERR_EFFECTIVE_DATE_OUTSIDE_WINDOW`, `ERR_TERMINATION_WINDOW_NOT_OPEN`, `ERR_NOTICE_DEADLINE_PASSED` (all HTTP 409), or `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §2.8: "9. **Aggregate and duplicate constraints** — split pool sums, minimum shares, duplicate split participants, duplicate society registrations, and audit sample-base validity, else `ERR_SPLIT_SUM_INVALID`, `ERR_ZERO_SHARE_LINE`, `ERR_DUPLICATE_SPLIT_PARTICIPANT`, `ERR_DUPLICATE_SOCIETY_REGISTRATION`, or `ERR_AUDIT_SAMPLE_BASE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/terminated_work_safety_beats_split_sum_constraint
        """
        writer = create_writer(legal_name="W1")
        work = create_work(title="Terminated Song", grant_date=GRANT_1990)
        effectuate_termination(work["id"])
        assert get_work(work["id"])["copyright_status"] == "TERMINATED"

        # The writer pool sums to 9000 (a tier-9 violation) AND the work is
        # terminated (tier 6); the fixed order returns the safety error.
        lines = [writer_split_line(writer["id"], 9000),
                 publisher_split_line("OurPub", 10000)]
        resp = api.create_split_set(
            create_split_set_payload(work["id"], get_work(work["id"])["version"],
                                     lines),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_WORK_RIGHTS_TERMINATED)

    def test_terminated_work_rejects_even_valid_split_set(self, api):
        """PRD §3.3: "Creating a set against a work whose copyright is `TERMINATED` is refused with `ERR_WORK_RIGHTS_TERMINATED`."

        Design: Difficulty/priority_pair_validation_conflict/terminated_work_safety_beats_split_sum_constraint
        """
        writer = create_writer(legal_name="W1")
        work = create_work(title="Terminated Song 2", grant_date=GRANT_1990)
        effectuate_termination(work["id"])

        lines = [writer_split_line(writer["id"], 10000),
                 publisher_split_line("OurPub", 10000)]
        resp = api.create_split_set(
            create_split_set_payload(work["id"], get_work(work["id"])["version"],
                                     lines),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_WORK_RIGHTS_TERMINATED)


class TestRightsReversionCascade:
    def _setup_pending_set_and_claim(self, api):
        """Work with a PENDING_CONFIRMATIONS split set whose WRITER line is
        already CONFIRMED while the PUBLISHER line is still PENDING; a claim
        with notice filed at logical 2026-01-01."""
        writer = create_writer(legal_name="W1")
        work = create_work(title="Old Catalog Song", grant_date=GRANT_1990)
        split_set = create_split_set(work["id"], [(writer["id"], 10000)])
        submit_split_set(split_set["id"])
        lines = list_split_lines(split_set["id"])
        validate_success(api.confirm_split_line(
            lines[0]["id"], make_writer_headers(writer["id"])))

        claim = create_termination_claim(work["id"], "2028-06-15T00:00:00Z")
        set_clock("2026-01-01T00:00:00Z")
        validate_success(api.file_notice(claim["id"], "N-2026-001", COPYRIGHT))
        return writer, work, split_set, lines, claim

    def test_make_effect_terminates_work_and_cancels_sets(self, api):
        """PRD §3.10: "Effectuation is the point where rights actually revert: the work's `copyright_status` moves to `TERMINATED`, and the cascade of §3.3 fires — every SplitSet of the work still in `DRAFT`, `PENDING_CONFIRMATIONS`, or `DISPUTED` is moved to `CANCELLED`, and each of their still-`PENDING` split lines is moved to `REJECTED` with `rejection_reason` set to `WORK_RIGHTS_TERMINATED` — while the Work's `version` increments."
        PRD §3.10: "Or, once the logical clock has reached the `intended_effective_date`, making the claim effective moves it from `NOTICE_FILED` to terminal `EFFECTIVE` — attempting it earlier is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/transitive_cascade/termination_effective_rights_reversion_chain
        """
        writer, work, split_set, lines, claim = (
            self._setup_pending_set_and_claim(api))
        set_clock("2028-06-15T00:00:00Z")
        effective = validate_success(api.make_effective(claim["id"], COPYRIGHT))
        assert effective["status"] == "EFFECTIVE"

        work_after = get_work(work["id"])
        assert work_after["copyright_status"] == "TERMINATED"

        set_after = validate_success(api.get_split_set(split_set["id"], ADMIN))
        assert set_after["status"] == "CANCELLED", (
            "the still-negotiating set is cancelled by the cascade")

    def test_cascade_rejects_only_pending_lines(self, api):
        """PRD §3.3: "Termination of the work's rights (§3.10) cancels any set of that work still in `DRAFT`, `PENDING_CONFIRMATIONS`, or `DISPUTED`, moving it to `CANCELLED`; each of its still-`PENDING` lines is moved to `REJECTED` by the system with `rejection_reason` set to `WORK_RIGHTS_TERMINATED`. `SUPERSEDED` and `CANCELLED` are terminal for a set."

        Design: Difficulty/transitive_cascade/termination_effective_rights_reversion_chain
        """
        writer, work, split_set, lines, claim = (
            self._setup_pending_set_and_claim(api))
        set_clock("2028-06-15T00:00:00Z")
        validate_success(api.make_effective(claim["id"], COPYRIGHT))

        after = list_split_lines(split_set["id"])
        writer_line = after[0]
        publisher_line = after[1]
        assert publisher_line["confirmation_status"] == "REJECTED"
        assert publisher_line["rejection_reason"] == "WORK_RIGHTS_TERMINATED"
        assert writer_line["confirmation_status"] == "CONFIRMED", (
            "the conditional cascade rejects only still-PENDING lines")
