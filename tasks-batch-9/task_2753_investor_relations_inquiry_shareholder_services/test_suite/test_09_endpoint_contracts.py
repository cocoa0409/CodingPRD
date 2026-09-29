"""Endpoint contract behaviours: inline action payloads, listings and overrides.

Every test in this module translates exactly one instance of the corner-design
`endpoints` section. The server is restarted before each test, so each one
builds its own world through the documented endpoints.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assertions,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    CLASS_GUIDANCE_REPEAT,
    CONTACT_INSTITUTIONAL_HOLDER,
    CONTACT_RETAIL_HOLDER,
    DISCLOSURE_FORM_8K,
    DISCLOSURE_STATUS_PUBLISHED,
    DRAFT_DRAFT,
    EVENT_CONFERENCE,
    EVENT_LOCKED,
    INQUIRY_NEW,
    INQUIRY_ROUTED,
    QUEUE_DISCLOSURE_COMMITTEE,
    QUEUE_IR_DESK,
    QUEUE_TRANSFER_AGENT_DESK,
    REQUEST_ALLOCATED,
    REQUEST_WAITLISTED,
    TOPIC_DIVIDEND,
    TOPIC_GUIDANCE,
)
from test_helpers import DISCLOSURE_OFFICER, IR_ADMIN, IR_ANALYST

CLOCK = "2026-08-01T00:00:00Z"


def _allocation_world(api: ApiClient):
    """One issuer, a TIER_1 institutional holder, a TIER_3 retail holder and an
    open CONFERENCE event holding one request from each of them."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="ALO", legal_name="Allocation Summary Corp", shares_outstanding=1000000
    )
    holder_a = fixtures.create_holder(
        api,
        company["id"],
        120000,
        display_name="Allocation Fund",
        email="alo1@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        nda_on_file=True,
    )
    holder_b = fixtures.create_holder(
        api,
        company["id"],
        5000,
        display_name="Allocation Retail",
        email="alo2@retail.test",
        contact_type=CONTACT_RETAIL_HOLDER,
    )
    event, requests = fixtures.build_open_event_with_requests(
        api,
        company["id"],
        [
            (holder_a["id"], "2026-09-01T13:00:00Z", "2026-09-01T13:30:00Z"),
            (holder_b["id"], "2026-09-01T14:00:00Z", "2026-09-01T14:30:00Z"),
        ],
        capacity_slots=2,
        event_type=EVENT_CONFERENCE,
        venue_city="Paris",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
    )
    return company, holder_a, holder_b, event, requests[0], requests[1]


