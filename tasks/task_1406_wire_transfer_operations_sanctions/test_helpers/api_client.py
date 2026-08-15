"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Test-driving hooks (PRD §2.5, §3.6)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/wire-ops/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def simulate_screening_hit(self, payload, headers):
        return self._request("POST", "/wire-ops/_screening/simulate", payload, headers)

    # ------------------------------------------------------------------
    # Customers (PRD §3.1)
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/wire-ops/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/wire-ops/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/wire-ops/customers", headers=headers, params=params)

    def freeze_customer(self, customer_id, headers):
        return self._request("POST", f"/wire-ops/customers/{customer_id}/freeze", {}, headers)

    def unfreeze_customer(self, customer_id, headers):
        return self._request(
            "POST", f"/wire-ops/customers/{customer_id}/unfreeze", {}, headers,
        )

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/wire-ops/customers/{customer_id}/close", {}, headers)

    def list_customer_accounts(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/wire-ops/customers/{customer_id}/accounts",
            headers=headers, params=params,
        )

    def list_customer_beneficiaries(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/wire-ops/customers/{customer_id}/beneficiaries",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Accounts (PRD §3.1)
    # ------------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/wire-ops/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/wire-ops/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/wire-ops/accounts", headers=headers, params=params)

    def mark_account_dormant(self, account_id, headers):
        return self._request(
            "POST", f"/wire-ops/accounts/{account_id}/mark-dormant", {}, headers,
        )

    def close_account(self, account_id, headers):
        return self._request("POST", f"/wire-ops/accounts/{account_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Beneficiaries (PRD §3.1)
    # ------------------------------------------------------------------
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/wire-ops/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id, headers):
        return self._request(
            "GET", f"/wire-ops/beneficiaries/{beneficiary_id}", headers=headers,
        )

    def list_beneficiaries(self, headers, params=None):
        return self._request(
            "GET", "/wire-ops/beneficiaries", headers=headers, params=params,
        )

    def retire_beneficiary(self, beneficiary_id, headers):
        return self._request(
            "POST", f"/wire-ops/beneficiaries/{beneficiary_id}/retire", {}, headers,
        )

    # ------------------------------------------------------------------
    # Business dates (PRD §2.5)
    # ------------------------------------------------------------------
    def create_business_date(self, payload, headers):
        return self._request("POST", "/wire-ops/business-dates", payload, headers)

    def get_business_date(self, business_date_id, headers):
        return self._request(
            "GET", f"/wire-ops/business-dates/{business_date_id}", headers=headers,
        )

    def list_business_dates(self, headers, params=None):
        return self._request(
            "GET", "/wire-ops/business-dates", headers=headers, params=params,
        )

    def close_cutoff(self, business_date_id, headers):
        return self._request(
            "POST", f"/wire-ops/business-dates/{business_date_id}/close-cutoff",
            {}, headers,
        )

    def close_day(self, business_date_id, headers):
        return self._request(
            "POST", f"/wire-ops/business-dates/{business_date_id}/close-day",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Wires (PRD §3.2-§3.5)
    # ------------------------------------------------------------------
    def create_wire(self, payload, headers):
        return self._request("POST", "/wire-ops/wires", payload, headers)

    def get_wire(self, wire_id, headers):
        return self._request("GET", f"/wire-ops/wires/{wire_id}", headers=headers)

    def list_wires(self, headers, params=None):
        return self._request("GET", "/wire-ops/wires", headers=headers, params=params)

    def submit_wire(self, wire_id, payload, headers):
        return self._request("POST", f"/wire-ops/wires/{wire_id}/submit", payload, headers)

    def approve_wire(self, wire_id, payload, headers):
        return self._request("POST", f"/wire-ops/wires/{wire_id}/approve", payload, headers)

    def reject_wire(self, wire_id, payload, headers):
        return self._request("POST", f"/wire-ops/wires/{wire_id}/reject", payload, headers)

    def release_wire(self, wire_id, payload, headers):
        return self._request("POST", f"/wire-ops/wires/{wire_id}/release", payload, headers)

    def cancel_wire(self, wire_id, headers):
        return self._request("POST", f"/wire-ops/wires/{wire_id}/cancel", {}, headers)

    def repair_wire(self, wire_id, payload, headers):
        return self._request("POST", f"/wire-ops/wires/{wire_id}/repair", payload, headers)

    def resubmit_wire(self, wire_id, headers):
        return self._request("POST", f"/wire-ops/wires/{wire_id}/resubmit", {}, headers)

    def place_fraud_hold(self, wire_id, payload, headers):
        return self._request(
            "POST", f"/wire-ops/wires/{wire_id}/fraud-holds", payload, headers,
        )

    def get_wire_summary(self, wire_id, headers):
        return self._request("GET", f"/wire-ops/wires/{wire_id}/summary", headers=headers)

    # ------------------------------------------------------------------
    # Approval records (PRD §3.4, §3.11)
    # ------------------------------------------------------------------
    def list_wire_approvals(self, wire_id, headers, params=None):
        return self._request(
            "GET", f"/wire-ops/wires/{wire_id}/approvals", headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Callback verifications (PRD §3.2)
    # ------------------------------------------------------------------
    def list_wire_callbacks(self, wire_id, headers, params=None):
        return self._request(
            "GET", f"/wire-ops/wires/{wire_id}/callbacks", headers=headers, params=params,
        )

    def get_callback(self, callback_id, headers):
        return self._request("GET", f"/wire-ops/callbacks/{callback_id}", headers=headers)

    def record_callback(self, callback_id, payload, headers):
        return self._request(
            "POST", f"/wire-ops/callbacks/{callback_id}/record", payload, headers,
        )

    # ------------------------------------------------------------------
    # Sanctions hits (PRD §3.6)
    # ------------------------------------------------------------------
    def list_wire_sanctions_hits(self, wire_id, headers, params=None):
        return self._request(
            "GET", f"/wire-ops/wires/{wire_id}/sanctions-hits",
            headers=headers, params=params,
        )

    def get_sanctions_hit(self, hit_id, headers):
        return self._request(
            "GET", f"/wire-ops/sanctions-hits/{hit_id}", headers=headers,
        )

    def release_sanctions_hit(self, hit_id, payload, headers):
        return self._request(
            "POST", f"/wire-ops/sanctions-hits/{hit_id}/release", payload, headers,
        )

    def confirm_sanctions_hit(self, hit_id, payload, headers):
        return self._request(
            "POST", f"/wire-ops/sanctions-hits/{hit_id}/confirm", payload, headers,
        )

    def escalate_sanctions_hit(self, hit_id, payload, headers):
        return self._request(
            "POST", f"/wire-ops/sanctions-hits/{hit_id}/escalate", payload, headers,
        )

    # ------------------------------------------------------------------
    # Fraud holds (PRD §3.8)
    # ------------------------------------------------------------------
    def list_wire_fraud_holds(self, wire_id, headers, params=None):
        return self._request(
            "GET", f"/wire-ops/wires/{wire_id}/fraud-holds", headers=headers, params=params,
        )

    def get_fraud_hold(self, hold_id, headers):
        return self._request("GET", f"/wire-ops/fraud-holds/{hold_id}", headers=headers)

    def confirm_fraud_hold(self, hold_id, payload, headers):
        return self._request(
            "POST", f"/wire-ops/fraud-holds/{hold_id}/customer-confirm", payload, headers,
        )

    # ------------------------------------------------------------------
    # Recalls (PRD §3.9)
    # ------------------------------------------------------------------
    def create_recall(self, payload, headers):
        return self._request("POST", "/wire-ops/recalls", payload, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/wire-ops/recalls/{recall_id}", headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/wire-ops/recalls", headers=headers, params=params)

    def send_recall(self, recall_id, headers):
        return self._request("POST", f"/wire-ops/recalls/{recall_id}/send", {}, headers)

    def respond_recall(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/wire-ops/recalls/{recall_id}/respond", payload, headers,
        )

    def complete_recall(self, recall_id, headers):
        return self._request(
            "POST", f"/wire-ops/recalls/{recall_id}/complete", {}, headers,
        )

    def decline_recall(self, recall_id, headers):
        return self._request(
            "POST", f"/wire-ops/recalls/{recall_id}/decline", {}, headers,
        )

    # ------------------------------------------------------------------
    # Correspondent charges & fee assessments (PRD §3.7)
    # ------------------------------------------------------------------
    def post_charge(self, wire_id, payload, headers):
        return self._request("POST", f"/wire-ops/wires/{wire_id}/charges", payload, headers)

    def list_wire_charges(self, wire_id, headers, params=None):
        return self._request(
            "GET", f"/wire-ops/wires/{wire_id}/charges", headers=headers, params=params,
        )

    def assess_fee(self, wire_id, payload, headers):
        return self._request(
            "POST", f"/wire-ops/wires/{wire_id}/fees/assess", payload, headers,
        )

    def list_wire_fees(self, wire_id, headers, params=None):
        return self._request(
            "GET", f"/wire-ops/wires/{wire_id}/fees", headers=headers, params=params,
        )

    def get_fee(self, fee_id, headers):
        return self._request("GET", f"/wire-ops/fees/{fee_id}", headers=headers)

    def bill_fee(self, fee_id, headers):
        return self._request("POST", f"/wire-ops/fees/{fee_id}/bill", {}, headers)

    def waive_fee(self, fee_id, headers):
        return self._request("POST", f"/wire-ops/fees/{fee_id}/waive", {}, headers)

    # ------------------------------------------------------------------
    # Investigations & tracers (PRD §3.10)
    # ------------------------------------------------------------------
    def create_investigation(self, payload, headers):
        return self._request("POST", "/wire-ops/investigations", payload, headers)

    def get_investigation(self, investigation_id, headers):
        return self._request(
            "GET", f"/wire-ops/investigations/{investigation_id}", headers=headers,
        )

    def list_investigations(self, headers, params=None):
        return self._request(
            "GET", "/wire-ops/investigations", headers=headers, params=params,
        )

    def dispatch_tracer(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"/wire-ops/investigations/{investigation_id}/tracers",
            payload, headers,
        )

    def respond_investigation(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"/wire-ops/investigations/{investigation_id}/respond",
            payload, headers,
        )

    def resolve_investigation(self, investigation_id, headers):
        return self._request(
            "POST", f"/wire-ops/investigations/{investigation_id}/resolve", {}, headers,
        )

    def close_investigation(self, investigation_id, headers):
        return self._request(
            "POST", f"/wire-ops/investigations/{investigation_id}/close", {}, headers,
        )

    def list_tracers(self, investigation_id, headers, params=None):
        return self._request(
            "GET", f"/wire-ops/investigations/{investigation_id}/tracers",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Audit log (PRD §2.4, §3.11)
    # ------------------------------------------------------------------
    def get_audit_log(self, entry_id, headers):
        return self._request("GET", f"/wire-ops/audit-logs/{entry_id}", headers=headers)

    def list_audit_logs(self, headers, params=None):
        return self._request("GET", "/wire-ops/audit-logs", headers=headers, params=params)


api_client = ApiClient()
