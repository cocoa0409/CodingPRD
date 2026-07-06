"""The conserved fee ledger: withdrawal refunds the paid amount without drift."""
from test_helpers import fixtures, validate_success, make_petitioner_headers
from test_helpers.constants import STANDARD_MISDEMEANOR_FEE_CENTS

CLERK = fixtures.CLERK


def test_withdraw_from_screened_refunds_paid_fee(api):
    """PRD §3.1: "When a filing-fee payment is recorded against a petition, the paid
    `amount_cents` is added both to that petition's `amount_paid_cents` and to the
    owning petitioner's `fee_paid_cents`."
    PRD §3.3: "Withdrawing from `SCREENED` refunds any fee already paid: the
    petition's `amount_paid_cents` is added to the petitioner's `fee_refunded_cents`."

    Design: Difficulty/compensating_invariant/withdraw_refunds_fee_ledger
    """
    ctx = fixtures.setup_screened_petition(api)
    petitioner_id = ctx["petitioner"]["id"]
    pet_id = ctx["petition"]["id"]
    fixtures.pay_fee(api, pet_id, STANDARD_MISDEMEANOR_FEE_CENTS)
    owner = make_petitioner_headers(petitioner_id)
    validate_success(api.transition_petition(pet_id, {"to_status": "WITHDRAWN"}, owner))
    petitioner = validate_success(api.get_petitioner(petitioner_id, CLERK))
    # NET_FEES = fee_paid_cents - fee_refunded_cents returns to 0 (conserved).
    assert petitioner["fee_paid_cents"] == STANDARD_MISDEMEANOR_FEE_CENTS
    assert petitioner["fee_refunded_cents"] == STANDARD_MISDEMEANOR_FEE_CENTS


def test_withdraw_from_filed_refunds_fee_and_clears_notifications(api):
    """PRD §3.3: "Withdrawing from `FILED` likewise refunds the paid amount and
    additionally clears the case's agency notices — every `AgencyNotification` of the
    petition that is not already `CLEARED` is moved to `CLEARED`."

    Design: Difficulty/compensating_invariant/withdraw_refunds_fee_ledger
    """
    ctx = fixtures.setup_filed_petition(api)
    petitioner_id = ctx["petitioner"]["id"]
    pet_id = ctx["petition"]["id"]
    owner = make_petitioner_headers(petitioner_id)
    validate_success(api.transition_petition(pet_id, {"to_status": "WITHDRAWN"}, owner))
    petitioner = validate_success(api.get_petitioner(petitioner_id, CLERK))
    assert petitioner["fee_refunded_cents"] == STANDARD_MISDEMEANOR_FEE_CENTS
    notifications = fixtures.list_notifications(api, pet_id)
    assert notifications, "the filed petition should have agency notifications"
    assert all(n["status"] == "CLEARED" for n in notifications)
