"""Provider roster and committee membership: creation defaults, computed
fields, uniqueness constraints, pagination, and the member activation cycle."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_committee_member,
    assert_instant_equals,
    assert_provider,
    assign_reviewer,
    create_case,
    create_committee_member_payload,
    create_provider,
    create_provider_payload,
    get_assignment,
    get_member,
    screen_case_in,
    seat_member,
    set_clock,
    submit_scores,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProviderCreation:
    def test_provider_create_returns_system_fields(self, quality_director_headers):
        """PRD §2.4: "`id` (string): a unique, server-minted identifier
        formatted as a UUID, with no type prefix."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments with every modification to the resource."
        PRD §2.5: "At startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; before any administrative call it remains at
        this default and never falls back to wall-clock time."

        Design: Corner/entities/provider_create_defaults_and_system_fields
        """
        resp = api_client.create_provider(
            create_provider_payload(full_name="Sys Fields", specialty="SURGERY"),
            quality_director_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_provider(data)
        assert data["version"] == 1, f"new resource version must be 1, got {data['version']}"
        assert_instant_equals(data["created_at"], "2026-08-01T00:00:00Z")

        fetched = validate_success(
            api_client.get_provider(data["id"], quality_director_headers))
        assert fetched["id"] == data["id"]
        assert fetched["full_name"] == "Sys Fields"
        assert fetched["specialty"] == "SURGERY"

    def test_provider_create_missing_specialty_returns_400(self, quality_director_headers):
        """PRD §3.1: "A `QualityDirector` registers each provider with a
        non-empty `full_name` and a `specialty` drawn from exactly eight values".
        PRD §2.8: "Required fields present, enum values valid, datetimes
        well-formed, strings non-empty (`ERR_VALIDATION`, 400)".

        Design: Corner/entities/provider_create_missing_required_returns_400
        """
        resp = api_client.create_provider({"full_name": "No Spec"}, quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=400)

    def test_provider_get_not_found_returns_404(self, quality_director_headers):
        """PRD §2.8: "The 404 variant names the resource that failed to
        resolve: `ERR_PROVIDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_CASE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_CONFLICT_NOT_FOUND`, `ERR_FOCUSED_REVIEW_NOT_FOUND`,
        `ERR_FOCUS_GROUP_NOT_FOUND`, or `ERR_MEMBERSHIP_NOT_FOUND`."

        Design: Corner/entities/provider_get_not_found_returns_404
        """
        resp = api_client.get_provider(NON_EXISTENT_UUID, quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_FOUND.value, expected_status=404)

    def test_provider_list_pagination_envelope(self, quality_director_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; it defaults to 10 when omitted, with a minimum of 1
        and a maximum of 100. The `offset` parameter specifies how many items
        to skip and defaults to 0."
        PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by their creation timestamp in ascending order."

        Design: Corner/endpoints/provider_list_pagination_envelope
        """
        p1 = create_provider("Page One", "SURGERY")
        # Move the logical clock so the two creation timestamps differ and the
        # creation-order sort is fully determined.
        set_clock("2026-08-02T00:00:00Z")
        p2 = create_provider("Page Two", "CARDIOLOGY")

        page1, meta1 = validate_paginated(
            api_client.list_providers(quality_director_headers,
                                      params={"limit": 1, "offset": 0}))
        assert len(page1) == 1 and page1[0]["id"] == p1["id"]
        assert meta1["total_count"] == 2 and meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api_client.list_providers(quality_director_headers,
                                      params={"limit": 1, "offset": 1}))
        assert len(page2) == 1 and page2[0]["id"] == p2["id"]
        assert meta2["total_count"] == 2 and meta2["has_more"] is False


