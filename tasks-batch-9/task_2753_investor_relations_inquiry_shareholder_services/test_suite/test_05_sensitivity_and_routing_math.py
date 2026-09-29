"""Intake sensitivity scoring, per-queue SLA allowances and the open-inquiry count.

Each test here exercises one arithmetic corner of inquiry intake and routing:
the six-term sensitivity sum and its ceiling of 100, the four service-level
allowances selected by the queue in force after the write, the exclusive 50
boundary of the transfer-agent desk, and the full recount of the issuer's
``open_inquiry_count`` when an answer is finally dispatched.
"""

from test_helpers import (
    ApiClient,
    CLASS_PUBLIC_DOMAIN,
    CONTACT_INSTITUTIONAL_HOLDER,
    CONTACT_RETAIL_HOLDER,
    CONTACT_SELL_SIDE_ANALYST,
    DEFAULT_CLOCK_UTC,
    DRAFT_SENT,
    INQUIRY_ANSWERED,
    INQUIRY_ESCALATED,
    INQUIRY_NEW,
    IR_ADMIN,
    IR_ANALYST,
    POSTURE_BLACKOUT,
    POSTURE_OPEN,
    QUEUE_DISCLOSURE_COMMITTEE,
    QUEUE_IR_DESK,
    QUEUE_SHAREHOLDER_SERVICES,
    QUEUE_TRANSFER_AGENT_DESK,
    TOPIC_DIVIDEND,
    TOPIC_GUIDANCE,
    TOPIC_MODEL_REQUEST,
    TOPIC_OTHER,
    assertions,
    factories,
    fixtures,
    validate_success,
)

CLOCK = DEFAULT_CLOCK_UTC


# ---------------------------------------------------------------------------
# Local composite setups (test_helpers has no equivalent)
# ---------------------------------------------------------------------------


def _blackout_issuer_with_escalated_prior(api: ApiClient):
    """A BLACKOUT issuer, an activist analyst, and a prior inquiry in ESCALATED."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.blackout_company(
        api,
        ticker="CAP",
        legal_name="Sensitivity Cap Corp",
        shares_outstanding=1000000,
        blackout_window_start="2026-08-01T00:00:00Z",
        blackout_window_end="2026-08-31T00:00:00Z",
    )
    analyst = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_SELL_SIDE_ANALYST,
        display_name="Cap Analyst",
        email="cap@bank.test",
        activist_flag=True,
    )
    prior = fixtures.create_inquiry(
        api,
        company["id"],
        analyst["id"],
        topic_category=TOPIC_MODEL_REQUEST,
        subject="Prior unpublished-detail request.",
        requests_nonpublic_detail=True,
    )
    prior = fixtures.route_inquiry(api, prior["id"])
    return company, analyst, prior


def _open_issuer_with_two_holder_types(api: ApiClient):
    """An OPEN issuer with one retail and one institutional holder."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="SLA", legal_name="SLA Hours Corp", shares_outstanding=1000000
    )
    retail = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_RETAIL_HOLDER,
        display_name="SLA Retail",
        email="sla1@retail.test",
        shares_held=100,
    )
    institution = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        display_name="SLA Institution",
        email="sla2@funds.test",
        shares_held=20000,
    )
    return company, retail, institution


