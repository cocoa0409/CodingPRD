"""Clearance authorization: grant cascade, regress cascade, freshness, SoD."""
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    clearance_decision_payload,
    clearance_request_payload,
    get_athlete,
    grant_clearance,
    get_case,
    get_protocol,
    get_success_data,
    medical_headers,
    parse_iso,
    physician_headers,
    record_status_entry,
    regress_payload,
    set_clock,
    setup_awaiting_clearance,
    setup_pending_clearance,
    validate_error,
    validate_success,
)


class TestGrantCascade:
    def test_grant_cascades_to_protocol_case_and_tier(self, api):
        """PRD §3.5: "On grant, `decision` is set to `GRANTED`,
        `decided_by_user_id` and `decided_at` are recorded, and `expires_at`
        is set to `decided_at` plus `72` hours. The protocol transitions from
        `AWAITING_CLEARANCE` to `CLEARED`, the injury case transitions from
        `RTP` to `CLEARED` with `cleared_on` set to the current logical date,
        the athlete's `availability_tier` is recomputed, and the athlete's
        `version` increments."
        PRD §3.7: "An `RTP` case whose protocol is `AWAITING_CLEARANCE`
        forces the contribution to at most `LIMITED`."

        Design: Difficulty/transitive_cascade/clearance_grant_four_hop_cascade
        """
        sc = setup_pending_clearance()
        athlete_before = get_athlete(sc["athlete"]["id"])
        assert athlete_before["availability_tier"] == "LIMITED", (
            "RTP case at AWAITING_CLEARANCE must cap the tier at LIMITED"
        )

        resp = api.decide_clearance(
            sc["clearance"]["id"], clearance_decision_payload("GRANTED"),
            physician_headers("phys-9"),
        )
        clearance = validate_success(resp)
        assert clearance["status"] == "GRANTED"

        protocol = get_protocol(sc["protocol"]["id"])
        assert protocol["status"] == "CLEARED", (
            "hop 2: grant must transition the protocol AWAITING_CLEARANCE -> CLEARED"
        )
        case = get_case(sc["case"]["id"])
        assert case["status"] == "CLEARED", (
            "hop 3: grant must transition the case RTP -> CLEARED"
        )
        assert str(case["cleared_on"]).startswith("2026-08-12"), (
            f"cleared_on must be the current logical date, got {case['cleared_on']!r}"
        )
        athlete = get_athlete(sc["athlete"]["id"])
        assert athlete["availability_tier"] == "FULL", (
            "hop 4: with no candidate cases remaining the tier must recompute to FULL"
        )

    def test_grant_records_decision_fields_and_ttl(self, api):
        """PRD §3.5: "On grant, `decision` is set to `GRANTED`,
        `decided_by_user_id` and `decided_at` are recorded, and `expires_at`
        is set to `decided_at` plus `72` hours."

        Design: Difficulty/transitive_cascade/clearance_grant_four_hop_cascade
        """
        sc = setup_pending_clearance()
        clearance = validate_success(
            api.decide_clearance(
                sc["clearance"]["id"], clearance_decision_payload("GRANTED"),
                physician_headers("phys-9"),
            )
        )
        assert clearance["decision"] == "GRANTED"
        assert clearance["decided_by_user_id"] == "phys-9"
        decided_at = parse_iso(clearance["decided_at"])
        expires_at = parse_iso(clearance["expires_at"])
        assert expires_at - decided_at == timedelta(hours=72), (
            "expires_at must equal decided_at + 72 hours"
        )