class TestCommitteeMembership:
    def test_member_specialty_denormalized_from_provider(self, quality_director_headers):
        """PRD §3.1: "The new member's `specialty` is denormalized from the
        referenced provider's record at creation time — any client-supplied
        `specialty` is ignored — and the member starts `ACTIVE` with a
        `reliability_completed_count` of 0."

        Design: Corner/entities/committee_member_specialty_computed_input_ignored
        """
        provider = create_provider("Spec Src", "SURGERY")
        resp = api_client.create_committee_member(
            create_committee_member_payload(
                provider_id=provider["id"], member_role="MEMBER",
                specialty="PSYCHIATRY"),
            quality_director_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_committee_member(data)
        assert data["specialty"] == "SURGERY", (
            f"specialty must be denormalized from the provider, got {data['specialty']}")
        assert data["status"] == "ACTIVE"
        assert data["reliability_completed_count"] == 0

    def test_member_starts_active(self, quality_director_headers):
        """PRD §3.1: "the member starts `ACTIVE` with a
        `reliability_completed_count` of 0."

        Design: Corner/state_machines/member_initial_state_active
        """
        provider = create_provider("Init Member", "CARDIOLOGY")
        resp = api_client.create_committee_member(
            create_committee_member_payload(provider_id=provider["id"], member_role="MEMBER"),
            quality_director_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"

    def test_second_active_membership_for_same_provider_rejected(self, quality_director_headers):
        """PRD §3.1: "At most one `ACTIVE` membership may exist per provider:
        seating or reactivating a member while another `ACTIVE` membership for
        the same provider exists is rejected with
        `ERR_MEMBER_ALREADY_ACTIVE_FOR_PROVIDER`."

        Design: Corner/validations/duplicate_active_membership_rejected
        """
        provider = create_provider("Dup Seat", "PEDIATRICS")
        seat_member(provider["id"], "MEMBER")
        resp = api_client.create_committee_member(
            create_committee_member_payload(provider_id=provider["id"], member_role="CHAIR"),
            quality_director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_ALREADY_ACTIVE_FOR_PROVIDER.value,
                       expected_status=409)


class TestMemberDeactivationCycle:
    def test_deactivation_waives_pending_assignments(self, quality_director_headers):
        """PRD §3.1: "Deactivation moves a member from `ACTIVE` to `INACTIVE`
        and ripples through their workload: every `PENDING` assignment held by
        that member flips to `WAIVED`, and each housing case has its `version`
        incremented and `updated_at` refreshed without any change to the
        case's own status."

        Design: Difficulty/non_linear_state_machine/member_cyclic_deactivate_reactivate
        """
        subject = create_provider("Subj Five", "SURGERY")
        member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        case = create_case(subject["id"], referral_source="INCIDENT_REPORT",
                           description="cycle case")
        screen_case_in(case["id"])
        assignment = assign_reviewer(case["id"], member["id"])

        deactivated = validate_success(
            api_client.deactivate_committee_member(member["id"], quality_director_headers))
        assert deactivated["status"] == "INACTIVE"
        waived = get_assignment(assignment["id"])
        assert waived["status"] == "WAIVED", (
            f"PENDING assignment must flip to WAIVED on deactivation, got {waived['status']}")

    def test_reactivation_does_not_unwaive_assignments(self, quality_director_headers):
        """PRD §3.1: "Reactivation returns an `INACTIVE` member to `ACTIVE` —
        subject to the one-active-membership rule above — but performs no
        retroactive un-waiver: previously `WAIVED` assignments stay `WAIVED`."
        PRD §3.1: "The member's `SUBMITTED` assignments and
        `reliability_completed_count` are untouched by deactivation."

        Design: Difficulty/non_linear_state_machine/member_cyclic_deactivate_reactivate
        """
        subject = create_provider("Subj Five", "SURGERY")
        member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        case = create_case(subject["id"], referral_source="INCIDENT_REPORT",
                           description="cycle case")
        screen_case_in(case["id"])
        assignment = assign_reviewer(case["id"], member["id"])

        api_client.deactivate_committee_member(member["id"], quality_director_headers)
        reactivated = validate_success(
            api_client.activate_committee_member(member["id"], quality_director_headers))
        assert reactivated["status"] == "ACTIVE"

        still_waived = get_assignment(assignment["id"])
        assert still_waived["status"] == "WAIVED", (
            "reactivation must not un-waive previously WAIVED assignments")
        member_after = get_member(member["id"])
        assert member_after["reliability_completed_count"] == 0


class TestMemberCycleConservesReliabilityLedger:
    def _setup_submitted_member(self):
        subject = create_provider("Subj TwentyOne", "PEDIATRICS")
        member_b = seat_member(create_provider("Rev B", "PEDIATRICS")["id"], "MEMBER")
        member_c = seat_member(create_provider("Rev C", "SURGERY")["id"], "MEMBER")
        case = create_case(subject["id"], description="ledger case")
        screen_case_in(case["id"])
        asg_b = assign_reviewer(case["id"], member_b["id"])
        assign_reviewer(case["id"], member_c["id"])
        submit_scores(asg_b["id"], member_b["id"], case["id"], 5)
        return subject, member_b, case, asg_b

    def test_reliability_count_survives_deactivate_activate_cycle(self, quality_director_headers):
        """PRD §3.1: "That counter records how many of the member's
        assignments have reached `SUBMITTED`; it is incremented on submission
        and never decremented."
        PRD §3.1: "The member's `SUBMITTED` assignments and
        `reliability_completed_count` are untouched by deactivation."

        Design: Difficulty/compensating_invariant/member_cycle_conserves_reliability_ledger
        """
        _, member_b, _, _ = self._setup_submitted_member()
        before = get_member(member_b["id"])
        assert before["reliability_completed_count"] == 1

        api_client.deactivate_committee_member(member_b["id"], quality_director_headers)
        api_client.activate_committee_member(member_b["id"], quality_director_headers)

        after = get_member(member_b["id"])
        assert after["reliability_completed_count"] == 1, (
            "deactivate/activate cycle must conserve the reliability ledger")
        assert after["status"] == "ACTIVE"

    def test_submitted_assignment_survives_member_cycle(self, quality_director_headers):
        """PRD §3.1: "Deactivation moves a member from `ACTIVE` to `INACTIVE`
        and ripples through their workload: every `PENDING` assignment held by
        that member flips to `WAIVED`".
        PRD §3.1: "The member's `SUBMITTED` assignments and
        `reliability_completed_count` are untouched by deactivation."

        Design: Difficulty/compensating_invariant/member_cycle_conserves_reliability_ledger
        """
        _, member_b, case, asg_b = self._setup_submitted_member()
        api_client.deactivate_committee_member(member_b["id"], quality_director_headers)
        api_client.activate_committee_member(member_b["id"], quality_director_headers)

        asg_after = get_assignment(asg_b["id"])
        assert asg_after["status"] == "SUBMITTED", (
            "the deactivation cascade touches PENDING rows only")
        assert asg_after["care_appropriateness_score"] == 5
        case_after = validate_success(api_client.get_case(case["id"], quality_director_headers))
        assert case_after["status"] == "IN_REVIEW"
