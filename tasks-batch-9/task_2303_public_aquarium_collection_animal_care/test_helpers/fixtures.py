"""Pytest fixtures and world builders.

Each test starts against an empty database and a logical clock parked at
2026-08-01T00:00:00Z, so every piece of state a test needs must be created here
through the published endpoints. `Builder` walks those endpoints in the order the
PRD requires and hands back the created resources.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient, api_client
from .constants import CLOCK_EPOCH, HABITAT_TARGETS
from .test_users import (
    AQUARIST_HEADERS,
    CLEARANCE_OFFICER_ID,
    CURATOR_HEADERS,
    DIRECTOR_HEADERS,
    PERMIT_OFFICER_HEADERS,
    PLAN_APPROVER_ID,
    VET_HEADERS,
    make_director_headers,
    make_liaison_headers,
)


# --------------------------------------------------------------------------
# Instant arithmetic
# --------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds.

    PRD §2.4 renders `created_at` (and every other server-minted instant) with
    three fractional digits, so instants read back from the API must parse here
    just as readily as the whole-second literals the builders send.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def format_instant(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift(instant: str, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0) -> str:
    return format_instant(
        parse_instant(instant) + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    )


def reading_for(habitat: str, severity: str, taken_at: str) -> Dict[str, Any]:
    """A reading whose largest deviation ratio is exactly 0.0, 1.0 or 2.0.

    The deviation is carried entirely by `temperature_c`, so the reading scores
    `NORMAL`, `WARNING` or `CRITICAL` with every other parameter on target.
    """
    targets = HABITAT_TARGETS[habitat]
    multiple = {"NORMAL": 0.0, "WARNING": 1.0, "CRITICAL": 2.0}[severity]
    return {
        "taken_at": taken_at,
        "temperature_c": targets["temperature_target"] + multiple * targets["temperature_band"],
        "salinity_ppt": targets["salinity_target"],
        "ph": targets["ph_target"],
        "dissolved_oxygen_mg_l": targets["oxygen_warn"],
        "ammonia_mg_l": 0.0,
        "nitrite_mg_l": 0.0,
    }


class Builder:
    """Walks the documented endpoints to assemble the state a test needs."""

    def __init__(self, api: Optional[ApiClient] = None):
        self.api = api or api_client
        self.now = CLOCK_EPOCH

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------
    def set_clock(self, instant: str) -> Dict[str, Any]:
        response = self.api.set_clock(f.clock_payload(instant), DIRECTOR_HEADERS)
        data = get_success_data(response)
        self.now = instant
        return data

    def advance(self, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0) -> Dict[str, Any]:
        return self.set_clock(shift(self.now, days=days, hours=hours, minutes=minutes, seconds=seconds))

    def advance_to(self, instant: str) -> Dict[str, Any]:
        return self.set_clock(instant)

    # ------------------------------------------------------------------
    # Life support estate
    # ------------------------------------------------------------------
    def create_plant(self, **overrides: Any) -> Dict[str, Any]:
        payload = f.life_support_system_payload(**overrides)
        return get_success_data(self.api.create_life_support_system(payload, DIRECTOR_HEADERS), 201)

    def append_reading(self, plant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_water_quality_reading(plant_id, payload, AQUARIST_HEADERS), 201
        )

    def append_graded_reading(self, plant: Dict[str, Any], severity: str, taken_at: Optional[str] = None) -> Dict[str, Any]:
        payload = reading_for(plant["design_habitat"], severity, taken_at or self.now)
        return self.append_reading(plant["id"], payload)

    def record_redundancy_test(self, plant_id: str, result: str, performed_at: Optional[str] = None) -> Dict[str, Any]:
        payload = f.redundancy_test_payload(performed_at or self.now, result)
        return get_success_data(self.api.create_redundancy_test(plant_id, payload, AQUARIST_HEADERS), 201)

    def get_plant(self, plant_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_life_support_system(plant_id, DIRECTOR_HEADERS))

    # ------------------------------------------------------------------
    # Exhibits
    # ------------------------------------------------------------------
    def create_exhibit(self, plant: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
        overrides.setdefault("habitat_type", plant["design_habitat"])
        payload = f.exhibit_payload(plant["id"], **overrides)
        return get_success_data(self.api.create_exhibit(payload, CURATOR_HEADERS), 201)

    def get_exhibit(self, exhibit_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_exhibit(exhibit_id, CURATOR_HEADERS))

    def exhibit_version(self, exhibit_id: str) -> int:
        return self.get_exhibit(exhibit_id)["version"]

    # ------------------------------------------------------------------
    # Species and institutions
    # ------------------------------------------------------------------
    def create_species(self, **overrides: Any) -> Dict[str, Any]:
        payload = f.species_payload(**overrides)
        return get_success_data(self.api.create_species(payload, CURATOR_HEADERS), 201)

    def get_species(self, species_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_species(species_id, CURATOR_HEADERS))

    def species_version(self, species_id: str) -> int:
        return self.get_species(species_id)["version"]

    def create_institution(self, **overrides: Any) -> Dict[str, Any]:
        payload = f.institution_payload(**overrides)
        return get_success_data(self.api.create_institution(payload, DIRECTOR_HEADERS), 201)

    # ------------------------------------------------------------------
    # Collection plan
    # ------------------------------------------------------------------
    def create_plan_entry(self, exhibit: Dict[str, Any], species: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
        version = overrides.pop("expected_exhibit_version", None)
        if version is None:
            version = self.exhibit_version(exhibit["id"])
        payload = f.collection_plan_entry_payload(exhibit["id"], species["id"], version, **overrides)
        return get_success_data(self.api.create_collection_plan_entry(payload, CURATOR_HEADERS), 201)

    def plan_action(self, entry_id: str, action: str, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
        payload = f.plan_status_action_payload(action, **overrides)
        return get_success_data(
            self.api.plan_entry_status_action(entry_id, payload, headers or make_director_headers(PLAN_APPROVER_ID))
        )

    def create_approved_plan_entry(self, exhibit: Dict[str, Any], species: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
        entry = self.create_plan_entry(exhibit, species, **overrides)
        return self.plan_action(entry["id"], "APPROVE")

    # ------------------------------------------------------------------
    # Acquisition requests
    # ------------------------------------------------------------------
    def create_acquisition(self, entry: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
        payload = f.acquisition_request_payload(entry["id"], **overrides)
        return get_success_data(self.api.create_acquisition_request(payload, CURATOR_HEADERS), 201)

    def submit_acquisition(self, request_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.submit_acquisition_request(request_id, dict(overrides), CURATOR_HEADERS)
        )

    def clear_acquisition(
        self,
        request_id: str,
        species_id: str,
        user_id: str = CLEARANCE_OFFICER_ID,
        **overrides: Any,
    ) -> Dict[str, Any]:
        payload = f.clearance_payload(self.species_version(species_id), **overrides)
        return get_success_data(
            self.api.clear_acquisition_request(request_id, payload, make_director_headers(user_id))
        )

    def cancel_acquisition(self, request_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.cancel_acquisition_request(request_id, dict(overrides), CURATOR_HEADERS)
        )

    def get_acquisition(self, request_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_acquisition_request(request_id, CURATOR_HEADERS))

    # ------------------------------------------------------------------
    # Permits
    # ------------------------------------------------------------------
    def draft_permit(self, request_id: str, permit_type: str, document_codes: List[str], **overrides: Any) -> Dict[str, Any]:
        payload = f.permit_payload(request_id, permit_type, document_codes, **overrides)
        return get_success_data(self.api.create_permit(payload, PERMIT_OFFICER_HEADERS), 201)

    def submit_permit(self, permit_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(self.api.submit_permit(permit_id, dict(overrides), PERMIT_OFFICER_HEADERS))

    def decide_permit(self, permit_id: str, decision: str, **overrides: Any) -> Dict[str, Any]:
        payload = f.permit_decision_payload(decision, **overrides)
        return get_success_data(self.api.decide_permit(permit_id, payload, DIRECTOR_HEADERS))

    def issue_permit(
        self,
        request_id: str,
        permit_type: str,
        document_codes: List[str],
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Draft, submit and issue one permit against an acquisition request."""
        permit = self.draft_permit(request_id, permit_type, document_codes)
        self.submit_permit(permit["id"])
        return self.decide_permit(
            permit["id"],
            "ISSUE",
            valid_from=valid_from or self.now,
            valid_until=valid_until or shift(self.now, days=365),
        )

    def get_permit(self, permit_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_permit(permit_id, PERMIT_OFFICER_HEADERS))

    # ------------------------------------------------------------------
    # Specimens
    # ------------------------------------------------------------------
    def accession_specimen(self, species: Dict[str, Any], request: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
        overrides.setdefault("arrival_at", self.now)
        payload = f.specimen_payload(species["id"], request["id"], **overrides)
        return get_success_data(self.api.create_specimen(payload, CURATOR_HEADERS), 201)

    def get_specimen(self, specimen_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_specimen(specimen_id, CURATOR_HEADERS))

    def quarantine_case_of(self, specimen_id: str) -> Dict[str, Any]:
        cases = get_success_data(self.api.list_specimen_quarantine_cases(specimen_id, CURATOR_HEADERS))
        assert cases, f"specimen {specimen_id} has no quarantine case"
        return cases[0]

    def get_quarantine_case(self, case_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_quarantine_case(case_id, VET_HEADERS))

    def review_quarantine(self, case_id: str, outcome: str, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
        payload = f.quarantine_review_payload(outcome, **overrides)
        return get_success_data(self.api.create_quarantine_review(case_id, payload, headers or VET_HEADERS))

    def open_vet_case(self, specimen_id: str, case_type: str, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
        overrides.setdefault("opened_at", self.now)
        payload = f.veterinary_case_payload(specimen_id, case_type, overrides.pop("opened_at"), **overrides)
        return get_success_data(self.api.create_veterinary_case(payload, headers or VET_HEADERS), 201)

    def close_vet_case(
        self,
        case_id: str,
        outcome: str,
        findings_severity: str,
        headers: Optional[Dict[str, str]] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        payload = f.case_closure_payload(outcome, findings_severity, **overrides)
        return get_success_data(self.api.close_veterinary_case(case_id, payload, headers or VET_HEADERS))

    def record_clean_exams(self, specimen_id: str, count: int = 2, opened_at: Optional[str] = None) -> List[Dict[str, Any]]:
        """Open `count` preventive exams, then close each with a clean finding.

        A clean exam only counts towards quarantine clearance once its
        `opened_at` lies strictly before the logical clock, so callers advance
        the clock between opening and closing.
        """
        cases = [self.open_vet_case(specimen_id, "PREVENTIVE_EXAM", opened_at=opened_at or self.now) for _ in range(count)]
        return cases

    def close_clean_exams(self, cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self.close_vet_case(case["id"], "RESOLVED", "NONE") for case in cases]

    def place(self, specimen_id: str, exhibit_id: str, **overrides: Any) -> Dict[str, Any]:
        version = overrides.pop("expected_exhibit_version", None)
        if version is None:
            version = self.exhibit_version(exhibit_id)
        payload = f.placement_payload(exhibit_id, version, **overrides)
        return get_success_data(self.api.place_specimen(specimen_id, payload, AQUARIST_HEADERS))

    def remove(self, specimen_id: str, exhibit_id: str, **overrides: Any) -> Dict[str, Any]:
        version = overrides.pop("expected_exhibit_version", None)
        if version is None:
            version = self.exhibit_version(exhibit_id)
        payload = f.removal_payload(version, **overrides)
        return get_success_data(self.api.remove_specimen(specimen_id, payload, AQUARIST_HEADERS))

    def declare_mortality(self, specimen_id: str, occurred_at: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
        payload = f.mortality_payload(occurred_at or self.now, **overrides)
        return get_success_data(self.api.declare_mortality(specimen_id, payload, VET_HEADERS))

    def log_feeding(self, specimen_id: str, appetite_score: int = 5, logged_at: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
        payload = f.husbandry_log_payload("FEEDING", logged_at or self.now, appetite_score=appetite_score, **overrides)
        return get_success_data(self.api.create_husbandry_log(specimen_id, payload, AQUARIST_HEADERS), 201)

    def log_behavior(self, specimen_id: str, behavior_code: str = "NORMAL", logged_at: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
        payload = f.husbandry_log_payload("BEHAVIOR", logged_at or self.now, behavior_code=behavior_code, **overrides)
        return get_success_data(self.api.create_husbandry_log(specimen_id, payload, AQUARIST_HEADERS), 201)

    # ------------------------------------------------------------------
    # Composite worlds
    # ------------------------------------------------------------------
    def approved_line(
        self,
        habitat: str = "COLD_MARINE",
        plant_overrides: Optional[Dict[str, Any]] = None,
        exhibit_overrides: Optional[Dict[str, Any]] = None,
        species_overrides: Optional[Dict[str, Any]] = None,
        entry_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Plant + exhibit + species + an APPROVED plan line for the pair."""
        plant = self.create_plant(design_habitat=habitat, **(plant_overrides or {}))
        exhibit = self.create_exhibit(plant, **(exhibit_overrides or {}))
        species = self.create_species(**(species_overrides or {}))
        entry = self.create_approved_plan_entry(exhibit, species, **(entry_overrides or {}))
        return {"plant": plant, "exhibit": exhibit, "species": species, "entry": entry}

    def cleared_acquisition(
        self,
        world: Optional[Dict[str, Any]] = None,
        source_type: str = "CAPTIVE_BRED",
        requested_count: int = 1,
        acquisition_overrides: Optional[Dict[str, Any]] = None,
        **world_kwargs: Any,
    ) -> Dict[str, Any]:
        """An approved line carrying a CLEARED acquisition request."""
        world = dict(world or self.approved_line(**world_kwargs))
        request = self.create_acquisition(
            world["entry"],
            source_type=source_type,
            requested_count=requested_count,
            **(acquisition_overrides or {}),
        )
        request = self.submit_acquisition(request["id"])
        if request["status"] == "PENDING_PERMIT":
            permit_type = "IMPORT" if source_type == "WILD_COLLECTION" else "POSSESSION"
            documents = (
                ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"]
                if permit_type == "IMPORT"
                else ["HEALTH_CERTIFICATE", "POSSESSION_AFFIDAVIT"]
            )
            world["permit"] = self.issue_permit(request["id"], permit_type, documents)
        request = self.clear_acquisition(request["id"], world["species"]["id"])
        world["request"] = request
        return world

    def quarantined_specimen(self, world: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """A specimen freshly accessioned, so QUARANTINE with an ACTIVE case."""
        world = dict(world or self.cleared_acquisition(**kwargs))
        specimen = self.accession_specimen(world["species"], world["request"])
        world["specimen"] = specimen
        world["quarantine_case"] = self.quarantine_case_of(specimen["id"])
        return world

    def cleared_specimen(self, world: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """A specimen through quarantine: disposition CLEARED, health HEALTHY."""
        world = dict(world or self.quarantined_specimen(**kwargs))
        specimen = world["specimen"]
        case = world["quarantine_case"]
        exams = self.record_clean_exams(specimen["id"], 2)
        self.advance_to(case["projected_release_at"])
        self.close_clean_exams(exams)
        world["quarantine_case"] = self.review_quarantine(case["id"], "CLEAR")
        world["specimen"] = self.get_specimen(specimen["id"])
        return world

    def specimen_on_exhibit(self, world: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """A cleared specimen placed on its exhibit."""
        world = dict(world or self.cleared_specimen(**kwargs))
        world["specimen"] = self.place(world["specimen"]["id"], world["exhibit"]["id"])
        world["exhibit"] = self.get_exhibit(world["exhibit"]["id"])
        return world

    # ------------------------------------------------------------------
    # Sessions and audits
    # ------------------------------------------------------------------
    def book_session(self, exhibit_id: str, starts_at: str, ends_at: str, **overrides: Any) -> Dict[str, Any]:
        payload = f.interaction_session_payload(exhibit_id, starts_at, ends_at, **overrides)
        return get_success_data(self.api.create_interaction_session(payload, AQUARIST_HEADERS), 201)

    def transition_session(self, session_id: str, action: str, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
        payload = f.session_transition_payload(action, **overrides)
        return get_success_data(
            self.api.transition_interaction_session(session_id, payload, headers or AQUARIST_HEADERS)
        )

    def get_session(self, session_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_interaction_session(session_id, AQUARIST_HEADERS))

    def schedule_audit(self, scheduled_for: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
        payload = f.accreditation_audit_payload(scheduled_for or self.now, **overrides)
        return get_success_data(self.api.create_accreditation_audit(payload, DIRECTOR_HEADERS), 201)

    def progress_audit(self, audit_id: str, action: str, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
        payload = f.audit_progression_payload(action, **overrides)
        return get_success_data(
            self.api.progress_accreditation_audit(audit_id, payload, headers or DIRECTOR_HEADERS)
        )

    # ------------------------------------------------------------------
    # Transfers
    # ------------------------------------------------------------------
    def draft_transfer(self, specimen_id: str, institution_id: str, proposed_transfer_at: str, **overrides: Any) -> Dict[str, Any]:
        payload = f.transfer_request_payload(specimen_id, institution_id, proposed_transfer_at, **overrides)
        return get_success_data(self.api.create_transfer_request(payload, PERMIT_OFFICER_HEADERS), 201)

    def submit_transfer(self, transfer_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.submit_transfer_request(transfer_id, dict(overrides), PERMIT_OFFICER_HEADERS)
        )

    def decide_transfer(self, transfer_id: str, decision: str, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
        payload = f.transfer_decision_payload(decision, **overrides)
        return get_success_data(
            self.api.decide_transfer_request(transfer_id, payload, headers or DIRECTOR_HEADERS)
        )

    def liaison_headers(self, institution_id: str) -> Dict[str, str]:
        return make_liaison_headers(institution_id)

    def complete_transfer(self, transfer_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.complete_transfer_request(transfer_id, {}, PERMIT_OFFICER_HEADERS)
        )


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------
def new_builder(api: Optional[ApiClient] = None) -> Builder:
    """A fresh builder over the shared client; the database is empty per test."""
    return Builder(api)
