"""Disclosure-boundary gates, temporal scheduling rules and check precedence.

Each test builds its own world through the documented endpoints. The server is
restarted before every test, so the store starts empty and the logical clock
starts at its default instant.
"""

from test_helpers import (
    ApiErrorId,
    CLASS_GUIDANCE_REPEAT,
    CLASS_MATERIAL_NONPUBLIC,
    CLASS_PUBLIC_DOMAIN,
    CONTACT_INSTITUTIONAL_HOLDER,
    DECISION_APPROVE,
    DECISION_REQUEST_CHANGES,
    DISCLOSURE_OFFICER,
    DISCLOSURE_OFFICER_USER_ID,
    DISCLOSURE_STATUS_DRAFT,
    DISCLOSURE_STATUS_PUBLISHED,
    DRAFT_CHANGES_REQUESTED,
    DRAFT_DRAFT,
    DRAFT_IN_REVIEW,
    EVENT_CONFERENCE,
    EVENT_NDR,
    EVENT_OPEN_FOR_REQUESTS,
    FUNDING_DECLARED_RATE,
    INQUIRY_AWAITING_APPROVAL,
    INQUIRY_DRAFTING,
    INSTRUCTION_DIVIDEND_PAYMENT,
    INSTRUCTION_RECORD_DATE_SET,
    INSTRUCTION_SUBMITTED,
    IR_ADMIN,
    IR_ADMIN_USER_ID,
    IR_ANALYST,
    METRIC_EPS,
    MODEL_ACCESS_NONE,
    NON_EXISTENT_UUID,
    POSTURE_BLACKOUT,
    REQUEST_REQUESTED,
    SERVICING_GRANT_MODEL_ACCESS,
    TOPIC_GUIDANCE,
    TOPIC_MODEL_REQUEST,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# GUIDANCE_REPEAT drafts need a PUBLISHED citation at submit-review
# ---------------------------------------------------------------------------


def _build_citation_world(api):
    """A DRAFT guidance row plus two GUIDANCE_REPEAT drafts, one uncited."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="CIT", legal_name="Citation Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Citation Holder",
        email="cit@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    disclosure = fixtures.create_disclosure(
        api,
        company["id"],
        disclosure_type="GUIDANCE_UPDATE",
        fact_key="EPS-FY2026-CIT",
        metric=METRIC_EPS,
        period_label="FY2026",
        guidance_low=2.00,
        guidance_high=2.20,
    )
    assert disclosure["status"] == DISCLOSURE_STATUS_DRAFT

    first_inquiry = fixtures.create_routed_inquiry(
        api,
        company["id"],
        holder["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="Repeat the range please.",
    )
    uncited = fixtures.create_draft(
        api,
        first_inquiry["id"],
        body_text="As guided previously.",
        disclosure_class=CLASS_GUIDANCE_REPEAT,
    )
    second_inquiry = fixtures.create_routed_inquiry(
        api,
        company["id"],
        holder["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="Same question from the same holder.",
    )
    cited = fixtures.create_draft(
        api,
        second_inquiry["id"],
        body_text="As guided in the attached release.",
        disclosure_class=CLASS_GUIDANCE_REPEAT,
        cited_disclosure_id=disclosure["id"],
    )
    return {
        "company": company,
        "holder": holder,
        "disclosure": disclosure,
        "first_inquiry": first_inquiry,
        "uncited_draft": uncited,
        "second_inquiry": second_inquiry,
        "cited_draft": cited,
    }


def test_guidance_repeat_without_a_citation_cannot_be_submitted(api):
    """A GUIDANCE_REPEAT draft carrying a null cited_disclosure_id is refused.

    PRD §3.6: "One content rule is enforced at this station: a draft whose
    `disclosure_class` is `GUIDANCE_REPEAT` must carry a non-null
    `cited_disclosure_id` and the disclosure it names must be in status `PUBLISHED` at
    that moment; a missing citation or an unpublished one is refused with
    `ERR_CITATION_REQUIRED`."

    Design: Corner/validations/guidance_repeat_draft_needs_a_published_citation
    """
    world = _build_citation_world(api)
    draft = world["uncited_draft"]
    assert draft["cited_disclosure_id"] is None

    refused = api.submit_draft_for_review(draft["id"], IR_ANALYST)
    validate_error(refused, ApiErrorId.CITATION_REQUIRED.value, 422)

    unchanged = fixtures.read_draft(api, draft["id"])
    assertions.assert_response_draft(unchanged, status=DRAFT_DRAFT)
    assertions.assert_version(unchanged, draft["version"], "ResponseDraft")

    inquiry = fixtures.read_inquiry(api, world["first_inquiry"]["id"])
    assert inquiry["status"] == INQUIRY_DRAFTING


def test_guidance_repeat_citing_an_unpublished_disclosure_cannot_be_submitted(api):
    """The citation exists but is still in DRAFT, so the status half of the rule fires.

    PRD §3.6: "One content rule is enforced at this station: a draft whose
    `disclosure_class` is `GUIDANCE_REPEAT` must carry a non-null
    `cited_disclosure_id` and the disclosure it names must be in status `PUBLISHED` at
    that moment; a missing citation or an unpublished one is refused with
    `ERR_CITATION_REQUIRED`."

    Design: Corner/validations/guidance_repeat_draft_needs_a_published_citation
    """
    world = _build_citation_world(api)
    draft = world["cited_draft"]
    assert draft["cited_disclosure_id"] == world["disclosure"]["id"]

    refused = api.submit_draft_for_review(draft["id"], IR_ANALYST)
    validate_error(refused, ApiErrorId.CITATION_REQUIRED.value, 422)

    unchanged = fixtures.read_draft(api, draft["id"])
    assertions.assert_response_draft(unchanged, status=DRAFT_DRAFT)
    assertions.assert_version(unchanged, draft["version"], "ResponseDraft")

    inquiry = fixtures.read_inquiry(api, world["second_inquiry"]["id"])
    assert inquiry["status"] == INQUIRY_DRAFTING


def test_publishing_the_citation_makes_the_identical_submission_succeed(api):
    """The same call that was refused succeeds once the cited row is PUBLISHED.

    PRD §3.6: "One content rule is enforced at this station: a draft whose
    `disclosure_class` is `GUIDANCE_REPEAT` must carry a non-null
    `cited_disclosure_id` and the disclosure it names must be in status `PUBLISHED` at
    that moment; a missing citation or an unpublished one is refused with
    `ERR_CITATION_REQUIRED`."
    PRD §3.6: "A successful submission increments the draft's `version` by 1 and drives
    the parent inquiry `DRAFTING` → `AWAITING_APPROVAL`, incrementing the inquiry's
    `version` by 1."
    PRD §3.4: "A successful publication stamps `published_at` with the logical clock,
    sets `status` to `PUBLISHED` and increments the row's `version` by 1."

    Design: Corner/validations/guidance_repeat_draft_needs_a_published_citation
    """
    world = _build_citation_world(api)
    draft = world["cited_draft"]
    inquiry_id = world["second_inquiry"]["id"]

    validate_error(
        api.submit_draft_for_review(draft["id"], IR_ANALYST),
        ApiErrorId.CITATION_REQUIRED.value,
        422,
    )
    inquiry_before = fixtures.read_inquiry(api, inquiry_id)

    published = validate_success(
        api.publish_disclosure(world["disclosure"]["id"], DISCLOSURE_OFFICER), 200
    )
    assertions.assert_disclosure(published, status=DISCLOSURE_STATUS_PUBLISHED)
    assertions.assert_ts_equals(published["published_at"], CLOCK, "published_at")

    accepted = validate_success(
        api.submit_draft_for_review(draft["id"], IR_ANALYST), 200
    )
    assertions.assert_response_draft(accepted, status=DRAFT_IN_REVIEW)
    assertions.assert_version(accepted, draft["version"] + 1, "ResponseDraft")

    inquiry_after = fixtures.read_inquiry(api, inquiry_id)
    assert inquiry_after["status"] == INQUIRY_AWAITING_APPROVAL
    assertions.assert_version(
        inquiry_after, inquiry_before["version"] + 1, "InquiryTicket"
    )

    # The uncited draft on the other inquiry is untouched by all of this.
    other = fixtures.read_draft(api, world["uncited_draft"]["id"])
    assert other["status"] == DRAFT_DRAFT
    assert fixtures.read_inquiry(api, world["first_inquiry"]["id"])["status"] == (
        INQUIRY_DRAFTING
    )


# ---------------------------------------------------------------------------
# MATERIAL_NONPUBLIC can never be approved
# ---------------------------------------------------------------------------


def _build_material_nonpublic_review(api):
    """A MATERIAL_NONPUBLIC draft sitting IN_REVIEW under an OPEN issuer."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api,
        ticker="MNP",
        legal_name="Selective Disclosure Corp",
        shares_outstanding=1000000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Curious Fund",
        email="mnp@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    pipeline = fixtures.build_answer_pipeline(
        api,
        company["id"],
        holder["id"],
        stage="in_review",
        topic_category=TOPIC_MODEL_REQUEST,
        subject="Segment detail for the current quarter.",
        body_text="Unreleased segment revenue is 412.5m.",
        disclosure_class=CLASS_MATERIAL_NONPUBLIC,
    )
    pipeline["company"] = company
    pipeline["holder"] = holder
    return pipeline


