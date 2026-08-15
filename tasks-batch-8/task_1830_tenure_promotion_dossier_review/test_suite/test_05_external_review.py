"""External review: solicitation, arm's-length and capacity gates, invitation
lifecycle and lazy expiry, letter-count and midterm gates, committee selection,
and the default logical clock (PRD §2.4, §3.4, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_invitation,
    assert_instant_eq,
    build_committee,
    create_committee,
    decline_invitation,
    invite_reviewer,
    latest_round,
    list_case_rounds,
    make_external_reviewer_headers,
    read_case,
    read_case_version,
    read_invitation,
    register_reviewer,
    set_logical_clock,
    setup_external_review_case,
    setup_solicited_case,
    validate_error,
    validate_paginated,
    validate_success,
)

PO_HEADERS = TEST_USERS["provost_creator_headers"]
READER_HEADERS = TEST_USERS["reader_headers"]


def test_invitation_lifecycle_time_gates(api):
    """PRD §3.4: "Both responses apply lazy expiry first: if the logical clock
    has passed the `response_deadline`, the invitation flips to `EXPIRED` and the
    response fails with `ERR_INVITATION_EXPIRED`."
    PRD §3.4: "submission is allowed only while the clock has not passed
    `review_window_end` — a late letter is rejected with
    `ERR_REVIEW_WINDOW_CLOSED`".
    PRD §3.4: "Any response, letter submission, or withdrawal attempted from an
    incompatible status is rejected with `ERR_INVALID_INVITATION_STATE`."

    Design: Corner/state_machines/invitation_lifecycle_time_gates
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    ctx = setup_external_review_case("E9110", full_name="Cand IL", reset_clock=False)
    case_id = ctx["case"]["id"]
    rev1 = register_reviewer("Rev IL1", "ril1@mit.edu")
    rev2 = register_reviewer("Rev IL2", "ril2@cmu.edu", institution="CMU")
    # A short letter window that closes on 2026-08-05.
    inv1 = invite_reviewer(case_id, rev1["id"], "2026-08-03", "2026-08-05")
    # A normal window; response deadline 2026-08-01 + 14 days = 2026-08-15.
    inv2 = invite_reviewer(case_id, rev2["id"], "2026-08-10", "2026-09-10")

    accept_invitation(inv1["id"], rev1["id"])

    # Letter submitted after the review window closed.
    set_logical_clock("2026-08-06T00:00:00Z")
    err_letter = api.submit_letter(
        inv1["id"], {"letter_text": "Too late."},
        make_external_reviewer_headers(rev1["id"]),
    )
    validate_error(err_letter, ApiErrorId.ERR_REVIEW_WINDOW_CLOSED)
    assert read_invitation(inv1["id"])["status"] == "ACCEPTED", (
        "A failed letter submission must not transition the invitation"
    )

    # Accept attempted after the response deadline: lazy expiry fires.
    set_logical_clock("2026-08-16T00:00:00Z")
    err_accept = api.accept_invitation(
        inv2["id"], make_external_reviewer_headers(rev2["id"])
    )
    validate_error(err_accept, ApiErrorId.ERR_INVITATION_EXPIRED)
    assert read_invitation(inv2["id"])["status"] == "EXPIRED"

    # EXPIRED is terminal for accept.
    err_again = api.accept_invitation(
        inv2["id"], make_external_reviewer_headers(rev2["id"])
    )
    validate_error(err_again, ApiErrorId.ERR_INVALID_INVITATION_STATE)


