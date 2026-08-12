"""The cycle calendar, its boundaries, the pinned invoice order and the surcharge."""

from test_helpers import (
    ADMIN,
    BILLING,
    ApiErrorId,
    assert_cycle,
    assert_same_instant,
    apply_credit,
    close_cycle,
    create_cycle,
    create_open_cycle,
    drive_cycle_to_return_due,
    find_charge,
    get_cycle,
    get_invoice,
    get_member,
    grant_credit,
    raise_charge,
    set_clock,
    setup_plan_and_member,
    validate_error,
    validate_success,
)


class TestCycleWindows:
    def test_the_three_boundaries_are_derived_from_start_at(self, api):
        """PRD §3.2: "`swap_by_at` is `start_at` plus `SWAP_BY_OFFSET_DAYS`,
        twenty days. `return_due_at` is `start_at` plus
        `RETURN_DUE_OFFSET_DAYS`, thirty days. `grace_ends_at` is
        `return_due_at` plus `GRACE_PERIOD_DAYS`, a further five days — so grace
        ends thirty-five days after the cycle starts."
        PRD §3.2: "the new row is born `SCHEDULED`, and its `cycle_index` is
        assigned as the member's previous highest index plus one, starting at 1
        and never exceeding `CYCLE_MAX_INDEX`, which is 240."

        Design: Corner/entities/corner_cycle_window_fields_are_computed_from_start_at
        """
        _, member = setup_plan_and_member()
        cycle = validate_success(
            api.create_cycle({"member_id": member["id"],
                              "start_at": "2026-05-01T00:00:00Z"}, ADMIN),
            201,
        )
        assert_cycle(cycle)
        assert_same_instant(cycle["swap_by_at"], "2026-05-21T00:00:00.000Z", "Cycle.swap_by_at")
        assert_same_instant(cycle["return_due_at"], "2026-05-31T00:00:00.000Z",
                            "Cycle.return_due_at")
        assert_same_instant(cycle["grace_ends_at"], "2026-06-05T00:00:00.000Z",
                            "Cycle.grace_ends_at")
        assert cycle["cycle_index"] == 1
        assert cycle["status"] == "SCHEDULED"
        assert cycle["swaps_used"] == 0

    def test_opening_a_cycle_before_its_start_instant_is_refused(self, api):
        """PRD §3.2: "It requires that the cycle is `SCHEDULED`, that the member
        is `ACTIVE`, and that the logical clock has reached `start_at`; opening
        early is refused with `ERR_CYCLE_NOT_STARTED`."

        Design: Corner/state_machines/corner_sm_cycle_open_before_start_at_is_rejected
        """
        _, member = setup_plan_and_member()
        cycle = create_cycle(member["id"], start_at="2026-06-01T00:00:00Z")

        resp = api.open_cycle(cycle["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_STARTED.value, 409)
        assert get_cycle(cycle["id"])["status"] == "SCHEDULED"
        assert get_member(member["id"])["outstanding_balance_cents"] == 0

    def test_closing_the_swap_window_at_exactly_swap_by_at_is_still_too_early(self, api):
        """PRD §3.2: "Closing the swap window is a `PlatformAdmin` action moving
        the cycle `OPEN → SWAP_CLOSED`. It is permitted only when the logical
        clock is **strictly after** `swap_by_at`; attempting it at or before
        that instant is refused with `ERR_SWAP_WINDOW_STILL_OPEN`."

        Design: Corner/state_machines/corner_sm_close_swap_window_before_swap_by_at_is_rejected
        """
        _, member = setup_plan_and_member()
        cycle = create_open_cycle(member["id"])
        set_clock("2026-05-21T00:00:00Z")

        resp = api.close_swap_window(cycle["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SWAP_WINDOW_STILL_OPEN.value, 409)
        assert get_cycle(cycle["id"])["status"] == "OPEN"

    def test_closing_the_swap_window_of_a_scheduled_cycle_is_an_invalid_state(self, api):
        """PRD §2.6 rung 22: "`Cycle.status` is a declared from-state for the
        requested cycle transition. Otherwise `ERR_CYCLE_INVALID_STATE` (409).
        Applies to cycle transition endpoints."
        PRD §3.2: "attempting any cycle transition from a state that does not
        declare it is refused with `ERR_CYCLE_INVALID_STATE`."

        Design: Corner/errors/corner_err_close_swap_window_on_a_scheduled_cycle_is_rejected
        """
        _, member = setup_plan_and_member()
        cycle = create_cycle(member["id"])
        set_clock("2026-05-22T00:00:00Z")

        resp = api.close_swap_window(cycle["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CYCLE_INVALID_STATE.value, 409)
        assert get_cycle(cycle["id"])["status"] == "SCHEDULED"


class TestGraceBoundary:
    def test_assessing_late_at_exactly_grace_ends_at_reaches_return_due_with_no_fee(self, api):
        """PRD §3.2: "From `SWAP_CLOSED` it moves the cycle to `RETURN_DUE` when
        the clock has passed `return_due_at` but has not yet passed
        `grace_ends_at`; on that edge **no** late fee accrues, precisely because
        the grace boundary has not been crossed."
        PRD §2.6 rung 36: "Lateness accrues only when the logical clock is
        **strictly after** the cycle's `grace_ends_at`; the boundary is
        **exclusive**, and this is deliberately the opposite inclusivity from
        rung 33."

        Design: Difficulty/boundary_precision_check/assess_late_exactly_at_grace_ends_at_accrues_zero_and_then_rejects
        """
        _, member = setup_plan_and_member(plan={"late_fee_mode": "PER_DAY"})
        cycle = create_open_cycle(member["id"])
        set_clock("2026-05-22T00:00:00Z")
        validate_success(api.close_swap_window(cycle["id"], ADMIN))
        set_clock("2026-06-05T00:00:00Z")

        first = validate_success(api.assess_late(cycle["id"], BILLING))
        assert_same_instant(get_cycle(cycle["id"])["grace_ends_at"],
                            "2026-06-05T00:00:00.000Z", "Cycle.grace_ends_at")
        assert first["status"] == "RETURN_DUE"
        assert get_cycle(cycle["id"])["late_fee_cents"] == 0

    def test_a_second_assessment_at_the_grace_instant_is_refused(self, api):
        """PRD §2.6 rung 36: "Assessment attempted at or before `grace_ends_at`
        on the transition into `GRACE` is refused with `ERR_GRACE_NOT_EXPIRED`
        (409). Applies to `POST /kidswear/cycles/{cycle_id}/assess-late`."
        PRD §3.2: "Attempting to move into `GRACE` at or before `grace_ends_at`
        is refused with `ERR_GRACE_NOT_EXPIRED`."

        Design: Difficulty/boundary_precision_check/assess_late_exactly_at_grace_ends_at_accrues_zero_and_then_rejects
        """
        _, member = setup_plan_and_member(plan={"late_fee_mode": "PER_DAY"})
        cycle = create_open_cycle(member["id"])
        set_clock("2026-05-22T00:00:00Z")
        validate_success(api.close_swap_window(cycle["id"], ADMIN))
        set_clock("2026-06-05T00:00:00Z")
        validate_success(api.assess_late(cycle["id"], BILLING))

        resp = api.assess_late(cycle["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_GRACE_NOT_EXPIRED.value, 409)
        assert get_cycle(cycle["id"])["status"] == "RETURN_DUE"


class TestVolumeDiscountOrdering:
    def test_the_tier_is_keyed_on_the_undiscounted_gross(self, api):
        """PRD §3.2: "an undiscounted gross is formed from the plan's
        `monthly_fee_cents` plus, when the member has `protection_enrolled` set,
        the flat `PROTECTION_FEE_CENTS_PER_CYCLE` of 900 cents per cycle; if
        that gross is at least 20000 cents a tier fraction of 0.10 applies,
        otherwise if it is at least 12000 cents a tier fraction of 0.05 applies,
        otherwise the tier fraction is zero; the effective discount fraction is
        the plan's `discount_pct` plus that tier fraction, capped at 0.50."
        PRD §3.2: "The tier is chosen from the **undiscounted** gross and is
        never re-evaluated against the discounted total — the definition looks
        circular because the gross that keys the tier contains the very
        protection fee the discount will later reduce, and the evaluation order
        resolves that circularity once and for all."
        PRD §3.2: "With the fraction resolved, `plan_charge_cents` is the plan's
        `monthly_fee_cents` reduced by the cycle's `proration_credit_cents` and
        then multiplied by one minus the effective discount fraction, rounded
        half up to the cent."

        Design: Difficulty/combinatorial_formula/volume_discount_tier_selected_from_undiscounted_gross
        """
        _, member = setup_plan_and_member(
            plan={"tier": "PLUS", "slots_per_box": 1, "swaps_per_cycle": 2,
                  "monthly_fee_cents": 11500, "protection_available": True,
                  "discount_pct": 0.05},
            member={"child_size_code": "7", "protection_enrolled": True,
                    "auto_apply_credit": False},
        )
        cycle = create_cycle(member["id"])
        opened = validate_success(api.open_cycle(cycle["id"], ADMIN))

        assert opened["status"] == "OPEN"
        after = get_cycle(cycle["id"])
        assert after["plan_charge_cents"] == 10350
        assert after["proration_credit_cents"] == 0

    def test_the_discount_is_recorded_across_the_plan_charge_and_the_protection_fee(self, api):
        """PRD §3.2: "When the member is enrolled in protection,
        `protection_fee_cents` is 900 cents multiplied by one minus the same
        fraction, rounded half up separately. The cycle's `discount_cents`
        records the money the discount removed."
        PRD §2.7: "The same effective discount fraction is applied to the flat
        protection fee of 900 cents, rounded half up separately, giving
        `protection_fee_cents`. The `discount_cents` field records the money the
        discount removed across the plan charge and the protection fee
        together."

        Design: Difficulty/combinatorial_formula/volume_discount_tier_selected_from_undiscounted_gross
        """
        _, member = setup_plan_and_member(
            plan={"tier": "PLUS", "slots_per_box": 1, "swaps_per_cycle": 2,
                  "monthly_fee_cents": 11500, "protection_available": True,
                  "discount_pct": 0.05},
            member={"child_size_code": "7", "protection_enrolled": True,
                    "auto_apply_credit": False},
        )
        cycle = create_open_cycle(member["id"])

        assert cycle["protection_fee_cents"] == 810
        assert cycle["discount_cents"] == 1240
        assert cycle["plan_charge_cents"] == 10350


class TestInvoiceOrdering:
    def test_the_surcharge_is_computed_on_the_post_credit_base(self, api):
        """PRD §2.7: "A surcharge of 8.75 percent is computed on the
        **post-credit** taxable base and rounded half up to the cent, giving
        `surcharge_cents`. The final `invoice_total_cents` is the post-credit
        base, floored at zero so it can never be negative, plus the surcharge."
        PRD §2.7: "The alternative reading — computing the surcharge on the
        pre-credit base and *then* subtracting credit — is explicitly
        **forbidden**."
        PRD §3.2: "The taxable base for the surcharge is the sum of
        `plan_charge_cents`, `protection_fee_cents`, `late_fee_cents` and
        `damage_fee_cents`, reduced by `credit_applied_cents` and floored at
        zero; `surcharge_cents` is 8.75 percent of that base, rounded half up."

        Design: Corner/calculations/corner_calc_surcharge_is_computed_on_the_post_credit_base
        """
        _, member = setup_plan_and_member(
            plan={"monthly_fee_cents": 6000, "discount_pct": 0},
            member={"protection_enrolled": False, "auto_apply_credit": False},
        )
        cycle = create_open_cycle(member["id"])
        charge = find_charge(member["id"], "PLAN_CHARGE")
        grant_credit(member["id"], 1000)
        apply_credit(member["id"], charge["id"])

        drive_cycle_to_return_due(cycle["id"])
        closed = validate_success(api.close_cycle(cycle["id"], BILLING))
        assert closed["status"] == "CLOSED"

        after = get_cycle(cycle["id"])
        assert after["plan_charge_cents"] == 6000
        assert after["protection_fee_cents"] == 0
        assert after["credit_applied_cents"] == 1000
        assert after["late_fee_cents"] == 0
        assert after["surcharge_cents"] == 438
        assert after["invoice_total_cents"] == 5438
        assert get_member(member["id"])["completed_cycles"] == 1

    def test_the_invoice_read_exposes_each_ordered_step_separately(self, api):
        """PRD §3.2: "A computed invoice read exposes every ordered step
        separately — `plan_charge_cents`, `proration_credit_cents`,
        `discount_cents`, `protection_fee_cents`, `late_fee_cents`,
        `damage_fee_cents`, `credit_applied_cents`, `surcharge_cents` and
        `invoice_total_cents` — so that the effect of each step is observable
        rather than inferred."
        PRD §3.2: "`swaps_used`, `paused_days`, `late_fee_cents`,
        `damage_fee_cents`, `credit_applied_cents`, `surcharge_cents` and
        `protection_waiver_used_cents` all begin at 0."

        Design: Corner/endpoints/corner_ep_invoice_read_exposes_each_ordered_step
        """
        _, member = setup_plan_and_member(
            plan={"monthly_fee_cents": 5000, "discount_pct": 0},
            member={"protection_enrolled": False, "auto_apply_credit": False},
        )
        cycle = create_open_cycle(member["id"])

        invoice = get_invoice(cycle["id"])
        assert invoice["plan_charge_cents"] == 5000
        assert invoice["proration_credit_cents"] == 0
        assert invoice["discount_cents"] == 0
        assert invoice["protection_fee_cents"] == 0
        assert invoice["late_fee_cents"] == 0
        assert invoice["damage_fee_cents"] == 0
        assert invoice["credit_applied_cents"] == 0

    def test_a_delinquent_household_cannot_take_the_ordinary_close_path(self, api):
        """PRD §2.6 rung 63: "A cycle may reach `CLOSED` only when the owning
        member is not `DELINQUENT`; a delinquent member's held cycle closes to
        `DELINQUENT_CLOSED` instead. An attempt to take the ordinary close path
        while the member is `DELINQUENT` is refused with
        `ERR_CYCLE_CLOSE_BLOCKED_BY_DELINQUENCY` (409)."
        PRD §3.1: "An `ACTIVE` member whose outstanding balance reaches or
        exceeds `DELINQUENCY_THRESHOLD_CENTS`, which is 15000 cents, becomes
        `DELINQUENT`."

        Design: Corner/validations/corner_val_cycle_close_while_delinquent_is_rejected
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        cycle = create_open_cycle(member["id"])
        drive_cycle_to_return_due(cycle["id"])
        raise_charge(member["id"], "LOST_LIABILITY", 20000)

        resp = api.close_cycle(cycle["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_CYCLE_CLOSE_BLOCKED_BY_DELINQUENCY.value, 409)

        after_member = get_member(member["id"])
        assert after_member["status"] == "DELINQUENT"
        assert after_member["outstanding_balance_cents"] == 25000
        assert after_member["completed_cycles"] == 0
        assert get_cycle(cycle["id"])["status"] == "RETURN_DUE"
