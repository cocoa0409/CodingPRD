"""Paginated list endpoints and FK reverse-reachability: a customer's loans,
a loan's payments, a lease's settlements.
"""
from test_helpers import (
    validate_success, validate_paginated,
    create_active_rate_card, create_customer, create_vehicle,
    create_loan_payload, record_payment_payload, create_settlement_payload,
    setup_loan, setup_matured_lease, elect_lease_end,
    TEST_USERS, make_borrower_headers,
)

FM = TEST_USERS["finance_manager_headers"]


def test_list_customer_loans_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope, where `total_count` is the size of the full matching set
    and `has_more` indicates whether further pages remain beyond the returned slice."

    Design: Corner/endpoints/list_loans_paginated_envelope
    """
    customer, vehicle, loan = setup_loan(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    data, meta = validate_paginated(api.list_customer_loans(customer["id"], borrower))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert any(item["id"] == loan["id"] for item in data)


def test_list_loan_payments_reverse_reachability(api):
    """PRD §3.3: "When a scheduled payment posts against a `CURRENT` loan, the system writes a
    `Payment` whose `status` is `POSTED`, whose `kind` is `SCHEDULED`, and whose `late_fee_cents`
    is 0; it then increments `payments_made_count` by one and recomputes `principal_balance_cents`
    on the actuarial schedule."

    Design: Corner/endpoints/list_loan_payments_reverse_reachability
    """
    customer, vehicle, loan = setup_loan(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    validate_success(api.record_payment(
        loan["id"], record_payment_payload(loan["monthly_payment_cents"], "SCHEDULED"),
        borrower), 201)
    data, meta = validate_paginated(api.list_loan_payments(loan["id"], FM))
    assert meta["total_count"] == 1
    assert data[0]["kind"] == "SCHEDULED"
    assert data[0]["status"] == "POSTED"


def test_list_lease_settlements_reverse_reachability(api):
    """PRD §3.6: "The settlement's `disposition_charge_cents` is set to the lease's
    `disposition_fee_cents`. The settlement's `total_due_cents` is the disposition fee plus the
    mileage overage."

    Design: Corner/endpoints/list_lease_settlements_reverse_reachability
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    elect_lease_end(matured["id"], customer["id"], "RETURN", 36000, matured["version"],
                    per_year_excess_miles=[0, 0, 0])
    data, meta = validate_paginated(api.list_lease_settlements(matured["id"], FM))
    assert meta["total_count"] == 1
    assert data[0]["election"] == "RETURN"
    assert data[0]["total_due_cents"] == 39500
