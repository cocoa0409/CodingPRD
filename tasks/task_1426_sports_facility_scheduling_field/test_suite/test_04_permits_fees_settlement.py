"""Permit lifecycle: provisional vs settlement fee variants, the confirm
gates, check-in/settle/no-show preconditions, terminal lockdown, and the
reschedule lineage pointer."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_permit,
    cancel_permit_as_owner,
    create_reschedule_payload,
    get_invoice,
    get_permit,
    issue_invoice,
    make_org_coordinator_headers,
    pay_invoice,
    reschedule_as_owner,
    set_clock,
    setup_awarded_permit,
    setup_confirmed_permit,
    setup_rained_out_permit,
    validate_error,
    validate_success,
)

SUPERVISOR = TEST_USERS["field_supervisor_headers"]
ADMIN = TEST_USERS["athletics_admin_headers"]


class TestPerLineRoundingOrder:
    """NONRESIDENT 45 minutes at 3250/hr: raw field 2437.5 -> line 2438;
    surcharge computed on the ROUNDED field line: round(2438 x 15%) = 366."""

    def test_field_and_surcharge_lines_rounded_independently(self, api):
        """PRD §3.6: "The field line `quoted_field_fee_cents` is that raw amount
        rounded half-up to whole cents."
        PRD §3.6: "The surcharge line applies only to `NONRESIDENT` and `COMMERCIAL`
        organizations: it is the already-rounded field line multiplied by
        `nonresident_surcharge_pct` or `commercial_surcharge_pct` respectively,
        divided by 100, and rounded half-up; `RESIDENT` organizations pay no
        surcharge."

        Design: Difficulty/combinatorial_formula/fee_per_line_rounding_then_sum_order
        """
        ctx = setup_awarded_permit(
            app_overrides={"start_minute": 840, "end_minute": 885,  # 14:00-14:45
                           "event_type": "LEAGUE_PRACTICE", "headcount": 20},
            org_overrides={"name": "Metro Adults", "classification": "NONRESIDENT",
                           "org_type": "ADULT_LEAGUE", "prior_seasons_active": 0})
        permit = ctx["permit"]
        assert permit["quoted_field_fee_cents"] == 2438, \
            "round_half_up(45 x 3250 / 60 = 2437.5)"
        assert permit["quoted_surcharge_cents"] == 366, \
            "round_half_up(2438 x 15 / 100 = 365.7) on the ROUNDED field line"

    def test_total_is_sum_of_rounded_lines(self, api):
        """PRD §2.6: "Where a quote or invoice comprises several lines, each line is
        rounded independently first and the rounded lines are then summed — this
        evaluation order is pinned, and the alternative of summing unrounded raw
        values and rounding once at the end is a known-incorrect variant that yields
        different totals."
        PRD §3.6: "The `deposit_required_cents` is the smaller of the quoted total and
        the larger of two floors: `min_deposit_cents`, and the quoted total multiplied
        by `deposit_pct` divided by 100 and rounded half-up."

        Total is 2438 + 366 = 2804 (the sum-then-round variant would yield 2803);
        deposit clamps to the total: min(2804, max(5000, 701)).

        Design: Difficulty/combinatorial_formula/fee_per_line_rounding_then_sum_order
        """
        ctx = setup_awarded_permit(
            app_overrides={"start_minute": 840, "end_minute": 885,
                           "event_type": "LEAGUE_PRACTICE", "headcount": 20},
            org_overrides={"name": "Metro Adults", "classification": "NONRESIDENT",
                           "org_type": "ADULT_LEAGUE", "prior_seasons_active": 0})
        permit = ctx["permit"]
        assert permit["quoted_total_cents"] == 2804, \
            "per-line-then-sum is pinned; the sum-then-round variant (2803) is incorrect"
        assert permit["deposit_required_cents"] == 2804, \
            "min(2804, max(5000, round(2804 x 25 / 100) = 701)) — clamped to the total"


class TestProvisionalVsSettlementFees:
    """Same pinned schedule, same 120-minute lights slot: the provisional variant
    bills the requested slot (9600); the settlement variant recomputes from actual
    attendance (90 min) and actual lights (60 min) to 5800."""

    def test_provisional_quote_bills_full_requested_slot(self, api):
        """PRD §3.6: "The provisional quote at award — and again at every reschedule —
        follows a pinned recipe. The slot's duration in minutes is `end_minute` minus
        `start_minute`."
        PRD §3.6: "The lights line prices `lights_minutes_quoted` — which equals the
        slot's full duration when lights were approved and 0 otherwise — by dividing
        it into 15-minute blocks rounded up to a whole block and multiplying by the
        pinned `lights_block_cents`, yielding `quoted_lights_fee_cents`."
        PRD §3.6: "The `final_total_cents` stays null until settlement,
        `attendance_minutes` stays null until check-in, `rain_reschedule_count`
        starts at 0, and `original_permit_id` starts null."

        120 minutes at 2000/hr -> 4000; 120 lights minutes -> 8 blocks x 700 = 5600;
        RESIDENT pays no surcharge; total 9600; deposit min(9600, max(5000, 2400))
        = 5000.

        Design: Difficulty/dual_variant_calc/permit_fee_provisional_vs_settlement_final
        """
        ctx = setup_awarded_permit(app_overrides={"wants_lights": True})
        permit = ctx["permit"]
        assert_permit(permit)
        assert permit["lights_approved"] is True
        assert permit["lights_minutes_quoted"] == 120
        assert permit["quoted_field_fee_cents"] == 4000
        assert permit["quoted_lights_fee_cents"] == 5600
        assert permit["quoted_surcharge_cents"] == 0
        assert permit["quoted_total_cents"] == 9600
        assert permit["deposit_required_cents"] == 5000
        assert permit["final_total_cents"] is None

    def test_settlement_final_variant_diverges_downward(self, api):
        """PRD §3.6: "The final field fee is the smaller of the quoted field fee and
        the pinned hourly rate multiplied by `attendance_minutes`, divided by 60, and
        rounded half-up. The final lights fee is the smaller of the quoted lights fee
        and the actual usage priced per block — the optional `actual_lights_minutes`
        divided by 15, rounded up to whole blocks, at the pinned `lights_block_cents`;
        when lights were never approved, the quoted lights line is zero, so the final
        lights line is zero as well. The surcharge line carries over from the
        provisional quote unchanged, so the final total can diverge downward from the
        provisional one but never upward through this mechanism."
        PRD §3.6: "The permit's `final_total_cents` records the recomputed total; the
        invoice's lines are updated and its `total_cents` and `balance_due_cents`
        recomputed; the season ledger releases the slot's awarded hours and adds
        `attendance_minutes` divided by 60 — integer division, per permit — to
        `attended_hours`; and the facility's `weekly_prime_hours_used` is recomputed."

        Final field = min(4000, round(90 x 2000 / 60)) = 3000; final lights =
        min(5600, ceil(60/15) x 700) = 2800; final total 5800. The invoice recomputes
        to 5800 with 5000 already paid: balance 800, still PARTIALLY_PAID.

        Design: Difficulty/dual_variant_calc/permit_fee_provisional_vs_settlement_final
        """
        ctx = setup_confirmed_permit(app_overrides={"wants_lights": True})
        permit_id = ctx["permit"]["id"]
        invoice_id = ctx["invoice"]["id"]
        assert ctx["permit"]["quoted_total_cents"] == 9600

        set_clock("2026-08-10T19:00:00Z")  # inside [17:30, 20:00] check-in window
        validate_success(api.check_in_permit(permit_id, {"attended_minutes": 90},
                                             SUPERVISOR), 200)
        set_clock("2026-08-10T20:01:00Z")  # past the slot end
        settled = validate_success(api.settle_permit(
            permit_id, {"actual_lights_minutes": 60}, SUPERVISOR), 200)
        assert settled["status"] == "COMPLETED"
        assert settled["final_total_cents"] == 5800, \
            "final variant diverges downward from the provisional 9600"
        assert settled["quoted_total_cents"] == 9600, "the provisional quote is retained"

        invoice = get_invoice(invoice_id)
        assert invoice["total_cents"] == 5800
        assert invoice["balance_due_cents"] == 800, "5800 total minus 5000 paid"
        assert invoice["status"] == "PARTIALLY_PAID"


class TestConfirmGates:
    def test_confirm_blocked_while_invoice_draft(self, api):
        """PRD §3.6: "Three gates must pass: the organization's `standing` must not be
        `SUSPENDED`, else `ERR_ORG_SUSPENDED`; the permit's invoice must be `ISSUED`,
        `PARTIALLY_PAID`, or `PAID`, else `ERR_INVALID_INVOICE_STATE`; and cleared
        payments must cover the deposit — the invoice's `paid_cents` at least its
        `deposit_cents` — else `ERR_DEPOSIT_NOT_PAID`."

        Invoice still DRAFT: the invoice-state gate fails.

        Design: Difficulty/cross_entity_state_dependency/permit_confirm_requires_invoice_issued_with_deposit
        """
        ctx = setup_awarded_permit()  # 2h no lights: quote 4000, deposit 4000
        assert ctx["invoice"]["status"] == "DRAFT"
        res = api.confirm_permit(ctx["permit"]["id"],
                                 make_org_coordinator_headers(ctx["organization"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_INVOICE_STATE)
        assert get_permit(ctx["permit"]["id"])["status"] == "RESERVED"

    def test_confirm_blocked_until_deposit_paid_then_succeeds(self, api):
        """PRD §3.6: "Three gates must pass: the organization's `standing` must not be
        `SUSPENDED`, else `ERR_ORG_SUSPENDED`; the permit's invoice must be `ISSUED`,
        `PARTIALLY_PAID`, or `PAID`, else `ERR_INVALID_INVOICE_STATE`; and cleared
        payments must cover the deposit — the invoice's `paid_cents` at least its
        `deposit_cents` — else `ERR_DEPOSIT_NOT_PAID`. A successful confirmation
        simply advances the permit and increments its `version`."

        Design: Difficulty/cross_entity_state_dependency/permit_confirm_requires_invoice_issued_with_deposit
        """
        ctx = setup_awarded_permit()
        org_id = ctx["organization"]["id"]
        invoice_id = ctx["invoice"]["id"]
        issue_invoice(invoice_id)

        res = api.confirm_permit(ctx["permit"]["id"], make_org_coordinator_headers(org_id))
        validate_error(res, ApiErrorId.ERR_DEPOSIT_NOT_PAID)
        assert get_permit(ctx["permit"]["id"])["status"] == "RESERVED"

        pay_invoice(invoice_id, 4000)  # == deposit_cents
        confirmed = validate_success(api.confirm_permit(
            ctx["permit"]["id"], make_org_coordinator_headers(org_id)), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["version"] > ctx["permit"]["version"]


class TestGameDayPreconditions:
    def test_mark_no_show_before_slot_end_rejected(self, api):
        """PRD §3.6: "When a `CONFIRMED` slot ends with no check-in recorded, the
        field supervisor marks a no-show. Doing so before the slot end has passed
        fails with `ERR_NO_SHOW_NOT_YET`, and a permit already carrying
        `attendance_minutes` cannot be marked at all."

        Clock inside the slot (19:00 for an 18:00-20:00 permit): the temporal gate
        fires and no StrikeRecord is created.

        Design: Corner/state_machines/mark_no_show_before_slot_end_rejected
        """
        ctx = setup_confirmed_permit()
        set_clock("2026-08-10T19:00:00Z")
        res = api.mark_no_show(ctx["permit"]["id"], SUPERVISOR)
        validate_error(res, ApiErrorId.ERR_NO_SHOW_NOT_YET)
        assert get_permit(ctx["permit"]["id"])["status"] == "CONFIRMED"
        strikes = validate_success(api.list_strike_records(
            ADMIN, params={"organization_id": ctx["organization"]["id"]}), 200)
        assert strikes == [], "rejected no-show must not create a StrikeRecord"

    def test_settle_without_checkin_rejected(self, api):
        """PRD §3.6: "Settlement is the permit's happy ending: after the slot has
        ended, the supervisor settles a checked-in `CONFIRMED` permit into
        `COMPLETED`. Attempting settlement without a check-in fails with
        `ERR_CHECKIN_REQUIRED`, and the logical clock must be past the slot's end."

        Design: Corner/state_machines/settle_without_checkin_rejected
        """
        ctx = setup_confirmed_permit()
        set_clock("2026-08-10T20:01:00Z")  # past the slot end
        res = api.settle_permit(ctx["permit"]["id"], {}, SUPERVISOR)
        validate_error(res, ApiErrorId.ERR_CHECKIN_REQUIRED)
        assert get_permit(ctx["permit"]["id"])["status"] == "CONFIRMED"

    def test_cancel_completed_permit_rejected_terminal_lockdown(self, api):
        """PRD §3.6: "A permit's `status` begins at `RESERVED` and ends at one of four
        terminal states: `COMPLETED`, `CANCELLED`, `NO_SHOW`, or `REVOKED`."
        PRD §2.8: "7. **State legality.** The target entity must be in a valid
        from-state for the requested transition: `ERR_INVALID_PERMIT_STATE`,
        `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_WINDOW_STATE`,
        `ERR_INVALID_INVOICE_STATE`, `ERR_INVALID_CLOSURE_STATE`,
        `ERR_INVALID_SCHEDULE_STATE`, `ERR_INVALID_PAYMENT_STATE`, or
        `ERR_INVALID_STRIKE_STATE` (all 409)."

        Full attendance (120 min) and full actual lights (120 min) settle the final
        total equal to the provisional 9600; a later cancel is rejected and the
        settled invoice is untouched.

        Design: Corner/state_machines/cancel_completed_permit_rejected_terminal_lockdown
        """
        ctx = setup_confirmed_permit(app_overrides={"wants_lights": True})
        permit_id = ctx["permit"]["id"]
        invoice_id = ctx["invoice"]["id"]
        org_id = ctx["organization"]["id"]
        set_clock("2026-08-10T19:00:00Z")
        validate_success(api.check_in_permit(permit_id, {"attended_minutes": 120},
                                             SUPERVISOR), 200)
        set_clock("2026-08-10T20:01:00Z")
        settled = validate_success(api.settle_permit(
            permit_id, {"actual_lights_minutes": 120}, SUPERVISOR), 200)
        assert settled["status"] == "COMPLETED"
        assert settled["final_total_cents"] == 9600

        res = cancel_permit_as_owner(permit_id, org_id)
        validate_error(res, ApiErrorId.ERR_INVALID_PERMIT_STATE)
        assert get_permit(permit_id)["status"] == "COMPLETED"
        invoice = get_invoice(invoice_id)
        assert invoice["total_cents"] == 9600, \
            "terminal lockdown: the settled invoice's numbers are untouched"

    def test_reschedule_from_confirmed_rejected(self, api):
        """PRD §3.7: "Rescheduling returns a `RAINED_OUT` permit to `CONFIRMED` on a
        new slot."
        PRD §2.8: "7. **State legality.** The target entity must be in a valid
        from-state for the requested transition: `ERR_INVALID_PERMIT_STATE`,
        `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_WINDOW_STATE`,
        `ERR_INVALID_INVOICE_STATE`, `ERR_INVALID_CLOSURE_STATE`,
        `ERR_INVALID_SCHEDULE_STATE`, `ERR_INVALID_PAYMENT_STATE`, or
        `ERR_INVALID_STRIKE_STATE` (all 409)."

        A healthy CONFIRMED permit (no closure) cannot be moved; the request carries
        the CURRENT version, so the rejection is the state gate, not the OCC guard.

        Design: Corner/endpoints/reschedule_from_confirmed_rejected_conditional_action
        """
        ctx = setup_confirmed_permit()
        permit = get_permit(ctx["permit"]["id"])
        res = api.reschedule_permit(
            permit["id"],
            create_reschedule_payload("2026-08-12", 1080, 1200, permit["version"]),
            make_org_coordinator_headers(ctx["organization"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_PERMIT_STATE)
        assert get_permit(permit["id"])["status"] == "CONFIRMED"


class TestRescheduleLineage:
    def test_permit_self_referential_lineage_visible_after_reschedule(
            self, api, athletics_admin_headers):
        """PRD §3.6: "The `final_total_cents` stays null until settlement,
        `attendance_minutes` stays null until check-in, `rain_reschedule_count` starts
        at 0, and `original_permit_id` starts null."
        PRD §3.7: "A successful reschedule replaces `permit_date`, `start_minute`, and
        `end_minute` with the new slot; sets `original_permit_id` to the lineage root —
        on the first reschedule the null becomes the permit's own `id`, the root of
        its reschedule lineage, and any later reschedule keeps that same root; and
        increments both `rain_reschedule_count` and `version`."
        PRD §3.6: "Permits can be browsed through the listing with filters on
        `organization_id`, `facility_id`, `application_id`, `fee_schedule_id`,
        `original_permit_id`, `permit_date`, and `status`."

        Design: Corner/entities/permit_self_referential_lineage_visible_after_reschedule
        """
        ctx = setup_rained_out_permit()
        permit = ctx["permit"]
        assert permit["original_permit_id"] is None

        res = reschedule_as_owner(permit["id"], ctx["organization"]["id"],
                                  "2026-08-12", 1080, 1200)
        moved = validate_success(res, 200)
        assert moved["status"] == "CONFIRMED"
        assert moved["original_permit_id"] == permit["id"], \
            "first reschedule: the null becomes the permit's own id (lineage root)"

        lineage = validate_success(api.list_permits(
            athletics_admin_headers, params={"original_permit_id": permit["id"]}), 200)
        assert [p["id"] for p in lineage] == [permit["id"]], \
            "the lineage filter returns exactly the rescheduled permit"
