"""Composite setup helpers.

Every helper builds its state exclusively through declared endpoints — the
database is empty at the start of every test. Setup calls use the lenient
validator so a broken precondition reports as a setup failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    adoption_application_payload,
    adoption_payload,
    animal_payload,
    contribution_payload,
    driver_payload,
    foster_application_payload,
    foster_home_payload,
    foster_placement_payload,
    health_certificate_payload,
    hold_payload,
    intake_record_payload,
    litter_payload,
    medical_record_payload,
    organization_payload,
    partner_commitment_payload,
    partner_organization_payload,
    permissive_adopter_payload,
    person_payload,
    transport_leg_payload,
    transport_run_payload,
)
from .test_users import (
    COUNSELOR_ONE,
    COUNSELOR_TWO,
    TEST_USERS,
    make_counselor_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
COORD = TEST_USERS["foster_coordinator_headers"]
COUNSELOR = TEST_USERS["adoption_counselor_headers"]
DISPATCH = TEST_USERS["transport_dispatcher_headers"]
VET = TEST_USERS["veterinarian_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


# --------------------------------------------------------------------------
# Tier 0 — single-call primitives
# --------------------------------------------------------------------------
def set_clock(api, to_iso8601, headers=ADMIN):
    return get_success_data(api.set_clock(to_iso8601, headers))


def new_organization(api, **overrides):
    return get_success_data(api.create_organization(organization_payload(**overrides), ADMIN))


def new_partner_organization(api, **overrides):
    return get_success_data(
        api.create_organization(partner_organization_payload(**overrides), ADMIN)
    )


def new_person(api, full_name="Dana Reed", email="dana@example.test", **overrides):
    return get_success_data(
        api.create_person(person_payload(full_name, email, **overrides), ADMIN)
    )


def new_adopter(api, full_name="Dana Reed", email="dana@example.test", **overrides):
    """A Person whose declared household satisfies every default restriction."""
    return get_success_data(
        api.create_person(permissive_adopter_payload(full_name, email, **overrides), ADMIN)
    )


def new_driver(api, full_name="Milo Frey", email="milo@example.test",
               license_number="CDL-8891", **overrides):
    return get_success_data(
        api.create_person(driver_payload(full_name, email, license_number, **overrides), ADMIN)
    )


def new_animal(api, organization_id, **overrides):
    return get_success_data(
        api.create_animal(animal_payload(organization_id, **overrides), INTAKE)
    )


def new_litter(api, label="Maple litter", **overrides):
    return get_success_data(api.create_litter(litter_payload(label, **overrides), INTAKE))


def take_into_custody(api, animal_id, intake_type="OWNER_SURRENDER",
                      intake_datetime="2026-05-01T00:00:00Z", **overrides):
    return get_success_data(
        api.create_intake_record(
            animal_id, intake_record_payload(intake_type, intake_datetime, **overrides), INTAKE
        )
    )


def impose_hold(api, animal_id, hold_type="MEDICAL", reason="post-op recovery"):
    return get_success_data(
        api.create_hold(animal_id, hold_payload(hold_type, reason), INTAKE)
    )


def new_contribution(api, donor_person_id, amount_cents, donor_reference, **overrides):
    return get_success_data(
        api.create_contribution(
            contribution_payload(donor_person_id, amount_cents, donor_reference, **overrides),
            FINANCE,
        )
    )


def new_partner_commitment(api, organization_id, **overrides):
    return get_success_data(
        api.create_partner_commitment(
            partner_commitment_payload(organization_id, **overrides), DISPATCH
        )
    )


def animal_version(api, animal_id, headers=ADMIN):
    return get_success_data(api.get_animal(animal_id, headers))["version"]


def leg_version(api, leg_id, headers=DISPATCH):
    return get_success_data(api.get_transport_leg(leg_id, headers))["version"]


def foster_home_version(api, foster_home_id, headers=COORD):
    return get_success_data(api.get_foster_home(foster_home_id, headers))["version"]


# --------------------------------------------------------------------------
# Tier 1 — medical shortcuts that move the animal's own axes
# --------------------------------------------------------------------------
def complete_procedure(api, animal_id, procedure_type, expense_category,
                       cost_cents=0, scheduled_at="2026-05-01T00:00:00Z",
                       funding_required=False, funding_contribution_ids=None):
    """Order and complete one procedure. Returns the completed medical record."""
    record = get_success_data(
        api.create_medical_record(
            animal_id,
            medical_record_payload(
                procedure_type=procedure_type,
                expense_category=expense_category,
                cost_cents=cost_cents,
                scheduled_at=scheduled_at,
                funding_required=funding_required,
            ),
            VET,
        )
    )
    body = {}
    if funding_contribution_ids is not None:
        body["funding_contribution_ids"] = funding_contribution_ids
    return get_success_data(api.complete_medical_record(record["id"], VET, body))


def make_altered(api, animal_id, scheduled_at="2026-05-01T00:00:00Z"):
    """Completing a SPAY_NEUTER sets the animal's alteration_status to ALTERED."""
    return complete_procedure(
        api, animal_id, "SPAY_NEUTER", "SPAY_NEUTER", 0, scheduled_at, False
    )


