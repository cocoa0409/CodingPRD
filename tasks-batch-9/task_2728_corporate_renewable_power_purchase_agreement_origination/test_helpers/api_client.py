"""API client: one method per endpoint listed in PRD section 4."""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Corporate renewable power purchase agreement origination API surface."""

    # ---- Logical clock ---------------------------------------------------

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Pricing nodes ---------------------------------------------------

    def create_pricing_node(self, payload, headers):
        return self._request("POST", "/ppa/pricing-nodes", payload, headers)

    def list_pricing_nodes(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/ppa/pricing-nodes", headers=headers,
                             params=params)

    def get_pricing_node(self, node_id, headers):
        return self._request("GET", f"/ppa/pricing-nodes/{node_id}",
                             headers=headers)

    # ---- Offtakers -------------------------------------------------------

    def create_offtaker(self, payload, headers):
        return self._request("POST", "/ppa/offtakers", payload, headers)

    def list_offtakers(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/ppa/offtakers", headers=headers,
                             params=params)

    def get_offtaker(self, offtaker_id, headers):
        return self._request("GET", f"/ppa/offtakers/{offtaker_id}",
                             headers=headers)

    def submit_offtaker_qualification(self, offtaker_id, headers, payload=None):
        return self._request(
            "POST", f"/ppa/offtakers/{offtaker_id}/submit-qualification",
            payload if payload is not None else {}, headers)

    def decide_offtaker_qualification(self, offtaker_id, payload, headers):
        return self._request(
            "POST", f"/ppa/offtakers/{offtaker_id}/qualification-decision",
            payload, headers)

    def change_offtaker_rating(self, offtaker_id, payload, headers):
        return self._request("POST", f"/ppa/offtakers/{offtaker_id}/rating-change",
                             payload, headers)

    def list_offtaker_allocations(self, offtaker_id, headers,
                                  params: Optional[Dict] = None):
        return self._request("GET", f"/ppa/offtakers/{offtaker_id}/allocations",
                             headers=headers, params=params)

    def list_offtaker_attribute_batches(self, offtaker_id, headers,
                                        params: Optional[Dict] = None):
        return self._request("GET",
                             f"/ppa/offtakers/{offtaker_id}/attribute-batches",
                             headers=headers, params=params)

    def list_offtaker_issued_guarantees(self, offtaker_id, headers,
                                        params: Optional[Dict] = None):
        return self._request("GET",
                             f"/ppa/offtakers/{offtaker_id}/issued-guarantees",
                             headers=headers, params=params)

    # ---- Projects --------------------------------------------------------

    def create_project(self, payload, headers):
        return self._request("POST", "/ppa/projects", payload, headers)

    def list_projects(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/ppa/projects", headers=headers,
                             params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/ppa/projects/{project_id}", headers=headers)

    def advance_project_milestone(self, project_id, payload, headers):
        return self._request("POST",
                             f"/ppa/projects/{project_id}/advance-milestone",
                             payload, headers)

    # ---- Deals -----------------------------------------------------------

    def create_deal(self, payload, headers):
        return self._request("POST", "/ppa/deals", payload, headers)

    def list_deals(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/ppa/deals", headers=headers, params=params)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/ppa/deals/{deal_id}", headers=headers)

    # ---- Term sheet rounds ----------------------------------------------

    def create_round(self, deal_id, payload, headers):
        return self._request("POST", f"/ppa/deals/{deal_id}/rounds", payload,
                             headers)

    def list_rounds(self, deal_id, headers, params: Optional[Dict] = None):
        return self._request("GET", f"/ppa/deals/{deal_id}/rounds",
                             headers=headers, params=params)

    def respond_to_round(self, round_id, payload, headers):
        return self._request("POST", f"/ppa/rounds/{round_id}/respond", payload,
                             headers)

    # ---- Allocations -----------------------------------------------------

    def create_allocation(self, deal_id, payload, headers):
        return self._request("POST", f"/ppa/deals/{deal_id}/allocations", payload,
                             headers)

    def list_allocations(self, deal_id, headers, params: Optional[Dict] = None):
        return self._request("GET", f"/ppa/deals/{deal_id}/allocations",
                             headers=headers, params=params)

    def decide_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/ppa/allocations/{allocation_id}/decision",
                             payload, headers)

    # ---- Credit ----------------------------------------------------------

    def submit_deal_credit(self, deal_id, headers, payload=None):
        return self._request("POST", f"/ppa/deals/{deal_id}/submit-credit",
                             payload if payload is not None else {}, headers)

    def decide_deal_credit(self, deal_id, payload, headers):
        return self._request("POST", f"/ppa/deals/{deal_id}/credit-decision",
                             payload, headers)

    def register_credit_support(self, deal_id, payload, headers):
        return self._request("POST", f"/ppa/deals/{deal_id}/credit-support",
                             payload, headers)

    def list_credit_support(self, deal_id, headers, params: Optional[Dict] = None):
        return self._request("GET", f"/ppa/deals/{deal_id}/credit-support",
                             headers=headers, params=params)

    def post_credit_support(self, instrument_id, payload, headers):
        return self._request("POST", f"/ppa/credit-support/{instrument_id}/post",
                             payload, headers)

    def release_credit_support(self, instrument_id, headers, payload=None):
        return self._request("POST",
                             f"/ppa/credit-support/{instrument_id}/release",
                             payload if payload is not None else {}, headers)

    # ---- Execution, conditions precedent and termination -----------------

    def execute_deal(self, deal_id, headers, payload=None):
        return self._request("POST", f"/ppa/deals/{deal_id}/execute",
                             payload if payload is not None else {}, headers)

    def list_conditions_precedent(self, deal_id, headers,
                                  params: Optional[Dict] = None):
        return self._request("GET", f"/ppa/deals/{deal_id}/conditions-precedent",
                             headers=headers, params=params)

    def resolve_condition_precedent(self, condition_id, payload, headers):
        return self._request("POST",
                             f"/ppa/conditions-precedent/{condition_id}/resolution",
                             payload, headers)

    def terminate_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/ppa/deals/{deal_id}/terminate", payload,
                             headers)

    # ---- Settlement ------------------------------------------------------

    def create_settlement_period(self, deal_id, payload, headers):
        return self._request("POST", f"/ppa/deals/{deal_id}/settlement-periods",
                             payload, headers)

    def list_settlement_periods(self, deal_id, headers,
                                params: Optional[Dict] = None):
        return self._request("GET", f"/ppa/deals/{deal_id}/settlement-periods",
                             headers=headers, params=params)

    def get_settlement_period(self, period_id, headers):
        return self._request("GET", f"/ppa/settlement-periods/{period_id}",
                             headers=headers)

    def create_meter_interval(self, period_id, payload, headers):
        return self._request("POST",
                             f"/ppa/settlement-periods/{period_id}/intervals",
                             payload, headers)

    def list_meter_intervals(self, period_id, headers,
                             params: Optional[Dict] = None):
        return self._request("GET",
                             f"/ppa/settlement-periods/{period_id}/intervals",
                             headers=headers, params=params)

    def calculate_settlement_period(self, period_id, headers, payload=None):
        return self._request("POST",
                             f"/ppa/settlement-periods/{period_id}/calculate",
                             payload if payload is not None else {}, headers)

    def advance_settlement_period(self, period_id, payload, headers):
        return self._request("POST",
                             f"/ppa/settlement-periods/{period_id}/advance",
                             payload, headers)

    def mint_attributes(self, period_id, payload, headers):
        return self._request("POST",
                             f"/ppa/settlement-periods/{period_id}/mint-attributes",
                             payload, headers)

    # ---- Environmental attribute batches --------------------------------

    def list_deal_attribute_batches(self, deal_id, headers,
                                    params: Optional[Dict] = None):
        return self._request("GET", f"/ppa/deals/{deal_id}/attribute-batches",
                             headers=headers, params=params)

    def transfer_attribute_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/ppa/attribute-batches/{batch_id}/transfer",
                             payload, headers)

    def cancel_attribute_transfer(self, batch_id, headers, payload=None):
        return self._request("POST",
                             f"/ppa/attribute-batches/{batch_id}/cancel-transfer",
                             payload if payload is not None else {}, headers)

    def retire_attribute_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/ppa/attribute-batches/{batch_id}/retire",
                             payload, headers)

    # ---- Risk events -----------------------------------------------------

    def create_risk_event(self, deal_id, payload, headers):
        return self._request("POST", f"/ppa/deals/{deal_id}/risk-events", payload,
                             headers)

    def list_risk_events(self, deal_id, headers, params: Optional[Dict] = None):
        return self._request("GET", f"/ppa/deals/{deal_id}/risk-events",
                             headers=headers, params=params)

    def review_risk_event(self, event_id, payload, headers):
        return self._request("POST", f"/ppa/risk-events/{event_id}/review",
                             payload, headers)


api_client = ApiClient()
