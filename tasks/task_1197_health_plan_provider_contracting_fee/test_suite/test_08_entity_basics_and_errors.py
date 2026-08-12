"""Corner coverage: entity creation/defaults, not-found errors, basic envelope."""
from test_helpers import (
    get_success_data, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_benchmark_payload, create_contract_payload,
    create_contract_version_payload, create_fee_schedule_entry_payload,
    create_network, create_network_payload, create_provider, create_provider_payload,
    create_draft_contract,
    make_contract_legal_headers, make_contract_manager_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["plan_admin_headers"]
CA = TEST_USERS["configuration_analyst_headers"]
CM = TEST_USERS["contract_manager_headers"]


class TestProviderCreationAppliesSystemDefaults:
    def test_provider_created_active_with_version_1(self, api):
        """PRD §3.2: "The provider record carries a `provider_status` that begins
        as `ACTIVE`"
        PRD §2.4: "`version` (integer): a system-managed counter that increments
        by one on every mutation of the resource"

        Design: Corner/entities/provider_creation_applies_system_defaults
        """
        resp = api.create_provider(create_provider_payload(), ADMIN)
        data = get_success_data(resp)
        assert resp.status_code == 201
        assert data["provider_status"] == "ACTIVE"
        assert data["version"] == 1
        assert data["id"]
        assert data["created_at"]
        assert data["updated_at"]


class TestContractAndEntryDefaultsApplied:
    def _setup(self, api):
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        contract = get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        contract = get_success_data(api.sign_contract(
            contract["id"], make_contract_legal_headers("cl-1")))
        contract = get_success_data(api.begin_configuration(contract["id"], CA))
        version = get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract["version"]),
            CM,
        ))
        return contract, version

    def test_contract_auto_renew_defaults_false(self, api):
        """PRD §3.2: "an optional `auto_renew` flag that defaults to false"

        Design: Corner/entities/contract_and_entry_defaults_applied
        """
        contract, _ = self._setup(api)
        fetched = get_success_data(api.get_contract(contract["id"], ADMIN))
        assert fetched["auto_renew"] is False

    def test_entry_benchmark_lookup_mode_defaults_strict(self, api):
        """PRD §3.4: "An optional `benchmark_lookup_mode` of `STRICT` or
        `PROVISIONAL` defaults to `STRICT`."

        Design: Corner/entities/contract_and_entry_defaults_applied
        """
        _, version = self._setup(api)
        payload = create_fee_schedule_entry_payload(
            hcpcs_code="99213", rate_type="FLAT_RATE", flat_rate_cents=5000)
        payload.pop("pct_of_medicare_bps", None)
        entry = get_success_data(api.create_fee_schedule_entry(version["id"], payload, CA))
        assert entry["benchmark_lookup_mode"] == "STRICT"


