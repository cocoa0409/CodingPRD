"""Off-site specialty care: the utilization-review fan-out, the deferral cycle, the
peer-review window and the authorization gate a transport must clear."""

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assert_specialty_referral,
    assert_utilization_review,
    fixtures as fx,
    make_peer_reviewer_headers,
    transport_order_payload,
    validate_error,
    validate_success,
)


class TestThreeWayDecisionFanOut:
    def test_approve_authorizes_the_parent_referral(self, api, utilization_reviewer_headers):
        """PRD §3.5: "- **`APPROVE`** moves the review from `OPEN` to `APPROVED` and
        authorizes the care: the parent referral moves from `PENDING_UR` to `AUTHORIZED`, its
        `authorized_at` is stamped from the clock, and its `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/ur_three_way_fanout_divergent_referral_side_effects
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1070", full_name="Ira Jelks", booked_at="2026-05-01T00:00:00Z"
        )
        referral, review = fx.setup_pending_ur_referral(
            inmate["id"], specialty="CARDIOLOGY", urgency="ROUTINE"
        )
        resp = api.decide_utilization_review(
            review["id"], {"decision": "APPROVE"}, utilization_reviewer_headers
        )
        data = validate_success(resp, 200)
        assert_utilization_review(data)
        assert data["status"] == "APPROVED"
        assert data["decision"] == "APPROVE"

        parent = fx.read_referral(referral["id"])
        assert_specialty_referral(parent)
        assert parent["status"] == "AUTHORIZED"
        assert_same_instant(parent["authorized_at"], "2026-05-01T00:00:00Z", "authorized_at")

    def test_deny_leaves_the_parent_referral_pending_ur(self, api, utilization_reviewer_headers):
        """PRD §3.5: "- **`DENY`** moves the review from `OPEN` to `DENIED` and —
        importantly — leaves the parent referral sitting in `PENDING_UR`. A denial is not
        final until peer review has resolved it, so the referral is not yet denied."
        PRD §3.5: "A **prospective** review — `retrospective` false — takes its allowance
        from the parent referral's urgency: `opened_at` plus 4 hours for an `EMERGENT`
        referral, `opened_at` plus 120 hours for a `ROUTINE` one."

        Design: Difficulty/non_linear_state_machine/ur_three_way_fanout_divergent_referral_side_effects
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1071", full_name="Ira Jelks", booked_at="2026-05-01T00:00:00Z"
        )
        referral, review = fx.setup_pending_ur_referral(
            inmate["id"], specialty="ONCOLOGY", urgency="ROUTINE"
        )
        resp = api.decide_utilization_review(
            review["id"], {"decision": "DENY"}, utilization_reviewer_headers
        )
        data = validate_success(resp, 200)
        assert data["status"] == "DENIED"
        assert_same_instant(
            data["turnaround_deadline_at"], "2026-05-06T00:00:00Z", "turnaround_deadline_at"
        )
        assert fx.read_referral(referral["id"])["status"] == "PENDING_UR"

    def test_defer_pushes_the_turnaround_deadline_out_by_seventy_two_hours(
        self, api, utilization_reviewer_headers
    ):
        """PRD §3.5: "- **`DEFER`** moves the review from `OPEN` to `DEFERRED`, increments
        `defer_count` by 1, and extends `turnaround_deadline_at` by a further 72 hours
        measured from its own previous value rather than from the clock. The parent referral
        again stays `PENDING_UR`. A deferral is accepted only while `defer_count` is strictly
        less than 1 — that is, only the very first deferral is permitted — and a second
        attempt is rejected at rung 14 with `ERR_MAX_DEFERRALS_EXCEEDED` (409)."

        Design: Difficulty/non_linear_state_machine/ur_three_way_fanout_divergent_referral_side_effects
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1072", full_name="Ira Jelks", booked_at="2026-05-01T00:00:00Z"
        )
        referral, review = fx.setup_pending_ur_referral(
            inmate["id"], specialty="ORTHOPEDICS", urgency="ROUTINE"
        )
        resp = api.decide_utilization_review(
            review["id"], {"decision": "DEFER"}, utilization_reviewer_headers
        )
        data = validate_success(resp, 200)
        assert data["status"] == "DEFERRED"
        assert data["defer_count"] == 1
        assert_same_instant(
            data["turnaround_deadline_at"], "2026-05-09T00:00:00Z", "turnaround_deadline_at"
        )
        assert fx.read_referral(referral["id"])["status"] == "PENDING_UR"

    def test_second_deferral_is_refused_after_the_review_is_reopened(
        self, api, utilization_reviewer_headers, provider_headers
    ):
        """PRD §3.5: "A `DEFERRED` review is reopened by a `Provider` supplying the missing
        clinical justification as `information_text`. This is the cycle edge: the review
        returns from `DEFERRED` to `OPEN`, `decision` and `decided_at` are cleared back to
        null, and `turnaround_deadline_at` retains the extended value the deferral gave it
        rather than reverting."
        PRD §3.5: "A deferral is accepted only while `defer_count` is strictly less than 1 —
        that is, only the very first deferral is permitted — and a second attempt is rejected
        at rung 14 with `ERR_MAX_DEFERRALS_EXCEEDED` (409)."

        Design: Corner/state_machines/ur_defer_cap_rejected_on_second_defer
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2140", full_name="Fay Hobbs", booked_at="2026-05-01T00:00:00Z"
        )
        referral, review = fx.setup_pending_ur_referral(
            inmate["id"], specialty="DIALYSIS", urgency="ROUTINE"
        )
        fx.decide_review(review["id"], "DEFER")
        validate_success(
            api.supply_review_information(
                review["id"],
                {"information_text": "dialysis chair availability confirmed"},
                provider_headers,
            ),
            200,
        )

        resp = api.decide_utilization_review(
            review["id"], {"decision": "DEFER"}, utilization_reviewer_headers
        )
        validate_error(resp, ApiErrorId.ERR_MAX_DEFERRALS_EXCEEDED.value, 409)

        current = fx.read_review(referral["id"], review["id"])
        assert current["status"] == "OPEN"
        assert current["defer_count"] == 1
        assert current["decision"] is None
        assert_same_instant(
            current["turnaround_deadline_at"],
            "2026-05-09T00:00:00Z",
            "turnaround_deadline_at keeps the extended value",
        )


