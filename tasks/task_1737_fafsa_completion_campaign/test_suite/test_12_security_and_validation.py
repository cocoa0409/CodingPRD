"""Access control and validation precedence: header context, role lists,
coordinator school scope, ownership, existence-before-state, and the
uniqueness constraint family (PRD §2.1, §2.9, §3.3, §3.6, §3.8, §3.9)."""
from test_helpers import (
    IMPORTER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    REVIEWER,
    add_aid_record,
    add_senior,
    add_school,
    coord,
    create_assignment,
    create_campaign,
    create_event,
    create_matched_senior,
    create_specialist,
    create_staff,
    create_support_case,
    enroll_school,
    grant_consent,
    make_school_coordinator_headers,
    make_staff_member_headers,
    setup_campaign_with_school,
    spec_headers,
    validate_error,
    validate_success,
)


class TestHeaderContext:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        value outside this declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.list_campaigns(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400


class TestExistenceBeforeState:
    def test_enroll_nonexistent_school_returns_404_even_in_draft_campaign(
        self, api, admin_headers
    ):
        """PRD §2.9: "The server evaluates checks in the following fixed order,
        and the first failure wins" — "4. Existence: path identifiers and body
        foreign-key references resolve to existing resources, validated left to
        right" runs before "5. State permission: the target entity is in a
        state that permits the operation". Enrolling a nonexistent school under
        a still-DRAFT campaign therefore reports the 404, not the campaign
        state error.

        Design: Corner/validations/existence_beats_state_on_nested_action
        """
        create_campaign()  # stays DRAFT: enroll would fail the state gate
        resp = api.enroll_school(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_SCHOOL_NOT_FOUND)
        assert resp.status_code == 404


class TestUniquenessConstraints:
    def test_all_five_uniqueness_invariants_rejected(self, api):
        """PRD §3.3: "Each record carries the school's own `student_ref`
        (unique within the school — a reuse attempt is
        `ERR_DUPLICATE_STUDENT_REF`)" and aid records carry "`external_ref`
        (unique per campaign — duplicates draw `ERR_DUPLICATE_EXTERNAL_REF`)".
        PRD §3.6: "at most one consent may be `GRANTED` for a senior at any
        time: creating a second while one is active, or regranting while
        another is active, is refused with `ERR_CONSENT_ALREADY_ACTIVE`."
        PRD §3.9: "One non-terminal case per senior-and-type pair is the limit
        (`ERR_CASE_ALREADY_OPEN`)."
        PRD §3.8: "only one non-terminal assignment may exist for a given
        event-and-staff pair (`ERR_DUPLICATE_ASSIGNMENT`)".

        Design: Corner/validations/uniqueness_constraints_rejected
        """
        campaign, school = setup_campaign_with_school()
        senior = add_senior(school, student_ref="S1")
        grant_consent(school, senior["id"], ["STATUS_DETAIL"])
        specialist = create_staff(
            campaign,
            full_name="Spec Sal",
            capabilities=["CASE_SPECIALIST", "EVENT_STAFF"],
        )
        create_support_case(school, senior["id"], "SPECIAL_CIRCUMSTANCE")
        add_aid_record(campaign, external_ref="EXT1")
        event = create_event(school, title="E1")
        create_assignment(school, event["id"], specialist)

        # 1. student_ref reused within the same school.
        resp = api.create_senior_record(
            {
                "school_id": school["id"],
                "student_ref": "S1",
                "full_name": "Other Name",
                "dob": "2009-09-09",
                "home_language": "es",
            },
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STUDENT_REF)

        # 2. external_ref reused within the same campaign.
        resp = api.create_aid_record(
            {
                "campaign_id": campaign["id"],
                "external_ref": "EXT1",
                "full_name": "Other",
                "dob": "2000-01-01",
                "school_code": "SC02",
                "district_code": "D02",
                "initial_status": "STARTED",
                "effective_date": "2027-01-11",
            },
            IMPORTER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EXTERNAL_REF)

        # 3. A second GRANTED consent for the same senior.
        resp = api.create_consent_record(
            {
                "senior_record_id": senior["id"],
                "scopes": ["OUTREACH"],
                "granted_by": "ADULT_STUDENT",
            },
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_ALREADY_ACTIVE)

        # 4. A second non-terminal case of the same type for the senior.
        resp = api.create_support_case(
            {"senior_record_id": senior["id"], "case_type": "SPECIAL_CIRCUMSTANCE"},
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_OPEN)

        # 5. A second non-terminal assignment for the same (event, staff).
        resp = api.create_staff_assignment(
            {
                "event_id": event["id"],
                "staff_profile_id": specialist["id"],
                "assigned_role": "VOLUNTEER",
            },
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT)


class TestRoleAuthorization:
    def test_coordinator_cannot_write_other_school(self, api):
        """PRD §2.1: "When `X-User-Role` is `SchoolCoordinator`, `X-User-ID` is
        the `id` of the acting `School`. Every write the coordinator performs
        must target resources of their own school: whenever a resource carries
        a `school_id` (directly or through its parent chain, such as an event's
        school or a senior's school), the server compares that field to
        `X-User-ID`, and a mismatch is rejected with
        `ERR_SCHOOL_SCOPE_VIOLATION`."

        Design: Corner/rbac/coordinator_cannot_write_other_school
        """
        campaign, school_a = setup_campaign_with_school(
            school_overrides={"name": "A HS", "school_code": "SC0A"}
        )
        school_b = enroll_school(
            add_school(
                campaign, name="B HS", district_code="D02", school_code="SC0B"
            )
        )

        resp = api.create_senior_record(
            {
                "school_id": school_b["id"],
                "student_ref": "S1",
                "full_name": "Ana Lee",
                "dob": "2009-03-04",
                "home_language": "en",
            },
            make_school_coordinator_headers(school_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCHOOL_SCOPE_VIOLATION)
        assert resp.status_code == 403

    def test_staff_member_cannot_create_event(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's
        authorized-role list is rejected with `ERR_UNAUTHORIZED_ROLE`." —
        PRD §4 authorizes only `SchoolCoordinator` for `POST /fafsa/events`.

        Design: Corner/rbac/staff_member_cannot_create_event
        """
        campaign, school = setup_campaign_with_school()
        staff = create_staff(campaign)
        resp = api.create_event(
            {
                "school_id": school["id"],
                "title": "E1",
                "start_time": "2026-09-10T10:00:00Z",
                "end_time": "2026-09-10T12:00:00Z",
                "capacity": 10,
                "cost_estimate_cents": 1000,
                "required_expert_count": 0,
                "supported_languages": [],
            },
            make_staff_member_headers(staff["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert resp.status_code == 403

    def test_specialist_cannot_confirm_match_link(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's
        authorized-role list is rejected with `ERR_UNAUTHORIZED_ROLE`." —
        PRD §4 authorizes only `MatchReviewer` for
        `POST /fafsa/match-links/{id}/confirm`; case work and data matching are
        segregated peer roles.

        Design: Corner/rbac/specialist_cannot_confirm_match_link
        """
        campaign, school = setup_campaign_with_school()
        specialist = create_specialist(campaign)
        _senior, _aid, link, _c = create_matched_senior(
            campaign,
            school,
            student_ref="S1",
            full_name="Ana Lee",
            dob="2009-03-04",
            aid_school_code="SC99",  # 0.85 -> SUGGESTED
            aid_status="SUBMITTED",
        )
        assert link["status"] == "SUGGESTED"

        resp = api.confirm_match_link(link["id"], spec_headers(specialist))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        resp = api.get_match_link(link["id"], REVIEWER)
        assert validate_success(resp, 200)["status"] == "SUGGESTED", (
            "the rejected confirm must leave the link SUGGESTED"
        )
