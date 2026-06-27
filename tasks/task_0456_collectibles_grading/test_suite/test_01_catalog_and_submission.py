"""Catalog configuration, submission creation, and the submit lifecycle.

Translations of difficulty queue (A) and corner queue (B) instances that live
in the catalog / draft / submit region of the workflow.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_customer, assert_service_level, assert_submission,
    create_customer_payload, create_service_level_payload,
    create_grading_standard_payload, create_submission_payload, create_item_payload,
    TEST_USERS, make_customer_headers,
    setup_catalog, setup_draft_submission, setup_submitted_submission,
)
from test_helpers import api_client as _api


LAB = TEST_USERS["lab_admin_headers"]


# ---------------------------------------------------------------------------
# Customer registration & defaults
# ---------------------------------------------------------------------------
def test_create_customer_returns_201_with_zero_store_credit(api):
    """PRD §3.2: "registration initializes the customer's wallet
    `store_credit_cents` to zero."

    Design: Corner/entities/create_customer_returns_201_with_zero_store_credit
    """
    resp = api.create_customer(create_customer_payload(email="e1@x.com", full_name="E One"))
    data = validate_success(resp, expected_status=201)
    assert_customer(data)
    assert data["store_credit_cents"] == 0, "store_credit_cents must default to 0"


def test_service_level_active_default_true_when_omitted(api):
    """PRD §3.1: "A service level also carries an `active` flag indicating whether
    new submissions may select the tier; when the flag is omitted at creation it
    defaults to true."

    Design: Corner/entities/service_level_active_default_true_when_omitted
    """
    resp = api.create_service_level(
        create_service_level_payload(code="ECONOMY", turnaround_business_days=30,
                                     base_fee_cents=1000, max_declared_value_cents=20000,
                                     insurance_rate_bps=100),
        LAB,
    )
    data = validate_success(resp, expected_status=201)
    assert data["active"] is True, "active must default to true when omitted"


# ---------------------------------------------------------------------------
# Submission system fields
# ---------------------------------------------------------------------------
def test_submission_create_mints_id_version_and_draft_status(api):
    """PRD §3.2: "A new submission begins in `DRAFT` status with an `item_count` of
    zero; its computed fee totals `total_estimated_fee_cents` and
    `total_final_fee_cents` both begin at zero."

    Design: Corner/entities/system_fields_id_and_version_minted_on_submission_create
    """
    # The design instance also names version==1, but PRD §2.4 only says version
    # "begins at the resource's first persisted value and increments by one on
    # every mutation" — it does not uniquely pin the initial integer, so a faithful
    # PRD-only reader could start it at 0. That assertion is therefore omitted; the
    # uniquely-derivable DRAFT-status / zeroed-totals claims are asserted instead.
    customer, sl, gs = setup_catalog(email="e4@x.com")
    cust_headers = make_customer_headers(customer["id"])
    resp = api.create_submission(create_submission_payload(customer["id"], sl["id"]), cust_headers)
    data = validate_success(resp, expected_status=201)
    assert_submission(data)
    assert data["status"] == "DRAFT", "fresh submission status must be DRAFT"
    assert data["item_count"] == 0, "fresh submission item_count must be 0"
    assert data["total_estimated_fee_cents"] == 0
    assert data["total_final_fee_cents"] == 0


# ---------------------------------------------------------------------------
# Submit lifecycle: empty submission boundary
# ---------------------------------------------------------------------------
def test_submit_empty_submission_rejected(api):
    """PRD §3.2: "The submit operation first requires that the submission contain
    at least one item: a submit attempt on a submission whose `item_count` is zero
    is rejected with `ERR_EMPTY_SUBMISSION`."

    Design: Difficulty/boundary_precision_check/empty_submission_zero_items_blocks_submit
    """
    customer, sl, gs, sub = setup_draft_submission(email="c12@x.com")
    cust_headers = make_customer_headers(customer["id"])
    resp = api.submit_submission(sub["id"], cust_headers)
    validate_error(resp, ApiErrorId.ERR_EMPTY_SUBMISSION.value)


def test_submit_empty_submission_does_not_advance_posture(api):
    """PRD §3.2: "a submit attempt on a submission whose `item_count` is zero is
    rejected with `ERR_EMPTY_SUBMISSION`."

    Design: Difficulty/boundary_precision_check/empty_submission_zero_items_blocks_submit
    """
    customer, sl, gs, sub = setup_draft_submission(email="c12b@x.com")
    cust_headers = make_customer_headers(customer["id"])
    api.submit_submission(sub["id"], cust_headers)
    after = validate_success(api.get_submission(sub["id"], cust_headers))
    assert after["status"] == "DRAFT", "rejected empty submit must leave submission in DRAFT"


# ---------------------------------------------------------------------------
# Submit lifecycle: declared-value tier cap boundary (X-1 / X / X+1)
# ---------------------------------------------------------------------------
def test_submit_declared_value_equal_to_tier_cap_accepted(api):
    """PRD §3.2: "It then requires that every item's `declared_value_cents` be less
    than or equal to the submission tier's `max_declared_value_cents`; if any
    item's declared value exceeds the tier cap, the submit is rejected with
    `ERR_DECLARED_VALUE_EXCEEDS_TIER`."
    PRD §3.8: "multiply `declared_value_cents` by `insurance_rate_bps`, divide by
    10000, and round the result up to the next whole cent (ceiling); add that
    estimated insurance to the base fee."

    Design: Difficulty/boundary_precision_check/declared_value_equal_to_tier_cap_is_accepted_inclusive
    """
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[{"declared_value_cents": 50000, "title": "Card J"}], email="c11@x.com",
    )
    assert sub["status"] == "SUBMITTED", "declared value == cap (50000) must be accepted (inclusive)"
    # estimate = base 5000 + ceil(50000*200/10000)=1000 -> 6000
    assert sub["total_estimated_fee_cents"] == 6000


def test_submit_declared_value_just_below_cap_accepted(api):
    """PRD §3.2: "every item's `declared_value_cents` be less than or equal to the
    submission tier's `max_declared_value_cents`; if any item's declared value
    exceeds the tier cap, the submit is rejected with
    `ERR_DECLARED_VALUE_EXCEEDS_TIER`."

    Design: Difficulty/boundary_precision_check/declared_value_equal_to_tier_cap_is_accepted_inclusive
    """
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[{"declared_value_cents": 49999, "title": "Below"}], email="c11b@x.com",
    )
    assert sub["status"] == "SUBMITTED", "declared value 49999 (< cap) must be accepted"


def test_submit_declared_value_over_tier_cap_rejected(api):
    """PRD §3.2: "if any item's declared value exceeds the tier cap, the submit is
    rejected with `ERR_DECLARED_VALUE_EXCEEDS_TIER`."
    PRD §3.2: "Between these two checks the empty-submission check is evaluated
    first."

    Design: Difficulty/priority_pair_validation_conflict/fiscal_beats_constraint_submit_over_tier_and_empty
    """
    customer, sl, gs, sub = setup_draft_submission(email="c10@x.com")
    cust_headers = make_customer_headers(customer["id"])
    api.add_item(sub["id"], create_item_payload(gs["id"], title="Card I", declared_value_cents=60000), cust_headers)
    resp = api.submit_submission(sub["id"], cust_headers)
    validate_error(resp, ApiErrorId.ERR_DECLARED_VALUE_EXCEEDS_TIER.value)


def test_submit_nonempty_over_cap_reports_fiscal_not_empty(api):
    """PRD §3.2: "It then requires that every item's `declared_value_cents` be less
    than or equal to the submission tier's `max_declared_value_cents`; if any
    item's declared value exceeds the tier cap, the submit is rejected with
    `ERR_DECLARED_VALUE_EXCEEDS_TIER`. Between these two checks the empty-submission
    check is evaluated first."

    Design: Difficulty/priority_pair_validation_conflict/fiscal_beats_constraint_submit_over_tier_and_empty
    """
    # A single over-cap item: the submission is non-empty, so the empty check
    # passes and the fiscal cap check is the one that fires.
    customer, sl, gs, sub = setup_draft_submission(email="c10b@x.com")
    cust_headers = make_customer_headers(customer["id"])
    api.add_item(sub["id"], create_item_payload(gs["id"], title="Over", declared_value_cents=60000), cust_headers)
    resp = api.submit_submission(sub["id"], cust_headers)
    validate_error(resp, ApiErrorId.ERR_DECLARED_VALUE_EXCEEDS_TIER.value)


# ---------------------------------------------------------------------------
# Submit estimate computation: per-item-ceil-then-sum rounding order
# ---------------------------------------------------------------------------
def test_submit_estimate_per_item_ceil_then_sum_rounding(api):
    """PRD §3.8: "The submission's `total_estimated_fee_cents` is then the sum of
    the per-item estimates, with the rounding order pinned: each item's insurance
    is ceiled first and the already-ceiled per-item estimates are then summed."

    Design: Difficulty/combinatorial_formula/estimate_submission_fee_per_item_then_sum_rounding_order
    """
    # ROUND tier: base 1000, rate 125bps, cap huge. Three items each 1201.
    # per item: ceil(1201*125/10000)=ceil(15.0125)=16 -> est 1016; sum 3048.
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[
            {"declared_value_cents": 1201, "title": "I1"},
            {"declared_value_cents": 1201, "title": "I2"},
            {"declared_value_cents": 1201, "title": "I3"},
        ],
        email="c4@x.com",
        sl_overrides={"code": "ROUND", "turnaround_business_days": 5, "base_fee_cents": 1000,
                      "max_declared_value_cents": 1000000000, "insurance_rate_bps": 125},
    )
    assert sub["total_estimated_fee_cents"] == 3048, (
        "per-item-ceil-then-sum must yield 3048, not sum-then-ceil 3046"
    )


def test_submit_estimate_per_item_estimate_pinned_on_each_item(api):
    """PRD §3.8: "At submit, each item's **estimate** is pinned into its
    `estimated_fee_cents`."
    PRD §3.8: "add that estimated insurance to the base fee."

    Design: Difficulty/combinatorial_formula/estimate_submission_fee_per_item_then_sum_rounding_order
    """
    # Each ROUND item declared 1201: per-item estimate = 1000 + ceil(1201*125/10000)
    # = 1000 + 16 = 1016. Confirms the per-item figure that is summed.
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[
            {"declared_value_cents": 1201, "title": "P1"},
            {"declared_value_cents": 1201, "title": "P2"},
            {"declared_value_cents": 1201, "title": "P3"},
        ],
        email="c4b@x.com",
        sl_overrides={"code": "ROUND", "turnaround_business_days": 5, "base_fee_cents": 1000,
                      "max_declared_value_cents": 1000000000, "insurance_rate_bps": 125},
    )
    cust_headers = make_customer_headers(customer["id"])
    fetched = validate_success(api.get_item(items[0]["id"], cust_headers))
    assert fetched["estimated_fee_cents"] == 1016, "each item's estimate must be ceil'd to 1016"


def test_submit_estimate_single_item_visible_immediately(api):
    """PRD §3.8: "At submit, each item's **estimate** is pinned into its
    `estimated_fee_cents`."
    PRD §3.8: "The estimate is the tier's `base_fee_cents` plus an estimated
    insurance charge computed on the item's full, **uncapped** declared value"

    Design: Corner/consistency_model/immediate_estimate_visible_in_submit_response
    """
    # One 30000 item @ EXPRESS: 5000 + ceil(30000*200/10000)=600 -> 5600.
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[{"declared_value_cents": 30000, "title": "AJ"}], email="e25@x.com",
    )
    assert sub["total_estimated_fee_cents"] == 5600, (
        "estimate must be computed and visible in the same submit response"
    )


# ---------------------------------------------------------------------------
# Frozen-item-set guard
# ---------------------------------------------------------------------------
def test_add_item_to_submitted_submission_rejected_frozen(api):
    """PRD §3.2: "Items may be added or removed only while the parent submission
    is in `DRAFT`; an attempt to add or remove an item once the submission has left
    `DRAFT` is rejected with `ERR_SUBMISSION_FROZEN`."

    Design: Corner/validations/add_item_to_submitted_submission_frozen
    """
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[{"declared_value_cents": 30000, "title": "AA"}], email="e17@x.com",
    )
    cust_headers = make_customer_headers(customer["id"])
    resp = api.add_item(sub["id"], create_item_payload(gs["id"], title="AB", declared_value_cents=30000), cust_headers)
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_FROZEN.value)


# ---------------------------------------------------------------------------
# Submit invalid transition
# ---------------------------------------------------------------------------
def test_submit_already_submitted_rejected(api):
    """PRD §3.2: "When both pass, the submission advances `DRAFT → SUBMITTED`, its
    item set is frozen, the estimated fee total is pinned, and an insurance
    policy is created for the batch."
    PRD §2.6: "then whether the target resource is in a valid state for the
    requested transition (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/submit_already_submitted_returns_invalid_state
    """
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[{"declared_value_cents": 30000, "title": "Q"}], email="e7@x.com",
    )
    cust_headers = make_customer_headers(customer["id"])
    resp = api.submit_submission(sub["id"], cust_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Delete draft item decrements count
# ---------------------------------------------------------------------------
def test_delete_draft_item_decrements_count(api):
    """PRD §3.2: "Removing an item from a draft lowers the parent's `item_count` by
    one."

    Design: Corner/endpoints/delete_draft_item_decrements_count
    """
    customer, sl, gs, sub = setup_draft_submission(email="e19@x.com")
    cust_headers = make_customer_headers(customer["id"])
    item = validate_success(
        api.add_item(sub["id"], create_item_payload(gs["id"], title="AD", declared_value_cents=30000), cust_headers),
        expected_status=201,
    )
    resp = api.delete_item(item["id"], cust_headers)
    # PRD §4: item removal returns 204 No Content. A 204 carries no body by
    # definition, so assert the status directly rather than parsing an envelope.
    assert resp.status_code == 204, f"delete must return 204, got {resp.status_code}: {resp.text}"
    after = validate_success(api.get_submission(sub["id"], cust_headers))
    assert after["item_count"] == 0, "item_count must drop 1 -> 0 after delete"
