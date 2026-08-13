"""Galley provisioning and alcohol-service compliance: input-set filtering,
order state machine, bartender certification, and the bar-service gate
(PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_passenger,
    assign_confirmed_bartender,
    assign_staff,
    confirm_assignment,
    create_booking,
    create_customer,
    create_paid_booking,
    create_placed_provision_order,
    create_provision_order,
    create_staff,
    get_booking,
    get_cruise,
    make_customer_headers,
    pay_booking,
    set_clock,
    setup_inventory,
    validate_error,
    validate_success,
    cancel_booking,
)

OM = TEST_USERS["ops_manager_headers"]
GALLEY = TEST_USERS["galley_manager_headers"]


class TestGalleyProvisionalInputSet:
    def test_cancelled_booking_excluded_from_provisional_covers(self, api):
        """PRD §3.5: "at creation the server computes the forward-looking
        `provisional_covers` — the sum of `party_size` over the cruise's bookings
        whose `booking_status` is `RESERVED` or `CONFIRMED` and whose
        `payment_status` is `PENDING` or `PAID` — and derives
        `provision_load_units` as the `provisional_covers` multiplied by the menu
        tier's `galley_load_per_cover`, carried to two decimal places and rounded
        half-up."

        Design: Corner/calculations/galley_provisional_input_set_excludes_cancelled
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        create_paid_booking(cruise["id"], customer["id"], 2, cruise["version"])
        version2 = get_cruise(cruise["id"])["version"]
        bk_b = create_booking(cruise["id"], customer["id"], 3, version2)
        cancel_booking(bk_b["id"], customer["id"])

        order = create_provision_order(cruise["id"])
        assert order["provisional_covers"] == 2, (
            f"Cancelled party-3 booking must be excluded, got "
            f"{order['provisional_covers']}"
        )
        assert order["provision_load_units"] == 5.0, (
            f"Load must be 5.0 (2 covers * 2.5), got "
            f"{order['provision_load_units']}"
        )

    def test_pending_payment_bookings_included_in_provisional_covers(self, api):
        """PRD §3.5: "Note the provisional booking set deliberately includes
        unpaid (`PENDING`) reservations and excludes `BOARDED` ones, so it does
        not coincide with the `reserved_covers` definition in §3.3."

        Design: Corner/calculations/galley_provisional_input_set_excludes_cancelled
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("c@example.com", "C")
        create_paid_booking(cruise["id"], customer["id"], 2, cruise["version"])
        version2 = get_cruise(cruise["id"])["version"]
        # Unpaid PENDING booking still feeds the galley forecast.
        create_booking(cruise["id"], customer["id"], 3, version2)

        order = create_provision_order(cruise["id"])
        assert order["provisional_covers"] == 5, (
            f"PENDING covers must be included in the forecast, got "
            f"{order['provisional_covers']}"
        )


class TestProvisionOrderStateMachine:
    def test_receive_from_draft_rejected(self, api):
        """PRD §3.5: "Receipt of goods moves a `PLACED` order to `RECEIVED`."
        PRD §2.8: "4. Target entity state permits the requested transition —
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/provision_order_receive_from_draft_invalid
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        create_paid_booking(cruise["id"], customer["id"], 1, cruise["version"])
        order = create_provision_order(cruise["id"])
        assert order["status"] == "DRAFT"

        resp = api.receive_provision_order(cruise["id"], order["id"], GALLEY)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_place_without_covers_rejected(self, api):
        """PRD §3.5: "Placing the order requires it to stand at `DRAFT`
        (otherwise `ERR_INVALID_STATE`), requires the cruise to be `SCHEDULED`
        (otherwise `ERR_CRUISE_NOT_BOOKABLE`), and requires at least one
        provisional cover — an order with zero covers is rejected with
        `ERR_NO_COVERS_TO_PROVISION` (HTTP 422)."

        Design: Corner/validations/provision_place_without_covers_rejected
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        order = create_provision_order(cruise["id"])
        assert order["provisional_covers"] == 0

        resp = api.place_provision_order(cruise["id"], order["id"], GALLEY)
        validate_error(resp, ApiErrorId.ERR_NO_COVERS_TO_PROVISION)


class TestAlcoholServiceCompliance:
    def test_bartender_confirm_gated_on_cert_expiry(self, api):
        """PRD §3.4: "Confirming an assignment requires it to stand at
        `ASSIGNED` (otherwise `ERR_INVALID_STATE`), requires the cruise to be
        `SCHEDULED` (otherwise `ERR_CRUISE_NOT_BOOKABLE`), and — when the
        `assigned_role` is `BARTENDER` — requires the referenced staff member's
        `alcohol_cert_expires_at` to be later than the current logical clock
        reading, failing with `ERR_ALCOHOL_CERT_EXPIRED` when the certification
        has lapsed."
        PRD §3.4: "`bar_service_enabled` starts false and is true only while at
        least one `CONFIRMED` staff assignment on the cruise references a staff
        member whose `alcohol_cert_expires_at` is later than the current logical
        clock reading."

        Design: Difficulty/cross_entity_state_dependency/bartender_confirm_gated_on_staffmember_cert
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        expired = create_staff("Exp", "BARTENDER", "2026-01-01T00:00:00Z")
        valid = create_staff("Val", "BARTENDER", "2027-01-01T00:00:00Z")
        asg_x = assign_staff(cruise["id"], expired["id"], "BARTENDER")
        asg_y = assign_staff(cruise["id"], valid["id"], "BARTENDER")
        set_clock("2026-08-05T00:00:00Z")

        resp = api.confirm_staff_assignment(cruise["id"], asg_x["id"], OM)
        validate_error(resp, ApiErrorId.ERR_ALCOHOL_CERT_EXPIRED)

        confirmed = confirm_assignment(cruise["id"], asg_y["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert get_cruise(cruise["id"])["bar_service_enabled"] is True

    def test_bar_service_flag_follows_clock_past_cert_expiry(self, api):
        """PRD §3.4: "Because the comparison is against the live clock,
        advancing time can silently flip the flag even with no staffing change"

        Design: Difficulty/cross_entity_state_dependency/bartender_confirm_gated_on_staffmember_cert
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        assign_confirmed_bartender(cruise["id"],
                                   cert_expires_at="2026-08-20T00:00:00Z")
        assert get_cruise(cruise["id"])["bar_service_enabled"] is True

        # Advancing the logical clock past the cert expiry flips the flag with
        # no staffing change at all.
        set_clock("2026-08-21T00:00:00Z")
        assert get_cruise(cruise["id"])["bar_service_enabled"] is False, (
            "bar_service_enabled must recompute against the live clock"
        )


class TestBarServicePaymentGate:
    def test_pay_with_bar_package_without_certified_bartender_rejected(self, api):
        """PRD §3.3: "when `bar_package_count` is greater than zero, the
        cruise's `bar_service_enabled` must be true at that moment (otherwise
        `ERR_BAR_SERVICE_UNAVAILABLE` — see §3.4 for how that flag is earned)"

        Design: Corner/validations/bar_package_pay_without_certified_bartender_rejected
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        assert cruise["bar_service_enabled"] is False
        customer = create_customer("a@example.com", "A")
        booking = create_booking(cruise["id"], customer["id"], 2,
                                 cruise["version"], bar_package_count=1)

        resp = api.pay_booking(booking["id"],
                               make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_BAR_SERVICE_UNAVAILABLE)
        assert get_booking(booking["id"])["payment_status"] == "PENDING", (
            "The rejected pay must leave payment_status unchanged"
        )

    def test_pay_with_bar_package_succeeds_once_bar_service_enabled(self, api):
        """PRD §3.4: "because §3.3 gates beverage-package payment on it, a
        booking carrying a positive `bar_package_count` can only be paid while
        certified staff stand confirmed on the cruise"

        Design: Corner/validations/bar_package_pay_without_certified_bartender_rejected
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        assign_confirmed_bartender(cruise["id"])
        assert get_cruise(cruise["id"])["bar_service_enabled"] is True
        customer = create_customer("b@example.com", "B")
        # Confirming the bartender recomputes bar_service_enabled, which bumps
        # the cruise version (PRD §2.10) — re-read before the OCC token.
        booking = create_booking(cruise["id"], customer["id"], 2,
                                 get_cruise(cruise["id"])["version"],
                                 bar_package_count=1)
        paid = pay_booking(booking["id"], customer["id"])
        assert paid["payment_status"] == "PAID"


class TestStaffingRbac:
    def test_galley_manager_cannot_confirm_staff(self, api):
        """PRD §2.1: "`GalleyManager` owns galley provisioning."
        PRD §2.1: "An attempt to perform an operation outside the roles
        authorized for it in §4 is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "POST | `/cruises/{id}/staff-assignments/{id}/confirm` | Confirm
        an assignment | OperationsManager"

        Design: Corner/rbac/galley_manager_cannot_confirm_staff
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        staff = create_staff("Sam", "SERVER")
        assignment = assign_staff(cruise["id"], staff["id"], "SERVER")
        assert assignment["status"] == "ASSIGNED"

        resp = api.confirm_staff_assignment(cruise["id"], assignment["id"],
                                            GALLEY)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
