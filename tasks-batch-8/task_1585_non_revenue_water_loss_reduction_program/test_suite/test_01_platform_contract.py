"""Platform-wide contract: response envelope, auth, pagination, entity
creation defaults, uniqueness, and the audit trail (PRD §2.1-§2.4, §2.12, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_audit_event,
    assert_customer_meter,
    assert_dma,
    create_dma,
    create_dma_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestResponseEnvelope:
    def test_success_envelope_shape(self, api, program_director_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources." and "The `api_request_id` is a
        server-generated unique identifier for the request that starts with
        `req_`."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        res = api.create_dma(
            create_dma_payload(code="DMA-ENV", name="Envelope"),
            program_director_headers,
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert body["data"]["id"], "created resource must carry its id in data"

    def test_error_envelope_shape(self, api, program_director_headers):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
        unique, machine-readable string that identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        res = api.get_dma(NON_EXISTENT_UUID, program_director_headers)
        assert res.status_code == 404, res.text
        body = res.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }
        assert body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/unauthenticated_missing_headers
        """
        res = api.list_dmas(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestDmaCreation:
    def test_create_dma_defaults(self, api, program_director_headers):
        """PRD §3.1: "New DMAs begin with `posture` `OPEN`, no finalized balance,
        and an `open_leak_count` of zero."
        PRD §2.4: "`version` (integer): a system-managed integer that increments
        by one on every modification of the resource, including modifications
        caused by derived-field recomputation on that resource."

        Design: Corner/entities/dma_create_success_and_defaults
        """
        res = api.create_dma(
            create_dma_payload(code="DMA-EN1", name="Entity One",
                               connection_count=100, mains_length_km=5.0,
                               target_nrw_pct=10.0),
            program_director_headers,
        )
        dma = validate_success(res, 201)
        assert_dma(dma)
        assert dma["posture"] == "OPEN"
        assert dma["open_leak_count"] == 0
        assert dma["latest_nrw_pct"] is None
        assert dma["version"] == 1

    def test_duplicate_dma_code_rejected(self, api, program_director_headers):
        """PRD §3.1: "A duplicate `code` is rejected with `ERR_DUPLICATE`."

        Design: Corner/entities/dma_duplicate_code_rejected
        """
        first = api.create_dma(
            create_dma_payload(code="DMA-DUP", name="First"),
            program_director_headers,
        )
        validate_success(first, 201)
        res = api.create_dma(
            create_dma_payload(code="DMA-DUP", name="Second", connection_count=200),
            program_director_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE, expected_status=409)

    def test_get_nonexistent_dma_returns_not_found(self, api, program_director_headers):
        """PRD §2.8: "Requests that target nested resources validate path
        identifiers sequentially from left to right, rejecting with
        `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve
        to an existing row."

        Design: Corner/entities/entity_not_found_returns_404
        """
        res = api.get_dma(NON_EXISTENT_UUID, program_director_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_missing_required_field_rejected(self, api, program_director_headers):
        """PRD §2.7: "Scalar constraints — numeric ranges, enum membership,
        required-field presence, and cross-field orderings on individual fields;
        failure yields `ERR_VALIDATION` (HTTP 422)."

        Design: Corner/entities/missing_required_field_returns_validation_error
        """
        payload = create_dma_payload(code="DMA-MISS", name="Missing Field")
        del payload["connection_count"]
        res = api.create_dma(payload, program_director_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=422)


class TestPagination:
    def test_dma_list_pagination_envelope(self, api, program_director_headers):
        """PRD §2.3: "`limit` caps the number of items returned: it defaults to
        10 when omitted, accepts a minimum of 1, and accepts a maximum of 100.
        `offset` states how many items to skip and defaults to 0." and "The
        `meta` object of a list response carries four pagination fields:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/dma_list_pagination_envelope
        """
        for i in range(1, 4):
            res = api.create_dma(
                create_dma_payload(code=f"DMA-PG{i}", name=f"Page {i}",
                                   connection_count=100, mains_length_km=5.0,
                                   target_nrw_pct=10.0),
                program_director_headers,
            )
            validate_success(res, 201)

        page1, meta1 = validate_paginated(
            api.list_dmas(program_director_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_dmas(program_director_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestMeterDefaults:
    def test_meter_create_applies_default_policy(self, api, meter_technician_headers):
        """PRD §3.5: "an optional `replacement_policy` selecting the replacement
        lane: `AGE_BASED` replaces on age alone, `ACCURACY_BASED` replaces on a
        failed accuracy test alone, and `HYBRID` applies whichever trigger fires
        first; omitted, the policy defaults to `ACCURACY_BASED`." and "A new
        meter begins `IN_SERVICE`, with `last_test_accuracy_pct` null until a
        test completes"

        Design: Corner/entities/meter_create_default_policy_applied
        """
        dma = create_dma(code="DMA-EN2", connection_count=100, mains_length_km=5.0,
                         target_nrw_pct=10.0)
        res = api.create_customer_meter(
            {
                "dma_id": dma["id"],
                "serial_number": "SN-EN2",
                "size_mm": 15,
                "installed_at": "2022-01-01T00:00:00Z",
            },
            meter_technician_headers,
        )
        meter = validate_success(res, 201)
        assert_customer_meter(meter)
        assert meter["replacement_policy"] == "ACCURACY_BASED"
        assert meter["status"] == "IN_SERVICE"
        assert meter["last_test_accuracy_pct"] is None


class TestAuditTrail:
    def test_mutation_appends_queryable_audit_event(self, api, program_director_headers):
        """PRD §2.12: "Every mutating operation — every create, every state
        transition, and every system-driven transition — appends an **audit
        event**." and "They may be listed by `ProgramDirector` and
        `RegulatorLiaison`, with optional filters on `entity_type`, `entity_id`,
        and `actor_user_id`."
        PRD §2.4: "The audit event is the single exception: because it is an
        immutable, append-only record, it carries only `id` and `created_at`;
        both `updated_at` and `version` are absent."

        Design: Corner/endpoints/audit_events_recorded_for_mutations
        """
        dma = create_dma(code="DMA-AUD", connection_count=100, mains_length_km=5.0,
                         target_nrw_pct=10.0)

        data, meta = validate_paginated(
            api.list_audit_events(
                program_director_headers,
                params={"entity_type": "DistrictMeteredArea", "entity_id": dma["id"]},
            )
        )
        assert meta["total_count"] >= 1
        matches = [e for e in data if e["entity_id"] == dma["id"]]
        assert matches, "expected an audit event for the DMA creation"
        event = matches[0]
        assert_audit_event(event)
        assert event["entity_type"] == "DistrictMeteredArea"
        assert event["actor_role"] == "ProgramDirector"
        assert event["actor_user_id"] == "pd-1"
