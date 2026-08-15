"""Sterile processing: turns, decon/cooldown minimums, slot capacity, the
rework loop, staging, and the readiness-projection boundary."""
from test_helpers import (
    ApiErrorId,
    add_tray,
    approve_request,
    assert_same_instant,
    coordinator,
    create_request,
    deliver_and_verify,
    get_success_data,
    list_escalations_of_request,
    make_nurse_headers,
    make_tech_headers,
    open_turn,
    set_clock,
    setup_approved_request,
    start_cycle_at,
    sterilize_tray,
    submit_request,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    fail_qa_payload,
    start_cycle_payload,
)

TECH = make_tech_headers()
NURSE = make_nurse_headers()

# Case dated 2026-08-05: far enough out that no readiness flip lands inside
# the twenty-four-hour escalation window at the clock times these tests use.
FAR_CASE_START = "2026-08-05T09:00:00Z"
FAR_CASE_END = "2026-08-05T12:00:00Z"


def _checked_in_world(**kwargs):
    """Standard world with the tray delivered on time and verified
    (tray CHECKED_IN)."""
    world = setup_approved_request(**kwargs)
    deliver_and_verify(world, at="2026-08-02T08:00:00Z")
    return world


def _rework_chain_to_quarantine(api, world):
    """Drive the tray through three QA failures. Returns the three turns."""
    tray = world["trays"][0]
    turns = []
    for cycle_at, reason in (("2026-08-02T08:35:00Z", "wet pack"),
                             ("2026-08-02T09:20:00Z", "BI failure"),
                             ("2026-08-02T10:05:00Z", "wet pack again")):
        turn = open_turn(tray["id"])
        start_cycle_at(world, turn["id"], cycle_at)
        get_success_data(api.fail_qa(turn["id"], fail_qa_payload(reason),
                                     TECH))
        turns.append(turn)
    return turns


