"""Portfolio setup, lease creation, and response-envelope claims."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_lease_space_record,
    create_project_record,
    create_property_record,
    create_tenant_record,
    create_active_lease,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPropertyDefaults:
    def test_property_creation_applies_default_capacity(self, api, landlord_pm_headers):
        """PRD 3.1: "Creating a property captures its display `name`, street
        `address`, and optionally `max_concurrent_construction_projects` — the
        cap on simultaneously overlapping construction windows across the whole
        building, which defaults to 2 when omitted and must be an integer of at
        least 1 when given."

        Design: Corner/entities/property_creation_applies_default_capacity
        """
        resp = api.create_property(
            {"name": "Default Tower", "address": "100 Default Ave"}, landlord_pm_headers
        )
        data = validate_success(resp, 201)
        assert data["max_concurrent_construction_projects"] == 2, (
            f"omitted capacity must default to 2, got "
            f"{data['max_concurrent_construction_projects']!r}"
        )


class TestLeaseCreation:
    def test_lease_creation_defaults_abatement_basis_calendar(self, api, landlord_pm_headers):
        """PRD 3.1: "optionally selects the `abatement_basis` — `CALENDAR` or
        `BUSINESS` — that the rent-abatement computation will later use,
        defaulting to `CALENDAR`. A new lease is `DRAFT`, its
        `delay_responsibility` is `NONE`, its `rent_abatement_credit_cents` is 0,
        and its `actual_rent_commencement_date` stays null until an occupancy
        certificate is issued."

        Design: Corner/entities/lease_creation_defaults_abatement_basis_calendar
        """
        prop = create_property_record()
        space = create_lease_space_record(prop["id"])
        tenant = create_tenant_record()
        payload = {
            "space_id": space["id"],
            "tenant_id": tenant["id"],
            "base_rent_annual_cents": 36_500_000,
            "scheduled_rent_commencement_date": "2026-10-01T00:00:00Z",
            "lease_term_months": 60,
        }
        resp = api.create_lease(payload, landlord_pm_headers)
        data = validate_success(resp, 201)
        assert data["abatement_basis"] == "CALENDAR"
        assert data["status"] == "DRAFT", f"new lease must be DRAFT, got {data['status']!r}"
        assert data["rent_abatement_credit_cents"] == 0

    def test_lease_missing_required_field_returns_invalid_request(self, api, landlord_pm_headers):
        """PRD 2.7: "5. **Body well-formedness.** Required fields are present,
        types are correct, enum members are valid, and monetary amounts are
        integer cents, else `ERR_INVALID_REQUEST` (400)."
        PRD 3.1: "the creation payload names the `space_id` of the premises and
        the `tenant_id` of the occupant, fixes the economics through
        `base_rent_annual_cents` (a strictly positive integer),
        `scheduled_rent_commencement_date` (the contractual rent start,
        normalized to UTC midnight), and `lease_term_months` (a strictly
        positive integer)"

        Design: Corner/entities/lease_missing_required_field_returns_invalid_request
        """
        prop = create_property_record()
        space = create_lease_space_record(prop["id"])
        tenant = create_tenant_record()
        payload = {
            "space_id": space["id"],
            "tenant_id": tenant["id"],
            # base_rent_annual_cents intentionally omitted
            "scheduled_rent_commencement_date": "2026-10-01T00:00:00Z",
            "lease_term_months": 60,
        }
        resp = api.create_lease(payload, landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestProjectExistenceAndUniqueness:
    def test_get_nonexistent_project_returns_not_found(self, api, landlord_pm_headers):
        """PRD 2.7: "4. **Existence.** Every resource id named in the URL path
        must exist, validated left to right from the outermost resource inward,
        else `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/get_nonexistent_project_returns_not_found
        """
        resp = api.get_project(NON_EXISTENT_UUID, landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_second_active_project_on_same_lease_rejected(self, api, landlord_pm_headers):
        """PRD 3.2: "One lease supports at most one non-terminal project:
        creating a second while any project of the lease sits outside
        `COMPLETED` and `CANCELLED` is rejected with
        `ERR_ACTIVE_PROJECT_EXISTS` (HTTP 409)."

        Design: Corner/state_machines/second_active_project_on_same_lease_rejected
        """
        prop = create_property_record()
        space = create_lease_space_record(prop["id"])
        tenant = create_tenant_record()
        lease = create_active_lease(space["id"], tenant["id"])
        first = create_project_record(lease["id"], project_name="TI-1")
        assert first["status"] == "INITIATED"
        resp = api.create_ti_project(
            lease["id"],
            {"project_name": "TI-2", "base_contract_cents": 1_000_000},
            landlord_pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_PROJECT_EXISTS)


class TestResponseEnvelope:
    def test_list_endpoint_pagination_envelope(self, api, landlord_pm_headers):
        """PRD 2.3: "List endpoints accept two query parameters. `limit` bounds
        the page size: it defaults to 10, must be at least 1, and may not exceed
        100. `offset` selects the starting position within the full result set
        and defaults to 0."
        PRD 2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count` (the full unpaginated count of matching
        resources), and `has_more` (whether further pages exist beyond the
        returned window)."

        Design: Corner/endpoints/list_endpoint_pagination_envelope
        """
        prop = create_property_record()
        create_lease_space_record(prop["id"], suite_number="1", floor=1, rentable_sqft=1000)
        create_lease_space_record(prop["id"], suite_number="2", floor=1, rentable_sqft=1200)
        resp = api.list_lease_spaces(prop["id"], landlord_pm_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith(
            "req_"
        ), "meta.api_request_id must be a server-generated req_ identifier (PRD 2.2)"
        assert len(data) == 2
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']!r}"
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

    def test_error_envelope_shape_on_404(self, api, landlord_pm_headers):
        """PRD 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." PRD 2.2: "The
        `error_id` is a unique, machine-readable string that identifies the
        specific error." PRD 2.2: "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape_on_404
        """
        resp = api.get_property(NON_EXISTENT_UUID, landlord_pm_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert body.get("response_type") == "error"
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["message"].strip(), "error message must be a non-empty explanation"
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
            f"error meta must contain only api_request_id and api_request_timestamp, "
            f"got {sorted(body['meta'].keys())}"
        )
