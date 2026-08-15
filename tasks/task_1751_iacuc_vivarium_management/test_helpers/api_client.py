"""API client: one method per endpoint defined in PRD §4.

All paths live under the /iacuc prefix. The base _request() method is
inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/iacuc/_clock/set_current_utc", payload, headers)

    # --- investigators / grants ---
    def create_investigator(self, payload, headers):
        return self._request("POST", "/iacuc/investigators", payload, headers)

    def get_investigator(self, investigator_id, headers):
        return self._request(
            "GET", f"/iacuc/investigators/{investigator_id}", headers=headers,
        )

    def list_investigator_grants(self, investigator_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/investigators/{investigator_id}/grants",
            headers=headers, params=params,
        )

    def list_investigator_protocols(self, investigator_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/investigators/{investigator_id}/protocols",
            headers=headers, params=params,
        )

    def create_grant(self, payload, headers):
        return self._request("POST", "/iacuc/grants", payload, headers)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/iacuc/grants/{grant_id}", headers=headers)

    def list_grant_protocols(self, grant_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/grants/{grant_id}/protocols", headers=headers, params=params,
        )

    def list_grant_charges(self, grant_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/grants/{grant_id}/charges", headers=headers, params=params,
        )

    # --- personnel / training / occupational health ---
    def create_personnel(self, payload, headers):
        return self._request("POST", "/iacuc/personnel", payload, headers)

    def get_personnel(self, personnel_id, headers):
        return self._request("GET", f"/iacuc/personnel/{personnel_id}", headers=headers)

    def create_training_enrollment(self, payload, headers):
        return self._request("POST", "/iacuc/training-enrollments", payload, headers)

    def list_personnel_training_enrollments(self, personnel_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/personnel/{personnel_id}/training-enrollments",
            headers=headers, params=params,
        )

    def complete_training_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/iacuc/training-enrollments/{enrollment_id}/complete",
            headers=headers,
        )

    def create_occ_health_enrollment(self, payload, headers):
        return self._request("POST", "/iacuc/occ-health-enrollments", payload, headers)

    def list_personnel_occ_health_enrollments(self, personnel_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/personnel/{personnel_id}/occ-health-enrollments",
            headers=headers, params=params,
        )

    def clear_occ_health_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/iacuc/occ-health-enrollments/{enrollment_id}/clear",
            headers=headers,
        )

    # --- protocols ---
    def create_protocol(self, payload, headers):
        return self._request("POST", "/iacuc/protocols", payload, headers)

    def get_protocol(self, protocol_id, headers):
        return self._request("GET", f"/iacuc/protocols/{protocol_id}", headers=headers)

    def submit_protocol(self, protocol_id, headers):
        return self._request(
            "POST", f"/iacuc/protocols/{protocol_id}/submit", headers=headers,
        )

    def record_review_decisions(self, protocol_id, payload, headers):
        return self._request(
            "POST", f"/iacuc/protocols/{protocol_id}/review-decisions",
            payload, headers,
        )

    def list_protocol_reviewers(self, protocol_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/protocols/{protocol_id}/reviewers",
            headers=headers, params=params,
        )

    def suspend_protocol(self, protocol_id, payload, headers):
        return self._request(
            "POST", f"/iacuc/protocols/{protocol_id}/suspend", payload, headers,
        )

    def reinstate_protocol(self, protocol_id, headers):
        return self._request(
            "POST", f"/iacuc/protocols/{protocol_id}/reinstate", headers=headers,
        )

    def attach_protocol_personnel(self, protocol_id, payload, headers):
        return self._request(
            "POST", f"/iacuc/protocols/{protocol_id}/personnel", payload, headers,
        )

    # --- cages / animals / litters ---
    def create_cage(self, payload, headers):
        return self._request("POST", "/iacuc/cages", payload, headers)

    def get_cage(self, cage_id, headers):
        return self._request("GET", f"/iacuc/cages/{cage_id}", headers=headers)

    def list_protocol_cages(self, protocol_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/protocols/{protocol_id}/cages",
            headers=headers, params=params,
        )

    def decommission_cage(self, cage_id, headers):
        return self._request(
            "POST", f"/iacuc/cages/{cage_id}/decommission", headers=headers,
        )

    def get_cage_productivity(self, cage_id, headers):
        return self._request(
            "GET", f"/iacuc/cages/{cage_id}/productivity", headers=headers,
        )

    def create_animal(self, payload, headers):
        return self._request("POST", "/iacuc/animals", payload, headers)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/iacuc/animals/{animal_id}", headers=headers)

    def list_cage_animals(self, cage_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/cages/{cage_id}/animals", headers=headers, params=params,
        )

    def list_protocol_animals(self, protocol_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/protocols/{protocol_id}/animals",
            headers=headers, params=params,
        )

    def transfer_animal(self, animal_id, payload, headers):
        return self._request(
            "POST", f"/iacuc/animals/{animal_id}/transfer", payload, headers,
        )

    def retire_animal(self, animal_id, headers):
        return self._request(
            "POST", f"/iacuc/animals/{animal_id}/retire", headers=headers,
        )

    def transfer_out_animal(self, animal_id, headers):
        return self._request(
            "POST", f"/iacuc/animals/{animal_id}/transfer-out", headers=headers,
        )

    def euthanize_animal(self, animal_id, headers):
        return self._request(
            "POST", f"/iacuc/animals/{animal_id}/euthanize", headers=headers,
        )

    def create_litter(self, payload, headers):
        return self._request("POST", "/iacuc/litters", payload, headers)

    def get_litter(self, litter_id, headers):
        return self._request("GET", f"/iacuc/litters/{litter_id}", headers=headers)

    def list_cage_litters(self, cage_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/cages/{cage_id}/litters", headers=headers, params=params,
        )

    def list_litter_animals(self, litter_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/litters/{litter_id}/animals", headers=headers, params=params,
        )

    def list_protocol_litters(self, protocol_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/protocols/{protocol_id}/litters",
            headers=headers, params=params,
        )

    def wean_litter(self, litter_id, payload, headers):
        return self._request(
            "POST", f"/iacuc/litters/{litter_id}/wean", payload, headers,
        )

    def close_litter(self, litter_id, headers):
        return self._request(
            "POST", f"/iacuc/litters/{litter_id}/close", headers=headers,
        )

    # --- census & billing ---
    def create_census_record(self, payload, headers):
        return self._request("POST", "/iacuc/census-records", payload, headers)

    def list_cage_census_records(self, cage_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/cages/{cage_id}/census-records",
            headers=headers, params=params,
        )

    def create_billing_run(self, payload, headers):
        return self._request("POST", "/iacuc/billing-runs", payload, headers)

    def get_billing_run(self, run_id, headers):
        return self._request("GET", f"/iacuc/billing-runs/{run_id}", headers=headers)

    def list_billing_run_charges(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/billing-runs/{run_id}/charges",
            headers=headers, params=params,
        )

    def list_cage_charges(self, cage_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/cages/{cage_id}/charges", headers=headers, params=params,
        )

    def list_protocol_charges(self, protocol_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/protocols/{protocol_id}/charges",
            headers=headers, params=params,
        )

    def compute_provisional(self, run_id, headers):
        return self._request(
            "POST", f"/iacuc/billing-runs/{run_id}/compute-provisional",
            headers=headers,
        )

    def finalize_billing_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/iacuc/billing-runs/{run_id}/finalize", payload, headers,
        )

    def post_billing_run(self, run_id, headers):
        return self._request(
            "POST", f"/iacuc/billing-runs/{run_id}/post", headers=headers,
        )

    def void_billing_run(self, run_id, headers):
        return self._request(
            "POST", f"/iacuc/billing-runs/{run_id}/void", headers=headers,
        )

    # --- inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/iacuc/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/iacuc/inspections/{inspection_id}", headers=headers,
        )

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/iacuc/inspections/{inspection_id}/complete", payload, headers,
        )

    # --- adverse events / deviations ---
    def create_adverse_event(self, payload, headers):
        return self._request("POST", "/iacuc/adverse-events", payload, headers)

    def list_protocol_adverse_events(self, protocol_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/protocols/{protocol_id}/adverse-events",
            headers=headers, params=params,
        )

    def list_animal_adverse_events(self, animal_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/animals/{animal_id}/adverse-events",
            headers=headers, params=params,
        )

    def list_personnel_adverse_events(self, personnel_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/personnel/{personnel_id}/adverse-events",
            headers=headers, params=params,
        )

    def begin_treatment(self, event_id, headers):
        return self._request(
            "POST", f"/iacuc/adverse-events/{event_id}/begin-treatment",
            headers=headers,
        )

    def escalate_adverse_event(self, event_id, headers):
        return self._request(
            "POST", f"/iacuc/adverse-events/{event_id}/escalate", headers=headers,
        )

    def resolve_adverse_event(self, event_id, headers):
        return self._request(
            "POST", f"/iacuc/adverse-events/{event_id}/resolve", headers=headers,
        )

    def create_protocol_deviation(self, payload, headers):
        return self._request("POST", "/iacuc/protocol-deviations", payload, headers)

    def list_protocol_deviations(self, protocol_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/protocols/{protocol_id}/deviations",
            headers=headers, params=params,
        )

    def list_personnel_protocol_deviations(self, personnel_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/personnel/{personnel_id}/protocol-deviations",
            headers=headers, params=params,
        )

    def begin_deviation_review(self, deviation_id, headers):
        return self._request(
            "POST", f"/iacuc/protocol-deviations/{deviation_id}/begin-review",
            headers=headers,
        )

    def close_deviation(self, deviation_id, headers):
        return self._request(
            "POST", f"/iacuc/protocol-deviations/{deviation_id}/close",
            headers=headers,
        )

    def impose_suspension(self, deviation_id, headers):
        return self._request(
            "POST", f"/iacuc/protocol-deviations/{deviation_id}/impose-suspension",
            headers=headers,
        )

    # --- procedure room bookings ---
    def create_room_booking(self, payload, headers):
        return self._request("POST", "/iacuc/room-bookings", payload, headers)

    def list_protocol_room_bookings(self, protocol_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/protocols/{protocol_id}/room-bookings",
            headers=headers, params=params,
        )

    def list_personnel_room_bookings(self, personnel_id, headers, params=None):
        return self._request(
            "GET", f"/iacuc/personnel/{personnel_id}/room-bookings",
            headers=headers, params=params,
        )

    def cancel_room_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/iacuc/room-bookings/{booking_id}/cancel", headers=headers,
        )


api_client = ApiClient()
