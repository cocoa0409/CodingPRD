"""Transitive cascades: withdrawal at depth four and slot release at depth three.

Each link in these chains is caused by the link before it rather than by the
triggering call, so every link is asserted in its own test: a withdrawal walks
disclosure -> draft -> inquiry -> issuer, and a slot release walks request ->
event counters -> waitlist promotion.
"""

from test_helpers import (
    ApiClient,
    BLOCKED_CITED_DISCLOSURE_WITHDRAWN,
    CLASS_GUIDANCE_REPEAT,
    CONTACT_INSTITUTIONAL_HOLDER,
    DISCLOSURE_OFFICER,
    DISCLOSURE_STATUS_WITHDRAWN,
    DRAFT_APPROVED,
    DRAFT_BLOCKED,
    EVENT_LOCKED,
    EVENT_NDR,
    INQUIRY_DRAFTING,
    IR_ADMIN,
    IR_ANALYST,
    METRIC_EPS,
    POSTURE_OPEN,
    QUEUE_IR_DESK,
    REQUEST_ALLOCATED,
    REQUEST_RELEASED,
    REQUEST_WAITLISTED,
    TIER_1,
    TIER_2,
    TOPIC_GUIDANCE,
    assertions,
    fixtures,
    validate_success,
)

# ---------------------------------------------------------------------------
# Local composite setup for the withdrawal cascade
# ---------------------------------------------------------------------------

_WITHDRAWAL_REASON = "Guidance withdrawn pending restatement review."


