"""Damage assessments: the charge formula, the invoice cascade (deposit capture,
standing recompute, lease suspension, unit loss), disputes, and deposit
conservation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_item,
    assign_item,
    confirm,
    make_customer,
    make_customer_headers,
    make_damage_assessment,
    make_equipment_item,
    make_reservation,
    set_clock,
    setup_returned_reservation,
    setup_suspended_lease_via_total_loss,
    validate_error,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]
TECH = TEST_USERS["technician_headers"]
MGR = TEST_USERS["manager_headers"]


class TestInvoiceCascade:
    def test_invoice_captures_deposit_and_bars_customer(self, api):
        """PRD Damage Assessments: "Link one moves money: the invoice captures from the
        reservation's deposit hold the smaller of the charge and the as-yet-uncaptured
        portion of the authorized hold — assessments against one reservation capturing
        in creation order, earliest first — adds that amount to the reservation's
        `deposit_captured_cents`, records it as the assessment's own
        `deposit_captured_cents`, and sets the assessment's `remainder_due_cents` to
        whatever of the charge the deposit could not cover."

        Design: Difficulty/transitive_cascade/damage_invoice_cascade_to_lease_suspension
        """
        ctx = setup_suspended_lease_via_total_loss()
        assessment = ctx["assessment"]
        reservation_after = validate_success(
            api.get_reservation(ctx["reservation"]["id"], FD))
        # TOTAL_LOSS on a 60000-price unit with 3 accrued days: no depreciation yet,
        # min(1.0 x 60000, 60000) = 60000; the 2400 hold caps the capture.
        assert assessment["charge_cents"] == 60000
        assert assessment["deposit_captured_cents"] == 2400
        assert assessment["remainder_due_cents"] == 57600
        assert reservation_after["deposit_captured_cents"] == 2400

    def test_invoice_cascade_suspends_lease_and_loses_unit(self, api):
        """PRD Damage Assessments: "Link three is the consequence: if standing lands on
        `BARRED`, every `ACTIVE` season lease of that customer suspends immediately.
        The fan-out link handles the unit: an invoice at severity `TOTAL_LOSS` flips
        the unit from `AWAITING_INSPECTION` to `LOST`."
        PRD Customer Profiles: "If any unpaid invoiced damage assessment against the
        customer's reservations has severity `TOTAL_LOSS`, the customer is `BARRED`."

        Design: Difficulty/transitive_cascade/damage_invoice_cascade_to_lease_suspension
        """
        ctx = setup_suspended_lease_via_total_loss()
        junior = validate_success(api.get_customer(ctx["junior"]["id"], FD))
        assert junior["standing"] == "BARRED"
        lease = validate_success(api.get_season_lease(ctx["lease"]["id"], FD))
        assert lease["status"] == "SUSPENDED"
        unit = validate_success(api.get_equipment_item(ctx["rental_unit"]["id"], FD))
        assert unit["status"] == "LOST"


class TestDepositConservation:
    def _setup_invoiced_cosmetic(self, api):
        """On-time 3-day rental on a 20000-price / 3000-rate unit (quote 9000) with a
        5000 hold; COSMETIC damage (2000) invoiced; unit inspected PASS."""
        ctx = setup_returned_reservation(rate=3000, price=20000,
                                         deposit_authorized_cents=5000)
        unit = ctx["units"][0]
        assessment = make_damage_assessment(ctx["reservation"], unit,
                                            severity="COSMETIC")
        invoiced = validate_success(api.invoice_damage_assessment(assessment["id"], FD))
        validate_success(api.inspect_equipment_item(unit["id"], {"outcome": "PASS"}, TECH))
        return ctx, invoiced

    def test_close_releases_uncaptured_remainder(self, api):
        """PRD The Deposit Waterfall: "At close or cancellation, the remainder is
        released into `deposit_released_cents`, set so that the invariant
        `deposit_authorized_cents` equals `deposit_captured_cents` plus
        `deposit_released_cents` always holds once the reservation is closed or
        cancelled."

        Design: Difficulty/compensating_invariant/deposit_capture_release_conservation
        """
        ctx, invoiced = self._setup_invoiced_cosmetic(api)
        assert invoiced["deposit_captured_cents"] == 2000
        assert invoiced["remainder_due_cents"] == 0

        closed = validate_success(api.close_reservation(ctx["reservation"]["id"], FD))
        # 5000 authorized == 2000 captured + 3000 released.
        assert closed["deposit_authorized_cents"] == 5000
        assert closed["deposit_captured_cents"] == 2000
        assert closed["deposit_released_cents"] == 3000
        assert closed["deposit_authorized_cents"] == (
            closed["deposit_captured_cents"] + closed["deposit_released_cents"])

    def test_close_settles_payment_axis(self, api):
        """PRD From Confirm to Close: "Closing moves fulfillment to `CLOSED` and
        payment from `CAPTURED` to `SETTLED`, and settles the deposit waterfall: every
        still-unclaimed portion of the hold is released so that authorized equals
        captured plus released."

        Design: Difficulty/compensating_invariant/deposit_capture_release_conservation
        """
        ctx, _ = self._setup_invoiced_cosmetic(api)
        closed = validate_success(api.close_reservation(ctx["reservation"]["id"], FD))
        assert closed["payment_status"] == "SETTLED"
        assert closed["fulfillment_status"] == "CLOSED"


class TestDamageChargeCalculation:
    def _setup_unit_with_47_accrued_days(self, api):
        """45-day on-time rental plus a 2-day on-time rental on the same unit:
        accrued_rental_days 47, so the depreciation factor is 1 - 0.02 x 1 = 0.98."""
        customer = make_customer()
        unit = make_equipment_item()
        r1 = make_reservation(customer, start_date="2026-12-01", end_date="2027-01-14")
        i1 = add_item(r1)
        assign_item(i1, preferred_equipment_item_id=unit["id"])
        confirm(r1, 36000)
        set_clock("2026-12-01T09:00:00Z")
        validate_success(api.pickup_reservation(r1["id"], FD))
        set_clock("2027-01-14T17:00:00Z")
        validate_success(api.return_reservation(r1["id"], FD))
        validate_success(api.inspect_equipment_item(unit["id"], {"outcome": "PASS"}, TECH))

        r2 = make_reservation(customer, start_date="2027-02-01", end_date="2027-02-02")
        i2 = add_item(r2)
        assign_item(i2, preferred_equipment_item_id=unit["id"])
        confirm(r2, 1600)
        set_clock("2027-02-01T09:00:00Z")
        validate_success(api.pickup_reservation(r2["id"], FD))
        set_clock("2027-02-02T17:00:00Z")
        returned = validate_success(api.return_reservation(r2["id"], FD))
        return unit, returned

    def test_depreciated_floor_binds_total_loss_but_not_major(self, api):
        """PRD Damage Assessments: "the depreciation factor starts at full value and
        sheds two percent for every complete thirty-day block in the unit's
        `accrued_rental_days`, never falling below a thirty-percent floor. The
        depreciated value is the purchase price times that factor, rounded half-up. The
        final `charge_cents` is the smaller of the severity percentage of the purchase
        price and the depreciated value, rounded half-up"

        Design: Corner/calculations/damage_charge_nested_min_depreciation
        """
        unit, returned = self._setup_unit_with_47_accrued_days(api)
        unit_after = validate_success(api.get_equipment_item(unit["id"], FD))
        assert unit_after["accrued_rental_days"] == 47

        major = make_damage_assessment(returned, unit, severity="MAJOR")
        total = make_damage_assessment(returned, unit, severity="TOTAL_LOSS")
        # Depreciated value: 60000 x 0.98 = 58800.
        assert major["charge_cents"] == 30000   # min(0.50 x 60000, 58800)
        assert total["charge_cents"] == 58800   # the nested min binds TOTAL_LOSS


class TestDisputeResolution:
    def test_upheld_with_adjusted_charge_compensates_capture(self, api):
        """PRD Damage Assessments: "`UPHELD` sends the assessment back to `INVOICED`,
        replacing `charge_cents` with an `adjusted_charge_cents` when one is provided
        and adjusting the reservation's captured deposit by the resulting delta"

        Design: Corner/state_machines/damage_dispute_upheld_cycle_adjusts_capture
        """
        ctx = setup_returned_reservation(rate=3000, price=20000,
                                         deposit_authorized_cents=5000)
        unit = ctx["units"][0]
        reservation = ctx["reservation"]
        assessment = make_damage_assessment(reservation, unit, severity="COSMETIC")
        invoiced = validate_success(api.invoice_damage_assessment(assessment["id"], FD))
        assert invoiced["charge_cents"] == 2000

        disputed = validate_success(api.dispute_damage_assessment(
            invoiced["id"], make_customer_headers(ctx["customer"]["id"])))
        assert disputed["status"] == "DISPUTED"

        resolved = validate_success(api.resolve_damage_assessment(
            invoiced["id"], {"resolution": "UPHELD", "adjusted_charge_cents": 1500}, MGR))
        assert resolved["status"] == "INVOICED"
        assert resolved["charge_cents"] == 1500
        assert resolved["deposit_captured_cents"] == 1500

        reservation_after = validate_success(api.get_reservation(reservation["id"], FD))
        # Capture delta -500 compensated on the reservation.
        assert reservation_after["deposit_captured_cents"] == 1500


class TestAssessmentReferentialIntegrity:
    def test_unit_never_on_reservation_rejected(self, api):
        """PRD Damage Assessments: "the unit must have genuinely been an item of that
        reservation, in any line status including already-`RETURNED` lines; a unit that
        was never on the reservation is rejected with `ERR_ITEM_NOT_IN_RESERVATION`."

        Design: Corner/validations/damage_item_not_in_reservation_rejected
        """
        ctx = setup_returned_reservation()
        unrelated = make_equipment_item(size_label="171cm")
        resp = api.create_damage_assessment(
            {"reservation_id": ctx["reservation"]["id"],
             "equipment_item_id": unrelated["id"], "severity": "MINOR"},
            TECH,
        )
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_IN_RESERVATION)


class TestStandingWatchThreshold:
    def test_third_late_return_flips_watch(self, api):
        """PRD Customer Profiles: "Otherwise, if any unpaid invoiced assessment exists
        at all, or the customer's `late_return_count` has reached three — exactly three
        late returns is enough, the boundary is inclusive — the customer is `WATCH`."
        PRD From Confirm to Close: "if any line came back with `late_days` above zero
        the customer's `late_return_count` increments by one — once per reservation,
        not per line"

        Design: Corner/calculations/standing_watch_threshold_at_third_late_return
        """
        customer = make_customer()
        unit = make_equipment_item()
        # Three separate 1-day rentals, each returned one day late.
        windows = (("2026-12-01", "2026-12-01", "2026-12-01T09:00:00Z", "2026-12-02T17:00:00Z"),
                   ("2026-12-10", "2026-12-10", "2026-12-10T09:00:00Z", "2026-12-11T17:00:00Z"),
                   ("2026-12-20", "2026-12-20", "2026-12-20T09:00:00Z", "2026-12-21T17:00:00Z"))
        for idx, (start, end, pickup_at, return_at) in enumerate(windows):
            reservation = make_reservation(customer, start_date=start, end_date=end)
            item = add_item(reservation)
            assign_item(item, preferred_equipment_item_id=unit["id"])
            confirm(reservation, 800)
            set_clock(pickup_at)
            validate_success(api.pickup_reservation(reservation["id"], FD))
            set_clock(return_at)
            validate_success(api.return_reservation(reservation["id"], FD))
            validate_success(api.inspect_equipment_item(unit["id"], {"outcome": "PASS"}, TECH))

            snapshot = validate_success(api.get_customer(customer["id"], FD))
            if idx < 2:
                assert snapshot["late_return_count"] == idx + 1
                assert snapshot["standing"] == "GOOD_STANDING"
            else:
                assert snapshot["late_return_count"] == 3
                assert snapshot["standing"] == "WATCH"