def test_arms_length_gate_on_solicitation(api):
    """PRD §2.7: "Finally, an invitation may only be created under an
    arm's-length certification: `is_arm_length` must be true and
    `declared_coauthor` must be false, otherwise creation is rejected with
    `ERR_ARMS_LENGTH_VIOLATION`."

    Design: Corner/validations/arms_length_gate_on_solicitation
    """
    ctx = setup_external_review_case("E9303", full_name="Cand AL")
    case_id = ctx["case"]["id"]
    reviewer = register_reviewer("Rev AL", "ral@mit.edu")

    coauthor = api.create_invitation(
        {
            "case_id": case_id,
            "reviewer_id": reviewer["id"],
            "review_window_start": "2026-08-10",
            "review_window_end": "2026-09-10",
            "is_arm_length": True,
            "declared_coauthor": True,
            "expected_case_version": read_case_version(case_id),
        },
        PO_HEADERS,
    )
    validate_error(coauthor, ApiErrorId.ERR_ARMS_LENGTH_VIOLATION)

    not_arm_length = api.create_invitation(
        {
            "case_id": case_id,
            "reviewer_id": reviewer["id"],
            "review_window_start": "2026-08-10",
            "review_window_end": "2026-09-10",
            "is_arm_length": False,
            "declared_coauthor": False,
            "expected_case_version": read_case_version(case_id),
        },
        PO_HEADERS,
    )
    validate_error(not_arm_length, ApiErrorId.ERR_ARMS_LENGTH_VIOLATION)

    data, meta = validate_paginated(
        api.list_invitations(READER_HEADERS, {"case_id": case_id})
    )
    assert meta["total_count"] == 0, "Rejected solicitations must not persist"


def test_duplicate_invitation_same_case_reviewer_rejected(api):
    """PRD §3.4: "no other invitation for the same case and reviewer may exist in
    `SOLICITED`, `ACCEPTED`, or `LETTER_RECEIVED` status
    (`ERR_DUPLICATE_INVITATION`)".
    PRD §3.4: "The provost office may withdraw a `SOLICITED` or `ACCEPTED`
    invitation, moving it to `WITHDRAWN`."

    Design: Corner/state_machines/duplicate_invitation_same_case_reviewer_rejected
    """
    ctx = setup_external_review_case("E9112", full_name="Cand DI")
    case_id = ctx["case"]["id"]
    reviewer = register_reviewer("Rev DI", "rdi@mit.edu")
    inv1 = invite_reviewer(case_id, reviewer["id"])
    assert inv1["status"] == "SOLICITED"

    dup = api.create_invitation(
        {
            "case_id": case_id,
            "reviewer_id": reviewer["id"],
            "review_window_start": "2026-08-12",
            "review_window_end": "2026-09-12",
            "is_arm_length": True,
            "declared_coauthor": False,
            "expected_case_version": read_case_version(case_id),
        },
        PO_HEADERS,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_INVITATION)

    # Withdrawing the first invitation frees the (case, reviewer) pair.
    validate_success(api.withdraw_invitation(inv1["id"], PO_HEADERS))
    inv2 = invite_reviewer(case_id, reviewer["id"], "2026-08-12", "2026-09-12")
    assert inv2["status"] == "SOLICITED"


class TestReviewerCapacityClosedTouch:
    def _setup_three_cases(self):
        set_logical_clock("2026-08-01T00:00:00Z")
        ctxs = [
            setup_external_review_case(emp, full_name=name, reset_clock=False)
            for emp, name in (
                ("E1901", "Cand K1"), ("E1902", "Cand K2"), ("E1903", "Cand K3")
            )
        ]
        reviewer = register_reviewer("Rev X", "rx@mit.edu")
        i1 = invite_reviewer(ctxs[0]["case"]["id"], reviewer["id"], "2026-08-10", "2026-09-10")
        i2 = invite_reviewer(ctxs[1]["case"]["id"], reviewer["id"], "2026-09-05", "2026-10-05")
        return ctxs, reviewer, i1, i2

    def test_touching_window_counts_toward_capacity(self, api):
        """PRD §3.4: "the reviewer must have capacity — if the reviewer already
        holds two invitations in `SOLICITED` or `ACCEPTED` status whose review
        windows overlap the new window under the closed semantics of §2.8, where
        touching windows count as overlapping, creation is rejected with
        `ERR_REVIEWER_CAPACITY_EXCEEDED`, while two such invitations whose
        windows do not touch the new one leave capacity open."

        Design: Difficulty/resource_temporal_overlap/reviewer_capacity_closed_interval_touch_counts
        """
        ctxs, reviewer, _i1, _i2 = self._setup_three_cases()
        # The new window [2026-09-10, 2026-09-25] merely TOUCHES i1 at
        # 2026-09-10 (closed semantics: the touch counts) and genuinely
        # overlaps i2 — the count reaches two.
        err = api.create_invitation(
            {
                "case_id": ctxs[2]["case"]["id"],
                "reviewer_id": reviewer["id"],
                "review_window_start": "2026-09-10",
                "review_window_end": "2026-09-25",
                "is_arm_length": True,
                "declared_coauthor": False,
                "expected_case_version": read_case_version(ctxs[2]["case"]["id"]),
            },
            PO_HEADERS,
        )
        validate_error(err, ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED)

    def test_capacity_rejection_materializes_no_invitation(self, api):
        """PRD §3.4: "creation is rejected with
        `ERR_REVIEWER_CAPACITY_EXCEEDED`, while two such invitations whose
        windows do not touch the new one leave capacity open."

        Design: Difficulty/resource_temporal_overlap/reviewer_capacity_closed_interval_touch_counts
        """
        ctxs, reviewer, i1, i2 = self._setup_three_cases()
        api.create_invitation(
            {
                "case_id": ctxs[2]["case"]["id"],
                "reviewer_id": reviewer["id"],
                "review_window_start": "2026-09-10",
                "review_window_end": "2026-09-25",
                "is_arm_length": True,
                "declared_coauthor": False,
                "expected_case_version": read_case_version(ctxs[2]["case"]["id"]),
            },
            PO_HEADERS,
        )
        data, meta = validate_paginated(
            api.list_invitations(READER_HEADERS, {"case_id": ctxs[2]["case"]["id"]})
        )
        assert meta["total_count"] == 0, "The rejected create must not materialize"
        assert read_invitation(i1["id"])["status"] == "SOLICITED"
        assert read_invitation(i2["id"])["status"] == "SOLICITED"


