"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5, §4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Lessee ---
    def create_lessee(self, payload, headers):
        return self._request("POST", "/lessees", payload, headers)

    def get_lessee(self, lessee_id, headers):
        return self._request("GET", f"/lessees/{lessee_id}", headers=headers)

    def reinstate_lessee(self, lessee_id, headers):
        return self._request(
            "POST", f"/lessees/{lessee_id}/reinstate", {}, headers
        )

    def terminate_lessee(self, lessee_id, headers):
        return self._request(
            "POST", f"/lessees/{lessee_id}/terminate", {}, headers
        )

    # --- Railcar / fleet ---
    def create_railcar(self, payload, headers):
        return self._request("POST", "/railcars", payload, headers)

    def list_railcars(self, headers, params=None):
        return self._request("GET", "/railcars", headers=headers, params=params)

    def get_railcar(self, railcar_id, headers):
        return self._request("GET", f"/railcars/{railcar_id}", headers=headers)

    def get_railcar_compliance(self, railcar_id, headers):
        return self._request(
            "GET", f"/railcars/{railcar_id}/compliance", headers=headers
        )

    def get_fleet_utilization(self, month, headers):
        return self._request(
            "GET", "/fleet/utilization", headers=headers, params={"month": month}
        )

    # --- TariffRate ---
    def create_tariff_rate(self, payload, headers):
        return self._request("POST", "/tariff-rates", payload, headers)

    def list_tariff_rates(self, headers, params=None):
        return self._request("GET", "/tariff-rates", headers=headers, params=params)

    def get_tariff_rate(self, tariff_id, headers):
        return self._request("GET", f"/tariff-rates/{tariff_id}", headers=headers)

    def amend_tariff_rate(self, tariff_id, payload, headers):
        return self._request("PUT", f"/tariff-rates/{tariff_id}", payload, headers)

    # --- LeaseAgreement ---
    def create_lease_agreement(self, payload, headers):
        return self._request("POST", "/lease-agreements", payload, headers)

    def list_lease_agreements(self, headers, params=None):
        return self._request(
            "GET", "/lease-agreements", headers=headers, params=params
        )

    def get_lease_agreement(self, lease_id, headers):
        return self._request(
            "GET", f"/lease-agreements/{lease_id}", headers=headers
        )

    def submit_lease_agreement(self, lease_id, headers):
        return self._request(
            "POST", f"/lease-agreements/{lease_id}/submit", {}, headers
        )

    def approve_lease_agreement(self, lease_id, headers):
        return self._request(
            "POST", f"/lease-agreements/{lease_id}/approve", {}, headers
        )

    def reject_lease_agreement(self, lease_id, headers):
        return self._request(
            "POST", f"/lease-agreements/{lease_id}/reject", {}, headers
        )

    def amend_lease_agreement(self, lease_id, payload, headers):
        return self._request(
            "PATCH", f"/lease-agreements/{lease_id}", payload, headers
        )

    def terminate_lease_agreement(self, lease_id, headers):
        return self._request(
            "POST", f"/lease-agreements/{lease_id}/terminate", {}, headers
        )

    def list_assignments_of_lease(self, lease_id, headers, params=None):
        return self._request(
            "GET",
            f"/lease-agreements/{lease_id}/assignments",
            headers=headers,
            params=params,
        )

    # --- LeaseAssignment ---
    def create_lease_assignment(self, payload, headers):
        return self._request("POST", "/lease-assignments", payload, headers)

    def list_lease_assignments(self, headers, params=None):
        return self._request(
            "GET", "/lease-assignments", headers=headers, params=params
        )

    def get_lease_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/lease-assignments/{assignment_id}", headers=headers
        )

    def deliver_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/lease-assignments/{assignment_id}/deliver", {}, headers
        )

    def return_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/lease-assignments/{assignment_id}/return", {}, headers
        )

    def settle_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/lease-assignments/{assignment_id}/settle", {}, headers
        )

    def cancel_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/lease-assignments/{assignment_id}/cancel", {}, headers
        )

    # --- MileageReport ---
    def create_mileage_report(self, payload, headers):
        return self._request("POST", "/mileage-reports", payload, headers)

    def list_mileage_reports(self, headers, params=None):
        return self._request(
            "GET", "/mileage-reports", headers=headers, params=params
        )

    def get_mileage_report(self, report_id, headers):
        return self._request(
            "GET", f"/mileage-reports/{report_id}", headers=headers
        )

    def validate_mileage_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/mileage-reports/{report_id}/validate", payload, headers
        )

    def dispute_mileage_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/mileage-reports/{report_id}/dispute", payload, headers
        )

    def resubmit_mileage_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/mileage-reports/{report_id}/resubmit", payload, headers
        )

    # --- CarHireStatement ---
    def generate_car_hire_statements(self, statement_month, headers):
        return self._request(
            "POST",
            "/car-hire-statements/generate",
            {"statement_month": statement_month},
            headers,
        )

    def list_car_hire_statements(self, headers, params=None):
        return self._request(
            "GET", "/car-hire-statements", headers=headers, params=params
        )

    def get_car_hire_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/car-hire-statements/{statement_id}", headers=headers
        )

    def finalize_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/car-hire-statements/{statement_id}/finalize", {}, headers
        )

    def dispute_statement(self, statement_id, dispute_reason, headers):
        return self._request(
            "POST",
            f"/car-hire-statements/{statement_id}/dispute",
            {"dispute_reason": dispute_reason},
            headers,
        )

    def recompute_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/car-hire-statements/{statement_id}/recompute", {}, headers
        )

    def settle_statement(self, statement_id, amount_cents, headers):
        return self._request(
            "POST",
            f"/car-hire-statements/{statement_id}/settle",
            {"amount_cents": amount_cents},
            headers,
        )

    # --- RepairAuthorization ---
    def create_repair_authorization(self, payload, headers):
        return self._request("POST", "/repair-authorizations", payload, headers)

    def list_repair_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/repair-authorizations", headers=headers, params=params
        )

    def get_repair_authorization(self, repair_id, headers):
        return self._request(
            "GET", f"/repair-authorizations/{repair_id}", headers=headers
        )

    def preauthorize_repair(self, repair_id, headers):
        return self._request(
            "POST", f"/repair-authorizations/{repair_id}/preauthorize", {}, headers
        )

    def approve_repair(self, repair_id, approved_amount_cents, headers):
        return self._request(
            "POST",
            f"/repair-authorizations/{repair_id}/approve",
            {"approved_amount_cents": approved_amount_cents},
            headers,
        )

    def request_repair_revision(self, repair_id, notes, headers):
        return self._request(
            "POST",
            f"/repair-authorizations/{repair_id}/request-revision",
            {"notes": notes},
            headers,
        )

    def revise_repair(self, repair_id, estimate_cents, headers):
        return self._request(
            "POST",
            f"/repair-authorizations/{repair_id}/revise",
            {"estimate_cents": estimate_cents},
            headers,
        )

    def reject_repair(self, repair_id, reason, headers):
        return self._request(
            "POST",
            f"/repair-authorizations/{repair_id}/reject",
            {"reason": reason},
            headers,
        )

    def start_repair_work(self, repair_id, headers):
        return self._request(
            "POST", f"/repair-authorizations/{repair_id}/start-work", {}, headers
        )

    def complete_repair(self, repair_id, final_cost_cents, headers):
        return self._request(
            "POST",
            f"/repair-authorizations/{repair_id}/complete",
            {"final_cost_cents": final_cost_cents},
            headers,
        )

    # --- CleaningRecord ---
    def create_cleaning_record(self, payload, headers):
        return self._request("POST", "/cleaning-records", payload, headers)

    def list_cleaning_records(self, headers, params=None):
        return self._request(
            "GET", "/cleaning-records", headers=headers, params=params
        )

    def get_cleaning_record(self, cleaning_id, headers):
        return self._request(
            "GET", f"/cleaning-records/{cleaning_id}", headers=headers
        )

    def complete_cleaning(self, cleaning_id, cleaning_grade_performed, cost_cents, headers):
        return self._request(
            "POST",
            f"/cleaning-records/{cleaning_id}/complete",
            {
                "cleaning_grade_performed": cleaning_grade_performed,
                "cost_cents": cost_cents,
            },
            headers,
        )

    def certify_cleaning(self, cleaning_id, certificate_ref, headers):
        return self._request(
            "POST",
            f"/cleaning-records/{cleaning_id}/certify",
            {"certificate_ref": certificate_ref},
            headers,
        )

    def fail_cleaning(self, cleaning_id, reason, headers):
        return self._request(
            "POST",
            f"/cleaning-records/{cleaning_id}/fail",
            {"reason": reason},
            headers,
        )

    # --- DamageAssessment ---
    def create_damage_assessment(self, payload, headers):
        return self._request("POST", "/damage-assessments", payload, headers)

    def list_damage_assessments(self, headers, params=None):
        return self._request(
            "GET", "/damage-assessments", headers=headers, params=params
        )

    def get_damage_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/damage-assessments/{assessment_id}", headers=headers
        )

    def submit_damage_assessment(self, assessment_id, line_items, headers):
        return self._request(
            "POST",
            f"/damage-assessments/{assessment_id}/submit",
            {"line_items": line_items},
            headers,
        )

    def dispute_damage_assessment(self, assessment_id, reason, headers):
        return self._request(
            "POST",
            f"/damage-assessments/{assessment_id}/dispute",
            {"reason": reason},
            headers,
        )

    def resubmit_damage_assessment(self, assessment_id, line_items, headers):
        return self._request(
            "POST",
            f"/damage-assessments/{assessment_id}/resubmit",
            {"line_items": line_items},
            headers,
        )

    def finalize_damage_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/damage-assessments/{assessment_id}/finalize", {}, headers
        )

    def invoice_damage_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/damage-assessments/{assessment_id}/invoice", {}, headers
        )

    def record_damage_payment(self, assessment_id, amount_cents, headers):
        return self._request(
            "POST",
            f"/damage-assessments/{assessment_id}/record-payment",
            {"amount_cents": amount_cents},
            headers,
        )

    # --- ComplianceDirective / RetrofitOrder ---
    def create_compliance_directive(self, payload, headers):
        return self._request("POST", "/compliance-directives", payload, headers)

    def list_compliance_directives(self, headers, params=None):
        return self._request(
            "GET", "/compliance-directives", headers=headers, params=params
        )

    def get_compliance_directive(self, directive_id, headers):
        return self._request(
            "GET", f"/compliance-directives/{directive_id}", headers=headers
        )

    def promote_directive(self, directive_id, headers):
        return self._request(
            "POST", f"/compliance-directives/{directive_id}/promote", {}, headers
        )

    def create_retrofit_order(self, payload, headers):
        return self._request("POST", "/retrofit-orders", payload, headers)

    def list_retrofit_orders(self, headers, params=None):
        return self._request(
            "GET", "/retrofit-orders", headers=headers, params=params
        )

    def get_retrofit_order(self, order_id, headers):
        return self._request("GET", f"/retrofit-orders/{order_id}", headers=headers)

    def defer_retrofit(self, order_id, reason, headers):
        return self._request(
            "POST", f"/retrofit-orders/{order_id}/defer", {"reason": reason}, headers
        )

    def reschedule_retrofit(self, order_id, scheduled_date, headers):
        return self._request(
            "POST",
            f"/retrofit-orders/{order_id}/reschedule",
            {"scheduled_date": scheduled_date},
            headers,
        )

    def start_retrofit(self, order_id, headers):
        return self._request(
            "POST", f"/retrofit-orders/{order_id}/start", {}, headers
        )

    def complete_retrofit(self, order_id, headers):
        return self._request(
            "POST", f"/retrofit-orders/{order_id}/complete", {}, headers
        )

    def certify_retrofit(self, order_id, certification_ref, headers):
        return self._request(
            "POST",
            f"/retrofit-orders/{order_id}/certify",
            {"certification_ref": certification_ref},
            headers,
        )

    def cancel_retrofit(self, order_id, headers):
        return self._request(
            "POST", f"/retrofit-orders/{order_id}/cancel", {}, headers
        )

    # --- RetirementCase ---
    def create_retirement_case(self, payload, headers):
        return self._request("POST", "/retirement-cases", payload, headers)

    def list_retirement_cases(self, headers, params=None):
        return self._request(
            "GET", "/retirement-cases", headers=headers, params=params
        )

    def get_retirement_case(self, case_id, headers):
        return self._request(
            "GET", f"/retirement-cases/{case_id}", headers=headers
        )

    def appraise_retirement(self, case_id, salvage_value_cents, book_value_cents, headers):
        return self._request(
            "POST",
            f"/retirement-cases/{case_id}/appraise",
            {
                "salvage_value_cents": salvage_value_cents,
                "book_value_cents": book_value_cents,
            },
            headers,
        )

    def approve_retirement(self, case_id, headers):
        return self._request(
            "POST", f"/retirement-cases/{case_id}/approve", {}, headers
        )

    def execute_retirement(self, case_id, headers):
        return self._request(
            "POST", f"/retirement-cases/{case_id}/execute", {}, headers
        )

    def cancel_retirement(self, case_id, headers):
        return self._request(
            "POST", f"/retirement-cases/{case_id}/cancel", {}, headers
        )

    # --- CapitalPool / PurchaseCommitment ---
    def create_capital_pool(self, payload, headers):
        return self._request("POST", "/capital-pools", payload, headers)

    def get_capital_pool(self, pool_id, headers):
        return self._request("GET", f"/capital-pools/{pool_id}", headers=headers)

    def create_commitment(self, pool_id, payload, headers):
        return self._request(
            "POST", f"/capital-pools/{pool_id}/commitments", payload, headers
        )

    def list_commitments(self, pool_id, headers, params=None):
        return self._request(
            "GET",
            f"/capital-pools/{pool_id}/commitments",
            headers=headers,
            params=params,
        )

    def get_commitment(self, pool_id, commitment_id, headers):
        return self._request(
            "GET",
            f"/capital-pools/{pool_id}/commitments/{commitment_id}",
            headers=headers,
        )

    def deliver_commitment(self, pool_id, commitment_id, car_mark, built_year, headers):
        return self._request(
            "POST",
            f"/capital-pools/{pool_id}/commitments/{commitment_id}/deliver",
            {"car_mark": car_mark, "built_year": built_year},
            headers,
        )

    def cancel_commitment(self, pool_id, commitment_id, headers):
        return self._request(
            "POST",
            f"/capital-pools/{pool_id}/commitments/{commitment_id}/cancel",
            {},
            headers,
        )


api_client = ApiClient()
