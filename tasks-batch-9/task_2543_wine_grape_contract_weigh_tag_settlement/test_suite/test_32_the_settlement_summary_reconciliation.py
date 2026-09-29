"""The reconciliation read, taken at three moments on one contract: graded but open, closed, and
part-paid. The figure that moves in the least obvious direction is the provisional total — it is a
live sum over the lines that are still provisional, so finalising them empties it while the final
total takes over, and the two money columns only reconcile if that handover happens.
"""
from test_helpers import (
    CLERK,
    MANAGER,
    close_settlement,
    grade_load,
    list_installments,
    list_settlement_lines,
    make_grower_headers,
    move_clock,
    pay_installment,
    read_settlement_summary,
    setup_single_load_on_pad,
    two_installment_plan,
    validate_success,
)

CLOSED_AT = "2026-08-28T09:00:00Z"

DELIVERED_TONS = 20.000
CONTRACT_CAP_TONS = 40.000
# The house tolerance is 10.0 per cent, so the hard cap is a tenth above the soft one.
HARD_CAP_TONS = 44.000

# 20.000 tons at 450000 cents a ton with a neutral grading: a 9,000,000-cent gross line, 60.0 per
# cent of which is advanced provisionally.
GROSS_LINE_CENTS = 9_000_000
PROVISIONAL_CENTS = 5_400_000
PROMPT_PAY_CREDIT_CENTS = 45_000
LIEN_HOLDBACK_CENTS = 450_000
NET_PAYABLE_CENTS = 8_595_000
HALF_OF_THE_NET_PAYABLE_CENTS = 4_297_500

NEUTRAL_READING = {"brix": 23.0, "ta_gl": 6.5, "ph": 3.40, "rot_pct": 1.0, "mog_pct": 0.5}

# The sixteen fields the reconciliation read is specified to return.
SUMMARY_FIELDS = (
    "contract_cap_tons",
    "hard_cap_tons",
    "cap_scope",
    "delivered_contract_tons",
    "delivered_over_tons",
    "rejected_tons",
    "tonnage_status",
    "settlement_basis",
    "provisional_settlement_cents",
    "final_settlement_cents",
    "prompt_pay_credit_cents",
    "lien_holdback_cents",
    "net_payable_cents",
    "installment_planned_total_cents",
    "installment_paid_total_cents",
    "outstanding_lien_balance_cents",
)


def _one_graded_load_on_an_open_contract() -> dict:
    """An ACTIVE 40.000-ton contract on a 50/50 lien-protected schedule with exactly one clean
    20.000-net-ton load graded against it, and no close yet."""
    ctx = setup_single_load_on_pad(
        contract_overrides={
            "contract_code": "GC-SUMMARY",
            "installment_plan": two_installment_plan(50.0, 50.0),
        },
        net_tons=DELIVERED_TONS,
        estimated_tons=DELIVERED_TONS,
        planned_tons=DELIVERED_TONS,
    )
    ctx["grading"] = grade_load(ctx, **NEUTRAL_READING)
    return ctx


def _closed(ctx: dict) -> dict:
    move_clock(CLOSED_AT)
    ctx["contract"] = close_settlement(ctx["contract"]["id"])
    ctx["installments"] = list_installments(contract_id=ctx["contract"]["id"])
    return ctx


def test_the_open_summary_reports_the_caps_and_the_delivered_tonnage(api):
    """The tonnage half of the reconciliation is a straight roll-up: the derived caps from
    acceptance, the one load poured into the contract bucket, nothing over and nothing refused.

    PRD: "It returns `contract_cap_tons`, `hard_cap_tons`, `cap_scope`, `delivered_contract_tons`,
    `delivered_over_tons`, `rejected_tons`, `tonnage_status`, `settlement_basis`"

    Design: Corner/endpoints/settlement_summary_reconciles_tonnage_and_money_before_and_after_the_close
    """
    ctx = _one_graded_load_on_an_open_contract()

    summary = read_settlement_summary(ctx["contract"]["id"])
    assert float(summary["contract_cap_tons"]) == CONTRACT_CAP_TONS
    assert float(summary["hard_cap_tons"]) == HARD_CAP_TONS
    assert summary["cap_scope"] == "PER_CONTRACT"
    assert float(summary["delivered_contract_tons"]) == DELIVERED_TONS
    assert float(summary["delivered_over_tons"]) == 0.000
    assert float(summary["rejected_tons"]) == 0.000
    assert summary["tonnage_status"] == "OPEN"
    assert summary["settlement_basis"] == "LOAD_BY_LOAD"


