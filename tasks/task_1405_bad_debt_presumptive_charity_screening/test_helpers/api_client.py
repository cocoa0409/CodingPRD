"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/self-pay/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------------------
    # Self-pay accounts (PRD §3.1)
    # ------------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/self-pay/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/self-pay/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/self-pay/accounts/{account_id}", headers=headers)

    # ------------------------------------------------------------------
    # Statements (PRD §3.2)
    # ------------------------------------------------------------------
    def issue_statement(self, account_id, headers):
        return self._request("POST", f"/self-pay/accounts/{account_id}/statements", {}, headers)

    def list_statements(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/self-pay/accounts/{account_id}/statements",
            headers=headers, params=params,
        )

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/self-pay/statements/{statement_id}", headers=headers)

    def mark_statement_delivered(self, statement_id, headers):
        return self._request(
            "POST", f"/self-pay/statements/{statement_id}/mark-delivered", {}, headers,
        )

    def mark_statement_returned(self, statement_id, headers):
        return self._request(
            "POST", f"/self-pay/statements/{statement_id}/mark-returned", {}, headers,
        )

    # ------------------------------------------------------------------
    # Presumptive charity screenings (PRD §3.3)
    # ------------------------------------------------------------------
    def create_screening(self, payload, headers):
        return self._request("POST", "/self-pay/presumptive-charity-screenings", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request(
            "GET", f"/self-pay/presumptive-charity-screenings/{screening_id}", headers=headers,
        )

    def list_account_screenings(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/self-pay/accounts/{account_id}/presumptive-charity-screenings",
            headers=headers, params=params,
        )

    def evaluate_screening(self, screening_id, headers):
        return self._request(
            "POST", f"/self-pay/presumptive-charity-screenings/{screening_id}/evaluate",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Early-out placements (PRD §3.4)
    # ------------------------------------------------------------------
    def create_early_out_placement(self, payload, headers):
        return self._request("POST", "/self-pay/early-out-placements", payload, headers)

    def get_early_out_placement(self, placement_id, headers):
        return self._request(
            "GET", f"/self-pay/early-out-placements/{placement_id}", headers=headers,
        )

    def list_account_early_out_placements(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/self-pay/accounts/{account_id}/early-out-placements",
            headers=headers, params=params,
        )

    def recall_early_out_placement(self, placement_id, headers):
        return self._request(
            "POST", f"/self-pay/early-out-placements/{placement_id}/recall", {}, headers,
        )

    # ------------------------------------------------------------------
    # Collection agency placements (PRD §3.5)
    # ------------------------------------------------------------------
    def create_agency_placement(self, payload, headers):
        return self._request("POST", "/self-pay/collection-agency-placements", payload, headers)

    def get_agency_placement(self, placement_id, headers):
        return self._request(
            "GET", f"/self-pay/collection-agency-placements/{placement_id}", headers=headers,
        )

    def list_account_agency_placements(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/self-pay/accounts/{account_id}/collection-agency-placements",
            headers=headers, params=params,
        )

    def recall_agency_placement(self, placement_id, headers):
        return self._request(
            "POST", f"/self-pay/collection-agency-placements/{placement_id}/recall", {}, headers,
        )

    def mark_credit_reported(self, placement_id, headers):
        return self._request(
            "POST",
            f"/self-pay/collection-agency-placements/{placement_id}/mark-credit-reported",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Patient disputes (PRD §3.6)
    # ------------------------------------------------------------------
    def file_dispute(self, payload, headers):
        return self._request("POST", "/self-pay/patient-disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/self-pay/patient-disputes/{dispute_id}", headers=headers)

    def list_account_disputes(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/self-pay/accounts/{account_id}/patient-disputes",
            headers=headers, params=params,
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/self-pay/patient-disputes/{dispute_id}/resolve", payload, headers,
        )

    # ------------------------------------------------------------------
    # Payment plans (PRD §3.7)
    # ------------------------------------------------------------------
    def create_payment_plan(self, payload, headers):
        return self._request("POST", "/self-pay/payment-plans", payload, headers)

    def get_payment_plan(self, plan_id, headers):
        return self._request("GET", f"/self-pay/payment-plans/{plan_id}", headers=headers)

    def list_account_payment_plans(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/self-pay/accounts/{account_id}/payment-plans",
            headers=headers, params=params,
        )

    def cure_payment_plan(self, plan_id, headers):
        return self._request("POST", f"/self-pay/payment-plans/{plan_id}/cure", {}, headers)

    def terminate_payment_plan(self, plan_id, headers):
        return self._request("POST", f"/self-pay/payment-plans/{plan_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Bad-debt / charity write-offs (PRD §3.9)
    # ------------------------------------------------------------------
    def create_write_off(self, payload, headers):
        return self._request("POST", "/self-pay/bad-debt-write-offs", payload, headers)

    def get_write_off(self, write_off_id, headers):
        return self._request(
            "GET", f"/self-pay/bad-debt-write-offs/{write_off_id}", headers=headers,
        )

    def list_write_offs(self, headers, params=None):
        return self._request("GET", "/self-pay/bad-debt-write-offs", headers=headers, params=params)

    def list_account_write_offs(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/self-pay/accounts/{account_id}/bad-debt-write-offs",
            headers=headers, params=params,
        )

    def approve_write_off(self, write_off_id, payload, headers):
        return self._request(
            "POST", f"/self-pay/bad-debt-write-offs/{write_off_id}/approve", payload, headers,
        )

    def reverse_write_off(self, write_off_id, headers):
        return self._request(
            "POST", f"/self-pay/bad-debt-write-offs/{write_off_id}/reverse", {}, headers,
        )

    # ------------------------------------------------------------------
    # Medicare bad-debt log (PRD §3.9)
    # ------------------------------------------------------------------
    def get_medicare_log_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/self-pay/medicare-bad-debt-log-entries/{entry_id}", headers=headers,
        )

    def list_medicare_log_entries(self, headers, params=None):
        return self._request(
            "GET", "/self-pay/medicare-bad-debt-log-entries", headers=headers, params=params,
        )

    def list_account_medicare_log_entries(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/self-pay/accounts/{account_id}/medicare-bad-debt-log-entries",
            headers=headers, params=params,
        )

    def list_write_off_medicare_log_entries(self, write_off_id, headers, params=None):
        return self._request(
            "GET", f"/self-pay/bad-debt-write-offs/{write_off_id}/medicare-bad-debt-log-entries",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Recovery transactions (PRD §3.8)
    # ------------------------------------------------------------------
    def post_recovery_transaction(self, payload, headers):
        return self._request("POST", "/self-pay/recovery-transactions", payload, headers)

    def get_recovery_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"/self-pay/recovery-transactions/{transaction_id}", headers=headers,
        )

    def list_recovery_transactions(self, headers, params=None):
        return self._request(
            "GET", "/self-pay/recovery-transactions", headers=headers, params=params,
        )

    def list_account_recovery_transactions(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/self-pay/accounts/{account_id}/recovery-transactions",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Vendor performance snapshots (PRD §3.4)
    # ------------------------------------------------------------------
    def create_vendor_snapshot(self, payload, headers):
        return self._request("POST", "/self-pay/vendor-performance-snapshots", payload, headers)

    def get_vendor_snapshot(self, snapshot_id, headers):
        return self._request(
            "GET", f"/self-pay/vendor-performance-snapshots/{snapshot_id}", headers=headers,
        )

    def list_vendor_snapshots(self, headers, params=None):
        return self._request(
            "GET", "/self-pay/vendor-performance-snapshots", headers=headers, params=params,
        )


api_client = ApiClient()
