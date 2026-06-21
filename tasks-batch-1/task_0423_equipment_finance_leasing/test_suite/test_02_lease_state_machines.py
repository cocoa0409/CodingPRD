"""State machines: credit-application revision cycle, lease parallel dimensions,
funding cascade, and transition lockdowns.

Difficulty queue: non_linear_state_machine.
Corner queue: state_machines, cross_cutting (OCC, funding cascade).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_lessor,
    create_approved_vendor,
    create_approved_lessee,
    create_lease,
    attach_equipment,
    set_clock,
    setup_active_lease,
    setup_end_of_term_lease,
    elect,
    exercise,
    TEST_USERS,
)

ANALYST = TEST_USERS["credit_analyst_headers"]      # analyst-1
ANALYST2 = TEST_USERS["credit_analyst_2_headers"]   # analyst-2
OFFICER = TEST_USERS["funding_officer_headers"]
SERVICER = TEST_USERS["servicer_headers"]


# ─── non_linear_state_machine / credit_application_revision_cycle ──────
def test_credit_application_revision_cycle_increments_count(api):
    """PRD §3.2: "From `RETURNED_FOR_INFO`, revising it returns it to `DRAFT`;
    revision increments `revision_count` by one and clears `submitted_by_user_id`
    back to empty, so the next submission re-stamps a fresh submitter."

    A submitted application taken through SUBMITTED -> RETURNED_FOR_INFO -> DRAFT
    (revise) -> SUBMITTED has revision_count == 1 and status SUBMITTED.

    Design: Difficulty/non_linear_state_machine/credit_application_revision_cycle
    """
    lessor_id = create_lessor()["id"]
    app = get_success_data(api.create_credit_application(
        lessor_id, {"applicant_legal_name": "Cust", "requested_amount_cents": 500_000,
                    "credit_score": 700}, ANALYST))
    api.submit_credit_application(lessor_id, app["id"], ANALYST)
    api.return_credit_application(lessor_id, app["id"], ANALYST2)
    api.revise_credit_application(lessor_id, app["id"], ANALYST)
    resubmitted = validate_success(
        api.submit_credit_application(lessor_id, app["id"], ANALYST), 200)
    assert resubmitted["status"] == "SUBMITTED", f"got {resubmitted['status']}"
    assert resubmitted["revision_count"] == 1, f"got {resubmitted['revision_count']}"


def test_revise_clears_submitter_allowing_original_to_resubmit(api):
    """PRD §3.2: "From `RETURNED_FOR_INFO`, revising it returns it to `DRAFT`;
    revision increments `revision_count` by one and clears `submitted_by_user_id`
    back to empty, so the next submission re-stamps a fresh submitter."

    After a full revision loop the application is back in SUBMITTED (re-stamped),
    confirming the RETURNED_FOR_INFO -> DRAFT -> SUBMITTED cycle is traversable
    more than once and revision_count tracks the passes.

    Design: Difficulty/non_linear_state_machine/credit_application_revision_cycle
    """
    lessor_id = create_lessor()["id"]
    app = get_success_data(api.create_credit_application(
        lessor_id, {"applicant_legal_name": "Cust", "requested_amount_cents": 500_000,
                    "credit_score": 700}, ANALYST))
    api.submit_credit_application(lessor_id, app["id"], ANALYST)
    # First loop.
    api.return_credit_application(lessor_id, app["id"], ANALYST2)
    api.revise_credit_application(lessor_id, app["id"], ANALYST)
    api.submit_credit_application(lessor_id, app["id"], ANALYST)
    # Second loop.
    api.return_credit_application(lessor_id, app["id"], ANALYST2)
    api.revise_credit_application(lessor_id, app["id"], ANALYST)
    final = validate_success(
        api.submit_credit_application(lessor_id, app["id"], ANALYST), 200)
    assert final["status"] == "SUBMITTED"
    assert final["revision_count"] == 2, f"got {final['revision_count']}"


# ─── non_linear_state_machine / lease_parallel_lifecycle_and_funding ──
def test_book_advances_lifecycle_only_not_funding(api):
    """PRD §3.4: "A freshly created lease sits in `lifecycle_status` `ORIGINATION`
    and `funding_status` `PENDING_FUNDING`; these two dimensions advance
    independently."
    PRD §3.7: "A lease reaches `ACTIVE` only when **both** dimensions align: its
    `lifecycle_status` is `BOOKED` and its `funding_status` is `FUNDED`."

    Immediately after booking, lifecycle_status is BOOKED while funding_status is
    still PENDING_FUNDING — the lease is not yet ACTIVE.

    Design: Difficulty/non_linear_state_machine/lease_parallel_lifecycle_and_funding_dimensions
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "SN-400", original_cost_cents=500_000)
    booked = get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    assert booked["lifecycle_status"] == "BOOKED", f"got {booked['lifecycle_status']}"
    assert booked["funding_status"] == "PENDING_FUNDING", f"got {booked['funding_status']}"


