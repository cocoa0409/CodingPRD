"""Reviewer assignment: existence checks, the conflict-avoidance chain,
the three-assignment cap, OCC stale-version rejection, waiver-driven slot
refill, and the ranked candidate query."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assign_reviewer,
    create_case,
    create_conflict_declaration_payload,
    create_provider,
    drive_case_to_notified,
    get_case,
    list_case_assignments,
    make_committee_member_headers,
    screen_case_in,
    seat_member,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

QD = TEST_USERS["quality_director_headers"]
PRC = TEST_USERS["peer_review_coordinator_headers"]


class TestAssignmentExistence:
    def test_assignment_get_not_found_returns_404(self, quality_director_headers):
        """PRD §2.8: "The 404 variant names the resource that failed to
        resolve: `ERR_PROVIDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_CASE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_CONFLICT_NOT_FOUND`, `ERR_FOCUSED_REVIEW_NOT_FOUND`,
        `ERR_FOCUS_GROUP_NOT_FOUND`, or `ERR_MEMBERSHIP_NOT_FOUND`."

        Design: Corner/entities/assignment_get_not_found_returns_404
        """
        resp = api_client.get_assignment(NON_EXISTENT_UUID, quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND.value, expected_status=404)

    def test_assignment_create_with_unknown_reviewer_returns_404(
            self, peer_review_coordinator_headers):
        """PRD §2.8: "Identifiers in the path resolve to existing rows,
        validated left to right; then foreign-key identifiers in the body
        (`reviewer_id`, `provider_id`, `member_id`, `subject_provider_id`),
        again left to right."

        Design: Corner/entities/body_fk_member_not_found_returns_404
        """
        subject = create_provider("Subj NF", "CARDIOLOGY")
        case = create_case(subject["id"], description="nf case")
        screened = screen_case_in(case["id"])
        resp = api_client.create_assignment(
            case["id"],
            {"reviewer_id": NON_EXISTENT_UUID,
             "expected_case_version": screened["version"]},
            peer_review_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, expected_status=404)

    def test_conflict_rescind_not_found_returns_404(self):
        """PRD §2.8: "The 404 variant names the resource that failed to
        resolve: `ERR_PROVIDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_CASE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_CONFLICT_NOT_FOUND`, `ERR_FOCUSED_REVIEW_NOT_FOUND`,
        `ERR_FOCUS_GROUP_NOT_FOUND`, or `ERR_MEMBERSHIP_NOT_FOUND`."

        Design: Corner/entities/conflict_rescind_not_found_returns_404
        """
        member = seat_member(create_provider("M Provider", "SURGERY")["id"], "MEMBER")
        resp = api_client.delete_conflict_declaration(
            NON_EXISTENT_UUID, make_committee_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_CONFLICT_NOT_FOUND.value, expected_status=404)


class TestConflictAvoidanceChain:
    def test_inactive_member_cannot_be_assigned(self, peer_review_coordinator_headers):
        """PRD §2.8: "Reviewer assignment enforces three checks in this
        order: the reviewer is `ACTIVE` (`ERR_REVIEWER_INACTIVE`), the
        reviewer is not the subject of the case (`ERR_REVIEWER_IS_SUBJECT`),
        and no conflict declaration links the reviewer to the subject
        (`ERR_REVIEWER_CONFLICT_DECLARED`)."
        PRD §3.1: "An `INACTIVE` member is excluded from reviewer candidacy
        and cannot be assigned to anything."

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_active_reviewer_member
        """
        subject = create_provider("Subj Fifteen", "SURGERY")
        member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        validate_success(api_client.deactivate_committee_member(member["id"], QD))
        case = create_case(subject["id"], description="gate case")
        screened = screen_case_in(case["id"])

        resp = api_client.create_assignment(
            case["id"],
            {"reviewer_id": member["id"], "expected_case_version": screened["version"]},
            peer_review_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_REVIEWER_INACTIVE.value, expected_status=422)
        assignments = list_case_assignments(case["id"])
        assert assignments == [], "the rejected assignment must not be persisted"

    def test_reactivated_member_can_be_assigned_again(self, peer_review_coordinator_headers):
        """PRD §3.1: "Reactivation returns an `INACTIVE` member to `ACTIVE`".
        PRD §2.8: "Reviewer assignment enforces three checks in this order:
        the reviewer is `ACTIVE` (`ERR_REVIEWER_INACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_active_reviewer_member
        """
        subject = create_provider("Subj Fifteen", "SURGERY")
        member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        validate_success(api_client.deactivate_committee_member(member["id"], QD))
        validate_success(api_client.activate_committee_member(member["id"], QD))
        case = create_case(subject["id"], description="gate case")
        screen_case_in(case["id"])

        assignment = assign_reviewer(case["id"], member["id"])
        assert assignment["reviewer_id"] == member["id"]
        assert assignment["status"] == "PENDING"

    def test_subject_provider_cannot_be_own_reviewer(self, peer_review_coordinator_headers):
        """PRD §2.8: "Reviewer assignment enforces three checks in this
        order: the reviewer is `ACTIVE` (`ERR_REVIEWER_INACTIVE`), the
        reviewer is not the subject of the case (`ERR_REVIEWER_IS_SUBJECT`),
        and no conflict declaration links the reviewer to the subject
        (`ERR_REVIEWER_CONFLICT_DECLARED`)."

        Design: Corner/validations/subject_provider_cannot_be_reviewer
        """
        subject = create_provider("Subj Self", "PEDIATRICS")
        member = seat_member(subject["id"], "MEMBER")
        case = create_case(subject["id"], description="self case")
        screened = screen_case_in(case["id"])
        resp = api_client.create_assignment(
            case["id"],
            {"reviewer_id": member["id"], "expected_case_version": screened["version"]},
            peer_review_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_REVIEWER_IS_SUBJECT.value, expected_status=422)

    def test_declared_conflict_blocks_assignment_until_rescinded(
            self, peer_review_coordinator_headers):
        """PRD §2.8: "no conflict declaration links the reviewer to the
        subject (`ERR_REVIEWER_CONFLICT_DECLARED`)".
        PRD §3.1: "Rescinding a declaration is a hard delete, again restricted
        to the declaring member, and it restores the member's eligibility for
        future assignments against that provider's cases."

        Design: Corner/validations/declared_conflict_blocks_assignment
        """
        subject = create_provider("Subj Conf", "SURGERY")
        member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        conflict = validate_success(api_client.create_conflict_declaration(
            member["id"],
            create_conflict_declaration_payload(provider_id=subject["id"],
                                                conflict_type="PRIOR_TREATING"),
            make_committee_member_headers(member["id"])), expected_status=201)
        case = create_case(subject["id"], description="conflict case")
        screen_case_in(case["id"])

        blocked = api_client.create_assignment(
            case["id"],
            {"reviewer_id": member["id"],
             "expected_case_version": get_case(case["id"])["version"]},
            peer_review_coordinator_headers)
        validate_error(blocked, ApiErrorId.ERR_REVIEWER_CONFLICT_DECLARED.value,
                       expected_status=422)

        deleted = api_client.delete_conflict_declaration(
            conflict["id"], make_committee_member_headers(member["id"]))
        assert deleted.status_code == 204

        assignment = assign_reviewer(case["id"], member["id"])
        assert assignment["sequence"] == 1, (
            "the blocked first attempt must not consume a sequence number")

    def test_duplicate_conflict_declaration_rejected(self):
        """PRD §3.1: "Declaring the same (`member_id`, `provider_id`) pair
        twice is rejected with `ERR_CONFLICT_ALREADY_DECLARED`."

        Design: Corner/validations/duplicate_conflict_declaration_rejected
        """
        subject = create_provider("Subj DC", "SURGERY")
        member = seat_member(create_provider("Rev B", "CARDIOLOGY")["id"], "MEMBER")
        member_headers = make_committee_member_headers(member["id"])
        validate_success(api_client.create_conflict_declaration(
            member["id"],
            create_conflict_declaration_payload(provider_id=subject["id"],
                                                conflict_type="FAMILY"),
            member_headers), expected_status=201)
        resp = api_client.create_conflict_declaration(
            member["id"],
            create_conflict_declaration_payload(provider_id=subject["id"],
                                                conflict_type="FINANCIAL"),
            member_headers)
        validate_error(resp, ApiErrorId.ERR_CONFLICT_ALREADY_DECLARED.value, expected_status=409)
        declarations = validate_success(
            api_client.list_member_conflict_declarations(member["id"], QD))
        assert len(declarations) == 1


class TestAssignmentCapAndSequences:
    def test_duplicate_assignment_rejected(self, peer_review_coordinator_headers):
        """PRD §3.3: "a reviewer who already holds a non-`WAIVED` assignment
        on the case is rejected with `ERR_REVIEWER_ALREADY_ASSIGNED`".

        Design: Corner/validations/duplicate_assignment_rejected
        """
        subject = create_provider("Subj Dup", "SURGERY")
        member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        case = create_case(subject["id"], description="dup case")
        screen_case_in(case["id"])
        assign_reviewer(case["id"], member["id"])

        resp = api_client.create_assignment(
            case["id"],
            {"reviewer_id": member["id"],
             "expected_case_version": get_case(case["id"])["version"]},
            peer_review_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_REVIEWER_ALREADY_ASSIGNED.value,
                       expected_status=422)
        assignments = list_case_assignments(case["id"])
        assert len(assignments) == 1

    def test_third_assignment_succeeds_at_cap(self, peer_review_coordinator_headers):
        """PRD §3.3: "a case that already has three non-`WAIVED` assignments
        is rejected with `ERR_CASE_FULLY_ASSIGNED`."
        PRD §3.3: "Its `sequence` is the count of all existing assignments on
        that case — of any status, `WAIVED` included — plus one".

        Design: Difficulty/boundary_precision_check/assignment_count_cap_boundary
        """
        subject = create_provider("Subj Thirteen", "SURGERY")
        members = [seat_member(create_provider(f"Rev {c}", s)["id"], "MEMBER")
                   for c, s in [("B", "SURGERY"), ("C", "CARDIOLOGY"),
                                ("D", "PEDIATRICS"), ("E", "EMERGENCY_MEDICINE")]]
        case = create_case(subject["id"], referral_source="INCIDENT_REPORT",
                           description="cap case")
        screen_case_in(case["id"])
        assign_reviewer(case["id"], members[0]["id"])
        assign_reviewer(case["id"], members[1]["id"])

        third = assign_reviewer(case["id"], members[2]["id"])
        assert third["sequence"] == 3, (
            f"the third create moves the count from 2 to 3, got sequence {third['sequence']}")

    def test_fourth_assignment_rejected_when_case_full(self, peer_review_coordinator_headers):
        """PRD §3.3: "a case that already has three non-`WAIVED` assignments
        is rejected with `ERR_CASE_FULLY_ASSIGNED`."

        Design: Difficulty/boundary_precision_check/assignment_count_cap_boundary
        """
        subject = create_provider("Subj Thirteen", "SURGERY")
        members = [seat_member(create_provider(f"Rev {c}", s)["id"], "MEMBER")
                   for c, s in [("B", "SURGERY"), ("C", "CARDIOLOGY"),
                                ("D", "PEDIATRICS"), ("E", "EMERGENCY_MEDICINE")]]
        case = create_case(subject["id"], referral_source="INCIDENT_REPORT",
                           description="cap case")
        screen_case_in(case["id"])
        for m in members[:3]:
            assign_reviewer(case["id"], m["id"])

        resp = api_client.create_assignment(
            case["id"],
            {"reviewer_id": members[3]["id"],
             "expected_case_version": get_case(case["id"])["version"]},
            peer_review_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_CASE_FULLY_ASSIGNED.value, expected_status=409)
        assignments = list_case_assignments(case["id"])
        assert len(assignments) == 3, "the rejected fourth assignment must not be persisted"

    def test_waived_slot_frees_capacity(self, quality_director_headers):
        """PRD §3.1: "A `WAIVED` assignment frees its slot toward the per-case
        cap of three non-`WAIVED` assignments, so the coordinator may seat a
        replacement reviewer."
        PRD §3.3: "sequence numbers are never reused, so a waived slot still
        consumes its ordinal."

        Design: Corner/validations/waived_slot_frees_capacity
        """
        subject = create_provider("Subj Cap", "CARDIOLOGY")
        members = [seat_member(create_provider(f"Rev {c}", s)["id"], "MEMBER")
                   for c, s in [("B", "CARDIOLOGY"), ("C", "SURGERY"),
                                ("D", "PEDIATRICS"), ("E", "EMERGENCY_MEDICINE")]]
        case = create_case(subject["id"], description="cap free case")
        screen_case_in(case["id"])
        for m in members[:3]:
            assign_reviewer(case["id"], m["id"])

        validate_success(
            api_client.deactivate_committee_member(members[2]["id"], QD))
        replacement = assign_reviewer(case["id"], members[3]["id"])
        assert replacement["sequence"] == 4, (
            "the WAIVED row freed its cap slot but not its sequence number")
        case_after = get_case(case["id"])
        assert case_after["status"] == "ASSIGNED", (
            "waiver and refill cause no case status change")

    def test_stale_case_version_on_assignment_create_returns_412(
            self, peer_review_coordinator_headers):
        """PRD §2.7: "If the case's current `version` has advanced past that
        value — for instance because another writer has already added a
        reviewer (legitimately consuming one of the three assignment slots) or
        another reviewer's submission has already advanced the case's status —
        the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing
        the client from acting on a case state it has not observed."

        Design: Corner/complexity_layers/occ_stale_assignment_create_returns_412
        """
        subject = create_provider("Subj OCC2", "PEDIATRICS")
        member_b = seat_member(create_provider("Rev B", "PEDIATRICS")["id"], "MEMBER")
        member_c = seat_member(create_provider("Rev C", "SURGERY")["id"], "MEMBER")
        case = create_case(subject["id"], description="occ case 2")
        screened = screen_case_in(case["id"])
        stale_version = screened["version"]

        created = api_client.create_assignment(
            case["id"],
            {"reviewer_id": member_b["id"], "expected_case_version": stale_version},
            peer_review_coordinator_headers)
        validate_success(created, expected_status=201)

        resp = api_client.create_assignment(
            case["id"],
            {"reviewer_id": member_c["id"], "expected_case_version": stale_version},
            peer_review_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
        assignments = list_case_assignments(case["id"])
        assert len(assignments) == 1


class TestReviewerCandidates:
    def test_candidate_ranking_specialty_reliability_created_tiebreak(
            self, peer_review_coordinator_headers):
        """PRD §3.3: "Eligible candidates are ranked with same-specialty
        members first — those whose `specialty` equals the subject provider's
        specialty — then by `reliability_completed_count` with higher counts
        first, then by member `created_at` with the earliest first; the member
        `id` is never used as a tie-break."

        Design: Corner/calculations/candidate_ranking_specialty_reliability_created_tiebreak
        """
        subject_q = create_provider("Subj Q", "INTERNAL_MEDICINE")
        subject_r = create_provider("Subj R", "SURGERY")

        # Seat members one second apart so the created_at tie-break is strict.
        seat_order = []
        chair_provider = create_provider("Chair A", "INTERNAL_MEDICINE")
        seat_order.append(seat_member(chair_provider["id"], "CHAIR"))  # A
        for name, spec in [("Rev B", "SURGERY"), ("Rev C", "INTERNAL_MEDICINE"),
                           ("Rev D", "SURGERY"), ("Rev E", "SURGERY")]:
            set_clock(f"2026-08-01T00:00:0{len(seat_order)}Z")
            seat_order.append(seat_member(create_provider(name, spec)["id"], "MEMBER"))
        m_a, m_b, m_c, m_d, m_e = seat_order

        # Resolve a case for Q reviewed by B, C, D (each earns reliability 1).
        ctx = {"subject": subject_q, "chair": m_a, "members": [m_b, m_c, m_d]}
        case_x, _, _ = drive_case_to_notified(ctx, scores=((5, None), (5, None), (5, None)))
        set_clock("2026-08-16T00:00:00Z")
        validate_success(api_client.close_no_response(case_x["id"], QD))

        case_y = create_case(subject_r["id"], referred_at="2026-08-16T00:00:00Z",
                             description="target case")
        screen_case_in(case_y["id"])

        data, meta = validate_paginated(
            api_client.get_reviewer_candidates(case_y["id"], peer_review_coordinator_headers))
        got = [c["id"] for c in data]
        expected = [m_b["id"], m_d["id"], m_e["id"], m_c["id"], m_a["id"]]
        assert got == expected, (
            f"expected ranking {expected} (same-specialty first, then "
            f"reliability_completed_count DESC, then created_at ASC), got {got}")

    def test_candidate_pool_empty_returns_empty_list(self, peer_review_coordinator_headers):
        """PRD §3.3: "a candidate must be `ACTIVE`, must not be the subject of
        the case (their `provider_id` must differ from the case's
        `subject_provider_id`), must hold no conflict declaration against the
        subject provider, and must not already hold a non-`WAIVED` assignment
        on the case."
        PRD §3.3: "An empty candidate pool is not an error: the query returns
        200 with an empty list."

        Design: Corner/calculations/candidate_pool_empty_returns_empty_list
        """
        subject = create_provider("Subj Solo", "SURGERY")
        seat_member(subject["id"], "MEMBER")
        case = create_case(subject["id"], description="empty pool case")
        screen_case_in(case["id"])

        data, meta = validate_paginated(
            api_client.get_reviewer_candidates(case["id"], peer_review_coordinator_headers))
        assert data == [], "the self-review exclusion empties the pool"
        assert meta["total_count"] == 0
