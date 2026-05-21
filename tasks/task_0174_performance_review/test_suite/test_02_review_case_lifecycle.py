"""ReviewCase lifecycle: DRAFT -> SUBMITTED -> RETURNED -> DRAFT cycle,
submit preconditions, revision cap, optimistic concurrency.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_review_case,
    create_active_employee,
    create_employee_with_role,
    create_open_cycle,
    create_review_case_payload,
    finalize_review_case_via_calibration,
    setup_finalized_review_case,
    setup_submittable_review_case,
    submit_review_case,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Creation + initial state
# ===========================================================================
class TestReviewCaseCreation:

    def test_create_review_case_initial_state(self, api):
        """PRD §3.3: "the server pins `cycle_id` from the URL, snapshots
        the subject's current manager into the case's own
        `manager_employee_id`, and seeds the case in `DRAFT` status".

        Claim: created case is in DRAFT with the correct manager
        snapshot and zero counters.
        """
        cyc = create_open_cycle()
        mgr = create_employee_with_role("Manager")
        hrbp = create_employee_with_role("HRBP")
        subj = create_active_employee(manager_employee_id=mgr.id)
        res = api.create_review_case(
            cyc["id"], create_review_case_payload(subj["id"]), hrbp.headers,
        )
        rc = validate_success(res, 201)
        assert_review_case(rc)
        assert rc["cycle_id"] == cyc["id"]
        assert rc["subject_employee_id"] == subj["id"]
        assert rc["manager_employee_id"] == mgr.id
        assert rc["status"] == "DRAFT"
        assert rc["revision_count"] == 0
        assert rc["peer_feedback_count"] == 0

    def test_create_review_case_unique_per_subject(self, api):
        """PRD §3.3: "Only one case may exist per `(cycle_id,
        subject_employee_id)`."."""
        bundle = setup_submittable_review_case()
        # Second attempt for the same subject under the same cycle.
        res = api.create_review_case(
            bundle.cycle["id"],
            create_review_case_payload(bundle.subject["id"]),
            bundle.hrbp.headers,
        )
        # PRD §3.3 says only-one-per-pair but does not pin a specific
        # error_id for the violation. Two-reader test: an implementer
        # could plausibly pick a generic ERR_VALIDATION or ERR_INVALID_STATE.
        # Assert HTTP 4xx without pinning a specific id.
        assert 400 <= res.status_code < 500

    def test_create_review_case_terminated_subject_rejected(self, api):
        """PRD §3.3: "The subject must be an `Employee` whose status is
        `ACTIVE` or `ON_PIP`"."""
        cyc = create_open_cycle()
        mgr = create_employee_with_role("Manager")
        hrbp = create_employee_with_role("HRBP")
        subj = create_active_employee(manager_employee_id=mgr.id)
        # Terminate the subject.
        from test_helpers import TEST_USERS
        api.terminate_employee(subj["id"], TEST_USERS["admin_headers"])
        res = api.create_review_case(
            cyc["id"], create_review_case_payload(subj["id"]), hrbp.headers,
        )
        # PRD §3.3 lists ACTIVE/ON_PIP but does not pin a specific
        # error_id for a TERMINATED subject. Accept any 4xx.
        assert 400 <= res.status_code < 500

    def test_create_review_case_subject_not_found(self, api):
        """PRD §2.5: "When a foreign key embedded in a request body
        (such as `manager_employee_id`, `subject_employee_id`,
        `reviewer_employee_id`, `triggering_review_case_id`, or
        `facilitator_employee_id`) refers to a record the server cannot
        find, the response is `ERR_REFERENCE_NOT_FOUND` with HTTP 404"."""
        cyc = create_open_cycle()
        hrbp = create_employee_with_role("HRBP")
        res = api.create_review_case(
            cyc["id"], create_review_case_payload(NON_EXISTENT_UUID),
            hrbp.headers,
        )
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ===========================================================================
# DRAFT -> SUBMITTED happy path + every precondition
# ===========================================================================
class TestSubmitReviewCase:

    def test_submit_happy_path_advances_to_submitted(self, api):
        """PRD §3.3: "On a successful submit, `weighted_goal_score` is
        recomputed, `updated_at` is refreshed, and `version` is
        incremented; the case moves `DRAFT → SUBMITTED`"."""
        bundle = setup_submittable_review_case()
        old_v = bundle.review_case["version"]
        res = api.submit_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.manager.headers,
        )
        rc = validate_success(res, 200)
        assert rc["status"] == "SUBMITTED"
        assert rc["version"] > old_v

    def test_submit_recomputes_weighted_goal_score(self, api):
        """PRD §3.3: "the score is the sum over all goals of each
        goal's `weight` multiplied by its `manager_score`, divided by
        100, with the result rounded half-up to two decimal places"."""
        bundle = setup_submittable_review_case(
            weights=(60, 40),
            self_scores=(5, 3),     # 5 and 3 for self
            manager_scores=(4, 2),  # 4 and 2 — final formula uses these
        )
        bundle = submit_review_case(bundle)
        # (60 * 4 + 40 * 2) / 100 = 320 / 100 = 3.20
        assert bundle.review_case["weighted_goal_score"] == pytest.approx(3.20, abs=0.001)

    def test_submit_without_two_peer_feedbacks_rejected(self, api):
        """PRD §3.3: "the case has at least two `SUBMITTED` feedback
        requests as measured by `peer_feedback_count` (otherwise
        `ERR_PEER_FEEDBACK_INSUFFICIENT`)".

        # difficulty: boundary_precision_check/peer_feedback_count_empty_set
        """
        bundle = setup_submittable_review_case(attach_feedback=False)
        res = api.submit_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.manager.headers,
        )
        validate_error(res, "ERR_PEER_FEEDBACK_INSUFFICIENT")

    def test_submit_with_only_one_peer_feedback_rejected(self, api):
        """PRD §3.3: "at least two `SUBMITTED` feedback requests as
        measured by `peer_feedback_count` (otherwise
        `ERR_PEER_FEEDBACK_INSUFFICIENT`)".

        Boundary at exactly one — the count is below the >=2 floor.

        # difficulty: boundary_precision_check/peer_feedback_count_empty_set
        """
        from test_helpers import (
            create_feedback_request_payload,
            submit_feedback_request_payload,
        )
        bundle = setup_submittable_review_case(attach_feedback=False)
        rev = create_employee_with_role("Reviewer",
                                        department=bundle.subject["department"])
        fr = validate_success(api.create_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"],
            create_feedback_request_payload(rev.id, relation="PEER"),
            bundle.hrbp.headers,
        ), 201)
        validate_success(api.submit_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"], fr["id"],
            submit_feedback_request_payload(), rev.headers,
        ), 200)
        # peer_feedback_count is now 1.
        res = api.submit_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.manager.headers,
        )
        validate_error(res, "ERR_PEER_FEEDBACK_INSUFFICIENT")

    def test_submit_with_exactly_two_peer_feedbacks_succeeds(self, api):
        """PRD §3.3: "at least two `SUBMITTED` feedback requests" — the
        floor is satisfied at exactly two.

        # difficulty: boundary_precision_check/peer_feedback_count_empty_set
        """
        bundle = setup_submittable_review_case(attach_feedback=True)
        res = api.submit_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.manager.headers,
        )
        rc = validate_success(res, 200)
        assert rc["status"] == "SUBMITTED"

    def test_submit_goal_weights_not_100_rejected(self, api):
        """PRD §3.3: "the sum of `weight` across the case's goals
        equals 100 (otherwise `ERR_GOAL_WEIGHTS_INVALID`)"."""
        # Build a case whose goals sum to 90 instead of 100. We can't
        # use the helper's add_goals_summing_to_100 here; build manually.
        from test_helpers import (
            create_goal_payload,
            create_feedback_request_payload,
            submit_feedback_request_payload,
        )
        cyc = create_open_cycle()
        mgr = create_employee_with_role("Manager")
        hrbp = create_employee_with_role("HRBP")
        subj = create_active_employee(manager_employee_id=mgr.id)
        rc = validate_success(api.create_review_case(
            cyc["id"], create_review_case_payload(subj["id"]),
            hrbp.headers,
        ), 201)
        for w in (50, 40):  # sums to 90, not 100
            validate_success(api.create_goal(
                cyc["id"], rc["id"],
                create_goal_payload(weight=w, self_score=3,
                                    manager_score=4),
                mgr.headers,
            ), 201)
        validate_success(api.update_review_case(
            cyc["id"], rc["id"], {"manager_rating": "MEETS"},
            mgr.headers,
        ), 200)
        # Add 2 SUBMITTED feedback requests so feedback gate doesn't fire.
        for _ in range(2):
            rev = create_employee_with_role("Reviewer")
            fr = validate_success(api.create_feedback_request(
                cyc["id"], rc["id"],
                create_feedback_request_payload(rev.id, relation="PEER"),
                hrbp.headers,
            ), 201)
            validate_success(api.submit_feedback_request(
                cyc["id"], rc["id"], fr["id"],
                submit_feedback_request_payload(), rev.headers,
            ), 200)
        res = api.submit_review_case(cyc["id"], rc["id"], mgr.headers)
        validate_error(res, "ERR_GOAL_WEIGHTS_INVALID")

    def test_submit_wrong_state_rejected(self, api):
        """PRD §2.7 / §3.3: submit requires the case to be in DRAFT.
        A second submit on an already-SUBMITTED case fails with
        ERR_INVALID_STATE (PRD §5)."""
        bundle = submit_review_case(setup_submittable_review_case())
        res = api.submit_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.manager.headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_submit_when_cycle_not_open(self, api):
        """PRD §3.3: "once the cycle leaves `OPEN`, any further
        mutation on those child resources is rejected with
        `ERR_CYCLE_NOT_OPEN`." This test drives bundle_a to SUBMITTED,
        locks the cycle (cycle -> IN_CALIBRATION, case -> LOCKED), then
        verifies that a PATCH on a child case after the cycle leaves
        OPEN is refused with ERR_CYCLE_NOT_OPEN.

        # difficulty: cross_entity_state_dependency/review_case_submit_requires_cycle_open
        """
        bundle_a = submit_review_case(setup_submittable_review_case())
        # Lock-reviews requires every case in {SUBMITTED, RETURNED};
        # bundle_a is SUBMITTED so lock proceeds.
        bundle_a.cycle = validate_success(api.lock_reviews(
            bundle_a.cycle["id"], bundle_a.hrbp.headers,
        ), 200)
        # PATCH manager_rating after cycle is IN_CALIBRATION must yield
        # ERR_CYCLE_NOT_OPEN per PRD §3.3 — the cycle-open gate fires
        # before the per-entity state check, per PRD §2.7.
        res = api.update_review_case(
            bundle_a.cycle["id"], bundle_a.review_case["id"],
            {"manager_rating": "MEETS"},
            bundle_a.manager.headers,
        )
        validate_error(res, "ERR_CYCLE_NOT_OPEN")


# ===========================================================================
# SUBMITTED -> RETURNED -> DRAFT revision loop + revision cap
# ===========================================================================
class TestRevisionLoop:

    def test_revision_count_increments_on_return(self, api):
        """PRD §3.3: "The transition advances the case `SUBMITTED →
        RETURNED`, increments `revision_count` by 1...".
        """
        bundle = submit_review_case(setup_submittable_review_case())
        res = api.return_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.hrbp.headers,
        )
        rc = validate_success(res, 200)
        assert rc["status"] == "RETURNED"
        assert rc["revision_count"] == 1

    def test_reopen_brings_case_back_to_draft(self, api):
        """PRD §3.3: "The Manager then reopens the case (`RETURNED →
        DRAFT`)...".
        """
        bundle = submit_review_case(setup_submittable_review_case())
        validate_success(api.return_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.hrbp.headers,
        ), 200)
        res = api.reopen_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.manager.headers,
        )
        rc = validate_success(res, 200)
        assert rc["status"] == "DRAFT"

    def test_three_revisions_then_fourth_return_rejected(self, api):
        """PRD §3.3: "A fourth return is refused with
        `ERR_REVISION_LIMIT`."

        # difficulty: non_linear_state_machine/review_case_revision_cycle
        """
        bundle = submit_review_case(setup_submittable_review_case())
        for i in range(3):
            ret = validate_success(api.return_review_case(
                bundle.cycle["id"], bundle.review_case["id"],
                bundle.hrbp.headers,
            ), 200)
            assert ret["revision_count"] == i + 1
            validate_success(api.reopen_review_case(
                bundle.cycle["id"], bundle.review_case["id"],
                bundle.manager.headers,
            ), 200)
            validate_success(api.submit_review_case(
                bundle.cycle["id"], bundle.review_case["id"],
                bundle.manager.headers,
            ), 200)
        # Now revision_count is 3; the next .../return must be refused.
        res = api.return_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.hrbp.headers,
        )
        validate_error(res, "ERR_REVISION_LIMIT")

    def test_cycle_revision_loop_completes_three_times(self, api):
        """PRD §3.3: "Up to three full return-reopen revision loops are
        therefore possible before the case must stand."

        # difficulty: non_linear_state_machine/review_case_revision_cycle
        """
        bundle = submit_review_case(setup_submittable_review_case())
        # Each loop: SUBMITTED -> RETURNED -> DRAFT -> SUBMITTED.
        for _ in range(3):
            validate_success(api.return_review_case(
                bundle.cycle["id"], bundle.review_case["id"],
                bundle.hrbp.headers,
            ), 200)
            validate_success(api.reopen_review_case(
                bundle.cycle["id"], bundle.review_case["id"],
                bundle.manager.headers,
            ), 200)
            validate_success(api.submit_review_case(
                bundle.cycle["id"], bundle.review_case["id"],
                bundle.manager.headers,
            ), 200)
        rc = validate_success(api.get_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.hrbp.headers,
        ), 200)
        assert rc["revision_count"] == 3
        assert rc["status"] == "SUBMITTED"


# ===========================================================================
# Optimistic concurrency on PATCH — PRD §2.6
# ===========================================================================
class TestReviewCaseOCC:

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.6: "When the client supplies a `version`, the server
        compares it against the current entity's `version`; if they
        differ, the request is rejected with `ERR_VERSION_CONFLICT`
        (HTTP 409) and no state changes."."""
        bundle = setup_submittable_review_case()
        stale = bundle.review_case["version"]
        # Bump the case version once.
        validate_success(api.update_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            {"manager_rating": "OUTSTANDING"},
            bundle.manager.headers,
        ), 200)
        # Now PATCH with the now-stale version.
        res = api.update_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            {"manager_rating": "MEETS", "version": stale},
            bundle.manager.headers,
        )
        validate_error(res, "ERR_VERSION_CONFLICT")
