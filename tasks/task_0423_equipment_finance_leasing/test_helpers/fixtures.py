"""Composite setup helpers for multi-step test prerequisites.

Most interesting test claims need the system in a specific state that takes
5-15 API calls to reach (originate -> attach equipment -> book -> fund ->
bill -> pay -> begin-end-of-term -> elect -> exercise -> ...). These helpers
encapsulate those preambles so tests focus on assertions.

All helpers use get_success_data() (lenient validator) internally so a setup
failure surfaces as a clear "Setup failed" error rather than a confusing
assertion failure. X-User-ID is opaque in this PRD (§2.1), so the shared
role headers in TEST_USERS are used throughout; the only identity that matters
is the credit-application submitter vs approver split (segregation of duties,
PRD §2.10), handled by the distinct analyst headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_lessor_payload,
    create_vendor_payload,
    create_credit_application_payload,
    approve_application_payload,
    create_lease_payload,
    create_equipment_payload,
    book_lease_payload,
    set_clock_payload,
    create_invoice_payload,
    create_payment_payload,
    create_eot_election_payload,
    exercise_election_payload,
)
from .test_users import TEST_USERS


# Role-header shortcuts.
ANALYST = TEST_USERS["credit_analyst_headers"]        # analyst-1 (submitter)
ANALYST2 = TEST_USERS["credit_analyst_2_headers"]     # analyst-2 (approver)
OFFICER = TEST_USERS["funding_officer_headers"]
SERVICER = TEST_USERS["servicer_headers"]
ASSET_MGR = TEST_USERS["asset_manager_headers"]


# ─── Tier 0: primitives ────────────────────────────────────────────────
def create_lessor(**overrides):
    """Create a Lessor. Returns the lessor dict."""
    res = api_client.create_lessor(create_lessor_payload(**overrides), OFFICER)
    return get_success_data(res)


def set_clock(lessor_id, to_iso8601):
    """Advance the lessor's logical clock. Returns the lessor dict."""
    res = api_client.set_clock(lessor_id, set_clock_payload(to_iso8601), OFFICER)
    return get_success_data(res)


def create_approved_vendor(lessor_id, **overrides):
    """Create a Vendor and move it to APPROVED. Returns the vendor dict."""
    vendor = get_success_data(
        api_client.create_vendor(lessor_id, create_vendor_payload(**overrides), OFFICER)
    )
    return get_success_data(api_client.approve_vendor(lessor_id, vendor["id"], OFFICER))


def create_pending_vendor(lessor_id, **overrides):
    """Create a Vendor left in PENDING. Returns the vendor dict."""
    return get_success_data(
        api_client.create_vendor(lessor_id, create_vendor_payload(**overrides), OFFICER)
    )


# ─── Tier 1: credit application -> approved lessee ──────────────────────
def create_approved_lessee(lessor_id, approved_amount_cents=1_000_000,
                           requested_amount_cents=None, credit_score=760):
    """Run a credit application through DRAFT -> SUBMITTED -> APPROVED (by a
    different analyst, satisfying segregation of duties) and return the minted
    lessee dict. The application is submitted by analyst-1 and approved by
    analyst-2."""
    if requested_amount_cents is None:
        requested_amount_cents = approved_amount_cents
    app = get_success_data(api_client.create_credit_application(
        lessor_id,
        create_credit_application_payload(
            requested_amount_cents=requested_amount_cents, credit_score=credit_score),
        ANALYST))
    api_client.submit_credit_application(lessor_id, app["id"], ANALYST)
    api_client.approve_credit_application(
        lessor_id, app["id"], approve_application_payload(approved_amount_cents), ANALYST2)
    lessees = get_success_data(api_client.list_lessees(
        lessor_id, OFFICER, params={"credit_application_id": app["id"]}))
    return lessees[0]


def create_submitted_application(lessor_id, requested_amount_cents=500_000,
                                 credit_score=760, submitter=None):
    """Create + submit a credit application (status SUBMITTED). Returns the app
    dict. The submitter defaults to analyst-1."""
    headers = submitter or ANALYST
    app = get_success_data(api_client.create_credit_application(
        lessor_id,
        create_credit_application_payload(
            requested_amount_cents=requested_amount_cents, credit_score=credit_score),
        headers))
    return get_success_data(
        api_client.submit_credit_application(lessor_id, app["id"], headers))


