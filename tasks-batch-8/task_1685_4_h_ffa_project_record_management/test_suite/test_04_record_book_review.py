"""Record book ledgering, submission, scoring variants, review, and OCC."""
import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    assert_ledger_entry,
    assert_record_book,
    build_approved_record_book,
    create_active_member,
    create_denied_volunteer,
    create_draft_record_book_with_entry,
    create_ledger_entry_payload,
    create_record_book_payload,
    create_volunteer,
    make_member_headers,
    make_volunteer_headers,
    record_attendance_and_hold,
    review_and_approve_book,
    set_logical_clock,
    setup_active_member_with_project,
    setup_club_with_volunteers,
    setup_eligible_member,
    submit_book,
    submit_record_book_payload,
    tag_animal,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestLedgerEntries:
    def test_ledger_entry_defaults_to_posted(self, api):
        """PRD §3.5: "Each line's `entry_status` is POSTED on creation."

        Design: Corner/entities/ledger_entry_computed_default_posted
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx)
        rb = validate_success(
            api.create_record_book(
                create_record_book_payload(project["id"]), make_member_headers(member["id"])
            ),
            201,
        )
        res = api.create_ledger_entry(
            create_ledger_entry_payload(rb["id"], entry_kind="EXPENSE", amount_cents=100, hours=0),
            make_member_headers(member["id"]),
        )
        entry = validate_success(res, 201)
        assert_ledger_entry(entry)
        assert entry["entry_status"] == "POSTED", (
            f"ledger line must be POSTED on creation, got {entry['entry_status']}"
        )


class TestSubmissionPreconditions:
    def test_submit_without_ledger_entries_rejected(self, api):
        """PRD §3.5: "A first submission moves DRAFT → SUBMITTED and requires
        that the book contains at least one POSTED ledger line and that the
        project is still ACTIVE." PRD §2.9: "the target
        resource is in a valid from-state for the requested transition;
        otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/record_book_submit_without_entries_rejected
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx)
        rb = validate_success(
            api.create_record_book(
                create_record_book_payload(project["id"]), make_member_headers(member["id"])
            ),
            201,
        )
        payload = submit_record_book_payload(rb["version"], **TEST_DEFAULTS["SCORES_70"])
        res = api.submit_record_book(rb["id"], payload, make_member_headers(member["id"]))
        validate_error(res, "ERR_INVALID_STATE")


class TestProvisionalVsFinalScore:
    def test_late_officer_book_scores_diverge(self, api):
        """PRD §3.5: "The provisional score, computed at submission, is the
        plain weighted sum of the four section scores: `completeness` at thirty
        percent, `accuracy` at twenty-five percent, `financial` at twenty-five
        percent, and `reflection` at twenty percent — no bonus, no penalty."
        PRD §3.5: "The final score, computed at approval, applies its
        adjustments in a pinned order: start from the same weighted sum; then,
        if the member's `is_club_officer` flag is set, add a five-point
        leadership bonus and cap the result at 100; then subtract the late
        penalty — three points per whole late day, with the penalty itself
        capped at fifteen points — and floor the result at zero."

        Sections 80/90/70/85 -> provisional 81.00; officer, 2 days late ->
        final = min(100, 81+5) - 2*3 = 80.00.

        Design: Difficulty/dual_variant_calc/record_book_provisional_vs_final_score
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx, officer=True)
        rb = create_draft_record_book_with_entry(project["id"], member["id"], amount_cents=15000)
        submitted = submit_book(
            rb, member["id"], submit_at=TEST_DEFAULTS["CLOCK_TWO_DAYS_LATE"]
        )
        assert_record_book(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["late_days"] == 2, (
            f"submitted 2026-07-17 against the 2026-07-15 deadline must be 2 days late, "
            f"got {submitted['late_days']}"
        )
        assert submitted["provisional_score"] == pytest.approx(81.00, abs=0.01), (
            f"provisional is the plain weighted sum 81.00, got {submitted['provisional_score']}"
        )
        assert submitted.get("final_score") is None, "final_score must not exist before approval"

        approved = review_and_approve_book(rb["id"], ctx["vol1"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved["final_score"] == pytest.approx(80.00, abs=0.01), (
            f"final applies +5 bonus then -6 late penalty: 80.00, got {approved['final_score']}"
        )
        assert approved["provisional_score"] == pytest.approx(81.00, abs=0.01)
        assert approved["final_score"] != pytest.approx(approved["provisional_score"], abs=0.001)

    def test_on_time_non_officer_book_scores_agree(self, api):
        """PRD §3.5: "The provisional score, computed at submission, is the
        plain weighted sum of the four section scores: `completeness` at thirty
        percent, `accuracy` at twenty-five percent, `financial` at twenty-five
        percent, and `reflection` at twenty percent — no bonus, no penalty."
        PRD §3.5: "if the member's `is_club_officer` flag is set, add a
        five-point leadership bonus and cap the result at 100; then subtract the
        late penalty — three points per whole late day, with the penalty itself
        capped at fifteen points — and floor the result at zero."

        Non-officer, submitted on 2026-07-10 (on time): both adjustments are
        zero, so final == provisional == 81.00.

        Design: Difficulty/dual_variant_calc/record_book_provisional_vs_final_score
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx, officer=False)
        rb = create_draft_record_book_with_entry(project["id"], member["id"])
        submitted = submit_book(rb, member["id"])
        assert submitted["late_days"] == 0
        assert submitted["provisional_score"] == pytest.approx(81.00, abs=0.01)

        approved = review_and_approve_book(rb["id"], ctx["vol1"]["id"])
        assert approved["final_score"] == pytest.approx(81.00, abs=0.01), (
            f"with no bonus and no penalty the variants coincide at 81.00, "
            f"got {approved['final_score']}"
        )


