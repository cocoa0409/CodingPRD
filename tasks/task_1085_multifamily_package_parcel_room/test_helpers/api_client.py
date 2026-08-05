"""API client: one method per endpoint of the Multifamily Package & Parcel Room API."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/parcelroom"


class ApiClient(GenericApiClient):
    # ─── Property ────────────────────────────────────────────────────────────
    def create_property(self, payload, headers):
        return self._request("POST", f"{BASE}/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"{BASE}/properties/{property_id}", headers=headers)

    def update_property_policy(self, property_id, payload, headers):
        return self._request("PATCH", f"{BASE}/properties/{property_id}/policy", payload, headers)

    def get_property_report(self, property_id, headers):
        return self._request("GET", f"{BASE}/properties/{property_id}/report", headers=headers)

    def aging_sweep(self, property_id, headers):
        return self._request("POST", f"{BASE}/properties/{property_id}/aging-sweep", {}, headers)

    def list_locker_banks(self, property_id, headers, params=None):
        return self._request("GET", f"{BASE}/properties/{property_id}/locker-banks",
                             headers=headers, params=params)

    def list_shelves(self, property_id, headers, params=None):
        return self._request("GET", f"{BASE}/properties/{property_id}/shelves",
                             headers=headers, params=params)

    def list_residents(self, property_id, headers, params=None):
        return self._request("GET", f"{BASE}/properties/{property_id}/residents",
                             headers=headers, params=params)

    def list_carriers(self, property_id, headers, params=None):
        return self._request("GET", f"{BASE}/properties/{property_id}/carriers",
                             headers=headers, params=params)

    # ─── LockerBank ──────────────────────────────────────────────────────────
    def create_locker_bank(self, payload, headers):
        return self._request("POST", f"{BASE}/locker-banks", payload, headers)

    def get_locker_bank(self, bank_id, headers):
        return self._request("GET", f"{BASE}/locker-banks/{bank_id}", headers=headers)

    def list_lockers(self, bank_id, headers, params=None):
        return self._request("GET", f"{BASE}/locker-banks/{bank_id}/lockers",
                             headers=headers, params=params)

    # ─── Locker ──────────────────────────────────────────────────────────────
    def create_locker(self, payload, headers):
        return self._request("POST", f"{BASE}/lockers", payload, headers)

    def get_locker(self, locker_id, headers):
        return self._request("GET", f"{BASE}/lockers/{locker_id}", headers=headers)

    def locker_out_of_service(self, locker_id, headers):
        return self._request("POST", f"{BASE}/lockers/{locker_id}/out-of-service", {}, headers)

    # ─── Shelf ───────────────────────────────────────────────────────────────
    def create_shelf(self, payload, headers):
        return self._request("POST", f"{BASE}/shelves", payload, headers)

    def get_shelf(self, shelf_id, headers):
        return self._request("GET", f"{BASE}/shelves/{shelf_id}", headers=headers)

    # ─── Resident ────────────────────────────────────────────────────────────
    def create_resident(self, payload, headers):
        return self._request("POST", f"{BASE}/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"{BASE}/residents/{resident_id}", headers=headers)

    def pms_sync(self, resident_id, payload, headers):
        return self._request("POST", f"{BASE}/residents/{resident_id}/pms-sync", payload, headers)

    # ─── Carrier ─────────────────────────────────────────────────────────────
    def create_carrier(self, payload, headers):
        return self._request("POST", f"{BASE}/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"{BASE}/carriers/{carrier_id}", headers=headers)

    # ─── Package ─────────────────────────────────────────────────────────────
    def create_package(self, payload, headers):
        return self._request("POST", f"{BASE}/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"{BASE}/packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", f"{BASE}/packages", headers=headers, params=params)

    def notify_package(self, package_id, payload, headers):
        return self._request("POST", f"{BASE}/packages/{package_id}/notify", payload, headers)

    def pickup_package(self, package_id, payload, headers):
        return self._request("POST", f"{BASE}/packages/{package_id}/pickup", payload, headers)

    def return_initiate(self, package_id, headers):
        return self._request("POST", f"{BASE}/packages/{package_id}/return-initiate", {}, headers)

    def return_complete(self, package_id, headers):
        return self._request("POST", f"{BASE}/packages/{package_id}/return-complete", {}, headers)

    def list_notifications(self, package_id, headers, params=None):
        return self._request("GET", f"{BASE}/packages/{package_id}/notifications",
                             headers=headers, params=params)

    def list_charges(self, package_id, headers, params=None):
        return self._request("GET", f"{BASE}/packages/{package_id}/charges",
                             headers=headers, params=params)

    # ─── RetailReturn ────────────────────────────────────────────────────────
    def create_retail_return(self, payload, headers):
        return self._request("POST", f"{BASE}/retail-returns", payload, headers)

    def get_retail_return(self, retail_return_id, headers):
        return self._request("GET", f"{BASE}/retail-returns/{retail_return_id}", headers=headers)

    def list_retail_returns(self, headers, params=None):
        return self._request("GET", f"{BASE}/retail-returns", headers=headers, params=params)

    def verify_label(self, retail_return_id, headers):
        return self._request("POST", f"{BASE}/retail-returns/{retail_return_id}/verify-label", {}, headers)

    def reject_return(self, retail_return_id, payload, headers):
        return self._request("POST", f"{BASE}/retail-returns/{retail_return_id}/reject", payload, headers)

    def carrier_pickup(self, retail_return_id, headers):
        return self._request("POST", f"{BASE}/retail-returns/{retail_return_id}/carrier-pickup", {}, headers)

    # ─── Logical clock (test-driving) ────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
