"""One client method per documented endpoint of the FSVP API."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fsvp"


class ApiClient(GenericApiClient):
    """Thin typed wrapper: one method per endpoint, no business logic."""

    # ------------------------------------------------------------------ clock
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --------------------------------------------------------------- Importer
    def create_importer(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/importers", payload, headers)

    def get_importer(self, importer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/importers/{importer_id}", None, headers)

    def get_records_package(
        self,
        importer_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/importers/{importer_id}/records-package", params, headers
        )

    # ------------------------------------------------------- QualifiedIndividual
    def create_qualified_individual(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/qualified-individuals", payload, headers)

    def list_importer_qualified_individuals(
        self,
        importer_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/importers/{importer_id}/qualified-individuals",
            params,
            headers,
        )

    def post_designation(
        self, qi_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/qualified-individuals/{qi_id}/designation", payload, headers
        )

    # --------------------------------------------------------- ForeignSupplier
    def create_foreign_supplier(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/foreign-suppliers", payload, headers)

    def get_foreign_supplier(
        self, supplier_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/foreign-suppliers/{supplier_id}", None, headers
        )

    def list_importer_foreign_suppliers(
        self,
        importer_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/importers/{importer_id}/foreign-suppliers", params, headers
        )

    def patch_supplier_compliance_status(
        self, supplier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{PREFIX}/foreign-suppliers/{supplier_id}/compliance-status",
            payload,
            headers,
        )

    def post_supplier_evaluation(
        self, supplier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/foreign-suppliers/{supplier_id}/evaluation", payload, headers
        )

    # ------------------------------------------------------------------- Food
    def create_food(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/foods", payload, headers)

    def list_importer_foods(
        self,
        importer_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/importers/{importer_id}/foods", params, headers
        )

    # ------------------------------------------------------- SupplierFoodPair
    def create_supplier_food_pair(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/supplier-food-pairs", payload, headers)

    def get_supplier_food_pair(
        self, pair_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/supplier-food-pairs/{pair_id}", None, headers
        )

    def list_supplier_food_pairs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/supplier-food-pairs", params, headers)

    def post_pair_verification_approval(
        self, pair_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/supplier-food-pairs/{pair_id}/verification-approval",
            payload,
            headers,
        )

    def post_pair_reassessment(
        self, pair_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/supplier-food-pairs/{pair_id}/reassessment", payload, headers
        )

    def post_pair_exemption(
        self, pair_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/supplier-food-pairs/{pair_id}/exemption", payload, headers
        )

    # ------------------------------------------------- HazardAnalysis / Hazard
    def create_hazard_analysis(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/hazard-analyses", payload, headers)

    def get_hazard_analysis(
        self, analysis_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/hazard-analyses/{analysis_id}", None, headers
        )

    def list_hazard_analyses(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/hazard-analyses", params, headers)

    def create_hazard(
        self, analysis_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/hazard-analyses/{analysis_id}/hazards", payload, headers
        )

    def list_hazards(
        self,
        analysis_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/hazard-analyses/{analysis_id}/hazards", params, headers
        )

    def post_hazard_analysis_approval(
        self, analysis_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/hazard-analyses/{analysis_id}/approval", payload, headers
        )

    # --------------------------------------------------- VerificationActivity
    def create_verification_activity(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/verification-activities", payload, headers)

    def get_verification_activity(
        self, activity_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/verification-activities/{activity_id}", None, headers
        )

    def list_verification_activities(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/verification-activities", params, headers)

    def patch_verification_activity(
        self, activity_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{PREFIX}/verification-activities/{activity_id}", payload, headers
        )

    def post_activity_review(
        self, activity_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/verification-activities/{activity_id}/review",
            payload,
            headers,
        )

    # ----------------------------------------------------- VerificationRecord
    def create_verification_record(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/verification-records", payload, headers)

    def get_verification_record(
        self,
        record_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/verification-records/{record_id}", params, headers
        )

    def list_verification_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/verification-records", params, headers)

    def post_record_attestation(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/verification-records/{record_id}/attestation", payload, headers
        )

    def post_record_rescission(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/verification-records/{record_id}/rescission", payload, headers
        )

    # -------------------------------------------------------- CorrectiveAction
    def get_corrective_action(
        self, action_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/corrective-actions/{action_id}", None, headers
        )

    def list_corrective_actions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/corrective-actions", params, headers)

    def post_corrective_action_decision(
        self, action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/corrective-actions/{action_id}/decision", payload, headers
        )

    def post_corrective_action_closure(
        self, action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/corrective-actions/{action_id}/closure", payload, headers
        )

    # --------------------------------------------------------- EntrySubmission
    def create_entry_submission(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/entry-submissions", payload, headers)

    def get_entry_submission(
        self, entry_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/entry-submissions/{entry_id}", None, headers)

    def list_entry_submissions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/entry-submissions", params, headers)