def _build_withdrawal_world(api: ApiClient):
    """An APPROVED draft citing a PUBLISHED guidance row, ready to be withdrawn.

    The whole chain is built with the clock at 2026-08-10T09:00:00Z — which puts
    the inquiry's first ``sla_due_at`` at 2026-08-13T09:00:00.000Z — and the
    clock is then advanced a day so that the recomputed deadline is visibly
    different from the original one.
    """
    fixtures.set_clock(api, "2026-08-10T09:00:00Z")
    company = fixtures.create_company(
        api,
        ticker="WDR",
        legal_name="Withdrawal Cascade Corp",
        shares_outstanding=1000000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        40000,
        display_name="Cascade Holder",
        email="wdr@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    disclosure = fixtures.create_published_guidance(
        api,
        company["id"],
        fact_key="FY2026-EPS-GUIDANCE",
        metric=METRIC_EPS,
        period_label="FY2026",
        guidance_low=2.00,
        guidance_high=2.20,
    )
    inquiry = fixtures.create_routed_inquiry(
        api,
        company["id"],
        holder["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="Does the FY2026 EPS range still hold?",
        headers=IR_ANALYST,
    )
    draft = fixtures.create_draft(
        api,
        inquiry["id"],
        body_text="Our published FY2026 EPS guidance range is unchanged.",
        disclosure_class=CLASS_GUIDANCE_REPEAT,
        cited_disclosure_id=disclosure["id"],
        headers=IR_ANALYST,
    )
    fixtures.submit_for_review(api, draft["id"], IR_ANALYST)
    draft = fixtures.decide_review(
        api, draft["id"], inquiry["id"], headers=DISCLOSURE_OFFICER
    )
    fixtures.set_clock(api, "2026-08-11T09:00:00Z")
    return {
        "company_id": company["id"],
        "disclosure_id": disclosure["id"],
        "inquiry_id": inquiry["id"],
        "draft_id": draft["id"],
        "published_version": disclosure["version"],
        "draft": draft,
    }


def _withdraw(api: ApiClient, disclosure_id: str):
    return validate_success(
        api.withdraw_disclosure(disclosure_id, _WITHDRAWAL_REASON, DISCLOSURE_OFFICER)
    )


class TestDisclosureWithdrawalCascade:
    """The four links fired by withdrawing a PUBLISHED disclosure."""

    def test_the_withdrawal_blocks_the_approved_draft_that_cites_it(
        self, api: ApiClient
    ):
        """PRD §3.4: "The first link sets `status` to `WITHDRAWN`, stores `withdrawal_reason`, and increments the disclosure's `version`."

        PRD §3.4: "The second link, caused by the first, finds every response draft whose `cited_disclosure_id` points at this disclosure and whose status is `IN_REVIEW` or `APPROVED`, and forces each to `BLOCKED` with `blocked_reason` set to `CITED_DISCLOSURE_WITHDRAWN` and its `version` incremented by 1; the `pinned_disclosure_version` on those drafts is deliberately left untouched, so the audit trail of what was pinned survives the block."

        PRD §3.6: "An approval that clears all of these moves the draft `IN_REVIEW` → `APPROVED` and captures the cited disclosure's current `version` into `pinned_disclosure_version`; when the draft cites nothing, `pinned_disclosure_version` stays null."

        Design: Difficulty/transitive_cascade/disclosure_withdrawal_cascades_to_draft_inquiry_and_company
        """
        world = _build_withdrawal_world(api)
        # The published guidance row is at version 2, and that is what approval
        # pinned onto the draft.
        assert world["published_version"] == 2
        assertions.assert_response_draft(
            world["draft"], status=DRAFT_APPROVED, pinned_disclosure_version=2
        )
        draft_version_before = world["draft"]["version"]

        withdrawn = _withdraw(api, world["disclosure_id"])
        assertions.assert_disclosure(
            withdrawn,
            status=DISCLOSURE_STATUS_WITHDRAWN,
            withdrawal_reason=_WITHDRAWAL_REASON,
            version=3,
        )

        blocked = fixtures.read_draft(api, world["draft_id"])
        assertions.assert_response_draft(
            blocked,
            status=DRAFT_BLOCKED,
            blocked_reason=BLOCKED_CITED_DISCLOSURE_WITHDRAWN,
            pinned_disclosure_version=2,
            version=draft_version_before + 1,
        )

    def test_the_blocked_draft_rewinds_its_inquiry_with_a_fresh_deadline(
        self, api: ApiClient
    ):
        """PRD §3.4: "The third link, caused by the second, takes each draft blocked in the second link whose inquiry ticket sits in `AWAITING_APPROVAL` and rewinds that inquiry `AWAITING_APPROVAL` → `DRAFTING`, recomputing `sla_due_at` from the logical clock and the service-level hours of the inquiry's current `routing_queue`, incrementing the inquiry's `version` by 1."

        PRD §3.5: "Each queue carries its own service-level allowance, and the deadline is the logical clock at the moment of the write plus that allowance: 48 hours for `DISCLOSURE_COMMITTEE`, three days (72 hours) for `IR_DESK`, four days (96 hours) for `TRANSFER_AGENT_DESK` and five days (120 hours) for `SHAREHOLDER_SERVICES`."

        PRD §3.5: "The deadline is recomputed on intake, on routing, and on every cascade link that returns an inquiry to `DRAFTING`."

        Design: Difficulty/transitive_cascade/disclosure_withdrawal_cascades_to_draft_inquiry_and_company
        """
        world = _build_withdrawal_world(api)
        before = fixtures.read_inquiry(api, world["inquiry_id"])
        assertions.assert_inquiry(before, routing_queue=QUEUE_IR_DESK)
        assertions.assert_ts_equals(
            before["sla_due_at"], "2026-08-13T09:00:00.000Z", "sla_due_at"
        )

        _withdraw(api, world["disclosure_id"])

        rewound = fixtures.read_inquiry(api, world["inquiry_id"])
        assertions.assert_inquiry(
            rewound,
            status=INQUIRY_DRAFTING,
            routing_queue=QUEUE_IR_DESK,
            version=before["version"] + 1,
        )
        # 2026-08-11T09:00:00Z plus the IR_DESK allowance of 72 hours.
        assertions.assert_ts_equals(
            rewound["sla_due_at"], "2026-08-14T09:00:00.000Z", "sla_due_at"
        )

    def test_the_rewound_inquiry_refreshes_its_issuer_at_the_fourth_link(
        self, api: ApiClient
    ):
        """PRD §3.4: "The fourth link, caused by the third, takes the issuer of each inquiry touched in the third link and recounts `open_inquiry_count`, re-derives `disclosure_posture`, stamps `posture_recomputed_at` with the logical clock, and increments the issuer's `version` by 1."

        PRD §2.11: "`open_inquiry_count` illustrates the pattern precisely. It is the number of that issuer's inquiry tickets whose status is `NEW`, `ROUTED`, `DRAFTING`, `AWAITING_APPROVAL` or `ESCALATED` — that is, every status except `ANSWERED`."

        PRD §2.7: "Whenever the posture is re-derived, `posture_recomputed_at` is stamped with the logical clock's current instant."

        Design: Difficulty/transitive_cascade/disclosure_withdrawal_cascades_to_draft_inquiry_and_company
        """
        world = _build_withdrawal_world(api)
        before = fixtures.read_company(api, world["company_id"])

        _withdraw(api, world["disclosure_id"])

        after = fixtures.read_company(api, world["company_id"])
        assertions.assert_company(
            after,
            open_inquiry_count=1,
            disclosure_posture=POSTURE_OPEN,
            version=before["version"] + 1,
        )
        assertions.assert_open_inquiry_count(
            after, [fixtures.read_inquiry(api, world["inquiry_id"])]
        )
        assertions.assert_ts_equals(
            after["posture_recomputed_at"],
            "2026-08-11T09:00:00.000Z",
            "posture_recomputed_at",
        )


# ---------------------------------------------------------------------------
# Local composite setup for the release-and-promotion cascade
# ---------------------------------------------------------------------------

_RELEASE_REASON = "Management schedule conflict at the venue."


def _build_allocated_event(api: ApiClient):
    """A LOCKED single-slot roadshow with one ALLOCATED and one WAITLISTED request.

    ``P1`` holds 12% of the register and ``P2`` holds 2%, both with an NDA, so the
    final scores are (50 + 8 + 20 + 5) * 1.20 = 99.60 and
    (35 + 8 + 8 + 5) * 1.20 = 67.20 — the lead-time bonus being 5 because the
    window opens 31 days after the logical clock.
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    company = fixtures.create_company(
        api,
        ticker="PRM",
        legal_name="Promotion Cascade Corp",
        shares_outstanding=1000000,
    )
    holder_one = fixtures.create_holder(
        api,
        company["id"],
        120000,
        display_name="Promo Holder One",
        email="p1@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        nda_on_file=True,
    )
    holder_two = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Promo Holder Two",
        email="p2@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        nda_on_file=True,
    )
    event = fixtures.open_event(
        api,
        company["id"],
        event_type=EVENT_NDR,
        venue_city="Chicago",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
        capacity_slots=1,
    )
    first = fixtures.create_meeting_request(
        api,
        event["id"],
        holder_one["id"],
        requested_slot_start="2026-09-01T13:00:00Z",
        requested_slot_end="2026-09-01T13:30:00Z",
    )
    second = fixtures.create_meeting_request(
        api,
        event["id"],
        holder_two["id"],
        requested_slot_start="2026-09-01T14:00:00Z",
        requested_slot_end="2026-09-01T14:30:00Z",
    )
    fixtures.allocate_event(api, event["id"], IR_ADMIN)
    return {
        "event_id": event["id"],
        "allocated_id": first["id"],
        "waitlisted_id": second["id"],
        "h1": holder_one,
        "h2": holder_two,
    }


class TestMeetingReleasePromotionCascade:
    """The three links fired by releasing the event's only allocated slot."""

    def test_releasing_the_slot_moves_the_request_to_released(self, api: ApiClient):
        """PRD §3.8: "The first link transitions the request `ALLOCATED` → `RELEASED`, stores the supplied reason as `release_reason`, and increments the request's `version` by 1."

        PRD §3.8: "The **final** variant runs during the allocation waterfall, is written to `final_priority_score`, uses the contact as it stands at allocation time, and adds a genuine lead-time bonus: 5 when the lead time is at least 14 days, otherwise 2 when the lead time is at least 7 days, otherwise 0."

        PRD §3.8: "A request that lands on `WAITLISTED` also stores its `final_priority_score` and increments its own `version` by 1, but `allocated_at` stays null — a waitlisted request has never been given a time — and it increases the event's `waitlisted_count` by 1 instead."

        Design: Difficulty/transitive_cascade/meeting_release_promotes_waitlisted_request_depth_three
        """
        world = _build_allocated_event(api)
        allocated_before = fixtures.read_meeting_request(api, world["allocated_id"])
        waitlisted_before = fixtures.read_meeting_request(api, world["waitlisted_id"])
        assertions.assert_contact(world["h1"], target_tier=TIER_1)
        assertions.assert_contact(world["h2"], target_tier=TIER_2)
        assertions.assert_meeting_request(
            allocated_before, status=REQUEST_ALLOCATED, promoted_from_waitlist=False
        )
        assertions.assert_meeting_request(
            waitlisted_before, status=REQUEST_WAITLISTED, allocated_at=None
        )
        assert allocated_before["final_priority_score"] == assertions.approx_2dp(99.60)
        assert waitlisted_before["final_priority_score"] == assertions.approx_2dp(67.20)

        released = fixtures.release_request(
            api, world["allocated_id"], _RELEASE_REASON, IR_ADMIN
        )
        assertions.assert_meeting_request(
            released,
            status=REQUEST_RELEASED,
            release_reason=_RELEASE_REASON,
            version=allocated_before["version"] + 1,
        )
        assert released["final_priority_score"] == assertions.approx_2dp(99.60)

    def test_the_freed_slot_promotes_the_highest_ranked_waitlisted_request(
        self, api: ApiClient
    ):
        """PRD §3.8: "The second link, caused by the first, decreases the event's `allocated_count` by 1, increases its `released_count` by 1, and increments the event's `version` by 1 — a slot is now free."

        PRD §3.8: "The third link, caused by the second, fires only while that free slot exists: from the pool of this event's requests in status `WAITLISTED` whose `final_priority_score` is at least 25, the promotion selector picks the single highest-ranked row using the same ordering as the run — `final_priority_score` descending, then the contact's `shares_held` descending, then creation timestamp ascending — and transitions it `WAITLISTED` → `ALLOCATED` with `promoted_from_waitlist` set to true and `allocated_at` stamped from the logical clock, then increases the event's `allocated_count` by 1 and decreases its `waitlisted_count` by 1."

        Design: Difficulty/transitive_cascade/meeting_release_promotes_waitlisted_request_depth_three
        """
        world = _build_allocated_event(api)

        fixtures.release_request(
            api, world["allocated_id"], _RELEASE_REASON, IR_ADMIN
        )

        promoted = fixtures.read_meeting_request(api, world["waitlisted_id"])
        assertions.assert_meeting_request(
            promoted,
            status=REQUEST_ALLOCATED,
            promoted_from_waitlist=True,
        )
        assert promoted["final_priority_score"] == assertions.approx_2dp(67.20)
        assertions.assert_ts_equals(
            promoted["allocated_at"], "2026-08-01T00:00:00.000Z", "allocated_at"
        )

        event = fixtures.read_event(api, world["event_id"])
        assertions.assert_roadshow_event(
            event,
            allocated_count=1,
            waitlisted_count=0,
            released_count=1,
            declined_count=0,
        )

    def test_the_release_and_the_promotion_conserve_the_request_ledger(
        self, api: ApiClient
    ):
        """PRD §3.8: "`request_ledger_total` is the count of every meeting request ever created against the event and is monotonic: it never decreases."

        PRD §3.8: "`allocated_count`, `waitlisted_count`, `released_count` and `declined_count` are the counts of that event's requests in the corresponding statuses, and `request_ledger_total` always equals the sum of those four counters plus the number of the event's requests still in `REQUESTED`."

        PRD §3.8: "Separately, `allocated_count` never exceeds `capacity_slots` at any point in time."

        Design: Difficulty/transitive_cascade/meeting_release_promotes_waitlisted_request_depth_three
        """
        world = _build_allocated_event(api)
        before = fixtures.read_event(api, world["event_id"])
        assertions.assert_roadshow_event(
            before, status=EVENT_LOCKED, request_ledger_total=2, capacity_slots=1
        )
        assertions.assert_request_ledger_conserved(before, 0)

        fixtures.release_request(
            api, world["allocated_id"], _RELEASE_REASON, IR_ADMIN
        )

        after = fixtures.read_event(api, world["event_id"])
        assertions.assert_roadshow_event(
            after, status=EVENT_LOCKED, request_ledger_total=2
        )
        assertions.assert_request_ledger_conserved(after, 0)
        assert after["allocated_count"] <= after["capacity_slots"]
