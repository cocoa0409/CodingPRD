"""The amortization schedule: per-installment interest rounding and residue absorption."""
from test_helpers import (
    validate_paginated,
    get_success_data,
    TEST_USERS,
    setup_originated_loan,
)

_SERVICER = TEST_USERS["loan_servicer_headers"]


def test_amortization_rounds_interest_per_installment_then_sums(api):
    """PRD §3.5: "the interest portion interest_due_cents is the running balance
    multiplied by the monthly rate, rounded half up to whole cents (interest is rounded
    per installment, before being summed anywhere)."
    PRD §3.5: "For every installment except the last, the principal portion
    principal_due_cents is the level payment rounded half up to whole cents, minus that
    installment's interest portion."

    Design: Difficulty/combinatorial_formula/amortization_round_per_installment_then_sum_mode_b
    """
    ctx = setup_originated_loan()
    data, _meta = validate_paginated(api.list_loan_installments(ctx["loan"]["id"], _SERVICER))
    by_seq = sorted(data, key=lambda i: i["sequence_no"])
    assert by_seq[0]["principal_due_cents"] == 194118
    assert by_seq[0]["interest_due_cents"] == 18000
    assert by_seq[1]["principal_due_cents"] == 199942
    assert by_seq[1]["interest_due_cents"] == 12176
    assert by_seq[2]["principal_due_cents"] == 205940
    assert by_seq[2]["interest_due_cents"] == 6178


def test_amortization_final_installment_absorbs_residue(api):
    """PRD §3.5: "For the final installment, the principal portion is set to the entire
    remaining running balance, so the final installment absorbs all rounding residue and
    the sum of every installment's principal equals the original principal exactly."

    Design: Difficulty/combinatorial_formula/amortization_round_per_installment_then_sum_mode_b
    """
    ctx = setup_originated_loan()
    data, _meta = validate_paginated(api.list_loan_installments(ctx["loan"]["id"], _SERVICER))
    total_principal = sum(i["principal_due_cents"] for i in data)
    assert total_principal == 600000


def test_loan_installments_pagination_envelope(api):
    """PRD §3.5: "When a loan is originated, the system generates its complete
    installment schedule."
    PRD §2.3: "Every list response includes limit, offset, total_count, and has_more in
    the meta object of the envelope."

    Design: Corner/endpoints/list_installments_pagination_envelope
    """
    ctx = setup_originated_loan()
    data, meta = validate_paginated(
        api.list_loan_installments(ctx["loan"]["id"], _SERVICER, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(data) == 3
