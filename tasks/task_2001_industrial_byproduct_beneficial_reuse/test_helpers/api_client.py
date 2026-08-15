"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Generators ---
    def create_generator(self, payload, headers):
        return self._request("POST", "/api/generators", payload, headers)

    def list_generators(self, headers, params=None):
        return self._request("GET", "/api/generators", headers=headers, params=params)

    def get_generator(self, generator_id, headers):
        return self._request("GET", f"/api/generators/{generator_id}", headers=headers)

    # --- Offtakers ---
    def create_offtaker(self, payload, headers):
        return self._request("POST", "/api/offtakers", payload, headers)

    def list_offtakers(self, headers, params=None):
        return self._request("GET", "/api/offtakers", headers=headers, params=params)

    # --- Byproduct streams ---
    def create_stream(self, payload, headers):
        return self._request("POST", "/api/streams", payload, headers)

    def list_streams(self, headers, params=None):
        return self._request("GET", "/api/streams", headers=headers, params=params)

    def get_stream(self, stream_id, headers):
        return self._request("GET", f"/api/streams/{stream_id}", headers=headers)

    # --- Characterization profiles ---
    def create_characterization(self, stream_id, payload, headers):
        return self._request(
            "POST", f"/api/streams/{stream_id}/characterizations", payload, headers
        )

    def list_characterizations(self, stream_id, headers, params=None):
        return self._request(
            "GET", f"/api/streams/{stream_id}/characterizations", headers=headers, params=params
        )

    def verify_characterization(self, characterization_id, headers):
        return self._request(
            "POST", f"/api/characterizations/{characterization_id}/verify", {}, headers
        )

    def reject_characterization(self, characterization_id, payload, headers):
        return self._request(
            "POST", f"/api/characterizations/{characterization_id}/reject", payload, headers
        )

    # --- Reuse-eligibility determinations ---
    def create_eligibility_determination(self, stream_id, payload, headers):
        return self._request(
            "POST", f"/api/streams/{stream_id}/eligibility-determinations", payload, headers
        )

    def list_eligibility_determinations(self, stream_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/streams/{stream_id}/eligibility-determinations",
            headers=headers,
            params=params,
        )

    def submit_eligibility(self, determination_id, headers):
        return self._request(
            "POST", f"/api/eligibility-determinations/{determination_id}/submit", {}, headers
        )

    def revise_eligibility(self, determination_id, headers):
        return self._request(
            "POST", f"/api/eligibility-determinations/{determination_id}/revise", {}, headers
        )

    def approve_eligibility(self, determination_id, headers):
        return self._request(
            "POST", f"/api/eligibility-determinations/{determination_id}/approve", {}, headers
        )

    def deny_eligibility(self, determination_id, payload, headers):
        return self._request(
            "POST", f"/api/eligibility-determinations/{determination_id}/deny", payload, headers
        )

    def suspend_eligibility(self, determination_id, headers):
        return self._request(
            "POST", f"/api/eligibility-determinations/{determination_id}/suspend", {}, headers
        )

    def reinstate_eligibility(self, determination_id, headers):
        return self._request(
            "POST", f"/api/eligibility-determinations/{determination_id}/reinstate", {}, headers
        )

    # --- State permits ---
    def create_state_permit(self, payload, headers):
        return self._request("POST", "/api/state-permits", payload, headers)

    def list_state_permits(self, headers, params=None):
        return self._request("GET", "/api/state-permits", headers=headers, params=params)

    def activate_state_permit(self, permit_id, headers):
        return self._request("POST", f"/api/state-permits/{permit_id}/activate", {}, headers)

    def revoke_state_permit(self, permit_id, headers):
        return self._request("POST", f"/api/state-permits/{permit_id}/revoke", {}, headers)

    # --- Supply agreements ---
    def create_supply_agreement(self, payload, headers):
        return self._request("POST", "/api/supply-agreements", payload, headers)

    def list_supply_agreements(self, headers, params=None):
        return self._request("GET", "/api/supply-agreements", headers=headers, params=params)

    def get_supply_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/supply-agreements/{agreement_id}", headers=headers)

    def activate_supply_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/api/supply-agreements/{agreement_id}/activate", {}, headers
        )

    def suspend_supply_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/api/supply-agreements/{agreement_id}/suspend", {}, headers
        )

    def resume_supply_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/api/supply-agreements/{agreement_id}/resume", {}, headers
        )

    def terminate_supply_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/api/supply-agreements/{agreement_id}/terminate", {}, headers
        )

    # --- Offtake commitments ---
    def create_offtake_commitment(self, payload, headers):
        return self._request("POST", "/api/offtake-commitments", payload, headers)

    def list_offtake_commitments(self, headers, params=None):
        return self._request("GET", "/api/offtake-commitments", headers=headers, params=params)

    def get_offtake_commitment(self, commitment_id, headers):
        return self._request("GET", f"/api/offtake-commitments/{commitment_id}", headers=headers)

    def activate_offtake_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"/api/offtake-commitments/{commitment_id}/activate", {}, headers
        )

    def resume_offtake_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"/api/offtake-commitments/{commitment_id}/resume", {}, headers
        )

    def terminate_offtake_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"/api/offtake-commitments/{commitment_id}/terminate", {}, headers
        )

    # --- Shipments ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/api/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/api/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/api/shipments/{shipment_id}", headers=headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/dispatch", {}, headers)

    def deliver_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/deliver", payload, headers)

    def accept_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/accept", {}, headers)

    def reject_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/reject", payload, headers)

    def recondition_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/recondition", {}, headers)

    def redeliver_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/redeliver", payload, headers)

    def dispose_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/dispose", {}, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/cancel", {}, headers)

    def void_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/void", payload, headers)

    def list_shipment_credit_entries(self, shipment_id, headers, params=None):
        return self._request(
            "GET", f"/api/shipments/{shipment_id}/credit-entries", headers=headers, params=params
        )

    # --- Storage ---
    def create_storage_facility(self, payload, headers):
        return self._request("POST", "/api/storage-facilities", payload, headers)

    def get_storage_facility(self, facility_id, headers):
        return self._request("GET", f"/api/storage-facilities/{facility_id}", headers=headers)

    def create_storage_reservation(self, payload, headers):
        return self._request("POST", "/api/storage-reservations", payload, headers)

    def list_storage_reservations(self, headers, params=None):
        return self._request("GET", "/api/storage-reservations", headers=headers, params=params)

    def get_storage_reservation(self, reservation_id, headers):
        return self._request("GET", f"/api/storage-reservations/{reservation_id}", headers=headers)

    def check_in_storage_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/api/storage-reservations/{reservation_id}/check-in", {}, headers
        )

    def release_storage_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/api/storage-reservations/{reservation_id}/release", {}, headers
        )

    def cancel_storage_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/api/storage-reservations/{reservation_id}/cancel", {}, headers
        )

    # --- Market price index ---
    def create_price_index_entry(self, payload, headers):
        return self._request("POST", "/api/price-index-entries", payload, headers)

    def list_price_index_entries(self, headers, params=None):
        return self._request("GET", "/api/price-index-entries", headers=headers, params=params)

    # --- Credit reporting ---
    def list_generator_credit_entries(self, generator_id, headers, params=None):
        return self._request(
            "GET", f"/api/generators/{generator_id}/credit-entries", headers=headers, params=params
        )

    def get_credit_summary(self, generator_id, headers, params=None):
        return self._request(
            "GET", f"/api/generators/{generator_id}/credit-summary", headers=headers, params=params
        )

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
