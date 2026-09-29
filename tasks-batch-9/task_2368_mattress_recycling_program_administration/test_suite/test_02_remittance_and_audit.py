"""Quarterly remittances: the two fee variants, payment, the audit cycle and the
delinquency cascade."""

import pytest

from test_helpers import (
    TEST_USERS,
    close_audit,
    create_active_rate,
    create_program,
    create_registrant,
    create_remittance,
    file_remittance,
    make_registrant_headers,
    pay_remittance,
    read_program,
    request_amendment,
    setup_ca_amendment_cycle_chain,
    setup_ca_quarterly_audit_adjudicated,
    setup_ca_quarterly_fee_chain,
    setup_ca_quarterly_filed_and_paid,
    submit_amendment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_self_assessed_fee_prices_the_quarter_at_the_period_start_rate(api):
    """PRD §3.3: "The self-assessed variant prices both lines at the rate
    applicable on `period_start`, counts exemption claims whose status is
    `PENDING` or `SUBSTANTIATED` — a claim counts as filed even before an auditor
    has looked at it — and never forfeits the discount."

    Design: Difficulty/dual_variant_calc/remittance_self_assessed_vs_audit_reconciled_fee_divergence
    """
    chain = setup_ca_quarterly_fee_chain(api, with_mattress_successor=True)

    filed = file_remittance(api, chain["remittance_id"], chain["registrant_id"])

    assert filed["status"] == "FILED"
    assert filed["early_filing_qualified"] is True
    assert filed["fee_self_assessed_cents"] == 1_271_043, (
        "the mattress line is priced at the 1100-cent rate covering 2026-10-01 "
        "even though a 1200-cent successor is active when the filing is made"
    )
    assert filed["fee_reconciled_cents"] is None
    assert (
        validate_success(
            api.get_fee_rate_schedule(chain["mattress_successor"]["id"], ADMIN)
        )["status"]
        == "ACTIVE"
    )


def test_audit_reconciled_fee_prices_the_quarter_at_the_period_end_rate(api):
    """PRD §3.4: "It prices both lines at the rate applicable on `period_end`, so
    a mid-period rate change prices the entire quarter at the later rate. It
    counts only claims whose status is `SUBSTANTIATED`, so disallowed and
    (impossibly, given the closure gate) pending claims contribute no credited
    exempt units."

    Design: Difficulty/dual_variant_calc/remittance_self_assessed_vs_audit_reconciled_fee_divergence
    """
    chain = setup_ca_quarterly_audit_adjudicated(api)

    closed = close_audit(api, chain["remittance_id"])

    assert closed["status"] == "AUDIT_CLOSED"
    assert closed["fee_self_assessed_cents"] == 1_271_043
    assert closed["fee_reconciled_cents"] == 1_522_500
    assert closed["fee_paid_cents"] == 1_271_043
    assert closed["balance_due_cents"] == 251_457


def test_early_filing_discount_is_rounded_once_per_sales_line(api):
    """PRD §3.3: "Round the line's discount — the gross amount multiplied by the
    discount percentage — half up to whole cents, subtract it from that line's
    gross amount, and add the difference to the running total. The per-line
    rounding placement is normative: rounding a single aggregate discount over the
    summed gross amounts is explicitly not the rule, and can differ by one cent
    for each pair of lines whose discounts land on a half cent."

    Design: Difficulty/combinatorial_formula/remittance_per_line_discount_rounding_order_locks_1271043
    """
    chain = setup_ca_quarterly_fee_chain(api, with_mattress_successor=True)

    filed = file_remittance(api, chain["remittance_id"], chain["registrant_id"])

    assert filed["fee_self_assessed_cents"] == 1_271_043, (
        "the foundation discount of 4819.5 and the mattress discount of 14536.5 "
        "each round up inside their own line"
    )
    assert filed["fee_self_assessed_cents"] != 1_271_044


def test_filing_stamps_the_early_qualification_from_the_logical_clock(api):
    """PRD §3.3: "First, the filing is early when `filed_at` falls at or before
    twenty days after `period_end`; `early_filing_qualified` records that
    determination."

    Design: Difficulty/combinatorial_formula/remittance_per_line_discount_rounding_order_locks_1271043
    """
    chain = setup_ca_quarterly_fee_chain(api, with_mattress_successor=True)

    filed = file_remittance(api, chain["remittance_id"], chain["registrant_id"])

    assert filed["status"] == "FILED"
    assert filed["early_filing_qualified"] is True
    assert filed["filed_at"] == "2027-01-10T00:00:00Z"


def test_third_amendment_request_is_refused_after_two_rounds(api):
    """PRD §3.4: "It is legal only from `UNDER_AUDIT` — otherwise
    `ERR_REMITTANCE_NOT_UNDER_AUDIT` — and only while `amendment_round` is less
    than 2; a third request is refused with `ERR_AMENDMENT_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/remittance_audit_amendment_cycle_capped_at_two_rounds
    """
    chain = setup_ca_amendment_cycle_chain(api)
    remittance_id = chain["remittance_id"]
    registrant_id = chain["registrant_id"]

    first_request = request_amendment(api, remittance_id, "Revise the mattress line")
    parent = submit_amendment(api, remittance_id, registrant_id, 540, 200, first_request["version"])
    assert parent["status"] == "UNDER_AUDIT"
    assert parent["amendment_round"] == 1
    second_request = request_amendment(api, remittance_id, "Revise the foundation line")
    parent = submit_amendment(api, remittance_id, registrant_id, 540, 215, second_request["version"])
    assert parent["amendment_round"] == 2

    response = api.request_remittance_amendment(
        remittance_id, {"note": "One more revision please"}, AUDITOR
    )

    validate_error(response, "ERR_AMENDMENT_LIMIT_EXCEEDED", 409)
    stored = validate_success(api.get_sales_remittance(remittance_id, AUDITOR))
    assert stored["status"] == "UNDER_AUDIT"
    assert stored["amendment_round"] == 2


def test_each_amendment_creates_a_draft_row_pointing_at_the_audited_parent(api):
    """PRD §3.4: "Accepting the submission does three things: it increments the
    audited remittance's `amendment_round` by one, increments that remittance's
    `version` by one, and creates a **new** remittance row in `DRAFT` whose
    `amends_remittance_id` points at the audited parent and which copies the
    parent's `registrant_id`, `state_program_id` and `period_code` while carrying
    the revised sales figures."

    Design: Difficulty/non_linear_state_machine/remittance_audit_amendment_cycle_capped_at_two_rounds
    """
    chain = setup_ca_amendment_cycle_chain(api)
    remittance_id = chain["remittance_id"]
    registrant_id = chain["registrant_id"]

    first_request = request_amendment(api, remittance_id, "Revise the mattress line")
    submit_amendment(api, remittance_id, registrant_id, 540, 200, first_request["version"])
    second_request = request_amendment(api, remittance_id, "Revise the foundation line")
    submit_amendment(api, remittance_id, registrant_id, 540, 215, second_request["version"])

    amendments, meta = validate_paginated(
        api.list_sales_remittances(
            make_registrant_headers(registrant_id),
            params={"amends_remittance_id": remittance_id},
        )
    )

    assert meta["total_count"] == 2
    assert [row["status"] for row in amendments] == ["DRAFT", "DRAFT"]
    assert all(row["amends_remittance_id"] == remittance_id for row in amendments)
    assert all(row["period_code"] == "2026Q4" for row in amendments)
    assert amendments[0]["units_sold_mattress"] == 540
    assert amendments[0]["units_sold_foundation"] == 200
    assert amendments[1]["units_sold_foundation"] == 215


def test_positive_balance_due_cascades_delinquency_into_the_program_posture(api):
    """PRD §3.4: "Third, because that registrant is now delinquent or suspended,
    the program's `delinquent_registrant_count` increases by one and the balance
    due is added to the program's `receivable_cents`; the count is the number of
    distinct registrants that are `DELINQUENT` or `SUSPENDED` and hold at least
    one `AUDIT_CLOSED` remittance of this program with a positive balance due."

    Design: Difficulty/transitive_cascade/audit_close_balance_cascades_registrant_delinquency_to_program_posture
    """
    chain = setup_ca_quarterly_audit_adjudicated(api)

    closed = close_audit(api, chain["remittance_id"])

    assert closed["balance_due_cents"] == 251_457
    registrant = validate_success(api.get_registrant(chain["registrant_id"], ADMIN))
    assert registrant["delinquent_balance_cents"] == 251_457
    assert registrant["compliance_status"] == "DELINQUENT"
    program = read_program(api, chain["program_id"])
    assert program["delinquent_registrant_count"] == 1
    assert program["receivable_cents"] == 251_457
    assert program["enforcement_posture"] == "ELEVATED"


def test_elevated_posture_freezes_the_refund_of_the_closed_remittance(api):
    """PRD §3.4: "Fourth, because the delinquent-registrant count has reached the
    program's `delinquency_alert_threshold`, the program's `enforcement_posture`
    flips from `NORMAL` to `ELEVATED` — and an elevated posture blocks every
    subsequent `PAID → REFUNDED` transition in that program until it clears."

    PRD §3.4: "With the default threshold of 1, a single short-paid audit closure
    is enough to freeze refunds program-wide."

    The frozen transition has to be a real `PAID → REFUNDED` one, so the refund is
    aimed at a *second* remittance of the same program that is still `PAID`. The
    short-paid remittance itself has left `PAID` for `AUDIT_CLOSED`, and PRD §2.10
    ranks the target record's own lifecycle state (step 9) ahead of the posture
    interlock (step 11), so a refund aimed at it would report
    `ERR_REMITTANCE_NOT_PAID` instead.

    Design: Difficulty/transitive_cascade/audit_close_balance_cascades_registrant_delinquency_to_program_posture
    """
    chain = setup_ca_quarterly_audit_adjudicated(api)

    # A second registrant of the same program, filed early and paid in full, so a
    # genuine PAID -> REFUNDED transition is available once the posture escalates.
    peer = create_registrant(
        api,
        legal_name="Sierra Foundation Supply Inc",
        registrant_type="MANUFACTURER",
        home_state_code="CA",
    )
    peer_remittance = create_remittance(
        api,
        peer["id"],
        chain["program_id"],
        period_code="2026Q4",
        units_sold_mattress=0,
        units_sold_foundation=100,
    )
    filed_peer = file_remittance(api, peer_remittance["id"], peer["id"])
    assert filed_peer["fee_self_assessed_cents"] == 88_650
    paid_peer = pay_remittance(api, peer_remittance["id"], peer["id"], 88_650)
    assert paid_peer["status"] == "PAID"

    close_audit(api, chain["remittance_id"])
    assert read_program(api, chain["program_id"])["enforcement_posture"] == "ELEVATED"

    response = api.refund_sales_remittance(
        peer_remittance["id"],
        {"amount_cents": 10_000, "reason": "Registrant overpayment claim"},
        ADMIN,
    )

    validate_error(response, "ERR_PROGRAM_POSTURE_ELEVATED", 422)
    stored = validate_success(api.get_sales_remittance(peer_remittance["id"], ADMIN))
    assert stored["status"] == "PAID"
    assert stored["fee_refunded_cents"] == 0


def draft_remittance_for_payment_conflict(api):
    """A California program with both unit classes priced, and one DRAFT 2026Q4
    remittance that has never been filed."""
    program = create_program(api)
    create_active_rate(
        api,
        program["id"],
        unit_class="FOUNDATION",
        fee_cents_per_unit=900,
        effective_from="2026-08-01T00:00:00Z",
    )
    create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-08-01T00:00:00Z",
    )
    registrant = create_registrant(
        api,
        legal_name="Golden State Mattress Co",
        registrant_type="BOTH",
        home_state_code="CA",
    )
    remittance = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q4",
        units_sold_mattress=300,
        units_sold_foundation=100,
    )
    return {
        "program_id": program["id"],
        "registrant_id": registrant["id"],
        "remittance_id": remittance["id"],
    }


