"""Self-study ratings and evidence: validation, lifecycle, quorum, segregation."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_rating,
    create_campus,
    create_evidence_payload,
    create_rating_payload,
    create_standard,
    create_system,
    create_term,
    get_success_data,
    make_leader_headers,
    make_officer_headers,
    set_clock,
    setup_self_study_term,
    submit_rating,
    validate_error,
    validate_success,
)

LEADER = TEST_USERS["leader_headers"]


class TestRatingCreationRules:
    def test_rating_value_out_of_range_rejected(self, api, officer_headers):
        """PRD §2.5: "Purely structural problems — a missing required field, an
        enum value outside its allowed set, an `enrollment` below 1, a `rating`
        outside 1 through 4, or a `closes_at` that is not strictly after
        `opens_at` — are reported as `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/rating_value_out_of_range_rejected
        """
        ctx = setup_self_study_term(system_name="Range School", advance=False)
        term = get_success_data(api.get_term(ctx["term"]["id"], officer_headers))
        payload = create_rating_payload(
            term_id=ctx["term"]["id"], campus_id=ctx["campuses"][0]["id"],
            standard_id=ctx["standards"][0]["id"], rating=5,
            expected_term_version=term["version"])
        # The setup already created a rating for this triple; use a second
        # standard so the out-of-range value is the only defect.
        extra = create_standard(code="T9", title="Teaching 9", domain="LEARNING",
                                weight_pct=100, evidence_min_items=0)
        payload["standard_id"] = extra["id"]
        resp = api.create_rating(payload, LEADER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_initial_state_new_rating_is_draft(self, api, officer_headers):
        """PRD §3.3: "The new rating starts in `DRAFT`."
        PRD §3.3: "On finalization the server stamps `finalized_at` with the
        current instant, increments the rating's `version`, and recomputes the
        campus composite index — which itself increments the campus's `version`."

        Design: Corner/state_machines/initial_state_new_rating_is_draft
        """
        ctx = setup_self_study_term(system_name="Init School", advance=False)
        rating = ctx["ratings"][(0, 0)]
        assert_rating(rating)
        assert rating["status"] == "DRAFT"
        assert rating["finalized_at"] is None, \
            "finalized_at is stamped only on finalization, so a new rating has none"

    def test_duplicate_rating_rejected(self, api, officer_headers, leader_headers):
        """PRD §3.3: "Uniqueness is enforced per (term, campus, standard) triple:
        a second rating for the same combination is rejected with
        `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/validations/duplicate_rating_rejected
        """
        ctx = setup_self_study_term(system_name="Dup County", advance=False)
        term = get_success_data(api.get_term(ctx["term"]["id"], officer_headers))
        payload = create_rating_payload(
            term_id=ctx["term"]["id"], campus_id=ctx["campuses"][0]["id"],
            standard_id=ctx["standards"][0]["id"], rating=3,
            expected_term_version=term["version"])
        resp = api.create_rating(payload, leader_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


class TestTermAdvanceGate:
    def test_advance_without_rating_coverage_rejected(self, api, officer_headers):
        """PRD §3.2: "the same constraint guards the advance from `PREPARATION`
        to `SELF_STUDY`, which additionally requires that every `IN_SCOPE`
        campus of the owning system already has at least one `SelfStudyRating`
        row — in any status — for every `Standard` in the catalogue."

        Design: Corner/state_machines/invalid_transition_term_preparation_to_review_skipped
        """
        set_clock("2026-08-01T00:00:00Z")
        system = create_system(name="Skip County", system_type="SINGLE_SCHOOL")
        create_campus(system["id"], name="Main", enrollment=100)
        create_standard(code="L1", title="Leadership 1", domain="LEADERSHIP",
                        weight_pct=100, evidence_min_items=0)
        term = create_term(system["id"])
        resp = api.advance_term(term["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRatingSubmitGate:
    def test_submit_blocked_while_term_in_preparation(self, api, leader_headers):
        """PRD §3.3: "Submitting moves a rating `DRAFT` → `SUBMITTED` (or
        `REOPENED` → `SUBMITTED`) and requires the rubric score to be within 1
        to 4, the owning term to be in `SELF_STUDY`, and — for the initial
        submission from `DRAFT` — the campus to be `IN_SCOPE`."

        Design: Difficulty/cross_entity_state_dependency/rating_submit_requires_term_self_study
        """
        ctx = setup_self_study_term(system_name="Gated School", advance=False)
        rating = ctx["ratings"][(0, 0)]
        assert rating["status"] == "DRAFT"
        resp = api.submit_rating(rating["id"], leader_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_submit_blocked_when_campus_out_of_scope(self, api, officer_headers,
                                                     leader_headers):
        """PRD §3.3: "Submitting moves a rating `DRAFT` → `SUBMITTED` (or
        `REOPENED` → `SUBMITTED`) and requires the rubric score to be within 1
        to 4, the owning term to be in `SELF_STUDY`, and — for the initial
        submission from `DRAFT` — the campus to be `IN_SCOPE`."

        Design: Difficulty/cross_entity_state_dependency/rating_submit_requires_term_self_study
        """
        ctx = setup_self_study_term(system_name="Scope-Gated School")
        rating = ctx["ratings"][(0, 0)]
        # Scope-out is allowed while the campus has no FINALIZED rating.
        get_success_data(api.scope_out_campus(ctx["campuses"][0]["id"],
                                              officer_headers))
        resp = api.submit_rating(rating["id"], leader_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEvidenceQuorum:
    def test_finalize_with_zero_min_items_and_no_evidence(self, api, officer_headers):
        """PRD §3.3: "Finalizing moves a rating `SUBMITTED` → `FINALIZED`, but
        only once the evidence quorum is satisfied: the count of `EvidenceItem`
        rows with `review_status` of `APPROVED` under the rating must be at
        least the standard's `evidence_min_items`, otherwise the request fails
        with `ERR_THRESHOLD_NOT_MET`."

        Design: Difficulty/boundary_precision_check/evidence_quorum_zero_min_items_allows_finalize
        """
        ctx = setup_self_study_term(system_name="ZeroQuorum School")
        rating = submit_rating(ctx["ratings"][(0, 0)]["id"])
        finalized = validate_success(
            api.finalize_rating(rating["id"], officer_headers))
        assert finalized["status"] == "FINALIZED", \
            "evidence_min_items 0 means zero APPROVED items satisfy the quorum"
        assert finalized["finalized_at"] is not None

    def test_finalize_with_zero_min_items_ignores_pending_evidence(
            self, api, officer_headers, leader_headers):
        """PRD §3.3: "Finalizing moves a rating `SUBMITTED` → `FINALIZED`, but
        only once the evidence quorum is satisfied: the count of `EvidenceItem`
        rows with `review_status` of `APPROVED` under the rating must be at
        least the standard's `evidence_min_items`, otherwise the request fails
        with `ERR_THRESHOLD_NOT_MET`."

        Design: Difficulty/boundary_precision_check/evidence_quorum_zero_min_items_allows_finalize
        """
        ctx = setup_self_study_term(system_name="ZeroQuorum Pending School")
        rating_id = ctx["ratings"][(0, 0)]["id"]
        # A PENDING evidence item does not count toward the APPROVED quorum.
        get_success_data(api.create_evidence(
            rating_id, create_evidence_payload(title="Draft exhibit"), leader_headers))
        submit_rating(rating_id)
        finalized = validate_success(api.finalize_rating(rating_id, officer_headers))
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_at"] is not None


class TestFinalizeReopenCycle:
    def test_reopen_then_refinalize_restores_composite(self, api, officer_headers):
        """PRD §3.3: "an officer may reopen a finalized rating (`FINALIZED` →
        `REOPENED`) only while the owning term is still in `SELF_STUDY`; the
        rating's `finalized_at` returns to null and the composite index is
        recomputed with this rating now excluded, again incrementing both
        versions."
        PRD §3.3: "If that set is empty, `composite_index_pct` is null."

        Design: Difficulty/non_linear_state_machine/rating_finalize_reopen_resubmit_cycle
        """
        ctx = setup_self_study_term(system_name="Cycle School",
                                    rating_values={(0, 0): 2})
        rating_id = ctx["ratings"][(0, 0)]["id"]
        campus_id = ctx["campuses"][0]["id"]
        finalized = validate_success(api.finalize_rating(
            submit_rating(rating_id)["id"], officer_headers))
        assert finalized["status"] == "FINALIZED"
        campus = get_success_data(api.get_campus(campus_id, officer_headers))
        assert campus["composite_index_pct"] == pytest.approx(50.00, abs=0.001)

        reopened = validate_success(api.reopen_rating(rating_id, officer_headers))
        assert reopened["status"] == "REOPENED"
        campus = get_success_data(api.get_campus(campus_id, officer_headers))
        assert campus["composite_index_pct"] is None, \
            "with no FINALIZED ratings remaining the composite set is empty"

        resubmitted = validate_success(api.submit_rating(rating_id, LEADER))
        assert resubmitted["status"] == "SUBMITTED"
        refinalized = validate_success(api.finalize_rating(rating_id, officer_headers))
        assert refinalized["status"] == "FINALIZED"
        campus = get_success_data(api.get_campus(campus_id, officer_headers))
        assert campus["composite_index_pct"] == pytest.approx(50.00, abs=0.001)

    def test_finalized_at_stamped_nulled_and_restamped(self, api, officer_headers):
        """PRD §3.3: "On finalization the server stamps `finalized_at` with the
        current instant, increments the rating's `version`, and recomputes the
        campus composite index — which itself increments the campus's `version`."
        PRD §3.3: "the rating's `finalized_at` returns to null and the composite
        index is recomputed with this rating now excluded, again incrementing
        both versions."

        Design: Difficulty/non_linear_state_machine/rating_finalize_reopen_resubmit_cycle
        """
        ctx = setup_self_study_term(system_name="Timestamp Cycle School")
        rating_id = ctx["ratings"][(0, 0)]["id"]
        submitted = submit_rating(rating_id)
        finalized = validate_success(api.finalize_rating(rating_id, officer_headers))
        assert finalized["finalized_at"] is not None
        assert finalized["version"] == submitted["version"] + 1

        reopened = validate_success(api.reopen_rating(rating_id, officer_headers))
        assert reopened["finalized_at"] is None
        assert reopened["version"] == finalized["version"] + 1

        resubmitted = validate_success(api.submit_rating(rating_id, LEADER))
        refinalized = validate_success(api.finalize_rating(rating_id, officer_headers))
        assert refinalized["finalized_at"] is not None
        assert refinalized["version"] == resubmitted["version"] + 1


class TestEvidenceSegregation:
    def test_officer_cannot_review_own_submission(self, api):
        """PRD §2.9: "An `AccreditationOfficer` may not approve or reject an
        `EvidenceItem` whose `submitted_by_user_id` equals the officer's own
        `X-User-ID`."
        PRD §2.1: "Segregation-of-duties checks compare these opaque identifiers
        against each other — an officer whose `X-User-ID` equals an evidence
        item's `submitted_by_user_id` is treated as the same individual."

        Design: Corner/errors/error_segregation_self_review_rejected
        """
        ctx = setup_self_study_term(system_name="SoD School")
        rating_id = ctx["ratings"][(0, 0)]["id"]
        leader = make_leader_headers("leader-1")
        evidence = get_success_data(api.create_evidence(
            rating_id, create_evidence_payload(title="Policy doc"), leader))
        assert evidence["submitted_by_user_id"] == "leader-1"
        submit_rating(rating_id, headers=leader)
        # Same opaque user id, now acting as the reviewing officer.
        resp = api.review_evidence(evidence["id"], {"decision": "APPROVED"},
                                   make_officer_headers("leader-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
