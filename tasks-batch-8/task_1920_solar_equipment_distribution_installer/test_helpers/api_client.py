"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/solar-dist/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/solar-dist/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/solar-dist/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/solar-dist/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request(
            "POST", f"/solar-dist/products/{product_id}/discontinue", {}, headers
        )

    # --- Compatibility rules ---
    def create_compatibility_rule(self, payload, headers):
        return self._request("POST", "/solar-dist/compatibility-rules", payload, headers)

    def list_compatibility_rules(self, headers, params=None):
        return self._request(
            "GET", "/solar-dist/compatibility-rules", headers=headers, params=params
        )

    def get_compatibility_rule(self, rule_id, headers):
        return self._request(
            "GET", f"/solar-dist/compatibility-rules/{rule_id}", headers=headers
        )

    def retire_compatibility_rule(self, rule_id, headers):
        return self._request(
            "POST", f"/solar-dist/compatibility-rules/{rule_id}/retire", {}, headers
        )

    # --- Tariff rates ---
    def create_tariff_rate(self, payload, headers):
        return self._request("POST", "/solar-dist/tariff-rates", payload, headers)

    def list_tariff_rates(self, headers, params=None):
        return self._request("GET", "/solar-dist/tariff-rates", headers=headers, params=params)

    def get_tariff_rate(self, rate_id, headers):
        return self._request("GET", f"/solar-dist/tariff-rates/{rate_id}", headers=headers)

    # --- Installers ---
    def create_installer(self, payload, headers):
        return self._request("POST", "/solar-dist/installers", payload, headers)

    def list_installers(self, headers, params=None):
        return self._request("GET", "/solar-dist/installers", headers=headers, params=params)

    def get_installer(self, installer_id, headers):
        return self._request("GET", f"/solar-dist/installers/{installer_id}", headers=headers)

    def activate_installer(self, installer_id, headers):
        return self._request(
            "POST", f"/solar-dist/installers/{installer_id}/activate", {}, headers
        )

    def suspend_installer(self, installer_id, headers):
        return self._request(
            "POST", f"/solar-dist/installers/{installer_id}/suspend", {}, headers
        )

    def reinstate_installer(self, installer_id, headers):
        return self._request(
            "POST", f"/solar-dist/installers/{installer_id}/reinstate", {}, headers
        )

    def terminate_installer(self, installer_id, headers):
        return self._request(
            "POST", f"/solar-dist/installers/{installer_id}/terminate", {}, headers
        )

    # --- Containers ---
    def create_container(self, payload, headers):
        return self._request("POST", "/solar-dist/containers", payload, headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/solar-dist/containers", headers=headers, params=params)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/solar-dist/containers/{container_id}", headers=headers)

    def update_container(self, container_id, payload, headers):
        return self._request(
            "PATCH", f"/solar-dist/containers/{container_id}", payload, headers
        )

    def depart_container(self, container_id, headers):
        return self._request(
            "POST", f"/solar-dist/containers/{container_id}/depart", {}, headers
        )

    def arrive_container(self, container_id, headers):
        return self._request(
            "POST", f"/solar-dist/containers/{container_id}/arrive", {}, headers
        )

    def receive_container(self, container_id, payload, headers):
        return self._request(
            "POST", f"/solar-dist/containers/{container_id}/receive", payload, headers
        )

    def close_container(self, container_id, headers):
        return self._request(
            "POST", f"/solar-dist/containers/{container_id}/close", {}, headers
        )

    def cancel_container(self, container_id, headers):
        return self._request(
            "POST", f"/solar-dist/containers/{container_id}/cancel", {}, headers
        )

    # --- Container lines ---
    def create_container_line(self, container_id, payload, headers):
        return self._request(
            "POST", f"/solar-dist/containers/{container_id}/lines", payload, headers
        )

    def list_container_lines(self, container_id, headers, params=None):
        return self._request(
            "GET", f"/solar-dist/containers/{container_id}/lines",
            headers=headers, params=params,
        )

    def get_container_line(self, container_id, line_id, headers):
        return self._request(
            "GET", f"/solar-dist/containers/{container_id}/lines/{line_id}",
            headers=headers,
        )

    def list_all_container_lines(self, headers, params=None):
        return self._request(
            "GET", "/solar-dist/container-lines", headers=headers, params=params
        )

    def get_container_line_by_id(self, line_id, headers):
        return self._request(
            "GET", f"/solar-dist/container-lines/{line_id}", headers=headers
        )

    # --- Inventory lots ---
    def list_inventory_lots(self, headers, params=None):
        return self._request(
            "GET", "/solar-dist/inventory-lots", headers=headers, params=params
        )

    def get_inventory_lot(self, lot_id, headers):
        return self._request(
            "GET", f"/solar-dist/inventory-lots/{lot_id}", headers=headers
        )

    def write_off_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/solar-dist/inventory-lots/{lot_id}/write-off", {}, headers
        )

    # --- Projects ---
    def create_project(self, installer_id, payload, headers):
        return self._request(
            "POST", f"/solar-dist/installers/{installer_id}/projects", payload, headers
        )

    def list_installer_projects(self, installer_id, headers, params=None):
        return self._request(
            "GET", f"/solar-dist/installers/{installer_id}/projects",
            headers=headers, params=params,
        )

    def get_project(self, project_id, headers):
        return self._request("GET", f"/solar-dist/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/solar-dist/projects", headers=headers, params=params)

    def lock_design(self, project_id, headers):
        return self._request(
            "POST", f"/solar-dist/projects/{project_id}/lock-design", {}, headers
        )

    def cancel_project(self, project_id, headers):
        return self._request(
            "POST", f"/solar-dist/projects/{project_id}/cancel", {}, headers
        )

    def complete_project(self, project_id, headers):
        return self._request(
            "POST", f"/solar-dist/projects/{project_id}/complete", {}, headers
        )

    def invoice_pto(self, project_id, headers):
        return self._request(
            "POST", f"/solar-dist/projects/{project_id}/invoice-pto", {}, headers
        )

    def write_off_project(self, project_id, headers):
        return self._request(
            "POST", f"/solar-dist/projects/{project_id}/write-off", {}, headers
        )

    # --- Allocations ---
    def create_allocation(self, project_id, payload, headers):
        return self._request(
            "POST", f"/solar-dist/projects/{project_id}/allocations", payload, headers
        )

    def list_project_allocations(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/solar-dist/projects/{project_id}/allocations",
            headers=headers, params=params,
        )

    def get_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/solar-dist/allocations/{allocation_id}", headers=headers
        )

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/solar-dist/allocations", headers=headers, params=params)

    def ship_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/solar-dist/allocations/{allocation_id}/ship", {}, headers
        )

    def release_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/solar-dist/allocations/{allocation_id}/release", {}, headers
        )

    # --- Invoices ---
    def list_project_invoices(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/solar-dist/projects/{project_id}/invoices",
            headers=headers, params=params,
        )

    def list_installer_invoices(self, installer_id, headers, params=None):
        return self._request(
            "GET", f"/solar-dist/installers/{installer_id}/invoices",
            headers=headers, params=params,
        )

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/solar-dist/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/solar-dist/invoices", headers=headers, params=params)

    def void_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/solar-dist/invoices/{invoice_id}/void", {}, headers
        )

    # --- Payments ---
    def post_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/solar-dist/invoices/{invoice_id}/payments", payload, headers
        )

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/solar-dist/invoices/{invoice_id}/payments",
            headers=headers, params=params,
        )

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/solar-dist/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/solar-dist/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/solar-dist/payments/{payment_id}/reverse", {}, headers
        )

    # --- RMA claims ---
    def create_rma_claim(self, payload, headers):
        return self._request("POST", "/solar-dist/rma-claims", payload, headers)

    def list_rma_claims(self, headers, params=None):
        return self._request("GET", "/solar-dist/rma-claims", headers=headers, params=params)

    def get_rma_claim(self, rma_id, headers):
        return self._request("GET", f"/solar-dist/rma-claims/{rma_id}", headers=headers)

    def submit_rma_claim(self, rma_id, headers):
        return self._request("POST", f"/solar-dist/rma-claims/{rma_id}/submit", {}, headers)

    def approve_rma_claim(self, rma_id, payload, headers):
        return self._request(
            "POST", f"/solar-dist/rma-claims/{rma_id}/approve", payload, headers
        )

    def reject_rma_claim(self, rma_id, headers):
        return self._request("POST", f"/solar-dist/rma-claims/{rma_id}/reject", {}, headers)

    def issue_rma_credit(self, rma_id, headers):
        return self._request(
            "POST", f"/solar-dist/rma-claims/{rma_id}/issue-credit", {}, headers
        )

    def close_rma_claim(self, rma_id, headers):
        return self._request("POST", f"/solar-dist/rma-claims/{rma_id}/close", {}, headers)

    # --- Permit packages ---
    def list_project_permit_packages(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/solar-dist/projects/{project_id}/permit-packages",
            headers=headers, params=params,
        )

    def get_permit_package(self, package_id, headers):
        return self._request(
            "GET", f"/solar-dist/permit-packages/{package_id}", headers=headers
        )

    def list_permit_packages(self, headers, params=None):
        return self._request(
            "GET", "/solar-dist/permit-packages", headers=headers, params=params
        )

    def upload_permit_document(self, package_id, payload, headers):
        return self._request(
            "POST", f"/solar-dist/permit-packages/{package_id}/documents",
            payload, headers,
        )

    def submit_permit_package(self, package_id, headers):
        return self._request(
            "POST", f"/solar-dist/permit-packages/{package_id}/submit", {}, headers
        )

    def approve_permit_package(self, package_id, headers):
        return self._request(
            "POST", f"/solar-dist/permit-packages/{package_id}/approve", {}, headers
        )

    def reject_permit_package(self, package_id, headers):
        return self._request(
            "POST", f"/solar-dist/permit-packages/{package_id}/reject", {}, headers
        )

    def reassemble_permit_package(self, package_id, headers):
        return self._request(
            "POST", f"/solar-dist/permit-packages/{package_id}/reassemble", {}, headers
        )

    def withdraw_permit_package(self, package_id, headers):
        return self._request(
            "POST", f"/solar-dist/permit-packages/{package_id}/withdraw", {}, headers
        )

    # --- Damage claims ---
    def create_damage_claim(self, container_id, payload, headers):
        return self._request(
            "POST", f"/solar-dist/containers/{container_id}/damage-claims",
            payload, headers,
        )

    def list_container_damage_claims(self, container_id, headers, params=None):
        return self._request(
            "GET", f"/solar-dist/containers/{container_id}/damage-claims",
            headers=headers, params=params,
        )

    def get_damage_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/solar-dist/damage-claims/{claim_id}", headers=headers
        )

    def list_damage_claims(self, headers, params=None):
        return self._request(
            "GET", "/solar-dist/damage-claims", headers=headers, params=params
        )

    def file_damage_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/solar-dist/damage-claims/{claim_id}/file", {}, headers
        )

    def settle_damage_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/solar-dist/damage-claims/{claim_id}/settle", {}, headers
        )

    def deny_damage_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/solar-dist/damage-claims/{claim_id}/deny", {}, headers
        )


api_client = ApiClient()
