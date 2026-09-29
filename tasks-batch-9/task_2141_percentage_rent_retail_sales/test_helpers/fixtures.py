"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints
only — each test starts against an empty database. Setup calls use the lenient
validator so a broken precondition surfaces as a setup failure rather than as a
confusing assertion inside the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import TEST_DEFAULTS
from .factories import (
    create_anchor_tenant_payload, create_audit_payload,
    create_center_payload, create_co_tenancy_clause_payload,
    create_kick_out_clause_payload, create_lease_payload,
    create_lease_year_payload, create_sales_report_payload,
    create_tenant_payload, submit_sales_report_payload,
)
from .test_users import (
    AUDITOR, CENTER_ADMIN, LEASE_ADMIN, make_auditor_headers,
    make_center_admin_headers, make_tenant_headers,
)

# Reporting-period boundaries for the 2026-09-01 to 2027-09-01 reporting year.
MONTH_STARTS = [
    "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z",
    "2026-12-01T00:00:00Z", "2027-01-01T00:00:00Z", "2027-02-01T00:00:00Z",
    "2027-03-01T00:00:00Z", "2027-04-01T00:00:00Z", "2027-05-01T00:00:00Z",
    "2027-06-01T00:00:00Z", "2027-07-01T00:00:00Z", "2027-08-01T00:00:00Z",
    "2027-09-01T00:00:00Z",
]

QUARTER_STARTS = [
    "2026-09-01T00:00:00Z", "2026-12-01T00:00:00Z", "2027-03-01T00:00:00Z",
    "2027-06-01T00:00:00Z", "2027-09-01T00:00:00Z",
]


def month_period(index: int) -> tuple:
    """(period_start, period_end) of the index-th month; index 1 is September."""
    return MONTH_STARTS[index - 1], MONTH_STARTS[index]


def quarter_period(index: int) -> tuple:
    """(period_start, period_end) of the index-th quarter; index 1 starts in September."""
    return QUARTER_STARTS[index - 1], QUARTER_STARTS[index]


# ─── Logical clock ────────────────────────────────────────────────────────

def set_clock(instant: str) -> str:
    """Move the logical clock and return the value the server reports back."""
    return get_success_data(api.set_clock(instant, CENTER_ADMIN))["current_utc"]


def read_clock(headers=None) -> str:
    return get_success_data(api.get_clock(headers or LEASE_ADMIN))["current_utc"]


# ─── Reads ────────────────────────────────────────────────────────────────

def read_center(center_id: str) -> dict:
    return get_success_data(api.get_center(center_id, CENTER_ADMIN))


def read_tenant(tenant_id: str) -> dict:
    return get_success_data(api.get_tenant(tenant_id, CENTER_ADMIN))


def read_lease(lease_id: str) -> dict:
    return get_success_data(api.get_lease(lease_id, CENTER_ADMIN))


def lease_version(lease_id: str) -> int:
    return read_lease(lease_id)["version"]


def read_lease_year(lease_year_id: str) -> dict:
    return get_success_data(api.get_lease_year(lease_year_id, LEASE_ADMIN))


def lease_year_version(lease_year_id: str) -> int:
    return read_lease_year(lease_year_id)["version"]


def read_report(report_id: str) -> dict:
    return get_success_data(api.get_sales_report(report_id, LEASE_ADMIN))


def read_charge(charge_id: str) -> dict:
    return get_success_data(api.get_charge(charge_id, LEASE_ADMIN))


def read_clause(clause_id: str) -> dict:
    return get_success_data(api.get_co_tenancy_clause(clause_id, CENTER_ADMIN))


def read_event(event_id: str) -> dict:
    return get_success_data(api.get_co_tenancy_event(event_id, CENTER_ADMIN))


def read_kick_out(clause_id: str) -> dict:
    return get_success_data(api.get_kick_out_clause(clause_id, CENTER_ADMIN))


def read_audit(audit_id: str) -> dict:
    return get_success_data(api.get_audit(audit_id, AUDITOR))


def list_charges(**filters) -> list:
    return get_success_data(api.list_charges(LEASE_ADMIN, params=filters or None))


def charges_for_year(lease_year_id: str, **filters) -> list:
    params = {"lease_year_id": lease_year_id}
    params.update(filters)
    return list_charges(**params)


def first_charge_of_type(lease_year_id: str, charge_type: str) -> dict:
    rows = charges_for_year(lease_year_id, charge_type=charge_type)
    assert rows, f"expected at least one {charge_type} charge on the reporting year"
    return rows[0]