def test_approving_a_material_nonpublic_draft_is_blocked_under_an_open_posture(api):
    """Posture is OPEN and the pinned version is current, so only the class can fail.

    PRD §3.6: "The draft's `disclosure_class` must not be `MATERIAL_NONPUBLIC` — such a
    draft can *never* be approved, regardless of posture, regardless of role, and the
    refusal is `ERR_SELECTIVE_DISCLOSURE_BLOCKED`."
    PRD §3.6: "Both branches stamp the acting user as `reviewer_user_id` and increment
    both the draft's `version` and the parent inquiry's `version` by 1."

    Design: Corner/validations/material_nonpublic_draft_can_never_be_approved
    """
    world = _build_material_nonpublic_review(api)
    draft_id = world["draft_id"]
    inquiry_id = world["inquiry_id"]

    inquiry_version = fixtures.inquiry_version(api, inquiry_id)
    assert inquiry_version == 4, (
        "intake, routing, opening the draft and submitting it each bumped the inquiry"
    )

    refused = api.review_draft(
        draft_id,
        factories.review_payload(DECISION_APPROVE, inquiry_version),
        DISCLOSURE_OFFICER,
    )
    validate_error(refused, ApiErrorId.SELECTIVE_DISCLOSURE_BLOCKED.value, 422)

    unchanged_draft = fixtures.read_draft(api, draft_id)
    assertions.assert_response_draft(
        unchanged_draft,
        status=DRAFT_IN_REVIEW,
        reviewer_user_id=None,
        pinned_disclosure_version=None,
    )
    assertions.assert_version(unchanged_draft, 2, "ResponseDraft")

    unchanged_inquiry = fixtures.read_inquiry(api, inquiry_id)
    assert unchanged_inquiry["status"] == INQUIRY_AWAITING_APPROVAL
    assertions.assert_version(unchanged_inquiry, inquiry_version, "InquiryTicket")


