"""Abstract report drafting, review slots, approval, and revision loop (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    approve_report,
    create_report_payload,
    drive_order_to_search_complete,
    drive_report_under_review,
    get_order,
    get_success_data,
    make_abstracter_headers,
    make_examiner_headers,
    make_ops_headers,
    open_report,
    start_review,
    submit_report,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestReportOpening:
    def test_second_active_report_rejected(self, api):
        """PRD §3.7: "the guard enforces three conditions — the order must actually
        be in `SEARCH_COMPLETE` (else `ERR_INVALID_STATE`), no other report for the
        order may currently occupy any of `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`,
        `REVISION_REQUIRED`, or `APPROVED` (else `ERR_REPORT_ALREADY_ACTIVE`,
        HTTP 409), and the supplied version must match the order's current
        `version` (else `ERR_STALE_VERSION`, HTTP 412, per §2.8)."
        Note: with a first report already DRAFT the order is necessarily out of
        SEARCH_COMPLETE, so the rejection is either the active-report rule or the
        state rule; both are 409 rejections of the second create.

        Design: Corner/validations/second_active_report_rejected
        """
        ctx = drive_order_to_search_complete("client_828", "abs_828", "ex_828")
        first = open_report(ctx["order"]["id"], "abs_828", title="Report 828-A")
        assert first["status"] == "DRAFT"

        fresh_version = get_order(ctx["order"]["id"])["version"]
        second = api.create_abstract_report(
            create_report_payload(
                ctx["order"]["id"],
                expected_abstract_order_version=fresh_version,
                title="Report 828-B",
            ),
            make_abstracter_headers("abs_828"),
        )
        assert second.status_code == 409, (
            f"second active report must be rejected with 409, got {second.status_code}"
        )
        validate_error_is_one_of(
            second, [ApiErrorId.ERR_REPORT_ALREADY_ACTIVE, ApiErrorId.ERR_INVALID_STATE]
        )

    def test_occ_stale_report_create_rejected(self, api):
        """PRD §2.8: "Opening the abstract report for an order likewise requires
        `expected_abstract_order_version`. In both cases, if the order's current
        `version` on the server has advanced past the supplied value — because
        another writer patched the scope, a cascade bumped the version, or any
        other mutation intervened — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412); the client must re-read the order and retry
        against the version it actually observes."

        Design: Corner/cross_cutting_layers/occ_stale_report_create_rejected
        """
        ctx = drive_order_to_search_complete("client_872", "abs_872", "ex_872")
        stale_version = ctx["order_at_creation"]["version"]  # creation-time version

        stale = api.create_abstract_report(
            create_report_payload(
                ctx["order"]["id"],
                expected_abstract_order_version=stale_version,
                title="Report 872 stale attempt",
            ),
            make_abstracter_headers("abs_872"),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_order(ctx["order"]["id"])["version"]
        assert fresh_version != stale_version, (
            "search-phase cascades must have advanced the order version"
        )
        retry = api.create_abstract_report(
            create_report_payload(
                ctx["order"]["id"],
                expected_abstract_order_version=fresh_version,
                title="Report 872",
            ),
            make_abstracter_headers("abs_872"),
        )
        report = validate_success(retry, 201)
        assert report["status"] == "DRAFT"


class TestReviewSlots:
    def test_start_review_inverted_slot_rejected(self, api):
        """PRD §3.7: "The slot must be strictly ordered — an end not later than the
        start yields `ERR_SLOT_INVALID` (HTTP 422) — and it must respect the
        examiner's buffered calendar: against every other non-`CANCELLED` report
        slot booked to the same examiner, the gap between the new slot and each
        existing slot must be at least thirty minutes on both sides, with a gap of
        exactly thirty minutes permitted; any tighter packing is rejected with
        `ERR_SLOT_CONFLICT` (HTTP 409)."
        PRD §3.7: "A fresh report's `revision_number` starts at 0;
        `revision_reason`, `reviewer_examiner_ref`, `review_slot_start`, and
        `review_slot_end` all begin null."

        Design: Corner/validations/start_review_inverted_slot_rejected
        """
        ctx = drive_order_to_search_complete("client_892", "abs_892", "ex_892")
        report = open_report(ctx["order"]["id"], "abs_892", title="Report 892")
        submit_report(report["id"], "abs_892")

        resp = api.start_report_review(
            report["id"],
            {
                "review_slot_start": "2026-08-02T11:00:00Z",
                "review_slot_end": "2026-08-02T10:00:00Z",
            },
            make_examiner_headers("ex_892"),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_INVALID)

        after = get_success_data(api.get_abstract_report(report["id"], make_ops_headers()))
        assert after["status"] == "SUBMITTED"
        assert after["reviewer_examiner_ref"] is None

    def test_review_slot_with_sub_thirty_minute_gap_rejected(self, api):
        """PRD §3.7: "against every other non-`CANCELLED` report slot booked to the
        same examiner, the gap between the new slot and each existing slot must be
        at least thirty minutes on both sides, with a gap of exactly thirty minutes
        permitted; any tighter packing is rejected with `ERR_SLOT_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/examiner_review_slot_thirty_minute_buffer
        """
        first = drive_report_under_review(
            "client_772", "abs_772a", "ex_772",
            review_slot_start="2026-08-02T10:00:00Z",
            review_slot_end="2026-08-02T11:00:00Z",
        )
        assert first["report"]["status"] == "UNDER_REVIEW"

        second = drive_order_to_search_complete("client_772", "abs_772b", "ex_772")
        report2 = open_report(second["order"]["id"], "abs_772b", title="Report 772-2")
        submit_report(report2["id"], "abs_772b")

        tight = api.start_report_review(
            report2["id"],
            {
                "review_slot_start": "2026-08-02T11:15:00Z",
                "review_slot_end": "2026-08-02T12:00:00Z",
            },
            make_examiner_headers("ex_772"),
        )
        validate_error(tight, ApiErrorId.ERR_SLOT_CONFLICT)

    def test_review_slot_with_exact_thirty_minute_gap_accepted(self, api):
        """PRD §3.7: "against every other non-`CANCELLED` report slot booked to the
        same examiner, the gap between the new slot and each existing slot must be
        at least thirty minutes on both sides, with a gap of exactly thirty minutes
        permitted; any tighter packing is rejected with `ERR_SLOT_CONFLICT`
        (HTTP 409). Booking records `reviewer_examiner_ref` as the acting
        examiner's `X-User-ID` along with both slot endpoints, and moves the report
        from `SUBMITTED` to `UNDER_REVIEW`."

        Design: Difficulty/resource_temporal_overlap/examiner_review_slot_thirty_minute_buffer
        """
        drive_report_under_review(
            "client_772", "abs_772a", "ex_772",
            review_slot_start="2026-08-02T10:00:00Z",
            review_slot_end="2026-08-02T11:00:00Z",
        )
        second = drive_order_to_search_complete("client_772", "abs_772b", "ex_772")
        report2 = open_report(second["order"]["id"], "abs_772b", title="Report 772-2")
        submit_report(report2["id"], "abs_772b")

        booked = start_review(
            report2["id"], "ex_772",
            review_slot_start="2026-08-02T11:30:00Z",
            review_slot_end="2026-08-02T12:00:00Z",
        )
        assert booked["status"] == "UNDER_REVIEW"
        assert booked["review_slot_start"] == "2026-08-02T11:30:00Z"
        assert booked["review_slot_end"] == "2026-08-02T12:00:00Z"
        assert booked["reviewer_examiner_ref"] == "ex_772"


class TestRevisionLoop:
    def test_require_revision_returns_report_to_drafting_and_counts_revision(self, api):
        """PRD §3.7: "Requiring revision — moving the report from `UNDER_REVIEW` to
        `REVISION_REQUIRED` — likewise requires the booked reviewer, takes a
        mandatory `reason`, increments `revision_number` by one, records
        `revision_reason` from that reason, returns the order from
        `REPORT_UNDER_REVIEW` to `REPORT_DRAFTING`, and increments the order's
        `version`; the abstracter may then re-submit, and the loop repeats."

        Design: Difficulty/non_linear_state_machine/report_review_revision_cycle
        """
        ctx = drive_report_under_review("client_722", "abs_722", "ex_722")
        resp = api.require_report_revision(
            ctx["report"]["id"],
            {"reason": "exception list incomplete"},
            make_examiner_headers("ex_722"),
        )
        revised = validate_success(resp, 200)
        assert revised["status"] == "REVISION_REQUIRED"
        assert revised["revision_number"] == 1
        assert revised["revision_reason"] == "exception list incomplete"

        order = get_order(ctx["order"]["id"])
        assert order["status"] == "REPORT_DRAFTING", (
            "order mirrors the report loop backward to REPORT_DRAFTING"
        )

    def test_revised_report_rebooks_slot_and_approves_to_ready_for_delivery(self, api):
        """PRD §3.7: "The abstracter submits the draft — or a revised draft —
        moving the report from `DRAFT` (or `REVISION_REQUIRED`) to `SUBMITTED`;
        submission requires the parent order to be in `REPORT_DRAFTING` (else
        `ERR_INVALID_STATE`), and it moves the order from `REPORT_DRAFTING` to
        `REPORT_UNDER_REVIEW`, incrementing the order's `version`."
        PRD §3.7: "Approval — moving the report from `UNDER_REVIEW` to `APPROVED`
        — requires that the caller be the booked `reviewer_examiner_ref` (else
        `ERR_FORBIDDEN`) and that no curative requirement on the order remains
        `OPEN` (else `ERR_OPEN_CURATIVE_REQUIREMENTS`, HTTP 409); approval moves
        the order from `REPORT_UNDER_REVIEW` to `READY_FOR_DELIVERY` and increments
        the order's `version`."

        Design: Difficulty/non_linear_state_machine/report_review_revision_cycle
        """
        ctx = drive_report_under_review("client_722", "abs_722", "ex_722")
        api.require_report_revision(
            ctx["report"]["id"],
            {"reason": "exception list incomplete"},
            make_examiner_headers("ex_722"),
        )

        resubmitted = submit_report(ctx["report"]["id"], "abs_722")
        assert resubmitted["status"] == "SUBMITTED"

        rebooked = start_review(
            ctx["report"]["id"], "ex_722",
            review_slot_start="2026-08-02T11:30:00Z",
            review_slot_end="2026-08-02T12:00:00Z",
        )
        assert rebooked["status"] == "UNDER_REVIEW", (
            "rebooking a second slot with exactly thirty-minute gap is legal"
        )

        approved = approve_report(ctx["report"]["id"], "ex_722")
        assert approved["status"] == "APPROVED"
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "READY_FOR_DELIVERY"


class TestApprovalAuthority:
    def test_abstracter_cannot_approve_report(self, api):
        """PRD §2.1: "an `Examiner` may approve or require revision only on a
        report whose `reviewer_examiner_ref` matches, and may never waive a
        requirement they themselves raised."
        PRD §2.1: "A request whose role is not permitted on the target endpoint —
        or whose `X-User-ID` fails an attribute-ownership rule — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/abstracter_cannot_approve_report
        """
        ctx = drive_report_under_review("client_862", "abs_862", "ex_862")
        resp = api.approve_abstract_report(
            ctx["report"]["id"], make_abstracter_headers("abs_862")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = get_success_data(
            api.get_abstract_report(ctx["report"]["id"], make_ops_headers())
        )
        assert after["status"] == "UNDER_REVIEW", "rejected approval leaves no side effects"
