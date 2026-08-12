"""Notice lifecycle — cyclic revision, parallel incident state, OCC on create
(difficulty rules non_linear_state_machine + cross_entity_state_dependency;
corner errors.stale_version_occ_conflict_on_notice_create)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_incident_confirmed,
    create_draft_notice,
    create_notice_payload,
    get_success_data,
    make_privacy_counsel_headers,
    make_general_counsel_headers,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["privacy_counsel_headers"]
GC = TEST_USERS["general_counsel_headers"]


class TestNoticeCyclicRevision:
    def test_legal_review_to_draft_loop_increments_version_label(self, api):
        """PRD §3.7: "If legal review uncovers problems, a `GeneralCounsel`
        may instead request changes, returning the notice from `LEGAL_REVIEW`
        to `DRAFT` and incrementing `version_label` by 1 — so a notice that
        has been through two round trips carries `version_label` 3."

        Design: Difficulty/non_linear_state_machine/notice_cyclic_revision_loop
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        je = ctx["jurisdiction_evaluations"][0]

        notice = create_draft_notice(inc, je)
        assert notice["version_label"] == 1
        # First round trip: DRAFT -> LEGAL_REVIEW -> DRAFT.
        api.submit_notice_for_review(inc["id"], notice["id"], PC)
        r1 = api.request_changes_notice(inc["id"], notice["id"], GC)
        n1 = validate_success(r1)
        assert n1["version_label"] == 2
        assert n1["status"] == "DRAFT"
        # Second round trip.
        api.submit_notice_for_review(inc["id"], notice["id"], PC)
        r2 = api.request_changes_notice(inc["id"], notice["id"], GC)
        n2 = validate_success(r2)
        assert n2["version_label"] == 3
        assert n2["status"] == "DRAFT"


class TestParallelStateDimensions:
    def test_investigation_status_unchanged_during_notice_approval(self, api):
        """PRD §3.7 approve side effect: "On approval, the server stamps
        `approved_by_user_id` to the acting user and `approved_at` to the
        current timestamp, and increments the incident's `version`." Nothing
        in approve touches `investigation_status`; the two state dimensions
        evolve independently (PRD §1: "two parallel state dimensions —
        `investigation_status` and `notification_status` — that evolve
        independently").

        Design: Difficulty/non_linear_state_machine/incident_parallel_state_dimensions
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        je = ctx["jurisdiction_evaluations"][0]
        notice = create_draft_notice(inc, je)
        api.submit_notice_for_review(inc["id"], notice["id"], PC)
        approve_resp = api.approve_notice(inc["id"], notice["id"], GC)
        approved = validate_success(approve_resp)
        assert approved["status"] == "APPROVED"

        after = get_success_data(api.get_incident(inc["id"], IC))
        assert after["investigation_status"] == "CONFIRMED"
        # notification dimension has advanced in parallel (REQUIRED or beyond).
        assert after["notification_status"] in ("REQUIRED", "DRAFTING", "APPROVED")


class TestNoticeApproveCrossEntity:
    def test_approve_when_incident_confirmed_stamps_approver(self, api):
        """PRD §3.7: "Approval — moving the notice from `LEGAL_REVIEW` to
        `APPROVED` — is a `GeneralCounsel`-exclusive action and carries three
        preconditions ... the incident's `investigation_status` must be
        `CONFIRMED`". "On approval, the server stamps `approved_by_user_id`
        to the acting user and `approved_at` to the current timestamp."

        Design: Difficulty/cross_entity_state_dependency/notice_approve_requires_incident_confirmed
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        je = ctx["jurisdiction_evaluations"][0]
        notice = create_draft_notice(inc, je)
        api.submit_notice_for_review(inc["id"], notice["id"], PC)
        approve_resp = api.approve_notice(inc["id"], notice["id"], GC)
        approved = validate_success(approve_resp)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] is not None
        assert approved["approved_at"] is not None


class TestOptimisticConcurrencyOnNoticeCreate:
    def test_second_notice_with_stale_incident_version_rejected(self, api):
        """PRD §2.6: "Creating a notice requires a non-optional
        `expected_incident_version` field in the request body, carrying the
        incident `version` the client last observed. If the incident's
        current `version` does not match, the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/stale_version_occ_conflict_on_notice_create
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        je = ctx["jurisdiction_evaluations"][0]
        inc_now = get_success_data(api.get_incident(inc["id"], IC))
        v = inc_now["version"]

        # First create succeeds, bumping incident.version.
        n1_resp = api.create_notice(
            inc["id"],
            create_notice_payload(je["id"], expected_incident_version=v),
            PC,
        )
        validate_success(n1_resp, expected_status=201)

        # Second create with the same (now stale) expected version is rejected.
        n2_resp = api.create_notice(
            inc["id"],
            create_notice_payload(je["id"], expected_incident_version=v),
            PC,
        )
        validate_error(n2_resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


class TestSegregationOfDutiesOnApprove:
    def test_same_user_cannot_approve_own_drafted_notice(self, api):
        """PRD §3.7: "segregation of duties requires the acting
        `GeneralCounsel` `X-User-ID` to differ from the `PrivacyCounsel`
        `X-User-ID` who created the notice, with violation rejected as
        `ERR_SEGREGATION_OF_DUTIES` (409)."

        Design: Corner/validations/segregation_of_duties_notice_approve
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        je = ctx["jurisdiction_evaluations"][0]

        same_user = "same-user-1"
        notice = create_draft_notice(
            inc, je, creator_headers=make_privacy_counsel_headers(same_user)
        )
        api.submit_notice_for_review(
            inc["id"], notice["id"], make_privacy_counsel_headers(same_user)
        )
        approve_resp = api.approve_notice(
            inc["id"], notice["id"], make_general_counsel_headers(same_user)
        )
        validate_error(
            approve_resp,
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            expected_status=409,
        )


class TestNoticeApproveDeadline:
    def test_approve_after_jurisdiction_deadline_rejected(self, api):
        """PRD §3.7: "the linked jurisdiction evaluation's `deadline_at` must
        be strictly in the future — approving a notice whose statutory
        deadline has already passed is rejected with `ERR_DEADLINE_PASSED`
        (409), also surfaced in some flows as `ERR_NOTICE_NOT_APPROVABLE`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/approve_notice_state_vs_business_temporal
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        je = ctx["jurisdiction_evaluations"][0]
        notice = create_draft_notice(inc, je)
        api.submit_notice_for_review(inc["id"], notice["id"], PC)

        # Advance logical clock past deadline (deadline was 30 calendar days
        # from 2026-05-01 -> 2026-05-31; move to 2026-06-15).
        api.set_current_utc("2026-06-15T00:00:00Z", IC)

        approve_resp = api.approve_notice(inc["id"], notice["id"], GC)
        # PRD names both error ids for this flow; accept either.
        validate_error_is_one_of(
            approve_resp,
            [
                ApiErrorId.ERR_DEADLINE_PASSED.value,
                ApiErrorId.ERR_NOTICE_NOT_APPROVABLE.value,
            ],
        )
        # Notice remains in LEGAL_REVIEW.
        n_after = get_success_data(api.get_notice(inc["id"], notice["id"], PC))
        assert n_after["status"] == "LEGAL_REVIEW"
