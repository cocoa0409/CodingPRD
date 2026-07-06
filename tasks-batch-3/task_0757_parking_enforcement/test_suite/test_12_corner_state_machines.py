"""Corner section: state_machines (terminal-state lockdown, idempotency,
precondition enforcement)."""
from test_helpers import (
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    TEST_USERS,
    setup_issuing_context,
    issue_in_context,
    create_payment,
    settle_payment,
    void_citation,
    file_contest,
    create_violation_code,
    retire_violation_code,
    setup_scheduled_hearing,
    setup_boot_eligible_vehicle,
)

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
MOTORIST = TEST_USERS["motorist_headers"]
HEARING = TEST_USERS["hearing_officer_headers"]


def test_void_already_void_citation_returns_invalid_state(api):
    """PRD §3.7: "Voiding a citation is permitted only while it is `ISSUED`; it moves
    the citation from `ISSUED` to `VOID`, removes it from the vehicle's unpaid set,
    and recomputes the vehicle balance and scofflaw tier, which may de-escalate the
    vehicle and thereby cancel a still-`ORDERED` order and clear its hold."

    Design: Corner/state_machines/void_already_void_citation_returns_invalid_state
    """
    ctx = setup_issuing_context()
    cit = issue_in_context(ctx)
    void_citation(cit["id"])
    validate_error(
        api.void_citation(cit["id"], SUPERVISOR),
        ApiErrorId.ERR_INVALID_STATE.value)


def test_settle_already_settled_payment_rejected(api):
    """PRD §3.5: "Settlement is allowed only while the payment is `PENDING` and while
    the citation is still `ISSUED` or `UPHELD` (otherwise `ERR_CITATION_NOT_PAYABLE`);
    it moves the payment from `PENDING` to `SETTLED` and increases the citation's
    `amount_paid_cents` by the payment's `amount_cents`, after which `amount_due_cents`
    is recomputed."

    A re-settle simultaneously violates the payment-PENDING precondition and the
    citation-payable precondition (the citation is now PAID); PRD §2.10 does not order
    these two State checks, so either 409 is faithful.

    Design: Corner/state_machines/settle_already_settled_payment_returns_invalid_state
    """
    ctx = setup_issuing_context(base_fine_cents=5000, code="EXP_METER")
    cit = issue_in_context(ctx)
    pay = create_payment(cit["id"], 5000, method="CARD")
    settle_payment(pay["id"])
    validate_error_is_one_of(
        api.settle_payment(pay["id"], MOTORIST),
        [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_CITATION_NOT_PAYABLE.value])


def test_refund_pending_payment_returns_not_refundable(api):
    """PRD §3.5: "A refund is permitted only on a payment in `status` `SETTLED`, else
    `ERR_PAYMENT_NOT_REFUNDABLE`; it moves the payment from `SETTLED` to `REFUNDED`
    and decreases the citation's `amount_paid_cents` by that payment's `amount_cents`."

    Design: Corner/state_machines/refund_pending_payment_returns_not_refundable
    """
    ctx = setup_issuing_context(base_fine_cents=5000, code="EXP_METER")
    cit = issue_in_context(ctx)
    pay = create_payment(cit["id"], 5000, method="CARD")  # left PENDING
    validate_error(
        api.refund_payment(pay["id"], SUPERVISOR),
        ApiErrorId.ERR_PAYMENT_NOT_REFUNDABLE.value)


def test_decide_hearing_invalid_decision_rejected(api):
    """PRD §3.6: "Deciding supplies a `decision`, which must be one of `UPHELD` or
    `DISMISSED`; any other value is rejected with `ERR_HEARING_DECISION_INVALID`."

    Design: Corner/state_machines/decide_hearing_invalid_decision_returns_error
    """
    ctx = setup_scheduled_hearing()
    validate_error(
        api.decide_hearing(ctx["hearing"]["id"], {"decision": "MAYBE"}, HEARING),
        ApiErrorId.ERR_HEARING_DECISION_INVALID.value)


def test_contest_already_exists_rejected(api):
    """PRD §3.6: "Furthermore, no non-terminal contest may already exist for that
    citation — a second concurrent contest is rejected with
    `ERR_CONTEST_ALREADY_EXISTS`."

    Filing again also violates the "citation currently in `status` `ISSUED`"
    precondition (the citation is now CONTESTED); PRD §2.10 does not order these two
    State checks, so either 409 is faithful.

    Design: Corner/state_machines/contest_already_exists_returns_error
    """
    ctx = setup_issuing_context()
    cit = issue_in_context(ctx)
    file_contest(cit["id"], grounds="First")
    validate_error_is_one_of(
        api.create_contest({"citation_id": cit["id"], "grounds": "Second"}, MOTORIST),
        [ApiErrorId.ERR_CONTEST_ALREADY_EXISTS.value,
         ApiErrorId.ERR_CITATION_NOT_CONTESTABLE.value])


def test_retire_already_retired_violation_returns_invalid_state(api):
    """PRD §3.1: "An `Admin` may retire a code, moving its `status` from `ACTIVE` to
    `RETIRED`. Retirement is one-way and terminal."

    Design: Corner/state_machines/retire_already_retired_violation_returns_invalid_state
    """
    vc = create_violation_code(code="OLD1", description="Deprecated",
                               base_fine_cents=5000, is_booting_eligible=False)
    retire_violation_code(vc["id"])
    validate_error(
        api.retire_violation_code(vc["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE.value)


def test_apply_already_applied_boot_returns_invalid_state(api):
    """PRD §3.8: "A supervisor may physically apply an ordered boot/tow, moving it
    from `ORDERED` to `APPLIED`, and may release an order that is currently `ORDERED`
    or `APPLIED`, moving it to `RELEASED`."

    Design: Corner/state_machines/boot_apply_twice_returns_invalid_state
    """
    ctx = setup_boot_eligible_vehicle()
    order_id = ctx["boot_order"]["id"]
    api.apply_boot_tow_order(order_id, SUPERVISOR)  # ORDERED -> APPLIED
    validate_error(
        api.apply_boot_tow_order(order_id, SUPERVISOR),
        ApiErrorId.ERR_INVALID_STATE.value)
