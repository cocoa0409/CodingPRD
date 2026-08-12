"""Cross-entity cascades: the depth-3 household suspension chain."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_household, create_plan, create_subscription, create_coop,
    create_visit, install_coop, assign_visit, create_product,
    create_order, place_order,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def _suspendable_scenario(api):
    """Plan (2 cleanings/period) + subscription + INSTALLED coop + one covered
    COOP_CLEANING SCHEDULED (used_cleanings == 1) + a PLACED order linked to
    that visit. Returns all participants."""
    plan = create_plan(plan_code="CLEAN2", monthly_fee_cents=2900,
                       included_cleanings_per_period=2, included_health_checks_per_period=1)
    household = create_household(name="H Casc", address="6 Hen Ln")
    subscription = create_subscription(household, plan["id"], "2026-05-01T00:00:00Z")
    coop = create_coop(household, 6, site_label="west")
    install_visit = install_coop(household, coop, date="2026-05-02")

    cleaning = create_visit(household, coop, "COOP_CLEANING",
                            "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")
    assert cleaning["coverage"] == "SUBSCRIPTION_COVERED"
    assign_visit(cleaning["id"], "tech-2")

    create_product(sku="FEED-B", name="Scratch Grains", unit_price_cents=500)
    order = create_order(household, [("FEED-B", 2)], fulfillment_visit_id=cleaning["id"])
    order = place_order(order["id"], household)
    assert order["status"] == "PLACED"
    return household, subscription, coop, install_visit, cleaning, order


class TestHouseholdSuspendCascade:
    def test_suspend_pauses_subscription_and_cancels_covered_visits(self, api):
        """PRD §3.1: "Suspension fires the system's deepest cascade. First, the
        household's subscription, if its status is `ACTIVE`, transitions to
        `PAUSED`. Second — caused by that pause — every covered ServiceVisit of
        the subscription (coverage `SUBSCRIPTION_COVERED` with status
        `REQUESTED`, `SCHEDULED`, or `RESCHEDULE_REQUESTED`) is cancelled, and
        each cancellation releases its reservation by decrementing the
        subscription's `used_cleanings` or `used_health_checks` counter."

        Design: Difficulty/transitive_cascade/household_suspend_cascade_depth3
        """
        household, subscription, coop, install_visit, cleaning, order = \
            _suspendable_scenario(api)

        suspended = validate_success(api.suspend_household(household["id"], BILLING), 200)
        assert suspended["status"] == "SUSPENDED"

        sub_after = validate_success(api.get_subscription(subscription["id"], BILLING), 200)
        assert sub_after["status"] == "PAUSED", "cascade link 1"
        assert sub_after["used_cleanings"] == 0, (
            "covered reservation released by the cancellation")

        cleaning_after = validate_success(api.get_service_visit(cleaning["id"], DISPATCHER), 200)
        assert cleaning_after["status"] == "CANCELLED", (
            "cascade link 2, caused by the PAUSED transition")

    def test_visit_cancellation_reverts_linked_order_and_spares_billable(self, api):
        """PRD §3.1: "Third — caused by each visit cancellation — any
        SupplyOrder whose `fulfillment_visit_id` pointed at a cancelled visit
        and whose status is `PLACED` reverts to `DRAFT` with its
        `fulfillment_visit_id` cleared to null."
        PRD §3.3: "Visits of type `PREDATOR_PROOFING` or `SETUP_INSTALL` are
        never covered, and neither is any visit scheduled outside the current
        period."

        Design: Difficulty/transitive_cascade/household_suspend_cascade_depth3
        """
        household, subscription, coop, install_visit, cleaning, order = \
            _suspendable_scenario(api)

        validate_success(api.suspend_household(household["id"], BILLING), 200)

        order_after = validate_success(api.get_supply_order(order["id"], DISPATCHER), 200)
        assert order_after["status"] == "DRAFT", (
            "cascade link 3, caused by the visit CANCELLED transition")
        assert order_after["fulfillment_visit_id"] is None

        install_after = validate_success(
            api.get_service_visit(install_visit["id"], DISPATCHER), 200)
        assert install_after["status"] == "COMPLETED", (
            "BILLABLE visits are untouched by the cascade")
