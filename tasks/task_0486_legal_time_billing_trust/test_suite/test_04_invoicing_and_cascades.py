"""Invoice drafting/finalize/void, the WIP-vs-final dual, finalize cascade,
parallel billing/collection dimensions, collection aging, and payment cascades.

Queue A: dual_variant_calc (invoice WIP), transitive_cascade (finalize depth-2),
non_linear_state_machine (parallel dims), boundary_precision_check (aging).
Queue B: state_machines (invoice), calculations (invoice_total + parallel stub),
cross_cutting (version, cascades, immediate consistency).
"""
import pytest
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    ApiErrorId,
    create_invoice_payload, create_expense_entry_payload, create_payment_payload,
    create_open_matter, ensure_billing_codes, capture_time_entry,
    setup_open_matter_with_time, setup_draft_invoice, setup_issued_invoice,
    set_clock,
    api_client,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
ATT = TEST_USERS["attorney_headers"]


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / invoice_wip_provisional_vs_final
# ---------------------------------------------------------------------------
def test_wip_summary_provisional_no_write_downs(api):
    """PRD §3.4: "that summary recomputes `wip_fees_cents` and
    `wip_expenses_cents` live as the sum of `billable_amount_cents` over the
    matter's `CAPTURED` time entries and the sum of `amount_cents` over its
    `CAPTURED` expense entries, and reports them alongside a `time_entry_count`
    and an `expense_entry_count`. No line write-downs are applied in this
    provisional view."

    Design: Difficulty/dual_variant_calc/invoice_wip_provisional_vs_final
    """
    ensure_billing_codes()
    # matter_rate 40000: min90 -> 40000*15/10 = 60000; min30 -> 40000*5/10 = 20000; WIP 80000.
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=40000)
    capture_time_entry(matter["id"], tk_id, minutes=90, worked_at="2026-05-01T09:00:00Z")
    capture_time_entry(matter["id"], tk_id, minutes=30, worked_at="2026-05-01T11:00:00Z")
    wip = validate_success(api.get_matter_wip_summary(matter["id"], CLERK))
    assert wip["wip_fees_cents"] == 80000


def test_finalize_pins_fees_after_line_write_down(api):
    """PRD §3.5: "The `fees_subtotal_cents` is the sum of `billable_amount_cents`
    over the attached time entries (each already rounded per the per-entry rule),
    then reduced by the total of the supplied `line_write_downs`." PRD §3.5: "The
    `written_off_cents` is set to the total of those line write-downs. The
    `total_cents` is `fees_subtotal_cents` plus `expenses_subtotal_cents` after
    the write-downs are applied."

    Design: Difficulty/dual_variant_calc/invoice_wip_provisional_vs_final
    """
    ensure_billing_codes()
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=40000)
    capture_time_entry(matter["id"], tk_id, minutes=90, worked_at="2026-05-01T09:00:00Z")
    te2 = capture_time_entry(matter["id"], tk_id, minutes=30, worked_at="2026-05-01T11:00:00Z")
    inv = validate_success(api.create_invoice(create_invoice_payload(matter["id"]), CLERK),
                           expected_status=201)
    final = validate_success(api.finalize_invoice(
        inv["id"], {"line_write_downs": [{"time_entry_id": te2["id"], "amount_cents": 20000}]},
        CLERK))
    assert final["fees_subtotal_cents"] == 60000
    assert final["written_off_cents"] == 20000
    assert final["total_cents"] == 60000


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / finalize_depth2_invoiced_wip_chain
# ---------------------------------------------------------------------------
def test_finalize_flips_entry_to_invoiced(api):
    """PRD §3.5: "Each attached time entry and expense entry flips from
    `CAPTURED` to `INVOICED` and has its `invoice_id` set to this invoice, so it
    can never re-enter another invoice's work-in-progress."

    Design: Difficulty/transitive_cascade/finalize_depth2_invoiced_wip_chain
    """
    base = setup_draft_invoice(matter_rate_cents=50000, minutes=60)
    te_id = base["time_entry"]["id"]
    inv_id = base["invoice"]["id"]
    validate_success(api.finalize_invoice(inv_id, {}, CLERK))
    te = validate_success(api.get_time_entry(te_id, CLERK))
    assert te["status"] == "INVOICED"
    assert te["invoice_id"] == inv_id