class TestRevisionCycle:
    def test_full_revision_cycle_reaches_approved(self, api):
        """PRD §3.5: "Review belongs to volunteers and runs SUBMITTED →
        UNDER_REVIEW → a terminal verdict, with one return path." PRD §3.5: "A
        book returned for revision is resubmitted the same way (RETURNED →
        SUBMITTED); resubmission requires only that the project is still ACTIVE,
        and it re-stamps `submitted_at` and recomputes both `late_days` and the
        `provisional_score`."

        DRAFT -> SUBMITTED -> UNDER_REVIEW -> RETURNED -> SUBMITTED ->
        UNDER_REVIEW -> APPROVED: the loop is not a linear pipeline.

        Design: Difficulty/non_linear_state_machine/record_book_revision_cycle
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx)
        rb = create_draft_record_book_with_entry(
            project["id"], member["id"], entry_kind="HOURS", amount_cents=0, hours=12
        )
        submitted = submit_book(rb, member["id"], scores=TEST_DEFAULTS["SCORES_70"])
        assert submitted["status"] == "SUBMITTED"
        vol_headers = make_volunteer_headers(ctx["vol1"]["id"])
        validate_success(api.begin_review_record_book(rb["id"], vol_headers), 200)
        returned = validate_success(api.return_record_book(rb["id"], vol_headers), 200)
        assert returned["status"] == "RETURNED"

        # Resubmit from RETURNED with the version captured from the return.
        resubmitted = validate_success(
            api.submit_record_book(
                rb["id"],
                submit_record_book_payload(returned["version"], **TEST_DEFAULTS["SCORES_90"]),
                make_member_headers(member["id"]),
            ),
            200,
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["provisional_score"] == pytest.approx(90.00, abs=0.01), (
            "resubmission must recompute the provisional score from the new sections"
        )

        validate_success(api.begin_review_record_book(rb["id"], vol_headers), 200)
        approved = validate_success(api.approve_record_book(rb["id"], vol_headers), 200)
        assert approved["status"] == "APPROVED", (
            "a book must be approvable after a full return-and-resubmit cycle"
        )

    def test_resubmission_recomputes_late_days(self, api):
        """PRD §3.5: "A book returned for revision is resubmitted the same way
        (RETURNED → SUBMITTED); resubmission requires only that the project is
        still ACTIVE, and it re-stamps `submitted_at` and recomputes both
        `late_days` and the `provisional_score`." PRD §3.5: "Lateness is
        measured against the program-year record-book deadline of July 15, 2026,
        end of day UTC: `late_days` counts the whole calendar dates by which the
        UTC date of `submitted_at` falls after that date, and is zero for a book
        submitted on or before it."

        First submit on time (late_days 0); after return, advance the clock to
        2026-07-17 and resubmit -> late_days recomputed to 2.

        Design: Difficulty/non_linear_state_machine/record_book_revision_cycle
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx)
        rb = create_draft_record_book_with_entry(project["id"], member["id"])
        submitted = submit_book(rb, member["id"], scores=TEST_DEFAULTS["SCORES_70"])
        assert submitted["late_days"] == 0

        vol_headers = make_volunteer_headers(ctx["vol1"]["id"])
        validate_success(api.begin_review_record_book(rb["id"], vol_headers), 200)
        returned = validate_success(api.return_record_book(rb["id"], vol_headers), 200)

        set_logical_clock(TEST_DEFAULTS["CLOCK_TWO_DAYS_LATE"])
        resubmitted = validate_success(
            api.submit_record_book(
                rb["id"],
                submit_record_book_payload(returned["version"], **TEST_DEFAULTS["SCORES_90"]),
                make_member_headers(member["id"]),
            ),
            200,
        )
        assert resubmitted["late_days"] == 2, (
            f"resubmission at 2026-07-17 must recompute late_days to 2, "
            f"got {resubmitted['late_days']}"
        )