def test_request_changes_still_works_after_the_selective_disclosure_refusal(api):
    """The refused APPROVE advanced nothing, so the same pinned version still decides.

    PRD §3.6: "The draft's `disclosure_class` must not be `MATERIAL_NONPUBLIC` — such a
    draft can *never* be approved, regardless of posture, regardless of role, and the
    refusal is `ERR_SELECTIVE_DISCLOSURE_BLOCKED`."
    PRD §3.6: "The branch moves the draft `IN_REVIEW` → `CHANGES_REQUESTED`, stores the
    supplied note as `reviewer_note`, and rewinds the parent inquiry
    `AWAITING_APPROVAL` → `DRAFTING` with `sla_due_at` recomputed from the logical clock
    and the inquiry's current queue allowance."
    PRD §3.6: "A permitted revision returns the draft to `DRAFT`, increases
    `revision_round` by 1, clears `blocked_reason` back to null, clears `reviewer_note`
    back to null, clears `pinned_disclosure_version` back to null, and replaces
    `body_text`, `disclosure_class` and `cited_disclosure_id` with whichever of those
    three the author supplied, leaving the others as they were."

    Design: Corner/validations/material_nonpublic_draft_can_never_be_approved
    """
    world = _build_material_nonpublic_review(api)
    draft_id = world["draft_id"]
    inquiry_id = world["inquiry_id"]

    inquiry_version = fixtures.inquiry_version(api, inquiry_id)
    validate_error(
        api.review_draft(
            draft_id,
            factories.review_payload(DECISION_APPROVE, inquiry_version),
            DISCLOSURE_OFFICER,
        ),
        ApiErrorId.SELECTIVE_DISCLOSURE_BLOCKED.value,
        422,
    )

    note = "Reclassify to public-domain language before resubmitting."
    changed = validate_success(
        api.review_draft(
            draft_id,
            factories.review_payload(DECISION_REQUEST_CHANGES, inquiry_version, note),
            DISCLOSURE_OFFICER,
        ),
        200,
    )
    assertions.assert_response_draft(
        changed,
        status=DRAFT_CHANGES_REQUESTED,
        reviewer_user_id=DISCLOSURE_OFFICER_USER_ID,
        reviewer_note=note,
        pinned_disclosure_version=None,
    )
    assertions.assert_version(changed, 3, "ResponseDraft")

    rewound = fixtures.read_inquiry(api, inquiry_id)
    assert rewound["status"] == INQUIRY_DRAFTING
    assertions.assert_version(rewound, inquiry_version + 1, "InquiryTicket")

    revised = validate_success(
        api.revise_draft(
            draft_id,
            factories.revise_payload(
                body_text="We do not comment beyond our published disclosures.",
                disclosure_class=CLASS_PUBLIC_DOMAIN,
            ),
            IR_ANALYST,
        ),
        200,
    )
    assertions.assert_response_draft(
        revised,
        status=DRAFT_DRAFT,
        revision_round=2,
        disclosure_class=CLASS_PUBLIC_DOMAIN,
        reviewer_note=None,
        blocked_reason=None,
        pinned_disclosure_version=None,
        body_text="We do not comment beyond our published disclosures.",
    )
    assertions.assert_version(revised, 4, "ResponseDraft")
    assert fixtures.read_inquiry(api, inquiry_id)["status"] == INQUIRY_DRAFTING