def ledger_entries(lease_year_id: str, entry_type: str = None,
                   headers=None) -> list:
    params = {"entry_type": entry_type} if entry_type else None
    return get_success_data(
        api.list_ledger_entries(lease_year_id, headers or LEASE_ADMIN, params=params))


def exclusions_for(report_id: str, **filters) -> list:
    return get_success_data(
        api.list_exclusions(report_id, LEASE_ADMIN, params=filters or None))


def reports_for_year(lease_year_id: str, **filters) -> list:
    params = {"lease_year_id": lease_year_id}
    params.update(filters)
    return get_success_data(api.list_sales_reports(LEASE_ADMIN, params=params))


def events_for_clause(clause_id: str) -> list:
    return get_success_data(
        api.list_co_tenancy_events(CENTER_ADMIN, params={"clause_id": clause_id}))


def first_event_for_clause(clause_id: str) -> dict:
    rows = events_for_clause(clause_id)
    assert rows, f"expected a co-tenancy event on clause {clause_id}"
    return rows[0]


# ─── Tier 1: single-resource creation ─────────────────────────────────────

def create_center(**overrides) -> dict:
    return get_success_data(
        api.create_center(create_center_payload(**overrides), CENTER_ADMIN))


def create_tenant(center_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_tenant(create_tenant_payload(center_id, **overrides),
                          CENTER_ADMIN))


def create_anchor_tenant(center_id: str, operating: bool = True,
                         **overrides) -> dict:
    tenant = get_success_data(
        api.create_tenant(create_anchor_tenant_payload(center_id, **overrides),
                          CENTER_ADMIN))
    if operating:
        tenant = set_tenant_status(tenant["id"], "OPERATING")
    return tenant


def set_tenant_status(tenant_id: str, to_status: str) -> dict:
    return get_success_data(
        api.set_tenant_status(tenant_id, {"to_status": to_status}, CENTER_ADMIN))


def create_lease(center_id: str, tenant_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_lease(create_lease_payload(center_id, tenant_id, **overrides),
                         CENTER_ADMIN))


def activate_lease(lease_id: str) -> dict:
    return get_success_data(api.activate_lease(lease_id, CENTER_ADMIN))


def amend_lease(lease_id: str, **fields) -> dict:
    payload = {"expected_lease_version": lease_version(lease_id)}
    payload.update(fields)
    return get_success_data(api.amend_lease(lease_id, payload, CENTER_ADMIN))


def open_lease_year(lease_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_lease_year(lease_id, create_lease_year_payload(**overrides),
                              LEASE_ADMIN))


def schedule_report(lease_year_id: str, period_start: str,
                    period_end: str) -> dict:
    return get_success_data(
        api.create_sales_report(
            lease_year_id,
            create_sales_report_payload(period_start, period_end),
            LEASE_ADMIN,
        ))


def schedule_monthly_report(lease_year_id: str, index: int) -> dict:
    start, end = month_period(index)
    return schedule_report(lease_year_id, start, end)


def schedule_quarterly_report(lease_year_id: str, index: int) -> dict:
    start, end = quarter_period(index)
    return schedule_report(lease_year_id, start, end)


def submit_report(report_id: str, tenant_id: str, gross_sales_cents: int,
                  exclusions=None) -> dict:
    return get_success_data(
        api.submit_sales_report(
            report_id,
            submit_sales_report_payload(gross_sales_cents, exclusions),
            make_tenant_headers(tenant_id),
        ))


def accept_report(report_id: str) -> dict:
    return get_success_data(api.accept_sales_report(report_id, LEASE_ADMIN))


def file_and_accept(report_id: str, tenant_id: str, gross_sales_cents: int,
                    exclusions=None) -> dict:
    submit_report(report_id, tenant_id, gross_sales_cents, exclusions)
    return accept_report(report_id)


def estimate_bill(report_id: str, lease_year_id: str,
                  expected_version: int = None) -> dict:
    """Estimate-bill a delinquent period, reading the year's version first."""
    version = (expected_version if expected_version is not None
               else lease_year_version(lease_year_id))
    return get_success_data(
        api.estimate_bill_sales_report(
            report_id, {"expected_lease_year_version": version}, LEASE_ADMIN))


def close_period(lease_year_id: str) -> dict:
    return get_success_data(api.close_period(lease_year_id, LEASE_ADMIN))


def reconcile(lease_year_id: str) -> dict:
    return get_success_data(api.reconcile_lease_year(lease_year_id, LEASE_ADMIN))


def reopen(lease_year_id: str, reason: str = "Late audit finding received") -> dict:
    return get_success_data(
        api.reopen_lease_year(lease_year_id, {"reason": reason}, LEASE_ADMIN))


