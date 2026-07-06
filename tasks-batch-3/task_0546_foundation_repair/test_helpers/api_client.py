"""API client: one method per endpoint defined in the Foundation Repair PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Lead ---
    def create_lead(self, payload, headers):
        return self._request("POST", "/foundation/leads", payload, headers)

    def get_lead(self, lead_id, headers):
        return self._request("GET", f"/foundation/leads/{lead_id}", headers=headers)

    def list_leads(self, headers, params=None):
        return self._request("GET", "/foundation/leads", headers=headers, params=params)

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/foundation/inspections", payload, headers)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/foundation/inspections/{inspection_id}/complete", payload, headers
        )

    def cancel_inspection(self, inspection_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/inspections/{inspection_id}/cancel", payload or {}, headers
        )

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/foundation/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params=None):
        return self._request(
            "GET", "/foundation/inspections", headers=headers, params=params
        )

    # --- EngineeringScope ---
    def create_scope(self, payload, headers):
        return self._request("POST", "/foundation/scopes", payload, headers)

    def finalize_scope(self, scope_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/scopes/{scope_id}/finalize", payload or {}, headers
        )

    def get_scope(self, scope_id, headers):
        return self._request("GET", f"/foundation/scopes/{scope_id}", headers=headers)

    def list_scopes(self, headers, params=None):
        return self._request("GET", "/foundation/scopes", headers=headers, params=params)

    # --- Quote ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/foundation/quotes", payload, headers)

    def send_quote(self, quote_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/quotes/{quote_id}/send", payload or {}, headers
        )

    def accept_quote(self, quote_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/quotes/{quote_id}/accept", payload or {}, headers
        )

    def reject_quote(self, quote_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/quotes/{quote_id}/reject", payload or {}, headers
        )

    def revise_quote(self, quote_id, payload, headers):
        return self._request(
            "POST", f"/foundation/quotes/{quote_id}/revise", payload, headers
        )

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/foundation/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/foundation/quotes", headers=headers, params=params)

    # --- Job ---
    def schedule_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/foundation/jobs/{job_id}/schedule", payload, headers
        )

    def start_job(self, job_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/jobs/{job_id}/start", payload or {}, headers
        )

    def complete_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/foundation/jobs/{job_id}/complete", payload, headers
        )

    def cancel_job(self, job_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/jobs/{job_id}/cancel", payload or {}, headers
        )

    def get_job(self, job_id, headers):
        return self._request("GET", f"/foundation/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/foundation/jobs", headers=headers, params=params)

    # --- Crew ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/foundation/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/foundation/crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/foundation/crews", headers=headers, params=params)

    # --- Permit ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/foundation/permits", payload, headers)

    def decide_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/foundation/permits/{permit_id}/decide", payload, headers
        )

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/foundation/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/foundation/permits", headers=headers, params=params)

    # --- Warranty ---
    def transfer_warranty(self, warranty_id, payload, headers):
        return self._request(
            "POST", f"/foundation/warranties/{warranty_id}/transfer", payload, headers
        )

    def void_warranty(self, warranty_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/warranties/{warranty_id}/void", payload or {}, headers
        )

    def get_warranty(self, warranty_id, headers):
        return self._request(
            "GET", f"/foundation/warranties/{warranty_id}", headers=headers
        )

    def list_warranties(self, headers, params=None):
        return self._request(
            "GET", "/foundation/warranties", headers=headers, params=params
        )

    # --- MaintenanceVisit ---
    def create_maintenance_visit(self, payload, headers):
        return self._request("POST", "/foundation/maintenance-visits", payload, headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/foundation/maintenance-visits/{visit_id}/complete", payload, headers
        )

    def mark_missed_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/foundation/maintenance-visits/{visit_id}/mark-missed",
            payload or {},
            headers,
        )

    def get_visit(self, visit_id, headers):
        return self._request(
            "GET", f"/foundation/maintenance-visits/{visit_id}", headers=headers
        )

    def list_visits(self, headers, params=None):
        return self._request(
            "GET", "/foundation/maintenance-visits", headers=headers, params=params
        )

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/foundation/claims", payload, headers)

    def review_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/claims/{claim_id}/review", payload or {}, headers
        )

    def request_info_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/claims/{claim_id}/request-info", payload or {}, headers
        )

    def resubmit_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/claims/{claim_id}/resubmit", payload or {}, headers
        )

    def approve_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/claims/{claim_id}/approve", payload or {}, headers
        )

    def deny_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/claims/{claim_id}/deny", payload or {}, headers
        )

    def resolve_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/foundation/claims/{claim_id}/resolve", payload or {}, headers
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/foundation/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/foundation/claims", headers=headers, params=params)

    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/foundation/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
