"""API client: one method per endpoint defined in the PRD.

Every LTL endpoint is mounted under ``/ltl``; the logical-clock control endpoint
sits at the root under ``/_clock``.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the LTL Freight Classification API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Terminals
    # ------------------------------------------------------------------
    def create_terminal(self, payload, headers):
        return self._request("POST", "/ltl/terminals", payload, headers)

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"/ltl/terminals/{terminal_id}", headers=headers)

    # ------------------------------------------------------------------
    # Shipper accounts
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/ltl/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/ltl/customers/{customer_id}", headers=headers)

    def change_customer_posture(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/ltl/customers/{customer_id}/posture", payload, headers
        )

    def complete_customer_education(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/ltl/customers/{customer_id}/education/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Classification standard releases
    # ------------------------------------------------------------------
    def create_tariff_version(self, payload, headers):
        return self._request("POST", "/ltl/tariff-versions", payload, headers)

    def get_tariff_version(self, tariff_version_id, headers):
        return self._request(
            "GET", f"/ltl/tariff-versions/{tariff_version_id}", headers=headers
        )

    def list_tariff_versions(self, headers, params=None):
        return self._request("GET", "/ltl/tariff-versions", headers=headers, params=params)

    def publish_tariff_version(self, tariff_version_id, payload, headers):
        return self._request(
            "POST", f"/ltl/tariff-versions/{tariff_version_id}/publish", payload, headers
        )

    # ------------------------------------------------------------------
    # Commodity profiles
    # ------------------------------------------------------------------
    def create_commodity_profile(self, payload, headers):
        return self._request("POST", "/ltl/commodity-profiles", payload, headers)

    def get_commodity_profile(self, commodity_profile_id, headers):
        return self._request(
            "GET", f"/ltl/commodity-profiles/{commodity_profile_id}", headers=headers
        )

    def list_commodity_profiles(self, headers, params=None):
        return self._request(
            "GET", "/ltl/commodity-profiles", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Pricing programs
    # ------------------------------------------------------------------
    def create_rate_program(self, payload, headers):
        return self._request("POST", "/ltl/rate-programs", payload, headers)

    def get_rate_program(self, rate_program_id, headers):
        return self._request(
            "GET", f"/ltl/rate-programs/{rate_program_id}", headers=headers
        )

    def list_rate_programs(self, headers, params=None):
        return self._request("GET", "/ltl/rate-programs", headers=headers, params=params)

    def approve_rate_program(self, rate_program_id, payload, headers):
        return self._request(
            "POST", f"/ltl/rate-programs/{rate_program_id}/approve", payload, headers
        )

    def activate_rate_program(self, rate_program_id, payload, headers):
        return self._request(
            "POST", f"/ltl/rate-programs/{rate_program_id}/activate", payload, headers
        )

    # ------------------------------------------------------------------
    # Exception agreements
    # ------------------------------------------------------------------
    def create_exception_agreement(self, payload, headers):
        return self._request("POST", "/ltl/exception-agreements", payload, headers)

    def get_exception_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/ltl/exception-agreements/{agreement_id}", headers=headers
        )

    def list_exception_agreements(self, headers, params=None):
        return self._request(
            "GET", "/ltl/exception-agreements", headers=headers, params=params
        )

    def approve_exception_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/ltl/exception-agreements/{agreement_id}/approve", payload, headers
        )

    # ------------------------------------------------------------------
    # Shipments (bills of lading)
    # ------------------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", "/ltl/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/ltl/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/ltl/shipments", headers=headers, params=params)

    def create_shipment_line(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/ltl/shipments/{shipment_id}/lines", payload, headers
        )

    def get_shipment_line(self, shipment_line_id, headers):
        return self._request(
            "GET", f"/ltl/shipment-lines/{shipment_line_id}", headers=headers
        )

    def list_shipment_lines(self, headers, params=None):
        return self._request("GET", "/ltl/shipment-lines", headers=headers, params=params)

    def bill_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/ltl/shipments/{shipment_id}/bill", payload, headers
        )

    def close_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/ltl/shipments/{shipment_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Dock capture
    # ------------------------------------------------------------------
    def create_capture_event(self, payload, headers):
        return self._request("POST", "/ltl/capture-events", payload, headers)

    def get_capture_event(self, capture_event_id, headers):
        return self._request(
            "GET", f"/ltl/capture-events/{capture_event_id}", headers=headers
        )

    def list_capture_events(self, headers, params=None):
        return self._request("GET", "/ltl/capture-events", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Inspection findings
    # ------------------------------------------------------------------
    def create_inspection_finding(self, payload, headers):
        return self._request("POST", "/ltl/inspection-findings", payload, headers)

    def get_inspection_finding(self, finding_id, headers):
        return self._request(
            "GET", f"/ltl/inspection-findings/{finding_id}", headers=headers
        )

    def list_inspection_findings(self, headers, params=None):
        return self._request(
            "GET", "/ltl/inspection-findings", headers=headers, params=params
        )

    def accept_inspection_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/ltl/inspection-findings/{finding_id}/accept", payload, headers
        )

    # ------------------------------------------------------------------
    # Correction notices
    # ------------------------------------------------------------------
    def create_correction_notice(self, payload, headers):
        return self._request("POST", "/ltl/correction-notices", payload, headers)

    def get_correction_notice(self, notice_id, headers):
        return self._request(
            "GET", f"/ltl/correction-notices/{notice_id}", headers=headers
        )

    def list_correction_notices(self, headers, params=None):
        return self._request(
            "GET", "/ltl/correction-notices", headers=headers, params=params
        )

    def issue_correction_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/ltl/correction-notices/{notice_id}/issue", payload, headers
        )

    def create_notice_sweep(self, payload, headers):
        return self._request("POST", "/ltl/notice-sweeps", payload, headers)

    # ------------------------------------------------------------------
    # Disputes
    # ------------------------------------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", "/ltl/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/ltl/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/ltl/disputes", headers=headers, params=params)

    def request_dispute_supplement(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/ltl/disputes/{dispute_id}/request-supplement", payload, headers
        )

    def supplement_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/ltl/disputes/{dispute_id}/supplement", payload, headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/ltl/disputes/{dispute_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Credit memos
    # ------------------------------------------------------------------
    def get_credit_memo(self, credit_memo_id, headers):
        return self._request(
            "GET", f"/ltl/credit-memos/{credit_memo_id}", headers=headers
        )

    def list_credit_memos(self, headers, params=None):
        return self._request("GET", "/ltl/credit-memos", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Repricing runs
    # ------------------------------------------------------------------
    def create_repricing_run(self, payload, headers):
        return self._request("POST", "/ltl/repricing-runs", payload, headers)

    def get_repricing_run(self, repricing_run_id, headers):
        return self._request(
            "GET", f"/ltl/repricing-runs/{repricing_run_id}", headers=headers
        )

    def list_repricing_runs(self, headers, params=None):
        return self._request("GET", "/ltl/repricing-runs", headers=headers, params=params)

    def model_repricing_run(self, repricing_run_id, payload, headers):
        return self._request(
            "POST", f"/ltl/repricing-runs/{repricing_run_id}/model", payload, headers
        )

    def commit_repricing_run(self, repricing_run_id, payload, headers):
        return self._request(
            "POST", f"/ltl/repricing-runs/{repricing_run_id}/commit", payload, headers
        )


api_client = ApiClient()
