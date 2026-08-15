"""Check-in, return assessments, the cleaning/repair loop, and fitting authorizations."""
from test_helpers import (
    ApiErrorId,
    acquire_unit,
    advance_ticket,
    assert_assessment,
    check_in_line,
    cleaning_ticket_for_unit,
    create_active_renter,
    create_catalog_item,
    create_confirmed_production,
    create_confirmed_reservation,
    create_fitting_payload,
    create_pull_list_for,
    dispatch_pull_list,
    get_assessment_for_line,
    get_line,
    get_pull_list,
    get_unit,
    list_lines,
    make_house_admin_headers,
    make_renter_contact_headers,
    make_wardrobe_staff_headers,
    pick_all_lines,
    publish_rate_card,
    set_logical_clock,
    setup_dispatched_scenario,
    submit_and_get_lines,
    validate_error,
    validate_success,
)

DISPATCH_CLOCK = "2026-08-31T00:00:00Z"
ON_DUE_CLOCK = "2026-09-10T00:00:00Z"


def _dispatched_single(api, **kwargs):
    """One-unit dispatched scenario; returns the context with lines refreshed."""
    return setup_dispatched_scenario(api, quantity=1, num_units=1, **kwargs)


class TestItemUnitRentalCycle:
    def test_unit_out_then_cleaning_on_checkin(self, api, wardrobe_staff_headers):
        """PRD §3.6: "With `damage_severity` of `NONE` the line becomes `RETURNED`, the unit
        moves `OUT` → `CLEANING`, and a cleaning ticket is created with `requires_repair`
        false."
        PRD §3.5: dispatch "moves every assigned unit `AVAILABLE` → `OUT`".

        Design: Difficulty/non_linear_state_machine/item_unit_rental_cycle
        """
        ctx = _dispatched_single(api)
        unit_id = ctx["units"][0]["id"]
        assert get_unit(api, unit_id)["status"] == "OUT"

        set_logical_clock(api, ON_DUE_CLOCK)
        line = check_in_line(api, ctx["lines"][0]["id"])
        assert line["status"] == "RETURNED"
        assert get_unit(api, unit_id)["status"] == "CLEANING"

    def test_ticket_ready_returns_unit_available(self, api):
        """PRD §3.6: "`WardrobeStaff` advance a ticket one stage at a time: `QUEUED` →
        `IN_CLEANING` → `INSPECTION`" and "Reaching `READY` stamps `ready_at` with the
        current logical timestamp and returns the unit from `CLEANING` or `REPAIR` to
        `AVAILABLE`."

        Design: Difficulty/non_linear_state_machine/item_unit_rental_cycle
        """
        ctx = _dispatched_single(api)
        unit_id = ctx["units"][0]["id"]
        set_logical_clock(api, ON_DUE_CLOCK)
        check_in_line(api, ctx["lines"][0]["id"])

        ticket = cleaning_ticket_for_unit(api, unit_id)
        assert ticket["status"] == "QUEUED"
        assert advance_ticket(api, ticket["id"])["status"] == "IN_CLEANING"
        ticket = advance_ticket(api, ticket["id"])
        assert ticket["status"] == "INSPECTION"
        ticket = advance_ticket(api, ticket["id"])
        assert ticket["status"] == "READY"
        assert ticket["ready_at"] is not None
        # The rotation loop closes: the same physical unit is assignable again.
        assert get_unit(api, unit_id)["status"] == "AVAILABLE"


