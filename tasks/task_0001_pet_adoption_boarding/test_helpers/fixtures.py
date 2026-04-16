"""Composite setup helpers for multi-step test state preparation."""
from datetime import datetime, timezone, timedelta
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client
from .factories import (
    create_shelter_payload, create_animal_payload, create_vaccination_payload,
    create_adopter_payload, create_home_visit_payload, submit_home_visit_payload,
    create_application_payload, create_reservation_payload, create_settlement_payload,
    future_iso, past_iso, _iso,
)
from .test_users import TEST_USERS, make_inspector_headers, make_approver_headers, make_reviewer_headers, make_adopter_headers


# -------------------------------------------------------------------
# Tier 1: Shelter / Animal / Adopter creation
# -------------------------------------------------------------------

def create_shelter(boarding_capacity: int = 10, adoption_fee_base: int = 20000,
                   boarding_rate_per_night: int = 5000, name: str = "Test Shelter") -> dict:
    payload = create_shelter_payload(
        name=name, boarding_capacity=boarding_capacity,
        adoption_fee_base=adoption_fee_base,
        boarding_rate_per_night=boarding_rate_per_night,
    )
    resp = api_client.create_shelter(payload, TEST_USERS["shelter_admin_headers"])
    return get_success_data(resp)


def create_animal(shelter_id: str, species: str = "DOG", age_months: int = 24,
                  special_care_level: str = "NONE", adoption_fee_override=None,
                  name: str = "Biscuit", temperament_tags=None) -> dict:
    payload = create_animal_payload(
        name=name, species=species, age_months=age_months,
        special_care_level=special_care_level,
    )
    if adoption_fee_override is not None:
        payload["adoption_fee_override"] = adoption_fee_override
    if temperament_tags is not None:
        payload["temperament_tags"] = temperament_tags
    resp = api_client.create_animal(shelter_id, payload, TEST_USERS["shelter_admin_headers"])
    return get_success_data(resp)


def required_vaccines_for_species(species: str):
    return {
        "DOG": ["RABIES", "DISTEMPER", "PARVO", "BORDETELLA"],
        "CAT": ["RABIES", "DISTEMPER", "FELV"],
        "RABBIT": ["RABIES"],
        "OTHER": ["RABIES"],
    }[species]


def fully_vaccinate_animal(shelter_id: str, animal_id: str, species: str = "DOG",
                           expires_in_days: int = 365) -> list:
    """Record every required vaccine for the species, with a long expiry."""
    records = []
    for vtype in required_vaccines_for_species(species):
        payload = create_vaccination_payload(
            vaccine_type=vtype,
            administered_date=past_iso(1),
            expires_date=future_iso(expires_in_days),
        )
        resp = api_client.create_vaccination(shelter_id, animal_id, payload,
                                             TEST_USERS["shelter_admin_headers"])
        records.append(get_success_data(resp))
    return records


def create_adopter(full_name: str = "Alice Adopter", household_size: int = 2,
                   has_yard: bool = True) -> dict:
    payload = create_adopter_payload(full_name=full_name, household_size=household_size, has_yard=has_yard)
    resp = api_client.create_adopter(payload, TEST_USERS["adopter_headers"])
    return get_success_data(resp)


# -------------------------------------------------------------------
# Tier 2: Home visit lifecycle (reach PASSED / FAILED state)
# -------------------------------------------------------------------

def schedule_home_visit(adopter_id: str, inspector_user_id: str = "inspector-01",
                        scheduled_for: str = None,
                        reviewer_headers: dict = None) -> dict:
    payload = create_home_visit_payload(
        scheduled_for=scheduled_for or future_iso(3),
        inspector_id=inspector_user_id,
    )
    resp = api_client.create_home_visit(
        adopter_id, payload,
        reviewer_headers or TEST_USERS["adoption_reviewer_headers"],
    )
    return get_success_data(resp)