def test_fund_completes_both_dimensions_and_auto_activates(api):
    """PRD §3.7: "A lease reaches `ACTIVE` only when **both** dimensions align: its
    `lifecycle_status` is `BOOKED` and its `funding_status` is `FUNDED`. This
    `BOOKED → ACTIVE` transition is performed automatically by the system at the
    moment funding completes — there is no separate operator action for it."

    After funding a BOOKED lease, funding_status is FUNDED and lifecycle_status has
    automatically advanced to ACTIVE.

    Design: Difficulty/non_linear_state_machine/lease_parallel_lifecycle_and_funding_dimensions
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "SN-401", original_cost_cents=500_000)
    get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    funded = get_success_data(api.fund_lease(lessor_id, lease["id"], OFFICER))
    assert funded["funding_status"] == "FUNDED", f"got {funded['funding_status']}"
    assert funded["lifecycle_status"] == "ACTIVE", f"got {funded['lifecycle_status']}"


# ─── Corner: state_machines / vendor_approve_from_approved_invalid_state ─
def test_approve_already_approved_vendor_rejected(api):
    """PRD §2.11: "that the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)".
    PRD §3.1: "An approved vendor may later be moved to `SUSPENDED`, and a suspended
    vendor may be returned to `APPROVED`".

    Approving a vendor already in APPROVED (no PENDING/SUSPENDED from-state) is an
    undefined transition and returns ERR_INVALID_STATE.

    Design: Corner/state_machines/vendor_approve_from_approved_invalid_state
    """
    lessor_id = create_lessor()["id"]
    vendor = create_approved_vendor(lessor_id)
    res = api.approve_vendor(lessor_id, vendor["id"], OFFICER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Corner: state_machines / begin_end_of_term_before_term_complete ──
def test_begin_end_of_term_before_term_paid_rejected(api):
    """PRD §3.11: "This is permitted only once the scheduled term is fully paid:
    `paid_installment_count` must be at least `term_months` minus
    `advance_payment_count` (otherwise `ERR_TERM_NOT_COMPLETE`)".

    An ACTIVE term-2 lease with zero paid installments cannot begin end-of-term.

    Design: Corner/state_machines/begin_end_of_term_before_term_complete
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=2, monthly_rate_factor_bps=2000,
        serial_number="C-SN-1")
    res = api.begin_end_of_term(ctx["lessor_id"], ctx["lease"]["id"], SERVICER)
    validate_error(res, ApiErrorId.ERR_TERM_NOT_COMPLETE.value)


