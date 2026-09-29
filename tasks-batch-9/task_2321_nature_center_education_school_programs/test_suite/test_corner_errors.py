"""Not-found codes for unresolvable identifiers in the Nature Center Education API.

Each case aims a well-formed request at an identifier that was never issued, so the
only thing that can decide the answer is the entity the identifier addresses.
"""

import pytest

from test_helpers import (
    BC,
    CS,
    CS_ASSESSOR,
    DEFAULT_CLOCK,
    ED,
    GO,
    SM,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assign_resources_payload,
    create_aid_application_payload,
    create_animal_payload,
    create_booking,
    create_booking_payload,
    create_fund,
    create_permit,
    create_program_offering_payload,
    create_published_offering,
    create_school,
    make_teacher_contact_headers,
    refresh_booking,
    set_clock,
    validate_error,
)

# --- Unknown path identifiers -------------------------------------------------------

_PATH_ID_CASES = [
    (
        "program offering",
        ApiErrorId.ERR_OFFERING_NOT_FOUND,
        lambda api, ctx: api.get_program_offering(NON_EXISTENT_UUID, CS),
    ),
    (
        "curriculum material",
        ApiErrorId.ERR_MATERIAL_NOT_FOUND,
        lambda api, ctx: api.publish_curriculum_material(NON_EXISTENT_UUID, CS),
    ),
    (
        "school partner",
        ApiErrorId.ERR_SCHOOL_NOT_FOUND,
        lambda api, ctx: api.get_school(NON_EXISTENT_UUID, BC),
    ),
    (
        "educator",
        ApiErrorId.ERR_EDUCATOR_NOT_FOUND,
        lambda api, ctx: api.get_educator(NON_EXISTENT_UUID, ED),
    ),
    (
        "training record",
        ApiErrorId.ERR_TRAINING_RECORD_NOT_FOUND,
        lambda api, ctx: api.assess_training_record(
            NON_EXISTENT_UUID, {"outcome": "PASS", "score": 88}, CS_ASSESSOR
        ),
    ),
    (
        "permit",
        ApiErrorId.ERR_PERMIT_NOT_FOUND,
        lambda api, ctx: api.get_permit(NON_EXISTENT_UUID, SM),
    ),
    (
        "animal ambassador",
        ApiErrorId.ERR_ANIMAL_NOT_FOUND,
        lambda api, ctx: api.get_animal(NON_EXISTENT_UUID, SM),
    ),
    (
        "trail segment",
        ApiErrorId.ERR_TRAIL_SEGMENT_NOT_FOUND,
        lambda api, ctx: api.get_trail_segment(NON_EXISTENT_UUID, SM),
    ),
    (
        "booking",
        ApiErrorId.ERR_BOOKING_NOT_FOUND,
        lambda api, ctx: api.get_booking(NON_EXISTENT_UUID, BC),
    ),
    (
        "scholarship fund",
        ApiErrorId.ERR_FUND_NOT_FOUND,
        lambda api, ctx: api.get_scholarship_fund(NON_EXISTENT_UUID, GO),
    ),
    (
        "aid application",
        ApiErrorId.ERR_AID_APPLICATION_NOT_FOUND,
        lambda api, ctx: api.get_aid_application(NON_EXISTENT_UUID, GO),
    ),
    (
        "equipment manifest",
        ApiErrorId.ERR_MANIFEST_NOT_FOUND,
        lambda api, ctx: api.advance_equipment_manifest(
            NON_EXISTENT_UUID, {"action": "LOAD"}, BC
        ),
    ),
    (
        "evaluation report",
        ApiErrorId.ERR_EVALUATION_REPORT_NOT_FOUND,
        lambda api, ctx: api.submit_evaluation_report(
            NON_EXISTENT_UUID, ctx["teacher_headers"]
        ),
    ),
]


# --- Unknown body foreign keys ------------------------------------------------------

