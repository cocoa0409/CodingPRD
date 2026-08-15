"""Amendment requests: OCC, in-flight uniqueness, materiality routing, the
revision loop, and the approval cascade (PRD §3.6, §2.8)."""
from test_helpers import (
    ApiErrorId,
    STANDARD_MATRIX,
    create_recorded_easement,
    create_requested_use_authorization,
    create_submitted_amendment,
    get_easement,
    make_board_reviewer_headers,
    make_coordinator_headers,
    resubmit_amendment_payload,
    validate_error,
    validate_success,
)

CHANGE_SUBDIVISION_TO_DISCRETIONARY = [
    {"use_type": "SUBDIVISION", "new_level": "DISCRETIONARY"}
]
CHANGE_RESIDENTIAL_TO_PERMITTED = [
    {"use_type": "RESIDENTIAL_CONSTRUCTION", "new_level": "PERMITTED"}
]
CHANGE_TIMBER_TO_PROHIBITED = [
    {"use_type": "TIMBER_HARVEST", "new_level": "PROHIBITED"}
]


class TestAmendmentUniquenessAndOcc:
    def test_second_inflight_amendment_rejected(self, api, coordinator_headers,
                                                trust_admin_headers):
        """PRD §3.6: "No other amendment of the same easement may be in flight —
        `SUBMITTED`, `STAFF_REVIEW`, `REVISION_REQUESTED`, or `BOARD_REVIEW` —
        else `ERR_AMENDMENT_ALREADY_IN_FLIGHT` (409)."

        Design: Corner/validations/second_inflight_amendment_rejected
        """
        ctx = create_recorded_easement(name="E-IA", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        easement_id = ctx["easement"]["id"]
        first = create_submitted_amendment(
            easement_id, ctx["version"],
            requested_changes=CHANGE_SUBDIVISION_TO_DISCRETIONARY, affected_acreage=10,
        )
        assert first["status"] == "SUBMITTED"

        # Fresh easement version: the second request clears OCC but hits the
        # per-easement in-flight uniqueness rule.
        fresh_version = get_easement(easement_id)["version"]
        resp = api.create_amendment_request(
            {
                "easement_id": easement_id,
                "expected_easement_version": fresh_version,
                "submitted_by_user_id": "coord-1",
                "requested_changes": [{"use_type": "SUBDIVISION",
                                       "new_level": "PROHIBITED"}],
                "affected_acreage": 5,
            },
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_ALREADY_IN_FLIGHT)

    def test_occ_stale_easement_version_on_amendment_create(self, api, coordinator_headers):
        """PRD §2.8: "Creating an amendment request requires
        `expected_easement_version` equal to the easement's current `version`. A
        client prices its requested changes against a permitted-use matrix the
        server may since have replaced — a prior amendment approval legitimately
        rewrites the matrix while leaving no amendment in flight — so a mismatch
        is rejected with `ERR_STALE_EASEMENT_VERSION` (HTTP 412)."
        PRD §3.6: "A created request is born `SUBMITTED`, its `materiality_score`
        and `review_path` are computed, and the easement's `version` advances by
        one."

        Design: Corner/validations/occ_stale_easement_version_on_amendment_create
        """
        ctx = create_recorded_easement(name="E-OC1", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        easement_id = ctx["easement"]["id"]
        version_at_record = ctx["version"]

        # Amendment A is created against the current version (bumping it) and
        # then withdrawn, leaving nothing in flight.
        first = create_submitted_amendment(
            easement_id, version_at_record,
            requested_changes=CHANGE_SUBDIVISION_TO_DISCRETIONARY, affected_acreage=10,
        )
        validate_success(api.withdraw_amendment_request(first["id"], coordinator_headers), 200)

        # Amendment B presents the pre-A version: stale even though no amendment
        # is in flight.
        resp = api.create_amendment_request(
            {
                "easement_id": easement_id,
                "expected_easement_version": version_at_record,
                "submitted_by_user_id": "coord-1",
                "requested_changes": CHANGE_SUBDIVISION_TO_DISCRETIONARY,
                "affected_acreage": 20,
            },
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_EASEMENT_VERSION)

    def test_amendment_approve_after_withdraw_terminal_lockdown(self, api,
                                                                coordinator_headers,
                                                                trust_admin_headers):
        """PRD §3.6: "A coordinator may withdraw the request from any
        non-terminal state — `SUBMITTED`, `STAFF_REVIEW`, `REVISION_REQUESTED`,
        or `BOARD_REVIEW` — moving it to `WITHDRAWN`."
        PRD §3.6: "Any transition attempted from a state where it is not defined
        is rejected with `ERR_INVALID_AMENDMENT_STATE` (409)."

        Design: Corner/state_machines/amendment_approve_after_withdraw_terminal_lockdown
        """
        ctx = create_recorded_easement(name="E-AW", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        amendment = create_submitted_amendment(
            ctx["easement"]["id"], ctx["version"],
            requested_changes=CHANGE_SUBDIVISION_TO_DISCRETIONARY, affected_acreage=10,
        )
        withdrawn = validate_success(
            api.withdraw_amendment_request(amendment["id"], coordinator_headers), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.approve_amendment_request(
            amendment["id"], make_coordinator_headers("coord-2")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AMENDMENT_STATE)
        after = validate_success(
            api.get_amendment_request(amendment["id"], trust_admin_headers), 200
        )
        assert after["status"] == "WITHDRAWN"


class TestMaterialityBoundary:
    def test_materiality_exactly_70_routes_board(self, api, coordinator_headers):
        """PRD §3.6: "Acreage points: the share of the parcel affected —
        `affected_acreage` divided by the easement's `parcel_acreage` —
        multiplied by fifty and rounded half-up to a whole number. Change points:
        ten points per requested change. Downgrade points: thirty when any change
        moves a cell from `PROHIBITED` to `PERMITTED`; otherwise fifteen when any
        change moves a cell from `DISCRETIONARY` to `PERMITTED`; otherwise zero —
        only the single largest downgrade contributes, never a sum across
        changes."
        PRD §3.6: "The `review_path` is `BOARD` when the score is 70 or higher —
        a score of exactly 70 routes to the board, while 69 stays with staff —
        and `STAFF` otherwise."

        Design: Difficulty/boundary_precision_check/materiality_exactly_70_routes_board
        """
        ctx = create_recorded_easement(name="E-B70", parcel_acreage=500,
                                       matrix=STANDARD_MATRIX)
        # 300/500 * 50 = 30 acreage points + 10 change + 30 downgrade = 70.
        amendment = create_submitted_amendment(
            ctx["easement"]["id"], ctx["version"],
            requested_changes=CHANGE_RESIDENTIAL_TO_PERMITTED, affected_acreage=300,
        )
        assert amendment["materiality_score"] == 70
        assert amendment["review_path"] == "BOARD", "the 70 boundary is inclusive"

    def test_materiality_69_routes_staff(self, api, coordinator_headers):
        """PRD §3.6: "The `review_path` is `BOARD` when the score is 70 or higher
        — a score of exactly 70 routes to the board, while 69 stays with staff —
        and `STAFF` otherwise."

        Design: Difficulty/boundary_precision_check/materiality_exactly_70_routes_board
        """
        ctx = create_recorded_easement(name="E-B69", parcel_acreage=500,
                                       matrix=STANDARD_MATRIX)
        # 290/500 * 50 = 29 acreage points + 10 change + 30 downgrade = 69.
        amendment = create_submitted_amendment(
            ctx["easement"]["id"], ctx["version"],
            requested_changes=CHANGE_RESIDENTIAL_TO_PERMITTED, affected_acreage=290,
        )
        assert amendment["materiality_score"] == 69
        assert amendment["review_path"] == "STAFF"


class TestRevisionCycle:
    def test_amendment_resubmit_recomputes_materiality(self, api, coordinator_headers):
        """PRD §3.6: "From there a coordinator may request revision, moving it to
        `REVISION_REQUESTED` and capturing `revision_notes`; the coordinator's
        resubmission moves it back to `SUBMITTED`, replacing `requested_changes`
        and `affected_acreage` wholesale and recomputing `materiality_score` and
        `review_path`."
        PRD §3.6: "Both fields are recomputed on every resubmission."

        Design: Difficulty/non_linear_state_machine/amendment_revision_cycle_resubmit_changes_materiality
        """
        ctx = create_recorded_easement(name="E-AM", parcel_acreage=500,
                                       matrix=STANDARD_MATRIX)
        amendment = create_submitted_amendment(
            ctx["easement"]["id"], ctx["version"],
            requested_changes=CHANGE_RESIDENTIAL_TO_PERMITTED, affected_acreage=250,
        )
        # 25 acreage + 10 change + 30 downgrade = 65 -> STAFF.
        assert amendment["materiality_score"] == 65
        assert amendment["review_path"] == "STAFF"
        assert amendment["status"] == "SUBMITTED"

        validate_success(api.start_amendment_review(amendment["id"], coordinator_headers), 200)
        revision = validate_success(
            api.request_amendment_revision(
                amendment["id"], {"revision_notes": "expand acreage"},
                coordinator_headers,
            ),
            200,
        )
        assert revision["status"] == "REVISION_REQUESTED"

        resubmitted = validate_success(
            api.resubmit_amendment_request(
                amendment["id"],
                resubmit_amendment_payload(
                    CHANGE_RESIDENTIAL_TO_PERMITTED, affected_acreage=300
                ),
                coordinator_headers,
            ),
            200,
        )
        # 30 acreage + 10 change + 30 downgrade = 70 -> BOARD; the loop returns
        # the request to SUBMITTED with the recomputed routing.
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["materiality_score"] == 70
        assert resubmitted["review_path"] == "BOARD"

    def test_amendment_revision_cycle_board_approval_applies_matrix(self, api,
                                                                    coordinator_headers,
                                                                    trust_admin_headers):
        """PRD §3.6: "On the staff lane, a `StewardshipCoordinator` approves from
        `STAFF_REVIEW` — permitted only when the request's `review_path` is
        `STAFF`, that is, a `materiality_score` below 70; attempting staff
        approval at 70 or above is rejected with
        `ERR_MATERIALITY_REQUIRES_BOARD` (403). On the board lane, a
        `TrustBoardReviewer` approves from `BOARD_REVIEW`."
        PRD §3.6: "Link one: the easement's `permitted_use_matrix` is mutated per
        `requested_changes`, `amendment_count` increments by one, and the
        easement's `version` advances by one."

        Design: Difficulty/non_linear_state_machine/amendment_revision_cycle_resubmit_changes_materiality
        """
        ctx = create_recorded_easement(name="E-AM2", parcel_acreage=500,
                                       matrix=STANDARD_MATRIX)
        easement_id = ctx["easement"]["id"]
        version_at_record = ctx["version"]
        amendment = create_submitted_amendment(
            easement_id, version_at_record,
            requested_changes=CHANGE_RESIDENTIAL_TO_PERMITTED, affected_acreage=250,
        )
        validate_success(api.start_amendment_review(amendment["id"], coordinator_headers), 200)
        validate_success(
            api.request_amendment_revision(
                amendment["id"], {"revision_notes": "expand acreage"},
                coordinator_headers,
            ),
            200,
        )
        validate_success(
            api.resubmit_amendment_request(
                amendment["id"],
                resubmit_amendment_payload(
                    CHANGE_RESIDENTIAL_TO_PERMITTED, affected_acreage=300
                ),
                coordinator_headers,
            ),
            200,
        )
        validate_success(api.start_amendment_review(amendment["id"], coordinator_headers), 200)

        # Staff lane is barred at score 70.
        resp = api.approve_amendment_request(
            amendment["id"], make_coordinator_headers("coord-2")
        )
        validate_error(resp, ApiErrorId.ERR_MATERIALITY_REQUIRES_BOARD)

        # Board lane approves; the matrix mutates and the easement version has
        # advanced by exactly two across create + approve.
        validate_success(
            api.escalate_amendment_to_board(amendment["id"], coordinator_headers), 200
        )
        approved = validate_success(
            api.approve_amendment_request(
                amendment["id"], make_board_reviewer_headers("board-9")
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "board-9"

        easement = get_easement(easement_id)
        assert easement["permitted_use_matrix"]["RESIDENTIAL_CONSTRUCTION"] == "PERMITTED"
        assert easement["amendment_count"] == 1
        assert easement["version"] == version_at_record + 2


class TestApprovalCascade:
    def test_amendment_approval_mutates_matrix(self, api, coordinator_headers,
                                               trust_admin_headers):
        """PRD §3.6: "Approval fires a two-link cascade. Link one: the easement's
        `permitted_use_matrix` is mutated per `requested_changes`,
        `amendment_count` increments by one, and the easement's `version`
        advances by one."
        PRD §3.6: "The `materiality_score` is the sum of the three components,
        capped at 100."

        Design: Difficulty/transitive_cascade/amendment_approval_auto_denies_pending_use_authorizations
        """
        ctx = create_recorded_easement(name="E-AA", parcel_acreage=500,
                                       matrix=STANDARD_MATRIX)
        easement_id = ctx["easement"]["id"]
        version_at_record = ctx["version"]
        create_requested_use_authorization(
            easement_id, ctx["landowner"]["id"], use_type="TIMBER_HARVEST",
            justification="selective thinning",
        )
        amendment = create_submitted_amendment(
            easement_id, version_at_record,
            requested_changes=CHANGE_TIMBER_TO_PROHIBITED, affected_acreage=100,
        )
        # 100/500 * 50 = 10 acreage + 10 change + 0 downgrade = 20 -> STAFF lane.
        assert amendment["materiality_score"] == 20
        assert amendment["review_path"] == "STAFF"

        validate_success(api.start_amendment_review(amendment["id"], coordinator_headers), 200)
        approved = validate_success(
            api.approve_amendment_request(
                amendment["id"], make_coordinator_headers("coord-2")
            ),
            200,
        )
        assert approved["status"] == "APPROVED"

        easement = get_easement(easement_id)
        assert easement["permitted_use_matrix"]["TIMBER_HARVEST"] == "PROHIBITED"
        assert easement["amendment_count"] == 1
        assert easement["version"] == version_at_record + 2, (
            "amendment create +1, approval cascade +1"
        )

    def test_amendment_approval_auto_denies_pending_use_authorization(self, api,
                                                                      coordinator_headers,
                                                                      trust_admin_headers):
        """PRD §3.6: "Link two: every use authorization of this easement still in
        `REQUESTED` whose `use_type` appears among the requested changes is set
        to `DENIED` with `decision_reason` `AMENDMENT_SUPERSEDES`."
        PRD §3.5: "When an amendment approval rewrites a cell, every
        still-`REQUESTED` authorization on that easement whose `use_type` appears
        among the amendment's changes is set to `DENIED` with `decision_reason`
        `AMENDMENT_SUPERSEDES` — the freeze's mirror image, described in §3.6."

        Design: Difficulty/transitive_cascade/amendment_approval_auto_denies_pending_use_authorizations
        """
        ctx = create_recorded_easement(name="E-AA2", parcel_acreage=500,
                                       matrix=STANDARD_MATRIX)
        easement_id = ctx["easement"]["id"]
        authorization = create_requested_use_authorization(
            easement_id, ctx["landowner"]["id"], use_type="TIMBER_HARVEST",
            justification="selective thinning",
        )
        amendment = create_submitted_amendment(
            easement_id, ctx["version"],
            requested_changes=CHANGE_TIMBER_TO_PROHIBITED, affected_acreage=100,
        )
        validate_success(api.start_amendment_review(amendment["id"], coordinator_headers), 200)
        validate_success(
            api.approve_amendment_request(
                amendment["id"], make_coordinator_headers("coord-2")
            ),
            200,
        )

        after = validate_success(
            api.get_use_authorization(authorization["id"], trust_admin_headers), 200
        )
        assert after["status"] == "DENIED"
        assert after["decision_reason"] == "AMENDMENT_SUPERSEDES"
