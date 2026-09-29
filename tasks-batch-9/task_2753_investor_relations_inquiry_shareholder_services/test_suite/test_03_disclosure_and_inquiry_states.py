"""Disclosure publication/withdrawal states and inquiry routing/escalation states.

Every test in this module translates exactly one corner-design instance of the
``state_machines`` section: the declared initial states of an inquiry ticket and
a roadshow event, the Disclosure DRAFT/PUBLISHED/WITHDRAWN machine, and the
InquiryTicket NEW/ROUTED/ESCALATED machine with its queue-override restriction.

The server is restarted before each test, so every world is built in-test
through the documented endpoints with the logical clock moved explicitly.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    CONTACT_INSTITUTIONAL_HOLDER,
    CONTACT_RETAIL_HOLDER,
    CONTACT_SELL_SIDE_ANALYST,
    DISCLOSURE_FORM_8K,
    DISCLOSURE_GUIDANCE_UPDATE,
    DISCLOSURE_OFFICER,
    DISCLOSURE_PRESS_RELEASE,
    DISCLOSURE_STATUS_DRAFT,
    DISCLOSURE_STATUS_PUBLISHED,
    DISCLOSURE_STATUS_WITHDRAWN,
    EVENT_NDR,
    EVENT_PLANNING,
    INQUIRY_ESCALATED,
    INQUIRY_NEW,
    INQUIRY_ROUTED,
    IR_ADMIN,
    IR_ANALYST,
    METRIC_EPS,
    QUEUE_DISCLOSURE_COMMITTEE,
    QUEUE_IR_DESK,
    TOPIC_GUIDANCE,
    TOPIC_MODEL_REQUEST,
    TOPIC_PROXY,
    assertions,
    fixtures,
    validate_error,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_DAY_TWO = "2026-08-02T00:00:00Z"
CLOCK_PUBLISH = "2026-08-05T12:00:00Z"


# ---------------------------------------------------------------------------
# Corner/state_machines/inquiry_and_event_start_in_their_declared_initial_states
# ---------------------------------------------------------------------------


def test_inquiry_intake_is_born_new_with_no_answered_at(api: ApiClient):
    """PRD §3.5: "A new ticket is born in status `NEW`, with `answered_at` null, and intake recounts the issuer's `open_inquiry_count` and increments the issuer's `version` by 1."

    PRD §2.5: "`version` (integer): a counter that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/inquiry_and_event_start_in_their_declared_initial_states
    """
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="INI", legal_name="Initial State Corp", shares_outstanding=1000000
    )
    contact = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_RETAIL_HOLDER,
        display_name="Init Holder",
        email="ini@retail.test",
        shares_held=100,
    )

    response = api.create_inquiry(
        {
            "company_id": company["id"],
            "contact_id": contact["id"],
            "topic_category": TOPIC_PROXY,
            "subject": "How do I vote my shares?",
        },
        IR_ANALYST,
    )
    inquiry = validate_success(response, 201)

    assertions.assert_inquiry(
        inquiry, status=INQUIRY_NEW, answered_at=None, version=1
    )
    reread = fixtures.read_inquiry(api, inquiry["id"])
    assert reread["status"] == INQUIRY_NEW
    assert reread["answered_at"] is None
    assert fixtures.read_company(api, company["id"])["open_inquiry_count"] == 1


def test_roadshow_event_is_born_planning_with_zeroed_counters(api: ApiClient):
    """PRD §3.8: "A new event is born in `PLANNING`, with `allocated_count`, `waitlisted_count`, `released_count`, `declined_count` and `request_ledger_total` all at zero and `version` at 1."

    Design: Corner/state_machines/inquiry_and_event_start_in_their_declared_initial_states
    """
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="INI", legal_name="Initial State Corp", shares_outstanding=1000000
    )

    response = api.create_roadshow_event(
        {
            "company_id": company["id"],
            "event_type": EVENT_NDR,
            "venue_city": "Chicago",
            "window_start": "2026-09-01T13:00:00Z",
            "window_end": "2026-09-01T18:00:00Z",
            "slot_minutes": 30,
            "capacity_slots": 2,
        },
        IR_ADMIN,
    )
    event = validate_success(response, 201)

    assertions.assert_roadshow_event(
        event,
        status=EVENT_PLANNING,
        allocated_count=0,
        waitlisted_count=0,
        released_count=0,
        declined_count=0,
        request_ledger_total=0,
        version=1,
    )
    reread = fixtures.read_event(api, event["id"])
    assertions.assert_roadshow_event(
        reread,
        status=EVENT_PLANNING,
        allocated_count=0,
        waitlisted_count=0,
        released_count=0,
        declined_count=0,
        request_ledger_total=0,
        version=1,
    )


# ---------------------------------------------------------------------------
# Corner/state_machines/disclosure_publish_stamps_published_at_from_the_logical_clock
# ---------------------------------------------------------------------------


def test_disclosure_publish_stamps_published_at_from_the_clock(api: ApiClient):
    """PRD §3.4: "A successful publication stamps `published_at` with the logical clock, sets `status` to `PUBLISHED` and increments the row's `version` by 1."

    PRD §3.4: "A new row is born in `DRAFT` with `published_at` null and `version` 1."

    PRD §3.4: "The `is_guidance` flag is not an operator's opinion but a derivation: it is true exactly when `disclosure_type` is `GUIDANCE_UPDATE` and `metric` is anything other than `NONE`, and it is that flag which selects the row into the consensus guidance band of §3.7."

    PRD §3.4: "Withdrawal is the destructive operation, and it takes a required non-empty `reason` string which is stored on the row as `withdrawal_reason` — a field that is null on every disclosure that has not been withdrawn."

    Design: Corner/state_machines/disclosure_publish_stamps_published_at_from_the_logical_clock
    """
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="PUB", legal_name="Publish Corp", shares_outstanding=1000000
    )
    disclosure = fixtures.create_disclosure(
        api,
        company["id"],
        disclosure_type=DISCLOSURE_PRESS_RELEASE,
        fact_key="PR-Q3-BUYBACK",
    )
    assertions.assert_disclosure(
        disclosure, status=DISCLOSURE_STATUS_DRAFT, published_at=None, version=1
    )

    # The clock moves after creation, so published_at can only come from the clock.
    fixtures.set_clock(api, CLOCK_PUBLISH)
    published = validate_success(api.publish_disclosure(disclosure["id"], DISCLOSURE_OFFICER))

    assertions.assert_disclosure(
        published,
        status=DISCLOSURE_STATUS_PUBLISHED,
        version=2,
        is_guidance=False,
        withdrawal_reason=None,
    )
    assertions.assert_ts_equals(published["published_at"], "2026-08-05T12:00:00.000Z", "published_at")

    reread = fixtures.read_disclosure(api, disclosure["id"])
    assert reread["status"] == DISCLOSURE_STATUS_PUBLISHED
    assert reread["version"] == 2
    assertions.assert_ts_equals(reread["published_at"], "2026-08-05T12:00:00.000Z", "published_at")


# ---------------------------------------------------------------------------
# Corner/state_machines/guidance_publish_without_period_label_rejected
# ---------------------------------------------------------------------------


def test_guidance_publish_without_period_label_is_refused(api: ApiClient):
    """PRD §3.4: "A guidance row faces one extra gate at this moment: if `disclosure_type` is `GUIDANCE_UPDATE`, then `metric` must not be `NONE`, `period_label` must not be null, both `guidance_low` and `guidance_high` must be present, and the low end must be less than or equal to the high end — a guidance row that fails any of these is refused with `ERR_INVALID_REQUEST` at publication time even though it was allowed to exist as a draft."

    PRD §3.4: "The `is_guidance` flag is not an operator's opinion but a derivation: it is true exactly when `disclosure_type` is `GUIDANCE_UPDATE` and `metric` is anything other than `NONE`, and it is that flag which selects the row into the consensus guidance band of §3.7."

    Design: Corner/state_machines/guidance_publish_without_period_label_rejected
    """
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api,
        ticker="GPL",
        legal_name="Guidance Precondition Corp",
        shares_outstanding=1000000,
    )
    # period_label defaults to null at creation, so this row exists but cannot publish.
    disclosure = fixtures.create_disclosure(
        api,
        company["id"],
        disclosure_type=DISCLOSURE_GUIDANCE_UPDATE,
        fact_key="EPS-NO-PERIOD",
        metric=METRIC_EPS,
        guidance_low=2.00,
        guidance_high=2.20,
    )
    assert disclosure["period_label"] is None
    assert disclosure["is_guidance"] is True

    validate_error(
        api.publish_disclosure(disclosure["id"], DISCLOSURE_OFFICER),
        ApiErrorId.INVALID_REQUEST.value,
    )

    reread = fixtures.read_disclosure(api, disclosure["id"])
    assertions.assert_disclosure(
        reread,
        status=DISCLOSURE_STATUS_DRAFT,
        published_at=None,
        version=1,
        is_guidance=True,
    )


# ---------------------------------------------------------------------------
# Corner/state_machines/disclosure_publish_twice_rejected
# ---------------------------------------------------------------------------


def test_publishing_an_already_published_disclosure_is_refused(api: ApiClient):
    """PRD §3.4: "Only a row currently in `DRAFT` may be published; anything else is refused with `ERR_DISCLOSURE_INVALID_STATE`."

    PRD §3.4: "A successful publication stamps `published_at` with the logical clock, sets `status` to `PUBLISHED` and increments the row's `version` by 1."

    Design: Corner/state_machines/disclosure_publish_twice_rejected
    """
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="IDP", legal_name="Idempotent Publish Corp", shares_outstanding=1000000
    )
    disclosure = fixtures.create_disclosure(
        api,
        company["id"],
        disclosure_type=DISCLOSURE_FORM_8K,
        fact_key="8K-2026-08-01",
    )
    first = fixtures.publish_disclosure(api, disclosure["id"])
    assert first["status"] == DISCLOSURE_STATUS_PUBLISHED
    assert first["version"] == 2

    validate_error(
        api.publish_disclosure(disclosure["id"], DISCLOSURE_OFFICER),
        ApiErrorId.DISCLOSURE_INVALID_STATE.value,
    )

    reread = fixtures.read_disclosure(api, disclosure["id"])
    assertions.assert_disclosure(reread, status=DISCLOSURE_STATUS_PUBLISHED, version=2)
    assertions.assert_ts_equals(reread["published_at"], "2026-08-01T00:00:00.000Z", "published_at")


# ---------------------------------------------------------------------------
# Corner/state_machines/withdrawn_draft_disclosure_is_locked_and_cascades_nothing
# ---------------------------------------------------------------------------

WITHDRAW_REASON = "Legal review pulled the release before publication."


def _withdrawn_draft_world(api: ApiClient):
    """One issuer with one disclosure withdrawn straight out of DRAFT."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="WTD", legal_name="Withdrawn Terminal Corp", shares_outstanding=1000000
    )
    disclosure = fixtures.create_disclosure(
        api,
        company["id"],
        disclosure_type=DISCLOSURE_PRESS_RELEASE,
        fact_key="PR-PULLED",
    )
    withdrawn = validate_success(
        api.withdraw_disclosure(disclosure["id"], WITHDRAW_REASON, DISCLOSURE_OFFICER)
    )
    return company, disclosure, withdrawn


