"""Hazards and controls: intake defaults, risk banding, verification gates,
the FAIL revision loop, reopen recurrence, and segregation of duties."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    add_control,
    assess_hazard,
    assert_control_item,
    assert_hazard,
    assert_iso_instant_equal,
    create_active_program,
    create_hazard_record,
    create_hazard_payload,
    get_control,
    get_hazard,
    get_success_data,
    implement_control,
    list_events,
    make_safety_manager_headers,
    make_supervisor_headers,
    set_clock,
    setup_hazard_with_controls,
    setup_roster,
    validate_error,
    validate_paginated,
    validate_success,
    verify_control,
)

ADMIN = TEST_USERS["ehs_admin_headers"]


class TestHazardIntake:
    def test_get_nonexistent_hazard_returns_not_found(self, api):
        """PRD §2.10: "The system confirms each path identifier in sequence and
        rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve, before any later identifier or any
        business rule is consulted."

        Design: Corner/entities/get_nonexistent_hazard_returns_not_found
        """
        set_clock("2026-06-01T00:00:00Z")
        resp = api.get_hazard(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_hazard_initial_state_open(self, api):
        """PRD §3.3: "New hazards open in `OPEN`."
        PRD §3.3: "Assessment is the `SafetyManager`'s call and moves the hazard
        `OPEN → ASSESSED`. The manager supplies `severity` and `probability`,
        each an integer from 1 to 5 — values outside that range are rejected
        with `ERR_INVALID_REQUEST`. From these, the system computes
        `risk_score`"

        Design: Corner/state_machines/hazard_initial_state_open
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        manager = employees["Marta M"]
        hazard = validate_success(api.create_hazard(
            create_hazard_payload(program["id"], location="L1", description="Spill",
                                  identified_by=employees["Ann A"]["id"]),
            make_safety_manager_headers(manager["id"])), expected_status=201)
        assert_hazard(hazard)
        assert hazard["status"] == "OPEN"
        assert hazard["risk_score"] is None, "risk fields are null until assessed"
        assert hazard["risk_band"] is None
        assert hazard["sla_breached"] is False

    def test_hazard_assess_invalid_severity_returns_invalid_request(self, api):
        """PRD §3.3: "The manager supplies `severity` and `probability`, each an
        integer from 1 to 5 — values outside that range are rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/hazard_assess_invalid_severity_returns_invalid_request
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        manager = employees["Marta M"]
        hazard = create_hazard_record(program["id"], manager["id"],
                                      identified_by=employees["Ann A"]["id"])

        resp = api.assess_hazard(hazard["id"], {"severity": 6, "probability": 2},
                                 make_safety_manager_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        unchanged = get_hazard(hazard["id"])
        assert unchanged["status"] == "OPEN"
        assert unchanged["risk_score"] is None


class TestAssessTransition:
    def test_assess_twice_returns_invalid_state(self, api):
        """PRD §2.6: "State and phase gates follow: the target resource's
        current status must permit the requested transition, with dedicated
        phase errors where they exist (`ERR_PROGRAM_NOT_DRAFT`,
        `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_NOT_CLOSED`,
        `ERR_PROGRAM_ALREADY_ACTIVE`, `ERR_CONTRACTOR_NOT_UNDER_REVIEW`) and
        `ERR_INVALID_STATE` as the generic fallback for any other impermissible
        transition."
        PRD §3.3: "Assessment is the `SafetyManager`'s call and moves the
        hazard `OPEN → ASSESSED`."

        Design: Corner/state_machines/assess_twice_returns_invalid_state
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        manager = employees["Marta M"]
        hazard = create_hazard_record(program["id"], manager["id"],
                                      identified_by=employees["Ann A"]["id"])
        assess_hazard(hazard["id"], manager["id"], severity=2, probability=2)

        resp = api.assess_hazard(hazard["id"], {"severity": 5, "probability": 5},
                                 make_safety_manager_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_hazard(hazard["id"])["risk_score"] == 4, \
            "the rejected re-assess leaves the first assessment intact"


class TestRiskBanding:
    def test_risk_score_band_and_sla_boundaries(self, api):
        """PRD §3.3: "From these, the system computes `risk_score` as the
        product of severity and probability, then bands it: a score of 4 or less
        is `LOW`; 5 through 9 is `MEDIUM`; 10 through 15 is `HIGH`; 16 or more
        is `CRITICAL`. The band sets the response clock: `response_sla_due` is
        the assessment timestamp plus 7 days for a `CRITICAL` hazard, 14 days
        for `HIGH`, 30 days for `MEDIUM`, and 60 days for `LOW`."

        Design: Corner/calculations/risk_score_band_and_sla_boundaries
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        manager = employees["Marta M"]
        low = create_hazard_record(program["id"], manager["id"],
                                   identified_by=employees["Ann A"]["id"],
                                   location="L1", description="Minor")
        critical = create_hazard_record(program["id"], manager["id"],
                                        identified_by=employees["Ann A"]["id"],
                                        location="L2", description="Severe")

        low = validate_success(api.assess_hazard(
            low["id"], {"severity": 4, "probability": 1},
            make_safety_manager_headers(manager["id"])))
        assert low["risk_score"] == 4
        assert low["risk_band"] == "LOW", "4 sits on the inclusive LOW upper edge"
        assert_iso_instant_equal(low["response_sla_due"], "2026-07-31T00:00:00Z")

        critical = validate_success(api.assess_hazard(
            critical["id"], {"severity": 4, "probability": 4},
            make_safety_manager_headers(manager["id"])))
        assert critical["risk_score"] == 16
        assert critical["risk_band"] == "CRITICAL", "16 sits on the CRITICAL edge"
        assert_iso_instant_equal(critical["response_sla_due"],
                                 "2026-06-08T00:00:00Z")


class TestControlListing:
    def test_hazard_controls_subresource_listing(self, api):
        """PRD §3.3: "Controls attach at the hazard: the first control created
        under an `ASSESSED` hazard automatically advances it to
        `CONTROLS_PLANNED`."
        PRD §3.3: "Controls may be browsed per hazard or listed globally,
        filtered by `hazard_id`, `implementer_id`, or `status`."

        Design: Corner/endpoints/hazard_controls_subresource_listing
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        manager = employees["Marta M"]
        hazard = create_hazard_record(program["id"], manager["id"],
                                      identified_by=employees["Ann A"]["id"],
                                      description="Noise")
        hazard = assess_hazard(hazard["id"], manager["id"], severity=3,
                               probability=2)
        add_control(hazard["id"], employees["Ann A"]["id"], manager["id"],
                    description="Enclosure", due_date="2026-06-20T00:00:00Z")
        assert get_hazard(hazard["id"])["status"] == "CONTROLS_PLANNED", \
            "the first control advances the hazard"
        add_control(hazard["id"], employees["Ann A"]["id"], manager["id"],
                    description="Signage", due_date="2026-06-22T00:00:00Z")

        rows, meta = validate_paginated(api.list_hazard_controls(
            hazard["id"], make_safety_manager_headers(manager["id"])))
        assert meta["total_count"] == 2
        assert len(rows) == 2
        for row in rows:
            assert_control_item(row)
            assert row["status"] == "PLANNED"
        assert rows[0]["description"] == "Enclosure", \
            "creation-time ascending order"


class TestVerifySegregationOfDuties:
    def test_sod_verifier_equals_implementer_rejected(self, api):
        """PRD §2.9: "The SafetyManager verifying a control must not be the
        employee recorded as its `implementer_id`."
        PRD §2.9: "Three check-and-balance pairs are enforced across the
        workflow, each rejecting with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)
        when the same identity appears on both sides of the check."

        Design: Corner/validations/sod_verifier_equals_implementer_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        ann = employees["Ann A"]
        hazard, controls = setup_hazard_with_controls(
            program["id"], ann["id"], ann["id"], control_count=1,
            implementer_id=ann["id"], severity=3, probability=2)
        implement_control(controls[0]["id"], ann["id"], role="Supervisor")

        resp = api.verify_control(controls[0]["id"], {"outcome": "PASS"},
                                  make_safety_manager_headers(ann["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_control(controls[0]["id"])["status"] == "IMPLEMENTED"
        assert list_events(program_id=program["id"], employee_id=ann["id"],
                           source_type="CONTROL_VERIFIED") == [], \
            "no CONTROL_VERIFIED event may be minted by the rejected verify"


class TestHazardVersioning:
    def test_hazard_version_increments_on_every_mutation(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one with every modification to the resource, including
        modifications produced by automatic state transitions, sweep effects,
        and cascade side effects."
        PRD §3.3: "the first control created under an `ASSESSED` hazard
        automatically advances it to `CONTROLS_PLANNED`."

        Design: Corner/cross_cutting_complexity_layers/hazard_version_increments_on_every_mutation
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        manager = employees["Marta M"]
        hazard = create_hazard_record(program["id"], manager["id"],
                                      identified_by=employees["Ann A"]["id"],
                                      description="Noise")
        assert hazard["version"] == 1
        assessed = assess_hazard(hazard["id"], manager["id"], severity=3,
                                 probability=2)
        assert assessed["version"] == 2
        add_control(hazard["id"], employees["Ann A"]["id"], manager["id"],
                    description="Enclosure")
        assert get_hazard(hazard["id"])["version"] == 3, \
            "the control-creation auto-transition is a real hazard mutation"


class TestVerifyGatedByHazardState:
    def test_control_verify_rejected_while_hazard_in_progress(self, api):
        """PRD §3.3: "Verification is only meaningful once the hazard stands in
        `PENDING_VERIFICATION` (any other hazard state yields
        `ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/control_verify_gated_by_hazard_state
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        hazard, controls = setup_hazard_with_controls(
            program["id"], ann["id"], manager["id"], control_count=2,
            implementer_id=ann["id"], severity=3, probability=2)
        implement_control(controls[0]["id"], ann["id"], role="Supervisor")
        assert get_hazard(hazard["id"])["status"] == "IN_PROGRESS", \
            "the sibling control is still PLANNED"

        resp = api.verify_control(controls[0]["id"], {"outcome": "PASS"},
                                  make_safety_manager_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_control(controls[0]["id"])["status"] == "IMPLEMENTED"
        assert get_hazard(hazard["id"])["status"] == "IN_PROGRESS"


class TestVerificationRevisionLoop:
    def _setup_revision_loop(self):
        """Hazard MEDIUM with two controls, both IMPLEMENTED, c1 already
        verified PASS. Returns (program, ann, manager, hazard, controls)."""
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        hazard, controls = setup_hazard_with_controls(
            program["id"], ann["id"], manager["id"], control_count=2,
            implementer_id=ann["id"], severity=3, probability=2,
            location="Line 3", description="Unguarded roller")
        implement_control(controls[0]["id"], ann["id"], role="Supervisor")
        implement_control(controls[1]["id"], ann["id"], role="Supervisor")
        verify_control(controls[0]["id"], manager["id"], outcome="PASS")
        return program, ann, manager, hazard, controls

    def test_hazard_closes_after_revision_and_can_reopen(self, api):
        """PRD §3.3: "When the verified control was the hazard's last
        non-verified control, the hazard itself closes, with the observation
        cascade described in §3.4."
        PRD §3.3: "A `CLOSED` hazard can recur: reopening it — a `SafetyManager`
        action requiring a `reason` — moves it `CLOSED → OPEN`, permitted only
        while the hazard's program is `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`).
        Reopening resets `sla_breached` to false and clears `severity`,
        `probability`, and the derived risk fields to null until the hazard is
        assessed again."

        Design: Difficulty/non_linear_state_machine/hazard_verification_revision_loop
        """
        _program, ann, manager, hazard, controls = self._setup_revision_loop()
        verify_control(controls[1]["id"], manager["id"], outcome="FAIL",
                       outcome_note="E-stop not wired",
                       due_date="2026-06-25T00:00:00Z")
        implement_control(controls[1]["id"], ann["id"], role="Supervisor")
        assert get_hazard(hazard["id"])["status"] == "PENDING_VERIFICATION", \
            "re-implementation readies the hazard for verification again"

        verify_control(controls[1]["id"], manager["id"], outcome="PASS")
        closed = get_hazard(hazard["id"])
        assert closed["status"] == "CLOSED", "last non-verified control verified"

        reopened = validate_success(api.reopen_hazard(
            hazard["id"], {"reason": "recurrence found in audit"},
            make_safety_manager_headers(manager["id"])))
        assert reopened["status"] == "OPEN"
        assert reopened["sla_breached"] is False
        assert reopened["severity"] is None
        assert reopened["probability"] is None
        assert reopened["risk_score"] is None
        assert reopened["risk_band"] is None
