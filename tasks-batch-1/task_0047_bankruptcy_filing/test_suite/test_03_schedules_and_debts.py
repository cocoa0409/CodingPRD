"""Schedule line items: the Schedule C over-exemption guard, immediate
reconciliation of derived case fields, and debt listing by case.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_schedule_payload,
    register_debtor, register_creditor, open_case, add_schedule, add_debt,
    make_debtor_headers,
)


def test_schedule_c_exemption_exceeds_asset_rejected(api):
    """PRD §3.3: "When a Schedule C line is added, its claimed_exempt_value_cents
    must not exceed the case's gross scheduled asset value ... A claimed exemption
    above that gross is rejected with ERR_EXEMPTION_EXCEEDS_ASSET (HTTP 422)."

    Design: Corner/validations/schedule_c_exemption_exceeds_asset_rejected
    """
    debtor = register_debtor(full_name="Ex Debtor")
    case = open_case(debtor, filed_chapter="CHAPTER_7")
    add_schedule(debtor, case, "A", description="house", asset_value_cents=500000)
    headers = make_debtor_headers(debtor["id"])
    res = api.create_schedule(create_schedule_payload(
        case["id"], "C", description="over-exempt", claimed_exempt_value_cents=800000), headers)
    validate_error(res, "ERR_EXEMPTION_EXCEEDS_ASSET")


def test_total_exempt_recomputed_on_each_schedule_c_add(api):
    """PRD §3.3: "total_exempt_value_cents is the sum of claimed_exempt_value_cents
    across all of the case's Schedule C rows." And: "Adding any schedule line
    recomputes two derived case fields and bumps the case's version."

    Design: Corner/cross_cutting_complexity_layers/derived_total_exempt_recomputed_on_schedule_c_add
    """
    debtor = register_debtor(full_name="Deriv Debtor")
    case = open_case(debtor, filed_chapter="CHAPTER_7")
    add_schedule(debtor, case, "A", description="house", asset_value_cents=1000000)
    add_schedule(debtor, case, "C", description="homestead", claimed_exempt_value_cents=250000)
    headers = make_debtor_headers(debtor["id"])

    res = api.create_schedule(create_schedule_payload(
        case["id"], "C", description="wildcard", claimed_exempt_value_cents=150000), headers)
    validate_success(res, 201)

    case_after = validate_success(api.get_case(case["id"], headers), 200)
    assert case_after["total_exempt_value_cents"] == 400000

# NOTE: corner instance entities/flat_fk_debt_filtered_by_case_reverse_reachability
# is SKIPPED. Its asserted rule — GET /debts?case_id returns only that case's debts
# (total_count == 2) — appears only inside the §4 routing-summary table cell
# ("List debts; filter by case_id"), which §4 explicitly labels "only a routing and
# authorization summary." No PRD prose states the filter's selection semantics, so
# the rule fails the rule-bearing (C2) PRD-citation requirement. Gap left as a gap.