# ---------------------------------------------------------------------------
# One stored BLACKOUT posture gates three unrelated operations
# ---------------------------------------------------------------------------


def _build_blackout_world(api):
    """An issuer whose stored posture has been recomputed to BLACKOUT.

    Prepared while the clock is outside the quiet period: a holder, an analyst with
    an NDA, a PUBLIC_DOMAIN draft IN_REVIEW and an open event holding one REQUESTED
    meeting request. The clock is then moved inside the window and the posture is
    recomputed.
    """
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api,
        ticker="BLK",
        legal_name="Blackout Gate Corp",
        shares_outstanding=1000000,
        blackout_window_start="2026-08-10T00:00:00Z",
        blackout_window_end="2026-08-20T00:00:00Z",
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        120000,
        display_name="Blackout Holder",
        email="blk1@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        nda_on_file=True,
    )
    analyst = fixtures.create_analyst(
        api,
        company["id"],
        display_name="Blackout Analyst",
        email="blk2@bank.test",
        nda_on_file=True,
    )
    pipeline = fixtures.build_answer_pipeline(
        api,
        company["id"],
        holder["id"],
        stage="in_review",
        topic_category=TOPIC_GUIDANCE,
        subject="Anything new on the range?",
        body_text="Nothing beyond our published disclosures.",
        disclosure_class=CLASS_PUBLIC_DOMAIN,
    )
    event, requests = fixtures.build_open_event_with_requests(
        api,
        company["id"],
        [(holder["id"], "2026-09-01T13:00:00Z", "2026-09-01T13:30:00Z")],
        capacity_slots=2,
        event_type=EVENT_CONFERENCE,
        venue_city="Tokyo",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
    )

    fixtures.set_clock(api, "2026-08-12T00:00:00Z")
    issuer = fixtures.recompute_posture(api, company["id"])
    assert issuer["disclosure_posture"] == POSTURE_BLACKOUT

    return {
        "company": issuer,
        "holder": holder,
        "analyst": analyst,
        "inquiry_id": pipeline["inquiry_id"],
        "draft_id": pipeline["draft_id"],
        "event": event,
        "request": requests[0],
    }


