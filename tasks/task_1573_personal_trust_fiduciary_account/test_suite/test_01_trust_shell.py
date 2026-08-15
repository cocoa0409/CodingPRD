"""Trust account shell: request shape, server-minted fields, envelope shape,
pagination, and not-found addressing."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_trust_account,
    create_trust_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OFFICER, create_trust


class TestCreateTrustValidation:
    def test_missing_trust_type_rejected(self, api):
        """PRD §2.8: "required fields are present, enum values are valid,
        integer cent amounts and units are positive where required,
        date strings are valid, `effective_from` is strictly earlier than
        `effective_to`, `share_bps` lies between 1 and 10000 inclusive, `limit`
        lies within its 1 to 100 range, and a TrustDocument's `version_number`
        is unique within its trust; any violation yields `ERR_VALIDATION`."

        Design: Corner/entities/create_trust_missing_required_and_invalid_enum_rejected
        """
        payload = create_trust_payload()
        del payload["trust_type"]
        resp = api.create_trust(payload, OFFICER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_invalid_trust_type_enum_rejected(self, api):
        """PRD §2.8: "required fields are present, enum values are valid,
        integer cent amounts and units are positive where required,
        date strings are valid, `effective_from` is strictly earlier than
        `effective_to`, `share_bps` lies between 1 and 10000 inclusive, `limit`
        lies within its 1 to 100 range, and a TrustDocument's `version_number`
        is unique within its trust; any violation yields `ERR_VALIDATION`."

        Design: Corner/entities/create_trust_missing_required_and_invalid_enum_rejected
        """
        resp = api.create_trust(create_trust_payload(trust_type="FOOBAR"), OFFICER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        data, meta = validate_paginated(api.list_trusts(OFFICER))
        assert meta["total_count"] == 0, "nothing may be persisted by rejected creates"


class TestServerMintedFields:
    def test_client_supplied_id_and_computed_fields_ignored(self, api):
        """PRD §2.4: "Every primary resource carries a server-minted `id`
        formatted as a UUID with no type prefix, a `created_at` timestamp
        recording when the resource was created, an `updated_at` timestamp
        refreshed on every mutation, and a `version` integer that increments
        by one on every mutation."
        PRD §2.6: "`income_balance_cents` is the sum of `amount_cents` over
        all of the trust's ledger rows in the INCOME bucket, and
        `principal_balance_cents` is the same sum over the PRINCIPAL bucket;
        both default to zero when no rows exist."

        Design: Corner/entities/system_and_computed_fields_input_ignored
        """
        payload = create_trust_payload(
            trust_name="Ignored Fields", id="client-supplied", income_balance_cents=999999
        )
        data = validate_success(api.create_trust(payload, OFFICER), expected_status=201)
        assert data["id"] != "client-supplied", "server must mint its own id"
        assert is_valid_uuid(data["id"])
        assert data["income_balance_cents"] == 0
        assert data["principal_balance_cents"] == 0
        assert data["version"] == 1
        assert_trust_account(data)

    def test_balances_default_to_zero_without_rows(self, api):
        """PRD §2.6: "`income_balance_cents` is the sum of `amount_cents` over
        all of the trust's ledger rows in the INCOME bucket, and
        `principal_balance_cents` is the same sum over the PRINCIPAL bucket;
        both default to zero when no rows exist."

        Design: Corner/entities/system_and_computed_fields_input_ignored
        """
        trust = create_trust()
        assert trust["income_balance_cents"] == 0
        assert trust["principal_balance_cents"] == 0
        assert trust["available_income_cents"] == 0
        assert trust["available_principal_cents"] == 0


class TestNotFoundAddressing:
    def test_missing_trust_id_yields_trust_not_found(self, api):
        """PRD §2.8: "path identifiers are validated left to right: a missing
        trust id yields `ERR_TRUST_NOT_FOUND`, and any other missing path id
        or body foreign-key id yields `ERR_RESOURCE_NOT_FOUND`."

        Design: Corner/entities/not_found_returns_404_per_resource_kind
        """
        resp = api.get_trust(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_TRUST_NOT_FOUND)

    def test_missing_document_id_yields_resource_not_found(self, api):
        """PRD §2.8: "path identifiers are validated left to right: a missing
        trust id yields `ERR_TRUST_NOT_FOUND`, and any other missing path id
        or body foreign-key id yields `ERR_RESOURCE_NOT_FOUND`."

        Design: Corner/entities/not_found_returns_404_per_resource_kind
        """
        resp = api.get_document(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


class TestPagination:
    def test_list_defaults_and_meta_fields(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10, and any value outside the inclusive range of 1 to
        100 is rejected with `ERR_VALIDATION`. The `offset` parameter controls
        how many items are skipped and defaults to 0. Unless otherwise
        specified, list endpoints return resources sorted by `created_at` in
        ascending order. The `meta` object of a list response carries exactly
        the pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_pagination_defaults_and_limit_cap
        """
        for name in ("P1", "P2", "P3"):
            create_trust(trust_name=name, trust_type="REVOCABLE", distribution_standard="HEMS")
        data, meta = validate_paginated(api.list_trusts(OFFICER))
        assert meta["total_count"] == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert len(data) == 3

    def test_limit_above_max_rejected(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10, and any value outside the inclusive range of 1 to
        100 is rejected with `ERR_VALIDATION`."

        Design: Corner/entities/list_pagination_defaults_and_limit_cap
        """
        resp = api.list_trusts(OFFICER, params={"limit": 101})
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestResponseEnvelope:
    def test_single_read_uses_object_envelope(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        Design: Corner/endpoints/response_envelope_object_and_array
        """
        trust = create_trust(trust_name="Envelope")
        resp = api.get_trust(trust["id"], OFFICER)
        data = validate_success(resp)
        body = resp.json()
        assert body["response_type"] == "object"
        assert data["id"] == trust["id"]
        req_id = body["meta"]["api_request_id"]
        assert isinstance(req_id, str) and req_id.startswith("req_"), (
            f"api_request_id must start with req_, got {req_id!r}"
        )
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    def test_list_read_uses_array_envelope_with_pagination_fields(self, api):
        """PRD §2.3: "The `meta` object of a list response carries exactly the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_object_and_array
        """
        create_trust(trust_name="Envelope List")
        resp = api.list_trusts(OFFICER)
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert isinstance(data, list)
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"meta missing pagination field {field}"
