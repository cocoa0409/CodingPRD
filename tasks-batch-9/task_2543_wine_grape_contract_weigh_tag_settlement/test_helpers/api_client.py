"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/grower-relations"


class ApiClient(GenericApiClient):
    # --- Producers ------------------------------------------------------------
    def create_grower(self, payload, headers):
        return self._request("POST", f"{BASE}/growers", payload, headers)

    def suspend_grower(self, grower_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/growers/{grower_id}/suspend", payload or {}, headers
        )

    def reinstate_grower(self, grower_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/growers/{grower_id}/reinstate", payload or {}, headers
        )

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"{BASE}/growers/{grower_id}", headers=headers)

    def list_growers(self, headers, params=None):
        return self._request("GET", f"{BASE}/growers", headers=headers, params=params)

    # --- Vineyard blocks ------------------------------------------------------
    def create_vineyard_block(self, payload, headers):
        return self._request("POST", f"{BASE}/vineyard-blocks", payload, headers)

    def get_vineyard_block(self, block_id, headers):
        return self._request("GET", f"{BASE}/vineyard-blocks/{block_id}", headers=headers)

    def list_vineyard_blocks(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/vineyard-blocks", headers=headers, params=params
        )

    # --- Quality specifications ----------------------------------------------
    def create_quality_spec(self, payload, headers):
        return self._request("POST", f"{BASE}/quality-specs", payload, headers)

    def get_quality_spec(self, spec_id, headers):
        return self._request("GET", f"{BASE}/quality-specs/{spec_id}", headers=headers)

    def list_quality_specs(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/quality-specs", headers=headers, params=params
        )

    # --- Grape contracts ------------------------------------------------------
    def create_grape_contract(self, payload, headers):
        return self._request("POST", f"{BASE}/grape-contracts", payload, headers)

    def offer_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/grape-contracts/{contract_id}/offer", payload or {}, headers
        )

    def counter_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/grape-contracts/{contract_id}/counter", payload, headers
        )

    def withdraw_offer(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/grape-contracts/{contract_id}/withdraw-offer",
            payload or {},
            headers,
        )

    def accept_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/grape-contracts/{contract_id}/accept", payload or {}, headers
        )

    def close_settlement(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/grape-contracts/{contract_id}/settlement-close",
            payload or {},
            headers,
        )

    def renew_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/grape-contracts/{contract_id}/renew", payload, headers
        )

    def serve_termination_notice(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/grape-contracts/{contract_id}/termination-notice",
            payload,
            headers,
        )

    def get_grape_contract(self, contract_id, headers):
        return self._request(
            "GET", f"{BASE}/grape-contracts/{contract_id}", headers=headers
        )

    def list_grape_contracts(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/grape-contracts", headers=headers, params=params
        )

    def get_settlement_summary(self, contract_id, headers):
        return self._request(
            "GET",
            f"{BASE}/grape-contracts/{contract_id}/settlement-summary",
            headers=headers,
        )

    # --- Contract-block allocations ------------------------------------------
    def create_allocation(self, payload, headers):
        return self._request(
            "POST", f"{BASE}/contract-block-allocations", payload, headers
        )

    def get_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"{BASE}/contract-block-allocations/{allocation_id}", headers=headers
        )

    def list_allocations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/contract-block-allocations", headers=headers, params=params
        )

    # --- Crush-pad lanes ------------------------------------------------------
    def create_lane(self, payload, headers):
        return self._request("POST", f"{BASE}/crush-pad-lanes", payload, headers)

    def get_lane(self, lane_id, headers):
        return self._request("GET", f"{BASE}/crush-pad-lanes/{lane_id}", headers=headers)

    def list_lanes(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/crush-pad-lanes", headers=headers, params=params
        )

    # --- Sampling crews -------------------------------------------------------
    def create_sampling_crew(self, payload, headers):
        return self._request("POST", f"{BASE}/sampling-crews", payload, headers)

    def get_sampling_crew(self, crew_id, headers):
        return self._request("GET", f"{BASE}/sampling-crews/{crew_id}", headers=headers)

    def list_sampling_crews(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/sampling-crews", headers=headers, params=params
        )

    # --- Sampling visits ------------------------------------------------------
    def create_sampling_visit(self, payload, headers):
        return self._request("POST", f"{BASE}/sampling-visits", payload, headers)

    def record_sampling_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/sampling-visits/{visit_id}/record", payload, headers
        )

    def get_sampling_visit(self, visit_id, headers):
        return self._request("GET", f"{BASE}/sampling-visits/{visit_id}", headers=headers)

    def list_sampling_visits(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/sampling-visits", headers=headers, params=params
        )

    # --- Pick calls -----------------------------------------------------------
    def create_pick_call(self, payload, headers):
        return self._request("POST", f"{BASE}/pick-calls", payload, headers)

    def acknowledge_pick_call(self, pick_call_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/pick-calls/{pick_call_id}/acknowledge", payload or {}, headers
        )

    def revise_pick_call(self, pick_call_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/pick-calls/{pick_call_id}/revise", payload, headers
        )

    def get_pick_call(self, pick_call_id, headers):
        return self._request("GET", f"{BASE}/pick-calls/{pick_call_id}", headers=headers)

    def list_pick_calls(self, headers, params=None):
        return self._request("GET", f"{BASE}/pick-calls", headers=headers, params=params)

    # --- Delivery appointments ------------------------------------------------
    def create_delivery_appointment(self, payload, headers):
        return self._request("POST", f"{BASE}/delivery-appointments", payload, headers)

    def cancel_delivery_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/delivery-appointments/{appointment_id}/cancel",
            payload or {},
            headers,
        )

    def get_delivery_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"{BASE}/delivery-appointments/{appointment_id}", headers=headers
        )

    def list_delivery_appointments(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/delivery-appointments", headers=headers, params=params
        )

    # --- Weigh tags -----------------------------------------------------------
    def create_weigh_tag(self, payload, headers):
        return self._request("POST", f"{BASE}/weigh-tags", payload, headers)

    def tare_weigh_tag(self, tag_id, payload, headers):
        return self._request("POST", f"{BASE}/weigh-tags/{tag_id}/tare", payload, headers)

    def create_grading(self, tag_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/weigh-tags/{tag_id}/grades", payload, headers
        )

    def create_grade_dispute(self, tag_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/weigh-tags/{tag_id}/grade-disputes", payload or {}, headers
        )

    def get_weigh_tag(self, tag_id, headers):
        return self._request("GET", f"{BASE}/weigh-tags/{tag_id}", headers=headers)

    def list_weigh_tags(self, headers, params=None):
        return self._request("GET", f"{BASE}/weigh-tags", headers=headers, params=params)

    # --- Quality gradings -----------------------------------------------------
    def get_quality_grade(self, grade_id, headers):
        return self._request("GET", f"{BASE}/quality-grades/{grade_id}", headers=headers)

    def list_quality_grades(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/quality-grades", headers=headers, params=params
        )

    # --- Settlement lines -----------------------------------------------------
    def get_settlement_line(self, line_id, headers):
        return self._request("GET", f"{BASE}/settlement-lines/{line_id}", headers=headers)

    def list_settlement_lines(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/settlement-lines", headers=headers, params=params
        )

    # --- Payment installments -------------------------------------------------
    def create_payment(self, installment_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/payment-installments/{installment_id}/payments",
            payload,
            headers,
        )

    def get_installment(self, installment_id, headers):
        return self._request(
            "GET", f"{BASE}/payment-installments/{installment_id}", headers=headers
        )

    def list_installments(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/payment-installments", headers=headers, params=params
        )

    # --- The logical harvest clock -------------------------------------------
    def get_clock(self, headers):
        return self._request("GET", "/_clock/current_utc", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
