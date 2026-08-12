"""Property intake, response envelope, listing, pagination, and append-only ledger shape."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_property_payload,
    assert_oreo_property,
    assert_ledger_entry,
    is_valid_uuid,
)

ADMIN = TEST_USERS["oreo_admin_headers"]
COMP = TEST_USERS["compliance_officer_headers"]


class TestPropertyIntake:
    def test_create_property_applies_defaults_and_computed_fields(self, api):
        """PRD §3.1: "Intake runs the provisional variant of the acquisition
        accounting rule: fair_value_at_acquisition is set equal to bpo_value, and
        acquisition_basis is computed as fair_value_at_acquisition minus eight
        percent of fair_value_at_acquisition rounded half-up to two decimal places
        — the cost-to-sell allowance of 0.08. The new property lands in
        lifecycle_status HELD, its appraisal_status is UNAPPRAISED because no
        certified appraisal exists yet, carrying_value starts equal to
        acquisition_basis with both capitalized_cost_total and expensed_cost_total
        at zero, recognized_gain_loss_total starts at zero, and an ACQUISITION
        ledger entry carrying positive acquisition_basis is appended. The
        holding_deadline is anchored at acquisition_date plus the statutory
        holding period of 1825 days — five years — with extension_days_approved
        starting at zero."

        Design: Corner/entities/create_property_applies_defaults_and_computed_fields
        """
        resp = api.create_property(
            create_property_payload(
                address="1420 Maple St",
                state_code="CA",
                county="Alameda",
                property_type="RESIDENTIAL",
                acquisition_date="2026-05-10",
                bpo_value=400000.00,
                foreclosure_debt=410000.00,
            ),
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert_oreo_property(data)
        assert data["version"] == 1
        assert data["lifecycle_status"] == "HELD"
        assert data["appraisal_status"] == "UNAPPRAISED"
        assert data["fair_value_at_acquisition"] == 400000.00
        assert data["acquisition_basis"] == 368000.00
        assert data["carrying_value"] == 368000.00
        assert data["capitalized_cost_total"] == 0.00
        assert data["expensed_cost_total"] == 0.00
        assert data["recognized_gain_loss_total"] == 0.00
        assert data["extension_days_approved"] == 0
        # holding_deadline == acquisition_date + 1825 days = 2031-05-09
        assert data["holding_deadline"].startswith("2031-05-09")

        # ACQUISITION ledger entry
        ledger_resp = api.list_ledger_entries(ADMIN, params={"property_id": data["id"]})
        entries, meta = validate_paginated(ledger_resp)
        acq = [e for e in entries if e["entry_type"] == "ACQUISITION"]
        assert len(acq) == 1
        assert acq[0]["amount"] == 368000.00

    def test_create_property_missing_required_field_returns_400(self, api):
        """PRD §2.10: "enum values in payloads are exact UPPERCASE strings" and
        PRD §5: ERR_VALIDATION -> 400 for "Missing required field, invalid type,
        invalid enum member, or range violation".

        Design: Corner/entities/create_property_missing_required_field_returns_400
        """
        payload = create_property_payload()
        payload.pop("bpo_value")
        resp = api.create_property(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_create_property_invalid_property_type_returns_400(self, api):
        """PRD §3.1: "property_type (one of RESIDENTIAL, COMMERCIAL, INDUSTRIAL,
        or LAND)"; §5 ERR_VALIDATION 400 for invalid enum member.

        Design: Corner/entities/create_property_invalid_property_type_returns_400
        """
        resp = api.create_property(
            create_property_payload(property_type="MOBILE_HOME"), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_create_property_ignores_client_supplied_id_input_ignored(self, api):
        """PRD §2.4: "Every persisted resource carries a server-minted id as an
        opaque UUID with no type prefix".

        Design: Corner/entities/create_property_ignores_client_supplied_id_input_ignored
        """
        supplied_id = "00000000-0000-0000-0000-000000000000"
        resp = api.create_property(
            create_property_payload(id=supplied_id), ADMIN
        )
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])
        assert data["id"] != supplied_id, "server-minted UUID must win over client id"


class TestPropertyReadAndList:
    def test_get_property_not_found_returns_404(self, api):
        """PRD §5: ERR_NOT_FOUND 404 for "Path id or body FK reference does not
        exist".

        Design: Corner/entities/get_property_not_found_returns_404
        """
        resp = api.get_property(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_properties_pagination_defaults(self, api):
        """PRD §2.3: "limit defaults to 10, must be at least 1, and must not
        exceed 100. offset defaults to 0 and must be non-negative. List responses
        sort by created_at ascending unless a specific endpoint documents a
        different ordering, and the meta envelope reports limit, offset,
        total_count, and has_more so callers can walk long collections without
        guessing."

        PRD §3.12: "The property list accepts optional lifecycle_status,
        appraisal_status, and state_code filters".

        Design: Corner/entities/list_properties_pagination_defaults
        """
        api.create_property(
            create_property_payload(
                address="1 A St", state_code="CA", acquisition_date="2026-05-10"
            ),
            ADMIN,
        )
        api.create_property(
            create_property_payload(
                address="2 B St",
                state_code="NV",
                county="Clark",
                property_type="LAND",
                acquisition_date="2026-05-11",
                bpo_value=150000.00,
                foreclosure_debt=148000.00,
            ),
            ADMIN,
        )

        # limit=1, offset=0
        resp = api.list_properties(ADMIN, params={"limit": 1})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

        # filter by state_code=NV
        resp = api.list_properties(ADMIN, params={"state_code": "NV"})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert data[0]["state_code"] == "NV"


class TestLedgerShape:
    def test_ledger_entry_has_no_version_field_immutability(self, api):
        """PRD §2.4: "Two entities deliberately break that pattern: CarryingCost
        and LedgerEntry carry only id and created_at — neither updated_at nor
        version exists on those rows, because costs and ledger postings are
        append-only facts."
        PRD §2.7: "ACQUISITION carries a positive acquisition_basis".

        Design: Corner/entities/ledger_entry_has_no_version_field_immutability
        """
        prop_resp = api.create_property(create_property_payload(), ADMIN)
        prop = validate_success(prop_resp, expected_status=201)

        list_resp = api.list_ledger_entries(ADMIN, params={"property_id": prop["id"]})
        entries, _meta = validate_paginated(list_resp)
        assert len(entries) >= 1
        entry_id = entries[0]["id"]

        one_resp = api.get_ledger_entry(entry_id, ADMIN)
        entry = validate_success(one_resp, expected_status=200)
        assert_ledger_entry(entry)
        assert "version" not in entry
        assert "updated_at" not in entry
        assert entry["entry_type"] == "ACQUISITION"
        assert entry["amount"] == 368000.00


class TestBrokerDefaults:
    def test_broker_score_null_before_first_closing(self, api):
        """PRD §3.4: "a new broker starts ACTIVE with a null performance_score
        because it has no settled closings yet."
        PRD §3.11: "A broker with zero settled closings has a null
        performance_score."

        Design: Corner/entities/broker_score_null_before_first_closing
        """
        from test_helpers import create_broker_payload

        resp = api.create_broker(create_broker_payload(), ADMIN)
        broker = validate_success(resp, expected_status=201)
        assert broker["status"] == "ACTIVE"
        assert broker.get("performance_score") is None


class TestResponseEnvelope:
    def test_response_envelope_conformance(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body: ... meta ...
        response_type ... data ..." and the error format: "The meta object for
        error responses contains only api_request_id and api_request_timestamp.
        The error_id is a unique, machine-readable string ... The message
        provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_conformance
        """
        api.create_property(create_property_payload(), ADMIN)

        # success envelope (list)
        list_resp = api.list_properties(ADMIN)
        body = list_resp.json()
        assert "meta" in body and "response_type" in body and "data" in body
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "array"
        assert isinstance(body["data"], list)
        for f in ("limit", "offset", "total_count", "has_more"):
            assert f in body["meta"]

        # error envelope
        err_resp = api.get_property(NON_EXISTENT_UUID, ADMIN)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert "message" in err_body["data"]
        assert "api_request_id" in err_body["meta"]
        assert "api_request_timestamp" in err_body["meta"]


class TestRBACIntake:
    def test_compliance_officer_cannot_create_property_forbidden(self, api):
        """PRD §4: "POST /api/oreo-properties | Take a foreclosed property into
        OREO at provisional fair value | OREOAdmin" — ComplianceOfficer is not
        on the authorized list.
        PRD §2.1: "A request whose role is not on the endpoint's authorized list
        is rejected with ERR_FORBIDDEN (HTTP 403)."

        Design: Corner/rbac/compliance_officer_cannot_create_property_forbidden
        """
        resp = api.create_property(create_property_payload(), COMP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
