"""Quantities the system must conserve: trust cash, and recognised advisor share."""
from test_helpers import (
    advisor_deposit,
    api_client,
    append_trust_line,
    calculate_run,
    cancel_booking,
    confirm_booking,
    controller,
    controller_refund,
    list_booking_ledger,
    list_client_ledger,
    new_booking,
    new_client,
    new_split_schedule,
    new_supplier,
    open_run,
    post_run,
    read_advisor,
    read_booking,
    read_client,
    read_supplier,
    record_receipt,
    set_clock,
    setup_active_advisor,
    statements_for_run,
    trust_ledger_entry_payload,
    validate_error,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]

MERIDIAN = {
    "name": "Meridian Air",
    "accreditation_scheme": "ARC",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 30,
}


def _standard_schedule():
    return new_split_schedule(
        name="Standard 2026",
        tiers=STANDARD_TIERS,
        platform_fee_tiers=FLAT_FEE_TIERS,
        chargeback_retention_pct=0.10,
    )


def _swept_then_cancelled_trust_booking():
    """A fully funded trust client whose confirmed booking is cancelled after the
    deposit has already been swept out to the supplier."""
    supplier = new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state="CA",
        legal_name="Priya Nair",
        email="priya.nair@example.com",
        schedule=_standard_schedule(),
        suppliers=[supplier],
    )
    advisor = ctx["advisor"]
    client = new_client(
        advisor["id"],
        full_name="Marco Vidal",
        home_state_code="CA",
        max_concurrent_trips=4,
    )
    advisor_deposit(
        client["id"], advisor["id"], 300_000, memo="Client wire, full trip funds"
    )
    booking = new_booking(
        advisor["id"],
        supplier["id"],
        client["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="CLIENT_TRUST",
        gross_sale_cents=2_000_000,
        deposit_amount_cents=100_000,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )
    booking = confirm_booking(booking["id"], supplier["id"])
    cancel_booking(booking["id"], advisor["id"], "CLIENT_INITIATED")
    return {
        "advisor": advisor,
        "client": client,
        "supplier": supplier,
        "booking": booking,
    }


def test_the_swept_deposit_comes_back_only_by_an_explicit_compensating_line():
    """PRD §3.6: "Where the `payment_method` was `CLIENT_TRUST` and confirmation had swept
    the deposit out, no compensating trust line is written automatically — a refund to the
    client is an explicit controller action, which is why an unrefunded balance can later
    block the advisor's departure."

    Design: Difficulty/compensating_invariant/trust_cash_conserved_across_disbursement_and_compensating_deposit
    """
    scenario = _swept_then_cancelled_trust_booking()
    client_id = scenario["client"]["id"]

    assert read_client(client_id)["trust_balance_cents"] == 200_000
    assert len(list_client_ledger(client_id)) == 2

    compensating = append_trust_line(
        client_id,
        "DEPOSIT",
        100_000,
        controller("ctrl-1"),
        memo="Supplier returned swept deposit after cancellation",
        booking_id=scenario["booking"]["id"],
    )
    assert compensating["balance_after_cents"] == 300_000

    booking_lines = list_booking_ledger(scenario["booking"]["id"])
    assert len(booking_lines) == 2
    assert sum(line["signed_amount_cents"] for line in booking_lines) == 0


def test_an_overdrawing_refund_appends_nothing_and_leaves_the_history_intact():
    """PRD §3.4: "Solvency second: any `DISBURSEMENT` or `REFUND` that would drive the
    running balance below zero is refused with `ERR_TRUST_FUNDS_INSUFFICIENT` (HTTP 402)
    and appends nothing at all."

    Design: Difficulty/compensating_invariant/trust_cash_conserved_across_disbursement_and_compensating_deposit
    """
    scenario = _swept_then_cancelled_trust_booking()
    client_id = scenario["client"]["id"]
    append_trust_line(
        client_id,
        "DEPOSIT",
        100_000,
        controller("ctrl-1"),
        memo="Supplier returned swept deposit after cancellation",
        booking_id=scenario["booking"]["id"],
    )

    validate_error(
        api_client.create_trust_ledger_entry(
            client_id,
            trust_ledger_entry_payload(
                "REFUND", 300_001, read_client(client_id)["version"], memo="Client refund"
            ),
            controller("ctrl-1"),
        ),
        "ERR_TRUST_FUNDS_INSUFFICIENT",
        402,
    )
    assert len(list_client_ledger(client_id)) == 3
    assert read_client(client_id)["trust_balance_cents"] == 300_000

    emptied = controller_refund(client_id, 300_000, memo="Client refund of trip funds")
    assert emptied["balance_after_cents"] == 0

    lines = list_client_ledger(client_id)
    assert [line["balance_after_cents"] for line in lines] == [
        300_000,
        200_000,
        300_000,
        0,
    ]
    assert lines[0]["amount_cents"] == 300_000
    assert read_client(client_id)["trust_balance_cents"] == 0


FIRST_REMIT_CLOCK = "2026-10-05T00:00:00Z"
FIRST_REMIT_DATE = "2026-10-05"
FIRST_PERIOD = "2026-10"
SECOND_REMIT_CLOCK = "2026-11-05T00:00:00Z"
SECOND_REMIT_DATE = "2026-11-05"
SECOND_PERIOD = "2026-11"
THIRD_PERIOD = "2026-12"


def _settled_then_charged_back_across_two_periods():
    """One booking settled and posted in the first period, then charged back, with a
    second collected booking waiting for the next period to absorb it."""
    supplier = new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=_standard_schedule(),
        suppliers=[supplier],
    )
    advisor = ctx["advisor"]
    client = new_client(
        advisor["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=4,
    )

    def _confirmed(gross, start, end):
        booking = new_booking(
            advisor["id"],
            supplier["id"],
            client["id"],
            channel="SUPPLIER_DIRECT",
            payment_method="MERCHANT_DIRECT",
            gross_sale_cents=gross,
            travel_start_date=start,
            travel_end_date=end,
        )
        return confirm_booking(booking["id"], supplier["id"])

    first = _confirmed(1_600_000, "2026-05-01", "2026-05-10")
    second = _confirmed(3_000_000, "2026-06-01", "2026-06-10")

    set_clock(FIRST_REMIT_CLOCK)
    record_receipt(first["id"], supplier["id"], 160_000, FIRST_REMIT_DATE)
    first_run = open_run(FIRST_PERIOD)
    first_run = calculate_run(first_run["id"], "ctrl-1")
    post_run(first_run["id"], "ctrl-2")

    set_clock(SECOND_REMIT_CLOCK)
    record_receipt(second["id"], supplier["id"], 300_000, SECOND_REMIT_DATE)
    return {
        "advisor": advisor,
        "client": client,
        "supplier": supplier,
        "first": read_booking(first["id"]),
        "second": read_booking(second["id"]),
        "first_run": first_run,
    }


def test_a_chargeback_is_recognised_in_exactly_one_later_statement():
    """PRD §3.8: "The statement's `chargeback_cents` is the sum of
    `chargeback_amount_cents` across the chargeback set plus whatever the advisor was
    carrying in `carryforward_chargeback_cents` at calculate time, and every booking in the
    chargeback set has `chargeback_recognized_at` stamped with the logical clock so that no
    later run can count it a second time."

    Design: Difficulty/compensating_invariant/recognized_advisor_share_conserved_across_chargeback_reversal
    """
    scenario = _settled_then_charged_back_across_two_periods()
    assert scenario["first_run"]["advisor_share_total_cents"] == 112_000
    assert scenario["first"]["settled_share_cents"] == 112_000
    assert scenario["first"]["settled_tier_level"] == 1

    charged_back = cancel_booking(
        scenario["first"]["id"], scenario["advisor"]["id"], "CLIENT_INITIATED"
    )
    assert charged_back["commission_status"] == "CHARGED_BACK"
    assert charged_back["chargeback_amount_cents"] == 112_000
    assert charged_back["settled_share_cents"] == 112_000

    second_run = calculate_run(open_run(SECOND_PERIOD)["id"], "ctrl-1")
    assert second_run["advisor_share_total_cents"] == 210_000
    assert second_run["chargeback_total_cents"] == 112_000
    assert second_run["platform_fee_total_cents"] == 10_500
    assert second_run["net_payout_total_cents"] == 87_500

    statement = statements_for_run(second_run["id"])[0]
    assert statement["chargeback_cents"] == 112_000
    assert statement["carryforward_applied_cents"] == 0
    assert read_booking(scenario["first"]["id"])["chargeback_recognized_at"] is not None

    post_run(second_run["id"], "ctrl-2")
    third_run = calculate_run(open_run(THIRD_PERIOD)["id"], "ctrl-1")
    assert third_run["statement_count"] == 0
    assert third_run["chargeback_total_cents"] == 0


def test_lifetime_accumulators_leave_only_the_uncancelled_share_recognised():
    """PRD §3.8: "Every statement of the run in status `DRAFT` moves to `POSTED`, and each
    statement reaching `POSTED` causes three further effects on rows the caller never named:
    the owning advisor's `lifetime_settled_share_cents` and `lifetime_chargeback_cents` are
    recomputed as the sums of `advisor_share_cents` and `chargeback_cents` across that
    advisor's statements in status `POSTED` or `PAID`; the advisor's
    `carryforward_chargeback_cents` is **replaced** by that statement's
    `carryforward_applied_cents` rather than incremented, so an unabsorbed chargeback is
    carried exactly once; and where the advisor has a `consortium_id`, that consortium's
    `marketing_fund_balance_cents` is recomputed with `Consortium.version` incrementing
    by 1."

    Design: Difficulty/compensating_invariant/recognized_advisor_share_conserved_across_chargeback_reversal
    """
    scenario = _settled_then_charged_back_across_two_periods()
    advisor_id = scenario["advisor"]["id"]
    cancel_booking(scenario["first"]["id"], advisor_id, "CLIENT_INITIATED")

    second_run = calculate_run(open_run(SECOND_PERIOD)["id"], "ctrl-1")
    post_run(second_run["id"], "ctrl-2")

    advisor = read_advisor(advisor_id)
    assert advisor["lifetime_settled_share_cents"] == 322_000
    assert advisor["lifetime_chargeback_cents"] == 112_000
    assert advisor["carryforward_chargeback_cents"] == 0
    assert (
        advisor["lifetime_settled_share_cents"] - advisor["lifetime_chargeback_cents"]
        == 210_000
    )

    third_run = calculate_run(open_run(THIRD_PERIOD)["id"], "ctrl-1")
    post_run(third_run["id"], "ctrl-2")

    unchanged = read_advisor(advisor_id)
    assert (
        unchanged["lifetime_settled_share_cents"]
        - unchanged["lifetime_chargeback_cents"]
        == 210_000
    )
    assert unchanged["carryforward_chargeback_cents"] == 0

    supplier = read_supplier(scenario["supplier"]["id"])
    assert supplier["chargeback_count"] == 1
    assert supplier["program_status"] == "STANDARD"