class TestAllocationRunSummary:
    def test_allocate_returns_inline_run_summary_object(self, api: ApiClient):
        """PRD §3.8: "The allocation waterfall is an `IRAdmin` operation and transitions the event `OPEN_FOR_REQUESTS` → `LOCKED`."
        PRD §3.8: "The run finishes by recomputing the event's counters, setting `status` to `LOCKED` and incrementing the event's `version` by 1, and it reports back `event_id`, the resulting `event_status`, the `evaluated_count` of candidates it scored, the resulting `allocated_count` and `waitlisted_count`, and a `threshold_deferred_count` that isolates the requests waitlisted because their score fell below 25 rather than because capacity ran out."
        PRD §3.8: "Candidates whose score is at least 25 are eligible; candidates below 25 are **threshold-deferred** and are never allocated in this run, however much capacity remains."

        Design: Corner/endpoints/allocation_run_returns_an_inline_run_summary
        """
        _company, _a, _b, event, _mra, _mrb = _allocation_world(api)

        response = api.allocate_event(event["id"], IR_ADMIN)
        summary = validate_success(response, 200)

        assertions.assert_allocation_summary(
            summary,
            event_id=event["id"],
            event_status=EVENT_LOCKED,
            evaluated_count=2,
            allocated_count=1,
            waitlisted_count=1,
            threshold_deferred_count=1,
        )

    def test_allocate_scores_split_the_two_requests_and_leave_the_slot_free(
        self, api: ApiClient
    ):
        """PRD §3.8: "Remaining capacity is the event's `capacity_slots` minus its current `allocated_count`, and the first that many rows of the ranked eligible list transition `REQUESTED` → `ALLOCATED`."
        PRD §3.8: "Every other eligible row, and every threshold-deferred row, transitions `REQUESTED` → `WAITLISTED`."
        PRD §3.8: "A request that lands on `ALLOCATED` stores its `final_priority_score`, stamps `allocated_at` with the logical clock, sets `promoted_from_waitlist` to false, increments its own `version` by 1, and increases the event's `allocated_count` by 1."
        PRD §3.8: "A request that lands on `WAITLISTED` also stores its `final_priority_score` and increments its own `version` by 1, but `allocated_at` stays null — a waitlisted request has never been given a time — and it increases the event's `waitlisted_count` by 1 instead."
        PRD §3.8: "A surviving request is born in `REQUESTED` with `final_priority_score` null, `allocated_at` null, `release_reason` null and `promoted_from_waitlist` false, and it increments the parent event's `request_ledger_total` by 1 along with the event's `version`."

        Design: Corner/endpoints/allocation_run_returns_an_inline_run_summary
        """
        _company, _a, _b, event, mr_a, mr_b = _allocation_world(api)

        validate_success(api.allocate_event(event["id"], IR_ADMIN), 200)

        allocated = fixtures.read_meeting_request(api, mr_a["id"])
        assertions.assert_meeting_request(
            allocated, status=REQUEST_ALLOCATED, promoted_from_waitlist=False
        )
        assert allocated["final_priority_score"] == assertions.approx_2dp(99.60)
        assertions.assert_ts_equals(allocated["allocated_at"], CLOCK, "allocated_at")

        waitlisted = fixtures.read_meeting_request(api, mr_b["id"])
        assertions.assert_meeting_request(waitlisted, status=REQUEST_WAITLISTED)
        assert waitlisted["final_priority_score"] == assertions.approx_2dp(16.20)
        assert waitlisted["allocated_at"] is None

        locked = fixtures.read_event(api, event["id"])
        assertions.assert_roadshow_event(
            locked,
            status=EVENT_LOCKED,
            allocated_count=1,
            waitlisted_count=1,
            request_ledger_total=2,
        )


class TestClockEndpointInlinePayload:
    def test_clock_set_reports_the_resulting_instant_as_current_utc(self, api: ApiClient):
        """PRD §2.4: "An `IRAdmin` may move it by supplying a `to_iso8601` instant; the response reports the resulting clock as `current_utc`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

        Design: Corner/endpoints/clock_endpoint_returns_the_new_instant_inline
        """
        response = api.set_clock("2026-08-05T12:00:00Z", IR_ADMIN)
        data = validate_success(response, 200)

        assertions.assert_ts_equals(
            data["current_utc"], "2026-08-05T12:00:00.000Z", "current_utc"
        )
        assert response.json()["response_type"] == "object"

    def test_registration_stamps_posture_recomputed_at_from_the_moved_clock(
        self, api: ApiClient
    ):
        """PRD §2.4: "An `IRAdmin` may move it by supplying a `to_iso8601` instant; the response reports the resulting clock as `current_utc`."
        PRD §3.1: "Registration also stamps the derived fields: `disclosure_posture` is derived immediately and `posture_recomputed_at` is stamped with the logical clock, `open_inquiry_count` and `dividend_paid_cents` both begin at zero, and `version` begins at 1."

        Design: Corner/endpoints/clock_endpoint_returns_the_new_instant_inline
        """
        clock = validate_success(api.set_clock("2026-08-05T12:00:00Z", IR_ADMIN), 200)
        assertions.assert_ts_equals(
            clock["current_utc"], "2026-08-05T12:00:00.000Z", "current_utc"
        )

        created = validate_success(
            api.create_company(
                {
                    "ticker": "CLK",
                    "legal_name": "Clock Corp",
                    "shares_outstanding": 1000000,
                },
                IR_ADMIN,
            ),
            201,
        )
        assertions.assert_company(
            created, open_inquiry_count=0, dividend_paid_cents=0, version=1
        )
        assertions.assert_ts_equals(
            created["posture_recomputed_at"],
            "2026-08-05T12:00:00.000Z",
            "posture_recomputed_at",
        )


