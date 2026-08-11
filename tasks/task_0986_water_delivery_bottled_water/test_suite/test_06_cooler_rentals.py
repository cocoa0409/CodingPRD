"""Cooler rentals: prorated rent accrual, suspend/resume cycle, and the
cross-entity requirement that installation needs an ACTIVE customer."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_customer, setup_cooler_rental, setup_installed_rental, install_rental,
    deliver_via_work_order, create_and_issue_invoice, set_clock,
    get_cooler_rental, get_work_order, get_invoice,
    OPS_ADMIN, DISPATCHER, DRIVER, BILLING_ADMIN,
)

# PRD §3.8: daily rate = monthly_rent_cents * 12 / 365, rounded half-up.
# 9000 * 12 / 365 = 295.8904... -> 296.
DAILY_RATE_9000 = 296


class TestProratedRent:
    def test_prorated_rent_full_period_after_install(self, api):
        """PRD §3.8: "For each rental that stands `INSTALLED`, `SUSPENDED`, or
        `RETURN_REQUESTED` at period end, or whose `returned_at` falls inside
        the period, the daily rate is the `monthly_rent_cents` multiplied by
        twelve — the months in a year — and divided by 365, the days in a year,
        rounded half-up to a whole cent at that daily-rate step. The rental's
        accrual for the period is that daily rate multiplied by the number of
        days in the half-open billing window on which the rental stood
        `INSTALLED`; suspended days accrue zero."

        Installed 2026-05-15 and standing INSTALLED for all 30 days of
        [2026-06-01, 2026-07-01): 296 * 30 = 8880.

        Design: Difficulty/combinatorial_formula/prorated_rent_mode_a_multilevel
        """
        s = setup_installed_rental("2026-05-15T09:00:00Z", monthly_rent_cents=9000,
                                   deposit_cents=30000, cooler_model="FREESTANDING")
        set_clock("2026-07-01T00:00:00Z")
        invoice = create_and_issue_invoice(s["customer"]["id"], "2026-06-01",
                                           "2026-07-01", "2026-07-15")
        assert invoice["subtotal_rent_cents"] == DAILY_RATE_9000 * 30, (
            f"30 installed days at daily rate 296 must yield 8880, "
            f"got {invoice['subtotal_rent_cents']}"
        )

    def test_prorated_rent_suspended_days_accrue_zero(self, api):
        """PRD §3.8: "The rental's accrual for the period is that daily rate
        multiplied by the number of days in the half-open billing window on
        which the rental stood `INSTALLED`; suspended days accrue zero."

        Installed 2026-05-15, suspended at 2026-06-16T00:00:00Z: June 1-15
        installed (15 days), June 16-30 suspended (zero accrual):
        296 * 15 = 4440.

        Design: Difficulty/combinatorial_formula/prorated_rent_mode_a_multilevel
        """
        s = setup_installed_rental("2026-05-15T09:00:00Z", monthly_rent_cents=9000,
                                   deposit_cents=30000, cooler_model="FREESTANDING")
        rental_id = s["rental"]["id"]
        set_clock("2026-06-16T00:00:00Z")
        validate_success(api.suspend_cooler_rental(rental_id, OPS_ADMIN), 200)
        set_clock("2026-07-01T00:00:00Z")
        invoice = create_and_issue_invoice(s["customer"]["id"], "2026-06-01",
                                           "2026-07-01", "2026-07-15")
        assert invoice["subtotal_rent_cents"] == DAILY_RATE_9000 * 15, (
            f"15 installed days at daily rate 296 must yield 4440, "
            f"got {invoice['subtotal_rent_cents']}"
        )


class TestSuspendResumeCycle:
    def test_suspend_resume_status_cycle(self, api):
        """PRD §3.6: "From `INSTALLED`, an `OpsAdmin` may suspend the rental —
        its `rental_status` moving to `SUSPENDED` — to pause rent accrual, and
        later resume it back to `INSTALLED`, restarting accrual from that
        moment."

        Design: Difficulty/non_linear_state_machine/cooler_rental_suspend_resume_cycle
        """
        s = setup_installed_rental("2026-06-01T09:00:00Z", monthly_rent_cents=9000,
                                   cooler_model="COUNTERTOP")
        rental_id = s["rental"]["id"]

        suspended = validate_success(api.suspend_cooler_rental(rental_id, OPS_ADMIN), 200)
        assert suspended["rental_status"] == "SUSPENDED"
        resumed = validate_success(api.resume_cooler_rental(rental_id, OPS_ADMIN), 200)
        assert resumed["rental_status"] == "INSTALLED"

        # Cycle a second time: the machine allows INSTALLED <-> SUSPENDED again.
        set_clock("2026-06-26T00:00:00Z")
        suspended2 = validate_success(api.suspend_cooler_rental(rental_id, OPS_ADMIN), 200)
        assert suspended2["rental_status"] == "SUSPENDED"
        resumed2 = validate_success(api.resume_cooler_rental(rental_id, OPS_ADMIN), 200)
        assert resumed2["rental_status"] == "INSTALLED"

    def test_accrual_counts_only_installed_days_across_cycle(self, api):
        """PRD §3.8: "The rental's accrual for the period is that daily rate
        multiplied by the number of days in the half-open billing window on
        which the rental stood `INSTALLED`; suspended days accrue zero."
        PRD §3.6: "From `INSTALLED`, an `OpsAdmin` may suspend the rental —
        its `rental_status` moving to `SUSPENDED` — to pause rent accrual, and
        later resume it back to `INSTALLED`, restarting accrual from that
        moment."

        Installed 2026-05-15; suspended 2026-06-16T00:00:00Z, resumed
        2026-06-21T00:00:00Z: June 1-15 (15 days) plus June 21-30 (10 days)
        installed, June 16-20 suspended: 296 * 25 = 7400.

        Design: Difficulty/non_linear_state_machine/cooler_rental_suspend_resume_cycle
        """
        s = setup_installed_rental("2026-05-15T09:00:00Z", monthly_rent_cents=9000,
                                   cooler_model="COUNTERTOP")
        rental_id = s["rental"]["id"]
        set_clock("2026-06-16T00:00:00Z")
        validate_success(api.suspend_cooler_rental(rental_id, OPS_ADMIN), 200)
        set_clock("2026-06-21T00:00:00Z")
        validate_success(api.resume_cooler_rental(rental_id, OPS_ADMIN), 200)

        set_clock("2026-07-01T00:00:00Z")
        invoice = create_and_issue_invoice(s["customer"]["id"], "2026-06-01",
                                           "2026-07-01", "2026-07-15")
        assert invoice["subtotal_rent_cents"] == DAILY_RATE_9000 * 25, (
            f"25 installed days at daily rate 296 must yield 7400, "
            f"got {invoice['subtotal_rent_cents']}"
        )


class TestInstallRequiresActiveCustomer:
    def _rental_on_suspended_customer(self, api):
        """Rental with a SCHEDULED install work order, then the customer is
        suspended over an unpaid invoice."""
        world = setup_customer(account_type="OFFICE", business_name="Cool9",
                               billing_email="c9@x.example", service_address="9 C",
                               service_mode="WILL_CALL", par_level_bottles=0,
                               pricing_tier="STANDARD")
        zone, customer = world["zone"], world["customer"]
        parts = setup_cooler_rental(customer["id"], monthly_rent_cents=5000,
                                    deposit_cents=15000, cooler_model="COUNTERTOP")
        # Generate an outstanding balance so the suspension gate opens.
        deliver_via_work_order(customer["id"], zone["id"], "2026-05-05", 1)
        create_and_issue_invoice(customer["id"], "2026-05-01", "2026-06-01",
                                 "2026-06-15")
        suspended = validate_success(api.suspend_customer(customer["id"], OPS_ADMIN), 200)
        return {"zone": zone, "customer": suspended,
                "rental": parts["rental"], "work_order": parts["work_order"]}

    def test_install_rejected_when_customer_suspended(self, api):
        """PRD §3.6: "Installation happens in the field: the driver marks the
        rental installed — allowed only while the customer is `ACTIVE` and the
        linked work order stands `IN_PROGRESS` — which stamps `installed_at`
        from the logical clock and completes the linked work order."
        PRD §2.6: "Whether the target resource is in a state that permits the
        requested transition — violations return `ERR_INVALID_STATE`; an
        operation attempted on a resource already sitting in a terminal state is
        instead rejected with `ERR_ALREADY_TERMINAL`."

        Design: Difficulty/cross_entity_state_dependency/cooler_install_requires_customer_active
        """
        s = self._rental_on_suspended_customer(api)
        assert s["customer"]["account_status"] == "SUSPENDED"

        set_clock("2026-06-01T10:00:00Z")
        res = api.install_cooler_rental(s["rental"]["id"], DRIVER)
        validate_error(res, "ERR_INVALID_STATE")
        rental = get_cooler_rental(s["rental"]["id"])
        assert rental["rental_status"] == "PENDING_INSTALL", \
            f"rejected install must leave the rental PENDING_INSTALL, got {rental['rental_status']}"

    def test_install_succeeds_when_customer_active(self, api):
        """PRD §3.6: "Installation happens in the field: the driver marks the
        rental installed — allowed only while the customer is `ACTIVE` and the
        linked work order stands `IN_PROGRESS` — which stamps `installed_at`
        from the logical clock and completes the linked work order."

        The same transition succeeds while the customer is ACTIVE, stamping
        installed_at and completing the linked work order — the contrast pins
        the customer-state dependency.

        Design: Difficulty/cross_entity_state_dependency/cooler_install_requires_customer_active
        """
        world = setup_customer(account_type="OFFICE", business_name="CoolActive",
                               billing_email="ca@x.example", service_address="9 CA",
                               service_mode="WILL_CALL", par_level_bottles=0,
                               pricing_tier="STANDARD")
        customer = world["customer"]
        parts = setup_cooler_rental(customer["id"], monthly_rent_cents=5000,
                                    deposit_cents=15000, cooler_model="COUNTERTOP")

        installed = install_rental(parts["rental"]["id"], "2026-06-01T10:00:00Z")
        assert installed["rental_status"] == "INSTALLED"
        assert installed["installed_at"] is not None, \
            "install must stamp installed_at from the logical clock"
        work_order = get_work_order(parts["work_order"]["id"])
        assert work_order["order_status"] == "COMPLETED", \
            f"install must complete the linked work order, got {work_order['order_status']}"
