"""Lead CRUD, response envelope, pagination, required-field validation, and the
zero-pier scope-finalize boundary (PRD §3.1, §2.2, §2.3, §2.6, §3.2)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_lead,
    create_completed_inspection,
    create_draft_scope,
    create_lead_payload,
    api_client,
    SALES,
    ENGINEER,
    NON_EXISTENT_UUID,
    ApiErrorId,
)


class TestLeadCrud:
    def test_create_lead_returns_201_and_envelope(self, api):
        """PRD §3.1: "A freshly created lead starts with a `financing_balance_cents` of 0 and
        an `active_visit_count` of 0; both are derived figures the system maintains, never
        client inputs."

        Design: Corner/entities/lead_create_returns_201_and_envelope
        """
        res = api.create_lead(create_lead_payload(customer_name="Env Owner"), SALES)
        lead = validate_success(res, 201)
        body = res.json()
        assert body["response_type"] == "object", body
        assert isinstance(body["meta"]["api_request_id"], str), body
        assert lead["financing_balance_cents"] == 0, lead
        assert lead["active_visit_count"] == 0, lead

    def test_get_nonexistent_lead_returns_not_found(self, api):
        """PRD §2.6: "the first identifier that does not resolve causes the request to be
        rejected with `ERR_NOT_FOUND` before any business rule runs."

        Design: Corner/entities/lead_get_nonexistent_returns_not_found
        """
        res = api.get_lead(NON_EXISTENT_UUID, SALES)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_list_leads_reports_pagination_meta(self, api):
        """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/lead_list_returns_pagination_fields
        """
        create_lead(region_code="SOUTH", customer_name="List Owner")
        res = api.list_leads(SALES)
        data, meta = validate_paginated(res)
        assert res.json()["response_type"] == "array", res.text
        assert meta["total_count"] == 1, meta
        assert meta["has_more"] is False, meta

    def test_create_lead_missing_region_code_rejected(self, api):
        """PRD §3.1: "supplying the `customer_name`, the `property_address`, the homeowner
        `contact_email`, and a `region_code` drawn from `NORTH`, `SOUTH`, `EAST`, or `WEST`."
        PRD §2.10: "(4) request-body schema validity — required fields present, enum values
        in range, numbers well-typed — yielding `ERR_VALIDATION`"

        Design: Corner/entities/lead_missing_required_field_returns_validation
        """
        payload = create_lead_payload()
        del payload["region_code"]
        res = api.create_lead(payload, SALES)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)


class TestScopeFinalizePierFloor:
    def test_finalize_zero_pier_scope_rejected(self, api):
        """PRD §3.2: "finalization requires that `pier_count` be at least 1, and a scope with
        no piers is rejected with `ERR_NO_PIERS`."

        Design: Difficulty/boundary_precision_check/zero_pier_scope_finalize_empty_set
        """
        lead = create_lead(region_code="NORTH")
        inspection = create_completed_inspection(lead["id"], soil_class="STABLE")
        scope = create_draft_scope(lead, inspection["id"], pier_count=0, anchor_count=2,
                                   avg_pier_depth_ft=12)
        res = api.finalize_scope(scope["id"], ENGINEER)
        validate_error(res, ApiErrorId.ERR_NO_PIERS.value)

    def test_finalize_one_pier_scope_succeeds(self, api):
        """PRD §3.2: "finalization requires that `pier_count` be at least 1, and a scope with
        no piers is rejected with `ERR_NO_PIERS`."

        Design: Difficulty/boundary_precision_check/zero_pier_scope_finalize_empty_set
        """
        lead = create_lead(region_code="NORTH")
        inspection = create_completed_inspection(lead["id"], soil_class="STABLE")
        scope = create_draft_scope(lead, inspection["id"], pier_count=1, anchor_count=0,
                                   avg_pier_depth_ft=12)
        # pier_count == 1 is exactly the floor -> finalize succeeds.
        finalized = validate_success(api.finalize_scope(scope["id"], ENGINEER), 200)
        assert finalized["status"] == "ENGINEERED", finalized
