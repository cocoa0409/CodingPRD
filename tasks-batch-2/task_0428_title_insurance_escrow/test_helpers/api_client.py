"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Agency ----
    def create_agency(self, payload, headers):
        return self._request("POST", "/title/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/title/agencies/{agency_id}", headers=headers)

    def transition_agency(self, agency_id, payload, headers):
        return self._request("POST", f"/title/agencies/{agency_id}/transitions", payload, headers)

    # ---- TitlePlantRecord ----
    def create_plant_record(self, payload, headers):
        return self._request("POST", "/title/plant-records", payload, headers)

    def get_plant_record(self, record_id, headers):
        return self._request("GET", f"/title/plant-records/{record_id}", headers=headers)

    def list_plant_records(self, headers, params=None):
        return self._request("GET", "/title/plant-records", headers=headers, params=params)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/title/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/title/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/title/orders", headers=headers, params=params)

    def transition_order(self, order_id, payload, headers):
        return self._request("POST", f"/title/orders/{order_id}/transitions", payload, headers)

    # ---- TitleSearch ----
    def create_title_search(self, order_id, payload, headers):
        return self._request("POST", f"/title/orders/{order_id}/title-searches", payload, headers)

    def list_title_searches(self, order_id, headers, params=None):
        return self._request("GET", f"/title/orders/{order_id}/title-searches", headers=headers, params=params)

    def get_title_search(self, search_id, headers):
        return self._request("GET", f"/title/title-searches/{search_id}", headers=headers)

    def transition_title_search(self, search_id, payload, headers):
        return self._request("POST", f"/title/title-searches/{search_id}/transitions", payload, headers)

    # ---- Commitment ----
    def create_commitment(self, order_id, payload, headers):
        return self._request("POST", f"/title/orders/{order_id}/commitments", payload, headers)

    def list_commitments(self, order_id, headers, params=None):
        return self._request("GET", f"/title/orders/{order_id}/commitments", headers=headers, params=params)

    def get_commitment(self, commitment_id, headers):
        return self._request("GET", f"/title/commitments/{commitment_id}", headers=headers)

    def transition_commitment(self, commitment_id, payload, headers):
        return self._request("POST", f"/title/commitments/{commitment_id}/transitions", payload, headers)

    # ---- Exception ----
    def create_exception(self, commitment_id, payload, headers):
        return self._request("POST", f"/title/commitments/{commitment_id}/exceptions", payload, headers)

    def list_exceptions(self, commitment_id, headers, params=None):
        return self._request("GET", f"/title/commitments/{commitment_id}/exceptions", headers=headers, params=params)

    def get_exception(self, exception_id, headers):
        return self._request("GET", f"/title/exceptions/{exception_id}", headers=headers)

    def transition_exception(self, exception_id, payload, headers):
        return self._request("POST", f"/title/exceptions/{exception_id}/transitions", payload, headers)

    # ---- Policy ----
    def create_policy(self, order_id, payload, headers):
        return self._request("POST", f"/title/orders/{order_id}/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/title/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/title/policies/{policy_id}", headers=headers)

    def transition_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/title/policies/{policy_id}/transitions", payload, headers)

    # ---- Endorsement ----
    def create_endorsement(self, policy_id, payload, headers):
        return self._request("POST", f"/title/policies/{policy_id}/endorsements", payload, headers)

    def list_endorsements(self, policy_id, headers, params=None):
        return self._request("GET", f"/title/policies/{policy_id}/endorsements", headers=headers, params=params)

    def get_endorsement(self, endorsement_id, headers):
        return self._request("GET", f"/title/endorsements/{endorsement_id}", headers=headers)

    def transition_endorsement(self, endorsement_id, payload, headers):
        return self._request("POST", f"/title/endorsements/{endorsement_id}/transitions", payload, headers)

    # ---- EscrowDeposit ----
    def create_deposit(self, order_id, payload, headers):
        return self._request("POST", f"/title/orders/{order_id}/deposits", payload, headers)

    def list_deposits(self, order_id, headers, params=None):
        return self._request("GET", f"/title/orders/{order_id}/deposits", headers=headers, params=params)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/title/deposits/{deposit_id}", headers=headers)

    def transition_deposit(self, deposit_id, payload, headers):
        return self._request("POST", f"/title/deposits/{deposit_id}/transitions", payload, headers)

    # ---- Disbursement ----
    def create_disbursement(self, order_id, payload, headers):
        return self._request("POST", f"/title/orders/{order_id}/disbursements", payload, headers)

    def list_disbursements(self, order_id, headers, params=None):
        return self._request("GET", f"/title/orders/{order_id}/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/title/disbursements/{disbursement_id}", headers=headers)

    def transition_disbursement(self, disbursement_id, payload, headers):
        return self._request("POST", f"/title/disbursements/{disbursement_id}/transitions", payload, headers)

    # ---- PremiumRemittance ----
    def list_remittances(self, policy_id, headers, params=None):
        return self._request("GET", f"/title/policies/{policy_id}/remittances", headers=headers, params=params)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/title/remittances/{remittance_id}", headers=headers)

    def transition_remittance(self, remittance_id, payload, headers):
        return self._request("POST", f"/title/remittances/{remittance_id}/transitions", payload, headers)

    # ---- Claim ----
    def create_claim(self, policy_id, payload, headers):
        return self._request("POST", f"/title/policies/{policy_id}/claims", payload, headers)

    def list_claims(self, policy_id, headers, params=None):
        return self._request("GET", f"/title/policies/{policy_id}/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/title/claims/{claim_id}", headers=headers)

    def transition_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/title/claims/{claim_id}/transitions", payload, headers)

    # ---- CurativeAction ----
    def create_curative_action(self, order_id, payload, headers):
        return self._request("POST", f"/title/orders/{order_id}/curative-actions", payload, headers)

    def list_curative_actions(self, order_id, headers, params=None):
        return self._request("GET", f"/title/orders/{order_id}/curative-actions", headers=headers, params=params)

    def get_curative_action(self, action_id, headers):
        return self._request("GET", f"/title/curative-actions/{action_id}", headers=headers)

    def transition_curative_action(self, action_id, payload, headers):
        return self._request("POST", f"/title/curative-actions/{action_id}/transitions", payload, headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/title/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
