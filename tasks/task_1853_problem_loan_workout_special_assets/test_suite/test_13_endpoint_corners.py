"""Corner coverage — endpoints: pagination envelope on list endpoints and FK
reverse-reachability of every child collection.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_workout_officer_headers, make_special_assets_manager_headers,
    make_loan_accounting_headers, make_appraisal_desk_headers,
    make_borrower_with_loan, open_workout_case, make_borrower, make_collateral,
    create_loan_payload, create_workout_case_payload,
)
from test_helpers.api_client import api_client


def test_pagination_envelope_on_list_endpoint(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100.
    The `offset` parameter says how many items to skip before the first returned item
    and defaults to 0. Every list response is sorted by the resources' creation
    timestamp (`created_at`) in ascending order, and every list response's `meta`
    object carries the four pagination fields `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/endpoints/pagination_envelope_on_list_endpoint
    """
    officer_h = make_workout_officer_headers("officer-e1")
    borrower = make_borrower(officer_h, legal_name="Page Co", tax_id="55-0000020",
                             naics_code="541712", internal_risk_rating=7)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-E01",
         "original_principal_cents": 7000000, "contractual_rate_bps": 800,
         "days_past_due": 62},
        officer_h))
    get_success_data(api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 7,
         "case_officer_id": "officer-e1"},
        officer_h))

    res = api_client.list_workout_cases(loan["id"], officer_h)
    body = res.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["response_type"] == "array"

    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10, "default limit is 10 when omitted"
    assert meta["offset"] == 0


def test_fk_reverse_reachability_filtered_lists(api):
    """PRD §2.7: "Filtered list routes support reverse reachability from a parent
    foreign key: loans filter by `borrower_id`; workout cases, proposals, impairment
    assessments, legal referrals, charge-offs, recoveries, and exit decisions filter
    by `case_id` — workout cases alternatively by `loan_id`; collateral items filter
    by `loan_id`; appraisals filter by `collateral_id`; action plans filter by
    `case_id` and by `supersedes_plan_id`. All of these lists honor the pagination
    contract of §2.3."

    Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
    """
    officer_h = make_workout_officer_headers("officer-e2")
    borrower = make_borrower(officer_h, legal_name="FK Co", tax_id="55-0000021",
                             naics_code="541713", internal_risk_rating=7)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-E02",
         "original_principal_cents": 6000000, "contractual_rate_bps": 800,
         "days_past_due": 62},
        officer_h))
    case = get_success_data(api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 7,
         "case_officer_id": "officer-e2"},
        officer_h))
    item = make_collateral(loan["id"], officer_h, collateral_type="INVENTORY",
                           description="Widgets", liquidation_discount_bps=4000)

    # Reverse reachability: the loan is listed under its borrower.
    loans, meta = validate_paginated(api_client.list_borrower_loans(borrower["id"], officer_h))
    assert meta["total_count"] == 1
    assert loans[0]["id"] == loan["id"]

    # Every child collection exists and is empty before any child is created.
    mgr_h = make_special_assets_manager_headers("mgr-e2")
    acct_h = make_loan_accounting_headers("acct-e2")
    desk_h = make_appraisal_desk_headers("appr-e2")

    child_lists = [
        api_client.list_action_plans(loan["id"], case["id"], officer_h),
        api_client.list_proposals(loan["id"], case["id"], officer_h),
        api_client.list_impairments(loan["id"], case["id"], acct_h),
        api_client.list_legal_referrals(loan["id"], case["id"], officer_h),
        api_client.list_charge_offs(loan["id"], case["id"], acct_h),
        api_client.list_recoveries(loan["id"], case["id"], acct_h),
        api_client.list_exit_decisions(loan["id"], case["id"], mgr_h),
        api_client.list_appraisals(loan["id"], item["id"], desk_h),
    ]
    for res in child_lists:
        data, meta = validate_paginated(res)
        assert data == [], f"expected empty list, got {data}"
        assert meta["total_count"] == 0