class TestRegressCascade:
    def test_regress_expires_pending_clearance_and_reverts_case(self, api, medical_staff_headers):
        """PRD §3.4: "On regress, `current_stage_index` decrements by `1`,
        `current_stage_entered_on` is set to the current logical date,
        `regression_count` increments by `1`, the protocol's `version`
        increments, and an `RTPStageAdvance` row is appended with `kind` set
        to `REGRESSION` and `readiness_snapshot` set to `null`."
        PRD §3.4: "The parent injury case automatically transitions from `RTP`
        back to `REHAB`, any `PENDING` clearance authorization on the protocol
        transitions to `EXPIRED`, the athlete's `availability_tier` is
        recomputed, and the athlete's `version` increments."

        Design: Difficulty/transitive_cascade/regress_cascade_expires_clearance_and_recomputes_tier
        """
        sc = setup_pending_clearance()
        resp = api.regress_rtp_protocol(
            sc["protocol"]["id"], regress_payload("pain recurrence"), medical_staff_headers
        )
        protocol = validate_success(resp)
        assert protocol["status"] == "REGRESSED"
        assert protocol["current_stage_index"] == 1, (
            "regress from final stage index 2 must decrement to 1"
        )
        assert protocol["regression_count"] == 1

        clearance = get_success_data(
            api.get_clearance(sc["clearance"]["id"], medical_staff_headers)
        )
        assert clearance["status"] == "EXPIRED", (
            "hop 2: the PENDING clearance must expire on regression"
        )
        case = get_case(sc["case"]["id"])
        assert case["status"] == "REHAB", "hop 3: the case must return RTP -> REHAB"

    def test_regress_lifts_awaiting_clearance_tier_cap(self, api, medical_staff_headers):
        """PRD §3.7: "An `RTP` case whose protocol is `AWAITING_CLEARANCE`
        forces the contribution to at most `LIMITED`."
        PRD §3.4: "The parent injury case automatically transitions from `RTP`
        back to `REHAB` ... the athlete's `availability_tier` is recomputed"

        Design: Difficulty/transitive_cascade/regress_cascade_expires_clearance_and_recomputes_tier
        """
        sc = setup_pending_clearance()
        before = get_athlete(sc["athlete"]["id"])
        assert before["availability_tier"] == "LIMITED"

        get_success_data(
            api.regress_rtp_protocol(
                sc["protocol"]["id"], regress_payload("pain recurrence"),
                medical_staff_headers,
            )
        )
        after = get_athlete(sc["athlete"]["id"])
        assert after["availability_tier"] == "FULL", (
            "REHAB case whose current entry designates FULL must yield tier FULL "
            "once the AWAITING_CLEARANCE cap no longer applies"
        )


class TestEvaluationFreshness:
    def test_grant_with_stale_evaluation_rejected(self, api):
        """PRD §3.5: "A `GRANTED` decision additionally requires the protocol
        to be `AWAITING_CLEARANCE` (otherwise
        `ERR_PROTOCOL_NOT_AWAITING_CLEARANCE`) and evaluation freshness: the
        difference between the current logical timestamp and the `created_at`
        of the latest `is_current` daily status entry must not exceed `72`
        hours; a stale evaluation is rejected with `ERR_STALE_EVALUATION`."

        Design: Difficulty/cross_entity_state_dependency/clearance_grant_requires_fresh_daily_status_evaluation
        """
        sc = setup_pending_clearance()
        # Latest entry was recorded at 2026-08-12T00:00:00Z; 8 days pass.
        set_clock("2026-08-20T00:00:00Z")
        resp = api.decide_clearance(
            sc["clearance"]["id"], clearance_decision_payload("GRANTED"),
            physician_headers("phys-9"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_EVALUATION)
        clearance = get_success_data(api.get_clearance(sc["clearance"]["id"], medical_headers("med-1")))
        assert clearance["status"] == "PENDING", "rejected grant must leave the clearance PENDING"

    def test_grant_at_exactly_72h_boundary_succeeds(self, api):
        """PRD §3.5: "evaluation freshness: the difference between the current
        logical timestamp and the `created_at` of the latest `is_current`
        daily status entry must not exceed `72` hours; a stale evaluation is
        rejected with `ERR_STALE_EVALUATION`."

        An evaluation exactly 72 hours old does not exceed the limit.

        Design: Difficulty/cross_entity_state_dependency/clearance_grant_requires_fresh_daily_status_evaluation
        """
        sc = setup_pending_clearance()
        # Latest entry was created at 2026-08-12T00:00:00Z; deciding at
        # 2026-08-15T00:00:00Z is exactly the 72-hour freshness limit.
        set_clock("2026-08-15T00:00:00Z")
        clearance = validate_success(
            api.decide_clearance(
                sc["clearance"]["id"], clearance_decision_payload("GRANTED"),
                physician_headers("phys-9"),
            )
        )
        assert clearance["status"] == "GRANTED"
        protocol = get_protocol(sc["protocol"]["id"])
        assert protocol["status"] == "CLEARED"

    def test_grant_beyond_72h_rejected(self, api):
        """PRD §3.5: "the difference between the current logical timestamp and
        the `created_at` of the latest `is_current` daily status entry must
        not exceed `72` hours; a stale evaluation is rejected with
        `ERR_STALE_EVALUATION`."

        Design: Difficulty/cross_entity_state_dependency/clearance_grant_requires_fresh_daily_status_evaluation
        """
        sc = setup_pending_clearance()
        set_clock("2026-08-15T01:00:00Z")  # 73 hours after the latest entry
        resp = api.decide_clearance(
            sc["clearance"]["id"], clearance_decision_payload("GRANTED"),
            physician_headers("phys-9"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_EVALUATION)


class TestValidationPriorityOnDecide:
    def test_state_error_precedes_sod_on_granted_clearance(self, api):
        """PRD §2.5: "Generic from-state legality is evaluated next, followed
        by segregation-of-duties checks ... A higher-priority failure masks
        all lower-priority failures for the same request."
        PRD §3.5: "The clearance must be `PENDING` (otherwise
        `ERR_CLEARANCE_NOT_PENDING`)."

        A decide on an already-GRANTED clearance by the original requester
        violates both rules; the from-state error must be reported.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_clearance_decide
        """
        sc = setup_pending_clearance()
        grant_clearance(sc["clearance"]["id"], "phys-9")
        resp = api.decide_clearance(
            sc["clearance"]["id"], clearance_decision_payload("GRANTED"),
            physician_headers("med-1"),  # med-1 is also the requester (SoD violation)
        )
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_NOT_PENDING)

    def test_state_error_precedes_sod_on_returned_clearance(self, api):
        """PRD §2.5: "Generic from-state legality is evaluated next, followed
        by segregation-of-duties checks ... A higher-priority failure masks
        all lower-priority failures for the same request."
        PRD §3.5: "A `RETURNED_FOR_REVIEW` decision sets `decision`,
        `decided_by_user_id`, and `decided_at` but leaves the protocol state
        unchanged."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_clearance_decide
        """
        sc = setup_pending_clearance()
        returned = validate_success(
            api.decide_clearance(
                sc["clearance"]["id"],
                clearance_decision_payload("RETURNED_FOR_REVIEW"),
                physician_headers("phys-9"),
            )
        )
        assert returned["status"] == "RETURNED_FOR_REVIEW"
        protocol = get_protocol(sc["protocol"]["id"])
        assert protocol["status"] == "AWAITING_CLEARANCE", (
            "RETURNED_FOR_REVIEW must leave the protocol state unchanged"
        )
        resp = api.decide_clearance(
            sc["clearance"]["id"], clearance_decision_payload("GRANTED"),
            physician_headers("med-1"),  # requester attempting to decide: SoD violation
        )
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_NOT_PENDING)