# ─── Tier 2: lease origination / equipment ─────────────────────────────
def create_lease(lessor_id, lessee_id, vendor_id, **lease_overrides):
    """Originate a lease (ORIGINATION / PENDING_FUNDING). Returns the lease dict."""
    return get_success_data(api_client.create_lease(
        lessor_id, lessee_id,
        create_lease_payload(vendor_id, **lease_overrides), OFFICER))


def attach_equipment(lessor_id, lease_id, serial_number, original_cost_cents=500_000,
                     **overrides):
    """Attach an EquipmentUnit (ON_LEASE). Returns the unit dict."""
    return get_success_data(api_client.attach_equipment(
        lessor_id, lease_id,
        create_equipment_payload(serial_number, original_cost_cents, **overrides),
        OFFICER))


def book_lease(lessor_id, lease_id, expected_version):
    """Book a lease (ORIGINATION -> BOOKED). Returns the booked lease dict."""
    return get_success_data(api_client.book_lease(
        lessor_id, lease_id, book_lease_payload(expected_version), OFFICER))


def fund_lease(lessor_id, lease_id):
    """Fund a BOOKED lease (-> FUNDED, auto ACTIVE). Returns the lease dict."""
    return get_success_data(api_client.fund_lease(lessor_id, lease_id, OFFICER))


# ─── Tier 3: full origination shortcuts ────────────────────────────────
def setup_booked_lease(lessor_id=None, lessee_id=None, vendor_id=None,
                       serial_number="SN-1", original_cost_cents=500_000,
                       approved_amount_cents=1_000_000, **lease_overrides):
    """End-to-end through BOOKED (not yet funded).

    Creates lessor (if not supplied), approved vendor, approved lessee, lease,
    one attached unit, then books. Returns dict with keys:
    lessor_id, vendor_id, lessee_id, lease, unit.
    """
    if lessor_id is None:
        lessor_id = create_lessor()["id"]
    if vendor_id is None:
        vendor_id = create_approved_vendor(lessor_id)["id"]
    if lessee_id is None:
        lessee_id = create_approved_lessee(
            lessor_id, approved_amount_cents=approved_amount_cents)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id, **lease_overrides)
    unit = attach_equipment(lessor_id, lease["id"], serial_number, original_cost_cents)
    booked = book_lease(lessor_id, lease["id"], lease["version"])
    return {
        "lessor_id": lessor_id,
        "vendor_id": vendor_id,
        "lessee_id": lessee_id,
        "lease": booked,
        "unit": unit,
    }


def setup_active_lease(lessor_id=None, lessee_id=None, vendor_id=None,
                       serial_number="SN-1", original_cost_cents=500_000,
                       approved_amount_cents=1_000_000, **lease_overrides):
    """End-to-end through ACTIVE (booked + funded).

    Returns dict: lessor_id, vendor_id, lessee_id, lease (ACTIVE), unit.
    """
    ctx = setup_booked_lease(
        lessor_id=lessor_id, lessee_id=lessee_id, vendor_id=vendor_id,
        serial_number=serial_number, original_cost_cents=original_cost_cents,
        approved_amount_cents=approved_amount_cents, **lease_overrides)
    ctx["lease"] = fund_lease(ctx["lessor_id"], ctx["lease"]["id"])
    return ctx


# ─── Tier 4: billing / installment settlement ──────────────────────────
def list_scheduled_lines(lessor_id, lease_id):
    """Return the lease's ScheduleLine rows in SCHEDULED status (list)."""
    return get_success_data(api_client.list_schedule_lines(
        lessor_id, lease_id, SERVICER, params={"status": "SCHEDULED"}))


def bill_line(lessor_id, lease_id, schedule_line_id):
    """Create an Invoice for a schedule line. Returns the invoice dict."""
    return get_success_data(api_client.create_invoice(
        lessor_id, lease_id, create_invoice_payload(schedule_line_id), SERVICER))


def pay_invoice_full(lessor_id, invoice_id, amount_cents):
    """Record a payment covering the invoice. Returns the payment dict."""
    return get_success_data(api_client.create_payment(
        lessor_id, invoice_id, create_payment_payload(amount_cents), SERVICER))