def test_blackout_posture_blocks_draft_approval(api):
    """A PUBLIC_DOMAIN draft with a current pinned version is stopped by the posture.

    PRD §2.7: "The first four are hard gates — when the stored posture is `BLACKOUT`
    they are refused with `ERR_DISCLOSURE_BLACKOUT` (HTTP 409)."
    PRD §3.6: "The issuer's stored `disclosure_posture` must not be `BLACKOUT`, or the
    approval is refused with `ERR_DISCLOSURE_BLACKOUT`."
    PRD §3.1: "When the refresh lands on `BLACKOUT`, it does not stop at the issuer row:
    every response draft of that issuer sitting in `IN_REVIEW` whose `disclosure_class`
    is `MATERIAL_NONPUBLIC` is forced to `BLOCKED` with `blocked_reason` set to
    `POSTURE_BLACKOUT`, and each of those drafts' inquiry tickets is rewound from
    `AWAITING_APPROVAL` to `DRAFTING` with a freshly computed `sla_due_at`."

    Design: Corner/validations/blackout_posture_gates_approval_allocation_and_model_access
    """
    world = _build_blackout_world(api)
    inquiry_version = fixtures.inquiry_version(api, world["inquiry_id"])

    refused = api.review_draft(
        world["draft_id"],
        factories.review_payload(DECISION_APPROVE, inquiry_version),
        DISCLOSURE_OFFICER,
    )
    validate_error(refused, ApiErrorId.DISCLOSURE_BLACKOUT.value, 409)

    draft = fixtures.read_draft(api, world["draft_id"])
    assertions.assert_response_draft(
        draft,
        status=DRAFT_IN_REVIEW,
        blocked_reason=None,
        reviewer_user_id=None,
    )
    inquiry = fixtures.read_inquiry(api, world["inquiry_id"])
    assert inquiry["status"] == INQUIRY_AWAITING_APPROVAL
    assertions.assert_version(inquiry, inquiry_version, "InquiryTicket")


def test_blackout_posture_blocks_the_allocation_waterfall(api):
    """The event is open and holds a REQUESTED bid, so only the posture can refuse it.

    PRD §2.7: "The first four are hard gates — when the stored posture is `BLACKOUT`
    they are refused with `ERR_DISCLOSURE_BLACKOUT` (HTTP 409)."
    PRD §3.8: "Three preconditions guard it: the event must be in `OPEN_FOR_REQUESTS`
    (otherwise `ERR_EVENT_INVALID_STATE`), the issuer's stored `disclosure_posture` must
    not be `BLACKOUT` (otherwise `ERR_DISCLOSURE_BLACKOUT`, since a quiet period is no
    time to be taking investor meetings), and at least one of the event's requests must
    be in `REQUESTED` (otherwise `ERR_NO_PENDING_REQUESTS`)."

    Design: Corner/validations/blackout_posture_gates_approval_allocation_and_model_access
    """
    world = _build_blackout_world(api)
    event = fixtures.read_event(api, world["event"]["id"])
    assert event["status"] == EVENT_OPEN_FOR_REQUESTS

    refused = api.allocate_event(event["id"], IR_ADMIN)
    validate_error(refused, ApiErrorId.DISCLOSURE_BLACKOUT.value, 409)

    after = fixtures.read_event(api, event["id"])
    assertions.assert_roadshow_event(
        after,
        status=EVENT_OPEN_FOR_REQUESTS,
        allocated_count=0,
        waitlisted_count=0,
        request_ledger_total=1,
    )
    assertions.assert_version(after, event["version"], "RoadshowEvent")

    request = fixtures.read_meeting_request(api, world["request"]["id"])
    assertions.assert_meeting_request(
        request,
        status=REQUEST_REQUESTED,
        final_priority_score=None,
        allocated_at=None,
    )


def test_blackout_posture_blocks_a_model_access_grant(api):
    """The analyst clears both the eligibility and NDA gates, so the posture decides.

    PRD §2.7: "The first four are hard gates — when the stored posture is `BLACKOUT`
    they are refused with `ERR_DISCLOSURE_BLACKOUT` (HTTP 409)."
    PRD §3.3: "And the issuer's stored `disclosure_posture` must not be `BLACKOUT`,
    because distributing a model during a quiet period is exactly the selective
    disclosure this system exists to prevent; a blackout is refused with
    `ERR_DISCLOSURE_BLACKOUT`."
    PRD §3.2: "Three fields are seeded by the system and cannot be supplied at creation:
    `model_access_status` starts at `NONE`, `threat_level` starts at `NONE`, and
    `dividend_received_cents` starts at 0."

    Design: Corner/validations/blackout_posture_gates_approval_allocation_and_model_access
    """
    world = _build_blackout_world(api)
    analyst = fixtures.read_contact(api, world["analyst"]["id"])
    assertions.assert_contact(analyst, model_access_status=MODEL_ACCESS_NONE)

    refused = api.servicing(
        analyst["id"],
        factories.servicing_payload(SERVICING_GRANT_MODEL_ACCESS),
        DISCLOSURE_OFFICER,
    )
    validate_error(refused, ApiErrorId.DISCLOSURE_BLACKOUT.value, 409)

    after = fixtures.read_contact(api, analyst["id"])
    assertions.assert_contact(after, model_access_status=MODEL_ACCESS_NONE)
    assertions.assert_version(after, analyst["version"], "Contact")


