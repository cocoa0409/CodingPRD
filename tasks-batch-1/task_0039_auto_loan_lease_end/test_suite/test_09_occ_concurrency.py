"""Optimistic concurrency control on the two supersede-style writes:
loan payoff and lease-end settlement creation.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    setup_loan, setup_matured_lease, elect_lease_end,
    record_payment_payload, create_settlement_payload,
    TEST_USERS, make_borrower_headers,
)

FM = TEST_USERS["finance_manager_headers"]


def test_payoff_with_stale_loan_version_rejected(api):
    """PRD §2.7: "If that value does not equal the loan's current `version` — for instance because
    a scheduled payment posted between the client's read and the payoff request, advancing the
    version and changing the actuarial payoff quote — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), so the borrower cannot tender against a balance they have not
    observed."

    Design: Corner/cross_cutting_complexity_layers/occ_payoff_stale_version_conflict
    """
    customer, vehicle, loan = setup_loan(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    stale_version = loan["version"]
    # A scheduled payment advances the loan's version, making the captured version stale.
    validate_success(api.record_payment(
        loan["id"], record_payment_payload(loan["monthly_payment_cents"], "SCHEDULED"),
        borrower), 201)
    # Payoff carrying the stale version (actuarial after 1 payment is 2462283).
    res = api.payoff_loan(
        loan["id"], {"amount_cents": 2462283, "expected_loan_version": stale_version}, borrower)
    validate_error(res, "ERR_STALE_VERSION")


def test_lease_election_with_stale_version_rejected(api):
    """PRD §2.7: "If that value does not equal the lease's current `version` — for instance
    because a prior election already moved the lease out of `MATURING` and advanced its version —
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so a superseded election cannot
    be applied on a stale view of the lease."

    Design: Corner/cross_cutting_complexity_layers/occ_lease_election_stale_version_conflict
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    stale_version = matured["version"]
    # A first RETURN election supersedes the lease (advances version, leaves MATURING).
    elect_lease_end(matured["id"], customer["id"], "RETURN", 36000, stale_version,
                    per_year_excess_miles=[0, 0, 0])
    # A second election carrying the now-stale version is rejected. After the first RETURN the
    # lease has left MATURING (now SETTLED), so PRD §2.8 evaluates the stale-version check
    # "alongside the state-legality check for that same operation" without pinning their relative
    # order; a faithful PRD-only implementer may return either ERR_STALE_VERSION or
    # ERR_LEASE_NOT_ELECTABLE.
    res = api.create_settlement(
        create_settlement_payload(matured["id"], "PURCHASE", 36000, stale_version), borrower)
    validate_error_is_one_of(res, ["ERR_STALE_VERSION", "ERR_LEASE_NOT_ELECTABLE"])
