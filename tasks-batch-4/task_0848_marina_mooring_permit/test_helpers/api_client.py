"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Marina ----
    def create_marina(self, payload, headers):
        return self._request("POST", "/marina/marinas", payload, headers)

    def get_marina(self, marina_id, headers):
        return self._request("GET", f"/marina/marinas/{marina_id}", headers=headers)

    def run_maintenance(self, marina_id, headers):
        return self._request(
            "POST", f"/marina/marinas/{marina_id}/run-maintenance", {}, headers
        )

    # ---- Berth ----
    def create_berth(self, payload, headers):
        return self._request("POST", "/marina/berths", payload, headers)

    def get_berth(self, berth_id, headers):
        return self._request("GET", f"/marina/berths/{berth_id}", headers=headers)

    def list_berths(self, headers, params=None):
        return self._request("GET", "/marina/berths", headers=headers, params=params)

    # ---- Boater ----
    def create_boater(self, payload, headers):
        return self._request("POST", "/marina/boaters", payload, headers)

    def get_boater(self, boater_id, headers):
        return self._request("GET", f"/marina/boaters/{boater_id}", headers=headers)

    # ---- Vessel ----
    def create_vessel(self, payload, headers):
        return self._request("POST", "/marina/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/marina/vessels/{vessel_id}", headers=headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/marina/vessels", headers=headers, params=params)

    def create_pumpout_record(self, vessel_id, payload, headers):
        return self._request(
            "POST", f"/marina/vessels/{vessel_id}/pump-out-records", payload, headers
        )

    def list_pumpout_records(self, vessel_id, headers, params=None):
        return self._request(
            "GET", f"/marina/vessels/{vessel_id}/pump-out-records",
            headers=headers, params=params,
        )

    # ---- Permit ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/marina/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/marina/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/marina/permits", headers=headers, params=params)

    def cancel_permit(self, permit_id, headers):
        return self._request("POST", f"/marina/permits/{permit_id}/cancel", {}, headers)

    def revoke_permit(self, permit_id, headers, payload=None):
        return self._request(
            "POST", f"/marina/permits/{permit_id}/revoke", payload or {}, headers
        )

    def transfer_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/marina/permits/{permit_id}/transfer", payload, headers
        )

    def reassign_berth(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/marina/permits/{permit_id}/reassign-berth", payload, headers
        )

    # ---- Lottery Round ----
    def create_lottery_round(self, payload, headers):
        return self._request("POST", "/marina/lottery-rounds", payload, headers)

    def get_lottery_round(self, round_id, headers):
        return self._request(
            "GET", f"/marina/lottery-rounds/{round_id}", headers=headers
        )

    def list_lottery_rounds(self, headers, params=None):
        return self._request(
            "GET", "/marina/lottery-rounds", headers=headers, params=params
        )

    def draw_round(self, round_id, headers):
        return self._request(
            "POST", f"/marina/lottery-rounds/{round_id}/draw", {}, headers
        )

    # ---- Lottery Entry ----
    def create_lottery_entry(self, payload, headers):
        return self._request("POST", "/marina/lottery-entries", payload, headers)

    def get_lottery_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/marina/lottery-entries/{entry_id}", headers=headers
        )

    def list_lottery_entries(self, headers, params=None):
        return self._request(
            "GET", "/marina/lottery-entries", headers=headers, params=params
        )

    def claim_entry(self, entry_id, headers, payload=None):
        return self._request(
            "POST", f"/marina/lottery-entries/{entry_id}/claim", payload or {}, headers
        )

    # ---- Derelict Report ----
    def create_derelict_report(self, payload, headers):
        return self._request("POST", "/marina/derelict-reports", payload, headers)

    def get_derelict_report(self, report_id, headers):
        return self._request(
            "GET", f"/marina/derelict-reports/{report_id}", headers=headers
        )

    def list_derelict_reports(self, headers, params=None):
        return self._request(
            "GET", "/marina/derelict-reports", headers=headers, params=params
        )

    def serve_notice(self, report_id, headers):
        return self._request(
            "POST", f"/marina/derelict-reports/{report_id}/serve-notice", {}, headers
        )

    def close_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/marina/derelict-reports/{report_id}/close", payload, headers
        )

    # ---- Ramp Pass ----
    def create_ramp_pass(self, payload, headers):
        return self._request("POST", "/marina/ramp-passes", payload, headers)

    def get_ramp_pass(self, pass_id, headers):
        return self._request("GET", f"/marina/ramp-passes/{pass_id}", headers=headers)

    def list_ramp_passes(self, headers, params=None):
        return self._request(
            "GET", "/marina/ramp-passes", headers=headers, params=params
        )

    def revoke_ramp_pass(self, pass_id, headers):
        return self._request(
            "POST", f"/marina/ramp-passes/{pass_id}/revoke", {}, headers
        )

    # ---- Invoice / Billing ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/marina/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/marina/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/marina/invoices/{invoice_id}/pay", payload, headers
        )

    def waive_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/marina/invoices/{invoice_id}/waive", {}, headers
        )


api_client = ApiClient()