def close_year(lease_year_id: str) -> dict:
    return get_success_data(api.close_lease_year(lease_year_id, CENTER_ADMIN))


def issue_charge(charge_id: str) -> dict:
    return get_success_data(api.issue_charge(charge_id, LEASE_ADMIN))


def void_charge(charge_id: str, reason: str = "Billed against a superseded figure") -> dict:
    return get_success_data(api.void_charge(charge_id, {"reason": reason}, LEASE_ADMIN))


def pay_charge(charge_id: str, amount_cents: int, headers=None) -> dict:
    return get_success_data(
        api.pay_charge(charge_id, {"amount_cents": amount_cents},
                       headers or LEASE_ADMIN))


def attach_co_tenancy_clause(lease_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_co_tenancy_clause(
            lease_id, create_co_tenancy_clause_payload(**overrides), CENTER_ADMIN))


def attach_kick_out_clause(lease_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_kick_out_clause(
            lease_id, create_kick_out_clause_payload(**overrides), CENTER_ADMIN))


def acknowledge_event(event_id: str) -> dict:
    return get_success_data(
        api.acknowledge_co_tenancy_event(event_id, LEASE_ADMIN))


def activate_relief(event_id: str, admin_user_id: str = "ca-relief-1") -> dict:
    return get_success_data(
        api.activate_relief(event_id, make_center_admin_headers(admin_user_id)))


def cure_event(event_id: str) -> dict:
    return get_success_data(api.cure_co_tenancy_event(event_id, LEASE_ADMIN))


def elect_termination(event_id: str, tenant_id: str) -> dict:
    return get_success_data(
        api.elect_termination(event_id, make_tenant_headers(tenant_id)))


def open_audit(report_id: str, window_start: str, window_end: str,
               auditor_user_id: str = "auditor-1") -> dict:
    return get_success_data(
        api.create_audit(
            create_audit_payload(report_id, window_start, window_end),
            make_auditor_headers(auditor_user_id),
        ))


def issue_findings(audit_id: str, proposed_adjustment_cents: int,
                   auditor_user_id: str = "auditor-1") -> dict:
    return get_success_data(
        api.issue_audit_findings(
            audit_id, {"proposed_adjustment_cents": proposed_adjustment_cents},
            make_auditor_headers(auditor_user_id)))


def settle_audit(audit_id: str, settled_adjustment_cents: int,
                 auditor_user_id: str = "auditor-1") -> dict:
    return get_success_data(
        api.settle_audit(
            audit_id, {"settled_adjustment_cents": settled_adjustment_cents},
            make_auditor_headers(auditor_user_id)))


def rescind_audit(audit_id: str, reason: str = "Audit scope withdrawn",
                  auditor_user_id: str = "auditor-1") -> dict:
    return get_success_data(
        api.rescind_audit(audit_id, {"reason": reason},
                          make_auditor_headers(auditor_user_id)))


def dispute_report(report_id: str, tenant_id: str,
                   reason: str = "POS export excluded layaway deposits") -> dict:
    return get_success_data(
        api.dispute_sales_report(report_id, {"reason": reason},
                                 make_tenant_headers(tenant_id)))


def amend_report(report_id: str, tenant_id: str,
                 reason: str = "Refiling with layaway deposits included") -> dict:
    return get_success_data(
        api.amend_sales_report(report_id, {"reason": reason},
                               make_tenant_headers(tenant_id)))


# ─── Tier 2: entity hierarchy ─────────────────────────────────────────────

def setup_active_lease(clock: str = None, center_overrides: dict = None,
                       tenant_overrides: dict = None, **lease_overrides) -> dict:
    """Center + INLINE tenant + ACTIVE lease. Returns center/tenant/lease."""
    set_clock(clock or TEST_DEFAULTS["CLOCK_AT_YEAR_START"])
    center = create_center(**(center_overrides or {}))
    tenant = create_tenant(center["id"], **(tenant_overrides or {}))
    lease = create_lease(center["id"], tenant["id"], **lease_overrides)
    lease = activate_lease(lease["id"])
    return {"center": center, "tenant": tenant, "lease": lease}


def setup_lease_year(clock: str = None, year_overrides: dict = None,
                     center_overrides: dict = None,
                     tenant_overrides: dict = None, **lease_overrides) -> dict:
    """ACTIVE lease plus an OPEN reporting year 1 spanning the standard span."""
    scene = setup_active_lease(clock=clock, center_overrides=center_overrides,
                               tenant_overrides=tenant_overrides,
                               **lease_overrides)
    scene["lease_year"] = open_lease_year(scene["lease"]["id"],
                                          **(year_overrides or {}))
    return scene