# ---------------------------------------------------------------------------
# Meeting slots must match the window and the fixed slot length
# ---------------------------------------------------------------------------


def _build_slot_world(api):
    """A 30-minute grid running 13:00 to 18:00 with one institutional holder."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="SLT", legal_name="Slot Rules Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Slot Holder",
        email="slt@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    event = fixtures.open_event(
        api,
        company["id"],
        event_type=EVENT_NDR,
        venue_city="Boston",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
        capacity_slots=4,
    )
    return company, holder, event


def _request_slot(api, event_id, contact_id, start, end):
    return api.create_meeting_request(
        factories.meeting_request_payload(
            event_id,
            contact_id,
            requested_slot_start=start,
            requested_slot_end=end,
        ),
        IR_ADMIN,
    )


def test_slot_of_the_wrong_length_inside_the_window_is_refused(api):
    """A 45-minute slot fully inside the window fails only the duration rule.

    PRD §3.8: "And the slot's length in minutes — the end instant minus the start
    instant, the slot itself being half-open so the end instant is not part of it — must
    exactly equal the event's `slot_minutes`; anything longer or shorter is refused with
    `ERR_SLOT_DURATION_INVALID`."

    Design: Corner/validations/meeting_slot_must_match_the_window_and_the_slot_length
    """
    _company, holder, event = _build_slot_world(api)

    refused = _request_slot(
        api,
        event["id"],
        holder["id"],
        "2026-09-01T14:00:00Z",
        "2026-09-01T14:45:00Z",
    )
    validate_error(refused, ApiErrorId.SLOT_DURATION_INVALID.value, 422)

    after = fixtures.read_event(api, event["id"])
    assertions.assert_roadshow_event(after, request_ledger_total=0)
    assertions.assert_version(after, event["version"], "RoadshowEvent")


def test_correctly_sized_slot_starting_before_the_window_is_refused(api):
    """A 30-minute slot is the right length but starts before window_start.

    PRD §3.8: "The slot must sit entirely inside the event's meeting window, meaning
    `requested_slot_start` is at or after `window_start` and `requested_slot_end` is at
    or before `window_end`; a slot poking out either side is refused with
    `ERR_SLOT_OUT_OF_WINDOW`."

    Design: Corner/validations/meeting_slot_must_match_the_window_and_the_slot_length
    """
    _company, holder, event = _build_slot_world(api)

    refused = _request_slot(
        api,
        event["id"],
        holder["id"],
        "2026-09-01T12:30:00Z",
        "2026-09-01T13:00:00Z",
    )
    validate_error(refused, ApiErrorId.SLOT_OUT_OF_WINDOW.value, 422)

    after = fixtures.read_event(api, event["id"])
    assertions.assert_roadshow_event(after, request_ledger_total=0)
    assertions.assert_version(after, event["version"], "RoadshowEvent")


def test_slot_flush_against_window_start_is_accepted_after_both_refusals(api):
    """Neither refused bid was stored, so the flush slot cannot double-book.

    PRD §3.8: "A surviving request is born in `REQUESTED` with `final_priority_score`
    null, `allocated_at` null, `release_reason` null and `promoted_from_waitlist` false,
    and it increments the parent event's `request_ledger_total` by 1 along with the
    event's `version`."
    PRD §3.8: "Nobody can be in two meetings at once, and management needs travel time
    between them, so a request collides with any *other* meeting request of the same
    contact whose status is `REQUESTED`, `ALLOCATED` or `WAITLISTED` when the two
    intervals overlap after the stored one is padded by half an hour on each side."

    Design: Corner/validations/meeting_slot_must_match_the_window_and_the_slot_length
    """
    _company, holder, event = _build_slot_world(api)

    validate_error(
        _request_slot(
            api, event["id"], holder["id"], "2026-09-01T14:00:00Z", "2026-09-01T14:45:00Z"
        ),
        ApiErrorId.SLOT_DURATION_INVALID.value,
        422,
    )
    validate_error(
        _request_slot(
            api, event["id"], holder["id"], "2026-09-01T12:30:00Z", "2026-09-01T13:00:00Z"
        ),
        ApiErrorId.SLOT_OUT_OF_WINDOW.value,
        422,
    )

    accepted = validate_success(
        _request_slot(
            api, event["id"], holder["id"], "2026-09-01T13:00:00Z", "2026-09-01T13:30:00Z"
        ),
        201,
    )
    assertions.assert_meeting_request(
        accepted,
        status=REQUEST_REQUESTED,
        final_priority_score=None,
        allocated_at=None,
        release_reason=None,
        promoted_from_waitlist=False,
    )

    after = fixtures.read_event(api, event["id"])
    assertions.assert_roadshow_event(after, request_ledger_total=1)
    assertions.assert_version(after, event["version"] + 1, "RoadshowEvent")


# ---------------------------------------------------------------------------
# Instruction dates against the clock and the ten-day payable lag
# ---------------------------------------------------------------------------


def _build_dividend_issuer(api):
    """An issuer with a funded reserve and one holder, clock at the default instant."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api,
        ticker="DTE",
        legal_name="Dividend Timing Corp",
        shares_outstanding=1000000,
        dividend_reserve_cents=100000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        1000,
        display_name="Dividend Timing Holder",
        email="dte@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    return company, holder


