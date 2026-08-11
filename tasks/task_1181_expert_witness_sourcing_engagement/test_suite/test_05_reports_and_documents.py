"""Reports (deadline pinning, revision cycle, disclosure gate) and privilege-gated documents."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_report, assert_document_production, ApiErrorId,
    create_report, submit_report, finalize_report,
    create_document, deliver_document, fund_retainer,
    setup_scenario, setup_active_engagement, set_clock,
    TEST_USERS, make_expert_headers, make_case_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["case_manager_headers"]


class TestReportCreation:

    def test_report_initial_state_and_pinned_deadline(self, api):
        """PRD §3.5: "The report pins its own `deadline_at` as a copy of the case's
        `report_deadline` taken at creation — version-pinned, so later edits to the case do
        not move an open report's deadline."
        PRD §3.5: "A successful submission stamps `submitted_at` with the current clock
        time; until the first submission the field is null."

        Design: Corner/state_machines/report_initial_state_and_pinned_deadline
        """
        sc = setup_active_engagement()
        report = create_report(sc["engagement"]["id"], title="Initial")
        assert_report(report)
        assert report["status"] == "DRAFT"
        from datetime import datetime, timezone
        pinned = datetime.fromisoformat(report["deadline_at"].replace("Z", "+00:00"))
        assert pinned == datetime(2026, 7, 1, 17, 0, 0, tzinfo=timezone.utc), (
            "deadline_at is pinned from the case's report_deadline at creation")
        assert report["revision_count"] == 0
        assert report["submitted_at"] is None

    def test_second_report_rejected_while_first_non_terminal(self, api):
        """PRD §3.5: "Each engagement supports at most one non-terminal report at a time:
        while any report on the engagement sits in `DRAFT`, `IN_REVIEW`,
        `REVISION_REQUESTED`, or `FINALIZED`, opening another is rejected with
        `ERR_REPORT_ALREADY_ACTIVE`."

        Design: Corner/endpoints/report_already_active_rejected
        """
        sc = setup_active_engagement()
        first = create_report(sc["engagement"]["id"], title="First")
        assert first["status"] == "DRAFT"

        res = api.create_report(sc["engagement"]["id"],
                                {"title": "Second", "report_type": "DAMAGES"}, CM)
        validate_error(res, ApiErrorId.ERR_REPORT_ALREADY_ACTIVE)

    def test_second_submit_rejected(self, api):
        """PRD §3.5: "Submission belongs to the engaged expert and moves the report
        `DRAFT` → `IN_REVIEW`."
        PRD §2.11: "then the target entity's state preconditions for the requested
        transition are checked, with violations yielding `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/report_second_submit_rejected
        """
        sc = setup_active_engagement()
        report = create_report(sc["engagement"]["id"])
        submitted = submit_report(report["id"], sc["expert"]["id"])
        assert submitted["status"] == "IN_REVIEW"

        res = api.submit_report(report["id"], make_expert_headers(sc["expert"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestReportDeadlineBoundary:

    def test_submit_exactly_at_deadline_passes(self, api):
        """PRD §3.5: "Submission is permitted only while the engagement is `ACTIVE` and the
        logical clock reads at or before the pinned `deadline_at` — a submission landing
        exactly at the deadline passes, while a strictly later one fails with
        `ERR_REPORT_DEADLINE_PASSED`."

        Design: Difficulty/boundary_precision_check/report_submit_at_exact_deadline
        """
        sc = setup_active_engagement()
        report = create_report(sc["engagement"]["id"])
        set_clock("2026-07-01T17:00:00Z")  # exactly the pinned deadline

        submitted = validate_success(
            api.submit_report(report["id"], make_expert_headers(sc["expert"]["id"])), 200)
        assert submitted["status"] == "IN_REVIEW", "now == deadline_at passes (<= semantics)"

    def test_submit_one_second_after_deadline_fails(self, api):
        """PRD §3.5: "Submission is permitted only while the engagement is `ACTIVE` and the
        logical clock reads at or before the pinned `deadline_at` — a submission landing
        exactly at the deadline passes, while a strictly later one fails with
        `ERR_REPORT_DEADLINE_PASSED`."

        Design: Difficulty/boundary_precision_check/report_submit_at_exact_deadline
        """
        sc = setup_active_engagement()
        report = create_report(sc["engagement"]["id"])
        set_clock("2026-07-01T17:00:01Z")  # one second past the pinned deadline

        res = api.submit_report(report["id"], make_expert_headers(sc["expert"]["id"]))
        validate_error(res, ApiErrorId.ERR_REPORT_DEADLINE_PASSED)


class TestReportRevisionCycle:

    def _setup_in_review(self, api):
        sc = setup_active_engagement()
        report = create_report(sc["engagement"]["id"], title="Liability report")
        report = submit_report(report["id"], sc["expert"]["id"])
        return sc, report

    def test_full_revision_loop_finalizes_with_count_one(self, api):
        """PRD §3.5: "A `decision` of `REQUEST_REVISION` moves the report `IN_REVIEW` →
        `REVISION_REQUESTED`; a `decision` of `FINALIZE` moves it `IN_REVIEW` →
        `FINALIZED`. The expert answers a revision request by returning a revised draft —
        `REVISION_REQUESTED` → `DRAFT` — carrying `revision_notes`, which increments
        `revision_count` by one".

        Design: Difficulty/non_linear_state_machine/report_revision_cycle
        """
        sc, report = self._setup_in_review(api)
        eid = sc["expert"]["id"]

        validate_success(api.review_report(report["id"],
                                           {"decision": "REQUEST_REVISION", "notes": "fix methods"}, CM), 200)
        validate_success(api.revise_report(report["id"],
                                           {"revision_notes": "methods fixed"},
                                           make_expert_headers(eid)), 200)
        validate_success(api.submit_report(report["id"], make_expert_headers(eid)), 200)
        finalized = validate_success(api.review_report(report["id"], {"decision": "FINALIZE"}, CM), 200)

        assert finalized["status"] == "FINALIZED"
        assert finalized["revision_count"] == 1, "exactly one REVISION_REQUESTED → DRAFT loop ran"
        assert finalized["submitted_at"] is not None

    def test_revision_loop_intermediate_states(self, api):
        """PRD §3.5: "A `decision` of `REQUEST_REVISION` moves the report `IN_REVIEW` →
        `REVISION_REQUESTED`" and "The expert answers a revision request by returning a
        revised draft — `REVISION_REQUESTED` → `DRAFT` — carrying `revision_notes`, which
        increments `revision_count` by one and reopens the submission gate, deadline check
        included, for the next attempt."

        Design: Difficulty/non_linear_state_machine/report_revision_cycle
        """
        sc, report = self._setup_in_review(api)
        eid = sc["expert"]["id"]

        revision_requested = validate_success(api.review_report(
            report["id"], {"decision": "REQUEST_REVISION", "notes": "fix methods"}, CM), 200)
        assert revision_requested["status"] == "REVISION_REQUESTED"
        assert revision_requested["revision_count"] == 0

        back_to_draft = validate_success(api.revise_report(
            report["id"], {"revision_notes": "methods fixed"}, make_expert_headers(eid)), 200)
        assert back_to_draft["status"] == "DRAFT"
        assert back_to_draft["revision_count"] == 1

        resubmitted = validate_success(api.submit_report(report["id"], make_expert_headers(eid)), 200)
        assert resubmitted["status"] == "IN_REVIEW", "revision reopens the submission gate"


class TestDisclosureGate:

    def test_disclose_after_trial_date_rejected(self, api):
        """PRD §3.5: "A `CaseManager` discloses a `FINALIZED` report — `FINALIZED` →
        `DISCLOSED` — only while the logical clock reads strictly before the case's
        `trial_date`; disclosure at or after the trial date fails with
        `ERR_TRIAL_DATE_PASSED`."

        Design: Corner/endpoints/disclose_after_trial_date_rejected
        """
        sc = setup_active_engagement()
        report = create_report(sc["engagement"]["id"])
        submit_report(report["id"], sc["expert"]["id"])
        finalize_report(report["id"])

        set_clock("2026-09-02T00:00:00Z")  # after trial_date 2026-09-01
        res = api.disclose_report(report["id"], CM)
        validate_error(res, ApiErrorId.ERR_TRIAL_DATE_PASSED)


class TestPrivilegeGate:
    """Document delivery gated by the engagement's posture."""

    def _setup_signed_with_documents(self, api):
        """SIGNED engagement (retainer 10000 not yet funded) with one DISCOVERABLE and one
        PRIVILEGED production registered."""
        sc = setup_scenario(target_state="SIGNED", fund=False,
                            engagement_overrides={"retainer_cents": 10_000})
        gid = sc["engagement"]["id"]
        discoverable = create_document(gid, privilege_tier="DISCOVERABLE",
                                       title="Public filing", content_ref="s3://b/d1")
        privileged = create_document(gid, privilege_tier="PRIVILEGED",
                                     title="Counsel strategy memo", content_ref="s3://b/d2")
        return sc, discoverable, privileged

    def test_deliver_gating_at_signed_state(self, api):
        """PRD §3.4: "a `DISCOVERABLE` production may be delivered once the engagement is
        `SIGNED` or `ACTIVE`; a `WORK_PRODUCT` production requires the engagement to be
        `ACTIVE`; and a `PRIVILEGED` production requires the engagement to be `ACTIVE` with
        `nda_executed` true. A delivery that violates its tier gate is rejected with
        `ERR_PRIVILEGE_TIER_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/document_deliver_requires_engagement_active
        """
        sc, discoverable, privileged = self._setup_signed_with_documents(api)
        assert sc["engagement"]["status"] == "SIGNED"
        assert sc["engagement"]["nda_executed"] is True

        delivered = validate_success(api.advance_document_production(
            discoverable["id"], {"action": "DELIVER"}, CM), 200)
        assert delivered["status"] == "DELIVERED", "DISCOVERABLE is allowed at SIGNED"

        res = api.advance_document_production(privileged["id"], {"action": "DELIVER"}, CM)
        validate_error(res, ApiErrorId.ERR_PRIVILEGE_TIER_BLOCKED)

    def test_privileged_deliver_succeeds_once_active(self, api):
        """PRD §3.4: "a `PRIVILEGED` production requires the engagement to be `ACTIVE` with
        `nda_executed` true."
        PRD §3.3: "a payment that brings the funded total to exactly `retainer_cents`
        completes funding and moves the engagement `SIGNED` → `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/document_deliver_requires_engagement_active
        """
        sc, discoverable, privileged = self._setup_signed_with_documents(api)
        gid = sc["engagement"]["id"]

        res = api.advance_document_production(privileged["id"], {"action": "DELIVER"}, CM)
        validate_error(res, ApiErrorId.ERR_PRIVILEGE_TIER_BLOCKED)

        funded = fund_retainer(gid, 10_000)
        assert funded["status"] == "ACTIVE"

        delivered = validate_success(api.advance_document_production(
            privileged["id"], {"action": "DELIVER"}, CM), 200)
        assert_document_production(delivered)
        assert delivered["status"] == "DELIVERED"
