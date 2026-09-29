"""API client: one method per endpoint declared by the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/land-admin"


class ApiClient(GenericApiClient):
    """Land administration and joint interest billing endpoints."""

    # --- Logical clock ----------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Leases -----------------------------------------------------------
    def create_lease(self, payload, headers):
        return self._request("POST", f"{PREFIX}/leases", payload, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"{PREFIX}/leases/{lease_id}", headers=headers)

    def exercise_lease_extension(self, lease_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/leases/{lease_id}/extension", payload, headers
        )

    def record_obligation_event(self, lease_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/leases/{lease_id}/obligation-events", payload, headers
        )

    # --- Wells ------------------------------------------------------------
    def create_well(self, payload, headers):
        return self._request("POST", f"{PREFIX}/wells", payload, headers)

    def list_wells(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/wells", headers=headers, params=params)

    def get_well(self, well_id, headers):
        return self._request("GET", f"{PREFIX}/wells/{well_id}", headers=headers)

    def change_well_status(self, well_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wells/{well_id}/status-changes", payload, headers
        )

    def create_lease_allocation(self, well_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wells/{well_id}/lease-allocations", payload, headers
        )

    def list_lease_allocations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lease-allocations", headers=headers, params=params
        )

    def get_lease_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/lease-allocations/{allocation_id}", headers=headers
        )

    def effectuate_pooling(self, well_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wells/{well_id}/pooling-effectuation", payload, headers
        )

    # --- Interest owners --------------------------------------------------
    def create_interest_owner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/interest-owners", payload, headers)

    def list_interest_owners(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/interest-owners", headers=headers, params=params
        )

    def get_interest_owner(self, owner_id, headers):
        return self._request(
            "GET", f"{PREFIX}/interest-owners/{owner_id}", headers=headers
        )

    def update_owner_compliance(self, owner_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/interest-owners/{owner_id}/compliance-updates",
            payload,
            headers,
        )

    def list_owner_jib_line_items(self, owner_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/interest-owners/{owner_id}/jib-line-items",
            headers=headers,
            params=params,
        )

    # --- Well interests ---------------------------------------------------
    def create_well_interest(self, well_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wells/{well_id}/interests", payload, headers
        )

    def list_well_interests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/well-interests", headers=headers, params=params
        )

    def get_well_interest(self, interest_id, headers):
        return self._request(
            "GET", f"{PREFIX}/well-interests/{interest_id}", headers=headers
        )

    def terminate_well_interest(self, interest_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/well-interests/{interest_id}/termination",
            payload,
            headers,
        )

    # --- AFEs and elections ----------------------------------------------
    def create_afe(self, well_id, payload, headers):
        return self._request("POST", f"{PREFIX}/wells/{well_id}/afes", payload, headers)

    def list_afes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/afes", headers=headers, params=params)

    def get_afe(self, afe_id, headers):
        return self._request("GET", f"{PREFIX}/afes/{afe_id}", headers=headers)

    def submit_afe_election(self, afe_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/afes/{afe_id}/elections", payload, headers
        )

    def list_afe_elections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/afe-elections", headers=headers, params=params
        )

    def get_afe_election(self, election_id, headers):
        return self._request(
            "GET", f"{PREFIX}/afe-elections/{election_id}", headers=headers
        )

    def close_afe_elections(self, afe_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/afes/{afe_id}/election-closures", payload, headers
        )

    # --- Cost entries -----------------------------------------------------
    def create_cost_entry(self, well_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wells/{well_id}/cost-entries", payload, headers
        )

    def list_cost_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cost-entries", headers=headers, params=params
        )

    def get_cost_entry(self, cost_entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/cost-entries/{cost_entry_id}", headers=headers
        )

    def pay_cost_entry(self, cost_entry_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cost-entries/{cost_entry_id}/payment", payload, headers
        )

    # --- Joint interest billing statements --------------------------------
    def create_jib_statement(self, well_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wells/{well_id}/jib-statements", payload, headers
        )

    def list_jib_statements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/jib-statements", headers=headers, params=params
        )

    def get_jib_statement(self, statement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/jib-statements/{statement_id}", headers=headers
        )

    def list_jib_statement_line_items(self, statement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/jib-statements/{statement_id}/line-items",
            headers=headers,
            params=params,
        )

    def issue_jib_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/jib-statements/{statement_id}/issuance", payload, headers
        )

    def revise_jib_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/jib-statements/{statement_id}/revisions", payload, headers
        )

    def void_jib_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/jib-statements/{statement_id}/void", payload, headers
        )

    def settle_jib_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/jib-statements/{statement_id}/settlement",
            payload,
            headers,
        )

    # --- Disputes ---------------------------------------------------------
    def file_dispute(self, statement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/jib-statements/{statement_id}/disputes", payload, headers
        )

    def list_disputes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"{PREFIX}/disputes/{dispute_id}", headers=headers)

    def create_dispute_exchange(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/disputes/{dispute_id}/exchanges", payload, headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/disputes/{dispute_id}/resolution", payload, headers
        )

    # --- Production revenue and disbursements -----------------------------
    def create_production_revenue(self, well_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wells/{well_id}/production-revenues", payload, headers
        )

    def list_production_revenues(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/production-revenues", headers=headers, params=params
        )

    def get_production_revenue(self, revenue_id, headers):
        return self._request(
            "GET", f"{PREFIX}/production-revenues/{revenue_id}", headers=headers
        )

    def release_production_revenue(self, revenue_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/production-revenues/{revenue_id}/release",
            payload,
            headers,
        )

    def list_owner_disbursements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/owner-disbursements", headers=headers, params=params
        )

    def get_owner_disbursement(self, disbursement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/owner-disbursements/{disbursement_id}", headers=headers
        )

    def release_disbursement_suspense(self, disbursement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/owner-disbursements/{disbursement_id}/suspense-release",
            payload,
            headers,
        )

    def pay_owner_disbursement(self, disbursement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/owner-disbursements/{disbursement_id}/payment",
            payload,
            headers,
        )

    # --- Assignment transfers ---------------------------------------------
    def create_assignment_transfer(self, well_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wells/{well_id}/assignment-transfers", payload, headers
        )

    def list_assignment_transfers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assignment-transfers", headers=headers, params=params
        )

    def get_assignment_transfer(self, transfer_id, headers):
        return self._request(
            "GET", f"{PREFIX}/assignment-transfers/{transfer_id}", headers=headers
        )

    def submit_ppr_election(self, transfer_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/assignment-transfers/{transfer_id}/ppr-elections",
            payload,
            headers,
        )

    def close_assignment_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/assignment-transfers/{transfer_id}/closing",
            payload,
            headers,
        )

    # --- Obligation evaluation pass ---------------------------------------
    def run_obligation_pass(self, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/obligation-runs", payload, headers
        )


api_client = ApiClient()