def test_before_the_close_only_the_provisional_column_carries_money(api):
    """Sixty per cent of the one gross line has been advanced, and every figure the close is
    responsible for is still zero — including both installment totals.

    PRD: "Until a close happens, `final_settlement_cents`, `prompt_pay_credit_cents`,
    `lien_holdback_cents` and `net_payable_cents` are all 0, `settlement_closed_at` is null, and
    every installment's `planned_amount_cents` and `due_at` are 0 and null respectively."

    Design: Corner/endpoints/settlement_summary_reconciles_tonnage_and_money_before_and_after_the_close
    """
    ctx = _one_graded_load_on_an_open_contract()

    summary = read_settlement_summary(ctx["contract"]["id"])
    assert summary["provisional_settlement_cents"] == PROVISIONAL_CENTS
    assert summary["final_settlement_cents"] == 0
    assert summary["prompt_pay_credit_cents"] == 0
    assert summary["lien_holdback_cents"] == 0
    assert summary["net_payable_cents"] == 0
    assert summary["installment_planned_total_cents"] == 0
    assert summary["installment_paid_total_cents"] == 0


def test_the_provisional_total_is_a_faithful_roll_up_of_the_lines(api):
    """The summary is not an independent tally of anything: the single line behind it carries
    exactly the tonnage and the two amounts the summary reports.

    PRD: "the third the sum of `provisional_amount_cents` over its `PROVISIONAL` lines."

    Design: Corner/endpoints/settlement_summary_reconciles_tonnage_and_money_before_and_after_the_close
    """
    ctx = _one_graded_load_on_an_open_contract()

    lines = list_settlement_lines(contract_id=ctx["contract"]["id"])
    assert len(lines) == 1
    assert lines[0]["status"] == "PROVISIONAL"
    assert lines[0]["bucket"] == "CONTRACT"
    assert float(lines[0]["tons"]) == DELIVERED_TONS
    assert lines[0]["gross_amount_cents"] == GROSS_LINE_CENTS
    assert lines[0]["provisional_amount_cents"] == PROVISIONAL_CENTS
    assert (
        read_settlement_summary(ctx["contract"]["id"])["provisional_settlement_cents"]
        == lines[0]["provisional_amount_cents"]
    )


def test_the_close_empties_the_provisional_column_rather_than_freezing_it(api):
    """The line is `FINAL` now and no line is provisional, so the provisional total is 0 — it was
    never a historical record of what had been advanced.

    PRD: "The close also stamps `settlement_closed_at` from the logical clock, flips every
    `PROVISIONAL` line to `FINAL`, transitions every installment `PENDING_SETTLEMENT →
    SCHEDULED`, recomputes the producer's `outstanding_lien_balance_cents`, and withdraws the
    harvest"

    Design: Corner/endpoints/settlement_summary_reconciles_tonnage_and_money_before_and_after_the_close
    """
    ctx = _closed(_one_graded_load_on_an_open_contract())

    assert list_settlement_lines(contract_id=ctx["contract"]["id"])[0]["status"] == "FINAL"
    assert read_settlement_summary(ctx["contract"]["id"])["provisional_settlement_cents"] == 0


