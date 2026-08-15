"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fluid-power"


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- shop config ---
    def create_shop(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shops", payload, headers)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"{PREFIX}/shops/{shop_id}", headers=headers)

    def patch_shop(self, shop_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/shops/{shop_id}", payload, headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"{PREFIX}/customers/{customer_id}/suspend", headers=headers)

    def reactivate_customer(self, customer_id, headers):
        return self._request("POST", f"{PREFIX}/customers/{customer_id}/reactivate", headers=headers)

    # --- technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", f"{PREFIX}/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"{PREFIX}/technicians/{technician_id}", headers=headers)

    # --- seal kits ---
    def create_seal_kit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seal-kits", payload, headers)

    def get_seal_kit(self, kit_id, headers):
        return self._request("GET", f"{PREFIX}/seal-kits/{kit_id}", headers=headers)

    # --- cylinders ---
    def create_cylinder(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cylinders", payload, headers)

    def get_cylinder(self, cylinder_id, headers):
        return self._request("GET", f"{PREFIX}/cylinders/{cylinder_id}", headers=headers)

    def list_cylinders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cylinders", headers=headers, params=params)

    # --- work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"{PREFIX}/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-orders", headers=headers, params=params)

    def start_teardown(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/start-teardown", payload, headers
        )

    def cancel_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/cancel", payload, headers
        )

    def authorize_scrap(self, work_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/authorize-scrap", headers=headers
        )

    def complete_scrap(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/complete-scrap", payload, headers
        )

    def start_repair(self, work_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/start-repair", headers=headers
        )

    def complete_assembly(self, work_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/complete-assembly", headers=headers
        )

    def record_cleanliness_check(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/cleanliness-checks", payload, headers
        )

    def select_exchange(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/select-exchange", payload, headers
        )

    def close_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/close", payload, headers
        )

    # --- teardown reports ---
    def create_teardown_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/teardown-reports", payload, headers)

    def get_teardown_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/teardown-reports/{report_id}", headers=headers)

    def list_teardown_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/teardown-reports", headers=headers, params=params)

    def patch_teardown_report(self, report_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/teardown-reports/{report_id}", payload, headers)

    # --- quotes ---
    def create_quote(self, payload, headers):
        return self._request("POST", f"{PREFIX}/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"{PREFIX}/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/quotes", headers=headers, params=params)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"{PREFIX}/quotes/{quote_id}/send", headers=headers)

    def approve_quote(self, quote_id, headers):
        return self._request("POST", f"{PREFIX}/quotes/{quote_id}/approve", headers=headers)

    def request_quote_revision(self, quote_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/quotes/{quote_id}/request-revision", payload, headers
        )

    # --- inventory ---
    def create_inventory_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inventory-items", payload, headers)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/inventory-items/{item_id}", headers=headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/inventory-items", headers=headers, params=params)

    # --- stock reservations ---
    def create_stock_reservation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stock-reservations", payload, headers)

    def get_stock_reservation(self, reservation_id, headers):
        return self._request("GET", f"{PREFIX}/stock-reservations/{reservation_id}", headers=headers)

    def list_stock_reservations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stock-reservations", headers=headers, params=params)

    def consume_stock_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/stock-reservations/{reservation_id}/consume", headers=headers
        )

    def release_stock_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/stock-reservations/{reservation_id}/release", headers=headers
        )

    # --- test bays / pressure tests ---
    def create_test_bay(self, payload, headers):
        return self._request("POST", f"{PREFIX}/test-bays", payload, headers)

    def get_test_bay(self, bay_id, headers):
        return self._request("GET", f"{PREFIX}/test-bays/{bay_id}", headers=headers)

    def create_pressure_test(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pressure-tests", payload, headers)

    def get_pressure_test(self, test_id, headers):
        return self._request("GET", f"{PREFIX}/pressure-tests/{test_id}", headers=headers)

    def list_pressure_tests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/pressure-tests", headers=headers, params=params)

    def record_pressure_test_result(self, test_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pressure-tests/{test_id}/record-result", payload, headers
        )

    def cancel_pressure_test(self, test_id, headers):
        return self._request("POST", f"{PREFIX}/pressure-tests/{test_id}/cancel", headers=headers)

    # --- certificates ---
    def create_certificate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"{PREFIX}/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/certificates", headers=headers, params=params)

    def revoke_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/certificates/{certificate_id}/revoke", payload, headers
        )

    # --- exchange pool ---
    def create_exchange_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/exchange-units", payload, headers)

    def get_exchange_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/exchange-units/{unit_id}", headers=headers)

    def list_exchange_units(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/exchange-units", headers=headers, params=params)

    def release_exchange_unit(self, unit_id, headers):
        return self._request("POST", f"{PREFIX}/exchange-units/{unit_id}/release", headers=headers)

    def fulfill_exchange_unit(self, unit_id, headers):
        return self._request("POST", f"{PREFIX}/exchange-units/{unit_id}/fulfill", headers=headers)

    def receive_core(self, unit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/exchange-units/{unit_id}/receive-core", headers=headers
        )

    def evaluate_core(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/exchange-units/{unit_id}/evaluate-core", payload, headers
        )

    # --- field service jobs ---
    def create_field_service_job(self, payload, headers):
        return self._request("POST", f"{PREFIX}/field-service-jobs", payload, headers)

    def get_field_service_job(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/field-service-jobs/{job_id}", headers=headers)

    def list_field_service_jobs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/field-service-jobs", headers=headers, params=params)

    def schedule_field_service_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/field-service-jobs/{job_id}/schedule", payload, headers
        )

    def dispatch_field_service_job(self, job_id, headers):
        return self._request(
            "POST", f"{PREFIX}/field-service-jobs/{job_id}/dispatch", headers=headers
        )

    def complete_field_service_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/field-service-jobs/{job_id}/complete", payload, headers
        )

    def cancel_field_service_job(self, job_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/field-service-jobs/{job_id}/cancel", payload, headers
        )


api_client = ApiClient()