def pay_all_scheduled_installments(lessor_id, lease_id):
    """Bill and fully pay every remaining SCHEDULED installment on the lease so
    paid_installment_count reaches term_months - advance_payment_count.

    Returns the refreshed lease dict.
    """
    while True:
        scheduled = list_scheduled_lines(lessor_id, lease_id)
        if not scheduled:
            break
        line = scheduled[0]
        inv = bill_line(lessor_id, lease_id, line["id"])
        pay_invoice_full(lessor_id, inv["id"], inv["total_due_cents"])
    return get_success_data(api_client.get_lease(lessor_id, lease_id, SERVICER))


def begin_end_of_term(lessor_id, lease_id):
    """Move an ACTIVE lease into END_OF_TERM. Returns the lease dict."""
    return get_success_data(
        api_client.begin_end_of_term(lessor_id, lease_id, SERVICER))


def setup_end_of_term_lease(lessor_id=None, serial_number="SN-1",
                            original_cost_cents=500_000, term_months=1,
                            equipment_cost_cents=500_000, monthly_rate_factor_bps=2000,
                            approved_amount_cents=1_000_000, clock_iso=None,
                            **lease_overrides):
    """End-to-end through END_OF_TERM: active lease -> bill+pay every installment
    -> begin-end-of-term.

    Returns dict: lessor_id, vendor_id, lessee_id, lease (END_OF_TERM), unit.
    """
    if lessor_id is None:
        lessor_id = create_lessor()["id"]
    if clock_iso is not None:
        set_clock(lessor_id, clock_iso)
    ctx = setup_active_lease(
        lessor_id=lessor_id, serial_number=serial_number,
        original_cost_cents=original_cost_cents,
        equipment_cost_cents=equipment_cost_cents, term_months=term_months,
        monthly_rate_factor_bps=monthly_rate_factor_bps,
        approved_amount_cents=approved_amount_cents, **lease_overrides)
    pay_all_scheduled_installments(lessor_id, ctx["lease"]["id"])
    ctx["lease"] = begin_end_of_term(lessor_id, ctx["lease"]["id"])
    return ctx


# ─── Tier 5: end-of-term elections / remarketing ───────────────────────
def elect(lessor_id, lease_id, election, **overrides):
    """Record an end-of-term election (status ELECTED). Returns the election dict."""
    return get_success_data(api_client.create_eot_election(
        lessor_id, lease_id, create_eot_election_payload(election, **overrides),
        SERVICER))


def exercise(lessor_id, lease_id, election_id, **overrides):
    """Exercise an ELECTED option. Returns the election dict."""
    return get_success_data(api_client.exercise_eot_election(
        lessor_id, lease_id, election_id,
        exercise_election_payload(**overrides), SERVICER))


def setup_returned_unit(lessor_id=None, serial_number="SN-1",
                        original_cost_cents=500_000, equipment_cost_cents=500_000,
                        clock_iso=None):
    """Full chain through a RETURNED unit: end-of-term FMV term-1 lease ->
    RETURN election exercised -> equipment returned.

    Returns dict: lessor_id, lease, unit (RETURNED), election.
    """
    ctx = setup_end_of_term_lease(
        lessor_id=lessor_id, serial_number=serial_number,
        original_cost_cents=original_cost_cents,
        equipment_cost_cents=equipment_cost_cents, term_months=1,
        clock_iso=clock_iso)
    election = elect(ctx["lessor_id"], ctx["lease"]["id"], "RETURN")
    exercise(ctx["lessor_id"], ctx["lease"]["id"], election["id"])
    unit = get_success_data(api_client.return_equipment(
        ctx["lessor_id"], ctx["unit"]["id"], ASSET_MGR))
    ctx["unit"] = unit
    ctx["election"] = election
    return ctx


def setup_listed_unit(lessor_id=None, serial_number="SN-1",
                      original_cost_cents=500_000, equipment_cost_cents=500_000):
    """RETURNED unit advanced to LISTED. Returns dict: lessor_id, lease, unit."""
    ctx = setup_returned_unit(
        lessor_id=lessor_id, serial_number=serial_number,
        original_cost_cents=original_cost_cents,
        equipment_cost_cents=equipment_cost_cents)
    ctx["unit"] = get_success_data(api_client.list_equipment(
        ctx["lessor_id"], ctx["unit"]["id"], ASSET_MGR))
    return ctx