class TestCapacityBeforeTemporalPriority:
    def _setup(self):
        # Solicitations happen at 2026-06-01 so both windows are future-valid.
        set_logical_clock("2026-06-01T00:00:00Z")
        ctx_t = setup_external_review_case("E1200", full_name="Cand T", reset_clock=False)
        ctx_t2 = setup_external_review_case("E1201", full_name="Cand T2", reset_clock=False)
        ctx_t3 = setup_external_review_case("E1202", full_name="Cand T3", reset_clock=False)
        reviewer = register_reviewer("Rev T", "rt@mit.edu")
        i1 = invite_reviewer(ctx_t["case"]["id"], reviewer["id"], "2026-06-10", "2026-07-10")
        i2 = invite_reviewer(ctx_t2["case"]["id"], reviewer["id"], "2026-06-15", "2026-07-15")
        # Advance past both review windows; the invitations linger SOLICITED
        # because nothing path-targets them.
        set_logical_clock("2026-08-01T00:00:00Z")
        return ctx_t3, reviewer, i1, i2

    def test_capacity_error_precedes_window_temporal_error(self, api):
        """PRD §2.12: "When a request would fail several checks, the error
        surfaced is the one from the earliest applicable priority. Priorities
        are evaluated in ascending order:"
        PRD §2.12: "**Structural constraints.** Uniqueness of `employee_id` and
        reviewer `email`, one non-retracted ballot per member per round, one
        active chair per committee, supersede-target shape, duplicate
        non-terminal invitations, interval sanity, extension overlap and day
        cap, reviewer capacity, and voter eligibility —
        `ERR_DUPLICATE_EMPLOYEE_ID`, `ERR_DUPLICATE_REVIEWER_EMAIL`,
        `ERR_DUPLICATE_BALLOT`, `ERR_CHAIR_CONFLICT`,
        `ERR_SUPERSEDE_TARGET_INVALID`, `ERR_DUPLICATE_INVITATION`,
        `ERR_INVALID_INTERVAL`, `ERR_EXTENSION_INTERVAL_OVERLAP`,
        `ERR_REVIEWER_CAPACITY_EXCEEDED`"
        PRD §2.12: "**Temporal windows.** Deadline checks against the logical
        clock — `ERR_REVIEW_CLOCK_EXPIRED`, `ERR_INVITATION_EXPIRED`,
        `ERR_REVIEW_WINDOW_CLOSED`, `ERR_NOTIFICATION_WINDOW_LAPSED`,
        `ERR_APPEAL_WINDOW_LAPSED`, `ERR_APPEAL_WINDOW_OPEN`, and
        `ERR_RETENTION_NOT_EXPIRED` (all HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/invitation_create_constraint_before_temporal
        """
        ctx_t3, reviewer, _i1, _i2 = self._setup()
        # Both fail: capacity (two overlapping SOLICITED invitations) and the
        # temporal window rule (window end 2026-07-20 is already past).
        err = api.create_invitation(
            {
                "case_id": ctx_t3["case"]["id"],
                "reviewer_id": reviewer["id"],
                "review_window_start": "2026-06-20",
                "review_window_end": "2026-07-20",
                "is_arm_length": True,
                "declared_coauthor": False,
                "expected_case_version": read_case_version(ctx_t3["case"]["id"]),
            },
            PO_HEADERS,
        )
        validate_error(err, ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED)

    def test_capacity_scan_does_not_expire_solicited_invitations(self, api):
        """PRD §2.4: "Reads of other invitations, such as capacity scans or list
        retrievals, never trigger expiry of an invitation they do not target."

        Design: Difficulty/priority_pair_validation_conflict/invitation_create_constraint_before_temporal
        """
        ctx_t3, reviewer, i1, i2 = self._setup()
        api.create_invitation(
            {
                "case_id": ctx_t3["case"]["id"],
                "reviewer_id": reviewer["id"],
                "review_window_start": "2026-06-20",
                "review_window_end": "2026-07-20",
                "is_arm_length": True,
                "declared_coauthor": False,
                "expected_case_version": read_case_version(ctx_t3["case"]["id"]),
            },
            PO_HEADERS,
        )
        # Observe via the list endpoint: a list retrieval has no path identifier
        # and per PRD §2.4 never triggers expiry — unlike a path-targeted GET,
        # which would flip a past-deadline SOLICITED invitation to EXPIRED on
        # its own and could not distinguish scan-expiry from read-expiry.
        data, _meta = validate_paginated(
            api.list_invitations(READER_HEADERS, {"reviewer_id": reviewer["id"]})
        )
        by_id = {inv["id"]: inv for inv in data}
        # Both deadlines passed on 2026-06-15, yet neither invitation flipped.
        assert by_id[i1["id"]]["status"] == "SOLICITED"
        assert by_id[i2["id"]]["status"] == "SOLICITED"


