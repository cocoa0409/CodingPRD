"""The top of the screening ladder: authentication order, shape, then existence.

The four rungs exercised here all sit above the domain rules. A forbidden role
answers before any id is resolved, a malformed body answers before the first
database read, an unassigned crew answers before the visit's own state, and the
per-operation state sets that guard module work are checked for their exact
membership rather than assumed nested.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CABINETS_NOT_MOUNTED,
    ERR_CREW_NOT_ASSIGNED,
    ERR_INVALID_MODULE_STATE,
    ERR_INVALID_VISIT_STATE,
    ERR_PROJECT_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_VALIDATION_FAILED,
)
from test_helpers.assertions import (
    assert_module_fields,
    assert_page_meta,
    assert_project_fields,
    assert_version,
    assert_visit_fields,
    ids_of,
)
from test_helpers.constants import (
    MODULE_MANUFACTURED,
    MODULE_PIXEL_TESTED,
    PRODUCTION_NOT_STARTED,
    REVISION_SUBMITTED,
    VISIT_SCHEDULED,
    VISIT_WINDOW_END,
    VISIT_WINDOW_START,
)
from test_helpers.factories import (
    calibrate_payload,
    commissioning_visit_payload,
    drawing_revision_payload,
    pixel_test_payload,
    project_payload,
)
from test_helpers.test_users import make_field_engineer_headers

#: A page size one past the declared ceiling, and an offset one below the floor.
OVER_LARGE_LIMIT = 101
NEGATIVE_OFFSET = -1

#: An install environment that is not a member of the declared enum.
UNKNOWN_INSTALL_ENVIRONMENT = "AIRPORT"

#: The east-coast crew that is never assigned to the visit under test.
EAST_REGION_CODE = "NAE"


class TestRequestShapeAboveExistence:
    """One rule, five surfaces, and it answers before any id is looked up."""

    def test_all_four_body_and_query_surfaces_answer_with_the_same_code(self, plant):
        """The request body and query shape are well formed: required fields
        present, JSON types correct, enum members recognised, numeric ranges
        honoured, any `window_end` strictly later than its `window_start`, `limit`
        within 1 to 100, and `offset` not negative — otherwise
        `ERR_VALIDATION_FAILED`.

        Design: Corner/validations/request_shape_is_checked_before_anything_resolves
        """
        model = plant.register_model()
        missing_name = project_payload(model["id"])
        missing_name.pop("customer_name")

        unknown_enum = plant.api.create_project(
            project_payload(
                model["id"], install_environment=UNKNOWN_INSTALL_ENVIRONMENT
            ),
            plant.engineer,
        )
        omitted_field = plant.api.create_project(missing_name, plant.engineer)
        over_limit = plant.api.list_projects(plant.engineer, {"limit": OVER_LARGE_LIMIT})
        under_offset = plant.api.list_projects(
            plant.engineer, {"offset": NEGATIVE_OFFSET}
        )

        validate_error(unknown_enum, ERR_VALIDATION_FAILED, 400)
        validate_error(omitted_field, ERR_VALIDATION_FAILED, 400)
        validate_error(over_limit, ERR_VALIDATION_FAILED, 400)
        validate_error(under_offset, ERR_VALIDATION_FAILED, 400)
        projects, meta = validate_paginated(plant.api.list_projects(plant.engineer))
        assert projects == []
        assert_page_meta(meta, total_count=0, has_more=False)

    def test_an_empty_window_answers_before_its_invented_references_resolve(self, plant):
        """Requests are screened in a fixed order, and the **first** rule that a
        request violates decides the response. Screening stops there: no later
        rule is consulted, no partial write is kept, and nothing at all is
        persisted.

        Design: Corner/validations/request_shape_is_checked_before_anything_resolves
        """
        empty_window = commissioning_visit_payload(
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            window_start=VISIT_WINDOW_START,
            window_end=VISIT_WINDOW_START,
        )

        response = plant.api.create_commissioning_visit(empty_window, plant.admin)

        validate_error(response, ERR_VALIDATION_FAILED, 400)
        visits, meta = validate_paginated(
            plant.api.list_commissioning_visits(plant.admin)
        )
        assert visits == []
        assert_page_meta(meta, total_count=0, has_more=False)

    def test_a_bad_enum_beats_a_missing_display_model(self, plant):
        """Every referenced catalogue record exists. Path-templated ids are
        resolved **left to right** and the first unresolved id decides the answer.
        For the three catalogue parents — a `display_model_id`, a
        `burn_in_chamber_id` or a `commissioning_crew_id` — a missing target
        yields `ERR_REFERENCE_NOT_FOUND`.

        Design: Corner/validations/request_shape_outranks_reference_existence
        """
        model = plant.register_model()

        malformed = plant.api.create_project(
            project_payload(
                NON_EXISTENT_UUID, install_environment=UNKNOWN_INSTALL_ENVIRONMENT
            ),
            plant.engineer,
        )
        unresolvable = plant.api.create_project(
            project_payload(NON_EXISTENT_UUID), plant.engineer
        )
        accepted = plant.api.create_project(
            project_payload(model["id"]), plant.engineer
        )

        validate_error(malformed, ERR_VALIDATION_FAILED, 400)
        validate_error(unresolvable, ERR_REFERENCE_NOT_FOUND, 404)
        created = validate_success(accepted, 201)
        assert_project_fields(created, production_state=PRODUCTION_NOT_STARTED)
        projects, meta = validate_paginated(plant.api.list_projects(plant.engineer))
        assert ids_of(projects) == [created["id"]]
        assert_page_meta(meta, total_count=1, has_more=False)


class TestAuthorizationAboveExistence:
    """A forbidden caller learns nothing about which projects exist."""

    def test_a_forbidden_role_hides_the_unresolvable_project(self, plant):
        """The authenticated role is permitted to invoke the target operation —
        otherwise `ERR_UNAUTHORIZED`. Applies to every operation.

        Design: Corner/validations/unauthorized_outranks_every_existence_check
        """
        model = plant.register_model()
        project = plant.create_project(model["id"])
        invented = drawing_revision_payload(NON_EXISTENT_UUID)

        forbidden = plant.api.create_drawing_revision(invented, plant.operator)
        permitted = plant.api.create_drawing_revision(invented, plant.engineer)
        real = plant.api.create_drawing_revision(
            drawing_revision_payload(project["id"]), plant.engineer
        )

        validate_error(forbidden, ERR_UNAUTHORIZED, 403)
        validate_error(permitted, ERR_PROJECT_NOT_FOUND, 404)
        revision = validate_success(real, 201)
        assert revision["revision_number"] == 1
        assert revision["revision_state"] == REVISION_SUBMITTED
        rows, meta = validate_paginated(
            plant.api.list_drawing_revisions(
                plant.engineer, {"project_id": project["id"]}
            )
        )
        assert ids_of(rows) == [revision["id"]]
        assert_page_meta(meta, total_count=1, has_more=False)


class TestCrewAssignmentAboveVisitStateAndMounting:
    """Three rungs are violated at once and the answer walks down them in order."""

    def _scheduled_visit_on_an_unbuilt_wall(self, plant):
        model = plant.register_model()
        project = plant.create_project(model["id"])
        booked_crew = plant.register_crew()
        other_crew = plant.register_crew(name="Crew East", region_code=EAST_REGION_CODE)
        visit = plant.book_visit(
            project["id"],
            booked_crew["id"],
            window_start=VISIT_WINDOW_START,
            window_end=VISIT_WINDOW_END,
        )
        return project, booked_crew, other_crew, visit

    def test_an_unassigned_crew_is_refused_before_the_visit_state_is_read(self, plant):
        """A `FieldEngineer` acting on a commissioning visit presents an
        `X-User-ID` equal to that visit's `commissioning_crew_id` — otherwise
        `ERR_CREW_NOT_ASSIGNED`. This rung guards arrival, on-site calibration and
        sign-off.

        Design: Corner/validations/crew_assignment_outranks_visit_state_and_mounting
        """
        project, _, other_crew, visit = self._scheduled_visit_on_an_unbuilt_wall(plant)

        response = plant.api.sign_off_visit(
            visit["id"], make_field_engineer_headers(other_crew["id"])
        )

        validate_error(response, ERR_CREW_NOT_ASSIGNED, 403)
        assert_project_fields(
            plant.project(project["id"]), production_state=PRODUCTION_NOT_STARTED
        )

    def test_the_booked_crew_then_hears_about_state_before_mounting(self, plant):
        """The visit's `visit_state` permits the operation: `SCHEDULED` for
        arrival, `ON_SITE` for on-site calibration, `CALIBRATED` for sign-off —
        otherwise `ERR_INVALID_VISIT_STATE`.

        Design: Corner/validations/crew_assignment_outranks_visit_state_and_mounting
        """
        project, booked_crew, _, visit = self._scheduled_visit_on_an_unbuilt_wall(plant)

        response = plant.api.sign_off_visit(
            visit["id"], make_field_engineer_headers(booked_crew["id"])
        )

        validate_error(response, ERR_INVALID_VISIT_STATE, 409)
        assert_project_fields(
            plant.project(project["id"]), production_state=PRODUCTION_NOT_STARTED
        )

    def test_only_a_state_satisfying_call_reaches_the_mounting_rung(self, plant):
        """The project's `production_state` is `INSTALLED`, meaning every cabinet
        of the project is `MOUNTED`, before a crew may go on site or sign off —
        otherwise `ERR_CABINETS_NOT_MOUNTED`.

        Design: Corner/validations/crew_assignment_outranks_visit_state_and_mounting
        """
        project, booked_crew, other_crew, visit = self._scheduled_visit_on_an_unbuilt_wall(
            plant
        )
        crew_headers = make_field_engineer_headers(booked_crew["id"])
        validate_error(
            plant.api.sign_off_visit(
                visit["id"], make_field_engineer_headers(other_crew["id"])
            ),
            ERR_CREW_NOT_ASSIGNED,
            403,
        )
        validate_error(
            plant.api.sign_off_visit(visit["id"], crew_headers),
            ERR_INVALID_VISIT_STATE,
            409,
        )

        response = plant.api.arrive_at_visit(visit["id"], crew_headers)

        validate_error(response, ERR_CABINETS_NOT_MOUNTED, 409)
        untouched = plant.visit(visit["id"])
        assert_visit_fields(
            untouched,
            visit_state=VISIT_SCHEDULED,
            commissioning_crew_id=booked_crew["id"],
        )
        assert untouched["arrived_at"] is None
        assert_version(untouched, 1, "visit")
        assert_project_fields(
            plant.project(project["id"]), production_state=PRODUCTION_NOT_STARTED
        )


class TestModuleOperationStateSets:
    """The pixel-test set and the calibrate set overlap without nesting."""

    def test_a_manufactured_module_cannot_be_calibrated(self, plant):
        """Calibration is recorded with three measurements —
        `measured_brightness_nits`, `measured_color_x` and `measured_color_y` —
        and is available while the module is `PIXEL_TESTED` or `REWORK`, with any
        other state refused as `ERR_INVALID_MODULE_STATE`.

        Design: Corner/validations/module_operations_require_the_right_module_state
        """
        model = plant.register_model()
        module = plant.register_module(model["id"], "M-STATE")

        response = plant.api.calibrate_module(
            module["id"], calibrate_payload(), plant.operator
        )

        validate_error(response, ERR_INVALID_MODULE_STATE, 409)
        untouched = plant.module(module["id"])
        assert_module_fields(
            untouched,
            module_state=MODULE_MANUFACTURED,
            rework_cycles=0,
            measured_brightness_nits=None,
            color_bin=None,
        )
        assert untouched["measured_color_x"] is None
        assert untouched["measured_color_y"] is None

    def test_a_pixel_tested_module_cannot_be_pixel_tested_again(self, plant):
        """The operation is available while the module is `MANUFACTURED` or
        `REWORK`; in any other state it is refused with
        `ERR_INVALID_MODULE_STATE`.

        Design: Corner/validations/module_operations_require_the_right_module_state
        """
        model = plant.register_model()
        module = plant.register_module(model["id"], "M-STATE")
        tested = plant.pixel_test(module["id"])
        assert_module_fields(tested, module_state=MODULE_PIXEL_TESTED, rework_cycles=0)

        response = plant.api.pixel_test_module(
            module["id"], pixel_test_payload(1, 1), plant.operator
        )

        validate_error(response, ERR_INVALID_MODULE_STATE, 409)
        assert_module_fields(
            plant.module(module["id"]),
            module_state=MODULE_PIXEL_TESTED,
            rework_cycles=0,
        )
