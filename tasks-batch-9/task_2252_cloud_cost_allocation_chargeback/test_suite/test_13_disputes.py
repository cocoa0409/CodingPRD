"""Disputes: the capped review conversation, the two invoice dimensions and the ledger."""

from test_helpers import (
    ADMIN_HEADERS,
    CONTROLLER_HEADERS,
    ApiErrorId,
    assert_budget_evaluation,
    assert_cents,
    assert_invoice_dimensions,
    assert_invoice_ledger,
    factories,
    fixtures,
    make_business_unit_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import AUGUST_FIFTH_UTC

QUESTION = "Which resource tags do you believe were misapplied?"
RESPONSE = "The billing team owns the resource, not us."


def _issued_invoice(api):
    """Ops BU billed 10000 cents of direct July compute on an ISSUED invoice."""
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    built = fixtures.direct_chargeback_invoice(api)
    assert_invoice_ledger(built["invoice"], 10000, 0, 0, 10000)
    assert_invoice_dimensions(built["invoice"], settlement_status="ISSUED", dispute_status="NONE")
    assert built["invoice"]["dispute_window_ends_at"].startswith("2026-08-12T00:00:00")
    built["owner"] = make_business_unit_owner_headers(built["unit"]["id"])
    return built


def _walk_to_the_third_round(api, dispute_id, owner):
    """Alternate review and information requests until `review_round` reads 3."""
    first = validate_success(api.start_review_dispute(dispute_id, CONTROLLER_HEADERS))
    assert first["status"] == "UNDER_REVIEW"
    assert first["review_round"] == 1

    asked = validate_success(
        api.request_info_dispute(dispute_id, {"question": QUESTION}, CONTROLLER_HEADERS)
    )
    assert asked["status"] == "INFO_REQUESTED"
    assert asked["review_round"] == 1

    second = validate_success(
        api.respond_dispute(dispute_id, {"response_text": RESPONSE}, owner)
    )
    assert second["status"] == "UNDER_REVIEW"
    assert second["review_round"] == 2

    asked_again = validate_success(
        api.request_info_dispute(dispute_id, {"question": QUESTION}, CONTROLLER_HEADERS)
    )
    assert asked_again["review_round"] == 2

    third = validate_success(
        api.respond_dispute(dispute_id, {"response_text": RESPONSE}, owner)
    )
    assert third["status"] == "UNDER_REVIEW"
    assert third["review_round"] == 3
    return third


def test_the_third_response_is_refused_because_the_review_rounds_are_capped(api):
    """Two answered questions reach round 3, and the next answer is refused.

    PRD §3.7: "Review and information requests may therefore alternate until
    `review_round` reaches 3, after which starting another round or accepting
    another response is rejected with `ERR_DISPUTE_ROUND_LIMIT` at HTTP 409."

    Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_capped_at_three_review_rounds
    """
    built = _issued_invoice(api)
    dispute = fixtures.file_dispute(
        api,
        built["invoice"],
        reason_code="SHARED_METHODOLOGY",
        claimed_credit_cents=4000,
        narrative="not our storage",
    )
    assert dispute["status"] == "OPEN"
    assert dispute["review_round"] == 0

    _walk_to_the_third_round(api, dispute["id"], built["owner"])

    capped = validate_success(
        api.request_info_dispute(dispute["id"], {"question": QUESTION}, CONTROLLER_HEADERS)
    )
    assert capped["status"] == "INFO_REQUESTED"
    assert capped["review_round"] == 3

    refused = api.respond_dispute(dispute["id"], {"response_text": RESPONSE}, built["owner"])
    validate_error(refused, ApiErrorId.DISPUTE_ROUND_LIMIT.value, 409)

    frozen = validate_success(api.get_dispute(dispute["id"], CONTROLLER_HEADERS))
    assert frozen["status"] == "INFO_REQUESTED"
    assert frozen["review_round"] == 3

    invoice = validate_success(
        api.get_chargeback_invoice(built["invoice"]["id"], CONTROLLER_HEADERS)
    )
    assert_invoice_dimensions(invoice, settlement_status="ISSUED", dispute_status="DISPUTED")


def test_an_information_request_is_still_admissible_at_the_third_round(api):
    """Asking is capped at or below 3 while answering is capped strictly below 3.

    PRD §3.7: "The controller may pause the review by asking for more information
    with a `question`, moving the dispute `UNDER_REVIEW → INFO_REQUESTED` and
    recording the question; that step requires `review_round` to be at or below
    3."

    Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_capped_at_three_review_rounds
    """
    built = _issued_invoice(api)
    dispute = fixtures.file_dispute(
        api,
        built["invoice"],
        reason_code="SHARED_METHODOLOGY",
        claimed_credit_cents=4000,
        narrative="not our storage",
    )
    at_the_cap = _walk_to_the_third_round(api, dispute["id"], built["owner"])

    asked_at_the_cap = validate_success(
        api.request_info_dispute(dispute["id"], {"question": QUESTION}, CONTROLLER_HEADERS)
    )
    assert asked_at_the_cap["status"] == "INFO_REQUESTED"
    assert asked_at_the_cap["review_round"] == 3
    assert asked_at_the_cap["version"] == at_the_cap["version"] + 1

    validate_error(
        api.respond_dispute(dispute["id"], {"response_text": RESPONSE}, built["owner"]),
        ApiErrorId.DISPUTE_ROUND_LIMIT.value,
        409,
    )

    record = validate_success(api.get_cost_record(built["record"]["id"], CONTROLLER_HEADERS))
    assert record["allocation_state"] == "DISPUTED_HOLD"

    _, meta = validate_paginated(
        api.list_disputes(CONTROLLER_HEADERS, {"chargeback_invoice_id": built["invoice"]["id"]})
    )
    assert meta["total_count"] == 1


def test_settlement_is_refused_while_the_invoice_reads_disputed(api):
    """The two dimensions move independently, and the dispute one blocks payment.

    PRD §3.6: "Settlement is also refused while `dispute_status` is `DISPUTED`."

    Design: Difficulty/non_linear_state_machine/invoice_settlement_and_dispute_dimensions_advance_independently
    """
    built = _issued_invoice(api)
    invoice_id = built["invoice"]["id"]

    dispute = fixtures.file_dispute(
        api,
        built["invoice"],
        reason_code="SHARED_METHODOLOGY",
        claimed_credit_cents=4000,
        narrative="not our storage",
    )
    disputed = validate_success(api.get_chargeback_invoice(invoice_id, CONTROLLER_HEADERS))
    assert_invoice_dimensions(disputed, settlement_status="ISSUED", dispute_status="DISPUTED")
    held = validate_success(api.get_cost_record(built["record"]["id"], CONTROLLER_HEADERS))
    assert held["allocation_state"] == "DISPUTED_HOLD"

    blocked = api.settle_invoice(invoice_id, 10000, built["owner"])
    validate_error(blocked, ApiErrorId.INVOICE_STATE_INVALID.value, 409)
    unpaid = validate_success(api.get_chargeback_invoice(invoice_id, CONTROLLER_HEADERS))
    assert_invoice_ledger(unpaid, 10000, 0, 0, 10000)

    withdrawn = validate_success(api.withdraw_dispute(dispute["id"], built["owner"]))
    assert withdrawn["status"] == "WITHDRAWN"

    released = validate_success(api.get_chargeback_invoice(invoice_id, CONTROLLER_HEADERS))
    assert_invoice_dimensions(released, settlement_status="ISSUED", dispute_status="NONE")
    assert_invoice_ledger(released, 10000, 0, 0, 10000)

    freed = validate_success(api.get_cost_record(built["record"]["id"], CONTROLLER_HEADERS))
    assert freed["allocation_state"] == "ALLOCATED"


def test_an_upheld_resolution_leaves_the_settlement_dimension_free_to_advance(api):
    """A second dispute is upheld with no credit, and the invoice then settles in full.

    PRD §3.7: "**`UNDER_REVIEW → RESOLVED_UPHELD`** sets `outcome` to `UPHELD`,
    fixes `granted_credit_cents` at 0, and records `resolved_by_user_id`."

    Design: Difficulty/non_linear_state_machine/invoice_settlement_and_dispute_dimensions_advance_independently
    """
    built = _issued_invoice(api)
    invoice_id = built["invoice"]["id"]
    owner = built["owner"]

    first = fixtures.file_dispute(
        api,
        built["invoice"],
        reason_code="SHARED_METHODOLOGY",
        claimed_credit_cents=4000,
        narrative="not our storage",
    )
    validate_success(api.withdraw_dispute(first["id"], owner))

    second = fixtures.file_dispute(
        api,
        built["invoice"],
        reason_code="WRONG_OWNER",
        claimed_credit_cents=2000,
        narrative="this resource belongs to billing",
    )
    assert second["status"] == "OPEN"
    validate_success(api.start_review_dispute(second["id"], CONTROLLER_HEADERS))

    resolved = validate_success(
        api.resolve_dispute(
            second["id"], factories.dispute_resolution_payload("UPHELD"), CONTROLLER_HEADERS
        )
    )
    assert resolved["status"] == "RESOLVED_UPHELD"
    assert resolved["outcome"] == "UPHELD"
    assert_cents(resolved["granted_credit_cents"], 0, "granted_credit_cents")
    assert resolved["resolved_by_user_id"] == "controller-1"

    uncredited = validate_success(api.get_chargeback_invoice(invoice_id, CONTROLLER_HEADERS))
    assert_invoice_dimensions(
        uncredited, settlement_status="ISSUED", dispute_status="DISPUTE_RESOLVED"
    )
    assert_invoice_ledger(uncredited, 10000, 0, 0, 10000)

    settled = validate_success(api.settle_invoice(invoice_id, 10000, owner))
    assert_invoice_dimensions(
        settled, settlement_status="SETTLED", dispute_status="DISPUTE_RESOLVED"
    )
    assert_invoice_ledger(settled, 10000, 0, 10000, 0)

    unit = validate_success(api.get_business_unit(built["unit"]["id"], ADMIN_HEADERS))
    assert_cents(unit["chargeback_balance_cents"], 0, "chargeback_balance_cents")


def _breached_july_budget(api, built):
    """A July budget on the billed unit, evaluated into BREACHED by the invoice."""
    budget = fixtures.create_active_budget(
        api,
        built["unit"]["id"],
        amount_cents=9000,
        forecast_cents=9500,
        accuracy_basis="PERIOD_END_BASIS",
    )
    budget = validate_success(api.evaluate_budget(budget["id"], CONTROLLER_HEADERS))
    assert_budget_evaluation(
        budget,
        actual_spend_cents=10000,
        variance_cents=1000,
        variance_pct=11.11,
        warning_flag=False,
        status="BREACHED",
    )
    return budget


def _resolve_with_a_credit(api, dispute_id, granted_credit_cents):
    validate_success(api.start_review_dispute(dispute_id, CONTROLLER_HEADERS))
    return validate_success(
        api.resolve_dispute(
            dispute_id,
            factories.dispute_resolution_payload(
                "ADJUSTED", granted_credit_cents=granted_credit_cents
            ),
            CONTROLLER_HEADERS,
        )
    )


def test_an_adjusted_credit_records_the_award_and_lowers_the_invoice(api):
    """The first two hops of the cascade: the dispute's award and the invoice's ledger.

    PRD §3.7: "It sets `outcome` to `ADJUSTED`, records `granted_credit_cents`
    and `resolved_by_user_id`, and increases the invoice's
    `credited_amount_cents` by the granted credit, which lowers `net_due_cents`."

    Design: Difficulty/transitive_cascade/dispute_credit_cascades_dispute_to_invoice_to_bu_balance_to_budget_status
    """
    built = _issued_invoice(api)
    _breached_july_budget(api, built)

    dispute = fixtures.file_dispute(
        api,
        built["invoice"],
        reason_code="SHARED_METHODOLOGY",
        claimed_credit_cents=4000,
        narrative="not our storage",
    )
    resolved = _resolve_with_a_credit(api, dispute["id"], 4000)

    assert resolved["status"] == "RESOLVED_ADJUSTED"
    assert resolved["outcome"] == "ADJUSTED"
    assert_cents(resolved["granted_credit_cents"], 4000, "granted_credit_cents")
    assert resolved["resolved_by_user_id"] == "controller-1"

    invoice = validate_success(
        api.get_chargeback_invoice(built["invoice"]["id"], CONTROLLER_HEADERS)
    )
    assert_invoice_dimensions(
        invoice, settlement_status="PARTIALLY_CREDITED", dispute_status="DISPUTE_RESOLVED"
    )
    assert_invoice_ledger(invoice, 10000, 4000, 0, 6000)


def test_the_same_credit_reaches_the_business_unit_balance_and_the_budget(api):
    """The last two hops: the balance falls to 6000 and the budget un-breaches.

    PRD §3.7: "The invoice change recomputes the business unit's
    `chargeback_balance_cents`, which in turn re-evaluates that unit's `ACTIVE`
    or `BREACHED` budget and may return a `BREACHED` budget to `ACTIVE`."

    Design: Difficulty/transitive_cascade/dispute_credit_cascades_dispute_to_invoice_to_bu_balance_to_budget_status
    """
    built = _issued_invoice(api)
    budget = _breached_july_budget(api, built)

    before = validate_success(api.get_business_unit(built["unit"]["id"], ADMIN_HEADERS))
    assert_cents(before["chargeback_balance_cents"], 10000, "chargeback_balance_cents")

    dispute = fixtures.file_dispute(
        api,
        built["invoice"],
        reason_code="SHARED_METHODOLOGY",
        claimed_credit_cents=4000,
        narrative="not our storage",
    )
    _resolve_with_a_credit(api, dispute["id"], 4000)

    after = validate_success(api.get_business_unit(built["unit"]["id"], ADMIN_HEADERS))
    assert_cents(after["chargeback_balance_cents"], 6000, "chargeback_balance_cents")

    unbreached = validate_success(api.get_budget(budget["id"], CONTROLLER_HEADERS))
    assert_budget_evaluation(
        unbreached,
        actual_spend_cents=6000,
        variance_cents=-3000,
        variance_pct=-33.33,
        warning_flag=False,
        status="ACTIVE",
    )

    record = validate_success(api.get_cost_record(built["record"]["id"], CONTROLLER_HEADERS))
    assert record["allocation_state"] == "ALLOCATED"


def test_filing_then_withdrawing_a_dispute_leaves_the_ledger_where_it_started(api):
    """Three checkpoints of gross equals credited plus paid plus net due.

    PRD §3.6: "`net_due_cents` is zero whenever `settlement_status` is `SETTLED`,
    `WRITTEN_OFF` or `VOIDED`, and otherwise is `gross_amount_cents` less
    `credited_amount_cents` less `paid_amount_cents`."

    Design: Difficulty/compensating_invariant/dispute_withdrawal_compensates_filing_without_ledger_drift
    """
    built = _issued_invoice(api)
    invoice_id = built["invoice"]["id"]
    unit_id = built["unit"]["id"]

    issued = validate_success(api.get_business_unit(unit_id, ADMIN_HEADERS))
    assert_cents(issued["chargeback_balance_cents"], 10000, "chargeback_balance_cents")

    dispute = fixtures.file_dispute(
        api,
        built["invoice"],
        reason_code="WRONG_OWNER",
        claimed_credit_cents=4000,
        narrative="this resource belongs to billing",
    )
    filed = validate_success(api.get_chargeback_invoice(invoice_id, CONTROLLER_HEADERS))
    assert_invoice_ledger(filed, 10000, 0, 0, 10000)
    assert_invoice_dimensions(filed, settlement_status="ISSUED", dispute_status="DISPUTED")
    held = validate_success(api.get_cost_record(built["record"]["id"], CONTROLLER_HEADERS))
    assert held["allocation_state"] == "DISPUTED_HOLD"

    withdrawn = validate_success(api.withdraw_dispute(dispute["id"], built["owner"]))
    assert withdrawn["status"] == "WITHDRAWN"

    restored = validate_success(api.get_chargeback_invoice(invoice_id, CONTROLLER_HEADERS))
    assert_invoice_ledger(restored, 10000, 0, 0, 10000)
    assert_invoice_dimensions(restored, settlement_status="ISSUED", dispute_status="NONE")
    freed = validate_success(api.get_cost_record(built["record"]["id"], CONTROLLER_HEADERS))
    assert freed["allocation_state"] == "ALLOCATED"

    unchanged = validate_success(api.get_business_unit(unit_id, ADMIN_HEADERS))
    assert_cents(unchanged["chargeback_balance_cents"], 10000, "chargeback_balance_cents")


def test_a_credit_then_a_payment_close_the_ledger_without_drift(api):
    """The remaining checkpoints: 4000 credited, 6000 paid, and 10000 refused.

    PRD §3.6: "The owner submits `payment_cents`, and the payment must **exactly
    clear** the invoice: `paid_amount_cents` plus the submitted `payment_cents`
    must equal `gross_amount_cents` less `credited_amount_cents`."

    Design: Difficulty/compensating_invariant/dispute_withdrawal_compensates_filing_without_ledger_drift
    """
    built = _issued_invoice(api)
    invoice_id = built["invoice"]["id"]
    owner = built["owner"]

    first = fixtures.file_dispute(
        api,
        built["invoice"],
        reason_code="WRONG_OWNER",
        claimed_credit_cents=4000,
        narrative="this resource belongs to billing",
    )
    validate_success(api.withdraw_dispute(first["id"], owner))

    second = fixtures.file_dispute(
        api,
        built["invoice"],
        reason_code="WRONG_OWNER",
        claimed_credit_cents=4000,
        narrative="this resource belongs to billing",
    )
    _resolve_with_a_credit(api, second["id"], 4000)

    credited = validate_success(api.get_chargeback_invoice(invoice_id, CONTROLLER_HEADERS))
    assert_invoice_ledger(credited, 10000, 4000, 0, 6000)
    assert credited["settlement_status"] == "PARTIALLY_CREDITED"
    balance = validate_success(api.get_business_unit(built["unit"]["id"], ADMIN_HEADERS))
    assert_cents(balance["chargeback_balance_cents"], 6000, "chargeback_balance_cents")

    validate_error(
        api.settle_invoice(invoice_id, 10000, owner), ApiErrorId.OVERPAYMENT.value, 422
    )
    still_open = validate_success(api.get_chargeback_invoice(invoice_id, CONTROLLER_HEADERS))
    assert_invoice_ledger(still_open, 10000, 4000, 0, 6000)

    settled = validate_success(api.settle_invoice(invoice_id, 6000, owner))
    assert settled["settlement_status"] == "SETTLED"
    assert_invoice_ledger(settled, 10000, 4000, 6000, 0)

    cleared = validate_success(api.get_business_unit(built["unit"]["id"], ADMIN_HEADERS))
    assert_cents(cleared["chargeback_balance_cents"], 0, "chargeback_balance_cents")
