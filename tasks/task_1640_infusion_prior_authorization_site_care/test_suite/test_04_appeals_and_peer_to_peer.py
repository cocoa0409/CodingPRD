"""Appeals ladder, appeal window, peer-to-peer scheduling/rescheduling, and
the completion cascades into the authorization request."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_timestamp_equals,
    create_appeal_payload,
    create_p2p_payload,
    decide_appeal,
    escalate_appeal,
    get_request,
    open_appeal,
    record_determination,
    reschedule_p2p,
    schedule_p2p,
    setup_appeal_at_level1,
    setup_appeal_decided_upheld,
    setup_denied_request,
    setup_p2p_on_decided_appeal,
    setup_submitted_request,
    validate_error,
    validate_success,
    AUTH_COORDINATOR_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
)


class TestAppealWindow:
    def test_appeal_at_deadline_allowed_one_second_late_rejected(self, api):
        """PRD §3.4: "A denial requires a `denial_reason` in the determination
        payload; the system stamps `denied_at` from the logical clock and sets
        `appeal_deadline` to sixty days after that instant."
        PRD §3.5: "The appeal must be opened on or before the request's
        `appeal_deadline`; a later attempt is rejected with
        `ERR_APPEAL_WINDOW_CLOSED` (422)."

        Design: Corner/validations/appeal_window_boundary_inclusive
        """
        ws_a = setup_denied_request(drug_code="J9147", member_id="M1147")
        ws_b = setup_denied_request(drug_code="J9148", member_id="M1148")

        # Denied at the 2026-08-01T00:00:00Z startup clock; +60 days.
        assert_timestamp_equals(
            ws_a["auth"]["appeal_deadline"], "2026-09-30T00:00:00Z")

        advance_clock("2026-09-30T00:00:00Z")
        appeal = validate_success(api.create_appeal(
            ws_a["auth"]["id"], create_appeal_payload("at-deadline"),
            AUTH_COORDINATOR_HEADERS), 201)
        assert appeal["status"] == "LEVEL_1", (
            "An appeal at exactly the deadline is allowed (inclusive bound)")

        advance_clock("2026-09-30T00:00:01Z")
        late = api.create_appeal(
            ws_b["auth"]["id"], create_appeal_payload("one-second-late"),
            AUTH_COORDINATOR_HEADERS)
        validate_error(late, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)


class TestDuplicateOpenAppeal:
    def test_second_open_appeal_rejected(self, api):
        """PRD §3.5: "And at most one appeal per request may be open at a
        time: if another appeal exists in any status other than
        `CLOSED_UPHELD` or `CLOSED_OVERTURNED`, creation is rejected with
        `ERR_DUPLICATE_OPEN_APPEAL` (409)."

        Design: Corner/validations/duplicate_open_appeal_rejected
        """
        ws = setup_appeal_at_level1(drug_code="J9149", member_id="M1149",
                                    reason="first")

        resp = api.create_appeal(
            ws["auth"]["id"], create_appeal_payload("second-while-open"),
            AUTH_COORDINATOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_APPEAL)

        appeals = validate_success(
            api.list_appeals(ws["auth"]["id"], AUTH_COORDINATOR_HEADERS))
        assert len(appeals) == 1, "Only one appeal exists for the request"


class TestAppealListing:
    def test_request_appeals_reverse_lookup(self, api):
        """PRD §3.5: "A coordinator may open an appeal on a `DENIED` request
        by supplying a `reason`"
        PRD §4: GET /infusion/authorization-requests/{id}/appeals lists the
        appeals of a request.

        Design: Corner/endpoints/fk_reverse_appeals_under_request
        """
        ws = setup_appeal_at_level1(drug_code="J9162", member_id="M1162",
                                    reason="contest")
        appeals = validate_success(
            api.list_appeals(ws["auth"]["id"], AUTH_COORDINATOR_HEADERS))
        assert len(appeals) == 1
        assert appeals[0]["id"] == ws["appeal"]["id"]
        assert appeals[0]["authorization_request_id"] == ws["auth"]["id"]


class TestAppealCascades:
    def test_level1_overturn_reapproves_with_fresh_window(self, api):
        """PRD §3.5: "An `OVERTURNED` decision at `LEVEL_1` closes the appeal
        as `CLOSED_OVERTURNED` and cascades: the parent request moves `DENIED`
        → `APPROVED`, its validity window is recomputed from the decision date
        exactly as in §3.4, and the request's `version` increments by one."
        PRD §3.4: "The `auth_valid_to` bound is the earliest of three
        instants: `auth_valid_from` plus the base length in days, the
        patient's `plan_year_end`, and `auth_valid_from` plus the policy's
        `max_course_days` in days."

        Design: Corner/state_machines/appeal_overturned_approves_auth_with_fresh_window
        """
        ws = setup_appeal_at_level1(drug_code="J9116", member_id="M1116",
                                    reason="new-evidence")
        advance_clock("2026-08-10T00:00:00Z")

        decided = decide_appeal(ws["appeal"]["id"], "OVERTURNED")
        assert decided["status"] == "CLOSED_OVERTURNED"

        auth = get_request(ws["auth"]["id"])
        assert auth["status"] == "APPROVED"
        assert_timestamp_equals(auth["auth_valid_from"], "2026-08-10T00:00:00Z")
        # min(+90d 2026-11-08, plan_year_end 2026-12-31, +60d 2026-10-09)
        assert_timestamp_equals(auth["auth_valid_to"], "2026-10-09T00:00:00Z")

    def test_full_escalation_ladder_to_external_upheld(self, api):
        """PRD §3.5: "Between levels, a coordinator escalates: from
        `LEVEL_1_DECIDED` to `LEVEL_2`, and from `LEVEL_2_DECIDED` to
        `EXTERNAL_REVIEW`, each incrementing `version`."
        PRD §3.5: "At `EXTERNAL_REVIEW`, an `UPHELD` decision closes the
        appeal as `CLOSED_UPHELD` and cascades the parent request `DENIED` →
        `DENIED_CLOSED` with a version increment, while an `OVERTURNED`
        decision closes it as `CLOSED_OVERTURNED` with the same approval
        cascade as the earlier levels."

        Design: Corner/state_machines/appeal_full_escalation_chain_to_external
        """
        ws = setup_appeal_at_level1(drug_code="J9117", member_id="M1117",
                                    reason="contest")
        appeal_id = ws["appeal"]["id"]

        s1 = decide_appeal(appeal_id, "UPHELD")
        assert s1["status"] == "LEVEL_1_DECIDED"
        s2 = escalate_appeal(appeal_id)
        assert s2["status"] == "LEVEL_2"
        s3 = decide_appeal(appeal_id, "UPHELD")
        assert s3["status"] == "LEVEL_2_DECIDED"
        s4 = escalate_appeal(appeal_id)
        assert s4["status"] == "EXTERNAL_REVIEW"
        s5 = decide_appeal(appeal_id, "UPHELD")
        assert s5["status"] == "CLOSED_UPHELD"

        auth = get_request(ws["auth"]["id"])
        assert auth["status"] == "DENIED_CLOSED", (
            "An externally upheld appeal closes the request DENIED_CLOSED")


class TestPeerToPeerScheduling:
    def test_touching_windows_conflict_for_same_reviewer_only(self, api):
        """PRD §3.5: "Calendar integrity is enforced per reviewer: the
        proposed window must not overlap any other review booked for the same
        `reviewer_user_id`, and because the intervals are closed, windows that
        merely touch at an endpoint still conflict; violations are rejected
        with `ERR_REVIEWER_SLOT_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/reviewer_closed_interval_touching_conflicts
        """
        ws = setup_p2p_on_decided_appeal(drug_code="J9072", member_id="M902")
        appeal_id = ws["appeal"]["id"]

        touching = api.create_peer_to_peer_review(
            appeal_id,
            create_p2p_payload("md-9", "2026-08-05T10:30:00Z",
                               "2026-08-05T11:00:00Z"),
            MEDICAL_DIRECTOR_HEADERS)
        validate_error(touching, ApiErrorId.ERR_REVIEWER_SLOT_CONFLICT)

        other = validate_success(api.create_peer_to_peer_review(
            appeal_id,
            create_p2p_payload("md-10", "2026-08-05T10:30:00Z",
                               "2026-08-05T11:00:00Z"),
            MEDICAL_DIRECTOR_HEADERS), 201)
        assert other["status"] == "SCHEDULED", (
            "The conflict is scoped to reviewer_user_id")

    def test_overlapping_window_conflicts_for_same_reviewer(self, api):
        """PRD §3.5: "Calendar integrity is enforced per reviewer: the
        proposed window must not overlap any other review booked for the same
        `reviewer_user_id`, and because the intervals are closed, windows that
        merely touch at an endpoint still conflict; violations are rejected
        with `ERR_REVIEWER_SLOT_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/reviewer_closed_interval_touching_conflicts
        """
        ws = setup_p2p_on_decided_appeal(drug_code="J9073", member_id="M903")
        overlap = api.create_peer_to_peer_review(
            ws["appeal"]["id"],
            create_p2p_payload("md-9", "2026-08-05T10:15:00Z",
                               "2026-08-05T10:45:00Z"),
            MEDICAL_DIRECTOR_HEADERS)
        validate_error(overlap, ApiErrorId.ERR_REVIEWER_SLOT_CONFLICT)


class TestPeerToPeerReschedule:
    def test_third_reschedule_rejected(self, api):
        """PRD §3.5: "Two preconditions guard it: the review's
        `reschedule_count` must be below two before the call — the third
        attempt is rejected with `ERR_P2P_RESCHEDULE_LIMIT` (409) — and the
        new window must survive the same closed-interval conflict check,
        evaluated against the reviewer's other reviews that are not yet
        `COMPLETED`."
        PRD §3.5: "Rescheduling moves a `SCHEDULED` review to a new window (a
        self-loop back to `SCHEDULED`) or revives a `NO_SHOW` review back to
        `SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/p2p_reschedule_cycle_with_limit
        """
        ws = setup_p2p_on_decided_appeal(drug_code="J9022", member_id="M402")
        p2p_id = ws["p2p"]["id"]
        assert ws["p2p"]["reschedule_count"] == 0

        first = reschedule_p2p(p2p_id, "2026-08-06T10:00:00Z",
                               "2026-08-06T10:30:00Z")
        assert first["status"] == "SCHEDULED", "Reschedule is a self-loop"
        assert first["reschedule_count"] == 1

        second = reschedule_p2p(p2p_id, "2026-08-07T10:00:00Z",
                                "2026-08-07T10:30:00Z")
        assert second["reschedule_count"] == 2

        third = api.reschedule_peer_to_peer_review(
            p2p_id,
            {"scheduled_start": "2026-08-08T10:00:00Z",
             "scheduled_end": "2026-08-08T10:30:00Z"},
            MEDICAL_DIRECTOR_HEADERS)
        validate_error(third, ApiErrorId.ERR_P2P_RESCHEDULE_LIMIT)

    def test_no_show_review_revived_by_reschedule(self, api):
        """PRD §3.5: "Rescheduling moves a `SCHEDULED` review to a new window
        (a self-loop back to `SCHEDULED`) or revives a `NO_SHOW` review back
        to `SCHEDULED`."
        PRD §3.5: "If the logical clock advances thirty minutes past a
        `SCHEDULED` call's `scheduled_end` with no completion recorded, the
        system marks the call `NO_SHOW`."

        Design: Difficulty/non_linear_state_machine/p2p_reschedule_cycle_with_limit
        """
        ws = setup_p2p_on_decided_appeal(drug_code="J9023", member_id="M403")
        p2p_id = ws["p2p"]["id"]

        advance_clock("2026-08-05T11:00:01Z")
        reviews = validate_success(api.list_peer_to_peer_reviews(
            ws["appeal"]["id"], MEDICAL_DIRECTOR_HEADERS))
        assert reviews[0]["status"] == "NO_SHOW"

        revived = reschedule_p2p(p2p_id, "2026-08-06T10:00:00Z",
                                 "2026-08-06T10:30:00Z")
        assert revived["status"] == "SCHEDULED", (
            "A NO_SHOW review is revived to SCHEDULED")
        assert revived["reschedule_count"] == 1


class TestPeerToPeerNoShow:
    def test_scheduled_call_becomes_no_show_after_grace(self, api):
        """PRD §2.4: "a peer-to-peer call still `SCHEDULED` thirty minutes
        past its `scheduled_end` becomes `NO_SHOW`"

        Design: Corner/state_machines/p2p_no_show_auto_transition
        """
        ws = setup_p2p_on_decided_appeal(drug_code="J9115", member_id="M1115")
        advance_clock("2026-08-05T11:00:01Z")
        reviews = validate_success(api.list_peer_to_peer_reviews(
            ws["appeal"]["id"], MEDICAL_DIRECTOR_HEADERS))
        assert reviews[0]["id"] == ws["p2p"]["id"]
        assert reviews[0]["status"] == "NO_SHOW", (
            "11:00:01 is past scheduled_end 10:30 + 30 minutes")


class TestPeerToPeerCompletionCascade:
    def test_uphold_completion_closes_appeal_and_denies_request(self, api):
        """PRD §3.5: "Completing a `SCHEDULED` call records an `outcome` of
        `UPHOLD` or `OVERTURN`, moves the review to `COMPLETED`, and cascades.
        An `UPHOLD` outcome moves an appeal resting at `LEVEL_1_DECIDED` or
        `LEVEL_2_DECIDED` to `CLOSED_UPHELD`; an `OVERTURN` outcome moves it
        to `CLOSED_OVERTURNED` — in both cases, from either decided level,
        with equal effect."
        PRD §3.5: "The appeal's own cascade then moves the authorization
        request: a closed-upheld appeal drives `DENIED` → `DENIED_CLOSED`,
        while a closed-overturned appeal drives `DENIED` → `APPROVED` with the
        validity window recomputed from that decision date."

        Design: Difficulty/transitive_cascade/p2p_uphold_closes_appeal_and_auth
        """
        ws = setup_p2p_on_decided_appeal(drug_code="J9032", member_id="M502")
        denied_version = ws["auth"]["version"]

        completed = validate_success(api.complete_peer_to_peer_review(
            ws["p2p"]["id"], {"outcome": "UPHOLD"}, MEDICAL_DIRECTOR_HEADERS))
        assert completed["status"] == "COMPLETED"
        assert completed["outcome"] == "UPHOLD"

        appeal = validate_success(
            api.get_appeal(ws["appeal"]["id"], MEDICAL_DIRECTOR_HEADERS))
        assert appeal["status"] == "CLOSED_UPHELD"

        auth = get_request(ws["auth"]["id"])
        assert auth["status"] == "DENIED_CLOSED"
        assert auth["version"] == denied_version + 1, (
            "The cascade increments the request version by one")

    def test_overturn_completion_reapproves_request(self, api):
        """PRD §3.5: "The appeal's own cascade then moves the authorization
        request: a closed-upheld appeal drives `DENIED` → `DENIED_CLOSED`,
        while a closed-overturned appeal drives `DENIED` → `APPROVED` with
        the validity window recomputed from that decision date."

        Design: Difficulty/transitive_cascade/p2p_uphold_closes_appeal_and_auth
        """
        ws = setup_p2p_on_decided_appeal(drug_code="J9033", member_id="M503")

        completed = validate_success(api.complete_peer_to_peer_review(
            ws["p2p"]["id"], {"outcome": "OVERTURN"}, MEDICAL_DIRECTOR_HEADERS))
        assert completed["status"] == "COMPLETED"
        assert completed["outcome"] == "OVERTURN"

        appeal = validate_success(
            api.get_appeal(ws["appeal"]["id"], MEDICAL_DIRECTOR_HEADERS))
        assert appeal["status"] == "CLOSED_OVERTURNED"

        auth = get_request(ws["auth"]["id"])
        assert auth["status"] == "APPROVED"
        # Decision date is the 2026-08-01 startup clock; course cap 60 binds.
        assert_timestamp_equals(auth["auth_valid_from"], "2026-08-01T00:00:00Z")
        assert_timestamp_equals(auth["auth_valid_to"], "2026-09-30T00:00:00Z")
