"""Content production, review cycles, disclosure compliance, termination
cascades (PRD §3.4, §3.5, §3.6, §3.9)."""
import pytest

from test_helpers import (
    BM_USER_ID,
    CO_USER_ID,
    TEST_USERS,
    ApiErrorId,
    assert_deliverable,
    assert_disclosure_check,
    approve_deliverable,
    disclosure_fail_payload,
    disclosure_pass_checklist,
    get_deal,
    get_deliverable,
    get_queued_check_id,
    make_active_deal,
    make_creator_headers,
    make_officer_headers,
    pass_disclosure_check,
    plan_deliverable,
    publish_deliverable,
    publish_flow,
    set_clock,
    submit_deliverable,
    validate_error,
    validate_success,
    verify_flow,
)

TM = TEST_USERS["talent_manager_headers"]
BM = TEST_USERS["brand_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestRevisionCycle:
    def test_revision_loop_lands_approved_with_one_round(self, api):
        """PRD §3.5: "Requesting a revision, with an optional `note`, moves
        `IN_REVIEW` → `REVISION_REQUESTED` and increments
        `revision_rounds_used`"
        PRD §3.5: "Approving moves `IN_REVIEW` → `APPROVED` and stamps the
        deliverable's `reviewed_by_user_id` with the acting operator's
        `X-User-ID`"

        IN_REVIEW -> REVISION_REQUESTED -> (resubmit) -> IN_REVIEW ->
        APPROVED, with revision_rounds_used incremented exactly once.

        Design: Difficulty/non_linear_state_machine/deliverable_revision_cycle
        """
        ns = make_active_deal()
        dl = plan_deliverable(ns.deal_id)
        submit_deliverable(dl["id"], ns.creator["id"])
        validate_success(api.review_deliverable(
            dl["id"], {"action": "REQUEST_REVISION", "note": "fix intro"}, BM))
        submit_deliverable(dl["id"], ns.creator["id"])
        approved = approve_deliverable(dl["id"])
        assert approved["status"] == "APPROVED"
        assert approved["revision_rounds_used"] == 1, (
            "the loop increments revision_rounds_used exactly once"
        )
        assert approved["reviewed_by_user_id"] == BM_USER_ID

    def test_revision_requested_accepts_resubmission(self, api):
        """PRD §3.5: "Submission belongs to the deal's creator and moves the
        deliverable from `PENDING_SUBMISSION` — or, after a change request,
        from `REVISION_REQUESTED` — into `IN_REVIEW`; the deal must still be
        `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/deliverable_revision_cycle
        """
        ns = make_active_deal()
        dl = plan_deliverable(ns.deal_id)
        submit_deliverable(dl["id"], ns.creator["id"])
        revision = validate_success(api.review_deliverable(
            dl["id"], {"action": "REQUEST_REVISION", "note": "fix intro"}, BM))
        assert revision["status"] == "REVISION_REQUESTED"
        assert revision["revision_rounds_used"] == 1

        resubmitted = submit_deliverable(dl["id"], ns.creator["id"])
        assert resubmitted["status"] == "IN_REVIEW", (
            "resubmission from REVISION_REQUESTED re-enters IN_REVIEW"
        )
        assert resubmitted["revision_rounds_used"] == 1, (
            "resubmission does not consume another round"
        )


class TestPublishGap:
    def test_sibling_publish_24h_gap_rejected(self, api):
        """PRD §3.5: "the new deliverable's `scheduled_publish_date` must sit
        at least 48 hours away from the `scheduled_publish_date` of every
        sibling deliverable on the same deal, else
        `ERR_PUBLISH_GAP_VIOLATION`"

        A second deliverable scheduled +24h after the first violates the
        48-hour buffer.

        Design: Difficulty/resource_temporal_overlap/deliverable_publish_min_gap
        """
        ns = make_active_deal(brief_overrides={"deliverables_per_slot": 3})
        plan_deliverable(ns.deal_id,
                         scheduled_publish_date="2026-08-20T10:00:00Z")
        res = api.create_deliverable(
            ns.deal_id,
            {"platform": "TIKTOK", "due_date": "2026-08-26T00:00:00Z",
             "scheduled_publish_date": "2026-08-21T10:00:00Z"},
            BM,
        )
        validate_error(res, ApiErrorId.ERR_PUBLISH_GAP_VIOLATION, 409)

    def test_sibling_publish_exactly_48h_gap_allowed(self, api):
        """PRD §3.5: "the new deliverable's `scheduled_publish_date` must sit
        at least 48 hours away from the `scheduled_publish_date` of every
        sibling deliverable on the same deal, else
        `ERR_PUBLISH_GAP_VIOLATION`"
        PRD §3.5: "A planned deliverable opens in `PENDING_SUBMISSION` with
        `revision_rounds_used` and `reshoot_count` at zero."

        Exactly +48h meets "at least 48 hours" — the boundary is inclusive.

        Design: Difficulty/resource_temporal_overlap/deliverable_publish_min_gap
        """
        ns = make_active_deal(brief_overrides={"deliverables_per_slot": 3})
        plan_deliverable(ns.deal_id,
                         scheduled_publish_date="2026-08-20T10:00:00Z")
        second = validate_success(
            api.create_deliverable(
                ns.deal_id,
                {"platform": "TIKTOK", "due_date": "2026-08-27T00:00:00Z",
                 "scheduled_publish_date": "2026-08-22T10:00:00Z"},
                BM,
            ),
            201,
        )
        assert_deliverable(second)
        assert second["status"] == "PENDING_SUBMISSION"


class TestPublishSafetyGate:
    def _setup_approved_then_suspend(self, api, content_window_end):
        ns = make_active_deal(
            brief_overrides={"content_window_end": content_window_end}
        )
        dl = plan_deliverable(ns.deal_id)
        submit_deliverable(dl["id"], ns.creator["id"])
        approve_deliverable(dl["id"])
        validate_success(api.transition_creator(
            ns.creator["id"], {"to_state": "SUSPENDED"}, TM))
        return ns, dl

    def test_publish_suspended_creator_outside_window_safety_wins(self, api):
        """PRD §3.5: "Two further gates fire in §2.8 order: the creator must
        be in good compliance standing — `ACTIVE` with `compliance_strikes`
        below the three-strike limit, else `ERR_CREATOR_COMPLIANCE_SUSPENDED`
        — and the logical clock must read at or after the brief's
        `content_window_start` and at or before its `content_window_end`,
        both bounds inclusive, else `ERR_PUBLISH_WINDOW_VIOLATION`."
        PRD §2.8: "A single request can violate several rules at once, so
        checks fire in a fixed global order and the first failing check
        determines the response."

        SUSPENDED creator AND clock past the content window: the compliance
        gate outranks the temporal gate.

        Design: Difficulty/priority_pair_validation_conflict/publish_suspended_creator_outside_window_safety_wins
        """
        ns, dl = self._setup_approved_then_suspend(api, "2026-08-31T23:59:59Z")
        set_clock("2026-09-05T00:00:00Z")
        res = api.publish_deliverable(
            dl["id"], {"content_url": "https://yt/late"},
            make_creator_headers(ns.creator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CREATOR_COMPLIANCE_SUSPENDED, 422)
        after = get_deliverable(dl["id"])
        assert after["status"] == "APPROVED", "rejected publish leaves state"

    def test_publish_suspended_creator_inside_window(self, api):
        """PRD §3.5: "the creator must be in good compliance standing —
        `ACTIVE` with `compliance_strikes` below the three-strike limit, else
        `ERR_CREATOR_COMPLIANCE_SUSPENDED`"
        PRD §3.1: "a `TalentManager` may also suspend an `ACTIVE` creator
        directly."

        The compliance gate fires on its own when the clock is inside the
        content window.

        Design: Difficulty/priority_pair_validation_conflict/publish_suspended_creator_outside_window_safety_wins
        """
        ns, dl = self._setup_approved_then_suspend(api, "2026-09-30T23:59:59Z")
        res = api.publish_deliverable(
            dl["id"], {"content_url": "https://yt/intime"},
            make_creator_headers(ns.creator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CREATOR_COMPLIANCE_SUSPENDED, 422)
        after = get_deliverable(dl["id"])
        assert after["status"] == "APPROVED"


class TestVerifyGate:
    def test_failed_check_leaves_deliverable_published(self, api):
        """PRD §3.6: "Recording `FAIL` while the check's `recheck_count` is
        below two moves the check to `FAILED`"
        PRD §3.5: "a passed disclosure check moves the deliverable from
        `PUBLISHED` to `VERIFIED`"

        A FAIL does not bubble: the deliverable stays PUBLISHED.

        Design: Difficulty/cross_entity_state_dependency/deliverable_verify_gated_on_disclosure_passed
        """
        ns = make_active_deal()
        dl = plan_deliverable(ns.deal_id)
        pub = publish_flow(ns.deal_id, dl["id"], ns.creator["id"],
                           url="https://yt/5")
        failed = validate_success(api.review_disclosure_check(
            pub.check_id,
            disclosure_fail_payload(has_ad_hashtag=True),
            make_officer_headers(CO_USER_ID),
        ))
        assert failed["status"] == "FAILED"
        deliverable = get_deliverable(dl["id"])
        assert deliverable["status"] == "PUBLISHED", (
            "a FAILED check leaves the deliverable PUBLISHED, not VERIFIED"
        )

    def test_requeue_then_pass_verifies_deliverable(self, api):
        """PRD §3.6: "requeueing returns the check from `FAILED` to `QUEUED`
        and increments `recheck_count`."
        PRD §3.5: "a passed disclosure check moves the deliverable from
        `PUBLISHED` to `VERIFIED`, stamps `verified_at`, drops the creator's
        `pending_disclosure_count` by one, and — when every deliverable of
        the deal is now `VERIFIED` — completes the deal."

        Design: Difficulty/cross_entity_state_dependency/deliverable_verify_gated_on_disclosure_passed
        """
        ns = make_active_deal()
        dl = plan_deliverable(ns.deal_id)
        pub = publish_flow(ns.deal_id, dl["id"], ns.creator["id"],
                           url="https://yt/5")
        validate_success(api.review_disclosure_check(
            pub.check_id,
            disclosure_fail_payload(has_ad_hashtag=True),
            make_officer_headers(CO_USER_ID),
        ))
        requeued = validate_success(api.requeue_disclosure_check(
            pub.check_id, make_creator_headers(ns.creator["id"])))
        assert requeued["status"] == "QUEUED"
        assert requeued["recheck_count"] == 1

        passed = pass_disclosure_check(pub.check_id, CO_USER_ID)
        assert passed["status"] == "PASSED"
        deliverable = get_deliverable(dl["id"])
        assert deliverable["status"] == "VERIFIED"
        deal = get_deal(ns.deal_id)
        assert deal["status"] == "COMPLETED", (
            "the deal's only deliverable verifying completes the deal"
        )


class TestTerminationCascade:
    def test_terminate_cascades_to_disclosure_and_pending_count(self, api):
        """PRD §3.4: "Termination cascades in a pinned order: every
        deliverable not already `VERIFIED` or `CANCELLED` moves to
        `CANCELLED`, leaving verified work untouched; each cancelled
        deliverable voids its disclosure checks sitting in `QUEUED` or
        `FAILED`; each voiding recomputes the creator's
        `pending_disclosure_count`"
        PRD §3.5: "A successful publish ... spawns a disclosure check in
        `QUEUED` for the deliverable, and lifts the creator's
        `pending_disclosure_count` by one."

        Depth-3 chain: Deal -> Deliverable -> DisclosureCheck -> Creator
        pending count.

        Design: Difficulty/transitive_cascade/deal_terminate_cascade_depth3
        """
        ns = make_active_deal(brief_overrides={"deliverables_per_slot": 2})
        d1 = plan_deliverable(ns.deal_id, platform="YOUTUBE",
                              scheduled_publish_date="2026-08-03T10:00:00Z")
        d2 = plan_deliverable(ns.deal_id, platform="TIKTOK",
                              due_date="2026-08-12T00:00:00Z",
                              scheduled_publish_date="2026-08-05T10:00:00Z")
        submit_deliverable(d1["id"], ns.creator["id"])  # D1 IN_REVIEW
        pub = publish_flow(ns.deal_id, d2["id"], ns.creator["id"],
                           url="https://tt/1")
        creator = validate_success(api.get_creator(ns.creator["id"], TM))
        assert creator["pending_disclosure_count"] == 1

        deal = validate_success(api.terminate_deal(
            ns.deal_id, {"reason": "brand pulled budget"}, BM))
        assert deal["status"] == "TERMINATED"
        assert get_deliverable(d1["id"])["status"] == "CANCELLED"
        assert get_deliverable(d2["id"])["status"] == "CANCELLED"
        checks = validate_success(api.list_deliverable_disclosure_checks(
            d2["id"], CO))
        assert checks[0]["status"] == "VOIDED", (
            "the cancelled deliverable's QUEUED check is voided (link 2)"
        )
        creator = validate_success(api.get_creator(ns.creator["id"], TM))
        assert creator["pending_disclosure_count"] == 0, (
            "voiding recomputes the pending count (link 3)"
        )

    def test_terminate_leaves_verified_deliverable_untouched(self, api):
        """PRD §3.4: "every deliverable not already `VERIFIED` or `CANCELLED`
        moves to `CANCELLED`, leaving verified work untouched"
        PRD §3.4: "and the brief's `slots_committed` is recomputed downward
        by one."

        Design: Difficulty/transitive_cascade/deal_terminate_cascade_depth3
        """
        ns = make_active_deal(brief_overrides={"deliverables_per_slot": 3})
        d1 = plan_deliverable(ns.deal_id, platform="YOUTUBE",
                              scheduled_publish_date="2026-08-03T10:00:00Z")
        d2 = plan_deliverable(ns.deal_id, platform="TIKTOK",
                              due_date="2026-08-12T00:00:00Z",
                              scheduled_publish_date="2026-08-05T10:00:00Z")
        d3 = plan_deliverable(ns.deal_id, platform="INSTAGRAM",
                              due_date="2026-08-14T00:00:00Z",
                              scheduled_publish_date="2026-08-07T10:00:00Z")
        verify_flow(ns.deal_id, d1["id"], ns.creator["id"],
                    url="https://yt/verified")
        deal_mid = get_deal(ns.deal_id)
        assert deal_mid["status"] == "ACTIVE", (
            "deal stays ACTIVE while sibling deliverables are unverified"
        )
        submit_deliverable(d2["id"], ns.creator["id"])
        pub = publish_flow(ns.deal_id, d3["id"], ns.creator["id"],
                           url="https://ig/1")

        validate_success(api.terminate_deal(
            ns.deal_id, {"reason": "budget cut"}, BM))
        assert get_deliverable(d1["id"])["status"] == "VERIFIED", (
            "VERIFIED work is untouched by termination"
        )
        assert get_deliverable(d2["id"])["status"] == "CANCELLED"
        assert get_deliverable(d3["id"])["status"] == "CANCELLED"
        checks = validate_success(api.list_deliverable_disclosure_checks(
            d3["id"], CO))
        assert checks[0]["status"] == "VOIDED"
        brief = validate_success(api.get_brief(ns.brief["id"], BM))
        assert brief["slots_committed"] == 0


class TestDealCompletion:
    def test_deal_auto_completes_when_all_deliverables_verified(self, api):
        """PRD §3.4: "A deal in `ACTIVE` completes itself: when the last of
        its deliverables reaches `VERIFIED` — every deliverable of the deal
        verified, with at least one deliverable existing — the deal bubble-up
        transitions to `COMPLETED`."
        PRD §3.5: "a passed disclosure check moves the deliverable from
        `PUBLISHED` to `VERIFIED`, stamps `verified_at`"

        Design: Corner/state_machines/deal_auto_completes_when_all_deliverables_verified
        """
        ns = make_active_deal()
        dl = plan_deliverable(ns.deal_id)
        publish_flow(ns.deal_id, dl["id"], ns.creator["id"],
                     url="https://yt/c1")
        pass_disclosure_check(get_queued_check_id(dl["id"]), CO_USER_ID)
        deliverable = get_deliverable(dl["id"])
        assert deliverable["status"] == "VERIFIED"
        deal = get_deal(ns.deal_id)
        assert deal["status"] == "COMPLETED", (
            "bubble-up completes the deal in the same request"
        )


class TestReshoot:
    def test_reshoot_accept_resets_and_limit_enforced(self, api):
        """PRD §3.9: "Accepting moves the re-shoot to `ACCEPTED`, stamps
        `responded_at`, and resets the deliverable: it returns to
        `PENDING_SUBMISSION` from whichever of `APPROVED`, `PUBLISHED`, or
        `VERIFIED` it occupied, its `content_url`, `published_at`, and
        `verified_at` are cleared, its `reshoot_count` increments by one, its
        disclosure checks in `QUEUED` or `FAILED` are voided, and the
        creator's `pending_disclosure_count` is recomputed."
        PRD §3.9: "is refused with `ERR_RESHOOT_LIMIT_EXCEEDED` once the
        deliverable's `reshoot_count` has reached one."

        Design: Corner/state_machines/reshoot_accept_resets_and_limit_enforced
        """
        ns = make_active_deal(brief_overrides={"deliverables_per_slot": 2})
        dl = plan_deliverable(ns.deal_id, platform="YOUTUBE",
                              scheduled_publish_date="2026-08-03T10:00:00Z")
        # Second deliverable keeps the deal ACTIVE after D1 verifies.
        plan_deliverable(ns.deal_id, platform="TIKTOK",
                         due_date="2026-08-12T00:00:00Z",
                         scheduled_publish_date="2026-08-05T10:00:00Z")
        verify_flow(ns.deal_id, dl["id"], ns.creator["id"],
                    url="https://yt/c3")
        assert get_deal(ns.deal_id)["status"] == "ACTIVE"

        reshoot = validate_success(api.create_reshoot(
            dl["id"], {"reason": "bad lighting"}, BM), 201)
        accepted = validate_success(api.respond_reshoot(
            reshoot["id"], {"action": "ACCEPT"},
            make_creator_headers(ns.creator["id"])))
        assert accepted["status"] == "ACCEPTED"
        reset = get_deliverable(dl["id"])
        assert reset["status"] == "PENDING_SUBMISSION"
        assert reset["reshoot_count"] == 1
        assert reset["content_url"] is None
        assert reset["published_at"] is None
        assert reset["verified_at"] is None

        # Full second production cycle reaches VERIFIED again.
        verify_flow(ns.deal_id, dl["id"], ns.creator["id"],
                    url="https://yt/c3b")
        assert get_deliverable(dl["id"])["status"] == "VERIFIED"

        res = api.create_reshoot(dl["id"], {"reason": "second ask"}, BM)
        validate_error(res, ApiErrorId.ERR_RESHOOT_LIMIT_EXCEEDED, 422)


class TestDisclosureEscalation:
    def test_disclosure_escalation_strike_cascade(self, api):
        """PRD §3.6: "A `FAIL` recorded when `recheck_count` has already
        reached two does not produce another `FAILED` cycle; it moves the
        check to terminal `ESCALATED` and fires the enforcement cascade: the
        creator's `compliance_strikes` increments by one, the creator's
        `pending_disclosure_count` is recomputed downward by one"
        PRD §3.6: "Recording `FAIL` while the check's `recheck_count` is
        below two moves the check to `FAILED`, from which the deal's creator
        — and only the deal's creator — may requeue it after fixing the
        content: requeueing returns the check from `FAILED` to `QUEUED` and
        increments `recheck_count`."

        Design: Corner/state_machines/disclosure_escalation_strike_cascade
        """
        ns = make_active_deal(brief_overrides={"deliverables_per_slot": 2})
        dl = plan_deliverable(ns.deal_id)
        pub = publish_flow(ns.deal_id, dl["id"], ns.creator["id"],
                           url="https://yt/c4")
        check_id = pub.check_id
        creator_headers = make_creator_headers(ns.creator["id"])

        # FAIL at recheck_count 0 -> FAILED; requeue -> 1.
        validate_success(api.review_disclosure_check(
            check_id, disclosure_fail_payload(), make_officer_headers(CO_USER_ID)))
        validate_success(api.requeue_disclosure_check(check_id, creator_headers))
        # FAIL at recheck_count 1 -> FAILED; requeue -> 2.
        validate_success(api.review_disclosure_check(
            check_id,
            disclosure_fail_payload(has_ad_hashtag=True),
            make_officer_headers(CO_USER_ID)))
        validate_success(api.requeue_disclosure_check(check_id, creator_headers))
        # FAIL at recheck_count 2 -> ESCALATED with the strike cascade.
        escalated = validate_success(api.review_disclosure_check(
            check_id,
            disclosure_fail_payload(has_ad_hashtag=True, verbal_disclosure=True),
            make_officer_headers(CO_USER_ID)))
        assert escalated["status"] == "ESCALATED"
        assert escalated["recheck_count"] == 2

        creator = validate_success(api.get_creator(ns.creator["id"], TM))
        assert creator["compliance_strikes"] == 1
        assert creator["pending_disclosure_count"] == 0
        deliverable = get_deliverable(dl["id"])
        assert deliverable["status"] == "PUBLISHED", (
            "escalation is not verification; the deliverable stays PUBLISHED"
        )


class TestDeliverablePlanningLimits:
    def test_deliverable_count_cap_enforced(self, api):
        """PRD §3.5: "the deal may not carry more non-`CANCELLED`
        deliverables than the brief's `deliverables_per_slot` — planning
        beyond that count is rejected with
        `ERR_DELIVERABLE_COUNT_EXCEEDED`."

        Design: Corner/calculations/deliverable_count_cap_enforced
        """
        ns = make_active_deal(brief_overrides={"deliverables_per_slot": 1})
        plan_deliverable(ns.deal_id,
                         scheduled_publish_date="2026-08-03T10:00:00Z")
        res = api.create_deliverable(
            ns.deal_id,
            {"platform": "TIKTOK", "due_date": "2026-08-12T00:00:00Z",
             "scheduled_publish_date": "2026-08-05T10:00:00Z"},
            BM,
        )
        validate_error(res, ApiErrorId.ERR_DELIVERABLE_COUNT_EXCEEDED, 422)

    def test_revision_limit_zero_rejected(self, api):
        """PRD §3.5: "a request made when `revision_rounds_used` has already
        reached the deal's `revision_rounds_included` is rejected with
        `ERR_REVISION_LIMIT_EXCEEDED`."

        With zero included rounds, the very first REQUEST_REVISION fails
        (0 has reached 0).

        Design: Corner/validations/revision_limit_zero_rejected
        """
        ns = make_active_deal(brief_overrides={"revision_rounds_included": 0,
                                               "usage_rights_days": 30})
        dl = plan_deliverable(ns.deal_id)
        submit_deliverable(dl["id"], ns.creator["id"])
        res = api.review_deliverable(
            dl["id"], {"action": "REQUEST_REVISION", "note": "change"}, BM)
        validate_error(res, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED, 422)
        after = get_deliverable(dl["id"])
        assert after["revision_rounds_used"] == 0
        assert after["status"] == "IN_REVIEW"

    def test_publish_outside_content_window_rejected(self, api):
        """PRD §3.5: "the logical clock must read at or after the brief's
        `content_window_start` and at or before its `content_window_end`,
        both bounds inclusive, else `ERR_PUBLISH_WINDOW_VIOLATION`."

        Design: Corner/validations/publish_outside_content_window_rejected
        """
        ns = make_active_deal(
            brief_overrides={
                "submission_window_end": "2026-09-30T23:59:59Z",
                "content_window_end": "2026-08-31T23:59:59Z",
            }
        )
        dl = plan_deliverable(ns.deal_id)
        submit_deliverable(dl["id"], ns.creator["id"])
        approve_deliverable(dl["id"])
        set_clock("2026-09-05T00:00:00Z")
        res = api.publish_deliverable(
            dl["id"], {"content_url": "https://yt/e3"},
            make_creator_headers(ns.creator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PUBLISH_WINDOW_VIOLATION, 422)
        after = get_deliverable(dl["id"])
        assert after["status"] == "APPROVED"


class TestDisclosureSegregation:
    def test_disclosure_review_rejected_same_user_as_approver(self, api):
        """PRD §2.10: "The `ComplianceOfficer` who reviews a deliverable's
        disclosure check must not be the operator recorded as that
        deliverable's `reviewed_by_user_id` — the person who approved the
        content for publication. ... Both violations are rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and both compare the acting
        `X-User-ID` against the recorded actor stamp."
        PRD §3.5: "Approving moves `IN_REVIEW` → `APPROVED` and stamps the
        deliverable's `reviewed_by_user_id` with the acting operator's
        `X-User-ID`"

        Design: Corner/rbac/disclosure_review_rejected_same_user_as_approver
        """
        ns = make_active_deal()
        dl = plan_deliverable(ns.deal_id)
        submit_deliverable(dl["id"], ns.creator["id"])
        approve_deliverable(dl["id"], approver_user_id=BM_USER_ID)
        publish_deliverable(dl["id"], ns.creator["id"], "https://yt/g1")
        check_id = get_queued_check_id(dl["id"])
        res = api.review_disclosure_check(
            check_id,
            disclosure_pass_checklist(),
            make_officer_headers(BM_USER_ID),  # same operator id as approver
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        checks = validate_success(api.list_deliverable_disclosure_checks(
            dl["id"], CO))
        assert checks[0]["status"] == "QUEUED", (
            "the rejected review leaves the check QUEUED"
        )
