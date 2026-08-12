"""The three hold axes and the five ordered custody gates."""
from test_helpers import (
    COUNSELOR_ONE,
    COUNSELOR_TWO,
    TEST_USERS,
    ApiErrorId,
    adoption_payload,
    animal_version,
    assert_hold_record,
    assert_same_instant,
    impose_hold,
    leg_version,
    make_counselor_headers,
    new_animal,
    new_driver,
    new_adopter,
    new_organization,
    new_person,
    screen_application,
    set_clock,
    setup_run_with_leg,
    submit_application,
    take_into_custody,
    make_altered,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
VET = TEST_USERS["veterinarian_headers"]
DISPATCH = TEST_USERS["transport_dispatcher_headers"]


def _unaltered_animal_with_medical_hold(api):
    """An adult unaltered dog whose stray hold has latched, an APPROVED application
    screened by counselor-1, and one ACTIVE MEDICAL hold."""
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    adopter = new_adopter(api)
    animal = new_animal(api, org["id"], name="Rex", size_class="LARGE", weight_lb=65.0,
                        date_of_birth="2020-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    hold = impose_hold(api, animal["id"], "MEDICAL", "kennel cough")
    set_clock(api, "2026-06-01T00:00:00Z")
    application = submit_application(api, animal["id"], adopter["id"])
    screen_application(api, application["id"], "APPROVE", COUNSELOR_ONE)
    return {
        "animal": animal,
        "application": application,
        "hold": hold,
        "animal_version": animal_version(api, animal["id"]),
    }


def test_medical_hold_gate_pre_empts_the_alteration_safety_rule(api):
    """PRD 2.6: "**Gate 4 — medical hold.** An `ACTIVE` `HoldRecord` whose `hold_type`
    is `MEDICAL` blocks exactly two operations — finalizing an adoption and
    transferring a foster placement to another home — with `ERR_MEDICAL_HOLD_ACTIVE`
    (HTTP 409)."
    PRD 2.5: "The system therefore evaluates a single global ladder of 45 rungs in a
    fixed sequence, and the first rung that fails determines the response."
    PRD 2.5: "**Gate 4** — no active medical hold restrains the target animal —
    otherwise `ERR_MEDICAL_HOLD_ACTIVE`."

    The animal is also unaltered and well over 16 weeks old, so the alteration rule at
    rung 28 would fail too; the gate at rung 15 is the observable answer.

    Design: Difficulty/priority_pair_validation_conflict/medical_hold_gate_preempts_alteration_safety_check
    """
    scenario = _unaltered_animal_with_medical_hold(api)

    validate_error(
        api.create_adoption(
            adoption_payload(scenario["application"]["id"], scenario["animal_version"]),
            make_counselor_headers(COUNSELOR_TWO),
        ),
        ApiErrorId.ERR_MEDICAL_HOLD_ACTIVE.value,
        409,
    )

    application = validate_success(
        api.get_adoption_application(scenario["application"]["id"], ADMIN)
    )
    assert application["status"] == "APPROVED"
    animal = validate_success(api.get_animal(scenario["animal"]["id"], ADMIN))
    assert animal["lifecycle_status"] == "IN_CUSTODY"


def test_releasing_the_medical_hold_surfaces_the_alteration_requirement(api):
    """PRD 3.3: "Releasing a hold moves it `ACTIVE → RELEASED`, stamps `released_at`
    with the current clock instant and `released_by_user_id` with the acting
    `X-User-ID`, increments the hold's `version` by one, and causes that hold's gate to
    stop firing for the animal."
    PRD 3.8: "And **alteration compliance** must hold: the animal must either already
    be `ALTERED`, or be younger than 16 weeks so that a deferred deposit can be taken
    instead. An unaltered animal at or over 16 weeks simply cannot be adopted out, and
    the refusal is `ERR_ALTERATION_REQUIRED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/medical_hold_gate_preempts_alteration_safety_check
    """
    scenario = _unaltered_animal_with_medical_hold(api)

    validate_error(
        api.create_adoption(
            adoption_payload(scenario["application"]["id"], scenario["animal_version"]),
            make_counselor_headers(COUNSELOR_TWO),
        ),
        ApiErrorId.ERR_MEDICAL_HOLD_ACTIVE.value,
        409,
    )

    released = validate_success(api.release_hold(scenario["hold"]["id"], ADMIN))
    assert released["status"] == "RELEASED"

    validate_error(
        api.create_adoption(
            adoption_payload(scenario["application"]["id"], scenario["animal_version"]),
            make_counselor_headers(COUNSELOR_TWO),
        ),
        ApiErrorId.ERR_ALTERATION_REQUIRED.value,
        422,
    )

    application = validate_success(
        api.get_adoption_application(scenario["application"]["id"], ADMIN)
    )
    assert application["status"] == "APPROVED"


def test_releasing_an_already_released_hold_is_an_invalid_state(api):
    """PRD 3.3: "A hold is a restraint imposed on an animal by an `IntakeOfficer`, a
    `Veterinarian` or a `PlatformAdmin`. It names a `hold_type` and a free-text
    `reason` recorded for audit, and it starts in `status` `ACTIVE` with `released_at`
    and `released_by_user_id` both null."
    PRD 3.3: "A hold already `RELEASED` cannot be released again; there is no
    transition out of `RELEASED`, so the attempt is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/hold_release_twice_returns_invalid_state
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    animal = new_animal(api, org["id"], name="Snap", weight_lb=30.0,
                        date_of_birth="2023-01-01T00:00:00Z", temperament="REACTIVE")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    hold = impose_hold(api, animal["id"], "BEHAVIORAL", "bite history under evaluation")
    assert_hold_record(hold)
    assert hold["status"] == "ACTIVE"
    assert hold["released_at"] is None
    assert hold["released_by_user_id"] is None

    released = validate_success(api.release_hold(hold["id"], INTAKE))
    assert released["status"] == "RELEASED"
    assert_same_instant(released["released_at"], "2026-05-01T00:00:00Z", "released_at")

    validate_error(
        api.release_hold(hold["id"], INTAKE), ApiErrorId.ERR_INVALID_STATE.value, 409
    )
    final = validate_success(api.get_hold(hold["id"], INTAKE))
    assert final["status"] == "RELEASED"


def test_legal_hold_blocks_a_manifest_while_a_medical_hold_does_not(api):
    """PRD 2.6: "**Gate 3 — legal hold.** An `ACTIVE` `HoldRecord` whose `hold_type` is
    `LEGAL` blocks transport and disposition writes only, with `ERR_LEGAL_HOLD_ACTIVE`
    (HTTP 409)."
    PRD 2.6: "**Gate 4 — medical hold.** An `ACTIVE` `HoldRecord` whose `hold_type` is
    `MEDICAL` blocks exactly two operations — finalizing an adoption and transferring a
    foster placement to another home — with `ERR_MEDICAL_HOLD_ACTIVE` (HTTP 409). A
    medical hold never blocks an owner reclaim and never blocks transport."
    PRD 3.2: "A reclaim is blocked by an active legal hold, but — and this asymmetry is
    deliberate — never by a medical or behavioural hold."

    Design: Corner/validations/legal_hold_blocks_transport_while_medical_hold_does_not
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    owner_m = new_person(api, "Owner M", "om@example.test")
    animal_l = new_animal(api, org["id"], name="Legal", size_class="SMALL", weight_lb=20.0,
                          date_of_birth="2022-01-01T00:00:00Z")
    animal_m = new_animal(api, org["id"], name="Medical", size_class="SMALL", weight_lb=20.0,
                          date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, animal_l["id"], "STRAY", "2026-05-01T00:00:00Z",
                      impound_billing_basis="CALENDAR_DAY")
    episode_m = take_into_custody(api, animal_m["id"], "STRAY", "2026-05-01T00:00:00Z",
                                  source_person_id=owner_m["id"],
                                  impound_billing_basis="CALENDAR_DAY")
    hold_l = impose_hold(api, animal_l["id"], "LEGAL", "cruelty investigation")
    hold_m = impose_hold(api, animal_m["id"], "MEDICAL", "upper respiratory infection")

    scenario = setup_run_with_leg(
        api, org["id"], driver=driver, leg_overrides={"species_policy": "DOGS_ONLY"}
    )
    leg = scenario["leg"]

    validate_error(
        api.create_manifest_entry(
            leg["id"],
            {"animal_id": animal_l["id"], "expected_leg_version": leg["version"]},
            DISPATCH,
        ),
        ApiErrorId.ERR_LEGAL_HOLD_ACTIVE.value,
        409,
    )

    entry = validate_success(
        api.create_manifest_entry(
            leg["id"],
            {"animal_id": animal_m["id"], "expected_leg_version": leg_version(api, leg["id"])},
            DISPATCH,
        ),
        201,
    )
    assert entry["status"] == "ASSIGNED"

    outcome = validate_success(
        api.reclaim(episode_m["id"], {"reclaiming_person_id": owner_m["id"]}, INTAKE), 201
    )
    assert outcome["outcome_type"] == "RETURN_TO_OWNER"

    assert validate_success(api.get_hold(hold_l["id"], INTAKE))["status"] == "ACTIVE"
    assert validate_success(api.get_hold(hold_m["id"], INTAKE))["status"] == "ACTIVE"


def test_behavioral_hold_blocks_only_the_adoption_finalization(api):
    """PRD 2.6: "**Gate 5 — behavioural hold.** An `ACTIVE` `HoldRecord` whose
    `hold_type` is `BEHAVIORAL` blocks exactly one operation — finalizing an adoption —
    with `ERR_BEHAVIORAL_HOLD_ACTIVE` (HTTP 409). A behavioural hold never blocks
    transport, never blocks a foster transfer, and never blocks a reclaim."

    Design: Corner/validations/behavioral_hold_blocks_adoption_only
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    adopter = new_adopter(api)
    driver = new_driver(api)
    animal = new_animal(api, org["id"], name="Snap", size_class="SMALL", weight_lb=20.0,
                        date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    make_altered(api, animal["id"], "2026-05-01T00:00:00Z")
    hold = impose_hold(api, animal["id"], "BEHAVIORAL", "resource guarding")
    application = submit_application(api, animal["id"], adopter["id"])
    screen_application(api, application["id"], "APPROVE", COUNSELOR_ONE)

    scenario = setup_run_with_leg(
        api, org["id"], driver=driver, leg_overrides={"species_policy": "DOGS_ONLY"}
    )
    expected_animal_version = animal_version(api, animal["id"])

    entry = validate_success(
        api.create_manifest_entry(
            scenario["leg"]["id"],
            {"animal_id": animal["id"],
             "expected_leg_version": scenario["leg"]["version"]},
            DISPATCH,
        ),
        201,
    )
    assert entry["status"] == "ASSIGNED"

    validate_error(
        api.create_adoption(
            adoption_payload(application["id"], expected_animal_version),
            make_counselor_headers(COUNSELOR_TWO),
        ),
        ApiErrorId.ERR_BEHAVIORAL_HOLD_ACTIVE.value,
        409,
    )
    assert validate_success(api.get_adoption_application(application["id"], ADMIN))[
        "status"
    ] == "APPROVED"
    assert validate_success(api.get_hold(hold["id"], INTAKE))["hold_type"] == "BEHAVIORAL"


def test_records_freeze_blocks_a_write_and_lifting_it_lets_the_write_through(api):
    """PRD 2.6: "While the flag is raised on the organization that owns the target
    resource, every create, update and delete under `/rescue` is rejected with
    `ERR_RECORDS_FROZEN` (HTTP 409)."
    PRD 2.6: "Reads are never gated — an organization under freeze remains fully
    readable, which is the point of a freeze during litigation or audit."
    PRD 3.1: "A freeze may only be raised from `UNFROZEN`, and it demands a non-empty
    `reason` string, which is stored as `records_freeze_reason`."

    Design: Corner/state_machines/records_freeze_gate_blocks_writes_and_lifts_cleanly
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    animal = new_animal(api, org["id"], name="Rex", weight_lb=40.0,
                        date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    frozen = validate_success(
        api.set_records_freeze(
            org["id"], {"freeze_active": True, "reason": "cruelty case subpoena"}, ADMIN
        )
    )
    assert frozen["records_freeze_active"] is True
    assert frozen["freeze_status"] == "FROZEN"
    assert frozen["records_freeze_reason"] == "cruelty case subpoena"

    validate_error(
        api.create_hold(
            animal["id"], {"hold_type": "MEDICAL", "reason": "post-op recovery"}, VET
        ),
        ApiErrorId.ERR_RECORDS_FROZEN.value,
        409,
    )

    read = validate_success(api.get_animal(animal["id"], ADMIN))
    assert read["lifecycle_status"] == "IN_CUSTODY"

    unfrozen = validate_success(
        api.set_records_freeze(org["id"], {"freeze_active": False}, ADMIN)
    )
    assert unfrozen["freeze_status"] == "UNFROZEN"

    hold = validate_success(
        api.create_hold(
            animal["id"], {"hold_type": "MEDICAL", "reason": "post-op recovery"}, VET
        ),
        201,
    )
    assert hold["status"] == "ACTIVE"
    assert hold["hold_type"] == "MEDICAL"


def test_outcome_closed_gate_pre_empts_the_state_rung_on_a_second_outcome(api):
    """PRD 2.6: "**Gate 2 — outcome closed.** An animal whose custody episode has been
    closed by an `OutcomeRecord` that has not been reversed sits in `lifecycle_status`
    `OUTCOME_CLOSED`, and further writes against it are rejected with
    `ERR_ANIMAL_OUTCOME_CLOSED` (HTTP 409)."
    PRD 3.9: "Note carefully what the gate ordering means for a second outcome:
    attempting to record another outcome on an animal whose custody is already closed
    reports `ERR_ANIMAL_OUTCOME_CLOSED`, not `ERR_INVALID_STATE`, because the gate sits
    above the state rung."
    PRD 3.9: "`is_live_release` is derived from the type and is true for exactly four
    members — `ADOPTION`, `FOSTER_TO_ADOPT`, `TRANSFER_OUT` and `RETURN_TO_OWNER`."

    Design: Corner/state_machines/outcome_closed_gate_blocks_second_outcome_on_same_animal
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    animal = new_animal(api, org["id"], name="Pixel", species="CAT", size_class="SMALL",
                        weight_lb=9.0, date_of_birth="2024-01-01T00:00:00Z")
    episode = take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    outcome = validate_success(
        api.create_outcome(animal["id"], {"outcome_type": "DIED_IN_CARE"}, INTAKE), 201
    )
    assert outcome["is_live_release"] is False

    validate_error(
        api.create_outcome(animal["id"], {"outcome_type": "EUTHANASIA_MEDICAL"}, INTAKE),
        ApiErrorId.ERR_ANIMAL_OUTCOME_CLOSED.value,
        409,
    )
    validate_error(
        api.create_intake_record(
            animal["id"],
            {"intake_type": "STRAY", "intake_datetime": "2026-05-02T00:00:00Z"},
            INTAKE,
        ),
        ApiErrorId.ERR_ANIMAL_OUTCOME_CLOSED.value,
        409,
    )

    assert validate_success(api.get_animal(animal["id"], ADMIN))[
        "lifecycle_status"
    ] == "OUTCOME_CLOSED"
    assert validate_success(api.get_intake_record(episode["id"], INTAKE))["status"] == "CLOSED"
    assert validate_success(api.get_outcome(outcome["id"], INTAKE))["reversed_at"] is None
