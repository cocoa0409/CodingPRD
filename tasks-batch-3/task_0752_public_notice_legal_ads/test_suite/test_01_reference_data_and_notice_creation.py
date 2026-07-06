"""Reference-data provisioning and notice drafting (corner-design instances).

Covers newspaper/account creation, notice field derivation, required-field and enum
validation, statutory-requirement gating, authentication, and role restriction.
"""
from prd_bench_local_runner.testing import (
    validate_success, validate_error, is_valid_uuid,
)
from test_helpers import (
    ApiErrorId,
    platform_admin_headers, make_advertiser_headers, make_publisher_headers,
    create_newspaper_payload, create_account_payload,
    create_statutory_requirement_payload, create_notice_payload,
    provision_reference,
    assert_newspaper,
)


def test_create_newspaper_returns_201_and_echoes_fields(api):
    """PRD §3.1: "The registration also fixes the paper's commercial terms — its
    `pricing_basis`, `chars_per_line`, `line_rate_first_cents`,
    `line_rate_subsequent_cents`, `word_rate_cents`, and the flat `affidavit_fee_cents`
    charged for the sworn affidavit of publication."

    Design: Corner/entities/create_newspaper_success_returns_201_and_fields
    """
    resp = api.create_newspaper(create_newspaper_payload(), platform_admin_headers())
    data = validate_success(resp, expected_status=201)
    assert_newspaper(data)
    assert data["pricing_basis"] == "PER_LINE"
    assert data["edition_line_capacity"] == 100


def test_get_newspaper_not_found(api):
    """PRD §2.8: "Any path `id` or foreign-key body field that does not resolve to a
    live resource yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_newspaper_not_found
    """
    resp = api.get_newspaper("00000000-0000-0000-0000-000000000000",
                            platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_notice_missing_body_text_rejected(api):
    """PRD §2.8: "A malformed request body — a missing required field, a value of the
    wrong type, or an invalid enum value — yields `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_notice_missing_body_text_rejected
    """
    ref = provision_reference(api)
    payload = create_notice_payload(ref["account"]["id"], ref["newspaper"]["id"],
                                    title="No Body")
    del payload["body_text"]
    resp = api.create_notice(payload, make_advertiser_headers(ref["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_create_notice_invalid_notice_type_enum_rejected(api):
    """PRD §2.8: "A malformed request body — a missing required field, a value of the
    wrong type, or an invalid enum value — yields `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_notice_invalid_notice_type_enum_rejected
    """
    np = validate_success(api.create_newspaper(create_newspaper_payload(),
                                              platform_admin_headers()), 201)
    acct = validate_success(api.create_account(create_account_payload(),
                                             platform_admin_headers()), 201)
    payload = create_notice_payload(acct["id"], np["id"], notice_type="OBITUARY",
                                    title="Bad Type")
    resp = api.create_notice(payload, make_advertiser_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_newspaper_system_fields_generated_version_starts_one(api):
    """PRD §2.4: "version, an integer that begins at 1 and increases by exactly one on
    every mutation that changes the resource."
    PRD §2.4: "Every persisted resource carries a server-minted `id`, which is a UUID
    with no type prefix."

    Design: Corner/entities/newspaper_system_fields_generated_version_starts_one
    """
    data = validate_success(api.create_newspaper(create_newspaper_payload(),
                                               platform_admin_headers()), 201)
    assert data["version"] == 1, f"version should start at 1, got {data['version']}"
    assert is_valid_uuid(data["id"]), "id must be a UUID with no type prefix"


def test_notice_word_and_line_count_computed(api):
    """PRD §3.2: "It computes `word_count` from the `body_text` and `line_count` by
    ceiling the character length of `body_text` against the target newspaper's
    `chars_per_line`."
    PRD §3.2: "When a rule is found, its `min_insertions` is copied onto the notice as
    `required_insertions`."

    Design: Corner/entities/notice_word_and_line_count_computed
    """
    ref = provision_reference(api)
    data = validate_success(
        api.create_notice(
            create_notice_payload(ref["account"]["id"], ref["newspaper"]["id"]),
            make_advertiser_headers(ref["account"]["id"])), 201)
    assert data["word_count"] == 15, f"word_count should be 15, got {data['word_count']}"
    assert data["line_count"] == 2, f"line_count should be 2, got {data['line_count']}"
    assert data["status"] == "DRAFT"
    assert data["required_insertions"] == 2


def test_create_notice_missing_statutory_requirement(api):
    """PRD §3.2: "It looks up the statutory requirement matching the notice's
    `notice_type` and `county`; if none exists, the draft is refused with
    `ERR_STATUTORY_REQUIREMENT_MISSING` (HTTP 422)."

    Design: Corner/errors/create_notice_missing_statutory_requirement
    """
    ref = provision_reference(api)  # only a PROBATE requirement is defined
    payload = create_notice_payload(ref["account"]["id"], ref["newspaper"]["id"],
                                    notice_type="BID", title="Bid No Rule")
    resp = api.create_notice(payload, make_advertiser_headers(ref["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STATUTORY_REQUIREMENT_MISSING, expected_status=422)


def test_publisher_cannot_create_notice(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership-scoped role acts on a resource it
    does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/publisher_cannot_create_notice
    """
    ref = provision_reference(api)
    payload = create_notice_payload(ref["account"]["id"], ref["newspaper"]["id"])
    resp = api.create_notice(payload, make_publisher_headers(ref["newspaper"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the four
    known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_rejected
    """
    resp = api.list_notices({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
