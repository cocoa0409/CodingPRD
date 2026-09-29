"""Uniqueness constraints, the one-live-draft rule and collective ownership checks.

Every test in this module builds its own world through the documented endpoints:
the server is restarted before each test, so the store starts empty and the
logical clock starts at its default instant.
"""

from test_helpers import (
    ApiErrorId,
    CLASS_PUBLIC_DOMAIN,
    CONTACT_INSTITUTIONAL_HOLDER,
    CONTACT_RETAIL_HOLDER,
    DISCLOSURE_OFFICER,
    DISCLOSURE_PRESS_RELEASE,
    DISCLOSURE_STATUS_DRAFT,
    DISCLOSURE_STATUS_PUBLISHED,
    DISCLOSURE_STATUS_SUPERSEDED,
    DRAFT_DRAFT,
    EVENT_NDR,
    EVENT_OPEN_FOR_REQUESTS,
    INQUIRY_DRAFTING,
    IR_ADMIN,
    IR_ANALYST,
    METRIC_EPS,
    TIER_1,
    TOPIC_GUIDANCE,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Ticker uniqueness
# ---------------------------------------------------------------------------


def test_second_issuer_reusing_a_live_ticker_is_refused(api):
    """A ticker collision is global, not scoped to the legal name.

    PRD §3.1: "The ticker is the exchange symbol: between one and eight uppercase
    characters, and unique across every issuer already on file — a collision is
    refused with `ERR_DUPLICATE_TICKER`."
    PRD §3.1: "The issuer collection may be filtered by `ticker` or by
    `disclosure_posture` and is paginated per §2.3."
    PRD §2.3: "`total_count` reports the number of rows matching the request's
    filters before pagination is applied, and `has_more` is true when rows matching
    the filters remain beyond the returned page."

    Design: Corner/validations/duplicate_ticker_is_rejected_across_companies
    """
    fixtures.set_clock(api, CLOCK)
    first = fixtures.create_company(
        api, ticker="DUP", legal_name="First Duplicate Corp", shares_outstanding=1000000
    )

    collision = api.create_company(
        factories.company_payload(
            ticker="DUP", legal_name="Second Duplicate Corp", shares_outstanding=2000000
        ),
        IR_ADMIN,
    )
    validate_error(collision, ApiErrorId.DUPLICATE_TICKER.value, 409)

    rows, meta = validate_paginated(api.list_companies(IR_ADMIN, ticker="DUP"))
    assert meta["total_count"] == 1, "the refused registration must not have written a row"
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["legal_name"] == "First Duplicate Corp"


# ---------------------------------------------------------------------------
# fact_key uniqueness and its release by supersession
# ---------------------------------------------------------------------------


def test_fact_key_collision_against_a_published_row_is_refused(api):
    """A second row may not take a fact_key that a PUBLISHED row still holds.

    PRD §3.4: "A fact key is unique per issuer, but only among the rows that are
    live: no two disclosures of the same issuer may share a `fact_key` while both
    are in `DRAFT` or `PUBLISHED`, and a collision is refused with
    `ERR_DUPLICATE_FACT_KEY`."

    Design: Corner/validations/fact_key_uniqueness_is_released_by_supersession
    """
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="FKY", legal_name="Fact Key Corp", shares_outstanding=1000000
    )
    live = fixtures.create_published_guidance(
        api,
        company["id"],
        fact_key="EPS-FY2026-INITIAL",
        metric=METRIC_EPS,
        period_label="FY2026",
        guidance_low=2.00,
        guidance_high=2.20,
    )
    assert live["status"] == DISCLOSURE_STATUS_PUBLISHED

    collision = api.create_disclosure(
        factories.disclosure_payload(
            company["id"],
            disclosure_type=DISCLOSURE_PRESS_RELEASE,
            fact_key="EPS-FY2026-INITIAL",
        ),
        DISCLOSURE_OFFICER,
    )
    validate_error(collision, ApiErrorId.DUPLICATE_FACT_KEY.value, 409)

    rows, meta = validate_paginated(
        api.list_disclosures(IR_ADMIN, company_id=company["id"])
    )
    assert meta["total_count"] == 1, "the refused draft must not have been written"
    assert rows[0]["id"] == live["id"]


