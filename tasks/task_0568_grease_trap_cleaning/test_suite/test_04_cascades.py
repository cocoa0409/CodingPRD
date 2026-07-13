"""Transitive reconciliation cascades: WorkOrder->Equipment->Site->Customer (depth 3)
and Equipment->Site->Customer (depth 2)."""
from test_helpers import (
    validate_success,
    TEST_USERS, make_technician_headers, get_success_data,
)
from test_helpers.fixtures import (
    setup_suspended_customer_overdue_equipment, new_technician, new_work_order,
    dispatch_work_order, start_work_order, file_manifest,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─────────────── Depth-3 cascade on WorkOrder completion ───────────────
def _complete_service_on_suspended_customer(freq_days=30):
    ctx = setup_suspended_customer_overdue_equipment(nominal_frequency_days=freq_days)
    tech = new_technician("BASIC")
    wo = new_work_order(ctx["site_id"], ctx["eq_id"], planned_start="2026-05-01T08:00:00Z",
                        planned_end="2026-05-01T10:00:00Z")
    dispatch_work_order(wo["id"], tech["id"])
    start_work_order(wo["id"], tech["id"])
    file_manifest(wo["id"], tech["id"], disposal_facility_permit="FAC-4", volume_gallons=60)
    get_success_data(api_client.complete_work_order(
        wo["id"], {"actual_hours": 2}, make_technician_headers(tech["id"])))
    return ctx


def test_completion_reschedules_equipment_and_regrades_site(api):
    """PRD §3.3: "the equipment's `last_service_at` is set to that `completed_at` and its
    `next_service_due_at` recomputed; then the equipment's `service_state` and the owning
    site's `compliance_status` and `projected_compliance_status` are re-graded".

    Design: Difficulty/transitive_cascade/complete_grease_trap_cascade_depth3
    """
    ctx = _complete_service_on_suspended_customer(freq_days=30)
    eq = validate_success(api.get_equipment(ctx["eq_id"], DISPATCHER), 200)
    assert eq["next_service_due_at"].startswith("2026-05-31"), \
        "next_service_due_at = completed_at (2026-05-01) + 30 days"
    site = validate_success(api.get_site(ctx["site_id"], COMPLIANCE), 200)
    assert site["compliance_status"] == "COMPLIANT", \
        "the now-serviced equipment re-grades the site COMPLIANT"


def test_completion_lifts_customer_suspension(api):
    """PRD §3.3: "then, if the owning customer is `SUSPENDED` and now has no `NON_COMPLIANT`
    site, that customer's `account_status` returns to `ACTIVE`."

    Design: Difficulty/transitive_cascade/complete_grease_trap_cascade_depth3
    """
    ctx = _complete_service_on_suspended_customer(freq_days=30)
    # The overdue equipment had suspended the customer at create time; servicing it lifts that.
    cust = validate_success(api.get_customer(ctx["cust_id"], ADMIN), 200)
    assert cust["account_status"] == "ACTIVE", \
        "servicing the sole overdue equipment must lift the cascade-driven suspension"


# ─────────────── Depth-2 cascade on Equipment decommission ───────────────
def test_decommission_regrades_site_to_compliant(api):
    """PRD §2.8: "A customer with at least one owned site graded `NON_COMPLIANT` is moved to
    `SUSPENDED`; a `SUSPENDED` customer whose owned sites are all no longer `NON_COMPLIANT`
    is moved back to `ACTIVE`."
    PRD §3.2: "A site's compliance grade is a threshold over its `ACTIVE` equipment only —
    decommissioned equipment is excluded."

    Design: Difficulty/transitive_cascade/decommission_equipment_cascade_depth2
    """
    ctx = setup_suspended_customer_overdue_equipment(nominal_frequency_days=30)
    res = api.decommission_equipment(ctx["eq_id"], ADMIN)
    eq = validate_success(res, 200)
    assert eq["status"] == "DECOMMISSIONED"
    site = validate_success(api.get_site(ctx["site_id"], COMPLIANCE), 200)
    assert site["compliance_status"] == "COMPLIANT", \
        "excluding the decommissioned overdue equipment re-grades the site COMPLIANT"


def test_decommission_lifts_customer_suspension(api):
    """PRD §2.8: "a `SUSPENDED` customer whose owned sites are all no longer `NON_COMPLIANT`
    is moved back to `ACTIVE`."

    Design: Difficulty/transitive_cascade/decommission_equipment_cascade_depth2
    """
    ctx = setup_suspended_customer_overdue_equipment(nominal_frequency_days=30)
    validate_success(api.decommission_equipment(ctx["eq_id"], ADMIN), 200)
    cust = validate_success(api.get_customer(ctx["cust_id"], ADMIN), 200)
    assert cust["account_status"] == "ACTIVE", \
        "decommissioning the sole overdue equipment lifts the customer suspension"