def submit_home_visit(adopter_id: str, hv_id: str, inspector_user_id: str,
                      safety_score: int = 85, yard_verified: bool = True) -> dict:
    payload = submit_home_visit_payload(safety_score=safety_score, yard_verified=yard_verified)
    resp = api_client.submit_home_visit(
        adopter_id, hv_id, payload,
        make_inspector_headers(inspector_user_id),
    )
    return get_success_data(resp)


def create_adopter_with_passed_home_visit(safety_score: int = 85,
                                          inspector_user_id: str = "inspector-01") -> dict:
    """Return adopter dict after completing a PASSED home visit."""
    adopter = create_adopter()
    hv = schedule_home_visit(adopter["id"], inspector_user_id=inspector_user_id)
    submit_home_visit(adopter["id"], hv["id"], inspector_user_id=inspector_user_id,
                      safety_score=safety_score)
    # Refresh adopter state
    resp = api_client.get_adopter(adopter["id"], TEST_USERS["shelter_admin_headers"])
    return get_success_data(resp)


# -------------------------------------------------------------------
# Tier 3: Ready-to-approve shelter + vaccinated animal + passed adopter
# -------------------------------------------------------------------

def setup_ready_for_approval(boarding_capacity: int = 10,
                             adoption_fee_base: int = 20000,
                             age_months: int = 24,
                             species: str = "DOG",
                             special_care_level: str = "NONE",
                             adoption_fee_override=None,
                             inspector_user_id: str = "inspector-01") -> dict:
    """Build a full scenario: shelter + compliant animal + adopter with PASSED HV.
    Returns dict with keys: shelter, animal, adopter.
    """
    shelter = create_shelter(boarding_capacity=boarding_capacity,
                             adoption_fee_base=adoption_fee_base)
    animal = create_animal(shelter["id"], species=species, age_months=age_months,
                           special_care_level=special_care_level,
                           adoption_fee_override=adoption_fee_override)
    fully_vaccinate_animal(shelter["id"], animal["id"], species=species)
    adopter = create_adopter_with_passed_home_visit(inspector_user_id=inspector_user_id)
    return {"shelter": shelter, "animal": animal, "adopter": adopter}


def submit_application(adopter_id: str, animal_id: str, adopter_headers: dict = None) -> dict:
    payload = create_application_payload(adopter_id=adopter_id, animal_id=animal_id)
    resp = api_client.create_application(payload, adopter_headers or TEST_USERS["adopter_headers"])
    return get_success_data(resp)


def walk_application_to_under_review(app_id: str,
                                     reviewer_user_id: str = "reviewer-01") -> dict:
    headers = make_reviewer_headers(reviewer_user_id)
    resp = api_client.begin_review(app_id, headers)
    return get_success_data(resp)


def approve_application(app_id: str, approver_user_id: str = "approver-01") -> dict:
    resp = api_client.approve_application(app_id, make_approver_headers(approver_user_id))
    return get_success_data(resp)


def setup_approved_application(reviewer_user_id: str = "reviewer-01",
                               approver_user_id: str = "approver-01",
                               age_months: int = 24,
                               species: str = "DOG",
                               adoption_fee_override=None,
                               adoption_fee_base: int = 20000,
                               special_care_level: str = "NONE") -> dict:
    """Shelter + animal + adopter + application walked to APPROVED."""
    ctx = setup_ready_for_approval(
        adoption_fee_base=adoption_fee_base,
        age_months=age_months, species=species,
        special_care_level=special_care_level,
        adoption_fee_override=adoption_fee_override,
    )
    adopter_headers = make_adopter_headers("adopter-app-" + ctx["adopter"]["id"][:6])
    app = submit_application(ctx["adopter"]["id"], ctx["animal"]["id"],
                             adopter_headers=adopter_headers)
    walk_application_to_under_review(app["id"], reviewer_user_id=reviewer_user_id)
    app = approve_application(app["id"], approver_user_id=approver_user_id)
    ctx["application"] = app
    ctx["adopter_headers"] = adopter_headers
    return ctx


