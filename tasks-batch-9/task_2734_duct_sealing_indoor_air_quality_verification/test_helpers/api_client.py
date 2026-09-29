"""One method per endpoint of PRD section 4.

Every path is rooted at the `/duct-sealing` prefix. Methods return the raw
`requests.Response` so that tests can assert on status codes as well as bodies.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _params(**kwargs: Any) -> Optional[Dict[str, Any]]:
    """Drop unsupplied query parameters so defaults stay server-side."""
    out = {k: v for k, v in kwargs.items() if v is not None}
    return out or None


class DuctSealingApiClient(GenericApiClient):
    """Endpoint surface of the duct-sealing IAQ service."""

    # -- logical clock -----------------------------------------------------
    def set_clock(self, to_iso8601: str, headers=None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def set_clock_raw(self, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # -- utility programs --------------------------------------------------
    def create_utility_program(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/utility-programs", payload, headers)

    def get_utility_program(self, program_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/utility-programs/{program_id}", None, headers
        )

    # -- technicians -------------------------------------------------------
    def create_technician(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/technicians", payload, headers)

    def get_technician(self, technician_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/technicians/{technician_id}", None, headers
        )

    def record_certification(
        self, technician_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/technicians/{technician_id}/certification",
            payload,
            headers,
        )

    # -- projects ----------------------------------------------------------
    def create_project(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/projects", payload, headers)

    def get_project(self, project_id, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/projects/{project_id}", None, headers)

    def list_projects(
        self,
        headers=None,
        utility_program_id=None,
        status=None,
        limit=None,
        offset=None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/projects",
            _params(
                utility_program_id=utility_program_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def raise_safety_hold(self, project_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/projects/{project_id}/safety-hold", payload, headers
        )

    def release_safety_hold(
        self, project_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/projects/{project_id}/release-safety-hold",
            payload,
            headers,
        )

    # -- duct systems ------------------------------------------------------
    def create_duct_system(self, project_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/projects/{project_id}/duct-systems", payload, headers
        )

    def list_duct_systems(
        self,
        project_id,
        headers=None,
        eligibility_status=None,
        seal_status=None,
        limit=None,
        offset=None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/projects/{project_id}/duct-systems",
            _params(
                eligibility_status=eligibility_status,
                seal_status=seal_status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_duct_system(self, duct_system_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/duct-systems/{duct_system_id}", None, headers
        )

    def record_asbestos_screening(
        self, duct_system_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/duct-systems/{duct_system_id}/asbestos-screening",
            payload,
            headers,
        )

    def exclude_duct_system(
        self, duct_system_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/duct-systems/{duct_system_id}/exclude",
            payload,
            headers,
        )

    # -- leakage tests -----------------------------------------------------
    def create_leakage_test(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/leakage-tests", payload, headers)

    def get_leakage_test(self, leakage_test_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/leakage-tests/{leakage_test_id}", None, headers
        )

    def list_leakage_tests(
        self,
        duct_system_id,
        headers=None,
        phase=None,
        status=None,
        limit=None,
        offset=None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/duct-systems/{duct_system_id}/leakage-tests",
            _params(phase=phase, status=status, limit=limit, offset=offset),
            headers,
        )

    def pressurize_leakage_test(
        self, leakage_test_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/leakage-tests/{leakage_test_id}/pressurize",
            payload,
            headers,
        )

    def record_leakage_test(
        self, leakage_test_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/leakage-tests/{leakage_test_id}/record",
            payload,
            headers,
        )

    def review_leakage_test(
        self, leakage_test_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/leakage-tests/{leakage_test_id}/review",
            payload,
            headers,
        )

    # -- combustion tests --------------------------------------------------
    def create_combustion_test(
        self, project_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/projects/{project_id}/combustion-tests",
            payload,
            headers,
        )

    def list_combustion_tests(
        self,
        project_id,
        headers=None,
        phase=None,
        verdict=None,
        limit=None,
        offset=None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/projects/{project_id}/combustion-tests",
            _params(phase=phase, verdict=verdict, limit=limit, offset=offset),
            headers,
        )

    # -- seal jobs ---------------------------------------------------------
    def create_seal_job(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/seal-jobs", payload, headers)

    def get_seal_job(self, seal_job_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/seal-jobs/{seal_job_id}", None, headers
        )

    def list_seal_jobs(
        self,
        headers=None,
        duct_system_id=None,
        pre_test_id=None,
        technician_id=None,
        retest_of_job_id=None,
        status=None,
        limit=None,
        offset=None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/seal-jobs",
            _params(
                duct_system_id=duct_system_id,
                pre_test_id=pre_test_id,
                technician_id=technician_id,
                retest_of_job_id=retest_of_job_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def mask_registers(self, seal_job_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/seal-jobs/{seal_job_id}/masks", payload, headers
        )

    def start_injection(self, seal_job_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/seal-jobs/{seal_job_id}/start-injection",
            payload if payload is not None else {},
            headers,
        )

    def append_leakage_sample(
        self, seal_job_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/seal-jobs/{seal_job_id}/leakage-samples",
            payload,
            headers,
        )

    def list_leakage_samples(
        self, seal_job_id, headers=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/seal-jobs/{seal_job_id}/leakage-samples",
            _params(limit=limit, offset=offset),
            headers,
        )

    def pause_seal_job(self, seal_job_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/seal-jobs/{seal_job_id}/pause", payload, headers
        )

    def resume_seal_job(self, seal_job_id, payload=None, headers=None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/seal-jobs/{seal_job_id}/resume",
            payload if payload is not None else {},
            headers,
        )

    def complete_seal(self, seal_job_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/seal-jobs/{seal_job_id}/complete-seal",
            payload,
            headers,
        )

    def abort_seal_job(self, seal_job_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/seal-jobs/{seal_job_id}/abort", payload, headers
        )

    def register_warranty(self, seal_job_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/seal-jobs/{seal_job_id}/warranty-registration",
            payload,
            headers,
        )

    # -- verification reports ----------------------------------------------
    def create_verification_report(self, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/verification-reports", payload, headers
        )

    def get_verification_report(self, report_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/verification-reports/{report_id}", None, headers
        )

    def list_verification_reports(
        self,
        headers=None,
        seal_job_id=None,
        post_test_id=None,
        status=None,
        limit=None,
        offset=None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/verification-reports",
            _params(
                seal_job_id=seal_job_id,
                post_test_id=post_test_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def issue_verification_report(
        self, report_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/verification-reports/{report_id}/issue",
            payload,
            headers,
        )

    # -- rebate claims -----------------------------------------------------
    def create_rebate_claim(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/rebate-claims", payload, headers)

    def get_rebate_claim(self, claim_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/rebate-claims/{claim_id}", None, headers
        )

    def list_rebate_claims(
        self,
        headers=None,
        verification_report_id=None,
        utility_program_id=None,
        status=None,
        limit=None,
        offset=None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/rebate-claims",
            _params(
                verification_report_id=verification_report_id,
                utility_program_id=utility_program_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def record_inspector_verification(
        self, claim_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/rebate-claims/{claim_id}/inspector-verification",
            payload,
            headers,
        )

    def resubmit_rebate_claim(self, claim_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/rebate-claims/{claim_id}/resubmit", payload, headers
        )

    def pay_rebate_claim(self, claim_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/rebate-claims/{claim_id}/pay", payload, headers
        )

    # -- comfort complaints ------------------------------------------------
    def create_comfort_complaint(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/comfort-complaints", payload, headers)

    def get_comfort_complaint(self, complaint_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/comfort-complaints/{complaint_id}", None, headers
        )

    def list_comfort_complaints(
        self, project_id, headers=None, status=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/projects/{project_id}/comfort-complaints",
            _params(status=status, limit=limit, offset=offset),
            headers,
        )

    def diagnose_comfort_complaint(
        self, complaint_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/comfort-complaints/{complaint_id}/diagnose",
            payload,
            headers,
        )

    def balance_comfort_complaint(
        self, complaint_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/comfort-complaints/{complaint_id}/balance",
            payload,
            headers,
        )

    def create_airflow_reading(
        self, complaint_id, payload, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/comfort-complaints/{complaint_id}/airflow-readings",
            payload,
            headers,
        )

    def list_airflow_readings(
        self, complaint_id, headers=None, room_label=None, limit=None, offset=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/comfort-complaints/{complaint_id}/airflow-readings",
            _params(room_label=room_label, limit=limit, offset=offset),
            headers,
        )
