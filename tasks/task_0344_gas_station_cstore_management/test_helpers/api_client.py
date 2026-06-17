"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Station ----
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    # ---- FuelGrade ----
    def create_fuel_grade(self, payload, headers):
        return self._request("POST", "/fuel-grades", payload, headers)

    def list_fuel_grades(self, headers, params=None):
        return self._request("GET", "/fuel-grades", headers=headers, params=params)

    def get_fuel_grade(self, grade_id, headers):
        return self._request("GET", f"/fuel-grades/{grade_id}", headers=headers)

    def reprice_fuel_grade(self, grade_id, payload, headers):
        return self._request("POST", f"/fuel-grades/{grade_id}/reprice", payload, headers)

    # ---- Tank ----
    def create_tank(self, payload, headers):
        return self._request("POST", "/tanks", payload, headers)

    def list_tanks(self, headers, params=None):
        return self._request("GET", "/tanks", headers=headers, params=params)

    def get_tank(self, tank_id, headers):
        return self._request("GET", f"/tanks/{tank_id}", headers=headers)

    def take_down_tank(self, tank_id, headers, payload=None):
        return self._request("POST", f"/tanks/{tank_id}/take-down", payload or {}, headers)

    def restore_tank(self, tank_id, headers, payload=None):
        return self._request("POST", f"/tanks/{tank_id}/restore", payload or {}, headers)

    # ---- Pump ----
    def create_pump(self, payload, headers):
        return self._request("POST", "/pumps", payload, headers)

    def list_pumps(self, headers, params=None):
        return self._request("GET", "/pumps", headers=headers, params=params)

    def get_pump(self, pump_id, headers):
        return self._request("GET", f"/pumps/{pump_id}", headers=headers)

    # ---- Delivery ----
    def create_delivery(self, payload, headers):
        return self._request("POST", "/deliveries", payload, headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def post_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/post", payload, headers)

    def reject_delivery(self, delivery_id, headers, payload=None):
        return self._request("POST", f"/deliveries/{delivery_id}/reject", payload or {}, headers)

    def void_delivery(self, delivery_id, headers, payload=None):
        return self._request("POST", f"/deliveries/{delivery_id}/void", payload or {}, headers)

    # ---- Shift ----
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def record_drop(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/drops", payload, headers)

    def begin_count_shift(self, shift_id, headers, payload=None):
        return self._request("POST", f"/shifts/{shift_id}/begin-count", payload or {}, headers)

    def close_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/close", payload, headers)

    # ---- FuelTransaction ----
    def create_fuel_transaction(self, payload, headers):
        return self._request("POST", "/fuel-transactions", payload, headers)

    def list_fuel_transactions(self, headers, params=None):
        return self._request("GET", "/fuel-transactions", headers=headers, params=params)

    def get_fuel_transaction(self, txn_id, headers):
        return self._request("GET", f"/fuel-transactions/{txn_id}", headers=headers)

    def capture_fuel_transaction(self, txn_id, headers, payload=None):
        return self._request("POST", f"/fuel-transactions/{txn_id}/capture", payload or {}, headers)

    def settle_fuel_transaction(self, txn_id, payload, headers):
        return self._request("POST", f"/fuel-transactions/{txn_id}/settle", payload, headers)

    def reverse_fuel_transaction(self, txn_id, headers, payload=None):
        return self._request("POST", f"/fuel-transactions/{txn_id}/reverse", payload or {}, headers)

    # ---- StoreTransaction ----
    def create_store_transaction(self, payload, headers):
        return self._request("POST", "/store-transactions", payload, headers)

    def list_store_transactions(self, headers, params=None):
        return self._request("GET", "/store-transactions", headers=headers, params=params)

    def get_store_transaction(self, store_txn_id, headers):
        return self._request("GET", f"/store-transactions/{store_txn_id}", headers=headers)

    def reverse_store_transaction(self, store_txn_id, headers, payload=None):
        return self._request("POST", f"/store-transactions/{store_txn_id}/reverse", payload or {}, headers)

    # ---- LoyaltyAccount ----
    def create_loyalty_account(self, payload, headers):
        return self._request("POST", "/loyalty-accounts", payload, headers)

    def list_loyalty_accounts(self, headers, params=None):
        return self._request("GET", "/loyalty-accounts", headers=headers, params=params)

    def get_loyalty_account(self, loyalty_id, headers):
        return self._request("GET", f"/loyalty-accounts/{loyalty_id}", headers=headers)

    def redeem_points(self, loyalty_id, payload, headers):
        return self._request("POST", f"/loyalty-accounts/{loyalty_id}/redeem", payload, headers)

    # ---- CarWashCode ----
    def create_car_wash_code(self, payload, headers):
        return self._request("POST", "/car-wash-codes", payload, headers)

    def list_car_wash_codes(self, headers, params=None):
        return self._request("GET", "/car-wash-codes", headers=headers, params=params)

    def get_car_wash_code(self, code_id, headers):
        return self._request("GET", f"/car-wash-codes/{code_id}", headers=headers)

    def redeem_car_wash_code(self, code_id, headers, payload=None):
        return self._request("POST", f"/car-wash-codes/{code_id}/redeem", payload or {}, headers)

    def reissue_car_wash_code(self, code_id, headers, payload=None):
        return self._request("POST", f"/car-wash-codes/{code_id}/reissue", payload or {}, headers)

    # ---- MarginReport ----
    def create_margin_report(self, payload, headers):
        return self._request("POST", "/margin-reports", payload, headers)


api_client = ApiClient()
