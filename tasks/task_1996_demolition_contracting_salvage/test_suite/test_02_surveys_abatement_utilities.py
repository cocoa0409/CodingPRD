"""Structure surveys, hazmat abatement, utility disconnects, listing."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_structure_survey_payload, complete_survey_payload,
    create_abatement_payload, create_utility_disconnect_payload,
    create_neighbor_notification_payload,
    make_abatement_supervisor_headers, make_clearance_officer_headers,
    make_utility_coordinator_headers,
    create_project, create_and_complete_survey,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
SUPERVISOR = TEST_USERS["site_supervisor_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]


class TestProjectSurveyLifecycle:
    def test_project_auto_advances_on_first_survey_and_bubbles_up(self):
        """PRD §3.1: "The very first survey created under a `DRAFT` project
        automatically advances the project to `SURVEY_PHASE`, incrementing the
        project's `version` by 1."
        PRD §3.1: "When at least one survey exists and every survey of the
        project is `COMPLETE` while the project is in `SURVEY_PHASE`, the project
        bubbles up to `PRECONDITIONS_PENDING`, its `version` incrementing by 1."

        Design: Corner/state_machines/project_auto_advances_on_first_survey_and_bubbles_up
        """
        project = create_project(name="Auto", address="18 Pine St", lot_area_sqft=12000)
        assert project["version"] == 1
        survey = get_success_data(
            api_client.create_structure_survey(
                project["id"], create_structure_survey_payload(), SURVEYOR
            )
        )
        mid = get_success_data(api_client.get_project(project["id"], SUPERVISOR))
        assert mid["status"] == "SURVEY_PHASE"
        assert mid["version"] == project["version"] + 1
        get_success_data(
            api_client.transition_structure_survey(
                survey["id"], complete_survey_payload(), SURVEYOR
            )
        )
        end = get_success_data(api_client.get_project(project["id"], SUPERVISOR))
        assert end["status"] == "PRECONDITIONS_PENDING"
        assert end["version"] == mid["version"] + 1

    def test_project_regresses_when_new_survey_created_in_preconditions_pending(self):
        """PRD §3.1: "Opening an additional survey while the project sits in
        `PRECONDITIONS_PENDING` — typically an `ADDENDUM` after something new is
        found — regresses the project back to `SURVEY_PHASE`, again incrementing
        `version`."

        Design: Corner/state_machines/project_regresses_when_new_survey_created_in_preconditions_pending
        """
        project = create_project(name="Regress", address="20 Pine St", lot_area_sqft=12000)
        create_and_complete_survey(project["id"])
        get_success_data(
            api_client.create_structure_survey(
                project["id"],
                create_structure_survey_payload(structure_label="Garage", survey_type="ADDENDUM"),
                SURVEYOR,
            )
        )
        after = get_success_data(api_client.get_project(project["id"], SUPERVISOR))
        assert after["status"] == "SURVEY_PHASE"

    def test_survey_create_missing_required_label_rejected(self):
        """PRD §3.1: "a `Surveyor` opens a structure survey under the project,
        naming the `structure_label` (for example "Main Bldg")"
        PRD §2.9: "required fields are present, types are correct, enum members
        are valid, and ranges hold ... (`ERR_VALIDATION`)."

        Design: Corner/entities/survey_create_missing_required_label_rejected
        """
        project = create_project(name="Req", address="4 Pine St", lot_area_sqft=12000)
        resp = api_client.create_structure_survey(
            project["id"], {"survey_type": "ADDENDUM"}, SURVEYOR
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_survey_create_under_not_found_project(self):
        """PRD §2.7: "The first identifier that fails to resolve, or the first
        child found outside the path parent's scope, rejects the request with
        `ERR_NOT_FOUND`"

        Design: Corner/entities/survey_create_under_not_found_project
        """
        resp = api_client.create_structure_survey(
            NON_EXISTENT_UUID, create_structure_survey_payload(structure_label="X"), SURVEYOR
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAbatement:
    def test_abatement_fail_clearance_recycle_to_certified(self):
        """PRD §3.2: "Failure is not the end of the line — a failed order supports
        a re-abatement cycle in which an `AbatementSupervisor` starts the work
        again from `CLEARANCE_FAILED` back to `ABATEMENT_ACTIVE`, with
        `started_by_user_id` re-recorded from the new starter."
        PRD §3.2: "certifying clearance moves the order to `CLEARANCE_CERTIFIED`,
        records the certifier as `certified_by_user_id`, and stamps `certified_at`
        from the logical clock."

        Design: Corner/state_machines/abatement_fail_clearance_recycle_to_certified
        """
        project = create_project(name="Recycle", address="28 Pine St", lot_area_sqft=12000)
        survey = create_and_complete_survey(project["id"], hazmat_found=True)
        ab = get_success_data(
            api_client.create_abatement(survey["id"], create_abatement_payload(), SURVEYOR)
        )
        starter = make_abatement_supervisor_headers("rc-s-1")
        officer = make_clearance_officer_headers("rc-c-1")
        get_success_data(api_client.transition_abatement(ab["id"], {"action": "START"}, starter))
        get_success_data(
            api_client.transition_abatement(ab["id"], {"action": "REQUEST_CLEARANCE"}, starter)
        )
        failed = get_success_data(
            api_client.transition_abatement(ab["id"], {"action": "FAIL_CLEARANCE"}, officer)
        )
        assert failed["status"] == "CLEARANCE_FAILED"
        restarted = get_success_data(
            api_client.transition_abatement(ab["id"], {"action": "START"}, starter)
        )
        assert restarted["status"] == "ABATEMENT_ACTIVE"
        get_success_data(
            api_client.transition_abatement(ab["id"], {"action": "REQUEST_CLEARANCE"}, starter)
        )
        certified = get_success_data(
            api_client.transition_abatement(ab["id"], {"action": "CERTIFY_CLEARANCE"}, officer)
        )
        assert certified["status"] == "CLEARANCE_CERTIFIED"
        assert certified["certified_by_user_id"] == "rc-c-1"

    def test_subresource_list_discovers_children(self):
        """PRD §3.2: "The order is born in `IDENTIFIED` status and carries its
        `structure_survey_id` back to the survey that identified the hazard."
        PRD §4: GET /demolition/structure-surveys/{id}/abatements — "List the
        abatement orders of a survey"

        Design: Corner/entities/subresource_list_discovers_children
        """
        project = create_project(name="FK", address="16 Pine St", lot_area_sqft=12000)
        survey = get_success_data(
            api_client.create_structure_survey(
                project["id"], create_structure_survey_payload(), SURVEYOR
            )
        )
        get_success_data(
            api_client.create_abatement(
                survey["id"],
                create_abatement_payload(material_type="ASBESTOS", description="pipe wrap",
                                         containment_method="wet"),
                SURVEYOR,
            )
        )
        get_success_data(
            api_client.create_abatement(
                survey["id"],
                create_abatement_payload(material_type="LEAD_PAINT", description="trim",
                                         containment_method="strip"),
                SURVEYOR,
            )
        )
        data, meta = validate_paginated(
            api_client.list_abatements(survey["id"], SURVEYOR)
        )
        assert meta["total_count"] == 2
        assert all(row["structure_survey_id"] == survey["id"] for row in data)


class TestUtilityDisconnect:
    def test_utility_create_invalid_enum_rejected(self):
        """PRD §3.3: "naming the `utility_type` — `ELECTRIC`, `GAS`, `WATER`,
        `SEWER`, or `TELECOM`"
        PRD §2.9: "required fields are present, types are correct, enum members
        are valid, and ranges hold ... (`ERR_VALIDATION`)."

        Design: Corner/entities/utility_create_invalid_enum_rejected
        """
        project = create_project(name="Enum", address="14 Pine St", lot_area_sqft=12000)
        resp = api_client.create_utility_disconnect(
            project["id"],
            create_utility_disconnect_payload(
                utility_type="PROPANE",
                disconnect_window_start="2026-08-03T08:00:00Z",
                disconnect_window_end="2026-08-03T09:00:00Z",
            ),
            TEST_USERS["utility_coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_utility_disconnect_parallel_dimensions_with_reject_cycle(self):
        """PRD §3.3: "verifying while `disconnect_status` is still `SCHEDULED` is
        rejected with `ERR_INVALID_STATE`."
        PRD §3.3: "Verification can be revoked: rejecting a verification moves
        `FIELD_VERIFIED` to `VERIFICATION_REJECTED`, and a rejected verification
        can be verified again back to `FIELD_VERIFIED`."
        PRD §3.3: "confirmation moves `FIELD_VERIFIED` to `CONFIRMED`, recording
        `confirmed_by_user_id`"

        Design: Difficulty/non_linear_state_machine/utility_disconnect_parallel_dimensions_with_reject_cycle
        """
        project = create_project(name="Util Lot", address="9 Elm St", lot_area_sqft=20000)
        ud = get_success_data(
            api_client.create_utility_disconnect(
                project["id"],
                create_utility_disconnect_payload(
                    disconnect_window_start="2026-08-03T08:00:00Z",
                    disconnect_window_end="2026-08-03T12:00:00Z",
                ),
                TEST_USERS["utility_coordinator_headers"],
            )
        )
        # VERIFY before REPORT_DISCONNECTED: cross-dimension guard.
        resp = api_client.transition_utility_disconnect(
            ud["id"], {"action": "VERIFY"}, make_utility_coordinator_headers("uu-x-1")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # REPORT_DISCONNECTED flips only the disconnect dimension.
        d1 = get_success_data(
            api_client.transition_utility_disconnect(
                ud["id"], {"action": "REPORT_DISCONNECTED"},
                make_utility_coordinator_headers("uu-r-1"),
            )
        )
        assert d1["disconnect_status"] == "REPORTED_DISCONNECTED"
        assert d1["verification_status"] == "UNVERIFIED"
        get_success_data(
            api_client.transition_utility_disconnect(
                ud["id"], {"action": "VERIFY"}, make_utility_coordinator_headers("uu-v-1")
            )
        )
        d2 = get_success_data(
            api_client.transition_utility_disconnect(
                ud["id"], {"action": "REJECT_VERIFICATION"},
                make_utility_coordinator_headers("uu-v-2"),
            )
        )
        assert d2["disconnect_status"] == "REPORTED_DISCONNECTED"
        assert d2["verification_status"] == "VERIFICATION_REJECTED"
        get_success_data(
            api_client.transition_utility_disconnect(
                ud["id"], {"action": "VERIFY"}, make_utility_coordinator_headers("uu-v-3")
            )
        )
        d3 = get_success_data(
            api_client.transition_utility_disconnect(
                ud["id"], {"action": "CONFIRM"}, make_utility_coordinator_headers("uu-c-1")
            )
        )
        assert d3["disconnect_status"] == "REPORTED_DISCONNECTED"
        assert d3["verification_status"] == "CONFIRMED"

    def test_utility_disconnect_born_with_parallel_initial_dimensions(self):
        """PRD §3.3: "A new disconnect is born with `disconnect_status`
        `SCHEDULED` and `verification_status` `UNVERIFIED`, the two dimensions
        evolving independently from there."
        PRD §3.3: "the `UtilityCoordinator` reports the physical disconnection,
        moving `disconnect_status` from `SCHEDULED` to `REPORTED_DISCONNECTED`
        and recording the operator as `reported_by_user_id`."

        Design: Difficulty/non_linear_state_machine/utility_disconnect_parallel_dimensions_with_reject_cycle
        """
        project = create_project(name="UtilBorn", address="9B Elm St", lot_area_sqft=20000)
        ud = get_success_data(
            api_client.create_utility_disconnect(
                project["id"], create_utility_disconnect_payload(),
                TEST_USERS["utility_coordinator_headers"],
            )
        )
        assert ud["disconnect_status"] == "SCHEDULED"
        assert ud["verification_status"] == "UNVERIFIED"
        after = get_success_data(
            api_client.transition_utility_disconnect(
                ud["id"], {"action": "REPORT_DISCONNECTED"},
                make_utility_coordinator_headers("ub-r-1"),
            )
        )
        assert after["disconnect_status"] == "REPORTED_DISCONNECTED"
        assert after["verification_status"] == "UNVERIFIED", "verification dim untouched"
        assert after["reported_by_user_id"] == "ub-r-1"

    def test_disconnect_windows_half_open_adjacency(self):
        """PRD §3.3: "Windows are half-open — they include their start instant and
        exclude their end — and two disconnects on the same project with the same
        `utility_type` may not overlap; an overlapping schedule is rejected with
        `ERR_DISCONNECT_WINDOW_OVERLAP`. Adjacency is allowed: one window ending
        exactly when the next begins does not count as overlap."

        Design: Difficulty/resource_temporal_overlap/disconnect_windows_half_open_adjacency
        """
        project = create_project(name="Overlap Lot", address="73 Elm St", lot_area_sqft=20000)
        uc = TEST_USERS["utility_coordinator_headers"]
        get_success_data(
            api_client.create_utility_disconnect(
                project["id"],
                create_utility_disconnect_payload(
                    disconnect_window_start="2026-08-03T08:00:00Z",
                    disconnect_window_end="2026-08-03T12:00:00Z",
                ),
                uc,
            )
        )
        # Adjacent (start == prior end): allowed under half-open semantics.
        resp_adjacent = api_client.create_utility_disconnect(
            project["id"],
            create_utility_disconnect_payload(
                disconnect_window_start="2026-08-03T12:00:00Z",
                disconnect_window_end="2026-08-03T16:00:00Z",
            ),
            uc,
        )
        validate_success(resp_adjacent, expected_status=201)
        # Overlapping (11:00 < 12:00): rejected.
        resp_overlap = api_client.create_utility_disconnect(
            project["id"],
            create_utility_disconnect_payload(
                disconnect_window_start="2026-08-03T11:00:00Z",
                disconnect_window_end="2026-08-03T13:00:00Z",
            ),
            uc,
        )
        validate_error(resp_overlap, ApiErrorId.ERR_DISCONNECT_WINDOW_OVERLAP)
        # Different utility_type overlapping in time: rule is per utility_type.
        resp_other = api_client.create_utility_disconnect(
            project["id"],
            create_utility_disconnect_payload(
                utility_type="GAS", provider_name="City Gas",
                disconnect_window_start="2026-08-03T09:00:00Z",
                disconnect_window_end="2026-08-03T10:00:00Z",
            ),
            uc,
        )
        validate_success(resp_other, expected_status=201)

    def test_disconnect_window_touching_at_start_boundary_allowed(self):
        """PRD §3.3: "Windows are half-open — they include their start instant and
        exclude their end — and two disconnects on the same project with the same
        `utility_type` may not overlap; an overlapping schedule is rejected with
        `ERR_DISCONNECT_WINDOW_OVERLAP`. Adjacency is allowed: one window ending
        exactly when the next begins does not count as overlap."

        Design: Difficulty/resource_temporal_overlap/disconnect_windows_half_open_adjacency
        """
        project = create_project(name="Overlap2", address="73B Elm St", lot_area_sqft=20000)
        uc = TEST_USERS["utility_coordinator_headers"]
        get_success_data(
            api_client.create_utility_disconnect(
                project["id"],
                create_utility_disconnect_payload(
                    disconnect_window_start="2026-08-03T08:00:00Z",
                    disconnect_window_end="2026-08-03T12:00:00Z",
                ),
                uc,
            )
        )
        # Window ending exactly when the first begins (reverse adjacency).
        resp = api_client.create_utility_disconnect(
            project["id"],
            create_utility_disconnect_payload(
                disconnect_window_start="2026-08-03T06:00:00Z",
                disconnect_window_end="2026-08-03T08:00:00Z",
            ),
            uc,
        )
        validate_success(resp, expected_status=201)


class TestListingAndPagination:
    def test_notification_list_pagination_interaction(self):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items from the front of the result set and
        defaults to 0."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns
        resources sorted by `created_at` in ascending order. The `meta` object of
        a list response carries the pagination fields `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/notification_list_pagination_interaction
        """
        project = create_project(name="Page", address="12 Pine St", lot_area_sqft=12000)
        for addr in ("A1", "A2", "A3"):
            get_success_data(
                api_client.create_neighbor_notification(
                    project["id"],
                    create_neighbor_notification_payload(
                        address=addr, scheduled_delivery_date="2026-08-03"
                    ),
                    SUPERVISOR,
                )
            )
        page1, meta1 = validate_paginated(
            api_client.list_neighbor_notifications(
                project["id"], SUPERVISOR, params={"limit": 2, "offset": 0}
            )
        )
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2
        assert page1[0]["address"] == "A1"
        page2, meta2 = validate_paginated(
            api_client.list_neighbor_notifications(
                project["id"], SUPERVISOR, params={"limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert page2[0]["address"] == "A3"
        assert meta2["has_more"] is False

    def test_projects_list_envelope_and_status_filter(self):
        """PRD §3.1: "Projects can be browsed through the project list, which
        optionally filters by `status` or by `pinned_engineering_survey_id` —
        the latter finds the one project currently pinned to a given engineering
        survey — alongside the standard `limit` and `offset` parameters."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/projects_list_envelope_and_status_filter
        """
        project = create_project(name="ListMe", address="80 Pine St", lot_area_sqft=12000)
        resp = api_client.list_projects(ADMIN, params={"status": "DRAFT"})
        body = resp.json()
        assert body["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert meta["total_count"] >= 1
        assert any(row["id"] == project["id"] for row in data)
        _, meta_closed = validate_paginated(
            api_client.list_projects(ADMIN, params={"status": "CLOSED", "limit": 10, "offset": 0})
        )
        assert meta_closed["total_count"] == 0
        assert meta_closed["has_more"] is False