class TestTerminalLockdown:
    def test_submit_on_approved_book_rejected(self, api):
        """PRD §3.5: "APPROVED and REJECTED are both terminal for the book."
        PRD §3.3: "any transition attempted from a state other than its declared
        from-state is rejected with `ERR_INVALID_STATE` (HTTP 409) — here and
        everywhere else in this section."

        Design: Corner/state_machines/record_book_terminal_approved_lockdown
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx)
        rb = create_draft_record_book_with_entry(project["id"], member["id"], amount_cents=100)
        submit_book(rb, member["id"], scores=TEST_DEFAULTS["SCORES_70"])
        approved = review_and_approve_book(rb["id"], ctx["vol1"]["id"])
        assert approved["status"] == "APPROVED"

        payload = submit_record_book_payload(approved["version"], **TEST_DEFAULTS["SCORES_90"])
        res = api.submit_record_book(rb["id"], payload, make_member_headers(member["id"]))
        validate_error(res, "ERR_INVALID_STATE")


class TestValidationPriority:
    def test_draft_book_approve_reports_state_not_screening(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline,
        and the first failing check determines the error returned." PRD §2.9:
        "the target resource is in a valid from-state for
        the requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409).
        Applies to all action endpoints, so a transition attempted from the
        wrong state always fails here before any business check runs."

        A DRAFT book approved by a PENDING (not cleared) volunteer violates both
        the from-state rule and the screening gate; the state error wins.

        Design: Difficulty/priority_pair_validation_conflict/state_before_business_safety_on_approve
        """
        ctx = setup_club_with_volunteers()
        pending_vol = create_volunteer(ctx["club"]["id"], base_clearance=50, risk_flags=2, years_service=0)
        member, project = setup_active_member_with_project(ctx)
        rb = create_draft_record_book_with_entry(project["id"], member["id"])
        assert rb["status"] == "DRAFT"

        res = api.approve_record_book(rb["id"], make_volunteer_headers(pending_vol["id"]))
        validate_error(res, "ERR_INVALID_STATE")

    def test_submitted_book_approve_reports_state_not_screening(self, api):
        """PRD §2.9: "Applies to all action endpoints, so a transition attempted
        from the wrong state always fails here before any business check runs."

        A SUBMITTED (never UNDER_REVIEW) book approved by a PENDING volunteer:
        the from-state violation is reported, not the screening violation.

        Design: Difficulty/priority_pair_validation_conflict/state_before_business_safety_on_approve
        """
        ctx = setup_club_with_volunteers()
        pending_vol = create_volunteer(ctx["club"]["id"], base_clearance=50, risk_flags=2, years_service=0)
        member, project = setup_active_member_with_project(ctx)
        rb = create_draft_record_book_with_entry(project["id"], member["id"])
        submitted = submit_book(rb, member["id"], scores=TEST_DEFAULTS["SCORES_70"])
        assert submitted["status"] == "SUBMITTED"

        res = api.approve_record_book(rb["id"], make_volunteer_headers(pending_vol["id"]))
        validate_error(res, "ERR_INVALID_STATE")


