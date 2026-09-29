"""API client: one method per endpoint the PRD defines, all under the /tdr prefix."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/tdr"


class ApiClient(GenericApiClient):
    """Typed endpoint methods for the Transfer of Development Rights program API."""

    # ── Logical clock and operations ────────────────────────────────────────
    def set_clock(self, current_utc: str, headers=None):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    def set_clock_raw(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    def run_compliance_sweep(self, headers=None, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/_ops/compliance-sweep", payload if payload is not None else {}, headers,
        )

    # ── Parties ─────────────────────────────────────────────────────────────
    def create_party(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/parties", payload, headers)

    def get_party(self, party_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/parties/{party_id}", headers=headers)

    def list_parties(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/parties", headers=headers, params=params)

    def party_account_action(self, party_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/parties/{party_id}/account-actions", payload, headers,
        )

    # ── Sending areas ───────────────────────────────────────────────────────
    def create_sending_area(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/sending-areas", payload, headers)

    def activate_sending_area(self, area_id: str, headers=None, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/sending-areas/{area_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def close_sending_area(self, area_id: str, headers=None, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/sending-areas/{area_id}/close",
            payload if payload is not None else {}, headers,
        )

    def get_sending_area(self, area_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/sending-areas/{area_id}", headers=headers)

    def list_sending_areas(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/sending-areas", headers=headers, params=params)

    # ── Receiving areas ─────────────────────────────────────────────────────
    def create_receiving_area(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/receiving-areas", payload, headers)

    def activate_receiving_area(self, area_id: str, headers=None, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/receiving-areas/{area_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def get_receiving_area(self, area_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/receiving-areas/{area_id}", headers=headers)

    def list_receiving_areas(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/receiving-areas", headers=headers, params=params)

    # ── Appraisal schedules ─────────────────────────────────────────────────
    def create_appraisal_schedule(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/appraisal-schedules", payload, headers)

    def get_appraisal_schedule(self, schedule_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/appraisal-schedules/{schedule_id}", headers=headers)

    def list_appraisal_schedules(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/appraisal-schedules", headers=headers, params=params)

    # ── Sending parcels ─────────────────────────────────────────────────────
    def create_sending_parcel(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/sending-parcels", payload, headers)

    def get_sending_parcel(self, parcel_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/sending-parcels/{parcel_id}", headers=headers)

    def list_sending_parcels(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/sending-parcels", headers=headers, params=params)

    # ── Severance applications ──────────────────────────────────────────────
    def create_severance_application(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/severance-applications", payload, headers)

    def get_severance_application(self, app_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/severance-applications/{app_id}", headers=headers)

    def list_severance_applications(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/severance-applications", headers=headers, params=params,
        )

    def screen_severance_application(self, app_id: str, headers=None, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/severance-applications/{app_id}/screen",
            payload if payload is not None else {}, headers,
        )

    def review_severance_application(self, app_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/severance-applications/{app_id}/review-decision", payload, headers,
        )

    def resubmit_severance_application(self, app_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/severance-applications/{app_id}/resubmit", payload, headers,
        )

    def certify_severance_application(self, app_id: str, headers=None, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/severance-applications/{app_id}/certify",
            payload if payload is not None else {}, headers,
        )

    # ── Conservation easements and inspections ──────────────────────────────
    def get_conservation_easement(self, easement_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/conservation-easements/{easement_id}", headers=headers,
        )

    def list_conservation_easements(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/conservation-easements", headers=headers, params=params,
        )

    def create_inspection(self, easement_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/conservation-easements/{easement_id}/inspections", payload, headers,
        )

    def list_easement_inspections(self, easement_id: str, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/conservation-easements/{easement_id}/inspections",
            headers=headers, params=params,
        )

    def get_monitoring_inspection(self, inspection_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/monitoring-inspections/{inspection_id}", headers=headers,
        )

    def verify_cure(self, inspection_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/monitoring-inspections/{inspection_id}/cure-verification",
            payload, headers,
        )

    # ── Certificates and chain of title ─────────────────────────────────────
    def get_certificate(self, certificate_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/certificates", headers=headers, params=params)

    def split_certificate(self, certificate_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/certificates/{certificate_id}/split", payload, headers,
        )

    def retire_certificate_units(self, certificate_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/certificates/{certificate_id}/retire", payload, headers,
        )

    def get_certificate_transfer(self, transfer_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/certificate-transfers/{transfer_id}", headers=headers,
        )

    def list_certificate_transfers(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/certificate-transfers", headers=headers, params=params,
        )

    # ── Market transactions ─────────────────────────────────────────────────
    def create_market_transaction(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/market-transactions", payload, headers)

    def get_market_transaction(self, tx_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/market-transactions/{tx_id}", headers=headers)

    def list_market_transactions(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/market-transactions", headers=headers, params=params)

    def settle_market_transaction(self, tx_id: str, headers=None, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/market-transactions/{tx_id}/settle",
            payload if payload is not None else {}, headers,
        )

    def cancel_market_transaction(self, tx_id: str, headers=None, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/market-transactions/{tx_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def reverse_market_transaction(self, tx_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/market-transactions/{tx_id}/reverse", payload, headers,
        )

    # ── Receiving-site applications and redemptions ─────────────────────────
    def create_receiving_site_application(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/receiving-site-applications", payload, headers)

    def get_receiving_site_application(self, app_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/receiving-site-applications/{app_id}", headers=headers,
        )

    def list_receiving_site_applications(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/receiving-site-applications", headers=headers, params=params,
        )

    def allocate_redemption(self, app_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/receiving-site-applications/{app_id}/redemptions", payload, headers,
        )

    def design_review_decision(self, app_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/receiving-site-applications/{app_id}/design-review-decision",
            payload, headers,
        )

    def resubmit_design(self, app_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/receiving-site-applications/{app_id}/resubmit-design",
            payload, headers,
        )

    def finalize_receiving_site_application(self, app_id: str, headers=None, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/receiving-site-applications/{app_id}/finalize",
            payload if payload is not None else {}, headers,
        )

    def get_certificate_redemption(self, redemption_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/certificate-redemptions/{redemption_id}", headers=headers,
        )

    def list_certificate_redemptions(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/certificate-redemptions", headers=headers, params=params,
        )

    def release_redemption(self, redemption_id: str, headers=None, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/certificate-redemptions/{redemption_id}/release",
            payload if payload is not None else {}, headers,
        )

    # ── Program evaluations ─────────────────────────────────────────────────
    def create_evaluation(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/evaluations", payload, headers)

    def get_evaluation(self, evaluation_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/evaluations/{evaluation_id}", headers=headers)

    def list_evaluations(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/evaluations", headers=headers, params=params)


api_client = ApiClient()
