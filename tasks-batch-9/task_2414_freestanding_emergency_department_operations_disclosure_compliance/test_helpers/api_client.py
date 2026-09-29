"""API client: one method per route in the PRD endpoint table.

Child collections are addressed under their parent (``/facilities/{id}/...``,
``/encounters/{id}/...``, ``/claims/{id}/...``) while single-resource reads and
action endpoints are addressed at the root of their own collection, exactly as
the endpoint table lays them out.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ----------------------------------------------------- logical clock ----
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ---------------------------------------------------------- facility ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def update_facility(self, facility_id, payload, headers):
        return self._request("PATCH", f"/facilities/{facility_id}", payload, headers)

    def create_signage_attestation(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/signage-attestations", payload, headers
        )

    def get_coverage_summary(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/coverage-summary",
            headers=headers,
            params=params,
        )

    def list_compliance_ledger_entries(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/compliance-ledger-entries",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------ disclosure template ----
    def create_disclosure_template(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/disclosure-templates", payload, headers
        )

    def list_disclosure_templates(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/disclosure-templates",
            headers=headers,
            params=params,
        )

    def get_disclosure_template(self, template_id, headers):
        return self._request(
            "GET", f"/disclosure-templates/{template_id}", headers=headers
        )

    def publish_disclosure_template(self, template_id, payload, headers):
        return self._request(
            "POST", f"/disclosure-templates/{template_id}/publish", payload, headers
        )

    # ----------------------------------------------------- payer contract ----
    def create_payer_contract(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/payer-contracts", payload, headers
        )

    def list_payer_contracts(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/payer-contracts",
            headers=headers,
            params=params,
        )

    def get_payer_contract(self, contract_id, headers):
        return self._request("GET", f"/payer-contracts/{contract_id}", headers=headers)

    # ---------------------------------------------------- physician shift ----
    def create_physician_shift(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/physician-shifts", payload, headers
        )

    def list_physician_shifts(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/physician-shifts",
            headers=headers,
            params=params,
        )

    def get_physician_shift(self, shift_id, headers):
        return self._request("GET", f"/physician-shifts/{shift_id}", headers=headers)

    # ----------------------------------------------------- volume forecast ---
    def create_volume_forecast(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/volume-forecasts", payload, headers
        )

    def list_volume_forecasts(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/volume-forecasts",
            headers=headers,
            params=params,
        )

    def get_volume_forecast(self, forecast_id, headers):
        return self._request("GET", f"/volume-forecasts/{forecast_id}", headers=headers)

    # -------------------------------------------------- transfer agreement ---
    def create_transfer_agreement(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/transfer-agreements", payload, headers
        )

    def list_transfer_agreements(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/transfer-agreements",
            headers=headers,
            params=params,
        )

    def get_transfer_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/transfer-agreements/{agreement_id}", headers=headers
        )

    # ------------------------------------------------------- ambulance MOU ---
    def create_ambulance_mou(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/ambulance-mous", payload, headers
        )

    def list_ambulance_mous(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/ambulance-mous",
            headers=headers,
            params=params,
        )

    def get_ambulance_mou(self, mou_id, headers):
        return self._request("GET", f"/ambulance-mous/{mou_id}", headers=headers)

    # ---------------------------------------------------------- encounter ----
    def register_encounter(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/encounters", payload, headers
        )

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/encounters/{encounter_id}", headers=headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/encounters", headers=headers, params=params)

    def record_disclosure_decision(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/disclosure-decision", payload, headers
        )

    def begin_mse(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/begin-mse", payload, headers
        )

    def complete_mse(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/complete-mse", payload, headers
        )

    def admit_to_observation(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/observation", payload, headers
        )

    def discharge_encounter(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/discharge", payload, headers
        )

    # ----------------------------------------------------- ancillary order ---
    def create_ancillary_order(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/ancillary-orders", payload, headers
        )

    def list_ancillary_orders(self, encounter_id, headers, params=None):
        return self._request(
            "GET",
            f"/encounters/{encounter_id}/ancillary-orders",
            headers=headers,
            params=params,
        )

    def get_ancillary_order(self, order_id, headers):
        return self._request("GET", f"/ancillary-orders/{order_id}", headers=headers)

    def resolve_ancillary_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/ancillary-orders/{order_id}/resolve", payload, headers
        )

    # ------------------------------------------------------ transfer order ---
    def create_transfer_order(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/transfer-orders", payload, headers
        )

    def list_transfer_orders(self, headers, params=None):
        return self._request("GET", "/transfer-orders", headers=headers, params=params)

    def get_transfer_order(self, order_id, headers):
        return self._request("GET", f"/transfer-orders/{order_id}", headers=headers)

    def accept_transfer_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/transfer-orders/{order_id}/accept", payload, headers
        )

    def decline_transfer_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/transfer-orders/{order_id}/decline", payload, headers
        )

    def complete_transfer_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/transfer-orders/{order_id}/complete", payload, headers
        )

    # -------------------------------------------------------------- claim ----
    def create_claim(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/claims", payload, headers
        )

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/adjudicate", payload, headers
        )

    # ------------------------------------------------------- dispute case ----
    def create_dispute_case(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/dispute-cases", payload, headers
        )

    def list_dispute_cases(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/claims/{claim_id}/dispute-cases", headers=headers, params=params
        )

    def get_dispute_case(self, case_id, headers):
        return self._request("GET", f"/dispute-cases/{case_id}", headers=headers)

    def submit_offer(self, case_id, payload, headers):
        return self._request(
            "POST", f"/dispute-cases/{case_id}/offers", payload, headers
        )

    def initiate_idr(self, case_id, payload, headers):
        return self._request(
            "POST", f"/dispute-cases/{case_id}/initiate-idr", payload, headers
        )

    def award_dispute(self, case_id, payload, headers):
        return self._request(
            "POST", f"/dispute-cases/{case_id}/award", payload, headers
        )

    def withdraw_award(self, case_id, payload, headers):
        return self._request(
            "POST", f"/dispute-cases/{case_id}/withdraw", payload, headers
        )


api_client = ApiClient()
