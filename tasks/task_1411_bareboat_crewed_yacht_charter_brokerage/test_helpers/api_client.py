"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- operators / brokers / clients ---
    def create_operator(self, payload, headers):
        return self._request("POST", "/operators", payload, headers)

    def suspend_operator(self, operator_id, headers):
        return self._request("POST", f"/operators/{operator_id}/suspend", {}, headers)

    def reactivate_operator(self, operator_id, headers):
        return self._request("POST", f"/operators/{operator_id}/reactivate", {}, headers)

    def create_broker(self, payload, headers):
        return self._request("POST", "/brokers", payload, headers)

    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def submit_resume(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/resume/submit", payload, headers)

    def review_resume(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/resume/review", payload, headers)

    # --- yachts & calendar ---
    def create_yacht(self, payload, headers):
        return self._request("POST", "/yachts", payload, headers)

    def get_yacht(self, yacht_id, headers):
        return self._request("GET", f"/yachts/{yacht_id}", headers=headers)

    def list_yachts(self, headers, params=None):
        return self._request("GET", "/yachts", headers=headers, params=params or {})

    def list_yacht(self, yacht_id, headers):
        return self._request("POST", f"/yachts/{yacht_id}/list", {}, headers)

    def delist_yacht(self, yacht_id, headers):
        return self._request("POST", f"/yachts/{yacht_id}/delist", {}, headers)

    def list_yacht_availability_blocks(self, yacht_id, headers, params=None):
        return self._request("GET", f"/yachts/{yacht_id}/availability-blocks",
                             headers=headers, params=params or {})

    def create_availability_block(self, yacht_id, payload, headers):
        return self._request("POST", f"/yachts/{yacht_id}/availability-blocks",
                             payload, headers)

    def release_availability_block(self, block_id, headers):
        return self._request("POST", f"/availability-blocks/{block_id}/release", {}, headers)

    # --- charter requests (negotiation) ---
    def create_charter_request(self, payload, headers):
        return self._request("POST", "/charter-requests", payload, headers)

    def get_charter_request(self, request_id, headers):
        return self._request("GET", f"/charter-requests/{request_id}", headers=headers)

    def list_charter_requests(self, headers, params=None):
        return self._request("GET", "/charter-requests", headers=headers, params=params or {})

    def submit_charter_request(self, request_id, headers):
        return self._request("POST", f"/charter-requests/{request_id}/submit", {}, headers)

    def offer_charter_request(self, request_id, payload, headers):
        return self._request("POST", f"/charter-requests/{request_id}/offer", payload, headers)

    def counter_charter_request(self, request_id, payload, headers):
        return self._request("POST", f"/charter-requests/{request_id}/counter", payload, headers)

    def accept_charter_request(self, request_id, payload, headers):
        return self._request("POST", f"/charter-requests/{request_id}/accept", payload, headers)

    def decline_charter_request(self, request_id, headers):
        return self._request("POST", f"/charter-requests/{request_id}/decline", {}, headers)

    def rebook_charter_request(self, request_id, payload, headers):
        return self._request("POST", f"/charter-requests/{request_id}/rebook", payload, headers)

    # --- charter agreements ---
    def get_charter_agreement(self, agreement_id, headers):
        return self._request("GET", f"/charter-agreements/{agreement_id}", headers=headers)

    def list_charter_agreements(self, headers, params=None):
        return self._request("GET", "/charter-agreements", headers=headers, params=params or {})

    def sign_charter_agreement(self, agreement_id, headers):
        return self._request("POST", f"/charter-agreements/{agreement_id}/sign", {}, headers)

    def void_charter_agreement(self, agreement_id, headers):
        return self._request("POST", f"/charter-agreements/{agreement_id}/void", {}, headers)

    def fund_charter_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/charter-agreements/{agreement_id}/fund", payload, headers)

    def start_prep(self, agreement_id, headers):
        return self._request("POST", f"/charter-agreements/{agreement_id}/start-prep", {}, headers)

    def embark(self, agreement_id, headers):
        return self._request("POST", f"/charter-agreements/{agreement_id}/embark", {}, headers)

    def complete(self, agreement_id, headers):
        return self._request("POST", f"/charter-agreements/{agreement_id}/complete", {}, headers)

    def cancel(self, agreement_id, payload, headers):
        return self._request("POST", f"/charter-agreements/{agreement_id}/cancel", payload, headers)

    # --- escrow ---
    def get_agreement_escrow(self, agreement_id, headers):
        return self._request("GET", f"/charter-agreements/{agreement_id}/escrow", headers=headers)

    def get_escrow_account(self, escrow_id, headers):
        return self._request("GET", f"/escrow-accounts/{escrow_id}", headers=headers)

    def list_escrow_movements(self, escrow_id, headers, params=None):
        return self._request("GET", f"/escrow-accounts/{escrow_id}/movements",
                             headers=headers, params=params or {})

    # --- APA expenses / provisioning ---
    def create_expense(self, agreement_id, payload, headers):
        return self._request("POST", f"/charter-agreements/{agreement_id}/expenses",
                             payload, headers)

    def list_expenses(self, agreement_id, headers, params=None):
        return self._request("GET", f"/charter-agreements/{agreement_id}/expenses",
                             headers=headers, params=params or {})

    def review_expense(self, expense_id, payload, headers):
        return self._request("POST", f"/expenses/{expense_id}/review", payload, headers)

    def dispute_expense(self, expense_id, headers):
        return self._request("POST", f"/expenses/{expense_id}/dispute", {}, headers)

    def resolve_expense(self, expense_id, payload, headers):
        return self._request("POST", f"/expenses/{expense_id}/resolve", payload, headers)

    def get_apa_position(self, agreement_id, headers):
        return self._request("GET", f"/charter-agreements/{agreement_id}/apa-position",
                             headers=headers)

    # --- insurance ---
    def create_insurance_certificate(self, agreement_id, payload, headers):
        return self._request("POST",
                             f"/charter-agreements/{agreement_id}/insurance-certificates",
                             payload, headers)

    def list_insurance_certificates(self, agreement_id, headers, params=None):
        return self._request("GET",
                             f"/charter-agreements/{agreement_id}/insurance-certificates",
                             headers=headers, params=params or {})

    def verify_insurance_certificate(self, certificate_id, payload, headers):
        return self._request("POST",
                             f"/insurance-certificates/{certificate_id}/verify",
                             payload, headers)

    # --- itinerary & port permits ---
    def create_itinerary_leg(self, agreement_id, payload, headers):
        return self._request("POST", f"/charter-agreements/{agreement_id}/itinerary-legs",
                             payload, headers)

    def list_itinerary_legs(self, agreement_id, headers, params=None):
        return self._request("GET", f"/charter-agreements/{agreement_id}/itinerary-legs",
                             headers=headers, params=params or {})

    def get_itinerary_leg(self, leg_id, headers):
        return self._request("GET", f"/itinerary-legs/{leg_id}", headers=headers)

    def create_port_permit(self, leg_id, payload, headers):
        return self._request("POST", f"/itinerary-legs/{leg_id}/permits", payload, headers)

    def list_port_permits(self, leg_id, headers, params=None):
        return self._request("GET", f"/itinerary-legs/{leg_id}/permits",
                             headers=headers, params=params or {})

    def decide_port_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/port-permits/{permit_id}/decide", payload, headers)

    def resubmit_port_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/port-permits/{permit_id}/resubmit", payload, headers)

    # --- commissions ---
    def list_commission_statements(self, agreement_id, headers, params=None):
        return self._request("GET",
                             f"/charter-agreements/{agreement_id}/commission-statements",
                             headers=headers, params=params or {})

    # --- agreement-scoped calendar view ---
    def list_agreement_availability_blocks(self, agreement_id, headers, params=None):
        return self._request("GET",
                             f"/charter-agreements/{agreement_id}/availability-blocks",
                             headers=headers, params=params or {})


api_client = ApiClient()