class TestTurnGuards:
    def test_turn_release_from_decontaminating_rejected(self, api):
        """PRD: "the tech may release a turn only while it is in `COOLDOWN` —
        any other turn state fails with `ERR_TURN_INVALID_STATE` (409)"

        Design: Corner/state_machines/turn_release_from_decontaminating_rejected
        """
        world = _checked_in_world(priority_class="STANDARD",
                                  case_start=FAR_CASE_START,
                                  case_end=FAR_CASE_END)
        tray = world["trays"][0]
        turn = open_turn(tray["id"])
        assert turn["status"] == "DECONTAMINATING"

        resp = api.release_turn(turn["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_TURN_INVALID_STATE)
        turn_after = validate_success(api.get_turn(turn["id"], TECH))
        assert turn_after["status"] == "DECONTAMINATING"
        tray_after = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_after["status"] == "PROCESSING"

    def test_turn_start_cycle_decon_minimum_boundary(self, api):
        """PRD: "Decontamination must have run its minimum: the current time
        must be at least `decon_started_at` plus thirty minutes, else
        `ERR_DECON_MIN_NOT_ELAPSED` (409)."

        Design: Corner/state_machines/turn_start_cycle_decon_minimum_boundary
        """
        world = _checked_in_world(priority_class="STANDARD",
                                  case_start=FAR_CASE_START,
                                  case_end=FAR_CASE_END)
        tray = world["trays"][0]
        # Turn opened at 2026-08-02T08:00:00Z (the check-in/verify clock).
        turn = open_turn(tray["id"])
        assert_same_instant(turn["decon_started_at"], "2026-08-02T08:00:00Z",
                            "turn.decon_started_at")

        set_clock("2026-08-02T08:29:00Z")
        resp = api.start_cycle(turn["id"],
                               start_cycle_payload(world["sterilizer"]["id"]),
                               TECH)
        validate_error(resp, ApiErrorId.ERR_DECON_MIN_NOT_ELAPSED)
        assert validate_success(
            api.get_turn(turn["id"], TECH))["status"] == "DECONTAMINATING"

        # At exactly decon_started_at + 30 minutes the minimum is met
        # ("at least" is inclusive).
        set_clock("2026-08-02T08:30:00Z")
        started = validate_success(
            api.start_cycle(turn["id"],
                            start_cycle_payload(world["sterilizer"]["id"]),
                            TECH))
        assert started["status"] == "STERILIZING"

    def test_turn_release_cooldown_boundary(self, api):
        """PRD: "the tech may release a turn only while it is in `COOLDOWN` —
        any other turn state fails with `ERR_TURN_INVALID_STATE` (409) — and
        only once the current time has reached `cycle_completed_at` plus the
        unit's `cooldown_minutes`, else `ERR_COOLDOWN_NOT_ELAPSED` (409)."

        Design: Corner/state_machines/turn_release_cooldown_boundary
        """
        world = _checked_in_world(priority_class="STANDARD",
                                  case_start=FAR_CASE_START,
                                  case_end=FAR_CASE_END)
        tray = world["trays"][0]
        turn = open_turn(tray["id"])
        # Cycle 08:35 + 60 min completes 09:35; cooldown 30 min ends 10:05.
        start_cycle_at(world, turn["id"], "2026-08-02T08:35:00Z")

        set_clock("2026-08-02T09:45:00Z")  # sweep moves the turn to COOLDOWN
        turn_now = validate_success(api.get_turn(turn["id"], TECH))
        assert turn_now["status"] == "COOLDOWN"
        resp = api.release_turn(turn["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_COOLDOWN_NOT_ELAPSED)
        assert validate_success(
            api.get_turn(turn["id"], TECH))["status"] == "COOLDOWN"

        set_clock("2026-08-02T10:05:00Z")  # exactly cycle end + cooldown
        released = validate_success(api.release_turn(turn["id"], TECH))
        assert released["status"] == "RELEASED"
        tray_after = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_after["status"] == "STERILE_READY"


class TestStaging:
    def test_tray_stage_before_sterile_ready_rejected(self, api):
        """PRD: "From `STERILE_READY`, an `ORCirculatorNurse` may stage the
        tray for its case, moving it to `STAGED`"
        PRD: "**State guards** — the target entity is in a state that permits the
        invoked transition, else the per-entity state error (the
        `ERR_{ENTITY}_INVALID_STATE` family, `ERR_VENDOR_NOT_ACTIVE`,
        `ERR_CASE_READINESS_BLOCKED`, `ERR_VENDOR_HAS_OPEN_WORK`) at 409."

        Design: Corner/state_machines/tray_stage_before_sterile_ready_rejected
        """
        world = _checked_in_world(priority_class="STANDARD",
                                  case_start=FAR_CASE_START,
                                  case_end=FAR_CASE_END)
        tray = world["trays"][0]
        resp = api.stage_tray(tray["id"], NURSE)
        validate_error(resp, ApiErrorId.ERR_TRAY_INVALID_STATE)
        assert validate_success(
            api.get_tray(tray["id"], coordinator()))["status"] == "CHECKED_IN"

    def test_tech_cannot_stage_tray(self, api):
        """PRD: "Beyond authentication, each operation is restricted to
        designated roles; an authenticated caller whose role is not on an
        operation's authorized list is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD: "From `STERILE_READY`, an `ORCirculatorNurse` may stage the tray
        for its case, moving it to `STAGED`"

        Design: Corner/rbac/tech_cannot_stage_tray
        """
        world = _checked_in_world()
        tray = world["trays"][0]
        sterilize_tray(world, tray["id"], cycle_at="2026-08-02T08:35:00Z",
                      release_at="2026-08-02T10:10:00Z")
        assert validate_success(
            api.get_tray(tray["id"], coordinator()))["status"] == "STERILE_READY"

        resp = api.stage_tray(tray["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert validate_success(
            api.get_tray(tray["id"], coordinator()))["status"] == "STERILE_READY"


class TestReworkCycle:
    """Difficulty instance: the guard-counted PROCESSING -> CHECKED_IN
    rework loop and its exit into QUARANTINED at the third failure."""

    def test_tray_rework_loop_returns_checked_in_twice(self, api):
        """PRD: "The tray's `rework_count` increments by one; while the
        resulting count is at most two, the tray returns from `PROCESSING` to
        `CHECKED_IN`, its projection is recomputed because it needs a fresh
        turn, and readiness is recomputed with the flip-escalation rule of
        §3.4 in force."
        PRD: "The tray must be `CHECKED_IN`, else `ERR_TRAY_INVALID_STATE`
        (409); the tray moves to `PROCESSING`, the turn begins in
        `DECONTAMINATING` with `decon_started_at` stamped from the clock,
        `sterilizer_unit_id` still null, and `attempt_number` set to one plus
        the count of prior turns on that tray."

        Design: Difficulty/non_linear_state_machine/tray_rework_cycle_to_quarantine
        """
        world = _checked_in_world(priority_class="STANDARD",
                                  case_start=FAR_CASE_START,
                                  case_end=FAR_CASE_END)
        tray = world["trays"][0]

        # First failure: PROCESSING -> CHECKED_IN, rework_count 1.
        turn1 = open_turn(tray["id"])
        start_cycle_at(world, turn1["id"], "2026-08-02T08:35:00Z")
        get_success_data(api.fail_qa(turn1["id"], fail_qa_payload("wet pack"),
                                     TECH))
        tray_now = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_now["status"] == "CHECKED_IN"
        assert tray_now["rework_count"] == 1
        turn1_now = validate_success(api.get_turn(turn1["id"], TECH))
        assert turn1_now["status"] == "FAILED_QA"
        assert turn1_now["attempt_number"] == 1

        # Second failure: the loop turns once more.
        turn2 = open_turn(tray["id"])
        assert turn2["attempt_number"] == 2
        start_cycle_at(world, turn2["id"], "2026-08-02T09:20:00Z")
        get_success_data(api.fail_qa(turn2["id"], fail_qa_payload("BI failure"),
                                     TECH))
        tray_now = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_now["status"] == "CHECKED_IN"
        assert tray_now["rework_count"] == 2
        assert validate_success(
            api.get_turn(turn2["id"], TECH))["status"] == "FAILED_QA"

    def test_tray_rework_third_failure_quarantines(self, api):
        """PRD: "When the failure would push the count past two — the third
        QA failure — the tray instead moves from `PROCESSING` to
        `QUARANTINED`, an `OPEN` escalation of type `STERILIZATION_DELAY` is
        auto-created, and readiness is recomputed."
        PRD: "The tray must be `CHECKED_IN`, else `ERR_TRAY_INVALID_STATE`
        (409)"

        Design: Difficulty/non_linear_state_machine/tray_rework_cycle_to_quarantine
        """
        world = _checked_in_world(priority_class="STANDARD",
                                  case_start=FAR_CASE_START,
                                  case_end=FAR_CASE_END)
        tray = world["trays"][0]
        turns = _rework_chain_to_quarantine(api, world)

        tray_now = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_now["status"] == "QUARANTINED", \
            "the third QA failure exceeds the two-rework budget"
        assert tray_now["rework_count"] == 3
        for i, turn in enumerate(turns, start=1):
            turn_now = validate_success(api.get_turn(turn["id"], TECH))
            assert turn_now["status"] == "FAILED_QA"
            assert turn_now["attempt_number"] == i

        # A quarantined tray cannot take another turn.
        resp = api.create_turn(tray["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_TRAY_INVALID_STATE)


class TestFailQaCascade:
    """Difficulty instance: fail-qa -> tray mutation -> readiness flip ->
    auto-escalation (depth-3 chain inside the 24-hour window)."""

    def _cascade_world(self):
        """Tray CHECKED_IN for the 2026-08-03 09:00 case (required
        sterile-ready 08:00); turn opened 05:30, cycle started 06:00 with a
        feasible 07:30 projection; clock at 06:30."""
        world = setup_approved_request()
        deliver_and_verify(world, at="2026-08-02T08:00:00Z")
        tray = world["trays"][0]
        set_clock("2026-08-03T05:30:00Z")
        turn = open_turn(tray["id"])
        start_cycle_at(world, turn["id"], "2026-08-03T06:00:00Z")
        set_clock("2026-08-03T06:30:00Z")
        return world, tray, turn

    def test_fail_qa_mutates_tray_projection_and_readiness(self, api):
        """PRD: "The tray's `rework_count` increments by one; while the
        resulting count is at most two, the tray returns from `PROCESSING` to
        `CHECKED_IN`, its projection is recomputed because it needs a fresh
        turn, and readiness is recomputed with the flip-escalation rule of
        §3.4 in force."
        PRD: "While a tray is `CHECKED_IN` with no active turn, its
        `projected_sterile_ready_at` is the current time plus the
        thirty-minute decontamination minimum plus the shortest full
        cycle-plus-cooldown available anywhere — the minimum, over all
        registered sterilizer units, of each unit's `cycle_minutes` plus its
        `cooldown_minutes`."
        PRD: "In every other situation — a request with zero trays, any tray
        still `EXPECTED`, `MISSING`, or `QUARANTINED`, or any projection that
        is null or lands after its deadline — the posture is `NOT_READY`."

        Design: Difficulty/transitive_cascade/fail_qa_cascade_tray_to_readiness_to_escalation
        """
        world, tray, turn = self._cascade_world()
        before = validate_success(
            api.get_request(world["request"]["id"], coordinator()))
        assert before["readiness"] == "AT_RISK", \
            "07:30 projection meets the 08:00 requirement"

        get_success_data(api.fail_qa(turn["id"], fail_qa_payload("BI failure"),
                                     TECH))
        turn_now = validate_success(api.get_turn(turn["id"], TECH))
        assert turn_now["status"] == "FAILED_QA"
        tray_now = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_now["status"] == "CHECKED_IN"
        assert tray_now["rework_count"] == 1
        # 06:30 + 30 decon + 90 (60 cycle + 30 cooldown, the fleet minimum).
        assert_same_instant(tray_now["projected_sterile_ready_at"],
                            "2026-08-03T08:30:00Z",
                            "tray.projected_sterile_ready_at")
        assert_same_instant(tray_now["required_sterile_ready_by"],
                            "2026-08-03T08:00:00Z",
                            "tray.required_sterile_ready_by")
        after = validate_success(
            api.get_request(world["request"]["id"], coordinator()))
        assert after["readiness"] == "NOT_READY", \
            "the 08:30 projection lands after the 08:00 requirement"

    def test_fail_qa_flip_opens_sterilization_delay_escalation(self, api):
        """PRD: "Whenever a recompute moves an `APPROVED` request into
        `AT_RISK` or `NOT_READY` while the case's `scheduled_start_at` is no
        more than twenty-four hours (1,440 minutes) from the current time, the
        system auto-creates an escalation in `OPEN`, typed by the underlying
        cause: a tray in `EXPECTED` or `MISSING` yields `MISSING_TRAY`, a tray
        in `QUARANTINED` yields `DOCUMENTATION`, and anything else — a late
        sterilization projection — yields `STERILIZATION_DELAY`."

        Design: Difficulty/transitive_cascade/fail_qa_cascade_tray_to_readiness_to_escalation
        """
        world, _tray, turn = self._cascade_world()
        get_success_data(api.fail_qa(turn["id"], fail_qa_payload("BI failure"),
                                     TECH))
        # The flip happened 150 minutes before the 09:00 case: inside window.
        escalations = list_escalations_of_request(world["request"]["id"])
        assert len(escalations) == 1, \
            "exactly one escalation is auto-created by the readiness flip"
        assert escalations[0]["type"] == "STERILIZATION_DELAY"
        assert escalations[0]["status"] == "OPEN"
        assert escalations[0]["request_id"] == world["request"]["id"]


class TestSterilizerCapacity:
    """Difficulty instance: aggregate slot capacity on a sterilizer unit."""

    def _three_turn_world(self):
        world = _checked_in_world(
            priority_class="STANDARD", case_start=FAR_CASE_START,
            case_end=FAR_CASE_END,
            tray_specs=[dict(tray_code=f"TK-{i}", declared_instrument_count=10,
                             replacement_value_cents=5000)
                        for i in (1, 2, 3)])
        turns = [open_turn(t["id"]) for t in world["trays"]]
        set_clock("2026-08-02T08:35:00Z")
        return world, turns

    def test_sterilizer_slot_admits_up_to_capacity(self, api):
        """PRD: "The unit must have a free slot: the count of turns currently
        `STERILIZING` on that unit must be below its `slot_capacity`, else
        `ERR_STERILIZER_CAPACITY_EXCEEDED` (409)."

        Design: Difficulty/resource_temporal_overlap/sterilizer_slot_capacity_count
        """
        world, turns = self._three_turn_world()
        unit = world["sterilizer"]["id"]
        first = validate_success(
            api.start_cycle(turns[0]["id"], start_cycle_payload(unit), TECH))
        assert first["status"] == "STERILIZING"
        # One active cycle on a two-slot unit: the second is admitted.
        second = validate_success(
            api.start_cycle(turns[1]["id"], start_cycle_payload(unit), TECH))
        assert second["status"] == "STERILIZING"

    def test_sterilizer_slot_rejects_beyond_capacity(self, api):
        """PRD: "The unit must have a free slot: the count of turns currently
        `STERILIZING` on that unit must be below its `slot_capacity`, else
        `ERR_STERILIZER_CAPACITY_EXCEEDED` (409)."

        Design: Difficulty/resource_temporal_overlap/sterilizer_slot_capacity_count
        """
        world, turns = self._three_turn_world()
        unit = world["sterilizer"]["id"]
        get_success_data(api.start_cycle(turns[0]["id"],
                                         start_cycle_payload(unit), TECH))
        get_success_data(api.start_cycle(turns[1]["id"],
                                         start_cycle_payload(unit), TECH))
        # Two active cycles on a two-slot unit: the third is refused.
        resp = api.start_cycle(turns[2]["id"], start_cycle_payload(unit), TECH)
        validate_error(resp, ApiErrorId.ERR_STERILIZER_CAPACITY_EXCEEDED)
        assert validate_success(
            api.get_turn(turns[2]["id"], TECH))["status"] == "DECONTAMINATING"
        for turn in turns[:2]:
            assert validate_success(
                api.get_turn(turn["id"], TECH))["status"] == "STERILIZING"


class TestReadinessProjectionBoundary:
    def test_readiness_projection_boundary_inclusive(self, api):
        """PRD: "Comparisons that decide whether a sterilization projection is
        on time are inclusive: a projection landing exactly at its deadline
        counts as on time."
        PRD: "Failing that, it is `AT_RISK` when every non-`CANCELLED` tray
        sits in `DELIVERY_PENDING`, `CHECKED_IN`, or `PROCESSING`, and every
        tray in `CHECKED_IN` or `PROCESSING` carries a
        `projected_sterile_ready_at` that is not null and falls at or before
        its `required_sterile_ready_by`."
        PRD: "Whenever a recompute moves an `APPROVED` request into `AT_RISK`
        or `NOT_READY` while the case's `scheduled_start_at` is no more than
        twenty-four hours (1,440 minutes) from the current time, the system
        auto-creates an escalation in `OPEN`, typed by the underlying cause"

        Design: Corner/calculations/readiness_projection_boundary_inclusive
        """
        # Two approved URGENT requests on the 2026-08-03 09:00 case; both
        # trays CHECKED_IN; turns opened 06:00 on case day. Turn A starts its
        # cycle at 06:30 (projection lands exactly at the 08:00 requirement);
        # turn B starts one minute later (08:01: late).
        world = setup_approved_request(
            tray_specs=[dict(tray_code="T-A", declared_instrument_count=5,
                             replacement_value_cents=1000)])
        rq_b = create_request(world["case"]["id"], world["vendor"]["id"],
                              "URGENT")
        tray_b = add_tray(rq_b["id"], tray_code="T-B",
                          declared_instrument_count=5,
                          replacement_value_cents=1000)
        submit_request(rq_b["id"])
        approve_request(rq_b["id"])
        world_b = {**world, "request": rq_b, "trays": [tray_b]}

        deliver_and_verify(world, at="2026-08-02T08:00:00Z")
        deliver_and_verify(world_b, at="2026-08-02T08:00:00Z")

        set_clock("2026-08-03T06:00:00Z")
        turn_a = open_turn(world["trays"][0]["id"])
        turn_b = open_turn(tray_b["id"])

        set_clock("2026-08-03T06:30:00Z")
        get_success_data(api.start_cycle(
            turn_a["id"], start_cycle_payload(world["sterilizer"]["id"]), TECH))
        tray_a_now = validate_success(
            api.get_tray(world["trays"][0]["id"], coordinator()))
        assert_same_instant(tray_a_now["projected_sterile_ready_at"],
                            "2026-08-03T08:00:00Z",
                            "tray A projected_sterile_ready_at")
        assert_same_instant(tray_a_now["required_sterile_ready_by"],
                            "2026-08-03T08:00:00Z",
                            "tray A required_sterile_ready_by")
        rq_a_now = validate_success(
            api.get_request(world["request"]["id"], coordinator()))
        assert rq_a_now["readiness"] == "AT_RISK", \
            "a projection equal to the deadline is on time"
        assert list_escalations_of_request(world["request"]["id"]) == [], \
            "no flip, no escalation"

        set_clock("2026-08-03T06:31:00Z")
        get_success_data(api.start_cycle(
            turn_b["id"], start_cycle_payload(world["sterilizer"]["id"]), TECH))
        rq_b_now = validate_success(api.get_request(rq_b["id"], coordinator()))
        assert rq_b_now["readiness"] == "NOT_READY", \
            "a projection one minute past the deadline is late"
        escalations_b = list_escalations_of_request(rq_b["id"])
        assert len(escalations_b) == 1
        assert escalations_b[0]["type"] == "STERILIZATION_DELAY"
        assert escalations_b[0]["status"] == "OPEN"
