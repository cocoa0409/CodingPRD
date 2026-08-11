"""Refill bay: tare tolerance, overfill guard, tiered charge, close (PRD §2.5, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    close_ticket,
    condemn_cylinder,
    create_priced_site,
    create_technician,
    create_ticket,
    fill_ticket,
    open_session,
    register_customer_cylinder,
    register_fleet_cylinders,
    TEST_USERS,
    ticket_in_state,
    validate_error,
    validate_success,
    weigh_ticket,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK1 = TEST_USERS["site_clerk_headers"]
OFFICER1 = TEST_USERS["compliance_officer_headers"]


class TestWeigh:
    def test_refill_ticket_initial_state_and_weigh(self, api):
        """PRD §3.4: "The ticket opens in `OPEN` status."
        PRD §3.4: "the ticket advances from `OPEN` to `WEIGHED` only if the absolute deviation between `measured_tare_lbs` and the cylinder's stamped `tare_weight_lbs` does not exceed one-tenth of a pound, and only if `pre_weight_lbs` is at least `measured_tare_lbs` — either failure is rejected with `ERR_TARE_MISMATCH`."
        PRD §3.4: "the cylinder's stamped `water_capacity_lbs` multiplied by 0.42, rounded half-up to two decimal places."

        Design: Corner/state_machines/refill_ticket_initial_state_and_weigh
        """
        site, _policy = create_priced_site()
        customer = register_customer_cylinder(fill="EMPTY")
        ticket = create_ticket(site["id"], customer["id"], CLERK1, pre_weight_lbs=17.50)
        assert ticket["status"] == "OPEN"
        assert ticket["max_fill_lbs"] == pytest.approx(19.99), "round_half_up(47.60 * 0.42, 2)"
        weighed = weigh_ticket(ticket["id"], 17.05, CLERK1)
        assert weighed["status"] == "WEIGHED"
        assert weighed["measured_tare_lbs"] == pytest.approx(17.05), "|17.05 - 17.00| = 0.05 <= 0.10"

    def test_tare_mismatch_beyond_tolerance(self, api):
        """PRD §3.4: "the ticket advances from `OPEN` to `WEIGHED` only if the absolute deviation between `measured_tare_lbs` and the cylinder's stamped `tare_weight_lbs` does not exceed one-tenth of a pound, and only if `pre_weight_lbs` is at least `measured_tare_lbs` — either failure is rejected with `ERR_TARE_MISMATCH`."

        Design: Corner/validations/tare_mismatch_beyond_tolerance
        """
        site, _policy = create_priced_site()
        customer = register_customer_cylinder(fill="EMPTY")  # stamped tare 17.00
        ticket_a = create_ticket(site["id"], customer["id"], CLERK1, pre_weight_lbs=17.50)
        ticket_b = create_ticket(site["id"], customer["id"], CLERK1, pre_weight_lbs=17.50)
        # 0.10 deviation is inside the inclusive tolerance.
        weighed = weigh_ticket(ticket_a["id"], 17.10, CLERK1)
        assert weighed["status"] == "WEIGHED"
        # 0.11 deviation is outside.
        res = api.weigh_refill_ticket(ticket_b["id"], {"measured_tare_lbs": 17.11}, CLERK1)
        validate_error(res, ApiErrorId.ERR_TARE_MISMATCH, expected_status=422)


class TestInvalidTransitions:
    def test_close_open_ticket_returns_invalid_state(self, api):
        """PRD §2.7 (stage 6): "The target resource is in a valid from-state for the requested transition, terminal states are locked against further action, the site is `ACTIVE` for sales and dispatch (`ERR_SITE_NOT_ACTIVE`), and a driver's arrival date matches the run's planned date; otherwise `ERR_INVALID_STATE`."
        PRD §3.4: "Closing takes the money." — closing operates on a `FILLED` ticket.

        Design: Corner/state_machines/close_open_ticket_returns_invalid_state
        """
        site, _policy = create_priced_site()
        customer = register_customer_cylinder(fill="EMPTY")
        ticket = create_ticket(site["id"], customer["id"], CLERK1, pre_weight_lbs=17.50)
        res = api.close_refill_ticket(ticket["id"], {"payment_cash_cents": 9999}, CLERK1)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_refill_fleet_cylinder_not_refillable(self, api):
        """PRD §3.4: "The referenced cylinder must exist (else `ERR_REFERENCE_NOT_FOUND`) and must be `owner_kind` `CUSTOMER` — opening a ticket against a fleet cylinder is rejected with `ERR_NOT_REFILLABLE`."

        Design: Corner/validations/refill_fleet_cylinder_not_refillable
        """
        site, _policy = create_priced_site()
        fleet = register_fleet_cylinders(site_id=site["id"], count=1, fill="EMPTY",
                                         serial_prefix="NR")[0]
        res = api.create_refill_ticket(
            {"site_id": site["id"], "cylinder_id": fleet["id"], "pre_weight_lbs": 17.50},
            CLERK1,
        )
        validate_error(res, ApiErrorId.ERR_NOT_REFILLABLE, expected_status=409)


class TestFill:
    def test_refill_charge_full_computation(self, api):
        """PRD §3.4: "the tier-one quantity is the smaller of `propane_lbs` and `tier1_max_lbs`; the tier-two quantity is whatever remains of `propane_lbs`; each tier's pounds are multiplied by that tier's per-pound rate and rounded half-up to whole cents individually; and `propane_charge_cents` is the sum of the two rounded tier amounts."
        PRD §3.4: "The `hazmat_fee_cents` on the ticket is zero when the site's `promo_waives_hazmat` is true and the site's flat `hazmat_fee_cents` otherwise, and the ticket's `total_cents` is `propane_charge_cents` plus `hazmat_fee_cents`."
        PRD §3.4: "the cylinder's `fill_status` becomes `FULL`; `business_date`, `sale_seq`, and `change_due_cents` are stamped exactly as at the exchange counter; the ticket lands in `CLOSED`"

        Design: Corner/calculations/refill_charge_full_computation
        """
        site, _policy = create_priced_site(site_overrides={"hazmat_fee_cents": 75})
        customer = register_customer_cylinder(fill="EMPTY")
        ticket = create_ticket(site["id"], customer["id"], CLERK1, pre_weight_lbs=17.00)
        weigh_ticket(ticket["id"], 17.00, CLERK1)
        filled = fill_ticket(ticket["id"], 35.50, CLERK1)  # 18.50 lbs dispensed
        assert filled["propane_lbs"] == pytest.approx(18.50)
        # tier1: 15.00 * 349 = 5235; tier2: round_half_up(3.50 * 299) = 1047
        assert filled["propane_charge_cents"] == 6282
        assert filled["hazmat_fee_cents"] == 75
        assert filled["total_cents"] == 6357
        closed = close_ticket(filled["id"], 6357, CLERK1)
        assert closed["status"] == "CLOSED"
        assert closed["change_due_cents"] == 0
        assert closed["sale_seq"] == 1
        cyl = validate_success(api.get_cylinder(customer["id"], ADMIN), 200)
        assert cyl["fill_status"] == "FULL"

    def test_overfill_exact_max_fill_allowed(self, api):
        """PRD §3.4: "The overfill guard is inclusive at the ceiling: `propane_lbs` equal to `max_fill_lbs` is permitted, and any excess, however small, is rejected with `ERR_OVERFILL_RISK`."

        Design: Difficulty/boundary_precision_check/overfill_exact_max_fill_allowed
        """
        site, _policy = create_priced_site()
        customer = register_customer_cylinder(fill="EMPTY")
        ticket = create_ticket(site["id"], customer["id"], CLERK1, pre_weight_lbs=17.00)
        assert ticket["max_fill_lbs"] == pytest.approx(19.99)
        weigh_ticket(ticket["id"], 17.00, CLERK1)
        # 36.99 - 17.00 = 19.99 lbs == max_fill_lbs exactly.
        filled = fill_ticket(ticket["id"], 36.99, CLERK1)
        assert filled["status"] == "FILLED"
        assert filled["propane_lbs"] == pytest.approx(19.99)
        # tier1 15.00*349 = 5235; tier2 round_half_up(4.99*299) = 1492; hazmat 0
        assert filled["propane_charge_cents"] == 6727
        assert filled["total_cents"] == 6727

    def test_overfill_one_centi_pound_over_rejected(self, api):
        """PRD §3.4: "The overfill guard is inclusive at the ceiling: `propane_lbs` equal to `max_fill_lbs` is permitted, and any excess, however small, is rejected with `ERR_OVERFILL_RISK`."

        Design: Difficulty/boundary_precision_check/overfill_exact_max_fill_allowed
        """
        site, _policy = create_priced_site()
        customer = register_customer_cylinder(fill="EMPTY")
        ticket = create_ticket(site["id"], customer["id"], CLERK1, pre_weight_lbs=17.00)
        weigh_ticket(ticket["id"], 17.00, CLERK1)
        # 37.00 - 17.00 = 20.00 lbs > max_fill 19.99.
        res = api.fill_refill_ticket(ticket["id"], {"post_weight_lbs": 37.00}, CLERK1)
        validate_error(res, ApiErrorId.ERR_OVERFILL_RISK, expected_status=422)

    def test_fill_quarantined_cylinder_rejected(self, api):
        """PRD §3.4: "and it must not be `QUARANTINED` (else `ERR_CYLINDER_QUARANTINED`)."

        Design: Corner/validations/fill_quarantined_cylinder_rejected
        """
        site, _policy = create_priced_site()
        customer = register_customer_cylinder(fill="EMPTY")
        ticket = ticket_in_state(site["id"], customer["id"], "WEIGHED", CLERK1,
                                 pre_weight_lbs=17.50, measured_tare_lbs=17.00)
        validate_success(
            api.quarantine_cylinder(customer["id"], {"note": "smell"}, OFFICER1), 200)
        res = api.fill_refill_ticket(ticket["id"], {"post_weight_lbs": 30.00}, CLERK1)
        validate_error(res, ApiErrorId.ERR_CYLINDER_QUARANTINED, expected_status=409)

    def test_fill_recert_due_cylinder_rejected(self, api):
        """PRD §3.4: "it must be `CERTIFIED` — a `RECERT_DUE` bottle is rejected with `ERR_CYLINDER_NOT_CERTIFIED`"
        The ticket was created and WEIGHED while the cylinder was still CERTIFIED; the clock advance flips the cylinder before the fill.

        Design: Difficulty/cross_entity_state_dependency/refill_fill_requires_cylinder_certified
        """
        site, _policy = create_priced_site()
        customer = register_customer_cylinder(fill="EMPTY", manufacture_date="2014-06-01")
        ticket = ticket_in_state(site["id"], customer["id"], "WEIGHED", CLERK1,
                                 pre_weight_lbs=17.50, measured_tare_lbs=17.00)
        advance_clock("2026-06-02T00:00:00Z")  # past the 2026-06-01 expiry
        res = api.fill_refill_ticket(ticket["id"], {"post_weight_lbs": 30.00}, CLERK1)
        validate_error(res, ApiErrorId.ERR_CYLINDER_NOT_CERTIFIED, expected_status=409)

    def test_fill_condemned_cylinder_rejected(self, api):
        """PRD §3.4: "the ticket must be `WEIGHED` (else `ERR_INVALID_STATE`); the cylinder must not be `CONDEMNED` (else `ERR_CYLINDER_CONDEMNED`)"

        Design: Difficulty/cross_entity_state_dependency/refill_fill_requires_cylinder_certified
        """
        site, _policy = create_priced_site()
        customer = register_customer_cylinder(fill="EMPTY")
        ticket = ticket_in_state(site["id"], customer["id"], "WEIGHED", CLERK1,
                                 pre_weight_lbs=17.50, measured_tare_lbs=17.00)
        condemn_cylinder(customer["id"])
        res = api.fill_refill_ticket(ticket["id"], {"post_weight_lbs": 30.00}, CLERK1)
        validate_error(res, ApiErrorId.ERR_CYLINDER_CONDEMNED, expected_status=409)


class TestClose:
    def test_insufficient_payment_at_refill_close(self, api):
        """PRD §3.4: "The clerk tenders `payment_cash_cents`, which must equal or exceed `total_cents` (else `ERR_INSUFFICIENT_PAYMENT`)"

        Design: Corner/validations/insufficient_payment_at_refill_close
        """
        site, _policy = create_priced_site()
        customer = register_customer_cylinder(fill="EMPTY")
        ticket = ticket_in_state(site["id"], customer["id"], "FILLED", CLERK1,
                                 pre_weight_lbs=17.00, post_weight_lbs=35.50)
        assert ticket["total_cents"] == 6282
        res = api.close_refill_ticket(ticket["id"], {"payment_cash_cents": 6281}, CLERK1)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PAYMENT, expected_status=402)
        after = validate_success(api.get_refill_ticket(ticket["id"], ADMIN), 200)
        assert after["status"] == "FILLED", "failed close leaves the ticket FILLED"
