"""Error precedence inside the fixed validation pipeline (PRD §2.8, §3.6):
state errors mask fiscal caps, and safety errors mask referential errors."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_order_payload,
    create_tint_formula_payload,
    create_voc_rule,
    get_account_version,
    place_order,
    setup_account_job_product,
    setup_account_with_job,
    create_product,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]


def _setup_suspended_account_over_credit(api):
    """Account with credit limit 50000 and one UNPAID order of total 43300
    (40000 list + 3300 tax); then the account is suspended."""
    account, _, job, product = setup_account_job_product(
        company_name="Tight Co", credit_limit_cents=50_000,
        jurisdiction_code="OH-OPEN", jurisdiction_name="Ohio Open",
        job_name="Shed", sku="P-CR", product_name="Can", list_price_cents=40_000)
    first = place_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 1}])
    assert first["total_cents"] == 43_300
    validate_success(api.suspend_contractor_account(account["id"], ADMIN))
    return account, job, product


def test_suspended_account_error_reported(api):
    """PRD §2.8: "Every request passes through a fixed validation pipeline,
    and within the pipeline the first failing check wins — its error masks any
    later failures the request would also have triggered." PRD §3.1: "A
    `SUSPENDED` account is barred from new financial commitments: creating an
    order for it, paying one of its orders, redeeming its loyalty points, or
    scheduling a delivery for one of its jobs is rejected with
    `ERR_ACCOUNT_SUSPENDED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/suspended_account_beats_credit_limit
    """
    account, job, product = _setup_suspended_account_over_credit(api)
    version = get_account_version(account["id"])
    resp = api.create_order(
        create_order_payload(account["id"], job["id"], version,
                             [{"product_id": product["id"], "quantity": 1}]),
        ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)


def test_suspended_account_error_masks_credit_limit(api):
    """PRD §2.8: "**Business rules**, evaluated in four ordered families:
    safety first (VOC compliance, `ERR_VOC_LIMIT_EXCEEDED`), then temporal
    rules (delivery window and buffer, VOC-rule overlap, bulletin effective
    date, rebate period validity and overlap), then constraints (SKU and
    jurisdiction-code uniqueness, empty spec, iteration exhaustion,
    tintability, the custom-tint no-return rule, return quantity), then
    referential rules (discontinued product, retired formula, formula/product
    mismatch, spec-line mismatch, job-account mismatch, bulletin replacement
    validity), and finally fiscal caps (credit limit, budget cap, points
    balance). Within an endpoint, a failure in an earlier family masks every
    later one." PRD §3.6: "the account's `outstanding_balance_cents` plus the
    new order's `total_cents` must not exceed its `credit_limit_cents`
    (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 422)".

    The second order would also breach the credit limit (43300 outstanding +
    43300 new = 86600 > 50000), but the state-stage suspension error fires
    first and masks it.

    Design: Difficulty/priority_pair_validation_conflict/suspended_account_beats_credit_limit
    """
    account, job, product = _setup_suspended_account_over_credit(api)
    account_view = validate_success(api.get_contractor_account(account["id"], ADMIN))
    assert account_view["outstanding_balance_cents"] == 43_300
    assert account_view["credit_limit_cents"] == 50_000
    version = account_view["version"]
    resp = api.create_order(
        create_order_payload(account["id"], job["id"], version,
                             [{"product_id": product["id"], "quantity": 1}]),
        ASSOCIATE)
    error = validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)
    assert error["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, (
        "the state error must win over the fiscal cap the request also violates")


def _setup_voc_and_retired_formula(api):
    """CA-SCAQMD-style jurisdiction with a FLAT 250 gpl VOC rule; a 300 gpl
    tintable FLAT product whose formula has been retired."""
    account, _, job = setup_account_with_job(
        company_name="Voc Co", credit_limit_cents=100_000_000,
        jurisdiction_code="CA-SCAQMD", jurisdiction_name="SCAQMD",
        job_name="LA Site")
    create_voc_rule(job["jurisdiction_id"], category="FLAT",
                    max_voc_gpl=250,
                    effective_from="2026-01-01T00:00:00Z")
    product = create_product(sku="P-VOC", name="Hot Flat", category="FLAT",
                             voc_gpl=300, list_price_cents=10_000, tintable=True)
    resp = api.create_tint_formula(
        create_tint_formula_payload(product["id"], color_code="SW 2000",
                                    name="Hot White",
                                    shots=[{"colorant_code": "W1",
                                            "ounces_128ths": 8}]),
        ADMIN)
    formula = validate_success(resp, expected_status=201)
    validate_success(api.retire_tint_formula(formula["id"], ADMIN))
    return account, job, product, formula


def test_voc_violation_error_reported(api):
    """PRD §3.8: "for every line of the order, the product's `voc_gpl` must
    not exceed the `max_voc_gpl` of the VOC rule effective at the logical
    clock now for the pair of the job's `jurisdiction_id` and the product's
    `category` (a jurisdiction-and-category pair with no effective rule is
    unrestricted). ... The same at-the-instant check governs order creation in
    §3.6, evaluated against the creation instant."

    A 300 gpl product against a 250 gpl limit is rejected
    ERR_VOC_LIMIT_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/voc_check_beats_retired_formula
    """
    account, job, product, formula = _setup_voc_and_retired_formula(api)
    resp = api.create_order(
        create_order_payload(account["id"], job["id"],
                             get_account_version(account["id"]),
                             [{"product_id": product["id"], "quantity": 1,
                               "formula_id": formula["id"]}]),
        ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_VOC_LIMIT_EXCEEDED)


def test_voc_error_masks_retired_formula(api):
    """PRD §3.6: "Because so many rules converge on this one operation, they
    are evaluated in a fixed sequence so the first failure masks the rest: the
    account-version OCC check runs first (`ERR_STALE_VERSION`), then the
    account must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`) and the job `OPEN`
    (`ERR_JOB_NOT_OPEN`); then each line is screened for VOC compliance
    (`ERR_VOC_LIMIT_EXCEEDED`); then the tint permission — a line carrying
    `formula_id` requires the product's `tintable` flag to be true
    (`ERR_PRODUCT_NOT_TINTABLE`, HTTP 422); then the referential checks —
    every referenced product must be `ACTIVE` (`ERR_PRODUCT_DISCONTINUED`),
    every referenced formula must be `ACTIVE` (`ERR_FORMULA_RETIRED`, HTTP
    422), ...".

    The same order line also references a RETIRED formula, but the earlier
    safety screen masks the referential failure.

    Design: Difficulty/priority_pair_validation_conflict/voc_check_beats_retired_formula
    """
    account, job, product, formula = _setup_voc_and_retired_formula(api)
    resp = api.create_order(
        create_order_payload(account["id"], job["id"],
                             get_account_version(account["id"]),
                             [{"product_id": product["id"], "quantity": 1,
                               "formula_id": formula["id"]}]),
        ASSOCIATE)
    error = validate_error(resp, ApiErrorId.ERR_VOC_LIMIT_EXCEEDED)
    assert error["error_id"] != ApiErrorId.ERR_FORMULA_RETIRED, (
        "the safety error must mask the referential error the line also "
        "would have triggered")