def test_withdrawn_draft_disclosure_rejects_publish_and_second_withdraw(api: ApiClient):
    """PRD §3.4: "A disclosure may be withdrawn from `DRAFT` or from `PUBLISHED`; withdrawing one that is already `SUPERSEDED` or `WITHDRAWN` is refused with `ERR_DISCLOSURE_INVALID_STATE`."

    PRD §3.4: "Only a row currently in `DRAFT` may be published; anything else is refused with `ERR_DISCLOSURE_INVALID_STATE`."

    PRD §3.4: "Both origins produce `WITHDRAWN` and both increment the disclosure's `version` by 1, but their blast radii are deliberately different."

    Design: Corner/state_machines/withdrawn_draft_disclosure_is_locked_and_cascades_nothing
    """
    _company, disclosure, withdrawn = _withdrawn_draft_world(api)

    assertions.assert_disclosure(
        withdrawn,
        status=DISCLOSURE_STATUS_WITHDRAWN,
        withdrawal_reason=WITHDRAW_REASON,
        published_at=None,
        version=2,
    )

    validate_error(
        api.publish_disclosure(disclosure["id"], DISCLOSURE_OFFICER),
        ApiErrorId.DISCLOSURE_INVALID_STATE.value,
    )
    validate_error(
        api.withdraw_disclosure(
            disclosure["id"], "Second attempt at the same withdrawal.", DISCLOSURE_OFFICER
        ),
        ApiErrorId.DISCLOSURE_INVALID_STATE.value,
    )

    reread = fixtures.read_disclosure(api, disclosure["id"])
    assertions.assert_disclosure(
        reread,
        status=DISCLOSURE_STATUS_WITHDRAWN,
        withdrawal_reason=WITHDRAW_REASON,
        published_at=None,
        version=2,
    )


