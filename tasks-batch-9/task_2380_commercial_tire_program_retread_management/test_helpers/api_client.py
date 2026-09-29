"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Commercial Tire Program & Retread Management API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Service locations
    # ------------------------------------------------------------------
    def create_service_location(self, payload, headers):
        return self._request("POST", "/service-locations", payload, headers)

    def update_service_location(self, location_id, payload, headers):
        return self._request(
            "PATCH", f"/service-locations/{location_id}", payload, headers
        )

    def get_service_location(self, location_id, headers):
        return self._request(
            "GET", f"/service-locations/{location_id}", headers=headers
        )

    def list_service_locations(self, headers, params=None):
        return self._request("GET", "/service-locations", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Fleet accounts
    # ------------------------------------------------------------------
    def create_fleet_account(self, payload, headers):
        return self._request("POST", "/fleet-accounts", payload, headers)

    def get_fleet_account(self, fleet_account_id, headers):
        return self._request(
            "GET", f"/fleet-accounts/{fleet_account_id}", headers=headers
        )

    def list_fleet_accounts(self, headers, params=None):
        return self._request("GET", "/fleet-accounts", headers=headers, params=params)

    def set_fleet_account_status(self, fleet_account_id, payload, headers):
        return self._request(
            "POST", f"/fleet-accounts/{fleet_account_id}/status", payload, headers
        )

    def get_cost_per_mile(self, fleet_account_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet-accounts/{fleet_account_id}/cost-per-mile",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # National agreements
    # ------------------------------------------------------------------
    def create_national_agreement(self, payload, headers):
        return self._request("POST", "/national-agreements", payload, headers)

    def activate_national_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/national-agreements/{agreement_id}/activate", payload, headers
        )

    def terminate_national_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/national-agreements/{agreement_id}/terminate", payload, headers
        )

    def get_national_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/national-agreements/{agreement_id}", headers=headers
        )

    def list_national_agreements(self, headers, params=None):
        return self._request(
            "GET", "/national-agreements", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Tire policies
    # ------------------------------------------------------------------
    def create_tire_policy(self, fleet_account_id, payload, headers):
        return self._request(
            "POST", f"/fleet-accounts/{fleet_account_id}/tire-policies", payload, headers
        )

    def update_tire_policy(self, policy_id, payload, headers):
        return self._request("PATCH", f"/tire-policies/{policy_id}", payload, headers)

    def get_tire_policy(self, policy_id, headers):
        return self._request("GET", f"/tire-policies/{policy_id}", headers=headers)

    def list_tire_policies(self, headers, params=None):
        return self._request("GET", "/tire-policies", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Vehicles
    # ------------------------------------------------------------------
    def create_vehicle(self, fleet_account_id, payload, headers):
        return self._request(
            "POST", f"/fleet-accounts/{fleet_account_id}/vehicles", payload, headers
        )

    def post_odometer(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/odometer", payload, headers
        )

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Casings
    # ------------------------------------------------------------------
    def create_casing(self, payload, headers):
        return self._request("POST", "/casings", payload, headers)

    def collect_casing(self, casing_id, payload, headers):
        return self._request("POST", f"/casings/{casing_id}/collect", payload, headers)

    def inspect_casing(self, casing_id, payload, headers):
        return self._request("POST", f"/casings/{casing_id}/inspect", payload, headers)

    def reject_casing(self, casing_id, payload, headers):
        return self._request("POST", f"/casings/{casing_id}/reject", payload, headers)

    def get_casing(self, casing_id, headers):
        return self._request("GET", f"/casings/{casing_id}", headers=headers)

    def list_casings(self, headers, params=None):
        return self._request("GET", "/casings", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Tire assets and surveys
    # ------------------------------------------------------------------
    def create_tire_asset(self, payload, headers):
        return self._request("POST", "/tire-assets", payload, headers)

    def mount_tire_asset(self, tire_asset_id, payload, headers):
        return self._request(
            "POST", f"/tire-assets/{tire_asset_id}/mount", payload, headers
        )

    def pull_tire_asset(self, tire_asset_id, payload, headers):
        return self._request(
            "POST", f"/tire-assets/{tire_asset_id}/pull", payload, headers
        )

    def create_tire_survey(self, tire_asset_id, payload, headers):
        return self._request(
            "POST", f"/tire-assets/{tire_asset_id}/surveys", payload, headers
        )

    def get_tire_asset(self, tire_asset_id, headers):
        return self._request("GET", f"/tire-assets/{tire_asset_id}", headers=headers)

    def list_tire_assets(self, headers, params=None):
        return self._request("GET", "/tire-assets", headers=headers, params=params)

    def get_tire_survey(self, survey_id, headers):
        return self._request("GET", f"/tire-surveys/{survey_id}", headers=headers)

    def list_tire_surveys(self, headers, params=None):
        return self._request("GET", "/tire-surveys", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Casing credit ledger
    # ------------------------------------------------------------------
    def get_casing_credit_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/casing-credit-entries/{entry_id}", headers=headers
        )

    def list_casing_credit_entries(self, headers, params=None):
        return self._request(
            "GET", "/casing-credit-entries", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Retread lines
    # ------------------------------------------------------------------
    def create_retread_line(self, location_id, payload, headers):
        return self._request(
            "POST", f"/service-locations/{location_id}/retread-lines", payload, headers
        )

    def set_retread_line_status(self, line_id, payload, headers):
        return self._request(
            "POST", f"/retread-lines/{line_id}/status", payload, headers
        )

    def get_retread_line(self, line_id, headers):
        return self._request("GET", f"/retread-lines/{line_id}", headers=headers)

    def list_retread_lines(self, headers, params=None):
        return self._request("GET", "/retread-lines", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Retread jobs
    # ------------------------------------------------------------------
    def create_retread_job(self, payload, headers):
        return self._request("POST", "/retread-jobs", payload, headers)

    def start_retread_job(self, job_id, payload, headers):
        return self._request("POST", f"/retread-jobs/{job_id}/start", payload, headers)

    def complete_retread_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/retread-jobs/{job_id}/complete", payload, headers
        )

    def fail_cure_retread_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/retread-jobs/{job_id}/fail-cure", payload, headers
        )

    def reschedule_retread_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/retread-jobs/{job_id}/reschedule", payload, headers
        )

    def cancel_retread_job(self, job_id, payload, headers):
        return self._request("POST", f"/retread-jobs/{job_id}/cancel", payload, headers)

    def get_retread_job(self, job_id, headers):
        return self._request("GET", f"/retread-jobs/{job_id}", headers=headers)

    def list_retread_jobs(self, headers, params=None):
        return self._request("GET", "/retread-jobs", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Technicians
    # ------------------------------------------------------------------
    def create_technician(self, location_id, payload, headers):
        return self._request(
            "POST", f"/service-locations/{location_id}/technicians", payload, headers
        )

    def set_technician_status(self, technician_id, payload, headers):
        return self._request(
            "POST", f"/technicians/{technician_id}/status", payload, headers
        )

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Road service calls
    # ------------------------------------------------------------------
    def create_road_service_call(self, payload, headers):
        return self._request("POST", "/road-service-calls", payload, headers)

    def dispatch_road_service_call(self, call_id, payload, headers):
        return self._request(
            "POST", f"/road-service-calls/{call_id}/dispatch", payload, headers
        )

    def arrive_road_service_call(self, call_id, payload, headers):
        return self._request(
            "POST", f"/road-service-calls/{call_id}/arrive", payload, headers
        )

    def complete_road_service_call(self, call_id, payload, headers):
        return self._request(
            "POST", f"/road-service-calls/{call_id}/complete", payload, headers
        )

    def cancel_road_service_call(self, call_id, payload, headers):
        return self._request(
            "POST", f"/road-service-calls/{call_id}/cancel", payload, headers
        )

    def get_road_service_call(self, call_id, headers):
        return self._request("GET", f"/road-service-calls/{call_id}", headers=headers)

    def list_road_service_calls(self, headers, params=None):
        return self._request(
            "GET", "/road-service-calls", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Scrap manifests
    # ------------------------------------------------------------------
    def create_scrap_manifest(self, location_id, payload, headers):
        return self._request(
            "POST", f"/service-locations/{location_id}/scrap-manifests", payload, headers
        )

    def add_scrap_manifest_line(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"/scrap-manifests/{manifest_id}/lines", payload, headers
        )

    def sign_scrap_manifest(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"/scrap-manifests/{manifest_id}/sign", payload, headers
        )

    def transport_scrap_manifest(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"/scrap-manifests/{manifest_id}/transport", payload, headers
        )

    def certify_scrap_manifest_destruction(self, manifest_id, payload, headers):
        return self._request(
            "POST",
            f"/scrap-manifests/{manifest_id}/certify-destruction",
            payload,
            headers,
        )

    def void_scrap_manifest(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"/scrap-manifests/{manifest_id}/void", payload, headers
        )

    def get_scrap_manifest(self, manifest_id, headers):
        return self._request("GET", f"/scrap-manifests/{manifest_id}", headers=headers)

    def list_scrap_manifests(self, headers, params=None):
        return self._request("GET", "/scrap-manifests", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Cross-location invoices
    # ------------------------------------------------------------------
    def create_cross_location_invoice(self, payload, headers):
        return self._request("POST", "/cross-location-invoices", payload, headers)

    def submit_cross_location_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/cross-location-invoices/{invoice_id}/submit", payload, headers
        )

    def settle_cross_location_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/cross-location-invoices/{invoice_id}/settle", payload, headers
        )

    def dispute_cross_location_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/cross-location-invoices/{invoice_id}/dispute", payload, headers
        )

    def get_cross_location_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"/cross-location-invoices/{invoice_id}", headers=headers
        )

    def list_cross_location_invoices(self, headers, params=None):
        return self._request(
            "GET", "/cross-location-invoices", headers=headers, params=params
        )


api_client = ApiClient()
