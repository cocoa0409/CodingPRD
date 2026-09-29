"""Eleven unresolvable reads, seven different codes, and the one gate above them.

Each entity collection owns its own not-found identifier while the three
catalogue collections deliberately share the generic reference code. Above all of
them sits the header gate, whose three distinct causes all answer 401 — including
the one that is easy to miss, a recognised role arriving without a user id.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_CABINET_NOT_FOUND,
    ERR_CASE_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_MODULE_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_REVISION_NOT_FOUND,
    ERR_RUN_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_VISIT_NOT_FOUND,
)
from test_helpers.assertions import assert_page_meta
from test_helpers.test_users import (
    USER_PLANT_ADMIN,
    make_field_engineer_headers,
    make_headers,
)

#: An id that resolves to nothing in any collection, presented by a caller whose
#: own identity is equally unknown to the crew register.
UNKNOWN_CREW_ID = "crew-unknown"

#: A role name that is not one of the seven the service declares.
UNDECLARED_ROLE = "PlantOperator"

#: A body that would fail the shape rung if the header gate ever let it through.
MALFORMED_MODEL_BODY = {"name": "Nope", "pixel_pitch_mm": "not-a-number"}


def _error_body(response):
    """The error payload, so both of its declared fields can be inspected."""
    return response.json()["data"]


class TestEveryCollectionOwnsItsNotFoundCode:
    """Eight entity reads answer with eight collection-specific identifiers."""

    def test_each_entity_read_names_its_own_collection(self, plant):
        """A referenced `project_id`, whether in a path or a body, resolves to a
        project — otherwise `ERR_PROJECT_NOT_FOUND`. A referenced `module_id`, in
        path or body, resolves — otherwise `ERR_MODULE_NOT_FOUND`. A referenced
        `service_case_id` resolves — otherwise `ERR_CASE_NOT_FOUND`.

        Design: Corner/errors/every_collection_reports_its_own_not_found_code
        """
        validate_error(
            plant.api.get_project(NON_EXISTENT_UUID, plant.engineer),
            ERR_PROJECT_NOT_FOUND,
            404,
        )
        validate_error(
            plant.api.get_drawing_revision(NON_EXISTENT_UUID, plant.engineer),
            ERR_REVISION_NOT_FOUND,
            404,
        )
        validate_error(
            plant.api.get_cabinet(NON_EXISTENT_UUID, plant.operator),
            ERR_CABINET_NOT_FOUND,
            404,
        )
        validate_error(
            plant.api.get_module(NON_EXISTENT_UUID, plant.operator),
            ERR_MODULE_NOT_FOUND,
            404,
        )
        validate_error(
            plant.api.get_burn_in_run(NON_EXISTENT_UUID, plant.qa),
            ERR_RUN_NOT_FOUND,
            404,
        )
        validate_error(
            plant.api.get_commissioning_visit(
                NON_EXISTENT_UUID, make_field_engineer_headers(UNKNOWN_CREW_ID)
            ),
            ERR_VISIT_NOT_FOUND,
            404,
        )
        validate_error(
            plant.api.get_service_contract(NON_EXISTENT_UUID, plant.service),
            ERR_CONTRACT_NOT_FOUND,
            404,
        )
        validate_error(
            plant.api.get_service_case(NON_EXISTENT_UUID, plant.service),
            ERR_CASE_NOT_FOUND,
            404,
        )

    def test_the_three_catalogue_reads_share_the_generic_reference_code(self, plant):
        """For the three catalogue parents — a `display_model_id`, a
        `burn_in_chamber_id` or a `commissioning_crew_id` — a missing target yields
        `ERR_REFERENCE_NOT_FOUND`. This rung guards project creation, module
        registration, burn-in scheduling, visit booking, and the three single-record
        catalogue reads.

        Design: Corner/errors/every_collection_reports_its_own_not_found_code
        """
        model_read = plant.api.get_display_model(NON_EXISTENT_UUID, plant.admin)
        chamber_read = plant.api.get_burn_in_chamber(NON_EXISTENT_UUID, plant.admin)
        crew_read = plant.api.get_commissioning_crew(NON_EXISTENT_UUID, plant.admin)

        validate_error(model_read, ERR_REFERENCE_NOT_FOUND, 404)
        validate_error(chamber_read, ERR_REFERENCE_NOT_FOUND, 404)
        validate_error(crew_read, ERR_REFERENCE_NOT_FOUND, 404)
        for response in (model_read, chamber_read, crew_read):
            body = _error_body(response)
            assert body["error_id"] == ERR_REFERENCE_NOT_FOUND
            assert isinstance(body.get("message"), str) and body["message"], (
                f"an error body must carry a message, got {body!r}"
            )


class TestHeaderGateOutranksEverything:
    """Three causes, one code, and it answers before role or shape is read."""

    def test_a_missing_role_a_missing_user_and_an_undeclared_role_are_all_401(self, plant):
        """Every request to the service carries two headers. `X-User-ID` identifies
        the acting user or crew, and `X-User-Role` names the role under which they
        act. If either header is absent, or if `X-User-Role` is not one of the seven
        role names defined below, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401).

        Design: Corner/errors/missing_or_unknown_auth_headers_are_unauthenticated
        """
        no_role = plant.api.list_display_models({"X-User-ID": USER_PLANT_ADMIN})
        no_user = plant.api.list_display_models({"X-User-Role": "PlantAdmin"})
        undeclared_role = plant.api.list_display_models(
            make_headers(USER_PLANT_ADMIN, UNDECLARED_ROLE)
        )

        validate_error(no_role, ERR_UNAUTHENTICATED, 401)
        validate_error(no_user, ERR_UNAUTHENTICATED, 401)
        validate_error(undeclared_role, ERR_UNAUTHENTICATED, 401)

    def test_the_gate_answers_before_the_role_check_and_the_shape_check(self, plant):
        """Requests are screened in a fixed order, and the **first** rule that a
        request violates decides the response. Both authentication headers are
        present and `X-User-Role` is one of the seven declared roles — otherwise
        `ERR_UNAUTHENTICATED`. Applies to every operation.

        Design: Corner/errors/missing_or_unknown_auth_headers_are_unauthenticated
        """
        response = plant.api.create_display_model(
            MALFORMED_MODEL_BODY, {"X-User-ID": USER_PLANT_ADMIN}
        )

        validate_error(response, ERR_UNAUTHENTICATED, 401)
        rows, meta = validate_paginated(plant.api.list_display_models(plant.admin))
        assert rows == []
        assert_page_meta(meta, total_count=0, has_more=False)
