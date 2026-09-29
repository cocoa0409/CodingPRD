"""One method per declared endpoint of the Corporate Archives & Heritage API.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as bodies. Query filters are passed through ``params``.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP surface of the API under test."""

    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ─── RetentionSchedule ────────────────────────────────────────────────
    def create_retention_schedule(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/retention-schedules", payload, headers)

    def list_retention_schedules(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/retention-schedules", None, headers, params)

    def get_retention_schedule(self, schedule_id: str, headers):
        return self._request("GET", f"/retention-schedules/{schedule_id}", None, headers)

    # ─── RecordSeries ─────────────────────────────────────────────────────
    def create_record_series(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/record-series", payload, headers)

    def list_record_series(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/record-series", None, headers, params)

    def get_record_series(self, series_id: str, headers):
        return self._request("GET", f"/record-series/{series_id}", None, headers)

    def dispose_record_series(self, series_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/record-series/{series_id}/dispose", payload, headers
        )

    # ─── LegalHold ────────────────────────────────────────────────────────
    def create_legal_hold(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/legal-holds", payload, headers)

    def list_legal_holds(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/legal-holds", None, headers, params)

    def get_legal_hold(self, hold_id: str, headers):
        return self._request("GET", f"/legal-holds/{hold_id}", None, headers)

    def activate_legal_hold(self, hold_id: str, headers, payload=None):
        return self._request(
            "POST", f"/legal-holds/{hold_id}/activate", payload or {}, headers
        )

    def release_legal_hold(self, hold_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/legal-holds/{hold_id}/release", payload, headers
        )

    # ─── AppraisalRecord ──────────────────────────────────────────────────
    def create_appraisal(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/appraisals", payload, headers)

    def list_appraisals(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/appraisals", None, headers, params)

    def get_appraisal(self, appraisal_id: str, headers):
        return self._request("GET", f"/appraisals/{appraisal_id}", None, headers)

    def screen_appraisal(self, appraisal_id: str, headers, payload=None):
        return self._request(
            "POST", f"/appraisals/{appraisal_id}/screen", payload or {}, headers
        )

    def finalize_appraisal(self, appraisal_id: str, headers, payload=None):
        return self._request(
            "POST", f"/appraisals/{appraisal_id}/finalize", payload or {}, headers
        )

    # ─── Accession ────────────────────────────────────────────────────────
    def create_accession(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/accessions", payload, headers)

    def list_accessions(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/accessions", None, headers, params)

    def get_accession(self, accession_id: str, headers):
        return self._request("GET", f"/accessions/{accession_id}", None, headers)

    def verify_accession_provenance(
        self, accession_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST", f"/accessions/{accession_id}/verify-provenance", payload, headers
        )

    def process_accession(self, accession_id: str, headers, payload=None):
        return self._request(
            "POST", f"/accessions/{accession_id}/process", payload or {}, headers
        )

    def reject_accession(self, accession_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/accessions/{accession_id}/reject", payload, headers
        )

    # ─── ArchivalItem ─────────────────────────────────────────────────────
    def create_archival_item(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/archival-items", payload, headers)

    def list_archival_items(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/archival-items", None, headers, params)

    def get_archival_item(self, item_id: str, headers):
        return self._request("GET", f"/archival-items/{item_id}", None, headers)

    # ─── StorageZone ──────────────────────────────────────────────────────
    def create_storage_zone(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/storage-zones", payload, headers)

    def list_storage_zones(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/storage-zones", None, headers, params)

    def get_storage_zone(self, zone_id: str, headers):
        return self._request("GET", f"/storage-zones/{zone_id}", None, headers)

    def record_environment_reading(
        self, zone_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST", f"/storage-zones/{zone_id}/environment-readings", payload, headers
        )

    # ─── FindingAid ───────────────────────────────────────────────────────
    def create_finding_aid(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/finding-aids", payload, headers)

    def list_finding_aids(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/finding-aids", None, headers, params)

    def get_finding_aid(self, aid_id: str, headers):
        return self._request("GET", f"/finding-aids/{aid_id}", None, headers)

    def submit_finding_aid_review(self, aid_id: str, headers, payload=None):
        return self._request(
            "POST", f"/finding-aids/{aid_id}/submit-review", payload or {}, headers
        )

    def publish_finding_aid(self, aid_id: str, headers, payload=None):
        return self._request(
            "POST", f"/finding-aids/{aid_id}/publish", payload or {}, headers
        )

    # ─── PreservationPlan ─────────────────────────────────────────────────
    def create_preservation_plan(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/preservation-plans", payload, headers)

    def list_preservation_plans(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/preservation-plans", None, headers, params)

    def get_preservation_plan(self, plan_id: str, headers):
        return self._request("GET", f"/preservation-plans/{plan_id}", None, headers)

    def activate_preservation_plan(self, plan_id: str, headers, payload=None):
        return self._request(
            "POST", f"/preservation-plans/{plan_id}/activate", payload or {}, headers
        )

    def close_preservation_plan(self, plan_id: str, headers, payload=None):
        return self._request(
            "POST", f"/preservation-plans/{plan_id}/close", payload or {}, headers
        )

    # ─── MigrationJob ─────────────────────────────────────────────────────
    def create_migration_job(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/migration-jobs", payload, headers)

    def list_migration_jobs(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/migration-jobs", None, headers, params)

    def get_migration_job(self, job_id: str, headers):
        return self._request("GET", f"/migration-jobs/{job_id}", None, headers)

    def approve_migration_job(self, job_id: str, headers, payload=None):
        return self._request(
            "POST", f"/migration-jobs/{job_id}/approve", payload or {}, headers
        )

    def start_migration_job(self, job_id: str, headers, payload=None):
        return self._request(
            "POST", f"/migration-jobs/{job_id}/start", payload or {}, headers
        )

    def complete_migration_job(self, job_id: str, headers, payload=None):
        return self._request(
            "POST", f"/migration-jobs/{job_id}/complete", payload or {}, headers
        )

    def cancel_migration_job(self, job_id: str, headers, payload=None):
        return self._request(
            "POST", f"/migration-jobs/{job_id}/cancel", payload or {}, headers
        )

    # ─── Requester ────────────────────────────────────────────────────────
    def create_requester(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/requesters", payload, headers)

    def list_requesters(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/requesters", None, headers, params)

    def get_requester(self, requester_id: str, headers):
        return self._request("GET", f"/requesters/{requester_id}", None, headers)

    def suspend_requester(self, requester_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/requesters/{requester_id}/suspend", payload, headers
        )

    # ─── AccessRequest ────────────────────────────────────────────────────
    def create_access_request(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/access-requests", payload, headers)

    def list_access_requests(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/access-requests", None, headers, params)

    def get_access_request(self, request_id: str, headers):
        return self._request("GET", f"/access-requests/{request_id}", None, headers)

    def begin_screening(self, request_id: str, headers, payload=None):
        return self._request(
            "POST", f"/access-requests/{request_id}/begin-screening",
            payload or {}, headers,
        )

    def revise_access_request(self, request_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/access-requests/{request_id}/revise", payload, headers
        )

    def approve_access_request(self, request_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/access-requests/{request_id}/approve", payload, headers
        )

    def deny_access_request(self, request_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/access-requests/{request_id}/deny", payload, headers
        )

    def close_access_request(self, request_id: str, headers, payload=None):
        return self._request(
            "POST", f"/access-requests/{request_id}/close", payload or {}, headers
        )

    # ─── ConfidentialityScreening ─────────────────────────────────────────
    def create_screening(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/confidentiality-screenings", payload, headers)

    def list_screenings(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/confidentiality-screenings", None, headers, params
        )

    def get_screening(self, screening_id: str, headers):
        return self._request(
            "GET", f"/confidentiality-screenings/{screening_id}", None, headers
        )

    def complete_screening(self, screening_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/confidentiality-screenings/{screening_id}/complete",
            payload, headers,
        )

    # ─── OralHistoryInterview ─────────────────────────────────────────────
    def create_interview(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/oral-history-interviews", payload, headers)

    def list_interviews(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/oral-history-interviews", None, headers, params)

    def get_interview(self, interview_id: str, headers):
        return self._request(
            "GET", f"/oral-history-interviews/{interview_id}", None, headers
        )

    def interview_consent(self, interview_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/oral-history-interviews/{interview_id}/consent", payload, headers
        )

    def interview_transcription(
        self, interview_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST", f"/oral-history-interviews/{interview_id}/transcription",
            payload, headers,
        )

    # ─── TrademarkEvidencePackage ─────────────────────────────────────────
    def create_evidence_package(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/trademark-evidence-packages", payload, headers)

    def list_evidence_packages(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/trademark-evidence-packages", None, headers, params
        )

    def get_evidence_package(self, package_id: str, headers):
        return self._request(
            "GET", f"/trademark-evidence-packages/{package_id}", None, headers
        )

    def certify_evidence_package(self, package_id: str, headers, payload=None):
        return self._request(
            "POST", f"/trademark-evidence-packages/{package_id}/certify",
            payload or {}, headers,
        )

    # ─── ExhibitLoan ──────────────────────────────────────────────────────
    def create_exhibit_loan(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/exhibit-loans", payload, headers)

    def list_exhibit_loans(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/exhibit-loans", None, headers, params)

    def get_exhibit_loan(self, loan_id: str, headers):
        return self._request("GET", f"/exhibit-loans/{loan_id}", None, headers)

    def confirm_exhibit_loan(self, loan_id: str, headers, payload=None):
        return self._request(
            "POST", f"/exhibit-loans/{loan_id}/confirm", payload or {}, headers
        )

    def check_out_exhibit_loan(self, loan_id: str, headers, payload=None):
        return self._request(
            "POST", f"/exhibit-loans/{loan_id}/check-out", payload or {}, headers
        )

    def return_exhibit_loan(self, loan_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/exhibit-loans/{loan_id}/return", payload, headers
        )

    def cancel_exhibit_loan(self, loan_id: str, headers, payload=None):
        return self._request(
            "POST", f"/exhibit-loans/{loan_id}/cancel", payload or {}, headers
        )

    # ─── DeaccessionProposal ──────────────────────────────────────────────
    def create_deaccession_proposal(self, payload: Dict[str, Any], headers):
        return self._request("POST", "/deaccession-proposals", payload, headers)

    def list_deaccession_proposals(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/deaccession-proposals", None, headers, params)

    def get_deaccession_proposal(self, proposal_id: str, headers):
        return self._request(
            "GET", f"/deaccession-proposals/{proposal_id}", None, headers
        )

    def legal_clearance(self, proposal_id: str, headers, payload=None):
        return self._request(
            "POST", f"/deaccession-proposals/{proposal_id}/legal-clearance",
            payload or {}, headers,
        )

    def heritage_clearance(self, proposal_id: str, headers, payload=None):
        return self._request(
            "POST", f"/deaccession-proposals/{proposal_id}/heritage-clearance",
            payload or {}, headers,
        )

    def approve_deaccession_proposal(self, proposal_id: str, headers, payload=None):
        return self._request(
            "POST", f"/deaccession-proposals/{proposal_id}/approve",
            payload or {}, headers,
        )

    def execute_deaccession_proposal(
        self, proposal_id: str, payload: Dict[str, Any], headers
    ):
        return self._request(
            "POST", f"/deaccession-proposals/{proposal_id}/execute", payload, headers
        )

    def reject_deaccession_proposal(self, proposal_id: str, headers, payload=None):
        return self._request(
            "POST", f"/deaccession-proposals/{proposal_id}/reject",
            payload or {}, headers,
        )

    # ─── Generic single-row read by collection path ───────────────────────
    def get_by_collection(self, collection_path: str, row_id: str, headers):
        """Read one row of any collection; used for the NOT_FOUND sweep."""
        return self._request("GET", f"{collection_path}/{row_id}", None, headers)
