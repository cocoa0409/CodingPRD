"""Observations and leading indicators: program phase gate, triage branches,
reporter filtering, rate computation, integrity-flag floor, and the
close-cascade payoff."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_claim_record,
    close_hazard_via_single_control,
    create_active_program,
    create_claim_record,
    create_employee_record,
    create_observation_record,
    create_observation_payload,
    get_leading_indicators,
    get_observation,
    get_success_data,
    implement_control,
    list_events,
    make_employee_headers,
    make_safety_manager_headers,
    set_clock,
    setup_hazard_with_controls,
    setup_roster,
    triage_observation_link,
    triage_observation_no_action,
    validate_error,
    validate_paginated,
    validate_success,
    verify_control,
)

ADMIN = TEST_USERS["ehs_admin_headers"]


class TestObservationPhaseGate:
    def test_observation_create_rejected_for_draft_program(self, api):
        """PRD §3.4: "An `Employee`, `Supervisor`, or `SafetyManager` submits
        one against an `ACTIVE` program (the same `ERR_PROGRAM_NOT_ACTIVE`
        phase gate as hazard reporting)"

        Design: Difficulty/cross_entity_state_dependency/observation_create_gated_by_program_active
        """
        set_clock("2026-06-01T00:00:00Z")
        from test_helpers import create_program
        program = create_program()  # stays DRAFT
        _role, employees = setup_roster(member_names=("Ann A",))
        ann = employees["Ann A"]

        resp = api.create_observation(
            create_observation_payload(program["id"], ann["id"], kind="OBSERVATION",
                                       description="Wet floor"),
            make_employee_headers(ann["id"]))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
        rows, meta = validate_paginated(
            api.list_observations(ADMIN, params={"program_id": program["id"]}))
        assert meta["total_count"] == 0, "no observation may persist against DRAFT"


class TestObservationCreateRules:
    def test_observation_future_occurred_at_rejected(self, api):
        """PRD §3.4: "providing the `program_id`, a `reporter_id`, a `kind` of
        `OBSERVATION` or `NEAR_MISS`, a `description`, and an `occurred_at`
        timestamp that must not lie after the logical now
        (`ERR_FUTURE_DATE_NOT_ALLOWED`)"

        Design: Corner/validations/observation_future_occurred_at_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        ann = employees["Ann A"]

        resp = api.create_observation(
            create_observation_payload(program["id"], ann["id"], kind="OBSERVATION",
                                       description="Tomorrow's spill",
                                       occurred_at="2026-06-02T00:00:00Z"),
            make_employee_headers(ann["id"]))
        validate_error(resp, ApiErrorId.ERR_FUTURE_DATE_NOT_ALLOWED)


class TestNoActionBranch:
    def test_observation_no_action_earns_no_points(self, api):
        """PRD §3.4: "The third branch, `NO_ACTION`, moves the observation
        `SUBMITTED → NO_ACTION` and pays nothing: this is the anti-gaming rule
        of the incentive design — only validated observations earn points, so an
        operator cannot farm rewards with unfounded reports."

        Design: Corner/state_machines/observation_no_action_earns_no_points
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        observation = create_observation_record(program["id"], ann["id"],
                                                kind="OBSERVATION",
                                                description="Faded sign")

        triaged = triage_observation_no_action(observation["id"], manager["id"])
        assert triaged["status"] == "NO_ACTION"
        assert list_events(program_id=program["id"], employee_id=ann["id"]) == [], \
            "NO_ACTION is terminal and mints no incentive events"


class TestReporterFilter:
    def test_observations_filtered_by_reporter(self, api):
        """PRD §3.4: "New observations sit in `SUBMITTED` and may be listed
        filtered by `program_id`, `kind`, `status`, `reporter_id`, or
        `linked_hazard_id`."

        Design: Corner/endpoints/observations_filtered_by_reporter
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        role, employees = setup_roster()
        ann = create_observation_record(
            program["id"], employees["Marta M"]["id"], kind="OBSERVATION",
            description="From A")
        bob = create_employee_record(role["id"], full_name="Bob B")
        create_observation_record(program["id"], bob["id"], kind="NEAR_MISS",
                                  description="From B")

        filtered, meta = validate_paginated(api.list_observations(
            ADMIN, params={"program_id": program["id"],
                           "reporter_id": employees["Marta M"]["id"]}))
        assert meta["total_count"] == 1
        assert filtered[0]["reporter_id"] == employees["Marta M"]["id"]
        assert filtered[0]["description"] == "From A"

        unfiltered, meta_all = validate_paginated(api.list_observations(
            ADMIN, params={"program_id": program["id"]}))
        assert meta_all["total_count"] == 2