def test_draft_withdrawal_touches_no_other_row(api: ApiClient):
    """PRD §3.4: "Withdrawing from `DRAFT` stops at the disclosure row."

    PRD §3.4: "Nothing downstream can exist, because an unpublished row could never have been legitimately cited by an approved draft, so no draft, inquiry or issuer is touched."

    PRD §3.1: "Registration also stamps the derived fields: `disclosure_posture` is derived immediately and `posture_recomputed_at` is stamped with the logical clock, `open_inquiry_count` and `dividend_paid_cents` both begin at zero, and `version` begins at 1."

    Design: Corner/state_machines/withdrawn_draft_disclosure_is_locked_and_cascades_nothing
    """
    company, disclosure, withdrawn = _withdrawn_draft_world(api)

    assert withdrawn["status"] == DISCLOSURE_STATUS_WITHDRAWN
    assert fixtures.read_disclosure(api, disclosure["id"])["version"] == 2
    # The issuer row is untouched by the DRAFT withdrawal branch.
    assertions.assert_company(fixtures.read_company(api, company["id"]), version=1)


# ---------------------------------------------------------------------------
# Corner/state_machines/inquiry_auto_escalates_at_the_sensitivity_threshold
# ---------------------------------------------------------------------------


def _escalation_world(api: ApiClient, ticker: str, legal_name: str, intake_clock: str):
    """An activist analyst's nonpublic MODEL_REQUEST inquiry, scoring exactly 80."""
    fixtures.set_clock(api, intake_clock)
    company = fixtures.create_company(
        api, ticker=ticker, legal_name=legal_name, shares_outstanding=1000000
    )
    contact = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_SELL_SIDE_ANALYST,
        display_name="Activist Analyst",
        email="esc@bank.test",
        activist_flag=True,
    )
    inquiry = fixtures.create_inquiry(
        api,
        company["id"],
        contact["id"],
        topic_category=TOPIC_MODEL_REQUEST,
        subject="Send me the unpublished segment build.",
        requests_nonpublic_detail=True,
    )
    return company, contact, inquiry