def test_paying_a_draft_reports_the_state_conflict_not_the_amount_mismatch(api):
    """PRD §3.3: "The request carries `amount_cents`, which must equal
    `fee_self_assessed_cents` precisely; anything else is rejected with
    `ERR_PAYMENT_AMOUNT_MISMATCH`. Paying a remittance that is not in `FILED` is
    rejected with `ERR_REMITTANCE_NOT_PAYABLE`."

    Design: Difficulty/priority_pair_validation_conflict/pay_on_draft_remittance_state_error_precedes_payment_amount_mismatch
    """
    chain = draft_remittance_for_payment_conflict(api)

    response = api.pay_sales_remittance(
        chain["remittance_id"],
        {"amount_cents": 1},
        make_registrant_headers(chain["registrant_id"]),
    )

    validate_error(response, "ERR_REMITTANCE_NOT_PAYABLE", 409)


def test_a_refused_payment_leaves_the_remittance_and_the_ledger_untouched(api):
    """PRD §3.3: "Paying a remittance that is not in `FILED` is rejected with
    `ERR_REMITTANCE_NOT_PAYABLE`. On success `fee_paid_cents` is set to the amount
    paid, and the program's `fee_collected_cents` and `reserve_balance_cents` are
    reconciled per §2.7, after which `reserve_coverage_months` and
    `recommended_rate_cents` are recomputed."

    Design: Difficulty/priority_pair_validation_conflict/pay_on_draft_remittance_state_error_precedes_payment_amount_mismatch
    """
    chain = draft_remittance_for_payment_conflict(api)

    api.pay_sales_remittance(
        chain["remittance_id"],
        {"amount_cents": 1},
        make_registrant_headers(chain["registrant_id"]),
    )

    stored = validate_success(api.get_sales_remittance(chain["remittance_id"], ADMIN))
    assert stored["status"] == "DRAFT"
    assert stored["fee_paid_cents"] == 0
    assert stored["fee_self_assessed_cents"] == 0
    program = read_program(api, chain["program_id"])
    assert program["fee_collected_cents"] == 0
    assert program["reserve_balance_cents"] == 5_000_000