# ─── Corner: state_machines / equipment_dispose_terminal_lockdown ─────
def test_disposed_unit_cannot_be_listed(api):
    """PRD §3.12: "The terminal states for an equipment unit are `SOLD` and
    `DISPOSED`."
    PRD §2.11: "that the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)".

    A unit returned then disposed is terminal; listing it returns ERR_INVALID_STATE
    and the unit remains DISPOSED.

    Design: Corner/state_machines/equipment_dispose_terminal_lockdown
    """
    from test_helpers import setup_returned_unit
    ctx = setup_returned_unit(serial_number="D-SN-1")
    asset_mgr = TEST_USERS["asset_manager_headers"]
    disposed = get_success_data(api.dispose_equipment(
        ctx["lessor_id"], ctx["unit"]["id"], asset_mgr))
    assert disposed["status"] == "DISPOSED"
    res = api.list_equipment(ctx["lessor_id"], ctx["unit"]["id"], asset_mgr)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_equipment(ctx["lessor_id"], ctx["unit"]["id"], asset_mgr))
    assert after["status"] == "DISPOSED"


# ─── Corner: state_machines / renew_election_extends_schedule_and_term ─
def test_exercise_renew_extends_term_months(api):
    """PRD §3.11: "Exercising a `RENEW` appends `renewal_months` new schedule lines
    and increases the lease's `term_months` by `renewal_months`."

    A fully-paid FMV term-1 lease at END_OF_TERM with a RENEW election of
    renewal_months 6, when exercised, advances the election to EXERCISED and raises
    term_months from 1 to 7.

    Design: Corner/state_machines/renew_election_extends_schedule_and_term
    """
    ctx = setup_end_of_term_lease(
        equipment_cost_cents=500_000, term_months=1, monthly_rate_factor_bps=2000,
        serial_number="E-SN-1")
    election = elect(ctx["lessor_id"], ctx["lease"]["id"], "RENEW", renewal_months=6)
    exercised = exercise(ctx["lessor_id"], ctx["lease"]["id"], election["id"])
    assert exercised["status"] == "EXERCISED", f"got {exercised['status']}"
    lease = get_success_data(api.get_lease(ctx["lessor_id"], ctx["lease"]["id"], SERVICER))
    assert lease["term_months"] == 7, f"got {lease['term_months']}"


# ─── Corner: state_machines / credit_application_decline_terminal ─────
def test_declined_application_cannot_be_approved(api):
    """PRD §3.2: "From `SUBMITTED`, the application resolves either to `APPROVED` or
    to `DECLINED`, and both are terminal."
    PRD §2.11: "that the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)".

    An application declined by a different analyst is terminal; approving it returns
    ERR_INVALID_STATE and it stays DECLINED.

    Design: Corner/state_machines/credit_application_decline_terminal
    """
    lessor_id = create_lessor()["id"]
    app = get_success_data(api.create_credit_application(
        lessor_id, {"applicant_legal_name": "Cust", "requested_amount_cents": 500_000,
                    "credit_score": 760}, ANALYST))
    api.submit_credit_application(lessor_id, app["id"], ANALYST)
    api.decline_credit_application(lessor_id, app["id"], ANALYST2)
    res = api.approve_credit_application(
        lessor_id, app["id"], {"approved_amount_cents": 500_000}, ANALYST2)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_credit_application(lessor_id, app["id"], ANALYST))
    assert after["status"] == "DECLINED"


# ─── Corner: state_machines / ucc_lapse_then_refile_at_boundary_allowed ─
def test_ucc_continuation_at_coverage_end_boundary_accepted(api):
    """PRD §3.7: "A filing whose coverage end is at or before the current clock has
    `LAPSED` and no longer occupies its interval; because the window is half-open,
    a continuation filed exactly at the prior filing's coverage-end instant is
    accepted."

    Funding auto-files a UCC covering [2026-01-01, 2031-01-01). With the clock at
    2031-01-01 (the half-open end), a manual continuation is accepted (status FILED).

    Design: Corner/state_machines/ucc_lapse_then_refile_at_boundary_allowed
    """
    lessor_id = create_lessor(home_state_code="NY")["id"]
    set_clock(lessor_id, "2026-01-01T00:00:00.000Z")
    ctx = setup_active_lease(
        lessor_id=lessor_id, equipment_cost_cents=500_000, term_months=60,
        monthly_rate_factor_bps=200, serial_number="H-SN-1")
    set_clock(lessor_id, "2031-01-01T00:00:00.000Z")
    res = api.create_ucc_filing(
        lessor_id, ctx["lease"]["id"], {"jurisdiction_state_code": "NY"}, OFFICER)
    new_filing = validate_success(res, 201)
    assert new_filing["status"] == "FILED", f"got {new_filing['status']}"


