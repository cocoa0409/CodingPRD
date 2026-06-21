"""Entity creation, validation, defaults, computed/system fields, immutability.

Translates queue B (Corner / entities) instances and the consistency_model
immediate-consistency instance.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_provider_headers,
    make_payer_headers,
    register_actors,
    set_clock,
    create_under_review_request,
    create_approved_request,
    create_draft_request,
)

ANON = TEST_USERS["anonymous_headers"]


def test_create_authorization_request_returns_201_with_fields(api):
    """PRD §3.2: "A `Provider` opens a prior-authorization request, which is
    created in the `DRAFT` state." PRD §3.2: "At creation the system copies the
    member's payer onto the request's `payer_id` field, so the request inherits
    the member's insurer automatically." PRD §2.5: "The `version` field is an
    integer that begins at its initial value and increments by one on every
    mutation of the resource."

    Design: Corner/entities/create_authorization_request_returns_201_with_fields
    """
    actors = register_actors(with_reviewer=False)
    prov = actors["provider"]
    resp = api.create_authorization_request(
        {
            "member_id": actors["member"]["id"],
            "provider_id": prov["id"],
            "request_type": "DRUG",
            "procedure_code": "NDC-1",
            "requested_units": 2,
            "unit_cost_cents": 5000,
        },
        make_provider_headers(prov["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
    assert data["payer_id"] == actors["payer"]["id"], "payer_id must be copied from member"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def test_create_request_missing_requested_units_validation(api):
    """PRD §3.2: "the `requested_units` (the number of units, sessions, or days,
    which must be at least 1)". PRD §3.9: "A request missing a required input
    field or carrying a value of the wrong type, enum, or range is rejected with
    `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_request_missing_requested_units_validation
    """
    actors = register_actors(with_reviewer=False)
    prov = actors["provider"]
    resp = api.create_authorization_request(
        {
            "member_id": actors["member"]["id"],
            "provider_id": prov["id"],
            "request_type": "DRUG",
            "procedure_code": "NDC-1",
            "unit_cost_cents": 5000,
        },
        make_provider_headers(prov["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_request_nonexistent_returns_not_found(api):
    """PRD §2.7: "the first reference that does not resolve to an existing row
    causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_request_nonexistent_returns_not_found
    """
    actors = register_actors(with_reviewer=False)
    resp = api.get_authorization_request(
        "00000000-0000-0000-0000-000000000000",
        make_provider_headers(actors["provider"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_member_coinsurance_rate_default_applied(api):
    """PRD §3.1: "an optional `coinsurance_rate` — the fraction of approved cost
    the member bears out of pocket — which must be at least 0.0 and at most 1.0
    and defaults to 0.2."

    Design: Corner/entities/member_coinsurance_rate_default_applied
    """
    payer = get_success_data(api.create_payer({"name": "Acme Health"}, ANON))
    resp = api.create_member({"payer_id": payer["id"], "member_number": "M1"}, ANON)
    data = validate_success(resp, expected_status=201)
    assert data["coinsurance_rate"] == 0.2, f"expected default 0.2, got {data['coinsurance_rate']}"


def test_request_type_invalid_enum_rejected(api):
    """PRD §3.2: "a `request_type` of either `SERVICE` or `DRUG`". PRD §3.9:
    "A request missing a required input field or carrying a value of the wrong
    type, enum, or range is rejected with `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/request_type_invalid_enum_rejected
    """
    actors = register_actors(with_reviewer=False)
    prov = actors["provider"]
    resp = api.create_authorization_request(
        {
            "member_id": actors["member"]["id"],
            "provider_id": prov["id"],
            "request_type": "SUPPLY",
            "procedure_code": "X",
            "requested_units": 1,
            "unit_cost_cents": 5000,
        },
        make_provider_headers(prov["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_member_active_auth_count_computed_field_starts_zero(api):
    """PRD §3.5: "Each `Member` carries a computed `active_authorization_count`:
    the number of that member's authorization requests in the `APPROVED` state
    whose `authorization_expires_at` is still in the future relative to the
    current clock."

    Design: Corner/entities/member_active_auth_count_computed_field_starts_zero
    """
    actors = register_actors(with_reviewer=False)
    resp = api.get_member(
        actors["member"]["id"], make_provider_headers(actors["provider"]["id"])
    )
    data = validate_success(resp)
    assert data["active_authorization_count"] == 0, (
        f"fresh member must have 0 active auths, got {data['active_authorization_count']}"
    )


def test_clinical_evidence_immutable_no_version_field(api):
    """PRD §2.5: "The one exception is `ClinicalEvidence`, which is immutable
    after upload: an evidence record carries only `id` and `created_at`, and has
    neither `updated_at` nor `version`."

    Design: Corner/entities/clinical_evidence_immutable_no_version_field
    """
    actors = register_actors(with_reviewer=False)
    prov = actors["provider"]
    req = create_draft_request(actors, request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-1"})
    resp = api.create_clinical_evidence(
        {"request_id": req["id"], "document_type": "IMAGING", "line_item_cost_cents": 0, "uri": "s3://x"},
        make_provider_headers(prov["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert "id" in data and "created_at" in data
    assert "version" not in data, "ClinicalEvidence must not expose a version field"


def test_approve_reflects_computed_fields_same_response_immediate(api):
    """PRD §2.6: "no derived counter, deadline, or status is left stale after the
    operation that affects it returns." PRD §3.3: "recomputes `member_cost_share_cents`
    using the approved units, sets `authorization_expires_at` to the current clock
    plus 365 days". PRD §3.5: "the system multiplies the request's `unit_cost_cents`
    by the member's `coinsurance_rate`, rounds that single-unit product half up to
    a whole cent, and then multiplies the rounded per-unit share by the effective
    number of units."

    Design: Corner/consistency_model/approve_reflects_computed_fields_same_response_immediate
    """
    actors = register_actors(member_overrides={"coinsurance_rate": 0.2})
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    approved = create_approved_request(
        actors,
        request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1",
                           "requested_units": 1, "unit_cost_cents": 10000},
        approved_units=1,
    )
    # fetch fresh to prove immediate consistency
    resp = api.get_authorization_request(
        approved["id"], make_provider_headers(actors["provider"]["id"])
    )
    data = validate_success(resp)
    assert data["approved_units"] == 1
    assert data["member_cost_share_cents"] == 2000, (
        f"10000*0.2=2000 per unit * 1 unit; got {data['member_cost_share_cents']}"
    )
    assert data["authorization_expires_at"] == "2027-06-01T00:00:00Z", (
        f"expiry should be clock + 365 days; got {data['authorization_expires_at']}"
    )
