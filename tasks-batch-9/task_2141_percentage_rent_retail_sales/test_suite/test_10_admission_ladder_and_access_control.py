"""The request admission ladder: which check wins when several would fail, and
who is allowed to call what.
"""
from test_helpers import (
    CENTER_ADMIN, LEASE_ADMIN, OWNERSHIP_ANALYST, TEST_DEFAULTS, ApiErrorId,
    create_center_payload, create_sales_report_payload, make_headers,
    make_tenant_headers, read_charge, read_kick_out, read_lease,
    read_lease_year, read_report, reopen, reports_for_year, set_clock,
    setup_year_with_periodic_charge, setup_year_with_pending_reports,
    setup_triggered_kick_out, setup_year_with_accepted_reports, submit_report,
    submit_sales_report_payload, close_period, create_tenant, open_audit,
    validate_error, validate_success, void_charge,
)

ARTIFICIAL_BREAKPOINT = TEST_DEFAULTS["ARTIFICIAL_BREAKPOINT_CENTS"]
UNREACHABLE_BREAKPOINT = TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"]
UNKNOWN_REPORT_ID = "00000000-0000-4000-8000-0000000000aa"


# ─── State (step 6) outranks the money rule (step 13) ─────────────────────

def test_paying_a_voided_charge_reports_the_state_error_not_the_money_error(api):
    """PRD §2.9: "Because state (step 6) outranks concurrency (step 7),
    referential rules (step 10), interval rules (step 11), shape rules (step
    12) and money rules (step 13), an operation attempted from the wrong state
    always reports the state error even when a later rule would also have
    blocked it."
    PRD §3.8: "The charge's `billing_status` must be `ISSUED`; paying against a
    draft or voided charge is refused with `ERR_CHARGE_STATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/charge_state_beats_payment_balance_rejected
    """
    scene = setup_year_with_periodic_charge(suite_code="1101")
    void_charge(scene["charge"]["id"],
                reason="Billed against a superseded sales figure")

    error = validate_error(
        api.pay_charge(scene["charge"]["id"], {"amount_cents": 99_999_999},
                       make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_CHARGE_STATE_INVALID.value, 409)

    assert error["error_id"] != ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value, (
        "the money rule sits below the state check on the ladder")


def test_refused_payment_on_a_voided_charge_moves_nothing(api):
    """PRD §2.9: "**Money rules, applied last.** A payment applied to a charge
    must be strictly positive and must not exceed that charge's outstanding
    balance — otherwise `ERR_PAYMENT_EXCEEDS_BALANCE` (422). This applies only
    to charge payments."
    PRD §3.8: "In the same request the collection axis follows: a charge that
    was `UNPAID` moves `UNPAID → WRITTEN_OFF`, and a charge that was `PARTIAL`
    moves `PARTIAL → WRITTEN_OFF` with its `paid_cents` retained on the row as
    a tenant credit — no refund resource is created."

    Design: Difficulty/priority_pair_validation_conflict/charge_state_beats_payment_balance_rejected
    """
    scene = setup_year_with_periodic_charge(suite_code="1101")
    void_charge(scene["charge"]["id"],
                reason="Billed against a superseded sales figure")

    validate_error(
        api.pay_charge(scene["charge"]["id"], {"amount_cents": 99_999_999},
                       make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_CHARGE_STATE_INVALID.value, 409)

    charge_now = read_charge(scene["charge"]["id"])
    assert charge_now["paid_cents"] == 0
    assert charge_now["collection_status"] == "WRITTEN_OFF"
    assert charge_now["billing_status"] == "VOID"
    assert read_lease_year(
        scene["lease_year"]["id"])["cumulative_billed_cents"] == 0


# ─── Referential rules (step 10) outrank interval rules (step 11) ─────────

def test_reopened_measurement_year_outranks_the_closed_election_window(api):
    """PRD §2.9: "**Cross-entity referential rules** (all HTTP 409), applying
    to lease creation, reporting-year creation, reconciliation and kick-out
    exercise: a lease's `tenant_id` must name a tenant belonging to the lease's
    `center_id` (`ERR_CENTER_MISMATCH`); a reporting year's `year_index` must
    be unique within its lease (`ERR_DUPLICATE_LEASE_YEAR_INDEX`);
    reconciliation requires every sales report of the year to be out of
    `PENDING`, `SUBMITTED`, `UNDER_AUDIT`, `DISPUTED` and `AMENDED`
    (`ERR_UNACCEPTED_REPORTS_BLOCK_RECONCILE`); exercising a kick-out right
    requires the measurement reporting year to be `RECONCILED`
    (`ERR_KICK_OUT_MEASUREMENT_YEAR_NOT_RECONCILED`); and exercising a kick-out
    right is refused while the lease is `RELIEF_ACTIVE`
    (`ERR_RELIEF_ACTIVE_BLOCKS_EXERCISE`)."
    PRD §2.9: "**Interval and clock rules** (all HTTP 409), applying to report
    scheduling, audit opening, estimate billing, relief activation, kick-out
    exercise and termination election: `ERR_REPORTING_PERIOD_OVERLAP`,
    `ERR_AUDIT_WINDOW_CONFLICT`, `ERR_REPORT_NOT_DELINQUENT`,
    `ERR_CURE_PERIOD_NOT_ELAPSED`, `ERR_KICK_OUT_ELECTION_WINDOW_CLOSED` and
    `ERR_TERMINATION_RIGHT_NOT_RIPE`. Each is defined in the workflow that
    raises it."

    Design: Difficulty/priority_pair_validation_conflict/kick_out_referential_beats_election_window_temporal_rejected
    """
    scene = setup_triggered_kick_out(suite_code="1201",
                                     artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    reopen(scene["lease_year"]["id"], reason="Late audit finding received")
    set_clock("2027-01-15T00:00:00Z")

    error = validate_error(
        api.exercise_kick_out_clause(
            scene["kick_out"]["id"], make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_KICK_OUT_MEASUREMENT_YEAR_NOT_RECONCILED.value, 409)

    assert error["error_id"] != ApiErrorId.ERR_KICK_OUT_ELECTION_WINDOW_CLOSED.value, (
        "the referential rule sits above the election-window clock rule")


def test_reopening_a_reconciled_year_never_re_arms_the_triggered_right(api):
    """PRD §3.10: "Reopening never re-arms a kick-out right: clauses already
    `TRIGGERED` keep their `status`, their `triggered_at` and their
    `election_deadline_at` untouched."
    PRD §3.10: "Leaving `RECONCILED` sets `true_up_delta_cents` back to null."

    Design: Difficulty/priority_pair_validation_conflict/kick_out_referential_beats_election_window_temporal_rejected
    """
    from test_helpers import assert_instant_equals

    scene = setup_triggered_kick_out(suite_code="1201",
                                     artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    reopen(scene["lease_year"]["id"], reason="Late audit finding received")
    set_clock("2027-01-15T00:00:00Z")

    validate_error(
        api.exercise_kick_out_clause(
            scene["kick_out"]["id"], make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_KICK_OUT_MEASUREMENT_YEAR_NOT_RECONCILED.value, 409)

    clause_now = read_kick_out(scene["kick_out"]["id"])
    assert clause_now["status"] == "TRIGGERED"
    assert_instant_equals(clause_now["election_deadline_at"],
                          "2026-12-01T00:00:00Z", "election_deadline_at")

    year_now = read_lease_year(scene["lease_year"]["id"])
    assert year_now["status"] == "RECONCILING"
    assert year_now["true_up_delta_cents"] is None
    assert read_lease(scene["lease"]["id"])["status"] == "ACTIVE"


# ─── The open-audit interlock (step 9) outranks referential rules (step 10)

def test_open_audit_interlock_outranks_the_unaccepted_reports_rule(api):
    """PRD §2.9: "**Open-audit interlock.** Reconciliation is refused while any
    audit targeting a report of that reporting year is `OPEN` or
    `FINDINGS_ISSUED` — that is, while the year's `open_audit_count` is greater
    than zero — rejecting with `ERR_OPEN_AUDIT_BLOCKS_RECONCILE` (409). This
    applies only to reconciliation."

    Design: Difficulty/priority_pair_validation_conflict/open_audit_safety_beats_unaccepted_reports_referential_rejected
    """
    scene = setup_year_with_accepted_reports(
        [30_000_000], suite_code="1301", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    open_audit(scene["reports"][0]["id"], "2026-10-05T00:00:00Z",
               "2026-10-20T00:00:00Z")
    close_period(scene["lease_year"]["id"])

    error = validate_error(
        api.reconcile_lease_year(scene["lease_year"]["id"], LEASE_ADMIN),
        ApiErrorId.ERR_OPEN_AUDIT_BLOCKS_RECONCILE.value, 409)

    assert error["error_id"] != (
        ApiErrorId.ERR_UNACCEPTED_REPORTS_BLOCK_RECONCILE.value), (
        "the open-audit interlock is evaluated before the referential rule")


def test_report_left_under_audit_still_reports_the_open_audit_error(api):
    """PRD §2.9: "**Cross-entity referential rules** (all HTTP 409), applying
    to lease creation, reporting-year creation, reconciliation and kick-out
    exercise: a lease's `tenant_id` must name a tenant belonging to the lease's
    `center_id` (`ERR_CENTER_MISMATCH`); a reporting year's `year_index` must
    be unique within its lease (`ERR_DUPLICATE_LEASE_YEAR_INDEX`);
    reconciliation requires every sales report of the year to be out of
    `PENDING`, `SUBMITTED`, `UNDER_AUDIT`, `DISPUTED` and `AMENDED`
    (`ERR_UNACCEPTED_REPORTS_BLOCK_RECONCILE`); exercising a kick-out right
    requires the measurement reporting year to be `RECONCILED`
    (`ERR_KICK_OUT_MEASUREMENT_YEAR_NOT_RECONCILED`); and exercising a kick-out
    right is refused while the lease is `RELIEF_ACTIVE`
    (`ERR_RELIEF_ACTIVE_BLOCKS_EXERCISE`)."
    PRD §3.7: "The report moves `ACCEPTED → UNDER_AUDIT` and the reporting
    year's `open_audit_count` increases by 1."

    Design: Difficulty/priority_pair_validation_conflict/open_audit_safety_beats_unaccepted_reports_referential_rejected
    """
    scene = setup_year_with_accepted_reports(
        [30_000_000], suite_code="1301", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    report = scene["reports"][0]
    open_audit(report["id"], "2026-10-05T00:00:00Z", "2026-10-20T00:00:00Z")
    close_period(scene["lease_year"]["id"])

    validate_error(
        api.reconcile_lease_year(scene["lease_year"]["id"], LEASE_ADMIN),
        ApiErrorId.ERR_OPEN_AUDIT_BLOCKS_RECONCILE.value, 409)

    assert read_report(report["id"])["status"] == "UNDER_AUDIT", (
        "the report would independently have tripped the referential rule")
    year_now = read_lease_year(scene["lease_year"]["id"])
    assert year_now["status"] == "RECONCILING"
    assert year_now["open_audit_count"] == 1
    assert year_now["true_up_delta_cents"] is None


# ─── Interval rules (step 11) outrank shape rules (step 12) ───────────────

def test_overlapping_period_that_also_runs_past_the_year_reports_the_overlap(api):
    """PRD §2.9: "When a request could fail several checks at once, the order
    in which those checks run decides which error the client sees, and that
    order is fixed."
    PRD §2.9: "**Domain shape rules** (all HTTP 422), applying to lease
    creation, lease amendment, report scheduling, report submission, report
    dispute and report amendment: `ERR_BREAKPOINT_CONFIG_INVALID`,
    `ERR_PERIOD_OUTSIDE_LEASE_YEAR`, `ERR_EXCLUSION_CODE_NOT_PERMITTED` and
    `ERR_AMENDMENT_LIMIT_EXCEEDED`, each defined in the workflow that raises
    it."

    Design: Difficulty/priority_pair_validation_conflict/period_overlap_temporal_beats_outside_year_constraint_rejected
    """
    scene = setup_year_with_pending_reports(1, suite_code="1401")

    error = validate_error(
        api.create_sales_report(
            scene["lease_year"]["id"],
            create_sales_report_payload("2026-09-15T00:00:00Z",
                                        "2027-09-15T00:00:00Z"),
            LEASE_ADMIN),
        ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP.value, 409)

    assert error["error_id"] != ApiErrorId.ERR_PERIOD_OUTSIDE_LEASE_YEAR.value, (
        "the interval rule is evaluated before the domain shape rule")


def test_period_refused_on_the_interval_rule_creates_no_report(api):
    """PRD §2.9: "**Interval and clock rules** (all HTTP 409), applying to
    report scheduling, audit opening, estimate billing, relief activation,
    kick-out exercise and termination election:
    `ERR_REPORTING_PERIOD_OVERLAP`, `ERR_AUDIT_WINDOW_CONFLICT`,
    `ERR_REPORT_NOT_DELINQUENT`, `ERR_CURE_PERIOD_NOT_ELAPSED`,
    `ERR_KICK_OUT_ELECTION_WINDOW_CLOSED` and
    `ERR_TERMINATION_RIGHT_NOT_RIPE`. Each is defined in the workflow that
    raises it."

    Design: Difficulty/priority_pair_validation_conflict/period_overlap_temporal_beats_outside_year_constraint_rejected
    """
    scene = setup_year_with_pending_reports(1, suite_code="1401")

    validate_error(
        api.create_sales_report(
            scene["lease_year"]["id"],
            create_sales_report_payload("2026-09-15T00:00:00Z",
                                        "2027-09-15T00:00:00Z"),
            LEASE_ADMIN),
        ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP.value, 409)

    remaining = reports_for_year(scene["lease_year"]["id"])
    assert len(remaining) == 1, "only the original September period survives"


# ─── Authentication, authorization and tenant ownership ───────────────────

def test_unknown_role_header_is_rejected_before_anything_else(api):
    """PRD §2.1: "Every request to the service must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity
    in which the caller acts. If either header is missing, empty, or if
    `X-User-Role` names something that is not one of the five roles defined
    below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before
    any other processing occurs."

    Design: Corner/errors/unknown_role_header_returns_unauthenticated
    """
    validate_error(
        api.create_center(
            create_center_payload(name="Ghost Center", code="GHOST",
                                  total_gla_sqft=100_000, anchor_gla_sqft=0),
            make_headers("ghost-1", "FacilitiesManager")),
        ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_tenant_user_may_not_accept_its_own_sales_report(api):
    """PRD §2.9: "**Role authorization.** The acting role appears in the
    endpoint's permitted role list — otherwise `ERR_UNAUTHORIZED` (403). This
    runs on every endpoint."
    PRD §3.5: "Acceptance is the landlord's vetting act, performed by a
    `LeaseAdministrator` and permitted while the reporting year is `OPEN` or
    `RECONCILING`."

    Design: Corner/rbac/tenant_user_cannot_accept_sales_report
    """
    scene = setup_year_with_pending_reports(1, suite_code="8101")
    report = scene["reports"][0]
    submit_report(report["id"], scene["tenant"]["id"], 30_000_000)

    validate_error(
        api.accept_sales_report(report["id"],
                                make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert read_report(report["id"])["status"] == "SUBMITTED"
    assert read_lease_year(
        scene["lease_year"]["id"])["cumulative_net_sales_cents"] == 0


def test_only_ownership_may_pull_the_center_sales_trend(api):
    """PRD §3.10: "Ownership sees the portfolio through a different lens. An
    `OwnershipAnalyst` — and no other role — pulls a comparable-store trend
    report for a center and a nominated `year_index`, which for this
    computation is read as year N."
    PRD §2.9: "**Role authorization.** The acting role appears in the
    endpoint's permitted role list — otherwise `ERR_UNAUTHORIZED` (403). This
    runs on every endpoint."

    Design: Corner/rbac/center_admin_cannot_read_sales_trend
    """
    scene = setup_year_with_pending_reports(1, suite_code="8201")

    validate_success(api.get_center(scene["center"]["id"], CENTER_ADMIN))

    validate_error(
        api.get_center_sales_trend(scene["center"]["id"], CENTER_ADMIN,
                                   params={"year_index": 1}),
        ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    validate_success(
        api.get_center_sales_trend(scene["center"]["id"], OWNERSHIP_ANALYST,
                                   params={"year_index": 1}))


def test_filing_against_another_tenants_lease_is_refused(api):
    """PRD §2.1: "Concretely, for a tenant-facing operation the server walks
    from the target resource to the owning lease — a sales report reaches its
    lease through its reporting year, a charge reaches its lease through its
    reporting year, and a co-tenancy event or kick-out clause reaches its lease
    directly — and requires `X-User-ID` to equal that lease's `tenant_id`. A
    mismatch is rejected with `ERR_NOT_LEASE_TENANT` (HTTP 403)."

    Design: Corner/validations/submit_by_wrong_tenant_returns_403_not_lease_tenant
    """
    scene = setup_year_with_pending_reports(1, suite_code="6101")
    report = scene["reports"][0]
    other_tenant = create_tenant(scene["center"]["id"],
                                 legal_name="Other Tenant LLC",
                                 trade_name="OtherShop")

    validate_error(
        api.submit_sales_report(report["id"],
                                submit_sales_report_payload(30_000_000),
                                make_tenant_headers(other_tenant["id"])),
        ApiErrorId.ERR_NOT_LEASE_TENANT.value, 403)

    report_now = read_report(report["id"])
    assert report_now["status"] == "PENDING"
    assert report_now["gross_sales_cents"] is None


def test_unknown_report_id_answers_not_found_before_any_state_check(api):
    """PRD §2.9: "**Existence.** Every resource named in the URL path must
    exist, validated left to right; only then is every id referenced in the
    request body resolved. The rejection is the not-found code matching
    whichever resource was missing: `ERR_CENTER_NOT_FOUND`,
    `ERR_TENANT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_LEASE_YEAR_NOT_FOUND`,
    `ERR_SALES_REPORT_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`,
    `ERR_CO_TENANCY_CLAUSE_NOT_FOUND`, `ERR_CO_TENANCY_EVENT_NOT_FOUND`,
    `ERR_KICK_OUT_CLAUSE_NOT_FOUND` or `ERR_AUDIT_NOT_FOUND`, each HTTP 404."

    Design: Corner/validations/existence_check_precedes_state_check_on_unknown_report
    """
    setup_year_with_pending_reports(1, suite_code="6801")

    error = validate_error(
        api.accept_sales_report(UNKNOWN_REPORT_ID, LEASE_ADMIN),
        ApiErrorId.ERR_SALES_REPORT_NOT_FOUND.value, 404)

    assert error["error_id"] != ApiErrorId.ERR_REPORT_STATE_INVALID.value, (
        "existence is checked before any state precondition")