def test_occ_invitation_stale_case_version(api):
    """PRD §2.11: "Creating a reviewer invitation likewise requires
    `expected_case_version` matching the target case's current `version`, with
    the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch."

    Design: Corner/cross_cutting_layers/occ_invitation_stale_case_version
    """
    ctx = setup_external_review_case("E9601", full_name="Cand OI")
    case_id = ctx["case"]["id"]
    snapshot_version = read_case_version(case_id)
    rev1 = register_reviewer("Rev OI1", "roi1@mit.edu")
    rev2 = register_reviewer("Rev OI2", "roi2@cmu.edu", institution="CMU")

    first = api.create_invitation(
        {
            "case_id": case_id,
            "reviewer_id": rev1["id"],
            "review_window_start": "2026-08-10",
            "review_window_end": "2026-09-10",
            "is_arm_length": True,
            "declared_coauthor": False,
            "expected_case_version": snapshot_version,
        },
        PO_HEADERS,
    )
    validate_success(first, 201)

    stale = api.create_invitation(
        {
            "case_id": case_id,
            "reviewer_id": rev2["id"],
            "review_window_start": "2026-08-10",
            "review_window_end": "2026-09-10",
            "is_arm_length": True,
            "declared_coauthor": False,
            "expected_case_version": snapshot_version,
        },
        PO_HEADERS,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


def test_return_for_revision_gated_on_accepted_invitations(api):
    """PRD §3.2: "A `ProvostOfficer` may return the case for revision only while
    no invitation of the case stands in `ACCEPTED` status — accepted reviewers
    must first be withdrawn or deliver their letters, otherwise the return is
    rejected with `ERR_OPEN_INVITATIONS_EXIST`. On return, the case moves to
    `RETURNED_FOR_REVISION`, every `SOLICITED` invitation of the case flips to
    `WITHDRAWN` and its review window is released, and the case's `version`
    increments by one."

    Design: Corner/state_machines/return_for_revision_gated_on_accepted_invitations
    """
    ctx = setup_external_review_case("E9111", full_name="Cand RG")
    case_id = ctx["case"]["id"]
    rev_a = register_reviewer("Rev RG1", "rrg1@mit.edu")
    rev_b = register_reviewer("Rev RG2", "rrg2@cmu.edu", institution="CMU")
    inv_a = invite_reviewer(case_id, rev_a["id"])
    inv_b = invite_reviewer(case_id, rev_b["id"])
    accept_invitation(inv_a["id"], rev_a["id"])

    blocked = api.return_for_revision(case_id, PO_HEADERS)
    validate_error(blocked, ApiErrorId.ERR_OPEN_INVITATIONS_EXIST)

    validate_success(api.withdraw_invitation(inv_a["id"], PO_HEADERS))
    returned = validate_success(api.return_for_revision(case_id, PO_HEADERS))
    assert returned["stage"] == "RETURNED_FOR_REVISION"
    assert read_invitation(inv_b["id"])["status"] == "WITHDRAWN", (
        "SOLICITED invitations auto-withdraw on the return transition"
    )


class TestLetterCountBoundary:
    def _setup_three_plus_decline(self, employee_id):
        ctx = setup_solicited_case(employee_id, letter_count=3, email_prefix="l")
        case_id = ctx["case"]["id"]
        rev4 = register_reviewer("Rev L4", f"{employee_id.lower()}l4@yale.edu",
                                 institution="Yale")
        inv4 = invite_reviewer(case_id, rev4["id"])
        decline_invitation(inv4["id"], rev4["id"])
        build_committee("DEPARTMENT", "CS", 1, email_prefix=f"c{employee_id.lower()}")
        return ctx, inv4

    def test_three_letters_with_one_decline_close_succeeds(self, api):
        """PRD §3.4: "Only invitations in `LETTER_RECEIVED` status count as
        usable letters — `SOLICITED`, `ACCEPTED`, `DECLINED`, `WITHDRAWN`, and
        `EXPIRED` never count — and the case needs at least three of them, with
        exactly three passing; a shortfall is rejected with
        `ERR_INSUFFICIENT_EXTERNAL_LETTERS`."

        Design: Difficulty/boundary_precision_check/letters_exactly_three_with_decline_passes
        """
        ctx, _inv4 = self._setup_three_plus_decline("E1300")
        closed = validate_success(api.close_solicitation(ctx["case"]["id"], PO_HEADERS))
        assert closed["stage"] == "DEPT_COMMITTEE", (
            "Exactly three usable letters satisfies the >= 3 minimum"
        )

    def test_declined_invitation_never_counts_and_round_created(self, api):
        """PRD §3.4: "On success the system creates the department-level review
        round in `SCHEDULED` status, bound to the selected committee, and
        increments the case's `version` by one."
        PRD §3.4: "Only invitations in `LETTER_RECEIVED` status count as usable
        letters — `SOLICITED`, `ACCEPTED`, `DECLINED`, `WITHDRAWN`, and
        `EXPIRED` never count".

        Design: Difficulty/boundary_precision_check/letters_exactly_three_with_decline_passes
        """
        ctx, inv4 = self._setup_three_plus_decline("E1301")
        validate_success(api.close_solicitation(ctx["case"]["id"], PO_HEADERS))

        assert read_invitation(inv4["id"])["status"] == "DECLINED"
        rounds = list_case_rounds(ctx["case"]["id"])
        assert len(rounds) == 1, f"Exactly one round must be created, got {len(rounds)}"
        assert rounds[0]["status"] == "SCHEDULED"
        assert rounds[0]["level"] == "DEPARTMENT"


def test_two_letters_close_solicitation_rejected(api):
    """PRD §3.4: "the case needs at least three of them, with exactly three
    passing; a shortfall is rejected with `ERR_INSUFFICIENT_EXTERNAL_LETTERS`."

    Design: Corner/calculations/two_letters_close_solicitation_rejected
    """
    ctx = setup_solicited_case("E9201", letter_count=2, email_prefix="t")
    build_committee("DEPARTMENT", "CS", 1, email_prefix="ct")
    err = api.close_solicitation(ctx["case"]["id"], PO_HEADERS)
    validate_error(err, ApiErrorId.ERR_INSUFFICIENT_EXTERNAL_LETTERS)
    assert read_case(ctx["case"]["id"])["stage"] == "EXTERNAL_REVIEW"


def test_close_solicitation_without_midterm_review_rejected(api):
    """PRD §3.4: "A `COMPLETED` mid-tenure review must exist for the case
    (`ERR_MIDTERM_REVIEW_MISSING`)".

    Design: Corner/validations/midterm_gate_matrix
    """
    ctx = setup_solicited_case("E9305", letter_count=3, with_midterm=False,
                               email_prefix="ma")
    build_committee("DEPARTMENT", "CS", 1, email_prefix="cma")
    err = api.close_solicitation(ctx["case"]["id"], PO_HEADERS)
    validate_error(err, ApiErrorId.ERR_MIDTERM_REVIEW_MISSING)


def test_close_solicitation_with_unsatisfactory_midterm_blocked(api):
    """PRD §3.4: "no completed mid-tenure review may carry the `UNSATISFACTORY`
    outcome (`ERR_MIDTERM_OUTCOME_BLOCKS`)".

    Design: Corner/validations/midterm_gate_matrix
    """
    ctx = setup_solicited_case(
        "E9306", letter_count=3, midterm_outcome="UNSATISFACTORY", email_prefix="mb"
    )
    build_committee("DEPARTMENT", "CS", 1, email_prefix="cmb")
    err = api.close_solicitation(ctx["case"]["id"], PO_HEADERS)
    validate_error(err, ApiErrorId.ERR_MIDTERM_OUTCOME_BLOCKS)


def test_committee_selector_tiebreak_and_empty_pool(api):
    """PRD §3.5: "Eligible committees are ranked by `term_start` with the most
    recent term first, ties broken by earliest `created_at`; entity identifiers
    are never used for ranking. An empty candidate set fails the calling
    transition with `ERR_NO_ELIGIBLE_COMMITTEE`."
    PRD §3.5: "the `academic_unit` must match the candidate's `department` for a
    `DEPARTMENT` round or the candidate's `college` for a `COLLEGE` round".

    Design: Corner/calculations/committee_selector_tiebreak_and_empty_pool
    """
    ctx_a = setup_solicited_case("E9203", department="CS", college="ENG",
                                 email_prefix="sa")
    ctx_b = setup_solicited_case("E9204", department="BIO", college="SCI",
                                 email_prefix="sb")
    # Two eligible DEPARTMENT committees for CS; the later term_start wins.
    create_committee("DEPARTMENT", "CS", term_start="2026-01-01", term_end="2026-12-31")
    comm_c2 = create_committee(
        "DEPARTMENT", "CS", term_start="2026-03-01", term_end="2027-03-01"
    )
    # Only a HISTORY committee exists for the BIO candidate — an empty set.
    create_committee("DEPARTMENT", "HISTORY")

    validate_success(api.close_solicitation(ctx_a["case"]["id"], PO_HEADERS))
    round_a = latest_round(ctx_a["case"]["id"], level="DEPARTMENT")
    assert round_a["committee_id"] == comm_c2["id"], (
        "The committee with the most recent term_start must win"
    )

    err_b = api.close_solicitation(ctx_b["case"]["id"], PO_HEADERS)
    validate_error(err_b, ApiErrorId.ERR_NO_ELIGIBLE_COMMITTEE)
    assert read_case(ctx_b["case"]["id"])["stage"] == "EXTERNAL_REVIEW"


def test_clock_default_drives_system_timestamps(api):
    """PRD §2.4: "When the server starts, and before any operator intervention,
    the logical clock reads exactly `2026-08-01T00:00:00Z`; it never silently
    falls back to the host's wall clock."
    PRD §3.4: "The invitation is created directly in `SOLICITED` status,
    `invited_at` is stamped with the current clock reading, and
    `response_deadline` is set fourteen days after `invited_at`."

    Design: Corner/endpoints/clock_default_drives_system_timestamps
    """
    # Deliberately no set_clock call: the startup default must drive stamps.
    ctx = setup_external_review_case("E9402", full_name="Cand CK", reset_clock=False)
    reviewer = register_reviewer("Rev CK", "rck@mit.edu")
    invitation = invite_reviewer(ctx["case"]["id"], reviewer["id"])
    assert_instant_eq(invitation["invited_at"], "2026-08-01T00:00:00Z", "invited_at")
    assert_instant_eq(
        invitation["response_deadline"], "2026-08-15T00:00:00Z",
        "response_deadline (invited_at + 14 days)",
    )
