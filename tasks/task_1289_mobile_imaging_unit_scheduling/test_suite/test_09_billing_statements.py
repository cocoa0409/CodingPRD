"""Billing: PER_DAY vs PER_SCAN provisional pricing, tiered overage, the
zero-scan floor, provisional-vs-final reconciliation, the dispute cycle,
payment exactness, and the monthly period invoice."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_day_to_bundle,
    book_and_complete_appointment,
    complete_site_day,
    drive_day_to_in_service,
    finalize_day_statement,
    get_day_statement,
    get_success_data,
    make_facility_coordinator_headers,
    publish_plan,
    register_and_transmit_study,
    setup_bookable_day,
    setup_completed_day,
    setup_in_service_day,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["operations_director_headers"]


# ---------------------------------------------------------------------------
# Dual-variant pricing on identical day outcomes
# ---------------------------------------------------------------------------

def test_per_day_completed_day_bills_flat_day_rate(api):
    """PRD §3.9: "Under `PER_DAY`: a completed day bills exactly
    `day_rate_cents`;"
    PRD §3.9: "Exactly one statement per site day is auto-created the moment
    the day completes, is cancelled, or is interrupted, carrying the day's
    `site_day_id`, the `contract_id` copied from the day, and
    `billing_model_snapshot` pinned from the contract at creation so later
    contract edits never reprice history."

    Design: Difficulty/dual_variant_calc/per_day_vs_per_scan_identical_day_divergent_billing
    """
    bundle = setup_completed_day(billing_model="PER_DAY")  # zero appointments
    stmt = get_day_statement(bundle["site_day"]["id"])
    assert stmt["billing_model_snapshot"] == "PER_DAY"
    assert stmt["provisional_amount_cents"] == 500000, (
        f"PER_DAY completed day must bill the flat day rate 500000, "
        f"got {stmt['provisional_amount_cents']}"
    )
    assert stmt["status"] == "PROVISIONAL"


def test_per_scan_zero_scan_day_bills_guaranteed_minimum(api):
    """PRD §3.9: "Under `PER_SCAN`: the charge is the billable count up to
    `included_scan_quota` times `scan_rate_cents`, plus any billable count
    beyond the quota times `overage_scan_rate_cents`, plus `no_show_count`
    times `no_show_fee_cents`; and when the day reached `READY` at least once
    yet the billable count is zero, the charge is raised to at least
    `guaranteed_minimum_cents`."

    Design: Difficulty/dual_variant_calc/per_day_vs_per_scan_identical_day_divergent_billing
    """
    # Identical operational outcome as the PER_DAY sibling: zero completed
    # scans on a day that held its full window. The variant diverges: the
    # PER_SCAN day prices its zero-scan floor instead of a flat day rate.
    bundle = setup_completed_day(billing_model="PER_SCAN")  # reached READY
    stmt = get_day_statement(bundle["site_day"]["id"])
    assert stmt["billing_model_snapshot"] == "PER_SCAN"
    assert stmt["completed_scan_count"] == 0
    assert stmt["provisional_amount_cents"] == 200000, (
        f"PER_SCAN zero-scan day must bill the guaranteed minimum 200000, "
        f"got {stmt['provisional_amount_cents']}"
    )


# ---------------------------------------------------------------------------
# Tiered overage and the zero-scan floor
# ---------------------------------------------------------------------------

def test_per_scan_overage_tiers_split_at_quota(api):
    """PRD §3.9: "Under `PER_SCAN`: the charge is the billable count up to
    `included_scan_quota` times `scan_rate_cents`, plus any billable count
    beyond the quota times `overage_scan_rate_cents`, plus `no_show_count`
    times `no_show_fee_cents`".
    PRD §3.9: "The provisional variant, computed at day close, counts every
    `COMPLETED` appointment as billable."

    Design: Difficulty/combinatorial_formula/per_scan_overage_tiers_and_zero_scan_floor
    """
    bundle = setup_in_service_day(
        billing_model="PER_SCAN", contract_overrides={"included_scan_quota": 3}
    )
    for ref, start in (
        ("P-001", "09:00"), ("P-002", "09:40"), ("P-003", "10:20"),
        ("P-004", "11:00"), ("P-005", "11:40"),
    ):
        book_and_complete_appointment(bundle, ref, scheduled_start=start)
    complete_site_day(bundle)

    stmt = get_day_statement(bundle["site_day"]["id"])
    assert stmt["completed_scan_count"] == 5
    # min(5, 3) * 40000 + max(0, 5 - 3) * 45000 = 120000 + 90000.
    assert stmt["provisional_amount_cents"] == 210000, (
        f"Tier split at quota must price 210000, got {stmt['provisional_amount_cents']}"
    )


def test_per_scan_zero_scan_floor_after_ready(api):
    """PRD §3.9: "Under `PER_SCAN`: the charge is the billable count up to
    `included_scan_quota` times `scan_rate_cents`, plus any billable count
    beyond the quota times `overage_scan_rate_cents`, plus `no_show_count`
    times `no_show_fee_cents`; and when the day reached `READY` at least once
    yet the billable count is zero, the charge is raised to at least
    `guaranteed_minimum_cents`."

    Design: Difficulty/combinatorial_formula/per_scan_overage_tiers_and_zero_scan_floor
    """
    bundle = setup_completed_day(billing_model="PER_SCAN")  # zero appointments
    stmt = get_day_statement(bundle["site_day"]["id"])
    assert stmt["completed_scan_count"] == 0
    assert stmt["provisional_amount_cents"] == 200000, (
        f"Day that reached READY with zero billable scans must floor at "
        f"200000, got {stmt['provisional_amount_cents']}"
    )


# ---------------------------------------------------------------------------
# Provisional vs final billable-set reconciliation
# ---------------------------------------------------------------------------

def _setup_per_scan_day_one_undelivered_scan(api):
    """PER_SCAN day with two COMPLETED appointments; only appointment 1's
    study is registered and DELIVERED (500 MB within the 750 MB budget)."""
    bundle = setup_in_service_day(billing_model="PER_SCAN")
    ap1 = book_and_complete_appointment(bundle, "P-001", scheduled_start="09:00")
    register_and_transmit_study(bundle, ap1["id"], "1.2.3.4", 500)
    ap2 = book_and_complete_appointment(bundle, "P-002", scheduled_start="09:40")
    complete_site_day(bundle)
    return bundle, ap1, ap2


def test_provisional_counts_all_completed_scans(api):
    """PRD §3.9: "The provisional variant, computed at day close, counts every
    `COMPLETED` appointment as billable."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_billable_reconciliation
    """
    bundle, _ap1, _ap2 = _setup_per_scan_day_one_undelivered_scan(api)
    stmt = get_day_statement(bundle["site_day"]["id"])
    assert stmt["completed_scan_count"] == 2
    assert stmt["provisional_amount_cents"] == 80000, (
        f"Provisional variant counts both COMPLETED appointments: 2 * 40000, "
        f"got {stmt['provisional_amount_cents']}"
    )


def test_final_counts_only_delivered_studies(api):
    """PRD §3.9: "The final variant, computed at finalization, tightens
    `PER_SCAN` to count only `COMPLETED` appointments whose image study is
    `DELIVERED` or `ACKNOWLEDGED` at that moment — scans without delivered
    images drop out of the billable set."
    PRD §3.9: "An `OperationsDirector` finalizes a `PROVISIONAL` statement
    (`ERR_STATEMENT_NOT_FINALIZABLE` from any other state), which recomputes
    the final variant — including the delivered-image billable set for
    `PER_SCAN` — and restates `net_due_cents` against the final amount."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_billable_reconciliation
    """
    bundle, _ap1, _ap2 = _setup_per_scan_day_one_undelivered_scan(api)
    stmt = get_day_statement(bundle["site_day"]["id"])
    assert stmt["provisional_amount_cents"] == 80000

    finalized = validate_success(api.finalize_billing_statement(stmt["id"], OPS))
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_amount_cents"] == 40000, (
        f"Only the DELIVERED study's appointment is billable at finalize: "
        f"expected 40000, got {finalized['final_amount_cents']}"
    )
    assert finalized["net_due_cents"] == 40000
    # The reconciliation delta is exactly the undelivered scan's 40000.
    assert stmt["provisional_amount_cents"] - finalized["final_amount_cents"] == 40000


# ---------------------------------------------------------------------------
# Finalize / dispute / resolve-dispute cycle
# ---------------------------------------------------------------------------

def _setup_finalized_per_day_statement(api):
    bundle = setup_completed_day(billing_model="PER_DAY")
    stmt = finalize_day_statement(bundle["site_day"]["id"])
    assert stmt["final_amount_cents"] == 500000
    return bundle, stmt


def test_finalize_dispute_moves_statement_to_disputed(api):
    """PRD §3.9: "A `FacilityCoordinator` of the statement's own facility may
    dispute a `FINALIZED` statement with a `reason` (a coordinator from another
    facility is refused with `ERR_FACILITY_MISMATCH`, and a non-finalized
    statement with `ERR_INVALID_STATE`), moving it to `DISPUTED`."

    Design: Difficulty/non_linear_state_machine/billing_statement_finalize_dispute_readjust_cycle
    """
    bundle, stmt = _setup_finalized_per_day_statement(api)
    coord = make_facility_coordinator_headers(bundle["facility"]["id"])
    resp = api.dispute_billing_statement(stmt["id"], {"reason": "day ended early"}, coord)
    data = validate_success(resp)
    assert data["status"] == "DISPUTED", (
        f"Dispute must move FINALIZED to DISPUTED, got {data['status']}"
    )


def test_resolve_dispute_adjust_rewrites_final_amount(api):
    """PRD §3.9: "An `OperationsDirector` resolves the dispute with a
    `resolution`: `UPHOLD` returns the statement to `FINALIZED` with amounts
    unchanged, while `ADJUST` overwrites `final_amount_cents` with the supplied
    `adjusted_amount_cents` and recomputes `net_due_cents`; the `FINALIZED` →
    `DISPUTED` → `FINALIZED` cycle may repeat."

    Design: Difficulty/non_linear_state_machine/billing_statement_finalize_dispute_readjust_cycle
    """
    bundle, stmt = _setup_finalized_per_day_statement(api)
    coord = make_facility_coordinator_headers(bundle["facility"]["id"])
    get_success_data(
        api.dispute_billing_statement(stmt["id"], {"reason": "day ended early"}, coord)
    )
    resolved = validate_success(
        api.resolve_dispute_billing_statement(
            stmt["id"], {"resolution": "ADJUST", "adjusted_amount_cents": 450000}, OPS
        )
    )
    assert resolved["status"] == "FINALIZED", (
        f"ADJUST resolution returns the statement to FINALIZED, got {resolved['status']}"
    )
    assert resolved["final_amount_cents"] == 450000
    assert resolved["net_due_cents"] == 450000


# ---------------------------------------------------------------------------
# Payment exactness
# ---------------------------------------------------------------------------

def test_mark_paid_amount_mismatch_rejected(api):
    """PRD §3.9: "From `FINALIZED`, invoicing moves the statement to
    `INVOICED`, and marking it paid requires the tendered `paid_amount_cents`
    to equal `net_due_cents` exactly — anything else is
    `ERR_PAYMENT_AMOUNT_MISMATCH` — before the statement lands in its terminal
    `PAID` state."

    Design: Corner/validations/mark_paid_amount_mismatch_rejected
    """
    bundle, stmt = _setup_finalized_per_day_statement(api)
    get_success_data(api.invoice_billing_statement(stmt["id"], OPS))

    resp = api.mark_paid_billing_statement(stmt["id"], {"paid_amount_cents": 499999}, OPS)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

    paid = validate_success(
        api.mark_paid_billing_statement(stmt["id"], {"paid_amount_cents": 500000}, OPS)
    )
    assert paid["status"] == "PAID", f"Exact net due must land PAID, got {paid['status']}"


# ---------------------------------------------------------------------------
# Period invoice: tier on gross, provisional exclusion
# ---------------------------------------------------------------------------

def _setup_two_completed_per_day_days(api):
    """Two zero-appointment PER_DAY days (2026-08-04, 2026-08-05), both
    COMPLETED; returns (bundle, day1, day2)."""
    bundle = setup_bookable_day(publish=False)
    day1 = bundle["site_day"]
    day2 = add_day_to_bundle(bundle, "2026-08-05")
    publish_plan(bundle["plan"]["id"])
    drive_day_to_in_service(bundle, site_day=day1)
    complete_site_day(bundle, day1["id"])
    drive_day_to_in_service(bundle, site_day=day2, technologist=bundle["technologist"])
    complete_site_day(bundle, day2["id"])
    bundle["site_day"] = day1
    return bundle, day1, day2


def test_period_invoice_tier_selected_on_gross(api):
    """PRD §3.9: "The volume tier is then selected on the gross — never on the
    discounted figure, which would be circular: a gross of at least 1,000,000
    cents earns 8 percent, a gross of at least 500,000 cents earns 5 percent,
    and anything below earns nothing."

    Design: Difficulty/combinatorial_formula/period_invoice_tier_on_gross
    """
    bundle, day1, day2 = _setup_two_completed_per_day_days(api)
    finalize_day_statement(day1["id"])
    finalize_day_statement(day2["id"])

    resp = api.get_period_invoice(bundle["contract"]["id"], "2026-08", OPS)
    data = validate_success(resp)
    assert data["gross_cents"] == 1000000, (
        f"Gross must be 500000 + 500000, got {data['gross_cents']}"
    )
    # The >= 1000000 boundary is inclusive and the tier reads the gross, not
    # the discounted net (a net-based read would wrongly land on 5%).
    assert data["tier_pct"] == 8, f"Gross 1000000 must earn 8 percent, got {data['tier_pct']}"


def test_period_invoice_discount_and_net(api):
    """PRD §3.9: "The `discount_cents` is the gross multiplied by the selected
    `tier_pct` and divided by one hundred, rounded half-up to whole cents, and
    `net_cents` is the gross minus the discount."

    Design: Difficulty/combinatorial_formula/period_invoice_tier_on_gross
    """
    bundle, day1, day2 = _setup_two_completed_per_day_days(api)
    finalize_day_statement(day1["id"])
    finalize_day_statement(day2["id"])

    data = validate_success(api.get_period_invoice(bundle["contract"]["id"], "2026-08", OPS))
    assert data["gross_cents"] == 1000000
    assert data["tier_pct"] == 8
    assert data["discount_cents"] == 80000, (
        f"round_half_up(1000000 * 8 / 100) must be 80000, got {data['discount_cents']}"
    )
    assert data["net_cents"] == 920000, (
        f"net must be 1000000 - 80000 = 920000, got {data['net_cents']}"
    )


def test_period_invoice_excludes_provisional_statements(api):
    """PRD §3.9: "Given a `month` (`YYYY-MM`), the period invoice sums
    `net_due_cents` over the contract's statements in `FINALIZED`, `INVOICED`,
    or `PAID` whose site day's `service_date` falls inside that month,
    inclusive of both ends, yielding `gross_cents`."

    Design: Corner/endpoints/period_invoice_excludes_provisional_statements
    """
    bundle, day1, day2 = _setup_two_completed_per_day_days(api)
    finalize_day_statement(day1["id"])
    # day2's statement stays PROVISIONAL and must be excluded from the rollup.

    data = validate_success(api.get_period_invoice(bundle["contract"]["id"], "2026-08", OPS))
    assert data["gross_cents"] == 500000, (
        f"Only the FINALIZED statement counts, got gross {data['gross_cents']}"
    )
    assert data["tier_pct"] == 5, (
        f"Gross 500000 hits the >= 500000 boundary at 5 percent, got {data['tier_pct']}"
    )
    assert data["discount_cents"] == 25000
    assert data["net_cents"] == 475000
