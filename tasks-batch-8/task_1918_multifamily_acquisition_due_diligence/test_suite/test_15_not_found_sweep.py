"""Per-resource 404 sweep: every entity type reports its own error id."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_error,
)

ANALYST = TEST_USERS["analyst_headers"]
UM1 = TEST_USERS["underwriting_manager_headers"]
POL1 = TEST_USERS["property_ops_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]

MISSING = {
    "unit": "00000000-0000-0000-0000-000000000001",
    "lease": "00000000-0000-0000-0000-000000000002",
    "concession": "00000000-0000-0000-0000-000000000003",
    "inspection": "00000000-0000-0000-0000-000000000004",
    "finding": "00000000-0000-0000-0000-000000000005",
    "utility": "00000000-0000-0000-0000-000000000006",
    "projection": "00000000-0000-0000-0000-000000000007",
    "deposit": "00000000-0000-0000-0000-000000000008",
    "decision": "00000000-0000-0000-0000-000000000009",
    "contract": "00000000-0000-0000-0000-00000000000a",
    "policy": "00000000-0000-0000-0000-00000000000b",
    "statement": "00000000-0000-0000-0000-00000000000c",
    "adjustment": "00000000-0000-0000-0000-00000000000d",
}


class TestNotFoundErrorsAcrossResources:
    def test_not_found_errors_across_resources(self, api):
        """PRD §2.4: "The 404 family is one error per entity type:
        `ERR_ACQUISITION_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_LEASE_FILE_NOT_FOUND`, `ERR_CONCESSION_NOT_FOUND`,
        `ERR_INSPECTION_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
        `ERR_UTILITY_RECORD_NOT_FOUND`, `ERR_TAX_PROJECTION_NOT_FOUND`,
        `ERR_DEPOSIT_NOT_FOUND`, `ERR_EMPLOYEE_DECISION_NOT_FOUND`,
        `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_INSURANCE_POLICY_NOT_FOUND`,
        `ERR_PRORATION_STATEMENT_NOT_FOUND`, and `ERR_ADJUSTMENT_NOT_FOUND`."

        Design: Corner/entities/not_found_errors_across_resources
        """
        cases = [
            (api.exclude_unit(MISSING["unit"], ANALYST),
             ApiErrorId.ERR_UNIT_NOT_FOUND),
            (api.audit_lease_file(MISSING["lease"], ANALYST),
             ApiErrorId.ERR_LEASE_FILE_NOT_FOUND),
            (api.verify_concession(MISSING["concession"], 100, ANALYST),
             ApiErrorId.ERR_CONCESSION_NOT_FOUND),
            (api.complete_inspection(MISSING["inspection"], 3, True, POL1),
             ApiErrorId.ERR_INSPECTION_NOT_FOUND),
            (api.verify_finding(MISSING["finding"], POL1),
             ApiErrorId.ERR_FINDING_NOT_FOUND),
            (api.get_utility_record(MISSING["utility"], ANALYST),
             ApiErrorId.ERR_UTILITY_RECORD_NOT_FOUND),
            (api.compute_tax_projection(MISSING["projection"], ANALYST),
             ApiErrorId.ERR_TAX_PROJECTION_NOT_FOUND),
            (api.reconcile_deposit(MISSING["deposit"], ANALYST),
             ApiErrorId.ERR_DEPOSIT_NOT_FOUND),
            (api.approve_employee_decision(MISSING["decision"], UM1),
             ApiErrorId.ERR_EMPLOYEE_DECISION_NOT_FOUND),
            (api.assume_service_contract(MISSING["contract"], VM1),
             ApiErrorId.ERR_SERVICE_CONTRACT_NOT_FOUND),
            (api.review_loss_runs(MISSING["policy"], UM1),
             ApiErrorId.ERR_INSURANCE_POLICY_NOT_FOUND),
            (api.get_proration_statement(MISSING["statement"], UM1),
             ApiErrorId.ERR_PRORATION_STATEMENT_NOT_FOUND),
            (api.evidence_adjustment(MISSING["adjustment"],
                                     {"evidence_note": "x"}, ANALYST),
             ApiErrorId.ERR_ADJUSTMENT_NOT_FOUND),
        ]
        for resp, expected in cases:
            err = validate_error(resp, expected, 404)
            assert err["error_id"] == expected.value, (
                f"expected the resource-specific 404 {expected.value}"
            )