class TestCheckinAutocloseCascade:
    def test_checkin_returns_line_and_creates_assessment(self, api):
        """PRD §3.6: "Check-in creates exactly one return assessment per line — a strict
        one-to-one, retrievable as an array of zero or one assessments for the line."

        Design: Difficulty/transitive_cascade/checkin_pull_list_autoclose_cascade
        """
        ctx = _dispatched_single(api)
        set_logical_clock(api, ON_DUE_CLOCK)
        line = check_in_line(api, ctx["lines"][0]["id"])
        assert line["status"] == "RETURNED"  # hop 1 of the bubble-up chain
        assessment = get_assessment_for_line(api, line["id"])
        assert_assessment(assessment)
        assert assessment["pull_list_line_id"] == line["id"]
        assert assessment["late_days"] == 0

    def test_last_line_checkin_closes_pull_list(self, api):
        """PRD §3.5: "A dispatched list closes automatically: when every line has reached a
        terminal state (`RETURNED`, `DAMAGED`, or `LOST`), every approved fitting on its
        lines has been restored, and every `DAMAGED` or `LOST` line has a damage claim in
        `POSTED` or `WAIVED` status, the list moves to `CLOSED`".

        Design: Difficulty/transitive_cascade/checkin_pull_list_autoclose_cascade
        """
        ctx = _dispatched_single(api)
        set_logical_clock(api, ON_DUE_CLOCK)
        check_in_line(api, ctx["lines"][0]["id"])
        # Hop 2: no close endpoint exists; the list flips on its own.
        assert get_pull_list(api, ctx["pull_list"]["id"])["status"] == "CLOSED"


class TestCleaningBacklogRushThreshold:
    def _setup_eleven(self, api):
        """11 units all dispatched on one qty-11 reservation; lines OUT at 2026-09-10."""
        publish_rate_card(api)
        item = create_catalog_item(api, name="Chorus dress", period="FIFTIES",
                                   replacement_value_cents=30000)
        units = [acquire_unit(api, item["id"], barcode=f"BC-14{i:02d}",
                              acquisition_cost_cents=20000) for i in range(1, 12)]
        renter = create_active_renter(api, name="Renter R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        create_confirmed_reservation(
            api, production["id"], renter, item["id"], quantity=11,
            window_start_date="2026-09-01", window_end_date="2026-09-10",
        )
        pull_list = create_pull_list_for(api, production["id"], renter)
        pull_list, lines = submit_and_get_lines(api, pull_list["id"])
        assert len(lines) == 11
        pick_all_lines(api, lines)
        dispatch_pull_list(api, pull_list["id"], at=DISPATCH_CLOCK)
        set_logical_clock(api, ON_DUE_CLOCK)
        return {"item": item, "units": units, "renter": renter, "lines": lines}

    def test_first_through_tenth_tickets_pay_base_fee(self, api):
        """PRD §3.6: "The base fee depends on the item's `category`: 1500 cents for
        `COSTUME`" and "when that depth is at least ten, the base fee is multiplied by a rush
        factor of 1.5 and rounded half up — a depth of exactly ten triggers the rush
        multiplier, nine does not."

        Design: Difficulty/boundary_precision_check/cleaning_backlog_rush_threshold
        """
        ctx = self._setup_eleven(api)
        for line in ctx["lines"][:10]:
            check_in_line(api, line["id"])

        first = cleaning_ticket_for_unit(api, ctx["lines"][0]["item_unit_id"])
        assert first["queue_depth_at_creation"] == 0
        assert first["cleaning_fee_cents"] == 1500

        tenth = cleaning_ticket_for_unit(api, ctx["lines"][9]["item_unit_id"])
        assert tenth["queue_depth_at_creation"] == 9, "nine tickets ahead of the tenth"
        assert tenth["cleaning_fee_cents"] == 1500, "9 >= 10 is false — no rush multiplier"

    def test_eleventh_ticket_triggers_rush_multiplier(self, api):
        """PRD §3.6: "The `queue_depth_at_creation` counts the tickets in `QUEUED` or
        `IN_CLEANING` status at the moment of creation; when that depth is at least ten, the
        base fee is multiplied by a rush factor of 1.5 and rounded half up — a depth of
        exactly ten triggers the rush multiplier, nine does not."

        Design: Difficulty/boundary_precision_check/cleaning_backlog_rush_threshold
        """
        ctx = self._setup_eleven(api)
        for line in ctx["lines"]:
            check_in_line(api, line["id"])

        eleventh = cleaning_ticket_for_unit(api, ctx["lines"][10]["item_unit_id"])
        assert eleventh["queue_depth_at_creation"] == 10
        # round_half_up(1500 * 1.5) = 2250.
        assert eleventh["cleaning_fee_cents"] == 2250