def _listing_world(api: ApiClient):
    """Two IR_DESK guidance inquiries and one TRANSFER_AGENT_DESK dividend inquiry,
    the first guidance ticket already routed."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="LSQ", legal_name="Listing Query Corp", shares_outstanding=1000000
    )
    institutional = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Query Fund",
        email="lsq1@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    retail = fixtures.create_holder(
        api,
        company["id"],
        100,
        display_name="Query Retail",
        email="lsq2@retail.test",
        contact_type=CONTACT_RETAIL_HOLDER,
    )
    first = fixtures.create_inquiry(
        api,
        company["id"],
        institutional["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="Guidance question one.",
    )
    second = fixtures.create_inquiry(
        api,
        company["id"],
        institutional["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="Guidance question two.",
    )
    third = fixtures.create_inquiry(
        api,
        company["id"],
        retail["id"],
        topic_category=TOPIC_DIVIDEND,
        subject="Dividend question.",
    )
    fixtures.route_inquiry(api, first["id"])
    return company, first, second, third


class TestInquiryListingFiltersAndPagination:
    def test_routing_queue_filter_pages_with_limit_and_offset(self, api: ApiClient):
        """PRD §3.5: "Inquiry tickets may be listed with filters on `company_id`, `contact_id`, `linked_prior_inquiry_id`, `status`, `routing_queue` and `topic_category`, and a single ticket read exposes its score, queue, deadline and current `version` — the last of which is precisely the value a reviewer must pin under §2.6."
        PRD §2.3: "`offset` is the number of rows to skip before the page begins and defaults to 0."
        PRD §2.3: "`total_count` reports the number of rows matching the request's filters before pagination is applied, and `has_more` is true when rows matching the filters remain beyond the returned page."
        PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered by the resource's creation timestamp, ascending."

        Design: Corner/endpoints/inquiry_listing_filters_and_paginates_together
        """
        company, first, second, _third = _listing_world(api)

        page_one, meta_one = validate_paginated(
            api.list_inquiries(
                IR_ANALYST,
                company_id=company["id"],
                routing_queue=QUEUE_IR_DESK,
                limit=1,
                offset=0,
            )
        )
        assert len(page_one) == 1
        assert meta_one["total_count"] == 2
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 1
        assert meta_one["offset"] == 0

        page_two, meta_two = validate_paginated(
            api.list_inquiries(
                IR_ANALYST,
                company_id=company["id"],
                routing_queue=QUEUE_IR_DESK,
                limit=1,
                offset=1,
            )
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 2
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 1

        assert page_one[0]["id"] == first["id"]
        assert page_two[0]["id"] == second["id"]

    def test_status_and_topic_filters_each_isolate_one_row(self, api: ApiClient):
        """PRD §3.5: "Inquiry tickets may be listed with filters on `company_id`, `contact_id`, `linked_prior_inquiry_id`, `status`, `routing_queue` and `topic_category`, and a single ticket read exposes its score, queue, deadline and current `version` — the last of which is precisely the value a reviewer must pin under §2.6."
        PRD §3.5: "If the `topic_category` is `DIVIDEND` or `RECORD_DATE` and the frozen `sensitivity_score` is strictly below 50, the queue is `TRANSFER_AGENT_DESK`."
        PRD §3.5: "A ticket in `NEW` whose frozen `sensitivity_score` is strictly below 80 transitions `NEW` → `ROUTED`."

        Design: Corner/endpoints/inquiry_listing_filters_and_paginates_together
        """
        company, first, _second, third = _listing_world(api)

        routed, routed_meta = validate_paginated(
            api.list_inquiries(
                IR_ANALYST, company_id=company["id"], status=INQUIRY_ROUTED
            )
        )
        assert routed_meta["total_count"] == 1
        assert len(routed) == 1
        assert routed[0]["id"] == first["id"]

        dividends, dividend_meta = validate_paginated(
            api.list_inquiries(
                IR_ANALYST, company_id=company["id"], topic_category=TOPIC_DIVIDEND
            )
        )
        assert dividend_meta["total_count"] == 1
        assert len(dividends) == 1
        assert dividends[0]["id"] == third["id"]
        assert dividends[0]["routing_queue"] == QUEUE_TRANSFER_AGENT_DESK


def _citation_world(api: ApiClient):
    """An issuer with a PUBLISHED FORM_8K row and a routed guidance inquiry."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="LNK", legal_name="Link Corp", shares_outstanding=1000000
    )
    disclosure = fixtures.create_published_disclosure(
        api,
        company["id"],
        disclosure_type=DISCLOSURE_FORM_8K,
        fact_key="8K-LINK-01",
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Link Holder",
        email="lnk@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    inquiry = fixtures.create_routed_inquiry(
        api,
        company["id"],
        holder["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="Point me at the filing.",
    )
    return company, disclosure, inquiry


class TestDraftToDisclosureLink:
    def test_citing_a_published_row_stores_the_link_without_pinning_it(
        self, api: ApiClient
    ):
        """PRD §3.6: "Optionally the author names the published disclosure the draft repeats through `cited_disclosure_id`, which defaults to null when the draft cites nothing."
        PRD §3.6: "The acting `X-User-ID` is stamped as `author_user_id` and becomes the only user permitted to move the draft forward; `reviewer_user_id`, `reviewer_note`, `pinned_disclosure_version` and `blocked_reason` all start null, `status` starts at `DRAFT`, `revision_round` starts at 1, and `version` starts at 1."
        PRD §4: "Operations that bring a new resource into existence return `201 Created`."

        Design: Corner/endpoints/draft_to_disclosure_link_is_queryable_from_both_sides
        """
        _company, disclosure, inquiry = _citation_world(api)

        draft = validate_success(
            api.create_response_draft(
                {
                    "inquiry_id": inquiry["id"],
                    "body_text": "See the filing linked below.",
                    "disclosure_class": CLASS_GUIDANCE_REPEAT,
                    "cited_disclosure_id": disclosure["id"],
                },
                IR_ANALYST,
            ),
            201,
        )
        assertions.assert_response_draft(
            draft,
            cited_disclosure_id=disclosure["id"],
            pinned_disclosure_version=None,
            reviewer_user_id=None,
            reviewer_note=None,
            blocked_reason=None,
            status=DRAFT_DRAFT,
            revision_round=1,
            version=1,
        )

    def test_the_link_is_queryable_from_the_disclosure_and_the_inquiry_side(
        self, api: ApiClient
    ):
        """PRD §3.6: "Drafts may be listed with filters on `inquiry_id`, `cited_disclosure_id`, `author_user_id`, `status` and `disclosure_class` — this listing is the only discovery channel for a draft that a cascade has quietly moved to `BLOCKED` — and addressing a draft that does not exist yields `ERR_RESPONSE_DRAFT_NOT_FOUND`."
        PRD §3.4: "A successful publication stamps `published_at` with the logical clock, sets `status` to `PUBLISHED` and increments the row's `version` by 1."
        PRD §3.4: "A new row is born in `DRAFT` with `published_at` null and `version` 1."

        Design: Corner/endpoints/draft_to_disclosure_link_is_queryable_from_both_sides
        """
        _company, disclosure, inquiry = _citation_world(api)

        draft = fixtures.create_draft(
            api,
            inquiry["id"],
            body_text="See the filing linked below.",
            disclosure_class=CLASS_GUIDANCE_REPEAT,
            cited_disclosure_id=disclosure["id"],
        )

        by_citation, citation_meta = validate_paginated(
            api.list_response_drafts(IR_ANALYST, cited_disclosure_id=disclosure["id"])
        )
        assert citation_meta["total_count"] == 1
        assert len(by_citation) == 1
        assert by_citation[0]["id"] == draft["id"]

        by_inquiry, inquiry_meta = validate_paginated(
            api.list_response_drafts(
                IR_ANALYST, inquiry_id=inquiry["id"], status=DRAFT_DRAFT
            )
        )
        assert inquiry_meta["total_count"] == 1
        assert len(by_inquiry) == 1
        assert by_inquiry[0]["disclosure_class"] == CLASS_GUIDANCE_REPEAT

        # Creating the citation does not write the disclosure: it is still the
        # PUBLISHED row at version 2 (born at 1, publication added exactly 1).
        unchanged = fixtures.read_disclosure(api, disclosure["id"], DISCLOSURE_OFFICER)
        assertions.assert_disclosure(
            unchanged, status=DISCLOSURE_STATUS_PUBLISHED, version=2
        )


def _override_world(api: ApiClient):
    """One NEW guidance inquiry whose intake queue is IR_DESK."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="OQR", legal_name="Override Queue Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Override Holder",
        email="oqr@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    inquiry = fixtures.create_inquiry(
        api,
        company["id"],
        holder["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="Range question for the committee.",
    )
    return company, holder, inquiry


class TestTargetQueueOverride:
    def test_analyst_supplying_target_queue_is_refused(self, api: ApiClient):
        """PRD §3.5: "An `IRAnalyst` supplying `target_queue` is refused with `ERR_QUEUE_OVERRIDE_FORBIDDEN` even though the routing operation itself is open to that role."
        PRD §3.5: "Otherwise, if the submitting contact's `contact_type` is `RETAIL_HOLDER`, the queue is `SHAREHOLDER_SERVICES`. Otherwise the queue is `IR_DESK`."

        Design: Corner/endpoints/target_queue_override_is_a_conditional_action
        """
        _company, _holder, inquiry = _override_world(api)
        assertions.assert_inquiry(
            inquiry, status=INQUIRY_NEW, routing_queue=QUEUE_IR_DESK, version=1
        )

        validate_error(
            api.route_inquiry(inquiry["id"], QUEUE_DISCLOSURE_COMMITTEE, IR_ANALYST),
            ApiErrorId.QUEUE_OVERRIDE_FORBIDDEN.value,
        )

        untouched = fixtures.read_inquiry(api, inquiry["id"])
        assertions.assert_inquiry(
            untouched, status=INQUIRY_NEW, routing_queue=QUEUE_IR_DESK, version=1
        )

    def test_officer_override_rewrites_the_queue_and_the_deadline(self, api: ApiClient):
        """PRD §3.5: "A `DisclosureOfficer` may supply any member of the queue enumeration, in which case `routing_queue` is replaced with the supplied value and `sla_due_at` is recomputed against that queue's allowance."
        PRD §3.5: "Each queue carries its own service-level allowance, and the deadline is the logical clock at the moment of the write plus that allowance: 48 hours for `DISCLOSURE_COMMITTEE`, three days (72 hours) for `IR_DESK`, four days (96 hours) for `TRANSFER_AGENT_DESK` and five days (120 hours) for `SHAREHOLDER_SERVICES`."
        PRD §3.5: "A ticket in `NEW` whose frozen `sensitivity_score` is strictly below 80 transitions `NEW` → `ROUTED`."
        PRD §3.5: "`sensitivity_score` is a disclosure-risk score on a 0-to-100 scale, computed once at intake and never recomputed no matter what happens afterwards to the contact, the issuer or the linked inquiry."

        Design: Corner/endpoints/target_queue_override_is_a_conditional_action
        """
        _company, _holder, inquiry = _override_world(api)

        routed = validate_success(
            api.route_inquiry(
                inquiry["id"], QUEUE_DISCLOSURE_COMMITTEE, DISCLOSURE_OFFICER
            ),
            200,
        )
        assertions.assert_inquiry(
            routed,
            status=INQUIRY_ROUTED,
            routing_queue=QUEUE_DISCLOSURE_COMMITTEE,
            sensitivity_score=40,
            version=2,
        )
        assertions.assert_ts_equals(
            routed["sla_due_at"],
            assertions.sla_due_at(CLOCK, QUEUE_DISCLOSURE_COMMITTEE),
            "sla_due_at",
        )
        assertions.assert_ts_equals(
            routed["sla_due_at"], "2026-08-03T00:00:00.000Z", "sla_due_at"
        )
