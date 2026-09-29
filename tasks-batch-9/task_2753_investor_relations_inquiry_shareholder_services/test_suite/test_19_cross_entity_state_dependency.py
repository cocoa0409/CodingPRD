"""Writes whose legality depends on the state of a joined row, not their own.

Two different entity pairs:

* ResponseDraft -> Disclosure — an APPROVED draft may be dispatched only while the
  disclosure it cites is still PUBLISHED at exactly the version pinned at approval;
* MeetingRequest -> RoadshowEvent — a request may be lodged only while its parent
  event has been opened for business.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    DISCLOSURE_OFFICER,
    IR_ADMIN,
    IR_ANALYST,
    assertions,
    fixtures,
    make_investor_headers,
    validate_error,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_PINNED = "2026-08-10T09:00:00Z"


def _build_approved_draft_citing_published_guidance(api: ApiClient):
    """An APPROVED GUIDANCE_REPEAT draft pinned to a published guidance row."""
    fixtures.set_clock(api, CLOCK_PINNED)
    company = fixtures.create_company(
        api,
        ticker="PIN",
        legal_name="Pinned Version Corp",
        shares_outstanding=1000000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        40000,
        display_name="Pin Holder",
        email="pin@funds.test",
    )
    cited = fixtures.create_published_guidance(
        api,
        company["id"],
        fact_key="FY2026-EPS-GUIDANCE",
        metric="EPS",
        period_label="FY2026",
        guidance_low=2.00,
        guidance_high=2.20,
    )
    assertions.assert_disclosure(cited, status="PUBLISHED", is_guidance=True)
    assertions.assert_version(cited, 2, "Disclosure")

    inquiry = fixtures.create_routed_inquiry(
        api,
        company["id"],
        holder["id"],
        topic_category="GUIDANCE",
        subject="Please confirm the FY2026 EPS range.",
    )
    draft = fixtures.create_draft(
        api,
        inquiry["id"],
        body_text="Our published FY2026 EPS guidance range is 2.00 to 2.20.",
        disclosure_class="GUIDANCE_REPEAT",
        cited_disclosure_id=cited["id"],
    )
    fixtures.submit_for_review(api, draft["id"])
    approved = fixtures.decide_review(api, draft["id"], inquiry["id"], decision="APPROVE")
    assertions.assert_response_draft(
        approved, status="APPROVED", pinned_disclosure_version=2
    )

    replacement = fixtures.create_disclosure(
        api,
        company["id"],
        disclosure_type="GUIDANCE_UPDATE",
        fact_key="FY2026-EPS-GUIDANCE-R2",
        metric="EPS",
        period_label="FY2026",
        guidance_low=2.05,
        guidance_high=2.15,
    )
    assertions.assert_disclosure(replacement, status="DRAFT")
    return company, holder, cited, inquiry, draft, replacement


class TestDraftSendBlockedBySupersededCitation:
    """ResponseDraft dispatch against the Disclosure it pinned at approval."""

    def test_publishing_the_replacement_supersedes_the_citation_without_touching_the_draft(
        self, api: ApiClient
    ):
        """Supersession bumps the cited row to version 3 and leaves the draft APPROVED.

        PRD §3.4: "When a guidance row is published, every *other* disclosure of the same
        issuer that is currently `PUBLISHED`, has `is_guidance` true, and carries the same
        `metric` and the same `period_label` transitions `PUBLISHED` → `SUPERSEDED` with
        its own `version` incremented by 1."
        PRD §3.4: "Supersession deliberately does **not** block anything downstream: an
        approved response draft citing the row it just superseded keeps its `APPROVED`
        status and keeps the now-stale `pinned_disclosure_version` it captured at approval,
        and the staleness surfaces only when the author tries to dispatch the answer, which
        is rejected with `ERR_PINNED_DISCLOSURE_STALE`."

        Design: Difficulty/cross_entity_state_dependency/draft_send_blocked_by_superseded_cited_disclosure
        """
        company, holder, cited, inquiry, draft, replacement = (
            _build_approved_draft_citing_published_guidance(api)
        )

        published = validate_success(
            api.publish_disclosure(replacement["id"], DISCLOSURE_OFFICER)
        )
        assertions.assert_disclosure(published, status="PUBLISHED")

        superseded = fixtures.read_disclosure(api, cited["id"])
        assertions.assert_disclosure(superseded, status="SUPERSEDED")
        assertions.assert_version(superseded, 3, "Disclosure")

        stored_draft = fixtures.read_draft(api, draft["id"])
        assertions.assert_response_draft(
            stored_draft,
            status="APPROVED",
            pinned_disclosure_version=2,
            blocked_reason=None,
        )
        assertions.assert_inquiry(
            fixtures.read_inquiry(api, inquiry["id"]), status="AWAITING_APPROVAL"
        )

    def test_send_refused_when_the_cited_disclosure_was_superseded_after_approval(
        self, api: ApiClient
    ):
        """The pinned-version gate stops the answer at the door and answers nothing.

        PRD §3.6: "The last gate is the pinned-version check: if the draft carries a
        non-null `cited_disclosure_id`, then that disclosure must still be in status
        `PUBLISHED` **and** its current `version` must still equal the draft's
        `pinned_disclosure_version`, or dispatch is refused with
        `ERR_PINNED_DISCLOSURE_STALE`."
        PRD §3.6: "A successful dispatch drives the parent inquiry `AWAITING_APPROVAL` →
        `ANSWERED` with `answered_at` stamped from the logical clock and the inquiry's
        `version` incremented, and then recounts the issuer's `open_inquiry_count` —
        `ANSWERED` being the one status outside the open set — incrementing the issuer's
        `version` by 1 as well."

        Design: Difficulty/cross_entity_state_dependency/draft_send_blocked_by_superseded_cited_disclosure
        """
        company, holder, cited, inquiry, draft, replacement = (
            _build_approved_draft_citing_published_guidance(api)
        )
        validate_success(api.publish_disclosure(replacement["id"], DISCLOSURE_OFFICER))

        validate_error(
            api.send_draft(draft["id"], IR_ANALYST),
            ApiErrorId.PINNED_DISCLOSURE_STALE.value,
        )

        stored_draft = fixtures.read_draft(api, draft["id"])
        assertions.assert_response_draft(
            stored_draft, status="APPROVED", pinned_disclosure_version=2
        )
        assertions.assert_inquiry(
            fixtures.read_inquiry(api, inquiry["id"]),
            status="AWAITING_APPROVAL",
            answered_at=None,
        )
        assertions.assert_company(
            fixtures.read_company(api, company["id"]), open_inquiry_count=1
        )


def _build_planning_event_world(api: ApiClient):
    """An issuer, one NDA-carrying TIER_2 holder and one event still in PLANNING."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api,
        ticker="GTE",
        legal_name="Gated Events Corp",
        shares_outstanding=1000000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Gate Holder",
        email="gte@funds.test",
        nda_on_file=True,
    )
    event = fixtures.create_event(
        api,
        company["id"],
        event_type="CONFERENCE",
        venue_city="London",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
        capacity_slots=3,
    )
    assertions.assert_roadshow_event(
        event,
        status="PLANNING",
        allocated_count=0,
        waitlisted_count=0,
        released_count=0,
        declined_count=0,
        request_ledger_total=0,
    )
    return company, holder, event


