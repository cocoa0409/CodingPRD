"""Construction phases, crew scheduling, capacity, and change orders
(PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_change_order,
    create_change_order_payload,
    create_phase,
    create_phase_payload,
    drive_to_approved,
    drive_to_construction,
    drive_to_council_review,
    get_district,
    make_engineer_headers,
    propose_change_order,
    set_clock,
    start_phase,
    api_client,
    validate_error,
    validate_success,
)

ENGINEER = TEST_USERS["engineer_headers"]
ENGINEER2 = TEST_USERS["engineer2_headers"]


class TestCrewBuffer:
    def test_four_day_gap_rejected(self, api):
        """PRD §3.6: "against every existing `PLANNED` or `IN_PROGRESS` phase
        of the same district sharing the same `crew_name`, the two ranges must
        be separated by at least five calendar days on one side or the other —
        the new phase starting at least five days after the existing phase
        ends, or the existing phase starting at least five days after the new
        phase ends — and a gap of exactly five days passes; anything tighter
        raises `ERR_PHASE_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/crew_buffer_five_day_gap_semantics
        """
        ctx = drive_to_approved("OV1", prefix="ov1", venue="City Hall Room A")
        create_phase(ctx["district"]["id"], name="PH1", crew_name="Alpha",
                     start_date="2026-09-10", end_date="2026-10-10")
        validate_error(
            api_client.create_construction_phase(
                create_phase_payload(district_id=ctx["district"]["id"], name="PH2",
                                     crew_name="Alpha", start_date="2026-10-14",
                                     end_date="2026-11-14", estimated_cost_cents=40000),
                ENGINEER,
            ),
            ApiErrorId.ERR_PHASE_SCHEDULE_CONFLICT,
        )

    def test_exactly_five_day_gap_accepted(self, api):
        """PRD §3.6: "the new phase starting at least five days after the
        existing phase ends, or the existing phase starting at least five days
        after the new phase ends — and a gap of exactly five days passes". PRD
        §3.6: "A planned phase opens in `PLANNED`."

        Design: Difficulty/resource_temporal_overlap/crew_buffer_five_day_gap_semantics
        """
        ctx = drive_to_approved("OV1", prefix="ov1", venue="City Hall Room A")
        create_phase(ctx["district"]["id"], name="PH1", crew_name="Alpha",
                     start_date="2026-09-10", end_date="2026-10-10")
        created = validate_success(
            api_client.create_construction_phase(
                create_phase_payload(district_id=ctx["district"]["id"], name="PH2",
                                     crew_name="Alpha", start_date="2026-10-15",
                                     end_date="2026-11-15", estimated_cost_cents=40000),
                ENGINEER,
            ),
            expected_status=201,
        )
        assert created["status"] == "PLANNED", "buffer comparison is >= (5 days passes)"


class TestSeasonAndCapacity:
    def test_season_window_violation(self, api):
        """PRD §3.6: "First, season containment: every calendar date of the new
        phase's inclusive range must fall inside the district's construction
        season for that date's calendar year, both season bounds inclusive; any
        date outside the season yields `ERR_SEASON_WINDOW_VIOLATION`."

        Design: Corner/errors/err_season_window_violation_triggered
        """
        ctx = drive_to_approved("ESW", prefix="esw", venue="ESW Room")
        validate_error(
            api_client.create_construction_phase(
                create_phase_payload(district_id=ctx["district"]["id"], name="WINTER",
                                     crew_name="Alpha", start_date="2026-12-01",
                                     end_date="2026-12-10", estimated_cost_cents=5000),
                ENGINEER,
            ),
            ApiErrorId.ERR_SEASON_WINDOW_VIOLATION,
        )

    def test_construction_capacity_exceeded(self, api):
        """PRD §3.6: "Third, concurrent capacity: on every calendar date the
        new phase covers, the number of existing `PLANNED` or `IN_PROGRESS`
        phases of the district already covering that date must be below two, so
        that at most two phases ever run concurrently counting the new one; a
        third overlapping phase is refused with
        `ERR_CONSTRUCTION_CAPACITY_EXCEEDED`."

        Design: Corner/errors/err_construction_capacity_exceeded_triggered
        """
        ctx = drive_to_approved("ECC", prefix="ecc", venue="ECC Room")
        district_id = ctx["district"]["id"]
        create_phase(district_id, name="PH1", crew_name="Alpha",
                     start_date="2026-09-10", end_date="2026-10-10",
                     estimated_cost_cents=50000)
        create_phase(district_id, name="PH2", crew_name="Beta",
                     start_date="2026-09-15", end_date="2026-10-05",
                     estimated_cost_cents=40000)
        validate_error(
            api_client.create_construction_phase(
                create_phase_payload(district_id=district_id, name="PH3",
                                     crew_name="Gamma", start_date="2026-09-20",
                                     end_date="2026-09-25", estimated_cost_cents=10000),
                ENGINEER,
            ),
            ApiErrorId.ERR_CONSTRUCTION_CAPACITY_EXCEEDED,
        )


class TestPhaseExecutionGates:
    def test_phase_start_date_boundary(self, api):
        """PRD §3.6: "Starting a phase requires it be `PLANNED`
        (`ERR_PHASE_NOT_PLANNED`), the district be `APPROVED` or
        `CONSTRUCTION`, and the current time to have reached midnight UTC at
        the start of the phase's `start_date` (`ERR_PHASE_START_NOT_REACHED`)".

        Design: Corner/state_machines/sm_phase_start_date_boundary
        """
        ctx = drive_to_approved("SPS", prefix="sps", venue="SPS Room")
        phase = create_phase(ctx["district"]["id"], name="PH2", crew_name="Beta",
                             start_date="2026-09-25", end_date="2026-10-05")

        set_clock("2026-09-24T23:59:59Z")  # one second before start_date
        validate_error(
            api_client.start_phase(phase["id"], ENGINEER),
            ApiErrorId.ERR_PHASE_START_NOT_REACHED,
        )

        set_clock("2026-09-25T00:00:00Z")  # exactly midnight UTC of start_date
        started = validate_success(api_client.start_phase(phase["id"], ENGINEER))
        assert started["status"] == "IN_PROGRESS"

    def test_phase_cancel_requires_planned(self, api):
        """PRD §3.6: "Cancelling is permitted only from `PLANNED` and lands the
        phase in `CANCELLED`." and "Starting a phase requires it be `PLANNED`
        (`ERR_PHASE_NOT_PLANNED`)".

        Design: Corner/errors/err_phase_cancel_requires_planned
        """
        ctx = drive_to_construction("ECP", prefix="ecp", venue="ECP Room")
        validate_error(
            api_client.cancel_phase(ctx["phase"]["id"], ENGINEER),
            ApiErrorId.ERR_PHASE_NOT_PLANNED,
        )

    def test_phase_complete_requires_in_progress(self, api):
        """PRD §3.6: "Completing requires the phase be `IN_PROGRESS`
        (`ERR_PHASE_NOT_IN_PROGRESS`) and stamps `completed_at`".

        Design: Corner/errors/err_phase_complete_requires_in_progress
        """
        ctx = drive_to_approved("ECQ", prefix="ecq", venue="ECQ Room")
        phase = create_phase(ctx["district"]["id"])
        validate_error(
            api_client.complete_phase(phase["id"], ENGINEER),
            ApiErrorId.ERR_PHASE_NOT_IN_PROGRESS,
        )

    def test_complete_construction_with_open_phase_rejected(self, api):
        """PRD §3.6: "The district must be in `CONSTRUCTION`
        (`ERR_DISTRICT_NOT_IN_CONSTRUCTION`), at least one phase must exist,
        and every phase must be terminal — `COMPLETED` or `CANCELLED` — with at
        least one `COMPLETED` among them; otherwise the request fails with
        `ERR_PHASES_NOT_ALL_COMPLETE`."

        Design: Corner/state_machines/sm_complete_construction_with_open_phase_rejected
        """
        ctx = drive_to_construction("SCC", prefix="scc", venue="SCC Room")
        validate_error(
            api_client.complete_construction(ctx["district"]["id"], ENGINEER),
            ApiErrorId.ERR_PHASES_NOT_ALL_COMPLETE,
        )


class TestPhaseStartDistrictGate:
    def test_phase_create_rejected_in_council_review(self, api):
        """PRD §3.6: "Planning is open only while the district is `APPROVED` or
        already under `CONSTRUCTION`
        (`ERR_DISTRICT_NOT_APPROVED_OR_UNDER_CONSTRUCTION`)".

        Design: Difficulty/cross_entity_state_dependency/phase_start_gated_by_district_approval
        """
        ctx = drive_to_council_review("XD2", prefix="xd2", venue="City Hall Room A")
        validate_error(
            api_client.create_construction_phase(
                create_phase_payload(district_id=ctx["district"]["id"]),
                ENGINEER,
            ),
            ApiErrorId.ERR_DISTRICT_NOT_APPROVED_OR_UNDER_CONSTRUCTION,
        )

    def test_first_phase_start_moves_district_to_construction(self, api):
        """PRD §3.6: "starting stamps `started_at`, moves the phase to
        `IN_PROGRESS`, and — when it is the first phase to start — moves the
        district from `APPROVED` to `CONSTRUCTION`, incrementing the district's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/phase_start_gated_by_district_approval
        """
        ctx = drive_to_approved("XD2", prefix="xd2", venue="City Hall Room A")
        phase = create_phase(ctx["district"]["id"])
        assert phase["status"] == "PLANNED"
        started = start_phase(phase["id"], at="2026-09-10T09:00:00Z")
        assert started["status"] == "IN_PROGRESS"
        assert get_district(ctx["district"]["id"])["status"] == "CONSTRUCTION"


class TestChangeOrders:
    def test_change_order_requires_construction(self, api):
        """PRD §3.6: "Scope changes arrive as **ChangeOrder** proposals, open
        only while the district is in `CONSTRUCTION`
        (`ERR_DISTRICT_NOT_IN_CONSTRUCTION`)".

        Design: Corner/errors/err_change_order_requires_construction
        """
        ctx = drive_to_approved("ECR", prefix="ecr", venue="ECR Room")
        phase = create_phase(ctx["district"]["id"])
        validate_error(
            api_client.create_change_order(
                create_change_order_payload(district_id=ctx["district"]["id"],
                                            phase_id=phase["id"], description="early",
                                            amount_cents=5000),
                ENGINEER,
            ),
            ApiErrorId.ERR_DISTRICT_NOT_IN_CONSTRUCTION,
        )

    def test_change_order_phase_not_in_district(self, api):
        """PRD §3.6: "an optional `phase_id` pinning the overrun to a phase —
        which, when present, must belong to the same district as the change
        order (`ERR_PHASE_NOT_IN_DISTRICT`)."

        Design: Corner/errors/err_phase_not_in_district_triggered
        """
        ctx_a = drive_to_construction("EPX-A", prefix="epxa", venue="EPX-A Room")
        # The EPX-A build advanced the logical clock to its phase start
        # (2026-09-10); rewind it so EPX-B's default hearing date satisfies
        # the ten-day statutory notice rule of PRD §3.3.
        set_clock("2026-08-01T00:00:00Z")
        ctx_b = drive_to_approved("EPX-B", prefix="epxb", venue="EPX-B Room")
        foreign_phase = create_phase(ctx_b["district"]["id"], name="PHB",
                                     crew_name="Beta")
        validate_error(
            api_client.create_change_order(
                create_change_order_payload(district_id=ctx_a["district"]["id"],
                                            phase_id=foreign_phase["id"],
                                            description="cross", amount_cents=5000),
                ENGINEER,
            ),
            ApiErrorId.ERR_PHASE_NOT_IN_DISTRICT,
        )

    def test_change_order_self_approve_segregation(self, api):
        """PRD §3.6: "Approval is deliberately a different pair of hands: the
        deciding engineer's `X-User-ID` must differ from `proposed_by_user_id`,
        and a self-approval is refused with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        Design: Corner/validations/v_change_order_self_approve_segregation
        """
        ctx = drive_to_construction("VSOD", prefix="vsod", venue="VSOD Room")
        order = propose_change_order(ctx["district"]["id"], amount_cents=5000,
                                     phase_id=ctx["phase"]["id"], engineer_id="eng-1")
        validate_error(
            api_client.approve_change_order(order["id"], make_engineer_headers("eng-1")),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        approved = approve_change_order(order["id"], engineer_id="eng-2")
        assert approved["status"] == "APPROVED"

    def test_change_order_double_decision_rejected(self, api):
        """PRD §3.6: "The order must still be `PROPOSED`
        (`ERR_CHANGE_ORDER_NOT_PROPOSED`) and the district still in
        `CONSTRUCTION`." PRD §3.6: "Rejection, under the same state gates,
        records `decided_by_user_id` and moves the order to `REJECTED`,
        touching no totals."

        Design: Corner/state_machines/sm_change_order_double_decision_rejected
        """
        ctx = drive_to_construction("SCO", prefix="sco", venue="SCO Room")
        order = propose_change_order(ctx["district"]["id"], amount_cents=5000,
                                     phase_id=ctx["phase"]["id"], engineer_id="eng-1")
        approve_change_order(order["id"], engineer_id="eng-2")
        validate_error(
            api_client.reject_change_order(order["id"], ENGINEER2),
            ApiErrorId.ERR_CHANGE_ORDER_NOT_PROPOSED,
        )


class TestOverrunThreshold:
    def _construction_with_cap(self):
        # Locked contract 10,000,000 -> cap = round(10,000,000 * 0.10) = 1,000,000.
        ctx = drive_to_construction(
            "B3", prefix="b3", methodology="PER_PARCEL",
            contract_price_cents=10000000, contingency_cents=0,
            venue="City Hall Room A",
        )
        return ctx

    def test_overrun_exactly_at_cap_is_not_overrun(self, api):
        """PRD §3.6: "The overrun rule is strict: the flag is true exactly when
        the cumulative approved change total is strictly greater than one tenth
        of the locked estimate's `contract_price_cents`, the cap itself rounded
        half-up to whole cents — landing exactly on the cap is not an overrun."

        Design: Difficulty/boundary_precision_check/overrun_flag_at_exactly_ten_percent_cap
        """
        ctx = self._construction_with_cap()
        order = propose_change_order(ctx["district"]["id"], amount_cents=1000000,
                                     phase_id=ctx["phase"]["id"], engineer_id="eng-1")
        approve_change_order(order["id"], engineer_id="eng-2")
        district = get_district(ctx["district"]["id"])
        assert district["approved_change_total_cents"] == 1000000
        assert district["overrun_flag"] is False, "exactly at cap is not overrun"

    def test_overrun_one_cent_above_cap_flips_flag(self, api):
        """PRD §3.6: "The overrun rule is strict: the flag is true exactly when
        the cumulative approved change total is strictly greater than one tenth
        of the locked estimate's `contract_price_cents`, the cap itself rounded
        half-up to whole cents — landing exactly on the cap is not an overrun."
        PRD §3.6: "Approving records the decider in `decided_by_user_id`, adds
        the order's `amount_cents` into the district's
        `approved_change_total_cents`, recomputes the district's
        `overrun_flag`".

        Design: Difficulty/boundary_precision_check/overrun_flag_at_exactly_ten_percent_cap
        """
        ctx = self._construction_with_cap()
        order1 = propose_change_order(ctx["district"]["id"], amount_cents=1000000,
                                      phase_id=ctx["phase"]["id"], engineer_id="eng-1")
        approve_change_order(order1["id"], engineer_id="eng-2")
        order2 = propose_change_order(ctx["district"]["id"], amount_cents=1,
                                      phase_id=ctx["phase"]["id"], engineer_id="eng-1")
        approve_change_order(order2["id"], engineer_id="eng-2")
        district = get_district(ctx["district"]["id"])
        assert district["approved_change_total_cents"] == 1000001
        assert district["overrun_flag"] is True, "strictly greater than the cap"
