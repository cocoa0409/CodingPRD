"""Regulatory inquiries: the response clock, the overdue sweep cascade, the
response/close happy path, invalid close, producer reinstatement guard, and
OCC on the response (PRD sections 2.5, 2.8, 2.9, 3.1, 3.5, 3.8).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_instant_equals,
    assert_inquiry,
    create_inquiry,
    create_producer,
    get_application,
    get_entry_for_application,
    get_inquiry,
    get_producer,
    setup_suspended_producer,
    submit_application,
    validate_error,
    validate_success,
    DEFAULT_CLOCK_ISO,
    TEST_USERS,
)

LC = TEST_USERS["licensing_coordinator_headers"]
OFFICER_A = TEST_USERS["compliance_officer_a_headers"]
OFFICER_B = TEST_USERS["compliance_officer_b_headers"]


def test_inquiry_overdue_suspends_producer():
    """PRD section 3.8: "The inquiry stamps `received_at` from the logical
    clock, computes its `response_due_at` as thirty days after receipt, and
    opens in `OPEN` status." and "Once the clock passes `response_due_at`, an
    `OPEN` inquiry turns `OVERDUE`, and the consequences are severe: when the
    inquiry names a producer who is currently `ACTIVE`, that producer is
    suspended".

    Design: Difficulty/transitive_cascade/inquiry_overdue_cascade_depth2
    """
    producer = create_producer(npn="NPN-2008", full_name="Overdue Target",
                               resident_state_code="TX")
    inquiry = create_inquiry(
        producer_id=producer["id"], state_code="TX", reference_number="INQ-2008"
    )
    assert_inquiry(inquiry)
    assert inquiry["status"] == "OPEN"
    assert_instant_equals(inquiry["received_at"], DEFAULT_CLOCK_ISO, "received_at")
    assert_instant_equals(
        inquiry["response_due_at"], "2026-08-31T00:00:00Z",
        "response_due_at is thirty days after receipt",
    )

    advance_clock("2026-09-01T00:00:00Z")
    assert get_inquiry(inquiry["id"])["status"] == "OVERDUE"
    assert get_producer(producer["id"])["status"] == "SUSPENDED", (
        "the overdue inquiry suspends the producer"
    )


def test_inquiry_overdue_declines_submitted_application():
    """PRD section 3.8: "the producer-suspension cascade of §3.5 fires — every
    one of that producer's still-`SUBMITTED` applications is declined with
    `decided_at` stamped, each such application's commission entry is forfeited
    from any non-terminal status, and the producer's held-commission total is
    recomputed."

    Design: Difficulty/transitive_cascade/inquiry_overdue_cascade_depth2
    """
    producer = create_producer(npn="NPN-2009", full_name="Cascade Target",
                               resident_state_code="TX")
    application = submit_application(
        producer["id"], state_code="TX", line_of_authority="LIFE",
        applicant_name="Sub", premium_cents=1_000_000,
    )
    entry = get_entry_for_application(application["id"])
    assert entry["status"] == "HELD"
    assert entry["hold_reason"] == "UNLICENSED_AT_SALE"
    inquiry = create_inquiry(
        producer_id=producer["id"], state_code="TX", reference_number="INQ-2009"
    )

    advance_clock("2026-09-01T00:00:00Z")
    assert get_inquiry(inquiry["id"])["status"] == "OVERDUE"

    declined = get_application(application["id"])
    assert declined["status"] == "DECLINED"
    assert_instant_equals(
        declined["decided_at"], "2026-09-01T00:00:00Z",
        "decided_at stamped from the logical clock at the cascade",
    )
    assert get_entry_for_application(application["id"])["status"] == "FORFEITED"
    assert get_producer(producer["id"])["commission_held_cents"] == 0


def test_inquiry_response_close_happy_path():
    """PRD section 3.8: "The response carries the narrative `response_text` and
    the OCC guard `expected_inquiry_version`; a version that has since advanced
    — most commonly because the sweep moved the inquiry to `OVERDUE` — is
    rejected with `ERR_STALE_VERSION`."
    PRD section 3.8: "A successful response moves the inquiry to
    `RESPONSE_SUBMITTED` and stamps `responded_at`."
    PRD section 3.8: "Closing the file is a `ComplianceOfficer` action that
    moves a `RESPONSE_SUBMITTED` inquiry to `CLOSED`, terminal".

    Design: Corner/state_machines/inquiry_response_close_happy_path
    """
    producer = create_producer(npn="NPN-3013", full_name="Happy Path",
                               resident_state_code="TX")
    inquiry = create_inquiry(
        producer_id=producer["id"], state_code="TX", reference_number="INQ-3013"
    )
    assert_instant_equals(inquiry["received_at"], DEFAULT_CLOCK_ISO, "received_at")
    assert_instant_equals(
        inquiry["response_due_at"], "2026-08-31T00:00:00Z", "response_due_at"
    )

    responded = validate_success(
        api_client.respond_to_inquiry(
            inquiry["id"],
            {"response_text": "acknowledged",
             "expected_inquiry_version": inquiry["version"]},
            OFFICER_B,
        ),
        200,
    )
    assert responded["status"] == "RESPONSE_SUBMITTED"
    assert responded["response_text"] == "acknowledged"
    assert_instant_equals(responded["responded_at"], DEFAULT_CLOCK_ISO, "responded_at")

    closed = validate_success(api_client.close_inquiry(inquiry["id"], OFFICER_B), 200)
    assert closed["status"] == "CLOSED"


def test_inquiry_close_before_response_rejected():
    """PRD section 3.8: "attempting to close an inquiry still `OPEN` or
    `OVERDUE` is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/inquiry_close_before_response_rejected
    """
    producer = create_producer(npn="NPN-3008", full_name="Early Close",
                               resident_state_code="TX")
    inquiry = create_inquiry(
        producer_id=producer["id"], state_code="TX", reference_number="INQ-3008"
    )

    resp = api_client.close_inquiry(inquiry["id"], OFFICER_B)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_inquiry(inquiry["id"])["status"] == "OPEN"


def test_producer_reinstate_blocked_while_inquiry_overdue():
    """PRD section 3.1: "a `ComplianceOfficer` reinstates a `SUSPENDED`
    producer to `ACTIVE`, but only when no regulatory inquiry naming that
    producer is still `OVERDUE`; attempting reinstatement while one remains
    overdue is rejected with `ERR_OVERDUE_INQUIRY_EXISTS` (HTTP 409)." PRD
    section 3.8: "Notably, a late response does not reinstate the suspended
    producer; that takes the explicit reinstatement of §3.1" — and answering
    "is allowed from both `OPEN` and `OVERDUE`."

    Design: Corner/state_machines/producer_reinstate_blocked_while_inquiry_overdue_rejected
    """
    bundle = setup_suspended_producer(npn="NPN-3011", reference_number="INQ-3011")
    producer_id = bundle["producer"]["id"]
    inquiry_id = bundle["inquiry"]["id"]
    assert bundle["producer"]["status"] == "SUSPENDED"

    blocked = api_client.reinstate_producer(producer_id, OFFICER_B)
    validate_error(blocked, ApiErrorId.ERR_OVERDUE_INQUIRY_EXISTS)

    overdue = get_inquiry(inquiry_id)
    assert overdue["status"] == "OVERDUE"
    responded = validate_success(
        api_client.respond_to_inquiry(
            inquiry_id,
            {"response_text": "late response",
             "expected_inquiry_version": overdue["version"]},
            OFFICER_B,
        ),
        200,
    )
    assert responded["status"] == "RESPONSE_SUBMITTED", (
        "a late response is allowed from OVERDUE"
    )

    reinstated = validate_success(api_client.reinstate_producer(producer_id, OFFICER_B), 200)
    assert reinstated["status"] == "ACTIVE"


def test_stale_version_occ_inquiry_response_rejected():
    """PRD section 2.8: "Submitting a regulatory-inquiry response requires the
    non-optional field `expected_inquiry_version`, carrying the `version` of
    the inquiry the client last observed."
    PRD section 2.8: "In both cases, if the value does not match the record's
    current `version` — because another write, such as a CE-credit acceptance
    recomputing the license's counters or a clock sweep moving the inquiry to
    `OVERDUE`, has legitimately advanced it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), so the client cannot overwrite state it has
    not observed."
    PRD section 2.5: "Each swept record's `version` increments by one."

    Design: Corner/cross_cutting_layers/stale_version_occ_inquiry_response_rejected
    """
    producer = create_producer(npn="NPN-3036", full_name="OCC Inquiry",
                               resident_state_code="TX")
    inquiry = create_inquiry(
        producer_id=producer["id"], state_code="TX", reference_number="INQ-3036"
    )
    observed_version = inquiry["version"]

    advance_clock("2026-09-01T00:00:00Z")

    stale = api_client.respond_to_inquiry(
        inquiry["id"],
        {"response_text": "stale", "expected_inquiry_version": observed_version},
        OFFICER_B,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = get_inquiry(inquiry["id"])
    assert fresh["status"] == "OVERDUE"
    assert fresh["version"] == observed_version + 1, (
        "the sweep legitimately advanced the inquiry version"
    )

    responded = validate_success(
        api_client.respond_to_inquiry(
            inquiry["id"],
            {"response_text": "fresh", "expected_inquiry_version": fresh["version"]},
            OFFICER_B,
        ),
        200,
    )
    assert responded["status"] == "RESPONSE_SUBMITTED"
