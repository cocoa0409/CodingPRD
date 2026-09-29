"""Opening reporting years, scheduling their periods and the freeze that
closing a period puts on tenant filing.
"""
from test_helpers import (
    ApiErrorId, assert_instant_equals,
    assert_sales_report, close_period, close_year, create_lease_year_payload,
    create_sales_report_payload, file_and_accept, LEASE_ADMIN,
    make_tenant_headers, month_period, read_lease_year, read_report, reconcile,
    reopen, reports_for_year, schedule_monthly_report, setup_lease_year,
    setup_year_with_pending_reports, submit_sales_report_payload,
    TEST_DEFAULTS, validate_error, validate_paginated, validate_success,
)


# ─── Scheduling a reporting period ────────────────────────────────────────

def test_scheduled_period_starts_pending_with_a_deadline_derived_due_at(api):
    """PRD §3.3: "The new report is created in `PENDING` with `submitted_at`
    null, `gross_sales_cents` null, `allowed_exclusions_cents` and
    `net_sales_cents` at 0, `source` at `TENANT_REPORTED`, `amendment_round` at
    0, `is_delinquent` false, and its `lease_year_id` pointing at the year it
    was scheduled into. Its `due_at` is computed as the period's `period_end`
    advanced by the lease's `reporting_deadline_days` whole days in UTC — this
    is the single place where the contractual filing deadline becomes a
    concrete instant."

    Design: Corner/state_machines/new_sales_report_starts_pending_with_computed_due_at
    """
    scene = setup_lease_year(suite_code="3901")
    start, end = month_period(1)

    data = validate_success(
        api.create_sales_report(scene["lease_year"]["id"],
                                create_sales_report_payload(start, end),
                                LEASE_ADMIN),
        201,
    )

    assert_sales_report(data)
    assert data["status"] == "PENDING"
    assert_instant_equals(data["due_at"], "2026-10-11T00:00:00Z",
                          "due_at is period_end plus ten whole days")
    assert data["gross_sales_cents"] is None
    assert data["submitted_at"] is None
    assert data["source"] == "TENANT_REPORTED"
    assert data["is_delinquent"] is False
    assert data["amendment_round"] == 0
    assert data["lease_year_id"] == scene["lease_year"]["id"]


def test_second_reporting_year_reusing_year_index_one_is_refused(api):
    """PRD §3.3: "Creation names the `year_index` — a 1-based ordinal of at
    least 1 that must be unique within the lease, with a duplicate refused as
    `ERR_DUPLICATE_LEASE_YEAR_INDEX` — together with the year's `period_start`
    and `period_end`, where the end must be strictly after the start."

    Design: Corner/validations/duplicate_lease_year_index_returns_409
    """
    scene = setup_lease_year(suite_code="6201")

    validate_error(
        api.create_lease_year(
            scene["lease"]["id"],
            create_lease_year_payload(year_index=1,
                                      period_start="2027-09-01T00:00:00Z",
                                      period_end="2028-09-01T00:00:00Z"),
            LEASE_ADMIN),
        ApiErrorId.ERR_DUPLICATE_LEASE_YEAR_INDEX.value, 409)

    _rows, meta = validate_paginated(
        api.list_lease_years(LEASE_ADMIN,
                             params={"lease_id": scene["lease"]["id"]}))
    assert meta["total_count"] == 1, "the duplicate year must not have been opened"


def test_period_running_past_the_reporting_year_end_is_refused(api):
    """PRD §3.3: "Two rules constrain scheduling. The proposed period must lie
    entirely inside the reporting year's own `period_start` to `period_end`
    span; a period that falls partly or wholly outside it is refused with
    `ERR_PERIOD_OUTSIDE_LEASE_YEAR`."

    Design: Corner/validations/report_period_outside_lease_year_returns_422
    """
    scene = setup_lease_year(suite_code="6401")

    validate_error(
        api.create_sales_report(
            scene["lease_year"]["id"],
            create_sales_report_payload("2027-08-15T00:00:00Z",
                                        "2027-09-15T00:00:00Z"),
            LEASE_ADMIN),
        ApiErrorId.ERR_PERIOD_OUTSIDE_LEASE_YEAR.value, 422)

    assert reports_for_year(scene["lease_year"]["id"]) == []


def test_adjacent_reporting_period_starting_where_the_last_one_ended_is_accepted(api):
    """PRD §2.10: "Two reporting periods on the same reporting year therefore
    collide only when one strictly begins before the other ends and that other
    strictly begins before the first one ends. Periods that merely touch —
    where a new period's `period_start` equals an existing period's
    `period_end` — do not collide, which is exactly what makes consecutive
    monthly periods expressible."

    Design: Difficulty/resource_temporal_overlap/report_period_half_open_adjacency_allowed_overlap_rejected
    """
    scene = setup_year_with_pending_reports(1, suite_code="2101")
    start, end = month_period(2)

    data = validate_success(
        api.create_sales_report(scene["lease_year"]["id"],
                                create_sales_report_payload(start, end),
                                LEASE_ADMIN),
        201,
    )

    assert_sales_report(data)
    assert_instant_equals(data["period_start"], "2026-10-01T00:00:00Z",
                          "the touching period keeps its requested start")
    assert len(reports_for_year(scene["lease_year"]["id"])) == 2


