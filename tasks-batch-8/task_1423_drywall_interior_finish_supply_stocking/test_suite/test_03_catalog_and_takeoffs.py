"""Board catalog, takeoff drafting/pricing, dual-variant lock repricing,
optimistic concurrency, and takeoff cancellation (PRD §2.3, §2.9, §3.2, §3.4, §3.5)."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_product, assert_takeoff,
    create_account, create_product, create_project,
    create_takeoff_with_lines, submit_takeoff, lock_takeoff, get_takeoff,
    create_product_payload,
)
from test_helpers import api_client

CM = TEST_USERS["credit_manager_headers"]
EST = TEST_USERS["estimator_headers"]
WH = TEST_USERS["warehouse_manager_headers"]


# ─── Catalog ─────────────────────────────────────────────────────────

def test_product_create_regular_and_rated(api, warehouse_manager_headers):
    """PRD §3.2: "Lead time is zero for `REGULAR` board and at least one day
    for either rated kind; the rated kinds are exactly the special-order
    products. A new product is born with `active` set to true."

    Design: Corner/entities/product_create_rated_requires_positive_lead_time
    """
    regular = validate_success(api.create_product(
        create_product_payload(sku="REG-4x8-1/2", lead_time_days=0),
        warehouse_manager_headers), 201)
    assert_product(regular)
    assert regular["active"] is True
    assert regular["lead_time_days"] == 0

    rated = validate_success(api.create_product(
        create_product_payload(sku="FIRE-4x8-5/8", board_kind="FIRE_RATED",
                               thickness_in="5/8", sheets_per_bundle=16,
                               unit_price_cents_per_sheet=2400, lead_time_days=7),
        warehouse_manager_headers), 201)
    assert_product(rated)
    assert rated["lead_time_days"] == 7
    assert rated["active"] is True


def test_product_list_pagination_defaults(api, warehouse_manager_headers):
    """PRD §2.3: "The `limit` parameter defaults to 10, must be at least 1, and
    may not exceed 100. The `offset` parameter defaults to 0."
    PRD §2.3: "List responses include the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/pagination_default_limit_and_offset
    """
    for i, (sku, length, spb, price) in enumerate([
            ("P-A", 8, 20, 1000), ("P-B", 10, 18, 1100), ("P-C", 12, 16, 1200)]):
        validate_success(api.create_product(
            create_product_payload(sku=sku, length_ft=length,
                                   sheets_per_bundle=spb,
                                   unit_price_cents_per_sheet=price),
            warehouse_manager_headers), 201)

    res = api.list_products(warehouse_manager_headers)
    data, meta = validate_paginated(res)
    body = res.json()
    assert "api_request_id" in body["meta"], "meta must contain api_request_id"
    assert "api_request_timestamp" in body["meta"], "meta must contain api_request_timestamp"
    assert len(data) == 3, f"Expected all 3 products under default limit, got {len(data)}"
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


# ─── Takeoff creation defaults and initial state ─────────────────────

def test_takeoff_created_in_draft(api):
    """PRD §3.4: "The draft begins in `DRAFT` status."

    Design: Corner/state_machines/takeoff_initial_state_is_draft
    """
    account = create_account(company_name="Init Co")
    project = create_project(account["id"])
    res = api_client.create_takeoff({"project_id": project["id"]}, EST)
    takeoff = validate_success(res, 201)
    assert takeoff["status"] == "DRAFT"


def test_takeoff_defaults_zero_aggregates(api):
    """PRD §3.4: "Nothing is priced while the takeoff is drafted."
    PRD §3.4: "Rolling up across active lines, the takeoff's `base_sheet_count`
    is the plain sum of `sheet_count`, its `billable_sheet_count` is the sum of
    `sheet_count` plus `waste_sheets` per line (equivalently, the base count
    padded for waste and rounded up to whole sheets), and its
    `quoted_subtotal_cents` is the sum of the per-line `quoted_line_cents`."

    A takeoff with no lines has empty sums: all aggregates are zero.

    Design: Corner/entities/takeoff_defaults_base_sheet_count_zero
    """
    account = create_account(company_name="Defaults Co", default_waste_pct_bp=1000)
    project = create_project(account["id"])
    res = api_client.create_takeoff({"project_id": project["id"]}, EST)
    takeoff = validate_success(res, 201)
    assert_takeoff(takeoff)
    assert takeoff["base_sheet_count"] == 0
    assert takeoff["billable_sheet_count"] == 0
    assert takeoff["quoted_subtotal_cents"] == 0


# ─── Waste allowance: account default vs takeoff override ────────────

def test_effective_waste_account_default_vs_override(api):
    """PRD §3.4: "The **effective waste allowance** for the takeoff is the
    `waste_pct_bp_override` when one was supplied, otherwise the account's
    `default_waste_pct_bp`."
    PRD §3.4: "Each active line's `waste_sheets` is its `sheet_count`
    multiplied by that effective allowance and divided by the 10,000
    basis-point denominator, rounded **up** to a whole sheet."

    100 sheets at 1000 bp default → 10 waste sheets → billable 110; at a 500 bp
    override → 5 waste sheets → billable 105. Bundle rounding
    (ceil(110/20)=ceil(105/20)=6 bundles at 1500c/sheet) prices both at 180000.

    Design: Corner/calculations/effective_waste_uses_account_default_when_no_override
    """
    account = create_account(company_name="Waste Co", default_waste_pct_bp=1000)
    product = create_product(sheets_per_bundle=20, unit_price_cents_per_sheet=1500)
    project = create_project(account["id"])

    tk_def, _ = create_takeoff_with_lines(project["id"], [(product["id"], 100)])
    tk_ovr, _ = create_takeoff_with_lines(
        project["id"], [(product["id"], 100)], waste_pct_bp_override=500)

    submit_takeoff(tk_def["id"])
    submit_takeoff(tk_ovr["id"])

    default_tk = get_takeoff(tk_def["id"])
    override_tk = get_takeoff(tk_ovr["id"])
    assert default_tk["billable_sheet_count"] == 110, (
        f"100 sheets + 10% waste must bill 110 sheets, got {default_tk['billable_sheet_count']}")
    assert override_tk["billable_sheet_count"] == 105, (
        f"100 sheets + 5% waste override must bill 105 sheets, got {override_tk['billable_sheet_count']}")
    assert default_tk["quoted_subtotal_cents"] == 180000
    assert override_tk["quoted_subtotal_cents"] == 180000


# ─── Dual-variant pricing at lock ────────────────────────────────────

def _setup_takeoff_with_price_move():
    """Account (10% waste) + REGULAR product (20/bundle, 1500c) + project +
    takeoff with one 50-sheet line, submitted, then price moved to 1700c."""
    account = create_account(company_name="Acme Drywall", default_waste_pct_bp=1000)
    product = create_product(sheets_per_bundle=20, unit_price_cents_per_sheet=1500)
    project = create_project(account["id"], distance_miles=10, framing_pct_complete=50)
    takeoff, _ = create_takeoff_with_lines(project["id"], [(product["id"], 50)])
    submitted = submit_takeoff(takeoff["id"])
    get_success_data(api_client.update_product(
        product["id"], {"unit_price_cents_per_sheet": 1700}, WH))
    return account, product, project, submitted


def test_lock_preserves_quoted_and_computes_final_subtotal(api):
    """PRD §3.5: "The `final_line_cents` of each line is recomputed exactly as
    the quoted amount was — bundle arithmetic unchanged — but using the
    product's `unit_price_cents_per_sheet` **as it stands at lock time** and
    the effective waste allowance as it stands at lock time, so a catalog price
    change between submission and lock flows into the final figures."
    PRD §3.5: "The takeoff's `final_subtotal_cents` is the sum of those
    per-line final amounts, while `quoted_subtotal_cents` is deliberately
    preserved untouched so the quote-to-final variance can be reported."

    50 sheets + 10% waste = 55 → ceil(55/20) = 3 bundles → 60 sheets billed:
    quoted at 1500c = 90000; final at 1700c = 102000.

    Design: Difficulty/dual_variant_calc/takeoff_lock_reprices_quoted_lines
    """
    _account, _product, _project, submitted = _setup_takeoff_with_price_move()
    assert submitted["quoted_subtotal_cents"] == 90000, (
        f"Provisional quote must snap submit-time prices: {submitted['quoted_subtotal_cents']}")

    locked = lock_takeoff(submitted["id"])
    assert locked["status"] == "LOCKED"
    assert locked["quoted_subtotal_cents"] == 90000, (
        f"quoted_subtotal_cents must be preserved untouched at lock, "
        f"got {locked['quoted_subtotal_cents']}")
    assert locked["final_subtotal_cents"] == 102000, (
        f"final_subtotal_cents must re-price at the lock-time price, "
        f"got {locked['final_subtotal_cents']}")


def test_lock_repricing_diverges_at_line_level(api, estimator_headers):
    """PRD §3.4: "The line's `quoted_line_cents` is then its `bundle_count`
    multiplied by the product's `sheets_per_bundle` multiplied by the product's
    **current** `unit_price_cents_per_sheet` — the provisional variant snaps
    today's catalog prices."
    PRD §3.5: "The `final_line_cents` of each line is recomputed exactly as the
    quoted amount was — bundle arithmetic unchanged — but using the product's
    `unit_price_cents_per_sheet` **as it stands at lock time** and the
    effective waste allowance as it stands at lock time, so a catalog price
    change between submission and lock flows into the final figures."

    Design: Difficulty/dual_variant_calc/takeoff_lock_reprices_quoted_lines
    """
    _account, _product, _project, submitted = _setup_takeoff_with_price_move()
    locked = lock_takeoff(submitted["id"])

    res = api_client.list_takeoff_lines(estimator_headers,
                                        params={"takeoff_id": locked["id"]})
    lines, _meta = validate_paginated(res)
    assert len(lines) == 1
    line = lines[0]
    assert line["waste_sheets"] == 5
    assert line["bundle_count"] == 3
    assert line["quoted_line_cents"] == 90000, (
        f"Provisional line price snaps the submit-time price, got {line['quoted_line_cents']}")
    assert line["final_line_cents"] == 102000, (
        f"Final line price uses the lock-time price, got {line['final_line_cents']}")
    assert line["quoted_line_cents"] != line["final_line_cents"]


# ─── Optimistic concurrency on lock (PRD §2.9) ───────────────────────

def test_lock_with_current_version_succeeds_and_increments(api):
    """PRD §3.5: "A successful lock increments the takeoff's `version` by one,
    so a second lock attempt carrying the same expected version necessarily
    fails as stale."
    PRD §2.9: "A lock request must carry the field `expected_takeoff_version`,
    holding the value of the takeoff's `version` the client last observed."

    Design: Corner/cross_cutting/optimistic_concurrency_correct_version_succeeds
    """
    account = create_account(company_name="Happy Co")
    product = create_product()
    project = create_project(account["id"])
    takeoff, _ = create_takeoff_with_lines(project["id"], [(product["id"], 20)])
    submit_takeoff(takeoff["id"])

    current = get_takeoff(takeoff["id"])
    res = api_client.lock_takeoff(
        takeoff["id"], {"expected_takeoff_version": current["version"]}, EST)
    locked = validate_success(res, 200)
    assert locked["status"] == "LOCKED"
    assert locked["version"] == current["version"] + 1, (
        f"Lock must increment version by one: {current['version']} -> {locked['version']}")


def test_lock_with_stale_version_rejected(api):
    """PRD §2.9: "If that value does not equal the takeoff's current `version`
    — because another estimator has since edited or locked it — the lock is
    rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a client from
    finalizing a pricing snapshot it never saw."

    Design: Corner/errors/err_stale_version_triggered_on_lock
    """
    account = create_account(company_name="OCC Co")
    product = create_product()
    project = create_project(account["id"])
    takeoff, _ = create_takeoff_with_lines(project["id"], [(product["id"], 20)])
    submit_takeoff(takeoff["id"])

    current = get_takeoff(takeoff["id"])
    res = api_client.lock_takeoff(
        takeoff["id"], {"expected_takeoff_version": current["version"] - 1}, EST)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


# ─── Takeoff cancellation paths ──────────────────────────────────────

def test_cancelled_takeoff_cannot_be_locked(api):
    """PRD §3.5: "The takeoff must actually be in `SUBMITTED` — locking
    anything else is rejected with `ERR_TAKEOFF_NOT_SUBMITTED` — and the
    optimistic-concurrency rule of Section 2.9 applies: the request must carry
    `expected_takeoff_version` equal to the takeoff's current `version`,
    failing which the lock is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    A CANCELLED takeoff is terminal; the lock is rejected either by the
    not-submitted guard or by the generic state guard.

    Design: Corner/state_machines/terminal_state_lockdown_cancelled_takeoff_cannot_lock
    """
    account = create_account(company_name="Term Co")
    product = create_product()
    project = create_project(account["id"])
    takeoff, _ = create_takeoff_with_lines(project["id"], [(product["id"], 20)])
    submit_takeoff(takeoff["id"])
    validate_success(api_client.cancel_takeoff(takeoff["id"], EST), 200)

    current = get_takeoff(takeoff["id"])
    res = api_client.lock_takeoff(
        takeoff["id"], {"expected_takeoff_version": current["version"]}, EST)
    actual = validate_error_is_one_of(
        res, [ApiErrorId.ERR_TAKEOFF_NOT_SUBMITTED, ApiErrorId.ERR_INVALID_STATE])
    assert actual in (ApiErrorId.ERR_TAKEOFF_NOT_SUBMITTED.value,
                      ApiErrorId.ERR_INVALID_STATE.value)


def test_submitted_takeoff_cancel_succeeds(api):
    """PRD §3.4: "A takeoff may be cancelled instead. From `DRAFT` the
    cancellation is unconditional. From `SUBMITTED` it is refused while any
    stocking order referencing the takeoff sits in `SCHEDULED` or `DISPATCHED`
    (`ERR_TAKEOFF_IN_USE`)."

    With no stocking order referencing it, SUBMITTED → CANCELLED is legal.

    Design: Difficulty/non_linear_state_machine/takeoff_cancel_releases_for_replacement
    """
    account = create_account(company_name="SM Co", default_waste_pct_bp=1000)
    product = create_product()
    project = create_project(account["id"], framing_pct_complete=50)
    takeoff, _ = create_takeoff_with_lines(project["id"], [(product["id"], 40)])
    submit_takeoff(takeoff["id"])

    res = api_client.cancel_takeoff(takeoff["id"], EST)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"


def test_cancelled_takeoff_replacement_can_be_submitted_and_locked(api):
    """PRD §3.4: "A takeoff may be cancelled instead. From `DRAFT` the
    cancellation is unconditional. From `SUBMITTED` it is refused while any
    stocking order referencing the takeoff sits in `SCHEDULED` or `DISPATCHED`
    (`ERR_TAKEOFF_IN_USE`)."

    The cancelled takeoff releases the project: a fresh takeoff on the same
    project goes all the way to LOCKED.

    Design: Difficulty/non_linear_state_machine/takeoff_cancel_releases_for_replacement
    """
    account = create_account(company_name="SM Co 2", default_waste_pct_bp=1000)
    product = create_product()
    project = create_project(account["id"], framing_pct_complete=50)
    takeoff, _ = create_takeoff_with_lines(project["id"], [(product["id"], 40)])
    submit_takeoff(takeoff["id"])
    validate_success(api_client.cancel_takeoff(takeoff["id"], EST), 200)

    takeoff2, _ = create_takeoff_with_lines(project["id"], [(product["id"], 40)])
    submit_takeoff(takeoff2["id"])
    locked = lock_takeoff(takeoff2["id"])
    assert locked["status"] == "LOCKED"


# ─── Empty-takeoff boundary (PRD §3.4) ───────────────────────────────

def test_submit_with_zero_active_lines_rejected(api):
    """PRD §3.4: "Submission is the first pricing event: the takeoff moves from
    `DRAFT` to `SUBMITTED`, guarded by two checks — the owning account must be
    `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`) and the takeoff must contain at least
    one line whose `line_status` is `ACTIVE` (`ERR_EMPTY_TAKEOFF`), with the
    special-order check described below ranking ahead of the empty-takeoff
    check in the global priority order."

    The only line was soft-cancelled, leaving zero ACTIVE lines.

    Design: Difficulty/boundary_precision_check/empty_takeoff_submit_rejected_at_zero_active_lines
    """
    account = create_account(company_name="Empty Co")
    product = create_product()
    project = create_project(account["id"])
    takeoff, lines = create_takeoff_with_lines(project["id"], [(product["id"], 20)])
    validate_success(
        api_client.delete_takeoff_line(takeoff["id"], lines[0]["id"], EST), 200)

    res = api_client.submit_takeoff(takeoff["id"], EST)
    validate_error(res, ApiErrorId.ERR_EMPTY_TAKEOFF)


def test_submit_with_one_active_line_succeeds(api):
    """PRD §3.4: "Submission is the first pricing event: the takeoff moves from
    `DRAFT` to `SUBMITTED`, guarded by two checks — the owning account must be
    `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`) and the takeoff must contain at least
    one line whose `line_status` is `ACTIVE` (`ERR_EMPTY_TAKEOFF`), with the
    special-order check described below ranking ahead of the empty-takeoff
    check in the global priority order."

    One ACTIVE line satisfies the non-empty boundary.

    Design: Difficulty/boundary_precision_check/empty_takeoff_submit_rejected_at_zero_active_lines
    """
    account = create_account(company_name="Empty Co 2")
    product = create_product()
    project = create_project(account["id"])
    takeoff, _ = create_takeoff_with_lines(project["id"], [(product["id"], 20)])

    submitted = submit_takeoff(takeoff["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["base_sheet_count"] == 20
