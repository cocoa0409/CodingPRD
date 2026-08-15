"""Community events: buffer-inclusive street-closure conflicts and the
certification / large-gathering approval gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_officer,
    decide_review,
    make_officer_headers,
    open_certification_review,
    propose_event,
    setup_cert_scoring_group,
    setup_group_with_member,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestClosureConflict:
    def _provisional_group_with_anchor(self, api):
        """PROVISIONAL group (CONDITIONAL review at 45 composite points) with one
        APPROVED BLOCK_PARTY whose closure is 2026-08-17T10:00-12:00, buffered
        to the closed interval [08:00, 14:00]."""
        ws = setup_cert_scoring_group(
            "Buffer Watch", "PCT16",
            member_count=5, trained_count=5,
            quorum_meeting_count=2, sent_alert_count=3,
        )
        review = open_certification_review(ws["group"]["id"], ws["reviewer"])
        assert review["certification_points"] == 45, (
            "5 trained members + 10 meeting + 0 event + 15 captain + 15 alerts"
        )
        decide_review(review["id"], ws["reviewer"], "CONDITIONAL")
        group = validate_success(api.get_watch_group(ws["group"]["id"], COORD))
        assert group["certification_status"] == "PROVISIONAL"

        anchor = propose_event(
            group["id"], "BLOCK_PARTY",
            "2026-08-17T10:00:00Z", "2026-08-17T12:00:00Z", 25,
        )
        approved = validate_success(
            api.approve_community_event(
                anchor["id"], make_officer_headers(ws["trainer"]["id"]),
            )
        )
        assert approved["event_status"] == "APPROVED"
        return ws, group

    def test_zero_gap_touch_of_buffered_windows_rejected(self, api):
        """PRD §3.7: "A two-hour buffer is prepended to `street_closure_start`
        and appended to `street_closure_end`, and the resulting buffered closed
        interval must not touch the buffered window of any other `APPROVED` event
        of the same group — zero-gap adjacency is forbidden, so the gap between
        two buffered windows must be greater than zero."
        PRD §3.7: "A collision is rejected with `ERR_CLOSURE_CONFLICT`, and the
        check runs both at proposal and again at approval."

        The anchor's buffered window is [08:00, 14:00]; the probing event's own
        window is likewise buffered on both ends, so its raw closure start of
        16:00:00 buffers to a window that touches the anchor at exactly 14:00 —
        zero gap.

        Design: Difficulty/resource_temporal_overlap/event_closure_buffer_inclusive_zero_gap_rejected
        """
        ws, group = self._provisional_group_with_anchor(api)
        resp = api.create_community_event(
            {
                "watch_group_id": group["id"],
                "event_kind": "BLOCK_PARTY",
                "street_closure_start": "2026-08-17T16:00:00Z",
                "street_closure_end": "2026-08-17T18:00:00Z",
                "estimated_attendance": 20,
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_CLOSURE_CONFLICT)

    def test_strictly_positive_gap_accepted(self, api):
        """PRD §3.7: "the gap between two buffered windows must be greater than
        zero."

        A raw closure start of 16:00:01 buffers to [14:00:01, 20:00], leaving a
        strictly positive one-second gap after the anchor's buffered end 14:00.

        Design: Difficulty/resource_temporal_overlap/event_closure_buffer_inclusive_zero_gap_rejected
        """
        ws, group = self._provisional_group_with_anchor(api)
        event = validate_success(
            api.create_community_event(
                {
                    "watch_group_id": group["id"],
                    "event_kind": "BLOCK_PARTY",
                    "street_closure_start": "2026-08-17T16:00:01Z",
                    "street_closure_end": "2026-08-17T18:00:00Z",
                    "estimated_attendance": 20,
                },
                COORD,
            ),
            201,
        )
        assert event["event_status"] == "PROPOSED"
        approved = validate_success(
            api.approve_community_event(
                event["id"], make_officer_headers(ws["trainer"]["id"]),
            )
        )
        assert approved["event_status"] == "APPROVED", (
            "The one-second positive gap is allowed at proposal and at approval"
        )


class TestApprovalGates:
    def _gate_workspace(self, api):
        """UNCERTIFIED group (FORMATION), one member, one officer, and NO
        data-share agreement."""
        group, block, member = setup_group_with_member("Gate Watch", "PCT12")
        officer = create_officer("B120", "Officer G", "PCT12")
        return group, block, member, officer

    def test_national_night_out_requires_certified(self, api):
        """PRD §3.7: "The certification gate requires the group's
        `certification_status` to be `CERTIFIED` for a `NATIONAL_NIGHT_OUT`, and
        either `PROVISIONAL` or `CERTIFIED` for the other kinds; a shortfall is
        rejected with `ERR_CERTIFICATION_REQUIRED`."

        Design: Difficulty/boundary_precision_check/certification_empty_set_and_attendance_tier_boundary
        """
        group, _b, _m, officer = self._gate_workspace(api)
        nno = propose_event(
            group["id"], "NATIONAL_NIGHT_OUT",
            "2026-08-20T18:00:00Z", "2026-08-20T21:00:00Z", 50,
        )
        resp = api.approve_community_event(
            nno["id"], make_officer_headers(officer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED)
        after = validate_success(api.get_community_event(nno["id"], COORD))
        assert after["event_status"] == "PROPOSED"

    def test_attendance_exactly_100_requires_active_agreement(self, api):
        """PRD §3.7: "The large-gathering notification rule requires the group to
        hold an `ACTIVE` data-sharing agreement whenever `estimated_attendance`
        reaches the permit tier of 100 or more; without one, approval is rejected
        with `ERR_DATA_SHARE_REQUIRED`."
        PRD §2.6: "then the data-sharing gate (`ERR_DATA_SHARE_REQUIRED`); then
        the certification gate (`ERR_CERTIFICATION_REQUIRED`)"

        Design: Difficulty/boundary_precision_check/certification_empty_set_and_attendance_tier_boundary
        """
        group, _b, _m, officer = self._gate_workspace(api)
        event = propose_event(
            group["id"], "BLOCK_PARTY",
            "2026-08-22T10:00:00Z", "2026-08-22T12:00:00Z", 100,
        )
        resp = api.approve_community_event(
            event["id"], make_officer_headers(officer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DATA_SHARE_REQUIRED)
        after = validate_success(api.get_community_event(event["id"], COORD))
        assert after["event_status"] == "PROPOSED"

    def test_attendance_99_falls_through_to_certification_gate(self, api):
        """PRD §3.7: "whenever `estimated_attendance` reaches the permit tier of
        100 or more" — at 99 the data-sharing gate stays silent.
        PRD §3.7: "either `PROVISIONAL` or `CERTIFIED` for the other kinds; a
        shortfall is rejected with `ERR_CERTIFICATION_REQUIRED`."

        Design: Difficulty/boundary_precision_check/certification_empty_set_and_attendance_tier_boundary
        """
        group, _b, _m, officer = self._gate_workspace(api)
        event = propose_event(
            group["id"], "BLOCK_PARTY",
            "2026-08-24T10:00:00Z", "2026-08-24T12:00:00Z", 99,
        )
        resp = api.approve_community_event(
            event["id"], make_officer_headers(officer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED)
        after = validate_success(api.get_community_event(event["id"], COORD))
        assert after["event_status"] == "PROPOSED"