def test_inquiry_scoring_eighty_takes_the_escalated_fork(api: ApiClient):
    """PRD §3.5: "A ticket in `NEW` whose score is at least 80 instead transitions `NEW` → `ESCALATED`, and the branches diverge in their side effects: the escalated branch overrides `routing_queue` to `DISCLOSURE_COMMITTEE` regardless of what the four selection clauses computed at intake, and recomputes `sla_due_at` against the disclosure committee's 48-hour allowance."

    PRD §3.5: "The base term comes from the topic: 40 for `GUIDANCE`, 30 for `MODEL_REQUEST`, 20 for `PROXY`, 15 for `DIVIDEND`, 15 for `RECORD_DATE` and 10 for `OTHER`."

    PRD §3.5: "Add 25 when `requests_nonpublic_detail` is true, and nothing when it is false."

    PRD §3.5: "Add 15 when the submitting contact's `contact_type` is `SELL_SIDE_ANALYST`, and nothing otherwise."

    PRD §3.5: "Add 10 when the submitting contact's `activist_flag` is true."

    PRD §3.5: "Each queue carries its own service-level allowance, and the deadline is the logical clock at the moment of the write plus that allowance: 48 hours for `DISCLOSURE_COMMITTEE`, three days (72 hours) for `IR_DESK`, four days (96 hours) for `TRANSFER_AGENT_DESK` and five days (120 hours) for `SHAREHOLDER_SERVICES`."

    PRD §3.5: "Either way the ticket's `version` increments by 1."

    Design: Corner/state_machines/inquiry_auto_escalates_at_the_sensitivity_threshold
    """
    _company, _contact, inquiry = _escalation_world(
        api, "ESC", "Escalation Fork Corp", CLOCK_START
    )
    # 30 (MODEL_REQUEST) + 25 (nonpublic detail) + 15 (analyst) + 10 (activist) = 80.
    assert inquiry["sensitivity_score"] == 80

    fixtures.set_clock(api, CLOCK_DAY_TWO)
    routed = validate_success(api.route_inquiry(inquiry["id"], None, IR_ANALYST))

    assertions.assert_inquiry(
        routed,
        status=INQUIRY_ESCALATED,
        routing_queue=QUEUE_DISCLOSURE_COMMITTEE,
        sensitivity_score=80,
        version=2,
    )
    assertions.assert_ts_equals(routed["sla_due_at"], "2026-08-04T00:00:00.000Z", "sla_due_at")