def test_supersession_releases_the_fact_key_for_reuse(api):
    """Once the holder of a key is SUPERSEDED the same key is accepted again.

    PRD §3.4: "Once a row reaches `SUPERSEDED` or `WITHDRAWN` it releases its key,
    and the same key may be used again."
    PRD §3.4: "When a guidance row is published, every *other* disclosure of the same
    issuer that is currently `PUBLISHED`, has `is_guidance` true, and carries the same
    `metric` and the same `period_label` transitions `PUBLISHED` → `SUPERSEDED` with
    its own `version` incremented by 1."
    PRD §3.4: "A new row is born in `DRAFT` with `published_at` null and `version` 1."

    Design: Corner/validations/fact_key_uniqueness_is_released_by_supersession
    """
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="FKY", legal_name="Fact Key Corp", shares_outstanding=1000000
    )
    first = fixtures.create_published_guidance(
        api,
        company["id"],
        fact_key="EPS-FY2026-INITIAL",
        metric=METRIC_EPS,
        period_label="FY2026",
        guidance_low=2.00,
        guidance_high=2.20,
    )

    replacement = fixtures.create_disclosure(
        api,
        company["id"],
        disclosure_type="GUIDANCE_UPDATE",
        fact_key="EPS-FY2026-UPDATE",
        metric=METRIC_EPS,
        period_label="FY2026",
        guidance_low=2.10,
        guidance_high=2.30,
    )
    published = validate_success(
        api.publish_disclosure(replacement["id"], DISCLOSURE_OFFICER), 200
    )
    assert published["status"] == DISCLOSURE_STATUS_PUBLISHED

    superseded = fixtures.read_disclosure(api, first["id"])
    assertions.assert_disclosure(
        superseded,
        status=DISCLOSURE_STATUS_SUPERSEDED,
        fact_key="EPS-FY2026-INITIAL",
    )
    assertions.assert_version(superseded, 3, "Disclosure")

    reuse = api.create_disclosure(
        factories.disclosure_payload(
            company["id"],
            disclosure_type=DISCLOSURE_PRESS_RELEASE,
            fact_key="EPS-FY2026-INITIAL",
        ),
        DISCLOSURE_OFFICER,
    )
    reborn = validate_success(reuse, 201)
    assertions.assert_disclosure(
        reborn,
        fact_key="EPS-FY2026-INITIAL",
        status=DISCLOSURE_STATUS_DRAFT,
        published_at=None,
    )
    assertions.assert_version(reborn, 1, "Disclosure")


# ---------------------------------------------------------------------------
# At most one live draft per inquiry
# ---------------------------------------------------------------------------


def test_second_live_draft_on_a_drafting_inquiry_is_refused(api):
    """The inquiry is in DRAFTING, so only the active-draft rule can fail.

    PRD §3.6: "What `DRAFTING` must not admit is a second live draft alongside a
    first, so an inquiry may hold at most one draft whose status is `DRAFT`,
    `IN_REVIEW`, `CHANGES_REQUESTED` or `APPROVED`, and a second one is refused with
    `ERR_ACTIVE_DRAFT_EXISTS`."
    PRD §3.6: "Opening a draft against an inquiry in `ROUTED` transitions that inquiry
    `ROUTED` → `DRAFTING` and increments its `version` by 1; opening one against an
    inquiry already in `DRAFTING` leaves the status where it is but still increments
    the inquiry's `version` by 1, because the new draft row is itself the write."
    PRD §3.6: "Drafts may be listed with filters on `inquiry_id`,
    `cited_disclosure_id`, `author_user_id`, `status` and `disclosure_class` — this
    listing is the only discovery channel for a draft that a cascade has quietly moved
    to `BLOCKED` — and addressing a draft that does not exist yields
    `ERR_RESPONSE_DRAFT_NOT_FOUND`."

    Design: Corner/validations/only_one_live_draft_per_inquiry
    """
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="ADX", legal_name="Active Draft Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Active Draft Holder",
        email="adx@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    inquiry = fixtures.create_routed_inquiry(
        api,
        company["id"],
        holder["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="One question, one answer.",
    )
    first_draft = fixtures.create_draft(
        api, inquiry["id"], body_text="First answer attempt.",
        disclosure_class=CLASS_PUBLIC_DOMAIN,
    )

    before = fixtures.read_inquiry(api, inquiry["id"])
    assert before["status"] == INQUIRY_DRAFTING, (
        "the state precondition on the parent inquiry must be satisfied"
    )

    second = api.create_response_draft(
        factories.response_draft_payload(
            inquiry["id"],
            body_text="Competing second answer.",
            disclosure_class=CLASS_PUBLIC_DOMAIN,
        ),
        IR_ANALYST,
    )
    validate_error(second, ApiErrorId.ACTIVE_DRAFT_EXISTS.value, 409)

    rows, meta = validate_paginated(
        api.list_response_drafts(IR_ANALYST, inquiry_id=inquiry["id"])
    )
    assert meta["total_count"] == 1, "the refused draft must not have been written"
    assert rows[0]["id"] == first_draft["id"]
    assert rows[0]["status"] == DRAFT_DRAFT

    after = fixtures.read_inquiry(api, inquiry["id"])
    assert after["status"] == INQUIRY_DRAFTING
    assertions.assert_version(after, before["version"], "InquiryTicket")


