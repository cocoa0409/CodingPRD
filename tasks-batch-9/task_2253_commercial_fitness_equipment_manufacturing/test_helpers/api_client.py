"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Equipment models ──────────────────────────────────────────────────
    def create_equipment_model(self, payload, headers):
        return self._request("POST", "/equipment-models", payload, headers)

    def list_equipment_models(self, headers, params=None):
        return self._request("GET", "/equipment-models", headers=headers, params=params)

    def get_equipment_model(self, model_id, headers):
        return self._request("GET", f"/equipment-models/{model_id}", headers=headers)

    # ─── Model revisions ───────────────────────────────────────────────────
    def create_model_revision(self, payload, headers):
        return self._request("POST", "/model-revisions", payload, headers)

    def list_model_revisions(self, headers, params=None):
        return self._request("GET", "/model-revisions", headers=headers, params=params)

    def get_model_revision(self, revision_id, headers):
        return self._request("GET", f"/model-revisions/{revision_id}", headers=headers)

    def submit_revision_for_testing(self, revision_id, headers, payload=None):
        return self._request(
            "POST", f"/model-revisions/{revision_id}/submit-for-testing", payload, headers
        )

    def rework_revision(self, revision_id, payload, headers):
        return self._request(
            "POST", f"/model-revisions/{revision_id}/rework", payload, headers
        )

    def qualify_revision(self, revision_id, headers, payload=None):
        return self._request(
            "POST", f"/model-revisions/{revision_id}/qualify", payload, headers
        )

    def release_revision(self, revision_id, headers, payload=None):
        return self._request(
            "POST", f"/model-revisions/{revision_id}/release", payload, headers
        )

    def sunset_revision(self, revision_id, payload, headers):
        return self._request(
            "POST", f"/model-revisions/{revision_id}/sunset", payload, headers
        )

    def mark_revision_obsolete(self, revision_id, headers, payload=None):
        return self._request(
            "POST", f"/model-revisions/{revision_id}/mark-obsolete", payload, headers
        )

    def get_qualification_report(self, revision_id, headers):
        return self._request(
            "GET", f"/model-revisions/{revision_id}/qualification-report", headers=headers
        )

    # ─── Durability rigs and runs ──────────────────────────────────────────
    def create_test_rig(self, payload, headers):
        return self._request("POST", "/test-rigs", payload, headers)

    def get_test_rig(self, rig_id, headers):
        return self._request("GET", f"/test-rigs/{rig_id}", headers=headers)

    def create_test_run(self, payload, headers):
        return self._request("POST", "/test-runs", payload, headers)

    def list_test_runs(self, headers, params=None):
        return self._request("GET", "/test-runs", headers=headers, params=params)

    def get_test_run(self, run_id, headers):
        return self._request("GET", f"/test-runs/{run_id}", headers=headers)

    def start_test_run(self, run_id, headers, payload=None):
        return self._request("POST", f"/test-runs/{run_id}/start", payload, headers)

    def complete_test_run(self, run_id, payload, headers):
        return self._request("POST", f"/test-runs/{run_id}/complete", payload, headers)

    def abort_test_run(self, run_id, payload, headers):
        return self._request("POST", f"/test-runs/{run_id}/abort", payload, headers)

    # ─── Firmware releases and certifications ──────────────────────────────
    def create_firmware_release(self, payload, headers):
        return self._request("POST", "/firmware-releases", payload, headers)

    def get_firmware_release(self, release_id, headers):
        return self._request("GET", f"/firmware-releases/{release_id}", headers=headers)

    def withdraw_firmware_release(self, release_id, payload, headers):
        return self._request(
            "POST", f"/firmware-releases/{release_id}/withdraw", payload, headers
        )

    def create_firmware_certification(self, payload, headers):
        return self._request("POST", "/firmware-certifications", payload, headers)

    def list_firmware_certifications(self, headers, params=None):
        return self._request(
            "GET", "/firmware-certifications", headers=headers, params=params
        )

    def get_firmware_certification(self, certification_id, headers):
        return self._request(
            "GET", f"/firmware-certifications/{certification_id}", headers=headers
        )

    def certify_firmware_certification(self, certification_id, headers, payload=None):
        return self._request(
            "POST", f"/firmware-certifications/{certification_id}/certify", payload, headers
        )

    def reject_firmware_certification(self, certification_id, payload, headers):
        return self._request(
            "POST", f"/firmware-certifications/{certification_id}/reject", payload, headers
        )

    # ─── Facilities ────────────────────────────────────────────────────────
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def suspend_facility(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/suspend", payload, headers)

    # ─── Orders and lines ──────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def create_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def void_order_line(self, line_id, headers, payload=None):
        return self._request("POST", f"/order-lines/{line_id}/void", payload, headers)

    def quote_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/quote", payload, headers)

    def confirm_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/confirm", payload, headers)

    def complete_order_production(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/orders/{order_id}/production/complete", payload, headers
        )

    def get_price_breakdown(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/price-breakdown", headers=headers)

    def apply_tradein_credit(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/apply-tradein-credit", payload, headers
        )

    def settle_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/settle", payload, headers)

    # ─── Service partners ──────────────────────────────────────────────────
    def create_service_partner(self, payload, headers):
        return self._request("POST", "/service-partners", payload, headers)

    def get_service_partner(self, partner_id, headers):
        return self._request("GET", f"/service-partners/{partner_id}", headers=headers)

    def post_parts_receipt(self, partner_id, payload, headers):
        return self._request(
            "POST", f"/service-partners/{partner_id}/parts-receipt", payload, headers
        )

    # ─── Install jobs ──────────────────────────────────────────────────────
    def create_install_job(self, payload, headers):
        return self._request("POST", "/install-jobs", payload, headers)

    def list_install_jobs(self, headers, params=None):
        return self._request("GET", "/install-jobs", headers=headers, params=params)

    def get_install_job(self, job_id, headers):
        return self._request("GET", f"/install-jobs/{job_id}", headers=headers)

    def arrive_install_job(self, job_id, headers, payload=None):
        return self._request("POST", f"/install-jobs/{job_id}/arrive", payload, headers)

    def complete_install_job(self, job_id, payload, headers):
        return self._request("POST", f"/install-jobs/{job_id}/complete", payload, headers)

    def resolve_punch_list(self, job_id, payload, headers):
        return self._request(
            "POST", f"/install-jobs/{job_id}/resolve-punch-list", payload, headers
        )

    def abort_install_job(self, job_id, payload, headers):
        return self._request("POST", f"/install-jobs/{job_id}/abort", payload, headers)

    # ─── Serialized assets ─────────────────────────────────────────────────
    def list_serialized_assets(self, headers, params=None):
        return self._request("GET", "/serialized-assets", headers=headers, params=params)

    def get_serialized_asset(self, asset_id, headers):
        return self._request("GET", f"/serialized-assets/{asset_id}", headers=headers)

    def load_firmware(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/serialized-assets/{asset_id}/load-firmware", payload, headers
        )

    def report_asset_usage(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/serialized-assets/{asset_id}/usage-report", payload, headers
        )

    def trade_in_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/serialized-assets/{asset_id}/trade-in", payload, headers
        )

    def reverse_asset_trade_in(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/serialized-assets/{asset_id}/trade-in/reverse", payload, headers
        )

    def refurb_intake_asset(self, asset_id, headers, payload=None):
        return self._request(
            "POST", f"/serialized-assets/{asset_id}/refurb/intake", payload, headers
        )

    def refurb_certify_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/serialized-assets/{asset_id}/refurb/certify", payload, headers
        )

    def resell_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/serialized-assets/{asset_id}/resell", payload, headers
        )

    def scrap_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/serialized-assets/{asset_id}/scrap", payload, headers
        )

    # ─── Preventive maintenance programs ───────────────────────────────────
    def create_pm_program(self, payload, headers):
        return self._request("POST", "/pm-programs", payload, headers)

    def list_pm_programs(self, headers, params=None):
        return self._request("GET", "/pm-programs", headers=headers, params=params)

    def get_pm_program(self, program_id, headers):
        return self._request("GET", f"/pm-programs/{program_id}", headers=headers)

    def activate_pm_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/pm-programs/{program_id}/activate", payload, headers
        )

    def revise_pm_program(self, program_id, payload, headers):
        return self._request("POST", f"/pm-programs/{program_id}/revise", payload, headers)

    def terminate_pm_program(self, program_id, payload, headers):
        return self._request(
            "POST", f"/pm-programs/{program_id}/terminate", payload, headers
        )

    # ─── Maintenance visits ────────────────────────────────────────────────
    def create_maintenance_visit(self, payload, headers):
        return self._request("POST", "/maintenance-visits", payload, headers)

    def list_maintenance_visits(self, headers, params=None):
        return self._request("GET", "/maintenance-visits", headers=headers, params=params)

    def get_maintenance_visit(self, visit_id, headers):
        return self._request("GET", f"/maintenance-visits/{visit_id}", headers=headers)

    def complete_maintenance_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-visits/{visit_id}/complete", payload, headers
        )

    def cancel_maintenance_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-visits/{visit_id}/cancel", payload, headers
        )

    # ─── Logical clock ─────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
