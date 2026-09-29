"""The screening ladder, the container-compliance matrix and the weight gates.

Screening is where the acceptance criteria of PRD §3.4 live, and the container
evaluation is the constraint-propagation pass whose output order is normative.
"""

from test_helpers import (
    ApiErrorId,
    SECOND_ACCEPTANCE_AGENT_ID,
    assert_animal_state,
    assert_flight_leg_state,
    assert_segment_state,
    validate_error,
    validate_success,
)


def test_withdrawn_weight_cap_restriction_no_longer_blocks_screen(api, workbench):
    """An ACTIVE weight cap refuses the screen on gross weight; withdrawing it
    removes the restriction from the acceptance decision entirely.

    PRD §3.1: "A restriction's `status` is `ACTIVE` or `WITHDRAWN` and defaults to
    `ACTIVE`; only `ACTIVE` rows participate in any acceptance decision."

    Design: Corner/validations/withdrawn_weight_cap_restriction_no_longer_blocks_screen
    """
    species = workbench.create_species()
    container = workbench.create_container()
    restriction = workbench.create_breed_restriction(
        species["id"],
        breed_name="Labrador",
        restriction_type="WEIGHT_CAPPED",
        max_weight_kg=20,
    )
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], species["id"], container["id"]
    )

    capped = api.screen_animal_record(animal["id"], workbench.acceptance())
    validate_error(capped, ApiErrorId.BREED_WEIGHT_CAP_EXCEEDED, 422)

    workbench.set_breed_restriction_status(restriction["id"], "WITHDRAWN")
    screened = validate_success(
        api.screen_animal_record(animal["id"], workbench.acceptance())
    )
    assert_animal_state(
        screened,
        status="SCREENED",
        container_compliance_state="COMPLIANT",
        deficiency_codes=[],
        chargeable_weight_kg=27,
    )
    assert workbench.read_species(species["id"])["breed_restriction_count"] == 0


def test_screen_with_retired_species_rejected(api, workbench, catalog):
    """Retiring a species blocks screening of the animals already booked under it,
    and the refused screen writes nothing onto the animal.

    PRD §3.1: "a `ProgramAdmin` may flip it, and retiring a species blocks both
    adding new animals of that species and screening existing ones, each attempt
    being refused with `ERR_SPECIES_RETIRED`."

    Design: Corner/validations/screen_with_retired_species_rejected
    """
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    workbench.set_species_status(catalog["species_id"], "RETIRED")

    refused = api.screen_animal_record(animal["id"], workbench.acceptance())
    validate_error(refused, ApiErrorId.SPECIES_RETIRED, 422)

    assert_animal_state(
        workbench.read_animal(animal["id"]),
        status="DRAFT",
        container_compliance_state="UNEVALUATED",
        deficiency_codes=[],
        chargeable_weight_kg=0,
    )


def test_screen_of_banned_breed_rejected(api, workbench):
    """The banned-breed rung outranks the age rung, so an underage animal of a
    banned breed reports the ban.

    PRD §2.6: "No `ACTIVE` breed restriction of `restriction_type` `BANNED` matches
    the animal's breed, compared case-insensitively — otherwise `ERR_BREED_BANNED`
    (422). Applies to `POST /animal-records/{id}/screen`."

    Design: Corner/validations/screen_of_banned_breed_rejected
    """
    species = workbench.create_species()
    container = workbench.create_container()
    workbench.create_breed_restriction(
        species["id"], breed_name="Labrador", restriction_type="BANNED"
    )
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"],
        species["id"],
        container["id"],
        breed_name="labrador",
        age_weeks=10,
    )

    refused = api.screen_animal_record(animal["id"], workbench.acceptance())
    validate_error(refused, ApiErrorId.BREED_BANNED, 422)

    assert_animal_state(workbench.read_animal(animal["id"]), status="DRAFT")
    assert workbench.read_species(species["id"])["breed_restriction_count"] == 1


def test_screen_of_underage_animal_rejected(api, workbench, catalog):
    """One week below the species minimum is refused; exactly at the minimum is
    accepted.

    PRD §2.6: "The animal's `age_weeks` is at least the species profile's
    `min_age_weeks` — otherwise `ERR_ANIMAL_UNDERAGE` (422)."

    Design: Corner/validations/screen_of_underage_animal_rejected
    """
    reservation = workbench.create_reservation()
    underage = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        age_weeks=15,
    )

    refused = api.screen_animal_record(underage["id"], workbench.acceptance())
    validate_error(refused, ApiErrorId.ANIMAL_UNDERAGE, 422)
    assert_animal_state(
        workbench.read_animal(underage["id"]), status="DRAFT", deficiency_codes=[]
    )

    at_minimum = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        animal_name="Taro",
        age_weeks=16,
    )
    screened = validate_success(
        api.screen_animal_record(at_minimum["id"], workbench.acceptance())
    )
    assert_animal_state(
        screened, status="SCREENED", container_compliance_state="COMPLIANT"
    )


