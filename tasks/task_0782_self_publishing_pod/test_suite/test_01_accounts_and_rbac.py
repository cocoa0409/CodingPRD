"""Account/channel creation, defaults, shape validation, and role/ownership gates.

Translates corner-design instances from sections `entities` and `rbac`.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_publisher_headers,
    create_publisher_payload, create_channel_payload, create_title_payload,
    NON_EXISTENT_UUID,
    create_publisher, create_title, create_amz_channel,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


def test_create_publisher_returns_balances_and_active_status(api):
    """PRD 3.1: "A freshly created publisher has status of ACTIVE - the only
    status a publisher ever holds - a reserve_held_cents of 0, and a
    lifetime_paid_cents of 0."

    Design: Corner/entities/create_publisher_returns_all_fields
    """
    resp = api.create_publisher(create_publisher_payload(), ADMIN)
    data = validate_success(resp, 201)
    assert data["reserve_held_cents"] == 0
    assert data["lifetime_paid_cents"] == 0
    assert data["status"] == "ACTIVE"


def test_publisher_payout_method_defaults_to_bank(api):
    """PRD 3.1: "optionally a payout_method, which is one of BANK or PAYPAL and
    defaults to BANK when omitted."

    Design: Corner/entities/publisher_payout_method_defaults_to_bank
    """
    payload = create_publisher_payload()
    payload.pop("payout_method", None)
    data = validate_success(api.create_publisher(payload, ADMIN), 201)
    assert data["payout_method"] == "BANK"


def test_channel_invalid_channel_type_enum_rejected(api):
    """PRD 3.5: "any malformed body - a missing required field, a bad enum
    member, or a non-positive price - yields ERR_INVALID_REQUEST (HTTP 422)."
    PRD 3.3: "a channel_type of RETAIL, LIBRARY, or DIRECT".

    Design: Corner/entities/channel_invalid_channel_type_enum_rejected
    """
    payload = create_channel_payload(channel_type="WHOLESALE", supports_formats=["PRINT"])
    validate_error(api.create_channel(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST)


def test_get_title_nonexistent_returns_not_found(api):
    """PRD 2.8: "Each entity type has its own not-found error -
    ERR_PUBLISHER_NOT_FOUND, ERR_TITLE_NOT_FOUND, ... - each returned with
    HTTP 404."

    Design: Corner/entities/get_title_nonexistent_returns_not_found
    """
    validate_error(api.get_title(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_TITLE_NOT_FOUND)


def test_create_format_missing_format_type_returns_invalid_request(api):
    """PRD 3.5: "any malformed body - a missing required field, a bad enum
    member, or a non-positive price - yields ERR_INVALID_REQUEST (HTTP 422)."
    PRD 3.2: "a publisher creates a Format, choosing a format_type of PRINT,
    EBOOK, or AUDIO."

    Design: Corner/entities/create_format_missing_format_type_returns_invalid_request
    """
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    headers = make_publisher_headers(pub["id"])
    validate_error(
        api.create_format(title["id"], {"trim_size": "6x9"}, headers),
        ApiErrorId.ERR_INVALID_REQUEST,
    )


def test_publisher_cannot_ingest_sales_forbidden(api):
    """PRD 2.1: "When a request is authenticated but the acting role is not
    permitted to perform the requested operation - or when a Publisher attempts
    to act on a resource it does not own - the request is rejected with
    ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/publisher_cannot_ingest_sales_forbidden
    """
    channel = create_amz_channel(api)
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = get_success_data(api.create_format(
        title["id"],
        {"format_type": "PRINT", "trim_size": "6x9", "interior_color": "BW", "page_count": 200},
        make_publisher_headers(pub["id"]),
    ))
    payload = {
        "format_id": fmt["id"], "channel_id": channel["id"], "territory": "US",
        "units": 1, "line_type": "SALE", "sale_date": "2026-03-10T00:00:00Z",
    }
    validate_error(
        api.create_sales_line(payload, make_publisher_headers(pub["id"])),
        ApiErrorId.ERR_FORBIDDEN,
    )


def test_reviewer_cannot_create_title_forbidden(api):
    """PRD 2.1: "When a request is authenticated but the acting role is not
    permitted to perform the requested operation - or when a Publisher attempts
    to act on a resource it does not own - the request is rejected with
    ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/reviewer_cannot_create_title_forbidden
    """
    pub = create_publisher(api)
    validate_error(
        api.create_title(create_title_payload(pub["id"]), REVIEWER),
        ApiErrorId.ERR_FORBIDDEN,
    )


def test_publisher_cannot_modify_other_publishers_title_forbidden(api):
    """PRD 2.1: "for a Title, the resource's publisher_id must equal X-User-ID;
    for any resource that hangs off a title (a Format, and transitively its
    Asset, Proof, ChannelPrice, or DistributionRequest), the owning title's
    publisher_id must equal X-User-ID."

    Design: Corner/rbac/publisher_cannot_modify_other_publishers_title_forbidden
    """
    pub_a = create_publisher(api, name="A House", email="a@x.com")
    pub_b = create_publisher(api, name="B House", email="b@x.com")
    title_a = create_title(api, pub_a["id"])
    # Publisher B tries to create a format under Publisher A's title.
    resp = api.create_format(
        title_a["id"], {"format_type": "EBOOK", "file_size_mb": 2.0},
        make_publisher_headers(pub_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