def test_finalize_drains_matter_wip_and_adds_ar(api):
    """PRD §3.5: "The matter's `wip_fees_cents` and `wip_expenses_cents` are
    decremented by the amounts just invoiced. The owning client's
    `ar_balance_cents` is increased by the invoice's `total_cents`."

    Design: Difficulty/transitive_cascade/finalize_depth2_invoiced_wip_chain
    """
    base = setup_draft_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    matter_id = base["matter"]["id"]
    client_id = base["client_id"]
    validate_success(api.finalize_invoice(inv_id, {}, CLERK))
    matter = validate_success(api.get_matter(matter_id, CLERK))
    assert matter["wip_fees_cents"] == 0
    ar = validate_success(api.get_client_ar_summary(client_id, CLERK))
    assert ar["ar_balance_cents"] == 50000


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / invoice_parallel_billing_x_collection_dimensions
# ---------------------------------------------------------------------------
def test_clock_advance_ages_collection_without_touching_billing(api):
    """PRD §3.5: "An `Invoice` carries two independent state dimensions on the
    same record: a `billing_status` that walks `DRAFT → ISSUED → PARTIALLY_PAID →
    PAID` ... and a `collection_status` that walks `CURRENT → DUE → OVERDUE →
    IN_COLLECTIONS` with a `SETTLED` terminus. These two dimensions evolve
    independently while the invoice is `ISSUED`."
    PRD §3.7: "If the current clock is strictly past the due date but no later
    than the due date plus the collections grace period of fifteen days, the
    invoice is `OVERDUE`."

    Design: Difficulty/non_linear_state_machine/invoice_parallel_billing_x_collection_dimensions
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    # issue 2026-06-01, net 30 -> due 2026-07-01; clock to 2026-07-15 -> OVERDUE.
    set_clock("2026-07-15T00:00:00Z")
    inv = validate_success(api.get_invoice(inv_id, CLERK))
    assert inv["billing_status"] == "ISSUED"
    assert inv["collection_status"] == "OVERDUE"


def test_billing_dimension_unchanged_by_clock(api):
    """PRD §3.5: "These two dimensions evolve independently while the invoice is
    `ISSUED`." PRD §3.7: "An invoice whose `billing_status` is `PAID`,
    `WRITTEN_OFF`, or `VOID` is `SETTLED` ... Otherwise, if the current clock
    instant is at or before the due date, the invoice is `DUE` when the clock has
    reached the `issue_date`".

    Design: Difficulty/non_linear_state_machine/invoice_parallel_billing_x_collection_dimensions
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    before = validate_success(api.get_invoice(inv_id, CLERK))
    assert before["billing_status"] == "ISSUED"
    set_clock("2026-07-15T00:00:00Z")
    after = validate_success(api.get_invoice(inv_id, CLERK))
    # Billing dimension stays ISSUED across the clock advance.
    assert after["billing_status"] == "ISSUED"


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / collection_aging_due_date_inclusive_boundary
# ---------------------------------------------------------------------------
def test_collection_status_due_at_exact_due_date(api):
    """PRD §3.7: "At exactly the due date the invoice is `DUE` and not yet
    `OVERDUE`; `OVERDUE` requires the clock to be strictly past the due date."

    Design: Difficulty/boundary_precision_check/collection_aging_due_date_inclusive_boundary
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    set_clock("2026-07-01T00:00:00Z")  # exactly due_date
    inv = validate_success(api.get_invoice(inv_id, CLERK))
    assert inv["collection_status"] == "DUE"


def test_collection_status_overdue_one_second_past_due(api):
    """PRD §3.7: "`OVERDUE` requires the clock to be strictly past the due date."
    PRD §3.7: "If the current clock is strictly past the due date but no later
    than the due date plus the collections grace period of fifteen days, the
    invoice is `OVERDUE`."

    Design: Difficulty/boundary_precision_check/collection_aging_due_date_inclusive_boundary
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    set_clock("2026-07-01T00:00:01Z")  # one second past due_date
    inv = validate_success(api.get_invoice(inv_id, CLERK))
    assert inv["collection_status"] == "OVERDUE"


