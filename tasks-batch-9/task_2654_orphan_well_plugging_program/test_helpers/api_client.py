"""One method per endpoint of the orphan well plugging program API."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin transport wrapper; every method returns the raw response."""

    # ------------------------------------------------------------------
    # Operators
    # ------------------------------------------------------------------
    def create_operator(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/operators", payload, headers)

    def get_operator(self, operator_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/operators/{operator_id}", None, headers)

    def list_operators(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/operators", None, headers, params)

    def operator_enforcement(
        self, operator_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/operators/{operator_id}/enforcement", payload, headers
        )

    # ------------------------------------------------------------------
    # Wells and production
    # ------------------------------------------------------------------
    def create_well(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/wells", payload, headers)

    def get_well(self, well_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/wells/{well_id}", None, headers)

    def list_wells(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/wells", None, headers, params)

    def create_production_record(
        self, well_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/wells/{well_id}/production-records", payload, headers
        )

    def list_production_records(
        self, well_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/wells/{well_id}/production-records", None, headers, params
        )

    # ------------------------------------------------------------------
    # Orphan determinations
    # ------------------------------------------------------------------
    def create_orphan_determination(
        self, well_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/wells/{well_id}/orphan-determinations", payload, headers
        )

    def get_orphan_determination(self, determination_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/orphan-determinations/{determination_id}", None, headers
        )

    def list_well_orphan_determinations(
        self, well_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/wells/{well_id}/orphan-determinations", None, headers, params
        )

    def submit_orphan_determination(
        self,
        determination_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/orphan-determinations/{determination_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def decide_orphan_determination(
        self, determination_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/orphan-determinations/{determination_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Site access
    # ------------------------------------------------------------------
    def create_site_access(
        self, well_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/wells/{well_id}/site-accesses", payload, headers)

    def get_site_access(self, site_access_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/site-accesses/{site_access_id}", None, headers)

    def list_well_site_accesses(
        self, well_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/wells/{well_id}/site-accesses", None, headers, params
        )

    def resolve_site_access(
        self, site_access_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/site-accesses/{site_access_id}/resolution", payload, headers
        )

    # ------------------------------------------------------------------
    # Transfers and enforcement
    # ------------------------------------------------------------------
    def create_well_transfer(
        self, well_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/wells/{well_id}/transfers", payload, headers)

    def get_well_transfer(self, transfer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/well-transfers/{transfer_id}", None, headers)

    def list_well_transfers(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/well-transfers", None, headers, params)

    def decide_well_transfer(
        self, transfer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/well-transfers/{transfer_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Contractors
    # ------------------------------------------------------------------
    def create_contractor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/contractors", payload, headers)

    def get_contractor(self, contractor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/contractors/{contractor_id}", None, headers)

    def list_contractors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/contractors", None, headers, params)

    def contractor_eligibility(
        self, contractor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/contractors/{contractor_id}/eligibility", payload, headers
        )

    # ------------------------------------------------------------------
    # Solicitations, bids, contracts
    # ------------------------------------------------------------------
    def create_solicitation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/solicitations", payload, headers)

    def get_solicitation(self, solicitation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/solicitations/{solicitation_id}", None, headers)

    def list_solicitations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/solicitations", None, headers, params)

    def solicitation_lifecycle(
        self, solicitation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/solicitations/{solicitation_id}/lifecycle", payload, headers
        )

    def create_bid(
        self, solicitation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/solicitations/{solicitation_id}/bids", payload, headers
        )

    def get_bid(self, bid_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/bids/{bid_id}", None, headers)

    def list_bids(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/bids", None, headers, params)

    def evaluate_bid(
        self, bid_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/bids/{bid_id}/evaluation", payload, headers)

    def award_solicitation(
        self,
        solicitation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/solicitations/{solicitation_id}/award",
            payload if payload is not None else {},
            headers,
        )

    def get_unit_cost_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/unit-cost-contracts/{contract_id}", None, headers)

    def list_unit_cost_contracts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/unit-cost-contracts", None, headers, params)

    # ------------------------------------------------------------------
    # Plugging jobs
    # ------------------------------------------------------------------
    def create_plugging_job(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/plugging-jobs", payload, headers)

    def get_plugging_job(self, job_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/plugging-jobs/{job_id}", None, headers)

    def list_plugging_jobs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/plugging-jobs", None, headers, params)

    def mobilize_plugging_job(
        self, job_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/plugging-jobs/{job_id}/mobilize",
            payload if payload is not None else {},
            headers,
        )

    def file_field_report(
        self, job_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/plugging-jobs/{job_id}/field-report", payload, headers
        )

    def review_plugging_job(
        self, job_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/plugging-jobs/{job_id}/review", payload, headers)

    # ------------------------------------------------------------------
    # Reclamation
    # ------------------------------------------------------------------
    def list_reclamation_tasks(
        self, job_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/plugging-jobs/{job_id}/reclamation-tasks", None, headers, params
        )

    def get_reclamation_task(self, task_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reclamation-tasks/{task_id}", None, headers)

    def progress_reclamation_task(
        self, task_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reclamation-tasks/{task_id}/progress", payload, headers
        )

    # ------------------------------------------------------------------
    # Funding
    # ------------------------------------------------------------------
    def create_funding_source(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/funding-sources", payload, headers)

    def get_funding_source(self, source_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/funding-sources/{source_id}", None, headers)

    def list_funding_sources(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/funding-sources", None, headers, params)

    def create_funding_commitments(
        self, job_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/plugging-jobs/{job_id}/funding-commitments",
            payload if payload is not None else {},
            headers,
        )

    def get_funding_allocation(self, allocation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/funding-allocations/{allocation_id}", None, headers
        )

    def list_funding_allocations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/funding-allocations", None, headers, params)

    def transition_funding_allocation(
        self, allocation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/funding-allocations/{allocation_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Grant reporting
    # ------------------------------------------------------------------
    def create_grant_report(
        self, source_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/funding-sources/{source_id}/grant-reports", payload, headers
        )

    def list_grant_reports(
        self, source_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/funding-sources/{source_id}/grant-reports", None, headers, params
        )

    def get_grant_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/grant-reports/{report_id}", None, headers)

    def submit_grant_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/grant-reports/{report_id}/submission", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )
