"""Accounting-record creation guards, daily accrual computation, and OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_money,
    assert_nav_invariants,
    assert_nav_record,
    assert_rate,
    base_kit,
    base_kit_with_final_nav,
    base_kit_with_nav,
    create_fund,
    create_manual_accrual,
    create_nav,
    create_nav_record_payload,
    create_security,
    create_share_class,
    finalize_nav,
    open_position,
    set_logical_clock,
    submit_price,
    approve_price,
    subscribe_shares,
    make_fund_accountant_headers,
    make_fund_controller_headers,
    validate_error,
    validate_success,
)

CTRL = TEST_USERS["fund_controller_headers"]
ACCT = TEST_USERS["fund_accountant_headers"]


def test_nav_record_initial_state_estimated(api):
    """PRD §3.4: "The new record is born `ESTIMATED`, and the creator's
    identifier is captured in `created_by_user_id` for the
    segregation-of-duties check at finalize time."
    PRD §3.4: "The record's `pricing_variant_used` reads `PROVISIONAL` while
    the record is `ESTIMATED` and `FINAL_PRICED` once it has reached `FINAL`
    or `REOPENED`."

    Design: Corner/state_machines/nav_record_initial_state_estimated
    """
    kit = base_kit(approve=False)
    resp = api.create_nav_record(
        create_nav_record_payload(kit["share_class"]["id"]),
        make_fund_accountant_headers("acct_1"),
    )
    nav = validate_success(resp, 201)
    assert_nav_record(nav)
    assert nav["status"] == "ESTIMATED"
    assert nav["pricing_variant_used"] == "PROVISIONAL"


def test_accrual_day_count_act365(api):
    """PRD §3.5: "The day count is 365 for an `ACT_365` fund and 360 for an
    `ACT_360` fund, so an identical base and rate accrue less per day under
    `ACT_365` than under `ACT_360` — a base of 52,340.00 at 10 basis points
    accrues 0.14 per day under `ACT_365` but 0.15 under `ACT_360`."

    Design: Difficulty/dual_variant_calc/expense_accrual_day_count_divergence
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund(ticker="F365X", day_count_convention="ACT_365")
    share_class = create_share_class(fund["id"], class_ticker="F365A")
    subscribe_shares(share_class["id"], 10000)
    security = create_security(security_identifier="CUSIP0365")
    open_position(share_class["id"], security["id"], quantity=5234,
                  cost_basis_total=52340)
    submit_price(security["id"], price=10.00)
    nav = create_nav(share_class["id"])
    # round2(52340.00 x 10 / 10000 / 365) = 0.14
    assert_money(nav["expense_accrual_total"], 0.14, "ACT_365 accrual")
    assert_money(nav["total_net_assets"], 52339.86, "ACT_365 TNA")


def test_accrual_day_count_act360(api):
    """PRD §3.5: "The day count is 365 for an `ACT_365` fund and 360 for an
    `ACT_360` fund, so an identical base and rate accrue less per day under
    `ACT_365` than under `ACT_360` — a base of 52,340.00 at 10 basis points
    accrues 0.14 per day under `ACT_365` but 0.15 under `ACT_360`."

    Design: Difficulty/dual_variant_calc/expense_accrual_day_count_divergence
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund(ticker="F360X", day_count_convention="ACT_360")
    share_class = create_share_class(fund["id"], class_ticker="F360A")
    subscribe_shares(share_class["id"], 10000)
    security = create_security(security_identifier="CUSIP0360")
    open_position(share_class["id"], security["id"], quantity=5234,
                  cost_basis_total=52340)
    submit_price(security["id"], price=10.00)
    nav = create_nav(share_class["id"])
    # round2(52340.00 x 10 / 10000 / 360) = 0.15
    assert_money(nav["expense_accrual_total"], 0.15, "ACT_360 accrual")
    assert_money(nav["total_net_assets"], 52339.85, "ACT_360 TNA")


def test_nav_per_position_rounding_before_sum(api):
    """PRD §2.6: "Position market values are rounded to 2 decimal places per
    position before they are summed into a gross asset value — summing raw
    products and rounding once at the end yields different cents and is
    non-conformant."

    Design: Corner/calculations/nav_per_position_rounding_before_sum
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    subscribe_shares(share_class["id"], 100)
    sec_a = create_security(security_identifier="CUSIP0001")
    sec_b = create_security(security_identifier="CUSIP0002")
    open_position(share_class["id"], sec_a["id"], quantity=1, cost_basis_total=2.00)
    open_position(share_class["id"], sec_b["id"], quantity=1, cost_basis_total=2.00)
    px_a = submit_price(sec_a["id"], price=2.005)
    px_b = submit_price(sec_b["id"], price=2.005)
    approve_price(px_a["id"])
    approve_price(px_b["id"])

    nav = create_nav(share_class["id"])
    # round2(1 x 2.005) + round2(1 x 2.005) = 2.01 + 2.01
    assert_money(nav["gross_asset_value"], 4.02, "gross_asset_value")
    assert_money(nav["expense_accrual_total"], 0.00, "expense_accrual_total")
    assert_money(nav["total_net_assets"], 4.02, "total_net_assets")
    assert_rate(nav["nav_per_share"], 0.0402, "nav_per_share")


def test_accrual_base_uses_prior_final_tna(api):
    """PRD §3.5: "The row's `base_net_assets` is the `total_net_assets` of the
    class's `FINAL` accounting record bearing the greatest `accounting_date`
    strictly before the accrual's date; when no such `FINAL` record exists —
    which is the case for the class's first-ever record — the base is instead
    the current `gross_asset_value` of the `ESTIMATED` record being built."

    Design: Corner/calculations/accrual_base_uses_prior_final_tna
    """
    kit = base_kit_with_final_nav()  # 2026-08-04 FINAL, TNA 99999.73
    set_logical_clock("2026-08-05T00:00:00Z")
    px2 = submit_price(kit["security"]["id"], price_date="2026-08-05",
                       price=200.00)
    approve_price(px2["id"])
    nav2 = create_nav(kit["share_class"]["id"], accounting_date="2026-08-05")
    assert_money(nav2["gross_asset_value"], 200000.00, "gross_asset_value")
    # Base is the prior FINAL TNA 99999.73, not the doubled current GAV.
    assert_money(nav2["expense_accrual_total"], 0.27, "expense_accrual_total")
    assert_money(nav2["total_net_assets"], 199999.73, "total_net_assets")
    assert_rate(nav2["nav_per_share"], 20.0000, "nav_per_share")


def test_duplicate_nav_date_rejected(api):
    """PRD §3.4: "The `accounting_date` must be strictly later than every
    existing record for that class — anything else is rejected with
    `ERR_NAV_DATE_NOT_SEQUENTIAL` (HTTP 409)."

    Design: Corner/validations/duplicate_nav_date_rejected
    """
    kit = base_kit(approve=False)
    create_nav(kit["share_class"]["id"])
    resp = api.create_nav_record(
        create_nav_record_payload(kit["share_class"]["id"]),
        make_fund_accountant_headers("acct_1"),
    )
    validate_error(resp, ApiErrorId.ERR_NAV_DATE_NOT_SEQUENTIAL, 409)


def test_nav_create_missing_price_rejected(api):
    """PRD §3.4: "Every `OPEN` position of the class must have at least one
    price observation of any status for its security on the `accounting_date`;
    a held security with no observation at all blocks creation with
    `ERR_MISSING_PRICE` (HTTP 422)."

    Design: Corner/validations/nav_create_missing_price_rejected
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    subscribe_shares(share_class["id"], 10000)
    security = create_security()
    open_position(share_class["id"], security["id"], quantity=1000)
    resp = api.create_nav_record(
        create_nav_record_payload(share_class["id"]), ACCT
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_PRICE, 422)


def test_nav_create_without_shares_rejected(api):
    """PRD §3.4: "And, as the fiscal check evaluated last in the pipeline, the
    class must actually have shares outstanding — creating a record while
    `shares_outstanding` is zero is rejected with `ERR_NO_SHARES_OUTSTANDING`
    (HTTP 422)."

    Design: Corner/validations/nav_create_without_shares_rejected
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    security = create_security()
    open_position(share_class["id"], security["id"], quantity=1000)
    submit_price(security["id"])
    resp = api.create_nav_record(
        create_nav_record_payload(share_class["id"]), ACCT
    )
    validate_error(resp, ApiErrorId.ERR_NO_SHARES_OUTSTANDING, 422)


def test_nav_create_rejects_computed_field_input(api):
    """PRD §2.9: "4. Request-body shape — required fields present, no unknown
    fields (system-managed fields such as `id`, `created_at`, `updated_at`, and
    `version` included), correct types and enum values, and numeric ranges
    respected (a price greater than zero, a creation quantity greater than
    zero, a counterparty quantity of zero or more, a cap rate greater than
    zero, an annual accrual rate greater than zero, a recovery window of one to
    thirty-six months, period and effectiveness end dates not before their
    start dates, positive amounts, positive share counts where supplied, and a
    well-formed clock timestamp) — `ERR_VALIDATION` (HTTP 400)."
    PRD §3.4: "Each business day, a `FundAccountant` creates the class's
    accounting record by supplying its `share_class_id` and the
    `accounting_date`."

    Design: Corner/entities/nav_create_rejects_computed_field_input
    """
    kit = base_kit(approve=False)
    payload = create_nav_record_payload(kit["share_class"]["id"])
    payload["gross_asset_value"] = 1
    resp = api.create_nav_record(payload, ACCT)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


def test_manual_admin_fee_accrual_rejected(api):
    """PRD §3.5: "`ADMIN_FEE` rows are system-managed and a manual create in
    that category is rejected with `ERR_CATEGORY_SYSTEM_MANAGED` (HTTP 422)."

    Design: Corner/validations/manual_admin_fee_accrual_rejected
    """
    kit = base_kit_with_nav(approve=False)
    resp = api.create_expense_accrual(
        {"share_class_id": kit["share_class"]["id"],
         "accrual_date": "2026-08-04", "category": "ADMIN_FEE",
         "annual_rate_bps": 5},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_CATEGORY_SYSTEM_MANAGED, 422)


def test_accrual_without_estimable_nav_rejected(api):
    """PRD §3.5: "The `accrual_date` must match an existing `ESTIMATED`
    accounting record for the class — otherwise the create is rejected with
    `ERR_NO_ESTIMABLE_NAV` (HTTP 422)"

    Design: Corner/validations/accrual_without_estimable_nav_rejected
    """
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    subscribe_shares(share_class["id"], 10000)
    resp = api.create_expense_accrual(
        {"share_class_id": share_class["id"], "accrual_date": "2026-08-04",
         "category": "CUSTODY_FEE", "annual_rate_bps": 5},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ESTIMABLE_NAV, 422)


def test_occ_finalize_stale_version(api):
    """PRD §2.8: "If the supplied value does not match the record's current
    `version`, the request is rejected with `ERR_STALE_NAV_VERSION` (HTTP 412);
    the client must re-read the record and resubmit against the fresh version."
    PRD §3.5: "Booking a manual accrual recomputes the matching `ESTIMATED`
    record — its `expense_accrual_total`, `total_net_assets`, and
    `nav_per_share` — and increments that record's `version` by one."

    Design: Corner/complexity_layers/occ_finalize_stale_version
    """
    kit = base_kit_with_nav(approve=True)
    nav_id = kit["nav"]["id"]
    stale_version = kit["nav"]["version"]

    create_manual_accrual(kit["share_class"]["id"], "2026-08-04",
                          category="CUSTODY_FEE", annual_rate_bps=5)

    stale = api.finalize_nav_record(
        nav_id, {"expected_nav_record_version": stale_version},
        make_fund_controller_headers("ctl_1"),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_NAV_VERSION, 412)

    fresh = validate_success(api.get_nav_record(nav_id, CTRL), 200)
    assert fresh["version"] == stale_version + 1
    # 0.27 admin row + round2(100000.00 x 5 / 10000 / 365) = 0.14 custody row.
    assert_money(fresh["expense_accrual_total"], 0.41, "expense_accrual_total")

    ok = api.finalize_nav_record(
        nav_id, {"expected_nav_record_version": fresh["version"]},
        make_fund_controller_headers("ctl_1"),
    )
    assert validate_success(ok, 200)["status"] == "FINAL"


def test_immediate_consistency_read_after_write(api):
    """PRD §2.10: "Every mutation, together with every cascade it triggers,
    commits atomically within its request: a price approval that recomputes
    several estimated records, a break resolution that moves a position and
    rebuilds the class's books, a finalization that posts accruals and books a
    waiver entry — each of these either fully succeeds or fully fails, with no
    intermediate state visible."

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    kit = base_kit_with_nav(approve=True)
    nav_id = kit["nav"]["id"]

    read1 = validate_success(api.get_nav_record(nav_id, TEST_USERS["pricing_committee_headers"]), 200)
    assert_money(read1["gross_asset_value"], 100000.00, "gross_asset_value")
    assert_money(read1["total_net_assets"], 99999.73, "total_net_assets")
    assert_nav_invariants(read1)

    finalize_nav(nav_id, expected_version=read1["version"])
    read2 = validate_success(api.get_nav_record(nav_id, ACCT), 200)
    assert read2["status"] == "FINAL"
    assert read2["pricing_variant_used"] == "FINAL_PRICED"