# ---------------------------------------------------------------------------
# Meeting-request contact ownership: the contact must sit under the event's issuer
# ---------------------------------------------------------------------------


def test_meeting_request_for_a_contact_of_another_issuer_is_refused(api):
    """Both rows exist and the slot is valid, so only the issuer link can fail.

    PRD §3.8: "The requesting contact must belong to the same issuer as the event, or
    the request is refused with `ERR_CONTACT_COMPANY_MISMATCH`."
    PRD §3.8: "A surviving request is born in `REQUESTED` with `final_priority_score`
    null, `allocated_at` null, `release_reason` null and `promoted_from_waitlist`
    false, and it increments the parent event's `request_ledger_total` by 1 along with
    the event's `version`."
    PRD §3.8: "Opening the event for business transitions it `PLANNING` →
    `OPEN_FOR_REQUESTS` and is refused with `ERR_EVENT_INVALID_STATE` from any other
    status."

    Design: Corner/validations/meeting_request_contact_must_belong_to_the_events_company
    """
    fixtures.set_clock(api, CLOCK)
    company_a = fixtures.create_company(
        api, ticker="MXA", legal_name="Mismatch Corp A", shares_outstanding=1000000
    )
    company_b = fixtures.create_company(
        api, ticker="MXB", legal_name="Mismatch Corp B", shares_outstanding=1000000
    )
    foreign_holder = fixtures.create_holder(
        api,
        company_b["id"],
        20000,
        display_name="Foreign Holder",
        email="mxb@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    event = fixtures.open_event(
        api,
        company_a["id"],
        event_type=EVENT_NDR,
        venue_city="Lisbon",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
        capacity_slots=2,
    )
    assert event["status"] == EVENT_OPEN_FOR_REQUESTS

    mismatch = api.create_meeting_request(
        factories.meeting_request_payload(
            event["id"],
            foreign_holder["id"],
            requested_slot_start="2026-09-01T13:00:00Z",
            requested_slot_end="2026-09-01T13:30:00Z",
        ),
        IR_ADMIN,
    )
    validate_error(mismatch, ApiErrorId.CONTACT_COMPANY_MISMATCH.value, 422)

    after = fixtures.read_event(api, event["id"])
    assertions.assert_roadshow_event(
        after,
        status=EVENT_OPEN_FOR_REQUESTS,
        request_ledger_total=0,
        allocated_count=0,
        waitlisted_count=0,
    )
    assertions.assert_version(after, event["version"], "RoadshowEvent")

    rows, meta = validate_paginated(
        api.list_meeting_requests(IR_ADMIN, event_id=event["id"])
    )
    assert meta["total_count"] == 0 and rows == [], "no request row may have been created"


# ---------------------------------------------------------------------------
# Collective positions against shares_outstanding
# ---------------------------------------------------------------------------


