"""Request creation rules (required fields, defaults, credential mapping, schedule)
and the DRAFT -> MATCHING submission gate, including the cross-entity org-posture gate."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_org_requester_headers,
    set_clock,
    create_org,
    create_draft_request,
    get_request,
    setup_confirmed_assignment,
    drive_to_checkout,
    verify_encounter,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_create_request_missing_consumer_name_returns_invalid_request():
    """PRD §3.3: "The payload names the filing organization via `org_id`, which must
    equal the caller's `X-User-ID`; identifies the deaf or hard-of-hearing
    `consumer_name`; selects a `modality` of `ASL_ONSITE`, `CART_ONSITE`, or `VRI`;
    and fixes the engagement with `scheduled_start` and `scheduled_end`."
    PRD §2.10: "Second, request-schema integrity: required fields present, types
    valid, enum values in their declared domains, unknown fields rejected, numeric
    ranges enforced (amounts positive, claims non-negative, end after start), and
    conditionally-required fields honored — failures surface as `ERR_INVALID_REQUEST`
    or `ERR_ONSITE_ADDRESS_REQUIRED` (HTTP 400)."

    Design: Corner/entities/create_request_missing_consumer_name_returns_invalid_request
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    payload = {
        "org_id": org["id"],
        "modality": "VRI",
        "scheduled_start": "2026-06-10T14:00:00Z",
        "scheduled_end": "2026-06-10T15:00:00Z",
    }
    resp = api_client.create_request(payload, make_org_requester_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, _meta = validate_paginated(
        api_client.list_requests(ADMIN, params={"org_id": org["id"]}))
    assert rows == [], "nothing may be persisted after a schema rejection"


def test_create_request_defaults_and_computed_credential_mapping():
    """PRD §3.3: "The `ada_context` is optional and defaults to `GENERAL`; when
    supplied it must be one of `MEDICAL`, `LEGAL`, `EDUCATION`, or `GENERAL`."
    PRD §3.3: "From the context the platform derives the credential bar: a `LEGAL`
    request demands a `SPECIALIST`, `MEDICAL` and `EDUCATION` demand `CERTIFIED`,
    and `GENERAL` demands `SCREENED`."
    PRD §3.3: "A new request is a `DRAFT` at `version` 1, with `offer_attempt_count`
    at zero and `cancellation_fee_cents`, `cancelled_at`, and `closed_at` all null."

    Design: Corner/entities/create_request_defaults_and_computed_credential_mapping
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org(name="County Court", org_type="LEGAL")
    r_gen = create_draft_request(
        org["id"],
        consumer_name="Dee Af",
        modality="VRI",
        ada_context=None,  # omitted entirely: the server default GENERAL must apply
        scheduled_start="2026-06-10T14:00:00Z",
        scheduled_end="2026-06-10T15:00:00Z",
        onsite_address=None,
        estimated_mileage=0,
    )
    r_leg = create_draft_request(
        org["id"],
        consumer_name="Lee Litigant",
        modality="ASL_ONSITE",
        ada_context="LEGAL",
        scheduled_start="2026-06-16T14:00:00Z",
        scheduled_end="2026-06-16T15:00:00Z",
        onsite_address="1 Court Pl",
        estimated_mileage=0,
    )
    assert r_gen["ada_context"] == "GENERAL", "omitted ada_context defaults to GENERAL"
    assert r_gen["required_credential_level"] == "SCREENED", "GENERAL maps to SCREENED"
    assert r_leg["ada_context"] == "LEGAL"
    assert r_leg["required_credential_level"] == "SPECIALIST", "LEGAL maps to SPECIALIST"
    for req in (r_gen, r_leg):
        assert req["status"] == "DRAFT" and req["version"] == 1
        assert req["offer_attempt_count"] == 0


def test_invalid_enum_value_returns_invalid_request():
    """PRD §3.3: the request payload "selects a `modality` of `ASL_ONSITE`,
    `CART_ONSITE`, or `VRI`".
    PRD §2.10: "Second, request-schema integrity: required fields present, types
    valid, enum values in their declared domains, unknown fields rejected, numeric
    ranges enforced (amounts positive, claims non-negative, end after start), and
    conditionally-required fields honored — failures surface as `ERR_INVALID_REQUEST`
    or `ERR_ONSITE_ADDRESS_REQUIRED` (HTTP 400)."

    Design: Corner/entities/invalid_enum_value_returns_invalid_request
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    payload = {
        "org_id": org["id"],
        "consumer_name": "Dee Af",
        "modality": "ASL_REMOTE",
        "scheduled_start": "2026-06-10T14:00:00Z",
        "scheduled_end": "2026-06-10T15:00:00Z",
    }
    resp = api_client.create_request(payload, make_org_requester_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_onsite_request_without_address_returns_error():
    """PRD §3.3: "For the two on-site modalities an `onsite_address` is required —
    omitting it is rejected with `ERR_ONSITE_ADDRESS_REQUIRED` (HTTP 400) — while a
    VRI booking must not demand one."

    Design: Corner/validations/create_onsite_request_without_address_returns_error
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    headers = make_org_requester_headers(org["id"])
    onsite_payload = {
        "org_id": org["id"],
        "consumer_name": "Dee Af",
        "modality": "ASL_ONSITE",
        "scheduled_start": "2026-06-10T14:00:00Z",
        "scheduled_end": "2026-06-10T15:00:00Z",
    }
    resp = api_client.create_request(onsite_payload, headers)
    validate_error(resp, ApiErrorId.ERR_ONSITE_ADDRESS_REQUIRED)
    vri_payload = dict(onsite_payload, modality="VRI")
    resp_vri = api_client.create_request(vri_payload, headers)
    data = validate_success(resp_vri, 201)
    assert data["modality"] == "VRI", "VRI booking without onsite_address succeeds"


def test_submit_within_two_hour_lead_returns_invalid_schedule():
    """PRD §3.3: "the schedule must be sane: `scheduled_end` strictly after
    `scheduled_start`, and `scheduled_start` at least two hours in the future at
    submit time. A bad schedule is rejected with `ERR_INVALID_SCHEDULE` (HTTP 422);
    submitting anything other than a `DRAFT` is rejected with `ERR_REQUEST_NOT_DRAFT`."

    Design: Corner/validations/submit_within_two_hour_lead_returns_invalid_schedule
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    req = create_draft_request(
        org["id"],
        consumer_name="Dee Af",
        modality="VRI",
        scheduled_start="2026-06-10T13:30:00Z",
        scheduled_end="2026-06-10T14:30:00Z",
        onsite_address=None,
        estimated_mileage=0,
    )
    set_clock("2026-06-10T12:30:00Z")  # only one hour of lead before the 13:30 start
    resp = api_client.submit_request(req["id"], make_org_requester_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_SCHEDULE)
    assert get_request(req["id"])["status"] == "DRAFT", "rejected submit leaves DRAFT"


def test_terminal_lockdown_cancelled_request_rejects_submit():
    """PRD §3.3: "submitting anything other than a `DRAFT` is rejected with
    `ERR_REQUEST_NOT_DRAFT`."
    PRD §3.6: "Cancelling a `DRAFT` or `MATCHING` request is fee-free and final."

    Design: Corner/state_machines/terminal_lockdown_cancelled_request_rejects_submit
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    req = create_draft_request(
        org["id"],
        consumer_name="Dee Af",
        modality="VRI",
        scheduled_start="2026-06-10T14:00:00Z",
        scheduled_end="2026-06-10T15:00:00Z",
        onsite_address=None,
        estimated_mileage=0,
    )
    cancelled = get_success_data(api_client.cancel_request(
        req["id"], make_org_requester_headers(org["id"])))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 0, "cancel from DRAFT is fee-free"
    resp = api_client.submit_request(req["id"], make_org_requester_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_DRAFT)
    assert get_request(req["id"])["status"] == "CANCELLED", "terminal state holds"


def test_cancel_completed_request_returns_not_cancellable():
    """PRD §3.6: "An `OrgRequester` (owning org, `ACTIVE`) or a `PlatformAdmin` may
    cancel the request itself while it stands in `DRAFT`, `MATCHING`, `OFFERED`, or
    `CONFIRMED` — any other state is rejected with `ERR_REQUEST_NOT_CANCELLABLE`."
    PRD §3.7: "Verification bubbles the request from `IN_PROGRESS` to `COMPLETED`."

    Design: Corner/errors/cancel_completed_request_returns_not_cancellable
    """
    ctx = setup_confirmed_assignment()
    drive_to_checkout(ctx)
    verify_encounter(ctx)
    assert ctx["request"]["status"] == "COMPLETED"
    resp = api_client.cancel_request(
        ctx["request"]["id"], make_org_requester_headers(ctx["org"]["id"]))
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_CANCELLABLE)
    assert get_request(ctx["request"]["id"])["status"] == "COMPLETED"


# ─── Difficulty: cross_entity_state_dependency / org posture ────────

def _setup_suspended_org_with_draft_request():
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    req = create_draft_request(
        org["id"],
        consumer_name="Pat Patient",
        modality="VRI",
        ada_context="GENERAL",
        scheduled_start="2026-06-10T14:00:00Z",
        scheduled_end="2026-06-10T15:00:00Z",
        onsite_address=None,
        estimated_mileage=0,
    )
    get_success_data(api_client.suspend_org(org["id"], ADMIN))
    return org, req


def test_submit_blocked_when_org_suspended_returns_org_not_active():
    """PRD §3.1: "Suspension is a hard gate on org-initiated writes: while an
    organization is `SUSPENDED`, its coordinators cannot submit or cancel requests,
    verify encounters, dispute invoices, or file complaints — each attempt is
    rejected with `ERR_ORG_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_org_suspended
    """
    org, req = _setup_suspended_org_with_draft_request()
    resp = api_client.submit_request(req["id"], make_org_requester_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_ORG_NOT_ACTIVE)


def test_submit_blocked_when_org_suspended_leaves_request_draft():
    """PRD §3.1: "Suspension is a hard gate on org-initiated writes: while an
    organization is `SUSPENDED`, its coordinators cannot submit or cancel requests,
    verify encounters, dispute invoices, or file complaints — each attempt is
    rejected with `ERR_ORG_NOT_ACTIVE` (HTTP 409)."
    PRD §3.3: "Submission moves a request from `DRAFT` to `MATCHING`." (a rejected
    submission performs no transition.)

    Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_org_suspended
    """
    org, req = _setup_suspended_org_with_draft_request()
    resp = api_client.submit_request(req["id"], make_org_requester_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_ORG_NOT_ACTIVE)
    after = get_request(req["id"])
    assert after["status"] == "DRAFT", (
        f"org posture failure must not move the request, got {after['status']}"
    )