def test_the_closed_summary_shows_the_whole_money_pipeline(api):
    """The three derived money figures and their sum, read back off the reconciliation endpoint in
    the order the pipeline produced them.

    PRD: "Step five computes `net_payable_cents` as the settlement total plus
    `prompt_pay_credit_cents` less `lien_holdback_cents`."

    Design: Corner/endpoints/settlement_summary_reconciles_tonnage_and_money_before_and_after_the_close
    """
    ctx = _closed(_one_graded_load_on_an_open_contract())

    summary = read_settlement_summary(ctx["contract"]["id"])
    assert summary["final_settlement_cents"] == GROSS_LINE_CENTS
    assert summary["prompt_pay_credit_cents"] == PROMPT_PAY_CREDIT_CENTS
    assert summary["lien_holdback_cents"] == LIEN_HOLDBACK_CENTS
    assert summary["net_payable_cents"] == NET_PAYABLE_CENTS
    assert summary["net_payable_cents"] == (
        GROSS_LINE_CENTS + PROMPT_PAY_CREDIT_CENTS - LIEN_HOLDBACK_CENTS
    )


def test_the_installment_totals_are_sums_across_the_schedule(api):
    """Two halves of the net payable, planned and nothing paid — and the producer's lien balance
    stands at the whole of it, because both halves are lien-protected and unpaid.

    PRD: "`installment_planned_total_cents` (the sum of `planned_amount_cents` across the
    contract's installments), `installment_paid_total_cents` (the sum of their
    `paid_amount_cents`), and `outstanding_lien_balance_cents` for the producer."

    Design: Corner/endpoints/settlement_summary_reconciles_tonnage_and_money_before_and_after_the_close
    """
    ctx = _closed(_one_graded_load_on_an_open_contract())

    planned = [row["planned_amount_cents"] for row in ctx["installments"]]
    assert planned == [HALF_OF_THE_NET_PAYABLE_CENTS, HALF_OF_THE_NET_PAYABLE_CENTS]

    summary = read_settlement_summary(ctx["contract"]["id"])
    assert summary["installment_planned_total_cents"] == NET_PAYABLE_CENTS
    assert summary["installment_paid_total_cents"] == 0
    assert summary["outstanding_lien_balance_cents"] == NET_PAYABLE_CENTS


def test_the_paid_total_tracks_the_payments_and_not_the_plan(api):
    """Half the money has actually moved: the paid total and the lien balance follow it, the
    planned total does not budge, and no tonnage column notices at all.

    PRD: "Every payment against a `lien_protected` installment recomputes the producer's
    `outstanding_lien_balance_cents`"

    Design: Corner/endpoints/settlement_summary_reconciles_tonnage_and_money_before_and_after_the_close
    """
    ctx = _closed(_one_graded_load_on_an_open_contract())
    paid = pay_installment(ctx["installments"][0]["id"], HALF_OF_THE_NET_PAYABLE_CENTS)
    assert paid["status"] == "PAID"

    summary = read_settlement_summary(ctx["contract"]["id"])
    assert summary["installment_paid_total_cents"] == HALF_OF_THE_NET_PAYABLE_CENTS
    assert summary["outstanding_lien_balance_cents"] == HALF_OF_THE_NET_PAYABLE_CENTS
    assert summary["installment_planned_total_cents"] == NET_PAYABLE_CENTS
    assert float(summary["delivered_contract_tons"]) == DELIVERED_TONS
    assert summary["tonnage_status"] == "OPEN"


def test_the_producer_sees_the_same_reconciliation_as_the_clerk(api):
    """The read is shared by the winery's two money-facing roles and the producer whose fruit it
    accounts for, and all three are served the same sixteen fields.

    PRD: "A dedicated computed read reconciles tonnage against money for a contract in one
    payload, available to the `GrowerRelationsManager`, the `AccountsPayableClerk` and the owning
    `Grower`."

    Design: Corner/endpoints/settlement_summary_reconciles_tonnage_and_money_before_and_after_the_close
    """
    ctx = _closed(_one_graded_load_on_an_open_contract())
    pay_installment(ctx["installments"][0]["id"], HALF_OF_THE_NET_PAYABLE_CENTS)

    contract_id = ctx["contract"]["id"]
    as_clerk = validate_success(api.get_settlement_summary(contract_id, CLERK))
    as_manager = validate_success(api.get_settlement_summary(contract_id, MANAGER))
    as_grower = validate_success(
        api.get_settlement_summary(contract_id, make_grower_headers(ctx["grower"]["id"]))
    )
    for field in SUMMARY_FIELDS:
        assert as_grower[field] == as_clerk[field] == as_manager[field]
