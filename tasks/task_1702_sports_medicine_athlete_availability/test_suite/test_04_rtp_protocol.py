"""RTP protocol: creation gating, readiness gate, regression cycle, OCC."""
from test_helpers import (
    ApiErrorId,
    advance_payload,
    advance_protocol_with_ready_entry,
    create_active_plan,
    create_plan,
    get_case,
    get_protocol,
    get_success_data,
    record_status_entry,
    regress_payload,
    rtp_protocol_payload,
    set_clock,
    setup_rehab_case,
    setup_rtp_case,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRtpCreationGating:
    def test_creation_blocked_when_plan_only_draft(self, api, medical_staff_headers):
        """PRD §3.4: "The case must be in `REHAB` (otherwise
        `ERR_CASE_NOT_IN_REHAB`), no protocol may already exist for the case
        (otherwise `ERR_RTP_ALREADY_EXISTS`), and at least one `ACTIVE`
        treatment plan must exist for the case (otherwise
        `ERR_NO_ACTIVE_TREATMENT_PLAN`)."

        Design: Difficulty/cross_entity_state_dependency/rtp_creation_requires_active_treatment_plan
        """
        sc = setup_rehab_case(sport="BASKETBALL", surface="COURT",
                              mechanism="NON_CONTACT", clock="2026-08-02T00:00:00Z",
                              occurred_on="2026-08-02", entry_date="2026-08-02",
                              season=("2026-08-01", "2027-04-01"))
        create_plan(sc["case"]["id"])  # deliberately left DRAFT
        resp = api.create_rtp_protocol(
            rtp_protocol_payload(sc["case"]["id"], total_stages=4), medical_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_TREATMENT_PLAN)
        case = get_case(sc["case"]["id"])
        assert case["status"] == "REHAB", "rejected RTP creation must not advance the case"

    def test_creation_blocked_when_plan_suspended(self, api, medical_staff_headers):
        """PRD §3.4: "at least one `ACTIVE` treatment plan must exist for the
        case (otherwise `ERR_NO_ACTIVE_TREATMENT_PLAN`)."

        Design: Difficulty/cross_entity_state_dependency/rtp_creation_requires_active_treatment_plan
        """
        sc = setup_rehab_case(sport="BASKETBALL", surface="COURT",
                              mechanism="NON_CONTACT", clock="2026-08-02T00:00:00Z",
                              occurred_on="2026-08-02", entry_date="2026-08-02",
                              season=("2026-08-01", "2027-04-01"))
        plan = create_active_plan(sc["case"]["id"])
        get_success_data(api.suspend_plan(plan["id"], {"reason": "illness"}, medical_staff_headers))
        resp = api.create_rtp_protocol(
            rtp_protocol_payload(sc["case"]["id"], total_stages=4), medical_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_TREATMENT_PLAN)


class TestReadinessGateComposition:
    def _severe_concussion_rtp(self, api, medical_staff_headers):
        sc = setup_rehab_case(
            sport="FOOTBALL", position="QB", severity_class="SEVERE",
            is_concussion=True, dx_code="S06.0X1A", body_region="HEAD_NECK",
            clock="2026-08-05T00:00:00Z", occurred_on="2026-08-05",
            entry_date="2026-08-05", season=("2026-08-01", "2027-02-01"),
        )
        create_active_plan(sc["case"]["id"])
        set_clock("2026-08-10T00:00:00Z")
        protocol = get_success_data(
            api.create_rtp_protocol(
                rtp_protocol_payload(sc["case"]["id"], total_stages=4), medical_staff_headers
            )
        )
        sc["protocol"] = protocol
        return sc

    def test_advance_blocked_below_composed_min_days(self, api, medical_staff_headers):
        """PRD §3.4: "The minimum days required for the stage is the base of
        `2` days, plus `2` additional days if the case's
        `severity_class_snapshot` is `SEVERE`, plus `1` additional day if the
        case's `is_concussion_snapshot` is true."
        PRD §3.4: "For concussion cases there is an independent hard floor:
        days in stage must be at least `3`, and this check is evaluated first;
        a breach yields `ERR_CONCUSSION_MIN_DAYS`, while any other failed
        conjunct yields `ERR_READINESS_NOT_MET`."

        A SEVERE concussion case at day 4 passes the hard floor (3) but fails
        the composed minimum (2+2+1=5) -> ERR_READINESS_NOT_MET.

        Design: Difficulty/combinatorial_formula/rtp_readiness_multi_input_gate
        """
        sc = self._severe_concussion_rtp(api, medical_staff_headers)
        set_clock("2026-08-14T00:00:00Z")
        record_status_entry(
            sc["case"]["id"], "2026-08-14", designation="LIMITED",
            symptom_free=True, functional_test_score=90,
        )
        protocol = get_protocol(sc["protocol"]["id"])
        resp = api.advance_rtp_protocol(
            protocol["id"], advance_payload(protocol["version"]), medical_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_READINESS_NOT_MET)
        after = get_protocol(protocol["id"])
        assert after["current_stage_index"] == 0, "gate failure must not mutate the stage"
        assert after["status"] == "NOT_STARTED"

    def test_advance_succeeds_at_composed_min_days(self, api, medical_staff_headers):
        """PRD §3.4: "The gate passes only when days in stage is at least the
        minimum, the latest entry exists and has `symptom_free` true, the
        latest entry's `functional_test_score` is at least `80`, no regression
        is in window, and the latest entry's `entry_date` is not earlier than
        `current_stage_entered_on`."
        PRD §3.4: "On a successful advance, `current_stage_index` increments
        by `1`, `current_stage_entered_on` is set to the current logical date,
        the protocol's `version` increments, and an `RTPStageAdvance` row is
        appended with `kind` set to `ADVANCE`, `from_stage_index` and
        `to_stage_index` recording the transition, `advanced_by_user_id`
        capturing the acting user, and `readiness_snapshot` containing the
        gate-time values of `days_in_stage`, `symptom_free`,
        `functional_test_score`, and `regression_in_window`."

        Design: Difficulty/combinatorial_formula/rtp_readiness_multi_input_gate
        """
        sc = self._severe_concussion_rtp(api, medical_staff_headers)
        set_clock("2026-08-15T00:00:00Z")
        record_status_entry(
            sc["case"]["id"], "2026-08-15", designation="LIMITED",
            symptom_free=True, functional_test_score=90,
        )
        protocol = get_protocol(sc["protocol"]["id"])
        resp = api.advance_rtp_protocol(
            protocol["id"], advance_payload(protocol["version"]), medical_staff_headers
        )
        advance_row = validate_success(resp, expected_status=201)
        assert advance_row["kind"] == "ADVANCE"
        assert advance_row["from_stage_index"] == 0
        assert advance_row["to_stage_index"] == 1
        snapshot = advance_row["readiness_snapshot"]
        assert snapshot["days_in_stage"] == 5, (
            "SEVERE concussion composed minimum is 2+2+1=5 days; day 5 must pass"
        )
        assert snapshot["symptom_free"] is True
        assert snapshot["functional_test_score"] == 90
        assert snapshot["regression_in_window"] is False
        after = get_protocol(protocol["id"])
        assert after["current_stage_index"] == 1
        assert after["status"] == "IN_PROGRESS"
        assert str(after["current_stage_entered_on"]).startswith("2026-08-15")


class TestConcussionOverlayAndFloor:
    def test_concussion_floor_fires_before_composed_gate(self, api, medical_staff_headers):
        """PRD §3.4: "For concussion cases there is an independent hard floor:
        days in stage must be at least `3`, and this check is evaluated first;
        a breach yields `ERR_CONCUSSION_MIN_DAYS`, while any other failed
        conjunct yields `ERR_READINESS_NOT_MET`."

        Design: Corner/state_machines/concussion_floor_fires_before_composed_gate
        """
        sc = setup_rtp_case(
            sport="FOOTBALL", position="WR", is_concussion=True,
            dx_code="S06.0X0A", body_region="HEAD_NECK", total_stages=4,
            clock="2026-08-02T00:00:00Z", occurred_on="2026-08-02",
            entry_date="2026-08-02", season=("2026-08-01", "2027-02-01"),
        )
        set_clock("2026-08-04T00:00:00Z")
        record_status_entry(
            sc["case"]["id"], "2026-08-04", designation="LIMITED",
            symptom_free=True, functional_test_score=90,
        )
        protocol = get_protocol(sc["protocol"]["id"])
        resp = api.advance_rtp_protocol(
            protocol["id"], advance_payload(protocol["version"]), medical_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_CONCUSSION_MIN_DAYS)
        after = get_protocol(protocol["id"])
        assert after["current_stage_index"] == 0, "floor breach must not mutate the stage"

    def test_advance_rejected_while_suspended_concussion(self, api, medical_staff_headers):
        """PRD §3.2: "For concussion cases, if the new latest `is_current`
        entry has `symptom_free` set to `false` while the RTP protocol is
        `IN_PROGRESS`, the protocol automatically transitions to
        `SUSPENDED_CONCUSSION`"
        PRD §3.4: "The protocol must be in `NOT_STARTED`, `IN_PROGRESS`, or
        `REGRESSED`; attempts from `SUSPENDED_CONCUSSION`,
        `AWAITING_CLEARANCE`, or `CLEARED` are rejected with
        `ERR_PROTOCOL_NOT_ADVANCEABLE`."

        Design: Corner/state_machines/advance_from_suspended_concussion_rejected
        """
        sc = setup_rtp_case(
            sport="FOOTBALL", position="QB", is_concussion=True,
            dx_code="S06.0X1A", body_region="HEAD_NECK", total_stages=4,
            clock="2026-08-02T00:00:00Z", occurred_on="2026-08-02",
            entry_date="2026-08-02", season=("2026-08-01", "2027-02-01"),
        )
        # Advance to stage 1 at day 4 (composed 2+1=3, floor 3 -> passes).
        advance_protocol_with_ready_entry(
            sc["case"]["id"], sc["protocol"]["id"], "2026-08-06",
            functional_test_score=85,
        )
        # Symptom flare: a new latest entry with symptom_free false.
        set_clock("2026-08-10T00:00:00Z")
        record_status_entry(
            sc["case"]["id"], "2026-08-10", designation="OUT",
            symptom_free=False, functional_test_score=50,
        )
        protocol = get_protocol(sc["protocol"]["id"])
        assert protocol["status"] == "SUSPENDED_CONCUSSION", (
            "symptom_free=false entry must auto-suspend the in-progress protocol"
        )
        resp = api.advance_rtp_protocol(
            protocol["id"], advance_payload(protocol["version"]), medical_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_ADVANCEABLE)


class TestRegressionCycle:
    def _regressed_protocol(self, api, medical_staff_headers):
        """MINOR non-concussion case; protocol (4 stages) advanced to stage 1,
        then regressed. Returns (scenario, protocol_after_regress)."""
        sc = setup_rtp_case(
            sport="BASKETBALL", position="G", dx_code="S93.4",
            body_region="ANKLE_FOOT", total_stages=4,
            clock="2026-08-02T00:00:00Z", occurred_on="2026-08-02",
            entry_date="2026-08-02", season=("2026-08-01", "2027-04-01"),
        )
        advance_protocol_with_ready_entry(
            sc["case"]["id"], sc["protocol"]["id"], "2026-08-05",
            functional_test_score=85,
        )
        resp = api.regress_rtp_protocol(
            sc["protocol"]["id"], regress_payload("swelling returned"), medical_staff_headers
        )
        protocol = validate_success(resp)
        return sc, protocol

    def test_regress_decrements_stage_and_returns_case_to_rehab(self, api, medical_staff_headers):
        """PRD §3.4: "On regress, `current_stage_index` decrements by `1`,
        `current_stage_entered_on` is set to the current logical date,
        `regression_count` increments by `1`, the protocol's `version`
        increments, and an `RTPStageAdvance` row is appended with `kind` set
        to `REGRESSION` and `readiness_snapshot` set to `null`. The parent
        injury case automatically transitions from `RTP` back to `REHAB`, any
        `PENDING` clearance authorization on the protocol transitions to
        `EXPIRED`, the athlete's `availability_tier` is recomputed, and the
        athlete's `version` increments."

        Design: Difficulty/non_linear_state_machine/rtp_protocol_regression_cycle
        """
        sc, protocol = self._regressed_protocol(api, medical_staff_headers)
        assert protocol["status"] == "REGRESSED"
        assert protocol["current_stage_index"] == 0, "regress from stage 1 must decrement to 0"
        assert protocol["regression_count"] == 1

        case = get_case(sc["case"]["id"])
        assert case["status"] == "REHAB", "regression must cascade the case RTP -> REHAB"

        rows, _meta = validate_paginated(
            api.list_protocol_advances(sc["protocol"]["id"], medical_staff_headers)
        )
        regressions = [r for r in rows if r["kind"] == "REGRESSION"]
        assert len(regressions) == 1
        reg = regressions[0]
        assert reg["from_stage_index"] == 1 and reg["to_stage_index"] == 0
        assert reg["readiness_snapshot"] is None, (
            "REGRESSION rows must carry readiness_snapshot null"
        )

    def test_immediate_readvance_blocked_by_regression_window(self, api, medical_staff_headers):
        """PRD §3.4: "A regression is in window if any `RTPStageAdvance` with
        `kind` equal to `REGRESSION` has a `created_at` date within the `14`
        days before the current logical date, inclusive."
        PRD §3.4: "The gate passes only when days in stage is at least the
        minimum, the latest entry exists and has `symptom_free` true, the
        latest entry's `functional_test_score` is at least `80`, no regression
        is in window, and the latest entry's `entry_date` is not earlier than
        `current_stage_entered_on`."

        Design: Difficulty/non_linear_state_machine/rtp_protocol_regression_cycle
        """
        sc, protocol = self._regressed_protocol(api, medical_staff_headers)
        # Same day as the regression: days-in-stage 0 < 2 and a regression is
        # in window — either way the readiness gate must reject.
        protocol = get_protocol(protocol["id"])
        resp = api.advance_rtp_protocol(
            protocol["id"], advance_payload(protocol["version"]), medical_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_READINESS_NOT_MET)
        after = get_protocol(protocol["id"])
        assert after["status"] == "REGRESSED"
        assert after["current_stage_index"] == 0

    def test_readvance_after_regression_window_closes_cycle(self, api, medical_staff_headers):
        """PRD §3.4: "The protocol must be in `NOT_STARTED`, `IN_PROGRESS`, or
        `REGRESSED`; attempts from `SUSPENDED_CONCUSSION`,
        `AWAITING_CLEARANCE`, or `CLEARED` are rejected with
        `ERR_PROTOCOL_NOT_ADVANCEABLE`."

        Design: Difficulty/non_linear_state_machine/rtp_protocol_regression_cycle
        """
        sc, protocol = self._regressed_protocol(api, medical_staff_headers)
        # Regressed on 2026-08-05; 15 days later the regression falls outside
        # the 14-day lookback and days-in-stage (15) clears the 2-day minimum.
        advance_protocol_with_ready_entry(
            sc["case"]["id"], sc["protocol"]["id"], "2026-08-20",
            functional_test_score=90,
        )
        after = get_protocol(sc["protocol"]["id"])
        assert after["status"] == "IN_PROGRESS", (
            "advance from REGRESSED must re-enter IN_PROGRESS (cycle closes)"
        )
        assert after["current_stage_index"] == 1
        assert after["regression_count"] == 1


class TestProtocolOcc:
    def test_advance_with_stale_protocol_version_rejected(self, api, medical_staff_headers):
        """PRD §2.6: "A request to append a stage advance to an RTP protocol
        must carry `expected_protocol_version` matching the protocol's current
        `version`."
        PRD §2.6: "If the supplied value does not match the parent entity's
        current `version`, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_protocol_version_on_advance_returns_412
        """
        sc = setup_rtp_case(
            sport="BASKETBALL", position="G", dx_code="S93.4",
            body_region="ANKLE_FOOT", total_stages=4,
            clock="2026-08-02T00:00:00Z", occurred_on="2026-08-02",
            entry_date="2026-08-02", season=("2026-08-01", "2027-04-01"),
        )
        stale_version = sc["protocol"]["version"]
        advance_protocol_with_ready_entry(
            sc["case"]["id"], sc["protocol"]["id"], "2026-08-05",
            functional_test_score=85,
        )
        # The successful advance bumped the protocol version; retrying with
        # the pre-advance version must be rejected.
        resp = api.advance_rtp_protocol(
            sc["protocol"]["id"], advance_payload(stale_version), medical_staff_headers
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
