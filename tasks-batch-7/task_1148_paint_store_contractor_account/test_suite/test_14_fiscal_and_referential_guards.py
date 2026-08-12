"""Fiscal caps (credit limit, budget cap), return guards, spec attribution,
and temporal guards on delivery windows, rebate periods, and bulletin
effective dates (PRD §3.1-§3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_delivery_payload,
    create_job_for_account,
    create_order_payload,
    create_publish_bulletin,
    create_product,
    create_rebate_statement_payload,
    create_spec_sheet_with_line,
    create_tint_formula_payload,
    get_account_version,
    get_first_order_line,
    get_first_spec_line,
    make_contractor_headers,
    place_and_pay_order,
    place_order,
    schedule_delivery,
    set_logical_clock,
    setup_account_job_product,
    setup_account_with_job,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
MANAGER = TEST_USERS["manager_headers"]
WRITER = TEST_USERS["spec_writer_headers"]


def test_credit_limit_exact_fit_passes(api):
    """PRD §3.6: "and only then the two fiscal caps — the account's
    `outstanding_balance_cents` plus the new order's `total_cents` must not
    exceed its `credit_limit_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 422),
    and the job's budget cap of §3.2 is checked after the credit limit."

    An order whose 43300 total exactly equals the 43300 credit limit passes:
    "must not exceed" is inclusive at equality.

    Design: Corner/validations/credit_limit_exact_fit_passes
    """
    account, _, job, product = setup_account_job_product(
        company_name="Fit Co", credit_limit_cents=43_300,
        jurisdiction_code="OK-OPEN", jurisdiction_name="Oklahoma",
        sku="P-FIT", list_price_cents=40_000)
    resp = api.create_order(
        create_order_payload(account["id"], job["id"],
                             get_account_version(account["id"]),
                             [{"product_id": product["id"], "quantity": 1}]),
        ASSOCIATE)
    order = validate_success(resp, expected_status=201)
    assert order["total_cents"] == 43_300, (
        f"total 40000 + tax 3300 = 43300 exactly fits the 43300 limit, "
        f"got {order['total_cents']}")


def test_credit_limit_one_cent_over_fails(api):
    """PRD §3.6: "and only then the two fiscal caps — the account's
    `outstanding_balance_cents` plus the new order's `total_cents` must not
    exceed its `credit_limit_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 422),
    and the job's budget cap of §3.2 is checked after the credit limit."

    With 43300 already outstanding against a 43300 limit, an identical second
    order pushes the exposure to 86600 and is rejected.

    Design: Corner/validations/credit_limit_exact_fit_passes
    """
    account, _, job, product = setup_account_job_product(
        company_name="Fit Co", credit_limit_cents=43_300,
        jurisdiction_code="OK-OPEN", jurisdiction_name="Oklahoma",
        sku="P-FIT", list_price_cents=40_000)
    place_order(account["id"], job["id"],
                [{"product_id": product["id"], "quantity": 1}])
    resp = api.create_order(
        create_order_payload(account["id"], job["id"],
                             get_account_version(account["id"]),
                             [{"product_id": product["id"], "quantity": 1}]),
        ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


def _setup_two_jobs(api):
    """One account with an uncapped job and a job capped at 10000; a 5000-list
    product."""
    account, jurisdiction, job_uncapped = setup_account_with_job(
        company_name="Bud Co", credit_limit_cents=1_000_000,
        jurisdiction_code="AR-OPEN", jurisdiction_name="Arkansas",
        job_name="Free")
    job_capped = create_job_for_account(account["id"], jurisdiction["id"],
                                        job_name="Capped", site_address="2 Ln",
                                        budget_cap_cents=10_000)
    product = create_product(sku="P-BUD", name="Can", list_price_cents=5000)
    return account, job_uncapped, job_capped, product


def test_uncapped_job_accepts_any_order(api):
    """PRD §3.2: "When a new order is created against the job, the cap is
    enforced at that moment: `spent_cents` plus the new order's `total_cents`
    must not exceed `budget_cap_cents`, or the create fails with
    `ERR_BUDGET_CAP_EXCEEDED` (HTTP 422); the check is skipped entirely for an
    uncapped job."

    Design: Corner/validations/budget_cap_null_vs_set
    """
    account, job_uncapped, _, product = _setup_two_jobs(api)
    resp = api.create_order(
        create_order_payload(account["id"], job_uncapped["id"],
                             get_account_version(account["id"]),
                             [{"product_id": product["id"], "quantity": 2}]),
        ASSOCIATE)
    order = validate_success(resp, expected_status=201)
    assert order["total_cents"] == 10_825


def test_capped_job_rejects_over_cap_order(api):
    """PRD §3.2: "When a new order is created against the job, the cap is
    enforced at that moment: `spent_cents` plus the new order's `total_cents`
    must not exceed `budget_cap_cents`, or the create fails with
    `ERR_BUDGET_CAP_EXCEEDED` (HTTP 422); the check is skipped entirely for an
    uncapped job."

    The identical 10825-total order exceeds the 10000 cap from a zero spend.

    Design: Corner/validations/budget_cap_null_vs_set
    """
    account, _, job_capped, product = _setup_two_jobs(api)
    resp = api.create_order(
        create_order_payload(account["id"], job_capped["id"],
                             get_account_version(account["id"]),
                             [{"product_id": product["id"], "quantity": 2}]),
        ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_BUDGET_CAP_EXCEEDED)


def _setup_paid_custom_tint_order(api):
    """Paid order whose single line carries a formula (custom tint)."""
    account, _, job, product = setup_account_job_product(
        company_name="Tint Co", credit_limit_cents=1_000_000,
        jurisdiction_code="RI-OPEN", jurisdiction_name="Rhode Island",
        sku="P-TINT", product_name="Base", list_price_cents=5000, tintable=True)
    resp = api.create_tint_formula(
        create_tint_formula_payload(product["id"], color_code="SW 4000",
                                    name="Custom"),
        ADMIN)
    formula = validate_success(resp, expected_status=201)
    order = place_and_pay_order(
        account["id"], job["id"],
        [{"product_id": product["id"], "quantity": 1,
          "formula_id": formula["id"]}],
        headers=ASSOCIATE)
    line = get_first_order_line(order["id"])
    return account, order, line


def test_custom_tint_line_never_returnable(api):
    """PRD §3.7: "Three guards apply in order: the line's order must have
    `payment_status` `PAID` or `PARTIALLY_REFUNDED` — an unpaid or fully
    refunded order has nothing to return against — otherwise
    `ERR_ORDER_NOT_REFUNDABLE` (HTTP 409); then the custom-tint prohibition —
    a line with `is_custom_tint` true is never returnable regardless of how
    many units remain, and the attempt is rejected with
    `ERR_CUSTOM_TINT_NO_RETURN` (HTTP 422); then the remaining-quantity check
    — the requested `quantity` must not exceed the line's `quantity` minus its
    `returned_quantity` so far, otherwise `ERR_RETURN_QUANTITY_EXCEEDED` (HTTP
    422)."

    The line is PAID with full quantity remaining; only the custom-tint
    prohibition can fire.

    Design: Corner/validations/custom_tint_line_never_returnable
    """
    account, order, line = _setup_paid_custom_tint_order(api)
    assert line["is_custom_tint"] is True
    resp = api.return_order_line(line["id"], {"quantity": 1}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_CUSTOM_TINT_NO_RETURN)
    line_after = validate_success(api.get_order_line(line["id"], ASSOCIATE))
    assert line_after["returned_quantity"] == 0, (
        "the rejected return must not consume any quantity")


def test_return_within_remaining_quantity_succeeds(api):
    """PRD §3.7: "then the remaining-quantity check — the requested `quantity`
    must not exceed the line's `quantity` minus its `returned_quantity` so
    far, otherwise `ERR_RETURN_QUANTITY_EXCEEDED` (HTTP 422)."

    Returning 2 of a 3-unit stock line succeeds and returns_quantity grows to
    2.

    Design: Corner/validations/return_cannot_exceed_remaining_quantity
    """
    account, _, job, product = setup_account_job_product(
        company_name="QtyR Co", credit_limit_cents=1_000_000,
        jurisdiction_code="DE-OPEN", jurisdiction_name="Delaware",
        sku="P-QR", list_price_cents=5000)
    order = place_and_pay_order(account["id"], job["id"],
                                [{"product_id": product["id"], "quantity": 3}],
                                headers=ASSOCIATE)
    line = get_first_order_line(order["id"])
    resp = api.return_order_line(line["id"], {"quantity": 2}, ASSOCIATE)
    record = validate_success(resp, expected_status=201)
    assert record["quantity"] == 2
    line_after = validate_success(api.get_order_line(line["id"], ASSOCIATE))
    assert line_after["returned_quantity"] == 2


def test_return_beyond_remaining_quantity_rejected(api):
    """PRD §3.7: "then the remaining-quantity check — the requested `quantity`
    must not exceed the line's `quantity` minus its `returned_quantity` so
    far, otherwise `ERR_RETURN_QUANTITY_EXCEEDED` (HTTP 422)."

    With 2 of 3 units already returned, a second return of 2 exceeds the
    remaining 1.

    Design: Corner/validations/return_cannot_exceed_remaining_quantity
    """
    account, _, job, product = setup_account_job_product(
        company_name="QtyR Co", credit_limit_cents=1_000_000,
        jurisdiction_code="DE-OPEN", jurisdiction_name="Delaware",
        sku="P-QR", list_price_cents=5000)
    order = place_and_pay_order(account["id"], job["id"],
                                [{"product_id": product["id"], "quantity": 3}],
                                headers=ASSOCIATE)
    line = get_first_order_line(order["id"])
    validate_success(api.return_order_line(line["id"], {"quantity": 2}, ASSOCIATE),
                     expected_status=201)
    resp = api.return_order_line(line["id"], {"quantity": 2}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDED)


def test_spec_attribution_requires_approved_sheet(api):
    """PRD §3.6: "then the referential checks — every referenced product must
    be `ACTIVE` (`ERR_PRODUCT_DISCONTINUED`), every referenced formula must be
    `ACTIVE` (`ERR_FORMULA_RETIRED`, HTTP 422), each formula's own
    `product_id` must equal its line's `product_id`
    (`ERR_FORMULA_PRODUCT_MISMATCH`, HTTP 422), and each referenced spec line
    must name the same product as its order line *and* belong to a sheet whose
    `status` is `APPROVED` — pull-through attribution only ever runs against
    approved specs — (`ERR_SPEC_LINE_PRODUCT_MISMATCH`, HTTP 422); ...".

    The referenced line's product matches, but its sheet is still DRAFT.

    Design: Corner/validations/spec_attribution_requires_approved_sheet
    """
    account, _, job, product = setup_account_job_product(
        company_name="Attr Co", credit_limit_cents=1_000_000,
        jurisdiction_code="NH-OPEN", jurisdiction_name="New Hampshire",
        sku="P-ATTR", list_price_cents=5000)
    sheet = create_spec_sheet_with_line(product["id"], project_code="PRJ-DR",
                                        specified_qty=5)
    line = get_first_spec_line(sheet["id"])
    resp = api.create_order(
        create_order_payload(account["id"], job["id"],
                             get_account_version(account["id"]),
                             [{"product_id": product["id"], "quantity": 1,
                               "spec_line_id": line["id"]}]),
        ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_SPEC_LINE_PRODUCT_MISMATCH)


def test_past_delivery_window_rejected(api):
    """PRD §3.8: "The guards run in pipeline order: the window shape —
    `window_end` must be after `window_start` — is a generic shape failure
    (`ERR_VALIDATION`); the contractor account must be `ACTIVE`
    (`ERR_ACCOUNT_SUSPENDED`) and the job `OPEN` (`ERR_JOB_NOT_OPEN`, HTTP
    409); the `window_start` must not lie before the logical clock now
    (`ERR_DELIVERY_WINDOW_PAST`, HTTP 422); then the buffer rule — ...".

    With the default logical clock at 2026-05-01, a 2026-04-01 window is in
    the past.

    Design: Corner/validations/past_delivery_window_rejected
    """
    account, _, job, product = setup_account_job_product(
        company_name="Past Co", credit_limit_cents=1_000_000,
        jurisdiction_code="IA-OPEN", jurisdiction_name="Iowa",
        sku="P-PAST", list_price_cents=5000)
    order = place_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 1}])
    resp = api.create_delivery(
        create_delivery_payload(order["id"], job["id"],
                                window_start="2026-04-01T09:00:00Z",
                                window_end="2026-04-01T10:00:00Z"),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_PAST)


def _setup_q2_statement(api):
    """Account with one statement for [2026-04-01, 2026-07-01), generated at
    clock 2026-07-05."""
    set_logical_clock("2026-07-05T00:00:00Z")
    account = validate_success(
        api.create_contractor_account(
            {"company_name": "Per Co", "credit_limit_cents": 1_000_000}, ADMIN),
        expected_status=201)
    stmt = validate_success(
        api.create_rebate_statement(
            create_rebate_statement_payload(account["id"],
                                            "2026-04-01T00:00:00Z",
                                            "2026-07-01T00:00:00Z"),
            ADMIN),
        expected_status=201)
    return account, stmt


def test_overlapping_rebate_period_rejected(api):
    """PRD §3.9: "Generation requires `period_end` after `period_start` (a
    shape failure, `ERR_VALIDATION`), requires the logical clock now to have
    reached `period_start` — a statement cannot be opened for a future period
    — (`ERR_REBATE_PERIOD_INVALID`, HTTP 422), and requires that no existing
    statement for the same account has a period overlapping the new one under
    half-open semantics, with adjacency allowed (`ERR_REBATE_PERIOD_OVERLAP`,
    HTTP 409)."

    A June-start window genuinely overlaps the existing Q2 statement.

    Design: Corner/validations/rebate_period_overlap_and_adjacency
    """
    account, _ = _setup_q2_statement(api)
    resp = api.create_rebate_statement(
        create_rebate_statement_payload(account["id"],
                                        "2026-06-01T00:00:00Z",
                                        "2026-08-01T00:00:00Z"),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_REBATE_PERIOD_OVERLAP)


def test_adjacent_rebate_period_allowed(api):
    """PRD §2.10: "Three kinds of time window recur, and all three use
    half-open semantics: the start instant is included, the end instant is
    excluded. A VOC rule is effective from `effective_from` (inclusive) until
    `effective_to` (exclusive), with a null `effective_to` meaning open-ended.
    A rebate statement covers [`period_start`, `period_end`). A delivery
    occupies [`window_start`, `window_end`). Overlap rules follow from the
    same semantics: two windows that merely touch — one ending exactly when
    the other begins — are adjacent, not overlapping, and are allowed unless a
    workflow says otherwise." PRD §3.9: "Generation requires `period_end`
    after `period_start` (a shape failure, `ERR_VALIDATION`), requires the
    logical clock now to have reached `period_start` — a statement cannot be
    opened for a future period — (`ERR_REBATE_PERIOD_INVALID`, HTTP 422), and
    requires that no existing statement for the same account has a period
    overlapping the new one under half-open semantics, with adjacency allowed
    (`ERR_REBATE_PERIOD_OVERLAP`, HTTP 409)."

    Q3 starts exactly at Q2's period_end.

    Design: Corner/validations/rebate_period_overlap_and_adjacency
    """
    account, _ = _setup_q2_statement(api)
    resp = api.create_rebate_statement(
        create_rebate_statement_payload(account["id"],
                                        "2026-07-01T00:00:00Z",
                                        "2026-10-01T00:00:00Z"),
        ADMIN)
    stmt = validate_success(resp, expected_status=201)
    assert stmt["status"] == "ACCRUED"


def test_take_effect_before_effective_date_rejected(api):
    """PRD §3.3: "Taking effect moves `PUBLISHED` to `EFFECTIVE`, allowed only
    once the logical clock has reached `effective_date` (attempting it earlier
    yields `ERR_BULLETIN_NOT_YET_EFFECTIVE`, HTTP 422)."

    With the default clock 2026-05-01 the 2026-06-01 bulletin is not yet due.

    Design: Corner/validations/bulletin_take_effect_before_effective_date
    """
    p_old = create_product(sku="P-BEF", name="Old", list_price_cents=5000)
    p_new = create_product(sku="P-AFT", name="New", voc_gpl=110,
                           list_price_cents=5500)
    bulletin = create_publish_bulletin(p_old["id"], p_new["id"],
                                       effective_date="2026-06-01T00:00:00Z",
                                       title="B")
    resp = api.take_effect_product_bulletin(bulletin["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_BULLETIN_NOT_YET_EFFECTIVE)


def test_take_effect_at_effective_date_succeeds(api):
    """PRD §3.3: "Taking effect moves `PUBLISHED` to `EFFECTIVE`, allowed only
    once the logical clock has reached `effective_date` (attempting it earlier
    yields `ERR_BULLETIN_NOT_YET_EFFECTIVE`, HTTP 422)."

    Once the clock reaches 2026-06-01 the same bulletin takes effect.

    Design: Corner/validations/bulletin_take_effect_before_effective_date
    """
    p_old = create_product(sku="P-BEF", name="Old", list_price_cents=5000)
    p_new = create_product(sku="P-AFT", name="New", voc_gpl=110,
                           list_price_cents=5500)
    bulletin = create_publish_bulletin(p_old["id"], p_new["id"],
                                       effective_date="2026-06-01T00:00:00Z",
                                       title="B")
    validate_error(api.take_effect_product_bulletin(bulletin["id"], ADMIN),
                   ApiErrorId.ERR_BULLETIN_NOT_YET_EFFECTIVE)
    set_logical_clock("2026-06-01T00:00:00Z")
    effected = validate_success(api.take_effect_product_bulletin(bulletin["id"], ADMIN))
    assert effected["status"] == "EFFECTIVE"


def test_contractor_cannot_act_on_other_account(api):
    """PRD §2.1: "When `X-User-Role` is `Contractor`, `X-User-ID` is the `id`
    of the acting `ContractorAccount`; ownership checks on any resource that
    references a `ContractorAccount` compare the resource's foreign-key field
    to `X-User-ID`. That ownership chain runs directly on contractor-facing
    resources and indirectly through the resource's `contractor_account_id`
    chain via job account, order, rebate statement, or color-match request; a
    `Contractor` caller whose `X-User-ID` does not match the owning account is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Contractor A's identity against contractor B's order is refused before
    any state check.

    Design: Corner/validations/contractor_cannot_act_on_other_account
    """
    acct_a = validate_success(
        api.create_contractor_account(
            {"company_name": "A Co", "credit_limit_cents": 1_000_000}, ADMIN),
        expected_status=201)
    account_b, _, job_b, product = setup_account_job_product(
        company_name="B Co", credit_limit_cents=1_000_000,
        jurisdiction_code="MS-OPEN", jurisdiction_name="Mississippi",
        job_name="JB", sku="P-OWN", list_price_cents=5000)
    order_b = place_order(account_b["id"], job_b["id"],
                          [{"product_id": product["id"], "quantity": 1}])
    resp = api.pay_order(order_b["id"], make_contractor_headers(acct_a["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    after = validate_success(api.get_order(order_b["id"], ASSOCIATE))
    assert after["payment_status"] == "UNPAID", (
        "the refused call must not mutate the order")


def test_rebate_generate_before_period_start_rejected(api):
    """PRD §3.9: "Generation requires `period_end` after `period_start` (a
    shape failure, `ERR_VALIDATION`), requires the logical clock now to have
    reached `period_start` — a statement cannot be opened for a future period
    — (`ERR_REBATE_PERIOD_INVALID`, HTTP 422), and requires that no existing
    statement for the same account has a period overlapping the new one under
    half-open semantics, with adjacency allowed (`ERR_REBATE_PERIOD_OVERLAP`,
    HTTP 409)."

    At clock 2026-03-15 a period starting 2026-04-01 is still in the future.

    Design: Corner/validations/rebate_generate_before_period_start_rejected
    """
    set_logical_clock("2026-03-15T00:00:00Z")
    account = validate_success(
        api.create_contractor_account(
            {"company_name": "Fut Co", "credit_limit_cents": 1_000_000}, ADMIN),
        expected_status=201)
    resp = api.create_rebate_statement(
        create_rebate_statement_payload(account["id"],
                                        "2026-04-01T00:00:00Z",
                                        "2026-07-01T00:00:00Z"),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_REBATE_PERIOD_INVALID)
