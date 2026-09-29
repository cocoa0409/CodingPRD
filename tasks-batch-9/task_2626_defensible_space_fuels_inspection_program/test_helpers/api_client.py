"""Typed client for the Defensible Space Fuels Inspection Program API.

One method per endpoint declared by the PRD.  Every method returns the raw
framework response object so that tests keep full control over success/error
validation.  ``headers`` is always explicit: the PRD requires an identity on
every request, and defaulting it here would hide authentication defects.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class FireDistrictClient:
    """Thin wrapper that names each PRD endpoint."""

    def __init__(self, base_url=None):
        self._client = GenericApiClient(base_url)

    # -- plumbing ----------------------------------------------------------
    def request(self, method, path, payload=None, headers=None, params=None):
        return self._client._request(
            method, path, payload=payload, headers=headers, params=params
        )

    def _get(self, path, headers=None, params=None):
        return self.request("GET", path, headers=headers, params=params)

    def _post(self, path, payload=None, headers=None):
        return self.request("POST", path, payload=payload or {}, headers=headers)

    def _patch(self, path, payload=None, headers=None):
        return self.request("PATCH", path, payload=payload or {}, headers=headers)

    # -- logical clock -----------------------------------------------------
    def set_clock(self, to_iso8601, headers=None):
        """Move the district's logical clock; performs no state transitions."""
        return self.request(
            "POST", CLOCK_PATH, payload={"to_iso8601": to_iso8601}, headers=headers
        )

    # -- inspection cycles -------------------------------------------------
    def create_cycle(self, payload, headers=None):
        return self._post(f"{API_PREFIX}/inspection-cycles", payload, headers)

    def activate_cycle(self, cycle_id, headers=None, payload=None):
        return self._post(
            f"{API_PREFIX}/inspection-cycles/{cycle_id}/activate", payload, headers
        )

    def advance_cycle(self, cycle_id, headers=None, payload=None):
        return self._post(
            f"{API_PREFIX}/inspection-cycles/{cycle_id}/advance", payload, headers
        )

    def close_cycle(self, cycle_id, headers=None, payload=None):
        return self._post(
            f"{API_PREFIX}/inspection-cycles/{cycle_id}/close", payload, headers
        )

    def get_cycle(self, cycle_id, headers=None):
        return self._get(f"{API_PREFIX}/inspection-cycles/{cycle_id}", headers)

    def get_cycle_metrics(self, cycle_id, headers=None):
        return self._get(f"{API_PREFIX}/inspection-cycles/{cycle_id}/metrics", headers)

    def get_priority_queue(self, cycle_id, headers=None, params=None):
        return self._get(
            f"{API_PREFIX}/inspection-cycles/{cycle_id}/priority-queue",
            headers,
            params,
        )

    # -- communities -------------------------------------------------------
    def create_community(self, payload, headers=None):
        return self._post(f"{API_PREFIX}/communities", payload, headers)

    def get_community(self, community_id, headers=None):
        return self._get(f"{API_PREFIX}/communities/{community_id}", headers)

    def get_community_metrics(self, community_id, headers=None):
        return self._get(f"{API_PREFIX}/communities/{community_id}/metrics", headers)

    def submit_certification(self, community_id, headers=None, payload=None):
        return self._post(
            f"{API_PREFIX}/communities/{community_id}/submit-certification",
            payload,
            headers,
        )

    def certification_decision(self, community_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/communities/{community_id}/certification-decision",
            payload,
            headers,
        )

    def reopen_organizing(self, community_id, headers=None, payload=None):
        return self._post(
            f"{API_PREFIX}/communities/{community_id}/reopen-organizing",
            payload,
            headers,
        )

    # -- parcels -----------------------------------------------------------
    def create_parcel(self, payload, headers=None):
        return self._post(f"{API_PREFIX}/parcels", payload, headers)

    def get_parcel(self, parcel_id, headers=None):
        return self._get(f"{API_PREFIX}/parcels/{parcel_id}", headers)

    def list_parcels(self, headers=None, params=None):
        return self._get(f"{API_PREFIX}/parcels", headers, params)

    def update_parcel(self, parcel_id, payload, headers=None):
        return self._patch(f"{API_PREFIX}/parcels/{parcel_id}", payload, headers)

    def record_survival_outcome(self, parcel_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/parcels/{parcel_id}/survival-outcome", payload, headers
        )

    def create_discretionary_notice(self, parcel_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/parcels/{parcel_id}/violation-notices", payload, headers
        )

    def open_certificate(self, parcel_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/parcels/{parcel_id}/compliance-certificates",
            payload,
            headers,
        )

    # -- inspectors --------------------------------------------------------
    def create_inspector(self, payload, headers=None):
        return self._post(f"{API_PREFIX}/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers=None):
        return self._get(f"{API_PREFIX}/inspectors/{inspector_id}", headers)

    # -- contractors -------------------------------------------------------
    def create_contractor(self, payload, headers=None):
        return self._post(f"{API_PREFIX}/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers=None):
        return self._get(f"{API_PREFIX}/contractors/{contractor_id}", headers)

    def update_contractor(self, contractor_id, payload, headers=None):
        return self._patch(
            f"{API_PREFIX}/contractors/{contractor_id}", payload, headers
        )

    # -- inspections -------------------------------------------------------
    def create_inspection(self, payload, headers=None):
        return self._post(f"{API_PREFIX}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers=None):
        return self._get(f"{API_PREFIX}/inspections/{inspection_id}", headers)

    def list_inspections(self, headers=None, params=None):
        return self._get(f"{API_PREFIX}/inspections", headers, params)

    def serve_notice(self, inspection_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/inspections/{inspection_id}/notice", payload, headers
        )

    def record_access_denial(self, inspection_id, headers=None, payload=None):
        return self._post(
            f"{API_PREFIX}/inspections/{inspection_id}/access-denial", payload, headers
        )

    def reschedule_inspection(self, inspection_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/inspections/{inspection_id}/reschedule", payload, headers
        )

    def cancel_inspection(self, inspection_id, headers=None, payload=None):
        return self._post(
            f"{API_PREFIX}/inspections/{inspection_id}/cancel", payload, headers
        )

    def create_zone_evaluation(self, inspection_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/inspections/{inspection_id}/zone-evaluations",
            payload,
            headers,
        )

    def create_hardening_finding(self, inspection_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/inspections/{inspection_id}/hardening-findings",
            payload,
            headers,
        )

    def complete_inspection(self, inspection_id, headers=None, payload=None):
        return self._post(
            f"{API_PREFIX}/inspections/{inspection_id}/complete", payload, headers
        )

    # -- zone evaluations / hardening findings ------------------------------
    def get_zone_evaluation(self, zone_evaluation_id, headers=None):
        return self._get(f"{API_PREFIX}/zone-evaluations/{zone_evaluation_id}", headers)

    def list_zone_evaluations(self, headers=None, params=None):
        return self._get(f"{API_PREFIX}/zone-evaluations", headers, params)

    def get_hardening_finding(self, hardening_finding_id, headers=None):
        return self._get(
            f"{API_PREFIX}/hardening-findings/{hardening_finding_id}", headers
        )

    def list_hardening_findings(self, headers=None, params=None):
        return self._get(f"{API_PREFIX}/hardening-findings", headers, params)

    # -- violation notices -------------------------------------------------
    def get_notice(self, notice_id, headers=None):
        return self._get(f"{API_PREFIX}/violation-notices/{notice_id}", headers)

    def list_notices(self, headers=None, params=None):
        return self._get(f"{API_PREFIX}/violation-notices", headers, params)

    def extend_notice(self, notice_id, headers=None, payload=None):
        return self._post(
            f"{API_PREFIX}/violation-notices/{notice_id}/extend", payload, headers
        )

    def void_notice(self, notice_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/violation-notices/{notice_id}/void", payload, headers
        )

    def authorize_abatement(self, notice_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/violation-notices/{notice_id}/authorize-abatement",
            payload,
            headers,
        )

    # -- abatement orders --------------------------------------------------
    def get_order(self, order_id, headers=None):
        return self._get(f"{API_PREFIX}/abatement-orders/{order_id}", headers)

    def list_orders(self, headers=None, params=None):
        return self._get(f"{API_PREFIX}/abatement-orders", headers, params)

    def award_order(self, order_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/abatement-orders/{order_id}/award", payload, headers
        )

    def cancel_order(self, order_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/abatement-orders/{order_id}/cancel", payload, headers
        )

    def complete_work(self, order_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/abatement-orders/{order_id}/complete-work", payload, headers
        )

    def verify_completion(self, order_id, headers=None, payload=None):
        return self._post(
            f"{API_PREFIX}/abatement-orders/{order_id}/verify-completion",
            payload,
            headers,
        )

    def record_payment(self, order_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/abatement-orders/{order_id}/payments", payload, headers
        )

    # -- cost recovery payments --------------------------------------------
    def get_payment(self, payment_id, headers=None):
        return self._get(f"{API_PREFIX}/cost-recovery-payments/{payment_id}", headers)

    def list_payments(self, headers=None, params=None):
        return self._get(f"{API_PREFIX}/cost-recovery-payments", headers, params)

    # -- support programs --------------------------------------------------
    def create_support_program(self, payload, headers=None):
        return self._post(f"{API_PREFIX}/support-programs", payload, headers)

    def get_support_program(self, support_program_id, headers=None):
        return self._get(f"{API_PREFIX}/support-programs/{support_program_id}", headers)

    def list_support_programs(self, headers=None, params=None):
        return self._get(f"{API_PREFIX}/support-programs", headers, params)

    # -- support enrollments -----------------------------------------------
    def create_enrollment(self, payload, headers=None):
        return self._post(f"{API_PREFIX}/support-enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers=None):
        return self._get(f"{API_PREFIX}/support-enrollments/{enrollment_id}", headers)

    def list_enrollments(self, headers=None, params=None):
        return self._get(f"{API_PREFIX}/support-enrollments", headers, params)

    def complete_enrollment(self, enrollment_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/support-enrollments/{enrollment_id}/complete",
            payload,
            headers,
        )

    def cancel_enrollment(self, enrollment_id, headers=None, payload=None):
        return self._post(
            f"{API_PREFIX}/support-enrollments/{enrollment_id}/cancel", payload, headers
        )

    # -- compliance certificates -------------------------------------------
    def get_certificate(self, certificate_id, headers=None):
        return self._get(
            f"{API_PREFIX}/compliance-certificates/{certificate_id}", headers
        )

    def list_certificates(self, headers=None, params=None):
        return self._get(f"{API_PREFIX}/compliance-certificates", headers, params)

    def certificate_decision(self, certificate_id, payload, headers=None):
        return self._post(
            f"{API_PREFIX}/compliance-certificates/{certificate_id}/decision",
            payload,
            headers,
        )
