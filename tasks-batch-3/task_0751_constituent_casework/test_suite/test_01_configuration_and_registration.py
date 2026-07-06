"""Configuration records, constituent registration, and newsletter reach/cost."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    assert_constituent, assert_newsletter,
    new_representative, new_constituent,
    create_constituent_payload, create_newsletter_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["office_admin_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_constituent_creation_returns_all_fields(api):
    """PRD §3.2: "On creation the constituent's `status` defaults to `ACTIVE`
    and their `upcoming_event_count` ledger starts at zero."

    Design: Corner/entities/constituent_create_returns_all_fields
    """
    rep = new_representative(api)
    resp = api.create_constituent(
        create_constituent_payload(rep["id"], full_name="New Cy", email="new@x.com", address="1 Ave"),
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert_constituent(data)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["upcoming_event_count"] == 0, "upcoming_event_count must start at zero"


def test_case_not_found_returns_404(api):
    """PRD §2.6: "every referenced resource, both the path id and any body foreign
    key, exists; references are validated left-to-right in the order they appear,
    and the first missing one yields its type-specific not-found error (404)".

    Design: Corner/entities/case_not_found_returns_404
    """
    resp = api.get_case(NON_EXISTENT_UUID, CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)


def test_constituent_missing_email_rejected(api):
    """PRD §2.6: "the body carries all required fields with valid types and enum
    values, else `ERR_INVALID_REQUEST` (400). Applies to all writes."
    PRD §3.2: "Registration supplies the `representative_id` of the district they
    belong to, their `full_name`, `email`, and `address`".

    Design: Corner/entities/constituent_missing_email_rejected
    """
    rep = new_representative(api)
    resp = api.create_constituent(
        {"representative_id": rep["id"], "full_name": "No Email", "address": "2 Ave"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_constituent_consent_defaults_false(api):
    """PRD §3.2: "Two consent flags are captured at registration and both default
    to false when omitted: `contact_consent`, which governs whether the constituent
    may be included as a newsletter recipient, and `data_sharing_consent`, which
    governs whether their case data may be shared with an external agency."

    Design: Corner/entities/constituent_consent_defaults_false
    """
    rep = new_representative(api)
    resp = api.create_constituent(
        create_constituent_payload(rep["id"], full_name="Def Cy", email="def@x.com", address="3 Ave"),
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["contact_consent"] is False, "contact_consent must default to false"
    assert data["data_sharing_consent"] is False, "data_sharing_consent must default to false"


def test_newsletter_recipient_count_and_cost(api):
    """PRD §3.8: "The `recipient_count` is the number of constituents belonging to
    the sending representative (matching on `representative_id`) whose `status` is
    `ACTIVE` and whose `contact_consent` is true."
    PRD §3.8: "The `send_cost_cents` is the `recipient_count` multiplied by the sum
    of a base postage charge of 55 cents plus a per-page printing charge of 8 cents
    times the campaign's `page_count`; the result is expressed in whole cents."

    Design: Corner/entities/newsletter_recipient_count_and_cost_computed
    """
    rep = new_representative(api)
    new_constituent(api, rep["id"], email="c1@x.com", contact_consent=True)
    new_constituent(api, rep["id"], email="c2@x.com", contact_consent=True)
    new_constituent(api, rep["id"], email="c3@x.com", contact_consent=False)

    resp = api.create_newsletter(rep["id"], create_newsletter_payload(page_count=3), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_newsletter(data)
    assert data["recipient_count"] == 2, f"expected recipient_count 2, got {data['recipient_count']}"
    assert data["send_cost_cents"] == 158, f"expected 158 cents, got {data['send_cost_cents']}"
    assert data["status"] == "SENT"


def test_anonymous_self_registration_allowed(api):
    """PRD §2.1: "`Anonymous` is the unauthenticated self-service surface. It exists
    solely so a new constituent can self-register."

    Design: Corner/rbac/anonymous_self_registration_allowed
    """
    rep = new_representative(api)
    resp = api.create_constituent(
        create_constituent_payload(rep["id"], full_name="Self Cy", email="self@x.com", address="q"),
        ANON,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