class TestApproveRequiresClearedVolunteer:
    def test_pending_volunteer_approve_rejected(self, api):
        """PRD §3.5: "Approval is gated on clearance: the acting volunteer's
        `screening_status` must be CLEARED, otherwise the approval is rejected
        with `ERR_SCREENING_NOT_CLEARED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/record_book_approve_requires_volunteer_cleared
        """
        ctx = setup_club_with_volunteers()
        pending_vol = create_volunteer(ctx["club"]["id"], base_clearance=50, risk_flags=2, years_service=0)
        member, project = setup_active_member_with_project(ctx)
        rb = create_draft_record_book_with_entry(project["id"], member["id"], amount_cents=2000)
        submit_book(rb, member["id"], scores=TEST_DEFAULTS["SCORES_70"])
        validate_success(
            api.begin_review_record_book(rb["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )

        res = api.approve_record_book(rb["id"], make_volunteer_headers(pending_vol["id"]))
        validate_error(res, "ERR_SCREENING_NOT_CLEARED")
        after = validate_success(
            api.get_record_book(rb["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert after["status"] == "UNDER_REVIEW"

    def test_denied_volunteer_approve_rejected(self, api):
        """PRD §3.5: "Approval is gated on clearance: the acting volunteer's
        `screening_status` must be CLEARED, otherwise the approval is rejected
        with `ERR_SCREENING_NOT_CLEARED` (HTTP 422)."

        A DENIED volunteer is equally not CLEARED.

        Design: Difficulty/cross_entity_state_dependency/record_book_approve_requires_volunteer_cleared
        """
        ctx = setup_club_with_volunteers()
        denied_vol = create_denied_volunteer(ctx["club"]["id"], base_clearance=50, risk_flags=0, years_service=3)
        member, project = setup_active_member_with_project(ctx)
        rb = create_draft_record_book_with_entry(project["id"], member["id"])
        submit_book(rb, member["id"], scores=TEST_DEFAULTS["SCORES_70"])
        validate_success(
            api.begin_review_record_book(rb["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )

        res = api.approve_record_book(rb["id"], make_volunteer_headers(denied_vol["id"]))
        validate_error(res, "ERR_SCREENING_NOT_CLEARED")


class TestApproveRecomputesPosture:
    def test_approve_flips_non_livestock_member_to_eligible(self, api):
        """PRD §3.5: "Approval computes the `final_score`, recomputes the owning
        member's `eligibility_posture`, and — because an APPROVED book is the
        precondition for project completion — it is the hinge on which the rest
        of the season swings." PRD §3.7: "The posture is ELIGIBLE when the
        attendance percentage is at least 75 and both documentary conditions
        hold."

        1 PRESENT of 1 (100%) + approved book + no livestock projects -> the
        approve cascade flips the member to ELIGIBLE.

        Design: Difficulty/transitive_cascade/record_book_approve_recomputes_posture
        """
        setup = setup_eligible_member()
        member = validate_success(
            api.get_member(
                setup["member"]["id"], make_volunteer_headers(setup["ctx"]["vol1"]["id"])
            ),
            200,
        )
        assert member["eligibility_posture"] == "ELIGIBLE", (
            f"attendance 100% + approved book + no livestock duty must be ELIGIBLE, "
            f"got {member['eligibility_posture']}"
        )

    def test_approve_yields_conditional_when_livestock_tag_unverified(self, api):
        """PRD §3.7: "It is CONDITIONAL when the attendance percentage is at
        least 75 and exactly one of the two documentary conditions holds — an
        approved record book without the required verified tags, or verified
        tags without an approved record book."

        BEEF project whose tag stays TAGGED (never verified): approval lands the
        approved-book leg only, so the recomputed posture is CONDITIONAL.

        Design: Difficulty/transitive_cascade/record_book_approve_recomputes_posture
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx, project_type="BEEF")
        record_attendance_and_hold(ctx, member["id"], ["PRESENT"])
        tag_animal(project["id"], member["id"], "BEEF", "2026-06-01T00:00:00Z")
        build_approved_record_book(ctx, member, project)

        member_after = validate_success(
            api.get_member(member["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert member_after["eligibility_posture"] == "CONDITIONAL", (
            f"approved book without the required verified tag must be CONDITIONAL, "
            f"got {member_after['eligibility_posture']}"
        )


class TestRecordBookRbac:
    def test_member_cannot_approve_record_book(self, api):
        """PRD §4: "`/api/record-books/{id}/approve` | Approve a record book;
        computes the final score | Volunteer". PRD §2.1: "A request whose role
        is recognized but is not permitted to invoke the target endpoint is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/member_cannot_approve_record_book
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx)
        rb = create_draft_record_book_with_entry(project["id"], member["id"], amount_cents=100)
        submit_book(rb, member["id"], scores=TEST_DEFAULTS["SCORES_70"])
        validate_success(
            api.begin_review_record_book(rb["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )

        res = api.approve_record_book(rb["id"], make_member_headers(member["id"]))
        validate_error(res, "ERR_UNAUTHORIZED")


class TestRecordBookOcc:
    def test_submit_with_stale_version_rejected(self, api):
        """PRD §2.7: "Submitting a record book requires the client to send
        `expected_record_book_version`, carrying the record book's `version` as
        the client last observed it. If the book's current version has advanced
        since that observation — because another writer resubmitted the book or
        a review action moved it — the submission is rejected with
        `ERR_STALE_VERSION` (HTTP 412) rather than silently building on a state
        the client never saw."

        The version captured at creation is advanced by submit, begin-review,
        and return; the resubmission carrying the stale capture is rejected.

        Design: Corner/cross_cutting_complexity_layers/record_book_submit_stale_version_rejected
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx)
        rb = create_draft_record_book_with_entry(project["id"], member["id"], amount_cents=100)
        stale_version = rb["version"]
        submit_book(rb, member["id"], scores=TEST_DEFAULTS["SCORES_70"])
        vol_headers = make_volunteer_headers(ctx["vol1"]["id"])
        validate_success(api.begin_review_record_book(rb["id"], vol_headers), 200)
        returned = validate_success(api.return_record_book(rb["id"], vol_headers), 200)
        assert returned["version"] != stale_version

        res = api.submit_record_book(
            rb["id"],
            submit_record_book_payload(stale_version, **TEST_DEFAULTS["SCORES_90"]),
            make_member_headers(member["id"]),
        )
        validate_error(res, "ERR_STALE_VERSION")