class TestTurnaroundVariants:
    def test_retrospective_review_takes_the_flat_seven_hundred_twenty_hour_allowance(
        self, api, provider_headers
    ):
        """PRD §3.5: "A **prospective** review — `retrospective` false — takes its allowance
        from the parent referral's urgency: `opened_at` plus 4 hours for an `EMERGENT`
        referral, `opened_at` plus 120 hours for a `ROUTINE` one. A **retrospective** review
        takes a flat allowance of 720 hours from `opened_at` regardless of urgency, so an
        emergent case reviewed after the fact carries a deadline 716 hours later than the
        identical case reviewed before."
        PRD §3.5: "`turnaround_breached` compares a reference instant — the review's
        `decided_at` when a decision has been recorded, otherwise the current clock — against
        `turnaround_deadline_at`, and is true only when the reference falls strictly after the
        deadline. Equality is not a breach."

        Design: Corner/calculations/ur_retrospective_flat_turnaround_variant
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2250", full_name="Rex Tulli", booked_at="2026-05-01T00:00:00Z"
        )
        prospective_referral = fx.request_referral(
            inmate["id"], specialty="CARDIOLOGY", urgency="EMERGENT"
        )
        retrospective_referral = fx.request_referral(
            inmate["id"], specialty="ONCOLOGY", urgency="EMERGENT"
        )

        prospective = validate_success(
            api.submit_referral_for_review(
                prospective_referral["id"], {"retrospective": False}, provider_headers
            ),
            201,
        )
        retrospective = validate_success(
            api.submit_referral_for_review(
                retrospective_referral["id"], {"retrospective": True}, provider_headers
            ),
            201,
        )

        assert_same_instant(
            prospective["turnaround_deadline_at"],
            "2026-05-01T04:00:00Z",
            "prospective turnaround_deadline_at",
        )
        assert_same_instant(
            retrospective["turnaround_deadline_at"],
            "2026-05-31T00:00:00Z",
            "retrospective turnaround_deadline_at",
        )
        assert retrospective["retrospective"] is True
        assert prospective["turnaround_breached"] is False


class TestPeerReview:
    def test_escalation_is_inside_the_window_at_exactly_forty_eight_hours_and_outside_one_second_later(
        self, api, provider_headers
    ):
        """PRD §3.5: "A `Provider` escalates a `DENIED` review to `PEER_REVIEW` within a
        closed 48-hour window measured from the review's `decided_at`: escalation at exactly
        48 hours after the denial is still inside the window, and one second later is outside
        and is rejected with `ERR_PEER_REVIEW_WINDOW_EXPIRED` (422)."

        Design: Corner/state_machines/peer_review_window_closed_boundary_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2150", full_name="Gus Imani", booked_at="2026-05-01T00:00:00Z"
        )
        referral_a, review_a = fx.setup_pending_ur_referral(
            inmate["id"], specialty="CARDIOLOGY", urgency="ROUTINE"
        )
        fx.decide_review(review_a["id"], "DENY")
        referral_b, review_b = fx.setup_pending_ur_referral(
            inmate["id"], specialty="OPHTHALMOLOGY", urgency="ROUTINE"
        )
        fx.decide_review(review_b["id"], "DENY")

        fx.set_clock("2026-05-03T00:00:00Z")
        at_boundary = api.escalate_peer_review(review_a["id"], provider_headers)
        data = validate_success(at_boundary, 200)
        assert data["status"] == "PEER_REVIEW"

        fx.set_clock("2026-05-03T00:00:01Z")
        past_boundary = api.escalate_peer_review(review_b["id"], provider_headers)
        validate_error(past_boundary, ApiErrorId.ERR_PEER_REVIEW_WINDOW_EXPIRED.value, 422)
        assert fx.read_review(referral_b["id"], review_b["id"])["status"] == "DENIED"

    def test_denying_reviewer_may_not_resolve_their_own_peer_review_and_overturn_reauthorizes(
        self, api
    ):
        """PRD §3.5: "Resolution belongs to a `PeerReviewer`, who supplies a `peer_decision`
        of either `OVERTURN` or `UPHOLD` on a review in `PEER_REVIEW`. The acting `X-User-ID`
        must differ from the review's `decided_by_user_id`; a reviewer resolving their own
        denial is refused with `ERR_SEGREGATION_OF_DUTIES` (403). Both branches set
        `peer_reviewer_user_id` to the acting user and increment the review's `version` by 1,
        and both then move the parent referral out of `PENDING_UR`: `OVERTURN` moves the
        review to `OVERTURNED` and the referral from `PENDING_UR` to `AUTHORIZED` with
        `authorized_at` stamped and its `version` incremented; `UPHOLD` moves the review to
        `UPHELD` and the referral from `PENDING_UR` to `DENIED`, again incrementing the
        referral's `version`."

        Design: Corner/state_machines/peer_review_overturn_reauthorizes_referral
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2120", full_name="Dee Flores", booked_at="2026-05-01T00:00:00Z"
        )
        referral, review = fx.setup_denied_review_in_peer_review(
            inmate["id"], denier_id="u-ur-1", specialty="ONCOLOGY", urgency="ROUTINE"
        )

        conflicted = api.peer_decide_utilization_review(
            review["id"], {"peer_decision": "OVERTURN"}, make_peer_reviewer_headers("u-ur-1")
        )
        validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        resolved = api.peer_decide_utilization_review(
            review["id"], {"peer_decision": "OVERTURN"}, make_peer_reviewer_headers("u-peer-1")
        )
        data = validate_success(resolved, 200)
        assert data["status"] == "OVERTURNED"
        assert data["peer_reviewer_user_id"] == "u-peer-1"
        assert data["decided_by_user_id"] == "u-ur-1"
        assert fx.read_referral(referral["id"])["status"] == "AUTHORIZED"

    def test_uphold_drives_the_parent_referral_to_the_terminal_denied_state(self, api):
        """PRD §3.5: "`UPHOLD` moves the review to `UPHELD` and the referral from
        `PENDING_UR` to `DENIED`, again incrementing the referral's `version`."
        PRD §3.5: "`APPROVED`, `OVERTURNED` and `UPHELD` are the review's terminal states;
        `DENIED` and `DEFERRED` are way stations."

        Design: Corner/state_machines/peer_review_uphold_denies_referral
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2130", full_name="Eli Gantt", booked_at="2026-05-01T00:00:00Z"
        )
        referral, review = fx.setup_denied_review_in_peer_review(
            inmate["id"], denier_id="u-ur-1", specialty="ORTHOPEDICS", urgency="ROUTINE"
        )
        data = fx.peer_decide(review["id"], "UPHOLD", peer_id="u-peer-1")
        assert data["status"] == "UPHELD"
        assert fx.read_referral(referral["id"])["status"] == "DENIED"


