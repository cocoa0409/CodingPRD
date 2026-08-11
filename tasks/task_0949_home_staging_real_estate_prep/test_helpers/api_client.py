"""API client: one method per endpoint published by the home-staging service."""

from prd_bench_local_runner.testing import GenericApiClient

P = "/staging"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{P}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def set_clock_raw(self, payload, headers):
        return self._request("POST", f"{P}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------- brokerages
    def create_brokerage(self, payload, headers):
        return self._request("POST", f"{P}/brokerages", payload, headers)

    def get_brokerage(self, brokerage_id, headers):
        return self._request("GET", f"{P}/brokerages/{brokerage_id}", headers=headers)

    # ---------------------------------------------------------------- clients
    def create_client(self, payload, headers):
        return self._request("POST", f"{P}/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", f"{P}/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"{P}/clients/{client_id}", headers=headers)

    def record_seller_consent(self, client_id, headers):
        return self._request("POST", f"{P}/clients/{client_id}/seller-consent", {}, headers)

    # ------------------------------------------------------------- properties
    def create_property(self, payload, headers):
        return self._request("POST", f"{P}/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", f"{P}/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"{P}/properties/{property_id}", headers=headers)

    # --------------------------------------------------------------- listings
    def create_listing(self, payload, headers):
        return self._request("POST", f"{P}/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", f"{P}/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"{P}/listings/{listing_id}", headers=headers)

    def listing_under_contract(self, listing_id, headers):
        return self._request("POST", f"{P}/listings/{listing_id}/under-contract", {}, headers)

    def listing_fall_out_of_escrow(self, listing_id, headers):
        return self._request("POST", f"{P}/listings/{listing_id}/fall-out-of-escrow", {}, headers)

    def listing_close(self, listing_id, headers):
        return self._request("POST", f"{P}/listings/{listing_id}/close", {}, headers)

    def listing_terminate(self, listing_id, termination_reason, headers):
        return self._request("POST", f"{P}/listings/{listing_id}/terminate",
                             {"termination_reason": termination_reason}, headers)

    # ---------------------------------------------------------- package tiers
    def create_package_tier(self, payload, headers):
        return self._request("POST", f"{P}/package-tiers", payload, headers)

    def list_package_tiers(self, headers, params=None):
        return self._request("GET", f"{P}/package-tiers", headers=headers, params=params)

    def get_package_tier(self, tier_id, headers):
        return self._request("GET", f"{P}/package-tiers/{tier_id}", headers=headers)

    # ---------------------------------------------------------------- vendors
    def create_vendor(self, payload, headers):
        return self._request("POST", f"{P}/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", f"{P}/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"{P}/vendors/{vendor_id}", headers=headers)

    def update_vendor(self, vendor_id, payload, headers):
        return self._request("PATCH", f"{P}/vendors/{vendor_id}", payload, headers)

    # -------------------------------------------------------- inventory items
    def create_inventory_item(self, payload, headers):
        return self._request("POST", f"{P}/inventory-items", payload, headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", f"{P}/inventory-items", headers=headers, params=params)

    def get_inventory_summary(self, headers, params=None):
        return self._request("GET", f"{P}/inventory-items/summary", headers=headers, params=params)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"{P}/inventory-items/{item_id}", headers=headers)

    def repair_in_item(self, item_id, headers):
        return self._request("POST", f"{P}/inventory-items/{item_id}/repair-in", {}, headers)

    def repair_out_item(self, item_id, headers):
        return self._request("POST", f"{P}/inventory-items/{item_id}/repair-out", {}, headers)

    def write_off_item(self, item_id, reason, headers):
        return self._request("POST", f"{P}/inventory-items/{item_id}/write-off",
                             {"reason": reason}, headers)

    # ---------------------------------------------------------- consultations
    def create_consultation(self, payload, headers):
        return self._request("POST", f"{P}/consultations", payload, headers)

    def list_consultations(self, headers, params=None):
        return self._request("GET", f"{P}/consultations", headers=headers, params=params)

    def get_consultation(self, consultation_id, headers):
        return self._request("GET", f"{P}/consultations/{consultation_id}", headers=headers)

    def hold_consultation(self, consultation_id, headers):
        return self._request("POST", f"{P}/consultations/{consultation_id}/hold", {}, headers)

    def add_scope_item(self, consultation_id, payload, headers):
        return self._request("POST", f"{P}/consultations/{consultation_id}/scope-items",
                             payload, headers)

    def list_scope_items(self, headers, params=None):
        return self._request("GET", f"{P}/scope-items", headers=headers, params=params)

    def get_scope_item(self, scope_item_id, headers):
        return self._request("GET", f"{P}/scope-items/{scope_item_id}", headers=headers)

    def submit_scope(self, consultation_id, payload, headers):
        return self._request("POST", f"{P}/consultations/{consultation_id}/submit-scope",
                             payload, headers)

    def approve_scope(self, consultation_id, headers):
        return self._request("POST", f"{P}/consultations/{consultation_id}/approve-scope",
                             {}, headers)

    def reject_scope(self, consultation_id, payload, headers):
        return self._request("POST", f"{P}/consultations/{consultation_id}/reject-scope",
                             payload, headers)

    def cancel_consultation(self, consultation_id, headers):
        return self._request("POST", f"{P}/consultations/{consultation_id}/cancel", {}, headers)

    # --------------------------------------------------------------- projects
    def create_project(self, payload, headers):
        return self._request("POST", f"{P}/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{P}/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{P}/projects/{project_id}", headers=headers)

    def authorize_project(self, project_id, headers):
        return self._request("POST", f"{P}/projects/{project_id}/authorize", {}, headers)

    def upgrade_package(self, project_id, package_tier_id, headers):
        return self._request("POST", f"{P}/projects/{project_id}/upgrade-package",
                             {"package_tier_id": package_tier_id}, headers)

    def downgrade_package(self, project_id, package_tier_id, headers):
        return self._request("POST", f"{P}/projects/{project_id}/downgrade-package",
                             {"package_tier_id": package_tier_id}, headers)

    def extend_window(self, project_id, headers):
        return self._request("POST", f"{P}/projects/{project_id}/extend-window", {}, headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"{P}/projects/{project_id}/close", {}, headers)

    # ------------------------------------------------------------------ pulls
    def open_pull(self, project_id, headers):
        return self._request("POST", f"{P}/projects/{project_id}/pulls", {}, headers)

    def list_pulls(self, headers, params=None):
        return self._request("GET", f"{P}/pulls", headers=headers, params=params)

    def get_pull(self, pull_id, headers):
        return self._request("GET", f"{P}/pulls/{pull_id}", headers=headers)

    def add_pull_line(self, pull_id, payload, headers):
        return self._request("POST", f"{P}/pulls/{pull_id}/lines", payload, headers)

    def list_pull_lines(self, headers, params=None):
        return self._request("GET", f"{P}/pull-lines", headers=headers, params=params)

    def get_pull_line(self, pull_line_id, headers):
        return self._request("GET", f"{P}/pull-lines/{pull_line_id}", headers=headers)

    def submit_pull(self, pull_id, headers):
        return self._request("POST", f"{P}/pulls/{pull_id}/submit", {}, headers)

    def commit_pull(self, pull_id, expected_project_version, headers):
        return self._request("POST", f"{P}/pulls/{pull_id}/commit",
                             {"expected_project_version": expected_project_version}, headers)

    def commit_pull_raw(self, pull_id, payload, headers):
        return self._request("POST", f"{P}/pulls/{pull_id}/commit", payload, headers)

    def release_pull(self, pull_id, headers):
        return self._request("POST", f"{P}/pulls/{pull_id}/release", {}, headers)

    def cancel_pull(self, pull_id, headers):
        return self._request("POST", f"{P}/pulls/{pull_id}/cancel", {}, headers)

    # ---------------------------------------------------------- rental orders
    def create_rental_order(self, payload, headers):
        return self._request("POST", f"{P}/rental-orders", payload, headers)

    def list_rental_orders(self, headers, params=None):
        return self._request("GET", f"{P}/rental-orders", headers=headers, params=params)

    def get_rental_order(self, rental_order_id, headers):
        return self._request("GET", f"{P}/rental-orders/{rental_order_id}", headers=headers)

    def place_rental_order(self, rental_order_id, headers):
        return self._request("POST", f"{P}/rental-orders/{rental_order_id}/place", {}, headers)

    def confirm_rental_order(self, rental_order_id, headers):
        return self._request("POST", f"{P}/rental-orders/{rental_order_id}/confirm", {}, headers)

    def cancel_rental_order(self, rental_order_id, headers):
        return self._request("POST", f"{P}/rental-orders/{rental_order_id}/cancel", {}, headers)

    # --------------------------------------------------------------- installs
    def schedule_install(self, project_id, payload, headers):
        return self._request("POST", f"{P}/projects/{project_id}/installs", payload, headers)

    def list_installs(self, headers, params=None):
        return self._request("GET", f"{P}/installs", headers=headers, params=params)

    def get_install(self, install_id, headers):
        return self._request("GET", f"{P}/installs/{install_id}", headers=headers)

    def start_install(self, install_id, headers):
        return self._request("POST", f"{P}/installs/{install_id}/start", {}, headers)

    def complete_install(self, install_id, headers):
        return self._request("POST", f"{P}/installs/{install_id}/complete", {}, headers)

    def install_no_access(self, install_id, headers):
        return self._request("POST", f"{P}/installs/{install_id}/no-access", {}, headers)

    def reschedule_install(self, install_id, scheduled_at, headers):
        return self._request("POST", f"{P}/installs/{install_id}/reschedule",
                             {"scheduled_at": scheduled_at}, headers)

    # ----------------------------------------------------------------- visits
    def schedule_visit(self, project_id, scheduled_at, headers):
        return self._request("POST", f"{P}/projects/{project_id}/visits",
                             {"scheduled_at": scheduled_at}, headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", f"{P}/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"{P}/visits/{visit_id}", headers=headers)

    def complete_visit(self, visit_id, hours_logged, headers):
        return self._request("POST", f"{P}/visits/{visit_id}/complete",
                             {"hours_logged": hours_logged}, headers)

    def visit_no_access(self, visit_id, headers):
        return self._request("POST", f"{P}/visits/{visit_id}/no-access", {}, headers)

    def reschedule_visit(self, visit_id, scheduled_at, headers):
        return self._request("POST", f"{P}/visits/{visit_id}/reschedule",
                             {"scheduled_at": scheduled_at}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"{P}/visits/{visit_id}/cancel", {}, headers)

    # ----------------------------------------------------------------- leases
    def list_leases(self, headers, params=None):
        return self._request("GET", f"{P}/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"{P}/leases/{lease_id}", headers=headers)

    def mark_term_complete(self, lease_id, headers):
        return self._request("POST", f"{P}/leases/{lease_id}/mark-term-complete", {}, headers)

    def accrue_holdover(self, lease_id, headers):
        return self._request("POST", f"{P}/leases/{lease_id}/accrue-holdover", {}, headers)

    def request_extension(self, lease_id, requested_cycles, expected_lease_version, headers):
        return self._request(
            "POST", f"{P}/leases/{lease_id}/extensions",
            {"requested_cycles": requested_cycles,
             "expected_lease_version": expected_lease_version}, headers)

    def request_extension_raw(self, lease_id, payload, headers):
        return self._request("POST", f"{P}/leases/{lease_id}/extensions", payload, headers)

    # ------------------------------------------------------------- extensions
    def list_extensions(self, headers, params=None):
        return self._request("GET", f"{P}/extensions", headers=headers, params=params)

    def get_extension(self, extension_id, headers):
        return self._request("GET", f"{P}/extensions/{extension_id}", headers=headers)

    def adjudicate_extension(self, extension_id, decision, headers):
        return self._request("POST", f"{P}/extensions/{extension_id}/adjudicate",
                             {"decision": decision}, headers)

    def apply_extension(self, extension_id, headers):
        return self._request("POST", f"{P}/extensions/{extension_id}/apply", {}, headers)

    # ---------------------------------------------------------------- pickups
    def schedule_pickup(self, project_id, payload, headers):
        return self._request("POST", f"{P}/projects/{project_id}/pickups", payload, headers)

    def list_pickups(self, headers, params=None):
        return self._request("GET", f"{P}/pickups", headers=headers, params=params)

    def get_pickup(self, pickup_id, headers):
        return self._request("GET", f"{P}/pickups/{pickup_id}", headers=headers)

    def start_pickup(self, pickup_id, headers):
        return self._request("POST", f"{P}/pickups/{pickup_id}/start", {}, headers)

    def complete_pickup(self, pickup_id, headers):
        return self._request("POST", f"{P}/pickups/{pickup_id}/complete", {}, headers)

    def pickup_no_access(self, pickup_id, headers):
        return self._request("POST", f"{P}/pickups/{pickup_id}/no-access", {}, headers)

    def pickup_refuse(self, pickup_id, headers):
        return self._request("POST", f"{P}/pickups/{pickup_id}/refuse", {}, headers)

    def reschedule_pickup(self, pickup_id, scheduled_at, headers):
        return self._request("POST", f"{P}/pickups/{pickup_id}/reschedule",
                             {"scheduled_at": scheduled_at}, headers)

    def raise_damage_assessment(self, pickup_id, payload, headers):
        return self._request("POST", f"{P}/pickups/{pickup_id}/damage-assessments",
                             payload, headers)

    # ------------------------------------------------------ damage assessment
    def list_damage_assessments(self, headers, params=None):
        return self._request("GET", f"{P}/damage-assessments", headers=headers, params=params)

    def get_damage_assessment(self, assessment_id, headers):
        return self._request("GET", f"{P}/damage-assessments/{assessment_id}", headers=headers)

    def assess_damage(self, assessment_id, headers):
        return self._request("POST", f"{P}/damage-assessments/{assessment_id}/assess", {}, headers)

    def dispute_damage(self, assessment_id, payload, headers):
        return self._request("POST", f"{P}/damage-assessments/{assessment_id}/dispute",
                             payload, headers)

    def adjudicate_damage(self, assessment_id, payload, headers):
        return self._request("POST", f"{P}/damage-assessments/{assessment_id}/adjudicate",
                             payload, headers)

    def finalize_damage(self, assessment_id, expected_pickup_version, headers):
        return self._request("POST", f"{P}/damage-assessments/{assessment_id}/finalize",
                             {"expected_pickup_version": expected_pickup_version}, headers)

    # ----------------------------------------------------------- photo shoots
    def schedule_photo_shoot(self, project_id, payload, headers):
        return self._request("POST", f"{P}/projects/{project_id}/photo-shoots", payload, headers)

    def list_photo_shoots(self, headers, params=None):
        return self._request("GET", f"{P}/photo-shoots", headers=headers, params=params)

    def get_photo_shoot(self, shoot_id, headers):
        return self._request("GET", f"{P}/photo-shoots/{shoot_id}", headers=headers)

    def complete_photo_shoot(self, shoot_id, headers):
        return self._request("POST", f"{P}/photo-shoots/{shoot_id}/complete", {}, headers)

    def deliver_photo_shoot(self, shoot_id, headers):
        return self._request("POST", f"{P}/photo-shoots/{shoot_id}/deliver", {}, headers)

    def cancel_photo_shoot(self, shoot_id, headers):
        return self._request("POST", f"{P}/photo-shoots/{shoot_id}/cancel", {}, headers)

    def request_reshoot(self, shoot_id, scheduled_at, headers):
        return self._request("POST", f"{P}/photo-shoots/{shoot_id}/request-reshoot",
                             {"scheduled_at": scheduled_at}, headers)

    # --------------------------------------------------------------- invoices
    def open_closeout(self, project_id, headers):
        return self._request("POST", f"{P}/projects/{project_id}/invoices", {}, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{P}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{P}/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"{P}/invoices/{invoice_id}/issue", {}, headers)

    def defer_invoice_to_closing(self, invoice_id, headers):
        return self._request("POST", f"{P}/invoices/{invoice_id}/defer-to-closing", {}, headers)

    def escalate_invoice(self, invoice_id, headers):
        return self._request("POST", f"{P}/invoices/{invoice_id}/escalate", {}, headers)

    def pay_invoice(self, invoice_id, amount_paid, headers):
        return self._request("POST", f"{P}/invoices/{invoice_id}/pay",
                             {"amount_paid": amount_paid}, headers)

    def void_invoice(self, invoice_id, reason, headers):
        return self._request("POST", f"{P}/invoices/{invoice_id}/void",
                             {"reason": reason}, headers)

    # --------------------------------------------------------------- deposits
    def list_deposits(self, headers, params=None):
        return self._request("GET", f"{P}/deposits", headers=headers, params=params)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"{P}/deposits/{deposit_id}", headers=headers)

    def collect_deposit(self, deposit_id, headers):
        return self._request("POST", f"{P}/deposits/{deposit_id}/collect", {}, headers)

    def apply_deposit(self, deposit_id, invoice_id, headers):
        return self._request("POST", f"{P}/deposits/{deposit_id}/apply",
                             {"invoice_id": invoice_id}, headers)

    def refund_deposit(self, deposit_id, headers):
        return self._request("POST", f"{P}/deposits/{deposit_id}/refund", {}, headers)

    def forfeit_deposit(self, deposit_id, reason, headers):
        return self._request("POST", f"{P}/deposits/{deposit_id}/forfeit",
                             {"reason": reason}, headers)


api_client = ApiClient()