def vaccinate_rabies(api, animal_id, scheduled_at="2026-05-01T00:00:00Z"):
    """Completing a VACCINE_RABIES stamps rabies_vaccinated_at with completed_at."""
    return complete_procedure(
        api, animal_id, "VACCINE_RABIES", "VACCINE", 0, scheduled_at, False
    )


def issue_certificate(api, animal_id, issued_at="2026-05-01T00:00:00Z",
                      destination_state="WA"):
    return get_success_data(
        api.issue_health_certificate(
            animal_id, health_certificate_payload(issued_at, destination_state), VET
        )
    )


# --------------------------------------------------------------------------
# Tier 2 — adoption pipeline
# --------------------------------------------------------------------------
def submit_application(api, animal_id, applicant_person_id, headers=None):
    return get_success_data(
        api.create_adoption_application(
            adoption_application_payload(animal_id, applicant_person_id),
            headers or make_counselor_headers(COUNSELOR_ONE),
        )
    )


def screen_application(api, application_id, decision="APPROVE", screener=COUNSELOR_ONE):
    return get_success_data(
        api.screen_adoption_application(
            application_id, {"decision": decision}, make_counselor_headers(screener)
        )
    )


def finalize_adoption(api, application_id, expected_animal_version,
                      finalizer=COUNSELOR_TWO, **options):
    return get_success_data(
        api.create_adoption(
            adoption_payload(application_id, expected_animal_version, **options),
            make_counselor_headers(finalizer),
        )
    )


def setup_adoptable_animal(api, clock_at_intake="2026-05-01T00:00:00Z",
                           clock_at_adoption="2026-06-01T00:00:00Z",
                           date_of_birth="2022-01-01T00:00:00Z",
                           species="DOG", size_class="MEDIUM", weight_lb=40.0,
                           altered=True, animal_overrides=None,
                           adopter_overrides=None, screener=COUNSELOR_ONE):
    """Shelter + adopter + an in-custody animal with an APPROVED application.

    The animal is OWNER_SURRENDER intaken at `clock_at_intake`, which carries a
    zero-day stray hold, so the hold has already latched to HOLD_EXPIRED by the
    time the clock reaches `clock_at_adoption`.
    Returns a dict with org, adopter, animal, application.
    """
    set_clock(api, clock_at_intake)
    org = new_organization(api)
    adopter = new_adopter(api, **(adopter_overrides or {}))
    animal = new_animal(
        api, org["id"], species=species, size_class=size_class, weight_lb=weight_lb,
        date_of_birth=date_of_birth, **(animal_overrides or {}),
    )
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", clock_at_intake)
    if altered:
        make_altered(api, animal["id"], clock_at_intake)
    if clock_at_adoption != clock_at_intake:
        set_clock(api, clock_at_adoption)
    application = submit_application(
        api, animal["id"], adopter["id"], make_counselor_headers(screener)
    )
    screen_application(api, application["id"], "APPROVE", screener)
    return {
        "org": org,
        "adopter": adopter,
        "animal": animal,
        "application": application,
    }


