"""Invoicing: the TM vs LUMP_SUM amount variants, retainage rounding and
release, the NTE cap, billable-content and FINAL-invoice fiscal rules, and
project completion terminality (PRD section 3.9)."""
from test_helpers import (
    ApiErrorId,
    advance_project,
    assert_invoice,
    create_approved_labor_entry,
    create_invoice,
    find_labor_entry,
    get_project,
    list_invoices,
    setup_project_commissioning,
    setup_project_completed,
    setup_project_mobilized,
    setup_signed_off_checklist,
    setup_tm_billable_scenario,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Dual variant: TM bills approved actuals, LUMP_SUM bills cumulative progress
# ---------------------------------------------------------------------------

def test_tm_invoice_bills_approved_actuals(api, pm_headers):
    """PRD section 3.9: "The labor portion is the sum of `total_cost_cents`
    over the project's labor entries standing `APPROVED` whose `work_date`
    falls within the inclusive billing period; the equipment portion is the
    sum of `equipment_charge_cents` over the project's lift permits standing
    `EXECUTED` whose `lift_starts_at` calendar date falls within the same
    inclusive period."
    PRD section 3.9: "The `retainage_cents` is the `gross_cents` multiplied by
    the project's `retainage_pct`, rounded half-up — computed exactly once on
    the summed gross, never line by line."
    PRD section 3.9: "The payable `amount_cents` is `gross_cents` minus
    `retainage_cents` plus `retainage_released_cents`."

    Design: Difficulty/dual_variant_calc/invoice_tm_vs_lump_sum_divergence
    """
    ctx = setup_tm_billable_scenario(name="TM Press Install", site_address="1 Plant Rd")
    project = ctx["project"]
    entry = ctx["labor_entry"]
    permit = ctx["lift_permit"]
    assert entry["total_cost_cents"] == 84800
    assert permit["equipment_charge_cents"] == 180000

    invoice = create_invoice(project["id"], kind="PROGRESS")
    assert_invoice(invoice)
    assert invoice["billing_mode_snapshot"] == "TM"
    # 84800 labor + 180000 equipment.
    assert invoice["gross_cents"] == 264800, (
        f"TM gross bills approved actuals: expected 264800, got {invoice['gross_cents']}"
    )
    assert invoice["retainage_cents"] == 26480
    assert invoice["retainage_released_cents"] == 0
    assert invoice["amount_cents"] == 238320
    assert entry["id"] in invoice["labor_entry_ids"]
    assert permit["id"] in invoice["lift_permit_ids"]

    assert find_labor_entry(project["id"], entry["id"])["status"] == "INVOICED", (
        "Issuing the invoice marks each included labor entry INVOICED"
    )


def test_lump_sum_invoice_bills_cumulative_progress(api, pm_headers):
    """PRD section 3.9: "The cumulative billing target is the project's
    `contract_amount_cents` multiplied by `progress_pct` and divided by one
    hundred, rounded half-up to whole cents; the invoice's `gross_cents` is
    that target minus the sum of `gross_cents` over all prior invoices of the
    project."
    PRD section 3.9: "Issuing the invoice marks each included labor entry
    `INVOICED` — the entry's terminal state — and the invoice records which
    rows it swept up in `labor_entry_ids` and `lift_permit_ids`; both lists
    stay empty on lump-sum work."

    Design: Difficulty/dual_variant_calc/invoice_tm_vs_lump_sum_divergence
    """
    tm_ctx = setup_tm_billable_scenario(name="TM Press Install", site_address="1 Plant Rd")
    ls_ctx = setup_project_mobilized(
        name="LS Conveyor Install",
        customer_name="Beta Foods",
        site_address="9 Mill Ave",
        billing_mode="LUMP_SUM",
    )

    tm_invoice = create_invoice(tm_ctx["project"]["id"], kind="PROGRESS")
    ls_invoice = create_invoice(
        ls_ctx["project"]["id"], kind="PROGRESS", progress_pct=10
    )

    # round_half_up(5000000 * 10 / 100) = 500000, no prior invoices.
    assert ls_invoice["billing_mode_snapshot"] == "LUMP_SUM"
    assert ls_invoice["gross_cents"] == 500000, (
        f"LUMP_SUM gross bills cumulative progress: expected 500000, got "
        f"{ls_invoice['gross_cents']}"
    )
    assert ls_invoice["retainage_cents"] == 50000
    assert ls_invoice["amount_cents"] == 450000
    assert ls_invoice["labor_entry_ids"] == []
    assert ls_invoice["lift_permit_ids"] == []

    assert tm_invoice["gross_cents"] == 264800
    assert tm_invoice["gross_cents"] != ls_invoice["gross_cents"], (
        "Same billing period, different billing variants must diverge"
    )


# ---------------------------------------------------------------------------
# Combinatorial formula: retainage rounded once on the summed gross
# ---------------------------------------------------------------------------

def _setup_three_approved_entries(api, pm_headers):
    """TM project in MOBILIZED with three APPROVED 8.5h MW_JOURNEYMAN DAY
    entries (total_cost_cents 92225 each)."""
    ctx = setup_project_mobilized(name="Rounding Job", site_address="4 Plant Rd")
    entries = [
        create_approved_labor_entry(
            ctx["project"]["id"],
            worker_ref=f"U-400{i}",
            work_date="2026-08-09",
            hours_worked=8.5,
        )
        for i in (1, 2, 3)
    ]
    return ctx, entries


def test_retainage_rounded_once_on_summed_gross(api, pm_headers):
    """PRD section 3.9: "The `retainage_cents` is the `gross_cents` multiplied
    by the project's `retainage_pct`, rounded half-up — computed exactly once
    on the summed gross, never line by line."
    PRD section 2.8: "Retainage on an invoice is likewise rounded half-up
    exactly once, computed on the summed gross and never line by line."

    Design: Difficulty/combinatorial_formula/invoice_retainage_rounding_on_summed_gross
    """
    ctx, entries = _setup_three_approved_entries(api, pm_headers)
    for entry in entries:
        # straight 68000 + overtime round_half_up(0.5*8500*1.5)=6375 + fringe
        # round_half_up(8.5*2100)=17850.
        assert entry["total_cost_cents"] == 92225

    invoice = create_invoice(ctx["project"]["id"], kind="PROGRESS")
    assert invoice["gross_cents"] == 276675, (
        f"3 x 92225 = 276675, got {invoice['gross_cents']}"
    )
    # Sum-then-round: round_half_up(276675 * 0.10) = round_half_up(27667.5) = 27668.
    assert invoice["retainage_cents"] == 27668, (
        f"Retainage rounds once on the summed gross: expected 27668, got "
        f"{invoice['retainage_cents']}"
    )


def test_retainage_per_line_order_would_differ(api, pm_headers):
    """PRD section 2.8: "Retainage on an invoice is likewise rounded half-up
    exactly once, computed on the summed gross and never line by line."
    PRD section 3.9: "The payable `amount_cents` is `gross_cents` minus
    `retainage_cents` plus `retainage_released_cents`."

    Design: Difficulty/combinatorial_formula/invoice_retainage_rounding_on_summed_gross
    """
    ctx, _entries = _setup_three_approved_entries(api, pm_headers)
    invoice = create_invoice(ctx["project"]["id"], kind="PROGRESS")

    per_line_total = 3 * 9223  # round_half_up(92225 * 0.10) per line = 27669
    assert invoice["retainage_cents"] == 27668
    assert invoice["retainage_cents"] != per_line_total, (
        "The per-line rounding order (27669) must NOT be what the system produces"
    )
    # 276675 - 27668 + 0.
    assert invoice["amount_cents"] == 249007


# ---------------------------------------------------------------------------
# Corner calculations
# ---------------------------------------------------------------------------

def test_final_invoice_releases_retainage(api, pm_headers):
    """PRD section 3.9: "A `FINAL` invoice additionally releases everything
    previously withheld: its `retainage_released_cents` is the sum of
    `retainage_cents` across all prior invoices of the project, while a
    `PROGRESS` invoice releases zero."
    PRD section 3.9: "Two further fiscal rules apply: a project may have at
    most one `FINAL` invoice, with a second attempt rejected as
    `ERR_FINAL_INVOICE_EXISTS`, and a `PROGRESS` invoice must have positive
    billable content — a gross of zero or less is rejected with
    `ERR_NO_BILLABLE_WORK`, while a `FINAL` invoice is exempt from this rule
    so that a pure retainage release remains possible."

    Design: Corner/calculations/final_invoice_releases_retainage
    """
    ctx = setup_tm_billable_scenario(name="Final Invoice Job", site_address="35 Plant Rd")
    project = ctx["project"]
    advance_project(project["id"])  # INSTALLING -> COMMISSIONING (executed lift present)

    progress = create_invoice(project["id"], kind="PROGRESS")
    assert progress["gross_cents"] == 264800
    assert progress["retainage_cents"] == 26480

    setup_signed_off_checklist(project["id"])
    completed = advance_project(project["id"])  # COMMISSIONING -> COMPLETED
    assert completed["work_status"] == "COMPLETED"

    final = create_invoice(
        project["id"], kind="FINAL", period_start="2026-09-01", period_end="2026-09-30"
    )
    assert_invoice(final)
    assert final["gross_cents"] == 0, (
        "The swept labor entry is INVOICED and no September work exists"
    )
    assert final["retainage_released_cents"] == 26480, (
        "FINAL releases the retainage withheld on the PROGRESS invoice"
    )
    assert final["amount_cents"] == 26480, (
        "Pure retainage release: 0 gross - 0 retainage + 26480 released"
    )


def test_lump_sum_second_progress_cumulative(api, pm_headers):
    """PRD section 3.9: "The cumulative billing target is the project's
    `contract_amount_cents` multiplied by `progress_pct` and divided by one
    hundred, rounded half-up to whole cents; the invoice's `gross_cents` is
    that target minus the sum of `gross_cents` over all prior invoices of the
    project."

    Design: Corner/calculations/lump_sum_second_progress_cumulative
    """
    ctx = setup_project_mobilized(
        name="Progress Job",
        customer_name="Beta Foods",
        site_address="36 Mill Ave",
        billing_mode="LUMP_SUM",
    )
    project = ctx["project"]

    first = create_invoice(
        project["id"],
        kind="PROGRESS",
        period_start="2026-08-01",
        period_end="2026-08-15",
        progress_pct=10,
    )
    assert first["gross_cents"] == 500000

    second = create_invoice(
        project["id"],
        kind="PROGRESS",
        period_start="2026-08-16",
        period_end="2026-08-31",
        progress_pct=25,
    )
    # Cumulative target round_half_up(5000000 * 25 / 100) = 1250000, less the
    # 500000 already invoiced.
    assert second["gross_cents"] == 750000, (
        f"Second invoice bills the increment 1250000 - 500000 = 750000, got "
        f"{second['gross_cents']}"
    )
    assert second["retainage_cents"] == 75000
    assert second["amount_cents"] == 675000


# ---------------------------------------------------------------------------
# Fiscal gates
# ---------------------------------------------------------------------------

def test_nte_exceeded_on_tm_invoice(api, pm_headers):
    """PRD section 3.9: "Time-and-materials billing is capped: if the sum of
    all prior invoices' `gross_cents` plus this invoice's `gross_cents` would
    exceed the project's `contract_amount_cents` not-to-exceed cap, creation
    is rejected with `ERR_NTE_EXCEEDED`."

    Design: Corner/validations/nte_exceeded_on_tm_invoice
    """
    ctx = setup_tm_billable_scenario(
        name="NTE Job",
        site_address="39 Plant Rd",
        contract_amount_cents=100000,
        labor_hours=10,  # 114500 approved, over the 100000 cap
        with_lift=False,
    )
    project = ctx["project"]
    entry = ctx["labor_entry"]
    assert entry["total_cost_cents"] == 114500

    resp = api.create_invoice(
        {
            "project_id": project["id"],
            "kind": "PROGRESS",
            "period_start": "2026-08-09",
            "period_end": "2026-08-09",
        },
        pm_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NTE_EXCEEDED)

    assert find_labor_entry(project["id"], entry["id"])["status"] == "APPROVED", (
        "A rejected invoice must not mark labor entries INVOICED"
    )
    assert list_invoices(project["id"]) == []


def test_no_billable_work_on_empty_period(api, pm_headers):
    """PRD section 3.9: "Two further fiscal rules apply: a project may have at
    most one `FINAL` invoice, with a second attempt rejected as
    `ERR_FINAL_INVOICE_EXISTS`, and a `PROGRESS` invoice must have positive
    billable content — a gross of zero or less is rejected with
    `ERR_NO_BILLABLE_WORK`, while a `FINAL` invoice is exempt from this rule
    so that a pure retainage release remains possible."

    Design: Corner/validations/no_billable_work_on_empty_period
    """
    ctx = setup_project_mobilized(name="Empty Bill Job", site_address="40 Plant Rd")
    project = ctx["project"]

    resp = api.create_invoice(
        {
            "project_id": project["id"],
            "kind": "PROGRESS",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
        },
        pm_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NO_BILLABLE_WORK)
    assert list_invoices(project["id"]) == []


def test_final_invoice_exists(api, pm_headers):
    """PRD section 3.9: "Two further fiscal rules apply: a project may have at
    most one `FINAL` invoice, with a second attempt rejected as
    `ERR_FINAL_INVOICE_EXISTS`, and a `PROGRESS` invoice must have positive
    billable content — a gross of zero or less is rejected with
    `ERR_NO_BILLABLE_WORK`, while a `FINAL` invoice is exempt from this rule
    so that a pure retainage release remains possible."

    Design: Corner/validations/final_invoice_exists
    """
    ctx = setup_project_completed(name="Double Final Job", site_address="41 Plant Rd")
    project = ctx["project"]
    assert project["work_status"] == "COMPLETED"

    first = create_invoice(project["id"], kind="FINAL")
    assert first["kind"] == "FINAL"

    resp = api.create_invoice(
        {
            "project_id": project["id"],
            "kind": "FINAL",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
        },
        pm_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FINAL_INVOICE_EXISTS)

    finals = [inv for inv in list_invoices(project["id"]) if inv["kind"] == "FINAL"]
    assert len(finals) == 1, "At most one FINAL invoice may exist per project"


# ---------------------------------------------------------------------------
# Priority pair: state beats fiscal
# ---------------------------------------------------------------------------

def _setup_completed_project_over_nte(api):
    """TM project with NTE 100000 run to COMPLETED, carrying one APPROVED 10h
    MW_JOURNEYMAN DAY entry (114500) — gross would breach the cap if the
    phase gate allowed the invoice."""
    ctx = setup_project_commissioning(
        name="Conflict Job", site_address="10 Plant Rd", contract_amount_cents=100000
    )
    entry = create_approved_labor_entry(
        ctx["project"]["id"], worker_ref="U-7001", work_date="2026-08-09", hours_worked=10
    )
    ctx["labor_entry"] = entry
    setup_signed_off_checklist(ctx["project"]["id"])
    ctx["project"] = advance_project(ctx["project"]["id"])  # -> COMPLETED
    return ctx


def test_progress_invoice_on_completed_project_is_invalid_state(api, pm_headers):
    """PRD section 3.9: "Phase gates apply at creation: a `PROGRESS` invoice
    requires the project to be in `MOBILIZED`, `INSTALLING`, or
    `COMMISSIONING`, while a `FINAL` invoice requires `COMPLETED`; issuing
    against the wrong phase fails with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/invoice_state_beats_fiscal
    """
    ctx = _setup_completed_project_over_nte(api)
    project = ctx["project"]
    assert project["work_status"] == "COMPLETED"
    assert ctx["labor_entry"]["total_cost_cents"] == 114500

    resp = api.create_invoice(
        {
            "project_id": project["id"],
            "kind": "PROGRESS",
            "period_start": "2026-08-09",
            "period_end": "2026-08-09",
        },
        pm_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_invalid_state_beats_nte_exceeded(api, pm_headers):
    """PRD section 2.6: "State and phase validity comes next
    (`ERR_INVALID_STATE`), then segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`), and only then request-schema validation —
    required fields present, enum members valid, ranges respected, and
    conditional requirements met (`ERR_VALIDATION`)."
    PRD section 2.6: "Temporal rules are evaluated after those
    (`ERR_INVALID_WINDOW`, `ERR_LOCKOUT_CONFLICT`,
    `ERR_CRANE_WINDOW_CONFLICT`, `ERR_OUTSIDE_LIFT_WINDOW`), then the fiscal
    rules (`ERR_NTE_EXCEEDED`, `ERR_FINAL_INVOICE_EXISTS`,
    `ERR_NO_BILLABLE_WORK`)."

    Design: Difficulty/priority_pair_validation_conflict/invoice_state_beats_fiscal
    """
    ctx = _setup_completed_project_over_nte(api)
    project = ctx["project"]

    resp = api.create_invoice(
        {
            "project_id": project["id"],
            "kind": "PROGRESS",
            "period_start": "2026-08-09",
            "period_end": "2026-08-09",
        },
        pm_headers,
    )
    err = resp.json()["data"]["error_id"]
    assert err == "ERR_INVALID_STATE", (
        f"Phase gate must fire before the fiscal NTE check, got {err}"
    )
    assert err != "ERR_NTE_EXCEEDED", (
        "Gross 114500 would breach the 100000 NTE cap, but state validity wins"
    )
    assert list_invoices(project["id"]) == [], "No invoice row may be created"


# ---------------------------------------------------------------------------
# Terminal work phase
# ---------------------------------------------------------------------------

def test_project_advance_from_completed_rejected(api, pm_headers):
    """PRD section 3.1: "`COMPLETED` is terminal: any attempt to advance a
    completed project is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/project_advance_from_completed_rejected
    """
    ctx = setup_project_completed(name="SM10 Job", site_address="32 Plant Rd")
    project = ctx["project"]
    assert project["work_status"] == "COMPLETED"

    resp = api.advance_project(project["id"], pm_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_project(project["id"])["work_status"] == "COMPLETED"
