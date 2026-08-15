"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Suppliers & regulatory documents (PRD §3.1)
    # ------------------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", "/tissue-bank/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/tissue-bank/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/tissue-bank/suppliers/{supplier_id}", headers=headers)

    def approve_supplier(self, supplier_id, headers):
        return self._request("POST", f"/tissue-bank/suppliers/{supplier_id}/approve", {}, headers)

    def suspend_supplier(self, supplier_id, headers):
        return self._request("POST", f"/tissue-bank/suppliers/{supplier_id}/suspend", {}, headers)

    def reinstate_supplier(self, supplier_id, headers):
        return self._request("POST", f"/tissue-bank/suppliers/{supplier_id}/reinstate", {}, headers)

    def disqualify_supplier(self, supplier_id, headers):
        return self._request("POST", f"/tissue-bank/suppliers/{supplier_id}/disqualify", {}, headers)

    def list_supplier_documents(self, supplier_id, headers, params=None):
        return self._request(
            "GET", f"/tissue-bank/suppliers/{supplier_id}/documents", headers=headers, params=params
        )

    def create_supplier_document(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"/tissue-bank/suppliers/{supplier_id}/documents", payload, headers
        )

    def verify_document(self, supplier_id, doc_id, headers):
        return self._request(
            "POST", f"/tissue-bank/suppliers/{supplier_id}/documents/{doc_id}/verify", {}, headers
        )

    def reject_document(self, supplier_id, doc_id, headers):
        return self._request(
            "POST", f"/tissue-bank/suppliers/{supplier_id}/documents/{doc_id}/reject", {}, headers
        )

    def list_supplier_shipments(self, supplier_id, headers):
        return self._request(
            "GET", f"/tissue-bank/suppliers/{supplier_id}/shipments", headers=headers
        )

    def list_supplier_recalls(self, supplier_id, headers):
        return self._request(
            "GET", f"/tissue-bank/suppliers/{supplier_id}/recalls", headers=headers
        )

    # ------------------------------------------------------------------
    # Shipments & tissue units (PRD §3.2, §3.4)
    # ------------------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", "/tissue-bank/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/tissue-bank/shipments/{shipment_id}", headers=headers)

    def accept_shipment(self, shipment_id, headers):
        return self._request("POST", f"/tissue-bank/shipments/{shipment_id}/accept", {}, headers)

    def reject_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/tissue-bank/shipments/{shipment_id}/reject", payload, headers
        )

    def list_tissue_units(self, headers, params=None):
        return self._request("GET", "/tissue-bank/tissue-units", headers=headers, params=params)

    def get_tissue_unit(self, unit_id, headers):
        return self._request("GET", f"/tissue-bank/tissue-units/{unit_id}", headers=headers)

    def release_unit(self, unit_id, headers):
        return self._request("POST", f"/tissue-bank/tissue-units/{unit_id}/release", {}, headers)

    def hold_unit(self, unit_id, headers):
        return self._request("POST", f"/tissue-bank/tissue-units/{unit_id}/hold", {}, headers)

    def issue_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/tissue-bank/tissue-units/{unit_id}/issue", payload, headers)

    def return_unit_to_stock(self, unit_id, headers):
        return self._request(
            "POST", f"/tissue-bank/tissue-units/{unit_id}/return-to-stock", {}, headers
        )

    def discard_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/tissue-bank/tissue-units/{unit_id}/discard", payload, headers)

    def return_unit_to_supplier(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/tissue-bank/tissue-units/{unit_id}/return-to-supplier", payload, headers
        )

    def list_unit_reservations(self, unit_id, headers):
        return self._request(
            "GET", f"/tissue-bank/tissue-units/{unit_id}/reservations", headers=headers
        )

    def list_unit_disposition_records(self, unit_id, headers):
        return self._request(
            "GET", f"/tissue-bank/tissue-units/{unit_id}/disposition-records", headers=headers
        )

    def list_unit_adverse_reactions(self, unit_id, headers):
        return self._request(
            "GET", f"/tissue-bank/tissue-units/{unit_id}/adverse-reactions", headers=headers
        )

    # ------------------------------------------------------------------
    # Freezers, readings, excursions (PRD §3.3)
    # ------------------------------------------------------------------
    def create_freezer(self, payload, headers):
        return self._request("POST", "/tissue-bank/freezers", payload, headers)

    def list_freezers(self, headers, params=None):
        return self._request("GET", "/tissue-bank/freezers", headers=headers, params=params)

    def get_freezer(self, freezer_id, headers):
        return self._request("GET", f"/tissue-bank/freezers/{freezer_id}", headers=headers)

    def update_freezer(self, freezer_id, payload, headers):
        return self._request("PUT", f"/tissue-bank/freezers/{freezer_id}", payload, headers)

    def create_reading(self, freezer_id, payload, headers):
        return self._request(
            "POST", f"/tissue-bank/freezers/{freezer_id}/readings", payload, headers
        )

    def list_readings(self, freezer_id, headers):
        return self._request("GET", f"/tissue-bank/freezers/{freezer_id}/readings", headers=headers)

    def report_excursion(self, freezer_id, payload, headers):
        return self._request(
            "POST", f"/tissue-bank/freezers/{freezer_id}/excursions", payload, headers
        )

    def list_freezer_excursions(self, freezer_id, headers):
        return self._request(
            "GET", f"/tissue-bank/freezers/{freezer_id}/excursions", headers=headers
        )

    def list_freezer_units(self, freezer_id, headers):
        return self._request("GET", f"/tissue-bank/freezers/{freezer_id}/units", headers=headers)

    def list_freezer_shipments(self, freezer_id, headers):
        return self._request(
            "GET", f"/tissue-bank/freezers/{freezer_id}/shipments", headers=headers
        )

    def get_excursion(self, excursion_id, headers):
        return self._request("GET", f"/tissue-bank/excursions/{excursion_id}", headers=headers)

    def investigate_excursion(self, excursion_id, headers):
        return self._request(
            "POST", f"/tissue-bank/excursions/{excursion_id}/investigate", {}, headers
        )

    def resolve_excursion(self, excursion_id, payload, headers):
        return self._request(
            "POST", f"/tissue-bank/excursions/{excursion_id}/resolve", payload, headers
        )

    def list_excursion_readings(self, excursion_id, headers):
        return self._request("GET", f"/tissue-bank/excursions/{excursion_id}/readings", headers=headers)

    # ------------------------------------------------------------------
    # Implant cases & reservations (PRD §3.5)
    # ------------------------------------------------------------------
    def create_implant_case(self, payload, headers):
        return self._request("POST", "/tissue-bank/implant-cases", payload, headers)

    def get_implant_case(self, case_id, headers):
        return self._request("GET", f"/tissue-bank/implant-cases/{case_id}", headers=headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/tissue-bank/implant-cases/{case_id}/cancel", {}, headers)

    def complete_case(self, case_id, headers):
        return self._request("POST", f"/tissue-bank/implant-cases/{case_id}/complete", {}, headers)

    def record_implantation(self, case_id, payload, headers):
        return self._request(
            "POST", f"/tissue-bank/implant-cases/{case_id}/record-implantation", payload, headers
        )

    def create_reservation(self, case_id, payload, headers):
        return self._request(
            "POST", f"/tissue-bank/implant-cases/{case_id}/reservations", payload, headers
        )

    def list_case_reservations(self, case_id, headers):
        return self._request(
            "GET", f"/tissue-bank/implant-cases/{case_id}/reservations", headers=headers
        )

    def list_case_adverse_reactions(self, case_id, headers):
        return self._request(
            "GET", f"/tissue-bank/implant-cases/{case_id}/adverse-reactions", headers=headers
        )

    def report_adverse_reaction(self, case_id, payload, headers):
        return self._request(
            "POST", f"/tissue-bank/implant-cases/{case_id}/adverse-reactions", payload, headers
        )

    def release_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/tissue-bank/reservations/{reservation_id}/release", {}, headers
        )

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/tissue-bank/reservations/{reservation_id}", headers=headers)

    # ------------------------------------------------------------------
    # Recalls (PRD §3.6)
    # ------------------------------------------------------------------
    def create_recall(self, payload, headers):
        return self._request("POST", "/tissue-bank/recalls", payload, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/tissue-bank/recalls/{recall_id}", headers=headers)

    def activate_recall(self, recall_id, headers):
        return self._request("POST", f"/tissue-bank/recalls/{recall_id}/activate", {}, headers)

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"/tissue-bank/recalls/{recall_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Adverse reaction cases (PRD §3.7)
    # ------------------------------------------------------------------
    def get_adverse_reaction(self, adverse_id, headers):
        return self._request("GET", f"/tissue-bank/adverse-reactions/{adverse_id}", headers=headers)

    def investigate_adverse_reaction(self, adverse_id, headers):
        return self._request(
            "POST", f"/tissue-bank/adverse-reactions/{adverse_id}/investigate", {}, headers
        )

    def resolve_adverse_reaction(self, adverse_id, payload, headers):
        return self._request(
            "POST", f"/tissue-bank/adverse-reactions/{adverse_id}/resolve", payload, headers
        )

    def reopen_adverse_reaction(self, adverse_id, payload, headers):
        return self._request(
            "POST", f"/tissue-bank/adverse-reactions/{adverse_id}/reopen", payload, headers
        )

    # ------------------------------------------------------------------
    # Par-level policies & valuation (PRD §3.9)
    # ------------------------------------------------------------------
    def create_par_policy(self, payload, headers):
        return self._request("POST", "/tissue-bank/par-level-policies", payload, headers)

    def get_par_policy(self, policy_id, headers):
        return self._request("GET", f"/tissue-bank/par-level-policies/{policy_id}", headers=headers)

    def update_par_policy(self, policy_id, payload, headers):
        return self._request("PUT", f"/tissue-bank/par-level-policies/{policy_id}", payload, headers)

    def get_inventory_valuation(self, tissue_type, method, headers):
        return self._request(
            "GET",
            "/tissue-bank/inventory/valuation",
            {"tissue_type": tissue_type, "method": method},
            headers,
        )

    # ------------------------------------------------------------------
    # Disposition records & retention (PRD §2.11)
    # ------------------------------------------------------------------
    def get_disposition_record(self, record_id, headers):
        return self._request(
            "GET", f"/tissue-bank/disposition-records/{record_id}", headers=headers
        )

    def finalize_disposition_record(self, record_id, headers):
        return self._request(
            "POST", f"/tissue-bank/disposition-records/{record_id}/finalize", {}, headers
        )

    def delete_disposition_record(self, record_id, headers):
        return self._request(
            "DELETE", f"/tissue-bank/disposition-records/{record_id}", headers=headers
        )


api_client = ApiClient()
