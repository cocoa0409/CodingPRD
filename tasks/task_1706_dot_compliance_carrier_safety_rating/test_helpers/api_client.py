"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Carrier ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/safety/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/safety/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/safety/carriers/{carrier_id}", headers=headers)

    def patch_carrier(self, carrier_id, payload, headers):
        return self._request("PATCH", f"/safety/carriers/{carrier_id}", payload, headers)

    def get_audit_readiness(self, carrier_id, headers):
        return self._request(
            "GET", f"/safety/carriers/{carrier_id}/audit-readiness", headers=headers
        )

    # --- Driver ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/safety/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/safety/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/safety/drivers/{driver_id}", headers=headers)

    def terminate_driver(self, driver_id, headers):
        return self._request(
            "POST", f"/safety/drivers/{driver_id}/terminate", {}, headers
        )

    def reinstate_driver(self, driver_id, headers):
        return self._request(
            "POST", f"/safety/drivers/{driver_id}/reinstate", {}, headers
        )

    # --- ViolationCategory ---
    def create_category(self, payload, headers):
        return self._request("POST", "/safety/violation-categories", payload, headers)

    def list_categories(self, headers, params=None):
        return self._request(
            "GET", "/safety/violation-categories", headers=headers, params=params
        )

    def get_category(self, category_id, headers):
        return self._request(
            "GET", f"/safety/violation-categories/{category_id}", headers=headers
        )

    # --- RoadsideInspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/safety/roadside-inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request(
            "GET", "/safety/roadside-inspections", headers=headers, params=params
        )

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/safety/roadside-inspections/{inspection_id}", headers=headers
        )

    def begin_review_inspection(self, inspection_id, headers):
        return self._request(
            "POST",
            f"/safety/roadside-inspections/{inspection_id}/begin-review",
            {},
            headers,
        )

    def finalize_inspection(self, inspection_id, headers):
        return self._request(
            "POST",
            f"/safety/roadside-inspections/{inspection_id}/finalize",
            {},
            headers,
        )

    # --- InspectionViolation ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/safety/inspection-violations", payload, headers)

    def list_violations(self, headers, params=None):
        return self._request(
            "GET", "/safety/inspection-violations", headers=headers, params=params
        )

    def get_violation(self, violation_id, headers):
        return self._request(
            "GET", f"/safety/inspection-violations/{violation_id}", headers=headers
        )

    # --- DataQsChallenge ---
    def create_challenge(self, payload, headers):
        return self._request("POST", "/safety/dataqs-challenges", payload, headers)

    def list_challenges(self, headers, params=None):
        return self._request(
            "GET", "/safety/dataqs-challenges", headers=headers, params=params
        )

    def get_challenge(self, challenge_id, headers):
        return self._request(
            "GET", f"/safety/dataqs-challenges/{challenge_id}", headers=headers
        )

    def start_review_challenge(self, challenge_id, headers):
        return self._request(
            "POST",
            f"/safety/dataqs-challenges/{challenge_id}/start-review",
            {},
            headers,
        )

    def decide_challenge(self, challenge_id, payload, headers):
        return self._request(
            "POST", f"/safety/dataqs-challenges/{challenge_id}/decide", payload, headers
        )

    def resubmit_challenge(self, challenge_id, payload, headers):
        return self._request(
            "POST",
            f"/safety/dataqs-challenges/{challenge_id}/resubmit",
            payload,
            headers,
        )

    # --- CoachingAssignment ---
    def create_coaching(self, payload, headers):
        return self._request("POST", "/safety/coaching-assignments", payload, headers)

    def list_coaching(self, headers, params=None):
        return self._request(
            "GET", "/safety/coaching-assignments", headers=headers, params=params
        )

    def get_coaching(self, coaching_id, headers):
        return self._request(
            "GET", f"/safety/coaching-assignments/{coaching_id}", headers=headers
        )

    def start_coaching(self, coaching_id, headers):
        return self._request(
            "POST", f"/safety/coaching-assignments/{coaching_id}/start", {}, headers
        )

    def complete_coaching(self, coaching_id, payload, headers):
        return self._request(
            "POST",
            f"/safety/coaching-assignments/{coaching_id}/complete",
            payload,
            headers,
        )

    def escalate_coaching(self, coaching_id, headers):
        return self._request(
            "POST",
            f"/safety/coaching-assignments/{coaching_id}/escalate",
            {},
            headers,
        )

    # --- DrugAlcoholTest ---
    def create_test(self, payload, headers):
        return self._request("POST", "/safety/drug-alcohol-tests", payload, headers)

    def list_tests(self, headers, params=None):
        return self._request(
            "GET", "/safety/drug-alcohol-tests", headers=headers, params=params
        )

    def get_test(self, test_id, headers):
        return self._request(
            "GET", f"/safety/drug-alcohol-tests/{test_id}", headers=headers
        )

    def report_lab_result(self, test_id, payload, headers):
        return self._request(
            "POST",
            f"/safety/drug-alcohol-tests/{test_id}/report-lab-result",
            payload,
            headers,
        )

    def verify_test(self, test_id, payload, headers):
        return self._request(
            "POST", f"/safety/drug-alcohol-tests/{test_id}/verify", payload, headers
        )

    # --- AccidentRecord ---
    def create_accident(self, payload, headers):
        return self._request("POST", "/safety/accident-records", payload, headers)

    def list_accidents(self, headers, params=None):
        return self._request(
            "GET", "/safety/accident-records", headers=headers, params=params
        )

    def get_accident(self, accident_id, headers):
        return self._request(
            "GET", f"/safety/accident-records/{accident_id}", headers=headers
        )

    def determine_preventability(self, accident_id, payload, headers):
        return self._request(
            "POST",
            f"/safety/accident-records/{accident_id}/determine-preventability",
            payload,
            headers,
        )

    # --- ComplianceAuditCase ---
    def create_audit_case(self, payload, headers):
        return self._request("POST", "/safety/compliance-audit-cases", payload, headers)

    def list_audit_cases(self, headers, params=None):
        return self._request(
            "GET", "/safety/compliance-audit-cases", headers=headers, params=params
        )

    def get_audit_case(self, case_id, headers):
        return self._request(
            "GET", f"/safety/compliance-audit-cases/{case_id}", headers=headers
        )

    def start_field_work(self, case_id, headers):
        return self._request(
            "POST",
            f"/safety/compliance-audit-cases/{case_id}/start-field-work",
            {},
            headers,
        )

    def issue_findings(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/safety/compliance-audit-cases/{case_id}/issue-findings",
            payload,
            headers,
        )

    def begin_corrective_action(self, case_id, headers):
        return self._request(
            "POST",
            f"/safety/compliance-audit-cases/{case_id}/begin-corrective-action",
            {},
            headers,
        )

    def close_audit_case(self, case_id, headers):
        return self._request(
            "POST", f"/safety/compliance-audit-cases/{case_id}/close", {}, headers
        )

    # --- RatingUpgradeRequest ---
    def create_upgrade_request(self, payload, headers):
        return self._request("POST", "/safety/rating-upgrade-requests", payload, headers)

    def list_upgrade_requests(self, headers, params=None):
        return self._request(
            "GET", "/safety/rating-upgrade-requests", headers=headers, params=params
        )

    def get_upgrade_request(self, request_id, headers):
        return self._request(
            "GET", f"/safety/rating-upgrade-requests/{request_id}", headers=headers
        )

    def start_review_upgrade(self, request_id, headers):
        return self._request(
            "POST",
            f"/safety/rating-upgrade-requests/{request_id}/start-review",
            {},
            headers,
        )

    def decide_upgrade(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/safety/rating-upgrade-requests/{request_id}/decide",
            payload,
            headers,
        )

    # --- InsurancePremiumModel ---
    def create_premium_model(self, payload, headers):
        return self._request(
            "POST", "/safety/insurance-premium-models", payload, headers
        )

    def list_premium_models(self, headers, params=None):
        return self._request(
            "GET", "/safety/insurance-premium-models", headers=headers, params=params
        )

    def get_premium_model(self, model_id, headers):
        return self._request(
            "GET", f"/safety/insurance-premium-models/{model_id}", headers=headers
        )

    def quote_premium_model(self, model_id, headers):
        return self._request(
            "POST", f"/safety/insurance-premium-models/{model_id}/quote", {}, headers
        )

    def recompute_premium_model(self, model_id, headers):
        return self._request(
            "POST",
            f"/safety/insurance-premium-models/{model_id}/recompute",
            {},
            headers,
        )

    def bind_premium_model(self, model_id, headers):
        return self._request(
            "POST", f"/safety/insurance-premium-models/{model_id}/bind", {}, headers
        )

    # --- DocumentRecord ---
    def create_document(self, payload, headers):
        return self._request("POST", "/safety/document-records", payload, headers)

    def list_documents(self, headers, params=None):
        return self._request(
            "GET", "/safety/document-records", headers=headers, params=params
        )

    def get_document(self, document_id, headers):
        return self._request(
            "GET", f"/safety/document-records/{document_id}", headers=headers
        )

    def purge_document(self, document_id, headers):
        return self._request(
            "POST", f"/safety/document-records/{document_id}/purge", {}, headers
        )

    # --- RandomTestingPeriod ---
    def create_period(self, payload, headers):
        return self._request("POST", "/safety/random-testing-periods", payload, headers)

    def list_periods(self, headers, params=None):
        return self._request(
            "GET", "/safety/random-testing-periods", headers=headers, params=params
        )

    def get_period(self, period_id, headers):
        return self._request(
            "GET", f"/safety/random-testing-periods/{period_id}", headers=headers
        )

    def close_period(self, period_id, headers):
        return self._request(
            "POST", f"/safety/random-testing-periods/{period_id}/close", {}, headers
        )

    # --- Measurement cycle + snapshots ---
    def run_measurement_cycle(self, payload, headers):
        return self._request("POST", "/safety/measurement-cycles", payload, headers)

    def list_snapshots(self, headers, params=None):
        return self._request(
            "GET", "/safety/measurement-snapshots", headers=headers, params=params
        )

    def get_snapshot(self, snapshot_id, headers):
        return self._request(
            "GET", f"/safety/measurement-snapshots/{snapshot_id}", headers=headers
        )

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