class TestMissingRequiredTin:
    def test_provider_without_tin_rejected(self, api):
        """PRD §2.10: "Request conformance — the body must conform to the
        endpoint's input schema: required fields present, types valid, enum
        values within their declared sets, and no undeclared fields. Violations
        yield `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/provider_missing_required_tin_returns_invalid_request
        """
        payload = {"legal_name": "Prov A", "npi": "NPI-A", "locality_code": "L01"}
        resp = api.create_provider(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestContractInvalidEnum:
    def test_escalator_mode_monthly_rejected(self, api):
        """PRD §3.2: "an `escalator_mode` of either `ANNIVERSARY` or `CALENDAR`"
        PRD §2.10: "Violations yield `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/contract_invalid_enum_returns_invalid_request
        """
        net = create_network()
        prov = create_provider()
        payload = create_contract_payload(network_id=net["id"], escalator_mode="MONTHLY")
        resp = api.create_contract(prov["id"], payload, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestContractGetNotFound:
    def test_unknown_contract_id_returns_not_found(self, api):
        """PRD §3.2: "any contract id that fails to resolve — on any
        contract-scoped endpoint — produces `ERR_CONTRACT_NOT_FOUND`."

        Design: Corner/entities/contract_get_returns_not_found
        """
        resp = api.get_contract(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND)


class TestNestedCreateWithUnknownParent:
    def test_create_contract_unknown_provider(self, api):
        """PRD §3.2: "the path provider must resolve (`ERR_PROVIDER_NOT_FOUND`)"

        Design: Corner/entities/nested_create_with_unknown_parent_returns_not_found
        """
        net = create_network()
        resp = api.create_contract(
            NON_EXISTENT_UUID,
            create_contract_payload(network_id=net["id"]),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_FOUND)


class TestAuditEventImmutableShape:
    def test_audit_events_have_no_version_field(self, api):
        """PRD §2.4: "An audit event is immutable once appended, so it carries
        only `id` and `created_at`; `updated_at` and `version` are absent from
        it by design."
        PRD §3.2: "its creation appends a `CONTRACT_CREATED` event to its own
        audit trail."

        Design: Corner/entities/audit_event_immutable_shape
        """
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        events = get_success_data(api.list_audit_events(contract["id"], ADMIN))
        assert len(events) >= 1
        types = {e["event_type"] for e in events}
        assert "CONTRACT_CREATED" in types
        for e in events:
            assert e["id"]
            assert e["created_at"]
            assert e["event_type"]
            assert e["actor_role"]
            assert e["actor_id"]
            assert e["occurred_at"]
            assert "version" not in e
            assert "updated_at" not in e


class TestEntryComputedRateAfterMapping:
    def test_computed_rate_null_then_populated_by_mapping(self, api):
        """PRD §3.4: "Freshly created entries are `STAGED` (their
        `entry_status`), with `medicare_benchmark_id`, `resolved_benchmark_cents`,
        and `computed_rate_cents` all unset — each is null until mapping."
        PRD §3.4: "A successful mapping stamps `medicare_benchmark_id` and
        `resolved_benchmark_cents` from the resolved row and computes the
        entry's `computed_rate_cents`: for percent-of-Medicare entries, the
        resolved benchmark cents multiplied by `pct_of_medicare_bps` and divided
        by ten thousand, rounded half up to whole cents"

        Design: Corner/entities/entry_computed_rate_after_mapping
        """
        from test_helpers import create_published_benchmark
        net = create_network()
        bench = create_published_benchmark()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        contract = get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        contract = get_success_data(api.sign_contract(
            contract["id"], make_contract_legal_headers("cl-1")))
        contract = get_success_data(api.begin_configuration(contract["id"], CA))
        version = get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract["version"]),
            CM,
        ))
        entry = get_success_data(api.create_fee_schedule_entry(
            version["id"], create_fee_schedule_entry_payload(), CA))
        assert entry["computed_rate_cents"] is None

        mapped = get_success_data(api.map_benchmark(entry["id"], CA))
        assert mapped["computed_rate_cents"] == 10000
        assert mapped["resolved_benchmark_cents"] == 10000
        assert mapped["medicare_benchmark_id"] == bench["id"]


class TestProvidersListPaginationDefaults:
    def test_list_providers_default_pagination(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted ... The `offset` parameter specifies how many
        items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/providers_list_pagination_defaults
        """
        create_provider()
        resp = api.list_providers(ADMIN)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(data) == 1


class TestProviderGetRoundTrip:
    def test_get_returns_stored_fields(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/endpoints/provider_get_round_trip
        """
        prov = create_provider()
        fetched = get_success_data(api.get_provider(prov["id"], ADMIN))
        assert fetched["tin"] == "TIN-A"
        assert fetched["locality_code"] == "L01"
        assert fetched["legal_name"] == "Prov A"
        assert fetched["npi"] == "NPI-A"


class TestResponseEnvelopeMetaPresent:
    def test_object_response_carries_meta(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_meta_present
        """
        net = create_network()
        resp = api.get_network(net["id"], ADMIN)
        body = resp.json()
        assert "meta" in body
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        assert "data" in body

    def test_error_response_carries_error_id_and_message(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error. The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_meta_present
        """
        resp = api.get_contract(NON_EXISTENT_UUID, ADMIN)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_CONTRACT_NOT_FOUND"
        assert "message" in body["data"]


class TestReverseReachabilityListsChildren:
    def test_list_versions_returns_created_version(self, api):
        """PRD §3.4: "Rates never attach to a contract directly; they attach to a
        **contract version**"
        PRD §4: GET `/contracts/{id}/versions` "List versions of a contract"

        Design: Corner/endpoints/reverse_reachability_lists_children
        """
        net = create_network()
        prov = create_provider()
        contract = create_draft_contract(network_id=net["id"], provider_id=prov["id"])
        contract = get_success_data(api.begin_negotiation(contract["id"], CM))
        contract = get_success_data(api.submit_for_signature(
            contract["id"], make_contract_manager_headers("cm-1")))
        contract = get_success_data(api.sign_contract(
            contract["id"], make_contract_legal_headers("cl-1")))
        contract = get_success_data(api.begin_configuration(contract["id"], CA))
        version = get_success_data(api.create_contract_version(
            contract["id"],
            create_contract_version_payload(
                version_number=1, effective_date="2026-07-01",
                expected_contract_version=contract["version"]),
            CM,
        ))
        versions = get_success_data(api.list_contract_versions(contract["id"], ADMIN))
        assert len(versions) == 1
        assert versions[0]["id"] == version["id"]
        assert versions[0]["version_number"] == 1
