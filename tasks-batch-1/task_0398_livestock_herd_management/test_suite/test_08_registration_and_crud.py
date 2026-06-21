"""Animal registration, CRUD, listing, pagination, mortality rate, and trace chain."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    create_herd,
    create_animal,
    record_mortality,
    plan_and_apply_movement,
    create_pasture,
    create_weighed_animal,
    assert_animal,
    ApiErrorId,
    TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAnimalRegistration:
    def test_create_animal_returns_201_with_system_fields(self, api):
        """PRD §3.2: "On registration the animal initializes both of its state
        dimensions: `life_status` to `ACTIVE` and `meat_clearance_status` to `CLEAR`.
        Its computed `latest_weight_kg` initializes to the `birth_weight_kg` and stays
        there until a weight record exists."
        PRD §2.4: "an integer `version` that starts at its initial value on creation".

        Design: Corner/entities/create_animal_returns_201_with_system_fields
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        data = validate_success(
            api.create_animal(
                {"herd_id": herd["id"], "ear_tag": "Z001", "sex": "FEMALE",
                 "birth_date": "2026-01-01", "birth_weight_kg": 38.0},
                HM,
            ),
            expected_status=201,
        )
        assert_animal(data)
        assert data["version"] == 1
        assert data["life_status"] == "ACTIVE"
        assert data["meat_clearance_status"] == "CLEAR"
        assert data["latest_weight_kg"] == 38.0

    def test_client_supplied_system_fields_ignored(self, api):
        """PRD §2.4: "Every persisted resource carries a server-minted `id` ... and an
        integer `version` that starts at its initial value on creation".

        Design: Corner/entities/animal_id_input_ignored_on_create
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        data = validate_success(
            api.create_animal(
                {"herd_id": herd["id"], "ear_tag": "Z040", "sex": "STEER",
                 "birth_date": "2026-01-01", "birth_weight_kg": 40.0,
                 "id": "ignore-me", "version": 99, "life_status": "SOLD"},
                HM,
            ),
            expected_status=201,
        )
        assert data["version"] == 1
        assert data["life_status"] == "ACTIVE"

    def test_get_animal_not_found(self, api):
        """PRD §2.5: "the system validates the path identifiers left to right and
        rejects the request with `ERR_NOT_FOUND` at the first identifier that does not
        resolve to an existing resource."

        Design: Corner/entities/get_animal_not_found_returns_404
        """
        set_clock("2026-04-01T00:00:00Z")
        resp = api.get_animal("00000000-0000-4000-8000-000000000999", HM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_animal_missing_birth_weight_rejected(self, api):
        """PRD §3.2: "a `birth_date` (an ISO 8601 date that may not be later than the
        current clock date), and a recorded `birth_weight_kg` greater than zero."
        PRD §2.5: "then request-shape validation of required fields, types, enum
        domains, and numeric ranges (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/create_animal_missing_required_field_returns_422
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        resp = api.create_animal(
            {"herd_id": herd["id"], "ear_tag": "Z010", "sex": "STEER",
             "birth_date": "2026-01-01"},
            HM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_animal_invalid_sex_enum_rejected(self, api):
        """PRD §3.2: "a `sex` that is one of `MALE`, `FEMALE`, or `STEER`".
        PRD §2.5: "then request-shape validation of required fields, types, enum
        domains, and numeric ranges (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/create_animal_invalid_enum_sex_returns_422
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        resp = api.create_animal(
            {"herd_id": herd["id"], "ear_tag": "Z020", "sex": "BULL",
             "birth_date": "2026-01-01", "birth_weight_kg": 40.0},
            HM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_duplicate_ear_tag_within_herd_rejected(self, api):
        """PRD §3.2: "the `ear_tag` must be unique within its herd, so a duplicate ear
        tag inside the same `herd_id` is rejected with `ERR_DUPLICATE_IDENTIFIER`".

        Design: Corner/entities/duplicate_ear_tag_within_herd_returns_409
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        create_animal(herd["id"], sex="STEER", birth_date="2026-01-01", ear_tag="Z030")
        resp = api.create_animal(
            {"herd_id": herd["id"], "ear_tag": "Z030", "sex": "STEER",
             "birth_date": "2026-01-01", "birth_weight_kg": 41.0},
            HM,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)


class TestLifeStatusInvalidTransition:
    def test_reinstate_active_animal_rejected(self, api):
        """PRD §3.3: "Moving a `SUSPENDED` animal back to `ACTIVE` requires that it
        currently be `SUSPENDED` ... If the animal is not in the state the requested
        transition starts from, the request is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/reinstate_active_animal_returns_invalid_state
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        resp = api.set_life_status(animal["id"], {"to_status": "ACTIVE"}, HM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestMortalityRate:
    def test_mortality_rate_one_of_four(self, api):
        """PRD §3.11: "The denominator is the herd's current `active_animal_count` plus
        that death count, approximating the inventory at the window's start. The rate is
        the deaths divided by the denominator, multiplied by 100 and rounded to two
        decimal places".

        Design: Corner/calculations/herd_mortality_rate_one_of_four
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        a0 = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01", ear_tag="K400")
        create_animal(herd["id"], sex="STEER", birth_date="2024-01-01", ear_tag="K401")
        create_animal(herd["id"], sex="STEER", birth_date="2024-01-01", ear_tag="K402")
        create_animal(herd["id"], sex="STEER", birth_date="2024-01-01", ear_tag="K403")
        record_mortality(a0["id"], died_on="2026-03-30", cause="DISEASE")
        herd_after = validate_success(api.get_herd(herd["id"], HM))
        assert herd_after["mortality_rate_pct"] == 25.00
        assert herd_after["active_animal_count"] == 3


class TestListingAndPagination:
    def test_list_animals_filtered_by_herd(self, api):
        """PRD §3.2: "Animals can be listed and filtered by their `herd_id`,
        `dam_animal_id`, `sire_animal_id`, or `current_pasture_id`".
        PRD §2.3: "where `total_count` is the count of matching items before the
        limit/offset window is applied".

        Design: Corner/endpoints/list_animals_filtered_by_herd_paginated
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        create_animal(herd["id"], sex="STEER", birth_date="2024-01-01", ear_tag="E020")
        create_animal(herd["id"], sex="STEER", birth_date="2024-01-01", ear_tag="E021")
        resp = api.list_animals(HM, params={"herd_id": herd["id"], "limit": 10, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2

    def test_pagination_limit_out_of_range_rejected(self, api):
        """PRD §2.3: "A `limit` outside the range of 1 through 100, or a negative
        `offset`, is rejected with `ERR_VALIDATION_LIMIT`."

        Design: Corner/validations/pagination_limit_out_of_range_returns_422
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        create_animal(herd["id"], sex="STEER", birth_date="2024-01-01", ear_tag="V060")
        resp = api.list_animals(HM, params={"herd_id": herd["id"], "limit": 500})
        validate_error(resp, ApiErrorId.ERR_VALIDATION_LIMIT.value)


class TestTraceChain:
    def test_trace_chain_ordered_birth_then_movement(self, api):
        """PRD §3.12: "The chain for an animal is returned ordered by `occurred_on`
        ascending and then by `created_at` ascending".
        PRD §3.2: "Creating an animal ... appends a `BIRTH` event to the animal's
        trace chain."
        PRD §3.8: "On a successful application the movement ... appends a `MOVEMENT`
        trace event."

        Design: Corner/endpoints/trace_chain_ordered_for_animal
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen = create_pasture(kind="PEN", capacity_au=10)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20",
                                       ear_tag="E010")
        plan_and_apply_movement(animal["id"], pen["id"], "2026-03-21T00:00:00Z")
        resp = api.get_trace(animal["id"], AUDITOR)
        data, _meta = validate_paginated(resp)
        assert data[0]["event_type"] == "BIRTH"
        assert data[1]["event_type"] == "MOVEMENT"
