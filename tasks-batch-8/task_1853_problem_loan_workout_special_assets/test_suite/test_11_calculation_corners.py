"""Corner coverage — calculations: CECL precision with non-round numbers, the
portfolio classified-exposure report's input-set filtering, and duplicate cash-flow
period rejection.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_loan_accounting_headers, make_portfolio_analyst_headers,
    make_workout_officer_headers, make_special_assets_manager_headers,
    make_credit_committee_headers,
    setup_case_in_impairment_review, setup_case_in_negotiation,
    make_borrower_with_loan, open_workout_case, make_borrower,
    create_impairment_cecl_payload, create_impairment_tdr_dcf_payload,
    create_loan_payload,
)
from test_helpers.api_client import api_client


def test_cecl_constants_and_precision_applied(api):
    """PRD §3.6: "Under `CECL`, `computed_reserve_cents` is the loan's
    `current_principal_cents` at finalization multiplied by
    `probability_of_default_bps` and by `loss_given_default_bps`, divided by one
    hundred million, rounded half up to whole cents: one multiplication chain, one
    division, one rounding."

    Design: Corner/calculations/cecl_constants_and_precision_applied
    """
    ctx = setup_case_in_impairment_review(
        officer_id="officer-c1", manager_id="mgr-c1", committee_id="cc-c1",
        borrower_overrides={"legal_name": "Odd Numbers Co", "tax_id": "55-0000013",
                            "naics_code": "541617", "internal_risk_rating": 8},
        loan_overrides={"loan_number": "LN-C01", "original_principal_cents": 73333333,
                        "contractual_rate_bps": 1000, "days_past_due": 80},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "CECL probe",
                        "target_resolution_date": "2027-01-25T00:00:00Z", "milestone_count": 1},
        proposal_overrides={"proposal_kind": "MODIFICATION", "concession_rate_bps": 1000,
                            "term_extension_months": 0, "principal_forgiveness_cents": 0,
                            "borrower_concession_cents": 1},
        concession=False,
    )
    loan, case = ctx["loan"], ctx["case"]
    acct_h = make_loan_accounting_headers("acct-c1")

    imp = get_success_data(api_client.create_impairment(
        loan["id"], case["id"],
        create_impairment_cecl_payload(probability_of_default_bps=1234,
                                       loss_given_default_bps=4321),
        acct_h))
    finalized = validate_success(api_client.finalize_impairment(
        loan["id"], case["id"], imp["id"], acct_h), 200)
    # 73,333,333 x 1,234 x 4,321 / 10^8 = 3,910,216.91... -> half-up 3,910,217.
    assert finalized["computed_reserve_cents"] == 3910217, (
        f"Expected 3910217, got {finalized['computed_reserve_cents']}")

    case_after = validate_success(api_client.get_workout_case(loan["id"], case["id"], acct_h), 200)
    assert case_after["impairment_reserve_cents"] == 3910217


def test_portfolio_report_input_set_filtering(api):
    """PRD §3.9: "The report walks every loan whose `status` is `WATCHLIST`,
    `WORKOUT`, or `FORECLOSURE` — `PERFORMING` and `RESOLVED` loans are excluded — in
    ascending `created_at` order, so the ledger walk is deterministic. Each included
    loan contributes two figures: toward the gross total, the sum of its
    `current_principal_cents` and `charged_off_principal_cents` with no reserve
    offset; toward the net total, that same sum minus the `impairment_reserve_cents`
    carried on the loan's single non-`CLOSED` workout case, counting only the active
    assessment's reserve and excluding superseded ones. A loan with no non-`CLOSED`
    case contributes zero."

    Design: Corner/calculations/portfolio_report_input_set_filtering
    """
    officer_h = make_workout_officer_headers("officer-c2")
    # L1: PERFORMING loan (must be excluded).
    bor_p = make_borrower(officer_h, legal_name="Perf Holder", tax_id="55-0000014",
                          naics_code="541618", internal_risk_rating=3)
    get_success_data(api_client.create_loan(
        {"borrower_id": bor_p["id"], "loan_number": "LN-P01",
         "original_principal_cents": 5000000, "contractual_rate_bps": 700,
         "days_past_due": 0}, officer_h))

    # L2: WORKOUT loan, current 100,000,000, ACTIVE CECL reserve 10,000,000.
    ctx_w = setup_case_in_impairment_review(
        officer_id="officer-c2", manager_id="mgr-c2", committee_id="cc-c2",
        borrower_overrides={"legal_name": "Workout Holder", "tax_id": "55-0000015",
                            "naics_code": "541618", "internal_risk_rating": 8,
                            "guarantor_name": "", "guarantor_net_worth_cents": 0},
        loan_overrides={"loan_number": "LN-W01", "original_principal_cents": 100000000,
                        "contractual_rate_bps": 1200, "days_past_due": 75},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "Report probe",
                        "target_resolution_date": "2027-02-01T00:00:00Z", "milestone_count": 1},
        proposal_overrides={"proposal_kind": "MODIFICATION", "concession_rate_bps": 600,
                            "term_extension_months": 6, "principal_forgiveness_cents": 0,
                            "borrower_concession_cents": 0},
        concession=True,
    )
    loan_w, case_w = ctx_w["loan"], ctx_w["case"]
    acct_h = make_loan_accounting_headers("acct-c2")
    imp = get_success_data(api_client.create_impairment(
        loan_w["id"], case_w["id"],
        create_impairment_cecl_payload(probability_of_default_bps=2500,
                                       loss_given_default_bps=4000),
        acct_h))
    validate_success(api_client.finalize_impairment(loan_w["id"], case_w["id"], imp["id"], acct_h), 200)

    # L3: WATCHLIST loan, current 20,000,000, no reserve (case fresh, LGD untouched).
    loan_w2 = get_success_data(api_client.create_loan(
        {"borrower_id": bor_p["id"], "loan_number": "LN-W02",
         "original_principal_cents": 20000000, "contractual_rate_bps": 800,
         "days_past_due": 65}, officer_h))
    get_success_data(api_client.create_workout_case(
        loan_w2["id"],
        {"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 6,
         "case_officer_id": "officer-c3"},
        make_workout_officer_headers("officer-c3")))

    report = validate_success(api_client.get_portfolio_report(
        make_portfolio_analyst_headers("analyst-c2")), 200)
    # gross = (100,000,000 + 0) + (20,000,000 + 0) = 120,000,000; the PERFORMING
    # loan's 5,000,000 is excluded.
    assert report["gross_classified_cents"] == 120000000, (
        f"Expected gross 120000000, got {report['gross_classified_cents']}")
    # net = (100,000,000 - 10,000,000) + (20,000,000 - 0) = 110,000,000.
    assert report["net_classified_cents"] == 110000000, (
        f"Expected net 110000000, got {report['net_classified_cents']}")
    assert report["gross_classified_cents"] != report["net_classified_cents"]


def test_tdr_dcf_duplicate_period_rejected(api):
    """PRD §3.6: "An empty array is forbidden for `TDR_DCF` (`ERR_EMPTY_CASH_FLOWS`),
    and two entries sharing the same `period_index` are rejected as
    `ERR_DUPLICATE_CASH_FLOW_PERIOD` (both HTTP 422)."

    Design: Corner/calculations/tdr_dcf_duplicate_period_rejected
    """
    ctx = setup_case_in_impairment_review(
        officer_id="officer-c4", manager_id="mgr-c4", committee_id="cc-c4",
        borrower_overrides={"legal_name": "Dup Period Co", "tax_id": "55-0000016",
                            "naics_code": "541619", "internal_risk_rating": 8},
        loan_overrides={"loan_number": "LN-C02", "original_principal_cents": 60000000,
                        "contractual_rate_bps": 1200, "days_past_due": 80},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "DCF probe",
                        "target_resolution_date": "2027-02-20T00:00:00Z", "milestone_count": 1},
        proposal_overrides={"proposal_kind": "RESTRUCTURE", "concession_rate_bps": 600,
                            "term_extension_months": 12, "principal_forgiveness_cents": 0,
                            "borrower_concession_cents": 0},
        concession=True,
    )
    loan, case = ctx["loan"], ctx["case"]
    acct_h = make_loan_accounting_headers("acct-c4")

    res = api_client.create_impairment(
        loan["id"], case["id"],
        create_impairment_tdr_dcf_payload(
            probability_of_default_bps=2000, loss_given_default_bps=3000,
            expected_cash_flows=[{"period_index": 6, "amount_cents": 1000000},
                                 {"period_index": 6, "amount_cents": 2000000}]),
        acct_h)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CASH_FLOW_PERIOD.value, expected_status=422)