def test_escalated_inquiry_stays_inside_the_open_inquiry_count(api: ApiClient):
    """PRD §3.5: "Escalation does not change `open_inquiry_count`, because `NEW` and `ESCALATED` are both open statuses."

    PRD §2.11: "It is the number of that issuer's inquiry tickets whose status is `NEW`, `ROUTED`, `DRAFTING`, `AWAITING_APPROVAL` or `ESCALATED` — that is, every status except `ANSWERED`."

    Design: Corner/state_machines/inquiry_auto_escalates_at_the_sensitivity_threshold
    """
    company, _contact, inquiry = _escalation_world(
        api, "ESC", "Escalation Fork Corp", CLOCK_START
    )
    assert fixtures.read_company(api, company["id"])["open_inquiry_count"] == 1

    fixtures.set_clock(api, CLOCK_DAY_TWO)
    routed = fixtures.route_inquiry(api, inquiry["id"])
    assert routed["status"] == INQUIRY_ESCALATED

    assert fixtures.read_company(api, company["id"])["open_inquiry_count"] == 1


# ---------------------------------------------------------------------------
# Corner/state_machines/escalated_inquiry_needs_an_officer_supplied_target_queue
# ---------------------------------------------------------------------------


def _escalated_inquiry(api: ApiClient):
    """An inquiry sitting in ESCALATED with the clock parked at 2026-08-02T00:00:00Z."""
    company, contact, inquiry = _escalation_world(
        api, "OVR", "Queue Override Corp", CLOCK_DAY_TWO
    )
    escalated = fixtures.route_inquiry(api, inquiry["id"])
    assert escalated["status"] == INQUIRY_ESCALATED
    return company, contact, escalated


def test_escalated_inquiry_reroute_without_officer_override_is_refused(api: ApiClient):
    """PRD §3.5: "The same restriction is what makes an escalated ticket recoverable: a ticket in `ESCALATED` transitions `ESCALATED` → `ROUTED` only when a `DisclosureOfficer` supplies `target_queue`, taking the supplied queue and a freshly computed deadline; an attempt to re-route an escalated ticket without a `DisclosureOfficer` supplying `target_queue` is likewise refused with `ERR_QUEUE_OVERRIDE_FORBIDDEN`."

    PRD §3.5: "An `IRAnalyst` supplying `target_queue` is refused with `ERR_QUEUE_OVERRIDE_FORBIDDEN` even though the routing operation itself is open to that role."

    Design: Corner/state_machines/escalated_inquiry_needs_an_officer_supplied_target_queue
    """
    _company, _contact, escalated = _escalated_inquiry(api)

    validate_error(
        api.route_inquiry(escalated["id"], None, IR_ANALYST),
        ApiErrorId.QUEUE_OVERRIDE_FORBIDDEN.value,
    )

    reread = fixtures.read_inquiry(api, escalated["id"])
    assertions.assert_inquiry(
        reread,
        status=INQUIRY_ESCALATED,
        routing_queue=QUEUE_DISCLOSURE_COMMITTEE,
        version=2,
    )


