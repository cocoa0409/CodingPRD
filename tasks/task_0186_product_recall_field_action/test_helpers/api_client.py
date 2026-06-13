"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    # ---- Lot ----
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    # ---- Unit ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def update_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/customers/{customer_id}", payload, headers)

    # ---- Recall ----
    def create_recall(self, payload, headers):
        return self._request("POST", "/recalls", payload, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/recalls/{recall_id}", headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/recalls", headers=headers, params=params)

    def add_affected_lot(self, recall_id, payload, headers):
        return self._request("POST", f"/recalls/{recall_id}/affected-lots", payload, headers)

    def classify_recall(self, recall_id, headers, payload=None):
        return self._request("POST", f"/recalls/{recall_id}/classify", payload or {}, headers)

    def reclassify_recall(self, recall_id, headers, payload=None):
        return self._request("POST", f"/recalls/{recall_id}/reclassify", payload or {}, headers)

    def announce_recall(self, recall_id, headers, payload=None):
        return self._request("POST", f"/recalls/{recall_id}/announce", payload or {}, headers)

    def begin_monitoring(self, recall_id, headers, payload=None):
        return self._request("POST", f"/recalls/{recall_id}/begin-monitoring", payload or {}, headers)

    def terminate_recall(self, recall_id, headers, payload=None):
        return self._request("POST", f"/recalls/{recall_id}/terminate", payload or {}, headers)

    def get_recall_effectiveness(self, recall_id, headers):
        return self._request("GET", f"/recalls/{recall_id}/effectiveness", headers=headers)

    # ---- AffectedLot ----
    def get_affected_lot(self, affected_lot_id, headers):
        return self._request("GET", f"/affected-lots/{affected_lot_id}", headers=headers)

    def list_affected_lots(self, headers, params=None):
        return self._request("GET", "/affected-lots", headers=headers, params=params)

    # ---- QuarantineHold ----
    def get_quarantine_hold(self, hold_id, headers):
        return self._request("GET", f"/quarantine-holds/{hold_id}", headers=headers)

    def list_quarantine_holds(self, headers, params=None):
        return self._request("GET", "/quarantine-holds", headers=headers, params=params)

    def lift_hold(self, hold_id, headers, payload=None):
        return self._request("POST", f"/quarantine-holds/{hold_id}/lift", payload or {}, headers)

    def reimpose_hold(self, hold_id, headers, payload=None):
        return self._request("POST", f"/quarantine-holds/{hold_id}/reimpose", payload or {}, headers)

    # ---- Notification ----
    def get_notification(self, notification_id, headers):
        return self._request("GET", f"/notifications/{notification_id}", headers=headers)

    def list_notifications(self, headers, params=None):
        return self._request("GET", "/notifications", headers=headers, params=params)

    def send_notification(self, notification_id, headers, payload=None):
        return self._request("POST", f"/notifications/{notification_id}/send", payload or {}, headers)

    def acknowledge_notification(self, notification_id, headers, payload=None):
        return self._request("POST", f"/notifications/{notification_id}/acknowledge", payload or {}, headers)

    # ---- Disposition ----
    def create_disposition(self, payload, headers):
        return self._request("POST", "/dispositions", payload, headers)

    def get_disposition(self, disposition_id, headers):
        return self._request("GET", f"/dispositions/{disposition_id}", headers=headers)

    def list_dispositions(self, headers, params=None):
        return self._request("GET", "/dispositions", headers=headers, params=params)

    def receive_return(self, disposition_id, headers, payload=None):
        return self._request("POST", f"/dispositions/{disposition_id}/receive-return", payload or {}, headers)

    def ship_replacement(self, disposition_id, headers, payload=None):
        return self._request("POST", f"/dispositions/{disposition_id}/ship-replacement", payload or {}, headers)

    def cancel_disposition(self, disposition_id, headers, payload=None):
        return self._request("POST", f"/dispositions/{disposition_id}/cancel", payload or {}, headers)

    def accrue_refund(self, disposition_id, headers, payload=None):
        return self._request("POST", f"/dispositions/{disposition_id}/accrue-refund", payload or {}, headers)

    def settle_refund(self, disposition_id, headers, payload=None):
        return self._request("POST", f"/dispositions/{disposition_id}/settle-refund", payload or {}, headers)

    # ---- RegulatoryReport ----
    def create_report(self, payload, headers):
        return self._request("POST", "/regulatory-reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/regulatory-reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/regulatory-reports", headers=headers, params=params)

    def submit_report(self, report_id, headers, payload=None):
        return self._request("POST", f"/regulatory-reports/{report_id}/submit", payload or {}, headers)

    def acknowledge_report(self, report_id, headers, payload=None):
        return self._request("POST", f"/regulatory-reports/{report_id}/acknowledge", payload or {}, headers)

    # ---- EffectivenessCheck ----
    def create_effectiveness_check(self, payload, headers):
        return self._request("POST", "/effectiveness-checks", payload, headers)

    def get_effectiveness_check(self, check_id, headers):
        return self._request("GET", f"/effectiveness-checks/{check_id}", headers=headers)

    def list_effectiveness_checks(self, headers, params=None):
        return self._request("GET", "/effectiveness-checks", headers=headers, params=params)

    # ---- Test clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