# ---------------------------------------------------------------------------
# Section 2 — State Machines (invoice) (queue B)
# ---------------------------------------------------------------------------
def test_finalize_already_issued_invoice_invalid_state(api):
    """PRD §3.5: "Finalize requires that the invoice's `billing_status` is `DRAFT`
    and the matter's `status` is `OPEN`".

    Design: Corner/state_machines/finalize_already_issued_invoice_invalid_state
    """
    base = setup_issued_invoice()
    validate_error(api.finalize_invoice(base["invoice"]["id"], {}, CLERK),
                   ApiErrorId.ERR_INVALID_STATE)


def test_void_issued_invoice_invalid_state(api):
    """PRD §3.5: "A `DRAFT` invoice that should not have been raised can be voided
    by a `BillingClerk`; only an un-issued draft may be voided."

    Design: Corner/state_machines/void_issued_invoice_invalid_state
    """
    base = setup_issued_invoice()
    validate_error(api.void_invoice(base["invoice"]["id"], CLERK),
                   ApiErrorId.ERR_INVALID_STATE)


def test_send_to_collections_from_current_invalid_state(api):
    """PRD §3.7: "Moving an invoice into `IN_COLLECTIONS` is an explicit action: a
    `BillingClerk` sends an `OVERDUE` invoice to collections, permitted only once
    the clock is past the due date plus the fifteen-day grace and while the
    invoice's `billing_status` is still `ISSUED` or `PARTIALLY_PAID`".

    Design: Corner/state_machines/send_to_collections_from_current_invalid_state
    """
    base = setup_issued_invoice()
    inv_id = base["invoice"]["id"]
    # Clock at 2026-06-15: at or before due 2026-07-01 -> DUE, not OVERDUE.
    set_clock("2026-06-15T00:00:00Z")
    validate_error(api.send_to_collections(inv_id, CLERK), ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Section 3 — Calculations (invoice_total) (queue B)
# ---------------------------------------------------------------------------
def test_invoice_total_includes_expenses(api):
    """PRD §3.5: "The `expenses_subtotal_cents` is the sum of `amount_cents` over
    the attached expense entries." PRD §3.5: "The `total_cents` is
    `fees_subtotal_cents` plus `expenses_subtotal_cents` after the write-downs are
    applied."

    Design: Corner/calculations/invoice_total_includes_expenses
    """
    ensure_billing_codes(expense=True)
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=40000)
    capture_time_entry(matter["id"], tk_id, minutes=90)
    validate_success(
        api.create_expense_entry(create_expense_entry_payload(matter["id"], 12000), ATT),
        expected_status=201)
    inv = validate_success(api.create_invoice(create_invoice_payload(matter["id"]), CLERK),
                           expected_status=201)
    final = validate_success(api.finalize_invoice(inv["id"], {}, CLERK))
    assert final["fees_subtotal_cents"] == 60000
    assert final["expenses_subtotal_cents"] == 12000
    assert final["total_cents"] == 72000


# ---------------------------------------------------------------------------
# Section 5 — Endpoints (void detaches) (queue B)
# ---------------------------------------------------------------------------
def test_void_draft_invoice_detaches_entries(api):
    """PRD §3.5: "Voiding moves `billing_status` to `VOID`, detaches any attached
    entries (their `status` stays `CAPTURED` and their `invoice_id` is cleared so
    they return to work-in-progress), and increments the invoice's `version`."

    Design: Corner/endpoints/void_draft_invoice_detaches_entries
    """
    base = setup_draft_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    te_id = base["time_entry"]["id"]
    voided = validate_success(api.void_invoice(inv_id, CLERK))
    assert voided["billing_status"] == "VOID"
    te = validate_success(api.get_time_entry(te_id, CLERK))
    assert te["status"] == "CAPTURED"