def setup_finalized_adoption(api, sponsorship_cents=None, sponsorship_reference="SPON-1",
                             finalize_options=None, **setup_kwargs):
    """setup_adoptable_animal plus an optional animal-designated sponsorship,
    finalized by a counselor who did not screen. Returns the setup dict plus
    `adoption` and (when created) `contribution`."""
    clock_at_intake = setup_kwargs.get("clock_at_intake", "2026-05-01T00:00:00Z")
    clock_at_adoption = setup_kwargs.get("clock_at_adoption", "2026-06-01T00:00:00Z")
    set_clock(api, clock_at_intake)
    org = new_organization(api)
    adopter = new_adopter(api, **(setup_kwargs.get("adopter_overrides") or {}))
    animal = new_animal(
        api, org["id"],
        species=setup_kwargs.get("species", "DOG"),
        size_class=setup_kwargs.get("size_class", "MEDIUM"),
        weight_lb=setup_kwargs.get("weight_lb", 40.0),
        date_of_birth=setup_kwargs.get("date_of_birth", "2022-01-01T00:00:00Z"),
        **(setup_kwargs.get("animal_overrides") or {}),
    )
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", clock_at_intake)
    if setup_kwargs.get("altered", True):
        make_altered(api, animal["id"], clock_at_intake)

    contribution = None
    if sponsorship_cents is not None:
        donor = new_person(api, "Gil Marsh", "gil@example.test")
        contribution = new_contribution(
            api, donor["id"], sponsorship_cents, sponsorship_reference,
            designated_animal_id=animal["id"], designated_program="NONE",
            restriction_category="UNRESTRICTED",
        )

    if clock_at_adoption != clock_at_intake:
        set_clock(api, clock_at_adoption)
    application = submit_application(api, animal["id"], adopter["id"])
    screen_application(api, application["id"], "APPROVE", COUNSELOR_ONE)
    adoption = finalize_adoption(
        api, application["id"], animal_version(api, animal["id"]),
        COUNSELOR_TWO, **(finalize_options or {}),
    )
    return {
        "org": org,
        "adopter": adopter,
        "animal": animal,
        "application": application,
        "adoption": adoption,
        "contribution": contribution,
    }


# --------------------------------------------------------------------------
# Tier 3 — foster pipeline
# --------------------------------------------------------------------------
def setup_foster_home(api, species_requested="DOG", home_overrides=None,
                      checked_at="2026-05-01T00:00:00Z", person_name="Rhea Voss",
                      person_email="rhea@example.test", person_overrides=None):
    """Foster parent + home + an APPROVED application whose home check has PASSED."""
    parent = new_person(
        api, person_name, person_email, **(person_overrides or {"housing_type": "HOUSE"})
    )
    home = get_success_data(
        api.create_foster_home(
            foster_home_payload(parent["id"], **(home_overrides or {})), COORD
        )
    )
    application = get_success_data(
        api.create_foster_application(
            foster_application_payload(parent["id"], home["id"], species_requested), COORD
        )
    )
    get_success_data(
        api.decide_foster_application(application["id"], {"decision": "APPROVE"}, COORD)
    )
    get_success_data(
        api.record_home_check(
            application["id"], {"result": "PASS", "checked_at": checked_at}, COORD
        )
    )
    return {"parent": parent, "home": home, "application": application}


def propose_placement(api, animal_id, home_id, application_id, **overrides):
    return get_success_data(
        api.create_foster_placement(
            foster_placement_payload(
                animal_id, home_id, application_id,
                foster_home_version(api, home_id), **overrides,
            ),
            COORD,
        )
    )


def activate_placement(api, placement_id):
    return get_success_data(api.activate_foster_placement(placement_id, COORD))


def place_animal_in_home(api, animal_id, home_id, application_id, **overrides):
    """Propose then activate one placement. Returns the ACTIVE placement."""
    placement = propose_placement(api, animal_id, home_id, application_id, **overrides)
    return activate_placement(api, placement["id"])


# --------------------------------------------------------------------------
# Tier 4 — transport
# --------------------------------------------------------------------------
def new_run(api, organization_id, **overrides):
    return get_success_data(
        api.create_transport_run(transport_run_payload(organization_id, **overrides), DISPATCH)
    )


