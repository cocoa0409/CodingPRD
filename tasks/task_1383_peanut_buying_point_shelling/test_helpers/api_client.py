"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- BuyingPoint / ops / clock ---
    def create_buying_point(self, payload, headers):
        return self._request("POST", "/buying-points", payload, headers)

    def get_buying_point(self, buying_point_id, headers):
        return self._request("GET", f"/buying-points/{buying_point_id}",
                             headers=headers)

    def run_ops(self, buying_point_id, headers):
        return self._request("POST", f"/buying-points/{buying_point_id}/run_ops",
                             headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Grower ---
    def create_grower(self, payload, headers):
        return self._request("POST", "/buying-points/growers", payload, headers)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/buying-points/growers/{grower_id}",
                             headers=headers)

    def list_growers(self, headers, params=None):
        return self._request("GET", "/buying-points/growers",
                             headers=headers, params=params)

    def suspend_grower(self, grower_id, headers):
        return self._request("POST", f"/buying-points/growers/{grower_id}/suspend",
                             headers=headers)

    def reinstate_grower(self, grower_id, headers):
        return self._request("POST",
                             f"/buying-points/growers/{grower_id}/reinstate",
                             headers=headers)

    # --- DiscountSchedule ---
    def create_discount_schedule(self, payload, headers):
        return self._request("POST", "/buying-points/discount-schedules",
                             payload, headers)

    def get_discount_schedule(self, schedule_id, headers):
        return self._request("GET", f"/buying-points/discount-schedules/{schedule_id}",
                             headers=headers)

    def list_discount_schedules(self, headers, params=None):
        return self._request("GET", "/buying-points/discount-schedules",
                             headers=headers, params=params)

    def activate_discount_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"/buying-points/discount-schedules/{schedule_id}/activate",
            headers=headers)

    def retire_discount_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"/buying-points/discount-schedules/{schedule_id}/retire",
            headers=headers)

    # --- FarmerStockLoad ---
    def create_load(self, payload, headers):
        return self._request("POST", "/buying-points/loads", payload, headers)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/buying-points/loads/{load_id}",
                             headers=headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/buying-points/loads",
                             headers=headers, params=params)

    def weigh_load(self, load_id, payload, headers):
        return self._request("POST", f"/buying-points/loads/{load_id}/weigh",
                             payload, headers)

    # --- GradeSheet ---
    def create_grade_sheet(self, load_id, payload, headers):
        return self._request("POST", f"/buying-points/loads/{load_id}/grade-sheets",
                             payload, headers)

    def get_grade_sheet(self, sheet_id, headers):
        return self._request("GET", f"/buying-points/grade-sheets/{sheet_id}",
                             headers=headers)

    def list_grade_sheets(self, headers, params=None):
        return self._request("GET", "/buying-points/grade-sheets",
                             headers=headers, params=params)

    def finalize_grade_sheet(self, sheet_id, headers):
        return self._request(
            "POST", f"/buying-points/grade-sheets/{sheet_id}/finalize",
            headers=headers)

    # --- AflatoxinCertificate ---
    def create_aflatoxin_certificate(self, load_id, payload, headers):
        return self._request(
            "POST", f"/buying-points/loads/{load_id}/aflatoxin-certificates",
            payload, headers)

    def get_aflatoxin_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/buying-points/aflatoxin-certificates/{certificate_id}",
            headers=headers)

    def list_aflatoxin_certificates(self, headers, params=None):
        return self._request("GET", "/buying-points/aflatoxin-certificates",
                             headers=headers, params=params)

    def record_aflatoxin_result(self, certificate_id, payload, headers):
        return self._request(
            "POST",
            f"/buying-points/aflatoxin-certificates/{certificate_id}/record-result",
            payload, headers)

    def confirm_aflatoxin_certificate(self, certificate_id, headers):
        return self._request(
            "POST",
            f"/buying-points/aflatoxin-certificates/{certificate_id}/confirm",
            headers=headers)

    def order_retest(self, certificate_id, headers):
        return self._request(
            "POST",
            f"/buying-points/aflatoxin-certificates/{certificate_id}/order-retest",
            headers=headers)

    # --- Dryer / DryerBooking ---
    def create_dryer(self, payload, headers):
        return self._request("POST", "/buying-points/dryers", payload, headers)

    def get_dryer(self, dryer_id, headers):
        return self._request("GET", f"/buying-points/dryers/{dryer_id}",
                             headers=headers)

    def list_dryers(self, headers, params=None):
        return self._request("GET", "/buying-points/dryers",
                             headers=headers, params=params)

    def create_dryer_booking(self, payload, headers):
        return self._request("POST", "/buying-points/dryer-bookings",
                             payload, headers)

    def get_dryer_booking(self, booking_id, headers):
        return self._request("GET", f"/buying-points/dryer-bookings/{booking_id}",
                             headers=headers)

    def list_dryer_bookings(self, headers, params=None):
        return self._request("GET", "/buying-points/dryer-bookings",
                             headers=headers, params=params)

    def complete_dryer_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/buying-points/dryer-bookings/{booking_id}/complete",
            payload, headers)

    def cancel_dryer_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/buying-points/dryer-bookings/{booking_id}/cancel",
            headers=headers)

    # --- Warehouse / StorageReceipt ---
    def create_warehouse(self, payload, headers):
        return self._request("POST", "/buying-points/warehouses", payload, headers)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"/buying-points/warehouses/{warehouse_id}",
                             headers=headers)

    def list_warehouses(self, headers, params=None):
        return self._request("GET", "/buying-points/warehouses",
                             headers=headers, params=params)

    def create_storage_receipt(self, payload, headers):
        return self._request("POST", "/buying-points/storage-receipts",
                             payload, headers)

    def get_storage_receipt(self, receipt_id, headers):
        return self._request("GET", f"/buying-points/storage-receipts/{receipt_id}",
                             headers=headers)

    def list_storage_receipts(self, headers, params=None):
        return self._request("GET", "/buying-points/storage-receipts",
                             headers=headers, params=params)

    # --- LoanPledge ---
    def create_loan_pledge(self, payload, headers):
        return self._request("POST", "/buying-points/loan-pledges",
                             payload, headers)

    def get_loan_pledge(self, pledge_id, headers):
        return self._request("GET", f"/buying-points/loan-pledges/{pledge_id}",
                             headers=headers)

    def list_loan_pledges(self, headers, params=None):
        return self._request("GET", "/buying-points/loan-pledges",
                             headers=headers, params=params)

    def repay_loan_pledge(self, pledge_id, payload, headers):
        return self._request("POST",
                             f"/buying-points/loan-pledges/{pledge_id}/repay",
                             payload, headers)

    def foreclose_loan_pledge(self, pledge_id, headers):
        return self._request("POST",
                             f"/buying-points/loan-pledges/{pledge_id}/foreclose",
                             headers=headers)

    # --- ShellerContract ---
    def create_sheller_contract(self, payload, headers):
        return self._request("POST", "/buying-points/sheller-contracts",
                             payload, headers)

    def get_sheller_contract(self, contract_id, headers):
        return self._request("GET", f"/buying-points/sheller-contracts/{contract_id}",
                             headers=headers)

    def list_sheller_contracts(self, headers, params=None):
        return self._request("GET", "/buying-points/sheller-contracts",
                             headers=headers, params=params)

    def activate_sheller_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/buying-points/sheller-contracts/{contract_id}/activate",
            headers=headers)

    def cancel_sheller_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/buying-points/sheller-contracts/{contract_id}/cancel",
            headers=headers)

    # --- DeliveryCall ---
    def create_delivery_call(self, payload, headers):
        return self._request("POST", "/buying-points/delivery-calls",
                             payload, headers)

    def get_delivery_call(self, call_id, headers):
        return self._request("GET", f"/buying-points/delivery-calls/{call_id}",
                             headers=headers)

    def list_delivery_calls(self, headers, params=None):
        return self._request("GET", "/buying-points/delivery-calls",
                             headers=headers, params=params)

    def allocate_delivery_call(self, call_id, payload, headers):
        return self._request(
            "POST", f"/buying-points/delivery-calls/{call_id}/allocate",
            payload, headers)

    def deliver_delivery_call(self, call_id, headers):
        return self._request(
            "POST", f"/buying-points/delivery-calls/{call_id}/deliver",
            headers=headers)

    def reconcile_delivery_call(self, call_id, payload, headers):
        return self._request(
            "POST", f"/buying-points/delivery-calls/{call_id}/reconcile",
            payload, headers)

    def cancel_delivery_call(self, call_id, headers):
        return self._request(
            "POST", f"/buying-points/delivery-calls/{call_id}/cancel",
            headers=headers)

    # --- AllocationLine (read-only junction) ---
    def get_allocation_line(self, line_id, headers):
        return self._request("GET", f"/buying-points/allocation-lines/{line_id}",
                             headers=headers)

    def list_allocation_lines(self, headers, params=None):
        return self._request("GET", "/buying-points/allocation-lines",
                             headers=headers, params=params)

    # --- Settlement ---
    def compute_settlement(self, grower_id, payload, headers):
        return self._request("POST",
                             f"/buying-points/growers/{grower_id}/settlements",
                             payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/buying-points/settlements/{settlement_id}",
                             headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/buying-points/settlements",
                             headers=headers, params=params)

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST",
                             f"/buying-points/settlements/{settlement_id}/approve",
                             headers=headers)

    def dispute_settlement(self, settlement_id, headers):
        return self._request("POST",
                             f"/buying-points/settlements/{settlement_id}/dispute",
                             headers=headers)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST",
                             f"/buying-points/settlements/{settlement_id}/pay",
                             headers=headers)

    def void_settlement(self, settlement_id, headers):
        return self._request("POST",
                             f"/buying-points/settlements/{settlement_id}/void",
                             headers=headers)

    # --- QuotaHistory ---
    def create_quota_history(self, payload, headers):
        return self._request("POST", "/buying-points/quota-histories",
                             payload, headers)

    def get_quota_history(self, quota_history_id, headers):
        return self._request("GET",
                             f"/buying-points/quota-histories/{quota_history_id}",
                             headers=headers)

    def list_quota_histories(self, headers, params=None):
        return self._request("GET", "/buying-points/quota-histories",
                             headers=headers, params=params)

    # --- HullLot ---
    def get_hull_lot(self, lot_id, headers):
        return self._request("GET", f"/buying-points/hull-lots/{lot_id}",
                             headers=headers)

    def list_hull_lots(self, headers, params=None):
        return self._request("GET", "/buying-points/hull-lots",
                             headers=headers, params=params)

    def list_hull_lot_for_sale(self, lot_id, payload, headers):
        return self._request("POST",
                             f"/buying-points/hull-lots/{lot_id}/list-for-sale",
                             payload, headers)

    def sell_hull_lot(self, lot_id, headers):
        return self._request("POST", f"/buying-points/hull-lots/{lot_id}/sell",
                             headers=headers)

    def dispose_hull_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/buying-points/hull-lots/{lot_id}/dispose",
                             payload, headers)


api_client = ApiClient()
