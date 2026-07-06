"""Warranty-active gating on claim filing, and inspection completion state/enum rules
(PRD §3.8, §3.7, §3.1)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    setup_completed_install,
    create_lead,
    create_completed_inspection,
    create_inspection_payload,
    complete_inspection_payload,
    create_claim_payload,
    make_customer_headers,
    api_client,
    SALES,
    ENGINEER,
    ADMIN,
    ApiErrorId,
)


class TestClaimRequiresActiveWarranty:
    def test_file_claim_on_voided_warranty_rejected(self, api):
        """PRD §3.8: "The referenced warranty must be `ACTIVE`, or the filing is rejected
        with `ERR_WARRANTY_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/claim_file_requires_warranty_active
        """
        ctx = setup_completed_install()
        validate_success(api.void_warranty(ctx["warranty"]["id"], ADMIN), 200)
        headers = make_customer_headers(ctx["lead"]["id"])
        res = api.create_claim(create_claim_payload(ctx["warranty"]["id"]), headers)
        validate_error(res, ApiErrorId.ERR_WARRANTY_NOT_ACTIVE.value)

    def test_file_claim_on_active_warranty_succeeds(self, api):
        """PRD §3.8: "The claim opens in `FILED`."

        Design: Difficulty/cross_entity_state_dependency/claim_file_requires_warranty_active
        """
        ctx = setup_completed_install()  # warranty ACTIVE
        headers = make_customer_headers(ctx["lead"]["id"])
        claim = validate_success(
            api.create_claim(create_claim_payload(ctx["warranty"]["id"]), headers), 201
        )
        assert claim["status"] == "FILED", claim


class TestInspectionCompletion:
    def test_complete_already_completed_inspection_rejected(self, api):
        """PRD §3.1: "An attempt to complete or cancel an inspection that is not in
        `SCHEDULED` is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/inspection_complete_twice_returns_invalid_state
        """
        lead = create_lead(region_code="NORTH")
        inspection = create_completed_inspection(lead["id"], soil_class="STABLE")
        # Second completion on an already-COMPLETED (terminal) inspection.
        res = api.complete_inspection(inspection["id"], complete_inspection_payload(), ENGINEER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_complete_with_invalid_soil_enum_rejected(self, api):
        """PRD §3.1: "The `soil_class` is one of `STABLE`, `EXPANSIVE`, or `UNSTABLE`"
        PRD §2.10: "(4) request-body schema validity — required fields present, enum values
        in range, numbers well-typed — yielding `ERR_VALIDATION`"

        Design: Corner/entities/inspection_complete_invalid_enum_rejected
        """
        lead = create_lead(region_code="NORTH")
        inspection = get_success_data(
            api.create_inspection(create_inspection_payload(lead["id"]), SALES)
        )
        res = api.complete_inspection(
            inspection["id"], complete_inspection_payload(soil_class="ROCKY"), ENGINEER
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)