def _threshold_issuer_with_two_funds(api: ApiClient):
    """An OPEN issuer with an activist-flagged fund and a passive fund."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api,
        ticker="THR",
        legal_name="Threshold Routing Corp",
        shares_outstanding=1000000,
    )
    activist = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        display_name="Activist Fund",
        email="thr1@funds.test",
        shares_held=20000,
        activist_flag=True,
    )
    passive = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        display_name="Passive Fund",
        email="thr2@funds.test",
        shares_held=20000,
    )
    return company, activist, passive


def _issuer_with_awaiting_approval_and_new(api: ApiClient):
    """Two GUIDANCE inquiries: the first walked to an APPROVED draft, the second NEW."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="OIC", legal_name="Open Count Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Count Holder",
        email="oic@funds.test",
    )
    first = fixtures.create_inquiry(
        api,
        company["id"],
        holder["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="First question about the range.",
    )
    second = fixtures.create_inquiry(
        api,
        company["id"],
        holder["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="Second question, still open.",
    )
    fixtures.route_inquiry(api, first["id"])
    draft = fixtures.create_draft(
        api,
        first["id"],
        body_text="Our published range is unchanged.",
        disclosure_class=CLASS_PUBLIC_DOMAIN,
    )
    fixtures.submit_for_review(api, draft["id"])
    return company, first, second, draft


# ---------------------------------------------------------------------------
# The six-term sensitivity sum and its ceiling
# ---------------------------------------------------------------------------


def test_sensitivity_score_saturates_at_one_hundred_when_every_term_applies(api: ApiClient):
    """PRD §3.5: "It is built by summing a base term with five conditional terms and then capping the total at 100."
    PRD §3.5: "The base term comes from the topic: 40 for `GUIDANCE`, 30 for `MODEL_REQUEST`, 20 for `PROXY`, 15 for `DIVIDEND`, 15 for `RECORD_DATE` and 10 for `OTHER`."
    PRD §3.5: "Add 25 when `requests_nonpublic_detail` is true, and nothing when it is false."
    PRD §3.5: "Add 15 when the submitting contact's `contact_type` is `SELL_SIDE_ANALYST`, and nothing otherwise."
    PRD §3.5: "Add 10 when the submitting contact's `activist_flag` is true."
    PRD §3.5: "Add 10 when `linked_prior_inquiry_id` is not null **and** the inquiry it names is itself in status `ESCALATED` — a follow-up to a routine inquiry earns nothing."
    PRD §3.5: "Finally add a posture term read from the issuer's `disclosure_posture` as stored at intake: 20 when it is `BLACKOUT`, 10 when it is `RESTRICTED`, and 0 when it is `OPEN`."
    PRD §3.5: "The sum of the base and the five terms is then capped at 100, so a score can never exceed that ceiling."

    Design: Corner/calculations/sensitivity_score_sums_all_six_terms_and_saturates_at_the_cap
    """
    company, analyst, prior = _blackout_issuer_with_escalated_prior(api)

    # The two soft inputs the score reads must be in the states the sum assumes.
    assert fixtures.read_company(api, company["id"])["disclosure_posture"] == POSTURE_BLACKOUT
    assert prior["status"] == INQUIRY_ESCALATED

    response = api.create_inquiry(
        factories.inquiry_payload(
            company["id"],
            analyst["id"],
            topic_category=TOPIC_GUIDANCE,
            subject="Following up on the same unpublished build.",
            requests_nonpublic_detail=True,
            linked_prior_inquiry_id=prior["id"],
        ),
        IR_ANALYST,
    )
    inquiry = validate_success(response, 201)

    # 40 + 25 + 15 + 10 + 10 + 20 = 120, clipped once at the end.
    assertions.assert_inquiry(inquiry, sensitivity_score=100)


def test_capped_sensitivity_score_routes_to_the_committee_without_escalating_at_intake(
    api: ApiClient,
):
    """PRD §3.5: "Otherwise, if the score is at least 60, the queue is `DISCLOSURE_COMMITTEE`."
    PRD §3.5: "Each queue carries its own service-level allowance, and the deadline is the logical clock at the moment of the write plus that allowance: 48 hours for `DISCLOSURE_COMMITTEE`, three days (72 hours) for `IR_DESK`, four days (96 hours) for `TRANSFER_AGENT_DESK` and five days (120 hours) for `SHAREHOLDER_SERVICES`."
    PRD §3.5: "A new ticket is born in status `NEW`, with `answered_at` null, and intake recounts the issuer's `open_inquiry_count` and increments the issuer's `version` by 1."

    Design: Corner/calculations/sensitivity_score_sums_all_six_terms_and_saturates_at_the_cap
    """
    company, analyst, prior = _blackout_issuer_with_escalated_prior(api)

    inquiry = validate_success(
        api.create_inquiry(
            factories.inquiry_payload(
                company["id"],
                analyst["id"],
                topic_category=TOPIC_GUIDANCE,
                subject="Following up on the same unpublished build.",
                requests_nonpublic_detail=True,
                linked_prior_inquiry_id=prior["id"],
            ),
            IR_ANALYST,
        ),
        201,
    )

    assertions.assert_inquiry(
        inquiry,
        sensitivity_score=100,
        routing_queue=QUEUE_DISCLOSURE_COMMITTEE,
        status=INQUIRY_NEW,
        answered_at=None,
    )
    assertions.assert_ts_equals(
        inquiry["sla_due_at"], "2026-08-03T00:00:00.000Z", "sla_due_at"
    )


# ---------------------------------------------------------------------------
# One clock instant, three queues, three deadlines
# ---------------------------------------------------------------------------


def test_each_routing_queue_selects_its_own_sla_allowance_from_the_same_instant(
    api: ApiClient,
):
    """PRD §3.5: "Each queue carries its own service-level allowance, and the deadline is the logical clock at the moment of the write plus that allowance: 48 hours for `DISCLOSURE_COMMITTEE`, three days (72 hours) for `IR_DESK`, four days (96 hours) for `TRANSFER_AGENT_DESK` and five days (120 hours) for `SHAREHOLDER_SERVICES`."
    PRD §3.5: "If the `topic_category` is `DIVIDEND` or `RECORD_DATE` and the frozen `sensitivity_score` is strictly below 50, the queue is `TRANSFER_AGENT_DESK`."
    PRD §3.5: "Otherwise, if the submitting contact's `contact_type` is `RETAIL_HOLDER`, the queue is `SHAREHOLDER_SERVICES`."
    PRD §3.5: "Otherwise the queue is `IR_DESK`."

    Design: Corner/calculations/sla_hours_constant_selected_per_routing_queue
    """
    company, retail, institution = _open_issuer_with_two_holder_types(api)
    assert fixtures.read_company(api, company["id"])["disclosure_posture"] == POSTURE_OPEN

    to_transfer_agent = validate_success(
        api.create_inquiry(
            factories.inquiry_payload(
                company["id"],
                retail["id"],
                topic_category=TOPIC_DIVIDEND,
                subject="When is the next dividend paid?",
            ),
            IR_ADMIN,
        ),
        201,
    )
    to_shareholder_services = validate_success(
        api.create_inquiry(
            factories.inquiry_payload(
                company["id"],
                retail["id"],
                topic_category=TOPIC_OTHER,
                subject="Please update my mailing address.",
            ),
            IR_ADMIN,
        ),
        201,
    )
    to_ir_desk = validate_success(
        api.create_inquiry(
            factories.inquiry_payload(
                company["id"],
                institution["id"],
                topic_category=TOPIC_GUIDANCE,
                subject="Clarify the published FY2026 range.",
            ),
            IR_ADMIN,
        ),
        201,
    )

    assertions.assert_inquiry(
        to_transfer_agent,
        sensitivity_score=15,
        routing_queue=QUEUE_TRANSFER_AGENT_DESK,
    )
    assertions.assert_ts_equals(
        to_transfer_agent["sla_due_at"], "2026-08-05T00:00:00.000Z", "sla_due_at (96h)"
    )

    assertions.assert_inquiry(
        to_shareholder_services,
        sensitivity_score=10,
        routing_queue=QUEUE_SHAREHOLDER_SERVICES,
    )
    assertions.assert_ts_equals(
        to_shareholder_services["sla_due_at"],
        "2026-08-06T00:00:00.000Z",
        "sla_due_at (120h)",
    )

    assertions.assert_inquiry(
        to_ir_desk, sensitivity_score=40, routing_queue=QUEUE_IR_DESK
    )
    assertions.assert_ts_equals(
        to_ir_desk["sla_due_at"], "2026-08-04T00:00:00.000Z", "sla_due_at (72h)"
    )


def test_three_intakes_leave_the_issuer_with_three_open_inquiries(api: ApiClient):
    """PRD §2.11: "It is the number of that issuer's inquiry tickets whose status is `NEW`, `ROUTED`, `DRAFTING`, `AWAITING_APPROVAL` or `ESCALATED` — that is, every status except `ANSWERED`."
    PRD §3.5: "A new ticket is born in status `NEW`, with `answered_at` null, and intake recounts the issuer's `open_inquiry_count` and increments the issuer's `version` by 1."

    Design: Corner/calculations/sla_hours_constant_selected_per_routing_queue
    """
    company, retail, institution = _open_issuer_with_two_holder_types(api)

    fixtures.create_inquiry(
        api,
        company["id"],
        retail["id"],
        headers=IR_ADMIN,
        topic_category=TOPIC_DIVIDEND,
        subject="When is the next dividend paid?",
    )
    fixtures.create_inquiry(
        api,
        company["id"],
        retail["id"],
        headers=IR_ADMIN,
        topic_category=TOPIC_OTHER,
        subject="Please update my mailing address.",
    )
    fixtures.create_inquiry(
        api,
        company["id"],
        institution["id"],
        headers=IR_ADMIN,
        topic_category=TOPIC_GUIDANCE,
        subject="Clarify the published FY2026 range.",
    )

    assertions.assert_company(
        fixtures.read_company(api, company["id"]), open_inquiry_count=3
    )


# ---------------------------------------------------------------------------
# The exclusive 50 boundary of the transfer-agent desk
# ---------------------------------------------------------------------------


def test_score_of_exactly_fifty_falls_through_to_the_ir_desk(api: ApiClient):
    """PRD §3.5: "If the `topic_category` is `DIVIDEND` or `RECORD_DATE` and the frozen `sensitivity_score` is strictly below 50, the queue is `TRANSFER_AGENT_DESK`."
    PRD §3.5: "Note the asymmetry of the two thresholds: the 50 boundary is exclusive, so a score of exactly 50 does not qualify for the transfer-agent desk, while the 60 boundary is inclusive, so a score of exactly 60 does reach the disclosure committee."
    PRD §3.5: "Otherwise the queue is `IR_DESK`."

    Design: Corner/calculations/transfer_agent_desk_threshold_is_exclusive_at_fifty
    """
    company, activist, _passive = _threshold_issuer_with_two_funds(api)

    inquiry = validate_success(
        api.create_inquiry(
            factories.inquiry_payload(
                company["id"],
                activist["id"],
                topic_category=TOPIC_DIVIDEND,
                subject="Send the unannounced dividend schedule.",
                requests_nonpublic_detail=True,
            ),
            IR_ANALYST,
        ),
        201,
    )

    # 15 (DIVIDEND) + 25 (nonpublic detail) + 10 (activist) = 50, not below 50.
    assertions.assert_inquiry(
        inquiry, sensitivity_score=50, routing_queue=QUEUE_IR_DESK
    )
    assertions.assert_ts_equals(
        inquiry["sla_due_at"], "2026-08-04T00:00:00.000Z", "sla_due_at (72h)"
    )


def test_score_of_forty_reaches_the_transfer_agent_desk(api: ApiClient):
    """PRD §3.5: "If the `topic_category` is `DIVIDEND` or `RECORD_DATE` and the frozen `sensitivity_score` is strictly below 50, the queue is `TRANSFER_AGENT_DESK`."
    PRD §3.5: "Each queue carries its own service-level allowance, and the deadline is the logical clock at the moment of the write plus that allowance: 48 hours for `DISCLOSURE_COMMITTEE`, three days (72 hours) for `IR_DESK`, four days (96 hours) for `TRANSFER_AGENT_DESK` and five days (120 hours) for `SHAREHOLDER_SERVICES`."
    PRD §3.5: "Add 10 when the submitting contact's `activist_flag` is true."

    Design: Corner/calculations/transfer_agent_desk_threshold_is_exclusive_at_fifty
    """
    company, _activist, passive = _threshold_issuer_with_two_funds(api)

    inquiry = validate_success(
        api.create_inquiry(
            factories.inquiry_payload(
                company["id"],
                passive["id"],
                topic_category=TOPIC_DIVIDEND,
                subject="Send the unannounced dividend schedule.",
                requests_nonpublic_detail=True,
            ),
            IR_ANALYST,
        ),
        201,
    )

    # 15 (DIVIDEND) + 25 (nonpublic detail), no activist term: 40 < 50.
    assertions.assert_inquiry(
        inquiry, sensitivity_score=40, routing_queue=QUEUE_TRANSFER_AGENT_DESK
    )
    assertions.assert_ts_equals(
        inquiry["sla_due_at"], "2026-08-05T00:00:00.000Z", "sla_due_at (96h)"
    )


# ---------------------------------------------------------------------------
# open_inquiry_count falls only when the answer is dispatched
# ---------------------------------------------------------------------------


def test_open_inquiry_count_still_counts_an_inquiry_awaiting_approval(api: ApiClient):
    """PRD §2.11: "It is the number of that issuer's inquiry tickets whose status is `NEW`, `ROUTED`, `DRAFTING`, `AWAITING_APPROVAL` or `ESCALATED` — that is, every status except `ANSWERED`."
    PRD §3.6: "The parent inquiry deliberately stays in `AWAITING_APPROVAL` — its version advances, but its status does not, because the answer has not yet gone out."

    Design: Corner/calculations/open_inquiry_count_drops_only_when_a_response_is_sent
    """
    company, first, second, draft = _issuer_with_awaiting_approval_and_new(api)

    # create, route, draft opened, submit-review: four writes on the inquiry row.
    assert fixtures.inquiry_version(api, first["id"]) == 4

    approved = fixtures.decide_review(api, draft["id"], first["id"])
    assertions.assert_response_draft(approved, status="APPROVED")

    assertions.assert_company(
        fixtures.read_company(api, company["id"]), open_inquiry_count=2
    )
    assert fixtures.read_inquiry(api, first["id"])["status"] == "AWAITING_APPROVAL"
    assert fixtures.read_inquiry(api, second["id"])["status"] == INQUIRY_NEW


def test_dispatching_the_answer_drops_the_open_inquiry_count_to_one(api: ApiClient):
    """PRD §3.6: "A successful dispatch drives the parent inquiry `AWAITING_APPROVAL` → `ANSWERED` with `answered_at` stamped from the logical clock and the inquiry's `version` incremented, and then recounts the issuer's `open_inquiry_count` — `ANSWERED` being the one status outside the open set — incrementing the issuer's `version` by 1 as well."
    PRD §2.11: "It is refreshed by inquiry intake, by the dispatch of an approved answer, and by every cascade link that changes an inquiry's status, and each refresh is a **full recount** over the issuer's inquiries rather than an incremental adjustment."

    Design: Corner/calculations/open_inquiry_count_drops_only_when_a_response_is_sent
    """
    company, first, second, draft = _issuer_with_awaiting_approval_and_new(api)
    fixtures.decide_review(api, draft["id"], first["id"])

    before = fixtures.read_company(api, company["id"])
    assertions.assert_company(before, open_inquiry_count=2)

    sent = validate_success(api.send_draft(draft["id"], IR_ANALYST), 200)
    assertions.assert_response_draft(sent, status=DRAFT_SENT)

    after = fixtures.read_company(api, company["id"])
    assertions.assert_company(after, open_inquiry_count=1)
    assert after["version"] == before["version"] + 1

    answered = fixtures.read_inquiry(api, first["id"])
    assertions.assert_inquiry(answered, status=INQUIRY_ANSWERED)
    assertions.assert_ts_equals(
        answered["answered_at"], "2026-08-01T00:00:00.000Z", "answered_at"
    )
    assertions.assert_inquiry(
        fixtures.read_inquiry(api, second["id"]), status=INQUIRY_NEW
    )
