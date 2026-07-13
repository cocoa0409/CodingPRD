"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch (the harness restarts the
server against an empty database before each test) using only PRD-declared
endpoints. Setup calls use get_success_data() (lenient) so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Owner is the only entity_backed role: after an Owner is created, any ownership
-gated Owner call uses make_owner_headers(owner["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    create_owner_payload, create_animal_payload, create_bite_case_payload,
    create_facility_payload, create_quarantine_order_payload,
    create_specimen_payload, create_pep_recommendation_payload,
    create_citation_payload, create_surveillance_region_payload,
    create_wildlife_report_payload,
)
from .test_users import (
    make_intake_officer_headers, make_epidemiologist_headers,
    make_veterinarian_headers, make_animal_control_officer_headers,
    make_health_dept_admin_headers, make_owner_headers,
)


# ---------------------------------------------------------------------------
# Role-header shortcuts (opaque roles use fixed operator ids).
# ---------------------------------------------------------------------------
def _intake():
    return make_intake_officer_headers()


def _epi():
    return make_epidemiologist_headers()


def _vet():
    return make_veterinarian_headers()


def _aco():
    return make_animal_control_officer_headers()


def _admin():
    return make_health_dept_admin_headers()


# ---------------------------------------------------------------------------
# Tier 1: primitive entity creators.
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Advance the logical clock to `iso` (HealthDeptAdmin only)."""
    return api_client.set_clock({"to_iso8601": iso}, _admin())


def create_owner(**overrides):
    return get_success_data(api_client.create_owner(create_owner_payload(**overrides), _intake()))


def create_animal(owner_id=None, **overrides):
    payload = create_animal_payload(**overrides)
    if owner_id is not None:
        payload["owner_id"] = owner_id
    return get_success_data(api_client.create_animal(payload, _intake()))


def create_bite_case(animal_id=None, **overrides):
    payload = create_bite_case_payload(**overrides)
    if animal_id is not None:
        payload["animal_id"] = animal_id
    return get_success_data(api_client.create_bite_case(payload, _intake()))


def create_facility(**overrides):
    return get_success_data(api_client.create_facility(create_facility_payload(**overrides), _admin()))


def create_region(region_code, positive_threshold=None):
    overrides = {}
    if positive_threshold is not None:
        overrides["positive_threshold"] = positive_threshold
    return get_success_data(
        api_client.create_surveillance_region(
            create_surveillance_region_payload(region_code, **overrides), _admin()))


def euthanize_animal(animal_id):
    """Move an animal to EUTHANIZED so it becomes specimen-eligible."""
    return get_success_data(
        api_client.disposition_animal(animal_id, {"disposition": "EUTHANIZED"}, _aco()))


def mark_animal_escaped(animal_id):
    """Record an unidentified REPORTED animal as AT_LARGE (escaped)."""
    return get_success_data(
        api_client.disposition_animal(animal_id, {"escaped": True}, _aco()))


def issue_quarantine_order(case_id, case_version, animal_id, order_type="FACILITY",
                           facility_id=None, start_date=CLOCK_START):
    payload = create_quarantine_order_payload(
        case_version, animal_id, order_type=order_type, start_date=start_date)
    if facility_id is not None:
        payload["facility_id"] = facility_id
    return get_success_data(api_client.create_quarantine_order(case_id, payload, _vet()))


def submit_specimen(case_id, animal_id, condition="SATISFACTORY",
                    collected_datetime="2026-03-01T06:30:00Z"):
    return get_success_data(api_client.create_specimen(
        case_id, create_specimen_payload(animal_id, condition=condition,
                                         collected_datetime=collected_datetime), _vet()))


def report_result(specimen_id, result, test_method="DFA"):
    return get_success_data(api_client.report_result(
        specimen_id, {"test_method": test_method, "result": result}, _vet()))


def create_pep(case_id, case_version):
    return get_success_data(api_client.create_pep_recommendation(
        case_id, create_pep_recommendation_payload(case_version), _epi()))


def administer_dose(pep_id):
    return get_success_data(api_client.administer_dose(pep_id, {}, _epi()))


def issue_citation(owner_id, case_id, violations):
    return get_success_data(api_client.create_citation(
        create_citation_payload(owner_id, case_id, violations), _aco()))


def refetch_case(case_id):
    return get_success_data(api_client.get_bite_case(case_id, _intake()))


def refetch_owner(owner_id):
    return get_success_data(api_client.get_owner(owner_id, _intake()))


def refetch_facility(facility_id):
    return get_success_data(api_client.get_facility(facility_id, _admin()))


def refetch_order(order_id):
    return get_success_data(api_client.get_quarantine_order(order_id, _vet()))


def refetch_animal(animal_id):
    return get_success_data(api_client.get_animal(animal_id, _intake()))


def refetch_region(region_id):
    return get_success_data(api_client.get_surveillance_region(region_id, _admin()))


# ---------------------------------------------------------------------------
# Tier 2 / 3: composite scenarios.
# ---------------------------------------------------------------------------
def setup_active_facility_order(vaccination_status="CURRENT", species="DOG",
                                animal_class="DOMESTIC", wound_category="CATEGORY_II",
                                region_code="RB-QO", capacity=5,
                                daily_boarding_cents=4000, clock=CLOCK_START,
                                start_date=CLOCK_START, with_owner=True):
    """Owner (optional) + animal + facility + OPEN case, clock set, then a FACILITY
    QuarantineOrder issued ACTIVE. Returns dict(owner, animal, facility, case, order)."""
    owner = create_owner() if with_owner else None
    animal = create_animal(
        owner_id=(owner["id"] if owner else None),
        species=species, animal_class=animal_class,
        vaccination_status=vaccination_status)
    facility = create_facility(capacity=capacity, daily_boarding_cents=daily_boarding_cents)
    case = create_bite_case(region_code=region_code, wound_category=wound_category,
                            animal_id=animal["id"])
    set_clock(clock)
    order = issue_quarantine_order(
        case["id"], case["version"], animal["id"],
        order_type="FACILITY", facility_id=facility["id"], start_date=start_date)
    return {"owner": owner, "animal": animal, "facility": facility,
            "case": case, "order": order}


def setup_home_confinement_order(region_code="RB-HC", clock=CLOCK_START,
                                 start_date=CLOCK_START, with_owner=False):
    """Animal + OPEN case, clock set, then a HOME_CONFINEMENT order issued ACTIVE.
    Returns dict(owner, animal, case, order)."""
    owner = create_owner() if with_owner else None
    animal = create_animal(owner_id=(owner["id"] if owner else None))
    case = create_bite_case(region_code=region_code, animal_id=animal["id"])
    set_clock(clock)
    order = issue_quarantine_order(
        case["id"], case["version"], animal["id"],
        order_type="HOME_CONFINEMENT", start_date=start_date)
    return {"owner": owner, "animal": animal, "case": case, "order": order}


def setup_pep_initiated(wound_category="CATEGORY_II", doses=1, region_code="RB-PEP"):
    """DOG (EXPIRED) -> MODERATE/INITIATE case, a PEPRecommendation created, then
    `doses` doses administered (INITIATED). Returns dict(animal, case, pep)."""
    animal = create_animal(species="DOG", animal_class="DOMESTIC",
                           vaccination_status="EXPIRED")
    case = create_bite_case(region_code=region_code, wound_category=wound_category,
                            animal_id=animal["id"])
    pep = create_pep(case["id"], case["version"])
    for _ in range(doses):
        pep = administer_dose(pep["id"])
    return {"animal": animal, "case": case, "pep": pep}


def setup_citation_issued(violations=("NO_CURRENT_VACCINATION", "UNLICENSED_ANIMAL"),
                          region_code="RB-CIT"):
    """Owner + CATEGORY_I case (no animal) + issued Citation.
    Returns dict(owner, case, citation)."""
    owner = create_owner()
    case = create_bite_case(region_code=region_code, wound_category="CATEGORY_I",
                            exposure_type="SCRATCH")
    citation = issue_citation(owner["id"], case["id"], list(violations))
    return {"owner": owner, "case": case, "citation": citation}


def setup_lab_pending_specimen(region_code="RB-LAB", positive_threshold=1,
                               species="DOG", animal_class="DOMESTIC",
                               wound_category="CATEGORY_III", create_region_flag=True):
    """SurveillanceRegion (optional) + EUTHANIZED animal + case + SATISFACTORY
    specimen (case now LAB_PENDING). Returns dict(region, animal, case, specimen)."""
    region = create_region(region_code, positive_threshold) if create_region_flag else None
    animal = create_animal(species=species, animal_class=animal_class,
                           vaccination_status="NONE")
    euthanize_animal(animal["id"])
    case = create_bite_case(region_code=region_code, wound_category=wound_category,
                            animal_id=animal["id"])
    specimen = submit_specimen(case["id"], animal["id"], condition="SATISFACTORY")
    return {"region": region, "animal": animal, "case": case, "specimen": specimen}


def add_lab_pending_case_for_region(region_code, species="SKUNK", animal_class="WILD",
                                    wound_category="CATEGORY_III",
                                    collected_datetime="2026-03-01T01:35:00Z"):
    """A further EUTHANIZED animal + case in an existing region + SATISFACTORY
    specimen. Returns dict(animal, case, specimen)."""
    animal = create_animal(species=species, animal_class=animal_class,
                           vaccination_status="NONE")
    euthanize_animal(animal["id"])
    case = create_bite_case(region_code=region_code, wound_category=wound_category,
                            animal_id=animal["id"])
    specimen = submit_specimen(case["id"], animal["id"], condition="SATISFACTORY",
                               collected_datetime=collected_datetime)
    return {"animal": animal, "case": case, "specimen": specimen}