class TestLateFees:
    def test_late_fee_three_days_computed(self, api):
        """PRD §3.6: "The `late_days` is the number of whole days between the `due_back_date`
        and the return date, never below zero" and "The late fee, computed at check-in and
        stored as the line's `late_fee_cents`, is the `late_days` times the item's
        `base_daily_rate_cents` times the same condition multiplier used for line rental
        charges (1.20 for `A`, 1.00 for `B`, 0.85 for `C`, taken from the unit's current
        grade) times the pinned rate card's `late_fee_daily_pct`, rounded half up to whole
        cents."

        Design: Corner/calculations/late_fee_three_days_computed
        """
        ctx = _dispatched_single(api)
        set_logical_clock(api, "2026-09-13T00:00:00Z")  # 3 days past due_back 2026-09-10
        line = check_in_line(api, ctx["lines"][0]["id"])
        assert line["status"] == "RETURNED"
        # 3 * 1000 * 1.00 (grade B) * 0.10 = 300.
        assert line["late_fee_cents"] == 300
        assessment = get_assessment_for_line(api, line["id"])
        assert assessment["late_days"] == 3

    def test_late_fee_zero_on_due_date(self, api):
        """PRD §3.6: "The `late_days` is the number of whole days between the `due_back_date`
        and the return date, never below zero — returning exactly on the due date yields zero
        late days."

        Design: Corner/calculations/late_fee_zero_on_due_date
        """
        ctx = _dispatched_single(api)
        set_logical_clock(api, ON_DUE_CLOCK)  # exactly due_back_date 2026-09-10
        line = check_in_line(api, ctx["lines"][0]["id"])
        assert line["late_fee_cents"] == 0
        assessment = get_assessment_for_line(api, line["id"])
        assert assessment["late_days"] == 0


class TestImmediateConsistency:
    def test_immediate_visibility_after_checkin(self, api, wardrobe_staff_headers):
        """PRD §2.8: "Many operations mutate more than one resource in a single request, and
        all such side effects are visible in the same response — the consistency model is
        immediate, with no deferred or asynchronous reconciliation."

        Design: Corner/consistency_model/immediate_visibility_after_checkin
        """
        ctx = _dispatched_single(api)
        set_logical_clock(api, ON_DUE_CLOCK)
        resp = api.check_in_line(
            ctx["lines"][0]["id"],
            {"condition_grade_after": "B", "damage_severity": "NONE",
             "restoration_complete": True},
            wardrobe_staff_headers,
        )
        line = validate_success(resp)
        assert line["status"] == "RETURNED"

        # The very next reads — no delay, no sweep — already show every side effect.
        assert get_unit(api, ctx["units"][0]["id"])["status"] == "CLEANING"
        assert get_pull_list(api, ctx["pull_list"]["id"])["status"] == "CLOSED"
        assessment = get_assessment_for_line(api, line["id"])
        assert assessment["condition_grade_after"] == "B"


