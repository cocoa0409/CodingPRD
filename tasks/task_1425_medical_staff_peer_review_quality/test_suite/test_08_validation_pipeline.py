"""The fixed validation pipeline: authentication first, and the pinned
precedence between pipeline stages when several violations coincide."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assign_reviewer,
    create_case,
    create_conflict_declaration_payload,
    create_provider,
    get_case,
    list_case_assignments,
    make_committee_member_headers,
    make_provider_headers,
    screen_case_in,
    seat_member,
    setup_case_in_deliberation,
    submit_assignment_payload,
    submit_scores,
    validate_error,
    validate_success,
)

QD = TEST_USERS["quality_director_headers"]
PRC = TEST_USERS["peer_review_coordinator_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request that is missing either header, or whose role
        value is not one of these four, is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/missing_auth_header_returns_unauthenticated
        """
        resp = api.list_providers(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


class TestRoleDenialPreemptsStateViolation:
    def _submitted_assignment(self):
        """Case with B assigned; B has already submitted (so a second submit
        is a state violation waiting to happen)."""
        subject = create_provider("Subj Ten", "CARDIOLOGY")
        member_b = seat_member(create_provider("Rev B", "CARDIOLOGY")["id"], "MEMBER")
        seat_member(create_provider("Rev C", "SURGERY")["id"], "MEMBER")
        case = create_case(subject["id"], description="priority case")
        screen_case_in(case["id"])
        asg_b = assign_reviewer(case["id"], member_b["id"])
        submit_scores(asg_b["id"], member_b["id"], case["id"], 4)
        return subject, member_b, case, asg_b

    def test_provider_role_denial_preempts_state_violation_on_submit(self):
        """PRD §2.8: "Every request passes through a fixed validation
        pipeline. The stages below are evaluated in order, and a failure at an
        earlier stage masks every later check — the reported error is always
        the first one that fires."
        PRD §2.8: "Role authorization. The acting role appears in the
        endpoint's authorized role list; otherwise `ERR_UNAUTHORIZED_ROLE`
        (403)."

        Design: Difficulty/priority_pair_validation_conflict/role_denial_prior_to_state_violation
        """
        subject, _, case, asg_b = self._submitted_assignment()
        fresh_version = get_case(case["id"])["version"]
        resp = api_client.submit_assignment(
            asg_b["id"], submit_assignment_payload(3, fresh_version),
            make_provider_headers(subject["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, expected_status=403)

    def test_coordinator_role_denial_preempts_state_violation_on_submit(self):
        """PRD §2.8: "Every request passes through a fixed validation
        pipeline. The stages below are evaluated in order, and a failure at an
        earlier stage masks every later check — the reported error is always
        the first one that fires."
        PRD §2.8: "State legality. The target entity must be in a state from
        which the requested transition exists; otherwise `ERR_INVALID_STATE`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/role_denial_prior_to_state_violation
        """
        _, _, case, asg_b = self._submitted_assignment()
        fresh_version = get_case(case["id"])["version"]
        resp = api_client.submit_assignment(
            asg_b["id"], submit_assignment_payload(3, fresh_version), PRC)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, expected_status=403)


class TestStateViolationPreemptsConflictSafety:
    def _deliberation_case_with_extra_member(self, declare_conflict):
        """Case driven to DELIBERATION with (4,4,4); a fifth member E is
        seated and optionally holds a declared conflict against the subject."""
        ctx = setup_case_in_deliberation(
            scores=((4, None), (4, None), (4, None)),
            subject_specialty="PEDIATRICS",
            member_specialties=("PEDIATRICS", "SURGERY", "CARDIOLOGY"))
        member_e = seat_member(create_provider("Rev E", "EMERGENCY_MEDICINE")["id"], "MEMBER")
        if declare_conflict:
            validate_success(api_client.create_conflict_declaration(
                member_e["id"],
                create_conflict_declaration_payload(provider_id=ctx["subject"]["id"],
                                                    conflict_type="FINANCIAL"),
                make_committee_member_headers(member_e["id"])), expected_status=201)
        return ctx, member_e

    def test_deliberation_state_error_preempts_declared_conflict(self):
        """PRD §3.3: "The case must be in `SCREENED_IN`, `ASSIGNED`, or
        `IN_REVIEW`."
        PRD §2.8: "Every request passes through a fixed validation pipeline.
        The stages below are evaluated in order, and a failure at an earlier
        stage masks every later check — the reported error is always the first
        one that fires."

        Design: Difficulty/priority_pair_validation_conflict/state_violation_prior_to_conflict_safety
        """
        ctx, member_e = self._deliberation_case_with_extra_member(declare_conflict=True)
        resp = api_client.create_assignment(
            ctx["case"]["id"],
            {"reviewer_id": member_e["id"],
             "expected_case_version": get_case(ctx["case"]["id"])["version"]},
            PRC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_deliberation_state_error_fires_without_any_conflict(self):
        """PRD §3.3: "The case must be in `SCREENED_IN`, `ASSIGNED`, or
        `IN_REVIEW`."
        PRD §2.8: "State legality. The target entity must be in a state from
        which the requested transition exists; otherwise `ERR_INVALID_STATE`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_violation_prior_to_conflict_safety
        """
        ctx, member_e = self._deliberation_case_with_extra_member(declare_conflict=False)
        resp = api_client.create_assignment(
            ctx["case"]["id"],
            {"reviewer_id": member_e["id"],
             "expected_case_version": get_case(ctx["case"]["id"])["version"]},
            PRC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        assignments = list_case_assignments(ctx["case"]["id"])
        assert len(assignments) == 3, "no fourth assignment may be persisted"