_BODY_FK_CASES = [
    (
        "booking create names an unknown school",
        ApiErrorId.ERR_SCHOOL_NOT_FOUND,
        lambda api, ctx: api.create_booking(
            create_booking_payload(NON_EXISTENT_UUID, ctx["offering"]["id"]), BC
        ),
    ),
    (
        "booking create names an unknown offering",
        ApiErrorId.ERR_OFFERING_NOT_FOUND,
        lambda api, ctx: api.create_booking(
            create_booking_payload(ctx["school"]["id"], NON_EXISTENT_UUID), BC
        ),
    ),
    (
        "resource assignment names an unknown trail segment",
        ApiErrorId.ERR_TRAIL_SEGMENT_NOT_FOUND,
        lambda api, ctx: api.assign_booking_resources(
            ctx["booking"]["id"],
            assign_resources_payload(
                ctx["booking"]["version"], trail_segment_id=NON_EXISTENT_UUID
            ),
            BC,
        ),
    ),
    (
        "resource assignment names an unknown educator",
        ApiErrorId.ERR_EDUCATOR_NOT_FOUND,
        lambda api, ctx: api.assign_booking_resources(
            ctx["booking"]["id"],
            assign_resources_payload(
                ctx["booking"]["version"], lead_educator_id=NON_EXISTENT_UUID
            ),
            BC,
        ),
    ),
    (
        "resource assignment names an unknown animal",
        ApiErrorId.ERR_ANIMAL_NOT_FOUND,
        lambda api, ctx: api.assign_booking_resources(
            ctx["booking"]["id"],
            assign_resources_payload(
                ctx["booking"]["version"], animal_id=NON_EXISTENT_UUID
            ),
            BC,
        ),
    ),
    (
        "animal registration names an unknown permit",
        ApiErrorId.ERR_PERMIT_NOT_FOUND,
        lambda api, ctx: api.create_animal(
            create_animal_payload(NON_EXISTENT_UUID), SM
        ),
    ),
    (
        "aid application names an unknown fund",
        ApiErrorId.ERR_FUND_NOT_FOUND,
        lambda api, ctx: api.create_aid_application(
            create_aid_application_payload(
                ctx["booking"]["id"], NON_EXISTENT_UUID, 1
            ),
            BC,
        ),
    ),
    (
        "aid application names an unknown booking",
        ApiErrorId.ERR_BOOKING_NOT_FOUND,
        lambda api, ctx: api.create_aid_application(
            create_aid_application_payload(
                NON_EXISTENT_UUID, ctx["fund"]["id"], ctx["fund"]["version"]
            ),
            BC,
        ),
    ),
    (
        "offering create names an unknown rain alternate",
        ApiErrorId.ERR_OFFERING_NOT_FOUND,
        lambda api, ctx: api.create_program_offering(
            create_program_offering_payload(
                title="Storm Day Alternate",
                rain_alternate_for_offering_id=NON_EXISTENT_UUID,
            ),
            CS,
        ),
    ),
]


def _fk_scenario():
    """A published offering, a partner school, an open pool and a fresh booking."""
    set_clock(DEFAULT_CLOCK)
    offering = create_published_offering()
    school = create_school()
    fund = create_fund()
    booking = create_booking(school["id"], offering["id"])
    return {"offering": offering, "school": school, "fund": fund, "booking": booking}


