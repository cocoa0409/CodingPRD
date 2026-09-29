"""The role ring, walked in both directions.

Seven writes are attempted by the seven wrong roles, including the two that would
also break a business rule further down the ladder, and then the two positives
that keep the matrix honest: the one shared write, and reads by everybody.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_UNAUTHORIZED
from test_helpers.assertions import assert_page_meta, assert_version, ids_of
from test_helpers.constants import (
    CABINET_PLANNED,
    REVISION_SUBMITTED,
    VISIT_SCHEDULED,
    VISIT_WINDOW_END,
    VISIT_WINDOW_START,
)
from test_helpers.factories import (
    commissioning_visit_payload,
    module_payload,
    project_payload,
    review_payload,
    service_contract_payload,
)
from test_helpers.test_users import (
    make_field_engineer_headers,
    make_plant_admin_headers,
)

#: The second on-site window, a whole day clear of the first, so the crew is never
#: double-booked by the two bookings this file makes.
SECOND_WINDOW_START = "2026-08-06T08:00:00.000Z"
SECOND_WINDOW_END = "2026-08-06T16:00:00.000Z"

#: An instant a PlantAdmin could legitimately move the clock to, offered here by a
#: role that may not.
ATTEMPTED_CLOCK_INSTANT = "2027-01-01T00:00:00.000Z"

#: A GOLD holding at the tier's floor, so nothing but the role can be at fault.
GOLD_SPARE_PCT_BP = 300
GOLD_TERM_MONTHS = 60

#: Exactly one product family is registered, so every role's catalogue read sees
#: the same single row.
CATALOGUE_SIZE = 1


def _two_projects_one_approved_and_one_awaiting_review(plant):
    """Project A with an approved package and a planned cabinet, project B waiting.

    Project B's only revision is still `SUBMITTED`, and it was submitted by the
    same design engineer who will later try to review it.
    """
    model = plant.register_model()
    crew = plant.register_crew()

    project_a = plant.create_project(model["id"])
    revision_a = plant.submit_revision(project_a["id"])
    plant.review_revision(revision_a["id"], "APPROVE")
    cabinet = plant.plan_cabinet(project_a["id"])

    project_b = plant.create_project(model["id"], customer_name="Role Wall B")
    revision_b = plant.submit_revision(project_b["id"])

    return {
        "model": model,
        "crew": crew,
        "project_a": project_a,
        "project_b": project_b,
        "revision_b": revision_b,
        "cabinet": cabinet,
    }


class TestNoRoleReachesAnothersExclusiveWrite:
    """There is no superuser, so every misdirected write answers the same way."""

    def test_five_misdirected_writes_are_all_refused_alike(self, plant):
        """A `PlantAdmin` seeds the catalogue — display models, burn-in chambers and
        commissioning crews — and drives the service's logical clock; it has no reach
        into engineering, production, QA or service workflows.

        Design: Corner/rbac/no_role_may_perform_another_roles_exclusive_write
        """
        scene = _two_projects_one_approved_and_one_awaiting_review(plant)

        as_admin = plant.api.create_project(
            project_payload(scene["model"]["id"], customer_name="Admin Overreach"),
            plant.admin,
        )
        as_reviewer = plant.api.create_module(
            module_payload(scene["model"]["id"], "REV-MADE-THIS"), plant.reviewer
        )
        as_service = plant.api.qa_approve_cabinet(
            scene["cabinet"]["id"], plant.service
        )
        as_field = plant.api.create_service_contract(
            service_contract_payload(
                scene["project_a"]["id"],
                tier="GOLD",
                spare_pct_bp=GOLD_SPARE_PCT_BP,
                term_months=GOLD_TERM_MONTHS,
            ),
            make_field_engineer_headers(scene["crew"]["id"]),
        )
        as_operator = plant.api.set_clock_raw(
            {"to_iso8601": ATTEMPTED_CLOCK_INSTANT}, plant.operator
        )

        for response in (as_admin, as_reviewer, as_service, as_field, as_operator):
            validate_error(response, ERR_UNAUTHORIZED, 403)

        projects, project_meta = validate_paginated(plant.api.list_projects(plant.engineer))
        modules, module_meta = validate_paginated(plant.api.list_modules(plant.operator))
        assert ids_of(projects) == [scene["project_a"]["id"], scene["project_b"]["id"]]
        assert_page_meta(project_meta, total_count=2, has_more=False)
        assert modules == []
        assert_page_meta(module_meta, total_count=0, has_more=False)

    def test_the_permission_rung_answers_before_duties_and_before_state(self, plant):
        """This ordering is observable and it matters, because a single bad request
        frequently violates several rules at once — a caller with the wrong role and a
        nonexistent id gets the authorization failure, not the not-found failure. The
        authenticated role is permitted to invoke the target operation — otherwise
        `ERR_UNAUTHORIZED`. Applies to every operation.

        Design: Corner/rbac/no_role_may_perform_another_roles_exclusive_write
        """
        scene = _two_projects_one_approved_and_one_awaiting_review(plant)

        self_review = plant.api.review_drawing_revision(
            scene["revision_b"]["id"], review_payload("APPROVE"), plant.engineer
        )
        premature_mount = plant.api.mount_cabinet(scene["cabinet"]["id"], plant.qa)

        validate_error(self_review, ERR_UNAUTHORIZED, 403)
        validate_error(premature_mount, ERR_UNAUTHORIZED, 403)

        untouched_revision = plant.revision(scene["revision_b"]["id"])
        assert untouched_revision["revision_state"] == REVISION_SUBMITTED
        assert untouched_revision["reviewed_by_user_id"] is None
        assert_version(untouched_revision, 1, "revision")

        untouched_cabinet = plant.cabinet(scene["cabinet"]["id"])
        assert untouched_cabinet["cabinet_state"] == CABINET_PLANNED
        assert_version(untouched_cabinet, 1, "cabinet")


class TestSharedWritesAndOpenReads:
    """One endpoint with two authorised roles, and reads with all seven."""

    def test_both_authorised_roles_book_the_same_endpoint(self, plant):
        """A commissioning visit may be booked by either a `PlantAdmin` or a
        `FieldEngineer`, naming the `project_id`, the `commissioning_crew_id`, and the
        half-open `window_start` and `window_end` of the on-site window as ISO 8601
        UTC instants with three fractional digits; `window_end` must be strictly later
        than `window_start`. A booking that survives both is created with
        `visit_state` `SCHEDULED`, and the crew's `scheduled_visit_count` rises by 1.

        Design: Corner/rbac/shared_and_read_operations_are_open_to_their_declared_roles
        """
        model = plant.register_model()
        crew = plant.register_crew()
        project = plant.create_project(model["id"])

        from_the_office = validate_success(
            plant.api.create_commissioning_visit(
                commissioning_visit_payload(
                    project["id"],
                    crew["id"],
                    window_start=VISIT_WINDOW_START,
                    window_end=VISIT_WINDOW_END,
                ),
                make_plant_admin_headers(),
            ),
            201,
        )
        from_the_van = validate_success(
            plant.api.create_commissioning_visit(
                commissioning_visit_payload(
                    project["id"],
                    crew["id"],
                    window_start=SECOND_WINDOW_START,
                    window_end=SECOND_WINDOW_END,
                ),
                make_field_engineer_headers(crew["id"]),
            ),
            201,
        )

        assert from_the_office["visit_state"] == VISIT_SCHEDULED
        assert from_the_van["visit_state"] == VISIT_SCHEDULED
        assert from_the_van["commissioning_crew_id"] == crew["id"]
        assert plant.crew(crew["id"])["scheduled_visit_count"] == 2

        visits, meta = validate_paginated(
            plant.api.list_commissioning_visits(
                plant.service, {"project_id": project["id"]}
            )
        )
        assert ids_of(visits) == [from_the_office["id"], from_the_van["id"]]
        assert_page_meta(meta, total_count=2, has_more=False)

    def test_the_catalogue_read_is_open_to_every_role(self, plant):
        """Every read operation is open to all seven roles.

        Design: Corner/rbac/shared_and_read_operations_are_open_to_their_declared_roles
        """
        model = plant.register_model()
        crew = plant.register_crew()

        every_role = (
            plant.admin,
            plant.engineer,
            plant.reviewer,
            plant.operator,
            plant.qa,
            plant.service,
            make_field_engineer_headers(crew["id"]),
        )

        for headers in every_role:
            rows, meta = validate_paginated(plant.api.list_display_models(headers))
            assert ids_of(rows) == [model["id"]]
            assert_page_meta(meta, total_count=CATALOGUE_SIZE, has_more=False)
