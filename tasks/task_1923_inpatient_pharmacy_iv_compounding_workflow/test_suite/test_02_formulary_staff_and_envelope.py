"""Configuration layer: drug defaults, staff schema, envelopes, 404s (PRD §2, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    assert_drug_product,
    validate_error,
    validate_success,
)


class TestDrugProductDefaults:
    def test_drug_create_applies_prd_documented_defaults(self, api, admin_headers):
        """PRD §3.1: "The `renal_dosing_policy` selects which weight variant feeds the Cockcroft-Gault equation at verification — `IBW` (the default) or `ABW_WHEN_OBESE`."
        PRD §3.1: "While a drug sits on the shortage list its `in_shortage` flag is true, which gates protocol activation; the flag and the formulary `status` (`ACTIVE` by default, `DISCONTINUED` when withdrawn) are the two fields a `PharmacyAdmin` can update on an existing drug, and either update increments the drug's `version`."

        Design: Corner/entities/drug_product_create_defaults
        """
        drug = validate_success(
            api.create_drug_product(
                {
                    "name": "Defaults Drug",
                    "schedule": "C_IV",
                    "concentration_mg_per_ml": 5.0,
                    "vial_size_ml": 2.0,
                },
                admin_headers,
            ),
            201,
        )
        assert_drug_product(drug)
        assert drug["renal_dosing_policy"] == "IBW"
        assert drug["status"] == "ACTIVE"


class TestStaffSchemaValidation:
    def test_staff_role_outside_enum_rejected(self, api, admin_headers):
        """PRD §3.1: "A `PharmacyAdmin` registers each staff member with a `full_name` and a `staff_role` drawn from `PRESCRIBER`, `PHARMACIST`, `TECHNICIAN`, or `NURSE`."
        PRD §2.7: "then request-body well-formedness — required fields present, types valid, enum values in range (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/staff_create_invalid_enum_returns_400
        """
        resp = api.create_staff_member(
            {"full_name": "Bad Role", "staff_role": "DOCTOR"}, admin_headers
        )
        validate_error(resp, "ERR_INVALID_REQUEST", 400)


class TestNotFoundAndErrorEnvelope:
    def test_get_order_with_nonexistent_id_returns_404(self, api, admin_headers):
        """PRD §2.8: "Whenever an endpoint path contains resource identifiers, the system validates them sequentially, left to right, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource."

        Design: Corner/entities/order_get_not_found_returns_404
        """
        resp = api.get_medication_order(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", admin_headers
        )
        validate_error(resp, "ERR_NOT_FOUND", 404)

    def test_error_envelope_shape_on_404(self, api, admin_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format:"
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

        Design: Corner/endpoints/response_envelope_error_shape
        """
        resp = api.get_drug_product(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", admin_headers
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)

    def test_get_order_nonexistent_uuid_also_404(self, api, admin_headers):
        """PRD §2.8: "Whenever an endpoint path contains resource identifiers, the system validates them sequentially, left to right, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource."

        Design: Corner/entities/order_get_not_found_returns_404
        """
        resp = api.get_medication_order(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, "ERR_NOT_FOUND", 404)
