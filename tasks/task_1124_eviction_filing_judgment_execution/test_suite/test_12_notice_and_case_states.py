"""Notice/case state-machine corners: cure lockdown, cure window,
unconditional-quit, filing refile cycle, dismissal gate, judgment
uniqueness (PRD 3.2, 3.3, 3.6)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    CLERK_B,
    create_notice_payload,
    get_case,
    get_notice,
    make_landlord_headers,
    prepare_package,
    review_package,
    set_clock,
    setup_case_notice_active,
    setup_case_notice_expired,
    setup_judgment_entered,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import api_client


class TestCuredNoticeTerminalLockdown:
    """Corner instance: a CURED notice accepts no further record-cure."""

    def test_second_cure_rejected(self, api):
        """PRD 2.7 rung 7: "State admissibility — the target entity is in a
        status that permits the operation (... a PENDING notice ...);
        failure yields ERR_INVALID_STATE."

        Design: Corner/state_machines/cured_notice_terminal_lockdown
        """
        ctx = setup_case_notice_active(
            "CA", claimed_rent_owed_cents=150000, served_on="2026-05-02")
        set_clock("2026-05-03T09:00:00Z")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        ok = validate_success(api.record_cure(
            ctx["notice"]["id"], {"paid_amount_cents": 150000}, ll), 200)
        assert ok["status"] == "CURED"

        resp = api.record_cure(
            ctx["notice"]["id"], {"paid_amount_cents": 150000}, ll)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_notice(ctx["notice"]["id"])["status"] == "CURED"


class TestCureAfterDeadlineRejected:
    """Corner instance: past-deadline cure on a still-PENDING notice fails
    with ERR_CURE_WINDOW_CLOSED (temporal gate independent of status)."""

    def test_cure_past_deadline_rejected_status_unchanged(self, api):
        """PRD 3.2: "any cure attempt after the deadline — or on an
        unconditional notice at any time — is rejected with
        ERR_CURE_WINDOW_CLOSED (HTTP 409)" and "Expiry itself is not
        client-driven: the ops-run sweep (§2.5) moves an overdue PENDING
        notice to EXPIRED".

        Design: Corner/state_machines/cure_after_deadline_rejected
        """
        ctx = setup_case_notice_active(
            "CA", claimed_rent_owed_cents=150000, served_on="2026-05-02")
        # CA cure 3 days -> deadline 2026-05-05T23:59:59Z. Move past it
        # WITHOUT an ops run, so the notice remains PENDING.
        set_clock("2026-05-06T00:00:01Z")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.record_cure(
            ctx["notice"]["id"], {"paid_amount_cents": 150000}, ll)
        validate_error(resp, ApiErrorId.ERR_CURE_WINDOW_CLOSED, 409)
        assert get_notice(ctx["notice"]["id"])["status"] == "PENDING"


class TestUnconditionalQuitNeverCurable:
    """Corner instance: UNCONDITIONAL_QUIT rejects any cure attempt."""

    def test_cure_on_unconditional_quit_rejected(self, api):
        """PRD 3.2: "An UNCONDITIONAL_QUIT notice is never curable, and any
        cure attempt after the deadline — or on an unconditional notice at
        any time — is rejected with ERR_CURE_WINDOW_CLOSED (HTTP 409)."

        Design: Corner/state_machines/unconditional_quit_never_curable
        """
        ctx = setup_case_notice_active(
            "CA", case_reason="SEVERE", notice_type="UNCONDITIONAL_QUIT",
            served_on="2026-05-02",
            clock_before_notice="2026-05-02T10:00:00Z",
        )
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.record_cure(
            ctx["notice"]["id"], {"violation_cured": True}, ll)
        validate_error(resp, ApiErrorId.ERR_CURE_WINDOW_CLOSED, 409)


class TestFilingRejectThenRefileCycle:
    """Corner instance: REJECT -> FILING_REJECTED; a fresh paid package can
    then be ACCEPTED, cycling the case to FILED."""

    def test_reject_then_refile_accepted(self, api):
        """PRD 3.3: "A REJECT decision stores the supplied rejection_reason
        on the package, marks it REJECTED, and moves the case to
        FILING_REJECTED; from there the landlord may prepare a fresh package
        and the cycle repeats, with acceptance moving the case to FILED".

        Design: Corner/state_machines/filing_reject_then_refile_cycle
        """
        ctx = setup_case_notice_expired("CA")
        p1 = prepare_package(ctx)
        p1 = review_package(p1, "REJECT", CLERK_A,
                            rejection_reason="wrong caption")
        assert p1["status"] == "REJECTED"
        assert get_case(ctx["case"]["id"])["status"] == "FILING_REJECTED"

        p2 = prepare_package(ctx)
        p2 = review_package(p2, "ACCEPT", CLERK_A)
        assert p2["status"] == "ACCEPTED"
        assert get_case(ctx["case"]["id"])["status"] == "FILED"


class TestDismissAfterJudgmentRejected:
    """Corner instance: dismissal is pre-judgment only."""

    def test_dismiss_in_judgment_entered_rejected(self, api):
        """PRD 3.2: "Once the case has reached JUDGMENT_ENTERED or beyond —
        or is already terminal — dismissal is rejected with
        ERR_INVALID_STATE (HTTP 409)."

        Design: Corner/state_machines/dismiss_after_judgment_rejected
        """
        ctx = setup_judgment_entered(
            "CA", oldest_unpaid_due_date="2026-06-01")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.dismiss_case(ctx["case"]["id"], {"reason": "changed mind"}, ll)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_dismiss_pre_judgment_succeeds(self, api):
        """PRD 3.2: "voluntary dismissal, with an optional reason recorded on
        the case as dismiss_reason, is available while the case is in DRAFT,
        NOTICE_ACTIVE, NOTICE_EXPIRED, FILING_REJECTED, FILED,
        SERVICE_COMPLETE, HEARING_SCHEDULED, ANSWERED, or HEARING_CONCLUDED,
        and moves the case to the terminal DISMISSED status."

        Design: Corner/state_machines/dismiss_after_judgment_rejected
        """
        ctx = setup_case_notice_active("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        case = validate_success(api.dismiss_case(
            ctx["case"]["id"], {"reason": "settled privately"}, ll), 200)
        assert case["status"] == "DISMISSED"
        assert case["dismiss_reason"] == "settled privately"


class TestSecondJudgmentRejected:
    """Corner instance: at most one judgment per case."""

    def test_second_judgment_rejected(self, api):
        """PRD 3.6: "At most one Judgment may ever exist for a case — a
        second attempt is rejected with ERR_JUDGMENT_EXISTS (HTTP 409)."

        Design: Corner/state_machines/second_judgment_rejected

        After the first judgment the case is JUDGMENT_ENTERED, which also
        fails the HEARING_CONCLUDED state gate. PRD 2.7's ladder evaluates
        state admissibility (rung 7, ERR_INVALID_STATE) before the judgment
        uniqueness business constraint (rung 9, ERR_JUDGMENT_EXISTS), while
        3.6 names ERR_JUDGMENT_EXISTS for "a second attempt"; the PRD does
        not state which rung reports this collision, so both 409 outcomes
        are accepted.
        """
        ctx = setup_judgment_entered(
            "CA", oldest_unpaid_due_date="2026-06-01")
        resp = api.enter_judgment(
            ctx["case"]["id"],
            {"possession_granted": True, "rent_awarded_cents": 1,
             "damages_cents": 0, "late_fee_cents": 0, "court_costs_cents": 0,
             "oldest_unpaid_due_date": "2026-06-01"},
            CLERK_B,
        )
        assert resp.status_code == 409
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_JUDGMENT_EXISTS, ApiErrorId.ERR_INVALID_STATE],
        )
