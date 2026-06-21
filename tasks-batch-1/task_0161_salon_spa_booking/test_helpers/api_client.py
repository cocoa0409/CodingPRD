"""API client: one method per endpoint defined in the Salon Spa Booking PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Salon ----
    def create_salon(self, payload, headers):
        return self._request("POST", "/salons", payload, headers)

    def get_salon(self, salon_id, headers):
        return self._request("GET", f"/salons/{salon_id}", headers=headers)

    def advance_clock(self, salon_id, payload, headers):
        return self._request("POST", f"/salons/{salon_id}/_clock/advance", payload, headers)

    # ---- Stylist ----
    def create_stylist(self, payload, headers):
        return self._request("POST", "/stylists", payload, headers)

    def get_stylist(self, stylist_id, headers):
        return self._request("GET", f"/stylists/{stylist_id}", headers=headers)

    def list_stylists(self, headers, params=None):
        return self._request("GET", "/stylists", headers=headers, params=params)

    def update_stylist(self, stylist_id, payload, headers):
        return self._request("PATCH", f"/stylists/{stylist_id}", payload, headers)

    # ---- Resource ----
    def create_resource(self, payload, headers):
        return self._request("POST", "/resources", payload, headers)

    def get_resource(self, resource_id, headers):
        return self._request("GET", f"/resources/{resource_id}", headers=headers)

    def list_resources(self, headers, params=None):
        return self._request("GET", "/resources", headers=headers, params=params)

    # ---- Service ----
    def create_service(self, payload, headers):
        return self._request("POST", "/services", payload, headers)

    def get_service(self, service_id, headers):
        return self._request("GET", f"/services/{service_id}", headers=headers)

    def list_services(self, headers, params=None):
        return self._request("GET", "/services", headers=headers, params=params)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def dispute_no_show(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/dispute-no-show", payload, headers)

    # ---- MembershipPlan ----
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"/membership-plans/{plan_id}", headers=headers)

    def list_membership_plans(self, headers, params=None):
        return self._request("GET", "/membership-plans", headers=headers, params=params)

    # ---- Membership ----
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def lapse_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/lapse", {}, headers)

    def reinstate_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/reinstate", {}, headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel", {}, headers)

    # ---- Package ----
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/packages", headers=headers, params=params)

    # ---- PackagePurchase ----
    def create_package_purchase(self, payload, headers):
        return self._request("POST", "/package-purchases", payload, headers)

    def get_package_purchase(self, purchase_id, headers):
        return self._request("GET", f"/package-purchases/{purchase_id}", headers=headers)

    def list_package_purchases(self, headers, params=None):
        return self._request("GET", "/package-purchases", headers=headers, params=params)

    # ---- ProductSku ----
    def create_product_sku(self, payload, headers):
        return self._request("POST", "/product-skus", payload, headers)

    def get_product_sku(self, sku_id, headers):
        return self._request("GET", f"/product-skus/{sku_id}", headers=headers)

    def list_product_skus(self, headers, params=None):
        return self._request("GET", "/product-skus", headers=headers, params=params)

    def restock_product_sku(self, sku_id, payload, headers):
        return self._request("POST", f"/product-skus/{sku_id}/restock", payload, headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def confirm_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/confirm", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/no-show", {}, headers)

    # ---- Checkout ----
    def create_checkout(self, payload, headers):
        return self._request("POST", "/checkouts", payload, headers)

    def get_checkout(self, checkout_id, headers):
        return self._request("GET", f"/checkouts/{checkout_id}", headers=headers)

    def list_checkouts(self, headers, params=None):
        return self._request("GET", "/checkouts", headers=headers, params=params)

    def void_checkout(self, checkout_id, headers):
        return self._request("POST", f"/checkouts/{checkout_id}/void", {}, headers)

    def list_checkout_product_sales(self, checkout_id, headers, params=None):
        return self._request(
            "GET", f"/checkouts/{checkout_id}/product-sales", headers=headers, params=params
        )

    # ---- ProductSale ----
    def get_product_sale(self, sale_id, headers):
        return self._request("GET", f"/product-sales/{sale_id}", headers=headers)

    def list_product_sales(self, headers, params=None):
        return self._request("GET", "/product-sales", headers=headers, params=params)


api_client = ApiClient()
