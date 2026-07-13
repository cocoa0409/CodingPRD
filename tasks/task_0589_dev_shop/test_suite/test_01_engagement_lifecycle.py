"""From lead to signed statement of work: client registration, engagement
birth defaults, reference resolution, body well-formedness, and the engagement's
own state machine (signing and closure)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_client_contact_headers,
    assert_client,
    assert_engagement,
    fixtures,
    factories as F,
)

AM = TEST_USERS["account_manager_headers"]
DL = TEST_USERS["delivery_lead_headers"]

NON_EXISTENT_ENGAGEMENT = "00000000-0000-4000-8000-000000000000"


def test_create_client_mints_uuid_and_version_one(api):
    """PRD 3.1: "An account manager registers one by supplying its `name`, the `billing_email` where invoices will be sent, and a `country_code` given as exactly two uppercase letters."
    PRD 2.4: "Every resource in this system carries an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`."
    PRD 2.4: "`version` is 1 at creation and increments by 1 on every mutation of that resource; `updated_at` is refreshed to the current logical clock on every mutation."

    Design: Corner/entities/create_client_mints_system_fields_and_returns_201
    """
    resp = api.create_client(
        F.create_client_payload(
            name="Acme Corp", billing_email="ap@acme.test", country_code="US"
        ),
        AM,
    )
    data = validate_success(resp, expected_status=201)
    assert_client(data)
    assert data["version"] == 1, f"a new resource starts at version 1, got {data['version']}"
    assert data["name"] == "Acme Corp"
    assert data["country_code"] == "US"
    # PRD 2.2: the success envelope carries meta.api_request_id / timestamp and a
    # response_type of "object" for a single resource.
    body = resp.json()
    assert body["response_type"] == "object", "a single resource is an object response"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]


def test_engagement_creation_seeds_computed_defaults(api):
    """PRD 3.1: "The new engagement is born in `LEAD` status, `UNBILLED` on its billing dimension, `HEALTHY` on its budget dimension, and at `version` 1."
    PRD 3.1: "Its commercial terms — `billing_model`, `contract_value`, `budget_hours_cap`, `standard_hourly_rate`, `start_date` and `end_date` — are all null at this point; the lead has not been priced."

    Design: Corner/entities/engagement_creation_seeds_computed_defaults
    """
    client = fixtures.create_client()
    resp = api.create_engagement(
        F.create_engagement_payload(
            client_id=client["id"], title="Acme Portal", source_channel="REFERRAL"
        ),
        AM,
    )
    data = validate_success(resp, expected_status=201)
    assert_engagement(data)
    assert data["status"] == "LEAD"
    assert data["billing_status"] == "UNBILLED"
    assert data["budget_posture"] == "HEALTHY"
    assert data["approved_hours"] == 0
    assert data["burn_ratio"] == 0
    assert data["invoiced_amount"] == 0
    assert data["contract_value"] is None, "an unpriced lead has no contract value"
    assert data["version"] == 1


def test_get_engagement_with_unknown_id_returns_not_found(api):
    """PRD 2.5: "A path identifier that does not resolve to an existing resource produces the corresponding not-found error for that entity type — `ERR_CLIENT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_SPRINT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_TIME_ENTRY_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_RETAINER_NOT_FOUND` or `ERR_INCIDENT_NOT_FOUND` — all at HTTP 404."

    Design: Corner/entities/get_engagement_with_unknown_id_returns_not_found
    """
    resp = api.get_engagement(NON_EXISTENT_ENGAGEMENT, DL)
    validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value)
    assert resp.json()["response_type"] == "error"


def test_create_engagement_without_source_channel_is_invalid(api):
    """PRD 3.1: "the account manager opens an engagement by naming the `client_id` it belongs to, a `title`, and a `source_channel` recording how the lead arrived — one of `REFERRAL`, `INBOUND`, `OUTBOUND` or `PARTNER`."
    PRD 2.5: "**Body well-formedness** — required fields present, enum values recognised, numbers positive where a positive number is required, dates in `YYYY-MM-DD` form, logged hours greater than 0 and no greater than 12, `limit` within 1 through 100, `offset` at least 0 (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_engagement_missing_required_field_returns_invalid_request
    """
    client = fixtures.create_client()
    resp = api.create_engagement({"client_id": client["id"], "title": "Acme Portal"}, AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    listed = validate_success(api.list_engagements(DL, params={"client_id": client["id"]}))
    assert len(listed) == 0, "a rejected create must not persist an engagement"


def test_create_engagement_with_unrecognised_source_channel_is_invalid(api):
    """PRD 3.1: "the account manager opens an engagement by naming the `client_id` it belongs to, a `title`, and a `source_channel` recording how the lead arrived — one of `REFERRAL`, `INBOUND`, `OUTBOUND` or `PARTNER`."
    PRD 2.5: "**Body well-formedness** — required fields present, enum values recognised, numbers positive where a positive number is required, dates in `YYYY-MM-DD` form, logged hours greater than 0 and no greater than 12, `limit` within 1 through 100, `offset` at least 0 (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/invalid_enum_source_channel_returns_invalid_request
    """
    client = fixtures.create_client()
    resp = api.create_engagement(
        F.create_engagement_payload(
            client_id=client["id"], title="Enumco Site", source_channel="COLD_CALL"
        ),
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_sign_engagement_while_still_lead_is_invalid_transition(api):
    """PRD 3.1: "Signing is a `ClientContact` action, permitted only when the acting `X-User-ID` is the engagement's own `client_id`, and only from `SOW_ISSUED`."
    PRD 2.5: "**Parent-state gates** — the engagement must be `ACTIVE` where the operation demands it (`ERR_ENGAGEMENT_NOT_ACTIVE`), then the sprint-state gates (`ERR_SPRINT_NOT_ACTIVE`), then the transition-legality check (`ERR_INVALID_TRANSITION`), then the milestone-completion gate on issuing (`ERR_MILESTONE_NOT_COMPLETED`), then the active-sprint gate on engagement closure (`ERR_ENGAGEMENT_HAS_ACTIVE_SPRINT`)."

    Design: Corner/state_machines/sign_engagement_while_still_lead_is_invalid_transition
    """
    client = fixtures.create_client()
    engagement = fixtures.create_lead(client["id"], title="Earlyco App")

    resp = api.sign_engagement(
        engagement["id"],
        F.sign_payload(signed_by_name="Dex Client"),
        make_client_contact_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION.value)

    after = validate_success(api.get_engagement(engagement["id"], DL))
    assert after["status"] == "LEAD", "a refused signature leaves the lead untouched"
    assert after.get("signed_at") is None, "signed_at is stamped only by a successful signature"


def test_close_engagement_with_an_active_sprint_is_rejected(api):
    """PRD 3.1: "An engagement may be closed only from `ACTIVE`, and only when none of its sprints is currently `ACTIVE` — if any is, the close is refused with `ERR_ENGAGEMENT_HAS_ACTIVE_SPRINT` (HTTP 409)."

    Design: Corner/state_machines/close_engagement_with_an_active_sprint_is_rejected
    """
    ctx = fixtures.setup_active_sprint()
    engagement_id = ctx["engagement"]["id"]

    blocked = api.close_engagement(engagement_id, DL)
    validate_error(blocked, ApiErrorId.ERR_ENGAGEMENT_HAS_ACTIVE_SPRINT.value)
    still_active = validate_success(api.get_engagement(engagement_id, DL))
    assert still_active["status"] == "ACTIVE", "the refused close leaves the engagement ACTIVE"

    fixtures.close_sprint(ctx["sprint"]["id"])
    closed = validate_success(api.close_engagement(engagement_id, DL))
    assert closed["status"] == "CLOSED", "with no ACTIVE sprint the same close succeeds"
