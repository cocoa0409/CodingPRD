"""Composite state builders for the live animal acceptance workflow.

The harness restarts the service before every test, so each fixture builds all
of its preconditions from scratch through the published endpoints.  Nothing is
inserted behind the API's back.

The builders are layered:

* ``workbench`` — one thin call per PRD §3 operation, used by every other layer.
* ``catalog`` — the programme reference data of PRD §3.1 and §3.2: a species
  acceptance profile, a container model, four stations and one mandatory United
  States import document requirement.
* state-progression builders — a booking pushed to a chosen point along the two
  reservation dimensions of PRD §3.4.
* entity-hierarchy builders — reservation, animals, segments, documents,
  allocations wired together.
* full-lifecycle shortcuts — a booking driven all the way to CONFIRMED, to an
  accepted segment, to a departed leg or to an arrived leg.
* accumulation builders — repeated irregular-operations sweeps, staged kennel
  allocations and staged refunds that target a specific threshold.
* finalisation builders — cancelled, interrupted or closed terminal states.

Every builder accepts ``**overrides`` which are merged into the payload of the
resource the builder is named after, so a test can vary one input without
restating the chain.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient, api_client
from .constants import (
    COUNTRY_HONG_KONG,
    COUNTRY_SINGAPORE,
    COUNTRY_UNITED_STATES,
    DOCUMENT_EXPIRES_AT_UTC,
    DOCUMENT_ISSUED_AT_UTC,
    STATION_HKG,
    STATION_JFK,
    STATION_LAX,
    STATION_SIN,
)
from .factories import (
    animal_incident_payload,
    animal_record_payload,
    breed_restriction_payload,
    container_model_payload,
    destination_requirement_payload,
    flight_leg_payload,
    health_document_payload,
    health_document_resubmit_payload,
    irops_care_sweep_payload,
    kennel_allocation_payload,
    reservation_payload,
    segment_assignment_payload,
    species_profile_payload,
    station_payload,
    temperature_embargo_rule_payload,
    welfare_check_payload,
)
from .test_users import (
    ACCEPTANCE_AGENT_ID,
    BOOKING_AGENT_ID,
    COMPLIANCE_OFFICER_ID,
    PROGRAM_ADMIN_ID,
    SECOND_ACCEPTANCE_AGENT_ID,
    VETERINARY_REVIEWER_ID,
    make_acceptance_agent_headers,
    make_compliance_officer_headers,
    make_program_admin_headers,
    make_reservations_agent_headers,
    make_veterinary_reviewer_headers,
)


class Workbench:
    """One method per PRD §3 operation, returning the created ``data`` payload."""

    def __init__(self, client: ApiClient) -> None:
        self.api = client

    # -- headers ---------------------------------------------------------

    @staticmethod
    def admin(user_id: str = PROGRAM_ADMIN_ID) -> Dict[str, str]:
        return make_program_admin_headers(user_id)

    @staticmethod
    def agent(user_id: str = BOOKING_AGENT_ID) -> Dict[str, str]:
        return make_reservations_agent_headers(user_id)

    @staticmethod
    def acceptance(user_id: str = ACCEPTANCE_AGENT_ID) -> Dict[str, str]:
        return make_acceptance_agent_headers(user_id)

    @staticmethod
    def reviewer(user_id: str = VETERINARY_REVIEWER_ID) -> Dict[str, str]:
        return make_veterinary_reviewer_headers(user_id)

    @staticmethod
    def officer(user_id: str = COMPLIANCE_OFFICER_ID) -> Dict[str, str]:
        return make_compliance_officer_headers(user_id)

    # -- programme reference data (PRD §3.1, §3.2) -----------------------

    def create_species(self, *, as_user_id: str = PROGRAM_ADMIN_ID, **overrides: Any):
        return get_success_data(
            self.api.create_species_profile(
                species_profile_payload(**overrides), self.admin(as_user_id)
            )
        )

    def set_species_status(
        self, species_id: str, status: str, *, as_user_id: str = PROGRAM_ADMIN_ID
    ):
        return get_success_data(
            self.api.set_species_profile_status(
                species_id, {"status": status}, self.admin(as_user_id)
            )
        )

    def create_breed_restriction(
        self, species_id: str, *, as_user_id: str = PROGRAM_ADMIN_ID, **overrides: Any
    ):
        return get_success_data(
            self.api.create_breed_restriction(
                breed_restriction_payload(species_id, **overrides),
                self.admin(as_user_id),
            )
        )

    def set_breed_restriction_status(
        self, restriction_id: str, status: str, *, as_user_id: str = PROGRAM_ADMIN_ID
    ):
        return get_success_data(
            self.api.set_breed_restriction_status(
                restriction_id, {"status": status}, self.admin(as_user_id)
            )
        )

    def create_destination_requirement(
        self, species_id: str, *, as_user_id: str = PROGRAM_ADMIN_ID, **overrides: Any
    ):
        return get_success_data(
            self.api.create_destination_requirement(
                destination_requirement_payload(species_id, **overrides),
                self.admin(as_user_id),
            )
        )

    def create_container(self, *, as_user_id: str = PROGRAM_ADMIN_ID, **overrides: Any):
        return get_success_data(
            self.api.create_container_model(
                container_model_payload(**overrides), self.admin(as_user_id)
            )
        )

    def create_station(self, *, as_user_id: str = PROGRAM_ADMIN_ID, **overrides: Any):
        return get_success_data(
            self.api.create_station(
                station_payload(**overrides), self.admin(as_user_id)
            )
        )

    def set_station_status(
        self, station_id: str, status: str, *, as_user_id: str = PROGRAM_ADMIN_ID
    ):
        return get_success_data(
            self.api.set_station_status(
                station_id, {"status": status}, self.admin(as_user_id)
            )
        )

    def create_embargo_rule(
        self, station_id: str, *, as_user_id: str = PROGRAM_ADMIN_ID, **overrides: Any
    ):
        return get_success_data(
            self.api.create_temperature_embargo_rule(
                temperature_embargo_rule_payload(station_id, **overrides),
                self.admin(as_user_id),
            )
        )

    def set_embargo_rule_status(
        self, rule_id: str, status: str, *, as_user_id: str = PROGRAM_ADMIN_ID
    ):
        return get_success_data(
            self.api.set_temperature_embargo_rule_status(
                rule_id, {"status": status}, self.admin(as_user_id)
            )
        )

    # -- flight legs (PRD §3.3) ------------------------------------------

    def create_leg(
        self,
        origin_station_id: str,
        destination_station_id: str,
        *,
        as_user_id: str = PROGRAM_ADMIN_ID,
        **overrides: Any,
    ):
        return get_success_data(
            self.api.create_flight_leg(
                flight_leg_payload(
                    origin_station_id, destination_station_id, **overrides
                ),
                self.admin(as_user_id),
            )
        )

    def update_forecast(
        self,
        leg_id: str,
        forecast_high_c: float,
        forecast_low_c: float,
        *,
        as_user_id: str = PROGRAM_ADMIN_ID,
    ):
        return get_success_data(
            self.api.update_flight_leg_forecast(
                leg_id,
                {"forecast_high_c": forecast_high_c, "forecast_low_c": forecast_low_c},
                self.admin(as_user_id),
            )
        )

    def delay_leg(
        self,
        leg_id: str,
        new_departure_utc: str,
        new_arrival_utc: str,
        *,
        as_user_id: str = PROGRAM_ADMIN_ID,
    ):
        return get_success_data(
            self.api.delay_flight_leg(
                leg_id,
                {
                    "new_departure_utc": new_departure_utc,
                    "new_arrival_utc": new_arrival_utc,
                },
                self.admin(as_user_id),
            )
        )

    def restore_leg(
        self,
        leg_id: str,
        restored_departure_utc: str,
        restored_arrival_utc: str,
        *,
        as_user_id: str = PROGRAM_ADMIN_ID,
    ):
        return get_success_data(
            self.api.restore_flight_leg_schedule(
                leg_id,
                {
                    "restored_departure_utc": restored_departure_utc,
                    "restored_arrival_utc": restored_arrival_utc,
                },
                self.admin(as_user_id),
            )
        )

    def cancel_leg(self, leg_id: str, *, as_user_id: str = PROGRAM_ADMIN_ID):
        return get_success_data(
            self.api.cancel_flight_leg(leg_id, self.admin(as_user_id))
        )

    def depart_leg(self, leg_id: str, *, as_user_id: str = ACCEPTANCE_AGENT_ID):
        return get_success_data(
            self.api.depart_flight_leg(leg_id, self.acceptance(as_user_id))
        )

    def arrive_leg(self, leg_id: str, *, as_user_id: str = ACCEPTANCE_AGENT_ID):
        return get_success_data(
            self.api.arrive_flight_leg(leg_id, self.acceptance(as_user_id))
        )

    # -- reservations and animals (PRD §3.4) -----------------------------

    def create_reservation(self, *, as_user_id: str = BOOKING_AGENT_ID, **overrides: Any):
        return get_success_data(
            self.api.create_reservation(
                reservation_payload(**overrides), self.agent(as_user_id)
            )
        )

    def create_animal(
        self,
        reservation_id: str,
        species_id: str,
        container_id: str,
        *,
        as_user_id: str = BOOKING_AGENT_ID,
        **overrides: Any,
    ):
        return get_success_data(
            self.api.create_animal_record(
                animal_record_payload(
                    reservation_id, species_id, container_id, **overrides
                ),
                self.agent(as_user_id),
            )
        )

    def amend_animal(
        self, animal_id: str, *, as_user_id: str = BOOKING_AGENT_ID, **overrides: Any
    ):
        return get_success_data(
            self.api.update_animal_record(animal_id, dict(overrides), self.agent(as_user_id))
        )

    def screen_animal(self, animal_id: str, *, as_user_id: str = ACCEPTANCE_AGENT_ID):
        return get_success_data(
            self.api.screen_animal_record(animal_id, self.acceptance(as_user_id))
        )

    def mark_travel_ready(self, animal_id: str, *, as_user_id: str = ACCEPTANCE_AGENT_ID):
        return get_success_data(
            self.api.mark_animal_record_travel_ready(
                animal_id, self.acceptance(as_user_id)
            )
        )

    def deny_animal(self, animal_id: str, *, as_user_id: str = ACCEPTANCE_AGENT_ID):
        return get_success_data(
            self.api.deny_animal_record(animal_id, self.acceptance(as_user_id))
        )

    def confirm_reservation(self, reservation_id: str, *, as_user_id: str = BOOKING_AGENT_ID):
        return get_success_data(
            self.api.confirm_reservation(reservation_id, self.agent(as_user_id))
        )

    def cancel_reservation(self, reservation_id: str, *, as_user_id: str = BOOKING_AGENT_ID):
        return get_success_data(
            self.api.cancel_reservation(reservation_id, self.agent(as_user_id))
        )

    def verify_compliance(
        self, reservation_id: str, *, as_user_id: str = VETERINARY_REVIEWER_ID
    ):
        return get_success_data(
            self.api.verify_reservation_compliance(
                reservation_id, self.reviewer(as_user_id)
            )
        )

    # -- segment assignments (PRD §3.5) ----------------------------------

    def leg_version(self, leg_id: str) -> int:
        return self.read_leg(leg_id)["version"]

    def station_version(self, station_id: str) -> int:
        return self.read_station(station_id)["version"]

    def create_segment(
        self,
        animal_id: str,
        leg_id: str,
        *,
        as_user_id: str = BOOKING_AGENT_ID,
        expected_flight_leg_version: Optional[int] = None,
        **overrides: Any,
    ):
        version = (
            self.leg_version(leg_id)
            if expected_flight_leg_version is None
            else expected_flight_leg_version
        )
        return get_success_data(
            self.api.create_segment_assignment(
                segment_assignment_payload(animal_id, leg_id, version, **overrides),
                self.agent(as_user_id),
            )
        )

    def accept_segment(self, segment_id: str, *, as_user_id: str = SECOND_ACCEPTANCE_AGENT_ID):
        return get_success_data(
            self.api.accept_segment_assignment(segment_id, self.acceptance(as_user_id))
        )

    def release_segment(self, segment_id: str, *, as_user_id: str = BOOKING_AGENT_ID):
        return get_success_data(
            self.api.release_segment_assignment(segment_id, self.agent(as_user_id))
        )

    def offload_segment(self, segment_id: str, *, as_user_id: str = ACCEPTANCE_AGENT_ID):
        return get_success_data(
            self.api.offload_segment_assignment(segment_id, self.acceptance(as_user_id))
        )

    # -- health documents (PRD §3.6) -------------------------------------

    def submit_document(
        self, animal_id: str, *, as_user_id: str = BOOKING_AGENT_ID, **overrides: Any
    ):
        return get_success_data(
            self.api.create_health_document(
                health_document_payload(animal_id, **overrides), self.agent(as_user_id)
            )
        )

    def start_document_review(
        self, document_id: str, *, as_user_id: str = VETERINARY_REVIEWER_ID
    ):
        return get_success_data(
            self.api.start_health_document_review(document_id, self.reviewer(as_user_id))
        )

    def verify_document(self, document_id: str, *, as_user_id: str = VETERINARY_REVIEWER_ID):
        return get_success_data(
            self.api.verify_health_document(document_id, self.reviewer(as_user_id))
        )

    def reject_document(
        self,
        document_id: str,
        *,
        as_user_id: str = VETERINARY_REVIEWER_ID,
        payload: Optional[Dict[str, Any]] = None,
    ):
        return get_success_data(
            self.api.reject_health_document(
                document_id, self.reviewer(as_user_id), payload
            )
        )

    def resubmit_document(
        self, document_id: str, *, as_user_id: str = BOOKING_AGENT_ID, **overrides: Any
    ):
        return get_success_data(
            self.api.resubmit_health_document(
                document_id,
                health_document_resubmit_payload(**overrides),
                self.agent(as_user_id),
            )
        )

    def verified_document(
        self,
        animal_id: str,
        *,
        reviewer_id: str = VETERINARY_REVIEWER_ID,
        **overrides: Any,
    ):
        """Submit, take under review and verify a health document in one step."""
        document = self.submit_document(animal_id, **overrides)
        self.start_document_review(document["id"], as_user_id=reviewer_id)
        return self.verify_document(document["id"], as_user_id=reviewer_id)

    # -- kennel allocations and welfare checks (PRD §3.7) ----------------

    def create_kennel_allocation(
        self,
        station_id: str,
        animal_id: str,
        *,
        as_user_id: str = ACCEPTANCE_AGENT_ID,
        expected_station_version: Optional[int] = None,
        **overrides: Any,
    ):
        version = (
            self.station_version(station_id)
            if expected_station_version is None
            else expected_station_version
        )
        return get_success_data(
            self.api.create_kennel_allocation(
                kennel_allocation_payload(station_id, animal_id, version, **overrides),
                self.acceptance(as_user_id),
            )
        )

    def occupy_kennel_allocation(
        self, allocation_id: str, *, as_user_id: str = ACCEPTANCE_AGENT_ID
    ):
        return get_success_data(
            self.api.occupy_kennel_allocation(allocation_id, self.acceptance(as_user_id))
        )

    def release_kennel_allocation(
        self, allocation_id: str, *, as_user_id: str = ACCEPTANCE_AGENT_ID
    ):
        return get_success_data(
            self.api.release_kennel_allocation(
                allocation_id, self.acceptance(as_user_id)
            )
        )

    def append_welfare_check(
        self, segment_id: str, *, as_user_id: str = ACCEPTANCE_AGENT_ID, **overrides: Any
    ):
        return get_success_data(
            self.api.create_welfare_check(
                welfare_check_payload(segment_id, **overrides),
                self.acceptance(as_user_id),
            )
        )

    def append_welfare_checks(
        self, segment_id: str, count: int, *, as_user_id: str = ACCEPTANCE_AGENT_ID
    ) -> List[Dict[str, Any]]:
        return [
            self.append_welfare_check(segment_id, as_user_id=as_user_id)
            for _ in range(count)
        ]

    # -- sweeps and incidents (PRD §3.8, §3.9) ---------------------------

    def sweep_irops(self, leg_id: str, *, as_user_id: str = ACCEPTANCE_AGENT_ID):
        return get_success_data(
            self.api.create_irops_care_sweep(
                irops_care_sweep_payload(leg_id), self.acceptance(as_user_id)
            )
        )

    def report_incident(
        self, animal_id: str, *, as_user_id: str = ACCEPTANCE_AGENT_ID, **overrides: Any
    ):
        return get_success_data(
            self.api.create_animal_incident(
                animal_incident_payload(animal_id, **overrides),
                self.acceptance(as_user_id),
            )
        )

    def investigate_incident(
        self, incident_id: str, *, as_user_id: str = COMPLIANCE_OFFICER_ID
    ):
        return get_success_data(
            self.api.investigate_animal_incident(incident_id, self.officer(as_user_id))
        )

    def disclose_incident(
        self,
        incident_id: str,
        *,
        as_user_id: str = COMPLIANCE_OFFICER_ID,
        **overrides: Any,
    ):
        return get_success_data(
            self.api.disclose_animal_incident(
                incident_id, self.officer(as_user_id), dict(overrides) or None
            )
        )

    def close_incident(
        self,
        incident_id: str,
        veterinary_finding: str,
        *,
        as_user_id: str = COMPLIANCE_OFFICER_ID,
    ):
        return get_success_data(
            self.api.close_animal_incident(
                incident_id,
                {"veterinary_finding": veterinary_finding},
                self.officer(as_user_id),
            )
        )

    # -- logical clock (PRD §2.7) ----------------------------------------

    def set_clock(self, to_iso8601: str, *, as_user_id: str = PROGRAM_ADMIN_ID):
        return get_success_data(
            self.api.set_clock({"to_iso8601": to_iso8601}, self.admin(as_user_id))
        )

    def read_clock(self, *, as_user_id: str = PROGRAM_ADMIN_ID):
        return get_success_data(self.api.get_clock(self.admin(as_user_id)))

    # -- reads -----------------------------------------------------------

    def read_species(self, species_id: str):
        return get_success_data(self.api.get_species_profile(species_id, self.admin()))

    def read_breed_restriction(self, restriction_id: str):
        return get_success_data(
            self.api.get_breed_restriction(restriction_id, self.admin())
        )

    def read_station(self, station_id: str):
        return get_success_data(self.api.get_station(station_id, self.admin()))

    def read_leg(self, leg_id: str):
        return get_success_data(self.api.get_flight_leg(leg_id, self.admin()))

    def read_reservation(self, reservation_id: str):
        return get_success_data(self.api.get_reservation(reservation_id, self.admin()))

    def read_animal(self, animal_id: str):
        return get_success_data(self.api.get_animal_record(animal_id, self.admin()))

    def read_segment(self, segment_id: str):
        return get_success_data(
            self.api.get_segment_assignment(segment_id, self.admin())
        )

    def read_document(self, document_id: str):
        return get_success_data(self.api.get_health_document(document_id, self.admin()))

    def read_allocation(self, allocation_id: str):
        return get_success_data(
            self.api.get_kennel_allocation(allocation_id, self.admin())
        )

    def read_incident(self, incident_id: str):
        return get_success_data(self.api.get_animal_incident(incident_id, self.admin()))

    def read_charge_summary(self, reservation_id: str):
        return get_success_data(
            self.api.get_reservation_charge_summary(reservation_id, self.admin())
        )


# ---------------------------------------------------------------------------
# Tier 0 — the workbench and the programme catalogue
# ---------------------------------------------------------------------------


@pytest.fixture
def workbench(api: ApiClient) -> Workbench:
    return Workbench(api)


@pytest.fixture
def catalog(workbench: Workbench) -> Dict[str, Any]:
    """Programme reference data: species, container, four stations, one
    mandatory United States health-certificate requirement."""
    species = workbench.create_species()
    container = workbench.create_container()
    hkg = workbench.create_station(
        iata_code=STATION_HKG, country_code=COUNTRY_HONG_KONG, kennel_bay_count=4
    )
    lax = workbench.create_station(
        iata_code=STATION_LAX, country_code=COUNTRY_UNITED_STATES, kennel_bay_count=6
    )
    jfk = workbench.create_station(
        iata_code=STATION_JFK, country_code=COUNTRY_UNITED_STATES, kennel_bay_count=6
    )
    sin = workbench.create_station(
        iata_code=STATION_SIN, country_code=COUNTRY_SINGAPORE, kennel_bay_count=6
    )
    requirement = workbench.create_destination_requirement(species["id"])
    return {
        "species": species,
        "species_id": species["id"],
        "container": container,
        "container_id": container["id"],
        "hkg": hkg,
        "hkg_id": hkg["id"],
        "lax": lax,
        "lax_id": lax["id"],
        "jfk": jfk,
        "jfk_id": jfk["id"],
        "sin": sin,
        "sin_id": sin["id"],
        "requirement": requirement,
        "requirement_id": requirement["id"],
    }


@pytest.fixture
def primary_leg(workbench: Workbench, catalog: Dict[str, Any]):
    """AN101 HKG to LAX, thirteen block hours, forecast well inside every
    embargo limit."""

    def _build(**overrides: Any) -> Dict[str, Any]:
        return workbench.create_leg(catalog["hkg_id"], catalog["lax_id"], **overrides)

    return _build


@pytest.fixture
def connecting_leg(workbench: Workbench, catalog: Dict[str, Any]):
    """A LAX to JFK continuation whose schedule the caller chooses."""

    def _build(
        *,
        flight_number: str = "AN205",
        scheduled_departure_utc: str = "2026-09-10T17:00:00Z",
        scheduled_arrival_utc: str = "2026-09-10T22:00:00Z",
        **overrides: Any,
    ) -> Dict[str, Any]:
        return workbench.create_leg(
            catalog["lax_id"],
            catalog["jfk_id"],
            flight_number=flight_number,
            scheduled_departure_utc=scheduled_departure_utc,
            scheduled_arrival_utc=scheduled_arrival_utc,
            **overrides,
        )

    return _build


# ---------------------------------------------------------------------------
# Tier 1 — entity hierarchy: reservation, animal, one reserved routing slot
# ---------------------------------------------------------------------------


@pytest.fixture
def booking_with_reserved_segment(
    workbench: Workbench, catalog: Dict[str, Any], primary_leg
):
    """A CHECKED reservation holding one DRAFT animal with one RESERVED slot at
    sequence index 1 on AN101."""

    def _build(
        *,
        reservation_overrides: Optional[Dict[str, Any]] = None,
        animal_overrides: Optional[Dict[str, Any]] = None,
        leg_overrides: Optional[Dict[str, Any]] = None,
        segment_overrides: Optional[Dict[str, Any]] = None,
        booked_by: str = BOOKING_AGENT_ID,
        **overrides: Any,
    ) -> Dict[str, Any]:
        leg = primary_leg(**(leg_overrides or {}))
        reservation = workbench.create_reservation(
            as_user_id=booked_by, **(reservation_overrides or {}), **overrides
        )
        animal = workbench.create_animal(
            reservation["id"],
            catalog["species_id"],
            catalog["container_id"],
            as_user_id=booked_by,
            **(animal_overrides or {}),
        )
        segment = workbench.create_segment(
            animal["id"],
            leg["id"],
            as_user_id=booked_by,
            **(segment_overrides or {}),
        )
        return {
            "catalog": catalog,
            "leg": leg,
            "leg_id": leg["id"],
            "reservation": reservation,
            "reservation_id": reservation["id"],
            "animal": animal,
            "animal_id": animal["id"],
            "segment": segment,
            "segment_id": segment["id"],
            "booked_by": booked_by,
        }

    return _build


# ---------------------------------------------------------------------------
# Tier 2 — state progression along the two reservation dimensions
# ---------------------------------------------------------------------------


@pytest.fixture
def screened_booking(workbench: Workbench, booking_with_reserved_segment):
    """The animal has passed screening, so its container has been evaluated and
    its reserved slot carries a provisional fee."""

    def _build(**overrides: Any) -> Dict[str, Any]:
        state = booking_with_reserved_segment(**overrides)
        state["animal"] = workbench.screen_animal(state["animal_id"])
        state["segment"] = workbench.read_segment(state["segment_id"])
        return state

    return _build


@pytest.fixture
def compliance_verified_booking(workbench: Workbench, screened_booking):
    """Screening done, one VERIFIED health certificate on file and the
    compliance sweep run, so ``compliance_status`` is VERIFIED."""

    def _build(
        *, document_overrides: Optional[Dict[str, Any]] = None, **overrides: Any
    ) -> Dict[str, Any]:
        state = screened_booking(**overrides)
        state["document"] = workbench.verified_document(
            state["animal_id"], **(document_overrides or {})
        )
        state["document_id"] = state["document"]["id"]
        state["reservation"] = workbench.verify_compliance(state["reservation_id"])
        return state

    return _build


@pytest.fixture
def travel_ready_booking(workbench: Workbench, compliance_verified_booking):
    """Every gate of PRD §3.4 has passed: the animal is TRAVEL_READY while the
    booking dimension is still PENDING."""

    def _build(**overrides: Any) -> Dict[str, Any]:
        state = compliance_verified_booking(**overrides)
        state["animal"] = workbench.mark_travel_ready(state["animal_id"])
        return state

    return _build


@pytest.fixture
def confirmed_booking(workbench: Workbench, travel_ready_booking):
    """A CONFIRMED, compliance-VERIFIED booking with one RESERVED slot priced at
    the provisional variant."""

    def _build(**overrides: Any) -> Dict[str, Any]:
        state = travel_ready_booking(**overrides)
        state["reservation"] = workbench.confirm_reservation(state["reservation_id"])
        state["leg"] = workbench.read_leg(state["leg_id"])
        state["segment"] = workbench.read_segment(state["segment_id"])
        return state

    return _build


# ---------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts
# ---------------------------------------------------------------------------


@pytest.fixture
def accepted_booking(workbench: Workbench, confirmed_booking):
    """A CONFIRMED booking whose single slot has been accepted at the counter
    with a measured weight, so the slot carries the final fee variant."""

    def _build(
        *,
        measured_weight_kg: float = 27,
        accepted_by: str = SECOND_ACCEPTANCE_AGENT_ID,
        **overrides: Any,
    ) -> Dict[str, Any]:
        state = confirmed_booking(**overrides)
        state["animal"] = workbench.amend_animal(
            state["animal_id"], measured_weight_kg=measured_weight_kg
        )
        state["segment"] = workbench.accept_segment(
            state["segment_id"], as_user_id=accepted_by
        )
        state["reservation"] = workbench.read_reservation(state["reservation_id"])
        state["accepted_by"] = accepted_by
        return state

    return _build


@pytest.fixture
def departed_booking(workbench: Workbench, accepted_booking):
    """The leg has departed, so the animal is IN_TRANSIT and the booking is
    IN_TRANSIT with the leg posture CLOSED."""

    def _build(*, departed_by: str = SECOND_ACCEPTANCE_AGENT_ID, **overrides: Any):
        state = accepted_booking(**overrides)
        state["leg"] = workbench.depart_leg(state["leg_id"], as_user_id=departed_by)
        state["animal"] = workbench.read_animal(state["animal_id"])
        state["reservation"] = workbench.read_reservation(state["reservation_id"])
        return state

    return _build


@pytest.fixture
def arrived_booking(workbench: Workbench, departed_booking):
    """The leg has arrived: the slot is COMPLETED, the animal DELIVERED and the
    booking COMPLETED."""

    def _build(*, arrived_by: str = SECOND_ACCEPTANCE_AGENT_ID, **overrides: Any):
        state = departed_booking(**overrides)
        state["leg"] = workbench.arrive_leg(state["leg_id"], as_user_id=arrived_by)
        state["segment"] = workbench.read_segment(state["segment_id"])
        state["animal"] = workbench.read_animal(state["animal_id"])
        state["reservation"] = workbench.read_reservation(state["reservation_id"])
        return state

    return _build


@pytest.fixture
def two_leg_confirmed_booking(
    workbench: Workbench, catalog: Dict[str, Any], primary_leg, connecting_leg
):
    """A CONFIRMED CHECKED booking whose single animal holds two RESERVED slots:
    sequence index 1 on AN101 out of HKG and sequence index 2 on a LAX to JFK
    continuation whose schedule the caller chooses."""

    def _build(
        *,
        second_leg_departure_utc: str = "2026-09-10T17:00:00Z",
        second_leg_arrival_utc: str = "2026-09-10T22:00:00Z",
        second_leg_overrides: Optional[Dict[str, Any]] = None,
        animal_overrides: Optional[Dict[str, Any]] = None,
        reservation_overrides: Optional[Dict[str, Any]] = None,
        leg_overrides: Optional[Dict[str, Any]] = None,
        booked_by: str = BOOKING_AGENT_ID,
        confirm: bool = True,
        **overrides: Any,
    ) -> Dict[str, Any]:
        leg1 = primary_leg(**(leg_overrides or {}))
        leg2 = connecting_leg(
            scheduled_departure_utc=second_leg_departure_utc,
            scheduled_arrival_utc=second_leg_arrival_utc,
            **(second_leg_overrides or {}),
        )
        reservation = workbench.create_reservation(
            as_user_id=booked_by, **(reservation_overrides or {}), **overrides
        )
        animal = workbench.create_animal(
            reservation["id"],
            catalog["species_id"],
            catalog["container_id"],
            as_user_id=booked_by,
            **(animal_overrides or {}),
        )
        segment1 = workbench.create_segment(
            animal["id"], leg1["id"], as_user_id=booked_by, sequence_index=1
        )
        segment2 = workbench.create_segment(
            animal["id"], leg2["id"], as_user_id=booked_by, sequence_index=2
        )
        animal = workbench.screen_animal(animal["id"])
        document = workbench.verified_document(animal["id"])
        reservation = workbench.verify_compliance(reservation["id"])
        animal = workbench.mark_travel_ready(animal["id"])
        if confirm:
            reservation = workbench.confirm_reservation(
                reservation["id"], as_user_id=booked_by
            )
        return {
            "catalog": catalog,
            "leg1": workbench.read_leg(leg1["id"]),
            "leg1_id": leg1["id"],
            "leg2": workbench.read_leg(leg2["id"]),
            "leg2_id": leg2["id"],
            "reservation": reservation,
            "reservation_id": reservation["id"],
            "animal": animal,
            "animal_id": animal["id"],
            "segment1": workbench.read_segment(segment1["id"]),
            "segment1_id": segment1["id"],
            "segment2": workbench.read_segment(segment2["id"]),
            "segment2_id": segment2["id"],
            "document": document,
            "document_id": document["id"],
            "booked_by": booked_by,
        }

    return _build


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ---------------------------------------------------------------------------


@pytest.fixture
def swept_booking(workbench: Workbench):
    """Charge irregular-operations care a chosen number of times so a test can
    aim the subtotal at a loyalty tier boundary."""

    def _build(leg_ids: List[str], *, times: int = 1, **overrides: Any):
        sweeps = []
        for _ in range(times):
            for leg_id in leg_ids:
                sweeps.append(workbench.sweep_irops(leg_id, **overrides))
        return sweeps

    return _build


@pytest.fixture
def staged_kennel_allocations(workbench: Workbench, screened_booking):
    """Two animals of one booking holding bays at HKG across overlapping
    occupancy windows, so a third request meets the projected peak."""

    def _build(
        *,
        first_bay_count: int = 2,
        first_window: tuple = ("2026-08-05T06:00:00Z", "2026-08-05T09:00:00Z"),
        second_bay_count: int = 2,
        second_window: tuple = ("2026-08-05T09:44:00Z", "2026-08-05T12:00:00Z"),
        **overrides: Any,
    ) -> Dict[str, Any]:
        state = screened_booking(**overrides)
        catalog_data = state["catalog"]
        second_animal = workbench.create_animal(
            state["reservation_id"],
            catalog_data["species_id"],
            catalog_data["container_id"],
            animal_name="Taro",
            breed_name="Beagle",
            declared_weight_kg=12,
            height_at_shoulder_cm=30,
            length_nose_to_tail_cm=45,
            age_weeks=40,
        )
        workbench.screen_animal(second_animal["id"])
        first = workbench.create_kennel_allocation(
            catalog_data["hkg_id"],
            state["animal_id"],
            bay_count=first_bay_count,
            occupancy_start_utc=first_window[0],
            occupancy_end_utc=first_window[1],
        )
        second = workbench.create_kennel_allocation(
            catalog_data["hkg_id"],
            second_animal["id"],
            bay_count=second_bay_count,
            occupancy_start_utc=second_window[0],
            occupancy_end_utc=second_window[1],
        )
        state["second_animal"] = second_animal
        state["second_animal_id"] = second_animal["id"]
        state["allocation_one"] = first
        state["allocation_one_id"] = first["id"]
        state["allocation_two"] = second
        state["allocation_two_id"] = second["id"]
        state["station"] = workbench.read_station(catalog_data["hkg_id"])
        return state

    return _build


# ---------------------------------------------------------------------------
# Tier 5 — finalisation and terminal states
# ---------------------------------------------------------------------------


@pytest.fixture
def cancelled_booking(workbench: Workbench, confirmed_booking):
    """A booking driven to CANCELLED, refunding half of its subtotal."""

    def _build(**overrides: Any) -> Dict[str, Any]:
        state = confirmed_booking(**overrides)
        state["reservation"] = workbench.cancel_reservation(state["reservation_id"])
        state["segment"] = workbench.read_segment(state["segment_id"])
        state["leg"] = workbench.read_leg(state["leg_id"])
        return state

    return _build


@pytest.fixture
def reported_incident(workbench: Workbench, screened_booking):
    """A REPORTED incident against a screened animal, with no segment cited so
    that neither the in-transit adder nor the welfare component applies."""

    def _build(
        *, reported_by: str = ACCEPTANCE_AGENT_ID, **overrides: Any
    ) -> Dict[str, Any]:
        incident_overrides = overrides.pop("incident_overrides", {}) or {}
        state = screened_booking(**overrides)
        incident = workbench.report_incident(
            state["animal_id"], as_user_id=reported_by, **incident_overrides
        )
        state["incident"] = incident
        state["incident_id"] = incident["id"]
        state["reported_by"] = reported_by
        return state

    return _build


@pytest.fixture
def investigated_incident(workbench: Workbench, reported_incident):
    """An incident moved to INVESTIGATING by an officer other than its
    reporter."""

    def _build(
        *, investigated_by: str = COMPLIANCE_OFFICER_ID, **overrides: Any
    ) -> Dict[str, Any]:
        state = reported_incident(**overrides)
        state["incident"] = workbench.investigate_incident(
            state["incident_id"], as_user_id=investigated_by
        )
        state["investigated_by"] = investigated_by
        return state

    return _build


DEFAULT_DOCUMENT_ISSUED_AT = DOCUMENT_ISSUED_AT_UTC
DEFAULT_DOCUMENT_EXPIRES_AT = DOCUMENT_EXPIRES_AT_UTC


__all__ = [
    "Workbench",
    "workbench",
    "catalog",
    "primary_leg",
    "connecting_leg",
    "booking_with_reserved_segment",
    "screened_booking",
    "compliance_verified_booking",
    "travel_ready_booking",
    "confirmed_booking",
    "accepted_booking",
    "departed_booking",
    "arrived_booking",
    "two_leg_confirmed_booking",
    "swept_booking",
    "staged_kennel_allocations",
    "cancelled_booking",
    "reported_incident",
    "investigated_incident",
    "DEFAULT_DOCUMENT_ISSUED_AT",
    "DEFAULT_DOCUMENT_EXPIRES_AT",
]
