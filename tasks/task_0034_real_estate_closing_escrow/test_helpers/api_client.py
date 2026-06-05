"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Purchase Agreements (PRD §3.1, §3.5, §3.6) ─────────────────
    def create_purchase_agreement(self, payload, headers):
        return self._request("POST", "/purchase-agreements", payload, headers)

    def get_purchase_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/purchase-agreements/{agreement_id}", headers=headers
        )

    def list_purchase_agreements(self, headers, params=None):
        return self._request(
            "GET", "/purchase-agreements", headers=headers, params=params
        )

    def activate_purchase_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/purchase-agreements/{agreement_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def clear_to_close_purchase_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/purchase-agreements/{agreement_id}/clear-to-close",
            payload if payload is not None else {},
            headers,
        )

    def close_purchase_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/purchase-agreements/{agreement_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def terminate_purchase_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/purchase-agreements/{agreement_id}/terminate",
            payload,
            headers,
        )

    # ─── Escrow Accounts (PRD §3.1) ─────────────────────────────────
    def get_escrow_account(self, escrow_id, headers):
        return self._request("GET", f"/escrow-accounts/{escrow_id}", headers=headers)

    def list_escrow_accounts(self, headers, params=None):
        return self._request(
            "GET", "/escrow-accounts", headers=headers, params=params
        )

    # ─── Earnest Money Deposits (PRD §3.1) ──────────────────────────
    def create_earnest_money_deposit(self, payload, headers):
        return self._request("POST", "/earnest-money-deposits", payload, headers)

    def confirm_earnest_money_deposit(self, deposit_id, payload, headers):
        return self._request(
            "POST",
            f"/earnest-money-deposits/{deposit_id}/confirm",
            payload,
            headers,
        )

    def get_earnest_money_deposit(self, deposit_id, headers):
        return self._request(
            "GET", f"/earnest-money-deposits/{deposit_id}", headers=headers
        )

    def list_earnest_money_deposits(self, headers, params=None):
        return self._request(
            "GET", "/earnest-money-deposits", headers=headers, params=params
        )

    # ─── Title Searches (PRD §3.2) ──────────────────────────────────
    def create_title_search(self, payload, headers):
        return self._request("POST", "/title-searches", payload, headers)

    def complete_title_search(self, search_id, payload, headers):
        return self._request(
            "POST", f"/title-searches/{search_id}/complete", payload, headers
        )

    def resolve_title_search(self, search_id, payload, headers):
        return self._request(
            "POST",
            f"/title-searches/{search_id}/resolve",
            payload if payload is not None else {},
            headers,
        )

    def get_title_search(self, search_id, headers):
        return self._request("GET", f"/title-searches/{search_id}", headers=headers)

    def list_title_searches(self, headers, params=None):
        return self._request(
            "GET", "/title-searches", headers=headers, params=params
        )

    # ─── Title Insurance Policies (PRD §3.2, §2.7 OCC) ──────────────
    def create_title_insurance_policy(self, payload, headers):
        return self._request("POST", "/title-insurance-policies", payload, headers)

    def get_title_insurance_policy(self, policy_id, headers):
        return self._request(
            "GET", f"/title-insurance-policies/{policy_id}", headers=headers
        )

    def list_title_insurance_policies(self, headers, params=None):
        return self._request(
            "GET", "/title-insurance-policies", headers=headers, params=params
        )

    # ─── CC&R Reviews (PRD §3.3) ────────────────────────────────────
    def create_ccr_review(self, payload, headers):
        return self._request("POST", "/ccr-reviews", payload, headers)

    def list_ccr_reviews(self, headers, params=None):
        return self._request("GET", "/ccr-reviews", headers=headers, params=params)

    def get_ccr_review(self, review_id, headers):
        return self._request("GET", f"/ccr-reviews/{review_id}", headers=headers)

    # ─── Closing Disclosures (PRD §3.4, §2.7 OCC) ───────────────────
    def create_closing_disclosure(self, payload, headers):
        return self._request("POST", "/closing-disclosures", payload, headers)

    def deliver_closing_disclosure(self, cd_id, headers, payload=None):
        return self._request(
            "POST",
            f"/closing-disclosures/{cd_id}/deliver",
            payload if payload is not None else {},
            headers,
        )

    def reissue_closing_disclosure(self, cd_id, payload, headers):
        return self._request(
            "POST", f"/closing-disclosures/{cd_id}/reissue", payload, headers
        )

    def acknowledge_closing_disclosure(self, cd_id, headers, payload=None):
        return self._request(
            "POST",
            f"/closing-disclosures/{cd_id}/acknowledge",
            payload if payload is not None else {},
            headers,
        )

    def get_closing_disclosure(self, cd_id, headers):
        return self._request(
            "GET", f"/closing-disclosures/{cd_id}", headers=headers
        )

    def list_closing_disclosures(self, headers, params=None):
        return self._request(
            "GET", "/closing-disclosures", headers=headers, params=params
        )

    # ─── Wire Instructions (PRD §3.5, §2.6) ─────────────────────────
    def create_wire_instruction(self, payload, headers):
        return self._request("POST", "/wire-instructions", payload, headers)

    def callback_verify_wire_instruction(self, wire_id, payload, headers):
        return self._request(
            "POST",
            f"/wire-instructions/{wire_id}/callback-verify",
            payload,
            headers,
        )

    def lock_wire_instruction(self, wire_id, headers, payload=None):
        return self._request(
            "POST",
            f"/wire-instructions/{wire_id}/lock",
            payload if payload is not None else {},
            headers,
        )

    def reject_wire_instruction(self, wire_id, headers, payload=None):
        return self._request(
            "POST",
            f"/wire-instructions/{wire_id}/reject",
            payload if payload is not None else {},
            headers,
        )

    def get_wire_instruction(self, wire_id, headers):
        return self._request("GET", f"/wire-instructions/{wire_id}", headers=headers)

    def list_wire_instructions(self, headers, params=None):
        return self._request(
            "GET", "/wire-instructions", headers=headers, params=params
        )

    # ─── Disbursements (PRD §3.5) ───────────────────────────────────
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/disbursements", payload, headers)

    def list_disbursements(self, headers, params=None):
        return self._request(
            "GET", "/disbursements", headers=headers, params=params
        )

    def get_disbursement(self, disbursement_id, headers):
        return self._request(
            "GET", f"/disbursements/{disbursement_id}", headers=headers
        )

    # ─── 1031 Exchange Accounts (PRD §3.7) ──────────────────────────
    def create_exchange_account(self, payload, headers):
        return self._request("POST", "/exchange-accounts", payload, headers)

    def identify_exchange_account(self, exchange_id, payload, headers):
        return self._request(
            "POST",
            f"/exchange-accounts/{exchange_id}/identify",
            payload,
            headers,
        )

    def get_exchange_account(self, exchange_id, headers):
        return self._request(
            "GET", f"/exchange-accounts/{exchange_id}", headers=headers
        )

    def list_exchange_accounts(self, headers, params=None):
        return self._request(
            "GET", "/exchange-accounts", headers=headers, params=params
        )

    # ─── Users (PRD §2.1) ───────────────────────────────────────────
    def create_user(self, payload, headers):
        return self._request("POST", "/users", payload, headers)

    def get_user(self, user_id, headers):
        return self._request("GET", f"/users/{user_id}", headers=headers)

    def list_users(self, headers, params=None):
        return self._request("GET", "/users", headers=headers, params=params)

    # ─── Test-driving clock (PRD §3.8) ──────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
