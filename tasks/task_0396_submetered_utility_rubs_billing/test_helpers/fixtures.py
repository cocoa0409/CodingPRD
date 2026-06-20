"""Composite setup helpers.

These encapsulate the multi-step API sequences that most test claims require to
reach an interesting state (a statement issued, a dispute under review, a
delinquent statement, etc.). Every fixture builds its preconditions from scratch
using only PRD-declared endpoints, because the server database is empty at the
start of every test.

Setup calls use get_success_data() (lenient) so a setup failure surfaces clearly.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_tenant_headers
from .factories import (
    create_property_payload,
    create_utility_payload,
    create_unit_payload,
    create_meter_payload,
    assign_meter_payload,
    create_lease_payload,
    create_vendor_bill_payload,
    create_billing_cycle_payload,
    create_meter_read_payload,
)

PM = TEST_USERS["property_manager_headers"]
TECH = TEST_USERS["meter_tech_headers"]

PERIOD = "2026-06"
PERIOD_START = "2026-06-01T00:00:00Z"
PERIOD_END = "2026-06-30T00:00:00Z"


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def set_clock(iso, headers=PM):
    return get_success_data(api_client.set_clock(iso, headers))


# --------------------------------------------------------------------------- #
# Tier 1 / 2: bootstrap building blocks
# --------------------------------------------------------------------------- #
def create_property(**overrides):
    return get_success_data(
        api_client.create_property(create_property_payload(**overrides), PM)
    )


def create_utility(property_id, **overrides):
    return get_success_data(
        api_client.create_utility(create_utility_payload(property_id, **overrides), PM)
    )


def create_unit(property_id, **overrides):
    return get_success_data(
        api_client.create_unit(create_unit_payload(property_id, **overrides), PM)
    )


def create_meter(property_id, utility_id, **overrides):
    return get_success_data(
        api_client.create_meter(create_meter_payload(property_id, utility_id, **overrides), PM)
    )


def create_and_assign_meter(property_id, utility_id, unit_id, serial_number, effective_from=PERIOD_START, **assign_overrides):
    meter = create_meter(property_id, utility_id, serial_number=serial_number)
    get_success_data(
        api_client.assign_meter(
            meter["id"],
            assign_meter_payload(unit_id, effective_from=effective_from, **assign_overrides),
            PM,
        )
    )
    return get_success_data(api_client.get_meter(meter["id"], PM))


def create_active_lease(unit_id, property_id, tenant_user_id, **overrides):
    lease = get_success_data(
        api_client.create_lease(
            create_lease_payload(unit_id, property_id, tenant_user_id, **overrides), PM
        )
    )
    get_success_data(api_client.activate_lease(lease["id"], PM))
    return get_success_data(api_client.get_lease(lease["id"], PM))


def create_vendor_bill(property_id, utility_id, total_cost_cents=30000, period_label=PERIOD):
    return get_success_data(
        api_client.create_vendor_bill(
            create_vendor_bill_payload(
                property_id, utility_id,
                total_cost_cents=total_cost_cents, period_label=period_label,
            ),
            PM,
        )
    )


def create_approved_vendor_bill(property_id, utility_id, total_cost_cents=30000, period_label=PERIOD):
    vb = create_vendor_bill(property_id, utility_id, total_cost_cents, period_label)
    return get_success_data(api_client.approve_vendor_bill(vb["id"], PM))


def open_billing_cycle(property_id, utility_id, vendor_bill_id, **overrides):
    return get_success_data(
        api_client.create_billing_cycle(
            create_billing_cycle_payload(property_id, utility_id, vendor_bill_id, **overrides),
            PM,
        )
    )


def submit_and_validate_read(meter_id, property_id, reading_value, period_label=PERIOD):
    """Create -> submit -> validate a read; returns the validated read."""
    read = get_success_data(
        api_client.create_meter_read(
            create_meter_read_payload(
                meter_id, property_id, reading_value=reading_value, period_label=period_label
            ),
            TECH,
        )
    )
    get_success_data(api_client.submit_meter_read(read["id"], headers=TECH))
    get_success_data(api_client.validate_meter_read(read["id"], PM))
    return get_success_data(api_client.get_meter_read(read["id"], PM))


# --------------------------------------------------------------------------- #
# Tier 3 / 5: end-to-end statement fixtures
# --------------------------------------------------------------------------- #
def setup_single_rubs_statement(
    total_cost_cents=7059,
    common_area_pct=0.00,
    recovery_cap_pct=0.85,
    monthly_admin_fee_cents=0,
    state_code="CA",
    tenant_user_id="tenant-A",
    occupant_count=1,
    move_in_date=PERIOD_START,
    issue_clock="2026-06-15T00:00:00Z",
):
    """Full single-unit RUBS chain ending in one ISSUED, UNPAID statement.

    With total 7059, common_area_pct 0, recovery_cap 0.85 -> recoverable 6000,
    single unit -> utility_charge_cents 6000, admin_fee 0 -> total_due 6000.
    Returns dict with property, utility, unit, lease, vendor_bill, cycle, statement.
    """
    set_clock(issue_clock)
    prop = create_property(
        state_code=state_code,
        recovery_cap_pct=recovery_cap_pct,
        common_area_pct=common_area_pct,
    )
    util = create_utility(
        prop["id"], allocation_method="RUBS",
        monthly_admin_fee_cents=monthly_admin_fee_cents,
    )
    unit = create_unit(prop["id"], unit_number="R1")
    lease = create_active_lease(
        unit["id"], prop["id"], tenant_user_id,
        occupant_count=occupant_count, move_in_date=move_in_date,
    )
    vb = create_approved_vendor_bill(prop["id"], util["id"], total_cost_cents=total_cost_cents)
    cycle = open_billing_cycle(prop["id"], util["id"], vb["id"])
    get_success_data(api_client.lock_reads(cycle["id"], PM))
    get_success_data(api_client.allocate_cycle(cycle["id"], PM))
    get_success_data(api_client.issue_statements(cycle["id"], PM))
    statements = get_success_data(
        api_client.list_statements(PM, params={"billing_cycle_id": cycle["id"]})
    )
    statement = statements[0]
    return {
        "property": prop,
        "utility": util,
        "unit": unit,
        "lease": lease,
        "vendor_bill": get_success_data(api_client.get_vendor_bill(vb["id"], PM)),
        "cycle": get_success_data(api_client.get_billing_cycle(cycle["id"], PM)),
        "statement": get_success_data(api_client.get_statement(statement["id"], PM)),
        "tenant_user_id": tenant_user_id,
    }


def setup_single_consumption_statement(
    total_cost_cents=50000,
    common_area_pct=0.00,
    recovery_cap_pct=0.85,
    reading_value=100,
    state_code="CA",
    tenant_user_id="tenant-C",
    issue_clock="2026-06-15T00:00:00Z",
):
    """Full single-unit CONSUMPTION chain ending in one ISSUED statement.

    A single meter + validated read carries all the consumption, so the lone unit
    receives the entire recoverable pool as utility_charge_cents.
    Returns dict with property, utility, unit, lease, meter, vendor_bill, cycle, statement.
    """
    set_clock(issue_clock)
    prop = create_property(
        state_code=state_code,
        recovery_cap_pct=recovery_cap_pct,
        common_area_pct=common_area_pct,
    )
    util = create_utility(prop["id"], allocation_method="CONSUMPTION", monthly_admin_fee_cents=0)
    unit = create_unit(prop["id"], unit_number="C1")
    lease = create_active_lease(unit["id"], prop["id"], tenant_user_id)
    meter = create_and_assign_meter(prop["id"], util["id"], unit["id"], "SC1")
    vb = create_approved_vendor_bill(prop["id"], util["id"], total_cost_cents=total_cost_cents)
    cycle = open_billing_cycle(prop["id"], util["id"], vb["id"])
    submit_and_validate_read(meter["id"], prop["id"], reading_value=reading_value)
    get_success_data(api_client.lock_reads(cycle["id"], PM))
    get_success_data(api_client.allocate_cycle(cycle["id"], PM))
    get_success_data(api_client.issue_statements(cycle["id"], PM))
    statements = get_success_data(
        api_client.list_statements(PM, params={"billing_cycle_id": cycle["id"]})
    )
    statement = statements[0]
    return {
        "property": prop,
        "utility": util,
        "unit": unit,
        "lease": lease,
        "meter": get_success_data(api_client.get_meter(meter["id"], PM)),
        "vendor_bill": get_success_data(api_client.get_vendor_bill(vb["id"], PM)),
        "cycle": get_success_data(api_client.get_billing_cycle(cycle["id"], PM)),
        "statement": get_success_data(api_client.get_statement(statement["id"], PM)),
        "tenant_user_id": tenant_user_id,
    }


def setup_two_unit_consumption_cycle(
    consumption_a=2,
    consumption_b=1,
    total_cost_cents=11765,
    issue_clock="2026-06-15T00:00:00Z",
):
    """CONSUMPTION property with two metered units; allocates + issues statements.

    With total 11765, common_area 0.10, recovery_cap 0.85 -> recoverable 10000.
    Unit A consumption `consumption_a`, unit B `consumption_b`.
    Returns dict with property, utility, unit_a, unit_b, cycle, statement_a, statement_b.
    """
    set_clock(issue_clock)
    prop = create_property(state_code="CA", recovery_cap_pct=0.85, common_area_pct=0.10)
    util = create_utility(prop["id"], allocation_method="CONSUMPTION")
    unit_a = create_unit(prop["id"], unit_number="A")
    unit_b = create_unit(prop["id"], unit_number="B")
    create_active_lease(unit_a["id"], prop["id"], "tA", occupant_count=1)
    create_active_lease(unit_b["id"], prop["id"], "tB", occupant_count=1)
    meter_a = create_and_assign_meter(prop["id"], util["id"], unit_a["id"], "MA")
    meter_b = create_and_assign_meter(prop["id"], util["id"], unit_b["id"], "MB")
    vb = create_approved_vendor_bill(prop["id"], util["id"], total_cost_cents=total_cost_cents)
    cycle = open_billing_cycle(prop["id"], util["id"], vb["id"])
    submit_and_validate_read(meter_a["id"], prop["id"], reading_value=consumption_a)
    submit_and_validate_read(meter_b["id"], prop["id"], reading_value=consumption_b)
    get_success_data(api_client.lock_reads(cycle["id"], PM))
    get_success_data(api_client.allocate_cycle(cycle["id"], PM))
    get_success_data(api_client.issue_statements(cycle["id"], PM))
    statements = get_success_data(
        api_client.list_statements(PM, params={"billing_cycle_id": cycle["id"]})
    )
    by_unit = {s["unit_id"]: s for s in statements}
    return {
        "property": prop,
        "utility": util,
        "unit_a": unit_a,
        "unit_b": unit_b,
        "cycle": get_success_data(api_client.get_billing_cycle(cycle["id"], PM)),
        "statement_a": by_unit[unit_a["id"]],
        "statement_b": by_unit[unit_b["id"]],
    }


def setup_two_unit_rubs_cycle(
    occupant_a=3,
    occupant_b=2,
    total_cost_cents=11765,
    issue_clock="2026-06-15T00:00:00Z",
):
    """RUBS property with two occupied units; allocates + issues statements.

    With total 11765, common_area 0.10, recovery_cap 0.85 -> recoverable 10000.
    Unit A occupant_count `occupant_a`, unit B `occupant_b`.
    Returns dict with property, utility, unit_a, unit_b, cycle, statement_a, statement_b.
    """
    set_clock(issue_clock)
    prop = create_property(state_code="CA", recovery_cap_pct=0.85, common_area_pct=0.10)
    util = create_utility(prop["id"], allocation_method="RUBS")
    unit_a = create_unit(prop["id"], unit_number="A")
    unit_b = create_unit(prop["id"], unit_number="B")
    create_active_lease(unit_a["id"], prop["id"], "rA", occupant_count=occupant_a)
    create_active_lease(unit_b["id"], prop["id"], "rB", occupant_count=occupant_b)
    vb = create_approved_vendor_bill(prop["id"], util["id"], total_cost_cents=total_cost_cents)
    cycle = open_billing_cycle(prop["id"], util["id"], vb["id"])
    get_success_data(api_client.lock_reads(cycle["id"], PM))
    get_success_data(api_client.allocate_cycle(cycle["id"], PM))
    get_success_data(api_client.issue_statements(cycle["id"], PM))
    statements = get_success_data(
        api_client.list_statements(PM, params={"billing_cycle_id": cycle["id"]})
    )
    by_unit = {s["unit_id"]: s for s in statements}
    return {
        "property": prop,
        "utility": util,
        "unit_a": unit_a,
        "unit_b": unit_b,
        "cycle": get_success_data(api_client.get_billing_cycle(cycle["id"], PM)),
        "statement_a": by_unit[unit_a["id"]],
        "statement_b": by_unit[unit_b["id"]],
    }


# --------------------------------------------------------------------------- #
# Tier 4: threshold / late-fee targeting
# --------------------------------------------------------------------------- #
def setup_statement_for_late_fee(target_balance_cents, state_code="CA", issue_clock="2026-06-15T00:00:00Z"):
    """Issue a single RUBS statement whose balance_due_cents == target_balance_cents.

    With common_area_pct 0 and recovery_cap 0.85 and a single unit, the whole
    recoverable pool lands on one statement. We pick total_cost so
    floor(total*0.85) == target_balance_cents (target/0.85 rounded so the floor
    lands exactly on target). Returns the issued statement bundle.
    """
    # choose total such that floor(total * 0.85) == target_balance_cents
    total = -(-target_balance_cents * 100 // 85)  # ceil(target/0.85)
    bundle = setup_single_rubs_statement(
        total_cost_cents=total,
        common_area_pct=0.00,
        recovery_cap_pct=0.85,
        state_code=state_code,
        issue_clock=issue_clock,
    )
    assert bundle["statement"]["balance_due_cents"] == target_balance_cents, (
        f"late-fee fixture expected balance {target_balance_cents}, "
        f"got {bundle['statement']['balance_due_cents']}"
    )
    return bundle


def setup_delinquent_statement(target_balance_cents=20000, issue_clock="2026-06-15T00:00:00Z"):
    """Issue a statement then advance the clock past due+grace and assess a late fee.

    Issued 2026-06-15 -> due 2026-07-06 -> grace boundary 2026-07-11 ->
    advance to 2026-07-15 and assess. Returns the bundle plus the DELINQUENT
    statement under key 'statement'.
    """
    bundle = setup_statement_for_late_fee(target_balance_cents, issue_clock=issue_clock)
    set_clock("2026-07-15T00:00:00Z")
    get_success_data(api_client.assess_late_fee(bundle["statement"]["id"], PM))
    bundle["statement"] = get_success_data(
        api_client.get_statement(bundle["statement"]["id"], PM)
    )
    return bundle


# --------------------------------------------------------------------------- #
# Dispute fixtures
# --------------------------------------------------------------------------- #
def setup_dispute_under_review(
    credit_amount_cents=0,
    reason="HIGH_READING",
    requested_re_read=False,
    total_cost_cents=7059,
    tenant_user_id="tenant-D",
):
    """Issue a statement, open a dispute as its owning tenant, start review.

    Returns dict with the issued bundle plus 'dispute' (UNDER_REVIEW).
    """
    bundle = setup_single_rubs_statement(
        total_cost_cents=total_cost_cents, tenant_user_id=tenant_user_id
    )
    tenant_headers = make_tenant_headers(tenant_user_id)
    dispute_payload = {"reason": reason, "requested_re_read": requested_re_read}
    if credit_amount_cents:
        dispute_payload["credit_amount_cents"] = credit_amount_cents
    dispute = get_success_data(
        api_client.open_dispute(bundle["statement"]["id"], dispute_payload, tenant_headers)
    )
    get_success_data(api_client.start_review(dispute["id"], PM))
    bundle["dispute"] = get_success_data(api_client.get_dispute(dispute["id"], PM))
    return bundle


def setup_open_dispute(reason="DOUBLE_BILLED", total_cost_cents=7059, tenant_user_id="tenant-O"):
    """Issue a statement and open a dispute (OPEN, review NOT started)."""
    bundle = setup_single_rubs_statement(
        total_cost_cents=total_cost_cents, tenant_user_id=tenant_user_id
    )
    tenant_headers = make_tenant_headers(tenant_user_id)
    dispute = get_success_data(
        api_client.open_dispute(bundle["statement"]["id"], {"reason": reason}, tenant_headers)
    )
    bundle["dispute"] = get_success_data(api_client.get_dispute(dispute["id"], PM))
    return bundle


# --------------------------------------------------------------------------- #
# Payment fixtures
# --------------------------------------------------------------------------- #
def setup_statement_with_payment(amount_cents, total_cost_cents=7059, tenant_user_id="tenant-P"):
    """Issue a statement and post one payment of amount_cents as the owning tenant.

    Returns the bundle plus 'payment' and the refreshed 'statement'.
    """
    bundle = setup_single_rubs_statement(
        total_cost_cents=total_cost_cents, tenant_user_id=tenant_user_id
    )
    tenant_headers = make_tenant_headers(tenant_user_id)
    stmt = bundle["statement"]
    payment = get_success_data(
        api_client.post_payment(
            stmt["id"],
            {"amount_cents": amount_cents, "expected_statement_version": stmt["version"]},
            tenant_headers,
        )
    )
    bundle["payment"] = get_success_data(api_client.get_payment(payment["id"], PM))
    bundle["statement"] = get_success_data(api_client.get_statement(stmt["id"], PM))
    return bundle
