"""API client: one method per endpoint declared in the PRD's endpoint reference.

All paths are absolute — the API is served at the root, with no version or
product prefix in front of the paths.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Hospital contracts ───────────────────────────
    def create_hospital_contract(self, payload, headers):
        return self._request("POST", "/hospital-contracts", payload, headers)

    def get_hospital_contract(self, contract_id, headers):
        return self._request("GET", f"/hospital-contracts/{contract_id}", headers=headers)

    def update_hospital_contract(self, contract_id, payload, headers):
        return self._request("PUT", f"/hospital-contracts/{contract_id}", payload, headers)

    def create_settlement_run(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/hospital-contracts/{contract_id}/settlement-runs", payload, headers
        )

    # ─── Surgeons ─────────────────────────────────────
    def create_surgeon(self, payload, headers):
        return self._request("POST", "/surgeons", payload, headers)

    def get_surgeon(self, surgeon_id, headers):
        return self._request("GET", f"/surgeons/{surgeon_id}", headers=headers)

    # ─── Preference cards ─────────────────────────────
    def create_preference_card(self, payload, headers):
        return self._request("POST", "/preference-cards", payload, headers)

    def get_preference_card(self, card_id, headers):
        return self._request("GET", f"/preference-cards/{card_id}", headers=headers)

    def list_preference_cards(self, headers, params=None):
        return self._request("GET", "/preference-cards", headers=headers, params=params)

    # ─── Perfusionists ────────────────────────────────
    def create_perfusionist(self, payload, headers):
        return self._request("POST", "/perfusionists", payload, headers)

    def get_perfusionist(self, perfusionist_id, headers):
        return self._request("GET", f"/perfusionists/{perfusionist_id}", headers=headers)

    def create_certification(self, perfusionist_id, payload, headers):
        return self._request(
            "POST", f"/perfusionists/{perfusionist_id}/certifications", payload, headers
        )

    def list_certifications(self, perfusionist_id, headers, params=None):
        return self._request(
            "GET", f"/perfusionists/{perfusionist_id}/certifications",
            headers=headers, params=params,
        )

    def create_ce_activity(self, perfusionist_id, payload, headers):
        return self._request(
            "POST", f"/perfusionists/{perfusionist_id}/ce-activities", payload, headers
        )

    def list_ce_activities(self, perfusionist_id, headers, params=None):
        return self._request(
            "GET", f"/perfusionists/{perfusionist_id}/ce-activities",
            headers=headers, params=params,
        )

    def adjudicate_ce_activity(self, ce_activity_id, payload, headers):
        return self._request(
            "POST", f"/ce-activities/{ce_activity_id}/verification", payload, headers
        )

    # ─── Perfusion devices ────────────────────────────
    def create_perfusion_device(self, payload, headers):
        return self._request("POST", "/perfusion-devices", payload, headers)

    def get_perfusion_device(self, device_id, headers):
        return self._request("GET", f"/perfusion-devices/{device_id}", headers=headers)

    def list_perfusion_devices(self, headers, params=None):
        return self._request("GET", "/perfusion-devices", headers=headers, params=params)

    def create_device_event_log(self, device_id, payload, headers):
        return self._request(
            "POST", f"/perfusion-devices/{device_id}/event-logs", payload, headers
        )

    def list_device_event_logs(self, device_id, headers, params=None):
        return self._request(
            "GET", f"/perfusion-devices/{device_id}/event-logs",
            headers=headers, params=params,
        )

    def create_service_completion(self, device_id, payload, headers):
        return self._request(
            "POST", f"/perfusion-devices/{device_id}/service-completions", payload, headers
        )

    # ─── Call rotation slots ──────────────────────────
    def create_call_rotation_slot(self, payload, headers):
        return self._request("POST", "/call-rotation-slots", payload, headers)

    def get_call_rotation_slot(self, slot_id, headers):
        return self._request("GET", f"/call-rotation-slots/{slot_id}", headers=headers)

    def list_call_rotation_slots(self, headers, params=None):
        return self._request("GET", "/call-rotation-slots", headers=headers, params=params)

    # ─── Bypass cases ─────────────────────────────────
    def create_bypass_case(self, payload, headers):
        return self._request("POST", "/bypass-cases", payload, headers)

    def get_bypass_case(self, case_id, headers):
        return self._request("GET", f"/bypass-cases/{case_id}", headers=headers)

    def list_bypass_cases(self, headers, params=None):
        return self._request("GET", "/bypass-cases", headers=headers, params=params)

    def assign_perfusionist(self, case_id, payload, headers):
        return self._request(
            "POST", f"/bypass-cases/{case_id}/assign-perfusionist", payload, headers
        )

    def configure_disposable_pack(self, case_id, payload, headers):
        return self._request(
            "POST", f"/bypass-cases/{case_id}/disposable-packs", payload, headers
        )

    def create_pump_checklist(self, case_id, payload, headers):
        return self._request(
            "POST", f"/bypass-cases/{case_id}/pump-checklists", payload, headers
        )

    def start_bypass(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/bypass-cases/{case_id}/start-bypass", payload or {}, headers
        )

    def end_bypass(self, case_id, payload, headers):
        return self._request("POST", f"/bypass-cases/{case_id}/end-bypass", payload, headers)

    def close_bypass_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/bypass-cases/{case_id}/close", payload or {}, headers)

    def cancel_bypass_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/bypass-cases/{case_id}/cancel", payload or {}, headers)

    def create_ecmo_run(self, case_id, payload, headers):
        return self._request("POST", f"/bypass-cases/{case_id}/ecmo-runs", payload, headers)

    # ─── Disposable packs ─────────────────────────────
    def get_disposable_pack(self, pack_id, headers):
        return self._request("GET", f"/disposable-packs/{pack_id}", headers=headers)

    def list_disposable_packs(self, headers, params=None):
        return self._request("GET", "/disposable-packs", headers=headers, params=params)

    def approve_disposable_pack(self, pack_id, payload, headers):
        return self._request("POST", f"/disposable-packs/{pack_id}/approve", payload, headers)

    # ─── Pump checklists ──────────────────────────────
    def get_pump_checklist(self, checklist_id, headers):
        return self._request("GET", f"/pump-checklists/{checklist_id}", headers=headers)

    def list_pump_checklists(self, headers, params=None):
        return self._request("GET", "/pump-checklists", headers=headers, params=params)

    def verify_pump_checklist(self, checklist_id, headers, payload=None):
        return self._request(
            "POST", f"/pump-checklists/{checklist_id}/verify", payload or {}, headers
        )

    # ─── ECMO runs ────────────────────────────────────
    def get_ecmo_run(self, run_id, headers):
        return self._request("GET", f"/ecmo-runs/{run_id}", headers=headers)

    def list_ecmo_runs(self, headers, params=None):
        return self._request("GET", "/ecmo-runs", headers=headers, params=params)

    def handoff_ecmo_run(self, run_id, payload, headers):
        return self._request("POST", f"/ecmo-runs/{run_id}/handoffs", payload, headers)

    def decannulate_ecmo_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"/ecmo-runs/{run_id}/decannulate", payload or {}, headers
        )

    # ─── Incident reports ─────────────────────────────
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers)

    def get_incident_report(self, report_id, headers):
        return self._request("GET", f"/incident-reports/{report_id}", headers=headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/incident-reports", headers=headers, params=params)

    def submit_incident_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"/incident-reports/{report_id}/submit", payload or {}, headers
        )

    def review_incident_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/incident-reports/{report_id}/review", payload, headers
        )

    def close_incident_report(self, report_id, payload, headers):
        return self._request("POST", f"/incident-reports/{report_id}/close", payload, headers)

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
