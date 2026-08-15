"""Role-based access control and committee privilege: role-list denials,
provider ownership scoping, the CHAIR attribute gate, and the privileged
notes surface."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assign_reviewer,
    create_case,
    create_case_payload,
    create_note_payload,
    create_provider,
    get_assignment,
    get_case,
    make_committee_member_headers,
    make_provider_headers,
    screen_case_in,
    seat_member,
    setup_case_in_deliberation,
    submit_assignment_payload,
    validate_error,
    validate_success,
)

QD = TEST_USERS["quality_director_headers"]
PRC = TEST_USERS["peer_review_coordinator_headers"]


class TestRoleListDenials:
    def test_provider_role_cannot_screen(self):
        """PRD §4: "| POST | `/peer-review/cases/{id}/screen` | Screen a
        referred case in or out | QualityDirector |".
        PRD §2.1: "A request whose role is well-formed but not among the roles
        authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/provider_role_cannot_screen
        """
        subject = create_provider("Subj RBAC1", "SURGERY")
        case = create_case(subject["id"], description="rbac case 1")
        resp = api_client.screen_case(case["id"], {"decision": "SCREEN_IN"},
                                      make_provider_headers(subject["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, expected_status=403)
        assert get_case(case["id"])["status"] == "REFERRED"

    def test_coordinator_cannot_screen(self):
        """PRD §2.1: "The `PeerReviewCoordinator` runs intake — referring
        cases and assigning reviewers — but cannot screen, score, finalize, or
        refer externally."
        PRD §2.1: "A request whose role is well-formed but not among the roles
        authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/coordinator_cannot_screen
        """
        subject = create_provider("Subj RBAC2", "CARDIOLOGY")
        case = create_case(subject["id"], description="rbac case 2")
        resp = api_client.screen_case(case["id"], {"decision": "SCREEN_IN"}, PRC)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, expected_status=403)
        assert get_case(case["id"])["status"] == "REFERRED"

    def test_member_cannot_create_case(self):
        """PRD §4: "| POST | `/peer-review/cases` | Refer a provider for peer
        review | PeerReviewCoordinator |".
        PRD §2.1: "A request whose role is well-formed but not among the roles
        authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/member_cannot_create_case
        """
        member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        subject = create_provider("Subj RBAC3", "PEDIATRICS")
        resp = api_client.create_case(
            create_case_payload(subject_provider_id=subject["id"],
                                description="rbac case 3"),
            make_committee_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, expected_status=403)

    def test_member_cannot_read_quality_trend(self):
        """PRD §4: "| GET | `/peer-review/providers/{id}/quality-trend` |
        Computed trailing-365-day trend metrics and trigger flags; read-only |
        QualityDirector, PeerReviewCoordinator |".
        PRD §2.1: "A request whose role is well-formed but not among the roles
        authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/member_cannot_read_quality_trend
        """
        subject = create_provider("Subj RBAC5", "CARDIOLOGY")
        member = seat_member(create_provider("Rev B", "CARDIOLOGY")["id"], "MEMBER")
        resp = api_client.get_provider_quality_trend(
            subject["id"], make_committee_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, expected_status=403)


class TestPrivilegeAndScope:
    def test_provider_cannot_read_privileged_notes(self):
        """PRD §2.9: "Case notes in particular are never exposed to the
        `Provider` role under any circumstances — they are the committee's
        privileged work product from the moment they are written."

        Design: Corner/rbac/provider_cannot_read_privileged_notes
        """
        subject = create_provider("Subj RBAC4", "SURGERY")
        member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        case = create_case(subject["id"], description="priv case")
        screen_case_in(case["id"])
        assign_reviewer(case["id"], member["id"])
        validate_success(api_client.create_case_note(
            case["id"], create_note_payload(body="privileged committee content"),
            make_committee_member_headers(member["id"])), expected_status=201)

        resp = api_client.list_case_notes(case["id"], make_provider_headers(subject["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, expected_status=403)

    def test_provider_reading_others_case_forbidden(self):
        """PRD §2.8: "A `Provider` may touch only cases whose
        `subject_provider_id` equals their `X-User-ID`; a `CommitteeMember`
        may declare or rescind only their own conflicts and may submit or
        revise only their own assignments; chair-gated actions require the
        acting member's `member_role` to be `CHAIR`. Violations surface as
        `ERR_FORBIDDEN_RESOURCE` (403), with the `ERR_CHAIR_REQUIRED` variant
        on the three chair-only actions."

        Design: Corner/rbac/provider_reading_others_case_forbidden
        """
        subject = create_provider("Subj Own", "SURGERY")
        other = create_provider("Other Prov", "CARDIOLOGY")
        case = create_case(subject["id"], description="scope case")

        resp = api_client.get_case(case["id"], make_provider_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE.value, expected_status=403)

        own = validate_success(api_client.get_case(case["id"],
                                                   make_provider_headers(subject["id"])))
        assert own["status"] == "REFERRED"

    def test_non_chair_finalize_returns_chair_required(self):
        """PRD §3.5: "Finalizing deliberation is a `CHAIR`-only action on a
        case in `DELIBERATION`; any other member attempting it is rejected
        with `ERR_CHAIR_REQUIRED`."

        Design: Corner/rbac/non_chair_finalize_returns_chair_required
        """
        ctx = setup_case_in_deliberation(scores=((4, None), (4, None), (4, None)))
        member_b = ctx["members"][0]
        resp = api_client.finalize_deliberation(
            ctx["case"]["id"], {"rationale_note": "member attempt"},
            make_committee_member_headers(member_b["id"]))
        validate_error(resp, ApiErrorId.ERR_CHAIR_REQUIRED.value, expected_status=403)

        case_after = get_case(ctx["case"]["id"])
        assert case_after["status"] == "DELIBERATION"
        deliberation = validate_success(api_client.get_case_deliberation(ctx["case"]["id"], QD))
        assert deliberation[0]["status"] == "OPEN"

    def test_member_cannot_submit_others_assignment(self):
        """PRD §3.4: "Reviewing is personal: only the assigned member may
        submit an assignment, so the acting member's identity must equal the
        assignment's `reviewer_id`, otherwise `ERR_FORBIDDEN_RESOURCE`."

        Design: Corner/rbac/member_cannot_submit_others_assignment
        """
        subject = create_provider("Subj Own2", "SURGERY")
        member_b = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        member_c = seat_member(create_provider("Rev C", "CARDIOLOGY")["id"], "MEMBER")
        case = create_case(subject["id"], description="own submit case")
        screen_case_in(case["id"])
        asg_b = assign_reviewer(case["id"], member_b["id"])

        fresh_version = get_case(case["id"])["version"]
        resp = api_client.submit_assignment(
            asg_b["id"], submit_assignment_payload(4, fresh_version),
            make_committee_member_headers(member_c["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE.value, expected_status=403)
        assert get_assignment(asg_b["id"])["status"] == "PENDING"
