"""API client: one method per endpoint defined in the PRD (§4).

Every business resource lives directly under the `/hail-ops` prefix; the four
nested read paths are the reverse lookups described in PRD §2.10.  The logical
clock endpoint sits outside the business prefix.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/hail-ops"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Hail Catastrophe PDR Ops API."""

    # ── Logical clock ─────────────────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── Storm events ──────────────────────────────────────────────────────────

    def create_storm_event(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/storm-events", payload, headers)

    def get_storm_event(self, storm_event_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/storm-events/{storm_event_id}", headers=headers
        )

    def decide_storm_event(self, storm_event_id: str, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/storm-events/{storm_event_id}/decision", payload, headers
        )

    def activate_storm_event(self, storm_event_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/storm-events/{storm_event_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def demobilize_storm_event(self, storm_event_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/storm-events/{storm_event_id}/demobilize",
            payload if payload is not None else {},
            headers,
        )

    def close_storm_event(self, storm_event_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/storm-events/{storm_event_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # ── Facilities ────────────────────────────────────────────────────────────

    def create_facility(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers):
        return self._request("GET", f"{PREFIX}/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/facilities", headers=headers, params=params)

    def commission_facility(self, facility_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/facilities/{facility_id}/commission",
            payload if payload is not None else {},
            headers,
        )

    def get_throughput_summary(self, facility_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/facilities/{facility_id}/throughput-summary", headers=headers
        )

    # ── Permits ───────────────────────────────────────────────────────────────

    def create_permit(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/permits", payload, headers)

    def decide_permit(self, permit_id: str, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/decision", payload, headers
        )

    def list_facility_permits(self, facility_id: str, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/facilities/{facility_id}/permits", headers=headers, params=params
        )

    # ── Housing units ─────────────────────────────────────────────────────────

    def create_housing_unit(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/housing-units", payload, headers)

    def list_facility_housing_units(
        self, facility_id: str, headers, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/facilities/{facility_id}/housing-units",
            headers=headers,
            params=params,
        )

    # ── Technicians ───────────────────────────────────────────────────────────

    def create_technician(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/technicians", payload, headers)

    def get_technician(self, technician_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/technicians/{technician_id}", headers=headers
        )

    # ── Crew deployments ──────────────────────────────────────────────────────

    def create_crew_deployment(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/crew-deployments", payload, headers)

    def get_crew_deployment(self, deployment_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/crew-deployments/{deployment_id}", headers=headers
        )

    def list_crew_deployments(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/crew-deployments", headers=headers, params=params
        )

    def set_crew_deployment_status(self, deployment_id: str, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/crew-deployments/{deployment_id}/status", payload, headers
        )

    # ── Insurers ──────────────────────────────────────────────────────────────

    def create_insurer(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/insurers", payload, headers)

    def get_insurer(self, insurer_id: str, headers):
        return self._request("GET", f"{PREFIX}/insurers/{insurer_id}", headers=headers)

    # ── Rate agreements ───────────────────────────────────────────────────────

    def create_rate_agreement(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/rate-agreements", payload, headers)

    def get_rate_agreement(self, rate_agreement_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/rate-agreements/{rate_agreement_id}", headers=headers
        )

    def list_rate_agreements(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/rate-agreements", headers=headers, params=params
        )

    def activate_rate_agreement(self, rate_agreement_id: str, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/rate-agreements/{rate_agreement_id}/activate",
            payload,
            headers,
        )

    # ── Vehicles ──────────────────────────────────────────────────────────────

    def create_vehicle(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers):
        return self._request("GET", f"{PREFIX}/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/vehicles", headers=headers, params=params)

    def estimate_vehicle(self, vehicle_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/vehicles/{vehicle_id}/estimate",
            payload if payload is not None else {},
            headers,
        )

    def triage_vehicle(self, vehicle_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/vehicles/{vehicle_id}/triage",
            payload if payload is not None else {},
            headers,
        )

    def vehicle_billing(self, vehicle_id: str, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/vehicles/{vehicle_id}/billing", payload, headers
        )

    def start_vehicle_repair(self, vehicle_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/vehicles/{vehicle_id}/start-repair",
            payload if payload is not None else {},
            headers,
        )

    def release_vehicle(self, vehicle_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/vehicles/{vehicle_id}/release",
            payload if payload is not None else {},
            headers,
        )

    # ── Damage lines ──────────────────────────────────────────────────────────

    def create_damage_line(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/damage-lines", payload, headers)

    def list_vehicle_damage_lines(
        self, vehicle_id: str, headers, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/vehicles/{vehicle_id}/damage-lines",
            headers=headers,
            params=params,
        )

    # ── Work tickets ──────────────────────────────────────────────────────────

    def create_work_ticket(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/work-tickets", payload, headers)

    def get_work_ticket(self, work_ticket_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/work-tickets/{work_ticket_id}", headers=headers
        )

    def list_work_tickets(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/work-tickets", headers=headers, params=params)

    def submit_work_ticket(self, work_ticket_id: str, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/work-tickets/{work_ticket_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    # ── Supplements ───────────────────────────────────────────────────────────

    def create_supplement(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/supplements", payload, headers)

    def get_supplement(self, supplement_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/supplements/{supplement_id}", headers=headers
        )

    def list_supplements(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/supplements", headers=headers, params=params)

    def review_supplement(self, supplement_id: str, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/supplements/{supplement_id}/review", payload, headers
        )

    def revise_supplement(self, supplement_id: str, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/supplements/{supplement_id}/revise", payload, headers
        )

    # ── Quality inspections ───────────────────────────────────────────────────

    def create_quality_inspection(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{PREFIX}/quality-inspections", payload, headers)

    def get_quality_inspection(self, inspection_id: str, headers):
        return self._request(
            "GET", f"{PREFIX}/quality-inspections/{inspection_id}", headers=headers
        )

    def list_quality_inspections(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/quality-inspections", headers=headers, params=params
        )

    # ── Raw escape hatch for header-ladder tests ──────────────────────────────

    def raw_post(self, path: str, payload=None, headers=None):
        """POST an arbitrary path with arbitrary (possibly absent) headers."""
        return self._request("POST", path, payload, headers)

    def raw_get(self, path: str, headers=None, params=None):
        """GET an arbitrary path with arbitrary (possibly absent) headers."""
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
