"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Tour ---
    def create_tour(self, payload, headers):
        return self._request("POST", "/tours", payload, headers)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/tours/{tour_id}", headers=headers)

    def list_tours(self, headers, params=None):
        return self._request("GET", "/tours", headers=headers, params=params)

    def transition_tour(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/transition", payload, headers)

    def get_financial_summary(self, tour_id, headers):
        return self._request("GET", f"/tours/{tour_id}/financial-summary", headers=headers)

    # --- Venue ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # --- Crate ---
    def create_crate(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/crates", payload, headers)

    def list_crates(self, tour_id, headers, params=None):
        return self._request("GET", f"/tours/{tour_id}/crates", headers=headers, params=params)

    def get_crate(self, tour_id, crate_id, headers):
        return self._request("GET", f"/tours/{tour_id}/crates/{crate_id}", headers=headers)

    # --- TourStop ---
    def create_stop(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/stops", payload, headers)

    def list_stops(self, tour_id, headers, params=None):
        return self._request("GET", f"/tours/{tour_id}/stops", headers=headers, params=params)

    def get_stop(self, tour_id, stop_id, headers):
        return self._request("GET", f"/tours/{tour_id}/stops/{stop_id}", headers=headers)

    def update_stop(self, tour_id, stop_id, payload, headers):
        return self._request("PATCH", f"/tours/{tour_id}/stops/{stop_id}", payload, headers)

    def transition_stop(self, tour_id, stop_id, payload, headers):
        return self._request(
            "POST", f"/tours/{tour_id}/stops/{stop_id}/transition", payload, headers
        )

    def assign_supervisor(self, tour_id, stop_id, payload, headers):
        return self._request(
            "POST", f"/tours/{tour_id}/stops/{stop_id}/assign-supervisor", payload, headers
        )

    # --- ParticipationContract ---
    def create_contract(self, tour_id, stop_id, payload, headers):
        return self._request(
            "POST", f"/tours/{tour_id}/stops/{stop_id}/contract", payload, headers
        )

    def get_contract(self, tour_id, stop_id, headers):
        return self._request(
            "GET", f"/tours/{tour_id}/stops/{stop_id}/contract", headers=headers
        )

    def transition_contract(self, tour_id, stop_id, payload, headers):
        return self._request(
            "POST", f"/tours/{tour_id}/stops/{stop_id}/contract/transition", payload, headers
        )

    # --- MarketingKit ---
    def create_marketing_kit(self, tour_id, stop_id, payload, headers):
        return self._request(
            "POST", f"/tours/{tour_id}/stops/{stop_id}/marketing-kit", payload, headers
        )

    def get_marketing_kit(self, tour_id, stop_id, headers):
        return self._request(
            "GET", f"/tours/{tour_id}/stops/{stop_id}/marketing-kit", headers=headers
        )

    def send_press_release(self, tour_id, stop_id, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/stops/{stop_id}/marketing-kit/send-press-release",
            None,
            headers,
        )

    def transition_marketing_kit(self, tour_id, stop_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/stops/{stop_id}/marketing-kit/transition",
            payload,
            headers,
        )

    # --- InsuranceCertificate ---
    def create_certificate(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/certificates", payload, headers)

    def list_certificates(self, tour_id, headers, params=None):
        return self._request(
            "GET", f"/tours/{tour_id}/certificates", headers=headers, params=params
        )

    def get_certificate(self, tour_id, cert_id, headers):
        return self._request(
            "GET", f"/tours/{tour_id}/certificates/{cert_id}", headers=headers
        )

    # --- Shipment ---
    def create_shipment(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/shipments", payload, headers)

    def list_shipments(self, tour_id, headers, params=None):
        return self._request(
            "GET", f"/tours/{tour_id}/shipments", headers=headers, params=params
        )

    def get_shipment(self, tour_id, shipment_id, headers):
        return self._request(
            "GET", f"/tours/{tour_id}/shipments/{shipment_id}", headers=headers
        )

    def transition_shipment(self, tour_id, shipment_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/shipments/{shipment_id}/transition",
            payload,
            headers,
        )

    # --- ConditionReport ---
    def create_report(self, tour_id, shipment_id, payload, headers):
        return self._request(
            "POST", f"/tours/{tour_id}/shipments/{shipment_id}/reports", payload, headers
        )

    def list_reports(self, tour_id, shipment_id, headers, params=None):
        return self._request(
            "GET",
            f"/tours/{tour_id}/shipments/{shipment_id}/reports",
            headers=headers,
            params=params,
        )

    def transition_report(self, tour_id, shipment_id, report_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/shipments/{shipment_id}/reports/{report_id}/transition",
            payload,
            headers,
        )

    # --- DamageClaim ---
    def create_claim(self, tour_id, shipment_id, payload, headers):
        return self._request(
            "POST", f"/tours/{tour_id}/shipments/{shipment_id}/claims", payload, headers
        )

    def list_claims(self, tour_id, shipment_id, headers, params=None):
        return self._request(
            "GET",
            f"/tours/{tour_id}/shipments/{shipment_id}/claims",
            headers=headers,
            params=params,
        )

    def transition_claim(self, tour_id, shipment_id, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/shipments/{shipment_id}/claims/{claim_id}/transition",
            payload,
            headers,
        )

    # --- Flat read aliases ---
    def flat_get_stop(self, stop_id, headers):
        return self._request("GET", f"/tours/stops/{stop_id}", headers=headers)

    def flat_list_stops(self, headers, params=None):
        return self._request("GET", "/tours/stops", headers=headers, params=params)

    def flat_get_contract(self, contract_id, headers):
        return self._request("GET", f"/tours/contracts/{contract_id}", headers=headers)

    def flat_list_contracts(self, headers, params=None):
        return self._request("GET", "/tours/contracts", headers=headers, params=params)

    def flat_get_crate(self, crate_id, headers):
        return self._request("GET", f"/tours/crates/{crate_id}", headers=headers)

    def flat_list_crates(self, headers, params=None):
        return self._request("GET", "/tours/crates", headers=headers, params=params)

    def flat_get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/tours/shipments/{shipment_id}", headers=headers)

    def flat_list_shipments(self, headers, params=None):
        return self._request("GET", "/tours/shipments", headers=headers, params=params)

    def flat_get_report(self, report_id, headers):
        return self._request("GET", f"/tours/reports/{report_id}", headers=headers)

    def flat_list_reports(self, headers, params=None):
        return self._request("GET", "/tours/reports", headers=headers, params=params)

    def flat_get_claim(self, claim_id, headers):
        return self._request("GET", f"/tours/claims/{claim_id}", headers=headers)

    def flat_list_claims(self, headers, params=None):
        return self._request("GET", "/tours/claims", headers=headers, params=params)

    def flat_get_marketing_kit(self, kit_id, headers):
        return self._request("GET", f"/tours/marketing-kits/{kit_id}", headers=headers)

    def flat_list_marketing_kits(self, headers, params=None):
        return self._request("GET", "/tours/marketing-kits", headers=headers, params=params)

    def flat_get_certificate(self, cert_id, headers):
        return self._request("GET", f"/tours/certificates/{cert_id}", headers=headers)

    def flat_list_certificates(self, headers, params=None):
        return self._request("GET", "/tours/certificates", headers=headers, params=params)


api_client = ApiClient()
