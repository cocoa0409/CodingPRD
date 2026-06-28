"""API client: one method per endpoint defined in the Pet Cremation & Aftercare PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Logical clock ----------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---------- Clinic ----------
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    def list_clinics(self, headers, params=None):
        return self._request("GET", "/clinics", headers=headers, params=params)

    def get_clinic_statement(self, clinic_id, headers, params=None):
        return self._request("GET", f"/clinics/{clinic_id}/statement",
                             headers=headers, params=params)

    # ---------- PetOwner ----------
    def create_petowner(self, payload, headers):
        return self._request("POST", "/petowners", payload, headers)

    def get_petowner(self, owner_id, headers):
        return self._request("GET", f"/petowners/{owner_id}", headers=headers)

    # ---------- Cooler ----------
    def create_cooler(self, payload, headers):
        return self._request("POST", "/coolers", payload, headers)

    def get_cooler(self, cooler_id, headers):
        return self._request("GET", f"/coolers/{cooler_id}", headers=headers)

    def list_coolers(self, headers, params=None):
        return self._request("GET", "/coolers", headers=headers, params=params)

    # ---------- Retort ----------
    def create_retort(self, payload, headers):
        return self._request("POST", "/retorts", payload, headers)

    def get_retort(self, retort_id, headers):
        return self._request("GET", f"/retorts/{retort_id}", headers=headers)

    # ---------- CremationBatch ----------
    def create_batch(self, payload, headers):
        return self._request("POST", "/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    def list_batch_cases(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/cases",
                             headers=headers, params=params)

    def assign_case(self, batch_id, case_id, headers):
        return self._request("POST", f"/batches/{batch_id}/assign-case",
                             {"case_id": case_id}, headers)

    def load_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/load", {}, headers)

    def fire_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/fire", {}, headers)

    def complete_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/complete", {}, headers)

    def reconcile_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/reconcile", {}, headers)

    # ---------- Case ----------
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def create_transport_leg(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/transport-legs", payload, headers)

    def list_transport_legs(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/transport-legs",
                             headers=headers, params=params)

    def patch_transport_leg(self, leg_id, status, headers):
        return self._request("PATCH", f"/transport-legs/{leg_id}",
                             {"status": status}, headers)

    def get_transport_leg(self, leg_id, headers):
        return self._request("GET", f"/transport-legs/{leg_id}", headers=headers)

    def list_custody_events(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/custody-events",
                             headers=headers, params=params)

    def receive_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/receive", {}, headers)

    def store_case(self, case_id, cooler_id, headers):
        return self._request("POST", f"/cases/{case_id}/store",
                             {"cooler_id": cooler_id}, headers)

    def ready_return(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/ready-return", payload, headers)

    def finalize_return(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/finalize-return", {}, headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/cancel", {}, headers)

    def create_invoice(self, case_id, expected_case_version, headers):
        return self._request("POST", f"/cases/{case_id}/invoices",
                             {"expected_case_version": expected_case_version}, headers)

    def list_case_invoices(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/invoices",
                             headers=headers, params=params)

    # ---------- KeepsakeOrder ----------
    def create_keepsake(self, case_id, item_type, headers):
        return self._request("POST", f"/cases/{case_id}/keepsake-orders",
                             {"item_type": item_type}, headers)

    def list_keepsakes(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/keepsake-orders",
                             headers=headers, params=params)

    def patch_keepsake(self, keepsake_id, status, headers):
        return self._request("PATCH", f"/keepsake-orders/{keepsake_id}",
                             {"status": status}, headers)

    # ---------- CertificateRecord ----------
    def list_certificates(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/certificates",
                             headers=headers, params=params)

    # ---------- ReturnRoute ----------
    def list_return_routes(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/return-routes",
                             headers=headers, params=params)

    def dispatch_return_route(self, route_id, headers):
        return self._request("POST", f"/return-routes/{route_id}/dispatch", {}, headers)

    def cancel_return_route(self, route_id, headers):
        return self._request("POST", f"/return-routes/{route_id}/cancel", {}, headers)

    # ---------- MemorialAddon ----------
    def create_memorial_addon(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/memorial-addons", payload, headers)

    def list_memorial_addons(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/memorial-addons",
                             headers=headers, params=params)

    def patch_memorial_addon(self, addon_id, status, headers):
        return self._request("PATCH", f"/memorial-addons/{addon_id}",
                             {"status": status}, headers)

    # ---------- Invoice ----------
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()
