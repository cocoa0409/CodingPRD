"""Line scheduling, die buffer, activation gates, changeover purges (PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    plant_base, create_die, qualify_die, create_line, create_lot, pass_lot,
    qc_passed_lot, create_formulation, create_order, confirm_order, confirmed_order,
    create_assignment, activated_assignment, start_run, complete_run,
    create_purge_event_payload, running_scene, released_batch,
    get_line, get_assignment, get_order, get_die,
    WINDOW_10_12, WINDOW_12_14, WINDOW_14_16, WINDOW_16_18, WINDOW_11_13, WINDOW_1230_14,
)

PE = TEST_USERS["process_engineer_headers"]
LO = TEST_USERS["line_operator_headers"]
PM = TEST_USERS["plant_manager_headers"]


class TestLineWindowOverlap:
    def test_touching_windows_accepted_half_open(self, api):
        """PRD §3.5: "First the line's diary: the new window must not overlap any
        other assignment on the same line in `SCHEDULED` or `ACTIVE` status,
        where overlap is judged on half-open windows — the new window starts
        before the other's `planned_end` and ends after the other's
        `planned_start` — and windows that merely touch, one's `planned_end`
        equal to the other's `planned_start`, do not overlap and are allowed; a
        true overlap is rejected with `ERR_LINE_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/line_half_open_adjacency
        """
        base = plant_base(customer_over={"credit_limit_cents": 20000000})
        dies = [qualify_die(create_die(base["prof"]["id"], die_code=c)["id"])
                for c in ("D-A", "D-B", "D-C")]
        line = create_line()
        orders = [
            confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"],
                            d["id"], ordered_length_m=n)
            for d, n in zip(dies, (5000, 3000, 2000))
        ]
        create_assignment(orders[0]["id"], dies[0]["id"], line["id"], WINDOW_10_12)
        # Touching window 12:00-14:00: planned_end == planned_start, allowed.
        adjacent = validate_success(api.create_line_assignment(
            {"work_order_id": orders[1]["id"], "die_id": dies[1]["id"], "line_id": line["id"],
             "planned_start": WINDOW_12_14[0], "planned_end": WINDOW_12_14[1]}, PE), 201)
        assert adjacent["status"] == "SCHEDULED"

    def test_overlapping_window_rejected(self, api):
        """PRD §3.5: "First the line's diary: the new window must not overlap any
        other assignment on the same line in `SCHEDULED` or `ACTIVE` status,
        where overlap is judged on half-open windows — the new window starts
        before the other's `planned_end` and ends after the other's
        `planned_start` — and windows that merely touch, one's `planned_end`
        equal to the other's `planned_start`, do not overlap and are allowed; a
        true overlap is rejected with `ERR_LINE_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/line_half_open_adjacency
        """
        base = plant_base(customer_over={"credit_limit_cents": 20000000})
        dies = [qualify_die(create_die(base["prof"]["id"], die_code=c)["id"])
                for c in ("D-A", "D-B", "D-C")]
        line = create_line()
        orders = [
            confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"],
                            d["id"], ordered_length_m=n)
            for d, n in zip(dies, (5000, 3000, 2000))
        ]
        create_assignment(orders[0]["id"], dies[0]["id"], line["id"], WINDOW_10_12)
        create_assignment(orders[1]["id"], dies[1]["id"], line["id"], WINDOW_12_14)
        # 11:00-13:00 overlaps both existing windows.
        resp = api.create_line_assignment(
            {"work_order_id": orders[2]["id"], "die_id": dies[2]["id"], "line_id": line["id"],
             "planned_start": WINDOW_11_13[0], "planned_end": WINDOW_11_13[1]}, PE)
        validate_error(resp, ApiErrorId.ERR_LINE_SCHEDULE_CONFLICT)


class TestDieBufferGap:
    def test_gap_below_buffer_rejected_even_without_overlap(self, api):
        """PRD §3.5: "Second the die's cooldown: for every other assignment on
        the same die in `SCHEDULED` or `ACTIVE` status, the gap between the
        windows is measured as the larger of zero and the new window's
        `planned_start` minus the other's `planned_end` when the new window
        follows it, or the larger of zero and the other's `planned_start` minus
        the new window's `planned_end` when it precedes it; whenever that gap is
        strictly less than the die's `buffer_hours` — including the zero-overlap
        case of touching windows, whose gap is zero — the creation is rejected
        with `ERR_DIE_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/die_buffer_gap
        """
        base = plant_base(customer_over={"credit_limit_cents": 20000000})
        die = qualify_die(create_die(base["prof"]["id"])["id"])  # buffer_hours = 4
        line = create_line()
        wo1 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        wo2 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"],
                              ordered_length_m=3000)
        create_assignment(wo1["id"], die["id"], line["id"], WINDOW_10_12)
        # Gap 14:00 - 12:00 = 2 h < buffer 4 h despite zero overlap.
        resp = api.create_line_assignment(
            {"work_order_id": wo2["id"], "die_id": die["id"], "line_id": line["id"],
             "planned_start": WINDOW_14_16[0], "planned_end": WINDOW_14_16[1]}, PE)
        validate_error(resp, ApiErrorId.ERR_DIE_BUFFER_CONFLICT)

    def test_gap_exactly_equal_to_buffer_accepted(self, api):
        """PRD §3.5: "Second the die's cooldown: for every other assignment on
        the same die in `SCHEDULED` or `ACTIVE` status, the gap between the
        windows is measured as the larger of zero and the new window's
        `planned_start` minus the other's `planned_end` when the new window
        follows it, or the larger of zero and the other's `planned_start` minus
        the new window's `planned_end` when it precedes it; whenever that gap is
        strictly less than the die's `buffer_hours` — including the zero-overlap
        case of touching windows, whose gap is zero — the creation is rejected
        with `ERR_DIE_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/die_buffer_gap
        """
        base = plant_base(customer_over={"credit_limit_cents": 20000000})
        die = qualify_die(create_die(base["prof"]["id"])["id"])
        line = create_line()
        wo1 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        wo3 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"],
                              ordered_length_m=2000)
        create_assignment(wo1["id"], die["id"], line["id"], WINDOW_10_12)
        # Gap 16:00 - 12:00 = 4 h == buffer_hours; only strictly-less rejects.
        ok = api.create_line_assignment(
            {"work_order_id": wo3["id"], "die_id": die["id"], "line_id": line["id"],
             "planned_start": WINDOW_16_18[0], "planned_end": WINDOW_16_18[1]}, PE)
        assert validate_success(ok, 201)["status"] == "SCHEDULED"


class TestActivationGates:
    def test_activate_rejected_while_line_in_setup(self, api):
        """PRD §3.5: "First, the line must be `IDLE`; activating against a line
        in `SETUP`, `RUNNING`, or `DOWN` is rejected with `ERR_LINE_NOT_IDLE`."

        Design: Difficulty/cross_entity_state_dependency/activate_requires_line_idle
        """
        base = plant_base(customer_over={"credit_limit_cents": 20000000})
        die_a = qualify_die(create_die(base["prof"]["id"], die_code="D-A")["id"])
        die_b = qualify_die(create_die(base["prof"]["id"], die_code="D-B")["id"])
        line = create_line()
        wo1 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die_a["id"])
        wo2 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die_b["id"],
                              ordered_length_m=3000)
        asg1 = activated_assignment(wo1["id"], die_a["id"], line["id"], WINDOW_10_12)
        asg2 = create_assignment(wo2["id"], die_b["id"], line["id"], WINDOW_14_16)

        resp = api.activate_assignment(asg2["id"], PE)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_IDLE)
        assert get_assignment(asg2["id"])["status"] == "SCHEDULED"
        assert get_line(line["id"])["status"] == "SETUP"

    def test_activate_rejected_while_line_running(self, api):
        """PRD §3.5: "First, the line must be `IDLE`; activating against a line
        in `SETUP`, `RUNNING`, or `DOWN` is rejected with `ERR_LINE_NOT_IDLE`."

        Design: Difficulty/cross_entity_state_dependency/activate_requires_line_idle
        """
        base = plant_base(customer_over={"credit_limit_cents": 20000000})
        die_a = qualify_die(create_die(base["prof"]["id"], die_code="D-A")["id"])
        die_b = qualify_die(create_die(base["prof"]["id"], die_code="D-B")["id"])
        line = create_line()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
        batch = released_batch(base["form"]["id"], lot_v["id"], lot_c["id"])
        wo1 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die_a["id"])
        wo2 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die_b["id"],
                              ordered_length_m=3000)
        asg1 = activated_assignment(wo1["id"], die_a["id"], line["id"], WINDOW_10_12)
        asg2 = create_assignment(wo2["id"], die_b["id"], line["id"], WINDOW_14_16)
        start_run(asg1["id"], batch["id"])  # line now RUNNING

        resp = api.activate_assignment(asg2["id"], PE)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_IDLE)
        assert get_assignment(asg2["id"])["status"] == "SCHEDULED"
        assert get_line(line["id"])["status"] == "RUNNING"

    def test_activate_with_draft_die_rejected(self, api):
        """PRD §3.5: "Second, the die must be `QUALIFIED` or `IN_SERVICE`; any
        other die status is `ERR_DIE_NOT_RUNNABLE`."

        Design: Corner/validations/activate_draft_die_rejected
        """
        base = plant_base()
        die = create_die(base["prof"]["id"])  # stays DRAFT
        line = create_line()
        wo = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        asg = create_assignment(wo["id"], die["id"], line["id"], WINDOW_10_12)

        resp = api.activate_assignment(asg["id"], PE)
        validate_error(resp, ApiErrorId.ERR_DIE_NOT_RUNNABLE)
        assert get_line(line["id"])["status"] == "IDLE"
        assert get_assignment(asg["id"])["status"] == "SCHEDULED"

    def test_activate_with_incompatible_screw_rejected(self, api):
        """PRD §3.5: "Third, the die must fit the line's screw: the line's
        `screw_diameter_mm` must be at least the die's `min_screw_mm` and at most
        its `max_screw_mm`, failing which the rejection is
        `ERR_LINE_INCOMPATIBLE_DIE`."

        Design: Corner/validations/activate_incompatible_screw_rejected
        """
        base = plant_base()
        die = qualify_die(create_die(base["prof"]["id"], die_code="D-W",
                                     min_screw_mm=65, max_screw_mm=90)["id"])
        line = create_line(screw_diameter_mm=60)  # 60 < min_screw_mm 65
        wo = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        asg = create_assignment(wo["id"], die["id"], line["id"], WINDOW_10_12)

        resp = api.activate_assignment(asg["id"], PE)
        validate_error(resp, ApiErrorId.ERR_LINE_INCOMPATIBLE_DIE)
        assert get_line(line["id"])["status"] == "IDLE"
        assert get_assignment(asg["id"])["status"] == "SCHEDULED"


class TestAssignmentUnwind:
    def test_cancel_active_assignment_returns_line_to_idle(self, api):
        """PRD §3.5: "Cancellation moves the assignment to `CANCELLED`, returns
        the line from `SETUP` to `IDLE` when a cancelled active assignment was
        what left it there, runs the order revert check — the order drops from
        `SCHEDULED` back to `CONFIRMED` when it has no remaining `SCHEDULED` or
        `ACTIVE` assignments and no `COMPLETED` runs — and increments the
        assignment's `version`."

        Design: Corner/state_machines/line_setup_to_idle_on_cancel
        """
        base = plant_base(customer_over={"credit_limit_cents": 20000000})
        die = qualify_die(create_die(base["prof"]["id"])["id"])
        line = create_line()
        wo1 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        wo2 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"],
                              ordered_length_m=3000)
        asg1 = activated_assignment(wo1["id"], die["id"], line["id"], WINDOW_10_12)
        asg2 = create_assignment(wo2["id"], die["id"], line["id"], WINDOW_16_18)

        validate_success(api.cancel_assignment(asg1["id"], PE), 200)
        assert get_line(line["id"])["status"] == "IDLE", "SETUP must be released on cancel"
        assert get_order(wo1["id"])["status"] == "CONFIRMED", "Order must revert from SCHEDULED"

        activated = validate_success(api.activate_assignment(asg2["id"], PE), 200)
        assert activated["status"] == "ACTIVE"

    def test_cancel_already_cancelled_assignment_rejected(self, api):
        """PRD §3.5: "a `SCHEDULED` assignment may be cancelled freely, and an
        `ACTIVE` one may be cancelled once no run under it is `RUNNING` or
        `HOLD`, again under penalty of `ERR_RUN_IN_PROGRESS`."
        PRD §2.8: "Sixth comes from-state validity: the target resource must be
        in a state from which the requested transition is defined, or the request
        surfaces `ERR_INVALID_STATE`."

        Design: Corner/state_machines/assignment_cancel_from_cancelled_rejected
        """
        base = plant_base()
        die = create_die(base["prof"]["id"])
        line = create_line()
        wo = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        asg = create_assignment(wo["id"], die["id"], line["id"], WINDOW_10_12)
        validate_success(api.cancel_assignment(asg["id"], PE), 200)
        assert get_order(wo["id"])["status"] == "CONFIRMED"

        resp = api.cancel_assignment(asg["id"], PE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_assignment(asg["id"])["status"] == "CANCELLED"
        assert get_order(wo["id"])["status"] == "CONFIRMED"


class TestPurgeEventsAndGate:
    def test_transition_classes_and_scrap_estimates(self, api):
        """PRD §3.5: "The event's `transition_class` is derived: if the two resin
        types differ, the class is `RESIN_CHANGE`; otherwise, if the two colour
        families are equal, `SAME_RESIN_SAME_COLOR`; otherwise, if the
        destination colour ranks strictly darker than the source on the plant's
        fixed ladder — `NATURAL` lightest, then `WHITE`, `YELLOW`, `RED`, `BLUE`,
        `GREEN`, `BROWN`, and `BLACK` darkest — the class is
        `SAME_RESIN_LIGHT_TO_DARK`; and every remaining same-resin case, where
        the destination ranks lighter than the source, is
        `SAME_RESIN_DARK_TO_LIGHT`."
        PRD §3.5: "Each class carries a base allowance — 2.0 kg for
        `SAME_RESIN_SAME_COLOR`, 4.0 kg for `SAME_RESIN_LIGHT_TO_DARK`, 8.0 kg
        for `SAME_RESIN_DARK_TO_LIGHT`, and 12.0 kg for `RESIN_CHANGE` — which is
        scaled by a screw factor read off the line's `screw_diameter_mm`: 1.0
        when the diameter is at most 45 mm, 1.6 when it is greater than 45 mm and
        at most 90 mm, and 2.2 when it exceeds 90 mm."

        Design: Difficulty/combinatorial_formula/purge_transition_tiers
        """
        line = create_line()  # screw 60 mm -> factor 1.6
        # RED (rank 3) -> BLACK (rank 7) on same resin: LIGHT_TO_DARK.
        pe_a = validate_success(api.create_purge_event(
            create_purge_event_payload(line["id"], "PVC", "PVC", "RED", "BLACK"), LO), 201)
        assert pe_a["transition_class"] == "SAME_RESIN_LIGHT_TO_DARK"
        assert pe_a["scrap_kg"] == pytest.approx(6.40, abs=0.001)  # 4.0 x 1.6 x 1.0

        # Resin family change dominates the class regardless of colour.
        pe_b = validate_success(api.create_purge_event(
            create_purge_event_payload(line["id"], "PVC", "ABS", "RED", "RED"), LO), 201)
        assert pe_b["transition_class"] == "RESIN_CHANGE"
        assert pe_b["scrap_kg"] == pytest.approx(19.20, abs=0.001)  # 12.0 x 1.6 x 1.0

    def test_grade_multiplier_and_screw_tiers(self, api):
        """PRD §3.5: "A grade multiplier then applies: 1.0 for `STANDARD`, 0.7
        for `HIGH_EFFICIENCY`."
        PRD §3.5: "Each class carries a base allowance — 2.0 kg for
        `SAME_RESIN_SAME_COLOR`, 4.0 kg for `SAME_RESIN_LIGHT_TO_DARK`, 8.0 kg
        for `SAME_RESIN_DARK_TO_LIGHT`, and 12.0 kg for `RESIN_CHANGE` — which is
        scaled by a screw factor read off the line's `screw_diameter_mm`: 1.0
        when the diameter is at most 45 mm, 1.6 when it is greater than 45 mm and
        at most 90 mm, and 2.2 when it exceeds 90 mm."

        Design: Difficulty/combinatorial_formula/purge_transition_tiers
        """
        line60 = create_line(line_code="L-60", screw_diameter_mm=60)
        high_eff = validate_success(api.create_purge_event(
            create_purge_event_payload(line60["id"], "PVC", "ABS", "RED", "RED",
                                       purge_grade="HIGH_EFFICIENCY"), LO), 201)
        assert high_eff["scrap_kg"] == pytest.approx(13.44, abs=0.001)  # 12.0 x 1.6 x 0.7

        dark_to_light = validate_success(api.create_purge_event(
            create_purge_event_payload(line60["id"], "PVC", "PVC", "BLACK", "RED"), LO), 201)
        assert dark_to_light["transition_class"] == "SAME_RESIN_DARK_TO_LIGHT"
        assert dark_to_light["scrap_kg"] == pytest.approx(12.80, abs=0.001)  # 8.0 x 1.6 x 1.0

        line45 = create_line(line_code="L-45", screw_diameter_mm=45)  # tier 1: factor 1.0
        same_color = validate_success(api.create_purge_event(
            create_purge_event_payload(line45["id"], "PVC", "PVC", "NATURAL", "NATURAL"), LO), 201)
        assert same_color["transition_class"] == "SAME_RESIN_SAME_COLOR"
        assert same_color["scrap_kg"] == pytest.approx(2.00, abs=0.001)  # 2.0 x 1.0 x 1.0

        line100 = create_line(line_code="L-100", screw_diameter_mm=100)  # tier 3: factor 2.2
        big = validate_success(api.create_purge_event(
            create_purge_event_payload(line100["id"], "PVC", "ABS", "RED", "RED"), LO), 201)
        assert big["transition_class"] == "RESIN_CHANGE"
        assert big["scrap_kg"] == pytest.approx(26.40, abs=0.001)  # 12.0 x 2.2 x 1.0

    def test_purge_gate_blocks_then_admits_activation(self, api):
        """PRD §3.5: "If such a reference exists and its work order's formulation
        differs from this order's formulation in `base_resin_type` or
        `color_family`, then a purge event must already exist on this line whose
        `from_resin_type` and `from_color_family` equal the prior formulation's
        resin and colour, whose `to_resin_type` and `to_color_family` equal this
        formulation's, and whose `created_at` is at or after the prior
        assignment's `updated_at`; without a matching event the activation is
        rejected with `ERR_PURGE_REQUIRED`."

        Design: Corner/validations/purge_gate_blocks_activate
        """
        base = plant_base(customer_over={"credit_limit_cents": 20000000})
        die_a = qualify_die(create_die(base["prof"]["id"], die_code="D-A")["id"])
        die_b = qualify_die(create_die(base["prof"]["id"], die_code="D-B")["id"])
        line = create_line()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
        form_blue = create_formulation(base["prof"]["id"], formula_code="F-BLUE25",
                                       color_family="BLUE")
        batch = released_batch(base["form"]["id"], lot_v["id"], lot_c["id"])
        wo1 = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die_a["id"])
        asg1 = activated_assignment(wo1["id"], die_a["id"], line["id"], WINDOW_10_12)
        run1 = start_run(asg1["id"], batch["id"])
        complete_run(run1["id"], 2000, 1.5, 0)
        validate_success(api.close_assignment(asg1["id"], PE), 200)

        wo2 = confirmed_order(base["cust"]["id"], base["prof"]["id"], form_blue["id"], die_b["id"],
                              ordered_length_m=3000)
        asg2 = create_assignment(wo2["id"], die_b["id"], line["id"], WINDOW_1230_14)

        blocked = api.activate_assignment(asg2["id"], PE)
        validate_error(blocked, ApiErrorId.ERR_PURGE_REQUIRED)
        assert get_assignment(asg2["id"])["status"] == "SCHEDULED"

        purge = validate_success(api.create_purge_event(
            create_purge_event_payload(line["id"], "PVC", "PVC", "RED", "BLUE"), LO), 201)
        assert purge["transition_class"] == "SAME_RESIN_LIGHT_TO_DARK"
        assert purge["scrap_kg"] == pytest.approx(6.40, abs=0.001)  # 4.0 x 1.6 x 1.0

        activated = validate_success(api.activate_assignment(asg2["id"], PE), 200)
        assert activated["status"] == "ACTIVE"
        assert get_line(line["id"])["status"] == "SETUP"
