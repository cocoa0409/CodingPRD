"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Landlords ────────────────────────────────────────────────
    def create_landlord(self, payload, headers):
        return self._request("POST", "/hcv/landlords", payload, headers)

    def list_landlords(self, headers, params=None):
        return self._request("GET", "/hcv/landlords", headers=headers, params=params)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/hcv/landlords/{landlord_id}", headers=headers)

    def suspend_landlord(self, landlord_id, headers):
        return self._request("POST", f"/hcv/landlords/{landlord_id}/suspend", {}, headers)

    def reinstate_landlord(self, landlord_id, headers):
        return self._request("POST", f"/hcv/landlords/{landlord_id}/reinstate", {}, headers)

    def terminate_landlord(self, landlord_id, headers):
        return self._request("POST", f"/hcv/landlords/{landlord_id}/terminate", {}, headers)

    def list_landlord_properties(self, landlord_id, headers, params=None):
        return self._request(
            "GET", f"/hcv/landlords/{landlord_id}/properties", headers=headers, params=params
        )

    # ── Properties / Units ───────────────────────────────────────
    def create_property(self, payload, headers):
        return self._request("POST", "/hcv/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/hcv/properties/{property_id}", headers=headers)

    def list_property_units(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/hcv/properties/{property_id}/units", headers=headers, params=params
        )

    def create_unit(self, property_id, payload, headers):
        return self._request("POST", f"/hcv/properties/{property_id}/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/hcv/units/{unit_id}", headers=headers)

    def delist_unit(self, unit_id, headers):
        return self._request("POST", f"/hcv/units/{unit_id}/delist", {}, headers)

    def list_unit_contracts(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/hcv/units/{unit_id}/contracts", headers=headers, params=params
        )

    # ── Voucher families ─────────────────────────────────────────
    def create_voucher_family(self, payload, headers):
        return self._request("POST", "/hcv/voucher-families", payload, headers)

    def get_voucher_family(self, family_id, headers):
        return self._request("GET", f"/hcv/voucher-families/{family_id}", headers=headers)

    def exit_voucher_family(self, family_id, headers):
        return self._request("POST", f"/hcv/voucher-families/{family_id}/exit", {}, headers)

    def list_family_portability_actions(self, family_id, headers, params=None):
        return self._request(
            "GET",
            f"/hcv/voucher-families/{family_id}/portability-actions",
            headers=headers,
            params=params,
        )

    # ── Payment standards / rent comparables ─────────────────────
    def create_payment_standard(self, payload, headers):
        return self._request("POST", "/hcv/payment-standards", payload, headers)

    def list_payment_standards(self, headers, params=None):
        return self._request("GET", "/hcv/payment-standards", headers=headers, params=params)

    def create_rent_comparable(self, payload, headers):
        return self._request("POST", "/hcv/rent-comparables", payload, headers)

    def list_rent_comparables(self, headers, params=None):
        return self._request("GET", "/hcv/rent-comparables", headers=headers, params=params)

    # ── HAP contracts ────────────────────────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", "/hcv/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/hcv/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/hcv/contracts/{contract_id}", headers=headers)

    def submit_contract(self, contract_id, headers):
        return self._request("POST", f"/hcv/contracts/{contract_id}/submit", {}, headers)

    def withdraw_contract(self, contract_id, headers):
        return self._request("POST", f"/hcv/contracts/{contract_id}/withdraw", {}, headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/hcv/contracts/{contract_id}/activate", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/hcv/contracts/{contract_id}/terminate", {}, headers)

    def list_contract_inspections(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/hcv/contracts/{contract_id}/inspections", headers=headers, params=params
        )

    def list_contract_hap_payments(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/hcv/contracts/{contract_id}/hap-payments", headers=headers, params=params
        )

    def list_contract_rent_increase_requests(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/hcv/contracts/{contract_id}/rent-increase-requests",
            headers=headers,
            params=params,
        )

    def list_contract_recertifications(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/hcv/contracts/{contract_id}/recertifications",
            headers=headers,
            params=params,
        )

    # ── Inspections / repair items ───────────────────────────────
    def schedule_inspection(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/hcv/contracts/{contract_id}/inspections", payload, headers
        )

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/hcv/inspections/{inspection_id}", headers=headers)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/hcv/inspections/{inspection_id}/record-result", payload, headers
        )

    def request_reinspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/hcv/inspections/{inspection_id}/request-reinspection", {}, headers
        )

    def list_inspection_repair_items(self, inspection_id, headers, params=None):
        return self._request(
            "GET",
            f"/hcv/inspections/{inspection_id}/repair-items",
            headers=headers,
            params=params,
        )

    def create_repair_item(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/hcv/inspections/{inspection_id}/repair-items", payload, headers
        )

    def mark_repair_item_repaired(self, repair_item_id, headers):
        return self._request(
            "POST", f"/hcv/repair-items/{repair_item_id}/mark-repaired", {}, headers
        )

    def verify_repair_item(self, repair_item_id, payload, headers):
        return self._request(
            "POST", f"/hcv/repair-items/{repair_item_id}/verify", payload, headers
        )

    # ── Rent increase requests ───────────────────────────────────
    def create_rent_increase_request(self, payload, headers):
        return self._request("POST", "/hcv/rent-increase-requests", payload, headers)

    def get_rent_increase_request(self, request_id, headers):
        return self._request(
            "GET", f"/hcv/rent-increase-requests/{request_id}", headers=headers
        )

    def approve_rent_increase_request(self, request_id, headers):
        return self._request(
            "POST", f"/hcv/rent-increase-requests/{request_id}/approve", {}, headers
        )

    def deny_rent_increase_request(self, request_id, headers):
        return self._request(
            "POST", f"/hcv/rent-increase-requests/{request_id}/deny", {}, headers
        )

    def withdraw_rent_increase_request(self, request_id, headers):
        return self._request(
            "POST", f"/hcv/rent-increase-requests/{request_id}/withdraw", {}, headers
        )

    # ── Recertifications ─────────────────────────────────────────
    def create_recertification(self, payload, headers):
        return self._request("POST", "/hcv/recertifications", payload, headers)

    def get_recertification(self, recertification_id, headers):
        return self._request(
            "GET", f"/hcv/recertifications/{recertification_id}", headers=headers
        )

    def complete_recertification(self, recertification_id, payload, headers):
        return self._request(
            "POST",
            f"/hcv/recertifications/{recertification_id}/complete",
            payload,
            headers,
        )

    # ── HAP payments ─────────────────────────────────────────────
    def disburse_hap_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/hcv/hap-payments/{payment_id}/disburse", {}, headers
        )

    # ── Portability actions ──────────────────────────────────────
    def create_portability_action(self, payload, headers):
        return self._request("POST", "/hcv/portability-actions", payload, headers)

    def get_portability_action(self, action_id, headers):
        return self._request("GET", f"/hcv/portability-actions/{action_id}", headers=headers)

    def accept_portability_billing(self, action_id, headers):
        return self._request(
            "POST", f"/hcv/portability-actions/{action_id}/accept-billing", {}, headers
        )

    def absorb_portability_action(self, action_id, headers):
        return self._request(
            "POST", f"/hcv/portability-actions/{action_id}/absorb", {}, headers
        )

    def terminate_portability_action(self, action_id, headers):
        return self._request(
            "POST", f"/hcv/portability-actions/{action_id}/terminate", {}, headers
        )

    # ── Logical clock (PRD §2.7) ─────────────────────────────────
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/hcv/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