def test_cargo_only_species_on_checked_routing_rejected(api, workbench):
    """A cargo-only acceptance class narrows the whole booking, so a checked
    reservation is refused on the routing rung rather than on acceptance class.

    PRD §3.4: "when the species profile's `acceptance_class` is `CARGO_ONLY`, or
    when an `ACTIVE` breed restriction of `restriction_type` `CARGO_ONLY` matches the
    breed, the owning reservation's `routing_type` must be `CARGO`, and a cabin or
    checked booking for such an animal is refused with
    `ERR_ROUTING_NOT_PERMITTED_FOR_BREED`."

    Design: Corner/validations/cargo_only_species_on_checked_routing_rejected
    """
    species = workbench.create_species(
        species_code="REPTILE",
        common_name="Reptile",
        acceptance_class="CARGO_ONLY",
        max_cabin_weight_kg=0,
        min_age_weeks=8,
    )
    container = workbench.create_container()

    checked = workbench.create_reservation(routing_type="CHECKED")
    on_checked = workbench.create_animal(
        checked["id"],
        species["id"],
        container["id"],
        animal_name="Sunny",
        breed_name="Iguana",
        declared_weight_kg=6,
        height_at_shoulder_cm=20,
        length_nose_to_tail_cm=40,
        age_weeks=30,
    )
    refused = api.screen_animal_record(on_checked["id"], workbench.acceptance())
    validate_error(refused, ApiErrorId.ROUTING_NOT_PERMITTED_FOR_BREED, 422)
    assert_animal_state(workbench.read_animal(on_checked["id"]), status="DRAFT")

    cargo = workbench.create_reservation(routing_type="CARGO")
    on_cargo = workbench.create_animal(
        cargo["id"],
        species["id"],
        container["id"],
        animal_name="Sunny",
        breed_name="Iguana",
        declared_weight_kg=6,
        height_at_shoulder_cm=20,
        length_nose_to_tail_cm=40,
        age_weeks=30,
    )
    screened = validate_success(
        api.screen_animal_record(on_cargo["id"], workbench.acceptance())
    )
    assert_animal_state(screened, status="SCREENED")


def test_cabin_acceptance_above_species_cabin_weight_rejected(
    api, workbench, catalog, primary_leg
):
    """Acceptance re-runs the cabin weight gate against the measured weight, so a
    booking that passed screening on its declared weight can still be refused.

    PRD §3.7: "Acceptance also re-runs the two weight gates against the measured
    weight rather than the declared one: a matching `WEIGHT_CAPPED` breed
    restriction's `max_weight_kg` must still be respected
    (`ERR_BREED_WEIGHT_CAP_EXCEEDED`), and on `CABIN` routing the gross weight must
    be at most the species profile's `max_cabin_weight_kg`
    (`ERR_CABIN_WEIGHT_EXCEEDED`)."

    Design: Corner/validations/cabin_acceptance_above_species_cabin_weight_rejected
    """
    cabin_container = workbench.create_container(
        model_code="CABIN-S",
        interior_length_cm=35,
        interior_width_cm=25,
        interior_height_cm=28,
        tare_weight_kg=2,
        ventilation_area_pct=10,
        ventilated_side_count=2,
        wheels_removable=True,
        cabin_eligible=True,
    )
    leg = primary_leg()
    reservation = workbench.create_reservation(
        passenger_name="Ho", contact_email="ho@example.com", routing_type="CABIN"
    )
    animal = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        cabin_container["id"],
        animal_name="Pip",
        breed_name="Terrier",
        declared_weight_kg=8,
        height_at_shoulder_cm=20,
        length_nose_to_tail_cm=30,
        age_weeks=52,
    )
    workbench.screen_animal(animal["id"])
    segment = workbench.create_segment(
        animal["id"], leg["id"], routing_type="CABIN", sequence_index=1
    )
    workbench.verified_document(animal["id"])
    workbench.mark_travel_ready(animal["id"])
    workbench.verify_compliance(reservation["id"])
    workbench.confirm_reservation(reservation["id"])

    workbench.amend_animal(animal["id"], measured_weight_kg=15)
    refused = api.accept_segment_assignment(
        segment["id"], workbench.acceptance(SECOND_ACCEPTANCE_AGENT_ID)
    )
    validate_error(refused, ApiErrorId.CABIN_WEIGHT_EXCEEDED, 422)

    assert_segment_state(
        workbench.read_segment(segment["id"]),
        status="RESERVED",
        fee_variant="PROVISIONAL_AT_RESERVATION",
    )
    assert_animal_state(
        workbench.read_animal(animal["id"]),
        status="TRAVEL_READY",
        container_compliance_state="COMPLIANT",
    )
    assert_flight_leg_state(workbench.read_leg(leg["id"]), booked_cabin_count=1)

    workbench.amend_animal(animal["id"], measured_weight_kg=10)
    accepted = validate_success(
        api.accept_segment_assignment(
            segment["id"], workbench.acceptance(SECOND_ACCEPTANCE_AGENT_ID)
        )
    )
    assert_segment_state(
        accepted, status="ACCEPTED", fee_variant="FINAL_AT_ACCEPTANCE"
    )