class TestUnknownPathIdentifiers:
    @pytest.mark.parametrize(
        "label,expected_error,call",
        _PATH_ID_CASES,
        ids=[case[0] for case in _PATH_ID_CASES],
    )
    def test_each_unknown_path_id_answers_with_its_owning_entity_code(
        self, api, label, expected_error, call
    ):
        """PRD §2.6: "The thirteen not-found codes map one-to-one onto the thirteen addressable entities: `ERR_OFFERING_NOT_FOUND`, `ERR_MATERIAL_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`, `ERR_EDUCATOR_NOT_FOUND`, `ERR_TRAINING_RECORD_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_TRAIL_SEGMENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FUND_NOT_FOUND`, `ERR_AID_APPLICATION_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND` and `ERR_EVALUATION_REPORT_NOT_FOUND`."

        Design: Corner/errors/each_unknown_path_id_answers_with_its_own_owning_entity_code
        """
        set_clock(DEFAULT_CLOCK)
        school = create_school()
        ctx = {"teacher_headers": make_teacher_contact_headers(school["id"])}

        error = validate_error(call(api, ctx), expected_error.value)
        assert error["message"].strip()

    def test_an_id_belonging_to_another_entity_still_answers_the_addressed_entity(
        self, api
    ):
        """PRD §2.9: "Every identifier in the path resolves, left to right, to the corresponding not-found code (404) as described in §2.6."

        Design: Corner/errors/each_unknown_path_id_answers_with_its_own_owning_entity_code
        """
        set_clock(DEFAULT_CLOCK)
        permit = create_permit()

        validate_error(
            api.get_animal(permit["id"], SM), ApiErrorId.ERR_ANIMAL_NOT_FOUND.value
        )
        validate_error(
            api.get_trail_segment(permit["id"], SM),
            ApiErrorId.ERR_TRAIL_SEGMENT_NOT_FOUND.value,
        )


class TestUnknownBodyForeignKeys:
    @pytest.mark.parametrize(
        "label,expected_error,call",
        _BODY_FK_CASES,
        ids=[case[0] for case in _BODY_FK_CASES],
    )
    def test_each_unknown_body_foreign_key_answers_the_referenced_entity_code(
        self, api, label, expected_error, call
    ):
        """PRD §2.9: "Every foreign key in the body resolves, in the order given in §2.6, to the corresponding not-found code (404)."

        Design: Corner/errors/each_unknown_body_foreign_key_answers_with_the_referenced_entity_code
        """
        ctx = _fk_scenario()

        error = validate_error(call(api, ctx), expected_error.value)
        assert error["message"].strip()

    def test_the_first_unresolvable_body_key_in_the_fixed_order_wins(self, api):
        """PRD §2.6: "The first of these that fails to resolve determines the 404 code."

        Design: Corner/errors/each_unknown_body_foreign_key_answers_with_the_referenced_entity_code
        """
        ctx = _fk_scenario()

        validate_error(
            api.create_booking(
                create_booking_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), BC
            ),
            ApiErrorId.ERR_SCHOOL_NOT_FOUND.value,
        )
        validate_error(
            api.assign_booking_resources(
                ctx["booking"]["id"],
                assign_resources_payload(
                    ctx["booking"]["version"],
                    trail_segment_id=NON_EXISTENT_UUID,
                    lead_educator_id=NON_EXISTENT_UUID,
                    animal_id=NON_EXISTENT_UUID,
                ),
                BC,
            ),
            ApiErrorId.ERR_TRAIL_SEGMENT_NOT_FOUND.value,
        )

    def test_a_body_key_that_fails_to_resolve_leaves_the_booking_untouched(self, api):
        """PRD §2.6: "Foreign keys carried in a request body are resolved after the path, and they too are resolved in a fixed order rather than all at once: `school_id` first, then `offering_id`, then `trail_segment_id`, then `lead_educator_id`, then `animal_id`, then `fund_id`, then `booking_id`."

        Design: Corner/errors/each_unknown_body_foreign_key_answers_with_the_referenced_entity_code
        """
        ctx = _fk_scenario()
        booking = ctx["booking"]

        validate_error(
            api.assign_booking_resources(
                booking["id"],
                assign_resources_payload(
                    booking["version"], lead_educator_id=NON_EXISTENT_UUID
                ),
                BC,
            ),
            ApiErrorId.ERR_EDUCATOR_NOT_FOUND.value,
        )

        after = refresh_booking(booking["id"])
        assert after.get("lead_educator_id") is None
        assert after["version"] == booking["version"]
        assert after["delivery_status"] == "REQUESTED"
