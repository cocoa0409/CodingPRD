"""Expedited review routing, reviewer assignment lifecycle, conflict
management, and the member workload counter (PRD §2.4, §2.9, §3.4, §3.5).
"""
from test_helpers import (
    ApiErrorId,
    adjudicate_declaration,
    approve_consent_document,
    assert_timestamp_equals,
    create_draft_protocol,
    declare_conflict,
    drive_to_under_expedited_review,
    file_recommendation,
    get_protocol,
    get_success_data,
    make_chair_headers,
    make_pi_headers,
    offer_assignment,
    register_chair,
    register_investigator,
    register_member,
    respond_to_assignment,
    set_clock,
    setup_approved_protocol,
    submit_protocol_ok,
    unique_email,
    upload_consent,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

COORDINATOR = TEST_USERS["coordinator_headers"]


def _under_expedited_with_consent(approve_consent=True):
    """Investigator + chair + protocol UNDER_EXPEDITED_REVIEW with one consent
    document (approved only when approve_consent). Returns dict."""
    inv = register_investigator()
    chair = register_chair(email=unique_email("chair"))
    proto = create_draft_protocol(inv["id"], claimed_review_level="EXPEDITED",
                                  risk_level="MINIMAL")
    cd = upload_consent(proto["id"], inv["id"])
    if approve_consent:
        approve_consent_document(cd["id"], chair["id"])
    drive_to_under_expedited_review(proto["id"], inv["id"])
    return {"investigator": inv, "chair": chair,
            "protocol": get_protocol(proto["id"]), "consent_document": cd}


def _member(email_prefix):
    return register_member("SCIENTIST", email=unique_email(email_prefix))


class TestExpeditedRouting:
    def test_expedited_disapprove_forces_full_board_referral(self, api):
        """PRD §3.5: "No non-voided submitted recommendation may be
        `DISAPPROVE` — expedited review cannot disapprove, so that situation is
        rejected with `ERR_EXPEDITED_DISAPPROVE_REQUIRES_BOARD` and the study
        belongs in front of the convened board instead." PRD §3.5: "Referring
        to the full board moves the protocol to `AWAITING_FULL_BOARD` with no
        further checks."

        Design: Corner/state_machines/expedited_disapprove_forces_full_board_referral
        """
        s = _under_expedited_with_consent()
        proto, chair = s["protocol"], s["chair"]
        rev1 = _member("revd1")
        rev2 = register_member("NON_SCIENTIST", email=unique_email("revd2"))

        a1 = offer_assignment(proto["id"], reviewer_id=rev1["id"], reviewer_role="PRIMARY")
        a2 = offer_assignment(proto["id"], reviewer_id=rev2["id"], reviewer_role="SECONDARY")
        respond_to_assignment(a1["id"], rev1["id"], "ACCEPT")
        respond_to_assignment(a2["id"], rev2["id"], "ACCEPT")
        file_recommendation(a1["id"], rev1["id"], "DISAPPROVE")
        file_recommendation(a2["id"], rev2["id"], "APPROVE")

        resp = api.expedited_determination(
            proto["id"], {"outcome": "APPROVE"}, make_chair_headers(chair["id"])
        )
        validate_error(resp, ApiErrorId.ERR_EXPEDITED_DISAPPROVE_REQUIRES_BOARD)

        data = validate_success(
            api.expedited_determination(
                proto["id"], {"outcome": "REFER_TO_FULL_BOARD"},
                make_chair_headers(chair["id"]),
            )
        )
        assert data["status"] == "AWAITING_FULL_BOARD"

    def test_expedited_approve_requires_two_recommendations(self, api):
        """PRD §3.5: "At least two review assignments must stand in `SUBMITTED`
        with `recommendation_voided` false, else
        `ERR_INSUFFICIENT_RECOMMENDATIONS`."

        Design: Corner/validations/expedited_approve_requires_two_recommendations
        """
        s = _under_expedited_with_consent()
        proto, chair = s["protocol"], s["chair"]
        rev1 = _member("revi1")

        a1 = offer_assignment(proto["id"], reviewer_id=rev1["id"], reviewer_role="PRIMARY")
        respond_to_assignment(a1["id"], rev1["id"], "ACCEPT")
        file_recommendation(a1["id"], rev1["id"], "APPROVE")

        resp = api.expedited_determination(
            proto["id"], {"outcome": "APPROVE"}, make_chair_headers(chair["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_RECOMMENDATIONS)
        assert get_protocol(proto["id"])["status"] == "UNDER_EXPEDITED_REVIEW"

    def test_approval_requires_approved_consent_document(self, api):
        """PRD §3.5: "And at least one consent document of the protocol must be
        `APPROVED`, else `ERR_NO_APPROVED_CONSENT`."

        Design: Corner/validations/approval_requires_approved_consent_document
        """
        s = _under_expedited_with_consent(approve_consent=False)
        proto, chair = s["protocol"], s["chair"]
        rev1 = _member("revn1")
        rev2 = register_member("NON_SCIENTIST", email=unique_email("revn2"))

        for idx, rev in enumerate((rev1, rev2)):
            role = "PRIMARY" if idx == 0 else "SECONDARY"
            asg = offer_assignment(proto["id"], reviewer_id=rev["id"], reviewer_role=role)
            respond_to_assignment(asg["id"], rev["id"], "ACCEPT")
            file_recommendation(asg["id"], rev["id"], "APPROVE")

        resp = api.expedited_determination(
            proto["id"], {"outcome": "APPROVE"}, make_chair_headers(chair["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_CONSENT)
        assert get_protocol(proto["id"])["status"] == "UNDER_EXPEDITED_REVIEW"


class TestAssignmentUniquenessAndPool:
    def test_duplicate_assignment_rejected(self, api):
        """PRD §3.4: "Uniqueness is enforced per protocol and reviewer: a
        second assignment in `OFFERED`, `ACCEPTED`, or `SUBMITTED` for the same
        pairing is rejected with `ERR_DUPLICATE_ASSIGNMENT` (HTTP 409)."

        Design: Corner/validations/duplicate_assignment_rejected
        """
        s = _under_expedited_with_consent()
        proto = s["protocol"]
        rev1 = _member("revda")

        a1 = offer_assignment(proto["id"], reviewer_id=rev1["id"], reviewer_role="PRIMARY")

        resp = api.create_review_assignment(
            proto["id"], {"reviewer_id": rev1["id"], "reviewer_role": "SECONDARY"},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT)

        # DECLINED is terminal and frees the (protocol, reviewer) pairing.
        respond_to_assignment(a1["id"], rev1["id"], "DECLINE")
        data = validate_success(
            api.create_review_assignment(
                proto["id"], {"reviewer_id": rev1["id"], "reviewer_role": "SECONDARY"},
                COORDINATOR,
            ),
            201,  # PRD §4: creates return 201 Created
        )
        assert data["status"] == "OFFERED"

    def test_auto_assign_empty_pool_rejected(self, api):
        """PRD §3.4: "The candidate pool is every `ACTIVE` member whose
        `active_assignment_count` is below the five-assignment ceiling, who
        holds no `CONFLICTED` declaration on this protocol, and who has no
        existing assignment on this protocol in `OFFERED`, `ACCEPTED`, or
        `SUBMITTED`." PRD §3.4: "An empty pool is rejected with
        `ERR_NO_ELIGIBLE_REVIEWER` (HTTP 422)."

        Design: Corner/validations/auto_assign_empty_pool_rejected
        """
        inv = register_investigator()
        proto = create_draft_protocol(inv["id"], title="Empty Pool")
        upload_consent(proto["id"], inv["id"], file_ref="s3://consent/empty.pdf")
        drive_to_under_expedited_review(proto["id"], inv["id"])

        # No IrbMember rows exist at all, so the candidate pool is empty.
        resp = api.create_review_assignment(proto["id"], {}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_REVIEWER)

    def test_reviewer_auto_selection_ranking_and_tiebreak(self, api):
        """PRD §3.4: "Candidates are ranked by `active_assignment_count`
        ascending, ties broken by the member's `created_at` ascending — never
        by `id` — and the first candidate receives the offer."

        Design: Corner/calculations/reviewer_auto_selection_ranking_and_tiebreak
        """
        inv = register_investigator()
        m_first = _member("first")
        m_second = register_member("NON_SCIENTIST", email=unique_email("second"))

        p1 = create_draft_protocol(inv["id"], title="Sel 1")
        upload_consent(p1["id"], inv["id"], file_ref="s3://consent/sel1.pdf")
        drive_to_under_expedited_review(p1["id"], inv["id"])
        p2 = create_draft_protocol(inv["id"], title="Sel 2")
        upload_consent(p2["id"], inv["id"], file_ref="s3://consent/sel2.pdf")
        drive_to_under_expedited_review(p2["id"], inv["id"])

        auto1 = validate_success(
            api.create_review_assignment(p1["id"], {}, COORDINATOR), 201)
        auto2 = validate_success(
            api.create_review_assignment(p2["id"], {}, COORDINATOR), 201)

        assert auto1["reviewer_id"] == m_first["id"], (
            "Tie at 0 active assignments must break by created_at ascending"
        )
        assert auto2["reviewer_id"] == m_second["id"], (
            "Fewest active assignments (0) beats the member already holding 1"
        )
        m1_after = get_success_data(api.get_member(m_first["id"], COORDINATOR))
        m2_after = get_success_data(api.get_member(m_second["id"], COORDINATOR))
        assert m1_after["active_assignment_count"] == 1
        assert m2_after["active_assignment_count"] == 1


class TestMemberWorkloadCounter:
    def _two_under_expedited_protocols(self):
        inv = register_investigator()
        rev = _member("revload")
        protocols = []
        for title in ("Load Study 1", "Load Study 2"):
            proto = create_draft_protocol(inv["id"], title=title)
            upload_consent(proto["id"], inv["id"])
            drive_to_under_expedited_review(proto["id"], inv["id"])
            protocols.append(proto)
        return inv, rev, protocols

    def _count(self, api, member_id):
        return get_success_data(api.get_member(member_id, COORDINATOR))[
            "active_assignment_count"
        ]

    def test_member_workload_accept_then_submit_round_trip(self, api):
        """PRD §3.4: "the assignment starts in `OFFERED`, and the member's
        `active_assignment_count` rises by one, since both `OFFERED` and
        `ACCEPTED` assignments count against a member's load." and "Accepting
        moves the assignment to `ACCEPTED` and leaves the member's count
        unchanged" and "Filing moves the assignment to the terminal `SUBMITTED`
        state, stores the recommendation, and decrements the member's count by
        one."

        Design: Difficulty/compensating_invariant/member_workload_counter_round_trip
        """
        _inv, rev, (p1, _p2) = self._two_under_expedited_protocols()
        assert self._count(api, rev["id"]) == 0

        a1 = offer_assignment(p1["id"], reviewer_id=rev["id"], reviewer_role="PRIMARY")
        assert self._count(api, rev["id"]) == 1, "OFFERED rises the count by one"

        respond_to_assignment(a1["id"], rev["id"], "ACCEPT")
        assert self._count(api, rev["id"]) == 1, "ACCEPTED leaves the count unchanged"

        submitted = file_recommendation(a1["id"], rev["id"], "APPROVE")
        assert submitted["status"] == "SUBMITTED"
        assert self._count(api, rev["id"]) == 0, (
            "SUBMITTED decrements the count, restoring the baseline"
        )

    def test_member_workload_decline_round_trip(self, api):
        """PRD §3.4: "declining moves it to `DECLINED` and recusing to
        `RECUSED`, each decrementing the count by one." The create/decline pair
        is a second forward/compensation round trip back to baseline zero.

        Design: Difficulty/compensating_invariant/member_workload_counter_round_trip
        """
        _inv, rev, (_p1, p2) = self._two_under_expedited_protocols()
        assert self._count(api, rev["id"]) == 0

        a2 = offer_assignment(p2["id"], reviewer_id=rev["id"], reviewer_role="PRIMARY")
        assert self._count(api, rev["id"]) == 1

        declined = respond_to_assignment(a2["id"], rev["id"], "DECLINE")
        assert declined["status"] == "DECLINED"
        assert self._count(api, rev["id"]) == 0, (
            "DECLINED decrements the count, restoring the baseline"
        )


class TestAssignmentOfferExpiry:
    def test_assignment_offer_expires_via_clock_sweep(self, api):
        """PRD §3.4: "The system stamps `offered_at` with the logical instant
        of creation and sets `response_deadline_at` seven days later" and
        "Offers left unanswered past their `response_deadline_at` are swept to
        `EXPIRED` by the clock, again decrementing the count."

        Design: Corner/state_machines/assignment_offer_expires_via_clock_sweep
        """
        s = _under_expedited_with_consent()
        proto = s["protocol"]
        rev1 = _member("revx1")

        a1 = offer_assignment(proto["id"], reviewer_id=rev1["id"], reviewer_role="PRIMARY")
        # Offered at the startup clock 2026-05-01T00:00:00Z; deadline +7 days.
        assert_timestamp_equals(a1["response_deadline_at"], "2026-05-08T00:00:00Z")
        assert a1["status"] == "OFFERED"

        set_clock("2026-05-09T00:00:00Z")

        after = get_success_data(api.get_review_assignment(a1["id"], COORDINATOR))
        assert after["status"] == "EXPIRED"
        assert_timestamp_equals(after["response_deadline_at"], "2026-05-08T00:00:00Z")
        member = get_success_data(api.get_member(rev1["id"], COORDINATOR))
        assert member["active_assignment_count"] == 0


class TestConflictSafetyPriority:
    def _conflicted_reviewer_with_submitted_assignment(self):
        """Protocol UNDER_EXPEDITED_REVIEW; rev1's assignment SUBMITTED; rev1's
        FINANCIAL declaration adjudicated CONFLICTED (voiding the submitted
        recommendation)."""
        s = _under_expedited_with_consent()
        proto, chair = s["protocol"], s["chair"]
        rev1 = _member("rev1")
        a1 = offer_assignment(proto["id"], reviewer_id=rev1["id"], reviewer_role="PRIMARY")
        respond_to_assignment(a1["id"], rev1["id"], "ACCEPT")
        file_recommendation(a1["id"], rev1["id"], "APPROVE")
        decl = declare_conflict(
            proto["id"], rev1["id"], declaration_type="FINANCIAL",
            detail="holds sponsor stock",
        )
        adjudicate_declaration(decl["id"], chair["id"], "CONFLICTED")
        return s, rev1, a1

    def test_conflict_safety_beats_duplicate_constraint(self, api):
        """PRD §3.4: "any residual attempt to accept an offer or file a
        recommendation while holding a `CONFLICTED` declaration on the protocol
        — as well as any coordinator attempt to offer such a reviewer an
        assignment — is rejected with `ERR_REVIEWER_CONFLICTED`." PRD §2.9
        lists "5. **Business safety gates** — ... reviewer and chair conflict
        checks (`ERR_REVIEWER_CONFLICTED`, `ERR_CHAIR_CONFLICTED`)" ahead of
        "6. **Business constraints** — ... assignment uniqueness and pool
        availability (`ERR_DUPLICATE_ASSIGNMENT`, `ERR_NO_ELIGIBLE_REVIEWER`)".

        Design: Difficulty/priority_pair_validation_conflict/assignment_conflict_safety_beats_duplicate_constraint
        """
        s, rev1, _a1 = self._conflicted_reviewer_with_submitted_assignment()
        proto = s["protocol"]

        # Re-offering rev1 violates both the conflict gate and the uniqueness
        # constraint (SUBMITTED is in the uniqueness set); safety wins.
        resp = api.create_review_assignment(
            proto["id"], {"reviewer_id": rev1["id"], "reviewer_role": "SECONDARY"},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_CONFLICTED)

    def test_conflicted_adjudication_voids_submitted_recommendation(self, api):
        """PRD §3.4: "every assignment already `SUBMITTED` has its
        `recommendation_voided` flag set true, excluding the recommendation
        from expedited completeness counts and from vote eligibility."

        Design: Difficulty/priority_pair_validation_conflict/assignment_conflict_safety_beats_duplicate_constraint
        """
        _s, _rev1, a1 = self._conflicted_reviewer_with_submitted_assignment()
        after = get_success_data(api.get_review_assignment(a1["id"], COORDINATOR))
        assert after["status"] == "SUBMITTED"
        assert after["recommendation_voided"] is True


class TestExpeditedApprovalSideEffects:
    def test_expedited_approval_creates_continuing_review_server_side(self, api):
        """PRD §3.5: "creates the first continuing-review cycle: `cycle_index`
        1, `due_at` equal to `approval_expires_at`, `window_opens_at` sixty
        days before the due date, status `PENDING_SUBMISSION`."

        Design: Corner/endpoints/expedited_approval_creates_continuing_review_server_side
        """
        scenario = setup_approved_protocol(risk_level="MINIMAL")
        proto = scenario["protocol"]

        rows, meta = validate_paginated(
            api.list_continuing_reviews(proto["id"], COORDINATOR)
        )
        assert len(rows) == 1, f"Exactly one cycle must exist, got {len(rows)}"
        cr = rows[0]
        assert cr["cycle_index"] == 1
        assert cr["status"] == "PENDING_SUBMISSION"
        # MINIMAL approval at 2026-05-01T00:00:00Z: due +365d, window -60d.
        assert_timestamp_equals(cr["due_at"], "2027-05-01T00:00:00Z")
        assert_timestamp_equals(cr["window_opens_at"], "2027-03-02T00:00:00Z")
