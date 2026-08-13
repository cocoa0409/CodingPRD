"""Form 1099-B lifecycle: generation, filing, the correction cycle, the
statute window, freezing, and aggregation scoping.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, ApiErrorId, TEST_USERS,
    setup_book, setup_settled_sale, setup_wash_sale_scenario,
    make_lot, make_disposition, settle,
    setup_draft_form, generate_form, setup_filed_form,
    setup_settled_sale_with_filed_form,
    get_customer_version,
    DEFAULT_STARTUP_CLOCK, PAST_CORRECTION_DEADLINE_CLOCK,
    assert_tax_form_1099b,
)

TAX_OPS = TEST_USERS["tax_ops_headers"]
FIRM_ADMIN = TEST_USERS["firm_admin_headers"]


def _get_form(s):
    return validate_success(
        api_client.get_tax_form(s["firm"]["id"], s["customer"]["id"], s["form"]["id"], TAX_OPS)
    )


def _settled_replacement_id(api, firm_id, account_id):
    """The account's single SETTLED disposition (the replacement row after a
    correction)."""
    data, _meta = validate_paginated(
        api.list_dispositions(firm_id, account_id, TAX_OPS, params={"status": "SETTLED"})
    )
    assert len(data) == 1
    return data[0]["id"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / form_1099b_correction_cycle_loop
# ---------------------------------------------------------------------------

def _cycle_setup():
    """One settled covered disposition (10 sh, basis 10000, proceeds 15000) +
    a FILED 2025 form."""
    return setup_settled_sale_with_filed_form(tin="TIN-CY-1", cusip="777777777")


def test_correction_cycle_first_loop(api):
    """PRD §3.8: "Three in-scope events flip a `FILED` form to
    `CORRECTION_PENDING` automatically, incrementing the customer's `version`:
    a disposition in scope is corrected, a basis change request in scope
    reaches `APPLIED`, or a wash-sale event is created in scope after filing.
    Refiling — again `FirmAdmin` — re-runs the aggregation against the
    corrected source data, overwrites every total, increments
    `correction_count` (which starts at zero on a fresh form)."

    Design: Difficulty/non_linear_state_machine/form_1099b_correction_cycle_loop
    """
    s = _cycle_setup()
    validate_success(api.correct_disposition(s["firm"]["id"], s["disposition"]["id"],
                                             {"proceeds_cents": 16000}, TAX_OPS))
    assert _get_form(s)["status"] == "CORRECTION_PENDING"
    refiled = validate_success(api.refile_tax_form(s["firm"]["id"], s["customer"]["id"], s["form"]["id"], FIRM_ADMIN))
    assert_tax_form_1099b(refiled)
    assert refiled["correction_count"] == 1, "FILED -> CORRECTION_PENDING -> REFILED once"
    assert refiled["status"] == "REFILED"
    assert refiled["short_term_proceeds_cents"] == 16000


def test_correction_cycle_loops_unbounded(api):
    """PRD §3.8: "Further qualifying changes flip a `REFILED` form back to
    `CORRECTION_PENDING` — the loop between filed and correction-pending is
    unbounded while the window stays open."

    Design: Difficulty/non_linear_state_machine/form_1099b_correction_cycle_loop
    """
    s = _cycle_setup()
    # First loop: correct the original disposition, refile.
    validate_success(api.correct_disposition(s["firm"]["id"], s["disposition"]["id"],
                                             {"proceeds_cents": 16000}, TAX_OPS))
    validate_success(api.refile_tax_form(s["firm"]["id"], s["customer"]["id"], s["form"]["id"], FIRM_ADMIN))
    # Second loop: correct the live replacement disposition, refile again.
    replacement_id = _settled_replacement_id(api, s["firm"]["id"], s["account"]["id"])
    validate_success(api.correct_disposition(s["firm"]["id"], replacement_id,
                                             {"proceeds_cents": 17000}, TAX_OPS))
    assert _get_form(s)["status"] == "CORRECTION_PENDING", "REFILED flips back to CORRECTION_PENDING"
    refiled = validate_success(api.refile_tax_form(s["firm"]["id"], s["customer"]["id"], s["form"]["id"], FIRM_ADMIN))
    assert refiled["correction_count"] == 2, "the cycle looped twice"
    assert refiled["status"] == "REFILED"
    assert refiled["short_term_proceeds_cents"] == 17000, "re-aggregated with the second corrected disposition"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / long_term_threshold_365_day_boundary
# ---------------------------------------------------------------------------

def _term_boundary_form(api):
    """365-day lot (2024-06-10) and 366-day lot (2024-06-09), each sold
    2025-06-10 for 15000 via SPECIFIC_ID; returns (scenario, generated form)."""
    s = setup_book(tin="TIN-BD-3", cusip="111111118", ticker="TRM")
    lot365 = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                      acquisition_date="2024-06-10T00:00:00Z", quantity=10, basis=10000)
    lot366 = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                      acquisition_date="2024-06-09T00:00:00Z", quantity=10, basis=10000)
    for lot in (lot365, lot366):
        disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                                quantity=10, proceeds=15000, method="SPECIFIC_ID",
                                lot_allocations=[{"lot_id": lot["id"], "quantity": 10}])
        settle(s["firm"]["id"], disp["id"])
    form = setup_draft_form(s["firm"]["id"], s["customer"]["id"], 2025)
    generated = generate_form(s["firm"]["id"], s["customer"]["id"], form["id"])
    return s, generated


def test_exactly_365_days_remains_short_term(api):
    """PRD §3.3: "the holding days are counted from the sold lot's
    `holding_period_start` to the disposition's `trade_date`, and the
    allocation is long-term only when that count strictly exceeds 365 days. A
    count of exactly 365 days remains short-term."

    Design: Difficulty/boundary_precision_check/long_term_threshold_365_day_boundary
    """
    _s, form = _term_boundary_form(api)
    assert form["short_term_proceeds_cents"] == 15000, "the 365-day lot is SHORT_TERM"
    assert form["short_term_basis_cents"] == 10000


def test_366_days_is_long_term(api):
    """PRD §3.3: "the allocation is long-term only when that count strictly
    exceeds 365 days."

    Design: Difficulty/boundary_precision_check/long_term_threshold_365_day_boundary
    """
    _s, form = _term_boundary_form(api)
    assert form["long_term_proceeds_cents"] == 15000, "the 366-day lot is LONG_TERM"
    assert form["long_term_basis_cents"] == 10000


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / form_file_gated_by_customer_version
# ---------------------------------------------------------------------------

def _generated_then_suspend():
    s = setup_settled_sale(tin="TIN-XD-1", cusip="111111119")
    form = setup_draft_form(s["firm"]["id"], s["customer"]["id"], 2025)
    generate_form(s["firm"]["id"], s["customer"]["id"], form["id"])
    validate_success(api_client.suspend_customer(s["firm"]["id"], s["customer"]["id"], FIRM_ADMIN))
    s["form"] = form
    return s


def test_file_rejected_when_customer_mutated_since_generate(api):
    """PRD §3.8: "Filing is a `FirmAdmin` act with a freshness guard: the form
    must be `GENERATED`, and the customer's current `version` must still equal
    `generated_from_version`, proving the customer's lot universe has not
    shifted since generation; a drifted form rejects with
    `ERR_STALE_FORM_VERSION` (HTTP 412)."
    PRD §2.4: "`version` (integer): a mutation counter that increments by one
    on every change to the resource, cascades included."

    Design: Difficulty/cross_entity_state_dependency/form_file_gated_by_customer_version
    """
    s = _generated_then_suspend()
    resp = api.file_tax_form(s["firm"]["id"], s["customer"]["id"], s["form"]["id"], FIRM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_FORM_VERSION)


def test_stale_file_leaves_form_generated(api):
    """PRD §3.8: "a drifted form rejects with `ERR_STALE_FORM_VERSION`
    (HTTP 412)."

    Design: Difficulty/cross_entity_state_dependency/form_file_gated_by_customer_version
    """
    s = _generated_then_suspend()
    validate_error(
        api.file_tax_form(s["firm"]["id"], s["customer"]["id"], s["form"]["id"], FIRM_ADMIN),
        ApiErrorId.ERR_STALE_FORM_VERSION,
    )
    assert _get_form(s)["status"] == "GENERATED", "rejected file leaves the form unchanged"


# ---------------------------------------------------------------------------
# Corner: state_machines / wash-sale invalidation + correction cascade
# ---------------------------------------------------------------------------

def test_settle_wash_sale_invalidates_generated_form_back_to_draft(api):
    """PRD §3.4: "A detected wash sale also reaches forward into reporting: any
    1099-B for this customer and tax year still sitting in `DRAFT` or
    `GENERATED` is invalidated back to `DRAFT` and must be regenerated (§3.8)."

    Design: Corner/state_machines/settle_wash_sale_invalidates_generated_form_back_to_draft
    """
    s = setup_wash_sale_scenario(tin="TIN-SM-8", cusip="212121212")
    form = setup_draft_form(s["firm"]["id"], s["customer"]["id"], 2025)
    generate_form(s["firm"]["id"], s["customer"]["id"], form["id"])
    settle(s["firm"]["id"], s["disposition"]["id"])
    form_after = validate_success(api.get_tax_form(s["firm"]["id"], s["customer"]["id"], form["id"], TAX_OPS))
    assert form_after["status"] == "DRAFT", "settle with wash-sale detection invalidated the GENERATED form"


def test_disposition_correct_marks_filed_form_correction_pending(api):
    """PRD §3.5: "The original row becomes `CORRECTED`, a terminal audit
    marker, and any 1099-B for this customer and tax year in `GENERATED`,
    `FILED`, or `CORRECTION_PENDING` is marked `CORRECTION_PENDING`, feeding
    the correction cycle of §3.8."

    Design: Corner/state_machines/disposition_correct_marks_filed_form_correction_pending
    """
    s = setup_settled_sale_with_filed_form(tin="TIN-SM-9", cusip="222222223")
    validate_success(api.correct_disposition(s["firm"]["id"], s["disposition"]["id"],
                                             {"proceeds_cents": 15500}, TAX_OPS))
    assert _get_form(s)["status"] == "CORRECTION_PENDING"


def test_form_generate_on_nondraft_rejected(api):
    """PRD §3.8: "Generation — `TaxOps` only, guarded by the customer-level
    concurrency check of §2.8 — is allowed while the form is `DRAFT` and the
    customer is anything but `CLOSED`."

    Design: Corner/state_machines/form_generate_on_nondraft_rejected
    """
    s = setup_settled_sale(tin="TIN-SM-12", cusip="252525252")
    form = setup_draft_form(s["firm"]["id"], s["customer"]["id"], 2025)
    generate_form(s["firm"]["id"], s["customer"]["id"], form["id"])
    version = get_customer_version(s["firm"]["id"], s["customer"]["id"])
    resp = api.generate_tax_form(s["firm"]["id"], s["customer"]["id"], form["id"],
                                 {"expected_customer_version": version}, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


# ---------------------------------------------------------------------------
# Corner: calculations / aggregation scoping and Box 1g
# ---------------------------------------------------------------------------

def test_form_1099b_aggregation_excludes_noncovered(api):
    """PRD §3.8: "The aggregation sweeps every disposition on every account of
    the customer whose `status` is `SETTLED` — corrected dispositions are
    excluded, because each was replaced by a new row — whose `trade_date` falls
    inside the form's `tax_year`, and which consumed at least one `COVERED`
    lot. Dispositions that touched only noncovered lots are not reported on the
    1099-B at all; they live in the customer's own records."

    Design: Corner/calculations/form_1099b_aggregation_excludes_noncovered
    """
    s = setup_book(tin="TIN-CALC-12", cusip="414141414", ticker="AGG")
    lot_nc = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                      acquisition_date="2010-06-01T00:00:00Z", quantity=10, basis=8000)
    lot_c = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                     acquisition_date="2025-01-05T00:00:00Z", quantity=10, basis=10000)
    assert lot_nc["covered_status"] == "NONCOVERED"
    assert lot_c["covered_status"] == "COVERED"
    disp_nc = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                               quantity=10, proceeds=12000, method="SPECIFIC_ID",
                               lot_allocations=[{"lot_id": lot_nc["id"], "quantity": 10}])
    settle(s["firm"]["id"], disp_nc["id"])
    disp_c = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                              quantity=10, proceeds=15000, method="SPECIFIC_ID",
                              trade_date="2025-06-12T00:00:00Z", settlement_date="2025-06-13T00:00:00Z",
                              lot_allocations=[{"lot_id": lot_c["id"], "quantity": 10}])
    settle(s["firm"]["id"], disp_c["id"])
    form = setup_draft_form(s["firm"]["id"], s["customer"]["id"], 2025)
    generated = generate_form(s["firm"]["id"], s["customer"]["id"], form["id"])
    assert_tax_form_1099b(generated)
    assert generated["short_term_proceeds_cents"] == 15000, "only the covered disposition aggregates"
    assert generated["short_term_basis_cents"] == 10000
    assert generated["long_term_proceeds_cents"] == 0
    assert generated["disallowed_wash_sale_loss_cents"] == 0


def test_form_1099b_box1g_collects_disallowed_wash_sales(api):
    """PRD §3.8: "A seventh figure, `disallowed_wash_sale_loss_cents`, sums
    every qualifying disposition's `wash_sale_disallowed_loss_cents` and is
    reported in Box 1g."

    Design: Corner/calculations/form_1099b_box1g_collects_disallowed_wash_sales
    """
    s = setup_wash_sale_scenario(repl_qty=60, repl_basis=246000, tin="TIN-CALC-13", cusip="424242424")
    settle(s["firm"]["id"], s["disposition"]["id"])
    form = setup_draft_form(s["firm"]["id"], s["customer"]["id"], 2025)
    generated = generate_form(s["firm"]["id"], s["customer"]["id"], form["id"])
    assert_tax_form_1099b(generated)
    assert generated["disallowed_wash_sale_loss_cents"] == 60000, "Box 1g collects the deferred loss"
    assert generated["short_term_proceeds_cents"] == 400000


# ---------------------------------------------------------------------------
# Corner: validations / correction window; errors / frozen form
# ---------------------------------------------------------------------------

def _correction_pending_scenario(tin="TIN-V-9", cusip="525252525", proceeds=15000, basis=10000):
    s = setup_settled_sale_with_filed_form(proceeds=proceeds, basis=basis, tin=tin, cusip=cusip)
    validate_success(api_client.correct_disposition(s["firm"]["id"], s["disposition"]["id"],
                                                    {"proceeds_cents": proceeds + 500}, TAX_OPS))
    return s


def test_refile_after_correction_window_closed_rejected(api):
    """PRD §3.8: "Refiling is lawful only inside the statute window: the
    logical clock must read no later than `filed_at` plus the firm's
    `correction_deadline_days`, or the attempt fails with
    `ERR_CORRECTION_WINDOW_CLOSED` (HTTP 422)."
    PRD §3.8: "Should the logical clock cross the deadline while a form still
    sits in `CORRECTION_PENDING`, the system freezes it: `FROZEN` is permanent,
    no further corrections are accepted."

    Design: Corner/validations/refile_after_correction_window_closed_rejected
    """
    s = _correction_pending_scenario()
    validate_success(api.set_clock({"to_iso8601": PAST_CORRECTION_DEADLINE_CLOCK}, FIRM_ADMIN))
    resp = api.refile_tax_form(s["firm"]["id"], s["customer"]["id"], s["form"]["id"], FIRM_ADMIN)
    # After the clock crosses the deadline the form is frozen; the refile is
    # rejected either by the window rule (ERR_CORRECTION_WINDOW_CLOSED) or by
    # the state gate on the frozen form (ERR_INVALID_STATE_TRANSITION).
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_CORRECTION_WINDOW_CLOSED, ApiErrorId.ERR_INVALID_STATE_TRANSITION]
    )


def test_frozen_form_blocks_disposition_correct(api):
    """PRD §3.5: "every 1099-B covering this customer and tax year must be
    outside `FROZEN`: correcting into a frozen year is refused with
    `ERR_FORM_FROZEN` (HTTP 409)."
    PRD §2.9: "advancing it can trigger the deferred sweep that freezes
    correction-pending forms whose statutory window has closed (§3.8)."

    Design: Corner/errors/error_form_frozen_blocks_disposition_correct
    """
    s = setup_book(tin="TIN-ER-2", cusip="606060606", ticker="FRZ")
    make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
             acquisition_date="2025-01-05T00:00:00Z", quantity=10, basis=10000)
    make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
             acquisition_date="2025-02-05T00:00:00Z", quantity=10, basis=8000)
    disp1 = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                             quantity=10, proceeds=15000)
    settle(s["firm"]["id"], disp1["id"])
    disp2 = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                             quantity=10, proceeds=9000,
                             trade_date="2025-06-12T00:00:00Z", settlement_date="2025-06-13T00:00:00Z")
    settle(s["firm"]["id"], disp2["id"])
    s["form"] = setup_filed_form(s["firm"]["id"], s["customer"]["id"], 2025)
    validate_success(api.correct_disposition(s["firm"]["id"], disp1["id"], {"proceeds_cents": 15500}, TAX_OPS))
    assert _get_form(s)["status"] == "CORRECTION_PENDING"
    validate_success(api.set_clock({"to_iso8601": PAST_CORRECTION_DEADLINE_CLOCK}, FIRM_ADMIN))
    resp = api.correct_disposition(s["firm"]["id"], disp2["id"], {"proceeds_cents": 9500}, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_FORM_FROZEN)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / OCC generate, default clock, refile cascade
# ---------------------------------------------------------------------------

def test_occ_form_generate_stale_customer_version(api):
    """PRD §2.8: "Generating a 1099-B —
    `POST /firms/{firmId}/customers/{customerId}/tax_forms_1099b/{formId}/generate`
    — requires `expected_customer_version`, matched against the customer's
    current `version`. A mismatch is rejected with `ERR_STALE_FORM_VERSION`
    (HTTP 412): the draft's snapshot no longer reflects the customer's lot
    universe."

    Design: Corner/cross_cutting_layers/occ_form_generate_stale_customer_version
    """
    s = setup_settled_sale(tin="TIN-X-1", cusip="666666667")
    stale_version = s["customer"]["version"]
    form = setup_draft_form(s["firm"]["id"], s["customer"]["id"], 2025)
    # Suspending the customer mutates it, advancing Customer.version.
    validate_success(api_client.suspend_customer(s["firm"]["id"], s["customer"]["id"], FIRM_ADMIN))
    resp = api.generate_tax_form(s["firm"]["id"], s["customer"]["id"], form["id"],
                                 {"expected_customer_version": stale_version}, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_STALE_FORM_VERSION)
    form_after = validate_success(api.get_tax_form(s["firm"]["id"], s["customer"]["id"], form["id"], TAX_OPS))
    assert form_after["status"] == "DRAFT", "rejected generate leaves the form unchanged"


def test_clock_default_startup_time(api):
    """PRD §2.9: "At startup the clock is fixed at 2026-08-01T00:00:00Z, and it
    must never fall back to real time."
    PRD §3.8: "A filed form records `filed_at` from the logical clock and moves
    to `FILED`."

    Design: Corner/cross_cutting_layers/clock_default_startup_time
    """
    s = setup_settled_sale(tin="TIN-X-3", cusip="686868686")
    form = setup_filed_form(s["firm"]["id"], s["customer"]["id"], 2025)
    # PRD pins the instant (the startup clock), not its string rendering;
    # both "...T00:00:00Z" and the §2.4 three-fractional-digit form denote it.
    from datetime import datetime, timezone
    filed = datetime.fromisoformat(form["filed_at"].replace("Z", "+00:00"))
    startup = datetime.fromisoformat(DEFAULT_STARTUP_CLOCK.replace("Z", "+00:00"))
    assert filed == startup, (
        "no set_current_utc call: filed_at must be the fixed startup default"
    )


def test_cascade_correct_then_refile_totals_updated(api):
    """PRD §3.8: "Refiling — again `FirmAdmin` — re-runs the aggregation
    against the corrected source data, overwrites every total, increments
    `correction_count` (which starts at zero on a fresh form), refreshes
    `generated_from_version` to the customer's then-current `version`, and
    moves the form to `REFILED`."

    Design: Corner/cross_cutting_layers/cascade_correct_then_refile_totals_updated
    """
    s = setup_settled_sale_with_filed_form(tin="TIN-X-4", cusip="696969696")
    validate_success(api.correct_disposition(s["firm"]["id"], s["disposition"]["id"],
                                             {"proceeds_cents": 18000}, TAX_OPS))
    refiled = validate_success(api.refile_tax_form(s["firm"]["id"], s["customer"]["id"], s["form"]["id"], FIRM_ADMIN))
    assert_tax_form_1099b(refiled)
    assert refiled["short_term_proceeds_cents"] == 18000, "re-aggregated from the corrected replacement"
    assert refiled["short_term_basis_cents"] == 10000
    assert refiled["correction_count"] == 1
    assert refiled["status"] == "REFILED"
