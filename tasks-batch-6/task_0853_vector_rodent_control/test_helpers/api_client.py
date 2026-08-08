"""API client: one method per endpoint published by the program API."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/vector-control"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Vector & Rodent Control Program API."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---------------------------------------------------------------- zones
    def create_zone(self, payload, headers):
        return self._request("POST", f"{PREFIX}/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"{PREFIX}/zones/{zone_id}", headers=headers)

    def get_surveillance_summary(self, zone_id, headers):
        return self._request(
            "GET", f"{PREFIX}/zones/{zone_id}/surveillance-summary", headers=headers
        )

    # ------------------------------------------------------- property owners
    def create_property_owner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/property-owners", payload, headers)

    def get_property_owner(self, owner_id, headers):
        return self._request(
            "GET", f"{PREFIX}/property-owners/{owner_id}", headers=headers
        )

    # ----------------------------------------------------------- properties
    def create_property(self, payload, headers):
        return self._request("POST", f"{PREFIX}/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request(
            "GET", f"{PREFIX}/properties/{property_id}", headers=headers
        )

    def list_properties(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/properties", headers=headers, params=params
        )

    # ------------------------------------------------------------- officers
    def create_officer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/officers", payload, headers)

    # ----------------------------------------------------------- complaints
    def create_complaint(self, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request(
            "GET", f"{PREFIX}/complaints/{complaint_id}", headers=headers
        )

    def list_complaints(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/complaints", headers=headers, params=params
        )

    def triage_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/triage", payload, headers
        )

    def close_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/close", payload, headers
        )

    # ---------------------------------------------------------- inspections
    def create_inspection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inspections", headers=headers, params=params
        )

    def start_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/start", {}, headers
        )

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/complete", payload, headers
        )

    def create_assessment(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/assessments",
            payload, headers,
        )

    def list_assessments(self, inspection_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inspections/{inspection_id}/assessments",
            headers=headers, params=params,
        )

    # ----------------------------------------------------- abatement orders
    def create_abatement_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/abatement-orders", payload, headers)

    def get_abatement_order(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/abatement-orders/{order_id}", headers=headers
        )

    def list_abatement_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/abatement-orders", headers=headers, params=params
        )

    def create_notice(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/abatement-orders/{order_id}/notices", payload, headers
        )

    def list_notices(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/abatement-orders/{order_id}/notices",
            headers=headers, params=params,
        )

    def record_service_result(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/notices/{notice_id}/service-result", payload, headers
        )

    def extend_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/abatement-orders/{order_id}/extend", payload, headers
        )

    def city_abate_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/abatement-orders/{order_id}/city-abate", payload, headers
        )

    # ------------------------------------------------------- bait stations
    def create_bait_station(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bait-stations", payload, headers)

    def get_bait_station(self, station_id, headers):
        return self._request(
            "GET", f"{PREFIX}/bait-stations/{station_id}", headers=headers
        )

    def list_bait_stations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/bait-stations", headers=headers, params=params
        )

    def create_reading(self, station_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bait-stations/{station_id}/readings", payload, headers
        )

    def list_readings(self, station_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/bait-stations/{station_id}/readings",
            headers=headers, params=params,
        )

    # ------------------------------------------------ cost-recovery invoices
    def create_invoice(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cost-recovery-invoices", payload, headers
        )

    def get_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"{PREFIX}/cost-recovery-invoices/{invoice_id}", headers=headers
        )

    def list_invoices(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cost-recovery-invoices", headers=headers, params=params
        )

    def approve_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cost-recovery-invoices/{invoice_id}/approve",
            payload, headers,
        )

    def create_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cost-recovery-invoices/{invoice_id}/payments",
            payload, headers,
        )

    def file_lien(self, invoice_id, headers):
        return self._request(
            "POST", f"{PREFIX}/cost-recovery-invoices/{invoice_id}/lien", {}, headers
        )

    def void_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cost-recovery-invoices/{invoice_id}/void",
            payload, headers,
        )

    # -------------------------------------------------------------- reports
    def get_program_summary(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/reports/program-summary", headers=headers, params=params
        )

    # --------------------------------------------------------- raw fallback
    def raw_get(self, path, headers=None, params=None):
        """Escape hatch for header-less calls; path is relative to the API prefix."""
        return self._request("GET", f"{PREFIX}{path}", headers=headers, params=params)


api_client = ApiClient()