def test_reporting_period_straddling_an_existing_one_is_refused(api):
    """PRD §3.3: "And the proposed period must not overlap any non-`VOID`
    report already on the year, under the half-open convention of Section 2.10
    — so a February period starting exactly where the January period ended is
    accepted, while a period that genuinely straddles an existing one is
    refused with `ERR_REPORTING_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/report_period_half_open_adjacency_allowed_overlap_rejected
    """
    scene = setup_year_with_pending_reports(1, suite_code="2101")
    schedule_monthly_report(scene["lease_year"]["id"], 2)

    validate_error(
        api.create_sales_report(
            scene["lease_year"]["id"],
            create_sales_report_payload("2026-09-15T00:00:00Z",
                                        "2026-10-15T00:00:00Z"),
            LEASE_ADMIN),
        ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP.value, 409)

    assert len(reports_for_year(scene["lease_year"]["id"])) == 2, (
        "the straddling request must leave the year's two periods untouched")


# ─── The reporting year's own status gate ─────────────────────────────────

def test_submitting_a_pending_period_while_the_year_reconciles_is_refused(api):
    """PRD §3.4: "The ordinary case is `PENDING → SUBMITTED`, which requires the
    owning reporting year to be `OPEN`."
    PRD §3.10: "A `LeaseAdministrator` first freezes the year `OPEN →
    RECONCILING`, which stops new reporting periods from being scheduled and
    stops reports still in `PENDING` from being submitted, then reconciles it
    `RECONCILING → RECONCILED`."
    PRD §2.9: "The rejection is the state code matching the entity that
    blocked: `ERR_TENANT_STATE_INVALID`, `ERR_LEASE_STATE_INVALID`,
    `ERR_LEASE_YEAR_STATE_INVALID`, `ERR_REPORT_STATE_INVALID`,
    `ERR_CHARGE_STATE_INVALID`, `ERR_CO_TENANCY_EVENT_STATE_INVALID`,
    `ERR_KICK_OUT_STATE_INVALID` or `ERR_AUDIT_STATE_INVALID`, each HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_lease_year_reconciling
    """
    scene = setup_year_with_pending_reports(1, suite_code="1801")
    report = scene["reports"][0]
    close_period(scene["lease_year"]["id"])

    validate_error(
        api.submit_sales_report(report["id"],
                                submit_sales_report_payload(30_000_000),
                                make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_LEASE_YEAR_STATE_INVALID.value, 409)

    report_now = read_report(report["id"])
    assert report_now["status"] == "PENDING", (
        "the report's own from-state was legal; the parent year blocked it")
    assert report_now["submitted_at"] is None


def test_frozen_year_leaves_running_totals_untouched_until_it_reopens(api):
    """PRD §3.4: "The ordinary case is `PENDING → SUBMITTED`, which requires the
    owning reporting year to be `OPEN`."
    PRD §3.3: "Reopening moves `RECONCILING → OPEN` and makes both available
    again."
    PRD §3.3: "The year is created `OPEN`, its `lease_id` set from the lease it
    was opened against, its `true_up_delta_cents` null, and its three running
    counters — `cumulative_net_sales_cents`, `cumulative_billed_cents` and
    `open_audit_count` — all at 0."

    Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_lease_year_reconciling
    """
    scene = setup_year_with_pending_reports(1, suite_code="1801")
    report = scene["reports"][0]
    close_period(scene["lease_year"]["id"])

    validate_error(
        api.submit_sales_report(report["id"],
                                submit_sales_report_payload(30_000_000),
                                make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_LEASE_YEAR_STATE_INVALID.value, 409)
    year_after_refusal = read_lease_year(scene["lease_year"]["id"])
    assert year_after_refusal["cumulative_net_sales_cents"] == 0
    assert year_after_refusal["status"] == "RECONCILING"

    reopen(scene["lease_year"]["id"], reason="Tenant filed after the freeze")
    filed = validate_success(
        api.submit_sales_report(report["id"],
                                submit_sales_report_payload(30_000_000),
                                make_tenant_headers(scene["tenant"]["id"])))
    assert filed["status"] == "SUBMITTED"
    assert read_lease_year(scene["lease_year"]["id"])["status"] == "OPEN"


def test_closed_reporting_year_refuses_a_further_reporting_period(api):
    """PRD §3.10: "Once the year is `CLOSED` it is immutable: every mutating
    operation scoped to it is refused with `ERR_LEASE_YEAR_STATE_INVALID`."
    PRD §3.10: "When it is exactly zero, no charge is created at all."

    Design: Corner/state_machines/closed_lease_year_rejects_further_report_scheduling
    """
    scene = setup_lease_year(
        suite_code="4001", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"])
    report = schedule_monthly_report(scene["lease_year"]["id"], 1)
    file_and_accept(report["id"], scene["tenant"]["id"], 30_000_000)
    close_period(scene["lease_year"]["id"])
    reconcile(scene["lease_year"]["id"])
    closed = close_year(scene["lease_year"]["id"])
    assert closed["status"] == "CLOSED"

    start, end = month_period(2)
    validate_error(
        api.create_sales_report(scene["lease_year"]["id"],
                                create_sales_report_payload(start, end),
                                LEASE_ADMIN),
        ApiErrorId.ERR_LEASE_YEAR_STATE_INVALID.value, 409)

    year_now = read_lease_year(scene["lease_year"]["id"])
    assert year_now["status"] == "CLOSED"
    assert year_now["true_up_delta_cents"] == 0
    assert len(reports_for_year(scene["lease_year"]["id"])) == 1
