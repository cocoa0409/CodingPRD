"""Corrective actions: manual creation, investigation, segregation of duties
on resolution."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_batch,
    make_compliance_manager_headers,
    validate_error,
    validate_success,
)

CM = TEST_USERS["compliance_manager_headers"]


class TestSegregationOfDuties:
    def test_segregation_of_duties_on_resolve(self, api):
        """PRD: "From `INVESTIGATING`, the resolve action transitions to
        `RESOLVED` — but only if the resolving `X-User-ID` differs from the
        CA's `opened_by` (segregation of duties). Violation yields
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The resolver provides a
        `resolution_note`; the system sets `closed_by` to the resolver's
        `X-User-ID`."

        Design: Corner/validations/segregation_of_duties_on_resolve
        """
        batch = create_batch(target_species="COD", product_form="FILLET")
        cm01 = make_compliance_manager_headers("cm-01")
        cm02 = make_compliance_manager_headers("cm-02")

        ca = validate_success(api.create_corrective_action(
            {"source_type": "MANUAL", "processing_batch_id": batch["id"],
             "reason": "audit finding"}, cm01), 201)
        assert ca["opened_by"] == "cm-01"

        validate_success(api.investigate_corrective_action(ca["id"], cm02))

        # The opener cannot resolve their own corrective action.
        resp = api.resolve_corrective_action(ca["id"],
                                             "self-resolution attempt", cm01)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        # A different ComplianceManager can.
        resolved = validate_success(api.resolve_corrective_action(
            ca["id"], "independent resolution", cm02))
        assert resolved["status"] == "RESOLVED"
        assert resolved["closed_by"] == "cm-02"