def add_leg(api, run_id, driver_person_id, **overrides):
    return get_success_data(
        api.create_transport_leg(
            run_id, transport_leg_payload(driver_person_id, **overrides), DISPATCH
        )
    )


def manifest_animal(api, leg_id, animal_id):
    """Manifest one animal, always re-reading the leg's current version first."""
    return get_success_data(
        api.create_manifest_entry(
            leg_id, {"animal_id": animal_id, "expected_leg_version": leg_version(api, leg_id)},
            DISPATCH,
        )
    )


def setup_run_with_leg(api, organization_id, run_overrides=None, leg_overrides=None,
                       driver=None):
    """A PLANNED run carrying one leg, plus its licensed driver."""
    driver = driver or new_driver(api)
    run = new_run(api, organization_id, **(run_overrides or {}))
    leg = add_leg(api, run["id"], driver["id"], **(leg_overrides or {}))
    return {"driver": driver, "run": run, "leg": leg}


def setup_relay_run(api, organization_id, driver=None, run_overrides=None,
                    leg1_overrides=None, leg2_overrides=None):
    """A PLANNED RELAY run with two sequenced legs on non-overlapping intervals."""
    driver = driver or new_driver(api)
    run = new_run(api, organization_id, run_type="RELAY",
                  destination_hub_code="HUB-C", **(run_overrides or {}))
    leg1_defaults = {
        "sequence_no": 1, "origin_hub_code": "HUB-A", "destination_hub_code": "HUB-B",
        "scheduled_depart_at": "2026-05-05T08:00:00Z",
        "scheduled_arrive_at": "2026-05-05T12:00:00Z",
    }
    leg1_defaults.update(leg1_overrides or {})
    leg2_defaults = {
        "sequence_no": 2, "origin_hub_code": "HUB-B", "destination_hub_code": "HUB-C",
        "scheduled_depart_at": "2026-05-05T14:00:00Z",
        "scheduled_arrive_at": "2026-05-05T18:00:00Z",
    }
    leg2_defaults.update(leg2_overrides or {})
    leg1 = add_leg(api, run["id"], driver["id"], **leg1_defaults)
    leg2 = add_leg(api, run["id"], driver["id"], **leg2_defaults)
    return {"driver": driver, "run": run, "leg1": leg1, "leg2": leg2}


def start_run(api, run_id):
    return get_success_data(api.start_transport_run(run_id, DISPATCH))


def depart_leg(api, leg_id, headers=DISPATCH):
    return get_success_data(api.depart_transport_leg(leg_id, headers))


def arrive_leg(api, leg_id, headers=DISPATCH):
    return get_success_data(api.arrive_transport_leg(leg_id, headers))


# --------------------------------------------------------------------------
# Tier 5 — outcomes
# --------------------------------------------------------------------------
def record_outcome(api, animal_id, outcome_type="DIED_IN_CARE", **overrides):
    payload = {"outcome_type": outcome_type}
    payload.update(overrides)
    return get_success_data(api.create_outcome(animal_id, payload, INTAKE))


def standing_outcome_for(api, animal_id, outcome_type=None):
    """The animal's outcome record, read back through the list endpoint."""
    params = {"animal_id": animal_id}
    if outcome_type:
        params["outcome_type"] = outcome_type
    response = api.list_outcomes(INTAKE, params)
    assert response.status_code == 200, (
        f"Setup step failed listing outcomes: HTTP {response.status_code} {response.text}"
    )
    rows = response.json()["data"]
    assert rows, f"expected at least one outcome record for animal {animal_id}"
    return rows[0]


def open_intake_for(api, animal_id):
    response = api.list_intake_records(INTAKE, {"animal_id": animal_id, "status": "OPEN"})
    assert response.status_code == 200, (
        f"Setup step failed listing custody episodes: HTTP {response.status_code} "
        f"{response.text}"
    )
    rows = response.json()["data"]
    assert rows, f"expected an OPEN custody episode for animal {animal_id}"
    return rows[0]


# Re-exported client for tests that want the module-level singleton directly.
default_api = api_client
