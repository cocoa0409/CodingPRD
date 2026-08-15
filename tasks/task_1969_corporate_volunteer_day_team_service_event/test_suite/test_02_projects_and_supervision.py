"""Project sourcing rules, supervision assignment rules, and project listing."""
from test_helpers import (
    ApiErrorId,
    add_signed_registration,
    assign_lead,
    create_event,
    create_partner,
    create_project,
    create_volunteer,
    get_assignment,
    make_nonprofit_coordinator_headers,
    match_project,
    setup_matched_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    vet_project,
    withdraw_assignment,
)


class TestProjectBoundsValidation:
    def test_project_inverted_volunteer_bounds_rejected(self, api, any_headers):
        """PRD §3.1: "`min_volunteers` must be at least 1, and `max_volunteers` must be at least `min_volunteers`; violations of these ranges are rejected with `ERR_VALIDATION`."

        Design: Corner/entities/project_inverted_volunteer_bounds_rejected
        """
        partner = create_partner()
        resp = api.create_service_project(
            {
                "nonprofit_id": partner["id"],
                "title": "Bad Bounds",
                "min_volunteers": 5,
                "max_volunteers": 3,
            },
            make_nonprofit_coordinator_headers(partner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        _, meta = validate_paginated(api.list_service_projects(any_headers, params={}))
        assert meta["total_count"] == 0


class TestProjectStateMachine:
    def test_project_vet_twice_rejected(self, api, cem_headers):
        """PRD §3.1: "A `CommunityEngagementManager` then vets a `PROPOSED` project, moving it to `VETTED`; the partner must still be `ACTIVE` (again `ERR_NONPROFIT_SUSPENDED`), and a project in any other from-state is rejected with `ERR_INVALID_PROJECT_TRANSITION`."

        Design: Corner/errors/project_vet_twice_rejected
        """
        partner = create_partner()
        project = create_project(partner["id"])
        vet_project(project["id"])
        resp = api.vet_project(project["id"], cem_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_PROJECT_TRANSITION)

    def test_filtered_list_reverse_fk_lookup(self, api, any_headers):
        """PRD §3.1: "Project listings may be filtered by `nonprofit_id`, `event_id`, or `status`."

        Design: Corner/endpoints/filtered_list_reverse_fk_lookup
        """
        partner = create_partner()
        proj_a = create_project(partner["id"], "P-1")
        proj_b = create_project(partner["id"], "P-2")
        ev_a = create_event("Day 36A")
        ev_b = create_event(
            "Day 36B", event_start_at="2026-08-21T09:00:00Z", event_end_at="2026-08-21T15:00:00Z"
        )
        vet_project(proj_a["id"])
        vet_project(proj_b["id"])
        match_project(proj_a["id"], ev_a["id"])
        match_project(proj_b["id"], ev_b["id"])

        data, meta = validate_paginated(
            api.list_service_projects(any_headers, params={"event_id": ev_a["id"]})
        )
        assert meta["total_count"] == 1
        assert [p["id"] for p in data] == [proj_a["id"]]


class TestSupervisionRules:
    def test_lead_not_qualified_without_flag_or_when_registered(self, api, cem_headers):
        """PRD §3.3: "The named lead must have `is_staff_lead` true and must not hold a non-`CANCELLED` registration on the same project (a lead cannot supervise a project they are also volunteering on); either failure is rejected with `ERR_LEAD_NOT_QUALIFIED`."

        Design: Corner/validations/lead_not_qualified_without_flag_or_when_registered
        """
        sc = setup_matched_scenario(event_name="Day 22")
        project_id = sc["project"]["id"]
        event_id = sc["event"]["id"]
        plain = create_volunteer("Plain", "p@corp.com")  # no is_staff_lead flag
        lead_registered = create_volunteer(
            "Lead Registered", "lr@corp.com", date_of_birth="1985-03-03", is_staff_lead=True
        )
        # The flagged lead registers as a participant on the same project
        add_signed_registration(event_id, project_id, lead_registered, wants_meal=False)

        resp1 = api.create_supervision_assignment(
            {"project_id": project_id, "lead_volunteer_id": plain["id"]}, cem_headers
        )
        validate_error(resp1, ApiErrorId.ERR_LEAD_NOT_QUALIFIED)

        resp2 = api.create_supervision_assignment(
            {"project_id": project_id, "lead_volunteer_id": lead_registered["id"]},
            cem_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_LEAD_NOT_QUALIFIED)

    def test_duplicate_active_supervision_rejected(self, api, cem_headers):
        """PRD §3.3: "Only one `ACTIVE` assignment may exist per project-and-lead pair; a duplicate is rejected with `ERR_ACTIVE_SUPERVISION_EXISTS`."

        Design: Corner/validations/duplicate_active_supervision_rejected
        """
        sc = setup_matched_scenario(event_name="Day 21", open_registration=False)
        project_id = sc["project"]["id"]
        lead = create_volunteer(
            "Lead One", "lead1@corp.com", date_of_birth="1985-03-03", is_staff_lead=True
        )
        assignment = assign_lead(project_id, lead)

        dup = api.create_supervision_assignment(
            {"project_id": project_id, "lead_volunteer_id": lead["id"]}, cem_headers
        )
        validate_error(dup, ApiErrorId.ERR_ACTIVE_SUPERVISION_EXISTS)

        # After withdrawal the pair is free again (the rule covers only ACTIVE)
        withdraw_assignment(assignment["id"])
        re_assigned = api.create_supervision_assignment(
            {"project_id": project_id, "lead_volunteer_id": lead["id"]}, cem_headers
        )
        data = validate_success(re_assigned, 201)
        assert data["status"] == "ACTIVE"
        assert data["id"] != assignment["id"]

    def test_supervision_double_withdraw_rejected(self, api, cem_headers):
        """PRD §3.3: "Only an `ACTIVE` assignment can be withdrawn (`ERR_INVALID_SUPERVISION_TRANSITION` otherwise)."

        Design: Corner/errors/supervision_double_withdraw_rejected
        """
        sc = setup_matched_scenario(event_name="Day 40", open_registration=False)
        lead = create_volunteer(
            "Lead One", "lead1@corp.com", date_of_birth="1985-03-03", is_staff_lead=True
        )
        assignment = assign_lead(sc["project"]["id"], lead)
        withdrawn = withdraw_assignment(assignment["id"])
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.withdraw_supervision_assignment(assignment["id"], cem_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_SUPERVISION_TRANSITION)
        assert get_assignment(assignment["id"])["status"] == "WITHDRAWN"


class TestCoordinatorOwnership:
    def test_coordinator_cannot_create_project_for_other_nonprofit(self, api, any_headers):
        """PRD §3.1: "Ownership is enforced at the door: the coordinator's `X-User-ID` must equal the proposed `nonprofit_id`, otherwise the request is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/coordinator_cannot_create_project_for_other_nonprofit
        """
        np1 = create_partner("River Guild", "ops@river.org")
        np2 = create_partner("City Shelter", "hi@shelter.org")
        resp = api.create_service_project(
            {
                "nonprofit_id": np1["id"],
                "title": "Intruder Project",
                "min_volunteers": 1,
                "max_volunteers": 5,
            },
            make_nonprofit_coordinator_headers(np2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        _, meta = validate_paginated(api.list_service_projects(any_headers, params={}))
        assert meta["total_count"] == 0
