"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----------------------------- Resort ----------------------------------- #
    def create_resort(self, payload, headers):
        return self._request("POST", "/resorts", payload, headers)

    def get_resort(self, resort_id, headers):
        return self._request("GET", f"/resorts/{resort_id}", headers=headers)

    def rollover_use_year(self, resort_id, headers, payload=None):
        return self._request(
            "POST", f"/resorts/{resort_id}/rollover-use-year",
            payload if payload is not None else {}, headers,
        )

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----------------------------- Owner ------------------------------------ #
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/owners", headers=headers, params=params)

    # -------------------------- InventoryUnit ------------------------------- #
    def create_inventory_unit(self, payload, headers):
        return self._request("POST", "/inventory-units", payload, headers)

    def get_inventory_unit(self, unit_id, headers):
        return self._request("GET", f"/inventory-units/{unit_id}", headers=headers)

    def list_inventory_units(self, headers, params=None):
        return self._request("GET", "/inventory-units", headers=headers, params=params)

    # ----------------------------- Contract --------------------------------- #
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/contracts/{contract_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def rescind_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/contracts/{contract_id}/rescind",
            payload if payload is not None else {}, headers,
        )

    # -------------------------- PointsAccount ------------------------------- #
    def get_points_account(self, account_id, headers):
        return self._request("GET", f"/points-accounts/{account_id}", headers=headers)

    def list_points_accounts(self, headers, params=None):
        return self._request("GET", "/points-accounts", headers=headers, params=params)

    def bank_points(self, account_id, payload, headers):
        return self._request("POST", f"/points-accounts/{account_id}/bank", payload, headers)

    # ---------------------------- Reservation ------------------------------- #
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/reservations/{reservation_id}/confirm",
            payload if payload is not None else {}, headers,
        )

    def cancel_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def complete_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/reservations/{reservation_id}/complete",
            payload if payload is not None else {}, headers,
        )

    def deposit_exchange(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/deposit-exchange", payload, headers,
        )

    # -------------------------- ExchangeDeposit ----------------------------- #
    def get_exchange_deposit(self, deposit_id, headers):
        return self._request("GET", f"/exchange-deposits/{deposit_id}", headers=headers)

    def list_exchange_deposits(self, headers, params=None):
        return self._request("GET", "/exchange-deposits", headers=headers, params=params)

    def redeem_exchange_deposit(self, deposit_id, headers, payload=None):
        return self._request(
            "POST", f"/exchange-deposits/{deposit_id}/redeem",
            payload if payload is not None else {}, headers,
        )

    def recall_exchange_deposit(self, deposit_id, headers, payload=None):
        return self._request(
            "POST", f"/exchange-deposits/{deposit_id}/recall",
            payload if payload is not None else {}, headers,
        )

    # ----------------------- MaintenanceFeeInvoice -------------------------- #
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/issue",
            payload if payload is not None else {}, headers,
        )

    def mark_invoice_delinquent(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/mark-delinquent",
            payload if payload is not None else {}, headers,
        )

    # ----------------------------- Payment ---------------------------------- #
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def clear_payment(self, payment_id, headers, payload=None):
        return self._request(
            "POST", f"/payments/{payment_id}/clear",
            payload if payload is not None else {}, headers,
        )

    def fail_payment(self, payment_id, headers, payload=None):
        return self._request(
            "POST", f"/payments/{payment_id}/fail",
            payload if payload is not None else {}, headers,
        )

    def reverse_payment(self, payment_id, headers, payload=None):
        return self._request(
            "POST", f"/payments/{payment_id}/reverse",
            payload if payload is not None else {}, headers,
        )

    # ------------------------- SpecialAssessment ---------------------------- #
    def create_special_assessment(self, payload, headers):
        return self._request("POST", "/special-assessments", payload, headers)

    def get_special_assessment(self, assessment_id, headers):
        return self._request("GET", f"/special-assessments/{assessment_id}", headers=headers)

    def list_special_assessments(self, headers, params=None):
        return self._request("GET", "/special-assessments", headers=headers, params=params)

    def levy_special_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/special-assessments/{assessment_id}/levy", payload, headers,
        )

    # --------------------------- ResaleTransfer ----------------------------- #
    def create_resale_transfer(self, payload, headers):
        return self._request("POST", "/resale-transfers", payload, headers)

    def get_resale_transfer(self, transfer_id, headers):
        return self._request("GET", f"/resale-transfers/{transfer_id}", headers=headers)

    def list_resale_transfers(self, headers, params=None):
        return self._request("GET", "/resale-transfers", headers=headers, params=params)

    def complete_resale_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST", f"/resale-transfers/{transfer_id}/complete",
            payload if payload is not None else {}, headers,
        )

    def rescind_resale_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST", f"/resale-transfers/{transfer_id}/rescind",
            payload if payload is not None else {}, headers,
        )

    # -------------------------- DelinquencyCase ----------------------------- #
    def get_delinquency_case(self, case_id, headers):
        return self._request("GET", f"/delinquency-cases/{case_id}", headers=headers)

    def list_delinquency_cases(self, headers, params=None):
        return self._request("GET", "/delinquency-cases", headers=headers, params=params)

    def escalate_delinquency_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/delinquency-cases/{case_id}/escalate",
            payload if payload is not None else {}, headers,
        )

    def foreclose_delinquency_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/delinquency-cases/{case_id}/foreclose",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()
