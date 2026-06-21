"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock (test-driving) ─────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    # ─── Employers ────────────────────────────────────
    def create_employer(self, payload, headers):
        return self._request("POST", "/clinic/employers", payload, headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/clinic/employers", headers=headers, params=params)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/clinic/employers/{employer_id}", headers=headers)

    def suspend_employer(self, employer_id, headers):
        return self._request("POST", f"/clinic/employers/{employer_id}/suspend", headers=headers)

    def reactivate_employer(self, employer_id, headers):
        return self._request("POST", f"/clinic/employers/{employer_id}/reactivate", headers=headers)

    def close_employer(self, employer_id, headers):
        return self._request("POST", f"/clinic/employers/{employer_id}/close", headers=headers)

    # ─── Protocols ────────────────────────────────────
    def create_protocol(self, payload, headers):
        return self._request("POST", "/clinic/protocols", payload, headers)

    def list_protocols(self, headers, params=None):
        return self._request("GET", "/clinic/protocols", headers=headers, params=params)

    def get_protocol(self, protocol_id, headers):
        return self._request("GET", f"/clinic/protocols/{protocol_id}", headers=headers)

    def activate_protocol(self, protocol_id, payload, headers):
        return self._request("POST", f"/clinic/protocols/{protocol_id}/activate", payload, headers)

    # ─── Workers ──────────────────────────────────────
    def create_worker(self, payload, headers):
        return self._request("POST", "/clinic/workers", payload, headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/clinic/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/clinic/workers/{worker_id}", headers=headers)

    # ─── Encounters ───────────────────────────────────
    def create_encounter(self, payload, headers):
        return self._request("POST", "/clinic/encounters", payload, headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/clinic/encounters", headers=headers, params=params)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/clinic/encounters/{encounter_id}", headers=headers)

    def check_in_encounter(self, encounter_id, headers):
        return self._request("POST", f"/clinic/encounters/{encounter_id}/check-in", headers=headers)

    def complete_encounter(self, encounter_id, headers):
        return self._request("POST", f"/clinic/encounters/{encounter_id}/complete", headers=headers)

    def cancel_encounter(self, encounter_id, headers):
        return self._request("POST", f"/clinic/encounters/{encounter_id}/cancel", headers=headers)

    def void_encounter(self, encounter_id, headers):
        return self._request("POST", f"/clinic/encounters/{encounter_id}/void", headers=headers)

    # ─── Clearances ───────────────────────────────────
    def create_clearance(self, payload, headers):
        return self._request("POST", "/clinic/clearances", payload, headers)

    def list_clearances(self, headers, params=None):
        return self._request("GET", "/clinic/clearances", headers=headers, params=params)

    def get_clearance(self, clearance_id, headers):
        return self._request("GET", f"/clinic/clearances/{clearance_id}", headers=headers)

    def rescind_clearance(self, clearance_id, headers):
        return self._request("POST", f"/clinic/clearances/{clearance_id}/rescind", headers=headers)

    # ─── Drug screens ─────────────────────────────────
    def create_drug_screen(self, payload, headers):
        return self._request("POST", "/clinic/drug-screens", payload, headers)

    def list_drug_screens(self, headers, params=None):
        return self._request("GET", "/clinic/drug-screens", headers=headers, params=params)

    def get_drug_screen(self, drug_screen_id, headers):
        return self._request("GET", f"/clinic/drug-screens/{drug_screen_id}", headers=headers)

    def record_lab_result(self, drug_screen_id, payload, headers):
        return self._request("POST", f"/clinic/drug-screens/{drug_screen_id}/lab-result", payload, headers)

    def mro_receive(self, drug_screen_id, headers):
        return self._request("POST", f"/clinic/drug-screens/{drug_screen_id}/mro-receive", headers=headers)

    def mro_verify(self, drug_screen_id, payload, headers):
        return self._request("POST", f"/clinic/drug-screens/{drug_screen_id}/mro-verify", payload, headers)

    def order_recollection(self, drug_screen_id, headers):
        return self._request("POST", f"/clinic/drug-screens/{drug_screen_id}/order-recollection", headers=headers)

    # ─── Custody events ───────────────────────────────
    def create_custody_event(self, payload, headers):
        return self._request("POST", "/clinic/custody-events", payload, headers)

    def list_custody_events(self, headers, params=None):
        return self._request("GET", "/clinic/custody-events", headers=headers, params=params)

    def get_custody_event(self, custody_event_id, headers):
        return self._request("GET", f"/clinic/custody-events/{custody_event_id}", headers=headers)

    # ─── Injury cases ─────────────────────────────────
    def create_injury_case(self, payload, headers):
        return self._request("POST", "/clinic/injury-cases", payload, headers)

    def list_injury_cases(self, headers, params=None):
        return self._request("GET", "/clinic/injury-cases", headers=headers, params=params)

    def get_injury_case(self, injury_case_id, headers):
        return self._request("GET", f"/clinic/injury-cases/{injury_case_id}", headers=headers)

    def reopen_injury_case(self, injury_case_id, headers):
        return self._request("POST", f"/clinic/injury-cases/{injury_case_id}/reopen", headers=headers)

    # ─── Work statuses ────────────────────────────────
    def create_work_status(self, payload, headers):
        return self._request("POST", "/clinic/work-statuses", payload, headers)

    def list_work_statuses(self, headers, params=None):
        return self._request("GET", "/clinic/work-statuses", headers=headers, params=params)

    def get_work_status(self, work_status_id, headers):
        return self._request("GET", f"/clinic/work-statuses/{work_status_id}", headers=headers)

    # ─── Surveillance exams ───────────────────────────
    def create_surveillance_exam(self, payload, headers):
        return self._request("POST", "/clinic/surveillance-exams", payload, headers)

    def list_surveillance_exams(self, headers, params=None):
        return self._request("GET", "/clinic/surveillance-exams", headers=headers, params=params)

    def get_surveillance_exam(self, exam_id, headers):
        return self._request("GET", f"/clinic/surveillance-exams/{exam_id}", headers=headers)

    def record_surveillance_exam(self, exam_id, headers):
        return self._request("POST", f"/clinic/surveillance-exams/{exam_id}/record", headers=headers)

    def finalize_surveillance_exam(self, exam_id, headers):
        return self._request("POST", f"/clinic/surveillance-exams/{exam_id}/finalize", headers=headers)

    def cancel_surveillance_exam(self, exam_id, headers):
        return self._request("POST", f"/clinic/surveillance-exams/{exam_id}/cancel", headers=headers)

    # ─── Invoices ─────────────────────────────────────
    def create_invoice(self, payload, headers):
        return self._request("POST", "/clinic/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/clinic/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/clinic/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/clinic/invoices/{invoice_id}/issue", payload, headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/clinic/invoices/{invoice_id}/payments", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/clinic/invoices/{invoice_id}/void", headers=headers)


api_client = ApiClient()