def _slot_payload(event_id: str, contact_id: str):
    return {
        "event_id": event_id,
        "contact_id": contact_id,
        "requested_slot_start": "2026-09-01T13:00:00Z",
        "requested_slot_end": "2026-09-01T13:30:00Z",
    }


class TestMeetingRequestRequiresOpenEvent:
    """MeetingRequest creation against the RoadshowEvent's own lifecycle state."""

    def test_request_refused_while_the_parent_event_is_still_planning(
        self, api: ApiClient
    ):
        """A perfectly shaped bid is refused purely because of the event's state.

        PRD §3.8: "The parent event must be in `OPEN_FOR_REQUESTS` — a request against an
        event still planning or already locked is refused with
        `ERR_EVENT_NOT_OPEN_FOR_REQUESTS`."
        PRD §3.8: "A new event is born in `PLANNING`, with `allocated_count`,
        `waitlisted_count`, `released_count`, `declined_count` and `request_ledger_total`
        all at zero and `version` at 1."

        Design: Difficulty/cross_entity_state_dependency/meeting_request_requires_event_open_for_requests
        """
        company, holder, event = _build_planning_event_world(api)

        validate_error(
            api.create_meeting_request(
                _slot_payload(event["id"], holder["id"]),
                make_investor_headers(holder["id"]),
            ),
            ApiErrorId.EVENT_NOT_OPEN_FOR_REQUESTS.value,
        )

        stored = fixtures.read_event(api, event["id"])
        assertions.assert_roadshow_event(
            stored, status="PLANNING", request_ledger_total=0
        )
        assertions.assert_version(stored, 1, "RoadshowEvent")

    def test_identical_request_is_accepted_once_the_event_is_open(self, api: ApiClient):
        """Opening the event makes the identical payload succeed and moves the ledger to 1.

        PRD §3.8: "Opening the event for business transitions it `PLANNING` →
        `OPEN_FOR_REQUESTS` and is refused with `ERR_EVENT_INVALID_STATE` from any other
        status."
        PRD §3.8: "A surviving request is born in `REQUESTED` with `final_priority_score`
        null, `allocated_at` null, `release_reason` null and `promoted_from_waitlist`
        false, and it increments the parent event's `request_ledger_total` by 1 along with
        the event's `version`."
        PRD §3.8: "The **provisional** variant runs at intake, is written to
        `provisional_priority_score`, uses the contact as it stands at intake, and its
        lead-time bonus is always zero."

        Design: Difficulty/cross_entity_state_dependency/meeting_request_requires_event_open_for_requests
        """
        company, holder, event = _build_planning_event_world(api)

        opened = validate_success(api.open_event_requests(event["id"], IR_ADMIN))
        assertions.assert_roadshow_event(opened, status="OPEN_FOR_REQUESTS")

        created = validate_success(
            api.create_meeting_request(
                _slot_payload(event["id"], holder["id"]),
                make_investor_headers(holder["id"]),
            ),
            expected_status=201,
        )
        assertions.assert_meeting_request(
            created,
            status="REQUESTED",
            final_priority_score=None,
            allocated_at=None,
            release_reason=None,
            promoted_from_waitlist=False,
        )
        assert created["provisional_priority_score"] == assertions.approx_2dp(61.20)

        stored = fixtures.read_event(api, event["id"])
        assertions.assert_roadshow_event(
            stored,
            status="OPEN_FOR_REQUESTS",
            request_ledger_total=1,
            allocated_count=0,
            waitlisted_count=0,
        )
