"""Payment settlement and the depth-2 close cascade."""
from test_helpers import validate_success, get_success_data, TEST_USERS
from test_helpers import fixtures as fx

BILLING = TEST_USERS["billing_manager_headers"]
DESK = TEST_USERS["desk_examiner_headers"]


def _pay_approved_bill(api):
    ctx = fx.setup_approved_fee_bill_on_settled_claim(api)
    get_success_data(api.pay_fee_bill(ctx["bill_id"], {"method": "ACH"}, BILLING))
    return ctx


def test_payment_marks_bill_and_assignment_paid(api):
    """PRD 3.7: "It moves the bill APPROVED -> PAID and creates a Payment ... Payment
    then cascades: hop one, the assignment's billing dimension advances BILLED -> PAID."

    Design: Difficulty/transitive_cascade/payment_close_cascade_depth2
    """
    ctx = _pay_approved_bill(api)
    bill = validate_success(api.get_fee_bill(ctx["bill_id"], DESK))
    assignment = validate_success(api.get_assignment(ctx["asg_id"], DESK))
    assert bill["status"] == "PAID"
    assert assignment["billing_status"] == "PAID"


def test_payment_closes_settled_claim(api):
    """PRD 3.7: "hop two, caused by that assignment becoming paid, if the claim is
    SETTLED and every one of its non-declined assignments is now in billing status
    PAID, the claim advances SETTLED -> CLOSED."

    Design: Difficulty/transitive_cascade/payment_close_cascade_depth2
    """
    ctx = _pay_approved_bill(api)
    claim = validate_success(api.get_claim(ctx["claim_id"], DESK))
    assert claim["status"] == "CLOSED"