def test_animal_record_put_amends_declared_weight_and_resets_compliance(
    api, workbench, screened_booking
):
    """Amending the declared weight invalidates the container evaluation, while
    amending only the measured weight leaves it standing.

    PRD §3.4: "When the amendment changes `container_model_id` or
    `declared_weight_kg`, the animal's `container_compliance_state` resets to
    `UNEVALUATED` and its `deficiency_codes` are cleared, which means the animal
    must be screened again before it can be marked travel-ready."

    Design: Corner/endpoints/animal_record_put_amends_declared_weight_and_resets_compliance
    """
    state = screened_booking()

    amended = validate_success(
        api.update_animal_record(
            state["animal_id"], {"declared_weight_kg": 30}, workbench.agent()
        )
    )
    assert amended["declared_weight_kg"] == 30
    assert amended["animal_kind"] == "PET"
    assert amended["measured_weight_kg"] is None
    assert amended["version"] == 3
    assert_animal_state(
        amended,
        status="SCREENED",
        container_compliance_state="UNEVALUATED",
        deficiency_codes=[],
    )

    second = workbench.create_animal(
        state["reservation_id"],
        state["catalog"]["species_id"],
        state["catalog"]["container_id"],
        animal_name="Taro",
    )
    workbench.screen_animal(second["id"])
    measured_only = validate_success(
        api.update_animal_record(
            second["id"], {"measured_weight_kg": 21.4}, workbench.acceptance()
        )
    )
    assert measured_only["measured_weight_kg"] == 21.4
    assert_animal_state(
        measured_only, status="SCREENED", container_compliance_state="COMPLIANT"
    )


def test_container_requirement_matrix_emits_ordered_deficiency_codes(
    api, workbench, catalog
):
    """Four independent requirement thresholds fail at once, and the codes are
    appended in the normative order rather than in any discovery order.

    PRD §3.4: "The evaluation then appends deficiency codes to `deficiency_codes`
    in **exactly this order**, skipping any test that does not fail. If the
    container model's `interior_height_cm` is strictly less than the required
    height, it appends `HEIGHT`. If its `interior_length_cm` is strictly less than
    the required length, it appends `LENGTH`. If its `ventilation_area_pct` is
    strictly less than the required ventilation percentage, it appends `VENT_PCT`.
    If its `ventilated_side_count` is strictly less than the required number of
    ventilated sides, it appends `VENT_SIDES`."

    Design: Difficulty/combinatorial_formula/container_requirement_matrix_emits_ordered_deficiency_codes
    """
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        animal_name="Bruno",
        breed_name="Mastiff",
        declared_weight_kg=30,
        height_at_shoulder_cm=45,
        length_nose_to_tail_cm=60,
        age_weeks=80,
    )

    screened = validate_success(
        api.screen_animal_record(animal["id"], workbench.acceptance())
    )
    assert_animal_state(
        screened,
        status="SCREENED",
        container_compliance_state="DEFICIENT",
        deficiency_codes=["HEIGHT", "LENGTH", "VENT_PCT", "VENT_SIDES"],
        chargeable_weight_kg=37,
    )


def test_container_requirement_matrix_deficiency_blocks_promotion(
    api, workbench, catalog
):
    """The same four-code matrix gates promotion, and the persisted list carries no
    routing-derived code on a checked booking.

    PRD §3.4: "When the resulting list is empty the animal's
    `container_compliance_state` becomes `COMPLIANT`; when it holds at least one
    code the state becomes `DEFICIENT`. Note that `interior_width_cm` constrains no
    deficiency code directly — it enters the picture only through the volumetric
    weight in the fee calculation."

    Design: Difficulty/combinatorial_formula/container_requirement_matrix_emits_ordered_deficiency_codes
    """
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        animal_name="Bruno",
        breed_name="Mastiff",
        declared_weight_kg=30,
        height_at_shoulder_cm=45,
        length_nose_to_tail_cm=60,
        age_weeks=80,
    )
    workbench.screen_animal(animal["id"])

    refused = api.mark_animal_record_travel_ready(
        animal["id"], workbench.acceptance()
    )
    validate_error(refused, ApiErrorId.CONTAINER_NON_COMPLIANT, 422)

    stored = workbench.read_animal(animal["id"])
    assert_animal_state(
        stored,
        status="SCREENED",
        container_compliance_state="DEFICIENT",
        deficiency_codes=["HEIGHT", "LENGTH", "VENT_PCT", "VENT_SIDES"],
        chargeable_weight_kg=37,
    )
    for routing_code in ("GROSS_WEIGHT", "CABIN_DIM", "WHEELS"):
        assert routing_code not in stored["deficiency_codes"]