class TestLeadingIndicators:
    def test_leading_indicator_rate_normalization_and_exclusion(self, api):
        """PRD §3.4: "The computation considers only triaged observations —
        those in `LINKED`, `NO_ACTION`, or `CLOSED`; `SUBMITTED` reports are
        excluded. The `observation_rate` normalizes the triaged count to 200,000
        exposure hours — the standard hundred-full-time-employee-years basis —
        rounded half-up to two decimal places, and `target_met` is true when
        that rate reaches the program's `observation_target_rate`. The
        `near_miss_ratio` is the near-miss share of the triaged count — zero
        when there are no triaged observations, otherwise rounded half-up to
        four decimal places."

        Design: Corner/calculations/leading_indicator_rate_normalization_and_exclusion
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program(observation_target_rate=5.0,
                                        exposure_hours=100_000)
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        triaged = [
            create_observation_record(program["id"], ann["id"], kind="OBSERVATION",
                                      description="O1"),
            create_observation_record(program["id"], ann["id"], kind="OBSERVATION",
                                      description="O2"),
            create_observation_record(program["id"], ann["id"], kind="NEAR_MISS",
                                      description="N1"),
        ]
        create_observation_record(program["id"], ann["id"], kind="OBSERVATION",
                                  description="O3 untriaged")
        for obs in triaged:
            triage_observation_no_action(obs["id"], manager["id"])

        indicators = get_leading_indicators(program["id"], reader_id=manager["id"])
        assert indicators["observation_count"] == 3, "SUBMITTED report excluded"
        assert indicators["near_miss_count"] == 1
        assert indicators["observation_rate"] == pytest.approx(6.0, abs=1e-9), \
            "3 triaged over 100000 hours normalizes to 6.0 per 200000 hours"
        assert indicators["near_miss_ratio"] == pytest.approx(0.3333, abs=1e-9)
        assert indicators["target_met"] is True
        assert indicators["integrity_flag"] is False, "no accepted claims exist"


class TestNearMissIntegrityFloor:
    def _setup_floor_scenario(self, api, extra_observation):
        """One ACCEPTED claim plus 4 OBSERVATION + 1 NEAR_MISS (all triaged
        NO_ACTION); optionally one more triaged OBSERVATION. Returns (program,
        ann, manager)."""
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        claim = create_claim_record(program["id"], manager["id"],
                                    occurred_on="2026-03-01", kind="INDEMNITY",
                                    incurred_cents=100_000)
        accept_claim_record(claim["id"], manager["id"])
        observations = [
            create_observation_record(program["id"], ann["id"], kind="OBSERVATION",
                                      description=f"Obs {i}")
            for i in range(1, 5)
        ]
        observations.append(create_observation_record(
            program["id"], ann["id"], kind="NEAR_MISS", description="NM 1"))
        if extra_observation:
            observations.append(create_observation_record(
                program["id"], ann["id"], kind="OBSERVATION", description="Obs 5"))
        for obs in observations:
            triage_observation_no_action(obs["id"], manager["id"])
        return program, ann, manager

    def test_near_miss_ratio_at_exactly_floor_does_not_flag(self, api):
        """PRD §3.4: "The `integrity_flag` rises when the program shows claims
        but thin near-miss reporting: specifically, when at least one claim of
        the program stands in `ACCEPTED` or `CLOSED` and the near-miss ratio —
        compared in its unrounded form — falls below the program's
        `near_miss_floor_ratio`."

        Design: Difficulty/boundary_precision_check/near_miss_ratio_exactly_floor
        """
        program, _ann, manager = self._setup_floor_scenario(api,
                                                            extra_observation=False)
        indicators = get_leading_indicators(program["id"], reader_id=manager["id"])
        assert indicators["observation_count"] == 5
        assert indicators["near_miss_count"] == 1
        assert indicators["near_miss_ratio"] == pytest.approx(0.2, abs=1e-9)
        assert indicators["integrity_flag"] is False, \
            "an unrounded ratio of exactly 0.20 is not below the 0.20 floor"


class TestTriageSegregationOfDuties:
    def _closed_hazard_program(self):
        """ACTIVE program whose hazard (reported by Ann, single control) has
        been verified CLOSED by the manager. Returns (program, ann, manager,
        hazard)."""
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        hazard, _control = close_hazard_via_single_control(
            program["id"], ann["id"], manager["id"], implementer_id=ann["id"],
            severity=3, probability=2)
        return program, ann, manager, hazard

    def test_triage_by_reporter_shadows_closed_hazard_error(self, api):
        """PRD §2.6: "Business guards run after state checks, in a fixed
        relative order. Segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES`)
        precede the contractor posture gate (`ERR_PROGRAM_RESTRICTED`), which in
        turn precedes the score-contradiction check on contractor decisions
        (`ERR_DECISION_CONTRADICTS_SCORE`)"
        PRD §2.6: "Referential-state guards come after those: the
        employee-active requirement (`ERR_EMPLOYEE_INACTIVE`), the open-hazard
        requirement on triage (`ERR_HAZARD_NOT_OPEN`), the verified-evidence
        requirement (`ERR_CONTROL_NOT_VERIFIED`)"

        Design: Difficulty/priority_pair_validation_conflict/triage_safety_beats_referential
        """
        program, ann, manager, hazard = self._closed_hazard_program()
        assert hazard["status"] == "CLOSED"
        observation = create_observation_record(
            program["id"], manager["id"], kind="OBSERVATION",
            description="Another bad ladder")

        resp = api.triage_observation(
            observation["id"], {"action": "LINK_EXISTING", "hazard_id": hazard["id"]},
            make_safety_manager_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_observation(observation["id"])["status"] == "SUBMITTED"


class TestTriageAuthorization:
    def test_employee_cannot_triage_observation_returns_unauthorized(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint — or that fails an entity-backed
        ownership check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.4: "Triage is the `SafetyManager`'s gateway decision"

        Design: Corner/rbac/employee_cannot_triage_observation_returns_unauthorized
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        role, employees = setup_roster(member_names=("Ann A",))
        ann = employees["Ann A"]
        bob = create_employee_record(role["id"], full_name="Bob B")
        observation = create_observation_record(program["id"], ann["id"],
                                                kind="OBSERVATION",
                                                description="Spill")

        resp = api.triage_observation(observation["id"], {"action": "NO_ACTION"},
                                      make_employee_headers(bob["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_observation(observation["id"])["status"] == "SUBMITTED"


class TestCloseCascadePayoff:
    def _setup_cascade_scenario(self):
        """CRITICAL hazard with one control; two observations (OBSERVATION and
        NEAR_MISS) reported by Ann and linked to the hazard; the control is
        IMPLEMENTED. Returns (program, ann, manager, hazard, control, obs)."""
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        hazard, controls = setup_hazard_with_controls(
            program["id"], ann["id"], manager["id"], control_count=1,
            implementer_id=ann["id"], severity=4, probability=4,
            location="Press 7", description="Missing guard")
        o1 = create_observation_record(program["id"], ann["id"], kind="OBSERVATION",
                                       description="Guard off")
        o2 = create_observation_record(program["id"], ann["id"], kind="NEAR_MISS",
                                       description="Hand nearly caught")
        triage_observation_link(o1["id"], hazard["id"], manager["id"])
        triage_observation_link(o2["id"], hazard["id"], manager["id"])
        implement_control(controls[0]["id"], ann["id"], role="Supervisor")
        return program, ann, manager, hazard, controls[0], (o1, o2)

    def test_control_verify_close_cascade_pays_validated_events(self, api):
        """PRD §3.8: "Six source types exist, with these base points:
        `OBSERVATION_VALIDATED` pays 10, `NEAR_MISS_VALIDATED` pays 20,
        `CONTROL_VERIFIED` pays 15, `ACTION_VERIFIED` pays 10,
        `MEETING_ATTENDED` pays 5, and `CLAIMS_FREE_BONUS` pays 50."
        PRD §3.8: "The `timeliness_multiplier` rewards prompt remediation: it is
        1.25 for a `CONTROL_VERIFIED` event whose `verified_at` falls on or
        before the control's `due_date`, and 1.0 in every other case — including
        every other source type. The `points_awarded` on each event is the
        product of base points and both multipliers, rounded half-up once to a
        whole integer."

        Design: Difficulty/transitive_cascade/control_verify_close_cascade
        """
        program, ann, manager, hazard, control, (o1, o2) = \
            self._setup_cascade_scenario()
        verify_control(control["id"], manager["id"], outcome="PASS")

        near_miss_events = list_events(program_id=program["id"],
                                       employee_id=ann["id"],
                                       source_type="NEAR_MISS_VALIDATED")
        assert len(near_miss_events) == 1
        assert near_miss_events[0]["points_awarded"] == 20
        assert near_miss_events[0]["reference_id"] == o2["id"]

        all_events = list_events(program_id=program["id"], employee_id=ann["id"])
        points_by_source = {e["source_type"]: e["points_awarded"]
                            for e in all_events}
        assert points_by_source == {
            "OBSERVATION_VALIDATED": 10,
            "NEAR_MISS_VALIDATED": 20,
            "CONTROL_VERIFIED": 19,  # round_half_up(15 * 1.0 * 1.25), on time
        }
        assert sum(points_by_source.values()) == 49