# -------------------------------------------------------------------
# Tier 4: Settlement lifecycle
# -------------------------------------------------------------------

def create_pending_settlement(subject_type: str, subject_id: str, amount: int,
                              method: str = "CARD") -> dict:
    payload = create_settlement_payload(subject_type=subject_type, subject_id=subject_id,
                                        amount=amount, method=method)
    resp = api_client.create_settlement(payload, TEST_USERS["finance_officer_headers"])
    return get_success_data(resp)


def capture_settlement(settlement_id: str) -> dict:
    resp = api_client.capture_settlement(settlement_id, TEST_USERS["finance_officer_headers"])
    return get_success_data(resp)


def create_and_capture_settlement(subject_type: str, subject_id: str, amount: int) -> dict:
    st = create_pending_settlement(subject_type, subject_id, amount)
    return capture_settlement(st["id"])


def setup_finalizable_application(**overrides) -> dict:
    """Approved app + captured ADOPTION settlement, ready to finalize."""
    ctx = setup_approved_application(**overrides)
    pinned_fee = ctx["application"]["pinned_fee"]
    settlement = create_and_capture_settlement("ADOPTION", ctx["application"]["id"], pinned_fee)
    ctx["settlement"] = settlement
    return ctx


# -------------------------------------------------------------------
# Tier 5: Boarding lifecycle
# -------------------------------------------------------------------

def create_boardable_animal(shelter_id: str, species: str = "DOG",
                            special_care_level: str = "NONE",
                            age_months: int = 24) -> dict:
    animal = create_animal(shelter_id, species=species, special_care_level=special_care_level,
                           age_months=age_months)
    fully_vaccinate_animal(shelter_id, animal["id"], species=species)
    return animal


def create_reservation(shelter_id: str, animal_id: str, owner_id: str, nights: int = 3,
                       check_in_offset_days: int = 1,
                       headers: dict = None) -> dict:
    check_in = datetime.now(timezone.utc) + timedelta(days=check_in_offset_days)
    check_out = check_in + timedelta(days=nights)
    payload = create_reservation_payload(
        animal_id=animal_id, owner_id=owner_id,
        check_in_date=_iso(check_in),
        check_out_date=_iso(check_out),
    )
    resp = api_client.create_reservation(shelter_id, payload,
                                         headers or TEST_USERS["boarding_coordinator_headers"])
    return get_success_data(resp)


def setup_reservation_scenario(boarding_capacity: int = 10,
                               boarding_rate_per_night: int = 5000,
                               special_care_level: str = "NONE",
                               nights: int = 3) -> dict:
    shelter = create_shelter(boarding_capacity=boarding_capacity,
                             boarding_rate_per_night=boarding_rate_per_night)
    animal = create_boardable_animal(shelter["id"], special_care_level=special_care_level)
    adopter = create_adopter()
    reservation = create_reservation(shelter["id"], animal["id"], adopter["id"], nights=nights)
    return {"shelter": shelter, "animal": animal, "adopter": adopter, "reservation": reservation}


def fill_shelter_to_capacity(shelter_id: str, leaving_free: int = 0) -> int:
    """Create enough RESERVED reservations so only `leaving_free` slots remain."""
    shelter_resp = api_client.get_shelter(shelter_id, TEST_USERS["shelter_admin_headers"])
    shelter = get_success_data(shelter_resp)
    capacity = shelter["boarding_capacity"]
    already_reserved = shelter["reserved_slots"]
    to_create = capacity - already_reserved - leaving_free
    created = 0
    adopter = create_adopter()
    for _ in range(to_create):
        animal = create_boardable_animal(shelter_id)
        create_reservation(shelter_id, animal["id"], adopter["id"], nights=2)
        created += 1
    return created


# Helpers for withdraw scenarios - give adopter headers matching the application's adopter
def make_adopter_headers_for(adopter_id: str) -> dict:
    """Make header where X-User-ID equals adopter_id (PRD §3.4 withdraw requires match)."""
    return build_user_headers(adopter_id, "Adopter")
