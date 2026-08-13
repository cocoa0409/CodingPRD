"""Response envelope shape, authentication/authorization, pagination
defaults, FK reverse reachability, and not-found errors."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_charge_record,
    create_contract,
    create_cycle,
    create_facility,
    create_payer,
    create_service_item,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import ADMIN, AUDITOR, CONSUMER, MANAGER, OFFICER


class TestEnvelopeShape:
    def test_success_envelope_shape_on_create(self, api):
        """PRD section 2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD section 2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."
        PRD section 2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD section 4: "Operations that create a new resource — registering a facility, payer, contract, service item, charge record, rate, shoppable list, publication cycle, machine-readable file, or discrepancy report — return `201 Created`."

        Design: Corner/endpoints/success_envelope_shape_on_create
        """
        resp = api.create_payer({"name": "PA", "payer_type": "COMMERCIAL"},
                                MANAGER)
        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        data = body["data"]
        assert is_valid_uuid(data["id"])
        assert data["created_at"] == data["updated_at"]
        assert data["version"] == 1

    def test_error_envelope_shape_on_failure(self, api):
        """PRD section 2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD section 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD section 2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape_on_failure
        """
        resp = api.create_payer({"name": "PA"}, MANAGER)
        assert resp.status_code == 400
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {
            "api_request_id", "api_request_timestamp"}
        assert body["data"]["error_id"] == "ERR_INVALID_REQUEST"
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0


class TestAuthentication:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD section 2.1: "A request missing either header, or carrying an empty value in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        resp = api.create_facility(
            {"name": "F", "cms_certification_number": "CCN-H1",
             "bed_count": 50}, headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400


class TestRbac:
    def test_rbac_contract_manager_cannot_create_service_item(self, api):
        """PRD section 2.1: "A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 2.1: "A `TransparencyOfficer` staffs the price-transparency office and owns service items, charge extraction, publication cycles, machine-readable files, shoppable lists, and the correction workflow."

        Design: Corner/rbac/rbac_contract_manager_cannot_create_service_item
        """
        resp = api.create_service_item(
            {"facility_id": NON_EXISTENT_UUID, "code": "70551",
             "code_type": "CPT", "description": "MRI",
             "service_class": "SHOPPABLE", "gross_charge_cents": 100000},
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403

    def test_rbac_officer_cannot_create_payer(self, api):
        """PRD section 2.1: "A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 2.1: "A `ContractManager` owns payer relations — payers, contracts, and negotiated rates."

        Design: Corner/rbac/rbac_officer_cannot_create_payer
        """
        resp = api.create_payer({"name": "PA", "payer_type": "COMMERCIAL"},
                                OFFICER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_officer_cannot_triage_discrepancy(self, api):
        """PRD section 2.1: "A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 2.1: "A `ComplianceAuditor` is the liaison to CMS: it submits attestations and corrective-action plans and triages discrepancy reports, and it is deliberately segregated from correction propose/approve/apply and from the CMS decision proxy."

        Design: Corner/rbac/rbac_officer_cannot_triage_discrepancy
        """
        resp = api.triage_discrepancy(
            NON_EXISTENT_UUID, {"outcome": "CONFIRMED"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_auditor_cannot_issue_cms_decision(self, api):
        """PRD section 2.1: "A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 2.1: "A `PlatformAdmin` is the hospital-system platform operator: it registers facilities, drives the test-only logical clock, and acts as the CMS decision proxy."

        Design: Corner/rbac/rbac_auditor_cannot_issue_cms_decision
        """
        fac = create_facility(name="F", cms_certification_number="CCN-R4",
                              bed_count=50)
        resp = api.cms_decision(fac["id"], {"decision": "ACCEPT_ATTESTATION"},
                                AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_consumer_cannot_freeze_cycle(self, api):
        """PRD section 2.1: "A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 2.1: "A `Consumer` is an anonymous public user of the shoppable display tool and discrepancy intake; it holds no exclusive write operations."

        Design: Corner/rbac/rbac_consumer_cannot_freeze_cycle
        """
        resp = api.freeze_cycle(NON_EXISTENT_UUID, CONSUMER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_platform_admin_cannot_validate_record(self, api):
        """PRD section 2.1: "A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 2.1: "A `TransparencyOfficer` staffs the price-transparency office and owns service items, charge extraction, publication cycles, machine-readable files, shoppable lists, and the correction workflow."

        Design: Corner/rbac/rbac_platform_admin_cannot_validate_record
        """
        resp = api.validate_charge_record(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_consumer_shared_read_allowed(self, api):
        """PRD section 2.1: "A `Consumer` is an anonymous public user of the shoppable display tool and discrepancy intake; it holds no exclusive write operations."
        PRD section 4: "| GET | `/transparency/facilities/{id}` | Read a facility incl. attestation posture and accrued penalty | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |"

        Design: Corner/rbac/rbac_consumer_shared_read_allowed
        """
        fac = create_facility(name="F", cms_certification_number="CCN-R7",
                              bed_count=50)
        data = get_success_data(api.get_facility(fac["id"], CONSUMER))
        assert data["id"] == fac["id"]


class TestPaginationAndReachability:
    def test_record_list_pagination_defaults_applied(self, api):
        """PRD section 2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD section 2.3: "The `offset` parameter skips a number of items from the front of the result set and defaults to 0."
        PRD section 2.3: "Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/record_list_pagination_defaults_applied
        """
        fac = create_facility(name="F", cms_certification_number="CCN-P1",
                              bed_count=50)
        si1 = create_service_item(fac["id"], code="70551", description="MRI",
                                  gross_charge_cents=100000)
        si2 = create_service_item(fac["id"], code="70450", description="CT",
                                  gross_charge_cents=80000)
        cycle = create_cycle(fac["id"])
        create_charge_record(fac["id"], cycle["id"], si1["id"],
                             discounted_cash_cents=50000)
        create_charge_record(fac["id"], cycle["id"], si2["id"],
                             discounted_cash_cents=40000)
        resp = api.list_charge_records(CONSUMER)
        assert resp.json()["response_type"] == "array"
        records, meta = validate_paginated(resp)
        assert len(records) == 2
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_fk_reverse_reachability_filtered_list_and_subresource(self, api):
        """PRD section 4: "| GET | `/transparency/standard-charge-records` | List/filter charge records by facility, cycle, item, supersedes target, or status | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |"
        PRD section 4: "| GET | `/transparency/payers/{id}/payer-contracts` | List contracts of a payer | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |"

        Design: Corner/endpoints/fk_reverse_reachability_filtered_list_and_subresource
        """
        fac = create_facility(name="F", cms_certification_number="CCN-P2",
                              bed_count=50)
        pa = create_payer(name="PA")
        pb = create_payer(name="PB")
        ca = create_contract(fac["id"], pa["id"])
        item = create_service_item(fac["id"], code="70551", description="MRI",
                                   gross_charge_cents=100000)
        cy_a = create_cycle(fac["id"])
        cy_b = create_cycle(fac["id"], period_start="2026-09-01T00:00:00Z",
                            period_end="2026-10-01T00:00:00Z")
        r_a = create_charge_record(fac["id"], cy_a["id"], item["id"],
                                   discounted_cash_cents=50000)
        # Children are findable from parents, scoped to the named parent only.
        records, meta = validate_paginated(api.list_charge_records(
            CONSUMER, params={"publication_cycle_id": cy_a["id"]}))
        assert len(records) == 1
        assert records[0]["id"] == r_a["id"]
        records, meta = validate_paginated(api.list_charge_records(
            CONSUMER, params={"publication_cycle_id": cy_b["id"]}))
        assert records == []
        assert meta["total_count"] == 0
        contracts, _ = validate_paginated(
            api.list_payer_contracts(pa["id"], CONSUMER))
        assert len(contracts) == 1
        assert contracts[0]["id"] == ca["id"]
        contracts, _ = validate_paginated(
            api.list_payer_contracts(pb["id"], CONSUMER))
        assert contracts == []


class TestNotFound:
    def test_facility_not_found_returns_404(self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung. The ladder runs: first, the authentication headers of §2.1 (presence, then role permission); second, existence — every identifier in the URL path is resolved left to right, and then every foreign-key reference in the request body is resolved in the body's declared field order, with a missing resource producing the corresponding 404 (`ERR_FACILITY_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_CHARGE_RECORD_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_SHOPPABLE_LIST_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, or `ERR_DISCREPANCY_NOT_FOUND`); third, state legality — the target resource must be in a status where the requested transition is defined (the 409 state errors); fourth, regulatory safety — segregation of duties, attestation-year alignment, and the consumer-display feature flag (`ERR_SOD_SAME_USER`, `ERR_ATTESTATION_YEAR_MISMATCH`, `ERR_DISPLAY_DISABLED`); fifth, structural constraints — duplicates, window overlaps, and entry composition rules; sixth, cross-referential coherence — the referenced records must belong to one another as the workflow requires; seventh, temporal sanity (`ERR_INVALID_WINDOW`); and last, fiscal and threshold rules."

        Design: Corner/errors/facility_not_found_returns_404
        """
        resp = api.get_facility(NON_EXISTENT_UUID, CONSUMER)
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_FOUND)
        assert resp.status_code == 404

    def test_payer_not_found_returns_404(self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung. The ladder runs: first, the authentication headers of §2.1 (presence, then role permission); second, existence — every identifier in the URL path is resolved left to right, and then every foreign-key reference in the request body is resolved in the body's declared field order, with a missing resource producing the corresponding 404 (`ERR_FACILITY_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_CHARGE_RECORD_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_SHOPPABLE_LIST_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, or `ERR_DISCREPANCY_NOT_FOUND`); third, state legality — the target resource must be in a status where the requested transition is defined (the 409 state errors); fourth, regulatory safety — segregation of duties, attestation-year alignment, and the consumer-display feature flag (`ERR_SOD_SAME_USER`, `ERR_ATTESTATION_YEAR_MISMATCH`, `ERR_DISPLAY_DISABLED`); fifth, structural constraints — duplicates, window overlaps, and entry composition rules; sixth, cross-referential coherence — the referenced records must belong to one another as the workflow requires; seventh, temporal sanity (`ERR_INVALID_WINDOW`); and last, fiscal and threshold rules."

        Design: Corner/errors/payer_not_found_returns_404
        """
        resp = api.get_payer(NON_EXISTENT_UUID, CONSUMER)
        validate_error(resp, ApiErrorId.ERR_PAYER_NOT_FOUND)

    def test_contract_not_found_returns_404(self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung. The ladder runs: first, the authentication headers of §2.1 (presence, then role permission); second, existence — every identifier in the URL path is resolved left to right, and then every foreign-key reference in the request body is resolved in the body's declared field order, with a missing resource producing the corresponding 404 (`ERR_FACILITY_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_CHARGE_RECORD_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_SHOPPABLE_LIST_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, or `ERR_DISCREPANCY_NOT_FOUND`); third, state legality — the target resource must be in a status where the requested transition is defined (the 409 state errors); fourth, regulatory safety — segregation of duties, attestation-year alignment, and the consumer-display feature flag (`ERR_SOD_SAME_USER`, `ERR_ATTESTATION_YEAR_MISMATCH`, `ERR_DISPLAY_DISABLED`); fifth, structural constraints — duplicates, window overlaps, and entry composition rules; sixth, cross-referential coherence — the referenced records must belong to one another as the workflow requires; seventh, temporal sanity (`ERR_INVALID_WINDOW`); and last, fiscal and threshold rules."

        Design: Corner/errors/contract_not_found_returns_404
        """
        resp = api.activate_contract(NON_EXISTENT_UUID, MANAGER)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND)

    def test_service_item_not_found_returns_404(self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung. The ladder runs: first, the authentication headers of §2.1 (presence, then role permission); second, existence — every identifier in the URL path is resolved left to right, and then every foreign-key reference in the request body is resolved in the body's declared field order, with a missing resource producing the corresponding 404 (`ERR_FACILITY_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_CHARGE_RECORD_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_SHOPPABLE_LIST_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, or `ERR_DISCREPANCY_NOT_FOUND`); third, state legality — the target resource must be in a status where the requested transition is defined (the 409 state errors); fourth, regulatory safety — segregation of duties, attestation-year alignment, and the consumer-display feature flag (`ERR_SOD_SAME_USER`, `ERR_ATTESTATION_YEAR_MISMATCH`, `ERR_DISPLAY_DISABLED`); fifth, structural constraints — duplicates, window overlaps, and entry composition rules; sixth, cross-referential coherence — the referenced records must belong to one another as the workflow requires; seventh, temporal sanity (`ERR_INVALID_WINDOW`); and last, fiscal and threshold rules."

        Design: Corner/errors/service_item_not_found_returns_404
        """
        fac = create_facility(name="F", cms_certification_number="CCN-ER1",
                              bed_count=50)
        item = create_service_item(fac["id"], code="70551", description="MRI",
                                   gross_charge_cents=100000)
        # The borrowed OCC version is irrelevant: existence is checked first.
        resp = api.patch_service_item(
            NON_EXISTENT_UUID,
            {"gross_charge_cents": 1,
             "expected_service_item_version": item["version"]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_SERVICE_ITEM_NOT_FOUND)

    def test_charge_record_not_found_returns_404(self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung. The ladder runs: first, the authentication headers of §2.1 (presence, then role permission); second, existence — every identifier in the URL path is resolved left to right, and then every foreign-key reference in the request body is resolved in the body's declared field order, with a missing resource producing the corresponding 404 (`ERR_FACILITY_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_CHARGE_RECORD_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_SHOPPABLE_LIST_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, or `ERR_DISCREPANCY_NOT_FOUND`); third, state legality — the target resource must be in a status where the requested transition is defined (the 409 state errors); fourth, regulatory safety — segregation of duties, attestation-year alignment, and the consumer-display feature flag (`ERR_SOD_SAME_USER`, `ERR_ATTESTATION_YEAR_MISMATCH`, `ERR_DISPLAY_DISABLED`); fifth, structural constraints — duplicates, window overlaps, and entry composition rules; sixth, cross-referential coherence — the referenced records must belong to one another as the workflow requires; seventh, temporal sanity (`ERR_INVALID_WINDOW`); and last, fiscal and threshold rules."

        Design: Corner/errors/charge_record_not_found_returns_404
        """
        resp = api.get_charge_record(NON_EXISTENT_UUID, CONSUMER)
        validate_error(resp, ApiErrorId.ERR_CHARGE_RECORD_NOT_FOUND)

    def test_rate_not_found_returns_404(self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung. The ladder runs: first, the authentication headers of §2.1 (presence, then role permission); second, existence — every identifier in the URL path is resolved left to right, and then every foreign-key reference in the request body is resolved in the body's declared field order, with a missing resource producing the corresponding 404 (`ERR_FACILITY_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_CHARGE_RECORD_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_SHOPPABLE_LIST_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, or `ERR_DISCREPANCY_NOT_FOUND`); third, state legality — the target resource must be in a status where the requested transition is defined (the 409 state errors); fourth, regulatory safety — segregation of duties, attestation-year alignment, and the consumer-display feature flag (`ERR_SOD_SAME_USER`, `ERR_ATTESTATION_YEAR_MISMATCH`, `ERR_DISPLAY_DISABLED`); fifth, structural constraints — duplicates, window overlaps, and entry composition rules; sixth, cross-referential coherence — the referenced records must belong to one another as the workflow requires; seventh, temporal sanity (`ERR_INVALID_WINDOW`); and last, fiscal and threshold rules."

        Design: Corner/errors/rate_not_found_returns_404
        """
        resp = api.get_rate(NON_EXISTENT_UUID, CONSUMER)
        validate_error(resp, ApiErrorId.ERR_RATE_NOT_FOUND)

    def test_shoppable_list_not_found_returns_404(self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung. The ladder runs: first, the authentication headers of §2.1 (presence, then role permission); second, existence — every identifier in the URL path is resolved left to right, and then every foreign-key reference in the request body is resolved in the body's declared field order, with a missing resource producing the corresponding 404 (`ERR_FACILITY_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_CHARGE_RECORD_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_SHOPPABLE_LIST_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, or `ERR_DISCREPANCY_NOT_FOUND`); third, state legality — the target resource must be in a status where the requested transition is defined (the 409 state errors); fourth, regulatory safety — segregation of duties, attestation-year alignment, and the consumer-display feature flag (`ERR_SOD_SAME_USER`, `ERR_ATTESTATION_YEAR_MISMATCH`, `ERR_DISPLAY_DISABLED`); fifth, structural constraints — duplicates, window overlaps, and entry composition rules; sixth, cross-referential coherence — the referenced records must belong to one another as the workflow requires; seventh, temporal sanity (`ERR_INVALID_WINDOW`); and last, fiscal and threshold rules."

        Design: Corner/errors/shoppable_list_not_found_returns_404
        """
        resp = api.display_list(NON_EXISTENT_UUID, CONSUMER)
        validate_error(resp, ApiErrorId.ERR_SHOPPABLE_LIST_NOT_FOUND)

    def test_cycle_not_found_returns_404(self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung. The ladder runs: first, the authentication headers of §2.1 (presence, then role permission); second, existence — every identifier in the URL path is resolved left to right, and then every foreign-key reference in the request body is resolved in the body's declared field order, with a missing resource producing the corresponding 404 (`ERR_FACILITY_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_CHARGE_RECORD_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_SHOPPABLE_LIST_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, or `ERR_DISCREPANCY_NOT_FOUND`); third, state legality — the target resource must be in a status where the requested transition is defined (the 409 state errors); fourth, regulatory safety — segregation of duties, attestation-year alignment, and the consumer-display feature flag (`ERR_SOD_SAME_USER`, `ERR_ATTESTATION_YEAR_MISMATCH`, `ERR_DISPLAY_DISABLED`); fifth, structural constraints — duplicates, window overlaps, and entry composition rules; sixth, cross-referential coherence — the referenced records must belong to one another as the workflow requires; seventh, temporal sanity (`ERR_INVALID_WINDOW`); and last, fiscal and threshold rules."

        Design: Corner/errors/cycle_not_found_returns_404
        """
        resp = api.get_cycle(NON_EXISTENT_UUID, CONSUMER)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_FOUND)

    def test_file_not_found_returns_404(self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung. The ladder runs: first, the authentication headers of §2.1 (presence, then role permission); second, existence — every identifier in the URL path is resolved left to right, and then every foreign-key reference in the request body is resolved in the body's declared field order, with a missing resource producing the corresponding 404 (`ERR_FACILITY_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_CHARGE_RECORD_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_SHOPPABLE_LIST_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, or `ERR_DISCREPANCY_NOT_FOUND`); third, state legality — the target resource must be in a status where the requested transition is defined (the 409 state errors); fourth, regulatory safety — segregation of duties, attestation-year alignment, and the consumer-display feature flag (`ERR_SOD_SAME_USER`, `ERR_ATTESTATION_YEAR_MISMATCH`, `ERR_DISPLAY_DISABLED`); fifth, structural constraints — duplicates, window overlaps, and entry composition rules; sixth, cross-referential coherence — the referenced records must belong to one another as the workflow requires; seventh, temporal sanity (`ERR_INVALID_WINDOW`); and last, fiscal and threshold rules."

        Design: Corner/errors/file_not_found_returns_404
        """
        resp = api.validate_machine_file(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_FILE_NOT_FOUND)

    def test_discrepancy_not_found_returns_404(self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung. The ladder runs: first, the authentication headers of §2.1 (presence, then role permission); second, existence — every identifier in the URL path is resolved left to right, and then every foreign-key reference in the request body is resolved in the body's declared field order, with a missing resource producing the corresponding 404 (`ERR_FACILITY_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_CHARGE_RECORD_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_SHOPPABLE_LIST_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, or `ERR_DISCREPANCY_NOT_FOUND`); third, state legality — the target resource must be in a status where the requested transition is defined (the 409 state errors); fourth, regulatory safety — segregation of duties, attestation-year alignment, and the consumer-display feature flag (`ERR_SOD_SAME_USER`, `ERR_ATTESTATION_YEAR_MISMATCH`, `ERR_DISPLAY_DISABLED`); fifth, structural constraints — duplicates, window overlaps, and entry composition rules; sixth, cross-referential coherence — the referenced records must belong to one another as the workflow requires; seventh, temporal sanity (`ERR_INVALID_WINDOW`); and last, fiscal and threshold rules."

        Design: Corner/errors/discrepancy_not_found_returns_404
        """
        resp = api.get_discrepancy(NON_EXISTENT_UUID, CONSUMER)
        validate_error(resp, ApiErrorId.ERR_DISCREPANCY_NOT_FOUND)