class TestRepairLoop:
    def test_cleaning_ticket_repair_loop_returns_unit(self, api):
        """PRD §3.6: "With `REPAIRABLE` the line becomes `DAMAGED`, the unit moves `OUT` →
        `REPAIR`, and the ticket is created with `requires_repair` true." and "a ticket with
        `requires_repair` true and `repair_done` false advances to `REPAIR`, a ticket with
        `requires_repair` false or `repair_done` true advances to `READY`, and a ticket in
        `REPAIR` advances back to `INSPECTION` with `repair_done` set true, so a repair
        always returns through inspection before release."

        Design: Corner/state_machines/cleaning_ticket_repair_loop_returns_unit
        """
        ctx = _dispatched_single(api)
        unit_id = ctx["units"][0]["id"]
        set_logical_clock(api, ON_DUE_CLOCK)
        line = check_in_line(
            api, ctx["lines"][0]["id"],
            condition_grade_after="C", damage_severity="REPAIRABLE",
        )
        assert line["status"] == "DAMAGED"
        assert get_unit(api, unit_id)["status"] == "REPAIR"

        ticket = cleaning_ticket_for_unit(api, unit_id)
        assert ticket["requires_repair"] is True
        assert ticket["status"] == "QUEUED"

        assert advance_ticket(api, ticket["id"])["status"] == "IN_CLEANING"
        ticket = advance_ticket(api, ticket["id"])
        assert ticket["status"] == "INSPECTION"
        ticket = advance_ticket(api, ticket["id"])
        assert ticket["status"] == "REPAIR"
        ticket = advance_ticket(api, ticket["id"])
        assert ticket["status"] == "INSPECTION"
        assert ticket["repair_done"] is True
        ticket = advance_ticket(api, ticket["id"])
        assert ticket["status"] == "READY"
        assert get_unit(api, unit_id)["status"] == "AVAILABLE"


