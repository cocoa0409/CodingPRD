"""Registry basics: response envelope shape, authentication floor, generator
creation defaults, required-field and existence checks, the verify-triggered
GENERATOR account, and meter-reading list pagination/filtering."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_account,
    assert_generator,
    assert_meter_reading,
    create_active_generator,
    create_generator,
    create_generator_payload,
    create_meter_reading,
    get_generator_account,
    is_iso8601_timestamp,
    is_valid_uuid,
    submit_generator_for_verification,
    validate_error,
    validate_paginated,
    validate_success,
    verify_generator,
)


def test_generator_create_applies_defaults(api, registry_admin_headers):
    """PRD §3.1: "A new generator starts in `REGISTERED` status with
    `rejection_reason` unset, `cumulative_accepted_kwh` and `carryover_kwh` at
    zero, the minted total `lifetime_minted_mwh` at zero, and `next_serial` at
    1."
    PRD §4: "Operations that create a new resource — registering a generator,
    ... — return `201 Created`."

    Design: Corner/entities/generator_create_applies_defaults
    """
    resp = api.create_generator(
        create_generator_payload(
            legal_name="Sierra Solar", facility_code="SS1", technology="SOLAR",
            nameplate_capacity_kw=5000, region_code="CAISO",
            commissioning_date="2020-01-01",
        ),
        registry_admin_headers,
    )
    gen = validate_success(resp, expected_status=201)
    assert_generator(gen)
    assert gen["status"] == "REGISTERED", f"initial status must be REGISTERED, got {gen['status']}"
    assert gen["rejection_reason"] is None
    assert gen["cumulative_accepted_kwh"] == 0
    assert gen["carryover_kwh"] == 0
    assert gen["lifetime_minted_mwh"] == 0
    assert gen["next_serial"] == 1

    fetched = validate_success(api.get_generator(gen["id"], registry_admin_headers))
    assert_generator(fetched)
    assert fetched["status"] == "REGISTERED"


def test_generator_create_missing_required_field_rejected(api, registry_admin_headers):
    """PRD §2.8: "Request schema — all required fields are present and all
    types and enum values are valid (`ERR_VALIDATION`)."
    PRD §3.1: registration supplies "the balancing-authority `region_code`".

    Design: Corner/entities/generator_create_missing_required_field_rejected
    """
    payload = create_generator_payload(legal_name="Sierra Solar", facility_code="SS1")
    del payload["region_code"]
    resp = api.create_generator(payload, registry_admin_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_generator_get_not_found_returns_404(api, registry_admin_headers):
    """PRD §2.8: "Existence — path identifiers are resolved first, validated
    left to right ... (`ERR_NOT_FOUND`)."
    PRD §5: `ERR_NOT_FOUND` maps to HTTP 404.

    Design: Corner/entities/generator_get_not_found_returns_404
    """
    resp = api.get_generator(NON_EXISTENT_UUID, registry_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_body_fk_reference_not_found_returns_404(api):
    """PRD §2.8: "only then are the foreign keys referenced in the request
    body (`generator_id`, `program_id`, `subscription_id`, `certificate_id`,
    ...) resolved (`ERR_NOT_FOUND`)."

    Design: Corner/entities/body_fk_reference_not_found_returns_404
    """
    from test_helpers import make_generator_operator_headers

    resp = api.create_meter_reading(
        {
            "generator_id": NON_EXISTENT_UUID,
            "period_start": "2026-07-01T00:00:00Z",
            "period_end": "2026-08-01T00:00:00Z",
            "metered_kwh": 100,
        },
        # X-User-ID matches the (absent) generator id, so the §2.1 ownership
        # comparison passes and the existence check is what fires.
        make_generator_operator_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_response_envelope_shape_success_and_error(api, registry_admin_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." and "The `response_type` is
    either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/response_envelope_shape_success_and_error
    """
    gen = create_generator(legal_name="Sierra Solar")

    ok = api.get_generator(gen["id"], registry_admin_headers)
    body = ok.json()
    assert ok.status_code == 200
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id must start with 'req_'"
    )
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"
    assert body["data"]["id"] == gen["id"]

    err = api.get_generator(NON_EXISTENT_UUID, registry_admin_headers)
    err_body = err.json()
    assert err_body.get("response_type") == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"].strip()
    assert set(err_body["meta"].keys()) <= {"api_request_id", "api_request_timestamp"}, (
        "error meta must carry only api_request_id and api_request_timestamp"
    )


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request with missing headers, or whose role value is not
    one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    resp = api.create_generator(
        create_generator_payload(legal_name="No Auth", facility_code="NA1"),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_generator_verify_auto_creates_generator_account(api, registry_admin_headers):
    """PRD §3.1: "Verification moves the generator from `VERIFICATION` to
    `ACTIVE` and, as part of the same mutation, auto-creates its generator
    account: an `Account` with `account_type` `GENERATOR`, wired to the
    generator through `generator_id`, named after the generator's
    `legal_name` in `owner_name`, and starting in `ACTIVE` standing."

    Design: Corner/entities/generator_verify_auto_creates_generator_account
    """
    gen = create_generator(legal_name="Sierra Solar", facility_code="SS1")
    submit_generator_for_verification(gen["id"])
    verified = verify_generator(gen["id"])
    assert verified["status"] == "ACTIVE"

    data, meta = validate_paginated(
        api.list_accounts(registry_admin_headers, params={"generator_id": gen["id"]})
    )
    assert meta["total_count"] == 1, f"verify must auto-create exactly one account, got {meta['total_count']}"
    account = data[0]
    assert_account(account)
    assert account["account_type"] == "GENERATOR"
    assert account["status"] == "ACTIVE"
    assert account["owner_name"] == "Sierra Solar"
    assert account["failure_strikes"] == 0
    assert account["active_holdings_mwh"] == 0


def test_meter_reading_list_pagination_and_filter(api, registry_admin_headers):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10, with a minimum of 1 and a maximum of 100.
    The `offset` parameter sets the number of items skipped and defaults to
    0." and "the `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD §2.3: "meter readings by `generator_id` and `status`".

    Design: Corner/entities/meter_reading_list_pagination_and_filter
    """
    g = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    rids = []
    for start, end in (
        ("2026-07-01T00:00:00Z", "2026-07-05T00:00:00Z"),
        ("2026-07-05T00:00:00Z", "2026-07-10T00:00:00Z"),
        ("2026-07-10T00:00:00Z", "2026-07-15T00:00:00Z"),
    ):
        rids.append(create_meter_reading(g["id"], start, end, 10)["id"])

    g2 = create_active_generator(
        legal_name="Other Wind", facility_code="OW1", technology="WIND", region_code="ERCOT"
    )
    create_meter_reading(g2["id"], "2026-07-01T00:00:00Z", "2026-07-05T00:00:00Z", 10)

    resp1 = api.list_meter_readings(
        registry_admin_headers, params={"generator_id": g["id"], "limit": 2, "offset": 0}
    )
    body1 = resp1.json()
    assert body1.get("response_type") == "array"
    assert isinstance(body1["meta"].get("api_request_id"), str)
    page1, meta1 = validate_paginated(resp1)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_meter_readings(
            registry_admin_headers, params={"generator_id": g["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    for reading in page1 + page2:
        assert_meter_reading(reading)
        assert reading["generator_id"] == g["id"], "the generator_id filter excluded nothing"
    assert {r["id"] for r in page1 + page2} == set(rids)

    other, meta_other = validate_paginated(
        api.list_meter_readings(registry_admin_headers, params={"generator_id": g2["id"]})
    )
    assert meta_other["total_count"] == 1
    assert all(r["generator_id"] == g2["id"] for r in other)


def test_generator_account_discoverable_and_wired(api, registry_admin_headers):
    """PRD §3.4: "`GENERATOR` accounts arise automatically when a generator
    is verified and are never created directly" — the wiring is discoverable
    through the account list's `generator_id` filter (PRD §2.3: "accounts by
    `account_type`, `generator_id`, `program_id`, and `status`").

    Design: Corner/entities/generator_verify_auto_creates_generator_account
    """
    gen = create_active_generator(legal_name="Sierra Solar")
    account = get_generator_account(gen["id"])
    assert account["generator_id"] == gen["id"]
    assert account["account_type"] == "GENERATOR"
    assert is_valid_uuid(account["id"])
