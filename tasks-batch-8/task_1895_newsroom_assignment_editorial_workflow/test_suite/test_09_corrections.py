"""Corrections governance: proposal, approval under segregation of duties,
issuance numbering, the published-story gate, and the retraction cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_staff_to,
    get_success_data,
    ingest_analytics,
    make_managing_editor_headers,
    propose_correction,
    setup_published_story,
    validate_error,
    validate_paginated,
    validate_success,
)

ND = TEST_USERS["news_director_headers"]


def _approved_correction(api, ctx, story_id, severity="MINOR",
                         text="Fix it", proposer_headers=None):
    """Propose (as the reporter by default) and approve (managing editor)."""
    c = propose_correction(proposer_headers or ctx["reporter_headers"],
                           story_id, severity=severity, correction_text=text)
    get_success_data(
        api.approve_correction(c["id"], ctx["managing_editor_headers"]))
    return c


class TestCorrectionApproval:
    def test_correction_double_approve_rejected(self, api):
        """PRD §3.6: "Approval moves a `PROPOSED` correction to `APPROVED` and
        records the approver in `approver_staff_id` — but the approver must
        not be the proposer, per §2.9's segregation rule. Rejection moves it
        to `REJECTED`. Both bump the correction's `version`, and both are
        rejected with `ERR_INVALID_STATE` once the correction has left
        `PROPOSED`."

        Design: Corner/state_machines/correction_double_approve_rejected
        """
        ctx, story, _slot = setup_published_story(with_managing_editor=True)
        c = propose_correction(ctx["reporter_headers"], story["id"],
                               severity="MINOR",
                               correction_text="Name spelling")
        me = ctx["managing_editor_headers"]
        first = api.approve_correction(c["id"], me)
        assert validate_success(first)["status"] == "APPROVED"
        second = api.approve_correction(c["id"], me)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    def test_sod_correction_self_approve(self, api):
        """PRD §2.9: "Three hand-offs forbid self-dealing, each enforced with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). The copy editor who completes
        an edit and advances a story toward fact-check must not be the story's
        author. The reviewer filing a fact-check or legal verdict must not be
        the story's author. And the managing editor who approves a correction
        must not be the staff member who proposed it."

        Design: Corner/rbac/sod_correction_self_approve
        """
        ctx, story, _slot = setup_published_story(with_managing_editor=True)
        me2 = add_staff_to(ctx, "managing_editor_2", "MANAGING_EDITOR",
                           full_name="ME Two SA", home_desk="BUSINESS",
                           hourly_rate_cents=8000)
        me1_h = ctx["managing_editor_headers"]
        c = propose_correction(me1_h, story["id"], severity="MAJOR",
                               correction_text="ME-initiated fix")

        resp = api.approve_correction(c["id"], me1_h)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        ok = api.approve_correction(
            c["id"], make_managing_editor_headers(me2["id"]))
        approved = validate_success(ok)
        assert approved["status"] == "APPROVED"
        assert approved["approver_staff_id"] == me2["id"]


class TestCorrectionNumbering:
    def test_correction_number_sequencing(self, api):
        """PRD §3.6: "Issuance assigns the `correction_number`: the count of
        the story's previously issued corrections plus one, evaluated at the
        instant of issue, so numbers are per-story chronological and gap-free;
        the story `version` bump in the same act serializes concurrent
        issuance."
        PRD §3.6: "The correction's `issued_at` is stamped with the logical
        clock, its `version` increments, and the story's `correction_count`
        rises by one with its own `version` increment."
        PRD §3.6: "The proposal carries a `severity` of `MINOR`, `MAJOR`, or
        `RETRACTION` and the public `correction_text`; the server records the
        proposer in `proposer_staff_id` from `X-User-ID`, the correction's
        `story_id` comes from the path, and it lands in `PROPOSED` status with
        `approver_staff_id`, `correction_number`, and `issued_at` all unset."

        Design: Corner/calculations/correction_number_sequencing
        """
        ctx, story, _slot = setup_published_story(with_managing_editor=True)
        c1 = _approved_correction(api, ctx, story["id"], "MINOR",
                                  "Fix spelling")
        c2 = _approved_correction(api, ctx, story["id"], "MAJOR",
                                  "Fix quote")
        c3 = propose_correction(ctx["reporter_headers"], story["id"],
                                "MINOR", "Fix caption")

        me = ctx["managing_editor_headers"]
        i1 = validate_success(api.issue_correction(c1["id"], me))
        i2 = validate_success(api.issue_correction(c2["id"], me))
        assert i1["correction_number"] == 1
        assert i2["correction_number"] == 2, "issued in chronological order"

        story_after = get_success_data(api.get_story(story["id"], ND))
        assert story_after["correction_count"] == 2
        assert story_after["status"] == "PUBLISHED", \
            "MINOR/MAJOR corrections do not retract"

        corrections, meta = validate_paginated(
            api.get_story_corrections(story["id"], ND))
        assert meta["total_count"] == 3
        assert corrections[2]["id"] == c3["id"]
        assert corrections[2]["correction_number"] is None, \
            "a PROPOSED correction holds no number"


class TestIssueRequiresPublished:
    def _retracted_with_pending_correction(self, api):
        """Published story; c1 RETRACTION and c2 MAJOR both approved while
        PUBLISHED; c1 issued, retracting the story. Returns (ctx, story, c2)."""
        ctx, story, _slot = setup_published_story(with_managing_editor=True)
        c1 = _approved_correction(api, ctx, story["id"], "RETRACTION",
                                  "Withdrawing the story")
        c2 = _approved_correction(api, ctx, story["id"], "MAJOR",
                                  "Fixing the quote")
        me = ctx["managing_editor_headers"]
        get_success_data(api.issue_correction(c1["id"], me))
        return ctx, story, c2

    def test_issue_after_retraction_rejected(self, api):
        """PRD §3.6: "A `ManagingEditor` issues an `APPROVED` correction, and
        the story must still be `PUBLISHED` at that instant — otherwise
        `ERR_STORY_NOT_PUBLISHED`."

        Design: Difficulty/cross_entity_state_dependency/correction_issue_requires_published_story
        """
        ctx, story, c2 = self._retracted_with_pending_correction(api)
        resp = api.issue_correction(c2["id"], ctx["managing_editor_headers"])
        validate_error(resp, ApiErrorId.ERR_STORY_NOT_PUBLISHED)
        story_after = get_success_data(api.get_story(story["id"], ND))
        assert story_after["status"] == "RETRACTED", \
            "the first retraction closed the second correction's window"

    def test_failed_issue_leaves_correction_approved(self, api):
        """PRD §3.6: "A `ManagingEditor` issues an `APPROVED` correction, and
        the story must still be `PUBLISHED` at that instant — otherwise
        `ERR_STORY_NOT_PUBLISHED`."

        Design: Difficulty/cross_entity_state_dependency/correction_issue_requires_published_story
        """
        ctx, story, c2 = self._retracted_with_pending_correction(api)
        resp = api.issue_correction(c2["id"], ctx["managing_editor_headers"])
        validate_error(resp, ApiErrorId.ERR_STORY_NOT_PUBLISHED)
        corrections, _meta = validate_paginated(
            api.get_story_corrections(story["id"], ND))
        c2_after = [c for c in corrections if c["id"] == c2["id"]][0]
        assert c2_after["status"] == "APPROVED", \
            "the failed issue did not transition the correction"


class TestRetractionCascade:
    def _retracted_story_with_analytics(self, api):
        """Published story carrying one ACTIVE SETTLED analytics report; a
        RETRACTION correction proposed by the author and approved by the
        managing editor. Returns (ctx, story, correction)."""
        ctx, story, _slot = setup_published_story(
            with_managing_editor=True, with_analyst=True, urgency="URGENT",
            deadline_at="2026-08-02T00:00:00Z")
        ingest_analytics(ctx, story["id"], variant="SETTLED", views=1000,
                         engagement_minutes=100)
        c = propose_correction(ctx["reporter_headers"], story["id"],
                               severity="RETRACTION",
                               correction_text="Story withdrawn: source fabrication")
        get_success_data(api.approve_correction(
            c["id"], ctx["managing_editor_headers"]))
        return ctx, story, c

    def test_issue_retraction_retracts_story(self, api):
        """PRD §3.6: "Issuing a correction whose `severity` is `RETRACTION`
        triggers a two-hop cascade: first the story moves `PUBLISHED →
        RETRACTED` with its `version` incremented; then every analytics report
        on that story still in `ACTIVE` status is voided, moving to `VOID`
        (§3.7)."
        PRD §3.6: "Issuance assigns the `correction_number`: the count of the
        story's previously issued corrections plus one, evaluated at the
        instant of issue, so numbers are per-story chronological and gap-free;
        the story `version` bump in the same act serializes concurrent
        issuance."

        Design: Difficulty/transitive_cascade/retraction_issue_chain
        """
        ctx, story, c = self._retracted_story_with_analytics(api)
        issued = validate_success(api.issue_correction(
            c["id"], ctx["managing_editor_headers"]))
        assert issued["status"] == "ISSUED"
        assert issued["correction_number"] == 1, \
            "the first issued correction on the story"
        assert issued["issued_at"] is not None

        story_after = get_success_data(api.get_story(story["id"], ND))
        assert story_after["status"] == "RETRACTED", "hop 1"
        assert story_after["correction_count"] == 1

    def test_retraction_voids_active_analytics(self, api):
        """PRD §3.6: "Issuing a correction whose `severity` is `RETRACTION`
        triggers a two-hop cascade: first the story moves `PUBLISHED →
        RETRACTED` with its `version` incremented; then every analytics report
        on that story still in `ACTIVE` status is voided, moving to `VOID`
        (§3.7)."

        Design: Difficulty/transitive_cascade/retraction_issue_chain
        """
        ctx, story, c = self._retracted_story_with_analytics(api)
        get_success_data(api.issue_correction(
            c["id"], ctx["managing_editor_headers"]))
        reports, meta = validate_paginated(
            api.get_story_analytics_reports(story["id"], ND))
        assert meta["total_count"] == 1
        assert reports[0]["status"] == "VOID", \
            "hop 2: the active report is voided because the story retracted"
