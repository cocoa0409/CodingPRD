"""API client: one method per endpoint defined in the PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ---- Calibration Standards ----
    def create_standard(self, payload, headers):
        return self._request("POST", "/calibration-standards", payload, headers)

    def list_standards(self, headers, params=None):
        return self._request("GET", "/calibration-standards", headers=headers, params=params)

    def get_standard(self, standard_id, headers):
        return self._request("GET", f"/calibration-standards/{standard_id}", headers=headers)

    def update_standard(self, standard_id, payload, headers):
        return self._request("PUT", f"/calibration-standards/{standard_id}", payload, headers)

    # ---- Calibration Vendors ----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/calibration-vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/calibration-vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/calibration-vendors/{vendor_id}", headers=headers)

    def patch_vendor(self, vendor_id, payload, headers):
        return self._request("PATCH", f"/calibration-vendors/{vendor_id}", payload, headers)

    # ---- Instruments ----
    def create_instrument(self, payload, headers):
        return self._request("POST", "/instruments", payload, headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", "/instruments", headers=headers, params=params)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/instruments/{instrument_id}", headers=headers)

    def release_instrument(self, instrument_id, payload, headers):
        return self._request("POST", f"/instruments/{instrument_id}/release", payload, headers)

    def retire_instrument(self, instrument_id, payload, headers):
        return self._request("POST", f"/instruments/{instrument_id}/retire", payload, headers)

    def drift_trend(self, instrument_id, headers, params=None):
        return self._request("GET", f"/instruments/{instrument_id}/drift-trend", headers=headers, params=params)

    # ---- Calibration Events (child of Instrument) ----
    def create_event(self, instrument_id, payload, headers):
        return self._request("POST", f"/instruments/{instrument_id}/calibration-events", payload, headers)

    def list_instrument_events(self, instrument_id, headers, params=None):
        return self._request("GET", f"/instruments/{instrument_id}/calibration-events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/calibration-events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/calibration-events", headers=headers, params=params)

    def start_event(self, event_id, headers):
        return self._request("POST", f"/calibration-events/{event_id}/start", {}, headers)

    def finalize_event(self, event_id, headers):
        return self._request("POST", f"/calibration-events/{event_id}/finalize", {}, headers)

    def reopen_event(self, event_id, headers):
        return self._request("POST", f"/calibration-events/{event_id}/reopen", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/calibration-events/{event_id}/cancel", {}, headers)

    # ---- Measurement Points (child of CalibrationEvent) ----
    def add_measurement_point(self, event_id, payload, headers):
        return self._request("POST", f"/calibration-events/{event_id}/measurement-points", payload, headers)

    def list_measurement_points(self, event_id, headers, params=None):
        return self._request("GET", f"/calibration-events/{event_id}/measurement-points", headers=headers, params=params)

    # ---- Certificates (child of CalibrationEvent) ----
    def issue_certificate(self, event_id, payload, headers):
        return self._request("POST", f"/calibration-events/{event_id}/certificates", payload, headers)

    def list_event_certificates(self, event_id, headers, params=None):
        return self._request("GET", f"/calibration-events/{event_id}/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def verify_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/verify", {}, headers)

    def reject_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/reject", {}, headers)

    def reissue_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/certificates/{certificate_id}/reissue", payload, headers)

    # ---- Out-of-Tolerance Impacts (child of Instrument) ----
    def list_instrument_impacts(self, instrument_id, headers, params=None):
        return self._request("GET", f"/instruments/{instrument_id}/impacts", headers=headers, params=params)

    def get_impact(self, impact_id, headers):
        return self._request("GET", f"/impacts/{impact_id}", headers=headers)

    def list_impacts(self, headers, params=None):
        return self._request("GET", "/impacts", headers=headers, params=params)

    def get_exposure(self, impact_id, headers, params=None):
        return self._request("GET", f"/impacts/{impact_id}/exposure", headers=headers, params=params)

    def investigate_impact(self, impact_id, headers):
        return self._request("POST", f"/impacts/{impact_id}/investigate", {}, headers)

    def disposition_impact(self, impact_id, payload, headers):
        return self._request("POST", f"/impacts/{impact_id}/disposition", payload, headers)

    def escalate_impact(self, impact_id, headers):
        return self._request("POST", f"/impacts/{impact_id}/escalate", {}, headers)

    def cancel_impact(self, impact_id, headers):
        return self._request("POST", f"/impacts/{impact_id}/cancel", {}, headers)

    # ---- Affected Products (child of OutOfToleranceImpact) ----
    def add_affected_product(self, impact_id, payload, headers):
        return self._request("POST", f"/impacts/{impact_id}/affected-products", payload, headers)

    def list_affected_products(self, impact_id, headers, params=None):
        return self._request("GET", f"/impacts/{impact_id}/affected-products", headers=headers, params=params)

    # ---- Gage R&R Studies (child of Instrument) ----
    def create_study(self, instrument_id, payload, headers):
        return self._request("POST", f"/instruments/{instrument_id}/gage-rr-studies", payload, headers)

    def list_instrument_studies(self, instrument_id, headers, params=None):
        return self._request("GET", f"/instruments/{instrument_id}/gage-rr-studies", headers=headers, params=params)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/gage-rr-studies/{study_id}", headers=headers)

    def add_trial(self, study_id, payload, headers):
        return self._request("POST", f"/gage-rr-studies/{study_id}/trials", payload, headers)

    def list_trials(self, study_id, headers, params=None):
        return self._request("GET", f"/gage-rr-studies/{study_id}/trials", headers=headers, params=params)

    def open_study(self, study_id, headers):
        return self._request("POST", f"/gage-rr-studies/{study_id}/open", {}, headers)

    def analyze_study(self, study_id, headers):
        return self._request("POST", f"/gage-rr-studies/{study_id}/analyze", {}, headers)

    def accept_study(self, study_id, headers):
        return self._request("POST", f"/gage-rr-studies/{study_id}/accept", {}, headers)

    def reject_study(self, study_id, headers):
        return self._request("POST", f"/gage-rr-studies/{study_id}/reject", {}, headers)

    def cancel_study(self, study_id, headers):
        return self._request("POST", f"/gage-rr-studies/{study_id}/cancel", {}, headers)


api_client = ApiClient()
