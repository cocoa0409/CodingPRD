"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Titles ----------------
    def create_title(self, payload, headers):
        return self._request("POST", "/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/titles/{title_id}", headers=headers)

    # ---------------- Cuts ----------------
    def create_cut(self, payload, headers):
        return self._request("POST", "/cuts", payload, headers)

    def derive_cut(self, cut_id, payload, headers):
        return self._request("POST", f"/cuts/{cut_id}/derive", payload, headers)

    def lock_cut(self, cut_id, headers):
        return self._request("POST", f"/cuts/{cut_id}/lock", {}, headers)

    def get_cut(self, cut_id, headers):
        return self._request("GET", f"/cuts/{cut_id}", headers=headers)

    def list_cuts(self, headers, params=None):
        return self._request("GET", "/cuts", headers=headers, params=params)

    # ---------------- Characters ----------------
    def create_character(self, payload, headers):
        return self._request("POST", "/characters", payload, headers)

    def get_character(self, character_id, headers):
        return self._request("GET", f"/characters/{character_id}", headers=headers)

    def list_characters(self, headers, params=None):
        return self._request("GET", "/characters", headers=headers, params=params)

    # ---------------- Platform specs ----------------
    def create_platform_spec(self, payload, headers):
        return self._request("POST", "/platform-specs", payload, headers)

    def get_platform_spec(self, platform_spec_id, headers):
        return self._request(
            "GET", f"/platform-specs/{platform_spec_id}", headers=headers
        )

    # ---------------- Voice talents ----------------
    def create_voice_talent(self, payload, headers):
        return self._request("POST", "/voice-talents", payload, headers)

    def get_voice_talent(self, talent_id, headers):
        return self._request("GET", f"/voice-talents/{talent_id}", headers=headers)

    def set_voice_talent_status(self, talent_id, payload, headers):
        return self._request(
            "POST", f"/voice-talents/{talent_id}/set-status", payload, headers
        )

    # ---------------- Studios ----------------
    def create_studio(self, payload, headers):
        return self._request("POST", "/studios", payload, headers)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/studios/{studio_id}", headers=headers)

    def set_studio_status(self, studio_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/set-status", payload, headers
        )

    # ---------------- Localization orders ----------------
    def create_localization_order(self, payload, headers):
        return self._request("POST", "/localization-orders", payload, headers)

    def get_localization_order(self, order_id, headers):
        return self._request(
            "GET", f"/localization-orders/{order_id}", headers=headers
        )

    def list_localization_orders(self, headers, params=None):
        return self._request(
            "GET", "/localization-orders", headers=headers, params=params
        )

    def get_order_invoice(self, order_id, headers):
        return self._request(
            "GET", f"/localization-orders/{order_id}/invoice", headers=headers
        )

    def deliver_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/localization-orders/{order_id}/deliver", payload, headers
        )

    def recall_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/localization-orders/{order_id}/recall", payload, headers
        )

    def cancel_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/localization-orders/{order_id}/cancel", payload, headers
        )

    # ---------------- Script adaptations ----------------
    def create_script_adaptation(self, payload, headers):
        return self._request("POST", "/script-adaptations", payload, headers)

    def get_script_adaptation(self, adaptation_id, headers):
        return self._request(
            "GET", f"/script-adaptations/{adaptation_id}", headers=headers
        )

    def list_script_adaptations(self, headers, params=None):
        return self._request(
            "GET", "/script-adaptations", headers=headers, params=params
        )

    def translate_adaptation(self, adaptation_id, headers):
        return self._request(
            "POST", f"/script-adaptations/{adaptation_id}/translate", {}, headers
        )

    def adapt_adaptation(self, adaptation_id, payload, headers):
        return self._request(
            "POST", f"/script-adaptations/{adaptation_id}/adapt", payload, headers
        )

    def submit_adaptation_review(self, adaptation_id, payload, headers):
        return self._request(
            "POST",
            f"/script-adaptations/{adaptation_id}/submit-review",
            payload,
            headers,
        )

    def review_adaptation(self, adaptation_id, payload, headers):
        return self._request(
            "POST", f"/script-adaptations/{adaptation_id}/review", payload, headers
        )

    # ---------------- Casting assignments ----------------
    def create_casting_assignment(self, payload, headers):
        return self._request("POST", "/casting-assignments", payload, headers)

    def get_casting_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/casting-assignments/{assignment_id}", headers=headers
        )

    def list_casting_assignments(self, headers, params=None):
        return self._request(
            "GET", "/casting-assignments", headers=headers, params=params
        )

    def request_hold(self, assignment_id, headers):
        return self._request(
            "POST", f"/casting-assignments/{assignment_id}/request-hold", {}, headers
        )

    def respond_hold(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/casting-assignments/{assignment_id}/respond-hold",
            payload,
            headers,
        )

    def confirm_casting_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/casting-assignments/{assignment_id}/confirm", {}, headers
        )

    def release_casting_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/casting-assignments/{assignment_id}/release", {}, headers
        )

    # ---------------- Recording sessions ----------------
    def create_recording_session(self, payload, headers):
        return self._request("POST", "/recording-sessions", payload, headers)

    def get_recording_session(self, session_id, headers):
        return self._request(
            "GET", f"/recording-sessions/{session_id}", headers=headers
        )

    def list_recording_sessions(self, headers, params=None):
        return self._request(
            "GET", "/recording-sessions", headers=headers, params=params
        )

    def confirm_recording_session(self, session_id, headers):
        return self._request(
            "POST", f"/recording-sessions/{session_id}/confirm", {}, headers
        )

    def start_recording_session(self, session_id, headers):
        return self._request(
            "POST", f"/recording-sessions/{session_id}/start", {}, headers
        )

    def complete_recording_session(self, session_id, headers):
        return self._request(
            "POST", f"/recording-sessions/{session_id}/complete", {}, headers
        )

    def cancel_recording_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/recording-sessions/{session_id}/cancel", payload, headers
        )

    def no_show_recording_session(self, session_id, headers):
        return self._request(
            "POST", f"/recording-sessions/{session_id}/no-show", {}, headers
        )

    # ---------------- Mix jobs ----------------
    def create_mix_job(self, payload, headers):
        return self._request("POST", "/mix-jobs", payload, headers)

    def get_mix_job(self, mix_job_id, headers):
        return self._request("GET", f"/mix-jobs/{mix_job_id}", headers=headers)

    def list_mix_jobs(self, headers, params=None):
        return self._request("GET", "/mix-jobs", headers=headers, params=params)

    def stem_check_mix_job(self, mix_job_id, headers):
        return self._request("POST", f"/mix-jobs/{mix_job_id}/stem-check", {}, headers)

    def mix_mix_job(self, mix_job_id, payload, headers):
        return self._request("POST", f"/mix-jobs/{mix_job_id}/mix", payload, headers)

    def conform_mix_job(self, mix_job_id, headers):
        return self._request("POST", f"/mix-jobs/{mix_job_id}/conform", {}, headers)

    # ---------------- Quality reviews ----------------
    def create_quality_review(self, payload, headers):
        return self._request("POST", "/quality-reviews", payload, headers)

    def get_quality_review(self, review_id, headers):
        return self._request("GET", f"/quality-reviews/{review_id}", headers=headers)

    def list_quality_reviews(self, headers, params=None):
        return self._request("GET", "/quality-reviews", headers=headers, params=params)

    def start_quality_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/quality-reviews/{review_id}/start", payload, headers
        )

    def decide_quality_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/quality-reviews/{review_id}/decide", payload, headers
        )

    # ---------------- Retake items ----------------
    def get_retake_item(self, retake_item_id, headers):
        return self._request("GET", f"/retake-items/{retake_item_id}", headers=headers)

    def list_retake_items(self, headers, params=None):
        return self._request("GET", "/retake-items", headers=headers, params=params)

    def waive_retake_item(self, retake_item_id, headers):
        return self._request(
            "POST", f"/retake-items/{retake_item_id}/waive", {}, headers
        )

    # ---------------- Talent payments ----------------
    def create_talent_payment(self, payload, headers):
        return self._request("POST", "/talent-payments", payload, headers)

    def get_talent_payment(self, payment_id, headers):
        return self._request("GET", f"/talent-payments/{payment_id}", headers=headers)

    def list_talent_payments(self, headers, params=None):
        return self._request("GET", "/talent-payments", headers=headers, params=params)

    def settle_talent_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/talent-payments/{payment_id}/settle", {}, headers
        )

    # ---------------- Logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