def _build_two_holder_register(api):
    """100,000 outstanding shares held 60,000 / 30,000 by two holders."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="AGG", legal_name="Aggregate Shares Corp", shares_outstanding=100000
    )
    holder_a = fixtures.create_holder(
        api,
        company["id"],
        60000,
        display_name="Aggregate Holder A",
        email="agg1@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    holder_b = fixtures.create_holder(
        api,
        company["id"],
        30000,
        display_name="Aggregate Holder B",
        email="agg2@retail.test",
        contact_type=CONTACT_RETAIL_HOLDER,
    )
    return company, holder_a, holder_b


def test_position_pushing_the_register_past_shares_outstanding_is_refused(api):
    """105,000 of 100,000 outstanding is refused and rewrites nothing.

    PRD §3.2: "Individually plausible positions can still be collectively impossible,
    so after the replacement the system sums `shares_held` across every contact of
    that issuer whose `contact_type` is `INSTITUTIONAL_HOLDER` or `RETAIL_HOLDER` —
    analyst rows are excluded from the sum — and refuses the write with
    `ERR_SHARES_EXCEED_OUTSTANDING` if that total would exceed the issuer's
    `shares_outstanding`."
    PRD §2.6: "Recording a new share position requires `expected_company_version`,
    carrying the client's last observed `version` of the issuer the holder sits under."

    Design: Corner/validations/collective_positions_may_not_exceed_shares_outstanding
    """
    company, holder_a, holder_b = _build_two_holder_register(api)
    company_version = fixtures.company_version(api, company["id"])

    refused = api.update_position(
        holder_b["id"],
        factories.position_payload(45000, company_version),
        IR_ADMIN,
    )
    validate_error(refused, ApiErrorId.SHARES_EXCEED_OUTSTANDING.value, 422)

    unchanged_b = fixtures.read_contact(api, holder_b["id"])
    assertions.assert_contact(unchanged_b, shares_held=30000)
    assertions.assert_version(unchanged_b, holder_b["version"], "Contact")

    unchanged_a = fixtures.read_contact(api, holder_a["id"])
    assertions.assert_contact(unchanged_a, shares_held=60000)
    assertions.assert_version(unchanged_a, holder_a["version"], "Contact")


def test_position_landing_exactly_on_shares_outstanding_is_accepted(api):
    """The refused patch never advanced the issuer, so the same version still works.

    PRD §3.2: "Individually plausible positions can still be collectively impossible,
    so after the replacement the system sums `shares_held` across every contact of
    that issuer whose `contact_type` is `INSTITUTIONAL_HOLDER` or `RETAIL_HOLDER` —
    analyst rows are excluded from the sum — and refuses the write with
    `ERR_SHARES_EXCEED_OUTSTANDING` if that total would exceed the issuer's
    `shares_outstanding`."
    PRD §3.2: "On creation, and again on every position update, the system divides the
    contact's `shares_held` by the issuer's `shares_outstanding` as stored at that
    moment, multiplies the quotient by 100, and rounds the result half up to 4 decimal
    places to obtain `ownership_pct`."
    PRD §3.2: "A position write that survives every check re-derives `ownership_pct`
    and `target_tier`, then re-derives the issuer's `disclosure_posture` and stamps
    `posture_recomputed_at`, incrementing both the contact's `version` and the issuer's
    `version` by 1."

    Design: Corner/validations/collective_positions_may_not_exceed_shares_outstanding
    """
    company, holder_a, holder_b = _build_two_holder_register(api)
    company_version = fixtures.company_version(api, company["id"])

    validate_error(
        api.update_position(
            holder_b["id"], factories.position_payload(45000, company_version), IR_ADMIN
        ),
        ApiErrorId.SHARES_EXCEED_OUTSTANDING.value,
        422,
    )

    accepted = validate_success(
        api.update_position(
            holder_b["id"], factories.position_payload(40000, company_version), IR_ADMIN
        ),
        200,
    )
    assertions.assert_contact(accepted, shares_held=40000, target_tier=TIER_1)
    assert accepted["ownership_pct"] == assertions.approx_4dp(40.0000)
    assertions.assert_version(accepted, holder_b["version"] + 1, "Contact")

    issuer = fixtures.read_company(api, company["id"])
    assertions.assert_version(issuer, company_version + 1, "Company")

    untouched_a = fixtures.read_contact(api, holder_a["id"])
    assertions.assert_contact(untouched_a, shares_held=60000)
    assertions.assert_version(untouched_a, holder_a["version"], "Contact")