class TestClearanceSegregationOfDuties:
    def test_decide_by_requester_forbidden(self, api):
        """PRD §3.5: "Segregation of duties is enforced: the decider's
        `X-User-ID` must differ from the requester's `requested_by_user_id`
        (otherwise `ERR_SOD_SELF_CLEARANCE`, HTTP 403), and the decider must
        differ from the recorder of the latest `is_current` daily status entry
        on the case (otherwise `ERR_SOD_EVALUATOR_CLEARANCE`, HTTP 403)."

        Design: Corner/errors/clearance_decide_by_requester_forbidden_sod
        """
        # Latest entry recorded by med-2 so only the self-clearance rule trips.
        sc = setup_awaiting_clearance(recorder_id="med-2")
        set_clock("2026-08-12T00:00:00Z")
        record_status_entry(
            sc["case"]["id"], "2026-08-12", designation="FULL",
            symptom_free=True, functional_test_score=95, recorder_id="med-2",
        )
        protocol = get_protocol(sc["protocol"]["id"])
        clearance = get_success_data(
            api.request_clearance(
                protocol["id"], clearance_request_payload(protocol["version"]),
                medical_headers("med-1"),
            )
        )
        resp = api.decide_clearance(
            clearance["id"], clearance_decision_payload("GRANTED"),
            physician_headers("med-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_SELF_CLEARANCE)

    def test_medical_staff_cannot_decide_clearance(self, api, medical_staff_headers):
        """PRD §2.1: "If the role is valid but not permitted for the requested
        endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: `POST /sports-med/clearances/{clearanceId}/decide` is
        authorized for `TeamPhysician` only.

        Design: Corner/rbac/medical_staff_cannot_decide_clearance
        """
        sc = setup_pending_clearance()
        resp = api.decide_clearance(
            sc["clearance"]["id"], clearance_decision_payload("GRANTED"),
            medical_staff_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