def setup_year_with_pending_reports(period_count: int = 1, **kwargs) -> dict:
    """Reporting year 1 with `period_count` consecutive PENDING monthly periods."""
    scene = setup_lease_year(**kwargs)
    scene["reports"] = [
        schedule_monthly_report(scene["lease_year"]["id"], index)
        for index in range(1, period_count + 1)
    ]
    return scene


# ─── Tier 3: full lifecycle shortcuts ─────────────────────────────────────

def setup_year_with_accepted_reports(gross_list, **kwargs) -> dict:
    """Reporting year 1 whose consecutive monthly periods are all ACCEPTED.

    One period per entry of `gross_list`, filed by the lease's own tenant and
    accepted by the lease administration desk in order.
    """
    scene = setup_lease_year(**kwargs)
    reports = []
    for index, gross in enumerate(gross_list, start=1):
        report = schedule_monthly_report(scene["lease_year"]["id"], index)
        reports.append(
            file_and_accept(report["id"], scene["tenant"]["id"], gross))
    scene["reports"] = reports
    return scene


def setup_year_with_periodic_charge(gross_list=(30_000_000, 30_000_000),
                                    **kwargs) -> dict:
    """Accepted monthly periods that carry the cumulative past the breakpoint.

    Defaults to two 30,000,000 periods against a 40,000,000 stated breakpoint,
    which issues a single 1,200,000 PERIODIC charge.
    """
    kwargs.setdefault("breakpoint_type", "ARTIFICIAL")
    kwargs.setdefault("artificial_breakpoint_cents",
                      TEST_DEFAULTS["ARTIFICIAL_BREAKPOINT_CENTS"])
    scene = setup_year_with_accepted_reports(list(gross_list), **kwargs)
    scene["charge"] = first_charge_of_type(scene["lease_year"]["id"], "PERIODIC")
    return scene


def setup_reconciled_year(gross_list=(30_000_000,),
                          reconcile_clock: str = None, **kwargs) -> dict:
    """Accepted periods, then close-period and reconcile the reporting year."""
    scene = setup_year_with_accepted_reports(list(gross_list), **kwargs)
    close_period(scene["lease_year"]["id"])
    if reconcile_clock:
        set_clock(reconcile_clock)
    scene["lease_year"] = reconcile(scene["lease_year"]["id"])
    return scene


def setup_report_under_audit(gross: int = 30_000_000,
                             window_start: str = "2026-10-05T00:00:00Z",
                             window_end: str = "2026-10-20T00:00:00Z",
                             **kwargs) -> dict:
    """One accepted September period placed under an OPEN audit."""
    scene = setup_year_with_accepted_reports([gross], **kwargs)
    scene["report"] = scene["reports"][0]
    scene["audit"] = open_audit(scene["report"]["id"], window_start, window_end)
    return scene


def setup_report_with_findings(gross: int = 30_000_000,
                               proposed_adjustment_cents: int = 2_000_000,
                               **kwargs) -> dict:
    """An audited September period whose auditor has issued findings."""
    scene = setup_report_under_audit(gross=gross, **kwargs)
    scene["audit"] = issue_findings(scene["audit"]["id"],
                                    proposed_adjustment_cents)
    return scene


# ─── Tier 4: co-tenancy and kick-out targeting ────────────────────────────

def setup_center_with_dark_anchor(clause_overrides: dict = None,
                                  clock: str = None,
                                  **lease_overrides) -> dict:
    """An OPERATING anchor that goes DARK under a lease carrying a clause.

    Returns center/anchor/tenant/lease/clause plus the co-tenancy `event` the
    occupancy monitor opened.
    """
    set_clock(clock or TEST_DEFAULTS["CLOCK_AT_YEAR_START"])
    center = create_center()
    anchor = create_anchor_tenant(center["id"])
    tenant = create_tenant(center["id"], legal_name="Inline Retail LLC",
                           trade_name="InlineShop")
    lease = create_lease(center["id"], tenant["id"], **lease_overrides)
    lease = activate_lease(lease["id"])
    clause = attach_co_tenancy_clause(lease["id"], **(clause_overrides or {}))
    anchor = set_tenant_status(anchor["id"], "DARK")
    event = first_event_for_clause(clause["id"])
    return {"center": center, "anchor": anchor, "tenant": tenant,
            "lease": lease, "clause": clause, "event": event}


def setup_acknowledged_co_tenancy_event(**kwargs) -> dict:
    """A co-tenancy violation acknowledged into CURE_PENDING."""
    scene = setup_center_with_dark_anchor(**kwargs)
    scene["event"] = acknowledge_event(scene["event"]["id"])
    return scene