def test_officer_target_queue_moves_escalated_inquiry_to_routed(api: ApiClient):
    """PRD §3.5: "The same restriction is what makes an escalated ticket recoverable: a ticket in `ESCALATED` transitions `ESCALATED` → `ROUTED` only when a `DisclosureOfficer` supplies `target_queue`, taking the supplied queue and a freshly computed deadline; an attempt to re-route an escalated ticket without a `DisclosureOfficer` supplying `target_queue` is likewise refused with `ERR_QUEUE_OVERRIDE_FORBIDDEN`."

    PRD §3.5: "A `DisclosureOfficer` may supply any member of the queue enumeration, in which case `routing_queue` is replaced with the supplied value and `sla_due_at` is recomputed against that queue's allowance."

    PRD §3.5: "`sensitivity_score` is a disclosure-risk score on a 0-to-100 scale, computed once at intake and never recomputed no matter what happens afterwards to the contact, the issuer or the linked inquiry."

    Design: Corner/state_machines/escalated_inquiry_needs_an_officer_supplied_target_queue
    """
    _company, _contact, escalated = _escalated_inquiry(api)

    rerouted = validate_success(
        api.route_inquiry(escalated["id"], QUEUE_IR_DESK, DISCLOSURE_OFFICER)
    )

    assertions.assert_inquiry(
        rerouted,
        status=INQUIRY_ROUTED,
        routing_queue=QUEUE_IR_DESK,
        sensitivity_score=80,
        version=3,
    )
    # 2026-08-02T00:00:00Z + the IR_DESK allowance of 72 hours.
    assertions.assert_ts_equals(rerouted["sla_due_at"], "2026-08-05T00:00:00.000Z", "sla_due_at")

    reread = fixtures.read_inquiry(api, escalated["id"])
    assert reread["status"] == INQUIRY_ROUTED
    assert reread["routing_queue"] == QUEUE_IR_DESK
    assert reread["sensitivity_score"] == 80


# ---------------------------------------------------------------------------
# Corner/state_machines/routed_inquiry_cannot_be_routed_again
# ---------------------------------------------------------------------------


def test_routing_a_routed_inquiry_is_refused(api: ApiClient):
    """PRD §3.5: "Routing a ticket that is in neither `NEW` nor `ESCALATED` is refused with `ERR_INQUIRY_INVALID_STATE`."

    PRD §3.5: "A ticket in `NEW` whose frozen `sensitivity_score` is strictly below 80 transitions `NEW` → `ROUTED`."

    PRD §3.5: "The routed branch leaves `routing_queue` and `sla_due_at` alone unless a queue override was supplied."

    PRD §3.5: "Otherwise the queue is `IR_DESK`."

    Design: Corner/state_machines/routed_inquiry_cannot_be_routed_again
    """
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="RRT", legal_name="Reroute Corp", shares_outstanding=1000000
    )
    contact = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        display_name="Reroute Holder",
        email="rrt@funds.test",
        shares_held=20000,
    )
    # GUIDANCE alone scores 40: below 60, not a retail holder, so the queue is IR_DESK.
    inquiry = fixtures.create_inquiry(
        api,
        company["id"],
        contact["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="Confirm the published range.",
    )
    assert inquiry["sensitivity_score"] == 40

    first = fixtures.route_inquiry(api, inquiry["id"])
    assertions.assert_inquiry(first, status=INQUIRY_ROUTED, routing_queue=QUEUE_IR_DESK, version=2)

    validate_error(
        api.route_inquiry(inquiry["id"], None, IR_ANALYST),
        ApiErrorId.INQUIRY_INVALID_STATE.value,
    )

    reread = fixtures.read_inquiry(api, inquiry["id"])
    assertions.assert_inquiry(
        reread, status=INQUIRY_ROUTED, routing_queue=QUEUE_IR_DESK, version=2
    )
    # The intake-time IR_DESK deadline survives both the route and the refusal.
    assertions.assert_ts_equals(reread["sla_due_at"], "2026-08-04T00:00:00.000Z", "sla_due_at")