def test_record_date_before_the_clocks_calendar_date_is_refused(api):
    """A RECORD_DATE_SET needs no payable date, so only the clock comparison can fail.

    PRD §3.9: "`record_date` is the date on which the holder snapshot is taken and is
    required for both `RECORD_DATE_SET` and `DIVIDEND_PAYMENT`; it is compared against
    the logical clock at UTC calendar-date granularity, and a record date whose calendar
    date falls earlier than the clock's current calendar date is refused with
    `ERR_RECORD_DATE_IN_PAST`."

    Design: Corner/validations/instruction_dates_respect_the_clock_and_the_payable_lag
    """
    company, _holder = _build_dividend_issuer(api)

    refused = api.create_instruction(
        factories.instruction_payload(
            company["id"],
            instruction_type=INSTRUCTION_RECORD_DATE_SET,
            record_date="2026-07-31",
        ),
        IR_ADMIN,
    )
    validate_error(refused, ApiErrorId.RECORD_DATE_IN_PAST.value, 422)

    rows, meta = validate_paginated(
        api.list_instructions(IR_ADMIN, company_id=company["id"])
    )
    assert meta["total_count"] == 0 and rows == [], (
        "a refused instruction must not have been written"
    )


def test_payable_date_nine_days_after_the_record_date_is_refused(api):
    """Both dates are in the future, so only the ten-day lag rule can fail.

    PRD §3.9: "`payable_date` is the date the dividend becomes payable and is required
    for `DIVIDEND_PAYMENT`; its calendar date must be at least ten days after the record
    date's calendar date, and a shorter lag is refused with
    `ERR_PAYABLE_DATE_TOO_EARLY`."

    Design: Corner/validations/instruction_dates_respect_the_clock_and_the_payable_lag
    """
    company, _holder = _build_dividend_issuer(api)

    refused = api.create_instruction(
        factories.dividend_instruction_payload(
            company["id"],
            record_date="2026-08-15",
            payable_date="2026-08-24",
            declared_rate_cents_per_share=1.0000,
        ),
        IR_ADMIN,
    )
    validate_error(refused, ApiErrorId.PAYABLE_DATE_TOO_EARLY.value, 422)

    rows, meta = validate_paginated(
        api.list_instructions(IR_ADMIN, company_id=company["id"])
    )
    assert meta["total_count"] == 0 and rows == [], (
        "a refused instruction must not have been written"
    )


