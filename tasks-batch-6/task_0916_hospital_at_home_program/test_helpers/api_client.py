"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ─────────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Patients ──────────────────────────────────────────────────────────

    def create_patient(self, payload, headers=None):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def update_patient(self, patient_id, payload, headers):
        return self._request("PATCH", f"/patients/{patient_id}", payload, headers)

    def list_patient_referrals(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/referrals", headers=headers, params=params
        )

    # ─── Referrals and eligibility ─────────────────────────────────────────

    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def mark_referral_eligible(self, referral_id, headers, payload=None):
        return self._request(
            "POST", f"/referrals/{referral_id}/mark-eligible", payload or {}, headers
        )

    def create_eligibility_assessment(self, payload, headers):
        return self._request("POST", "/eligibility-assessments", payload, headers)

    def list_referral_assessments(self, referral_id, headers, params=None):
        return self._request(
            "GET",
            f"/referrals/{referral_id}/eligibility-assessments",
            headers=headers,
            params=params,
        )

    # ─── Episodes ──────────────────────────────────────────────────────────

    def create_episode(self, payload, headers):
        return self._request("POST", "/episodes", payload, headers)

    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/episodes/{episode_id}", headers=headers)

    def list_episodes(self, headers, params=None):
        return self._request("GET", "/episodes", headers=headers, params=params)

    def get_episode_ledger(self, episode_id, headers):
        return self._request("GET", f"/episodes/{episode_id}/ledger", headers=headers)

    def sign_med_rec(self, episode_id, headers, payload=None):
        return self._request(
            "POST", f"/episodes/{episode_id}/sign-med-rec", payload or {}, headers
        )

    def begin_discharge(self, episode_id, headers, payload=None):
        return self._request(
            "POST", f"/episodes/{episode_id}/begin-discharge", payload or {}, headers
        )

    def discharge_episode(self, episode_id, headers, payload=None):
        return self._request(
            "POST", f"/episodes/{episode_id}/discharge", payload or {}, headers
        )

    def readmit_episode(self, episode_id, headers, payload=None):
        return self._request(
            "POST", f"/episodes/{episode_id}/readmit", payload or {}, headers
        )

    # ─── Visits ────────────────────────────────────────────────────────────

    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def list_episode_visits(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/episodes/{episode_id}/visits", headers=headers, params=params
        )

    def depart_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST", f"/visits/{visit_id}/depart", payload or {}, headers
        )

    def complete_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST", f"/visits/{visit_id}/complete", payload or {}, headers
        )

    def close_unperformed_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/visits/{visit_id}/close-unperformed", payload, headers
        )

    def attest_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST", f"/visits/{visit_id}/attest", payload or {}, headers
        )

    # ─── Compliance days ───────────────────────────────────────────────────

    def list_compliance_days(self, episode_id, headers, params=None):
        return self._request(
            "GET",
            f"/episodes/{episode_id}/compliance-days",
            headers=headers,
            params=params,
        )

    def finalize_compliance_day(self, compliance_day_id, headers, payload=None):
        return self._request(
            "POST",
            f"/compliance-days/{compliance_day_id}/finalize",
            payload or {},
            headers,
        )

    # ─── Device kits and components ────────────────────────────────────────

    def create_device_kit(self, payload, headers):
        return self._request("POST", "/device-kits", payload, headers)

    def get_device_kit(self, kit_id, headers):
        return self._request("GET", f"/device-kits/{kit_id}", headers=headers)

    def list_episode_device_kits(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/episodes/{episode_id}/device-kits", headers=headers, params=params
        )

    def deploy_device_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/device-kits/{kit_id}/deploy", payload, headers)

    def get_device_kit_census(self, headers):
        return self._request("GET", "/device-kit-census", headers=headers)

    def create_device_component(self, kit_id, payload, headers):
        return self._request(
            "POST", f"/device-kits/{kit_id}/components", payload, headers
        )

    def list_device_kit_components(self, kit_id, headers, params=None):
        return self._request(
            "GET", f"/device-kits/{kit_id}/components", headers=headers, params=params
        )

    def reconcile_device_component(self, component_id, payload, headers):
        return self._request(
            "POST", f"/device-components/{component_id}/reconcile", payload, headers
        )

    # ─── Monitoring lapses ─────────────────────────────────────────────────

    def create_monitoring_lapse(self, payload, headers):
        return self._request("POST", "/monitoring-lapses", payload, headers)

    def list_episode_monitoring_lapses(self, episode_id, headers, params=None):
        return self._request(
            "GET",
            f"/episodes/{episode_id}/monitoring-lapses",
            headers=headers,
            params=params,
        )

    # ─── Delivery orders ───────────────────────────────────────────────────

    def create_delivery_order(self, payload, headers):
        return self._request("POST", "/delivery-orders", payload, headers)

    def list_episode_delivery_orders(self, episode_id, headers, params=None):
        return self._request(
            "GET",
            f"/episodes/{episode_id}/delivery-orders",
            headers=headers,
            params=params,
        )

    def authorize_delivery_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/authorize", payload or {}, headers
        )

    def dispatch_delivery_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/dispatch", payload or {}, headers
        )

    def deliver_delivery_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/deliver", payload, headers
        )

    def refuse_delivery_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/refuse", payload or {}, headers
        )

    # ─── Meal plans ────────────────────────────────────────────────────────

    def create_meal_plan(self, payload, headers):
        return self._request("POST", "/meal-plans", payload, headers)

    def list_episode_meal_plans(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/episodes/{episode_id}/meal-plans", headers=headers, params=params
        )

    # ─── Escalation events ─────────────────────────────────────────────────

    def create_escalation_event(self, payload, headers):
        return self._request("POST", "/escalation-events", payload, headers)

    def list_episode_escalation_events(self, episode_id, headers, params=None):
        return self._request(
            "GET",
            f"/episodes/{episode_id}/escalation-events",
            headers=headers,
            params=params,
        )

    def acknowledge_escalation(self, escalation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/escalation-events/{escalation_id}/acknowledge",
            payload or {},
            headers,
        )

    def promote_escalation(self, escalation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/escalation-events/{escalation_id}/promote",
            payload or {},
            headers,
        )

    def resolve_escalation(self, escalation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/escalation-events/{escalation_id}/resolve",
            payload or {},
            headers,
        )

    def convert_escalation_to_bed_return(self, escalation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/escalation-events/{escalation_id}/convert-bed-return",
            payload or {},
            headers,
        )

    # ─── Inpatient units and bed reservations ──────────────────────────────

    def create_inpatient_unit(self, payload, headers):
        return self._request("POST", "/inpatient-units", payload, headers)

    def get_inpatient_unit(self, unit_id, headers):
        return self._request("GET", f"/inpatient-units/{unit_id}", headers=headers)

    def create_bed_reservation(self, payload, headers):
        return self._request("POST", "/bed-reservations", payload, headers)

    def get_bed_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/bed-reservations/{reservation_id}", headers=headers
        )

    def list_bed_reservations(self, headers, params=None):
        return self._request("GET", "/bed-reservations", headers=headers, params=params)

    # ─── Billing claims ────────────────────────────────────────────────────

    def create_billing_claim(self, payload, headers):
        return self._request("POST", "/billing-claims", payload, headers)

    def list_episode_billing_claims(self, episode_id, headers, params=None):
        return self._request(
            "GET",
            f"/episodes/{episode_id}/billing-claims",
            headers=headers,
            params=params,
        )

    def submit_billing_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/billing-claims/{claim_id}/submit", payload or {}, headers
        )

    def record_claim_outcome(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/billing-claims/{claim_id}/record-outcome", payload, headers
        )

    def appeal_billing_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/billing-claims/{claim_id}/appeal", payload or {}, headers
        )


api_client = ApiClient()
