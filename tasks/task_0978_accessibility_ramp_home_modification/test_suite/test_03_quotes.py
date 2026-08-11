"""Quote drafting, pricing arithmetic, submission, review, expiry, and OCC gating."""
import re
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, assert_quote, assert_quote_line_item,
    create_case, create_assessed_case, create_draft_quote, add_quote_line,
    setup_case_with_draft_quote, setup_submitted_quote, setup_under_review_quote,
    add_funding_source, approve_funding, add_allocation, submit_quote,
    set_clock, get_case, case_version,
    create_quote_payload, create_quote_line_item_payload,
)

IC = TEST_USERS["intake_coordinator_headers"]
AS = TEST_USERS["assessor_headers"]
PM = TEST_USERS["project_manager_headers"]
FC = TEST_USERS["funding_coordinator_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: per-line vs aggregate rounding divergence (Quote domain)
# ---------------------------------------------------------------------------

def _setup_rounding_divergence_quote(api):
    """ASSESSED case + DRAFT quote with two MATERIAL lines whose per-line
    round-half-up extended prices diverge from the aggregate-rounded reading."""
    set_clock()
    case, _ = create_assessed_case(mobility_score=50, hazard_count=2,
                                   client_name="Dana Cole", client_address="11 Ramp Way",
                                   client_phone="555-0101")
    quote = create_draft_quote(case["id"])  # contingency_pct omitted -> default 10.0
    line_a = add_quote_line(case["id"], quote["id"], line_type="MATERIAL",
                            description="Aluminum panel A", quantity=1.5, unit="sqft",
                            unit_price_cents=333, tax_rate_pct=0.0, sort_order=1)
    line_b = add_quote_line(case["id"], quote["id"], line_type="MATERIAL",
                            description="Aluminum panel B", quantity=2.5, unit="sqft",
                            unit_price_cents=333, tax_rate_pct=0.0, sort_order=2)
    return case, quote, line_a, line_b


def test_quote_per_line_rounding_extended_prices(api):
    """PRD §2.5: "Quote and invoice arithmetic is performed per line: each line's
    extended price and each line's tax are rounded half up to whole cents
    independently before any summation takes place, and totals are sums of those
    already-rounded line amounts."
    PRD §3.3: "Each line's `extended_price_cents` is its `quantity` multiplied by
    its `unit_price_cents`, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/quote_per_line_vs_aggregate_rounding_divergence
    """
    case, quote, line_a, line_b = _setup_rounding_divergence_quote(api)
    assert line_a["extended_price_cents"] == 500, "round_half_up(1.5*333=499.5) per line"
    assert line_b["extended_price_cents"] == 833, "round_half_up(2.5*333=832.5) per line"
    q = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert q["material_cost_cents"] == 1333, "sum of per-line-rounded extended prices"
    assert q["subtotal_cents"] == 1333, "aggregate-rounding reading would give 1332"


def test_quote_per_line_rounding_contingency_and_total(api):
    """PRD §3.3: "The `contingency_cents` is the subtotal multiplied by
    `contingency_pct` and divided by 100, rounded half up to whole cents; the
    contingency percentage defaults to 10.0 when not supplied and may never exceed
    25.0. Finally, `total_cents` is the subtotal plus the contingency minus any
    applied `discount_cents`, and the quote's total tax is the sum of all line tax
    amounts."

    Design: Difficulty/dual_variant_calc/quote_per_line_vs_aggregate_rounding_divergence
    """
    case, quote, _, _ = _setup_rounding_divergence_quote(api)
    q = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert q["contingency_pct"] == pytest.approx(10.0)
    assert q["contingency_cents"] == 133, "round_half_up(1333 * 10 / 100)"
    assert q["total_cents"] == 1466, "aggregate-rounding reading would give 1465"


# ---------------------------------------------------------------------------
# Difficulty: per-line tax rounding order
# ---------------------------------------------------------------------------

def _setup_tax_rounding_quote(api):
    """ASSESSED case + DRAFT quote with two taxable 105-cent lines at 10%."""
    set_clock()
    case, _ = create_assessed_case(mobility_score=40, hazard_count=3,
                                   client_name="Gus Hale", client_address="44 Grab Bar St",
                                   client_phone="555-0104")
    quote = create_draft_quote(case["id"])  # default contingency 10.0
    line_a = add_quote_line(case["id"], quote["id"], line_type="LABOR",
                            description="Install hour", quantity=1, unit="hour",
                            unit_price_cents=105, is_taxable=True,
                            tax_rate_pct=10.0, sort_order=1)
    line_b = add_quote_line(case["id"], quote["id"], line_type="MATERIAL",
                            description="Anchors", quantity=1, unit="each",
                            unit_price_cents=105, is_taxable=True,
                            tax_rate_pct=10.0, sort_order=2)
    return case, quote, line_a, line_b


def test_quote_tax_rounded_per_line(api):
    """PRD §3.3: "Each line's `tax_cents` is that extended price multiplied by the
    line's `tax_rate_pct` and divided by 100, rounded half up to whole cents — but
    only when `is_taxable` is true; a non-taxable line's tax is exactly zero."
    PRD §2.5: "The system never sums raw unrounded products and rounds only at the
    total level, because per-line rounding is what the client's paperwork shows."

    Design: Difficulty/combinatorial_formula/quote_tax_rounded_per_line_before_subtotal
    """
    case, quote, line_a, line_b = _setup_tax_rounding_quote(api)
    assert line_a["tax_cents"] == 11, "round_half_up(105 * 10 / 100) = round_half_up(10.5)"
    assert line_b["tax_cents"] == 11
    assert line_a["tax_cents"] + line_b["tax_cents"] == 22, (
        "sum-then-round order would give 21")


def test_quote_tax_rounding_subtotal_and_total(api):
    """PRD §3.3: "The `subtotal_cents` adds up the extended prices of every line —
    labor, material, permit, equipment, demolition, electrical, and plumbing
    alike. The `contingency_cents` is the subtotal multiplied by `contingency_pct`
    and divided by 100, rounded half up to whole cents; the contingency percentage
    defaults to 10.0 when not supplied and may never exceed 25.0. Finally,
    `total_cents` is the subtotal plus the contingency minus any applied
    `discount_cents`, and the quote's total tax is the sum of all line tax
    amounts."

    Design: Difficulty/combinatorial_formula/quote_tax_rounded_per_line_before_subtotal
    """
    case, quote, _, _ = _setup_tax_rounding_quote(api)
    q = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert q["subtotal_cents"] == 210
    assert q["contingency_cents"] == 21
    assert q["total_cents"] == 231


# ---------------------------------------------------------------------------
# Difficulty: empty-quote submission boundary
# ---------------------------------------------------------------------------

def test_quote_submit_with_zero_line_items_rejected(api):
    """PRD §3.3: "Submitting the quote is a `ProjectManager` action with two
    preconditions, evaluated in the order given in §2.6: the quote must contain at
    least one line item (otherwise `ERR_QUOTE_EMPTY`), and `valid_until` must
    still lie in the future."

    Design: Difficulty/boundary_precision_check/quote_submit_with_zero_line_items_rejected
    """
    set_clock()
    case, _ = create_assessed_case(client_name="Owen Prew", client_address="32 Empty Ln",
                                   client_phone="555-0112")
    quote = create_draft_quote(case["id"])
    res = api.submit_quote(case["id"], quote["id"], PM)
    validate_error(res, ApiErrorId.ERR_QUOTE_EMPTY, expected_status=422)


def test_quote_submit_rejection_leaves_quote_draft(api):
    """PRD §3.3: "Submission moves the quote from `DRAFT` to `SUBMITTED`, stamps
    `submitted_at`, computes `funding_gap_cents` as the quote's `total_cents`
    minus the case's `total_funded_cents` with the result floored at zero so it
    can never be negative, and moves the case from `QUOTE_DRAFTED` to
    `QUOTE_SUBMITTED`." A rejected submission applies none of this.

    Design: Difficulty/boundary_precision_check/quote_submit_with_zero_line_items_rejected
    """
    set_clock()
    case, _ = create_assessed_case(client_name="Owen Prew2", client_address="32b Empty Ln",
                                   client_phone="555-0113")
    quote = create_draft_quote(case["id"])
    validate_error(api.submit_quote(case["id"], quote["id"], PM),
                   ApiErrorId.ERR_QUOTE_EMPTY, expected_status=422)
    q = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert q["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Difficulty: quote creation gated by parent case state
# ---------------------------------------------------------------------------

def test_quote_create_on_intake_case_rejected(api):
    """PRD §3.3: "The create request carries the quote's `valid_until` expiration
    date, an optional `contingency_pct`, and the concurrency guard
    `expected_case_version` described in §2.4; quoting a case that has not reached
    `ASSESSED` is rejected with `ERR_CASE_NOT_ASSESSED`, and a stale guard value
    is rejected with `ERR_STALE_VERSION`."

    Design: Difficulty/cross_entity_state_dependency/quote_creation_gated_by_case_assessed_state
    """
    set_clock()
    case = create_case(client_name="Quinn Rhea", client_address="54 Gate St",
                       client_phone="555-0114")
    res = api.create_quote(
        case["id"], create_quote_payload(case["version"]), PM)
    validate_error(res, ApiErrorId.ERR_CASE_NOT_ASSESSED, expected_status=409)


def test_quote_create_succeeds_once_case_assessed(api):
    """PRD §3.3: "Once a case is `ASSESSED` — with at least one `COMPLETED`
    assessment on file — a `ProjectManager` drafts a quote." "Drafting the first
    quote moves the case from `ASSESSED` to `QUOTE_DRAFTED`, and the quote itself
    is born in `DRAFT`."

    Design: Difficulty/cross_entity_state_dependency/quote_creation_gated_by_case_assessed_state
    """
    set_clock()
    case, _ = create_assessed_case(mobility_score=50, hazard_count=2,
                                   client_name="Quinn Rhea2", client_address="54b Gate St",
                                   client_phone="555-0115")
    res = api.create_quote(case["id"], create_quote_payload(case["version"]), PM)
    quote = validate_success(res, 201)
    assert_quote(quote)
    assert quote["status"] == "DRAFT"
    assert get_case(case["id"])["status"] == "QUOTE_DRAFTED"


# ---------------------------------------------------------------------------
# Difficulty: state error beats business-constraint error (priority pair)
# ---------------------------------------------------------------------------

def test_state_error_beats_constraint_error_on_line_add(api):
    """PRD §2.6: "Because the ladder is ordered, a single request can only ever
    surface the earliest failing check". Rung 5: "The resource being acted on must
    be in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)." Rung
    6b: "adding a quote line item whose quantity or unit price is not positive
    fails with `ERR_INVALID_LINE_ITEM` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/quote_line_item_state_error_beats_constraint_error
    """
    set_clock()
    case, quote = setup_submitted_quote(unit_price_cents=5000)
    res = api.add_quote_line_item(
        case["id"], quote["id"],
        create_quote_line_item_payload(line_type="MATERIAL", description="Bad line",
                                       quantity=0, unit_price_cents=100, sort_order=2),
        PM)
    validate_error(res, ApiErrorId.ERR_QUOTE_NOT_DRAFT, expected_status=409)


def test_priority_rejection_leaves_quote_unchanged(api):
    """PRD §3.3: "A `ProjectManager` adds line items to a `DRAFT` quote —
    attempting to add one to a quote in any other state fails with
    `ERR_QUOTE_NOT_DRAFT`". A rejected addition changes nothing.

    Design: Difficulty/priority_pair_validation_conflict/quote_line_item_state_error_beats_constraint_error
    """
    set_clock()
    case, quote = setup_submitted_quote(unit_price_cents=5000)
    before = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    validate_error(api.add_quote_line_item(
        case["id"], quote["id"],
        create_quote_line_item_payload(line_type="MATERIAL", description="Bad line",
                                       quantity=0, unit_price_cents=100, sort_order=2),
        PM), ApiErrorId.ERR_QUOTE_NOT_DRAFT, expected_status=409)
    after = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert after["status"] == "SUBMITTED"
    assert after["subtotal_cents"] == before["subtotal_cents"] == 5000
    assert after["total_cents"] == before["total_cents"]


# ---------------------------------------------------------------------------
# Corner: defaults, retrieval, transitions, expiry, numbering, recompute
# ---------------------------------------------------------------------------

def test_quote_contingency_defaults_to_10_pct(api):
    """PRD §3.3: "The `contingency_cents` is the subtotal multiplied by
    `contingency_pct` and divided by 100, rounded half up to whole cents; the
    contingency percentage defaults to 10.0 when not supplied and may never exceed
    25.0."

    Design: Corner/entities/quote_contingency_defaults_to_10_pct
    """
    set_clock()
    case, _ = create_assessed_case(client_name="Eve Fenn", client_address="6 Contingency Ct",
                                   client_phone="555-0208")
    quote = create_draft_quote(case["id"])
    assert quote["contingency_pct"] == pytest.approx(10.0), "default must be applied"
    add_quote_line(case["id"], quote["id"], line_type="LABOR", description="Work",
                   quantity=1, unit="hour", unit_price_cents=10000,
                   tax_rate_pct=0.0, sort_order=1)
    q = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert q["subtotal_cents"] == 10000
    assert q["contingency_cents"] == 1000


def test_quote_list_reverse_reachable_from_case(api):
    """PRD §2.7: "The stored records mirror that hierarchy: every case-child
    record persists its parent linkage in a `case_id` field, and deeper records
    carry their own parent keys — a quote line item its `quote_id`, an invoice
    line item its `invoice_id`, a funding allocation its `funding_source_id` — so
    the URL path and the stored references always agree about which aggregate a
    record belongs to."

    Design: Corner/entities/quote_list_reverse_reachable_from_case
    """
    set_clock()
    case, _ = create_assessed_case(client_name="Kim Lott", client_address="12 Reverse Ln",
                                   client_phone="555-0214")
    quote = create_draft_quote(case["id"])
    data, _ = validate_paginated(api.list_quotes(case["id"], IC))
    assert len(data) == 1
    assert data[0]["id"] == quote["id"]
    assert data[0]["case_id"] == case["id"]


def test_quote_approve_from_submitted_rejected(api):
    """PRD §3.3: "Review belongs to the `FundingCoordinator`. Starting review
    moves the quote from `SUBMITTED` to `UNDER_REVIEW`. Approving the quote
    requires that sufficient funding has been allocated — or that self-pay has
    been approved — to cover the total". Approval is a review-stage transition, so
    a merely SUBMITTED quote is not in a state from which it exists.
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/quote_approve_from_submitted_rejected
    """
    set_clock()
    case, quote = setup_submitted_quote(unit_price_cents=5000)
    res = api.approve_quote(case["id"], quote["id"], FC)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    q = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert q["status"] == "SUBMITTED"


def test_quote_rejected_terminal_lockdown(api):
    """PRD §3.3: "Rejection moves the quote from `UNDER_REVIEW` to `REJECTED`,
    stamps `decided_at`, and releases every `PENDING` allocation back to
    `RELEASED`." "`APPROVED`, `REJECTED`, `SUPERSEDED`, and `EXPIRED` are all
    terminal for a quote."

    Design: Corner/state_machines/quote_rejected_terminal_lockdown
    """
    set_clock()
    case, quote, src, alloc = setup_under_review_quote(quote_total=5000, approved_cents=5000)
    rejected = validate_success(api.reject_quote(case["id"], quote["id"], FC), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["decided_at"] is not None
    res = api.approve_quote(case["id"], quote["id"], FC)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    allocs, _ = validate_paginated(api.list_funding_allocations(case["id"], src["id"], IC))
    assert all(a["status"] == "RELEASED" for a in allocs)
    src_after = validate_success(api.get_funding_source(case["id"], src["id"], IC), 200)
    assert src_after["remaining_cents"] == 5000, "PENDING allocations never decremented the source"


def test_quote_expire_after_valid_until_releases_allocations(api):
    """PRD §3.3: "Independently of review, if the current date passes a quote's
    `valid_until` while it sits in `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW`, the
    quote becomes `EXPIRED` and its pending allocations are likewise released."
    PRD §2.9: "The time-driven transitions are: a quote in DRAFT, SUBMITTED, or
    UNDER_REVIEW whose `valid_until` has passed becomes EXPIRED".

    Design: Corner/state_machines/quote_expire_after_valid_until_releases_allocations
    """
    set_clock()
    case, _ = create_assessed_case(client_name="Gus Joff", client_address="33 Expire Ave",
                                   client_phone="555-0235")
    quote = create_draft_quote(case["id"], contingency_pct=0.0,
                               valid_until="2026-05-10T00:00:00Z")
    add_quote_line(case["id"], quote["id"], line_type="MATERIAL", description="Kit",
                   quantity=1, unit_price_cents=5000, tax_rate_pct=0.0, sort_order=1)
    src = approve_funding(case["id"],
                          add_funding_source(case["id"], 5000, source_type="CHARITY",
                                             program_name="C1")["id"],
                          5000)
    submit_quote(case["id"], quote["id"])
    alloc = add_allocation(case["id"], src["id"], quote["id"], 5000)
    set_clock("2026-05-11T00:00:00Z")
    q = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert q["status"] == "EXPIRED"
    allocs, _ = validate_paginated(api.list_funding_allocations(case["id"], src["id"], IC))
    statuses = {a["id"]: a["status"] for a in allocs}
    assert statuses[alloc["id"]] == "RELEASED"


def test_quote_number_format_q_date_seq(api):
    """PRD §3.3: "The server assigns a human-readable `quote_number` in the format
    Q-YYYYMMDD-NNN and a `revision` number: the first quote on a case is revision
    1, and each subsequent quote created for the same case increments the
    revision."
    PRD §2.9: "On startup the logical clock reads 2026-05-01T00:00:00Z".

    Design: Corner/endpoints/quote_number_format_q_date_seq
    """
    set_clock()
    case, _ = create_assessed_case(client_name="Ute Xeno", client_address="47 Number Ave",
                                   client_phone="555-0501")
    quote = create_draft_quote(case["id"])
    assert re.fullmatch(r"Q-20260501-[0-9]{3}", quote["quote_number"]), (
        f"quote_number {quote['quote_number']!r} must follow Q-YYYYMMDD-NNN on the logical clock date")
    assert quote["revision"] == 1


def test_quote_totals_recompute_on_second_line_item(api):
    """PRD §3.3: "Every line addition or modification recomputes the quote's money
    fields". "The quote's `labor_cost_cents` is the sum of the extended prices of
    all `LABOR` lines, `material_cost_cents` the sum over `MATERIAL` lines".
    "Finally, `total_cents` is the subtotal plus the contingency minus any applied
    `discount_cents`".

    Design: Corner/calculations/quote_totals_recompute_on_second_line_item
    """
    set_clock()
    case, _ = create_assessed_case(client_name="Pia Sorn", client_address="42 Recompute Rd",
                                   client_phone="555-0309")
    quote = create_draft_quote(case["id"], contingency_pct=0.0)
    add_quote_line(case["id"], quote["id"], line_type="MATERIAL", description="Panels",
                   quantity=1, unit_price_cents=10000, tax_rate_pct=0.0, sort_order=1)
    q1 = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert q1["subtotal_cents"] == 10000
    assert q1["total_cents"] == 10000
    add_quote_line(case["id"], quote["id"], line_type="LABOR", description="Install hours",
                   quantity=2, unit="hour", unit_price_cents=5000, tax_rate_pct=0.0, sort_order=2)
    q2 = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert q2["subtotal_cents"] == 20000
    assert q2["material_cost_cents"] == 10000
    assert q2["labor_cost_cents"] == 10000
    assert q2["total_cents"] == 20000


def test_quote_not_found_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."

    Design: Corner/errors/quote_not_found_returns_404
    """
    case = create_case(client_name="NF Quote", client_address="52 NF Rd",
                       client_phone="555-0602")
    res = api.get_quote(case["id"], NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_QUOTE_NOT_FOUND, expected_status=404)


def test_line_item_zero_price_rejected(api):
    """PRD §3.3: "Both `quantity` and `unit_price_cents` must be positive; a line
    violating this is rejected with `ERR_INVALID_LINE_ITEM`."

    Design: Corner/validations/line_item_zero_price_rejected
    """
    set_clock()
    case, quote = setup_case_with_draft_quote(contingency_pct=None, n_lines=0)
    res = api.add_quote_line_item(
        case["id"], quote["id"],
        create_quote_line_item_payload(line_type="MATERIAL", description="Free stuff",
                                       quantity=1, unit_price_cents=0, sort_order=1),
        PM)
    validate_error(res, ApiErrorId.ERR_INVALID_LINE_ITEM, expected_status=422)