class TestFittings:
    def _submitted_lines_per_item(self, api):
        """Three items (PROHIBITED / REVERSIBLE_ONLY / TAILORING_ALLOWED), one CONFIRMED
        reservation each (same window), one submitted pull list -> three PENDING lines."""
        publish_rate_card(api)
        i_prohibited = create_catalog_item(
            api, name="IP", period="MEDIEVAL", category="WEAPONRY", size_class="NONE",
            alteration_policy="PROHIBITED", replacement_value_cents=150000,
            base_daily_rate_cents=2000, base_weekly_rate_cents=9000,
        )
        acquire_unit(api, i_prohibited["id"], barcode="BC-AP1",
                     acquisition_cost_cents=90000)
        i_reversible = create_catalog_item(
            api, name="IR", period="REGENCY", alteration_policy="REVERSIBLE_ONLY",
            replacement_value_cents=80000, base_daily_rate_cents=900,
            base_weekly_rate_cents=4500,
        )
        acquire_unit(api, i_reversible["id"], barcode="BC-AP2")
        i_tailoring = create_catalog_item(
            api, name="IT", size_class="L", alteration_policy="TAILORING_ALLOWED",
        )
        acquire_unit(api, i_tailoring["id"], barcode="BC-AP3")
        renter = create_active_renter(api, name="R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")

        reservation_ids = {}
        for key, item in (("prohibited", i_prohibited), ("reversible", i_reversible),
                          ("tailoring", i_tailoring)):
            reservation = create_confirmed_reservation(
                api, production["id"], renter, item["id"], quantity=1,
                window_start_date="2026-09-01", window_end_date="2026-09-05",
            )
            reservation_ids[key] = reservation["id"]
        pull_list = create_pull_list_for(api, production["id"], renter)
        submit_and_get_lines(api, pull_list["id"])
        lines = {
            key: list_lines(api, reservation_id=reservation_id)[0]
            for key, reservation_id in reservation_ids.items()
        }
        return {"renter": renter, "lines": lines, "pull_list": pull_list}

    def test_error_alteration_prohibited_policy_matrix(self, api):
        """PRD §3.6: "The item's `alteration_policy` gates the request: `PROHIBITED` rejects
        every alteration type, and `REVERSIBLE_ONLY` allows only `HEM`, `TAKE_IN`, and
        `LET_OUT` — a forbidden request fails with `ERR_ALTERATION_PROHIBITED`;
        `TAILORING_ALLOWED` permits all six types."

        Design: Corner/errors/error_alteration_prohibited_policy_matrix
        """
        ctx = self._submitted_lines_per_item(api)
        headers = make_renter_contact_headers(ctx["renter"]["id"])
        lines = ctx["lines"]

        resp = api.create_fitting(
            create_fitting_payload(pull_list_line_id=lines["prohibited"]["id"],
                                   alteration_type="HEM"),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_ALTERATION_PROHIBITED, 422)

        resp = api.create_fitting(
            create_fitting_payload(pull_list_line_id=lines["reversible"]["id"],
                                   alteration_type="DYE"),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_ALTERATION_PROHIBITED, 422)

        ok_reversible = validate_success(
            api.create_fitting(
                create_fitting_payload(pull_list_line_id=lines["reversible"]["id"],
                                       alteration_type="HEM"),
                headers,
            ),
            201,
        )
        assert ok_reversible["status"] == "REQUESTED"

        ok_tailoring = validate_success(
            api.create_fitting(
                create_fitting_payload(pull_list_line_id=lines["tailoring"]["id"],
                                       alteration_type="DYE"),
                headers,
            ),
            201,
        )
        assert ok_tailoring["status"] == "REQUESTED"

    def test_checkin_restoration_gate_blocks_then_releases(self, api):
        """PRD §3.6: "if the line carries a fitting authorization in `APPROVED` status,
        `restoration_complete` must be true or the check-in is rejected with
        `ERR_RESTORATION_INCOMPLETE`." and "When `restoration_complete` is true, every
        fitting authorization on the line in `APPROVED` status moves automatically to
        `RESTORED`."

        Design: Corner/state_machines/checkin_restoration_gate_blocks_then_releases
        """
        ctx = _dispatched_single(api)
        line_id = ctx["lines"][0]["id"]
        renter_headers = make_renter_contact_headers(ctx["renter"]["id"])

        # Request the fitting on the OUT line (OUT is an allowed from-state for requests)
        # and approve it, so the line carries an APPROVED authorization at check-in.
        fitting = validate_success(
            api.create_fitting(
                create_fitting_payload(pull_list_line_id=line_id,
                                       alteration_type="TAKE_IN"),
                renter_headers,
            ),
            201,
        )
        validate_success(
            api.decide_fitting(fitting["id"], "APPROVED", make_house_admin_headers())
        )

        set_logical_clock(api, ON_DUE_CLOCK)
        resp = api.check_in_line(
            line_id,
            {"condition_grade_after": "B", "damage_severity": "NONE",
             "restoration_complete": False},
            make_wardrobe_staff_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RESTORATION_INCOMPLETE, 409)
        assert get_line(api, line_id)["status"] == "OUT"

        ok = validate_success(
            api.check_in_line(
                line_id,
                {"condition_grade_after": "B", "damage_severity": "NONE",
                 "restoration_complete": True},
                make_wardrobe_staff_headers(),
            )
        )
        assert ok["status"] == "RETURNED"
        restored = validate_success(api.get_fitting(fitting["id"], make_house_admin_headers()))
        assert restored["status"] == "RESTORED"

    def test_fitting_terminal_lockdown_rejected(self, api, house_admin_headers):
        """PRD §3.6: "The authorization states are `REQUESTED`, `APPROVED`, `REJECTED`, and
        `RESTORED`, with `REJECTED` and `RESTORED` terminal" and "A `HouseAdmin` then decides
        it with a `decision`: approval requires the line still be in `PENDING`, `PICKED`, or
        `OUT` (`ERR_INVALID_STATE` otherwise)".

        Design: Corner/state_machines/fitting_terminal_lockdown_rejected
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="I1")
        acquire_unit(api, item["id"], barcode="BC-F1")
        renter = create_active_renter(api, name="R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        create_confirmed_reservation(api, production["id"], renter, item["id"], quantity=1)
        pull_list = create_pull_list_for(api, production["id"], renter)
        _, lines = submit_and_get_lines(api, pull_list["id"])

        fitting = validate_success(
            api.create_fitting(
                create_fitting_payload(pull_list_line_id=lines[0]["id"],
                                       alteration_type="HEM"),
                make_renter_contact_headers(renter["id"]),
            ),
            201,
        )
        rejected = validate_success(
            api.decide_fitting(fitting["id"], "REJECTED", house_admin_headers)
        )
        assert rejected["status"] == "REJECTED"

        resp = api.decide_fitting(fitting["id"], "APPROVED", house_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert validate_success(api.get_fitting(fitting["id"], house_admin_headers))["status"] == "REJECTED"
