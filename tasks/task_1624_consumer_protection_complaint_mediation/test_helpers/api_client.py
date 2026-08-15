"""API client: one method per endpoint defined in the PRD (§4 endpoint index)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/consumer-protection"


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- Consumers ---
    def create_consumer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/consumers", payload, headers)

    def get_consumer(self, consumer_id, headers):
        return self._request("GET", f"{PREFIX}/consumers/{consumer_id}", headers=headers)

    # --- Businesses ---
    def create_business(self, payload, headers):
        return self._request("POST", f"{PREFIX}/businesses", payload, headers)

    def list_businesses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/businesses", headers=headers, params=params)

    def get_business(self, business_id, headers):
        return self._request("GET", f"{PREFIX}/businesses/{business_id}", headers=headers)

    def set_rating_method(self, business_id, payload, headers):
        return self._request("POST", f"{PREFIX}/businesses/{business_id}/rating-method", payload, headers)

    def get_business_rating(self, business_id, headers):
        return self._request("GET", f"{PREFIX}/businesses/{business_id}/rating", headers=headers)

    def get_business_complaint_statistics(self, business_id, headers):
        return self._request("GET", f"{PREFIX}/businesses/{business_id}/complaint-statistics", headers=headers)

    # --- Mediators ---
    def create_mediator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mediators", payload, headers)

    def get_mediator(self, mediator_id, headers):
        return self._request("GET", f"{PREFIX}/mediators/{mediator_id}", headers=headers)

    def deactivate_mediator(self, mediator_id, headers=None):
        return self._request("POST", f"{PREFIX}/mediators/{mediator_id}/deactivate", {}, headers)

    # --- Mediation rooms ---
    def list_mediation_rooms(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/mediation-rooms", headers=headers, params=params)

    def create_mediation_room(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mediation-rooms", payload, headers)

    def get_mediation_room(self, room_id, headers):
        return self._request("GET", f"{PREFIX}/mediation-rooms/{room_id}", headers=headers)

    def take_room_out_of_service(self, room_id, headers=None):
        return self._request("POST", f"{PREFIX}/mediation-rooms/{room_id}/take-out-of-service", {}, headers)

    # --- Complaints ---
    def create_complaint(self, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"{PREFIX}/complaints/{complaint_id}", headers=headers)

    def screen_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/screen", payload, headers)

    def appeal_complaint(self, complaint_id, headers=None):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/appeal", {}, headers)

    def withdraw_complaint(self, complaint_id, headers=None):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/withdraw", {}, headers)

    def notify_business(self, complaint_id, headers=None):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/notify-business", {}, headers)

    def submit_business_response(self, complaint_id, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/business-responses", payload, headers)

    def offer_mediation(self, complaint_id, headers=None):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/offer-mediation", {}, headers)

    def close_unresolved(self, complaint_id, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/close-unresolved", payload, headers)

    def retract_publication(self, complaint_id, headers=None):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/retract-publication", {}, headers)

    def refer_enforcement(self, complaint_id, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/refer-enforcement", payload, headers)

    # --- Business responses ---
    def list_business_responses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/business-responses", headers=headers, params=params)

    def get_business_response(self, response_id, headers):
        return self._request("GET", f"{PREFIX}/business-responses/{response_id}", headers=headers)

    def review_business_response(self, response_id, payload, headers):
        return self._request("POST", f"{PREFIX}/business-responses/{response_id}/review", payload, headers)

    # --- Mediation sessions ---
    def create_mediation_session(self, complaint_id, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/mediation-sessions", payload, headers)

    def list_mediation_sessions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/mediation-sessions", headers=headers, params=params)

    def get_mediation_session(self, session_id, headers):
        return self._request("GET", f"{PREFIX}/mediation-sessions/{session_id}", headers=headers)

    def confirm_session(self, session_id, headers=None):
        return self._request("POST", f"{PREFIX}/mediation-sessions/{session_id}/confirm", {}, headers)

    def decline_session(self, session_id, headers=None):
        return self._request("POST", f"{PREFIX}/mediation-sessions/{session_id}/decline", {}, headers)

    def cancel_session(self, session_id, headers=None):
        return self._request("POST", f"{PREFIX}/mediation-sessions/{session_id}/cancel", {}, headers)

    def complete_session(self, session_id, payload, headers):
        return self._request("POST", f"{PREFIX}/mediation-sessions/{session_id}/complete", payload, headers)

    # --- Settlement offers ---
    def create_settlement_offer(self, complaint_id, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/settlement-offers", payload, headers)

    def list_settlement_offers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/settlement-offers", headers=headers, params=params)

    def get_settlement_offer(self, offer_id, headers):
        return self._request("GET", f"{PREFIX}/settlement-offers/{offer_id}", headers=headers)

    def accept_offer(self, offer_id, headers=None):
        return self._request("POST", f"{PREFIX}/settlement-offers/{offer_id}/accept", {}, headers)

    def reject_offer(self, offer_id, headers=None):
        return self._request("POST", f"{PREFIX}/settlement-offers/{offer_id}/reject", {}, headers)

    def withdraw_offer(self, offer_id, headers=None):
        return self._request("POST", f"{PREFIX}/settlement-offers/{offer_id}/withdraw", {}, headers)

    def rescind_offer(self, offer_id, headers=None):
        return self._request("POST", f"{PREFIX}/settlement-offers/{offer_id}/rescind", {}, headers)

    # --- Settlements ---
    def create_settlement(self, complaint_id, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"{PREFIX}/settlements/{settlement_id}", headers=headers)

    def execute_settlement(self, settlement_id, headers=None):
        return self._request("POST", f"{PREFIX}/settlements/{settlement_id}/execute", {}, headers)

    def mark_settlement_breached(self, settlement_id, headers=None):
        return self._request("POST", f"{PREFIX}/settlements/{settlement_id}/mark-breached", {}, headers)

    # --- Restitution payments ---
    def pledge_restitution_payment(self, business_id, payload, headers):
        return self._request("POST", f"{PREFIX}/businesses/{business_id}/restitution-payments", payload, headers)

    def list_restitution_payments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/restitution-payments", headers=headers, params=params)

    def get_restitution_payment(self, payment_id, headers):
        return self._request("GET", f"{PREFIX}/restitution-payments/{payment_id}", headers=headers)

    def mark_payment_received(self, payment_id, headers=None):
        return self._request("POST", f"{PREFIX}/restitution-payments/{payment_id}/mark-received", {}, headers)

    def mark_payment_returned(self, payment_id, headers=None):
        return self._request("POST", f"{PREFIX}/restitution-payments/{payment_id}/mark-returned", {}, headers)

    def disburse_payment(self, payment_id, headers=None):
        return self._request("POST", f"{PREFIX}/restitution-payments/{payment_id}/disburse", {}, headers)

    # --- Enforcement referrals ---
    def list_enforcement_referrals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/enforcement-referrals", headers=headers, params=params)

    def get_enforcement_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/enforcement-referrals/{referral_id}", headers=headers)

    def review_enforcement_referral(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/enforcement-referrals/{referral_id}/review", payload, headers)

    # --- Scam alerts ---
    def create_scam_alert(self, payload, headers):
        return self._request("POST", f"{PREFIX}/scam-alerts", payload, headers)

    def list_scam_alerts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/scam-alerts", headers=headers, params=params)

    def get_scam_alert(self, alert_id, headers):
        return self._request("GET", f"{PREFIX}/scam-alerts/{alert_id}", headers=headers)

    def publish_scam_alert(self, alert_id, headers=None):
        return self._request("POST", f"{PREFIX}/scam-alerts/{alert_id}/publish", {}, headers)

    def archive_scam_alert(self, alert_id, headers=None):
        return self._request("POST", f"{PREFIX}/scam-alerts/{alert_id}/archive", {}, headers)

    # --- Audit events ---
    def list_complaint_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/complaint-events", headers=headers, params=params)

    def get_complaint_event(self, event_id, headers):
        return self._request("GET", f"{PREFIX}/complaint-events/{event_id}", headers=headers)


api_client = ApiClient()