def test_payable_date_exactly_ten_days_out_is_accepted_after_both_refusals(api):
    """The two refusals stored no cycle, so the accepted one cannot collide.

    PRD §3.9: "`payable_date` is the date the dividend becomes payable and is required
    for `DIVIDEND_PAYMENT`; its calendar date must be at least ten days after the record
    date's calendar date, and a shorter lag is refused with
    `ERR_PAYABLE_DATE_TOO_EARLY`."
    PRD §3.9: "A new instruction is born in `SUBMITTED` with `acknowledged_by_user_id`,
    `executed_by_user_id`, `snapshot_holder_count`, `snapshot_shares_total`,
    `payout_ledger`, `total_payout_cents`, `executed_at` and `decision_reason` all null,
    and `version` at 1."
    PRD §3.9: "`funding_mode` selects which payout variant will run and is either
    `DECLARED_RATE` or `RESERVE_CAPPED`, defaulting to `DECLARED_RATE` for a dividend
    instruction."

    Design: Corner/validations/instruction_dates_respect_the_clock_and_the_payable_lag
    """
    company, _holder = _build_dividend_issuer(api)

    validate_error(
        api.create_instruction(
            factories.instruction_payload(
                company["id"],
                instruction_type=INSTRUCTION_RECORD_DATE_SET,
                record_date="2026-07-31",
            ),
            IR_ADMIN,
        ),
        ApiErrorId.RECORD_DATE_IN_PAST.value,
        422,
    )
    validate_error(
        api.create_instruction(
            factories.dividend_instruction_payload(
                company["id"], record_date="2026-08-15", payable_date="2026-08-24"
            ),
            IR_ADMIN,
        ),
        ApiErrorId.PAYABLE_DATE_TOO_EARLY.value,
        422,
    )

    accepted = validate_success(
        api.create_instruction(
            factories.dividend_instruction_payload(
                company["id"],
                record_date="2026-08-15",
                payable_date="2026-08-25",
                declared_rate_cents_per_share=1.0000,
            ),
            IR_ADMIN,
        ),
        201,
    )
    assertions.assert_instruction(
        accepted,
        instruction_type=INSTRUCTION_DIVIDEND_PAYMENT,
        status=INSTRUCTION_SUBMITTED,
        funding_mode=FUNDING_DECLARED_RATE,
        submitted_by_user_id=IR_ADMIN_USER_ID,
        acknowledged_by_user_id=None,
        executed_by_user_id=None,
        snapshot_holder_count=None,
        snapshot_shares_total=None,
        payout_ledger=None,
        total_payout_cents=None,
        executed_at=None,
        decision_reason=None,
    )
    assert accepted["record_date"] == "2026-08-15"
    assert accepted["payable_date"] == "2026-08-25"
    assertions.assert_version(accepted, 1, "TransferAgentInstruction")

    stored = fixtures.read_instruction(api, accepted["id"])
    assert stored["status"] == INSTRUCTION_SUBMITTED


# ---------------------------------------------------------------------------
# The role check outranks path existence
# ---------------------------------------------------------------------------


def test_publishing_a_missing_disclosure_as_an_analyst_is_403_not_404(api):
    """Authorisation sits above path existence in the fixed precedence order.

    PRD §2.10: "Checks therefore run in a fixed order, and the **first** check to fail
    decides the response; later checks are never reached."
    PRD §2.1: "When both headers are well formed but the named role does not appear on
    the endpoint's authorised-role list in §4, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.4: "A `DisclosureOfficer` owns it exclusively, and no other role may create,
    publish or withdraw one."

    Design: Corner/validations/role_check_outranks_path_existence_returns_403
    """
    fixtures.set_clock(api, CLOCK)

    unauthorised = api.publish_disclosure(NON_EXISTENT_UUID, IR_ANALYST)
    validate_error(unauthorised, ApiErrorId.UNAUTHORIZED.value, 403)
    envelope = unauthorised.json()
    assert envelope["response_type"] == "error"
    assert envelope["meta"]["api_request_id"].startswith("req_")


def test_the_same_missing_path_is_404_for_the_owning_role(api):
    """With the role check satisfied the request falls through to path existence.

    PRD §2.10: "Checks therefore run in a fixed order, and the **first** check to fail
    decides the response; later checks are never reached."
    PRD §3.4: "Addressing a disclosure that does not exist — or citing one that does not
    exist — yields `ERR_DISCLOSURE_NOT_FOUND`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/validations/role_check_outranks_path_existence_returns_403
    """
    fixtures.set_clock(api, CLOCK)

    validate_error(
        api.publish_disclosure(NON_EXISTENT_UUID, IR_ANALYST),
        ApiErrorId.UNAUTHORIZED.value,
        403,
    )

    missing = api.publish_disclosure(NON_EXISTENT_UUID, DISCLOSURE_OFFICER)
    validate_error(missing, ApiErrorId.DISCLOSURE_NOT_FOUND.value, 404)
    envelope = missing.json()
    assert envelope["response_type"] == "error"
    assert envelope["meta"]["api_request_id"].startswith("req_")