def test_payment_books_the_fee_into_the_program_reserve(api):
    """PRD §2.7: "The reserve balance (`reserve_balance_cents`) is then the opening
    reserve (`reserve_opening_cents`) plus fees collected, less site credits paid,
    less hauler payments paid."

    Design: Difficulty/compensating_invariant/pay_then_refund_restores_program_ledger_exactly
    """
    chain = setup_ca_quarterly_filed_and_paid(api, with_mattress_successor=False)

    program = read_program(api, chain["program_id"])

    assert chain["remittance"]["status"] == "PAID"
    assert chain["remittance"]["fee_paid_cents"] == 1_271_043
    assert program["fee_collected_cents"] == 1_271_043
    assert program["reserve_balance_cents"] == 6_271_043
    assert program["site_credit_paid_cents"] == 0
    assert program["hauler_payment_paid_cents"] == 0


def test_refunding_the_full_payment_restores_the_reserve_exactly(api):
    """PRD §2.7: "Because every total is a re-derivation and not an increment, the
    ledger obeys a strict compensation invariant: for a forward action and its
    compensating action of the same amount — a payment of some amount followed by
    a refund of that same amount — both `fee_collected_cents` and
    `reserve_balance_cents` return to exactly their pre-action values, with no
    drift."

    Design: Difficulty/compensating_invariant/pay_then_refund_restores_program_ledger_exactly
    """
    chain = setup_ca_quarterly_filed_and_paid(api, with_mattress_successor=False)

    refunded = validate_success(
        api.refund_sales_remittance(
            chain["remittance_id"],
            {
                "amount_cents": 1_271_043,
                "reason": "Duplicate remittance withdrawn by registrant",
            },
            ADMIN,
        )
    )

    assert refunded["status"] == "REFUNDED"
    assert refunded["fee_paid_cents"] == 1_271_043
    assert refunded["fee_refunded_cents"] == 1_271_043
    program = read_program(api, chain["program_id"])
    assert program["fee_collected_cents"] == 0
    assert program["reserve_balance_cents"] == 5_000_000
    assert program["reserve_coverage_months"] == pytest.approx(1.00)
    assert program["recommended_rate_cents"] == 1075
    assert program["site_credit_paid_cents"] == 0
    assert program["hauler_payment_paid_cents"] == 0