# ─── Corner: cross_cutting / occ_correct_version_books_successfully ────
def test_book_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.9: "A booking request must carry `expected_lease_version`, and the
    server compares it to the target lease's current `version`."
    PRD §3.4: "booking increments the lease's `version` by one".
    PRD §2.4: "an integer `version` that begins at 1".

    Booking with expected_lease_version equal to the lease's current version (1)
    succeeds, sets lifecycle_status BOOKED, and bumps version to 2.

    Design: Corner/cross_cutting/occ_correct_version_books_successfully
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "V-SN-1", original_cost_cents=500_000)
    assert lease["version"] == 1
    booked = validate_success(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER), 200)
    assert booked["lifecycle_status"] == "BOOKED"
    assert booked["version"] == 2, f"got {booked['version']}"


# ─── Corner: cross_cutting / occ_stale_version_book_rejected ──────────
def test_book_with_stale_version_rejected(api):
    """PRD §2.9: "If they do not match — meaning the lease's version has advanced
    since the client last read it ... the booking is rejected with
    `ERR_STALE_VERSION` and HTTP status 412."

    A first book bumps the lease version from 1 to 2; a second book carrying the
    stale version 1 is rejected with ERR_STALE_VERSION (412).

    Design: Corner/cross_cutting/occ_stale_version_book_rejected
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "W-SN-1", original_cost_cents=500_000)
    stale_version = lease["version"]
    get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": stale_version}, OFFICER))
    res = api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": stale_version}, OFFICER)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


# ─── Corner: cross_cutting / funding_cascade_creates_ucc_and_sales_tax ─
def test_funding_cascade_files_ucc_generates_sales_tax_and_activates(api):
    """PRD §3.7: "Funding triggers a three-deep cascade. First the system creates a
    **UCC Filing** in `PENDING` and immediately auto-files it, moving it to
    `FILED`".
    PRD §3.7: "Then it generates a `SALES_USE` **Tax Assessment** whose taxable
    base feeds the lessor's tax liability."
    PRD §3.8: "For a `SALES_USE` assessment, the taxable base is the lease's
    `equipment_cost_cents`, and the tax amount is that base multiplied by the
    lessor's `sales_tax_rate_bps`, divided by 10,000, rounded half up".

    Funding a BOOKED lease (cost 500000, NY lessor at 825 bps) yields a FILED
    UccFiling and a SALES_USE assessment of 41250, and auto-advances to ACTIVE.

    Design: Corner/cross_cutting/funding_cascade_creates_ucc_and_sales_tax
    """
    lessor_id = create_lessor(home_state_code="NY")["id"]
    set_clock(lessor_id, "2026-01-01T00:00:00.000Z")
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "X-SN-1", original_cost_cents=500_000)
    get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    funded = get_success_data(api.fund_lease(lessor_id, lease["id"], OFFICER))
    assert funded["lifecycle_status"] == "ACTIVE"
    assert funded["funding_status"] == "FUNDED"
    filings = get_success_data(api.list_lease_ucc_filings(
        lessor_id, lease["id"], OFFICER, params={"status": "FILED"}))
    assert len(filings) >= 1 and filings[0]["status"] == "FILED"
    assessments = get_success_data(api.list_lease_tax_assessments(
        lessor_id, lease["id"], SERVICER, params={"tax_type": "SALES_USE"}))
    assert len(assessments) >= 1
    assert assessments[0]["tax_amount_cents"] == 41250, f"got {assessments[0]['tax_amount_cents']}"
