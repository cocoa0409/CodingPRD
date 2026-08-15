"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer accounts ---
    def create_customer_account(self, payload, headers):
        return self._request("POST", "/customer-accounts", payload, headers)

    def get_customer_account(self, customer_id, headers):
        return self._request("GET", f"/customer-accounts/{customer_id}", headers=headers)

    def reinstate_customer_account(self, customer_id, headers):
        return self._request("POST", f"/customer-accounts/{customer_id}/reinstate", {}, headers)

    # --- Equipment classes ---
    def create_equipment_class(self, payload, headers):
        return self._request("POST", "/equipment-classes", payload, headers)

    def list_equipment_classes(self, headers, params=None):
        return self._request("GET", "/equipment-classes", headers=headers, params=params)

    # --- Equipment units ---
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/equipment-units", payload, headers)

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", "/equipment-units", headers=headers, params=params)

    def get_equipment_unit(self, unit_id, headers):
        return self._request("GET", f"/equipment-units/{unit_id}", headers=headers)

    def recover_equipment_unit(self, unit_id, headers):
        return self._request("POST", f"/equipment-units/{unit_id}/recover", {}, headers)

    # --- Rental contracts ---
    def create_rental_contract(self, payload, headers):
        return self._request("POST", "/rental-contracts", payload, headers)

    def list_rental_contracts(self, headers, params=None):
        return self._request("GET", "/rental-contracts", headers=headers, params=params)

    def get_rental_contract(self, contract_id, headers):
        return self._request("GET", f"/rental-contracts/{contract_id}", headers=headers)

    def activate_rental_contract(self, contract_id, headers):
        return self._request("POST", f"/rental-contracts/{contract_id}/activate", {}, headers)

    def close_rental_contract(self, contract_id, headers):
        return self._request("POST", f"/rental-contracts/{contract_id}/close", {}, headers)

    def get_contract_invoice(self, contract_id, headers):
        return self._request("GET", f"/rental-contracts/{contract_id}/invoice", headers=headers)

    # --- Rental lines ---
    def create_rental_line(self, payload, headers):
        return self._request("POST", "/rental-lines", payload, headers)

    def list_rental_lines(self, headers, params=None):
        return self._request("GET", "/rental-lines", headers=headers, params=params)

    def get_rental_line(self, line_id, headers):
        return self._request("GET", f"/rental-lines/{line_id}", headers=headers)

    def off_rent_line(self, line_id, headers):
        return self._request("POST", f"/rental-lines/{line_id}/off-rent", {}, headers)

    def re_rent_line(self, line_id, headers):
        return self._request("POST", f"/rental-lines/{line_id}/re-rent", {}, headers)

    # --- Delivery trips ---
    def create_delivery_trip(self, payload, headers):
        return self._request("POST", "/delivery-trips", payload, headers)

    def list_delivery_trips(self, headers, params=None):
        return self._request("GET", "/delivery-trips", headers=headers, params=params)

    def get_delivery_trip(self, trip_id, headers):
        return self._request("GET", f"/delivery-trips/{trip_id}", headers=headers)

    def start_delivery_trip(self, trip_id, headers):
        return self._request("POST", f"/delivery-trips/{trip_id}/start", {}, headers)

    def complete_delivery_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/delivery-trips/{trip_id}/complete", payload, headers)

    def fail_delivery_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/delivery-trips/{trip_id}/fail", payload, headers)

    def reschedule_delivery_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/delivery-trips/{trip_id}/reschedule", payload, headers)

    # --- Inspection records ---
    def create_inspection_record(self, payload, headers):
        return self._request("POST", "/inspection-records", payload, headers)

    def list_inspection_records(self, headers, params=None):
        return self._request("GET", "/inspection-records", headers=headers, params=params)

    def get_inspection_record(self, record_id, headers):
        return self._request("GET", f"/inspection-records/{record_id}", headers=headers)

    def certify_inspection_record(self, record_id, headers):
        return self._request("POST", f"/inspection-records/{record_id}/certify", {}, headers)

    def reject_inspection_record(self, record_id, headers):
        return self._request("POST", f"/inspection-records/{record_id}/reject", {}, headers)

    # --- Training records ---
    def create_training_record(self, payload, headers):
        return self._request("POST", "/training-records", payload, headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/training-records", headers=headers, params=params)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/training-records/{record_id}", headers=headers)

    # --- Damage claims ---
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/damage-claims", payload, headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/damage-claims", headers=headers, params=params)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/damage-claims/{claim_id}", headers=headers)

    def assess_damage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/assess", payload, headers)

    def charge_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/charge", {}, headers)

    def dispute_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/dispute", {}, headers)

    def resolve_damage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/resolve", payload, headers)

    # --- Logical clock (test-driving admin capability, PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
# The harness restarts the API server before every test (per-test-server
# isolation), which kills every keep-alive connection the previous server
# instance held. Sending `Connection: close` makes urllib3 open a fresh TCP
# connection per request instead of pooling one that can go stale mid-test
# when several suite rounds run concurrently on the same host.
api_client.session.headers["Connection"] = "close"
