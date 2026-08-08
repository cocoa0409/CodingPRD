"""API client: one method per endpoint defined in the PRD.

Every resource is mounted under the /clinic prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Patients ─────────────────────────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/clinic/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/clinic/patients/{patient_id}", headers=headers)

    def get_therapy_status(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/clinic/patients/{patient_id}/therapy-status",
            headers=headers, params=params,
        )

    def set_eligibility_hold(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/clinic/patients/{patient_id}/eligibility-hold", payload, headers
        )

    # ── Providers ────────────────────────────────────────────────────────────
    def create_provider(self, payload, headers):
        return self._request("POST", "/clinic/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/clinic/providers/{provider_id}", headers=headers)

    # ── Protocols ────────────────────────────────────────────────────────────
    def publish_protocol(self, payload, headers):
        return self._request("POST", "/clinic/protocols", payload, headers)

    def get_protocol(self, protocol_id, headers):
        return self._request("GET", f"/clinic/protocols/{protocol_id}", headers=headers)

    def list_protocols(self, headers, params=None):
        return self._request("GET", "/clinic/protocols", headers=headers, params=params)

    # ── Consents ─────────────────────────────────────────────────────────────
    def sign_consent(self, payload, headers):
        return self._request("POST", "/clinic/consents", payload, headers)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"/clinic/consents/{consent_id}", headers=headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", "/clinic/consents", headers=headers, params=params)

    # ── Consults ─────────────────────────────────────────────────────────────
    def create_consult(self, payload, headers):
        return self._request("POST", "/clinic/consults", payload, headers)

    def get_consult(self, consult_id, headers):
        return self._request("GET", f"/clinic/consults/{consult_id}", headers=headers)

    def list_consults(self, headers, params=None):
        return self._request("GET", "/clinic/consults", headers=headers, params=params)

    # ── Lab panels ───────────────────────────────────────────────────────────
    def create_lab_panel(self, payload, headers):
        return self._request("POST", "/clinic/lab-panels", payload, headers)

    def get_lab_panel(self, panel_id, headers):
        return self._request("GET", f"/clinic/lab-panels/{panel_id}", headers=headers)

    def list_lab_panels(self, headers, params=None):
        return self._request("GET", "/clinic/lab-panels", headers=headers, params=params)

    def acknowledge_critical_lab(self, panel_id, payload, headers):
        return self._request(
            "POST", f"/clinic/lab-panels/{panel_id}/acknowledge-critical", payload, headers
        )

    # ── Pellet lots ──────────────────────────────────────────────────────────
    def create_pellet_lot(self, payload, headers):
        return self._request("POST", "/clinic/pellet-lots", payload, headers)

    def get_pellet_lot(self, lot_id, headers):
        return self._request("GET", f"/clinic/pellet-lots/{lot_id}", headers=headers)

    def release_pellet_lot(self, lot_id, headers, payload=None):
        return self._request(
            "POST", f"/clinic/pellet-lots/{lot_id}/release", payload or {}, headers
        )

    def recall_pellet_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/clinic/pellet-lots/{lot_id}/recall", payload, headers)

    def get_recall_impact(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/clinic/pellet-lots/{lot_id}/recall-impact", headers=headers, params=params
        )

    def list_lot_allocations(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/clinic/pellet-lots/{lot_id}/allocations", headers=headers, params=params
        )

    # ── Standing orders ──────────────────────────────────────────────────────
    def create_standing_order(self, payload, headers):
        return self._request("POST", "/clinic/standing-orders", payload, headers)

    def get_standing_order(self, order_id, headers):
        return self._request("GET", f"/clinic/standing-orders/{order_id}", headers=headers)

    def list_standing_orders(self, headers, params=None):
        return self._request("GET", "/clinic/standing-orders", headers=headers, params=params)

    def revoke_standing_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/clinic/standing-orders/{order_id}/revoke", payload, headers
        )

    def reinstate_standing_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/clinic/standing-orders/{order_id}/reinstate", payload or {}, headers
        )

    # ── Procedures ───────────────────────────────────────────────────────────
    def create_procedure(self, payload, headers):
        return self._request("POST", "/clinic/procedures", payload, headers)

    def get_procedure(self, procedure_id, headers):
        return self._request("GET", f"/clinic/procedures/{procedure_id}", headers=headers)

    def list_procedures(self, headers, params=None):
        return self._request("GET", "/clinic/procedures", headers=headers, params=params)

    def attach_consent(self, procedure_id, payload, headers):
        return self._request(
            "POST", f"/clinic/procedures/{procedure_id}/consent-attach", payload, headers
        )

    def run_allocation(self, procedure_id, payload, headers):
        return self._request(
            "POST", f"/clinic/procedures/{procedure_id}/allocations", payload, headers
        )

    def list_procedure_allocations(self, procedure_id, headers, params=None):
        return self._request(
            "GET", f"/clinic/procedures/{procedure_id}/allocations",
            headers=headers, params=params,
        )

    def open_supply(self, procedure_id, headers, payload=None):
        return self._request(
            "POST", f"/clinic/procedures/{procedure_id}/open-supply", payload or {}, headers
        )

    def perform_procedure(self, procedure_id, payload, headers):
        return self._request(
            "POST", f"/clinic/procedures/{procedure_id}/perform", payload, headers
        )

    def cancel_procedure(self, procedure_id, payload, headers):
        return self._request(
            "POST", f"/clinic/procedures/{procedure_id}/cancel", payload or {}, headers
        )

    def void_procedure(self, procedure_id, payload, headers):
        return self._request(
            "POST", f"/clinic/procedures/{procedure_id}/void", payload, headers
        )

    def get_refund_quote(self, procedure_id, headers):
        return self._request(
            "GET", f"/clinic/procedures/{procedure_id}/refund-quote", headers=headers
        )

    # ── Injection visits ─────────────────────────────────────────────────────
    def create_injection_visit(self, payload, headers):
        return self._request("POST", "/clinic/injection-visits", payload, headers)

    def get_injection_visit(self, visit_id, headers):
        return self._request("GET", f"/clinic/injection-visits/{visit_id}", headers=headers)

    def list_injection_visits(self, headers, params=None):
        return self._request("GET", "/clinic/injection-visits", headers=headers, params=params)

    def administer_injection_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST", f"/clinic/injection-visits/{visit_id}/administer", payload or {}, headers
        )

    def cancel_injection_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/clinic/injection-visits/{visit_id}/cancel", payload or {}, headers
        )

    def void_injection_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/clinic/injection-visits/{visit_id}/void", payload, headers
        )

    # ── Memberships ──────────────────────────────────────────────────────────
    def create_membership(self, payload, headers):
        return self._request("POST", "/clinic/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/clinic/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/clinic/memberships", headers=headers, params=params)

    def pause_membership(self, membership_id, headers, payload=None):
        return self._request(
            "POST", f"/clinic/memberships/{membership_id}/pause", payload or {}, headers
        )

    def resume_membership(self, membership_id, headers, payload=None):
        return self._request(
            "POST", f"/clinic/memberships/{membership_id}/resume", payload or {}, headers
        )

    def change_membership_tier(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/clinic/memberships/{membership_id}/tier-change", payload, headers
        )

    def cancel_membership(self, membership_id, headers, payload=None):
        return self._request(
            "POST", f"/clinic/memberships/{membership_id}/cancel", payload or {}, headers
        )

    # ── Series packs ─────────────────────────────────────────────────────────
    def create_series_pack(self, payload, headers):
        return self._request("POST", "/clinic/series-packs", payload, headers)

    def get_series_pack(self, pack_id, headers):
        return self._request("GET", f"/clinic/series-packs/{pack_id}", headers=headers)

    def list_series_packs(self, headers, params=None):
        return self._request("GET", "/clinic/series-packs", headers=headers, params=params)

    def refund_series_pack(self, pack_id, payload, headers):
        return self._request(
            "POST", f"/clinic/series-packs/{pack_id}/refund", payload or {}, headers
        )

    # ── Adverse events ───────────────────────────────────────────────────────
    def create_adverse_event(self, payload, headers):
        return self._request("POST", "/clinic/adverse-events", payload, headers)

    def get_adverse_event(self, event_id, headers):
        return self._request("GET", f"/clinic/adverse-events/{event_id}", headers=headers)

    def list_adverse_events(self, headers, params=None):
        return self._request("GET", "/clinic/adverse-events", headers=headers, params=params)

    def review_adverse_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/clinic/adverse-events/{event_id}/review", payload, headers
        )

    # ── Financing ────────────────────────────────────────────────────────────
    def create_financing_plan(self, payload, headers):
        return self._request("POST", "/clinic/financing-plans", payload, headers)

    def get_financing_plan(self, plan_id, headers):
        return self._request("GET", f"/clinic/financing-plans/{plan_id}", headers=headers)

    def list_financing_plans(self, headers, params=None):
        return self._request("GET", "/clinic/financing-plans", headers=headers, params=params)

    def activate_financing_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/clinic/financing-plans/{plan_id}/activate", payload or {}, headers
        )

    def pay_installment(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/clinic/financing-plans/{plan_id}/payments", payload, headers
        )

    def run_delinquency(self, headers, payload=None):
        return self._request("POST", "/clinic/billing/delinquency-run", payload or {}, headers)

    # ── Patient notifications ────────────────────────────────────────────────
    def get_notification(self, notification_id, headers):
        return self._request(
            "GET", f"/clinic/patient-notifications/{notification_id}", headers=headers
        )

    def list_notifications(self, headers, params=None):
        return self._request(
            "GET", "/clinic/patient-notifications", headers=headers, params=params
        )

    def acknowledge_notification(self, notification_id, headers, payload=None):
        return self._request(
            "POST", f"/clinic/patient-notifications/{notification_id}/acknowledge",
            payload or {}, headers,
        )

    # ── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/clinic/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