def setup_relief_active_lease(admin_user_id: str = "ca-relief-1",
                              **kwargs) -> dict:
    """A lease driven all the way to RELIEF_ACTIVE by a lapsed cure period."""
    scene = setup_acknowledged_co_tenancy_event(**kwargs)
    scene["event"] = activate_relief(scene["event"]["id"], admin_user_id)
    scene["lease"] = read_lease(scene["lease"]["id"])
    scene["clause"] = read_clause(scene["clause"]["id"])
    scene["relief_admin_user_id"] = admin_user_id
    return scene


def setup_triggered_kick_out(threshold_sales_cents: int = 100_000_000,
                             election_window_days: int = 30,
                             gross: int = 30_000_000,
                             reconcile_clock: str = "2026-11-01T00:00:00Z",
                             **lease_overrides) -> dict:
    """A kick-out right armed against year 1 and TRIGGERED by reconciliation.

    Sales of `gross` fall strictly below `threshold_sales_cents`, so
    reconciling the measurement year triggers the tenant's election.
    """
    lease_overrides.setdefault("breakpoint_type", "ARTIFICIAL")
    lease_overrides.setdefault("artificial_breakpoint_cents",
                               TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"])
    scene = setup_active_lease(**lease_overrides)
    scene["kick_out"] = attach_kick_out_clause(
        scene["lease"]["id"],
        threshold_sales_cents=threshold_sales_cents,
        election_window_days=election_window_days,
    )
    scene["lease_year"] = open_lease_year(scene["lease"]["id"])
    report = schedule_monthly_report(scene["lease_year"]["id"], 1)
    scene["reports"] = [file_and_accept(report["id"], scene["tenant"]["id"], gross)]
    close_period(scene["lease_year"]["id"])
    set_clock(reconcile_clock)
    scene["lease_year"] = reconcile(scene["lease_year"]["id"])
    scene["kick_out"] = read_kick_out(scene["kick_out"]["id"])
    return scene


def setup_delinquent_report(history_gross=(30_000_000,),
                            delinquent_clock: str = "2026-11-12T00:00:00Z",
                            **lease_overrides) -> dict:
    """Accepted history plus one PENDING period whose due date has passed.

    Defaults to an accepted September period at 30,000,000 and an October
    period whose 2026-11-11 deadline the clock has already passed.
    """
    lease_overrides.setdefault("breakpoint_type", "ARTIFICIAL")
    lease_overrides.setdefault("artificial_breakpoint_cents",
                               TEST_DEFAULTS["ARTIFICIAL_BREAKPOINT_CENTS"])
    scene = setup_year_with_accepted_reports(list(history_gross), **lease_overrides)
    next_index = len(history_gross) + 1
    scene["delinquent_report"] = schedule_monthly_report(
        scene["lease_year"]["id"], next_index)
    set_clock(delinquent_clock)
    return scene


__all__ = [
    "MONTH_STARTS", "QUARTER_STARTS", "month_period", "quarter_period",
    "set_clock", "read_clock", "read_center", "read_tenant", "read_lease",
    "lease_version", "read_lease_year", "lease_year_version", "read_report",
    "read_charge", "read_clause", "read_event", "read_kick_out", "read_audit",
    "list_charges", "charges_for_year", "first_charge_of_type",
    "ledger_entries", "exclusions_for", "reports_for_year",
    "events_for_clause", "first_event_for_clause", "create_center",
    "create_tenant", "create_anchor_tenant", "set_tenant_status",
    "create_lease", "activate_lease", "amend_lease", "open_lease_year",
    "schedule_report", "schedule_monthly_report", "schedule_quarterly_report",
    "submit_report", "accept_report", "file_and_accept", "estimate_bill",
    "close_period", "reconcile", "reopen", "close_year", "issue_charge",
    "void_charge", "pay_charge", "attach_co_tenancy_clause",
    "attach_kick_out_clause", "acknowledge_event", "activate_relief",
    "cure_event", "elect_termination", "open_audit", "issue_findings",
    "settle_audit", "rescind_audit", "dispute_report", "amend_report",
    "setup_active_lease", "setup_lease_year", "setup_year_with_pending_reports",
    "setup_year_with_accepted_reports", "setup_year_with_periodic_charge",
    "setup_reconciled_year", "setup_report_under_audit",
    "setup_report_with_findings", "setup_center_with_dark_anchor",
    "setup_acknowledged_co_tenancy_event", "setup_relief_active_lease",
    "setup_triggered_kick_out", "setup_delinquent_report",
]
