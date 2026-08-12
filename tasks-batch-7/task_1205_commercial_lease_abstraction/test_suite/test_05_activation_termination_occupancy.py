"""Lease activation gates, termination cascade, and occupancy reporting."""
from test_helpers import (
    ApiErrorId,
    add_schedule_line,
    certify_lease,
    create_billing,
    create_critical_date_on,
    create_lease,
    create_pool,
    create_property,
    issue_billing,
    mark_billing_paid,
    set_clock,
    setup_active_lease,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ACCT = TEST_USERS["lease_accountant_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
PROP_MGR = TEST_USERS["property_manager_headers"]


class TestActivationGates:
    def test_activation_blocked_without_abstraction_certification(self, api):
        """PRD §3.3: "Activation is the moment a drafted lease goes live,
        performed by a `PortfolioManager` and guarded by three fiscal and
        data-quality gates evaluated after the basic state check. First, the
        abstraction dimension must be `CERTIFIED`, else
        `ERR_ABSTRACTION_NOT_CERTIFIED`."

        Design: Corner/validations/activation_blocked_without_abstraction_certification
        """
        set_clock()
        prop = create_property()
        lease = create_lease(prop["id"])  # never abstracted/certified
        add_schedule_line(lease["id"])
        pool = create_pool(prop["id"])
        create_billing(lease["id"], pool["id"])  # DRAFT billing exists
        resp = api.activate_lease(lease["id"], PM)
        validate_error(resp, ApiErrorId.ERR_ABSTRACTION_NOT_CERTIFIED)

    def test_err_schedule_gap_on_activate(self, api):
        """PRD §3.3: "Second, the rent schedule must cover the full span from
        `commencement_date` to `expiration_date` with no gap, else
        `ERR_SCHEDULE_GAP`."

        Design: Corner/errors/err_schedule_gap_on_activate
        """
        set_clock()
        prop = create_property()
        lease = create_lease(prop["id"])
        certify_lease(lease["id"])
        # Schedule covers only H1 2027; H2 up to expiration 2027-12-31 is a gap.
        add_schedule_line(lease["id"], period_start="2027-01-01",
                          period_end="2027-07-01", base_rent_cents=600000)
        pool = create_pool(prop["id"])
        create_billing(lease["id"], pool["id"])
        resp = api.activate_lease(lease["id"], PM)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_GAP)


class TestTermination:
    def test_terminate_blocked_by_outstanding_billing(self, api):
        """PRD §3.4: "Termination is rejected with `ERR_OUTSTANDING_BILLING` if
        any RecoveryBilling of the lease is in `ISSUED` status with an unpaid
        amount greater than zero, and with `ERR_OPEN_RECONCILIATION` if any
        Reconciliation is `OPEN` or `CHALLENGED`."

        Design: Corner/validations/terminate_blocked_by_outstanding_billing
        """
        ctx = setup_active_lease()  # one ISSUED, unpaid billing
        resp = api.terminate_lease(ctx["lease"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BILLING)

    def test_termination_cascades_draft_billing_to_void(self, api):
        """PRD §3.4: "A successful termination moves `status` from `ACTIVE` to
        `TERMINATED`, transitions all `PENDING` CriticalDate rows to `WAIVED`,
        voids all `DRAFT` RecoveryBilling rows, recomputes the property's
        `posture`, and increments the lease's `version`."

        Design: Difficulty/transitive_cascade/termination_cascade_to_billing_and_dates
        """
        ctx = setup_active_lease(issue_billing_after_activation=False)
        b_draft = ctx["billing"]
        b_paid = create_billing(ctx["lease"]["id"], ctx["pool"]["id"],
                                fiscal_year=2026, period_index=2)
        issue_billing(b_paid["id"])
        mark_billing_paid(b_paid["id"])
        lease = validate_success(api.terminate_lease(ctx["lease"]["id"], PM))
        assert lease["status"] == "TERMINATED"
        draft_after = validate_success(api.get_recovery_billing(b_draft["id"], ACCT))
        assert draft_after["status"] == "VOID", (
            f"DRAFT billing must cascade to VOID, got {draft_after['status']}"
        )

    def test_termination_cascades_pending_dates_and_keeps_paid_billing(self, api):
        """PRD §3.4: "A successful termination moves `status` from `ACTIVE` to
        `TERMINATED`, transitions all `PENDING` CriticalDate rows to `WAIVED`,
        voids all `DRAFT` RecoveryBilling rows, recomputes the property's
        `posture`, and increments the lease's `version`."
        (The cascade names only PENDING dates and DRAFT billings; a PAID
        billing is already terminal and is untouched.)

        Design: Difficulty/transitive_cascade/termination_cascade_to_billing_and_dates
        """
        ctx = setup_active_lease(issue_billing_after_activation=False)
        b_paid = create_billing(ctx["lease"]["id"], ctx["pool"]["id"],
                                fiscal_year=2026, period_index=2)
        issue_billing(b_paid["id"])
        mark_billing_paid(b_paid["id"])
        cd = create_critical_date_on(
            ctx["lease"]["id"], kind="NOTICE_DEADLINE",
            due_date="2027-09-01", advance_notice_days=30,
        )
        lease = validate_success(api.terminate_lease(ctx["lease"]["id"], PM))
        assert lease["status"] == "TERMINATED"
        cd_after = validate_success(api.get_critical_date(cd["id"], PROP_MGR))
        assert cd_after["status"] == "WAIVED", (
            f"PENDING CriticalDate must cascade to WAIVED, got {cd_after['status']}"
        )
        paid_after = validate_success(api.get_recovery_billing(b_paid["id"], ACCT))
        assert paid_after["status"] == "PAID", (
            f"terminal PAID billing must not be cascaded, got {paid_after['status']}"
        )


class TestOccupancyReport:
    def test_occupancy_rate_excludes_inactive_leases(self, api, lease_accountant_headers):
        """PRD §3.1: "Occupied square footage is the sum of `leased_sf` over all
        leases on the property that are `ACTIVE` and whose term overlaps the
        fiscal year — that is, whose `commencement_date` falls before the fiscal
        year's end and whose `expiration_date` falls after the fiscal year's
        start. The occupancy rate in basis points is the occupied square footage
        multiplied by 10000 and divided by the property's total rentable square
        footage, rounded half-up to a whole basis point; when nothing is
        occupied, the rate is 0."

        Design: Corner/calculations/occupancy_rate_excludes_inactive_leases
        """
        set_clock()
        prop = create_property()
        pool = create_pool(prop["id"], budgeted_cents=100)

        # Lease A: 4000 SF, fully activated -> counts.
        la = create_lease(prop["id"], tenant_legal_name="A", suite="100",
                          leased_sf=4000, pro_rata_share_bps=4000)
        certify_lease(la["id"])
        add_schedule_line(la["id"])
        ba = create_billing(la["id"], pool["id"])
        validate_success(api.activate_lease(la["id"], PM))
        issue_billing(ba["id"])

        # Lease B: 3000 SF, stays DRAFT -> excluded.
        create_lease(prop["id"], tenant_legal_name="B", suite="200",
                     leased_sf=3000, base_rent_annual_cents=100,
                     pro_rata_share_bps=3000)

        # Lease C: 2000 SF, activated then TERMINATED -> excluded.
        lc = create_lease(prop["id"], tenant_legal_name="C", suite="300",
                          leased_sf=2000, base_rent_annual_cents=100,
                          pro_rata_share_bps=2000)
        certify_lease(lc["id"])
        add_schedule_line(lc["id"], base_rent_cents=100)
        bc = create_billing(lc["id"], pool["id"])
        validate_success(api.activate_lease(lc["id"], PM))
        issue_billing(bc["id"])
        mark_billing_paid(bc["id"])
        terminated = validate_success(api.terminate_lease(lc["id"], PM))
        assert terminated["status"] == "TERMINATED"

        data = validate_success(
            api.get_occupancy_report(
                prop["id"], lease_accountant_headers, params={"fiscal_year": 2026},
            )
        )
        assert data["occupied_sf"] == 4000, (
            f"only ACTIVE lease A counts, expected 4000, got {data['occupied_sf']}"
        )
        assert data["total_rentable_sf"] == 10000
        assert data["occupancy_rate_bps"] == 4000, (
            f"4000/10000 -> 4000 bps, got {data['occupancy_rate_bps']}"
        )