class TestTransportAuthorizationGate:
    def test_transport_create_is_refused_while_the_referral_is_still_pending_ur(
        self, api, custody_officer_headers
    ):
        """PRD §3.6: "The parent referral must be `AUTHORIZED`; a referral in any other
        status refuses the create at rung 10 with `ERR_REFERRAL_NOT_AUTHORIZED` (409)."

        Design: Difficulty/cross_entity_state_dependency/transport_creation_gated_by_referral_authorization
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1180", full_name="Vic Ward", booked_at="2026-05-01T00:00:00Z"
        )
        referral, review = fx.setup_pending_ur_referral(
            inmate["id"], specialty="ORTHOPEDICS", urgency="ROUTINE"
        )
        version = fx.referral_version(referral["id"])
        resp = api.create_transport_order(
            transport_order_payload(referral["id"], "2026-05-05T08:00:00Z", version),
            custody_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_AUTHORIZED.value, 409)
        assert fx.transports_for(referral["id"]) == []

    def test_the_identical_transport_create_succeeds_once_review_approves(
        self, api, custody_officer_headers
    ):
        """PRD §3.6: "The parent referral must be `AUTHORIZED`; a referral in any other
        status refuses the create at rung 10 with `ERR_REFERRAL_NOT_AUTHORIZED` (409)."
        PRD §3.6: "The `required_escort_level` comes straight from the patient's
        `custody_level` as it stands at creation time: a `MINIMUM` custody patient requires
        `ESCORT_1`, a `MEDIUM` custody patient requires `ESCORT_2`, and a `MAXIMUM` custody
        patient requires `ESCORT_2_ARMED`."

        Design: Difficulty/cross_entity_state_dependency/transport_creation_gated_by_referral_authorization
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1181", full_name="Vic Ward", booked_at="2026-05-01T00:00:00Z"
        )
        referral, review = fx.setup_pending_ur_referral(
            inmate["id"], specialty="ORTHOPEDICS", urgency="ROUTINE"
        )
        stale_version = fx.referral_version(referral["id"])
        validate_error(
            api.create_transport_order(
                transport_order_payload(referral["id"], "2026-05-05T08:00:00Z", stale_version),
                custody_officer_headers,
            ),
            ApiErrorId.ERR_REFERRAL_NOT_AUTHORIZED.value,
            409,
        )

        fx.decide_review(review["id"], "APPROVE")
        fresh_version = fx.referral_version(referral["id"])
        resp = api.create_transport_order(
            transport_order_payload(referral["id"], "2026-05-05T08:00:00Z", fresh_version),
            custody_officer_headers,
        )
        trip = validate_success(resp, 201)
        assert trip["status"] == "DRAFT"
        assert trip["required_escort_level"] == "ESCORT_2"
        assert fx.read_referral(referral["id"])["status"] == "AUTHORIZED"