# ---------------------------------------------------------------------------
# Section 5 — Endpoints (FK reverse lookups) (queue B)
# ---------------------------------------------------------------------------
def test_fk_reverse_time_entries_by_matter(api):
    """PRD §4 endpoint table: "GET `/firm/time-entries` | List time entries
    (filter by `matter_id`, `timekeeper_id`, `invoice_id`, `status`)".

    Design: Corner/endpoints/fk_reverse_time_entries_by_matter
    """
    from test_helpers import validate_paginated
    base = setup_open_matter_with_time(matter_rate_cents=50000, minutes=60)
    matter_id = base["matter"]["id"]
    te_id = base["time_entry"]["id"]
    data, meta = validate_paginated(api.list_time_entries(CLERK, params={"matter_id": matter_id}))
    assert meta["total_count"] == 1
    assert any(e["id"] == te_id for e in data)


def test_pagination_limit_out_of_bounds(api):
    """PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is
    rejected with `ERR_VALIDATION_LIMIT`."

    Design: Corner/endpoints/pagination_limit_out_of_bounds
    """
    from test_helpers import create_client
    create_client()
    validate_error(api.list_clients(CLERK, params={"limit": 500}),
                   ApiErrorId.ERR_VALIDATION_LIMIT)


# ---------------------------------------------------------------------------
# Section 8 — Cross-cutting complexity layers (queue B)
# ---------------------------------------------------------------------------
def test_occ_version_increments_on_each_invoice_write(api):
    """PRD §2.4: "The `version` of a resource begins at 1 on creation and
    increases by exactly 1 on every mutation". PRD §3.5: "its `billing_status`
    becomes `ISSUED`, and its `version` is incremented."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_invoice_write
    """
    base = setup_draft_invoice(matter_rate_cents=50000, minutes=60)
    assert base["invoice"]["version"] == 1
    final = validate_success(api.finalize_invoice(base["invoice"]["id"], {}, CLERK))
    assert final["version"] == 2


def test_derived_field_ar_balance_reconciles_on_payment(api):
    """PRD §3.6: "The provisional `ar_balance_cents` is the sum, over the client's
    invoices whose `billing_status` is `ISSUED` or `PARTIALLY_PAID`, of
    `total_cents` minus `amount_paid_cents` minus `written_off_cents`; it is
    recomputed on every invoice finalize, payment, and write-down."

    Design: Corner/cross_cutting_complexity_layers/derived_field_ar_balance_reconciles_on_payment
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    client_id = base["client_id"]
    inv_id = base["invoice"]["id"]
    ar0 = validate_success(api.get_client_ar_summary(client_id, CLERK))
    assert ar0["ar_balance_cents"] == 50000
    validate_success(api.create_payment(inv_id, create_payment_payload(20000, "CARD"), CLERK),
                     expected_status=201)
    ar1 = validate_success(api.get_client_ar_summary(client_id, CLERK))
    assert ar1["ar_balance_cents"] == 30000


def test_cascade_partial_payment_sets_partially_paid(api):
    """PRD §3.6: "while the cumulative paid is strictly greater than zero but
    strictly less than that owed amount, an `ISSUED` invoice becomes
    `PARTIALLY_PAID`".

    Design: Corner/cross_cutting_complexity_layers/cascade_partial_payment_sets_partially_paid
    """
    base = setup_issued_invoice(matter_rate_cents=50000, minutes=60)
    inv_id = base["invoice"]["id"]
    validate_success(api.create_payment(inv_id, create_payment_payload(20000, "CHECK"), CLERK),
                     expected_status=201)
    inv = validate_success(api.get_invoice(inv_id, CLERK))
    assert inv["billing_status"] == "PARTIALLY_PAID"
    assert inv["amount_paid_cents"] == 20000


def test_immediate_consistency_finalize_visible_same_response(api):
    """PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field." PRD §3.5: "The
    `total_cents` is `fees_subtotal_cents` plus `expenses_subtotal_cents` after
    the write-downs are applied."

    Design: Corner/consistency_model/immediate_consistency_finalize_visible_same_response
    """
    base = setup_draft_invoice(matter_rate_cents=50000, minutes=60)
    final = validate_success(api.finalize_invoice(base["invoice"]["id"], {}, CLERK))
    assert final["total_cents"] == 50000
    assert final["billing_status"] == "ISSUED"
