"""One method per endpoint published in PRD §4.

Every method returns the raw ``requests.Response`` so that tests can assert on
HTTP status codes and on the envelope described in PRD §2.2.  All endpoints are
mounted at the service root, so no path prefix is applied.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin, fully typed façade over the live animal travel HTTP API."""

    # ------------------------------------------------------------------
    # Species profiles (PRD §3.1)
    # ------------------------------------------------------------------

    def create_species_profile(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/species-profiles", payload, headers=headers)

    def get_species_profile(
        self, species_profile_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/species-profiles/{species_profile_id}", headers=headers
        )

    def list_species_profiles(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/species-profiles", headers=headers, params=params)

    def set_species_profile_status(
        self, species_profile_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PUT",
            f"/species-profiles/{species_profile_id}/status",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Breed restrictions (PRD §3.1)
    # ------------------------------------------------------------------

    def create_breed_restriction(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/breed-restrictions", payload, headers=headers)

    def list_species_breed_restrictions(
        self,
        species_profile_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/species-profiles/{species_profile_id}/breed-restrictions",
            headers=headers,
            params=params,
        )

    def get_breed_restriction(
        self, breed_restriction_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/breed-restrictions/{breed_restriction_id}", headers=headers
        )

    def set_breed_restriction_status(
        self, breed_restriction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PUT",
            f"/breed-restrictions/{breed_restriction_id}/status",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Destination requirements (PRD §3.1)
    # ------------------------------------------------------------------

    def create_destination_requirement(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/destination-requirements", payload, headers=headers
        )

    def list_species_destination_requirements(
        self,
        species_profile_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/species-profiles/{species_profile_id}/destination-requirements",
            headers=headers,
            params=params,
        )

    def get_destination_requirement(
        self, destination_requirement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/destination-requirements/{destination_requirement_id}",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Container models (PRD §3.2)
    # ------------------------------------------------------------------

    def create_container_model(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/container-models", payload, headers=headers)

    def get_container_model(
        self, container_model_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/container-models/{container_model_id}", headers=headers
        )

    def list_container_models(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/container-models", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Stations (PRD §3.2)
    # ------------------------------------------------------------------

    def create_station(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/stations", payload, headers=headers)

    def get_station(self, station_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_stations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/stations", headers=headers, params=params)

    def set_station_status(
        self, station_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PUT", f"/stations/{station_id}/status", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Temperature embargo rules (PRD §3.2)
    # ------------------------------------------------------------------

    def create_temperature_embargo_rule(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/temperature-embargo-rules", payload, headers=headers
        )

    def list_station_temperature_embargo_rules(
        self,
        station_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/stations/{station_id}/temperature-embargo-rules",
            headers=headers,
            params=params,
        )

    def get_temperature_embargo_rule(
        self, embargo_rule_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/temperature-embargo-rules/{embargo_rule_id}", headers=headers
        )

    def set_temperature_embargo_rule_status(
        self, embargo_rule_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PUT",
            f"/temperature-embargo-rules/{embargo_rule_id}/status",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Flight legs (PRD §3.3)
    # ------------------------------------------------------------------

    def create_flight_leg(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/flight-legs", payload, headers=headers)

    def get_flight_leg(
        self, flight_leg_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/flight-legs/{flight_leg_id}", headers=headers)

    def list_flight_legs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/flight-legs", headers=headers, params=params)

    def update_flight_leg_forecast(
        self, flight_leg_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PUT", f"/flight-legs/{flight_leg_id}/forecast", payload, headers=headers
        )

    def delay_flight_leg(
        self, flight_leg_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/flight-legs/{flight_leg_id}/delay", payload, headers=headers
        )

    def restore_flight_leg_schedule(
        self, flight_leg_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/flight-legs/{flight_leg_id}/restore-schedule",
            payload,
            headers=headers,
        )

    def cancel_flight_leg(
        self,
        flight_leg_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/flight-legs/{flight_leg_id}/cancel", payload or {}, headers=headers
        )

    def depart_flight_leg(
        self,
        flight_leg_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/flight-legs/{flight_leg_id}/depart", payload or {}, headers=headers
        )

    def arrive_flight_leg(
        self,
        flight_leg_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/flight-legs/{flight_leg_id}/arrive", payload or {}, headers=headers
        )

    # ------------------------------------------------------------------
    # Reservations (PRD §3.4)
    # ------------------------------------------------------------------

    def create_reservation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/reservations", payload, headers=headers)

    def get_reservation(
        self, reservation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/reservations", headers=headers, params=params)

    def get_reservation_charge_summary(
        self, reservation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/reservations/{reservation_id}/charge-summary", headers=headers
        )

    def confirm_reservation(
        self,
        reservation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/reservations/{reservation_id}/confirm", payload or {}, headers=headers
        )

    def cancel_reservation(
        self,
        reservation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancel", payload or {}, headers=headers
        )

    def verify_reservation_compliance(
        self,
        reservation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/reservations/{reservation_id}/verify-compliance",
            payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Animal records (PRD §3.4)
    # ------------------------------------------------------------------

    def create_animal_record(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/animal-records", payload, headers=headers)

    def get_animal_record(
        self, animal_record_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/animal-records/{animal_record_id}", headers=headers
        )

    def list_animal_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/animal-records", headers=headers, params=params)

    def update_animal_record(
        self, animal_record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PUT", f"/animal-records/{animal_record_id}", payload, headers=headers
        )

    def screen_animal_record(
        self,
        animal_record_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/animal-records/{animal_record_id}/screen",
            payload or {},
            headers=headers,
        )

    def mark_animal_record_travel_ready(
        self,
        animal_record_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/animal-records/{animal_record_id}/mark-travel-ready",
            payload or {},
            headers=headers,
        )

    def deny_animal_record(
        self,
        animal_record_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/animal-records/{animal_record_id}/deny",
            payload or {},
            headers=headers,
        )

    def list_animal_health_documents(
        self,
        animal_record_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/animal-records/{animal_record_id}/health-documents",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Segment assignments (PRD §3.5)
    # ------------------------------------------------------------------

    def create_segment_assignment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/segment-assignments", payload, headers=headers)

    def get_segment_assignment(
        self, segment_assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/segment-assignments/{segment_assignment_id}", headers=headers
        )

    def list_segment_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/segment-assignments", headers=headers, params=params
        )

    def accept_segment_assignment(
        self,
        segment_assignment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/segment-assignments/{segment_assignment_id}/accept",
            payload or {},
            headers=headers,
        )

    def release_segment_assignment(
        self,
        segment_assignment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/segment-assignments/{segment_assignment_id}/release",
            payload or {},
            headers=headers,
        )

    def offload_segment_assignment(
        self,
        segment_assignment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/segment-assignments/{segment_assignment_id}/offload",
            payload or {},
            headers=headers,
        )

    def list_segment_welfare_checks(
        self,
        segment_assignment_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/segment-assignments/{segment_assignment_id}/welfare-checks",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Welfare checks (PRD §3.7)
    # ------------------------------------------------------------------

    def create_welfare_check(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/welfare-checks", payload, headers=headers)

    # ------------------------------------------------------------------
    # Health documents (PRD §3.6)
    # ------------------------------------------------------------------

    def create_health_document(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/health-documents", payload, headers=headers)

    def get_health_document(
        self, health_document_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/health-documents/{health_document_id}", headers=headers
        )

    def start_health_document_review(
        self,
        health_document_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/health-documents/{health_document_id}/start-review",
            payload or {},
            headers=headers,
        )

    def verify_health_document(
        self,
        health_document_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/health-documents/{health_document_id}/verify",
            payload or {},
            headers=headers,
        )

    def reject_health_document(
        self,
        health_document_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/health-documents/{health_document_id}/reject",
            payload or {},
            headers=headers,
        )

    def resubmit_health_document(
        self, health_document_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/health-documents/{health_document_id}/resubmit",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Kennel allocations (PRD §3.7)
    # ------------------------------------------------------------------

    def create_kennel_allocation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/kennel-allocations", payload, headers=headers)

    def get_kennel_allocation(
        self, kennel_allocation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/kennel-allocations/{kennel_allocation_id}", headers=headers
        )

    def list_kennel_allocations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/kennel-allocations", headers=headers, params=params
        )

    def occupy_kennel_allocation(
        self,
        kennel_allocation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/kennel-allocations/{kennel_allocation_id}/occupy",
            payload or {},
            headers=headers,
        )

    def release_kennel_allocation(
        self,
        kennel_allocation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/kennel-allocations/{kennel_allocation_id}/release",
            payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Irregular operations care sweeps (PRD §3.8)
    # ------------------------------------------------------------------

    def create_irops_care_sweep(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/irops-care-sweeps", payload, headers=headers)

    # ------------------------------------------------------------------
    # Animal incidents (PRD §3.9)
    # ------------------------------------------------------------------

    def create_animal_incident(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/animal-incidents", payload, headers=headers)

    def get_animal_incident(
        self, animal_incident_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/animal-incidents/{animal_incident_id}", headers=headers
        )

    def list_animal_incidents(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/animal-incidents", headers=headers, params=params)

    def investigate_animal_incident(
        self,
        animal_incident_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/animal-incidents/{animal_incident_id}/investigate",
            payload or {},
            headers=headers,
        )

    def disclose_animal_incident(
        self,
        animal_incident_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/animal-incidents/{animal_incident_id}/disclose",
            payload or {},
            headers=headers,
        )

    def close_animal_incident(
        self, animal_incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/animal-incidents/{animal_incident_id}/close",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Logical clock (PRD §2.7)
    # ------------------------------------------------------------------

    def set_clock(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    def get_clock(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/_clock", headers=headers)

    # ------------------------------------------------------------------
    # Generic escape hatches for envelope-level probes
    # ------------------------------------------------------------------

    def get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", path, headers=headers, params=params)

    def post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("POST", path, payload, headers=headers)


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
